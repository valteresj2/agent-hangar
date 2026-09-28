"""API de administração (/api) — exige credencial com escopo admin (ver AuthMiddleware)."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import auth, config, deploy
from .. import services as svc
from .. import spec as specmod
from ..db import SessionLocal
from ..models import Agent, ApiKey, AuditLog, Deployment, Job, LlmConnection, McpServer, Skill, TestRun, UsageEvent

router = APIRouter(prefix="/api")


def db_dep():
    with SessionLocal() as db:
        yield db


def actor(request: Request) -> str:
    p = request.scope.get("state", {}).get("principal")
    return p.name if p else "admin"


def guard(fn):
    try:
        return fn()
    except svc.PlatformError as e:
        raise HTTPException(400, str(e)) from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


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


class ConnectBody(BaseModel):
    client: str
    mode: str = "mcp"


class KeyBody(BaseModel):
    name: str
    scopes: list[str] = Field(default_factory=lambda: ["invoke"])
    agents: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ plataforma
@router.get("/health")
def health():
    return {"status": "ok", "version": config.VERSION}


@router.get("/overview")
def overview(db=Depends(db_dep)):
    return svc.overview(db)


@router.get("/connect")
def connect():
    b = config.PUBLIC_BASE_URL
    return {"base_url": b, "mcp_url": f"{b}/mcp", "gateway": f"{b}/gw/<slug>"}


@router.get("/spec/schema")
def spec_schema():
    return specmod.json_schema()


# ------------------------------------------------------------------ agentes
@router.get("/agents")
def agents(db=Depends(db_dep)):
    return svc.list_agents(db)


@router.post("/agents")
def create_agent(body: NewAgent, request: Request, db=Depends(db_dep)):
    a = guard(lambda: svc.create_agent(db, body.name, body.objective, body.final_output, owner=body.owner,
                                       actor=actor(request), slug=body.slug))
    return svc.agent_dict(db, a, detail=True)


@router.get("/agents/{slug}")
def agent(slug: str, db=Depends(db_dep)):
    def go():
        a = svc.get_agent(db, slug)
        svc.refresh_deployments(db, [a])
        return svc.agent_dict(db, a, detail=True)
    return guard(go)


@router.patch("/agents/{slug}")
def patch_agent(slug: str, patch: dict, request: Request, db=Depends(db_dep)):
    """JSON Merge Patch (RFC 7396) sobre a spec (e name/objective/final_output/owner). null apaga."""
    return guard(lambda: svc.agent_dict(db, svc.design_agent(db, slug, patch, actor(request)), detail=True))


@router.put("/agents/{slug}/spec")
def put_spec(slug: str, spec: dict, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.agent_dict(db, svc.replace_spec(db, slug, spec, actor(request)), detail=True))


@router.post("/agents/{slug}/rollback")
def rollback(slug: str, body: RollbackBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.agent_dict(db, svc.rollback_agent(db, slug, body.version, actor(request)), detail=True))


@router.get("/agents/{slug}/logs")
def logs(slug: str, env: str = "prod"):
    return {"logs": deploy.logs(slug, env)}


@router.post("/agents/{slug}/test")
def test(slug: str, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.test_dict(svc.run_tests(db, slug, actor(request))))


@router.post("/agents/{slug}/deploy")
def deploy_ep(slug: str, body: EnvBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.dep_dict(svc.deploy_env(db, slug, body.env, actor(request))))


@router.post("/agents/{slug}/ship")
def ship(slug: str, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.ship(db, slug, actor(request)))


@router.post("/agents/{slug}/stop")
def stop(slug: str, body: EnvBody, request: Request, db=Depends(db_dep)):
    guard(lambda: svc.stop(db, slug, body.env, actor(request)))
    return {"ok": True}


@router.post("/agents/{slug}/chat")
def chat(slug: str, body: Msg, db=Depends(db_dep)):
    return guard(lambda: svc.chat(db, slug, body.message, body.env, "admin-ui"))


@router.delete("/agents/{slug}")
def delete(slug: str, request: Request, db=Depends(db_dep)):
    guard(lambda: svc.delete_agent(db, slug, actor(request)))
    return {"ok": True}


# ------------------------------------------------------------------ jobs de harness
@router.post("/agents/{slug}/job")
def run_job(slug: str, body: JobBody, request: Request, db=Depends(db_dep)):
    """wait=true (padrão): bloqueia até terminar. wait=false: devolve o job em fila na hora — acompanhe por
    GET /api/jobs/{id} ou pelo stream GET /api/jobs/{id}/events."""
    if body.wait:
        return guard(lambda: svc.job_dict(svc.run_harness_job(db, slug, body.task, body.env, body.timeout_s,
                                                              actor(request), "admin-ui")))
    return guard(lambda: svc.job_dict(svc.submit_job(db, slug, body.task, body.env, body.timeout_s,
                                                     actor(request), "admin-ui")))


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db=Depends(db_dep)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job não encontrado")
    return svc.job_dict(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.job_dict(svc.cancel_job(db, job_id, actor(request))))


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: int):
    """Server-Sent Events: status, logs do container em tempo real e o resultado final."""
    gen = svc.job_events(job_id)

    async def stream():
        while True:
            ev = await run_in_threadpool(next, gen, None)
            if ev is None:
                return
            yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ catálogo
@router.get("/catalog")
def catalog(db=Depends(db_dep)):
    return {"skills": [{"name": s.name, "description": s.description, "content": s.content}
                       for s in db.scalars(select(Skill))],
            "mcp_servers": [{"name": m.name, "url": m.url, "description": m.description}
                            for m in db.scalars(select(McpServer))],
            "llm_connections": [svc.llm_connection_dict(c) for c in db.scalars(select(LlmConnection))],
            "fallback_model": config.DEFAULT_MODEL}


@router.post("/catalog/skills")
def add_skill(b: SkillBody, request: Request, db=Depends(db_dep)):
    svc.upsert_skill(db, b.name, b.description, b.content, actor(request))
    return {"ok": True}


@router.post("/catalog/mcps")
def add_mcp(b: McpBody, request: Request, db=Depends(db_dep)):
    guard(lambda: svc.upsert_mcp(db, b.name, b.url, b.description, actor(request)))
    return {"ok": True}


@router.post("/catalog/llm")
def add_llm_connection(b: LlmConnectionBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.llm_connection_dict(svc.upsert_llm_connection(
        db, b.name, b.base_url, b.model_name, b.api_key, b.description, actor(request), b.protocol,
        b.price_in_per_mtok, b.price_out_per_mtok)))


@router.delete("/catalog/llm/{name}")
def del_llm_connection(name: str, request: Request, db=Depends(db_dep)):
    guard(lambda: svc.delete_llm_connection(db, name, actor(request)))
    return {"ok": True}


# ------------------------------------------------------------------ GitOps e templates
@router.post("/apply")
def apply(doc: dict, request: Request, db=Depends(db_dep)):
    """Aplica um documento {skills, mcp_servers, agents} (formato de `hangar apply`). Idempotente."""
    return guard(lambda: svc.apply_document(db, doc, actor(request)))


@router.get("/templates")
def templates():
    return svc.list_templates()


@router.get("/templates/{template_id}")
def template(template_id: str):
    return guard(lambda: svc.get_template(template_id))


@router.post("/templates/{template_id}/apply")
def apply_template(template_id: str, body: TemplateApply, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.apply_template(db, template_id, body.connection, body.harness_connection,
                                            actor(request)))


# ------------------------------------------------------------------ conexões com ferramentas (plug and play)
@router.get("/connect/clients")
def connect_clients():
    return svc.connect.clients()


@router.get("/agents/{slug}/connections")
def agent_connections(slug: str, db=Depends(db_dep)):
    return guard(lambda: (svc.get_agent(db, slug), svc.connect.connections(db, slug))[1])


@router.get("/agents/{slug}/connections/snippet")
def connection_snippet(slug: str, client: str, mode: str = "mcp", db=Depends(db_dep)):
    """Prévia do trecho com <SUA_CHAVE> no lugar da chave (não cria nada)."""
    def go():
        a = svc.get_agent(db, slug)
        return svc.connect.snippet(client, mode, a.slug, a.name)
    return guard(go)


@router.post("/agents/{slug}/connections")
def create_connection(slug: str, body: ConnectBody, request: Request, db=Depends(db_dep)):
    """Cria a chave da ferramenta (invoke, só este agente) e devolve o trecho pronto com ela. Revogue com
    DELETE /api/keys/{id}."""
    return guard(lambda: svc.connect.connect(db, slug, body.client, body.mode, actor(request)))


# ------------------------------------------------------------------ chaves de API
@router.get("/keys")
def keys(db=Depends(db_dep)):
    return [auth.api_key_dict(k) for k in db.scalars(select(ApiKey).order_by(ApiKey.id.desc()))]


@router.post("/keys")
def create_key(body: KeyBody, request: Request, db=Depends(db_dep)):
    for s in body.agents:
        guard(lambda s=s: svc.get_agent(db, s))
    row, raw = guard(lambda: auth.create_api_key(db, body.name, body.scopes, body.agents, actor(request)))
    svc.audit(db, actor(request), "api_key.create", body.name, f"scopes={row.scopes} agents={row.agents}")
    return {**auth.api_key_dict(row), "key": raw, "note": "guarde agora: a chave não será exibida de novo"}


@router.delete("/keys/{key_id}")
def revoke_key(key_id: int, request: Request, db=Depends(db_dep)):
    guard(lambda: auth.revoke_api_key(db, key_id))
    svc.audit(db, actor(request), "api_key.revoke", str(key_id))
    return {"ok": True}


# ------------------------------------------------------------------ listagens
@router.get("/tests")
def all_tests(db=Depends(db_dep)):
    names = {a.id: a for a in db.scalars(select(Agent))}
    return [{**svc.test_dict(t), "agent": names[t.agent_id].slug, "agent_name": names[t.agent_id].name}
            for t in db.scalars(select(TestRun).order_by(TestRun.id.desc()).limit(100)) if t.agent_id in names]


@router.get("/deployments")
def all_deployments(db=Depends(db_dep)):
    svc.refresh_deployments(db)
    names = {a.id: a for a in db.scalars(select(Agent))}
    return [{**svc.dep_dict(d), "agent": names[d.agent_id].slug, "agent_name": names[d.agent_id].name}
            for d in db.scalars(select(Deployment).order_by(Deployment.id.desc()).limit(100)) if d.agent_id in names]


@router.get("/usage")
def usage(db=Depends(db_dep)):
    names = {a.id: a for a in db.scalars(select(Agent))}
    return [svc.usage_row(u, names[u.agent_id].slug)
            for u in db.scalars(select(UsageEvent).order_by(UsageEvent.id.desc()).limit(100)) if u.agent_id in names]


@router.get("/audit")
def audit_log(db=Depends(db_dep)):
    return [{"at": svc.iso(r.created_at), "actor": r.actor, "action": r.action, "target": r.target,
             "detail": r.detail} for r in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200))]
