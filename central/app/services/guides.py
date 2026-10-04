"""Guia do agente, para quem vai usá-lo: um fluxo montado da spec (entrada → agente → skills, ferramentas, memória e
especialistas → saída), uma ficha factual e um texto em Markdown (o que é, o que faz, como usar).

O fluxo e a ficha saem sempre da spec da versão descrita: não custam nada e não ficam desatualizados. O texto fica
fora da spec (tabela agent_guides): corrigir a documentação não cria versão nova nem exige testes. Quem cria o agente
pelo chat escreve o texto (set_agent_guide); se uma versão vai para produção sem texto, o hangar gera um rascunho com
o LLM do agente, só a partir da spec e dos testes aprovados, marcado como rascunho até um mantenedor revisar."""
import json
import logging
import re
import threading

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..models import Agent, AgentGuide, AgentLineage, Schedule, TestRun, now
from .access import Access
from .common import PlatformError, audit, get_agent, spec_of
from .views import endpoints

log = logging.getLogger("hangar.guides")
MAX_TEXT = 20_000

GUIDE_SYSTEM = (
    "Você escreve o guia de um agente de IA corporativo para as pessoas que vão usá-lo. Use SOMENTE os fatos "
    "fornecidos (spec, ferramentas, especialistas e exemplos de pedidos que passaram nos testes): não invente "
    "capacidades, integrações, dados ou números. Escreva no idioma do objetivo do agente, em Markdown simples, com "
    "estas seções e nesta ordem: '## O que é' (2 frases), '## O que faz' (lista), '## O que não faz' (lista curta, só "
    "o que decorre dos fatos, por exemplo ferramentas que ele não tem), '## Como usar' (como pedir, com 2 a 4 pedidos de "
    "exemplo) e '## Limites' (dados que acessa, memória, quando chama especialistas). Se o idioma não for português, "
    "traduza os títulos das seções. No máximo 350 palavras. Responda só com o Markdown.")


# ------------------------------------------------------------------ leitura
def _version_spec(a: Agent, version: int) -> dict:
    if version == a.current_version:
        return spec_of(a)
    row = next((v for v in a.versions if v.version == version), None)
    return dict(row.spec) if row else spec_of(a)


def _running(a: Agent, env: str):
    return next((d for d in a.deployments if d.env == env and d.status == "running"), None)


def described_version(a: Agent) -> int:
    """O guia descreve a versão em produção; sem produção, a versão mais nova."""
    dep = _running(a, "prod")
    return dep.version if dep else a.current_version


def latest(db: Session, a: Agent) -> AgentGuide | None:
    return db.scalar(select(AgentGuide).where(AgentGuide.agent_id == a.id).order_by(AgentGuide.version.desc()))


def _names(items) -> list[str]:
    return [i if isinstance(i, str) else (i.get("name") or "") for i in items or [] if i]


def _model(spec: dict) -> str:
    h, llm = spec.get("harness"), spec.get("llm") or {}
    if h:
        return f"harness {h.get('id')}"
    return llm.get("model") or llm.get("connection") or config.DEFAULT_MODEL


def _examples(db: Session, a: Agent, version: int, spec: dict, limit=4) -> list[str]:
    """Pedidos dos casos de teste que passaram na versão descrita: exemplos reais, não inventados."""
    run = db.scalar(select(TestRun).where(TestRun.agent_id == a.id, TestRun.version == version,
                                          TestRun.status == "passed").order_by(TestRun.id.desc()))
    # testing.py grava os casos como "caso: <nome>" (os smokes são "smoke: …")
    names = {re.sub(r"^caso: ", "", r.get("name") or "") for r in (run.results or []) if r.get("passed")} if run else set()
    out = []
    for c in spec.get("tests", []):
        if c.get("workspace"):
            continue
        if run is None or not names or not c.get("name") or c["name"] in names:
            out.append(c["input"])
    return [x for x in out if x and x.strip().lower() not in ("ping", "olá", "oi")][:limit]


def _graph(db: Session, acc: Access, a: Agent, spec: dict, schedules: list[Schedule]) -> dict:
    """Nós e arestas do fluxo. Mostra QUAIS skills e ferramentas o agente usa — nunca o conteúdo delas."""
    nodes, edges = [], []

    def node(nid, kind, label, sub="", href=""):
        nodes.append({"id": nid, "kind": kind, "label": label, "sub": sub, "href": href})
        return nid

    channels = spec.get("channels") or []
    node("in", "input", "Pedido", ", ".join(channels) if channels else "Claude · ChatGPT · VS Code · API (OpenAI, MCP, A2A)")
    edges.append(["in", "agent"])
    for s in schedules:
        if s.enabled:
            node(f"sched{s.id}", "schedule", "Agendamento", s.name or "")
            edges.append([f"sched{s.id}", "agent"])
    node("agent", "agent", a.name, _model(spec))
    h = spec.get("harness")
    if h:
        node("job", "job", "Container efêmero", "1 por tarefa · devolve resultado + git diff")
        edges.append(["agent", "job"])
    for n in _names(spec.get("skills")):
        edges.append(["agent", node(f"skill:{n}", "skill", n, "skill")])
    for n in _names(spec.get("mcps")):
        edges.append(["agent", node(f"mcp:{n}", "mcp", n, "ferramentas MCP")])
    for t in spec.get("tools", []):
        edges.append(["agent", node(f"tool:{t['name']}", "tool", t["name"], "ferramenta")])
    mem = spec.get("memory")
    if mem:
        scope = {"agent": "só este agente", "team": "compartilhada com o time", "org": "compartilhada com a empresa"}
        edges.append(["agent", node("memory", "memory", "Memória", scope.get(mem.get("scope", "agent"), "")
                                    + ("" if mem.get("write", True) else " · só leitura"))])
    for sub in spec.get("sub_agents", []):
        sa = db.scalar(select(Agent).where(Agent.slug == sub))
        visible = bool(sa and acc.can("view", sa))
        edges.append(["agent", node(f"sub:{sub}", "specialist", sa.name if visible else sub,
                                    "especialista (A2A)", f"#/agents/{sub}" if visible else "")])
    node("out", "output", "Entrega", a.final_output)
    edges.append(["agent", "out"])
    return {"nodes": nodes, "edges": edges}


def guide(db: Session, acc: Access, slug: str) -> dict:
    a = get_agent(db, slug)
    acc.require("view", a)
    perms = acc.permissions(a)
    version = described_version(a)
    spec = _version_spec(a, version)
    schedules = list(db.scalars(select(Schedule).where(Schedule.agent_id == a.id)))
    lin = db.scalar(select(AgentLineage).where(AgentLineage.agent_id == a.id))
    prod, stage = _running(a, "prod"), _running(a, "stage")
    use = bool(perms & {"consume", "view_spec"})
    from .schedules import when_text
    facts = {
        "name": a.name, "slug": a.slug, "objective": a.objective, "final_output": a.final_output, "kind": a.kind,
        "owner": a.owner, "version": version, "prod_version": prod.version if prod else None,
        "stage_version": stage.version if stage else None, "model": _model(spec), "harness": bool(spec.get("harness")),
        "memory": spec.get("memory"), "skills": _names(spec.get("skills")), "mcps": _names(spec.get("mcps")),
        "tools": [t["name"] for t in spec.get("tools", [])], "sub_agents": list(spec.get("sub_agents", [])),
        "channels": spec.get("channels") or [],
        "schedules": [{"name": s.name, "when": when_text(s)} for s in schedules if s.enabled] if use else [],
        "built_from": ({"mode": lin.mode, "based_on": lin.based_on, "specialists": lin.specialists} if lin else None),
        "examples": _examples(db, a, version, spec) if use else [],
        "endpoints": endpoints(a.slug) if "consume" in perms else None,
    }
    g = latest(db, a)
    doc = None
    if g:
        doc = {"text": g.text, "source": g.source, "reviewed": g.reviewed, "version": g.version,
               "updated_by": g.updated_by, "updated_at": g.updated_at.isoformat() if g.updated_at else None,
               "outdated": g.version < version}
    return {"facts": facts, "graph": _graph(db, acc, a, spec, schedules), "doc": doc,
            "can_edit": "edit" in perms, "can_generate": "edit" in perms and _llm_target(db, spec) is not None}


def card_summary(db: Session, a: Agent) -> str:
    """Resumo para o agent card A2A: o primeiro parágrafo do guia revisado (nunca de um rascunho não revisado)."""
    g = latest(db, a)
    if not g or not g.reviewed or not g.text.strip():
        return ""
    for block in re.split(r"\n\s*\n", g.text):
        lines = [x for x in block.strip().splitlines() if x.strip() and not x.lstrip().startswith("#")]
        text = " ".join(x.strip().lstrip("-*• ").strip() for x in lines)
        text = re.sub(r"[*_`]", "", text).strip()
        if text:
            return text[:280]
    return ""


# ------------------------------------------------------------------ escrita
def _upsert(db: Session, a: Agent, version: int, text: str, source: str, reviewed: bool, actor: str) -> AgentGuide:
    row = db.scalar(select(AgentGuide).where(AgentGuide.agent_id == a.id, AgentGuide.version == version))
    if row is None:
        row = AgentGuide(agent_id=a.id, version=version)
        db.add(row)
    row.text, row.source, row.reviewed, row.updated_by, row.updated_at = text, source, reviewed, actor, now()
    db.commit()
    return row


def set_text(db: Session, acc: Access, slug: str, text: str, actor: str) -> dict:
    a = get_agent(db, slug)
    acc.require("edit", a)
    text = (text or "").strip()
    if not text:
        raise PlatformError("o guia não pode ficar vazio")
    if len(text) > MAX_TEXT:
        raise PlatformError(f"o guia passa de {MAX_TEXT} caracteres")
    version = described_version(a)
    _upsert(db, a, version, text, "author", True, actor)
    audit(db, actor, "agent.guide", slug, f"v{version}")
    return guide(db, acc, slug)


def approve(db: Session, acc: Access, slug: str, actor: str) -> dict:
    a = get_agent(db, slug)
    acc.require("edit", a)
    g = latest(db, a)
    if not g:
        raise PlatformError("este agente ainda não tem guia")
    g.reviewed, g.updated_by, g.updated_at = True, actor, now()
    db.commit()
    audit(db, actor, "agent.guide.approve", slug, f"v{g.version}")
    return guide(db, acc, slug)


# ------------------------------------------------------------------ rascunho gerado
def _llm_target(db: Session, spec: dict):
    """Conexão openai do juiz ou do próprio agente. Sem conexão (agente mock), não há rascunho gerado."""
    from .testing import _judge_target
    try:
        return _judge_target(db, spec)
    except PlatformError:
        return None


def _facts_prompt(db: Session, a: Agent, version: int, spec: dict) -> str:
    subs = []
    for s in spec.get("sub_agents", []):
        sa = db.scalar(select(Agent).where(Agent.slug == s))
        subs.append(f"- {sa.name}: {sa.objective}" if sa else f"- {s}")
    skills = [s if isinstance(s, str) else f"{s.get('name')}: {s.get('description', '')}" for s in spec.get("skills", [])]
    tools = [f"{t['name']}: {t.get('description', '')}" for t in spec.get("tools", [])]
    ex = _examples(db, a, version, spec, limit=6)
    parts = [f"Nome: {a.name}", f"Objetivo: {a.objective}", f"Entrega (saída final): {a.final_output}",
             f"Tipo: {'agente executor de código (harness)' if spec.get('harness') else a.kind}",
             "Instruções do agente:\n" + (spec.get("instructions") or "(sem instruções)")[:6000],
             "Skills: " + ("; ".join(skills) or "nenhuma"),
             "Servidores MCP: " + (", ".join(_names(spec.get("mcps"))) or "nenhum"),
             "Ferramentas: " + ("; ".join(tools) or "nenhuma"),
             "Memória de longo prazo: " + (json.dumps(spec.get("memory"), ensure_ascii=False) if spec.get("memory")
                                           else "não usa"),
             "Especialistas que ele chama:\n" + ("\n".join(subs) or "nenhum"),
             "Pedidos que passaram nos testes:\n" + ("\n".join(f"- {x}" for x in ex) or "nenhum")]
    return "\n\n".join(parts)


def generate_draft(db: Session, slug: str, actor: str = "hangar", force: bool = False) -> AgentGuide | None:
    """Gera o rascunho do guia da versão descrita. Não sobrescreve um texto escrito por pessoa, salvo com force."""
    a = get_agent(db, slug)
    version = described_version(a)
    row = db.scalar(select(AgentGuide).where(AgentGuide.agent_id == a.id, AgentGuide.version == version))
    if row and row.source == "author" and not force:
        return row
    spec = _version_spec(a, version)
    target = _llm_target(db, spec)
    if target is None:
        raise PlatformError("sem conexão de LLM (protocolo openai) para gerar o rascunho: defina llm.connection ou "
                            "judge.connection na spec, ou escreva o guia")
    base, key, model = target
    r = httpx.post(f"{base}/chat/completions", timeout=120, headers={"Authorization": f"Bearer {key}"} if key else {},
                   json={"model": model, "temperature": 0.2,
                         "messages": [{"role": "system", "content": GUIDE_SYSTEM},
                                      {"role": "user", "content": _facts_prompt(db, a, version, spec)}]})
    r.raise_for_status()
    text = (r.json()["choices"][0]["message"].get("content") or "").strip()
    text = re.sub(r"^```(?:markdown|md)?\s*|\s*```$", "", text).strip()
    if not text:
        raise PlatformError("o LLM não devolveu o texto do guia")
    row = _upsert(db, a, version, text[:MAX_TEXT], "generated", False, actor)
    audit(db, actor, "agent.guide.generate", slug, f"v{version}")
    return row


def generate(db: Session, acc: Access, slug: str, actor: str) -> dict:
    a = get_agent(db, slug)
    acc.require("edit", a)
    try:
        generate_draft(db, slug, actor, force=True)
    except httpx.HTTPError as e:
        raise PlatformError(f"falha ao chamar o LLM: {e}") from None
    return guide(db, acc, slug)


def after_promote(db: Session, a: Agent, version: int):
    """Uma versão subiu para produção sem guia escrito para ela: gera o rascunho em segundo plano (melhor esforço,
    não atrasa nem derruba o ship)."""
    if not config.GUIDE_AUTOGEN:
        return
    has = db.scalar(select(AgentGuide.id).where(AgentGuide.agent_id == a.id, AgentGuide.version == version))
    if has or _llm_target(db, _version_spec(a, version)) is None:
        return
    slug = a.slug

    def run():
        from ..db import SessionLocal
        try:
            with SessionLocal() as s:
                generate_draft(s, slug)
        except Exception as e:  # noqa: BLE001 — o guia nunca derruba o ship
            log.warning("rascunho do guia de %s não gerado: %s", slug, e)
    threading.Thread(target=run, name=f"guide-{slug}", daemon=True).start()

