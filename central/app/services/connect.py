"""Conexões plug and play de um agente com ferramentas agênticas.

Dois modos, opcionais e independentes por ferramenta:
- "mcp": o agente vira uma FERRAMENTA (1 tool MCP) do cliente (Claude Code/Desktop, Codex, OpenCode, Cursor, VS Code,
  LibreChat, Open WebUI…) — o LLM do cliente decide quando chamá-lo;
- "model": o agente vira um MODELO no seletor do cliente de chat (LibreChat, Open WebUI, OpenCode, SDKs OpenAI) — ele
  conduz a conversa, recebe anexos e usa as próprias tools.
Cada conexão tem a sua chave (escopo invoke, só aquele agente, marcada com cliente/modo): revogável sozinha, e o
uso aparece por ferramenta nas métricas mesmo quando o cliente não manda X-Channel.
"""
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, config
from ..models import ApiKey
from .common import PlatformError, audit, get_agent

MODES = ("mcp", "model")
KEY_PLACEHOLDER = "<SUA_CHAVE>"

# id -> (rótulo, modos suportados, nota)
CLIENTS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "claude-code": ("Claude Code", ("mcp",), "CLI da Anthropic. O agente vira uma ferramenta que o Claude chama."),
    "claude-desktop": ("Claude Desktop", ("mcp",), "App desktop, via mcp-remote (precisa de Node.js)."),
    "codex": ("Codex CLI", ("mcp",), "CLI da OpenAI (~/.codex/config.toml)."),
    "opencode": ("OpenCode", ("mcp", "model"), "Como ferramenta (MCP) ou como modelo (provedor OpenAI-compatible)."),
    "cursor": ("Cursor", ("mcp",), "IDE: .cursor/mcp.json (no projeto) ou ~/.cursor/mcp.json (global)."),
    "vscode": ("VS Code (Copilot)", ("mcp",), "Agent mode do Copilot: .vscode/mcp.json."),
    "librechat": ("LibreChat", ("model", "mcp"), "Como modelo (recomendado: anexos, workspace por conversa, "
                                                 "progresso ao vivo) ou como ferramenta MCP."),
    "open-webui": ("Open WebUI", ("model", "mcp"), "Como modelo (conexão OpenAI) ou como ferramenta (MCP)."),
    "openai-sdk": ("SDK OpenAI / outros", ("model",), "Qualquer cliente OpenAI-compatible (Python, JS, n8n…)."),
    "generic-mcp": ("Outro cliente MCP", ("mcp",), "Qualquer cliente MCP com Streamable HTTP e cabeçalhos."),
}


def clients() -> list[dict]:
    return [{"id": k, "label": v[0], "modes": list(v[1]), "note": v[2]} for k, v in CLIENTS.items()]


def _name(slug: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", slug)


def snippet(client: str, mode: str, slug: str, agent_name: str, key: str = KEY_PLACEHOLDER) -> dict:
    """Configuração pronta para colar: {language, file, content, steps}."""
    if client not in CLIENTS:
        raise PlatformError(f"cliente desconhecido: {client}. Opções: {sorted(CLIENTS)}")
    if mode not in CLIENTS[client][1]:
        raise PlatformError(f"{CLIENTS[client][0]} não suporta o modo '{mode}' (suporta: {list(CLIENTS[client][1])})")
    base = config.PUBLIC_BASE_URL
    mcp_url, v1 = f"{base}/gw/{slug}/mcp", f"{base}/gw/{slug}/v1"
    name = _name(slug)
    hdr = {"Authorization": f"Bearer {key}", "X-Channel": client}
    in_docker = base.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")

    if mode == "mcp":
        if client == "claude-code":
            return {"language": "bash", "file": None, "steps": ["Rode no terminal (escopo do usuário; troque "
                                                                 "--scope user por project para só este projeto)."],
                    "content": f'claude mcp add --transport http --scope user {name} {mcp_url} '
                               f'--header "Authorization: Bearer {key}" --header "X-Channel: claude-code"'}
        if client == "claude-desktop":
            cfg = {"mcpServers": {name: {"command": "npx", "args": [
                "-y", "mcp-remote", mcp_url, "--header", f"Authorization: Bearer {key}",
                "--header", "X-Channel: claude-desktop", *(["--allow-http"] if mcp_url.startswith("http:") else [])]}}}
            return {"language": "json", "file": "claude_desktop_config.json",
                    "steps": ["Claude Desktop → Settings → Developer → Edit Config.",
                              "Mescle o bloco em mcpServers e reinicie o Claude Desktop."],
                    "content": json.dumps(cfg, indent=2, ensure_ascii=False)}
        if client == "codex":
            return {"language": "toml", "file": "~/.codex/config.toml",
                    "steps": ["Acrescente ao ~/.codex/config.toml e reinicie o Codex."],
                    "content": f'[mcp_servers.{name.replace("-", "_")}]\nurl = "{mcp_url}"\n'
                               f'http_headers = {{ Authorization = "Bearer {key}", X-Channel = "codex" }}\n'}
        if client == "opencode":
            cfg = {"$schema": "https://opencode.ai/config.json",
                   "mcp": {name: {"type": "remote", "url": mcp_url, "enabled": True, "headers": hdr}}}
            return {"language": "json", "file": "opencode.json (projeto) ou ~/.config/opencode/opencode.json",
                    "steps": ["Mescle o bloco no opencode.json."], "content": json.dumps(cfg, indent=2)}
        if client == "cursor":
            return {"language": "json", "file": ".cursor/mcp.json",
                    "steps": ["Mescle em .cursor/mcp.json; o servidor aparece em Settings → MCP."],
                    "content": json.dumps({"mcpServers": {name: {"url": mcp_url, "headers": hdr}}}, indent=2)}
        if client == "vscode":
            return {"language": "json", "file": ".vscode/mcp.json",
                    "steps": ["Mescle em .vscode/mcp.json e habilite o servidor no Copilot Chat (modo Agent)."],
                    "content": json.dumps({"servers": {name: {"type": "http", "url": mcp_url, "headers": hdr}}},
                                          indent=2)}
        if client == "librechat":
            content = (f"mcpServers:\n  {name}:\n    type: streamable-http\n"
                       f'    url: "{in_docker}/gw/{slug}/mcp"\n    headers:\n'
                       f'      Authorization: "Bearer {key}"\n      X-Channel: "librechat"\n'
                       f'      X-Conversation-Id: "{{{{LIBRECHAT_BODY_CONVERSATIONID}}}}"\n')
            return {"language": "yaml", "file": "librechat.yaml",
                    "steps": ["Acrescente ao librechat.yaml e reinicie o LibreChat.",
                              "No chat, ative o servidor pelo seletor de MCP (ícone de ferramentas)."],
                    "content": content}
        if client == "open-webui":
            return {"language": "text", "file": None,
                    "steps": ["Open WebUI → Admin Panel → Settings → External Tools → + (Add Connection).",
                              "Type: MCP (Streamable HTTP); URL e chave abaixo; Auth: Bearer.",
                              "Habilite a ferramenta no modelo (Workspace → Models) ou no chat."],
                    "content": f"URL:   {in_docker}/gw/{slug}/mcp\nAuth:  Bearer\nKey:   {key}\n"}
        return {"language": "text", "file": None,
                "steps": ["Cliente MCP genérico: transporte Streamable HTTP, servidor stateless (sem sessão)."],
                "content": f"URL: {mcp_url}\nHeaders:\n  Authorization: Bearer {key}\n  X-Channel: {client}\n"
                           f"Tool: {name} (argumento: message)\n"}

    # ---------------------------------------------------------------- modo modelo
    if client == "librechat":
        content = (f'endpoints:\n  custom:\n    - name: "{agent_name}"\n      apiKey: "{key}"\n'
                   f'      baseURL: "{in_docker}/gw/{slug}/v1"\n'
                   f'      models:\n        default: ["{slug}"]\n        fetch: false\n'
                   f'      titleConvo: true\n      titleEndpoint: "{agent_name} (títulos)"\n'
                   f'      headers:\n        X-Channel: "librechat"\n'
                   f'        X-Conversation-Id: "{{{{LIBRECHAT_BODY_CONVERSATIONID}}}}"   # workspace por conversa\n'
                   f'        X-User-Id: "{{{{LIBRECHAT_USER_ID}}}}"\n'
                   f'      dropParams: ["stop", "frequency_penalty", "presence_penalty", "top_p", "user"]\n'
                   f'    - name: "{agent_name} (títulos)"          # títulos baratos: 1 chamada, sem ferramentas\n'
                   f'      apiKey: "{key}"\n      baseURL: "{in_docker}/gw/{slug}/v1"\n'
                   f'      models:\n        default: ["{slug}"]\n        fetch: false\n      titleConvo: false\n'
                   f'      headers:\n        X-Hangar-Mode: "lite"\n        X-Channel: "librechat-title"\n'
                   f'fileConfig:\n  endpoints:\n    "{agent_name}":                 # anexos chegam ao agente\n'
                   f'      supportedMimeTypes: ["^image/.*", "^text/.*", "^application/.*"]\n')
        return {"language": "yaml", "file": "librechat.yaml",
                "steps": ["Mescle no librechat.yaml e reinicie o LibreChat.",
                          "Opcional: modelSpecs.enforce: true esconde o endpoint de títulos do seletor.",
                          "Kit completo pronto: integrations/librechat no repositório."],
                "content": content}
    if client == "open-webui":
        return {"language": "text", "file": None,
                "steps": ["Open WebUI → Admin Panel → Settings → Connections → OpenAI API → +.",
                          f"Model IDs: adicione {slug} (ou deixe o Open WebUI listar via /models).",
                          "Para workspace por conversa, rode o Open WebUI com ENABLE_FORWARD_USER_INFO_HEADERS=true "
                          "(o id do chat vira a sessão do agente)."],
                "content": f"URL:  {in_docker}/gw/{slug}/v1\nKey:  {key}\nModel: {slug}\n"}
    if client == "opencode":
        cfg = {"$schema": "https://opencode.ai/config.json", "provider": {"hangar": {
            "npm": "@ai-sdk/openai-compatible", "name": "Agent Hangar",
            "options": {"baseURL": v1, "apiKey": key, "headers": {"X-Channel": "opencode"}},
            "models": {slug: {"name": agent_name}}}}}
        return {"language": "json", "file": "opencode.json",
                "steps": ["Mescle no opencode.json e escolha o modelo com /models."],
                "content": json.dumps(cfg, indent=2, ensure_ascii=False)}
    return {"language": "python", "file": None,
            "steps": ["Qualquer SDK/cliente OpenAI-compatible (stream suportado)."],
            "content": f'from openai import OpenAI\n\nclient = OpenAI(base_url="{v1}", api_key="{key}",\n'
                       f'                default_headers={{"X-Channel": "openai-sdk"}})\n'
                       f'r = client.chat.completions.create(model="{slug}",\n'
                       f'                                   messages=[{{"role": "user", "content": "Olá!"}}])\n'
                       f'print(r.choices[0].message.content)\n'}


def connect(db: Session, slug: str, client: str, mode: str, actor: str = "admin") -> dict:
    """Cria a chave da conexão (invoke, só este agente) e devolve o trecho pronto com ela preenchida."""
    a = get_agent(db, slug)
    snippet(client, mode, a.slug, a.name)  # valida cliente/modo antes de criar a chave
    row, raw = auth.create_api_key(db, f"{a.slug} · {CLIENTS[client][0]} ({mode})"[:100], ["invoke"], [a.slug],
                                   actor, client=client, mode=mode)
    audit(db, actor, "agent.connect", a.slug, f"{client} ({mode}) chave #{row.id}")
    return {"connection": connection_dict(row), "key": raw, **snippet(client, mode, a.slug, a.name, raw),
            "note": "A chave aparece só agora; revogar a conexão desliga só esta ferramenta."}


def connection_dict(k: ApiKey) -> dict:
    label = CLIENTS.get(k.client or "", (k.client or "?",))[0]
    return {**auth.api_key_dict(k), "client_label": label}


def connections(db: Session, slug: str) -> list[dict]:
    rows = db.scalars(select(ApiKey).where(ApiKey.client.is_not(None), ApiKey.revoked_at.is_(None))
                      .order_by(ApiKey.id.desc()))
    return [connection_dict(k) for k in rows if k.agents == [slug]]
