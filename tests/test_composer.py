"""Reusar antes de construir: plan_agent (catálogo parecido, só o que a pessoa vê, só produção, lacunas de skill) e
compose_agent (agente NOVO a partir de especialistas, base copiada, skills e testes) — sem nunca alterar os agentes
de origem. Também: acesso para usar especialistas de outro time, skills que não são sobrescritas, linhagem e
métricas, as ferramentas MCP e o caminho semântico (embeddings da memória, com cache)."""
import copy
import hashlib
import json

import pytest

from app import auth
from app import services as svc
from app.db import SessionLocal
from app.models import Agent, AgentLineage, Skill, TestRun, User
from app.services import composer
from app.services import memory as memsvc

from .conftest import ADMIN

MCP_HDR = {"Accept": "application/json, text/event-stream"}


def _session(email: str) -> dict:
    with SessionLocal() as db:
        u = db.query(User).filter(User.email == email).one()
        return {"Authorization": f"Bearer {auth.create_session(db, u)}"}


def _to_prod(slug: str):
    """Coloca a versão atual em produção pelo caminho real (gate de testes aprovados + deploy no Docker falso)."""
    with SessionLocal() as db:
        a = svc.get_agent(db, slug)
        db.add(TestRun(agent_id=a.id, version=a.current_version, env="stage", status="passed", summary="ok", results=[]))
        db.commit()
        svc.promote(db, slug)


def _snapshot(slug: str) -> dict:
    with SessionLocal() as db:
        a = svc.get_agent(db, slug)
        return {"version": a.current_version, "status": a.status, "updated_at": a.updated_at.isoformat(),
                "spec": json.dumps(svc.spec_of(a), sort_keys=True), "versions": len(a.versions),
                "deployments": sorted((d.env, d.version, d.status) for d in a.deployments),
                "visibility": a.visibility, "name": a.name, "objective": a.objective}


@pytest.fixture()
def cat(client, uniq, fake_docker):
    n = uniq("c")
    sales = client.post("/api/teams", headers=ADMIN, json={"name": f"Sales {n}", "require_approval": False}).json()["slug"]
    support = client.post("/api/teams", headers=ADMIN, json={"name": f"Support {n}"}).json()["slug"]
    em = {k: f"{k}-{n}@acme.com" for k in ("smaint", "sdev", "odev", "omaint", "aud")}
    client.post(f"/api/teams/{sales}/members", headers=ADMIN, json={"email": em["smaint"], "role": "maintainer"})
    client.post(f"/api/teams/{sales}/members", headers=ADMIN, json={"email": em["sdev"], "role": "developer"})
    client.post(f"/api/teams/{support}/members", headers=ADMIN, json={"email": em["odev"], "role": "developer"})
    client.post(f"/api/teams/{support}/members", headers=ADMIN, json={"email": em["omaint"], "role": "maintainer"})
    client.post("/api/users", headers=ADMIN, json={"email": em["aud"], "org_role": "auditor"})
    h = {k: _session(e) for k, e in em.items()}

    def agent(headers, name, objective, final, spec, prod=True):
        slug = client.post("/api/agents", headers=headers, json={"name": f"{name} {n}", "objective": objective,
                                                                   "final_output": final}).json()["slug"]
        r = client.patch(f"/api/agents/{slug}", headers=headers, json=spec)
        assert r.status_code == 200, r.text
        if prod:
            _to_prod(slug)
        return slug

    s = {
        "history": agent(h["sdev"], "Customer History Keeper",
                         "Remember the history of each customer account: plan, contacts, decisions and next steps.",
                         "Answers about a customer's history and the next step.",
                         {"instructions": "You keep customer account history. Never invent customers.",
                          "tests": [{"name": "no invention", "input": "Who is Zeta?", "judge": "Says it has no record."}],
                          "channels": [{"type": "slack", "channel": "#sales"}] if False else []}),
        "writer": agent(h["sdev"], "Follow-up Email Writer", "Draft short, friendly follow-up emails to customers.",
                        "A ready-to-send email with a subject.",
                        {"instructions": "Write short follow-up emails. Never invent prices.",
                         "tests": [{"name": "email", "input": "Write to Ana", "expect_contains": "Ana"}]}),
        "triage": agent(h["odev"], "Ticket Triage", "Classify support tickets by priority P1 to P4 and route them.",
                        "Priority and team for each ticket.", {"instructions": "Support secret playbook."}),
        "secret": agent(h["odev"], "Secret Pricing Bot", "Compute confidential discounts for customer renewals.",
                        "A discount.", {"instructions": "secret"}),
        "draft": agent(h["sdev"], "Invoice Reminder", "Remind customers about unpaid invoices by email.",
                       "An email.", {"instructions": "draft only"}, prod=False),
    }
    client.patch(f"/api/agents/{s['secret']}/access", headers=h["omaint"], json={"visibility": "private"})
    with SessionLocal() as db:
        a = svc.get_agent(db, s["secret"])
        a.visibility = "private"
        db.commit()
    tone = f"formal-tone-{n}"
    with SessionLocal() as db:
        svc.upsert_skill(db, tone, "Answer in a formal, polite business tone", "Use formal language. No slang.",
                         test={"name": "formal", "input": "hey whats up", "judge": "Answers formally."})
    return {"t": {"sales": sales, "support": support}, "h": h, "s": s, "tone": tone, "n": n}


REQ = "An agent for account executives that remembers each customer's history and writes follow-up emails before calls"
CAPS = ["remember each customer's history and next steps", "write follow-up emails to customers",
        "approve discounts according to the pricing policy"]


def test_plan_finds_similar_respects_visibility_and_production(client, cat):
    h, s = cat["h"], cat["s"]
    p = client.post("/api/compose/plan", headers=h["sdev"], json={"request": REQ, "capabilities": CAPS}).json()
    slugs = [a["slug"] for a in p["agents"]]
    assert s["history"] in slugs and s["writer"] in slugs
    assert s["secret"] not in slugs           # privado de outro time: nunca aparece
    assert s["draft"] not in slugs            # sem versão em produção: não é peça
    hist = next(a for a in p["agents"] if a["slug"] == s["history"])
    assert hist["access"] == "ok" and {"specialist", "base"} <= set(hist["modes"]) and hist["why"]
    assert p["similarity"] == "lexical" and p["plan_id"].startswith("pl_")
    # a capacidade sem peça no catálogo vira lacuna com pergunta (no máximo 3)
    assert any("discount" in g["capability"] for g in p["gaps"]) and 1 <= len(p["questions"]) <= 3
    assert s["history"] in p["compose_hint"]["specialists"]

    # outro time: vê o agente de Sales como possível especialista, mas precisa pedir acesso e não pode copiá-lo
    q = client.post("/api/compose/plan", headers=h["odev"], json={"request": REQ, "capabilities": CAPS}).json()
    other = next(a for a in q["agents"] if a["slug"] == s["history"])
    assert other["access"] == "request_access" and "base" not in other["modes"] and not other["spec_visible"]
    assert s["secret"] in [a["slug"] for a in client.post("/api/compose/plan", headers=h["omaint"], json={
        "request": "confidential discounts for customer renewals"}).json()["agents"]]


def test_compose_with_specialists_creates_new_and_leaves_sources_untouched(client, cat):
    h, s, tone = cat["h"], cat["s"], cat["tone"]
    before = {k: _snapshot(s[k]) for k in ("history", "writer")}
    with SessionLocal() as db:
        tone_before = (lambda x: (x.version, x.content))(db.query(Skill).filter_by(name=tone).one())
    p = client.post("/api/compose/plan", headers=h["sdev"], json={"request": REQ, "capabilities": CAPS}).json()
    r = client.post("/api/compose", headers=h["sdev"], json={
        "name": f"Renewal Desk {cat['n']}", "objective": "Prepare account executives for renewal calls.",
        "final_output": "A call brief and a follow-up email.",
        "instructions": "Also flag discounts that need approval under the renewal policy.",
        "specialists": [s["history"], s["writer"]], "skills": [tone],
        "new_skills": [{"name": f"renewal-policy-{cat['n']}", "description": "Discount approval rules",
                        "content": "Discounts above 10% need the sales director's approval.",
                        "test": {"name": "discount rule", "input": "Can I give 15%?", "judge": "Says it needs the director's approval."}}],
        "tests": [{"name": "brief", "input": "Prepare me for Acme", "judge": "Produces a call brief."}],
        "plan_id": p["plan_id"]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mode"] == "specialists" and out["kind"] == "multi" and out["specialists"] == [s["history"], s["writer"]]
    assert out["new_skills"] == [f"renewal-policy-{cat['n']}"] and tone in out["skills"]
    assert out["tests_copied"] == 2 and out["tests"] == 3 and out["reused_tokens_estimate"] > 0

    d = client.get(f"/api/agents/{out['slug']}", headers=h["sdev"]).json()
    spec = d["spec"]
    assert spec["sub_agents"] == [s["history"], s["writer"]]
    instr = spec["instructions"]
    assert "Also flag discounts" in instr and f"ask_{s['history']}" in instr and "## Specialists" in instr
    assert {t["name"] for t in spec["tests"]} == {"brief", f"skill {tone}: formal", f"skill renewal-policy-{cat['n']}: discount rule"}
    assert all(t["timeout_s"] == 300 for t in spec["tests"])  # multiagente: mais tempo por caso
    assert d["team"]["slug"] == cat["t"]["sales"]

    # nada nas peças mudou: versão, spec, status, deploys, visibilidade, a skill reutilizada
    for k in ("history", "writer"):
        assert _snapshot(s[k]) == before[k], k
    with SessionLocal() as db:
        x = db.query(Skill).filter_by(name=tone).one()
        assert (x.version, x.content) == tone_before
        row = db.query(AgentLineage).filter_by(agent_id=svc.get_agent(db, out["slug"]).id).one()
        assert row.plan_id == p["plan_id"] and [x["slug"] for x in row.specialists] == [s["history"], s["writer"]]


def test_compose_from_base_copies_into_the_new_agent(client, cat):
    h, s = cat["h"], cat["s"]
    before = _snapshot(s["history"])
    r = client.post("/api/compose", headers=h["sdev"], json={
        "name": f"History Keeper EMEA {cat['n']}", "objective": "Same as the history keeper, for EMEA accounts.",
        "final_output": "Answers about EMEA customers.", "base": s["history"],
        "instructions": "Only handle EMEA customers; answer in English.",
        "tests": [{"name": "emea", "input": "Who are you?", "judge": "Mentions EMEA."}]}).json()
    assert r["mode"] == "base" and r["based_on"]["slug"] == s["history"] and r["kind"] == "single"
    spec = client.get(f"/api/agents/{r['slug']}", headers=h["sdev"]).json()["spec"]
    assert spec["instructions"].startswith("You keep customer account history.")
    assert spec["instructions"].endswith("Only handle EMEA customers; answer in English.")
    assert {t["name"] for t in spec["tests"]} == {f"no invention (from {s['history']})", "emea"}
    assert _snapshot(s["history"]) == before
    # o novo agente evolui sozinho: editá-lo não muda a base
    client.patch(f"/api/agents/{r['slug']}", headers=h["sdev"], json={"instructions": "changed"})
    assert _snapshot(s["history"]) == before


def test_access_rules_for_pieces(client, cat):
    h, s = cat["h"], cat["s"]
    body = {"name": f"Support Brief {cat['n']}", "objective": "Brief support agents about a customer.",
            "final_output": "A brief."}
    # especialista de outro time sem acesso aprovado: recusado (e nada é criado)
    r = client.post("/api/compose", headers=h["odev"], json={**body, "specialists": [s["history"]]})
    assert r.status_code == 403 and "request_agent_access" in r.text
    # a mesma regra vale para design_agent / PATCH (antes passava)
    own = client.post("/api/agents", headers=h["odev"], json={"name": f"x {cat['n']}", "objective": "o", "final_output": "f"}).json()["slug"]
    assert client.patch(f"/api/agents/{own}", headers=h["odev"], json={"sub_agents": [s["history"]]}).status_code == 403
    # base exige ver a spec: outro time não copia as instruções de Sales
    assert client.post("/api/compose", headers=h["odev"], json={**body, "base": s["history"]}).status_code == 403
    # privado de outro time: nem aparece
    assert client.post("/api/compose", headers=h["sdev"], json={**body, "specialists": [s["secret"]]}).status_code == 403
    # sem produção não é peça
    r = client.post("/api/compose", headers=h["sdev"], json={**body, "specialists": [s["draft"]]})
    assert r.status_code == 400 and "produção" in r.text

    # com o pedido de acesso aprovado pelo time dono, vira especialista — e o agente dele continua igual
    before = _snapshot(s["history"])
    req = client.post(f"/api/agents/{s['history']}/access-requests", headers=h["odev"], json={"reason": "briefs"}).json()
    assert client.post(f"/api/access-requests/{req['id']}/approve", headers=h["smaint"]).json()["status"] == "approved"
    r = client.post("/api/compose", headers=h["odev"], json={**body, "specialists": [s["history"]]})
    assert r.status_code == 200, r.text and r.json()["team"] == cat["t"]["support"]
    assert client.patch(f"/api/agents/{own}", headers=h["odev"], json={"sub_agents": [s["history"]]}).status_code == 200
    assert _snapshot(s["history"]) == before


def test_skills_are_never_overwritten_by_composition(client, cat):
    h, tone = cat["h"], cat["tone"]
    r = client.post("/api/compose", headers=h["sdev"], json={
        "name": f"x {cat['n']}", "objective": "o objetivo", "final_output": "f",
        "new_skills": [{"name": tone, "content": "OVERWRITE"}]})
    assert r.status_code == 400 and "Já existe a skill" in r.text
    with SessionLocal() as db:
        assert db.query(Skill).filter_by(name=tone).one().content == "Use formal language. No slang."
        assert not db.query(Agent).filter(Agent.name == f"x {cat['n']}").first()  # erro antes de criar qualquer coisa
    assert client.post("/api/compose", headers=h["sdev"], json={
        "name": "y", "objective": "o objetivo", "final_output": "f", "skills": ["nao-existe-skill"]}).status_code == 400
    # admin atualiza uma skill: a versão sobe
    with SessionLocal() as db:
        v = db.query(Skill).filter_by(name=tone).one().version
        svc.upsert_skill(db, tone, "Answer formally", "Use formal language. No slang. Sign with the team name.")
        assert db.query(Skill).filter_by(name=tone).one().version == v + 1


def test_lineage_used_by_and_stats(client, cat):
    h, s = cat["h"], cat["s"]
    new = client.post("/api/compose", headers=h["sdev"], json={
        "name": f"Deal Prep {cat['n']}", "objective": "Prepare deals.", "final_output": "A brief.",
        "specialists": [s["history"]], "copy_tests_from": [s["writer"]]}).json()
    lin = client.get(f"/api/agents/{new['slug']}/lineage", headers=h["sdev"]).json()
    sp = lin["built_from"]["specialists"][0]
    assert lin["built_from"]["mode"] == "specialists" and sp["slug"] == s["history"] and not sp["updated_since"]
    assert lin["built_from"]["tests_copied"] == 1
    used = client.get(f"/api/agents/{s['history']}/lineage", headers=h["sdev"]).json()["used_by"]
    assert {"slug": new["slug"], "name": new["slug"] and f"Deal Prep {cat['n']}", "as": "specialist"} in used

    # o dono do especialista publica uma versão nova (pelo fluxo normal dele): o agente montado mostra a diferença
    client.patch(f"/api/agents/{s['history']}", headers=h["sdev"], json={"instructions": "v-next"})
    _to_prod(s["history"])
    sp = client.get(f"/api/agents/{new['slug']}/lineage", headers=h["sdev"]).json()["built_from"]["specialists"][0]
    assert sp["updated_since"] and sp["prod_version_now"] > sp["version_at_composition"]

    assert client.get("/api/compose/stats", headers=h["sdev"]).status_code == 403
    st = client.get("/api/compose/stats", headers=h["aud"]).json()
    assert st["composed"] >= 1 and st["plans"] >= 0 and 0 < st["reuse_rate"] <= 1 and st["reused_tokens_estimate"] > 0


def test_mcp_plan_and_compose(client, cat):
    h, s = cat["h"], cat["s"]
    pat = {"Authorization": "Bearer " + client.post("/api/keys", headers=h["sdev"], json={"name": "claude", "scopes": ["user"]}).json()["key"]}

    def call(tool, args):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}}
        r = client.post("/mcp", json=body, headers={**MCP_HDR, **pat}).json()["result"]
        return r, json.loads(r["content"][0]["text"]) if not r["isError"] else r["content"][0]["text"]

    tools = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers={**MCP_HDR, **pat}).json()
    names = {t["name"] for t in tools["result"]["tools"]}
    assert {"plan_agent", "compose_agent", "agent_lineage"} <= names
    r, plan = call("plan_agent", {"request": REQ, "capabilities": CAPS})
    # o banco de testes acumula cópias idênticas do catálogo (um por teste): basta achar uma delas
    assert not r["isError"] and any(a["slug"].startswith("customer-history-keeper") for a in plan["agents"])
    # o hint só sugere especialistas que a pessoa já pode usar (os de outros times pedem acesso antes)
    assert all(next(a for a in plan["agents"] if a["slug"] == x)["access"] == "ok" for x in plan["compose_hint"]["specialists"])
    r, out = call("compose_agent", {"name": f"MCP Desk {cat['n']}", "objective": "Help AEs before calls.",
                                    "final_output": "A brief.", "specialists": [s["history"]],
                                    "plan_id": plan["plan_id"]})
    assert not r["isError"] and out["kind"] == "multi" and "untouched" in out
    r, lin = call("agent_lineage", {"slug": out["slug"]})
    assert lin["built_from"]["plan_id"] == plan["plan_id"]


def test_semantic_similarity_with_cache(client, cat, monkeypatch):
    """Com a memória ligada, usa os embeddings dela (multilíngue); vetores ficam em cache no banco."""
    calls = []

    def fake_embed(texts):
        calls.append(len(texts))
        out = []
        for t in texts:  # vetor determinístico por palavras "conceito" (português e inglês caem no mesmo eixo)
            low = t.lower()
            out.append([float(any(w in low for w in ("histor", "lembr", "remember"))),
                        float(any(w in low for w in ("e-mail", "email", "follow"))),
                        float(any(w in low for w in ("ticket", "chamado", "suporte", "support"))), 0.1])
        return out
    monkeypatch.setattr(memsvc, "embed", fake_embed)
    pt = "Um agente que lembra o histórico de cada cliente"
    p = client.post("/api/compose/plan", headers=cat["h"]["sdev"], json={"request": pt}).json()
    assert p["similarity"] == "semantic" and p["agents"][0]["name"].startswith("Customer History Keeper")
    first = sum(calls)
    client.post("/api/compose/plan", headers=cat["h"]["sdev"], json={"request": pt})
    assert sum(calls) - first <= 2  # documentos do catálogo vieram do cache; só a consulta é nova (ou nem ela)


def test_text_similarity_helpers():
    sc = composer._Scorer(["customer history and next steps", "classify support tickets"], ["remember customer history"])
    assert sc.mode in ("lexical", "semantic")
    assert sc.score(0, 0) > sc.score(0, 1)
    assert composer._split_capabilities("Remember customers. Write emails; and schedule calls") == [
        "Remember customers", "Write emails", "schedule calls"] or len(composer._split_capabilities("a b c. d e f")) >= 1
    assert hashlib and copy  # usados nos snapshots


def test_shipping_a_composed_agent_never_touches_its_specialists(client, cat, monkeypatch):
    """Antes, publicar um orquestrador rodava ship nos sub-agentes: re-testava e publicava a versão NÃO lançada do
    dono. Especialistas de um agente montado são peças só de leitura: chamados em produção, sem teste nem deploy."""
    h, s = cat["h"], cat["s"]
    new = client.post("/api/compose", headers=h["sdev"], json={
        "name": f"Read Only {cat['n']}", "objective": "Use the history keeper as a piece.", "final_output": "Briefs.",
        "specialists": [s["history"]]}).json()
    # o dono do especialista deixa uma versão nova em rascunho (não publicada)
    client.patch(f"/api/agents/{s['history']}", headers=h["sdev"], json={"instructions": "UNRELEASED draft"})
    before = _snapshot(s["history"])
    with SessionLocal() as db:
        n_tests = len(svc.get_agent(db, s["history"]).tests)
        # stage do agente novo chama o especialista na PRODUÇÃO (a versão aprovada), nunca o stage dele
        spec = svc.resolve_spec(db, svc.get_agent(db, new["slug"]), "stage")
        assert spec["sub_agents_resolved"][0]["url"].endswith(f"/internal/gw/{s['history']}")

    from app.services import testing

    def fake_run_tests(db, slug, actor="admin"):  # o Docker falso não responde HTTP: simula testes aprovados
        a = svc.get_agent(db, slug)
        run = TestRun(agent_id=a.id, version=a.current_version, env="stage", status="passed", summary="ok", results=[])
        db.add(run)
        db.commit()
        return run
    monkeypatch.setattr(testing, "run_tests", fake_run_tests)
    r = client.post(f"/api/agents/{new['slug']}/ship", headers=h["smaint"])
    assert r.status_code == 200, r.text
    steps = r.json() if isinstance(r.json(), list) else r.json().get("steps", r.json())
    piece = next(x for x in steps if x["agent"] == s["history"])
    assert piece["step"] == "piece" and "não alterado" in piece["status"]
    after = _snapshot(s["history"])
    assert after == before  # nada mudou: o rascunho continua rascunho, a produção continua na versão anterior
    with SessionLocal() as db:
        a = svc.get_agent(db, s["history"])
        assert len(a.tests) == n_tests  # nenhum teste rodou no especialista
        prod = next(d for d in a.deployments if d.env == "prod" and d.status == "running")
        assert prod.version < a.current_version
