"""Agendamentos: cron (fuso, horário de verão, regras clássicas) e o ciclo agendar -> disparar -> histórico."""
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app import config
from app import services as svc
from app.cron import Cron, CronError
from app.db import SessionLocal
from app.models import Schedule, TestRun

from .conftest import ADMIN
from .test_access import _session

SP = "America/Sao_Paulo"


# ------------------------------------------------------------------ cron
def test_cron_next_in_timezone():
    friday_10_sp = datetime(2026, 10, 2, 13, 0, tzinfo=UTC)  # sexta 10:00 em São Paulo (UTC-3)
    nxt = Cron("0 9 * * 1-5").next_after(friday_10_sp, SP)
    assert nxt == datetime(2026, 10, 5, 12, 0, tzinfo=UTC)  # segunda 09:00 SP
    assert Cron("30 8 5 * *").next_after(friday_10_sp, SP) == datetime(2026, 10, 5, 11, 30, tzinfo=UTC)
    assert Cron("@daily").expr == "0 0 * * *"
    assert Cron("0 12 * * sun").next_after(friday_10_sp, "UTC").weekday() == 6
    # dia-do-mês E dia-da-semana restritos: basta um bater (cron clássico)
    c = Cron("0 9 1 * mon")
    hits = []
    t = datetime(2026, 10, 1, tzinfo=UTC)
    for _ in range(5):
        t = c.next_after(t, "UTC")
        hits.append(t.day)
    assert hits == [1, 5, 12, 19, 26]


def test_cron_daylight_saving():
    # Nova York: em 8/3/2026 o relógio pula de 2h para 3h; "9h" continua sendo 9h local (13:00 UTC depois)
    before = Cron("0 9 * * *").next_after(datetime(2026, 3, 7, 12, 0, tzinfo=UTC), "America/New_York")
    after = Cron("0 9 * * *").next_after(before, "America/New_York")
    assert before.hour == 14 and after.hour == 13


@pytest.mark.parametrize("bad", ["", "* * *", "60 * * * *", "0 25 * * *", "0 9 * * 8", "0 9 31 2 *", "a b c d e"])
def test_cron_rejects_invalid(bad):
    with pytest.raises(CronError):
        c = Cron(bad)
        c.next_after(datetime(2026, 1, 1, tzinfo=UTC))


def test_cron_describe_in_portuguese():
    assert Cron("0 9 * * 1-5").describe() == "de segunda a sexta às 09:00"
    assert Cron("0 9 * * 1").describe() == "toda segunda às 09:00"
    assert Cron("30 18 * * *").describe() == "todo dia às 18:30"
    assert Cron("0 8 5 * *").describe() == "todo dia 5 do mês às 08:00"


# ------------------------------------------------------------------ ciclo completo
def _prod_harness_agent(client, uniq, headers=ADMIN):
    slug = client.post("/api/agents", headers=headers, json={"name": uniq("Agendado"), "objective": "o",
                                                              "final_output": "f"}).json()["slug"]
    client.patch(f"/api/agents/{slug}", headers=headers, json={"harness": {"id": "codex"}})
    return slug


def _to_prod(client, slug):
    with SessionLocal() as db:
        a = svc.get_agent(db, slug)
        db.add(TestRun(agent_id=a.id, version=a.current_version, env="stage", status="passed", summary="ok"))
        db.commit()
    assert client.post(f"/api/agents/{slug}/deploy", headers=ADMIN, json={"env": "prod"}).json()["status"] == "running"


def _fire(sid):
    """Avança o relógio até o próximo disparo e roda o que o agendador reservou."""
    with SessionLocal() as db:
        at = db.get(Schedule, sid).next_run_at
    at = at if at.tzinfo else at.replace(tzinfo=UTC)
    claimed = [x for x in svc.schedules.tick(at + timedelta(seconds=1)) if x[0] == sid]
    return [svc.schedules.execute(i, trig) for i, trig in claimed]


def test_schedule_waits_for_production_then_runs(client, uniq):
    slug = _prod_harness_agent(client, uniq)
    r = client.post(f"/api/agents/{slug}/schedules", headers=ADMIN,
                    json={"message": "Gere o resumo da semana", "cron": "0 9 * * 1", "timezone": SP})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["when"] == "toda segunda às 09:00" and s["next_run_local"].endswith("09:00") and not s["agent_in_production"]
    # ainda não está em produção: a execução é pulada, mas o agendamento segue valendo
    run = _fire(s["id"])[0]
    assert run.status == "skipped" and "produção" in run.error
    _to_prod(client, slug)
    run = _fire(s["id"])[0]
    assert run.status == "passed" and run.output and run.version
    runs = client.get(f"/api/schedules/{s['id']}/runs", headers=ADMIN).json()
    assert [x["status"] for x in runs] == ["passed", "skipped"]
    after = client.get(f"/api/agents/{slug}/schedules", headers=ADMIN).json()[0]
    assert after["last_status"] == "passed" and after["next_run_at"] > s["next_run_at"]  # já aponta a próxima semana


def test_one_off_schedule_disables_itself(client, uniq):
    slug = _prod_harness_agent(client, uniq)
    _to_prod(client, slug)
    when = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0).isoformat()
    s = client.post(f"/api/agents/{slug}/schedules", headers=ADMIN, json={"message": "rodar uma vez", "run_at": when}).json()
    assert s["when"].startswith("uma vez em")
    assert _fire(s["id"])[0].status == "passed"
    after = client.get(f"/api/agents/{slug}/schedules", headers=ADMIN).json()[0]
    assert after["enabled"] is False and after["next_run_at"] is None


def test_webhook_receives_result(client, uniq, monkeypatch):
    got = []
    monkeypatch.setattr(config, "SCHEDULE_ALLOW_PRIVATE_WEBHOOKS", True)
    monkeypatch.setattr(svc.schedules, "HTTP", lambda: httpx.Client(transport=httpx.MockTransport(
        lambda req: (got.append(json.loads(req.content)), httpx.Response(200))[1])))
    slug = _prod_harness_agent(client, uniq)
    _to_prod(client, slug)
    s = client.post(f"/api/agents/{slug}/schedules", headers=ADMIN,
                    json={"message": "resumo", "cron": "0 8 * * *", "notify_url": "https://hooks.example.com/x"}).json()
    run = client.post(f"/api/schedules/{s['id']}/run", headers=ADMIN).json()  # "rodar agora"
    assert run["trigger"] == "manual" and run["notify_status"] == "enviado (200)"
    assert got[0]["status"] == "passed" and got[0]["text"].startswith("*") and got[0]["agent"] == slug


def test_schedule_guards(client, uniq):
    slug = _prod_harness_agent(client, uniq)
    post = lambda body: client.post(f"/api/agents/{slug}/schedules", headers=ADMIN, json=body)  # noqa: E731
    assert post({"message": "x", "cron": "* * * * *"}).status_code == 400  # a cada minuto: abaixo do mínimo
    assert post({"message": "x"}).status_code == 400  # sem cron nem run_at
    assert post({"message": "x", "cron": "0 9 * * *", "timezone": "Marte/Base"}).status_code == 400
    assert post({"message": "x", "run_at": "2020-01-01T09:00"}).status_code == 400  # passado
    r = post({"message": "x", "cron": "0 9 * * *", "notify_url": "http://127.0.0.1:8080/interno"})
    assert r.status_code == 400 and "rede interna" in r.json()["detail"]


def test_schedule_permissions(client, uniq):
    team = client.post("/api/teams", headers=ADMIN, json={"name": uniq("Time")}).json()["slug"]
    dev, cons = f"{uniq('dev')}@acme.com", f"{uniq('cons')}@acme.com"
    client.post(f"/api/teams/{team}/members", headers=ADMIN, json={"email": dev, "role": "developer"})
    client.post(f"/api/teams/{team}/members", headers=ADMIN, json={"email": cons, "role": "consumer"})
    slug = _prod_harness_agent(client, uniq, _session(dev))
    body = {"message": "x", "cron": "0 9 * * *"}
    assert client.post(f"/api/agents/{slug}/schedules", headers=_session(cons), json=body).status_code == 403
    sid = client.post(f"/api/agents/{slug}/schedules", headers=_session(dev), json=body).json()["id"]
    assert client.get(f"/api/agents/{slug}/schedules", headers=_session(cons)).json()[0]["id"] == sid  # consumer vê
    assert client.delete(f"/api/schedules/{sid}", headers=_session(cons)).status_code == 403
    assert client.patch(f"/api/schedules/{sid}", headers=_session(dev), json={"enabled": False}).json()["enabled"] is False


def test_org_timezone_is_the_default(client, uniq):
    assert client.patch("/api/org", headers=ADMIN, json={"timezone": "Nope/Nope"}).status_code == 400
    client.patch("/api/org", headers=ADMIN, json={"timezone": SP})
    try:
        slug = _prod_harness_agent(client, uniq)
        s = client.post(f"/api/agents/{slug}/schedules", headers=ADMIN, json={"message": "x", "cron": "0 9 * * *"}).json()
        assert s["timezone"] == SP
    finally:
        client.patch("/api/org", headers=ADMIN, json={"timezone": "UTC"})


def test_schedule_via_mcp(client, uniq):
    slug = _prod_harness_agent(client, uniq)
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "schedule_agent", "arguments": {"slug": slug, "message": "relatório diário",
                                                                "cron": "0 18 * * 1-5", "timezone": SP}}}
    r = client.post("/mcp", json=body, headers={"Accept": "application/json, text/event-stream", **ADMIN}).json()
    res = json.loads(r["result"]["content"][0]["text"])
    assert res["when"] == "de segunda a sexta às 18:00" and res["next_run_local"].endswith("18:00")


def test_deleting_agent_removes_schedules_and_requests(client, uniq):
    slug = _prod_harness_agent(client, uniq)
    _to_prod(client, slug)
    s = client.post(f"/api/agents/{slug}/schedules", headers=ADMIN, json={"message": "x", "cron": "0 9 * * *"}).json()
    client.post(f"/api/schedules/{s['id']}/run", headers=ADMIN)
    assert client.delete(f"/api/agents/{slug}", headers=ADMIN).status_code == 200
    assert all(x["id"] != s["id"] for x in client.get("/api/schedules", headers=ADMIN).json())
