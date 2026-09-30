"""Memória dos agentes: proxy MCP (agente -> central -> serviço de memória), config do serviço e API admin."""
import hmac

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask

from .. import auth, config
from .. import services as svc
from ..db import SessionLocal
from .deps import acc, db_dep, guard, require_auditor
from .internal import caller_agent, caller_specs

router = APIRouter()
FORWARD = ("content-type", "accept", "mcp-session-id", "mcp-protocol-version", "last-event-id", "x-session-id")
BACK = ("content-type", "mcp-session-id", "cache-control")


# ------------------------------------------------------------------ proxy para os agentes
def _authorize(request: Request) -> dict:
    """Headers que o serviço de memória recebe: grupos decididos aqui, a partir da spec e do ambiente provado."""
    if not svc.memory.enabled():
        raise HTTPException(503, "memória desligada nesta instalação")
    with SessionLocal() as db:
        a = caller_agent(request, db)
        mem = svc.memory.effective(caller_specs(a))
        if not mem:
            raise HTTPException(403, f"'{a.slug}' não tem `memory` na spec")
        env = auth.verified_env(a.slug, request.headers.get("x-agent-env", ""),
                                request.headers.get("x-agent-env-token", ""))
        read, write = svc.memory.groups(db, a, mem, env)
        return {"Authorization": f"Bearer {config.MEMORY_TOKEN}", "X-Memory-Read": ",".join(read),
                "X-Memory-Write": write, "X-Memory-Actor": a.slug}


@router.api_route("/internal/memory/mcp", methods=["GET", "POST", "DELETE"])
async def memory_proxy(request: Request):
    extra = await run_in_threadpool(_authorize, request)
    body = await request.body()
    fwd = {h: request.headers[h] for h in FORWARD if h in request.headers}
    client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=10))
    try:
        up = await client.send(client.build_request(request.method, f"{config.MEMORY_URL}/mcp", content=body,
                                                    headers={**fwd, **extra}), stream=True)
    except Exception as e:
        await client.aclose()
        return Response(f'{{"error": "memória indisponível: {type(e).__name__}"}}', 502, media_type="application/json")
    headers = {k: v for k, v in up.headers.items() if k.lower() in BACK}

    async def close():
        await up.aclose()
        await client.aclose()
    return StreamingResponse(up.aiter_bytes(), status_code=up.status_code, headers=headers, background=BackgroundTask(close))


@router.get("/internal/memory/config")
def memory_config(request: Request, db=Depends(db_dep)):
    """Só o serviço de memória (MEMORY_TOKEN): LLM de extração e, se usados, embeddings remotos."""
    tok = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not config.MEMORY_TOKEN or not hmac.compare_digest(tok, config.MEMORY_TOKEN):
        raise HTTPException(401, "token de memória inválido")
    return guard(lambda: svc.memory.service_config(db))


# ------------------------------------------------------------------ administração
@router.get("/api/memory/status", dependencies=[Depends(require_auditor)])
def memory_status():
    return svc.memory.status()


@router.get("/api/agents/{slug}/memory")
def agent_memory(slug: str, request: Request, env: str = "prod", q: str = "", limit: int = 50, db=Depends(db_dep)):
    return guard(lambda: svc.memory.agent_facts(db, acc(request, db), svc.get_agent(db, slug), env, q, limit))


@router.delete("/api/agents/{slug}/memory")
def agent_memory_clear(slug: str, request: Request, env: str = "prod", db=Depends(db_dep)):
    return guard(lambda: svc.memory.clear_agent(db, acc(request, db), svc.get_agent(db, slug), env))
