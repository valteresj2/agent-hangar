"""Catálogo reutilizável: skills, MCP servers e conexões de LLM (e a resolução delas para um agente)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, crypto
from ..models import Agent, LlmConnection, McpServer, Skill
from .common import PlatformError, audit, iso, spec_of

PROTOCOLS = ("openai", "anthropic", "deepseek")

# Cada harness exige uma conexão do protocolo que ele fala nativamente. claude-code fala a API de Mensagens
# da Anthropic; codex e hermes falam o formato da OpenAI (provedor real ou gateway: LiteLLM, OpenRouter…);
# deepseek-harness só tem caminho verificado contra a API oficial da DeepSeek.
HARNESS_PROTOCOL = {"claude-code": "anthropic", "codex": "openai", "hermes": "openai",
                    "deepseek-harness": "deepseek"}


# ------------------------------------------------------------------ skills e MCPs
def upsert_skill(db: Session, name, description, content, actor="admin"):
    s = db.scalar(select(Skill).where(Skill.name == name)) or Skill(name=name)
    s.description, s.content = description or "", content or ""
    db.add(s)
    db.commit()
    audit(db, actor, "skill.upsert", name)
    return s


def upsert_mcp(db: Session, name, url, description="", actor="admin"):
    if not url.startswith(("http://", "https://")):
        raise PlatformError("url do MCP deve ser http(s) (Streamable HTTP)")
    m = db.scalar(select(McpServer).where(McpServer.name == name)) or McpServer(name=name)
    m.url, m.description = url, description or ""
    db.add(m)
    db.commit()
    audit(db, actor, "mcp.upsert", name, url)
    return m


# ------------------------------------------------------------------ conexões de LLM
def upsert_llm_connection(db: Session, name, base_url, model_name, api_key="", description="", actor="admin",
                          protocol="openai", price_in_per_mtok=None, price_out_per_mtok=None) -> LlmConnection:
    if not (name and base_url and model_name):
        raise PlatformError("name, base_url e model_name são obrigatórios")
    if not base_url.startswith(("http://", "https://")):
        raise PlatformError("base_url deve ser uma URL http(s), ex.: https://openrouter.ai/api/v1")
    if protocol not in PROTOCOLS:
        raise PlatformError("protocol deve ser 'openai' (chat, codex, hermes), 'anthropic' (harness claude-code) "
                            "ou 'deepseek' (harness deepseek-harness, API nativa da DeepSeek)")
    c = db.scalar(select(LlmConnection).where(LlmConnection.name == name)) or LlmConnection(name=name)
    c.base_url, c.model_name, c.description, c.protocol = base_url.rstrip("/"), model_name, description or "", protocol
    c.price_in_per_mtok, c.price_out_per_mtok = price_in_per_mtok, price_out_per_mtok
    if api_key:  # reenviar vazio preserva a chave atual (útil para só trocar a URL/modelo)
        c.api_key = crypto.encrypt(api_key)
    db.add(c)
    db.commit()
    audit(db, actor, "llm_connection.upsert", name, f"{base_url} · {model_name} · {protocol}")
    return c


def delete_llm_connection(db: Session, name, actor="admin"):
    c = db.scalar(select(LlmConnection).where(LlmConnection.name == name))
    if not c:
        raise PlatformError(f"Conexão '{name}' não encontrada")
    in_use = [a.slug for a in db.scalars(select(Agent)) if uses_connection(spec_of(a), name)]
    if in_use:
        raise PlatformError(f"Conexão em uso por: {', '.join(in_use)}. Troque o LLM desses agentes antes.")
    db.delete(c)
    db.commit()
    audit(db, actor, "llm_connection.delete", name)


def uses_connection(spec: dict, name: str) -> bool:
    names = set()
    for block_key in ("llm", "harness", "judge"):
        block = spec.get(block_key) or {}
        names.add(block.get("connection"))
        for e in ("stage", "prod"):
            if isinstance(block.get(e), dict):
                names.add(block[e].get("connection"))
    return name in names


def mask_key(k: str) -> str:
    try:
        plain = crypto.decrypt(k)
    except Exception:
        return "····"
    return f"····{plain[-4:]}" if len(plain) > 4 else ("····" if plain else "")


def llm_connection_dict(c: LlmConnection) -> dict:
    """Nunca devolve a chave — só os 4 últimos caracteres, para o admin reconhecer qual é."""
    return {"name": c.name, "base_url": c.base_url, "model_name": c.model_name, "description": c.description,
            "protocol": c.protocol, "api_key": mask_key(c.api_key), "has_key": bool(c.api_key),
            "price_in_per_mtok": c.price_in_per_mtok, "price_out_per_mtok": c.price_out_per_mtok,
            "created_at": iso(c.created_at)}


def get_connection(db: Session, name: str) -> LlmConnection:
    conn = db.scalar(select(LlmConnection).where(LlmConnection.name == name))
    if not conn:
        raise PlatformError(f"Conexão de LLM '{name}' não está no catálogo. Use register_llm_connection.")
    return conn


def resolve_llm(db: Session, spec: dict, env: str) -> dict:
    """LlmConnection do catálogo (com override por ambiente) -> {connection, base_url, api_key, model,
    temperature} prontos para o container do agente de chat."""
    llm = spec.get("llm") or {}
    override = llm.get(env) if isinstance(llm.get(env), dict) else {}
    conn_name = override.get("connection") or llm.get("connection") or ""
    model = override.get("model") or llm.get("model") or ""
    temperature = override.get("temperature", llm.get("temperature", 0.2))
    if not conn_name:
        return {"connection": "", "base_url": "", "api_key": "", "model": model or config.DEFAULT_MODEL,
                "temperature": temperature, "prices": (None, None)}
    conn = get_connection(db, conn_name)
    if conn.protocol != "openai":
        raise PlatformError(
            f"Conexão '{conn_name}' é protocol='{conn.protocol}'; agentes de chat precisam de uma conexão "
            "protocol='openai' (endpoint /v1/chat/completions).")
    return {"connection": conn.name, "base_url": conn.base_url, "api_key": crypto.decrypt(conn.api_key),
            "model": model or conn.model_name, "temperature": temperature,
            "prices": (conn.price_in_per_mtok, conn.price_out_per_mtok)}


def resolve_harness(db: Session, spec: dict, env: str) -> dict:
    """Harness (claude-code | codex | hermes | deepseek-harness) + a conexão que o alimenta, com override
    por ambiente. Sem `connection`, o job roda em modo mock (sem chamar LLM nenhum)."""
    h = spec.get("harness") or {}
    if not h.get("id"):
        raise PlatformError("Agente sem harness configurado. Use design_agent(harness={'id':"
                            "'claude-code'|'codex'|'hermes'|'deepseek-harness','connection':'<nome>'}).")
    override = h.get(env) if isinstance(h.get(env), dict) else {}
    harness_id = override.get("id") or h.get("id")
    if harness_id not in HARNESS_PROTOCOL:
        raise PlatformError(f"Harness '{harness_id}' desconhecido. Opções: {sorted(HARNESS_PROTOCOL)}")
    conn_name = override.get("connection") or h.get("connection") or ""
    if not conn_name:
        return {"harness_id": harness_id, "connection": "", "base_url": "", "api_key": "", "model": "",
                "mock": True, "prices": (None, None)}
    conn = get_connection(db, conn_name)
    wanted = HARNESS_PROTOCOL[harness_id]
    if conn.protocol != wanted:
        raise PlatformError(f"Conexão '{conn_name}' é protocol='{conn.protocol}'; o harness '{harness_id}' "
                            f"precisa de uma conexão protocol='{wanted}'.")
    return {"harness_id": harness_id, "connection": conn.name, "base_url": conn.base_url,
            "api_key": crypto.decrypt(conn.api_key), "model": conn.model_name, "mock": False,
            "prices": (conn.price_in_per_mtok, conn.price_out_per_mtok)}


def cost_usd(tokens_in: int, tokens_out: int, prices: tuple) -> float:
    p_in, p_out = prices or (None, None)
    return round(((tokens_in or 0) * (p_in or 0) + (tokens_out or 0) * (p_out or 0)) / 1_000_000, 6)
