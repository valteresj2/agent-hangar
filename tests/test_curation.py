# ruff: noqa: F811  (env e rt são fixtures importadas de test_employees)
"""Curadoria noturna das lições: propõe juntar, reescrever, retirar e criar lições; o gestor aplica ou dispensa."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.db import SessionLocal
from app.models import Agent, Employee, Organization
from app.services import curation, llm

from .test_employees import assign, env, hire, make_active, rt, work  # noqa: F401


@pytest.fixture(autouse=True)
def _reset():
    curation._last_run.clear()
    yield
    curation._last_run.clear()


def _lesson(client, env, slug, text):
    r = client.post(f"/api/employees/{slug}/lessons", headers=env["h"]["mgr"], json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()["lesson"]["id"]


def _curation_sugs(client, env, slug):
    return [s for s in client.get(f"/api/employees/{slug}/suggestions", headers=env["h"]["mgr"]).json()
            if s["kind"] == "curation"]


def _fake_model(monkeypatch, items, seen=None):
    monkeypatch.setattr(llm, "target_for_employee", lambda db, e: ("http://llm", "k", "m"))

    def call(base, key, model, system, user, json_mode=False):
        if seen is not None:
            seen.append(user)
        return json.dumps({"items": items})
    monkeypatch.setattr(llm, "CALL", call)


def test_without_a_model_repeated_lessons_become_one(client, env, rt):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    a = _lesson(client, env, slug, "Confira o CNPJ antes de lançar.")
    b = _lesson(client, env, slug, "confira o CNPJ antes de lançar")
    _lesson(client, env, slug, "Responda em português.")
    out = client.post(f"/api/employees/{slug}/curation", headers=env["h"]["mgr"]).json()
    assert out["curation"]["source"] == "regra" and len(out["items"]) == 1
    sug = _curation_sugs(client, env, slug)[0]
    assert sug["action"] == "merge" and {x["id"] for x in sug["replaces"]} == {a, b}
    assert client.post(f"/api/employees/{slug}/curation", headers=env["h"]["req"]).status_code in (403, 404)
    r = client.post(f"/api/employees/{slug}/suggestions/{sug['id']}/apply", headers=env["h"]["mgr"],
                    json={"text": "Confira o CNPJ na Receita antes de lançar."})
    texts = [x["text"] for x in r.json()["lessons"]]
    assert texts == ["Responda em português.", "Confira o CNPJ na Receita antes de lançar."]
    assert _curation_sugs(client, env, slug) == []  # as lições citadas não existem mais


def test_the_model_proposes_and_only_valid_proposals_survive(client, env, rt, monkeypatch):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    old = _lesson(client, env, slug, "Use o modelo de e-mail antigo de cobrança.")
    keep = _lesson(client, env, slug, "Sempre cite o número da fatura.")
    tid = assign(client, env, slug, "resolva a cobrança da fatura 88")
    work()
    seen: list[str] = []
    _fake_model(monkeypatch, [
        {"action": "remove", "lessons": [old], "text": "", "why": f"o gestor recusou o modelo antigo em #{tid}", "tasks": [tid]},
        {"action": "new", "lessons": [], "text": "Antes de cobrar, confira se o pagamento já caiu.", "why": "duas tarefas", "tasks": [tid, 999999]},
        {"action": "rewrite", "lessons": ["nao-existe"], "text": "x", "why": "id inventado"},  # lição inexistente: fora
        {"action": "merge", "lessons": [keep], "text": "só uma", "why": "merge de uma só"},  # merge precisa de 2: fora
        {"action": "explode", "lessons": [], "text": "?"},  # ação desconhecida: fora
    ], seen)
    out = client.post(f"/api/employees/{slug}/curation", headers=env["h"]["mgr"]).json()
    assert out["curation"]["source"] == "modelo" and [i["action"] for i in out["items"]] == ["remove", "new"]
    assert out["items"][1]["tasks"] == [tid]  # tarefa inventada pelo modelo não fica
    assert f"[{old}]" in seen[0] and f"#{tid}" in seen[0]  # o modelo viu as lições (com id) e as tarefas do período
    sugs = {s["action"]: s for s in _curation_sugs(client, env, slug)}
    assert client.post(f"/api/employees/{slug}/suggestions/{sugs['remove']['id']}/apply", headers=env["h"]["mgr"], json={}).status_code == 200
    client.post(f"/api/employees/{slug}/suggestions/{sugs['new']['id']}/apply", headers=env["h"]["mgr"], json={})
    lessons = client.get(f"/api/employees/{slug}", headers=env["h"]["own"]).json()["lessons"]
    assert [x["text"] for x in lessons] == ["Sempre cite o número da fatura.", "Antes de cobrar, confira se o pagamento já caiu."]
    assert lessons[-1]["source"].startswith("curate:")
    # a próxima tarefa já recebe a lição nova no prompt
    tid2 = assign(client, env, slug, "outra cobrança")
    work()
    assert any("confira se o pagamento já caiu" in c[2] for c in rt.calls if c[1] == tid2)


def test_dismissed_proposals_stay_away_and_a_broken_model_falls_back_to_the_rule(client, env, rt, monkeypatch):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    _lesson(client, env, slug, "Revise o valor.")
    _lesson(client, env, slug, "revise o valor")
    monkeypatch.setattr(llm, "target_for_employee", lambda db, e: ("http://llm", "k", "m"))
    monkeypatch.setattr(llm, "CALL", lambda *a, **k: "não é JSON")
    out = client.post(f"/api/employees/{slug}/curation", headers=env["h"]["mgr"]).json()
    assert out["curation"]["source"] == "regra" and out["items"][0]["action"] == "merge"
    sid = _curation_sugs(client, env, slug)[0]["id"]
    assert client.post(f"/api/employees/{slug}/suggestions/{sid}/dismiss", headers=env["h"]["mgr"]).status_code == 200
    assert _curation_sugs(client, env, slug) == []


def _emp(db, slug) -> Employee:
    return db.query(Employee).join(Agent, Agent.id == Employee.agent_id).filter(Agent.slug == slug).one()


def test_runs_once_a_day_overnight_only_for_who_worked(client, env, rt, monkeypatch):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    other = hire(client, env, title="Analista de cobrança")
    make_active(client, env, other, rt)
    assign(client, env, slug, "trabalho do dia")
    work()
    with SessionLocal() as db:
        org = db.get(Organization, 1)
        tz, org.timezone = org.timezone, "UTC"
        for x in (_emp(db, slug), _emp(db, other)):  # a varredura do executor (no work) pode já ter revisado hoje
            x.curation = None
        db.commit()
        curation._last_run.clear()
        try:
            day = datetime.now(UTC).replace(hour=2, minute=0, second=0, microsecond=0)
            assert curation.sweep(db, day) == 0  # antes das 3h
            assert curation.sweep(db, day + timedelta(hours=2)) >= 1
            assert curation.sweep(db, day + timedelta(hours=3)) == 0  # uma vez por dia
            db.expire_all()
            assert _emp(db, slug).curation  # trabalhou: revisado
            assert _emp(db, other).curation is None  # só fez a experiência: nada a revisar
        finally:
            db.get(Organization, 1).timezone = tz
            db.commit()
