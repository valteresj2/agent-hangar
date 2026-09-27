"""Runtime de um agente. Cada agente = 1 container isolado desta imagem.

Protocolos expostos:
  - OpenAI-compatible : POST /v1/chat/completions, GET /v1/models
  - A2A (JSON-RPC)    : GET /.well-known/agent.json, POST /a2a  (message/send)
  - ACP (IBM/BeeAI)   : GET /acp/agents, POST /acp/runs         (compat. legado)
  - MCP               : POST /mcp — o próprio agente como servidor MCP (1 tool), para
                         Claude Desktop/Code, OpenCode etc. o usarem como ferramenta externa
"""
import ast
import json
import operator
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

SPEC = json.loads(os.environ["AGENT_SPEC"])
SLUG = os.environ.get("AGENT_SLUG", "agent")
ENV = os.environ.get("AGENT_ENV", "stage")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://litellm:4000/v1").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
# Credencial deste agente na central (HMAC do slug — nunca o token de admin). Vai junto com X-Agent-Slug
# nas chamadas a sub-agentes e ao dashboard; a central confere se o destino é permitido para este agente.
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")
INTERNAL_BASE_URL = os.environ.get("INTERNAL_BASE_URL", "http://central:8080").rstrip("/")
INTERNAL_HEADERS = {"Authorization": f"Bearer {INTERNAL_TOKEN}", "X-Agent-Slug": SLUG}
LLM = SPEC.get("llm", {})
MODEL = LLM.get("model", "mock/echo")
PRICES = LLM.get("prices") or [None, None]  # US$ por 1M tokens (entrada, saída), da conexão do catálogo
MAX_STEPS = 6
TOOLS_TTL_S = 300  # a lista de tools dos MCPs externos é reconstruída de tempos em tempos


# ---------------------------------------------------------------- tools
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg, ast.Mod: operator.mod}


def _calc(expr: str):
    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.operand))
        raise ValueError("expressão não suportada")
    return ev(ast.parse(expr, mode="eval").body)


def _safe(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:64]


class Tool:
    def __init__(self, name, description, parameters, fn):
        self.name, self.description, self.parameters, self.fn = name, description, parameters, fn

    def schema(self):
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters}}


async def _http_tool(t, args):
    method = t.get("method", "GET").upper()
    async with httpx.AsyncClient(timeout=30) as c:
        r = await (c.get(t["url"], params=args) if method == "GET" else c.request(method, t["url"], json=args))
    return r.text[:8000]


async def _dashboard_call(args):
    """Builtin 'platform_dashboard': lê dados operacionais da própria Central (agentes, deployments,
    testes, uso) via /internal/dashboard, autenticado com INTERNAL_TOKEN — nunca o ADMIN_TOKEN, que
    não deve existir dentro de um agente. Somente leitura; não cria, muda nem apaga nada."""
    kind = args.get("kind", "overview")
    path = f"agents/{args['slug']}" if kind == "agent" and args.get("slug") else kind
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{INTERNAL_BASE_URL}/internal/dashboard/{path}", headers=INTERNAL_HEADERS)
    if r.status_code >= 400:
        return f"erro ({r.status_code}): {r.text[:400]}"
    return r.text[:6000]


async def _mcp_call(url, tool, args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(url) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(tool, args)
            return "\n".join(getattr(c, "text", str(c)) for c in res.content)[:8000]


async def _mcp_list(url):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(url) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return (await s.list_tools()).tools


async def _ask_sub(sub, args):
    res = await _a2a_call(sub["url"], args.get("message", ""))
    return res


async def _a2a_call(base_url, message):
    body = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "message/send",
            "params": {"message": {"kind": "message", "role": "user", "messageId": str(uuid.uuid4()),
                                   "parts": [{"kind": "text", "text": message}]}}}
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{base_url.rstrip('/')}/a2a", json=body, headers=INTERNAL_HEADERS)
    if r.status_code >= 400:
        return f"[erro do sub-agente: HTTP {r.status_code} {r.text[:200]}]"
    data = r.json()
    if "error" in data:
        return f"[erro do sub-agente: {data['error'].get('message')}]"
    return "".join(p.get("text", "") for p in data["result"].get("parts", []))


def _closure(fn, *a):
    async def run(args):
        return await fn(*a, args)
    return run


_tools_cache: tuple[float, list] = (0.0, [])


async def get_tools() -> list["Tool"]:
    """Tools montadas uma vez e reaproveitadas (antes: listava todos os MCPs a cada mensagem). Se algum MCP
    estava fora do ar, a próxima chamada tenta de novo em vez de esperar o TTL."""
    global _tools_cache
    ts, tools = _tools_cache
    if ts and time.monotonic() - ts < TOOLS_TTL_S:
        return tools
    tools, complete = await build_tools()
    _tools_cache = (time.monotonic() if complete else 0.0, tools)
    return tools


def cost_usd(usage: dict) -> float:
    p_in, p_out = (list(PRICES) + [None, None])[:2]
    return round((usage.get("prompt_tokens", 0) * (p_in or 0) + usage.get("completion_tokens", 0) * (p_out or 0))
                 / 1_000_000, 6)


async def build_tools() -> tuple[list[Tool], bool]:
    tools: list[Tool] = []
    complete = True
    for t in SPEC.get("tools", []):
        kind = t.get("type", "http")
        if kind == "builtin" and t["name"] == "calculator":
            async def calc(args):
                return str(_calc(args["expression"]))
            tools.append(Tool("calculator", "Avalia uma expressão aritmética.",
                              {"type": "object", "properties": {"expression": {"type": "string"}},
                               "required": ["expression"]}, calc))
        elif kind == "builtin" and t["name"] == "current_time":
            async def now(args):
                return datetime.now(UTC).isoformat()
            tools.append(Tool("current_time", "Data e hora atuais (UTC).",
                              {"type": "object", "properties": {}}, now))
        elif kind == "builtin" and t["name"] == "platform_dashboard":
            tools.append(Tool(
                "platform_dashboard",
                "Consulta dados operacionais REAIS e ATUAIS do Agent Hangar (nunca invente números). "
                "kind='overview': totais e séries da plataforma. kind='agents': lista de todos os agentes. "
                "kind='agent'+slug: detalhe de um agente (spec, versões, testes, deployments, uso). "
                "kind='deployments'|'tests'|'usage'|'audit': últimos 100 registros de cada.",
                {"type": "object", "properties": {
                    "kind": {"type": "string", "enum": ["overview", "agents", "agent", "deployments",
                                                        "tests", "usage", "audit"]},
                    "slug": {"type": "string", "description": "obrigatório quando kind='agent'"}},
                 "required": ["kind"]}, _dashboard_call))
        elif kind == "http":
            tools.append(Tool(_safe(t["name"]), t.get("description", ""),
                              t.get("parameters", {"type": "object", "properties": {}}),
                              _closure(_http_tool, t)))
    for m in SPEC.get("mcps", []):
        try:
            for mt in await _mcp_list(m["url"]):
                tools.append(Tool(_safe(f"{m['name']}__{mt.name}"), mt.description or "",
                                  mt.inputSchema, _closure(_mcp_call, m["url"], mt.name)))
        except Exception as e:  # MCP fora do ar não derruba o agente
            complete = False
            print(f"[warn] MCP {m['name']} indisponível: {e}", flush=True)
    for s in SPEC.get("sub_agents_resolved", []):
        tools.append(Tool(_safe(f"ask_{s['slug']}"),
                          f"Delega ao agente '{s['name']}': {s.get('objective', '')}",
                          {"type": "object", "properties": {"message": {"type": "string"}},
                           "required": ["message"]}, _closure(_ask_sub, s)))
    return tools, complete


# ---------------------------------------------------------------- prompt / LLM
def system_prompt() -> str:
    parts = [f"Você é o agente '{SPEC.get('name', SLUG)}'.",
             f"Objetivo: {SPEC.get('objective', '')}",
             f"Saída final esperada: {SPEC.get('final_output', '')}"]
    if SPEC.get("instructions"):
        parts.append("Instruções:\n" + SPEC["instructions"])
    for sk in SPEC.get("skills_resolved", []):
        parts.append(f"## Skill: {sk['name']}\n{sk.get('content', '')}")
    return "\n\n".join(parts)


async def mock_llm(messages, tools):
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    subs = [t for t in tools if t.name.startswith("ask_")]
    if last.lower().startswith("calc:"):
        return f"[mock:{SLUG}] {_calc(last[5:].strip())}"
    if subs:
        outs = []
        for t in subs:
            outs.append(f"{t.name}: {await t.fn({'message': last})}")
        return f"[mock:{SLUG}] delegado -> " + " | ".join(outs)
    return f"[mock:{SLUG}] {last}"


async def chat(messages: list[dict]) -> tuple[str, dict, list]:
    text, usage, trace = await _chat(messages)
    usage["cost_usd"] = cost_usd(usage)
    return text, usage, trace


async def _chat(messages: list[dict]) -> tuple[str, dict, list]:
    tools = await get_tools()
    msgs = [{"role": "system", "content": system_prompt()}] + [m for m in messages if m["role"] != "system"]
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    trace: list = []
    if MODEL.startswith("mock"):
        text = await mock_llm(msgs, tools)
        n_in = sum(len(str(m["content"]).split()) for m in msgs)
        n_out = len(text.split())
        return text, {"prompt_tokens": n_in, "completion_tokens": n_out, "total_tokens": n_in + n_out}, trace
    by_name = {t.name: t for t in tools}
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"} if LLM_API_KEY else {}
    for _ in range(MAX_STEPS):
        payload = {"model": MODEL, "messages": msgs, "temperature": LLM.get("temperature", 0.2)}
        if tools:
            payload["tools"] = [t.schema() for t in tools]
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(f"{LLM_BASE_URL}/chat/completions", json=payload, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"LLM {r.status_code}: {r.text[:300]}")
        data = r.json()
        for k in usage:
            usage[k] += (data.get("usage") or {}).get(k, 0)
        msg = data["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return msg.get("content") or "", usage, trace
        msgs.append(msg)
        for call in calls:
            name = call["function"]["name"]
            args = {}
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
                out = await by_name[name].fn(args) if name in by_name else f"tool {name} inexistente"
            except Exception as e:
                out = f"erro: {e}"
            trace.append({"tool": name, "args": args, "result": str(out)[:300]})
            msgs.append({"role": "tool", "tool_call_id": call["id"], "content": str(out)})
    return "Limite de passos de ferramentas atingido.", usage, trace


# ---------------------------------------------------------------- MCP (o agente como ferramenta)
# stateless_http=True evita o handshake de sessão do Streamable HTTP (Mcp-Session-Id): cada chamada
# é autocontida, o que permite expor isso atrás do proxy genérico da central sem tratamento especial.
_MCP_TOOL_NAME = _safe(SLUG).strip("_") or "agent"
agent_mcp = FastMCP(
    SPEC.get("name", SLUG),
    instructions=f"Ferramenta do agente '{SPEC.get('name', SLUG)}' do Agent Hangar.\nObjetivo: "
                 f"{SPEC.get('objective', '')}\nSaída esperada: {SPEC.get('final_output', '')}",
    stateless_http=True, json_response=True, streamable_http_path="/mcp",
    # A proteção contra DNS rebinding do SDK valida o header Host contra uma allowlist; o hostname do
    # container (agent-<slug>-<env>) é dinâmico e este endpoint só é alcançado via proxy autenticado da
    # central ou de dentro da própria rede Docker — a barreira de confiança já existe em outra camada.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@agent_mcp.tool(name=_MCP_TOOL_NAME,
                description=(f"{SPEC.get('objective', '')} Devolve: {SPEC.get('final_output', '')}").strip())
async def _agent_mcp_tool(message: str) -> str:
    """Envia uma mensagem/tarefa ao agente (usa as mesmas instruções, skills, MCPs e tools configurados
    nele) e devolve a resposta final."""
    text, _usage, _trace = await chat([{"role": "user", "content": message}])
    return text


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with agent_mcp.session_manager.run():
        yield


app = FastAPI(title=f"agent-{SLUG}", lifespan=lifespan)


# ---------------------------------------------------------------- endpoints
@app.get("/health")
def health():
    return {"status": "ok", "agent": SLUG, "env": ENV, "model": MODEL}


@app.get("/v1/models")
def models():
    return {"object": "list", "data": [{"id": SLUG, "object": "model", "owned_by": "agent-hangar"}]}


@app.post("/v1/chat/completions")
async def chat_completions(req: Request):
    body = await req.json()
    try:
        text, usage, trace = await chat(body.get("messages", []))
    except Exception as e:
        return JSONResponse({"error": {"message": str(e), "type": "agent_error"}}, status_code=502)
    cid, created = f"chatcmpl-{uuid.uuid4().hex[:12]}", int(time.time())
    if body.get("stream"):
        def chunk(delta, finish=None, extra=None):
            d = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": SLUG,
                 "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            return "data: " + json.dumps({**d, **(extra or {})}) + "\n\n"

        async def sse():  # resposta já pronta, enviada como stream (compat. com clientes que exigem SSE)
            yield chunk({"role": "assistant", "content": ""})
            yield chunk({"content": text})
            yield chunk({}, "stop", {"usage": usage})
            yield "data: [DONE]\n\n"
        return StreamingResponse(sse(), media_type="text/event-stream")
    return {"id": cid, "object": "chat.completion",
            "created": created, "model": SLUG,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}],
            "usage": usage, "x_trace": trace}


def _card():
    return {"protocolVersion": "0.3.0", "name": SPEC.get("name", SLUG),
            "description": SPEC.get("objective", ""), "url": f"{PUBLIC_URL}/a2a",
            "preferredTransport": "JSONRPC", "version": str(SPEC.get("version", 1)),
            "capabilities": {"streaming": False, "pushNotifications": False},
            "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
            "skills": [{"id": s["name"], "name": s["name"], "description": s.get("description", ""),
                        "tags": []} for s in SPEC.get("skills_resolved", [])]
                      or [{"id": SLUG, "name": SPEC.get("name", SLUG),
                           "description": SPEC.get("final_output", ""), "tags": []}]}


@app.get("/.well-known/agent.json")
@app.get("/.well-known/agent-card.json")
def agent_card():
    return _card()


@app.post("/a2a")
async def a2a(req: Request):
    body = await req.json()
    rid = body.get("id")
    if body.get("method") not in ("message/send", "SendMessage"):
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}}
    parts = body.get("params", {}).get("message", {}).get("parts", [])
    text_in = "".join(p.get("text", "") for p in parts)
    try:
        text, usage, _ = await chat([{"role": "user", "content": text_in}])
    except Exception as e:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": str(e)}}
    return {"jsonrpc": "2.0", "id": rid, "result": {
        "kind": "message", "role": "agent", "messageId": str(uuid.uuid4()),
        "parts": [{"kind": "text", "text": text}], "metadata": {"usage": usage}}}


@app.get("/acp/agents")
def acp_agents():
    return {"agents": [{"name": SLUG, "description": SPEC.get("objective", ""),
                        "metadata": {"framework": "agent-hangar", "version": SPEC.get("version", 1)}}]}


@app.get("/acp/agents/{name}")
def acp_agent(name: str):
    return acp_agents()["agents"][0] if name == SLUG else JSONResponse({"error": "not found"}, 404)


@app.post("/acp/runs")
async def acp_runs(req: Request):
    body = await req.json()
    text_in = "\n".join(p.get("content", "") for m in body.get("input", []) for p in m.get("parts", []))
    try:
        text, usage, _ = await chat([{"role": "user", "content": text_in}])
    except Exception as e:
        return JSONResponse({"status": "failed", "error": {"message": str(e)}}, status_code=502)
    return {"run_id": str(uuid.uuid4()), "agent_name": SLUG, "status": "completed",
            "output": [{"role": f"agent/{SLUG}",
                        "parts": [{"content_type": "text/plain", "content": text}]}],
            "metadata": {"usage": usage}}


# Por último: rotas explícitas acima têm prioridade sobre este mount (Starlette casa na ordem de
# registro). O sub-app do MCP define sua própria rota "/mcp" (streamable_http_path acima).
app.mount("/", agent_mcp.streamable_http_app())
