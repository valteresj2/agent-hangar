"""Agent Hangar — app FastAPI: API admin, gateway dos agentes, MCP da plataforma e UI."""
import hashlib
import hmac
import logging
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth, config, crypto, db
from . import services as svc
from .mcp_tools import mcp
from .routers import access, admin, gateway, internal, remote_mcp, schedules, scim

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hangar")

mcp_app = mcp.streamable_http_app()


def _write_gateway_files():
    try:
        with db.SessionLocal() as s:
            svc.mcp_gateway.write_files(s)
    except OSError as e:
        log.warning("catálogo Docker MCP: não foi possível escrever em %s (%s)", config.MCP_GATEWAY_CONFIG_DIR, e)


@asynccontextmanager
async def lifespan(app):
    crypto.check_key()
    if not config.INTERNAL_SECRET:
        raise RuntimeError("INTERNAL_SECRET não definido (rode scripts/setup.sh ou veja .env.example)")
    if not config.ADMIN_TOKEN or config.ADMIN_TOKEN in ("changeme", "change-me"):
        log.warning("ADMIN_TOKEN vazio ou padrão — defina um valor forte antes de expor a central")
    await run_in_threadpool(db.migrate)
    await run_in_threadpool(svc.recover_orphans)
    await run_in_threadpool(_write_gateway_files)  # o gateway Docker MCP precisa dos arquivos mesmo sem servidor ativo
    svc.schedules.start()
    try:
        async with mcp.session_manager.run():
            yield
    finally:
        svc.schedules.stop()


app = FastAPI(title=config.APP_NAME, version=config.VERSION, lifespan=lifespan)

_GW = re.compile(r"^/gw(?:-stage)?/([^/]+)(?:/|$)")
OPEN_PREFIXES = ("/ui", "/api/health", "/internal", "/api/auth/", "/login", "/favicon.ico")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def _may_consume(principal, slug: str) -> bool:
    with db.SessionLocal() as s:
        a = svc.find_agent(s, slug)
        return a is None or svc.access.of(s, principal).can("consume", a)  # inexistente: o gateway responde 404


class AuthMiddleware:
    """Autentica tudo, menos a UI estática, o health, o login e /internal (que tem autenticação própria por
    token de job ou de agente). Credencial: header (Bearer/X-API-Key) ou cookie de sessão da UI — este exige
    o header X-CSRF-Token igual ao cookie hangar_csrf em toda escrita (double-submit).
    /gw/<slug> exige poder usar aquele agente; /scim, chave scim; o resto (/api, /mcp), admin ou usuário —
    e cada rota confere a permissão sobre o recurso."""

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
        via_cookie = False
        if not token:
            token = auth.cookie(headers, auth.SESSION_COOKIE)
            via_cookie = bool(token)

        def _auth():
            with db.SessionLocal() as s:
                return auth.authenticate(s, token)

        principal = await run_in_threadpool(_auth) if token else None
        if principal is None:
            return await JSONResponse({"error": "unauthorized"}, 401)(scope, receive, send)
        if via_cookie and scope["method"] not in SAFE_METHODS:
            csrf = auth.cookie(headers, auth.CSRF_COOKIE)
            if not csrf or not hmac.compare_digest(csrf, headers.get("x-csrf-token", "")):
                return await JSONResponse({"error": "csrf: recarregue a página"}, 403)(scope, receive, send)
        m = _GW.match(path)
        if m:
            slug = m.group(1)
            allowed = (await run_in_threadpool(_may_consume, principal, slug)) if principal.is_user \
                and not principal.is_admin else principal.can_invoke(slug)
        elif path.startswith("/scim"):
            allowed = "scim" in principal.scopes or principal.is_admin
        else:
            allowed = principal.can_use_api
        if not allowed:
            return await JSONResponse({"error": "forbidden: a credencial não tem permissão para este recurso"},
                                      403)(scope, receive, send)
        scope.setdefault("state", {})["principal"] = principal
        return await self.app(scope, receive, send)


app.add_middleware(AuthMiddleware)
app.include_router(access.router)
app.include_router(admin.router)
app.include_router(scim.router)
app.include_router(schedules.router)
app.include_router(remote_mcp.router)
app.include_router(internal.router)
app.include_router(gateway.router)


STATIC = os.path.join(os.path.dirname(__file__), "static")
# carimbo de versão dos arquivos da UI: muda a cada atualização, então o navegador nunca mistura versões
UI_VERSION = hashlib.sha256(b"".join(open(os.path.join(STATIC, f), "rb").read()
                                     for f in sorted(os.listdir(STATIC)))).hexdigest()[:12]
_INDEX = open(os.path.join(STATIC, "index.html"), encoding="utf-8").read().replace("__V__", UI_VERSION)


@app.get("/")
@app.get("/ui")  # sem a barra final: sem esta rota, o MCP montado em "/" respondia 404
@app.get("/login")
def root():
    return RedirectResponse(f"/ui/?v={UI_VERSION}")  # URL nova a cada versão: fura até um index.html em cache


@app.get("/favicon.ico")
def favicon():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#F4B400" stroke-width="2.2" '
           'stroke-linejoin="round"><path d="M2.5 20.5V11L12 3.5 21.5 11v9.5"/><path d="M6.5 20.5v-6h11v6"/></svg>')
    return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "max-age=86400"})


@app.get("/ui/")
@app.get("/ui/index.html")
def ui_index():
    return HTMLResponse(_INDEX, headers={"Cache-Control": "no-cache"})


class UIFiles(StaticFiles):
    """UI sem cache heurístico: o navegador sempre revalida (ETag), então uma atualização da central aparece no
    próximo carregamento — sem Ctrl+F5."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


app.mount("/ui", UIFiles(directory=STATIC, html=True), name="ui")
app.mount("/", mcp_app)
