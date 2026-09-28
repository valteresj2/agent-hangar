"""Runtime de um agente. Cada agente = 1 container isolado desta imagem.

Protocolos expostos:
  - OpenAI-compatible : POST /v1/chat/completions, GET /v1/models
  - A2A (JSON-RPC)    : GET /.well-known/agent.json, POST /a2a  (message/send)
  - ACP (IBM/BeeAI)   : GET /acp/agents, POST /acp/runs         (compat. legado)
  - MCP               : POST /mcp — o próprio agente como servidor MCP (1 tool), para
                         Claude Desktop/Code, OpenCode etc. o usarem como ferramenta externa
"""
import ast
import asyncio
import contextvars
import hashlib
import json
import mimetypes
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
from mcp.types import CallToolResult, TextContent

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
MAX_STEPS = int(LLM.get("max_steps") or 6)
VISION = LLM.get("vision", True)  # False: imagens não vão ao LLM (só ao workspace, para OCR/análise por tool)
LLM_TIMEOUT_S = 300
TOOL_OUTPUT_LIMIT = 16000
# Sessão (conversa) do request atual: vem do cliente (X-Session-Id / X-Conversation-Id, p.ex. o id da conversa no
# LibreChat) e é repassada aos MCPs, que a usam para separar workspaces, arquivos e estado por conversa.
SESSION = contextvars.ContextVar("session", default="")
CHANNEL = contextvars.ContextVar("channel", default="")
# Progresso das tools durante o streaming (fila lida pelo gerador SSE) e modo "lite" (títulos, resumos: uma chamada
# curta ao LLM, sem tools nem prompt do agente). Ver chat_completions.
PROGRESS: contextvars.ContextVar = contextvars.ContextVar("progress", default=None)
MODE = contextvars.ContextVar("mode", default="full")
# Imagens devolvidas por tools MCP (ex.: preview_file) na rodada atual: vão ao LLM como mensagem de visão.
TOOL_IMAGES: contextvars.ContextVar = contextvars.ContextVar("tool_images", default=None)
MAX_TOOL_IMAGES = 4
PROGRESS_STREAM = os.environ.get("PROGRESS_STREAM", "reasoning")  # "off" desliga


def progress(text: str):
    q = PROGRESS.get()
    if q is not None:
        q.put_nowait(text)


_ARG_HINTS = ("query", "code", "title", "path", "url", "filename", "message", "markdown")


def _describe(name: str, args: dict) -> str:
    label = name.split("__")[-1]
    hint = next((str(args[k]) for k in _ARG_HINTS if args.get(k)), "")
    hint = " ".join(hint.strip().splitlines()[:1])[:140]
    return f"🔧 {label}" + (f": {hint}" if hint else "")
# Clientes que renderizam LaTeX com $…$ (LibreChat) transformam "R$ 10 … R$ 20" em fórmula. Para eles, o $ de
# valores monetários sai escapado (\$), que o markdown exibe como "$". Fórmulas ($x^2$) não são afetadas.
LATEX_DOLLAR_CHANNELS = {c.strip() for c in os.environ.get("LATEX_DOLLAR_CHANNELS", "librechat,open-webui").split(",") if c}
_CURRENCY = re.compile(r"(?<![\\$])\$(?=\s?-?\d)")


def render_for_channel(text: str) -> str:
    if CHANNEL.get() in LATEX_DOLLAR_CHANNELS and "$" in text:
        return _CURRENCY.sub(r"\\$", text)
    return text
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
    def __init__(self, name, description, parameters, fn, hidden=False):
        self.name, self.description, self.parameters, self.fn = name, description, parameters, fn
        # hidden: usada só pelo runtime (ex.: ingest_file recebe os anexos), não é oferecida ao LLM
        self.hidden = hidden

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


def _mcp_headers() -> dict:
    h = {"X-Agent-Slug": SLUG}
    if SESSION.get():
        h["X-Session-Id"] = SESSION.get()
    return h


async def _mcp_call(url, tool, args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(url, headers=_mcp_headers(), timeout=900, sse_read_timeout=900) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(tool, args)
            images = TOOL_IMAGES.get()
            texts = []
            for c in res.content:
                if getattr(c, "type", "") == "image":
                    if images is not None:
                        images.append((c.mimeType or "image/png", c.data))
                    continue
                texts.append(getattr(c, "text", str(c)))
            text = "\n".join(texts)
            if len(text) > TOOL_OUTPUT_LIMIT:
                text = text[:TOOL_OUTPUT_LIMIT] + f"\n… [truncado: {len(text)} caracteres]"
            return ("ERRO DA FERRAMENTA: " + text) if res.isError else text


async def _mcp_list(url):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(url, headers=_mcp_headers()) as (r, w, _):
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
                                  mt.inputSchema, _closure(_mcp_call, m["url"], mt.name),
                                  hidden=mt.name == "ingest_file"))
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


def text_of(content) -> str:
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return content or ""


# ---------------------------------------------------------------- anexos (imagens, PDFs, planilhas…)
_ingested: dict[tuple[str, str], str] = {}


def _data_url(url: str) -> tuple[str, str] | None:
    if not isinstance(url, str) or not url.startswith("data:") or "," not in url:
        return None
    head, b64 = url.split(",", 1)
    return head[5:].split(";")[0] or "application/octet-stream", b64


async def prepare_attachments(messages: list[dict], tools: list[Tool]) -> list[dict]:
    """Notas em formato neutro ([📎 arquivo → workspace: nome]): texto em português aqui fazia o modelo responder em
    português a um usuário que escreveu em inglês.

    Anexos no formato OpenAI ({type:'image_url'} e {type:'file', file:{filename, file_data}}), como o LibreChat
    envia, são gravados no workspace via a tool `ingest_file` de um MCP do agente (se houver) e trocados por uma
    nota com o nome do arquivo. Imagens continuam indo ao LLM (visão), a menos que llm.vision=false."""
    ingest = next((t for t in tools if t.name.endswith("__ingest_file")), None)
    out = []
    for m in messages:
        content = m.get("content")
        if m.get("role") != "user" or not isinstance(content, list):
            out.append(m)
            continue
        parts, notes = [], []
        for part in content:
            kind = part.get("type") if isinstance(part, dict) else None
            if kind == "image_url":
                url = (part.get("image_url") or {}).get("url", "")
                name, du = None, _data_url(url)
                if du and ingest:
                    ext = mimetypes.guess_extension(du[0]) or ".png"
                    name = await _ingest(ingest, f"imagem_{hashlib.sha256(du[1].encode()).hexdigest()[:8]}{ext}", du)
                if name:
                    notes.append(f"[📎 image → workspace: {name}]")
                if VISION:
                    parts.append(part)
            elif kind in ("file", "input_file"):
                f = part.get("file") or part
                du = _data_url(f.get("file_data", ""))
                fname = f.get("filename") or "arquivo"
                if du and ingest:
                    name = await _ingest(ingest, fname, du)
                    notes.append(f"[📎 {fname} ({du[0]}) → workspace: {name}]"
                                 if name else f"[📎 {fname} → workspace: ERROR (not saved)]")
                else:
                    notes.append(f"[📎 {fname} → no workspace (this agent has no file tools)]")
            elif kind == "text":
                parts.append(part)
        if notes:
            parts.insert(0, {"type": "text", "text": "\n".join(notes)})
        if all(p.get("type") == "text" for p in parts):
            out.append({**m, "content": "\n".join(p["text"] for p in parts)})
        else:
            out.append({**m, "content": parts})
    return out


async def _ingest(tool: Tool, filename: str, du: tuple[str, str]) -> str | None:
    key = (SESSION.get(), hashlib.sha256(du[1].encode()).hexdigest())
    if key in _ingested:
        return _ingested[key]
    try:
        res = await tool.fn({"filename": filename, "data_base64": du[1], "mime_type": du[0]})
        name = json.loads(res).get("path") if res.strip().startswith("{") else None
    except Exception as e:
        print(f"[warn] ingest_file falhou para {filename}: {e}", flush=True)
        return None
    if name:
        _ingested[key] = name
    return name


async def mock_llm(messages, tools):
    last = next((text_of(m["content"]) for m in reversed(messages) if m["role"] == "user"), "")
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
    text, usage, trace = await (_lite(messages) if MODE.get() == "lite" else _chat(messages))
    usage["cost_usd"] = cost_usd(usage)
    return text, usage, trace


async def _lite(messages: list[dict]) -> tuple[str, dict, list]:
    """Uma chamada curta, sem tools e sem o prompt do agente — para títulos de conversa e tarefas triviais do
    cliente (o LibreChat manda os títulos por um endpoint com X-Hangar-Mode: lite)."""
    msgs = [{"role": "system", "content": f"Você é o assistente '{SPEC.get('name', SLUG)}'. Responda de forma "
                                          "direta e curta, sem usar ferramentas."}]
    msgs += [{"role": m["role"], "content": text_of(m.get("content"))} for m in messages
             if m.get("role") in ("system", "user", "assistant")][-6:]
    if MODEL.startswith("mock"):
        text = f"[mock:{SLUG}] {text_of(msgs[-1]['content'])[:60]}"
        return text, {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}, []
    headers = {"Authorization": f"Bearer {LLM_API_KEY}"} if LLM_API_KEY else {}
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    # modelos com raciocínio gastam tokens antes do texto: um teto baixo devolve conteúdo vazio. 1500 costuma
    # sobrar; se ainda vier vazio, uma segunda tentativa sem teto.
    for limit in (1500, None):
        payload = {"model": MODEL, "messages": msgs, "temperature": 0.2}
        if limit:
            payload["max_tokens"] = limit
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=payload)
        if r.status_code >= 400:
            raise RuntimeError(f"LLM {r.status_code}: {r.text[:300]}")
        data = r.json()
        for k in usage:
            usage[k] += (data.get("usage") or {}).get(k, 0)
        text = (data["choices"][0]["message"].get("content") or "").strip()
        if text:
            return text, usage, []
    return "", usage, []


async def _chat(messages: list[dict]) -> tuple[str, dict, list]:
    tools = await get_tools()
    messages = await prepare_attachments(messages, tools)
    # instruções de sistema do cliente (ex.: o prompt de Artifacts do LibreChat) vêm depois das do agente
    client_sys = "\n\n".join(text_of(m["content"]) for m in messages if m["role"] == "system")
    sys_prompt = system_prompt() + (f"\n\n## Instruções do cliente\n{client_sys}" if client_sys.strip() else "")
    msgs = [{"role": "system", "content": sys_prompt}] + [m for m in messages if m["role"] != "system"]
    llm_tools = [t for t in tools if not t.hidden]
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
        if llm_tools:
            payload["tools"] = [t.schema() for t in llm_tools]
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_S) as c:
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
        step_images: list = []
        TOOL_IMAGES.set(step_images)
        for call in calls:
            name = call["function"]["name"]
            args = {}
            t_call = time.monotonic()
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
                progress(_describe(name, args))
                out = await by_name[name].fn(args) if name in by_name else f"tool {name} inexistente"
            except Exception as e:
                out = f"erro: {e}"
            failed = str(out).startswith(("erro", "ERRO DA FERRAMENTA", "tool "))
            progress(f" {'✗' if failed else '✓'} {time.monotonic() - t_call:.1f}s\n")
            trace.append({"tool": name, "args": {k: (str(v)[:200]) for k, v in args.items()},
                          "result": str(out)[:300]})
            msgs.append({"role": "tool", "tool_call_id": call["id"], "content": str(out)})
        if step_images and VISION:
            parts = [{"type": "text", "text": f"Imagens devolvidas pelas ferramentas nesta etapa ({len(step_images)}), "
                                              "para você conferir visualmente:"}]
            parts += [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
                      for mime, b64 in step_images[:MAX_TOOL_IMAGES]]
            msgs.append({"role": "user", "content": parts})
    # passos esgotados: uma última chamada SEM tools para o modelo resumir o que já tem
    msgs.append({"role": "user", "content": "Limite de passos atingido. Responda agora com o que já foi obtido, "
                                            "incluindo links de arquivos gerados, e diga o que ficou pendente."})
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_S) as c:
        r = await c.post(f"{LLM_BASE_URL}/chat/completions", headers=headers,
                         json={"model": MODEL, "messages": msgs, "temperature": LLM.get("temperature", 0.2)})
    if r.status_code >= 400:
        return "Limite de passos de ferramentas atingido.", usage, trace
    data = r.json()
    for k in usage:
        usage[k] += (data.get("usage") or {}).get(k, 0)
    return data["choices"][0]["message"].get("content") or "", usage, trace


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
async def _agent_mcp_tool(message: str) -> CallToolResult:
    """Envia uma mensagem/tarefa ao agente (usa as mesmas instruções, skills, MCPs e tools configurados
    nele) e devolve a resposta final."""
    text, usage, _trace = await chat([{"role": "user", "content": message}])
    # o cliente vê só o texto; tokens/custo vão em _meta, que o gateway do hangar lê para as métricas
    return CallToolResult(content=[TextContent(type="text", text=text)], _meta={"usage": usage})


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


def set_session(req: Request, body: dict | None = None):
    """Sessão = X-Session-Id, ou X-Conversation-Id (LibreChat: {{LIBRECHAT_BODY_CONVERSATIONID}}), ou o campo
    `user` do corpo OpenAI. Sem nenhum deles, fica vazia (os MCPs usam um workspace padrão)."""
    h = req.headers
    sid = h.get("x-session-id") or h.get("x-conversation-id") or h.get("x-openwebui-chat-id") or ""
    if not sid or sid in ("new", "null", "undefined") or sid.startswith("{{"):
        sid = (body or {}).get("user") or h.get("x-user-id") or h.get("x-openwebui-user-id") or ""
    SESSION.set(str(sid)[:200])
    CHANNEL.set(h.get("x-channel", "").lower())
    MODE.set("lite" if h.get("x-hangar-mode", "").lower() == "lite" else "full")


@app.post("/v1/chat/completions")
async def chat_completions(req: Request):
    body = await req.json()
    set_session(req, body)
    cid, created = f"chatcmpl-{uuid.uuid4().hex[:12]}", int(time.time())
    if body.get("stream"):
        def chunk(delta, finish=None, extra=None):
            d = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": SLUG,
                 "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            return "data: " + json.dumps({**d, **(extra or {})}, ensure_ascii=False) + "\n\n"

        # O agente trabalha (várias chamadas de tool) antes de ter a resposta. Enquanto isso: cada tool vira uma
        # linha em `reasoning_content` (clientes como o LibreChat mostram num bloco recolhível de "pensamento",
        # fora da resposta) e, sem novidade por 10s, um comentário SSE de keepalive segura a conexão.
        queue: asyncio.Queue = asyncio.Queue()
        show = PROGRESS_STREAM != "off" and req.headers.get("x-progress", "").lower() != "off"
        PROGRESS.set(queue if show else None)
        task = asyncio.create_task(chat(body.get("messages", [])))

        async def sse():
            yield chunk({"role": "assistant", "content": ""})
            while not task.done() or not queue.empty():
                getter = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({getter, task}, timeout=10, return_when=asyncio.FIRST_COMPLETED)
                if getter in done:
                    yield chunk({"reasoning_content": getter.result()})
                    continue
                getter.cancel()
                if not done:
                    yield ": keepalive\n\n"
            try:
                text, usage, _trace = task.result()
            except Exception as e:
                yield chunk({"content": f"Erro no agente: {e}"}, "stop")
                yield "data: [DONE]\n\n"
                return
            yield chunk({"content": render_for_channel(text)})
            yield chunk({}, "stop", {"usage": usage})
            yield "data: [DONE]\n\n"
        return StreamingResponse(sse(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    try:
        text, usage, trace = await chat(body.get("messages", []))
    except Exception as e:
        return JSONResponse({"error": {"message": str(e), "type": "agent_error"}}, status_code=502)
    text = render_for_channel(text)
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
    set_session(req, {"user": body.get("params", {}).get("message", {}).get("contextId")})
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
    set_session(req, {"user": body.get("session_id")})
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
