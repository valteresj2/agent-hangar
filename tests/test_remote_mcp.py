"""MCP remoto com OAuth: descoberta (RFC 9728/8414), DCR, PKCE, troca e renovação de tokens e o proxy interno
(só agentes com o MCP na spec; o token do provedor nunca chega ao agente)."""
import base64
import hashlib
import json
import urllib.parse
from datetime import timedelta

import httpx
import pytest

from app import auth
from app import services as svc
from app.db import SessionLocal
from app.models import RemoteMcp, now

from .conftest import ADMIN

MCP = "http://ap.test/mcp"


class FakeProvider:
    """Servidor MCP + servidor de autorização, como o Activepieces responde."""

    def __init__(self):
        self.codes, self.issued, self.mcp_auth = {}, 0, []

    def handler(self, req: httpx.Request) -> httpx.Response:
        url, path = str(req.url), req.url.path
        if path == "/mcp":
            authz = req.headers.get("authorization", "")
            if not authz.startswith("Bearer at-"):
                return httpx.Response(401, headers={"WWW-Authenticate": 'Bearer resource_metadata="http://ap.test/.well-known/oauth-protected-resource/mcp"'})
            self.mcp_auth.append(authz)
            body = json.loads(req.content or b"{}")
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body.get("id"), "result": {"tools": [{"name": "ap_run_action"}]}},
                                  headers={"mcp-session-id": "s1"})
        if path == "/.well-known/oauth-protected-resource/mcp":
            return httpx.Response(200, json={"resource": MCP, "authorization_servers": ["http://ap.test"],
                                             "scopes_supported": ["mcp", "openid"]})
        if path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={"authorization_endpoint": "http://ap.test/authorize", "token_endpoint": "http://ap.test/token",
                                             "registration_endpoint": "http://ap.test/register", "code_challenge_methods_supported": ["S256"]})
        if path == "/register":
            assert json.loads(req.content)["token_endpoint_auth_method"] == "none"
            return httpx.Response(201, json={"client_id": "cli-1"})
        if path == "/token":
            form = urllib.parse.parse_qs(req.content.decode())
            assert form["resource"] == [MCP] and form["client_id"] == ["cli-1"]
            if form["grant_type"] == ["authorization_code"]:
                challenge = self.codes[form["code"][0]]
                verifier = form["code_verifier"][0]
                assert base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=") == challenge
            else:
                assert form["refresh_token"][0].startswith("rt-")
            self.issued += 1
            return httpx.Response(200, json={"access_token": f"at-{self.issued}", "refresh_token": f"rt-{self.issued}",
                                             "expires_in": 900, "token_type": "Bearer"})
        return httpx.Response(404, text=url)


@pytest.fixture()
def provider(monkeypatch, client):
    p = FakeProvider()
    monkeypatch.setattr(svc.remote_mcp, "HTTP", lambda: httpx.Client(transport=httpx.MockTransport(p.handler)))
    yield p
    client.cookies.clear()
    with SessionLocal() as db:
        db.query(RemoteMcp).delete()
        db.commit()


def _connect(client, provider, name="ap"):
    r = client.post("/api/remote-mcps", headers=ADMIN, json={"name": name, "url": MCP, "browser_base": "http://localhost:8098"})
    assert r.status_code == 200, r.text
    authz = r.json()["authorize_url"]
    assert authz.startswith("http://localhost:8098/authorize?")  # tela de autorização na origem pública
    q = urllib.parse.parse_qs(urllib.parse.urlparse(authz).query)
    assert q["code_challenge_method"] == ["S256"] and q["resource"] == [MCP] and q["redirect_uri"][0].endswith("/api/remote-mcps/callback")
    provider.codes["code-1"] = q["code_challenge"][0]
    cb = client.get("/api/remote-mcps/callback", headers=ADMIN, params={"code": "code-1", "state": q["state"][0]}, follow_redirects=False)
    assert cb.status_code == 303 and "remote_ok=" + name in cb.headers["location"], cb.headers.get("location")


def test_connect_and_catalog_entry(client, provider):
    _connect(client, provider)
    r = client.get("/api/remote-mcps", headers=ADMIN).json()[0]
    assert r["status"] == "connected" and r["has_refresh_token"]
    with SessionLocal() as db:  # tokens só criptografados no banco
        row = db.query(RemoteMcp).filter_by(name="ap").one()
        assert row.access_token.startswith("enc:") and "at-1" not in row.access_token
    item = next(m for m in client.get("/api/catalog", headers=ADMIN).json()["mcp_servers"] if m["name"] == "ap")
    assert item["url"].endswith("/internal/mcp-remote/ap")


def test_state_mismatch_is_rejected(client, provider):
    r = client.post("/api/remote-mcps", headers=ADMIN, json={"name": "ap", "url": MCP})
    cb = client.get("/api/remote-mcps/callback", headers=ADMIN, params={"code": "x", "state": "forjado"}, follow_redirects=False)
    assert "remote_error=" in cb.headers["location"] and r.status_code == 200


def test_token_refresh(client, provider):
    _connect(client, provider)
    with SessionLocal() as db:
        db.query(RemoteMcp).filter_by(name="ap").one().expires_at = now() - timedelta(minutes=1)
        db.commit()
        _, tok = svc.remote_mcp.token(db, "ap")
    assert tok == "at-2" and provider.issued == 2  # renovou com o refresh token


def test_proxy_forwards_with_provider_token_only_for_allowed_agents(client, provider, monkeypatch, uniq):
    _connect(client, provider)
    from app.routers import remote_mcp as router_mod
    real = httpx.AsyncClient
    monkeypatch.setattr(router_mod.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(provider.handler)))
    ok = client.post("/api/agents", headers=ADMIN, json={"name": uniq("Com AP"), "objective": "o", "final_output": "f"}).json()["slug"]
    client.patch(f"/api/agents/{ok}", headers=ADMIN, json={"mcps": ["ap"]})
    no = client.post("/api/agents", headers=ADMIN, json={"name": uniq("Sem AP"), "objective": "o", "final_output": "f"}).json()["slug"]
    call = {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}
    h = lambda slug: {"X-Agent-Slug": slug, "Authorization": f"Bearer {auth.agent_token(slug)}"}  # noqa: E731
    r = client.post("/internal/mcp-remote/ap", headers=h(ok), json=call)
    assert r.status_code == 200 and r.json()["result"]["tools"][0]["name"] == "ap_run_action"
    assert r.headers["mcp-session-id"] == "s1" and provider.mcp_auth[-1] == "Bearer at-1"
    assert client.post("/internal/mcp-remote/ap", headers=h(no), json=call).status_code == 403
    assert client.post("/internal/mcp-remote/ap", headers={"X-Agent-Slug": ok, "Authorization": "Bearer x"}, json=call).status_code == 401
    assert client.post("/internal/mcp-remote/ap", headers=ADMIN, json=call).status_code == 401  # admin token não é token de agente


def test_only_admin_and_remove(client, provider, uniq):
    _connect(client, provider)
    team = client.post("/api/teams", headers=ADMIN, json={"name": uniq("T")}).json()["slug"]
    email = f"{uniq('m')}@acme.com"
    client.post(f"/api/teams/{team}/members", headers=ADMIN, json={"email": email, "role": "maintainer"})
    from .test_access import _session
    assert client.get("/api/remote-mcps", headers=_session(email)).status_code == 403
    assert client.delete("/api/remote-mcps/ap", headers=ADMIN).status_code == 200
    assert all(m["name"] != "ap" for m in client.get("/api/catalog", headers=ADMIN).json()["mcp_servers"])
