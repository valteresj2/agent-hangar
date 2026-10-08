# ruff: noqa: F811  (env e rt são fixtures importadas de test_employees)
"""Modo sombra (ações que mudam algo são simuladas e revisadas pelo gestor) e plano de carreira (promover, rebaixar e
sair da sombra, sempre por decisão do gestor)."""
from app import services as svc
from app.db import SessionLocal
from app.models import Employee, HumanRequest
from app.services import employee_tasks as tasksmod
from app.services import employee_work as workmod
from app.services import employees as empmod

from .test_employees import assign, env, hire, make_active, open_request, rt, task, work  # noqa: F401


def _emp(db, slug) -> Employee:
    return db.query(Employee).filter(Employee.agent_id == svc.get_agent(db, slug).id).one()


def test_shadow_mode_simulates_changes_and_the_manager_reviews(client, env, rt):
    slug = hire(client, env, shadow=True)
    make_active(client, env, slug, rt)
    d = client.get(f"/api/employees/{slug}", headers=env["h"]["own"]).json()
    assert d["shadow"] is True and d["career"]["shadow"]["on"] is True
    tid = assign(client, env, slug, 'use send_email {"to": "ana@cliente.com", "body": "Olá"}')
    work()
    t = task(client, env, tid)
    assert t["status"] == "done" and t["result"].startswith("simulado: send_email")  # não esperou aprovação
    assert any(e["kind"] == "shadow" for e in t["events"])
    log = client.get(f"/api/employees/{slug}/shadow", headers=env["h"]["mgr"]).json()
    act = log["actions"][0]
    assert act["kind"] == "shadow" and act["action_type"] == "send_external" and act["mode"] == "approve"
    assert act["payload"]["to"] == "ana@cliente.com" and log["stats"]["to_review"] == 1
    assert all(x["kind"] != "shadow" for x in client.get("/api/decisions", headers=env["h"]["mgr"]).json())
    # ler continua de verdade
    tid2 = assign(client, env, slug, 'use crm_lookup {"id": 1}')
    work()
    assert task(client, env, tid2)["result"].startswith("feito: crm_lookup")
    url = f"/api/decisions/{act['id']}"
    assert client.post(url, headers=env["h"]["mgr"], json={"decision": "disagree"}).status_code == 400  # diga por quê
    assert client.post(url, headers=env["h"]["mgr"], json={"decision": "agree"}).json()["decision"] == "agree"
    assert client.get(f"/api/employees/{slug}/shadow", headers=env["h"]["mgr"]).json()["stats"]["agree_rate"] == 100.0


def test_shadow_disagreements_become_a_lesson_and_never_is_still_denied(client, env, rt):
    slug = hire(client, env, shadow=True, authority=[{"action_type": "delete", "mode": "never"}],
                accept_default_authority=False)
    make_active(client, env, slug, rt)
    for i in range(3):
        tid = assign(client, env, slug, f'use send_email {{"to": "c{i}@cliente.com"}}')
        work()
        sid = client.get(f"/api/employees/{slug}/shadow?status=open", headers=env["h"]["mgr"]).json()["actions"][0]["id"]
        client.post(f"/api/decisions/{sid}", headers=env["h"]["mgr"], json={"decision": "disagree", "reason": f"motivo {i}"})
    sug = {s["id"]: s for s in client.get(f"/api/employees/{slug}/suggestions", headers=env["h"]["own"]).json()}
    assert "lesson:send_email" in sug and "motivo 0" in sug["lesson:send_email"]["lesson"]
    tid = assign(client, env, slug, 'use delete_record {"id": 7}')
    work()
    assert task(client, env, tid)["result"].startswith("negado")  # "nunca" vale também no modo sombra


def test_only_the_manager_switches_shadow_and_it_is_logged(client, env, rt):
    slug = hire(client, env)
    assert client.post(f"/api/employees/{slug}/shadow", headers=env["h"]["own"], json={"on": True}).status_code == 403
    r = client.post(f"/api/employees/{slug}/shadow", headers=env["h"]["mgr"], json={"on": True, "reason": "começar com calma"})
    assert r.json()["shadow"] is True
    hist = client.get(f"/api/employees/{slug}/career", headers=env["h"]["own"]).json()["history"]
    assert hist[0]["kind"] == "shadow" and hist[0]["to"] is True and hist[0]["reason"] == "começar com calma"


def test_career_promotes_when_criteria_are_met_only_by_the_manager(client, env, rt, monkeypatch):
    monkeypatch.setitem(workmod.CAREER, "intern", {"next": "junior", "tasks": 2, "approvals": 2, "unedited": 90, "max_fail": 10})
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    c = client.get(f"/api/employees/{slug}/career", headers=env["h"]["own"]).json()
    assert c["level"] == "intern" and c["next"] == "junior" and c["ready"] is False
    for i in range(2):
        tid = assign(client, env, slug, f'use send_email {{"to": "x{i}@cliente.com"}}')
        work()
        client.post(f"/api/decisions/{open_request(client, env, tid)['id']}", headers=env["h"]["mgr"], json={"decision": "approve"})
        work()
    c = client.get(f"/api/employees/{slug}/career", headers=env["h"]["own"]).json()
    assert c["ready"] is True, c["criteria"]
    sug = {s["id"]: s for s in client.get(f"/api/employees/{slug}/suggestions", headers=env["h"]["own"]).json()}
    assert "promote:junior" in sug
    url = f"/api/employees/{slug}/suggestions/promote:junior/apply"
    assert client.post(url, headers=env["h"]["own"], json={}).status_code == 403
    out = client.post(url, headers=env["h"]["mgr"], json={}).json()
    assert out["autonomy_level"] == "junior"
    assert next(a for a in out["authority"] if a["action_type"] == "write_internal")["mode"] == "notify"  # padrão do júnior
    hist = client.get(f"/api/employees/{slug}/career", headers=env["h"]["own"]).json()["history"]
    assert hist[0]["kind"] == "promote" and hist[0]["from"] == "intern" and hist[0]["to"] == "junior"


def test_warning_signs_suggest_a_step_back(client, env, rt):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    client.patch(f"/api/employees/{slug}", headers=env["h"]["mgr"], json={"autonomy_level": "junior"})
    for i in range(3):
        tid = assign(client, env, slug, f'use send_email {{"to": "y{i}@cliente.com"}}')
        work()
        client.post(f"/api/decisions/{open_request(client, env, tid)['id']}", headers=env["h"]["mgr"],
                    json={"decision": "reject", "reason": "não"})
        work()
    c = client.get(f"/api/employees/{slug}/career", headers=env["h"]["own"]).json()
    assert any("recusadas" in s for s in c["demotion_signals"])
    out = client.post(f"/api/employees/{slug}/suggestions/demote:intern/apply", headers=env["h"]["mgr"], json={}).json()
    assert out["autonomy_level"] == "intern"


def test_high_agreement_in_shadow_suggests_going_live(client, env, rt, monkeypatch):
    monkeypatch.setitem(workmod.LEAVE_SHADOW, "reviewed", 2)
    slug = hire(client, env, shadow=True)
    make_active(client, env, slug, rt)
    for i in range(2):
        assign(client, env, slug, f'use send_email {{"to": "z{i}@cliente.com"}}')
        work()
    for a in client.get(f"/api/employees/{slug}/shadow?status=open", headers=env["h"]["mgr"]).json()["actions"]:
        client.post(f"/api/decisions/{a['id']}", headers=env["h"]["mgr"], json={"decision": "agree"})
    sug = {s["id"] for s in client.get(f"/api/employees/{slug}/suggestions", headers=env["h"]["own"]).json()}
    assert "leave_shadow" in sug
    out = client.post(f"/api/employees/{slug}/suggestions/leave_shadow/apply", headers=env["h"]["mgr"], json={}).json()
    assert out["shadow"] is False
    tid = assign(client, env, slug, 'use send_email {"to": "real@cliente.com"}')
    work()
    assert task(client, env, tid)["status"] == "waiting_human"  # agora a alçada vale de verdade
    with SessionLocal() as db:
        e = _emp(db, slug)
        r = empmod.make_report(db, e, "weekly")
        assert "Carreira: intern -> junior" in r.summary
        assert db.query(HumanRequest).filter(HumanRequest.employee_id == e.id, HumanRequest.kind == "shadow").count() == 2
        assert tasksmod.QUIET == ("notice", "shadow")
