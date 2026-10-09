"""Plugins: catálogo, rascunho/importação de OpenAPI, revisão (quatro olhos), instalação por time e o servidor MCP
interno que os agentes chamam (/internal/plugins/<nome>/mcp, autenticado pelo token interno do agente)."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .. import services as svc
from ..db import SessionLocal
from .deps import acc, db_dep, guard
from .internal import caller_agent, caller_specs

router = APIRouter()


class ManifestBody(BaseModel):
    manifest: dict | str
    team: str | None = None
    source: str = "manual"


class OpenApiBody(BaseModel):
    document: dict | str
    name: str = ""
    base_url: str = ""
    only: list[str] | None = None


class ReviewBody(BaseModel):
    decision: str
    note: str = ""


class InstallBody(BaseModel):
    team: str | None = None
    settings: dict | None = None
    secrets: dict | None = None
    credential: str | None = None
    enabled: bool | None = None


class TeamBody(BaseModel):
    team: str | None = None


@router.get("/api/plugins")
def plugins(request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.plugins.list_plugins(db, acc(request, db)))


@router.post("/api/plugins")
def create(body: ManifestBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.plugins.create(db, acc(request, db), body.manifest, body.team, body.source))


@router.post("/api/plugins/import-openapi")
def import_openapi(body: OpenApiBody, request: Request, db=Depends(db_dep)):
    """Devolve um rascunho de manifesto (não grava): revise as ações e salve com POST /api/plugins."""
    acc(request, db)
    return guard(lambda: {"manifest": svc.plugins.from_openapi(body.document, body.name, body.base_url, body.only)})


@router.get("/api/plugins/{name}")
def detail(name: str, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.plugins.get_plugin(db, acc(request, db), name))


@router.put("/api/plugins/{name}")
def update(name: str, body: ManifestBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.plugins.update(db, acc(request, db), name, body.manifest))


@router.delete("/api/plugins/{name}")
def delete(name: str, request: Request, db=Depends(db_dep)):
    guard(lambda: svc.plugins.delete(db, acc(request, db), name))
    return {"deleted": name}


@router.post("/api/plugins/{name}/submit")
def submit(name: str, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.plugins.submit(db, acc(request, db), name))


@router.post("/api/plugins/{name}/review")
def review(name: str, body: ReviewBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.plugins.review(db, acc(request, db), name, body.decision, body.note))


@router.post("/api/plugins/{name}/disable")
def disable(name: str, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.plugins.set_disabled(db, acc(request, db), name, True))


@router.post("/api/plugins/{name}/enable")
def enable(name: str, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.plugins.set_disabled(db, acc(request, db), name, False))


@router.put("/api/plugins/{name}/install")
def install(name: str, body: InstallBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.plugins.install(db, acc(request, db), name, body.team, body.settings, body.secrets,
                                             body.credential, body.enabled))


@router.delete("/api/plugins/{name}/install")
def uninstall(name: str, request: Request, team: str | None = None, db=Depends(db_dep)):
    guard(lambda: svc.plugins.uninstall(db, acc(request, db), name, team))
    return {"uninstalled": name, "team": team}


@router.post("/api/plugins/{name}/install/test")
def test(name: str, body: TeamBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.plugins.test_install(db, acc(request, db), name, body.team))


# ------------------------------------------------------------------ servidor MCP interno (agente -> central -> sistema)
def _mcp(request: Request, name: str, msg: dict):
    with SessionLocal() as db:
        a = caller_agent(request, db)
        try:
            return svc.plugins.mcp_handle(db, a, caller_specs(a), name, msg)
        except svc.access.Forbidden as e:
            raise HTTPException(403, str(e)) from None
        except svc.PlatformError as e:
            return {"jsonrpc": "2.0", "id": msg.get("id"), "error": {"code": -32000, "message": str(e)}}


@router.api_route("/internal/plugins/{name}/mcp", methods=["GET", "POST", "DELETE"])
async def plugin_mcp(name: str, request: Request):
    if request.method != "POST":
        return Response(status_code=405)  # sem stream SSE nem sessão: cada chamada é independente
    try:
        msg = json.loads(await request.body() or b"{}")
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON inválido"}}, 400)
    if not isinstance(msg, dict):
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "lotes não suportados"}}, 400)
    out = await run_in_threadpool(_mcp, request, name, msg)
    return JSONResponse(out) if out is not None else Response(status_code=202)
