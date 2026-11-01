"""Modelos que o provedor vai descontinuar: quem usa é avisado antes, com um substituto e a troca testada em stage.

- A data vem da tabela pública do LiteLLM (deprecation_date), lida na atualização da lista de cada conexão, ou do
  admin (Provedores de LLM → o modelo), que a coleta não desfaz.
- Uso: o modelo do agente (llm), do harness, do juiz dos testes e o modelo por resposta (execution.light_model), em
  stage e em produção; um modelo vazio na spec é o padrão da conexão. Também conta ser o padrão da conexão e estar
  sincronizado com o Hangar desktop.
- Avisos na caixa de entrada a 60, 30, 14, 7 e 1 dia(s) da data e depois dela (MODEL_DEPRECATION_WARN_DAYS define a
  antecedência): o admin vê o modelo e todos que usam; quem edita o agente vê o seu agente. Cada faixa é um item novo,
  então quem arquivou o aviso de 30 dias recebe o de 7.
- Substituto: um modelo da mesma conexão, do mesmo tipo e com os mesmos recursos (ferramentas, imagens), sem data de
  saída próxima, de preferência da mesma família e numa versão mais nova.
- Nada muda sozinho: a troca cria uma versão nova do agente e roda os testes em stage (org.edit_agent); a produção
  segue na versão anterior até alguém publicar.
"""
import re
import time
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..models import Agent, LlmConnection, LlmModel, now
from ..tenancy import current_org
from .common import PlatformError, audit, get_agent, spec_of

STAGES = (60, 30, 14, 7, 1)
BLOCKING_DAYS = 7  # daqui para baixo o aviso entra em "Travados" na caixa de entrada
WHERE_LABEL = {"llm": "modelo do agente", "harness": "harness", "judge": "juiz dos testes",
               "light_model": "modelo por resposta"}
_NOISE = {"latest", "preview", "exp", "experimental", "chat", "instruct", "it", "v"}


def horizon() -> int:
    return max(1, config.MODEL_DEPRECATION_WARN_DAYS)


def days_left(d: date) -> int:
    return (d - now().date()).days


def stage_of(days: int) -> int:
    """A faixa do aviso: 60, 30, 14, 7, 1 ou 0 (a data já chegou)."""
    if days <= 0:
        return 0
    return min(s for s in STAGES if s >= days) if days <= STAGES[0] else STAGES[0]


def stage_started(d: date, stage: int) -> datetime:
    """Quando a faixa do aviso começou (data estável: ler o aviso não o faz voltar como novo)."""
    return datetime.combine(d - timedelta(days=stage), datetime.min.time(), tzinfo=UTC)


def when_text(d: date) -> str:
    n = days_left(d)
    if n > 1:
        return f"sai do provedor em {d.isoformat()} (em {n} dias)"
    if n == 1:
        return f"sai do provedor amanhã ({d.isoformat()})"
    if n == 0:
        return f"sai do provedor hoje ({d.isoformat()})"
    return f"saiu do provedor em {d.isoformat()}"


# ------------------------------------------------------------------ quem usa
def uses_of(spec: dict, conns: dict[str, LlmConnection]) -> list[tuple[str, str, str, str]]:
    """(conexão, modelo, onde, ambiente) que a spec usa; o modelo vazio vira o padrão da conexão."""
    out = []
    for env in ("stage", "prod"):
        llm_conn = ""
        for key in ("llm", "harness", "judge"):
            b = spec.get(key) or {}
            o = b.get(env) if isinstance(b.get(env), dict) else {}
            c = o.get("connection") or b.get("connection")
            if not c:
                continue
            if key == "llm":
                llm_conn = c
            m = o.get("model") or b.get("model") or (conns[c].model_name if c in conns else "")
            if m:
                out.append((c, m, key, env))
        light = ((spec.get("execution") or {}).get("light_model") or "").strip()
        if light and light != "auto" and llm_conn:
            out.append((llm_conn, light, "light_model", env))
    return out


def usage_map(db: Session) -> dict[tuple[str, str], list[dict]]:
    """(conexão, modelo) -> agentes que usam, com onde e em que ambiente."""
    conns = {c.name: c for c in db.scalars(select(LlmConnection))}
    out: dict[tuple[str, str], dict[int, dict]] = {}
    for a in db.scalars(select(Agent)):
        if a.status == "archived":
            continue
        try:
            spec = spec_of(a)
        except Exception:
            continue
        for c, m, where, env in uses_of(spec, conns):
            row = out.setdefault((c, m), {}).setdefault(a.id, {"agent": a.slug, "agent_id": a.id, "name": a.name,
                                                               "where": [], "envs": []})
            if where not in row["where"]:
                row["where"].append(where)
            if env not in row["envs"]:
                row["envs"].append(env)
    return {k: list(v.values()) for k, v in out.items()}


# ------------------------------------------------------------------ substituto
def _tail(mid: str) -> str:
    return mid.lower().rsplit("/", 1)[-1]


def _family(mid: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", _tail(mid)) if t not in _NOISE and len(t) > 1}


def _version(mid: str) -> tuple:
    """Números do nome (3-5 → (3, 5)), sem as datas (20240620), que só desempatam."""
    nums = re.findall(r"\d+", _tail(mid))
    return (tuple(int(n) for n in nums if len(n) < 6), max((int(n) for n in nums if len(n) >= 6), default=0))


def replacement(db: Session, conn: LlmConnection, m: LlmModel) -> dict | None:
    """O melhor substituto na mesma conexão: mesmo tipo e recursos, sem saída próxima, família parecida, mais novo."""
    limit = now().date() + timedelta(days=horizon() * 2)
    need = {c for c in (m.caps or []) if c in ("tools", "vision")}
    fam, ver = _family(m.model_id), _version(m.model_id)
    best, best_key = None, None
    q = select(LlmModel).where(LlmModel.connection_id == conn.id, LlmModel.available.is_(True),
                               LlmModel.kind == m.kind, LlmModel.id != m.id)
    for x in db.scalars(q):
        if x.deprecates_on and x.deprecates_on <= limit:
            continue
        if not need <= set(x.caps or []):
            continue
        if m.context_length and x.context_length and x.context_length < m.context_length // 2:
            continue
        f = _family(x.model_id)
        sim = len(fam & f) / len(fam | f) if fam | f else 0.0
        v = _version(x.model_id)
        # preço parecido vem antes da versão: quem usa um modelo barato não deve ser levado ao mais caro da casa
        gap = (abs((x.price_in_per_mtok or 0) - m.price_in_per_mtok) / max(m.price_in_per_mtok, 0.01)
               if m.price_in_per_mtok is not None and x.price_in_per_mtok is not None else 0.5)
        key = (round(sim, 2), v >= ver, -round(gap, 2), v, x.first_seen.timestamp() if x.first_seen else 0)
        if best_key is None or key > best_key:
            best, best_key = x, key
    if best is None:
        return None
    reasons = []
    if best_key[0] >= 0.5:
        reasons.append("mesma família")
    if _version(best.model_id) > ver:
        reasons.append("versão mais nova")
    reasons.append("sem data de saída próxima" if not best.deprecates_on else f"sai só em {best.deprecates_on.isoformat()}")
    if need:
        reasons.append("com " + " e ".join({"tools": "ferramentas", "vision": "leitura de imagens"}[c] for c in sorted(need)))
    if best.price_in_per_mtok is not None or best.price_out_per_mtok is not None:
        reasons.append(f"US$ {best.price_in_per_mtok or 0} / {best.price_out_per_mtok or 0} por 1M tokens"
                       + (f" (hoje: {m.price_in_per_mtok or 0} / {m.price_out_per_mtok or 0})"
                          if m.price_in_per_mtok is not None or m.price_out_per_mtok is not None else ""))
    return {"connection": conn.name, "model": best.model_id, "reasons": reasons,
            "price_in_per_mtok": best.price_in_per_mtok, "price_out_per_mtok": best.price_out_per_mtok}


# ------------------------------------------------------------------ a lista
def deprecations(db: Session, all_dates: bool = False) -> list[dict]:
    """Modelos com data de saída dentro da antecedência (ou já vencida) e quem usa cada um. all_dates: todos os que
    têm data, mesmo longe."""
    today = now().date()
    q = (select(LlmModel, LlmConnection).join(LlmConnection, LlmConnection.id == LlmModel.connection_id)
         .where(LlmModel.deprecates_on.is_not(None)))
    if not all_dates:
        q = q.where(LlmModel.deprecates_on <= today + timedelta(days=horizon()))
    uses = usage_map(db)
    out = []
    for m, c in db.execute(q.order_by(LlmModel.deprecates_on)):
        hidden = set(c.desktop_hidden_models or [])
        desktop = bool(c.sync_desktop) and m.kind == "text" and m.model_id not in hidden
        agents = uses.get((c.name, m.model_id), [])
        n = days_left(m.deprecates_on)
        out.append({"model_pk": m.id, "connection": c.name, "provider": c.provider or "custom", "model": m.model_id,
                    "deprecates_on": m.deprecates_on.isoformat(), "source": m.deprecation_source, "days_left": n,
                    "stage": stage_of(n), "when": when_text(m.deprecates_on), "agents": agents,
                    "connection_default": c.model_name == m.model_id, "desktop": desktop,
                    "in_use": bool(agents) or c.model_name == m.model_id or desktop,
                    "replacement": replacement(db, c, m)})
    return out


_CACHE: dict[int, tuple[float, list]] = {}


def cached(db: Session, ttl: float = 600) -> list[dict]:
    """A lista da empresa, recalculada no máximo a cada 10 minutos (a caixa de entrada abre muitas vezes)."""
    org = current_org()
    hit = _CACHE.get(org)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = deprecations(db)
    _CACHE[org] = (time.time(), val)
    return val


def forget():
    _CACHE.clear()


# ------------------------------------------------------------------ o agente
def change_for(spec: dict, conns: dict[str, LlmConnection], conn: str, old: str, new: str) -> dict:
    """O merge patch que troca `old` por `new` em todo lugar da spec que usa (conn, old)."""
    patch: dict = {}
    for key in ("llm", "harness", "judge"):
        b = spec.get(key) or {}
        if not b:
            continue
        base_c = b.get("connection") or ""
        base_m = b.get("model") or (conns[base_c].model_name if base_c in conns else "")
        if base_c == conn and base_m == old:
            patch.setdefault(key, {})["model"] = new
        for env in ("stage", "prod"):
            o = b.get(env) if isinstance(b.get(env), dict) else None
            if not o:
                continue
            c = o.get("connection") or base_c
            m = o.get("model") or (base_m if not o.get("connection") else (conns[c].model_name if c in conns else ""))
            if c == conn and m == old and (o.get("model") or o.get("connection")):
                patch.setdefault(key, {})[env] = {"model": new}
    llm = spec.get("llm") or {}
    if ((spec.get("execution") or {}).get("light_model") or "") == old and llm.get("connection") == conn:
        patch["execution"] = {"light_model": new}
    return patch


def for_agent(db: Session, a: Agent) -> list[dict]:
    """Os modelos do agente com data de saída (qualquer data conhecida), cada um com o substituto e a troca pronta."""
    conns = {c.name: c for c in db.scalars(select(LlmConnection))}
    spec = spec_of(a)
    seen, out = set(), []
    for c, mid, _where, _env in uses_of(spec, conns):
        if (c, mid) in seen or c not in conns:
            continue
        seen.add((c, mid))
        m = db.scalar(select(LlmModel).where(LlmModel.connection_id == conns[c].id, LlmModel.model_id == mid))
        if m is None or m.deprecates_on is None:
            continue
        n = days_left(m.deprecates_on)
        rep = replacement(db, conns[c], m)
        uses = [u for u in uses_of(spec, conns) if u[0] == c and u[1] == mid]
        out.append({"connection": c, "model": mid, "deprecates_on": m.deprecates_on.isoformat(), "days_left": n,
                    "stage": stage_of(n), "when": when_text(m.deprecates_on), "soon": n <= horizon(),
                    "where": sorted({u[2] for u in uses}), "envs": sorted({u[3] for u in uses}),
                    "replacement": rep,
                    "changes": change_for(spec, conns, c, mid, rep["model"]) if rep else None})
    return out


def warnings_for(db: Session, a: Agent) -> list[str]:
    """Avisos curtos para quem constrói ou edita o agente (MCP): modelos dele que vão sair."""
    return [f"o modelo {x['model']} ({x['connection']}) {x['when']}"
            + (f"; use {x['replacement']['model']}" if x["replacement"] else "") for x in for_agent(db, a)
            if x["days_left"] <= horizon() * 3]


def swap(db: Session, acc, slug: str, connection: str, model: str, to: str = "", test: bool = True) -> dict:
    """Troca o modelo que vai sair por `to` (padrão: o substituto recomendado) numa versão nova, testada em stage."""
    from . import org
    a = get_agent(db, slug)
    acc.require("edit", a)
    item = next((x for x in for_agent(db, a) if x["connection"] == connection and x["model"] == model), None)
    if item is None:
        raise PlatformError(f"o agente não usa o modelo '{model}' da conexão '{connection}', ou ele não tem data de saída")
    target = to or (item["replacement"] or {}).get("model") or ""
    if not target:
        raise PlatformError("não há substituto compatível nessa conexão; informe o modelo (to) ou peça a um admin "
                            "para cadastrar um")
    conns = {c.name: c for c in db.scalars(select(LlmConnection))}
    patch = change_for(spec_of(a), conns, connection, model, target)
    out = org.edit_agent(db, acc, slug, patch, test=test, note=f"troca de {model} (descontinuado) por {target}")
    audit(db, acc.p.name, "agent.model_deprecation_swap", slug, f"{connection}: {model} → {target}")
    forget()
    return {**out, "from": model, "to": target, "connection": connection}


# ------------------------------------------------------------------ caixa de entrada
def inbox_items(db: Session, acc) -> list[dict]:
    """Os avisos de quem está olhando: o admin vê cada modelo e todos que usam; quem edita um agente vê o seu."""
    out = []
    for x in cached(db):
        if not x["in_use"]:
            continue
        rep = f" Recomendado: {x['replacement']['model']}." if x["replacement"] else " Sem substituto na conexão."
        blocked = x["days_left"] <= BLOCKING_DAYS
        at = stage_started(date.fromisoformat(x["deprecates_on"]), x["stage"])
        if acc.p.is_admin:
            names = [u["name"] for u in x["agents"]]
            extra = ([", ".join(names[:5]) + (f" e mais {len(names) - 5}" if len(names) > 5 else "")] if names else [])
            extra += ["o padrão da conexão"] if x["connection_default"] else []
            extra += ["o Hangar desktop"] if x["desktop"] else []
            out.append({"key": f"deprec:{x['model_pk']}:{x['stage']}",
                        "title": f"O modelo {x['model']} ({x['connection']}) {x['when']} e é usado por {', '.join(extra)}.{rep}",
                        "link": f"#/providers/{x['provider']}", "blocked": blocked, "at": at,
                        "data": {"connection": x["connection"], "model": x["model"], "deprecates_on": x["deprecates_on"],
                                 "agents": [u["agent"] for u in x["agents"]]}})
            continue
        for u in x["agents"]:
            a = db.get(Agent, u["agent_id"])
            if a is None or not acc.can("edit", a):
                continue
            out.append({"key": f"deprec:{x['model_pk']}:{a.id}:{x['stage']}",
                        "title": f"{a.name}: o modelo {x['model']} {x['when']}.{rep} Troque e teste na página do agente.",
                        "link": f"#/agents/{a.slug}", "blocked": blocked, "at": at,
                        "data": {"agent": a.slug, "connection": x["connection"], "model": x["model"],
                                 "deprecates_on": x["deprecates_on"]}})
    return out
