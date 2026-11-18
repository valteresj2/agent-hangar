"""HangarLLM como hub: a empresa liga o Agent Hangar ao HangarLLM uma vez (endereço + chave de gestão) e passa a usar o
gateway para os LLMs dos agentes.

O que a ligação faz:
- cria (ou atualiza) a conexão de LLM `hangarllm`, com a lista e o preço dos modelos lidos do próprio gateway;
- dá a cada agente, por ambiente, uma chave virtual só dele: os modelos que ele usa, um orçamento por período e validade
  curta, renovada pela central antes de vencer. A chave de gestão nunca sai da central nem chega a um agente;
- os agentes mandam etiquetas em cada chamada (agente, ambiente, tarefa) e o gasto real de cada chave volta para cá;
- excluir o agente revoga as chaves dele; desligar o hub revoga todas.

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


def HTTP() -> httpx.Client:  # noqa: N802 — os testes trocam por um cliente com transporte falso
    return httpx.Client(timeout=20)


class HubError(PlatformError):
    pass


# ------------------------------------------------------------------ chamadas ao HangarLLM
def _root(url: str) -> str:
    return (url or "").strip().rstrip("/").removesuffix("/v1")


def _call(url: str, method: str, path: str, key: str = "", json: dict | None = None, params: dict | None = None):
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        with HTTP() as c:
            r = c.request(method, f"{_root(url)}{path}", headers=headers, json=json, params=params)
    except httpx.HTTPError as e:
        raise HubError(f"não consegui falar com o HangarLLM em {_root(url)}: {type(e).__name__}. "
                       "De dentro do Docker, use o endereço da rede (ex.: http://hangarllm:4000) ou "
                       "host.docker.internal, não localhost.") from None
    if r.status_code >= 400:
        hint = {401: "chave inválida", 403: "a chave não é de gestão (use a chave mestra ou uma chave de gestão)"}
        detail = r.text[:300]
        raise HubError(f"HangarLLM respondeu HTTP {r.status_code} em {path}"
                       + (f" ({hint[r.status_code]})" if r.status_code in hint else "") + f": {detail}")
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


def connect(db: Session, url: str, admin_key: str = "", ui_url: str = "", budget_usd: float | None = None,
            budget_period: str | None = None, actor: str = "admin") -> dict:
    """Liga (ou atualiza) o hub. Reenviar sem a chave mantém a atual. Confere tudo antes de gravar."""
    from . import catalog, llm_models
    h = link(db)
    url = _root(url)
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
    sync = llm_models.sync_connection(db, conn, actor)
    audit(db, actor, "hangarllm.connect", url, f"{len(names)} modelos · orçamento US$ {h.budget_usd:g}/{h.budget_period}")
    return {**status(db), "sync": sync}


def disconnect(db: Session, actor: str = "admin") -> dict:
    """Desliga o hub: revoga todas as chaves criadas e remove a conexão. Barrado se algum agente ainda a usa."""
    from . import catalog
    h = link(db)
    if h is None:
        raise HubError("o HangarLLM não está ligado")
    conn = db.get(LlmConnection, h.connection_id) if h.connection_id else None
    if conn is not None:
        catalog.delete_llm_connection(db, conn.name, actor)  # barra se algum agente usa
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


def _ensure_key(db: Session, h: HubLink, agent_id: int | None, env: str, alias: str, models: list[str],
                meta: dict) -> str:
    """A chave deste agente e ambiente (ou da central): reaproveita a que existe, acerta os modelos se mudaram e cria
    se ainda não há. Devolve o valor da chave."""
    models = sorted(set(m for m in models if m))
    k = db.scalar(select(HubKey).where(HubKey.agent_id.is_(None) if agent_id is None else HubKey.agent_id == agent_id,
                                       HubKey.env == env))
    admin = _admin_key(h)
    if k is not None:
        exp = k.expires_at if k.expires_at is None or k.expires_at.tzinfo else k.expires_at.replace(tzinfo=UTC)
        stale = exp is not None and exp - now() < RENEW_BEFORE
        if sorted(k.models or []) != models or stale:
            body = {"key": k.token, "models": models}
            if stale:
                body["duration"] = KEY_DURATION
            out = _call(h.url, "POST", "/key/update", admin, json=body)
            k.models = models
            k.expires_at = _parse_dt(out.get("expires")) or k.expires_at
            db.commit()
        return crypto.decrypt(k.key)
    out = _call(h.url, "POST", "/key/generate", admin, json={
        "key_alias": alias, "duration": KEY_DURATION, "models": models,
        "max_budget": h.budget_usd, "budget_duration": h.budget_period,
        "metadata": {**meta, "tags": [TAG] + [f"{k}:{v}" for k, v in (meta.get("agent_hangar") or {}).items()
                                              if k in ("agent", "env")]}})
    value = out.get("key") or ""
    if not value:
        raise HubError("o HangarLLM não devolveu a chave criada")
    k = HubKey(agent_id=agent_id, env=env, alias=alias, key=crypto.encrypt(value), token=out.get("token") or "",
               models=models, expires_at=_parse_dt(out.get("expires")), org_id=h.org_id)
    db.add(k)
    db.commit()
    return value


def agent_key(db: Session, agent: Agent, env: str, models: list[str]) -> str:
    """A chave do agente neste ambiente, só com os modelos que ele usa. Sem hub ligado é um erro claro: a chave de
    gestão nunca vai para um agente."""
    h = link(db)
    if h is None:
        raise HubError("a conexão 'hangarllm' precisa do hub ligado: abra Hub HangarLLM e ligue de novo")
    alias = f"{TAG}/{h.org_id}/{agent.slug}/{env}"
    key = _ensure_key(db, h, agent.id, env, alias, models,
                      {"agent_hangar": {"org": h.org_id, "agent": agent.slug, "env": env}})
    audit(db, "plataforma", "hangarllm.key", agent.slug, f"{env} · {', '.join(sorted(set(models)))}")
    return key


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
def refresh(db: Session) -> dict:
    """Renova as chaves perto de vencer e lê o gasto real de cada uma no HangarLLM."""
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
    return {"ok": h.status == "ok", "renewed": renewed, "error": h.error}


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


# ------------------------------------------------------------------ rede do Docker
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
    isolated = {"llm_connections": len(others), "connectors": db.query(McpServer).count(), "skills": db.query(Skill).count()}
    if h is None:
        return {"connected": False, "isolated": isolated}
    conn = db.get(LlmConnection, h.connection_id) if h.connection_id else None
    kinds: dict = {}
    if conn is not None:
        for m in db.scalars(select(LlmModel).where(LlmModel.connection_id == conn.id, LlmModel.available.is_(True))):
            kinds[m.kind or "other"] = kinds.get(m.kind or "other", 0) + 1
    slugs = {a.id: a.slug for a in db.scalars(select(Agent))}
    keys = [{"agent": slugs.get(k.agent_id, "") if k.agent_id else "", "central": k.agent_id is None, "env": k.env,
             "alias": k.alias, "models": k.models or [], "expires_at": iso(k.expires_at), "spend_usd": k.spend_usd,
             "spend_at": iso(k.spend_at)} for k in db.scalars(select(HubKey).order_by(HubKey.id))]
    return {"connected": True, "url": h.url, "ui_url": h.ui_url, "status": h.status, "error": h.error,
            "checked_at": iso(h.checked_at), "budget_usd": h.budget_usd, "budget_period": h.budget_period,
            "connection": conn.name if conn else "", "default_model": conn.model_name if conn else "",
            "models": kinds, "models_total": sum(kinds.values()), "keys": keys,
            "spend_usd": round(sum(k["spend_usd"] or 0 for k in keys), 6), "isolated": isolated}
