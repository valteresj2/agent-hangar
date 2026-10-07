# ruff: noqa: F811  (env e rt são fixtures importadas de test_employees)
"""Digital employee delegando trabalho de código a um agente com harness: o funcionário continua um agente de chat
(gate antes de cada ferramenta) e cada job de código passa pela alçada como run_code."""
from pathlib import Path

import pytest

from app import auth
from app import services as svc
from app.db import SessionLocal
from app.models import ActionCatalog, Employee, TestRun, now
from app.services import employee_gate as gatemod
from app.services import employee_tasks as tasksmod

from .conftest import ADMIN
from .test_employees import assign, env, hire, make_active, rt, task, work  # noqa: F401


def _coder(client, env, name="Code bot") -> str:
    slug = client.post("/api/agents", headers=ADMIN, json={"name": f"{name} {env['n']}", "objective": "muda código",
                                                           "final_output": "diff", "team": env["team"]}).json()["slug"]
    client.patch(f"/api/agents/{slug}", headers=ADMIN, json={"harness": {"id": "claude-code"}})
    with SessionLocal() as db:  # só agentes em produção entram como peça: testes aprovados + promote (Docker falso)
        a = svc.get_agent(db, slug)
        db.add(TestRun(agent_id=a.id, version=a.current_version, env="stage", status="passed", summary="ok", results=[]))
        db.commit()
        svc.promote(db, slug)
    return slug


def test_employee_itself_cannot_be_a_harness_but_can_delegate_code(client, env, rt):
    with SessionLocal() as db:  # pela API o campo nem existe; o serviço também recusa
        acc = svc.access.Access(db, auth.Principal("admin-token", {"admin"}))
        with pytest.raises(svc.PlatformError, match="specialists"):
            svc.employees.hire(db, acc, **_job(env), harness={"id": "claude-code"})
    coder = _coder(client, env)
    slug = hire(client, env, specialists=[coder])
    with SessionLocal() as db:
        spec = svc.resolve_spec(db, svc.get_agent(db, slug), "prod")
        sub = next(s for s in spec["sub_agents_resolved"] if s["slug"] == coder)
        assert sub["harness"] is True and sub["timeout_s"] > 180  # um job de código leva mais que uma conversa
        assert "harness" not in spec  # o funcionário continua um agente de chat
    make_active(client, env, slug, rt)
    tid = assign(client, env, slug, "corrija o bug do login")
    with SessionLocal() as db:
        agent = svc.get_agent(db, slug)
        g = tasksmod.gate(db, agent, tid, f"ask_{coder}", f"agent:{coder}", {"message": "corrija o login em auth.py"},
                          "o bug está no auth.py")
        assert g["status"] == "waiting"  # estagiário + piso da empresa: job de código pede aprovação
        assert db.scalar(gatemod.select(ActionCatalog).where(ActionCatalog.tool_ref == f"agent:{coder}")).action_type == "run_code"
    r = next(d for d in client.get("/api/decisions", headers=env["h"]["mgr"]).json() if d["task"] and d["task"]["id"] == tid)
    assert r["action_type"] == "run_code" and r["payload"]["message"].startswith("corrija o login")
    assert r["rationale"] == "o bug está no auth.py"
    client.post(f"/api/decisions/{r['id']}", headers=env["h"]["mgr"], json={"decision": "approve"})
    with SessionLocal() as db:
        again = tasksmod.gate(db, svc.get_agent(db, slug), tid, f"ask_{coder}", f"agent:{coder}",
                              {"message": "corrija o login em auth.py"})
        assert again["status"] == "allowed"  # a aprovação vale uma vez, para aquele job exato


def test_run_code_is_on_the_company_floor_and_reclassifies_old_rows(client, env):
    floor = {f["action_type"]: f for f in client.get("/api/admin/authority-floor", headers=ADMIN).json()}
    assert floor["run_code"]["min_mode"] == "approve"
    coder = _coder(client, env, "Was chat")
    with SessionLocal() as db:
        db.add(ActionCatalog(tool_ref=f"agent:{coder}", action_type="delegate", risk=2, classified_by="auto:rule",
                             updated_at=now()))
        db.commit()
        assert gatemod.classify(db, f"agent:{coder}").action_type == "run_code"
        e = Employee(id=0, autonomy_level="senior")
        assert gatemod.AUTONOMY_DEFAULTS["senior"]["run_code"] == "notify"
        assert gatemod.evaluate(db, e, "run_code", {})["mode"] == "approve"  # o piso vale por cima do sênior


def _job(env):
    from .test_employees import _fields
    return _fields(env)


def test_harness_job_and_diff_come_back_in_the_tool_result():
    # o runtime roda no container do agente; aqui conferimos o contrato no código dele
    src = (Path(__file__).parent.parent / "runtime" / "app.py").read_text(encoding="utf-8")
    assert 'meta.get("job_id")' in src and "[job #" in src and 'sub.get("timeout_s", 180)' in src


def test_code_job_from_the_reply_lands_in_the_timeline(client, env, rt, monkeypatch):
    slug = hire(client, env)
    make_active(client, env, slug, rt)
    real = rt._act

    def act(s, tid, last):  # o agente devolve o resultado do harness (como o _a2a_call do runtime)
        return real(s, tid, last) + "\n\n[job #4242 · diff de 3 linha(s)]\n+fix"
    monkeypatch.setattr(rt, "_act", act)
    tid = assign(client, env, slug, "corrija")
    work()
    t = task(client, env, tid)
    assert [e["payload"] for e in t["events"] if e["kind"] == "job"] == [{"job": 4242}]
