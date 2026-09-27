"""Agent Hangar — app FastAPI: API admin, gateway dos agentes, MCP da plataforma e UI."""
import logging
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, config, crypto, db
from . import services as svc
from .mcp_tools import mcp
from .routers import admin, gateway, internal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hangar")

mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app):
    crypto.check_key()
    if not config.INTERNAL_SECRET:
        raise RuntimeError("INTERNAL_SECRET não definido (rode scripts/setup.sh ou veja .env.example)")
    if not config.ADMIN_TOKEN or config.ADMIN_TOKEN in ("changeme", "change-me"):
        log.warning("ADMIN_TOKEN vazio ou padrão — defina um valor forte antes de expor a central")
    await run_in_threadpool(db.migrate)
    await run_in_threadpool(svc.recover_orphans)
    async with mcp.session_manager.run():
        yield


app = FastAPI(title=config.APP_NAME, version=config.VERSION, lifespan=lifespan)

_GW = re.compile(r"^/gw(?:-stage)?/([^/]+)(?:/|$)")
OPEN_PREFIXES = ("/ui", "/api/health", "/internal")


class AuthMiddleware:
    """Autentica tudo, menos a UI estática, o health e /internal (que tem autenticação própria por
    token de job ou de agente). /gw/<slug> exige permissão de invocar aquele agente; o resto exige admin."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        if path == "/" or path.startswith(OPEN_PREFIXES):
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        token = auth.token_from_headers(headers)

        def _auth():
            with db.SessionLocal() as s:
                return auth.authenticate(s, token)

        principal = await run_in_threadpool(_auth) if token else None
        if principal is None:
            return await JSONResponse({"error": "unauthorized"}, 401)(scope, receive, send)
        m = _GW.match(path)
        allowed = principal.can_invoke(m.group(1)) if m else principal.is_admin
        if not allowed:
            return await JSONResponse({"error": "forbidden: a chave não tem permissão para este recurso"},
                                      403)(scope, receive, send)
        scope.setdefault("state", {})["principal"] = principal
        return await self.app(scope, receive, send)


app.add_middleware(AuthMiddleware)
app.include_router(admin.router)
app.include_router(internal.router)
app.include_router(gateway.router)


@app.get("/")
def root():
    return RedirectResponse("/ui/")


app.mount("/ui", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="ui")
app.mount("/", mcp_app)
