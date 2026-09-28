"""Login OAuth2 (Google, Microsoft Entra ID, GitHub) com os provedores simulados, e provisionamento SCIM 2.0."""
import urllib.parse

import httpx
import pytest

from app import config, sso

from .conftest import ADMIN


class FakeIdP:
    """Responde token + perfil como os provedores reais; `profiles[provider]` é o perfil devolvido."""

    def __init__(self):
        self.profiles = {}
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls.append((request.method, url))
        if request.method == "POST":
            body = urllib.parse.parse_qs(request.content.decode())
            assert body["code_verifier"][0] and body["client_secret"][0] == "segredo"
            return httpx.Response(200, json={"access_token": "at-" + body["code"][0], "token_type": "bearer"})
        p = self.profiles
        if "googleapis.com/oauth2/v3/userinfo" in url:
            return httpx.Response(200, json=p["google"])
        if "graph.microsoft.com/v1.0/me/memberOf" in url:
            return httpx.Response(200, json={"value": [{"id": g, "displayName": g} for g in p["ms_groups"]]})
        if "graph.microsoft.com/v1.0/me" in url:
            return httpx.Response(200, json=p["microsoft"])
        if url.endswith("api.github.com/user"):
            return httpx.Response(200, json=p["github"])
        if url.endswith("/user/emails"):
            return httpx.Response(200, json=p["gh_emails"])
        if "/user/memberships/orgs/" in url:
            org = url.rsplit("/", 1)[1]
            return httpx.Response(200 if org in p["gh_orgs"] else 404, json={"state": "active"})
        if "/user/teams" in url:
            return httpx.Response(200, json=[{"slug": t.split("/")[1], "organization": {"login": t.split("/")[0]}}
                                             for t in p.get("gh_teams", [])])
        return httpx.Response(404, json={})


@pytest.fixture()
def idp(monkeypatch, client):
    fake = FakeIdP()
    monkeypatch.setattr(sso, "HTTP", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler)))
    yield fake
    client.cookies.clear()


def _configure(client, provider, **settings):
    r = client.put(f"/api/sso/{provider}", headers=ADMIN,
                   json={"enabled": True, "client_id": f"{provider}-id", "client_secret": "segredo", "settings": settings})
    assert r.status_code == 200, r.text
    return r.json()


def _login(client, provider, code="c1"):
    """Faz o vai-e-volta do navegador: /login → provedor → /callback. Devolve a resposta do callback."""
    r = client.get(f"/api/auth/login/{provider}", params={"next": "#/agents"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    q = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["redirect_uri"][0].endswith(f"/api/auth/callback/{provider}")
    return client.get(f"/api/auth/callback/{provider}", params={"code": code, "state": q["state"][0]},
                      follow_redirects=False)


def test_google_login_creates_user_and_session(client, idp, uniq, monkeypatch):
    email = f"{uniq('ana')}@acme.com"
    monkeypatch.setattr(config, "BOOTSTRAP_ADMIN_EMAILS", {email})
    _configure(client, "google", allowed_domains=["acme.com"])
    assert any(p["id"] == "google" for p in client.get("/api/auth/providers").json()["providers"])
    idp.profiles["google"] = {"sub": uniq("g"), "email": email, "email_verified": True, "name": "Ana", "hd": "acme.com"}
    r = _login(client, "google")
    assert r.status_code == 303 and r.headers["location"] == "/ui/#/agents"
    me = client.get("/api/me").json()  # cookie de sessão
    assert me["user"]["email"] == email and me["is_admin"]  # BOOTSTRAP_ADMIN_EMAILS


def test_google_rejects_other_domain_and_unverified(client, idp, uniq):
    _configure(client, "google", allowed_domains=["acme.com"])
    idp.profiles["google"] = {"sub": uniq("g"), "email": "x@gmail.com", "email_verified": True}
    r = _login(client, "google")
    assert "/ui/#/login?error=" in r.headers["location"] and "gmail.com" in urllib.parse.unquote(r.headers["location"])
    idp.profiles["google"] = {"sub": uniq("g"), "email": f"{uniq('u')}@acme.com", "email_verified": False}
    assert "error=" in _login(client, "google").headers["location"]


def test_tampered_state_is_rejected(client, idp):
    _configure(client, "google", allowed_domains=["acme.com"])
    client.get("/api/auth/login/google", follow_redirects=False)
    r = client.get("/api/auth/callback/google", params={"code": "x", "state": "forjado"}, follow_redirects=False)
    assert "error=" in r.headers["location"]


def test_microsoft_groups_map_to_teams(client, idp, uniq):
    team = client.post("/api/teams", headers=ADMIN, json={"name": uniq("Dados")}).json()["slug"]
    _configure(client, "microsoft", tenant="acme.onmicrosoft.com")
    client.post("/api/sso/mappings", headers=ADMIN, json={"provider": "microsoft", "external_group": "grp-dados",
                                                          "team": team, "role": "developer"})
    email = f"{uniq('bia')}@acme.com"
    idp.profiles.update(microsoft={"id": uniq("oid"), "displayName": "Bia", "mail": email}, ms_groups=["grp-dados"])
    assert _login(client, "microsoft").headers["location"] == "/ui/#/agents"
    teams = client.get("/api/me").json()["teams"]
    assert teams == [{"id": teams[0]["id"], "slug": team, "name": teams[0]["name"], "role": "developer",
                      "source": "sso:microsoft"}]
    # saiu do grupo no Entra: sai do time no próximo login
    idp.profiles["ms_groups"] = []
    client.cookies.clear()
    _login(client, "microsoft")
    assert client.get("/api/me").json()["teams"] == []
    # com mapeamentos, o login pede o escopo de grupos
    loc = client.get("/api/auth/login/microsoft", follow_redirects=False).headers["location"]
    assert "GroupMember.Read.All" in urllib.parse.unquote(loc) and "/acme.onmicrosoft.com/" in loc


def test_microsoft_requires_fixed_tenant(client):
    r = client.put("/api/sso/microsoft", headers=ADMIN, json={"client_id": "x", "client_secret": "y",
                                                              "settings": {"tenant": "common"}})
    assert r.status_code == 400


def test_github_requires_org_membership(client, idp, uniq):
    _configure(client, "github", orgs=["acme"])
    idp.profiles.update(github={"id": 1, "login": "caio", "name": "Caio"},
                        gh_emails=[{"email": f"{uniq('caio')}@acme.com", "primary": True, "verified": True}],
                        gh_orgs=[])
    assert "error=" in _login(client, "github").headers["location"]
    idp.profiles["gh_orgs"] = ["acme"]
    assert _login(client, "github").headers["location"] == "/ui/#/agents"


# ------------------------------------------------------------------ SCIM
@pytest.fixture()
def scim(client):
    key = client.post("/api/keys", headers=ADMIN, json={"name": "entra", "scopes": ["scim"]}).json()["key"]
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/scim+json"}


def test_scim_provisioning_and_deprovisioning(client, scim, uniq):
    email = f"{uniq('scim')}@acme.com"
    assert client.get("/api/agents", headers=scim).status_code == 403  # chave scim não entra na API
    assert client.get("/scim/v2/Users", headers=ADMIN | {"Authorization": "Bearer ah_invalida"}).status_code == 401
    r = client.post("/scim/v2/Users", headers=scim, json={"userName": email, "externalId": "ext-1",
                                                          "name": {"givenName": "Duda", "familyName": "S"},
                                                          "active": True})
    assert r.status_code == 201
    uid = r.json()["id"]
    found = client.get("/scim/v2/Users", headers=scim, params={"filter": f'userName eq "{email}"'}).json()
    assert found["totalResults"] == 1 and found["Resources"][0]["name"]["formatted"] == "Duda S"
    assert client.post("/scim/v2/Users", headers=scim, json={"userName": email}).status_code == 409

    # grupo SCIM mapeado para um time: o usuário vira membro
    team = client.post("/api/teams", headers=ADMIN, json={"name": uniq("Vendas")}).json()["slug"]
    gname = uniq("grp-vendas")
    client.post("/api/sso/mappings", headers=ADMIN, json={"provider": "scim", "external_group": gname, "team": team,
                                                          "role": "consumer"})
    gid = client.post("/scim/v2/Groups", headers=scim, json={"displayName": gname,
                                                             "members": [{"value": uid}]}).json()["id"]
    members = client.get(f"/api/teams/{team}/members", headers=ADMIN).json()
    assert [m["email"] for m in members] == [email] and members[0]["source"] == "scim"
    client.patch(f"/scim/v2/Groups/{gid}", headers=scim, json={
        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
        "Operations": [{"op": "remove", "path": f'members[value eq "{uid}"]'}]})
    assert client.get(f"/api/teams/{team}/members", headers=ADMIN).json() == []

    # desligamento pelo diretório: sessão e chaves morrem
    from app import auth
    from app.db import SessionLocal
    from app.models import User
    with SessionLocal() as db:
        token = auth.create_session(db, db.get(User, int(uid)))
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    r = client.patch(f"/scim/v2/Users/{uid}", headers=scim, json={
        "Operations": [{"op": "Replace", "path": "active", "value": "False"}]})
    assert r.json()["active"] is False
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_scim_discovery(client, scim):
    assert client.get("/scim/v2/ServiceProviderConfig", headers=scim).json()["patch"]["supported"]
    assert client.get("/scim/v2/ResourceTypes", headers=scim).json()["totalResults"] == 2
