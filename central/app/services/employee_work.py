"""Digital employee (F2): o trabalho do dia a dia sem ninguém pedir, medido e com aprendizado.

- Rotinas: um cron vira uma tarefa a cada disparo, só com o funcionário ativo e nunca duas ao mesmo tempo (se a tarefa
  anterior da rotina ainda está aberta, o disparo é pulado e contado).
- Webhook de entrada: cada funcionário pode ter um token (guardado só como hash); POST /hooks/employees/{slug} cria uma
  tarefa, e o mesmo dedupe_key dentro da janela não vira uma segunda tarefa.
- Metas medidas: cada meta aponta para uma métrica da plataforma e tem um alvo; a página e os relatórios comparam.
- Aprendizado: das decisões dos últimos 30 dias saem sugestões — afrouxar a alçada de um tipo de ação que o gestor
  sempre aprova sem editar (nunca abaixo do piso da empresa) e transformar correções repetidas numa lição, que passa a
  ir no prompt de cada tarefa nova. Nada muda sozinho: o gestor aplica ou dispensa."""
import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .. import config
from ..cron import Cron, CronError, zone
from ..models import Employee, EmployeeRoutine, EmployeeTask, HumanRequest, Organization, now
from . import employee_gate as gatemod
from . import employee_tasks as tasksmod
from .access import Access, Forbidden
from .common import PlatformError, audit, iso

# ------------------------------------------------------------------ rotinas


def _tz(db: Session) -> str:
    org = db.get(Organization, 1)
    return org.timezone if org and org.timezone else "UTC"


def _cron(expr: str, tz: str) -> str:
    try:
        c = Cron(expr)
        if c.min_interval_minutes(tz) < config.SCHEDULE_MIN_INTERVAL_MIN:
            raise PlatformError(f"intervalo mínimo entre disparos: {config.SCHEDULE_MIN_INTERVAL_MIN} minutos")
    except CronError as e:
        raise PlatformError(f"cron inválido: {e}") from None
    zone(tz)
    return c.expr


def routine_dict(r: EmployeeRoutine) -> dict:
    nxt = tasksmod._aware(r.next_run_at)
    try:
        when = Cron(r.cron).describe()
    except CronError:
        when = r.cron
    return {"id": r.id, "title": r.title, "body": r.body, "cron": r.cron, "timezone": r.timezone, "when": when,
            "priority": r.priority, "enabled": r.enabled, "next_run_at": iso(nxt),
            "next_run_local": nxt.astimezone(zone(r.timezone)).strftime("%d/%m/%Y %H:%M") if nxt else None,
            "last_run_at": iso(tasksmod._aware(r.last_run_at)), "last_task_id": r.last_task_id, "skipped": r.skipped}


def routines_of(db: Session, e: Employee) -> list[dict]:
    return [routine_dict(r) for r in db.scalars(select(EmployeeRoutine).where(EmployeeRoutine.employee_id == e.id)
                                                 .order_by(EmployeeRoutine.id))]


def set_routine(db: Session, acc: Access, slug: str, title: str = "", body: str = "", cron: str = "",
                timezone: str = "", priority: int = 2, enabled: bool = True, routine_id: int | None = None) -> dict:
    from .employees import find
    e, a = find(db, acc, slug, "manage")
    if e.status == "offboarded":
        raise PlatformError("este Digital employee foi desligado")
    r = db.get(EmployeeRoutine, routine_id) if routine_id else EmployeeRoutine(employee_id=e.id, created_by=acc.p.name)
    if r is None or r.employee_id != e.id:
        raise PlatformError(f"rotina #{routine_id} não existe neste Digital employee")
    if title or not r.title:
        if not (title or "").strip():
            raise PlatformError("a rotina precisa de um título (vira o título de cada tarefa)")
        r.title = title.strip()[:300]
    if body or routine_id is None:
        r.body = body or ""
    r.timezone = timezone or r.timezone or _tz(db)
    if cron or not r.cron:
        if not (cron or "").strip():
            raise PlatformError("informe o cron da rotina, ex.: '0 9 * * 1-5' (dias úteis às 9h)")
        r.cron = _cron(cron, r.timezone)
    r.priority = max(1, min(int(priority or 2), 3))
    r.enabled = bool(enabled)
    r.next_run_at = Cron(r.cron).next_after(now(), r.timezone) if r.enabled else None
    if "schedule" not in (e.channels or []):  # o canal "schedule" passa a valer para este funcionário
        e.channels = [*(e.channels or []), "schedule"]
    db.add(r)
    db.commit()
    audit(db, acc.p.name, "employee.routine", a.slug, f"#{r.id} {r.cron} {r.title[:80]}")
    return routine_dict(r)


def delete_routine(db: Session, acc: Access, slug: str, routine_id: int) -> dict:
    from .employees import find
    e, a = find(db, acc, slug, "manage")
    r = db.get(EmployeeRoutine, routine_id)
    if r is None or r.employee_id != e.id:
        raise PlatformError(f"rotina #{routine_id} não existe neste Digital employee")
    db.delete(r)
    db.commit()
    audit(db, acc.p.name, "employee.routine.delete", a.slug, f"#{routine_id}")
    return {"ok": True}


def _routine_task(db: Session, e: Employee, r: EmployeeRoutine, trigger: str) -> EmployeeTask | None:
    """Cria a tarefa da rotina, a menos que a anterior ainda esteja aberta (aí pula e conta)."""
    if r.last_task_id:
        prev = db.get(EmployeeTask, r.last_task_id)
        if prev is not None and prev.status not in tasksmod.TERMINAL:
            r.skipped += 1
            tasksmod.event(db, prev, "note", {"routine": r.id, "skipped": "a tarefa anterior da rotina ainda está aberta"})
            db.commit()
            return None
    t = tasksmod.create_task(db, e, r.title, r.body, "routine", f"rotina #{r.id} ({trigger})", None, r.priority,
                             routine_id=r.id)
    r.last_task_id, r.last_run_at = t.id, now()
    db.commit()
    return t


def run_routine_now(db: Session, acc: Access, slug: str, routine_id: int) -> dict:
    from .employees import find, task_dict
    e, a = find(db, acc, slug, "manage")
    r = db.get(EmployeeRoutine, routine_id)
    if r is None or r.employee_id != e.id:
        raise PlatformError(f"rotina #{routine_id} não existe neste Digital employee")
    if e.status not in ("probation", "active", "paused"):
        raise PlatformError(f"'{slug}' ainda não trabalha (status {e.status})")
    t = _routine_task(db, e, r, f"manual por {acc.p.name}")
    if t is None:
        raise PlatformError("a tarefa anterior desta rotina ainda está aberta: espere ela terminar")
    return task_dict(db, t)


def fire_routines(db: Session, at=None) -> list[int]:
    """Dispara as rotinas vencidas de funcionários ativos. A reserva é um UPDATE condicional em next_run_at, seguro com
    mais de uma réplica da central."""
    at = at or now()
    fired = []
    due = db.execute(select(EmployeeRoutine.id, EmployeeRoutine.next_run_at).join(
        Employee, Employee.id == EmployeeRoutine.employee_id).where(
        EmployeeRoutine.enabled.is_(True), EmployeeRoutine.next_run_at.is_not(None), EmployeeRoutine.next_run_at <= at,
        Employee.status == "active")).all()
    for rid, old in due:
        r = db.get(EmployeeRoutine, rid)
        nxt = Cron(r.cron).next_after(at, r.timezone)
        res = db.execute(update(EmployeeRoutine).where(EmployeeRoutine.id == rid, EmployeeRoutine.next_run_at == old)
                         .values(next_run_at=nxt))
        db.commit()
        if res.rowcount != 1:
            continue  # outra réplica pegou
        db.refresh(r)
        t = _routine_task(db, db.get(Employee, r.employee_id), r, "agendada")
        if t is not None:
            fired.append(t.id)
    return fired


# ------------------------------------------------------------------ webhook de entrada

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def webhook_info(e: Employee, slug: str) -> dict:
    return {"enabled": bool(e.webhook_token_hash), "hint": e.webhook_token_hint,
            "url": f"{config.PUBLIC_BASE_URL}/hooks/employees/{slug}"}


def set_webhook(db: Session, acc: Access, slug: str, enabled: bool = True) -> dict:
    """Gera (ou troca) o token do webhook de entrada. O token aparece só nesta resposta."""
    from .employees import find
    e, a = find(db, acc, slug, "manage")
    if not enabled:
        e.webhook_token_hash, e.webhook_token_hint = "", ""
        e.channels = [c for c in e.channels or [] if c != "webhook"]
        db.commit()
        audit(db, acc.p.name, "employee.webhook.off", a.slug, "")
        return webhook_info(e, a.slug)
    token = "ehk_" + secrets.token_urlsafe(32)
    e.webhook_token_hash, e.webhook_token_hint = _hash(token), token[-4:]
    if "webhook" not in (e.channels or []):
        e.channels = [*(e.channels or []), "webhook"]
    db.commit()
    audit(db, acc.p.name, "employee.webhook.token", a.slug, f"…{token[-4:]}")
    return {**webhook_info(e, a.slug), "token": token,
            "example": f"curl -X POST {config.PUBLIC_BASE_URL}/hooks/employees/{a.slug} -H 'Authorization: Bearer {token}' "
                       "-H 'Content-Type: application/json' -d '{\"title\": \"...\", \"body\": \"...\", \"dedupe_key\": \"evento-123\"}'"}


def inbound(db: Session, slug: str, token: str, title: str, body: str = "", dedupe_key: str = "", priority: int = 2,
            due_at=None, source_name: str = "") -> dict:
    """Tarefa vinda de outro sistema (CRM, formulário, alerta). Autenticada pelo token do funcionário."""
    from .common import get_agent
    try:
        a = get_agent(db, slug)
    except PlatformError:
        raise Forbidden("token inválido") from None
    e = db.scalar(select(Employee).where(Employee.agent_id == a.id))
    if e is None or not e.webhook_token_hash or not secrets.compare_digest(_hash(token or ""), e.webhook_token_hash):
        raise Forbidden("token inválido")
    if "webhook" not in (e.channels or []):
        raise Forbidden("o canal webhook está desligado para este Digital employee")
    if e.status not in ("probation", "active", "paused"):
        raise PlatformError(f"'{slug}' não recebe tarefas agora (status {e.status})")
    key = (dedupe_key or "").strip()[:200]
    if key:
        since = now() - timedelta(days=config.EMPLOYEE_DEDUPE_DAYS)
        dup = db.scalar(select(EmployeeTask).where(EmployeeTask.employee_id == e.id, EmployeeTask.dedupe_key == key,
                                                   EmployeeTask.created_at >= since).order_by(EmployeeTask.id))
        if dup is not None:
            return {"id": dup.id, "status": dup.status, "duplicate": True}
    t = tasksmod.create_task(db, e, (title or "")[:300], (body or "")[:20000], "webhook",
                             f"webhook{' ' + source_name[:60] if source_name else ''}", None, priority, due_at,
                             dedupe_key=key)
    audit(db, f"webhook:{slug}", "employee.task", slug, f"#{t.id} {t.title[:120]}")
    return {"id": t.id, "status": t.status, "duplicate": False}


# ------------------------------------------------------------------ metas medidas

# métrica -> (rótulo, maior é melhor?, unidade)
KPI_METRICS = {
    "tasks_done": ("tarefas concluídas (30 dias)", True, ""),
    "done_rate": ("% das tarefas concluídas com sucesso", True, "%"),
    "on_time_rate": ("% concluídas dentro do prazo", True, "%"),
    "approved_unedited_rate": ("% das ações aprovadas sem edição", True, "%"),
    "avg_decision_min": ("tempo médio de decisão (min)", False, "min"),
    "cost_per_task": ("custo por tarefa (US$)", False, "US$"),
    "expired_decisions": ("decisões expiradas (30 dias)", False, ""),
}


def validate_kpis(kpis: list) -> list[dict]:
    out = []
    for k in kpis or []:
        if isinstance(k, str):
            k = {"name": k}
        name = str(k.get("name") or "").strip()
        metric = k.get("metric") or ""
        if not name and not metric:
            continue
        if metric and metric not in KPI_METRICS:
            raise PlatformError(f"métrica '{metric}': use {', '.join(KPI_METRICS)}")
        target = k.get("target")
        if target not in (None, ""):
            try:
                target = float(target)
            except (TypeError, ValueError):
                raise PlatformError(f"alvo da meta '{name or metric}' precisa ser um número") from None
        else:
            target = None
        out.append({"name": name or KPI_METRICS[metric][0], "metric": metric, "target": target})
    return out


def kpi_actuals(db: Session, e: Employee, days: int = 30) -> dict:
    from .employees import metrics
    m = metrics(db, e, days)
    since = now() - timedelta(days=days)
    finished = m["done"] + m["failed"]
    timed = list(db.scalars(select(EmployeeTask).where(EmployeeTask.employee_id == e.id, EmployeeTask.created_at >= since,
                                                       EmployeeTask.status == "done", EmployeeTask.due_at.is_not(None))))
    on_time = sum(1 for t in timed if t.finished_at and tasksmod._aware(t.finished_at) <= tasksmod._aware(t.due_at))
    decided = m["approved"] + m["rejected"]
    return {"tasks_done": m["done"], "done_rate": round(100 * m["done"] / finished, 1) if finished else None,
            "on_time_rate": round(100 * on_time / len(timed), 1) if timed else None,
            "approved_unedited_rate": round(100 * m["approved_unedited"] / decided, 1) if decided else None,
            "avg_decision_min": m["avg_decision_min"], "cost_per_task": m["cost_per_task"] or None,
            "expired_decisions": m["expired"]}


def kpi_status(db: Session, e: Employee) -> list[dict]:
    actual = kpi_actuals(db, e) if e.kpis else {}
    out = []
    for k in e.kpis or []:
        k = k if isinstance(k, dict) else {"name": str(k)}
        metric, target = k.get("metric") or "", k.get("target")
        val = actual.get(metric) if metric else None
        higher = KPI_METRICS[metric][1] if metric in KPI_METRICS else True
        ok = None
        if metric and target is not None and val is not None:
            ok = val >= target if higher else val <= target
        out.append({"name": k.get("name") or "", "metric": metric, "target": target, "actual": val,
                    "unit": KPI_METRICS[metric][2] if metric in KPI_METRICS else "", "higher_is_better": higher, "ok": ok})
    return out


# ------------------------------------------------------------------ aprendizado: sugestões e lições

def _corrections(db: Session, e: Employee, since) -> dict[str, list[HumanRequest]]:
    rows = db.scalars(select(HumanRequest).where(
        HumanRequest.employee_id == e.id, HumanRequest.kind == "approval", HumanRequest.status == "decided",
        HumanRequest.decision.in_(("approve_edited", "reject", "instruct")), HumanRequest.decided_at >= since))
    by_tool: dict[str, list[HumanRequest]] = {}
    for r in rows:
        by_tool.setdefault(r.tool_name or r.tool_ref, []).append(r)
    return by_tool


def _edit_summary(r: HumanRequest, en: bool = False) -> str:
    before, after = r.action_payload or {}, r.edited_payload or {}
    changed = [k for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)]
    if not changed:
        return "edited" if en else "editou"
    return ("changed " if en else "mudou ") + ", ".join(changed)


def suggestions(db: Session, e: Employee) -> list[dict]:
    en = tasksmod.lang_of(e) == "en"
    since = now() - timedelta(days=30)
    dismissed = {k: v for k, v in (e.dismissed or {}).items() if v >= (now() - timedelta(days=30)).date().isoformat()}
    out = []
    # 1) o gestor sempre aprova sem editar: sugerir "faz e avisa" (só se o piso da empresa permitir)
    eff = {x["action_type"]: x for x in gatemod.summary(db, e)}
    floor = gatemod.floor_of(db)
    for t, row in eff.items():
        if row["mode"] not in ("approve", "approve_2"):
            continue
        fl = floor.get(t)
        if fl and gatemod.RANK[fl.min_mode] > gatemod.RANK["notify"]:
            continue  # o piso não deixa
        decided = list(db.scalars(select(HumanRequest).where(
            HumanRequest.employee_id == e.id, HumanRequest.kind == "approval", HumanRequest.action_type == t,
            HumanRequest.status == "decided", HumanRequest.decided_at >= since)))
        if len(decided) >= config.LEARN_MIN_APPROVALS and all(r.decision == "approve" for r in decided):
            sid = f"loosen:{t}"
            if sid in dismissed:
                continue
            out.append({"id": sid, "kind": "authority", "action_type": t, "from": row["mode"], "to": "notify",
                        "evidence": len(decided),
                        "text": (f"{len(decided)} approvals of '{t}' in 30 days, all without edits: let it do this and "
                                 "notify you instead of waiting?") if en else
                                (f"{len(decided)} aprovações de '{t}' em 30 dias, todas sem edição: deixar ele fazer e "
                                 "só avisar, em vez de esperar?")})
    # 2) correções repetidas na mesma ferramenta: sugerir uma lição para as próximas tarefas
    for tool, rows in _corrections(db, e, since).items():
        if len(rows) < config.LEARN_MIN_CORRECTIONS:
            continue
        sid = f"lesson:{tool}"
        if sid in dismissed or any(x.get("source") == sid for x in e.lessons or []):
            continue
        reasons = []
        for r in rows:
            txt = (r.reason or "").strip() or (_edit_summary(r, en) if r.decision == "approve_edited" else "")
            if txt and txt not in reasons:
                reasons.append(txt)
        lesson = ((f"When using {tool}: " if en else f"Ao usar {tool}: ") + "; ".join(reasons[:5])) if reasons else \
            (f"Check {tool} actions carefully: your manager corrected them {len(rows)} times." if en else
             f"Revise as ações de {tool} com cuidado: o gestor as corrigiu {len(rows)} vezes.")
        out.append({"id": sid, "kind": "lesson", "tool": tool, "evidence": len(rows),
                    "decisions": {d: sum(r.decision == d for r in rows) for d in ("approve_edited", "reject", "instruct")},
                    "examples": [{"request": r.id, "decision": r.decision, "reason": r.reason,
                                  "edit": _edit_summary(r, en) if r.decision == "approve_edited" else ""} for r in rows[-5:]],
                    "lesson": lesson[:1000],
                    "text": (f"Your manager corrected {len(rows)} '{tool}' actions in 30 days. Turn this into a lesson "
                             "for its next tasks?") if en else
                            (f"O gestor corrigiu {len(rows)} ações de '{tool}' em 30 dias. Virar uma lição para as "
                             "próximas tarefas?")})
    return out


def suggestions_for(db: Session, acc: Access, slug: str) -> list[dict]:
    from .employees import find
    e, _ = find(db, acc, slug)
    return suggestions(db, e)


def add_lesson(db: Session, e: Employee, text: str, source: str, who: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise PlatformError("escreva a lição")
    lessons = list(e.lessons or [])
    if len(lessons) >= 20:
        raise PlatformError("no máximo 20 lições: remova uma antes")
    item = {"id": secrets.token_hex(4), "text": text[:1000], "source": source, "added_by": who, "at": iso(now())}
    e.lessons = [*lessons, item]
    db.commit()
    return item


def apply_suggestion(db: Session, acc: Access, slug: str, suggestion_id: str, text: str = "") -> dict:
    from .employees import find, set_authority
    e, a = find(db, acc, slug, "manage")
    sug = next((s for s in suggestions(db, e) if s["id"] == suggestion_id), None)
    if sug is None:
        raise PlatformError("sugestão não encontrada (já aplicada, dispensada ou sem evidência suficiente)")
    if sug["kind"] == "authority":
        if acc.p.user_id != e.manager_user_id and not acc.p.is_admin:
            raise Forbidden("só o gestor (ou um admin) afrouxa a alçada")
        from ..models import AuthorityRule
        rules = [{"action_type": r.action_type, "mode": r.mode, "conditions": r.conditions, "approver": r.approver,
                  "expires_in_min": r.expires_in_min, "note": r.note}
                 for r in db.scalars(select(AuthorityRule).where(AuthorityRule.employee_id == e.id))
                 if not (r.action_type == sug["action_type"] and not r.conditions)]
        rules.append({"action_type": sug["action_type"], "mode": sug["to"], "note": f"sugestão aplicada por {acc.p.name}"})
        out = set_authority(db, acc, slug, rules)
        audit(db, acc.p.name, "employee.learn.authority", a.slug, f"{sug['action_type']} -> {sug['to']}")
        return {"applied": sug["id"], **out}
    item = add_lesson(db, e, text or sug["lesson"], sug["id"], acc.p.name)
    audit(db, acc.p.name, "employee.learn.lesson", a.slug, item["text"][:200])
    return {"applied": sug["id"], "lesson": item, "lessons": e.lessons}


def dismiss_suggestion(db: Session, acc: Access, slug: str, suggestion_id: str) -> dict:
    from .employees import find
    e, a = find(db, acc, slug, "manage")
    e.dismissed = {**(e.dismissed or {}), suggestion_id: now().date().isoformat()}
    db.commit()
    return {"dismissed": suggestion_id}


def lesson_manual(db: Session, acc: Access, slug: str, text: str) -> dict:
    from .employees import find
    e, a = find(db, acc, slug, "manage")
    item = add_lesson(db, e, text, "manual", acc.p.name)
    audit(db, acc.p.name, "employee.lesson", a.slug, item["text"][:200])
    return {"lesson": item, "lessons": e.lessons}


def remove_lesson(db: Session, acc: Access, slug: str, lesson_id: str) -> dict:
    from .employees import find
    e, a = find(db, acc, slug, "manage")
    before = list(e.lessons or [])
    e.lessons = [x for x in before if x.get("id") != lesson_id]
    if len(e.lessons) == len(before):
        raise PlatformError("lição não encontrada")
    db.commit()
    audit(db, acc.p.name, "employee.lesson.remove", a.slug, lesson_id)
    return {"lessons": e.lessons}

