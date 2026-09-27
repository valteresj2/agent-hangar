from app import auth

from .conftest import ADMIN


def test_health_is_open(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["version"]


def test_admin_api_requires_token(client):
    assert client.get("/api/agents").status_code == 401
    assert client.get("/api/agents", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/agents", headers=ADMIN).status_code == 200


def test_mcp_requires_token(client):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    hdr = {"Accept": "application/json, text/event-stream"}
    assert client.post("/mcp", json=body, headers=hdr).status_code == 401
    r = client.post("/mcp", json=body, headers={**hdr, **ADMIN})
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert {"register_agent", "design_agent", "ship_agent", "apply_template", "create_consumer_key",
            "rollback_agent", "get_spec_schema"} <= names


def test_invoke_key_scopes(client, uniq):
    slug = client.post("/api/agents", headers=ADMIN,
                       json={"name": uniq("Scoped"), "objective": "o", "final_output": "f"}).json()["slug"]
    r = client.post("/api/keys", headers=ADMIN, json={"name": "librechat", "scopes": ["invoke"], "agents": [slug]})
    assert r.status_code == 200
    key = r.json()["key"]
    assert key.startswith("ah_")
    h = {"Authorization": f"Bearer {key}"}
    assert client.get("/api/agents", headers=h).status_code == 403            # não é admin
    assert client.post("/gw/outro-agente/a2a", headers=h, json={}).status_code == 403
    assert client.post(f"/gw/{slug}/a2a", headers=h, json={}).status_code == 503  # permitido; não está no ar
    # X-API-Key também vale
    assert client.post(f"/gw/{slug}/a2a", headers={"X-API-Key": key}, json={}).status_code == 503

    kid = r.json()["id"]
    assert client.delete(f"/api/keys/{kid}", headers=ADMIN).status_code == 200
    assert client.post(f"/gw/{slug}/a2a", headers=h, json={}).status_code == 401


def test_key_list_never_shows_secret(client):
    r = client.post("/api/keys", headers=ADMIN, json={"name": "ci", "scopes": ["admin"]})
    raw = r.json()["key"]
    listing = client.get("/api/keys", headers=ADMIN).text
    assert raw not in listing and r.json()["prefix"] in listing


def test_bad_scope_rejected(client):
    assert client.post("/api/keys", headers=ADMIN, json={"name": "x", "scopes": ["root"]}).status_code == 400


def test_internal_token_is_per_agent(client, uniq):
    a = client.post("/api/agents", headers=ADMIN,
                    json={"name": uniq("Orq"), "objective": "o", "final_output": "f"}).json()["slug"]
    b = client.post("/api/agents", headers=ADMIN,
                    json={"name": uniq("Sub"), "objective": "o", "final_output": "f"}).json()["slug"]
    # sem credencial / token de outro agente / admin token: todos recusados
    assert client.post(f"/internal/gw/{b}/a2a", json={}).status_code == 401
    forged = {"X-Agent-Slug": a, "Authorization": f"Bearer {auth.agent_token(b)}"}
    assert client.post(f"/internal/gw/{b}/a2a", headers=forged, json={}).status_code == 401
    assert client.post(f"/internal/gw/{b}/a2a", headers={**ADMIN, "X-Agent-Slug": a}, json={}).status_code == 401
    # token certo, mas b não é sub_agent de a
    own = {"X-Agent-Slug": a, "Authorization": f"Bearer {auth.agent_token(a)}"}
    assert client.post(f"/internal/gw/{b}/a2a", headers=own, json={}).status_code == 403
    client.patch(f"/api/agents/{a}", headers=ADMIN, json={"sub_agents": [b]})
    assert client.post(f"/internal/gw/{b}/a2a", headers=own, json={}).status_code == 503  # autorizado
    # dashboard só com a tool platform_dashboard
    assert client.get("/internal/dashboard/overview", headers=own).status_code == 403


def test_patch_spec_and_rollback_api(client, uniq):
    slug = client.post("/api/agents", headers=ADMIN,
                       json={"name": uniq("Api"), "objective": "o", "final_output": "f"}).json()["slug"]
    r = client.patch(f"/api/agents/{slug}", headers=ADMIN, json={"instructions": "a"})
    assert r.json()["version"] == 2
    r = client.put(f"/api/agents/{slug}/spec", headers=ADMIN, json={"instructions": "b"})
    assert r.json()["version"] == 3
    r = client.put(f"/api/agents/{slug}/spec", headers=ADMIN, json={"bogus": 1})
    assert r.status_code == 400 and "bogus" in r.json()["detail"]
    r = client.post(f"/api/agents/{slug}/rollback", headers=ADMIN, json={"version": 2})
    assert r.json()["spec"]["instructions"] == "a"


def test_templates_endpoint(client):
    r = client.get("/api/templates", headers=ADMIN)
    assert any(t["id"] == "doc-qa" for t in r.json())
