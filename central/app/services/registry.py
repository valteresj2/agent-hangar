"""Registro e versionamento de agentes: criar, desenhar (merge patch), substituir spec, rollback, apply."""
from sqlalchemy.orm import Session

from .. import deploy
from .. import spec as specmod
from ..models import Agent, AgentVersion, UsageEvent
from .common import PlatformError, audit, find_agent, get_agent, slugify, spec_of

META_KEYS = ("name", "objective", "final_output", "owner")


def create_agent(db: Session, name: str, objective: str, final_output: str, kind="single", owner="",
                 actor="admin", slug: str | None = None) -> Agent:
    if not (name and objective and final_output):
        raise PlatformError("name, objective e final_output são obrigatórios")
    if slug:
        slug = slugify(slug)
        if find_agent(db, slug):
            raise PlatformError(f"slug '{slug}' já existe")
    else:
        base, i = slugify(name), 2
        slug = base
        while find_agent(db, slug):
            slug, i = f"{base}-{i}", i + 1
    a = Agent(slug=slug, name=name, objective=objective, final_output=final_output, kind=kind or "single",
              owner=owner or "", status="draft", current_version=1)
    a.versions.append(AgentVersion(version=1, spec=specmod.default_spec(), created_by=actor))
    db.add(a)
    db.commit()
    audit(db, actor, "agent.register", slug, f"{name} | objetivo: {objective}")
    return a


def _check_refs(db: Session, slug: str, spec: dict):
    for s in spec.get("sub_agents", []):
        if s == slug:
            raise PlatformError("Agente não pode ser sub-agente de si mesmo")
        get_agent(db, s)


def _commit_version(db: Session, a: Agent, spec: dict, actor: str, action: str, detail: str) -> Agent:
    """Valida, e só cria uma versão nova se a spec realmente mudou."""
    try:
        spec = specmod.validate(spec)
    except specmod.SpecError as e:
        raise PlatformError(str(e)) from None
    _check_refs(db, a.slug, spec)
    a.kind = "multi" if spec.get("sub_agents") else "single"
    if spec == specmod.normalize_legacy(spec_of(a)):
        db.commit()
        return a
    a.current_version += 1
    a.status = "draft"
    a.versions.append(AgentVersion(version=a.current_version, spec=spec, created_by=actor))
    db.commit()
    audit(db, actor, action, a.slug, f"v{a.current_version}: {detail}")
    return a


def design_agent(db: Session, slug: str, patch: dict, actor="admin") -> Agent:
    """Aplica `patch` como JSON Merge Patch (RFC 7396) sobre a spec atual: objetos mesclam, listas e valores
    substituem, e null apaga (ex.: {"llm": {"model": null}} volta ao modelo padrão da conexão)."""
    a = get_agent(db, slug)
    unknown = set(patch) - specmod.SPEC_KEYS - set(META_KEYS)
    if unknown:
        raise PlatformError(f"Campos desconhecidos: {sorted(unknown)}. Válidos: {sorted(specmod.SPEC_KEYS)}")
    for k in META_KEYS:
        if patch.get(k):
            setattr(a, k, patch[k])
    spec_patch = {k: v for k, v in patch.items() if k in specmod.SPEC_KEYS}
    merged = specmod.merge_patch(specmod.normalize_legacy(spec_of(a)), spec_patch)
    return _commit_version(db, a, merged, actor, "agent.design", f"campos {sorted(patch)}")


def replace_spec(db: Session, slug: str, spec: dict, actor="admin") -> Agent:
    """Substitui a spec inteira (editor da UI e GitOps/apply)."""
    return _commit_version(db, get_agent(db, slug), spec or {}, actor, "agent.spec", "spec substituída")


def rollback_agent(db: Session, slug: str, version: int, actor="admin") -> Agent:
    """Cria uma versão nova com a spec de uma versão anterior (o histórico nunca é reescrito)."""
    a = get_agent(db, slug)
    old = spec_of(a, version)
    return _commit_version(db, a, old, actor, "agent.rollback", f"restaurada a v{version}")


def delete_agent(db: Session, slug: str, actor="admin"):
    a = get_agent(db, slug)
    for env in ("stage", "prod"):
        deploy.stop_agent(slug, env)
    db.query(UsageEvent).filter(UsageEvent.agent_id == a.id).delete()
    db.delete(a)
    db.commit()
    audit(db, actor, "agent.delete", slug)


def apply_document(db: Session, doc: dict, actor="admin") -> list[dict]:
    """GitOps: aplica o estado desejado de um documento {skills, mcp_servers, agents}. Idempotente — só
    cria versão quando a spec muda. Agentes são aplicados na ordem do documento (membros antes do
    orquestrador)."""
    from .catalog import upsert_mcp, upsert_skill

    out = []
    for s in doc.get("skills", []) or []:
        upsert_skill(db, s["name"], s.get("description", ""), s.get("content", ""), actor)
        out.append({"kind": "skill", "name": s["name"], "action": "upserted"})
    for m in doc.get("mcp_servers", []) or []:
        upsert_mcp(db, m["name"], m["url"], m.get("description", ""), actor)
        out.append({"kind": "mcp_server", "name": m["name"], "action": "upserted"})
    for item in doc.get("agents", []) or []:
        slug = slugify(item.get("slug") or item["name"])
        a = find_agent(db, slug)
        action = "unchanged"
        if not a:
            a = create_agent(db, item["name"], item["objective"], item["final_output"], owner=item.get("owner", ""),
                             actor=actor, slug=slug)
            action = "created"
        else:
            for k in META_KEYS:
                if item.get(k):
                    setattr(a, k, item[k])
        before = a.current_version
        replace_spec(db, slug, item.get("spec") or {}, actor)
        if action == "unchanged" and a.current_version != before:
            action = "updated"
        out.append({"kind": "agent", "slug": slug, "action": action, "version": a.current_version})
    return out
