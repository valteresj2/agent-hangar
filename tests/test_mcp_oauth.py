"""OAuth 2.1 do MCP (Claude.ai, ChatGPT…): descoberta, registro dinâmico, consentimento no portal, PKCE, tokens
curtos com refresh rotativo e detecção de reuso, revogação pela pessoa e pelo admin; e o estado compartilhado
entre réplicas (códigos de uso único, contadores)."""
import base64
import hashlib
import secrets
import urllib.parse

import pytest

from app import auth, config, shared

from .conftest import ADMIN

MCP_HDR = {"Accept": "application/json, text/event-stream"}
LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
CB = "https://claude.ai/api/mcp/auth_callback"


def pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


@pytest.fixture()
def person(client, uniq):
    name = uniq("ana").lower()
    pw = "-".join(["Senha", "Boa", "123"])
    u = client.post("/api/users", headers=ADMIN, json={"username": name, "password": pw}).json()
    yield name, pw, u
    client.cookies.clear()


def _login(client, name, pw):
    client.cookies.clear()
    assert client.post("/api/auth/password", json={"username": name, "password": pw}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get(auth.CSRF_COOKIE)}


def _register(client, uris=(CB,), name="Claude"):
    return client.post("/oauth/register", json={"client_name": name, "redirect_uris": list(uris),
                                                "token_endpoint_auth_method": "none",
                                                "grant_types": ["authorization_code", "refresh_token"]})


def _authorize(client, person, client_id):
    """Fluxo completo até o código: /oauth/authorize -> portal (logado) -> consentimento -> redirect com code."""
    verifier, challenge = pkce()
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": CB, "state": "st-1",
         "code_challenge": challenge, "code_challenge_method": "S256", "resource": f"{config.PUBLIC_BASE_URL}/mcp"}
    r = client.get("/oauth/authorize", params=q, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("/app/#/oauth?")
    params = dict(urllib.parse.parse_qsl(r.headers["location"].split("?", 1)[1]))
    csrf = _login(client, person[0], person[1])
    info = client.get("/api/oauth/consent", params=params).json()
    assert info["client_name"] == "Claude" and info["redirect_host"] == "claude.ai"
    r = client.post("/api/oauth/consent", headers=csrf, json={"params": params, "approve": True})
    assert r.status_code == 200, r.text
    back = urllib.parse.urlsplit(r.json()["redirect"])
    got = dict(urllib.parse.parse_qsl(back.query))
    assert f"{back.scheme}://{back.netloc}{back.path}" == CB and got["state"] == "st-1" and got["iss"] == config.PUBLIC_BASE_URL
    client.cookies.clear()
    return got["code"], verifier


def _exchange(client, client_id, code, verifier):
    return client.post("/oauth/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": CB,
                                             "client_id": client_id, "code_verifier": verifier})


def test_discovery(client):
    r = client.post("/mcp", json=LIST, headers=MCP_HDR)
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == \
        f'Bearer resource_metadata="{config.PUBLIC_BASE_URL}/.well-known/oauth-protected-resource/mcp"'
    pr = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert pr["resource"] == f"{config.PUBLIC_BASE_URL}/mcp" and pr["authorization_servers"] == [config.PUBLIC_BASE_URL]
    md = client.get("/.well-known/oauth-authorization-server").json()
    assert md["code_challenge_methods_supported"] == ["S256"] and md["registration_endpoint"].endswith("/oauth/register")
    pre = client.options("/oauth/token", headers={"Origin": "https://inspector.local", "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == "*"
    assert client.get("/.well-known/oauth-authorization-server").headers["access-control-allow-origin"] == "*"


def test_registration_only_to_allowed_redirects(client):
    bad = _register(client, ["https://evil.example.com/cb"])
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_redirect_uri"
    assert _register(client, ["http://claude.ai/cb"]).status_code == 400            # https obrigatório fora do localhost
    assert _register(client, ["https://claude.ai.evil.com/cb"]).status_code == 400   # sufixo falso
    ok = _register(client, [CB, "http://127.0.0.1:33418/callback"])
    assert ok.status_code == 201 and ok.json()["client_id"].startswith("mcp_") and ok.json()["token_endpoint_auth_method"] == "none"
    assert _register(client, ["https://chatgpt.com/connector_platform_oauth_redirect"], "ChatGPT").status_code == 201


def test_authorize_rejects_bad_requests(client):
    cid = _register(client).json()["client_id"]
    r = client.get("/oauth/authorize", params={"response_type": "code", "client_id": "mcp_nope", "redirect_uri": CB},
                   follow_redirects=False)
    assert r.status_code == 400 and "text/html" in r.headers["content-type"]  # nunca redireciona para app desconhecido
    r = client.get("/oauth/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": "https://claude.ai/x"},
                   follow_redirects=False)
    assert r.status_code == 400  # redirect diferente do registrado
    r = client.get("/oauth/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": CB, "state": "s"},
                   follow_redirects=False)  # sem PKCE: o erro volta para o app
    assert r.status_code == 302 and "error=invalid_request" in r.headers["location"] and r.headers["location"].startswith(CB)


def test_full_flow_tokens_refresh_and_reuse(client, person):
    cid = _register(client).json()["client_id"]
    code, verifier = _authorize(client, person, cid)
    assert _exchange(client, cid, code, "x" * 50).json()["error"] == "invalid_grant"  # verifier errado
    tok = _exchange(client, cid, code, verifier)
    assert tok.status_code == 200 and tok.headers["cache-control"] == "no-store"
    t = tok.json()
    assert t["access_token"].startswith("aho_") and t["refresh_token"].startswith("ahr_") and t["expires_in"] == 3600
    assert _exchange(client, cid, code, verifier).json()["error"] == "invalid_grant"  # código de uso único

    bearer = {"Authorization": f"Bearer {t['access_token']}"}
    r = client.post("/mcp", json=LIST, headers={**MCP_HDR, **bearer})
    assert r.status_code == 200 and r.json()["result"]["tools"]
    assert client.get("/api/agents", headers=bearer).status_code == 403  # o token OAuth só vale no /mcp

    # refresh rotativo: o novo par funciona; reapresentar o refresh antigo derruba a autorização inteira
    r2 = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": t["refresh_token"], "client_id": cid}).json()
    assert r2["refresh_token"] != t["refresh_token"]
    auth.clear_cache()
    assert client.post("/mcp", json=LIST, headers={**MCP_HDR, **bearer}).status_code == 401  # access antigo trocado
    b2 = {"Authorization": f"Bearer {r2['access_token']}"}
    assert client.post("/mcp", json=LIST, headers={**MCP_HDR, **b2}).status_code == 200
    reuse = client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": t["refresh_token"]})
    assert reuse.json()["error"] == "invalid_grant"
    assert client.post("/mcp", json=LIST, headers={**MCP_HDR, **b2}).status_code == 401
    assert client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": r2["refresh_token"]}).status_code == 400


def test_person_and_admin_revoke(client, person):
    cid = _register(client).json()["client_id"]
    code, verifier = _authorize(client, person, cid)
    t = _exchange(client, cid, code, verifier).json()
    bearer = {**MCP_HDR, "Authorization": f"Bearer {t['access_token']}"}
    csrf = _login(client, person[0], person[1])
    apps = client.get("/api/me/oauth").json()
    assert len(apps) == 1 and apps[0]["client_name"] == "Claude" and not apps[0]["revoked"]
    assert client.delete(f"/api/me/oauth/{apps[0]['id']}", headers=csrf).status_code == 200
    client.cookies.clear()
    assert client.post("/mcp", json=LIST, headers=bearer).status_code == 401

    # admin bloqueia o app: todas as autorizações dele caem e ele não consegue mais pedir acesso
    code, verifier = _authorize(client, person, cid)
    t = _exchange(client, cid, code, verifier).json()
    listed = {c["id"]: c for c in client.get("/api/oauth/clients", headers=ADMIN).json()}
    assert listed[cid]["active_grants"] == 1
    assert client.delete(f"/api/oauth/clients/{cid}", headers=ADMIN).status_code == 200
    assert client.post("/mcp", json=LIST, headers={**MCP_HDR, "Authorization": f"Bearer {t['access_token']}"}).status_code == 401
    r = client.get("/oauth/authorize", params={"response_type": "code", "client_id": cid, "redirect_uri": CB}, follow_redirects=False)
    assert r.status_code == 400


def test_deactivated_person_loses_apps(client, person):
    cid = _register(client).json()["client_id"]
    code, verifier = _authorize(client, person, cid)
    t = _exchange(client, cid, code, verifier).json()
    client.patch(f"/api/users/{person[2]['id']}", headers=ADMIN, json={"active": False})
    assert client.post("/mcp", json=LIST, headers={**MCP_HDR, "Authorization": f"Bearer {t['access_token']}"}).status_code == 401
    assert client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": t["refresh_token"]}).status_code == 400


def test_disabled(client, monkeypatch):
    monkeypatch.setattr(config, "OAUTH_ENABLED", False)
    assert _register(client).status_code == 403
    assert "www-authenticate" not in client.post("/mcp", json=LIST, headers=MCP_HDR).headers


def test_shared_state_primitives(uniq):
    k = uniq("code")
    assert shared.take_once(k, 60) and not shared.take_once(k, 60)
    shared.put(k + "-v", {"a": 1}, 60)
    assert shared.get(k + "-v") == {"a": 1}
    shared.put(k + "-old", {"a": 1}, -1)
    assert shared.get(k + "-old") is None and shared.take_once(k + "-old", 60)  # vencido: pode reservar de novo
    assert shared.hits(k + "-h", 60) == 0
    assert shared.hits(k + "-h", 60, add=True) == 1 and shared.hits(k + "-h", 60, add=True) == 2
    shared.sweep()
    with shared.cluster_lock("teste"):
        pass
