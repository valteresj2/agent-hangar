"""Memória dos agentes: spec, grupos impostos pela central (escopo, stage x prod provado por token), proxy, config
do serviço e API de administração com permissões."""
import json

import httpx
import pytest

from app import auth, config
from app import services as svc
from app.db import SessionLocal

from .conftest import ADMIN
from .test_access import org_setup  # noqa: F401  (fixture)


@pytest.fixture()
def memory_on(monkeypatch):
    monkeypatch.setattr(config, "MEMORY_URL", "http://memory:8000")
    monkeypatch.setattr(config, "MEMORY_TOKEN", "mem-token")


@pytest.fixture()
def upstream(monkeypatch):
    """Serviço de memória falso: guarda os headers de cada chamada."""
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.url.path == "/mcp":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "recall"}]}})
        if req.url.path == "/admin/facts":
            return httpx.Response(200, json={"group": req.url.params["group"], "facts": [{"fact": "ACME é cliente Enterprise"}]})
        if req.url.path.startswith("/admin/groups/"):
            return httpx.Response(200, json={"cleared": req.url.path.rsplit("/", 1)[1]})
        return httpx.Response(404)

    from app.routers import memory as router_mod
    real = httpx.AsyncClient
    monkeypatch.setattr(router_mod.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(svc.memory, "HTTP", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return seen


def _agent(client, uniq, memory=None, headers=ADMIN):
    slug = client.post("/api/agents", headers=headers, json={"name": uniq("Mem"), "objective": "o", "final_output": "f"}).json()["slug"]
    if memory is not None:
        r = client.patch(f"/api/agents/{slug}", headers=headers, json={"memory": memory})
        assert r.status_code == 200, r.text
    return slug


def _call(client, slug, env=None, env_token=None):
    h = {"X-Agent-Slug": slug, "Authorization": f"Bearer {auth.agent_token(slug)}"}
    if env:
        h["X-Agent-Env"] = env
        h["X-Agent-Env-Token"] = env_token if env_token is not None else auth.agent_env_token(slug, env)
    return client.post("/internal/memory/mcp", headers=h, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})


def test_spec_validation(client, uniq):
    slug = _agent(client, uniq)
    assert client.patch(f"/api/agents/{slug}", headers=ADMIN, json={"memory": {"scope": "galaxy"}}).status_code == 400
    assert client.patch(f"/api/agents/{slug}", headers=ADMIN, json={"memory": {"scope": "team", "write": False}}).status_code == 200


def test_resolve_spec_adds_memory_mcp_only_when_enabled(client, uniq, monkeypatch):
    slug = _agent(client, uniq, {"scope": "agent"})
    with SessionLocal() as db:
        a = svc.get_agent(db, slug)
        with pytest.raises(svc.PlatformError, match="memória não está ligada"):
            svc.resolve_spec(db, a, "stage")
        monkeypatch.setattr(config, "MEMORY_URL", "http://memory:8000")
        mcps = svc.resolve_spec(db, a, "stage")["mcps"]
    assert {"name": "memory", "url": f"{config.INTERNAL_BASE_URL}/internal/memory/mcp"} in mcps


def test_proxy_groups_by_env_and_scope(client, uniq, memory_on, upstream):
    slug = _agent(client, uniq, {"scope": "agent"})
    r = _call(client, slug, "prod")
    assert r.status_code == 200 and r.json()["result"]["tools"][0]["name"] == "recall"
    h = upstream[-1].headers
    assert h["authorization"] == "Bearer mem-token"  # o token do agente não vai para o serviço
    assert h["x-memory-read"] == f"agent-{slug}" and h["x-memory-write"] == f"agent-{slug}" and h["x-memory-actor"] == slug

    _call(client, slug)  # sem prova de ambiente = stage: lê produção, grava à parte
    h = upstream[-1].headers
    assert h["x-memory-read"] == f"agent-{slug},agent-{slug}__stage" and h["x-memory-write"] == f"agent-{slug}__stage"

    _call(client, slug, "prod", env_token=auth.agent_env_token(slug, "stage"))  # stage se passando por prod
    assert upstream[-1].headers["x-memory-write"] == f"agent-{slug}__stage"


def test_proxy_rejects(client, uniq, memory_on, upstream):
    no_mem = _agent(client, uniq)
    assert _call(client, no_mem, "prod").status_code == 403
    slug = _agent(client, uniq, {})
    bad = client.post("/internal/memory/mcp", headers={"X-Agent-Slug": slug, "Authorization": "Bearer x"}, json={})
    assert bad.status_code == 401
    assert client.post("/internal/memory/mcp", headers=ADMIN, json={}).status_code == 401  # admin não é agente
    assert not upstream


def test_team_scope_and_read_only(client, org_setup, memory_on, upstream):  # noqa: F811
    s = org_setup
    client.patch(f"/api/agents/{s['slug']}", headers=s["h"]["dev"], json={"memory": {"scope": "team", "write": False}})
    _call(client, s["slug"], "prod")
    h = upstream[-1].headers
    assert h["x-memory-read"] == f"team-{s['ta']}" and h["x-memory-write"] == ""


def test_narrowest_scope_wins(client, uniq):
    assert svc.memory.effective([{"memory": {"scope": "org"}}, {"memory": {"scope": "team", "write": False}}]) == \
        {"scope": "team", "write": False}
    assert svc.memory.effective([{"mcps": []}]) is None


def test_service_config_needs_memory_token(client, memory_on, monkeypatch, uniq):
    name = uniq("memllm")
    with SessionLocal() as db:
        svc.upsert_llm_connection(db, name, "https://llm.test/v1", "m-1", api_key="sk-segredo")
    monkeypatch.setattr(config, "MEMORY_LLM_CONNECTION", name)
    assert client.get("/internal/memory/config", headers={"Authorization": "Bearer errado"}).status_code == 401
    assert client.get("/internal/memory/config", headers=ADMIN).status_code == 401
    c = client.get("/internal/memory/config", headers={"Authorization": "Bearer mem-token"}).json()
    assert c["llm"] == {"base_url": "https://llm.test/v1", "api_key": "sk-segredo", "model": "m-1", "output_mode": "json_object"}


def test_admin_facts_and_clear_permissions(client, org_setup, memory_on, upstream):  # noqa: F811
    s, h = org_setup, org_setup["h"]
    client.patch(f"/api/agents/{s['slug']}", headers=h["dev"], json={"memory": {"scope": "agent"}})
    r = client.get(f"/api/agents/{s['slug']}/memory", headers=h["dev"], params={"env": "stage"})
    assert r.status_code == 200 and r.json()["group"] == f"agent-{s['slug']}__stage" and r.json()["facts"]
    assert client.get(f"/api/agents/{s['slug']}/memory", headers=h["aud"]).status_code == 200
    for who in ("cons", "out"):
        assert client.get(f"/api/agents/{s['slug']}/memory", headers=h[who]).status_code == 403
    assert client.delete(f"/api/agents/{s['slug']}/memory", headers=h["dev"]).status_code == 403  # manage
    r = client.delete(f"/api/agents/{s['slug']}/memory", headers={**h["maint"]})
    assert r.status_code == 200 and r.json()["cleared"] == f"agent-{s['slug']}"


def test_status_disabled_by_default(client):
    assert client.get("/api/memory/status", headers=ADMIN).json() == {"enabled": False}


def test_runtime_sends_env_proof(monkeypatch):
    import importlib.util
    import os
    import sys
    for k, v in {"AGENT_SPEC": json.dumps({"mcps": []}), "AGENT_SLUG": "x", "AGENT_ENV": "prod",
                 "INTERNAL_ENV_TOKEN": "tok"}.items():
        monkeypatch.setenv(k, v)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location("runtime_env_probe", os.path.join(root, "runtime", "app.py"))
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "runtime_env_probe", mod)
    spec.loader.exec_module(mod)
    assert mod.INTERNAL_HEADERS["X-Agent-Env"] == "prod" and mod.INTERNAL_HEADERS["X-Agent-Env-Token"] == "tok"


def test_delete_agent_forgets_its_memory(client, uniq, memory_on, upstream):
    slug = _agent(client, uniq, {"scope": "agent"})
    assert client.delete(f"/api/agents/{slug}", headers=ADMIN).status_code == 200
    cleared = [r.url.path for r in upstream if r.method == "DELETE"]
    assert cleared == [f"/admin/groups/agent-{slug}", f"/admin/groups/agent-{slug}__stage"]
