# ruff: noqa: F811  (env e rt são fixtures importadas de test_employees)
"""Capacidade faltando: o Digital employee pede o que não tem; o gestor anexa um especialista (versão nova, testes e
quatro olhos), pede para construir, recusa ou instrui. Um agente nunca se dá poderes sozinho."""
from app import services as svc
from app.db import SessionLocal
from app.models import AgentLineage, HumanRequest, TaskCheckpoint, TestRun
from app.services import employee_tasks as tasksmod

from .conftest import ADMIN
from .test_employees import assign, env, hire, make_active, rt, task, work  # noqa: F401


def _agent(client, env, name, team=None, prod=True) -> str:
    slug = client.post("/api/agents", headers=ADMIN, json={"name": f"{name} {env['n']}", "objective": "lê contratos assinados",
                                                           "final_output": "resumo", "team": team or env["team"]}).json()["slug"]
    if prod:
        with SessionLocal() as db:
            a = svc.get_agent(db, slug)
            db.add(TestRun(agent_id=a.id, version=a.current_version, env="stage", status="passed", summary="ok", results=[]))
            db.commit()
            svc.promote(db, slug)
    return slug


def _request(client, env, tid, who="mgr"):
    return next(d for d in client.get("/api/decisions", headers=env["h"][who]).json()
                if d["task"] and d["task"]["id"] == tid and d["kind"] == "capability")


def _last_prompt(tid) -> str:
    with SessionLocal() as db:
        cp = db.query(TaskCheckpoint).filter(TaskCheckpoint.task_id == tid).order_by(TaskCheckpoint.seq.desc()).first()
        return cp.messages[-1]["content"]


def test_missing_capability_pauses_and_the_manager_attaches_a_specialist(client, env, rt):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    reader = _agent(client, env, "Contract reader")
    tid = assign(client, env, slug, "need: read the signed contracts in the shared drive")
    work()
    assert task(client, env, tid)["status"] == "waiting_human"
    r = _request(client, env, tid)
    assert r["question"] == "read the signed contracts in the shared drive" and isinstance(r["payload"]["options"], list)
    url = f"/api/decisions/{r['id']}"
    assert client.post(url, headers=env["h"]["out"], json={"decision": "attach", "edit": {"specialist": reader}}).status_code == 403
    assert client.post(url, headers=env["h"]["mgr"], json={"decision": "attach"}).status_code == 400  # qual agente?
    draft = _agent(client, env, "Draft bot", prod=False)
    bad = client.post(url, headers=env["h"]["mgr"], json={"decision": "attach", "edit": {"specialist": draft}})
    assert bad.status_code == 400 and "produção" in bad.json()["detail"]
    out = client.post(url, headers=env["h"]["mgr"], json={"decision": "attach", "edit": {"specialist": reader}}).json()
    assert out["attach"] == "active" and out["status"] == "decided"
    with SessionLocal() as db:
        a = svc.get_agent(db, slug)
        assert reader in svc.spec_of(a)["sub_agents"]
        lineage = db.query(AgentLineage).filter(AgentLineage.agent_id == a.id).one()
        assert reader in [x["slug"] for x in lineage.specialists]  # peça só leitura: nunca publicada por ele
    t = task(client, env, tid)
    assert t["status"] == "new" and f"use ask_{reader}" in _last_prompt(tid)
    work()
    assert task(client, env, tid)["status"] == "done"


def test_attach_waits_for_four_eyes_and_resumes_after_approval(client, env, rt, monkeypatch):
    monkeypatch.setattr(svc.runtime, "promote", lambda db, slug, actor="admin", **k: None)

    def ship(db, slug, actor="admin", _seen=None, promote_prod=True):
        a = svc.get_agent(db, slug)
        db.add(TestRun(agent_id=a.id, version=a.current_version, status="passed", summary="ok"))
        db.commit()
        return []
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    reader = _agent(client, env, "Reader four eyes")
    monkeypatch.setattr(svc.runtime, "ship", ship)
    client.patch(f"/api/teams/{env['team']}", headers=ADMIN, json={"require_approval": True})
    tid = assign(client, env, slug, "need: read contracts")
    work()
    r = _request(client, env, tid)
    out = client.post(f"/api/decisions/{r['id']}", headers=env["h"]["mgr"],
                      json={"decision": "attach", "edit": {"specialist": reader}}).json()
    assert out["attach"] == "approval_pending" and "Aprovações" in out["message"]
    assert task(client, env, tid)["status"] == "waiting_human"  # espera os quatro olhos
    promo = next(x for x in client.get("/api/approvals", headers=env["h"]["mt2"]).json()["to_decide"] if x["kind"] == "promotion")
    assert client.post(f"/api/promotions/{promo['id']}/approve", headers=env["h"]["mt2"], json={}).status_code == 200
    assert task(client, env, tid)["status"] == "new" and "CAPACIDADE" in _last_prompt(tid)


def test_build_keeps_the_request_open_and_reject_resumes_without_it(client, env, rt):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    tid = assign(client, env, slug, "need: run the billing reconciliation")
    work()
    r = _request(client, env, tid)
    b = client.post(f"/api/decisions/{r['id']}", headers=env["h"]["mgr"], json={"decision": "build"}).json()
    assert slug in b["build_prompt"] and "billing reconciliation" in b["build_prompt"] and b["status"] == "open"
    assert task(client, env, tid)["status"] == "waiting_human"
    with SessionLocal() as db:  # construir leva tempo: o prazo da decisão passa a 7 dias
        assert (tasksmod._aware(db.get(HumanRequest, r["id"]).expires_at) - tasksmod.now()).days >= 6
    client.post(f"/api/decisions/{r['id']}", headers=env["h"]["mgr"], json={"decision": "reject", "reason": "não agora"})
    assert "RECUSADO" in _last_prompt(tid)
    work()
    t = task(client, env, tid)
    assert t["status"] == "done" and "não executei" in t["result"]


def test_an_agent_never_attaches_itself_and_capabilities_need_a_task(client, env, rt):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    tid = assign(client, env, slug, "need: more power")
    work()
    r = _request(client, env, tid)
    bad = client.post(f"/api/decisions/{r['id']}", headers=env["h"]["mgr"], json={"decision": "attach", "edit": {"specialist": slug}})
    assert bad.status_code == 400 and "si mesmo" in bad.json()["detail"]
    with SessionLocal() as db:
        g = tasksmod.gate(db, svc.get_agent(db, slug), None, "request_capability", "hangar:request_capability",
                          {"need": "x"}, "", "capability")
        assert g["status"] == "denied"
        assert db.get(HumanRequest, r["id"]).status == "open"
