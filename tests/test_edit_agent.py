"""Editar depois pelo MCP: ver a spec, editar em stage, testar, comparar versões e publicar (ou pedir aprovação)."""
import json

from .conftest import ADMIN
from .test_access import _session


def _mcp(client, headers, tool, args):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    r = client.post("/mcp", json=body, headers={"Accept": "application/json, text/event-stream", **headers})
    res = r.json()["result"]
    text = res["content"][0]["text"] if res.get("content") else ""
    return res.get("isError", False), (json.loads(text) if text.startswith("{") else text)


def _harness_agent(client, headers, uniq):
    err, a = _mcp(client, headers, "register_agent", {"name": uniq("Editavel"), "objective": "o", "final_output": "f"})
    assert not err, a
    err, _ = _mcp(client, headers, "design_agent", {"slug": a["slug"], "harness": {"id": "codex"},
                                                     "tests": [{"input": "faça", "expect_contains": "x"}]})
    assert not err
    return a["slug"]


def test_edit_test_and_promote_as_admin(client, uniq):
    slug = _harness_agent(client, ADMIN, uniq)
    err, spec = _mcp(client, ADMIN, "get_agent_spec", {"slug": slug})
    assert not err and spec["current_version"] == 2 and spec["prod_version"] is None
    # esqueceu as instruções: edita, testa em stage e publica numa chamada só
    err, r = _mcp(client, ADMIN, "edit_agent", {"slug": slug, "instructions": "Seja objetivo.",
                                                 "objective": "objetivo revisado", "promote": True})
    assert not err, r
    paths = {c["path"] for c in r["changes"]}
    assert {"instructions", "objective"} <= paths and r["version"] == 3
    assert r["tests"]["status"] == "passed" and r["production"]["status"] == "deployed" and r["prod_version"] == 3
    # nova edição: a produção segue na v3 até publicar
    err, r = _mcp(client, ADMIN, "edit_agent", {"slug": slug, "changes": {"channels": ["slack"]}})
    assert r["version"] == 4 and r["prod_version"] == 3 and "produção continua na v3" in r["note"]
    err, d = _mcp(client, ADMIN, "diff_agent_versions", {"slug": slug, "from_version": 3})
    assert [c["path"] for c in d["changes"]] == ["channels"]
    # sem mudanças e sem teste novo: promote usa o teste aprovado da versão atual
    err, r = _mcp(client, ADMIN, "edit_agent", {"slug": slug, "test": False, "promote": True})
    assert r["production"]["status"] == "deployed" and not r["changes"]


def test_developer_edit_goes_to_approval(client, uniq):
    team = client.post("/api/teams", headers=ADMIN, json={"name": uniq("Squad")}).json()["slug"]
    email = f"{uniq('dev')}@acme.com"
    client.post(f"/api/teams/{team}/members", headers=ADMIN, json={"email": email, "role": "developer"})
    dev = _session(email)
    slug = _harness_agent(client, dev, uniq)
    err, r = _mcp(client, dev, "edit_agent", {"slug": slug, "instructions": "nova", "promote": True})
    assert not err and r["production"]["status"] == "approval_pending" and "mantenedor" in r["next"]
    # consumer não edita
    cons = f"{uniq('cons')}@acme.com"
    client.post(f"/api/teams/{team}/members", headers=ADMIN, json={"email": cons, "role": "consumer"})
    err, msg = _mcp(client, _session(cons), "edit_agent", {"slug": slug, "instructions": "x"})
    assert err and "editar" in str(msg)


def test_edit_via_http_api(client, uniq):
    slug = _harness_agent(client, ADMIN, uniq)
    r = client.post(f"/api/agents/{slug}/edit", headers=ADMIN, json={"changes": {"instructions": "api"}, "test": False})
    assert r.status_code == 200 and r.json()["changes"][0]["path"] == "instructions"
    d = client.get(f"/api/agents/{slug}/diff", headers=ADMIN, params={"from_version": 2}).json()
    assert d["changes"][0]["to"] == "api"
