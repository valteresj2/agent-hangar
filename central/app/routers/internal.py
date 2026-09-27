"""Rotas chamadas de dentro dos containers (nunca por clientes externos). Isentas do AuthMiddleware: cada
uma confere a credencial própria — token de uso único do job, ou token interno do agente que chama."""
import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from .. import auth
from .. import services as svc
from ..db import SessionLocal
from ..models import Agent, AuditLog, Deployment, Job, TestRun, UsageEvent

router = APIRouter(prefix="/internal")


def db_dep():
    with SessionLocal() as db:
        yield db


class JobCallback(BaseModel):
    status: str  # passed | failed
    result: str = ""
    diff: str = ""
    logs: str = ""
    usage: dict | None = None


@router.post("/jobs/{job_id}/callback")
def job_callback(job_id: int, body: JobCallback, request: Request, db=Depends(db_dep)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "job não encontrado")
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not job.token or not hmac.compare_digest(token, job.token):
        raise HTTPException(401, "token de job inválido")
    if body.status not in ("passed", "failed"):
        raise HTTPException(400, "status deve ser 'passed' ou 'failed'")
    svc.complete_job(db, job, body.status, body.result, body.diff, body.logs, body.usage)
    return {"ok": True}


# ------------------------------------------------------------------ identidade do agente que chama
def caller_agent(request: Request, db) -> Agent:
    slug = request.headers.get("x-agent-slug", "")
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not auth.verify_agent_token(slug, token):
        raise HTTPException(401, "token interno inválido para este agente")
    a = svc.find_agent(db, slug)
    if not a:
        raise HTTPException(401, "agente desconhecido")
    return a


def caller_specs(a: Agent) -> list[dict]:
    """Specs que o container do agente pode estar rodando: a versão atual e as dos deployments no ar."""
    versions = {a.current_version} | {d.version for d in a.deployments if d.status == "running"}
    out = []
    for v in versions:
        try:
            out.append(svc.spec_of(a, v))
        except svc.PlatformError:
            pass
    return out


def may_call(a: Agent, target_slug: str) -> bool:
    return any(target_slug in (s.get("sub_agents") or []) for s in caller_specs(a))


def may_read_dashboard(a: Agent) -> bool:
    return any(t.get("type") == "builtin" and t.get("name") == "platform_dashboard"
               for s in caller_specs(a) for t in (s.get("tools") or []))


# ------------------------------------------------------------------ dashboard (somente leitura)
def dashboard_caller(request: Request, db=Depends(db_dep)):
    a = caller_agent(request, db)
    if not may_read_dashboard(a):
        raise HTTPException(403, "este agente não tem a tool platform_dashboard")
    return db


@router.get("/dashboard/overview")
def dash_overview(db=Depends(dashboard_caller)):
    return svc.overview(db)


@router.get("/dashboard/agents")
def dash_agents(db=Depends(dashboard_caller)):
    return svc.list_agents(db)


@router.get("/dashboard/agents/{slug}")
def dash_agent(slug: str, db=Depends(dashboard_caller)):
    a = svc.find_agent(db, slug)
    if not a:
        raise HTTPException(404, f"agente '{slug}' não encontrado")
    return svc.agent_dict(db, a, detail=True)


@router.get("/dashboard/deployments")
def dash_deployments(db=Depends(dashboard_caller)):
    svc.refresh_deployments(db)
    names = {a.id: a.slug for a in db.scalars(select(Agent))}
    return [{**svc.dep_dict(d), "agent": names[d.agent_id]} for d in
            db.scalars(select(Deployment).order_by(Deployment.id.desc()).limit(100)) if d.agent_id in names]


@router.get("/dashboard/tests")
def dash_tests(db=Depends(dashboard_caller)):
    names = {a.id: a.slug for a in db.scalars(select(Agent))}
    return [{**svc.test_dict(t), "agent": names[t.agent_id]} for t in
            db.scalars(select(TestRun).order_by(TestRun.id.desc()).limit(100)) if t.agent_id in names]


@router.get("/dashboard/usage")
def dash_usage(db=Depends(dashboard_caller)):
    names = {a.id: a.slug for a in db.scalars(select(Agent))}
    return [svc.usage_row(u, names[u.agent_id]) for u in
            db.scalars(select(UsageEvent).order_by(UsageEvent.id.desc()).limit(100)) if u.agent_id in names]


@router.get("/dashboard/audit")
def dash_audit(db=Depends(dashboard_caller)):
    return [{"at": svc.iso(r.created_at), "actor": r.actor, "action": r.action, "target": r.target,
             "detail": r.detail} for r in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(100))]
