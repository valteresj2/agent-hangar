"""Login (OAuth2), sessão, empresa, times, usuários, pedidos de acesso, aprovações e configuração de SSO."""
import secrets
import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from .. import auth, config, sso
from ..services import org
from .deps import acc, actor, db_dep, guard, principal, require_admin

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ cookies
def _set_session(resp, raw: str):
    kw = {"secure": config.COOKIE_SECURE, "samesite": "lax", "path": "/", "max_age": config.SESSION_TTL_HOURS * 3600}
    resp.set_cookie(auth.SESSION_COOKIE, raw, httponly=True, **kw)
    # double-submit: a UI lê este cookie e manda no header X-CSRF-Token em toda escrita
    resp.set_cookie(auth.CSRF_COOKIE, secrets.token_urlsafe(24), httponly=False, **kw)


def _clear(resp):
    for c in (auth.SESSION_COOKIE, auth.CSRF_COOKIE):
        resp.delete_cookie(c, path="/")
    resp.delete_cookie(sso.STATE_COOKIE, path="/api/auth")


# ------------------------------------------------------------------ login
class TokenLogin(BaseModel):
    token: str


class PasswordLogin(BaseModel):
    username: str  # usuário ou e-mail
    password: str


class PasswordChange(BaseModel):
    current: str
    new: str


@router.get("/auth/providers")
def providers(db=Depends(db_dep)):
    return {"providers": sso.public_providers(db), "token_login": True, "password_login": config.LOCAL_LOGIN}


@router.post("/auth/password")
def password_login(body: PasswordLogin, db=Depends(db_dep)):
    """Conta local: usuário (ou e-mail) e senha -> sessão em cookie."""
    user = guard(lambda: org.password_login(db, body.username, body.password))
    resp = JSONResponse({"ok": True})
    _set_session(resp, auth.create_session(db, user))
    return resp


@router.post("/me/password")
def change_password(body: PasswordChange, request: Request, db=Depends(db_dep)):
    guard(lambda: org.change_password(db, acc(request, db), body.current, body.new))
    return {"ok": True}


@router.get("/auth/login/{provider}")
def login(provider: str, next: str = "#/", db=Depends(db_dep)):
    try:
        url, state = sso.start(db, provider, next)
    except sso.AuthError as e:
        return RedirectResponse("/ui/#/login?error=" + urllib.parse.quote(str(e)), 303)
    resp = RedirectResponse(url, 303)
    resp.set_cookie(sso.STATE_COOKIE, state, max_age=600, httponly=True, secure=config.COOKIE_SECURE,
                    samesite="lax", path="/api/auth")
    return resp


@router.get("/auth/callback/{provider}")
def callback(provider: str, request: Request, code: str = "", state: str = "", error: str = "",
             error_description: str = "", db=Depends(db_dep)):
    try:
        if error:
            raise sso.AuthError(f"o provedor recusou o login ({error_description or error})")
        user, nxt = sso.finish(db, provider, code, state, request.cookies.get(sso.STATE_COOKIE, ""))
    except sso.AuthError as e:
        resp = RedirectResponse("/ui/#/login?error=" + urllib.parse.quote(str(e)[:300]), 303)
        resp.delete_cookie(sso.STATE_COOKIE, path="/api/auth")
        return resp
    resp = RedirectResponse("/ui/" + sso.safe_next(nxt), 303)
    resp.delete_cookie(sso.STATE_COOKIE, path="/api/auth")
    _set_session(resp, auth.create_session(db, user))
    return resp


@router.post("/auth/token")
def token_login(body: TokenLogin, db=Depends(db_dep)):
    """Entrar com token: ADMIN_TOKEN (emergência), chave admin ou token pessoal ("user"). Abre uma sessão em
    cookie — o token não fica guardado no navegador."""
    p = auth.authenticate(db, body.token.strip())
    if p is None:
        raise HTTPException(401, "token inválido")
    if p.is_user:
        from ..models import User
        raw = auth.create_session(db, db.get(User, p.user_id))
    elif "admin" in p.scopes:
        raw = auth.create_session(db, None, admin=True, label=p.name)
        org.audit(db, p.name, "auth.token_login", "admin", "sessão de emergência")
    else:
        raise HTTPException(403, "esta chave não dá acesso à UI (use uma chave admin ou um token pessoal)")
    resp = JSONResponse({"ok": True})
    _set_session(resp, raw)
    return resp


@router.post("/auth/logout")
def logout(request: Request, db=Depends(db_dep)):
    auth.end_session(db, request.cookies.get(auth.SESSION_COOKIE, ""))
    resp = JSONResponse({"ok": True})
    _clear(resp)
    return resp


@router.get("/me")
def me(request: Request, db=Depends(db_dep)):
    return org.me(db, acc(request, db))


# ------------------------------------------------------------------ empresa
class OrgBody(BaseModel):
    name: str | None = None
    default_visibility: str | None = None


@router.get("/org")
def get_org(db=Depends(db_dep)):
    return org.org_dict(db)


@router.patch("/org")
def patch_org(body: OrgBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: org.update_org(db, acc(request, db), body.name, body.default_visibility))


# ------------------------------------------------------------------ times e membros
class TeamBody(BaseModel):
    name: str
    slug: str = ""
    description: str = ""
    require_approval: bool = True
    maintainer: str | None = None  # e-mail ou usuário: já entra como mantenedor


class TeamPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    require_approval: bool | None = None
    budget_usd_month: float | None = None
    budget_enforce: bool | None = None


class MemberBody(BaseModel):
    email: str
    role: str = "consumer"


class RoleBody(BaseModel):
    role: str


@router.get("/teams")
def teams(request: Request, db=Depends(db_dep)):
    return org.list_teams(db, acc(request, db))


@router.post("/teams")
def create_team(body: TeamBody, request: Request, db=Depends(db_dep)):
    a = acc(request, db)
    return guard(lambda: org.team_dict(db, org.create_team(db, a, body.name, body.slug, body.description,
                                                           body.require_approval, body.maintainer), a))


@router.get("/teams/{team}")
def team(team: str, request: Request, db=Depends(db_dep)):
    a = acc(request, db)
    return guard(lambda: org.team_dict(db, org.find_team(db, team), a))


@router.patch("/teams/{team}")
def patch_team(team: str, body: TeamPatch, request: Request, db=Depends(db_dep)):
    a = acc(request, db)
    return guard(lambda: org.team_dict(db, org.update_team(db, a, team, body.model_dump(exclude_unset=True)), a))


@router.delete("/teams/{team}")
def delete_team(team: str, request: Request, db=Depends(db_dep)):
    guard(lambda: org.delete_team(db, acc(request, db), team))
    return {"ok": True}


@router.get("/teams/{team}/members")
def team_members(team: str, request: Request, db=Depends(db_dep)):
    return guard(lambda: org.members(db, acc(request, db), team))


@router.post("/teams/{team}/members")
def add_member(team: str, body: MemberBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: org.add_member(db, acc(request, db), team, body.email, body.role))


@router.patch("/teams/{team}/members/{user_id}")
def set_member_role(team: str, user_id: int, body: RoleBody, request: Request, db=Depends(db_dep)):
    def go():
        a = acc(request, db)
        from ..models import User
        u = db.get(User, user_id)
        if not u:
            raise org.PlatformError("usuário não encontrado")
        return org.add_member(db, a, team, u.email, body.role)
    return guard(go)


@router.delete("/teams/{team}/members/{user_id}")
def remove_member(team: str, user_id: int, request: Request, db=Depends(db_dep)):
    guard(lambda: org.remove_member(db, acc(request, db), team, user_id))
    return {"ok": True}


# ------------------------------------------------------------------ usuários
class UserBody(BaseModel):
    email: str = ""
    name: str = ""
    org_role: str = "member"
    username: str | None = None  # com senha: conta local
    password: str | None = None


class UserPatch(BaseModel):
    org_role: str | None = None
    active: bool | None = None
    name: str | None = None
    username: str | None = None
    password: str | None = None  # redefine (e encerra as sessões da pessoa)
    email: str | None = None


@router.get("/users")
def users(request: Request, db=Depends(db_dep)):
    return guard(lambda: org.list_users(db, acc(request, db)))


@router.post("/users")
def create_user(body: UserBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: org.user_dict(db, org.create_user(db, acc(request, db), body.email, body.name, body.org_role,
                                                           body.username, body.password)))


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, request: Request, db=Depends(db_dep)):
    return guard(lambda: org.user_dict(db, org.update_user(db, acc(request, db), user_id, body.org_role, body.active,
                                                           body.name, body.username, body.password, body.email)))


# ------------------------------------------------------------------ acesso a agentes e aprovações
class ReasonBody(BaseModel):
    reason: str = ""


class NoteBody(BaseModel):
    note: str = ""


class AgentAccessBody(BaseModel):
    visibility: str | None = None
    expose_spec: bool | None = None
    team: str | None = None


@router.get("/approvals")
def approvals(request: Request, db=Depends(db_dep)):
    return org.approvals(db, acc(request, db))


@router.post("/agents/{slug}/access-requests")
def request_access(slug: str, body: ReasonBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: org.request_access(db, acc(request, db), slug, body.reason))


@router.get("/agents/{slug}/grants")
def grants(slug: str, request: Request, db=Depends(db_dep)):
    return guard(lambda: org.agent_grants(db, acc(request, db), slug))


@router.patch("/agents/{slug}/access")
def agent_access(slug: str, body: AgentAccessBody, request: Request, db=Depends(db_dep)):
    def go():
        a = acc(request, db)
        agent = org.set_agent_access(db, a, slug, body.visibility, body.expose_spec, body.team)
        return {"slug": agent.slug, "visibility": agent.visibility, "expose_spec": agent.expose_spec,
                "team_id": agent.team_id}
    return guard(go)


@router.post("/access-requests/{rid}/{decision}")
def decide_access(rid: int, decision: str, request: Request, db=Depends(db_dep)):
    a = acc(request, db)
    if decision == "revoke":
        return guard(lambda: org.revoke_access(db, a, rid))
    if decision not in ("approve", "reject"):
        raise HTTPException(404, "use approve, reject ou revoke")
    return guard(lambda: org.decide_access(db, a, rid, decision == "approve"))


@router.post("/promotions/{rid}/{decision}")
def decide_promotion(rid: int, decision: str, body: NoteBody, request: Request, db=Depends(db_dep)):
    if decision not in ("approve", "reject"):
        raise HTTPException(404, "use approve ou reject")
    return guard(lambda: org.decide_promotion(db, acc(request, db), rid, decision == "approve", body.note))


# ------------------------------------------------------------------ SSO (OAuth2) e SCIM — só admin
class ProviderBody(BaseModel):
    enabled: bool = True
    client_id: str = ""
    client_secret: str = ""  # vazio mantém o atual
    settings: dict = {}


class MappingBody(BaseModel):
    provider: str
    external_group: str
    team: str
    role: str = "consumer"


@router.get("/sso", dependencies=[Depends(require_admin)])
def sso_config(db=Depends(db_dep)):
    return {"providers": sso.admin_view(db), "mappings": sso.mappings(db),
            "scim_url": f"{config.PUBLIC_BASE_URL}/scim/v2",
            "bootstrap_admins": sorted(config.BOOTSTRAP_ADMIN_EMAILS)}


@router.put("/sso/{provider}", dependencies=[Depends(require_admin)])
def sso_save(provider: str, body: ProviderBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: sso.save_provider(db, provider, body.enabled, body.client_id, body.client_secret,
                                           body.settings, actor(request)))


@router.post("/sso/mappings", dependencies=[Depends(require_admin)])
def sso_add_mapping(body: MappingBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: sso.add_mapping(db, body.provider, body.external_group, org.find_team(db, body.team).id,
                                         body.role, actor(request)))


@router.delete("/sso/mappings/{mid}", dependencies=[Depends(require_admin)])
def sso_delete_mapping(mid: int, request: Request, db=Depends(db_dep)):
    guard(lambda: sso.delete_mapping(db, mid, actor(request)))
    return {"ok": True}


__all__ = ["router", "principal"]
