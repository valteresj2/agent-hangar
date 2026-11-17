"""Retorno marcado pelo próprio Digital employee (set_followup): a tarefa dorme e acorda na hora para conferir."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.db import SessionLocal
from app.models import EmployeeTask, TaskEvent
from app.services import employee_tasks as tasksmod
from app.services import followups
from app.services.common import PlatformError

from .test_employees import assign, env, hire, make_active, rt, task, work  # noqa: F401


@pytest.fixture(autouse=True)
def _close_leftover_tasks():
    with SessionLocal() as db:
        start = db.query(EmployeeTask.id).order_by(EmployeeTask.id.desc()).limit(1).scalar() or 0
    yield
    with SessionLocal() as db:
        for t in db.query(EmployeeTask).filter(EmployeeTask.id > start, EmployeeTask.status.notin_(tasksmod.TERMINAL)):
            t.status = "cancelled"
        db.commit()


def _pending_at(tid) -> datetime:
    with SessionLocal() as db:
        ev = followups.current(db, db.get(EmployeeTask, tid))
        return tasksmod._aware(datetime.fromisoformat(ev.payload["at"]))


def test_when_is_a_duration_or_an_instant_within_limits():
    at = datetime(2026, 11, 17, 12, tzinfo=UTC)
    assert followups.parse_when({"in": "2h"}, at) == at + timedelta(hours=2)
    assert followups.parse_when({"in": "1,5d"}, at) == at + timedelta(days=1.5)
    assert followups.parse_when({"at": "2026-11-18T09:00:00-03:00"}, at) == datetime(2026, 11, 18, 12, tzinfo=UTC)
    for bad in ({"in": "2 horas"}, {"in": "1m"}, {"in": "31d"}, {"at": "2026-11-18T09:00:00"}, {"at": "amanhã"}, {}):
        with pytest.raises(PlatformError):
            followups.parse_when(bad, at)


def test_task_sleeps_until_the_follow_up_and_wakes_with_what_to_check(client, env, rt):  # noqa: F811
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    args = {"in": "2h", "check": "conferir se o pagamento da fatura 88 caiu no extrato e dar baixa"}
    tid = assign(client, env, slug, f"use set_followup {json.dumps(args)}")
    work()
    t = task(client, env, tid)
    assert t["status"] == "waiting_timer"
    assert t["diagnosis"]["state"] == "timer" and "fatura 88" in t["diagnosis"]["check"]
    due = _pending_at(tid)
    with SessionLocal() as db:
        assert followups.sweep(db, due - timedelta(minutes=1)) == 0  # antes da hora: segue dormindo
    work()
    assert task(client, env, tid)["status"] == "waiting_timer"
    with SessionLocal() as db:
        assert followups.sweep(db, due + timedelta(seconds=1)) == 1
    t = task(client, env, tid)
    assert t["status"] == "new" and any(m["body"].startswith("RETORNO MARCADO") and "fatura 88" in m["body"]
                                        for m in t["messages"])
    work()
    assert task(client, env, tid)["status"] == "done"
    assert "RETORNO MARCADO" in rt.calls[-1][2]  # a rodada que acordou leu o que conferir
    with SessionLocal() as db:
        states = [e.payload["state"] for e in db.query(TaskEvent).filter_by(task_id=tid, kind="followup")]
        assert states == ["done"]


def test_marking_again_replaces_and_a_message_wakes_early(client, env, rt):  # noqa: F811
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    tid = assign(client, env, slug, 'use set_followup {"in": "3d", "check": "primeiro"}')
    work()
    with SessionLocal() as db:
        t = db.get(EmployeeTask, tid)
        ctx = type("C", (), {"db": db, "task": t})()
        followups.set_followup(ctx, {"in": "1d", "check": "segundo"})
        assert followups.info(db, t)["check"] == "segundo"
        assert [e.payload["state"] for e in db.query(TaskEvent).filter_by(task_id=tid, kind="followup")] == ["cancelled", "pending"]
    r = client.post(f"/api/tasks/{tid}/messages", headers=env["h"]["req"], json={"body": "o cliente já pagou, pode conferir agora"})
    assert r.status_code == 200 and r.json()["task_status"] == "new"
    with SessionLocal() as db:
        assert not followups.pending(db, db.get(EmployeeTask, tid))
        assert db.query(TaskEvent).filter_by(task_id=tid, kind="followup").order_by(TaskEvent.id.desc()).first().payload["state"] == "early"


def test_hold_keeps_the_follow_up_and_cancel_clears_it(client, env, rt):  # noqa: F811
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    tid = assign(client, env, slug, 'use set_followup {"in": "2h", "check": "ver o build"}')
    work()
    assert client.post(f"/api/tasks/{tid}/hold", headers=env["h"]["req"], json={"on": True}).json()["status"] == "on_hold"
    with SessionLocal() as db:
        assert followups.sweep(db, _pending_at(tid) + timedelta(minutes=1)) == 0  # pausada: o retorno não acorda
    assert client.post(f"/api/tasks/{tid}/hold", headers=env["h"]["req"], json={"on": False}).json()["status"] == "waiting_timer"
    with SessionLocal() as db:
        t = db.get(EmployeeTask, tid)
        assert followups.cancel_followup(type("C", (), {"db": db, "task": t})(), {}) == "Retorno desmarcado."
        assert followups.sweep(db) == 1  # sem retorno pendente: volta para a fila
        assert db.get(EmployeeTask, tid).status == "new"
