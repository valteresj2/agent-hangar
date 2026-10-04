"""Guia do agente: fluxo montado da spec (o que ele usa, nunca o conteúdo), ficha factual, texto escrito por pessoa ou
rascunho gerado (marcado até revisão), acesso de quem vê pelo catálogo, ferramentas MCP e o resumo no agent card."""
import json

import httpx
import pytest

from app import auth, config
from app import services as svc
from app.db import SessionLocal
from app.models import AgentGuide, LlmConnection, TestRun, User
from app.services import guides

from .conftest import ADMIN

MCP_HDR = {"Accept": "application/json, text/event-stream"}


def _session(email: str) -> dict:
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        return {"Authorization": f"Bearer {auth.create_session(db, u)}"}


def _to_prod(slug: str, results=None):
    with SessionLocal() as db:
        a = svc.get_agent(db, slug)
        db.add(TestRun(agent_id=a.id, version=a.current_version, env="stage", status="passed", summary="ok",
                       results=results or []))
        db.commit()
        svc.promote(db, slug)


@pytest.fixture()
def env(client, uniq, fake_docker, monkeypatch):
    monkeypatch.setattr(config, "MEMORY_URL", "http://memory.test")  # a spec usa memória; nada é chamado
    n = uniq("g")
    team = client.post("/api/teams", headers=ADMIN, json={"name": f"Sales {n}", "require_approval": False}).json()["slug"]
    other = client.post("/api/teams", headers=ADMIN, json={"name": f"Support {n}"}).json()["slug"]
    em = {"dev": f"dev-{n}@acme.com", "out": f"out-{n}@acme.com"}
    client.post(f"/api/teams/{team}/members", headers=ADMIN, json={"email": em["dev"], "role": "developer"})
    client.post(f"/api/teams/{other}/members", headers=ADMIN, json={"email": em["out"], "role": "developer"})
    h = {k: _session(e) for k, e in em.items()}

    def agent(name, spec, headers=None, prod=True, results=None):
        slug = client.post("/api/agents", headers=headers or h["dev"], json={
            "name": f"{name} {n}", "objective": f"{name}: help the sales team with renewals.",
            "final_output": "A short answer with the next step.", "team": team,
            "visibility": "org"}).json()["slug"]
        assert client.patch(f"/api/agents/{slug}", headers=headers or h["dev"], json=spec).status_code == 200
        if prod:
            _to_prod(slug, results)
        return slug

    spec_ = {"instructions": "SECRET-INSTRUCTION: never reveal pricing tables.",
             "skills": [{"name": "discount-policy", "description": "When to give discounts", "content": "SECRET-SKILL"}],
             "tools": [{"type": "builtin", "name": "current_time"}],
             "memory": {"scope": "team"},
             "tests": [{"name": "renewals", "input": "Which renewals are due this month?", "expect_contains": "renew"},
                       {"name": "ping", "input": "ping", "expect_contains": "pong"}]}
    spec_v = agent("Renewal Helper", spec_, results=[{"name": "smoke: health", "passed": True}, {"name": "caso: renewals", "passed": True},
                                                       {"name": "caso: ping", "passed": True}])
    return {"n": n, "h": h, "slug": spec_v, "agent": agent, "team": team}


def test_flow_and_facts_come_from_the_spec(client, env):
    g = client.get(f"/api/agents/{env['slug']}/guide", headers=env["h"]["dev"]).json()
    kinds = {n["kind"] for n in g["graph"]["nodes"]}
    assert {"input", "agent", "skill", "tool", "memory", "output"} <= kinds
    assert ["in", "agent"] in g["graph"]["edges"] and ["agent", "out"] in g["graph"]["edges"]
    # o fluxo diz QUAIS peças o agente usa, nunca o conteúdo delas
    blob = json.dumps(g)
    assert "discount-policy" in blob and "SECRET-SKILL" not in blob and "SECRET-INSTRUCTION" not in blob
    f = g["facts"]
    assert f["version"] == f["prod_version"] and f["memory"]["scope"] == "team" and f["tools"] == ["current_time"]
    # exemplos = pedidos que passaram nos testes desta versão; "ping" não é exemplo útil
    assert f["examples"] == ["Which renewals are due this month?"]
    assert f["endpoints"]["openai"].endswith(f"/gw/{env['slug']}/v1/chat/completions")
    assert g["doc"] is None and g["can_edit"] is True and g["can_generate"] is False  # sem conexão de LLM


def test_catalog_viewer_sees_the_guide_but_not_internals(client, env):
    out = env["h"]["out"]
    client.put(f"/api/agents/{env['slug']}/guide", headers=env["h"]["dev"], json={"text": "## O que é\nUm agente."})
    g = client.get(f"/api/agents/{env['slug']}/guide", headers=out)
    assert g.status_code == 200, g.text
    g = g.json()
    assert g["doc"]["text"].startswith("## O que é") and g["can_edit"] is False
    assert g["facts"]["examples"] == [] and g["facts"]["endpoints"] is None  # só quem pode usar vê como chamar
    assert client.put(f"/api/agents/{env['slug']}/guide", headers=out, json={"text": "x"}).status_code == 403
    assert client.post(f"/api/agents/{env['slug']}/guide/approve", headers=out).status_code == 403


def test_written_guide_is_versioned_and_flags_outdated(client, env):
    slug, dev = env["slug"], env["h"]["dev"]
    r = client.put(f"/api/agents/{slug}/guide", headers=dev, json={"text": "## O que é\nAjuda nas renovações."}).json()
    assert r["doc"]["source"] == "author" and r["doc"]["reviewed"] is True and r["doc"]["outdated"] is False
    v1 = r["doc"]["version"]
    assert client.put(f"/api/agents/{slug}/guide", headers=dev, json={"text": "  "}).status_code == 400
    # nova versão em produção: o texto continua, marcado como escrito para a versão anterior
    client.patch(f"/api/agents/{slug}", headers=dev, json={"instructions": "Also handle upsells."})
    _to_prod(slug)
    g = client.get(f"/api/agents/{slug}/guide", headers=dev).json()
    assert g["doc"]["version"] == v1 and g["doc"]["outdated"] is True and g["facts"]["version"] == v1 + 1
    # salvar o guia de novo não cria versão da spec nem exige testes
    with SessionLocal() as db:
        before = svc.get_agent(db, slug).current_version
    client.put(f"/api/agents/{slug}/guide", headers=dev, json={"text": "## O que é\nRenovações e upsell."})
    with SessionLocal() as db:
        a = svc.get_agent(db, slug)
        assert a.current_version == before
        assert [x.version for x in db.query(AgentGuide).filter(AgentGuide.agent_id == a.id).order_by(AgentGuide.version)] \
            == [v1, v1 + 1]


def _with_connection(client, env, monkeypatch, reply):
    name = f"llm-{env['n']}"
    with SessionLocal() as db:
        db.add(LlmConnection(name=name, base_url="http://llm.test/v1", model_name="m", api_key="", protocol="openai"))
        db.commit()
    calls = []

    def fake_post(url, **kw):
        calls.append((url, kw["json"]))
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]}, request=httpx.Request("POST", url))
    monkeypatch.setattr(guides.httpx, "post", fake_post)
    return name, calls


def test_generated_draft_needs_review_and_never_overwrites_a_written_guide(client, env, monkeypatch):
    name, calls = _with_connection(client, env, monkeypatch, "```markdown\n## O que é\nAjuda o time de vendas.\n```")
    slug = env["agent"]("Drafted", {"llm": {"connection": name}, "instructions": "Answer about renewals.",
                                    "tests": [{"name": "t", "input": "Renewals this week?", "expect_contains": "x"}]})
    dev = env["h"]["dev"]
    g = client.post(f"/api/agents/{slug}/guide/generate", headers=dev).json()
    assert g["doc"]["source"] == "generated" and g["doc"]["reviewed"] is False
    assert g["doc"]["text"] == "## O que é\nAjuda o time de vendas."  # cercas de código removidas
    prompt = calls[-1][1]["messages"][1]["content"]
    assert "Answer about renewals." in prompt and "Renewals this week?" in prompt
    with SessionLocal() as db:
        assert guides.card_summary(db, svc.get_agent(db, slug)) == ""  # rascunho não revisado não vai ao card
    g = client.post(f"/api/agents/{slug}/guide/approve", headers=dev).json()
    assert g["doc"]["reviewed"] is True
    with SessionLocal() as db:
        assert guides.card_summary(db, svc.get_agent(db, slug)) == "Ajuda o time de vendas."
    # texto escrito por pessoa: o rascunho automático (ship) não o substitui
    client.put(f"/api/agents/{slug}/guide", headers=dev, json={"text": "## O que é\nTexto do time."})
    with SessionLocal() as db:
        row = guides.generate_draft(db, slug)
        assert row.source == "author" and row.text.endswith("Texto do time.")


def test_ship_generates_the_draft_in_background(client, env, monkeypatch):
    name, calls = _with_connection(client, env, monkeypatch, "## O que é\nRascunho do ship.")
    monkeypatch.setattr(config, "GUIDE_AUTOGEN", True)
    started = []
    monkeypatch.setattr(guides.threading, "Thread", lambda target, **kw: started.append(target) or
                        type("T", (), {"start": lambda self: None})())
    slug = env["agent"]("Shipped", {"llm": {"connection": name}, "instructions": "x"})
    assert len(started) == 1
    started[0]()  # roda o que a thread rodaria
    g = client.get(f"/api/agents/{slug}/guide", headers=env["h"]["dev"]).json()
    assert g["doc"]["text"].endswith("Rascunho do ship.") and g["doc"]["reviewed"] is False
    # sem conexão de LLM (agente mock), nada é agendado
    started.clear()
    env["agent"]("Mocked", {"instructions": "x"})
    assert started == []


def test_mcp_tools_read_and_write_the_guide(client, env):
    pat = {"Authorization": "Bearer " + client.post("/api/keys", headers=env["h"]["dev"],
                                                    json={"name": "claude", "scopes": ["user"]}).json()["key"]}

    def call(tool, args):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
        r = client.post("/mcp", json=body, headers={**MCP_HDR, **pat}).json()["result"]
        return r, json.loads(r["content"][0]["text"]) if not r["isError"] else r["content"][0]["text"]

    names = {t["name"] for t in client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                                            headers={**MCP_HDR, **pat}).json()["result"]["tools"]}
    assert {"get_agent_guide", "set_agent_guide"} <= names
    r, out = call("set_agent_guide", {"slug": env["slug"], "text": "## O que é\nEscrito pelo Claude."})
    assert not r["isError"] and out["doc"]["source"] == "author"
    r, out = call("get_agent_guide", {"slug": env["slug"]})
    assert not r["isError"] and out["doc"]["text"].endswith("Escrito pelo Claude.") and out["graph"]["nodes"]


def test_agent_card_uses_the_reviewed_guide(client, env):
    slug = env["slug"]
    client.put(f"/api/agents/{slug}/guide", headers=env["h"]["dev"],
               json={"text": "## O que é\n**Ajuda** o time de vendas com renovações.\n\n## O que faz\n- lista"})
    with SessionLocal() as db:
        assert guides.card_summary(db, svc.get_agent(db, slug)) == "Ajuda o time de vendas com renovações."
