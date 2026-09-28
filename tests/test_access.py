"""Times, papéis, visibilidade, pedidos de acesso, aprovação de produção (quatro olhos), chaves com dono,
orçamento e sessão da UI (cookie + CSRF)."""
import pytest

from app import auth
from app import services as svc
from app.db import SessionLocal
from app.models import TestRun, User

from .conftest import ADMIN


def _session(email: str) -> dict:
    """Header com o token de sessão do usuário (o mesmo que o login OAuth2 abre)."""
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        return {"Authorization": f"Bearer {auth.create_session(db, u)}"}


@pytest.fixture()
def org_setup(client, uniq):
    """Time A (maint, dev, cons) e time B (out); auditor sem time."""
    n = uniq("t")
    ta = client.post("/api/teams", headers=ADMIN, json={"name": f"Time A {n}"}).json()["slug"]
    tb = client.post("/api/teams", headers=ADMIN, json={"name": f"Time B {n}"}).json()["slug"]
    emails = {k: f"{k}-{n}@acme.com" for k in ("maint", "dev", "cons", "out", "aud")}
    for k, role in (("maint", "maintainer"), ("dev", "developer"), ("cons", "consumer")):
        assert client.post(f"/api/teams/{ta}/members", headers=ADMIN,
                           json={"email": emails[k], "role": role}).status_code == 200
    client.post(f"/api/teams/{tb}/members", headers=ADMIN, json={"email": emails["out"], "role": "developer"})
    client.post("/api/users", headers=ADMIN, json={"email": emails["aud"], "org_role": "auditor"})
    h = {k: _session(e) for k, e in emails.items()}
    slug = client.post("/api/agents", headers=h["dev"], json={"name": uniq("Agente A"), "objective": "o",
                                                               "final_output": "f"}).json()["slug"]
    client.patch(f"/api/agents/{slug}", headers=h["dev"], json={"instructions": "segredo do time A"})
    return {"ta": ta, "tb": tb, "h": h, "emails": emails, "slug": slug}


def test_roles_and_visibility(client, org_setup):
    s, h, slug = org_setup, org_setup["h"], org_setup["slug"]
    me = client.get("/api/me", headers=h["dev"]).json()
    assert me["can_create_agents"] and me["teams"][0]["slug"] == s["ta"]

    # agente novo vai para o time de quem criou, com visibilidade "org"
    d = client.get(f"/api/agents/{slug}", headers=h["dev"]).json()
    assert d["team"]["slug"] == s["ta"] and d["visibility"] == "org" and d["access"] == "developer"
    assert d["spec"]["instructions"] == "segredo do time A"

    # outro time: vê no catálogo, sem a spec, e pode pedir acesso
    out = client.get(f"/api/agents/{slug}", headers=h["out"]).json()
    assert out["access"] == "viewer" and out["spec"] is None and "request_access" in out["permissions"]
    assert any(a["slug"] == slug and a["access"] == "viewer" for a in client.get("/api/agents", headers=h["out"]).json())
    assert client.patch(f"/api/agents/{slug}", headers=h["out"], json={"instructions": "x"}).status_code == 403

    # consumer: usa, mas não edita nem vê instruções
    c = client.get(f"/api/agents/{slug}", headers=h["cons"]).json()
    assert "consume" in c["permissions"] and "edit" not in c["permissions"] and c["spec"] is None
    assert client.patch(f"/api/agents/{slug}", headers=h["cons"], json={"instructions": "x"}).status_code == 403
    assert client.post("/api/agents", headers=h["cons"],
                       json={"name": "x", "objective": "o", "final_output": "f"}).status_code == 403

    # auditor lê tudo; expose_spec abre as instruções para os outros times
    assert client.get(f"/api/agents/{slug}", headers=h["aud"]).json()["spec"]["instructions"]
    assert client.patch(f"/api/agents/{slug}/access", headers=h["dev"], json={"expose_spec": True}).status_code == 403
    assert client.patch(f"/api/agents/{slug}/access", headers=h["maint"], json={"expose_spec": True}).status_code == 200
    assert client.get(f"/api/agents/{slug}", headers=h["out"]).json()["spec"]["instructions"]

    # privado: some para os outros times
    client.patch(f"/api/agents/{slug}/access", headers=h["maint"], json={"visibility": "private"})
    assert client.get(f"/api/agents/{slug}", headers=h["out"]).status_code == 403
    assert all(a["slug"] != slug for a in client.get("/api/agents", headers=h["out"]).json())


def test_admin_only_areas(client, org_setup):
    h = org_setup["h"]["dev"]
    assert client.post("/api/catalog/skills", headers=h, json={"name": "x"}).status_code == 403
    assert client.get("/api/audit", headers=h).status_code == 403
    assert client.get("/api/users", headers=h).status_code == 403
    assert client.get("/api/sso", headers=h).status_code == 403
    assert client.post("/api/keys", headers=h, json={"name": "x", "scopes": ["admin"]}).status_code == 403
    assert client.post("/api/teams", headers=h, json={"name": "x"}).status_code == 403
    assert client.get("/api/audit", headers=org_setup["h"]["aud"]).status_code == 200


def test_access_request_grant_and_revoke(client, org_setup):
    h, slug = org_setup["h"], org_setup["slug"]
    assert client.post(f"/api/agents/{slug}/connections", headers=h["out"], json={"client": "claude-code"}).status_code == 403
    r = client.post(f"/api/agents/{slug}/access-requests", headers=h["out"], json={"reason": "análise"}).json()
    todo = client.get("/api/approvals", headers=h["maint"]).json()["to_decide"]
    assert any(x["kind"] == "access" and x["id"] == r["id"] for x in todo)
    assert client.post(f"/api/access-requests/{r['id']}/approve", headers=h["dev"]).status_code == 403
    assert client.post(f"/api/access-requests/{r['id']}/approve", headers=h["maint"]).json()["status"] == "approved"

    conn = client.post(f"/api/agents/{slug}/connections", headers=h["out"], json={"client": "claude-code"}).json()
    key = {"Authorization": f"Bearer {conn['key']}"}
    assert client.post(f"/gw/{slug}/mcp", headers=key, json={}).status_code == 503  # permitido; não está no ar
    # o mantenedor vê a conexão de outra pessoa; o dono só as próprias
    assert any(c["id"] == conn["connection"]["id"] for c in client.get(f"/api/agents/{slug}/connections", headers=h["maint"]).json())

    client.post(f"/api/access-requests/{r['id']}/revoke", headers=h["maint"])
    assert client.post(f"/gw/{slug}/mcp", headers=key, json={}).status_code == 401  # chave morreu junto


def test_member_removal_and_deactivation_revoke_keys(client, org_setup):
    s, h, slug = org_setup, org_setup["h"], org_setup["slug"]
    k1 = client.post(f"/api/agents/{slug}/connections", headers=h["cons"], json={"client": "librechat", "mode": "model"}).json()["key"]
    assert client.post(f"/gw/{slug}/v1/chat/completions", headers={"Authorization": f"Bearer {k1}"}, json={}).status_code == 503
    uid = client.get("/api/me", headers=h["cons"]).json()["user"]["id"]
    client.delete(f"/api/teams/{s['ta']}/members/{uid}", headers=h["maint"])
    assert client.post(f"/gw/{slug}/v1/chat/completions", headers={"Authorization": f"Bearer {k1}"}, json={}).status_code == 401

    pat = client.post("/api/keys", headers=h["dev"], json={"name": "cli", "scopes": ["user"]}).json()["key"]
    assert client.get("/api/me", headers={"Authorization": f"Bearer {pat}"}).json()["user"]["email"] == s["emails"]["dev"]
    dev_id = client.get("/api/me", headers=h["dev"]).json()["user"]["id"]
    assert client.patch(f"/api/users/{dev_id}", headers=ADMIN, json={"active": False}).status_code == 200
    assert client.get("/api/me", headers=h["dev"]).status_code == 401  # sessão encerrada
    assert client.get("/api/me", headers={"Authorization": f"Bearer {pat}"}).status_code == 401  # token pessoal morto


def _passed(slug):
    with SessionLocal() as db:
        a = svc.get_agent(db, slug)
        db.add(TestRun(agent_id=a.id, version=a.current_version, env="stage", status="passed", summary="ok"))
        db.commit()


def test_promotion_needs_four_eyes(client, org_setup):
    s, h, slug = org_setup, org_setup["h"], org_setup["slug"]
    _passed(slug)
    r = client.post(f"/api/agents/{slug}/deploy", headers=h["dev"], json={"env": "prod"}).json()
    assert r["status"] == "approval_pending"
    rid = r["request"]["id"]
    assert client.get(f"/api/agents/{slug}", headers=h["dev"]).json()["pending_promotion"]
    assert not client.get(f"/api/agents/{slug}", headers=h["out"]).json()["pending_promotion"]  # assunto do time
    # quem pediu não aprova; consumer não aprova; mantenedor aprova e o deploy acontece
    assert client.post(f"/api/promotions/{rid}/approve", headers=h["dev"], json={}).status_code == 403
    assert client.post(f"/api/promotions/{rid}/approve", headers=h["cons"], json={}).status_code == 403
    assert client.post(f"/api/promotions/{rid}/approve", headers=h["maint"], json={}).json()["status"] == "approved"
    assert client.get(f"/api/agents/{slug}", headers=h["dev"]).json()["prod"]

    # time com aprovação obrigatória: nem o mantenedor promove sozinho; admin libera o time
    client.patch(f"/api/agents/{slug}", headers=h["dev"], json={"instructions": "v nova"})
    _passed(slug)
    assert client.post(f"/api/agents/{slug}/deploy", headers=h["maint"], json={"env": "prod"}).json()["status"] == "approval_pending"
    assert client.patch(f"/api/teams/{s['ta']}", headers=h["maint"], json={"require_approval": False}).status_code == 403
    client.patch(f"/api/teams/{s['ta']}", headers=ADMIN, json={"require_approval": False})
    assert client.post(f"/api/agents/{slug}/deploy", headers=h["maint"], json={"env": "prod"}).json()["status"] == "running"


def test_stale_promotion_is_superseded(client, org_setup):
    h, slug = org_setup["h"], org_setup["slug"]
    _passed(slug)
    rid = client.post(f"/api/agents/{slug}/deploy", headers=h["dev"], json={"env": "prod"}).json()["request"]["id"]
    client.patch(f"/api/agents/{slug}", headers=h["dev"], json={"instructions": "mudou depois do pedido"})
    r = client.post(f"/api/promotions/{rid}/approve", headers=h["maint"], json={})
    assert r.status_code == 400 and "mudou" in r.json()["detail"]


def test_ship_by_developer_ends_in_approval(client, org_setup, uniq):
    h = org_setup["h"]
    slug = client.post("/api/agents", headers=h["dev"], json={"name": uniq("Harness"), "objective": "o",
                                                               "final_output": "f"}).json()["slug"]
    client.patch(f"/api/agents/{slug}", headers=h["dev"], json={"harness": {"id": "codex"},
                                                                "tests": [{"input": "faça", "expect_contains": "x"}]})
    steps = client.post(f"/api/agents/{slug}/ship", headers=h["dev"]).json()
    assert steps[-1]["step"] == "prod" and steps[-1]["status"] == "approval_pending"


def test_budget_blocks_gateway(client, org_setup):
    s, h, slug = org_setup, org_setup["h"], org_setup["slug"]
    client.patch(f"/api/agents/{slug}/access", headers=h["maint"], json={"visibility": "open"})
    _passed(slug)
    client.patch(f"/api/teams/{s['ta']}", headers=ADMIN, json={"require_approval": False, "budget_usd_month": 0.01,
                                                              "budget_enforce": True})
    client.post(f"/api/agents/{slug}/deploy", headers=h["maint"], json={"env": "prod"})
    with SessionLocal() as db:
        svc.record_usage(db, svc.get_agent(db, slug).id, "prod", "api", "openai", 10, True, cost=1.0)
    t = client.get(f"/api/teams/{s['ta']}", headers=h["maint"]).json()
    assert t["budget_state"] == "over" and t["spent_month"] >= 1
    r = client.post(f"/gw/{slug}/v1/chat/completions", headers=h["out"], json={"messages": []})
    assert r.status_code == 429  # "open": outro time usa direto, mas o orçamento do time acabou


def test_cookie_session_requires_csrf(client, org_setup):
    token = org_setup["h"]["dev"]["Authorization"].split()[1]
    try:
        client.cookies.set(auth.SESSION_COOKIE, token)
        client.cookies.set(auth.CSRF_COOKIE, "abc")
        assert client.get("/api/me").status_code == 200
        body = {"name": "x", "scopes": ["user"]}
        assert client.post("/api/keys", json=body).status_code == 403
        assert client.post("/api/keys", json=body, headers={"X-CSRF-Token": "abc"}).status_code == 200
    finally:
        client.cookies.clear()


def test_token_login_opens_session(client):
    try:
        r = client.post("/api/auth/token", json={"token": "test-admin-token"})
        assert r.status_code == 200 and auth.SESSION_COOKIE in r.cookies
        assert client.get("/api/me").json()["is_admin"]
        assert client.post("/api/auth/token", json={"token": "errado"}).status_code == 401
    finally:
        client.cookies.clear()


def _mcp(client, headers, tool, args):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    r = client.post("/mcp", json=body, headers={"Accept": "application/json, text/event-stream", **headers})
    return r.json()["result"]


def test_mcp_acts_as_the_user(client, org_setup, uniq):
    h = org_setup["h"]
    pat = {"Authorization": "Bearer " + client.post("/api/keys", headers=h["dev"],
                                                    json={"name": "mcp", "scopes": ["user"]}).json()["key"]}
    assert "Time A" in str(_mcp(client, pat, "whoami", {}))
    assert _mcp(client, pat, "register_skill", {"name": "x", "description": "d", "content": "c"})["isError"]
    r = _mcp(client, pat, "register_agent", {"name": uniq("Via MCP"), "objective": "o", "final_output": "f"})
    assert not r["isError"] and org_setup["ta"] in str(r)
    # consumer via MCP não cria agente
    cpat = {"Authorization": "Bearer " + client.post("/api/keys", headers=h["cons"],
                                                     json={"name": "mcp", "scopes": ["user"]}).json()["key"]}
    assert _mcp(client, cpat, "register_agent", {"name": "x", "objective": "o", "final_output": "f"})["isError"]


def test_admin_creates_many_teams_with_maintainer(client, uniq):
    names = [uniq("Squad") for _ in range(3)]
    email = f"{uniq('lider')}@acme.com"
    slugs = [client.post("/api/teams", headers=ADMIN, json={"name": n, "maintainer": email}).json()["slug"] for n in names]
    listed = {t["slug"] for t in client.get("/api/teams", headers=ADMIN).json()}
    assert set(slugs) <= listed
    for s in slugs:
        members = client.get(f"/api/teams/{s}/members", headers=ADMIN).json()
        assert [(m["email"], m["role"]) for m in members] == [(email, "maintainer")]
    assert client.post("/api/teams", headers=ADMIN, json={"name": names[0]}).status_code == 400  # duplicado
    assert client.post("/api/teams", headers=ADMIN, json={"name": "New"}).status_code == 400  # reservado
    r = client.post("/api/teams", headers=ADMIN, json={"name": uniq("X"), "maintainer": "ninguem"})
    assert r.status_code == 400 and "não encontrado" in r.json()["detail"]
