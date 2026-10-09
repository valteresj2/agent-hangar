# ruff: noqa: F811  (env é fixture importada de test_employees)
"""Plugins P3 (Creator mode pelo MCP, com testes em stage e quatro olhos) e P4 (vitrine interna: categorias, destaque,
uso, histórico de versões, pedidos de instalação e exportação)."""
import json

import httpx
import pytest
import yaml

from app import config
from app.services import plugins as plugmod

from .conftest import ADMIN
from .test_employees import env  # noqa: F401

MANIFEST = """
name: {name}
title: Faturas
version: {version}
description: Faturas do ERP.
category: finance
tags: [ERP, faturas]
readme: "# Faturas\\nConsulta faturas do ERP."
base_url: https://erp.example.com/api
auth: {{type: api_key, name: X-Key}}
tools:
  - {{name: get_invoice, method: GET, path: "/invoices/{{number}}"}}
tests:
  - {{name: fatura existe, tool: get_invoice, args: {{number: "7"}}, expect_contains: "\\"total\\""}}
  - {{name: fatura inexistente, tool: get_invoice, args: {{number: "404"}}, expect_status: 404, expect_error: true}}
"""


class FakeERP:
    def __init__(self):
        self.keys = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def request(self, method, url, headers=None, params=None, json=None):
        self.keys.append((headers or {}).get("X-Key"))
        if url.endswith("/404"):
            return httpx.Response(404, json={"error": "not found"}, request=httpx.Request(method, url))
        if url.endswith("/500"):
            return httpx.Response(500, json={"error": "boom"}, request=httpx.Request(method, url))
        return httpx.Response(200, json={"number": url.rsplit("/", 1)[-1], "total": 99}, request=httpx.Request(method, url))


@pytest.fixture()
def erp(monkeypatch):
    fake = FakeERP()
    monkeypatch.setattr(plugmod, "HTTP", lambda: fake)
    monkeypatch.setattr(config, "PLUGIN_ALLOW_PRIVATE", True)
    return fake


def _pat(client, env, who):
    key = client.post("/api/keys", headers=env["h"][who], json={"name": f"mcp-{who}", "scopes": ["user"]}).json()["key"]
    return {"Authorization": f"Bearer {key}"}


def _mcp(client, headers, tool, args):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
    r = client.post("/mcp", json=body, headers={"Accept": "application/json, text/event-stream", **headers}).json()["result"]
    text = r["content"][0]["text"] if r.get("content") else ""
    try:
        return r.get("isError"), json.loads(text)
    except ValueError:
        return r.get("isError"), text


# ------------------------------------------------------------------ P3: creator mode pelo MCP
def test_creator_mode_drafts_tests_in_stage_and_needs_four_eyes(client, env, erp):
    name = f"fat-{env['n']}"
    dev = _pat(client, env, "own")
    err, d = _mcp(client, dev, "plugin_draft", {"manifest": MANIFEST.format(name=name, version="1.0.0"), "team": env["team"]})
    assert not err and d["status"] == "draft" and d["stage_install"] is False and "STAGE" in d["next"]
    err, out = _mcp(client, dev, "plugin_test", {"name": name})
    assert err and "instalação de stage" in str(out)
    err, out = _mcp(client, dev, "plugin_submit", {"name": name})
    assert err and "testes em stage" in str(out)  # sem relatório passando, não envia
    # a credencial de teste é cadastrada no portal (nunca pelo chat)
    r = client.put(f"/api/plugins/{name}/install", headers=env["h"]["own"],
                   json={"team": env["team"], "stage": True, "credential": "test-key"})
    assert r.status_code == 200 and r.json()["stage"] is True
    assert client.put(f"/api/plugins/{name}/install", headers=env["h"]["mgr"], json={"team": env["team"]}).status_code == 400  # rascunho não instala em produção
    err, rep = _mcp(client, dev, "plugin_test", {"name": name})
    assert not err and rep["passed"] is True and [x["ok"] for x in rep["results"]] == [True, True]
    assert erp.keys[-1] == "test-key"
    # mudou o rascunho: o relatório não vale mais
    changed = MANIFEST.format(name=name, version="1.0.0").replace("Faturas do ERP.", "Faturas do ERP (v2).")
    _mcp(client, dev, "plugin_draft", {"manifest": changed})
    err, out = _mcp(client, dev, "plugin_submit", {"name": name})
    assert err and "testes em stage" in str(out)
    _mcp(client, dev, "plugin_test", {"name": name})
    err, d = _mcp(client, dev, "plugin_submit", {"name": name})
    assert not err and d["status"] == "pending" and d["tests_ok"] is True
    # quatro olhos: quem criou não aprova; o admin aprova pelo MCP
    err, out = _mcp(client, dev, "plugin_review", {"name": name, "decision": "approve"})
    assert err
    err, d = _mcp(client, ADMIN, "plugin_review", {"name": name, "decision": "approve"})
    assert not err and d["status"] == "approved" and d["approved_version"] == "1.0.0"
    # a instalação de stage nunca serve os agentes nem aparece como instalada
    assert d["installed_for"] == []
    detail = client.get(f"/api/plugins/{name}", headers=env["h"]["own"]).json()
    assert detail["source"] == "creator" and detail["history"][0]["version"] == "1.0.0" and detail["history"][0]["tests"] is True


def test_failing_stage_tests_block_submit_and_review(client, env, erp):
    name = f"fat-bad-{env['n']}"
    bad = MANIFEST.format(name=name, version="1.0.0").replace('args: {number: "7"}', 'args: {number: "500"}')
    client.post("/api/plugins", headers=env["h"]["own"], json={"manifest": bad, "team": env["team"]})
    client.put(f"/api/plugins/{name}/install", headers=env["h"]["own"], json={"team": env["team"], "stage": True, "credential": "k"})
    rep = client.post(f"/api/plugins/{name}/tests", headers=env["h"]["own"], json={"team": env["team"]}).json()
    assert rep["passed"] is False and rep["results"][0]["why"] == "a ferramenta devolveu erro"
    assert client.post(f"/api/plugins/{name}/submit", headers=env["h"]["own"]).status_code == 400
    assert client.post(f"/api/plugins/{name}/tests", headers=env["h"]["out"],
                       json={}).status_code == 403


def test_openapi_by_url_through_mcp(client, env, monkeypatch):
    doc = {"openapi": "3.0.0", "info": {"title": "CRM", "version": "1.0.0"}, "servers": [{"url": "https://crm.example.com"}],
           "paths": {"/contacts/{id}": {"get": {"operationId": "getContact", "parameters": [
               {"name": "id", "in": "path", "schema": {"type": "string"}}]}}}}

    class Fetch:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            return httpx.Response(200, text=json.dumps(doc), request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "Client", lambda **k: Fetch())
    monkeypatch.setattr(config, "PLUGIN_ALLOW_PRIVATE", True)
    err, out = _mcp(client, _pat(client, env, "own"), "plugin_from_openapi", {"url": "https://crm.example.com/openapi.json"})
    assert not err and out["tools"] == 1 and "get_contact" in out["manifest_yaml"]
    assert yaml.safe_load(out["manifest_yaml"])["name"] == "crm"


# ------------------------------------------------------------------ P4: vitrine interna
def _live(client, env, name):
    client.post("/api/plugins", headers=env["h"]["own"], json={"manifest": MANIFEST.format(name=name, version="1.0.0"),
                                                                "team": env["team"]})
    client.put(f"/api/plugins/{name}/install", headers=env["h"]["own"], json={"team": env["team"], "stage": True, "credential": "k"})
    client.post(f"/api/plugins/{name}/tests", headers=env["h"]["own"], json={"team": env["team"]})
    client.post(f"/api/plugins/{name}/submit", headers=env["h"]["own"])
    assert client.post(f"/api/plugins/{name}/review", headers=ADMIN, json={"decision": "approve", "note": "ok"}).json()["status"] == "approved"


def test_gallery_featured_requests_and_export(client, env, erp):
    name = f"fat-g-{env['n']}"
    _live(client, env, name)
    card = next(x for x in client.get("/api/plugins", headers=env["h"]["req"]).json() if x["name"] == name)
    assert card["category"] == "finance" and card["tags"] == ["erp", "faturas"] and card["installs_count"] == 0 and card["featured"] is False
    assert client.post(f"/api/plugins/{name}/feature", headers=env["h"]["mgr"], json={"on": True}).status_code == 403
    assert client.post(f"/api/plugins/{name}/feature", headers=ADMIN, json={"on": True}).json()["featured"] is True
    # alguém do time pede; o mantenedor vê o pedido; instalar resolve o pedido
    assert client.post(f"/api/plugins/{name}/requests", headers=env["h"]["out"], json={"team": env["team"]}).status_code == 403
    d = client.post(f"/api/plugins/{name}/requests", headers=env["h"]["req"], json={"team": env["team"], "note": "para cobrança"}).json()
    assert d["requests"][0]["team"] == env["team"] and d["requests"][0]["note"] == "para cobrança"
    mine = client.get(f"/api/plugins/{name}", headers=env["h"]["mgr"]).json()
    assert mine["requests"] and mine["readme"].startswith("# Faturas")
    client.put(f"/api/plugins/{name}/install", headers=env["h"]["mgr"], json={"team": env["team"], "credential": "prod-key"})
    after = client.get(f"/api/plugins/{name}", headers=env["h"]["mgr"]).json()
    assert after["requests"] == [] and after["installs_count"] == 1 and after["installed_for"] == [env["team"]]
    assert client.post(f"/api/plugins/{name}/requests", headers=env["h"]["req"], json={"team": env["team"]}).status_code == 400
    # exportar: o manifesto aprovado, para levar a outro ambiente (lá passa pela revisão de novo)
    r = client.get(f"/api/plugins/{name}/export", headers=env["h"]["req"])
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    m = yaml.safe_load(r.text)
    assert m["name"] == name and m["version"] == "1.0.0" and "prod-key" not in r.text
    assert client.get(f"/api/plugins/{name}/export?draft=true", headers=env["h"]["out"]).status_code == 403  # outro time
