"""Runtime do agente: anexos no formato OpenAI (como o LibreChat envia), sessão e moeda para clientes com LaTeX."""
import asyncio
import base64
import importlib.util
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def rt():
    os.environ["AGENT_SPEC"] = json.dumps({"name": "T", "llm": {"model": "mock/echo"}})
    # carregado pelo caminho: "app" já é o pacote da central nos outros testes
    spec = importlib.util.spec_from_file_location("agent_runtime", os.path.join(ROOT, "runtime", "app.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["agent_runtime"] = mod
    spec.loader.exec_module(mod)
    return mod


def _tools(rt, calls):
    async def ingest(args):
        calls.append(args)
        return json.dumps({"path": args["filename"], "new": True})
    return [rt.Tool("data-studio__ingest_file", "", {}, ingest, hidden=True)]


def test_attachments_are_ingested_and_replaced(rt):
    calls = []
    pdf = base64.b64encode(b"%PDF-1.4 teste").decode()
    png = base64.b64encode(b"\x89PNG fake").decode()
    msgs = [{"role": "user", "content": [
        {"type": "file", "file": {"filename": "rel.pdf", "file_data": f"data:application/pdf;base64,{pdf}"}},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}},
        {"type": "text", "text": "analise"}]}]
    rt.SESSION.set("conv-1")
    out = asyncio.run(rt.prepare_attachments(msgs, _tools(rt, calls)))
    assert [c["filename"] for c in calls][0] == "rel.pdf" and calls[0]["data_base64"] == pdf
    parts = out[0]["content"]
    assert parts[0]["type"] == "text" and "rel.pdf" in parts[0]["text"] and "image → workspace: imagem_" in parts[0]["text"]
    assert any(p["type"] == "image_url" for p in parts)          # visão continua recebendo a imagem
    assert not any(p["type"] == "file" for p in parts)           # o PDF bruto não vai ao LLM


def test_same_attachment_is_ingested_once_per_session(rt):
    calls = []
    data = base64.b64encode(b"a,b\n1,2").decode()
    msg = {"role": "user", "content": [{"type": "file", "file": {"filename": "x.csv",
                                                                  "file_data": f"data:text/csv;base64,{data}"}}]}
    rt.SESSION.set("conv-2")
    tools = _tools(rt, calls)
    asyncio.run(rt.prepare_attachments([msg], tools))
    asyncio.run(rt.prepare_attachments([msg], tools))
    assert len(calls) == 1


def test_without_workspace_file_is_described(rt):
    msg = {"role": "user", "content": [{"type": "file", "file": {"filename": "x.csv", "file_data": "data:text/csv;base64,YQ=="}},
                                       {"type": "text", "text": "oi"}]}
    out = asyncio.run(rt.prepare_attachments([msg], []))
    assert isinstance(out[0]["content"], str) and "no workspace" in out[0]["content"]


def test_currency_escaped_only_for_latex_channels(rt):
    rt.CHANNEL.set("librechat")
    assert rt.render_for_channel("R$ 10 e R$ 20; $x^2$") == r"R\$ 10 e R\$ 20; $x^2$"
    rt.CHANNEL.set("api")
    assert rt.render_for_channel("R$ 10") == "R$ 10"


def test_mock_reads_multimodal_text(rt):
    text, usage, _ = asyncio.run(rt.chat([{"role": "user", "content": [{"type": "text", "text": "olá"}]}]))
    assert text.endswith("olá") and usage["total_tokens"] > 0


def _fake_llm(rt, monkeypatch, replies):
    """Substitui o LLM por respostas prontas (uma por chamada) e devolve a lista de payloads recebidos."""
    import httpx
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=replies[min(len(seen) - 1, len(replies) - 1)])

    real = httpx.AsyncClient
    monkeypatch.setattr(rt.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(rt, "MODEL", "fake-model")
    return seen


def test_tool_loop_emits_progress(rt, monkeypatch):
    call = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "data-studio__run_sql",
                                                      "arguments": json.dumps({"query": "SELECT 1\nFROM t"})}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}}
    final = {"choices": [{"message": {"role": "assistant", "content": "pronto"}}],
             "usage": {"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23}}
    seen = _fake_llm(rt, monkeypatch, [call, final])

    async def sql(args):
        return "1 linha"

    async def tools():
        return [rt.Tool("data-studio__run_sql", "", {"type": "object"}, sql)]
    monkeypatch.setattr(rt, "get_tools", tools)

    async def run():
        q = asyncio.Queue()
        rt.PROGRESS.set(q)
        rt.MODE.set("full")
        out = await rt.chat([{"role": "user", "content": "conte"}])
        return out, [q.get_nowait() for _ in range(q.qsize())]
    (text, usage, trace), events = asyncio.run(run())
    assert text == "pronto" and usage["total_tokens"] == 35 and trace[0]["tool"] == "data-studio__run_sql"
    assert events[0] == "🔧 run_sql: SELECT 1" and events[1].strip().startswith("✓")
    assert "tools" in seen[0]


def test_lite_mode_skips_tools_and_agent_prompt(rt, monkeypatch):
    seen = _fake_llm(rt, monkeypatch, [{"choices": [{"message": {"content": "Vendas 2026"}}], "usage": {}}])

    async def run():
        rt.MODE.set("lite")
        return await rt.chat([{"role": "user", "content": [{"type": "text", "text": "gere um título"}]}])
    text, _, trace = asyncio.run(run())
    assert text == "Vendas 2026" and trace == []
    assert "tools" not in seen[0] and seen[0]["max_tokens"] == 1500
    assert "Instruções" not in seen[0]["messages"][0]["content"]
