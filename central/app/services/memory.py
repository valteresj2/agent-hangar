"""Memória de longo prazo dos agentes (Graphiti sobre Neo4j/FalkorDB, serviço `memory`, ver docs/memory.md).

A central é quem decide os grupos de memória — o agente nunca escolhe:
- escopo `agent` -> agent-<slug>; `team` -> team-<slug do time>; `org` -> org-<id>
- produção lê e grava no grupo base; stage grava em <base>__stage e lê os dois (testa com a memória real sem
  sujá-la). O ambiente vem do token por ambiente do container (auth.agent_env_token), não de um header livre.
Quando as specs no ar divergem (versão atual x deployment), vale o escopo mais estreito e só grava se todas gravam.
"""
import httpx
from sqlalchemy.orm import Session

from .. import config, crypto
from ..models import Agent, Team
from .access import Access
from .catalog import get_connection
from .common import PlatformError, audit

SCOPES = ("agent", "team", "org")  # do mais estreito ao mais largo
STAGE_SUFFIX = "__stage"
HTTP = lambda: httpx.Client(timeout=30)  # noqa: E731  (os testes trocam)


def enabled() -> bool:
    return bool(config.MEMORY_URL and config.MEMORY_TOKEN)


def base_group(db: Session, a: Agent, scope: str) -> str:
    if scope == "org":
        return f"org-{a.org_id}"
    if scope == "team" and a.team_id:
        t = db.get(Team, a.team_id)
        if t:
            return f"team-{t.slug}"
    return f"agent-{a.slug}"


def effective(specs: list[dict]) -> dict | None:
    mems = [s["memory"] for s in specs if s.get("memory")]
    if not mems:
        return None
    return {"scope": min((m.get("scope") or "agent" for m in mems), key=SCOPES.index),
            "write": all(m.get("write", True) for m in mems)}


def groups(db: Session, a: Agent, mem: dict, env: str) -> tuple[list[str], str]:
    """(grupos de leitura, grupo de escrita — vazio se só leitura)."""
    base = base_group(db, a, mem["scope"])
    if env == "prod":
        return [base], base if mem["write"] else ""
    return [base, base + STAGE_SUFFIX], (base + STAGE_SUFFIX) if mem["write"] else ""


def service_config(db: Session) -> dict:
    """O que o serviço de memória precisa para o Graphiti: LLM de extração (e embeddings remotos, se usados)."""
    out: dict = {"llm": {}, "embedding": {}}
    if config.MEMORY_LLM_CONNECTION:
        c = get_connection(db, config.MEMORY_LLM_CONNECTION)
        if c.protocol != "openai":
            raise PlatformError("MEMORY_LLM_CONNECTION precisa ser uma conexão protocol='openai'")
        out["llm"] = {"base_url": c.base_url, "api_key": crypto.decrypt(c.api_key),
                      "model": config.MEMORY_LLM_MODEL or c.model_name, "output_mode": config.MEMORY_LLM_OUTPUT_MODE}
    if config.MEMORY_EMBEDDING_CONNECTION:
        c = get_connection(db, config.MEMORY_EMBEDDING_CONNECTION)
        out["embedding"] = {"base_url": c.base_url, "api_key": crypto.decrypt(c.api_key),
                            "model": config.MEMORY_EMBEDDING_MODEL or c.model_name}
    return out


# ------------------------------------------------------------------ administração (UI / API)
def _call(method: str, path: str, **kw) -> dict:
    if not enabled():
        raise PlatformError("memória desligada nesta instalação (docker compose --profile memory; ver docs/memory.md)")
    try:
        with HTTP() as http:
            r = http.request(method, config.MEMORY_URL + path, headers={"Authorization": f"Bearer {config.MEMORY_TOKEN}"}, **kw)
    except httpx.HTTPError as e:
        raise PlatformError(f"serviço de memória indisponível: {type(e).__name__}") from None
    if r.status_code >= 400:
        raise PlatformError(f"serviço de memória: HTTP {r.status_code} {r.text[:200]}")
    return r.json()


def status() -> dict:
    if not enabled():
        return {"enabled": False}
    try:
        return {"enabled": True, **_call("GET", "/admin/status")}
    except PlatformError as e:
        return {"enabled": True, "ready": False, "error": str(e)}


def _agent_groups(db: Session, a: Agent, env: str) -> tuple[dict, str]:
    from .common import spec_of

    mem = effective([spec_of(a)])
    if not mem:
        raise PlatformError(f"'{a.slug}' não usa memória (adicione `memory` na spec)")
    if env not in ("prod", "stage"):
        raise PlatformError("env deve ser prod ou stage")
    base = base_group(db, a, mem["scope"])
    return mem, base if env == "prod" else base + STAGE_SUFFIX


def agent_facts(db: Session, acc: Access, a: Agent, env: str = "prod", q: str = "", limit: int = 50) -> dict:
    acc.require("view_spec", a)
    mem, group = _agent_groups(db, a, env)
    r = _call("GET", "/admin/facts", params={"group": group, "q": q, "limit": limit})
    shared = mem["scope"] != "agent"
    return {**r, "scope": mem["scope"], "write": mem["write"], "env": env, "shared": shared}


def clear_agent(db: Session, acc: Access, a: Agent, env: str = "prod") -> dict:
    acc.require("manage", a)
    mem, group = _agent_groups(db, a, env)
    if mem["scope"] == "org" and not acc.p.is_admin:  # time: o mantenedor do time (manage) já basta
        raise PlatformError("memória da empresa: só um admin apaga")
    r = _call("DELETE", f"/admin/groups/{group}")
    audit(db, acc.p.name, "memory.clear", a.slug, group)
    return r


def forget_agent(slug: str):
    """Agente excluído: apaga a memória de escopo `agent` (produção e stage). Melhor esforço."""
    if not enabled():
        return
    for group in (f"agent-{slug}", f"agent-{slug}{STAGE_SUFFIX}"):
        try:
            _call("DELETE", f"/admin/groups/{group}")
        except PlatformError:
            pass
