# ruff: noqa: F811  (env, rt e channels são fixtures importadas)
"""Ritmo das mensagens: fora do expediente, teto por hora e baixa prioridade esperam e saem num resumo só; urgente
sai na hora."""
from datetime import timedelta

import pytest

from app.db import SessionLocal
from app.models import Employee, EmployeeTask, HumanRequest, PacedMessage, now
from app.services import pacing

from .test_employees import assign, env, hire, make_active, open_request, rt, task, work  # noqa: F401
from .test_employees_notify import _slack_on, channels  # noqa: F401


@pytest.fixture(autouse=True)
def _clean():
    yield
    with SessionLocal() as db:
        db.query(PacedMessage).delete()
        db.commit()


def _pace(client, env, slug, **p):
    r = client.put(f"/api/employees/{slug}/pacing", headers=env["h"]["mgr"], json=p)
    assert r.status_code == 200, r.text
    return r.json()


def _ask(client, env, slug, n=1, priority=2):
    r = client.post(f"/api/employees/{slug}/tasks", headers=env["h"]["req"], json={
        "title": f"envio {n}", "body": f'use send_email {{"to": "c{n}@cliente.com", "body": "Olá"}}', "priority": priority})
    assert r.status_code == 200, r.text
    work()
    return open_request(client, env, r.json()["id"])


def _posted(slack, rid) -> bool:
    """O pedido chegou à pessoa: a mensagem dele ou o resumo do ritmo (o resumo diário da empresa é outra coisa)."""
    return any(f"#{rid}" in m["text"] or f"#{rid}" in str(m.get("blocks")) for m in slack.of("chat.postMessage")
               if not m["text"].startswith("Agent Hangar —"))


def test_settings_are_validated_and_only_who_manages_changes_them(client, env, rt):
    slug = hire(client, env)
    assert client.get(f"/api/employees/{slug}/pacing", headers=env["h"]["own"]).json()["pacing"] == pacing.DEFAULT
    assert _pace(client, env, slug, quiet="business", max_per_hour=4, low="digest")["pacing"] == {
        "quiet": "business", "max_per_hour": 4, "low": "digest"}
    for bad in ({"quiet": "night"}, {"max_per_hour": 61}, {"low": "later"}):
        assert client.put(f"/api/employees/{slug}/pacing", headers=env["h"]["mgr"], json=bad).status_code == 400
    assert client.put(f"/api/employees/{slug}/pacing", headers=env["h"]["req"], json={"quiet": "off"}).status_code in (403, 404)
    assert client.get(f"/api/employees/{slug}", headers=env["h"]["own"]).json()["pacing"]["max_per_hour"] == 4


def test_outside_business_hours_waits_and_goes_out_in_one_summary(client, env, rt, channels, monkeypatch):
    slack = channels
    _slack_on(client)
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    _pace(client, env, slug, quiet="business")
    monkeypatch.setattr(pacing, "in_quiet", lambda db, at=None: True)
    r1, r2, r3 = (_ask(client, env, slug, n) for n in (1, 2, 3))
    assert not any(_posted(slack, r["id"]) for r in (r1, r2, r3))  # fora do expediente: ninguém é chamado
    assert client.get(f"/api/employees/{slug}/pacing", headers=env["h"]["own"]).json()["held"] == 3
    # um deles é decidido no portal no meio-tempo: não entra no resumo
    assert client.post(f"/api/decisions/{r3['id']}", headers=env["h"]["mgr"], json={"decision": "reject"}).status_code == 200
    with SessionLocal() as db:
        assert pacing.sweep(db) == 0  # ainda fora do expediente
    monkeypatch.setattr(pacing, "in_quiet", lambda db, at=None: False)
    before = len(slack.of("chat.postMessage"))
    with SessionLocal() as db:
        assert pacing.sweep(db) == 1
    msgs = slack.of("chat.postMessage")[before:]
    assert len(msgs) == 1 and "esperaram" in msgs[0]["text"] and "fora do expediente" in msgs[0]["text"]
    body = str(msgs[0]["blocks"])
    assert f"#{r1['id']}" in body and f"#{r2['id']}" in body and f"#{r3['id']}" not in body
    with SessionLocal() as db:
        assert pacing.sweep(db) == 0  # já saiu
        assert {m.status for m in db.query(PacedMessage).filter(PacedMessage.reason == "quiet")} == {"released", "dropped"}


def test_hourly_cap_and_urgent_goes_out_anyway(client, env, rt, channels, monkeypatch):
    slack = channels
    _slack_on(client)
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    _pace(client, env, slug, max_per_hour=1)
    with SessionLocal() as db:  # o pedido de admissão também foi uma mensagem dele para a gestora
        db.query(PacedMessage).delete()
        db.commit()
    first, second = _ask(client, env, slug, 1), _ask(client, env, slug, 2)
    assert _posted(slack, first["id"]) and not _posted(slack, second["id"])
    urgent = _ask(client, env, slug, 3, priority=1)  # prioridade alta: não espera o teto
    assert _posted(slack, urgent["id"])
    with SessionLocal() as db:
        assert pacing.sweep(db) == 0  # a hora ainda não virou
        assert pacing.sweep(db, now() + timedelta(minutes=61)) == 1
    assert _posted(slack, second["id"])


def test_expiring_request_is_urgent_even_outside_business_hours(client, env, rt):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    tid = assign(client, env, slug, 'use send_email {"to": "x@cliente.com", "body": "Olá"}')
    work()
    rid = open_request(client, env, tid)["id"]
    _pace(client, env, slug, quiet="business")
    with SessionLocal() as db:
        r = db.get(HumanRequest, rid)
        e = db.get(Employee, r.employee_id)
        assert pacing.request_priority(db, r, "expiring") == "urgent"
        assert pacing.request_priority(db, r, "new") == "normal"
        db.get(EmployeeTask, tid).priority = 3
        db.commit()
        assert pacing.request_priority(db, r, "new") == "low"
        assert pacing.allow(db, e, r.assigned_user_id, "request", r.id, "urgent") is True


def test_low_priority_waits_for_the_digest_hour(client, env, rt, channels, monkeypatch):
    slack = channels
    _slack_on(client)
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    _pace(client, env, slug, low="digest")
    monkeypatch.setattr(pacing, "_digest_moment", lambda db, at: now() - timedelta(hours=2))
    low = _ask(client, env, slug, 1, priority=3)
    normal = _ask(client, env, slug, 2)
    assert not _posted(slack, low["id"]) and _posted(slack, normal["id"])
    monkeypatch.setattr(pacing, "_digest_moment", lambda db, at: now() - timedelta(hours=2))  # o de hoje já passou
    with SessionLocal() as db:
        assert pacing.sweep(db) == 0  # chegou depois do resumo de hoje: espera o de amanhã
    monkeypatch.setattr(pacing, "_digest_moment", lambda db, at: now() + timedelta(seconds=1))
    with SessionLocal() as db:
        assert pacing.sweep(db) == 1
    assert _posted(slack, low["id"])
