from app import services as svc
from app.models import Job, UsageEvent

from .conftest import ADMIN


def _harness_agent(db, uniq, conn=None):
    a = svc.create_agent(db, uniq("Dev"), "executa tarefas", "diff")
    svc.design_agent(db, a.slug, {"harness": {"id": "claude-code", **({"connection": conn} if conn else {})}})
    return a


def test_job_runs_and_records_cost(db, uniq, fake_docker):
    conn = uniq("anthropic")
    svc.upsert_llm_connection(db, conn, "https://api.anthropic.com", "claude-x", "sk-ant-test", "", "t",
                              "anthropic", 3.0, 15.0)
    a = _harness_agent(db, uniq, conn)
    job = svc.run_harness_job(db, a.slug, "crie um arquivo", "stage", 30, "t", "api")
    assert job.status == "passed" and job.tokens_in == 1000 and job.tokens_out == 500
    assert job.cost_usd == round((1000 * 3 + 500 * 15) / 1e6, 6)
    assert fake_docker.jobs[-1]["image"].endswith("harness-claude-code:latest")
    assert fake_docker.jobs[-1]["env"]["LLM_API_KEY"] == "sk-ant-test"  # decriptada só para o container
    ev = db.query(UsageEvent).filter_by(agent_id=a.id).order_by(UsageEvent.id.desc()).first()
    assert ev.protocol == "harness-job" and ev.cost_usd == job.cost_usd


def test_reported_cost_used_without_catalog_prices(db, uniq, fake_docker):
    conn = uniq("anthropic")
    svc.upsert_llm_connection(db, conn, "https://api.anthropic.com", "claude-x", "sk", "", "t", "anthropic")
    fake_docker.job_result = {**fake_docker.job_result,
                              "usage": {"input_tokens": 10, "output_tokens": 5, "reported_cost_usd": 0.0123}}
    a = _harness_agent(db, uniq, conn)
    job = svc.run_harness_job(db, a.slug, "x", "stage", 30, "t", "api")
    assert job.cost_usd == 0.0123


def test_wrong_protocol_rejected(db, uniq, fake_docker):
    conn = uniq("openai")
    svc.upsert_llm_connection(db, conn, "https://x/v1", "m", "k", "", "t", "openai")
    a = _harness_agent(db, uniq, conn)
    try:
        svc.submit_job(db, a.slug, "x")
        raise AssertionError("deveria falhar")
    except svc.PlatformError as e:
        assert "anthropic" in str(e)


def test_async_job_api_and_callback_token(client, db, uniq, monkeypatch):
    import app.deploy as deploy
    monkeypatch.setattr(deploy, "run_job_container", lambda *a, **k: None)  # ninguém chama o callback
    a = _harness_agent(db, uniq)
    r = client.post(f"/api/agents/{a.slug}/job", headers=ADMIN, json={"task": "x", "wait": False, "timeout_s": 10})
    job_id = r.json()["id"]
    assert r.json()["status"] in ("queued", "running")
    # callback com token errado é recusado
    bad = client.post(f"/internal/jobs/{job_id}/callback", headers={"Authorization": "Bearer nope"},
                      json={"status": "passed"})
    assert bad.status_code == 401
    token = db.get(Job, job_id).token
    ok = client.post(f"/internal/jobs/{job_id}/callback", headers={"Authorization": f"Bearer {token}"},
                     json={"status": "passed", "result": "feito", "usage": {"input_tokens": 3, "output_tokens": 4}})
    assert ok.status_code == 200
    final = svc.wait_job(job_id, 10)
    assert final.status == "passed" and final.result == "feito"


def test_cancel_job(client, db, uniq, monkeypatch):
    import app.deploy as deploy
    monkeypatch.setattr(deploy, "run_job_container", lambda *a, **k: None)
    a = _harness_agent(db, uniq)
    job_id = client.post(f"/api/agents/{a.slug}/job", headers=ADMIN,
                         json={"task": "x", "wait": False, "timeout_s": 30}).json()["id"]
    r = client.post(f"/api/jobs/{job_id}/cancel", headers=ADMIN)
    assert r.json()["status"] == "cancelled"
    assert svc.wait_job(job_id, 10).status == "cancelled"
