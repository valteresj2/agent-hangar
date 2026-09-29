"""API (/api). Todo mundo autenticado como admin ou como usuário (sessão/token pessoal) entra; cada rota confere
a permissão sobre o recurso (services/access.py): admin vê tudo, os outros veem e fazem conforme o papel."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import auth, config, deploy
from .. import services as svc
from .. import spec as specmod
from ..models import Agent, ApiKey, AuditLog, Deployment, Job, LlmConnection, McpServer, Skill, TestRun, UsageEvent
from ..services import org
from .deps import acc, actor, db_dep, guard, principal, require_admin, require_auditor

router = APIRouter(prefix="/api")


def _agent(request: Request, db, slug: str, action: str = "view"):
    """Agente + checagem de permissão (403/400 já tratados)."""
    def go():
        a = svc.get_agent(db, slug)
        acc(request, db).require(action, a)
        return a
    return guard(go)


# ------------------------------------------------------------------ corpos
class Msg(BaseModel):
    message: str
    env: str = "prod"


class EnvBody(BaseModel):
    env: str = "stage"


class NewAgent(BaseModel):
    name: str
    objective: str
    final_output: str
    owner: str = ""
    slug: str | None = None
    team: str | None = None
    visibility: str | None = None


class RollbackBody(BaseModel):
    version: int


class SkillBody(BaseModel):
    name: str
    description: str = ""
    content: str = ""


class McpBody(BaseModel):
    name: str
    url: str
    description: str = ""


class LlmConnectionBody(BaseModel):
    name: str
    base_url: str
    model_name: str
    api_key: str = ""  # vazio ao editar preserva a chave já salva
    description: str = ""
    protocol: str = "openai"
    price_in_per_mtok: float | None = None
    price_out_per_mtok: float | None = None


class JobBody(BaseModel):
    task: str
    env: str = "stage"
    timeout_s: int | None = None
    wait: bool = True


class TemplateApply(BaseModel):
    connection: str = ""
    harness_connection: str = ""
    team: str | None = None


class ConnectBody(BaseModel):
    client: str
    mode: str = "mcp"


class KeyBody(BaseModel):
    name: str
    scopes: list[str] = Field(default_factory=lambda: ["invoke"])
    agents: list[str] = Field(default_factory=list)


class ShipBody(BaseModel):
    note: str = ""  # vai no pedido de aprovação, quando houver


# ------------------------------------------------------------------ plataforma
@router.get("/health")
def health():
    return {"status": "ok", "version": config.VERSION}


@router.get("/overview")
def overview(request: Request, db=Depends(db_dep)):
    return svc.overview(db, acc(request, db))


@router.get("/connect")
def connect():
    b = config.PUBLIC_BASE_URL
    return {"base_url": b, "mcp_url": f"{b}/mcp", "gateway": f"{b}/gw/<slug>"}


@router.get("/spec/schema")
def spec_schema():
    return specmod.json_schema()


# ------------------------------------------------------------------ agentes
@router.get("/agents")
def agents(request: Request, db=Depends(db_dep)):
    return svc.list_agents(db, acc(request, db))


@router.post("/agents")
def create_agent(body: NewAgent, request: Request, db=Depends(db_dep)):
    def go():
        a = acc(request, db)
        team = a.team_for_new_agent(body.team)
        agent = svc.create_agent(db, body.name, body.objective, body.final_output, owner=body.owner,
                                 actor=actor(request), slug=body.slug, team_id=team.id, visibility=body.visibility)
        return svc.agent_dict(db, agent, detail=True, acc=a)
    return guard(go)


@router.get("/agents/{slug}")
def agent(slug: str, request: Request, db=Depends(db_dep)):
    a = _agent(request, db, slug)
    svc.refresh_deployments(db, [a])
    return svc.agent_dict(db, a, detail=True, acc=acc(request, db))


@router.patch("/agents/{slug}")
def patch_agent(slug: str, patch: dict, request: Request, db=Depends(db_dep)):
    """JSON Merge Patch (RFC 7396) sobre a spec (e name/objective/final_output/owner). null apaga."""
    _agent(request, db, slug, "edit")
    return guard(lambda: svc.agent_dict(db, svc.design_agent(db, slug, patch, actor(request)), detail=True,
                                        acc=acc(request, db)))


@router.put("/agents/{slug}/spec")
def put_spec(slug: str, spec: dict, request: Request, db=Depends(db_dep)):
    _agent(request, db, slug, "edit")
    return guard(lambda: svc.agent_dict(db, svc.replace_spec(db, slug, spec, actor(request)), detail=True,
                                        acc=acc(request, db)))


@router.post("/agents/{slug}/rollback")
def rollback(slug: str, body: RollbackBody, request: Request, db=Depends(db_dep)):
    _agent(request, db, slug, "edit")
    return guard(lambda: svc.agent_dict(db, svc.rollback_agent(db, slug, body.version, actor(request)), detail=True,
                                        acc=acc(request, db)))


class EditBody(BaseModel):
    changes: dict = Field(default_factory=dict)  # merge patch da spec + name/objective/final_output/owner
    test: bool = True
    promote: bool = False
    note: str = ""


@router.post("/agents/{slug}/edit")
def edit_agent(slug: str, body: EditBody, request: Request, db=Depends(db_dep)):
    """Editar depois: nova versão -> stage + testes -> (promote) produção ou pedido de aprovação."""
    return guard(lambda: org.edit_agent(db, acc(request, db), slug, body.changes, body.test, body.promote, body.note))


@router.get("/agents/{slug}/diff")
def diff_versions(slug: str, request: Request, from_version: int, to_version: int | None = None, db=Depends(db_dep)):
    _agent(request, db, slug, "view_spec")
    return guard(lambda: svc.registry.diff_versions(db, slug, from_version, to_version))


@router.get("/agents/{slug}/logs")
def logs(slug: str, request: Request, env: str = "prod", db=Depends(db_dep)):
    # logs podem ter conversas: só quem edita (ou auditor)
    _agent(request, db, slug, "view_spec" if principal(request).is_auditor else "edit")
    return {"logs": deploy.logs(slug, env)}


@router.post("/agents/{slug}/test")
def test(slug: str, request: Request, db=Depends(db_dep)):
    _agent(request, db, slug, "edit")
    return guard(lambda: svc.test_dict(svc.run_tests(db, slug, actor(request))))


@router.post("/agents/{slug}/deploy")
def deploy_ep(slug: str, body: EnvBody, request: Request, db=Depends(db_dep)):
    """stage: quem edita. prod: quem pode promover promove; os outros geram um pedido de aprovação
    (status "approval_pending")."""
    _agent(request, db, slug, "edit")
    if body.env != "prod":
        return guard(lambda: svc.dep_dict(svc.deploy_env(db, slug, body.env, actor(request))))
    r = guard(lambda: org.promote(db, acc(request, db), slug))
    if r["status"] == "deployed":
        return r["deployment"]
    req = r["request"]
    return {"status": "approval_pending", "version": req["version"], "url": "", "request": req}


@router.post("/agents/{slug}/ship")
def ship(slug: str, request: Request, body: ShipBody | None = None, db=Depends(db_dep)):
    """Testa (sub-agentes primeiro) e promove. Sem permissão de promover direto, o último passo vem como
    {"step": "prod", "status": "approval_pending", "request": <id>}."""
    return guard(lambda: org.ship(db, acc(request, db), slug, body.note if body else "")["steps"])


@router.post("/agents/{slug}/stop")
def stop(slug: str, body: EnvBody, request: Request, db=Depends(db_dep)):
    _agent(request, db, slug, "manage" if body.env == "prod" else "edit")
    guard(lambda: svc.stop(db, slug, body.env, actor(request)))
    return {"ok": True}


@router.post("/agents/{slug}/chat")
def chat(slug: str, body: Msg, request: Request, db=Depends(db_dep)):
    _agent(request, db, slug, "consume" if body.env == "prod" else "edit")
    return guard(lambda: svc.chat(db, slug, body.message, body.env, "admin-ui", actor(request)))


@router.delete("/agents/{slug}")
def delete(slug: str, request: Request, db=Depends(db_dep)):
    _agent(request, db, slug, "manage")
    guard(lambda: svc.delete_agent(db, slug, actor(request)))
    return {"ok": True}


# ------------------------------------------------------------------ jobs de harness
@router.post("/agents/{slug}/job")
def run_job(slug: str, body: JobBody, request: Request, db=Depends(db_dep)):
    """wait=true (padrão): bloqueia até terminar. wait=false: devolve o job em fila na hora — acompanhe por
    GET /api/jobs/{id} ou pelo stream GET /api/jobs/{id}/events."""
    _agent(request, db, slug, "consume" if body.env == "prod" else "edit")
    if body.wait:
        return guard(lambda: svc.job_dict(svc.run_harness_job(db, slug, body.task, body.env, body.timeout_s,
                                                              actor(request), "admin-ui")))
    return guard(lambda: svc.job_dict(svc.submit_job(db, slug, body.task, body.env, body.timeout_s,
                                                     actor(request), "admin-ui")))


def _job(request: Request, db, job_id: int) -> Job:
    job = db.get(Job, job_id)
    a = db.get(Agent, job.agent_id) if job else None
    if not job or not a or not acc(request, db).can("usage", a):
        raise HTTPException(404, "job não encontrado")
    return job


@router.get("/jobs/{job_id}")
def get_job(job_id: int, request: Request, db=Depends(db_dep)):
    return svc.job_dict(_job(request, db, job_id))


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, request: Request, db=Depends(db_dep)):
    _job(request, db, job_id)
    return guard(lambda: svc.job_dict(svc.cancel_job(db, job_id, actor(request))))


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: int, request: Request):
    """Server-Sent Events: status, logs do container em tempo real e o resultado final."""
    def check():
        from ..db import SessionLocal
        with SessionLocal() as db:
            _job(request, db, job_id)
    await run_in_threadpool(check)
    gen = svc.job_events(job_id)

    async def stream():
        while True:
            ev = await run_in_threadpool(next, gen, None)
            if ev is None:
                return
            yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ catálogo (leitura: todos; escrita: admin)
@router.get("/catalog")
def catalog(db=Depends(db_dep)):
    return {"skills": [{"name": s.name, "description": s.description, "content": s.content}
                       for s in db.scalars(select(Skill))],
            "mcp_servers": [{"name": m.name, "url": m.url, "description": m.description}
                            for m in db.scalars(select(McpServer))],
            "llm_connections": [svc.llm_connection_dict(c) for c in db.scalars(select(LlmConnection))],
            "fallback_model": config.DEFAULT_MODEL}


@router.post("/catalog/skills", dependencies=[Depends(require_admin)])
def add_skill(b: SkillBody, request: Request, db=Depends(db_dep)):
    svc.upsert_skill(db, b.name, b.description, b.content, actor(request))
    return {"ok": True}


@router.post("/catalog/mcps", dependencies=[Depends(require_admin)])
def add_mcp(b: McpBody, request: Request, db=Depends(db_dep)):
    guard(lambda: svc.upsert_mcp(db, b.name, b.url, b.description, actor(request)))
    return {"ok": True}


@router.post("/catalog/llm", dependencies=[Depends(require_admin)])
def add_llm_connection(b: LlmConnectionBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.llm_connection_dict(svc.upsert_llm_connection(
        db, b.name, b.base_url, b.model_name, b.api_key, b.description, actor(request), b.protocol,
        b.price_in_per_mtok, b.price_out_per_mtok)))


@router.delete("/catalog/llm/{name}", dependencies=[Depends(require_admin)])
def del_llm_connection(name: str, request: Request, db=Depends(db_dep)):
    guard(lambda: svc.delete_llm_connection(db, name, actor(request)))
    return {"ok": True}


# ------------------------------------------------------------------ GitOps e templates
@router.post("/apply")
def apply(doc: dict, request: Request, db=Depends(db_dep)):
    """Aplica um documento {skills, mcp_servers, agents} (formato de `hangar apply`). Idempotente. Agentes novos
    vão para o time do campo `team` (ou o único time onde você é developer)."""
    return guard(lambda: svc.apply_document(db, doc, actor(request), acc(request, db)))


@router.get("/templates")
def templates():
    return svc.list_templates()


@router.get("/templates/{template_id}")
def template(template_id: str):
    return guard(lambda: svc.get_template(template_id))


@router.post("/templates/{template_id}/apply")
def apply_template(template_id: str, body: TemplateApply, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.apply_template(db, template_id, body.connection, body.harness_connection,
                                            actor(request), acc(request, db), body.team))


# ------------------------------------------------------------------ conexões com ferramentas (plug and play)
@router.get("/connect/clients")
def connect_clients():
    return svc.connect.clients()


@router.get("/agents/{slug}/connections")
def agent_connections(slug: str, request: Request, db=Depends(db_dep)):
    """Quem administra o agente vê todas as conexões; os outros, só as próprias."""
    a = _agent(request, db, slug, "consume")
    p = principal(request)
    mine = None if acc(request, db).can("manage", a) else p.user_id
    return svc.connect.connections(db, slug, owner=mine)


@router.get("/agents/{slug}/connections/snippet")
def connection_snippet(slug: str, client: str, request: Request, mode: str = "mcp", db=Depends(db_dep)):
    """Prévia do trecho com <SUA_CHAVE> no lugar da chave (não cria nada)."""
    a = _agent(request, db, slug)
    return guard(lambda: svc.connect.snippet(client, mode, a.slug, a.name))


@router.post("/agents/{slug}/connections")
def create_connection(slug: str, body: ConnectBody, request: Request, db=Depends(db_dep)):
    """Cria a chave da ferramenta (invoke, só este agente, dona = quem pediu) e devolve o trecho pronto com ela.
    Revogue com DELETE /api/keys/{id}."""
    _agent(request, db, slug, "consume")
    p = principal(request)
    return guard(lambda: svc.connect.connect(db, slug, body.client, body.mode, actor(request),
                                             user_id=p.user_id if p.is_user else None))


# ------------------------------------------------------------------ chaves de API
@router.get("/keys")
def keys(request: Request, db=Depends(db_dep)):
    p = principal(request)
    q = select(ApiKey).order_by(ApiKey.id.desc())
    if not p.is_admin:
        q = q.where(ApiKey.user_id == p.user_id)
    return [auth.api_key_dict(k) for k in db.scalars(q)]


@router.post("/keys")
def create_key(body: KeyBody, request: Request, db=Depends(db_dep)):
    """admin/scim: só admins. user: token pessoal (age como você — CLI, MCP da plataforma). invoke: chama só os
    agentes listados (que você pode usar)."""
    p = principal(request)
    a = acc(request, db)

    def go():
        scopes = set(body.scopes)
        if scopes & {"admin", "scim"} and not p.is_admin:
            raise svc.access.Forbidden("chaves admin e scim são criadas só por admins")
        agents = [svc.get_agent(db, s) for s in body.agents]
        if "invoke" in scopes and not p.is_admin:
            if not agents:
                raise svc.PlatformError("informe os agentes que a chave pode chamar")
            for ag in agents:
                a.require("consume", ag)
        owner = p.user_id if p.is_user else None
        if "user" in scopes and not owner:
            raise svc.PlatformError("token pessoal (user) só pode ser criado por um usuário logado")
        row, raw = auth.create_api_key(db, body.name, sorted(scopes), body.agents, actor(request), user_id=owner)
        svc.audit(db, actor(request), "api_key.create", body.name, f"scopes={row.scopes} agents={row.agents}")
        return {**auth.api_key_dict(row), "key": raw, "note": "guarde agora: a chave não será exibida de novo"}
    return guard(go)


@router.delete("/keys/{key_id}")
def revoke_key(key_id: int, request: Request, db=Depends(db_dep)):
    p = principal(request)
    k = db.get(ApiKey, key_id)
    if not k or not (p.is_admin or (p.user_id and k.user_id == p.user_id) or _manages_key_agent(request, db, k)):
        raise HTTPException(404, "chave não encontrada")
    guard(lambda: auth.revoke_api_key(db, key_id))
    svc.audit(db, actor(request), "api_key.revoke", str(key_id))
    return {"ok": True}


def _manages_key_agent(request: Request, db, k: ApiKey) -> bool:
    """Mantenedor do agente pode desligar as conexões dele (aba Conectar)."""
    if not k.client or len(k.agents or []) != 1:
        return False
    a = svc.find_agent(db, k.agents[0])
    return bool(a and acc(request, db).can("manage", a))


# ------------------------------------------------------------------ listagens (filtradas pelo que você pode ver)
def _agents_where(request: Request, db, action: str) -> dict[int, Agent]:
    a = acc(request, db)
    return {x.id: x for x in db.scalars(select(Agent)) if a.can(action, x)}


@router.get("/tests")
def all_tests(request: Request, db=Depends(db_dep)):
    names = _agents_where(request, db, "view_spec")
    return [{**svc.test_dict(t), "agent": names[t.agent_id].slug, "agent_name": names[t.agent_id].name}
            for t in db.scalars(select(TestRun).order_by(TestRun.id.desc()).limit(300)) if t.agent_id in names][:100]


@router.get("/deployments")
def all_deployments(request: Request, db=Depends(db_dep)):
    svc.refresh_deployments(db)
    names = _agents_where(request, db, "view_spec")
    return [{**svc.dep_dict(d), "agent": names[d.agent_id].slug, "agent_name": names[d.agent_id].name}
            for d in db.scalars(select(Deployment).order_by(Deployment.id.desc()).limit(300))
            if d.agent_id in names][:100]


@router.get("/usage")
def usage(request: Request, db=Depends(db_dep)):
    names = _agents_where(request, db, "usage")
    return [svc.usage_row(u, names[u.agent_id].slug)
            for u in db.scalars(select(UsageEvent).order_by(UsageEvent.id.desc()).limit(500))
            if u.agent_id in names][:100]


@router.get("/audit", dependencies=[Depends(require_auditor)])
def audit_log(db=Depends(db_dep)):
    return [{"at": svc.iso(r.created_at), "actor": r.actor, "action": r.action, "target": r.target,
             "detail": r.detail} for r in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200))]
