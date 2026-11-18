"""HangarLLM como hub: a empresa liga o Agent Hangar ao HangarLLM uma vez (endereço + chave de gestão; sem endereço, a
central acha o container no Docker) e tudo se conecta: os LLMs, os servidores MCP e as skills do gateway.

O que a ligação faz:
- cria (ou atualiza) a conexão de LLM `hangarllm`, com a lista e o preço dos modelos lidos do próprio gateway;
- dá a cada agente, por ambiente, uma chave virtual só dele: os modelos que ele usa, um orçamento por período e validade
  curta, renovada pela central antes de vencer. A chave de gestão nunca sai da central nem chega a um agente;
- os agentes mandam etiquetas em cada chamada (agente, ambiente, tarefa) e o gasto real de cada chave volta para cá;
- excluir o agente revoga as chaves dele; desligar o hub revoga todas;
- cada servidor do gateway de MCP vira um conector `hub:<alias>`: o agente chama pela ponte da central com a chave dele,
  que só alcança os servidores do hub da spec dele;
- as skills publicadas no Skill Hub chegam aqui (somente leitura) e as da empresa vão para lá (`share_skills`).

Os outros jeitos de ligar um LLM (provedor direto, outro gateway) continuam valendo, isolados: sem chave por agente nem
gasto real do gateway.
"""
import logging
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config, crypto, tenancy
from ..models import Agent, HubKey, HubLink, LlmConnection, LlmModel, McpServer, Skill, now
from .common import PlatformError, audit, iso

log = logging.getLogger("hangar.hangarllm")

PROVIDER = "hangarllm"
CONNECTION = "hangarllm"
KEY_DURATION = "30d"
RENEW_BEFORE = timedelta(days=7)
TAG = "agent-hangar"
NETWORK_ALIAS = "hangarllm"
PERIODS = ("1d", "7d", "30d")
NO_MCP = "no-mcp-servers"  # marcador do HangarLLM: a chave não alcança nenhum servidor MCP
NO_MODELS = "no-default-models"  # marcador do HangarLLM: a chave não chama nenhum modelo (agente só com MCP do hub)
MCP_PREFIX = "hub:"  # conectores que vêm do hub: hub:<alias do servidor no HangarLLM>
SKILL_TAG = "agent-hangar"  # palavra-chave das skills que a central publica no hub


def HTTP() -> httpx.Client:  # noqa: N802 — os testes trocam por um cliente com transporte falso
    return httpx.Client(timeout=20)


class HubError(PlatformError):
    pass


# ------------------------------------------------------------------ chamadas ao HangarLLM
def _root(url: str) -> str:
    return (url or "").strip().rstrip("/").removesuffix("/v1")


def _request(url: str, method: str, path: str, key: str = "", **kw) -> httpx.Response:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        with HTTP() as c:
            r = c.request(method, f"{_root(url)}{path}", headers=headers, **kw)
    except httpx.HTTPError as e:
        raise HubError(f"não consegui falar com o HangarLLM em {_root(url)}: {type(e).__name__}. "
                       "De dentro do Docker, use o endereço da rede (ex.: http://hangarllm:4000) ou "
                       "host.docker.internal, não localhost.") from None
    if r.status_code >= 400:
        hint = {401: "chave inválida", 403: "a chave não é de gestão (use a chave mestra ou uma chave de gestão)",
                429: "limite de pedidos do HangarLLM: continua na próxima sincronização"}
        err = HubError(f"HangarLLM respondeu HTTP {r.status_code} em {path}"
                       + (f" ({hint[r.status_code]})" if r.status_code in hint else "") + f": {r.text[:300]}")
        err.status = r.status_code
        raise err
    return r


def _call(url: str, method: str, path: str, key: str = "", json: dict | None = None, params: dict | None = None):
    r = _request(url, method, path, key, json=json, params=params)
    if r.status_code == 204 or not r.content:
        return {}
    try:
        return r.json()
    except ValueError:
        raise HubError(f"HangarLLM não devolveu JSON em {path}") from None


def probe(url: str, admin_key: str) -> dict:
    """Confere endereço e chave: saúde, lista de modelos e permissão de gestão (criar chaves)."""
    if not url.startswith(("http://", "https://")):
        raise HubError("o endereço do HangarLLM deve ser http(s), ex.: http://hangarllm:4000")
    if not admin_key:
        raise HubError("informe a chave de gestão do HangarLLM (a chave mestra ou uma chave de gestão)")
    health = _call(url, "GET", "/health/readiness")
    info = _call(url, "GET", "/model/info", admin_key)
    _call(url, "GET", "/key/list", admin_key, params={"size": 1})  # só quem pode gerir chaves passa
    models = [m for m in (info.get("data") or []) if isinstance(m, dict) and m.get("model_name")]
    return {"health": health.get("status", ""), "models": models}


def _chat_models(models: list[dict]) -> list[str]:
    """Os nomes que uma chave pode chamar (um por grupo), com os de texto primeiro."""
    names: list[str] = []
    for m in sorted(models, key=lambda m: (m.get("model_info") or {}).get("mode") not in (None, "chat", "responses")):
        n = m["model_name"]
        if n not in names:
            names.append(n)
    return names


# ------------------------------------------------------------------ a ligação
def link(db: Session) -> HubLink | None:
    return db.scalar(select(HubLink).where(HubLink.org_id == tenancy.current_org()))


def _admin_key(h: HubLink) -> str:
    return crypto.decrypt(h.admin_key) if h.admin_key else ""


def connection(db: Session) -> LlmConnection | None:
    h = link(db)
    return db.get(LlmConnection, h.connection_id) if h and h.connection_id else None


def is_hub(conn: LlmConnection | None) -> bool:
    return bool(conn is not None and conn.provider == PROVIDER)


def connect(db: Session, url: str = "", admin_key: str = "", ui_url: str = "", budget_usd: float | None = None,
            budget_period: str | None = None, actor: str = "admin", share_skills: bool | None = None) -> dict:
    """Liga (ou atualiza) o hub. Reenviar sem a chave mantém a atual. Confere tudo antes de gravar."""
    from . import catalog, llm_models
    h = link(db)
    url = _root(url)
    found_local = None
    if not url:  # plug and play: sem endereço, procura o HangarLLM no Docker desta instalação e liga na rede dos agentes
        found_local = next(iter(discover()), None)
        if found_local is None:
            raise HubError("não achei um HangarLLM no Docker desta instalação: informe o endereço dele")
        if not found_local["attached"]:
            attach_network(found_local["container"], actor)
        url = found_local["url"]
    key = admin_key or (_admin_key(h) if h else "")
    if budget_period is not None and budget_period not in PERIODS:
        raise HubError(f"período do orçamento: {', '.join(PERIODS)}")
    if budget_usd is not None and budget_usd <= 0:
        raise HubError("o orçamento por agente precisa ser maior que zero")
    found = probe(url, key)
    names = _chat_models(found["models"])
    if not names:
        raise HubError("o HangarLLM não tem nenhum modelo cadastrado: cadastre um em Models + Endpoints e tente de novo")
    if h is None:
        h = HubLink(url=url, org_id=tenancy.current_org())
        db.add(h)
    h.url, h.ui_url = url, (ui_url or h.ui_url or "").strip().rstrip("/")
    if admin_key:
        h.admin_key = crypto.encrypt(admin_key)
    if budget_usd is not None:
        h.budget_usd = float(budget_usd)
    if budget_period is not None:
        h.budget_period = budget_period
    if share_skills is not None:
        h.share_skills = bool(share_skills)
    h.status, h.error, h.checked_at = "ok", "", now()
    db.commit()
    central = _ensure_key(db, h, None, "", f"{TAG}/{h.org_id}/central", names,
                          {"agent_hangar": {"org": h.org_id, "role": "central"}})
    conn = db.get(LlmConnection, h.connection_id) if h.connection_id else None
    default = (conn.model_name if conn and conn.model_name in names else "") or names[0]
    conn = catalog.upsert_llm_connection(
        db, conn.name if conn else CONNECTION, f"{url}/v1", default, central,
        "HangarLLM (hub): modelos, chaves por agente e gasto real", actor, "openai", provider=PROVIDER)
    h.connection_id = conn.id
    db.commit()
    models_sync = llm_models.sync_connection(db, conn, actor)
    hub_sync = sync(db, actor)
    audit(db, actor, "hangarllm.connect", url, f"{len(names)} modelos · orçamento US$ {h.budget_usd:g}/{h.budget_period}")
    return {**status(db), "sync": models_sync, "hub_sync": hub_sync, "discovered": found_local}


def disconnect(db: Session, actor: str = "admin") -> dict:
    """Desliga o hub: revoga todas as chaves criadas e remove a conexão. Barrado se algum agente ainda a usa."""
    from . import catalog
    h = link(db)
    if h is None:
        raise HubError("o HangarLLM não está ligado")
    conn = db.get(LlmConnection, h.connection_id) if h.connection_id else None
    in_use = sorted({f"{u} ({m.name})" for m in db.scalars(select(McpServer).where(McpServer.source == "hub"))
                     for u in _users(db, "mcps", m.name)})
    if in_use:
        raise HubError(f"conector do hub em uso por: {', '.join(in_use)}. Tire dos agentes antes de desligar.")
    if conn is not None:
        catalog.delete_llm_connection(db, conn.name, actor)  # barra se algum agente usa
    for m in db.scalars(select(McpServer).where(McpServer.source == "hub")):
        db.delete(m)
    for s in db.scalars(select(Skill)):
        if s.source == "hub":  # a cópia fica como skill da empresa (os agentes que a usam continuam funcionando)
            s.source, s.hub_ref = "", ""
        elif s.hub_ref:
            try:  # tira do Skill Hub as que a central publicou lá
                _call(h.url, "DELETE", f"/skill-hub/skills/{s.name}", _admin_key(h))
            except HubError as e:
                log.warning("não tirei a skill %s do HangarLLM: %s", s.name, e)
            s.hub_ref = ""
    keys = list(db.scalars(select(HubKey)))
    _revoke(h, keys)
    for k in keys:
        db.delete(k)
    db.delete(h)
    db.commit()
    audit(db, actor, "hangarllm.disconnect", h.url, f"{len(keys)} chave(s) revogada(s)")
    return {"ok": True, "revoked": len(keys)}


# ------------------------------------------------------------------ chaves virtuais
def _parse_dt(v) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _perm(mcps: list[str]) -> dict:
    """O que a chave alcança no gateway de MCP: só os servidores listados (nenhum = o marcador do HangarLLM)."""
    return {"mcp_servers": mcps or [NO_MCP]}


def _ensure_key(db: Session, h: HubLink, agent_id: int | None, env: str, alias: str, models: list[str] | None,
                meta: dict, mcps: list[str] | None = None) -> str:
    """A chave deste agente e ambiente (ou da central): reaproveita a que existe, acerta modelos e servidores MCP se
    mudaram e cria se ainda não há. `None` mantém o que a chave já tem. Devolve o valor da chave."""
    k = db.scalar(select(HubKey).where(HubKey.agent_id.is_(None) if agent_id is None else HubKey.agent_id == agent_id,
                                       HubKey.env == env))
    if models is not None:
        models = sorted(set(m for m in models if m))
    if mcps is not None:
        mcps = sorted(set(m for m in mcps if m))
    admin = _admin_key(h)
    if k is not None:
        models = (k.models or []) if models is None else models
        mcps = (k.mcps or []) if mcps is None else mcps
        exp = k.expires_at if k.expires_at is None or k.expires_at.tzinfo else k.expires_at.replace(tzinfo=UTC)
        stale = exp is not None and exp - now() < RENEW_BEFORE
        if sorted(k.models or []) != models or sorted(k.mcps or []) != mcps or stale:
            body = {"key": k.token, "models": models or [NO_MODELS], "object_permission": _perm(mcps)}
            if stale:
                body["duration"] = KEY_DURATION
            out = _call(h.url, "POST", "/key/update", admin, json=body)
            k.models, k.mcps = models, mcps
            k.expires_at = _parse_dt(out.get("expires")) or k.expires_at
            db.commit()
        return crypto.decrypt(k.key)
    models, mcps = models or [], mcps or []
    out = _call(h.url, "POST", "/key/generate", admin, json={
        "key_alias": alias, "duration": KEY_DURATION, "models": models or [NO_MODELS],
        "max_budget": h.budget_usd, "budget_duration": h.budget_period, "auto_rotate": False,
        "object_permission": _perm(mcps),
        "metadata": {**meta, "tags": [TAG] + [f"{k}:{v}" for k, v in (meta.get("agent_hangar") or {}).items()
                                              if k in ("agent", "env")]}})
    value = out.get("key") or ""
    if not value:
        raise HubError("o HangarLLM não devolveu a chave criada")
    k = HubKey(agent_id=agent_id, env=env, alias=alias, key=crypto.encrypt(value), token=out.get("token") or "",
               models=models, mcps=mcps, expires_at=_parse_dt(out.get("expires")), org_id=h.org_id)
    db.add(k)
    db.commit()
    return value


def agent_key(db: Session, agent: Agent, env: str, models: list[str] | None = None,
              mcps: list[str] | None = None) -> str:
    """A chave do agente neste ambiente, só com os modelos e os servidores MCP do hub que ele usa (`None` mantém o que
    ela já tem). Sem hub ligado é um erro claro: a chave de gestão nunca vai para um agente."""
    h = link(db)
    if h is None:
        raise HubError("o agente usa o HangarLLM, mas o hub não está ligado: abra Provedores → HangarLLM e ligue de novo")
    alias = f"{TAG}/{h.org_id}/{agent.slug}/{env}"
    key = _ensure_key(db, h, agent.id, env, alias, models,
                      {"agent_hangar": {"org": h.org_id, "agent": agent.slug, "env": env}}, mcps)
    audit(db, "plataforma", "hangarllm.key", agent.slug,
          f"{env} · {', '.join(sorted(set(models or [])))}" + (f" · MCP {', '.join(mcps)}" if mcps else ""))
    return key


def central_key(db: Session) -> str:
    h = link(db)
    k = db.scalar(select(HubKey).where(HubKey.agent_id.is_(None), HubKey.env == "")) if h else None
    if k is None:
        raise HubError("o hub HangarLLM não está ligado")
    return crypto.decrypt(k.key)


def _revoke(h: HubLink, keys: list[HubKey]) -> None:
    tokens = [k.token for k in keys if k.token]
    if not tokens:
        return
    try:
        _call(h.url, "POST", "/key/delete", _admin_key(h), json={"keys": tokens})
    except HubError as e:  # o hub fora do ar não impede excluir: as chaves vencem sozinhas (validade curta)
        log.warning("não revoguei %d chave(s) no HangarLLM: %s", len(tokens), e)


def revoke_agent(db: Session, agent_id: int, actor: str = "admin") -> int:
    """Revoga as chaves de um agente (exclusão). Nunca levanta."""
    h = link(db)
    keys = list(db.scalars(select(HubKey).where(HubKey.agent_id == agent_id)))
    if not keys:
        return 0
    if h is not None:
        _revoke(h, keys)
    for k in keys:
        db.delete(k)
    db.commit()
    audit(db, actor, "hangarllm.revoke", str(agent_id), f"{len(keys)} chave(s)")
    return len(keys)


# ------------------------------------------------------------------ manutenção: validade e gasto real
def refresh(db: Session, actor: str = "agendador") -> dict:
    """Renova as chaves perto de vencer, lê o gasto real de cada uma e sincroniza os MCPs e as skills."""
    h = link(db)
    if h is None:
        return {"ok": False, "renewed": 0}
    admin = _admin_key(h)
    renewed = 0
    try:
        for k in db.scalars(select(HubKey)).all():
            exp = k.expires_at if k.expires_at is None or k.expires_at.tzinfo else k.expires_at.replace(tzinfo=UTC)
            if exp is not None and exp - now() < RENEW_BEFORE:
                out = _call(h.url, "POST", "/key/update", admin, json={"key": k.token, "duration": KEY_DURATION})
                k.expires_at = _parse_dt(out.get("expires")) or k.expires_at
                renewed += 1
        mine = {k.alias: k for k in db.scalars(select(HubKey))}
        page = 1
        while mine:
            out = _call(h.url, "GET", "/key/list", admin,
                        params={"return_full_object": "true", "size": 100, "page": page})
            for row in out.get("keys") or []:
                k = mine.get(row.get("key_alias") or "") if isinstance(row, dict) else None
                if k is not None:
                    k.spend_usd, k.spend_at = float(row.get("spend") or 0), now()
            if page >= int(out.get("total_pages") or 1):
                break
            page += 1
        h.status, h.error, h.checked_at = "ok", "", now()
    except HubError as e:
        h.status, h.error, h.checked_at = "error", str(e)[:500], now()
    db.commit()
    if renewed:
        audit(db, "agendador", "hangarllm.renew", h.url, f"{renewed} chave(s)")
    hub_sync = sync(db, actor) if h.status == "ok" else {}
    return {"ok": h.status == "ok", "renewed": renewed, "error": h.error, "hub_sync": hub_sync}


def refresh_due() -> int:
    """De hora em hora, em todas as empresas com hub ligado. O agendador chama em segundo plano."""
    from ..db import SessionLocal
    n = 0
    with SessionLocal() as db:
        orgs = [h.org_id for h in db.scalars(select(HubLink))]
    for org in orgs:
        with tenancy.using(org), SessionLocal() as db:
            try:
                refresh(db)
                n += 1
            except Exception:  # noqa: BLE001 — uma empresa com problema não para as outras
                db.rollback()
                log.exception("falha ao atualizar o hub da empresa %s", org)
    return n


# ------------------------------------------------------------------ MCP do hub
def mcp_name(alias: str) -> str:
    return f"{MCP_PREFIX}{alias}"


def is_hub_mcp(name: str) -> bool:
    return (name or "").startswith(MCP_PREFIX)


def _names(items) -> set[str]:
    return {(x if isinstance(x, str) else (x or {}).get("name")) or "" for x in items or []}


def spec_mcps(*specs: dict) -> list[str]:
    """Os servidores do hub (alias no HangarLLM) que estas specs usam."""
    return sorted({n[len(MCP_PREFIX):] for sp in specs for n in _names((sp or {}).get("mcps")) if is_hub_mcp(n)})


def _users(db: Session, field: str, name: str) -> list[str]:
    from .common import spec_of
    out = []
    for a in db.scalars(select(Agent)):
        try:
            if name in _names(spec_of(a).get(field)):
                out.append(a.slug)
        except PlatformError:
            continue
    return out


def tags_header(slug: str, env: str, task: str = "") -> str:
    return ",".join([TAG, f"agent:{slug}", f"env:{env}"] + ([f"task:{task}"] if task else []))


def mcp_headers(db: Session, agent: Agent | None, env: str = "", task: str = "", aliases: list[str] | None = None) -> dict:
    """Headers para o gateway de MCP do HangarLLM. Agente: a chave dele (liberando só os servidores do hub das specs
    dele) e as etiquetas; sem agente (a central conferindo o servidor): a chave da central."""
    if agent is None:
        return {"x-hangarllm-api-key": central_key(db)}
    env = env if env in ("stage", "prod") else "stage"
    key = agent_key(db, agent, env, None, aliases or [])
    h = {"x-hangarllm-api-key": key, "x-hangarllm-tags": tags_header(agent.slug, env, task)}
    if task:
        h["x-hangarllm-session-id"] = f"{agent.slug}-task-{task}"
    return h


def sync_mcps(db: Session, h: HubLink, actor: str = "agendador") -> dict:
    """Cada servidor MCP do HangarLLM vira um conector `hub:<alias>`: os agentes o escolhem como qualquer conector e
    chamam pela ponte da central, que fala com o gateway com a chave do próprio agente. As ferramentas passam pela
    mesma aprovação dos outros conectores (nova ou alterada fica bloqueada até um admin aprovar)."""
    from . import connectors
    servers = _call(h.url, "GET", "/v1/mcp/server", _admin_key(h))
    servers = servers if isinstance(servers, list) else (servers.get("data") or [])
    live = {}
    for sv in servers:
        if not isinstance(sv, dict) or (sv.get("approval_status") or "active") not in ("active", "approved"):
            continue
        alias = sv.get("alias") or sv.get("server_name") or ""
        if alias:
            live[alias] = sv
    _ensure_key(db, h, None, "", f"{TAG}/{h.org_id}/central", None, {}, sorted(live))  # a central confere todos
    have = {m.name: m for m in db.scalars(select(McpServer).where(McpServer.source == "hub"))}
    added, updated, gone, kept = [], [], [], []
    for alias, sv in live.items():
        name = mcp_name(alias)
        m = have.get(name)
        if m is None:
            if db.scalar(select(McpServer).where(McpServer.name == name)) is not None:
                continue  # nome já usado por um conector local
            m = McpServer(name=name, org_id=h.org_id, created_by="hangarllm", source="hub")
            db.add(m)
            added.append(name)
        else:
            updated.append(name)
        m.url = connectors.proxy_url(name)
        m.upstream_url = f"{h.url}/{alias}/mcp"
        m.transport, m.auth, m.headers, m.timeout_s = "http", "hub", [], 120
        m.tool_prefix = f"{alias}-"  # o gateway chama as ferramentas de <alias>-<ferramenta>; o agente vê só <ferramenta>
        m.description = (sv.get("description") or f"Servidor MCP do HangarLLM: {sv.get('server_name') or alias}")[:1000]
        m.category = m.category or "hub"
    db.commit()
    for name in added + updated:
        m = db.scalar(select(McpServer).where(McpServer.name == name))
        try:
            connectors.check(db, m, first=name in added)
        except Exception as e:  # noqa: BLE001 — um servidor com problema não para a sincronização
            db.rollback()
            m.status, m.status_detail = "error", str(e)[:300]
            db.commit()
    for name, m in have.items():
        if name[len(MCP_PREFIX):] in live:
            continue
        users = _users(db, "mcps", name)
        if users:  # tirado do hub, mas ainda na spec de alguém: fica, marcado
            m.status, m.status_detail = "error", f"removido do HangarLLM; ainda na spec de: {', '.join(users)}"
            kept.append(name)
        else:
            db.delete(m)
            gone.append(name)
    db.commit()
    if added or gone:
        audit(db, actor, "hangarllm.mcp", h.url, f"+{len(added)} −{len(gone)}")
    return {"servers": len(live), "added": added, "removed": gone, "orphaned": kept}


# ------------------------------------------------------------------ skills: do hub para cá e daqui para o hub
def _ref(sk: dict) -> str:
    import hashlib
    digest = hashlib.sha1(f"{sk.get('version')}|{sk.get('updated_at')}".encode()).hexdigest()[:10]
    return f"{str(sk.get('version') or '')[:28]}#{digest}"


def _org_tag(h: HubLink) -> str:
    return f"{SKILL_TAG}-org-{h.org_id}"


def _hub_skills(h: HubLink) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while offset is not None and len(out) < 2000:
        page = _call(h.url, "GET", "/skill-hub/skills", _admin_key(h), params={"limit": 100, "offset": offset})
        out += [x for x in page.get("skills") or [] if isinstance(x, dict) and x.get("name")]
        offset = page.get("next_offset")
    return out


def _zip(s: Skill) -> bytes:
    """O pacote no formato do Skill Hub: SKILL.md na raiz e os arquivos ao lado."""
    import io
    import zipfile

    from .skill_package import skill_md
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", skill_md(s.name, s.description or s.name, s.content or ""))
        for f in s.files or []:
            zf.writestr(f["path"], f["content"])
    return buf.getvalue()


def _pull(db: Session, h: HubLink, sk: dict) -> Skill:
    from . import skill_package
    from .catalog import upsert_skill
    from .skill_studio import record
    data = _request(h.url, "GET", f"/skill-hub/skills/{sk['name']}/archive", _admin_key(h)).content
    pkg = skill_package.from_upload(f"{sk['name']}.zip", data)
    report = skill_package.scan(pkg["content"], pkg["files"])
    if not report["ok"]:
        raise HubError("a verificação de segurança bloqueou: " + "; ".join(map(str, report["blocked"]))[:200])
    desc = str(pkg["meta"].get("description") or sk.get("description") or "")[:1000]
    s = upsert_skill(db, sk["name"], desc, pkg["content"], "hangarllm")
    s.files, s.source, s.hub_ref, s.updated_at = pkg["files"], "hub", _ref(sk), now()
    s.status = "active"
    db.commit()
    record(db, s, "hangarllm", f"do HangarLLM (v{sk.get('version') or '?'})")
    return s


def _push(db: Session, h: HubLink, s: Skill, exists: bool) -> None:
    from . import skill_package
    report = skill_package.scan(s.content or "", s.files or [])
    if not report["ok"]:
        raise HubError("a verificação de segurança bloqueou a publicação (segredo no conteúdo?)")
    files = {"file": (f"{s.name}.zip", _zip(s), "application/zip")}
    admin = _admin_key(h)
    path = f"/skill-hub/skills/{s.name}/upload" if exists else "/skill-hub/skills/upload"
    _request(h.url, "PUT" if exists else "POST", path, admin, files=files, data={"version": f"{s.version}.0.0"})
    _call(h.url, "PUT", f"/skill-hub/skills/{s.name}", admin,
          json={"namespace": SKILL_TAG, "keywords": [SKILL_TAG, _org_tag(h)]})
    s.hub_ref = str(s.version)
    db.commit()


def _shared(h: HubLink, s: Skill | None) -> bool:
    return bool(s is not None and s.source != "hub" and h.share_skills and (s.status or "active") == "active")


def sync_skills(db: Session, h: HubLink, actor: str = "agendador") -> dict:
    """As skills publicadas no Skill Hub chegam aqui (somente leitura: edita-se no HangarLLM) e, com `share_skills`, as
    skills da empresa vão para o hub, marcadas com a palavra-chave da empresa. Nome igual de outra origem não é
    sobrescrito nem lá nem cá: aparece como conflito."""
    hub = {sk["name"]: sk for sk in _hub_skills(h)}
    mine = {n for n, sk in hub.items() if _org_tag(h) in (sk.get("keywords") or [])}
    local = {s.name: s for s in db.scalars(select(Skill))}
    res: dict = {"pulled": [], "pushed": [], "removed": [], "unpublished": [], "conflicts": [], "errors": []}
    for name, sk in hub.items():  # do hub para cá: só as publicadas
        if name in mine or sk.get("visibility") == "private":
            continue
        s = local.get(name)
        if s is not None and s.source != "hub":
            res["conflicts"].append(name)
            continue
        if s is not None and s.hub_ref == _ref(sk):
            continue
        try:
            local[name] = _pull(db, h, sk)
            res["pulled"].append(name)
        except (HubError, PlatformError) as e:
            db.rollback()
            res["errors"].append(f"{name}: {e}"[:300])
    for name, s in list(local.items()):  # tiradas do hub (ou despublicadas)
        if s.source != "hub" or (name in hub and name not in mine and hub[name].get("visibility") != "private"):
            continue
        if _users(db, "skills", name):
            s.status = "deprecated"  # ainda em uso: fica, sem entrar em agentes novos
        else:
            db.delete(s)
            local.pop(name)
            res["removed"].append(name)
    db.commit()
    limited = False
    for name, s in local.items():  # daqui para o hub
        if not _shared(h, s) or limited:
            continue
        if name in hub and name not in mine:
            res["conflicts"].append(name)
            continue
        if name in mine and s.hub_ref == str(s.version) \
                and str(hub[name].get("version") or "").startswith(f"{s.version}."):
            continue
        try:
            _push(db, h, s, name in mine)
            res["pushed"].append(name)
        except HubError as e:
            db.rollback()
            limited = getattr(e, "status", 0) == 429
            res["errors"].append(f"{name}: {e}"[:300])
    for name in mine:  # as da empresa que não deviam mais estar lá
        s = local.get(name)
        if _shared(h, s):
            continue
        try:
            _call(h.url, "DELETE", f"/skill-hub/skills/{name}", _admin_key(h))
            if s is not None:
                s.hub_ref = ""
            res["unpublished"].append(name)
        except HubError as e:
            res["errors"].append(f"{name}: {e}"[:300])
    db.commit()
    res["conflicts"] = sorted(set(res["conflicts"]))
    if res["pulled"] or res["pushed"] or res["removed"] or res["unpublished"]:
        audit(db, actor, "hangarllm.skills", h.url, f"↓{len(res['pulled'])} ↑{len(res['pushed'])} "
                                                    f"−{len(res['removed']) + len(res['unpublished'])}")
    return res


def sync(db: Session, actor: str = "agendador") -> dict:
    """MCPs e skills, cada parte por si: uma falha não impede a outra. Guarda o resumo para a tela."""
    h = link(db)
    if h is None:
        return {}
    out: dict = {"at": iso(now())}
    for part, fn in (("mcps", sync_mcps), ("skills", sync_skills)):
        try:
            out[part] = fn(db, h, actor)
        except HubError as e:
            db.rollback()
            out[part] = {"error": str(e)[:500]}
        h = link(db)
    h.sync = out
    db.commit()
    return out


# ------------------------------------------------------------------ rede do Docker
def discover() -> list[dict]:
    """Instalação local: os containers do HangarLLM (o serviço da API, porta 4000) que a central enxerga no Docker."""
    from .. import deploy
    try:
        containers = deploy.client().containers.list()
    except Exception:  # noqa: BLE001 — sem Docker (Kubernetes, testes): não há o que procurar
        return []
    out = []
    for c in containers:
        conf = c.attrs.get("Config") or {}
        image, ports = str(conf.get("Image") or ""), conf.get("ExposedPorts") or {}
        if "hangarllm" not in f"{c.name} {image}".lower() or "4000/tcp" not in ports:
            continue
        nets = (c.attrs.get("NetworkSettings") or {}).get("Networks") or {}
        out.append({"container": c.name, "image": image, "url": f"http://{NETWORK_ALIAS}:4000",
                    "attached": config.AGENTS_NETWORK in nets and config.JOBS_NETWORK in nets})
    return sorted(out, key=lambda x: (not x["attached"], x["container"]))


def attach_network(container: str = "hangarllm-hangarllm-1", actor: str = "admin") -> dict:
    """Instalação local: põe o container do HangarLLM nas redes dos agentes e dos jobs com o nome `hangarllm`. Assim a
    central e os agentes chegam nele por http://hangarllm:4000, sem passar pelo TLS local. Refazer depois de recriar
    o container do HangarLLM."""
    from .. import deploy
    try:
        c = deploy.client()
        target = c.containers.get(container)
    except Exception as e:  # noqa: BLE001
        raise HubError(f"não achei o container '{container}' no Docker: {type(e).__name__}") from None
    done = []
    for net in (config.AGENTS_NETWORK, config.JOBS_NETWORK):
        if net in (target.attrs.get("NetworkSettings", {}).get("Networks") or {}):
            done.append(net)
            continue
        try:
            c.networks.get(net).connect(target, aliases=[NETWORK_ALIAS])
            done.append(net)
        except Exception as e:  # noqa: BLE001
            raise HubError(f"não consegui ligar '{container}' à rede {net}: {e}") from None
    return {"ok": True, "container": container, "networks": done, "url": f"http://{NETWORK_ALIAS}:4000"}


# ------------------------------------------------------------------ o painel
def status(db: Session) -> dict:
    """O que a tela Hub HangarLLM mostra: a ligação, os modelos, as chaves com o gasto real e o que segue isolado."""
    h = link(db)
    others = [c for c in db.scalars(select(LlmConnection)) if not is_hub(c)]
    skills = list(db.scalars(select(Skill).order_by(Skill.name)))
    hub_mcps = list(db.scalars(select(McpServer).where(McpServer.source == "hub").order_by(McpServer.name)))
    isolated = {"llm_connections": len(others),
                "connectors": db.query(McpServer).filter(McpServer.source != "hub").count(),
                "skills": sum(1 for x in skills if x.source != "hub" and not x.hub_ref)}
    if h is None:
        return {"connected": False, "isolated": isolated, "found": discover()}
    conn = db.get(LlmConnection, h.connection_id) if h.connection_id else None
    kinds: dict = {}
    if conn is not None:
        for m in db.scalars(select(LlmModel).where(LlmModel.connection_id == conn.id, LlmModel.available.is_(True))):
            kinds[m.kind or "other"] = kinds.get(m.kind or "other", 0) + 1
    slugs = {a.id: a.slug for a in db.scalars(select(Agent))}
    keys = [{"agent": slugs.get(k.agent_id, "") if k.agent_id else "", "central": k.agent_id is None, "env": k.env,
             "alias": k.alias, "models": [m for m in k.models or [] if m != NO_MODELS], "mcps": k.mcps or [],
             "expires_at": iso(k.expires_at), "spend_usd": k.spend_usd,
             "spend_at": iso(k.spend_at)} for k in db.scalars(select(HubKey).order_by(HubKey.id))]
    return {"connected": True, "url": h.url, "ui_url": h.ui_url, "status": h.status, "error": h.error,
            "checked_at": iso(h.checked_at), "budget_usd": h.budget_usd, "budget_period": h.budget_period,
            "connection": conn.name if conn else "", "default_model": conn.model_name if conn else "",
            "models": kinds, "models_total": sum(kinds.values()), "keys": keys,
            "spend_usd": round(sum(k["spend_usd"] or 0 for k in keys), 6), "isolated": isolated,
            "share_skills": h.share_skills, "sync": h.sync or {},
            "mcps": [{"name": m.name, "alias": m.name[len(MCP_PREFIX):], "description": m.description,
                      "status": m.status, "status_detail": m.status_detail,
                      "tools": sum(1 for t in m.tools or [] if t.get("state") == "approved"),
                      "pending": sum(1 for t in m.tools or [] if t.get("state") in ("pending", "changed")),
                      "used_by": _users(db, "mcps", m.name)} for m in hub_mcps],
            "skills": {"from_hub": [{"name": x.name, "version": x.hub_ref.split("#")[0], "status": x.status}
                                    for x in skills if x.source == "hub"],
                       "published": [{"name": x.name, "version": x.version} for x in skills
                                     if x.source != "hub" and x.hub_ref],
                       "conflicts": ((h.sync or {}).get("skills") or {}).get("conflicts") or []}}
