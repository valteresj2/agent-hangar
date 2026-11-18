"""Marketplace de Digital employees: a vitrine dos que já foram admitidos e que a pessoa pode ver, e o "usar este
agente", que contrata uma cópia pessoal a partir do cargo. O original nunca é alterado (o mesmo princípio do composer).

O que a cópia leva: o cargo (título, missão, responsabilidades, sistemas, metas e as tarefas de experiência) e, para
quem pode ver a spec do original, as instruções, as skills e os apps (a base do composer). O que nunca vai: conversas,
tarefas, memória, lições, regras de alçada próprias e as contas conectadas. A cópia começa em modo sombra, com a alçada
padrão do nível inicial, e passa pela experiência como qualquer contratação."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Agent, Employee, EmployeeTask, Team
from . import avatars
from . import employee_tasks as tasksmod
from . import employees as empmod
from .access import Access, Forbidden
from .common import PlatformError, iso, spec_of
from .runtime import active_deployment

EXAMPLES = 4  # quantos pedidos de exemplo a página mostra (os títulos das tarefas de experiência)


def _listed(e: Employee, a: Agent) -> bool:
    """Entra na vitrine: admitido (ativo) e do time. Um agente pessoal é só do dono, não é oferta."""
    return e.status == "active" and not a.personal_owner_id


def _mine(acc: Access, e: Employee, a: Agent) -> bool:
    uid = acc.p.user_id
    return bool(acc.can("manage", a) or (uid and uid in (e.owner_user_id, e.manager_user_id)))


def _card(acc: Access, e: Employee, a: Agent, teams: dict[int, str]) -> dict:
    return {"slug": a.slug, "name": a.name, "title": e.title, "mission": e.mission,
            "avatar_url": avatars.url(avatars.of(a)), "team": teams.get(a.team_id) or "",
            "systems": [str(s) for s in e.systems or []], "mine": _mine(acc, e, a),
            "hired_at": iso(tasksmod._aware(e.hired_at)) if e.hired_at else None}


def _teams(db: Session) -> dict[int, str]:
    return {t.id: t.name for t in db.scalars(select(Team))}


def listing(db: Session, acc: Access) -> list[dict]:
    teams = _teams(db)
    out = []
    for e in db.scalars(select(Employee).where(Employee.status == "active").order_by(Employee.hired_at.desc())):
        a = db.get(Agent, e.agent_id)
        if a and _listed(e, a) and acc.can("view", a):
            out.append(_card(acc, e, a, teams))
    return out


def _find(db: Session, acc: Access, slug: str) -> tuple[Employee, Agent]:
    e, a = empmod.find(db, acc, slug)
    if not _listed(e, a):
        raise Forbidden(f"'{slug}' não está no marketplace")
    return e, a


def _names(items) -> list[str]:
    return [str(x.get("name") or x.get("slug") or "") if isinstance(x, dict) else str(x) for x in items or []]


def _base_spec(acc: Access, a: Agent) -> dict | None:
    """A spec em produção, só para quem pode vê-la: é ela que a cópia leva como base."""
    d = active_deployment(a, "prod")
    return spec_of(a, d.version) if d and acc.can("view_spec", a) else None


def _probation(db: Session, e: Employee) -> list[EmployeeTask]:
    return list(db.scalars(select(EmployeeTask).where(EmployeeTask.employee_id == e.id, EmployeeTask.probation.is_(True))
                           .order_by(EmployeeTask.id)))


def _copy_block(db: Session, acc: Access) -> str:
    """Por que a pessoa não pode criar a cópia agora ('' = pode). As mesmas regras do agente pessoal."""
    from . import workspace
    try:
        workspace.check_personal(db, acc, None)
        workspace.personal_team(db, acc, None)
    except (Forbidden, PlatformError) as err:
        return str(err)
    return ""


def detail(db: Session, acc: Access, slug: str) -> dict:
    e, a = _find(db, acc, slug)
    spec = _base_spec(acc, a)
    blocked = _copy_block(db, acc)
    return {**_card(acc, e, a, _teams(db)),
            "responsibilities": list(e.responsibilities or []),
            "examples": [t.title for t in _probation(db, e) if t.title][:EXAMPLES],
            # só com permissão de ver a spec: as instruções e as peças do original
            "instructions": (spec.get("instructions") or "") if spec else None,
            "skills": _names(spec.get("skills")) if spec else [],
            "apps": _names(spec.get("mcps")) if spec else [],
            "copy": {"allowed": not blocked, "reason": blocked, "full": spec is not None}}


def use(db: Session, acc: Access, slug: str) -> dict:
    """Contrata uma cópia pessoal do cargo. Devolve o mesmo que a contratação: {created, employee} ou o que falta."""
    e, a = _find(db, acc, slug)
    tasks = [{"title": t.title, "body": t.body, "expected": t.expected} for t in _probation(db, e) if t.expected]
    full = _base_spec(acc, a) is not None
    return empmod.hire(
        db, acc, "", name=a.name, title=e.title, mission=e.mission, responsibilities=list(e.responsibilities or []),
        systems=list(e.systems or []), kpis=list(e.kpis or []), probation_tasks=tasks, channels=["portal", "mcp"],
        accept_default_authority=True, shadow=True, personal=True, base=a.slug if full else "",
        instructions_from_base=full, default_llm=True, working_hours=e.working_hours or "",
        task_budget_usd=e.task_budget_usd, task_time_limit_min=e.task_time_limit_min)
