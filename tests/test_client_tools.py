"""Ferramentas do cliente (modo agente de código: chat do VS Code, Cline, Roo, Continue): o cliente manda `tools`,
o agente devolve `tool_calls` para ele executar e usa o resultado; as tools do próprio agente seguem no servidor e o
contexto delas é reinserido quando o cliente devolve os resultados. E o teste de conexão da central."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from .conftest import ADMIN
from .test_runtime import _fake_llm, rt  # noqa: F401  (fixture)

PING = {"type": "function", "function": {"name": "hangar_ping", "description": "teste",
                                         "parameters": {"type": "object", "properties": {"nonce": {"type": "string"}}}}}


@pytest.fixture()
def api(rt):  # noqa: F811
    rt.MODE.set("full")
    # sem `with`: o lifespan (MCP do agente) só pode subir uma vez por processo e estas rotas não precisam dele
    yield TestClient(rt.app)


def _sse(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: {")]


def test_mock_roundtrip_non_stream(api):
    r = api.post("/v1/chat/completions", json={"model": "t", "tools": [PING],
                                               "messages": [{"role": "user", "content": "chame hangar_ping nonce=abc"}]})
    ch = r.json()["choices"][0]
    assert ch["finish_reason"] == "tool_calls" and ch["message"]["content"] is None
    call = ch["message"]["tool_calls"][0]
    assert call["function"]["name"] == "hangar_ping" and json.loads(call["function"]["arguments"]) == {"nonce": "abc"}
    r2 = api.post("/v1/chat/completions", json={"model": "t", "tools": [PING], "messages": [
        {"role": "user", "content": "chame hangar_ping nonce=abc"}, ch["message"],
        {"role": "tool", "tool_call_id": call["id"], "content": "pong abc"}]})
    ch2 = r2.json()["choices"][0]
    assert ch2["finish_reason"] == "stop" and "pong abc" in ch2["message"]["content"]


def test_mock_roundtrip_stream(api):
    r = api.post("/v1/chat/completions", json={"model": "t", "stream": True, "tools": [PING],
                                               "messages": [{"role": "user", "content": "chame hangar_ping nonce=x1"}]})
    evs = _sse(r.text)
    deltas = [c["delta"] for e in evs for c in e["choices"]]
    calls = [tc for d in deltas for tc in d.get("tool_calls", [])]
    assert calls and calls[0]["index"] == 0 and calls[0]["function"]["name"] == "hangar_ping"
    assert evs[-1]["choices"][0]["finish_reason"] == "tool_calls" and "usage" in evs[-1]
    assert r.text.rstrip().endswith("data: [DONE]")


def test_client_tools_can_be_disabled(api, rt, monkeypatch):  # noqa: F811
    monkeypatch.setattr(rt, "CLIENT_TOOLS", False)
    r = api.post("/v1/chat/completions", json={"model": "t", "tools": [PING],
                                               "messages": [{"role": "user", "content": "chame hangar_ping nonce=abc"}]})
    assert r.json()["choices"][0]["finish_reason"] == "stop"


def test_invalid_client_tools_are_ignored(rt):  # noqa: F811
    tools = rt._client_tools([PING, {"type": "function", "function": {"name": "com espaço"}},
                              {"type": "code_interpreter"}, "lixo"])
    assert [t["function"]["name"] for t in tools] == ["hangar_ping"]


def test_mixed_round_keeps_server_context(rt, monkeypatch):  # noqa: F811
    """O LLM pede uma tool do agente e uma do cliente na mesma rodada: a do agente roda aqui, a do cliente volta; na
    requisição seguinte, a rodada do servidor é reinserida antes da chamada do cliente."""
    mixed = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "s1", "type": "function", "function": {"name": "memory__recall", "arguments": "{\"query\": \"x\"}"}},
        {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{\"path\": \"a.py\"}"}}]}}],
             "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}}
    final = {"choices": [{"message": {"role": "assistant", "content": "editado"}}], "usage": {}}
    seen = _fake_llm(rt, monkeypatch, [mixed, final])

    async def recall(args):
        return "fato da memória"

    async def tools():
        return [rt.Tool("memory__recall", "", {"type": "object"}, recall)]
    monkeypatch.setattr(rt, "get_tools", tools)
    read_file = {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}}
    user = {"role": "user", "content": "corrija a.py"}

    text, _u, trace, calls = asyncio.run(rt.chat_full([user], [read_file]))
    assert text == "" and [c["id"] for c in calls] == ["c1"]
    assert trace[0]["tool"] == "memory__recall" and trace[-1] == {"client_tool_calls": ["read_file"]}
    assert {t["function"]["name"] for t in seen[0]["tools"]} == {"memory__recall", "read_file"}
    assert "Ferramentas do ambiente do usuário" in seen[0]["messages"][0]["content"]

    text2, *_ = asyncio.run(rt.chat_full(
        [user, {"role": "assistant", "content": None, "tool_calls": calls},
         {"role": "tool", "tool_call_id": "c1", "content": "print(1)"}], [read_file]))
    assert text2 == "editado"
    roles = [(m["role"], m.get("tool_call_id") or [c["id"] for c in m.get("tool_calls") or []]) for m in seen[1]["messages"][1:]]
    assert roles == [("user", []), ("assistant", ["s1"]), ("tool", "s1"), ("assistant", ["c1"]), ("tool", "c1")]


# ------------------------------------------------------------------ central: teste de conexão
def test_connection_probe(client, uniq, monkeypatch, rt):  # noqa: F811
    """A central fala com o container pelo stream, devolve o resultado da ferramenta e confere a resposta."""
    from app import services as svc
    from app.services import connect as conn

    slug = client.post("/api/agents", headers=ADMIN, json={"name": uniq("Dev"), "objective": "o", "final_output": "f"}).json()["slug"]
    assert client.post(f"/api/agents/{slug}/deploy", headers=ADMIN, json={"env": "stage"}).status_code == 200
    rt.MODE.set("full")
    runtime = TestClient(rt.app)

    def handler(req: httpx.Request) -> httpx.Response:
        r = runtime.post("/v1/chat/completions", content=req.content, headers={"content-type": "application/json"})
        return httpx.Response(r.status_code, content=r.content, headers={"content-type": r.headers["content-type"]})
    monkeypatch.setattr(conn, "HTTP", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    r = client.post(f"/api/agents/{slug}/connections/test", headers=ADMIN, json={"env": "stage"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] and [s["ok"] for s in d["steps"]] == [True, True] and "pong" in d["reply"]
    assert client.post(f"/api/agents/{slug}/connections/test", headers=ADMIN, json={"env": "prod"}).status_code == 400
    assert svc.connect.CLIENTS["cline"][1] == ("model",) and "model" in svc.connect.CLIENTS["vscode"][1]


def test_coding_client_snippets():
    from app.services import connect as conn
    for client in ("vscode", "cline", "continue"):
        s = conn.snippet(client, "model", "dev-bot", "Dev Bot", key="ah_x")
        assert "/gw/dev-bot/v1" in s["content"] and "ah_x" in s["content"]
    assert "tool_use" in conn.snippet("continue", "model", "dev-bot", "Dev Bot")["content"]


def test_invalid_body_is_400(api):
    r = api.post("/v1/chat/completions", content=b'{"messages": [{"role": "user", "content": "s\xf3"}]}',
                 headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json()["error"]["type"] == "invalid_request_error"
