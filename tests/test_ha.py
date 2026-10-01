"""Várias réplicas da central: callback de job em outra réplica, recuperação só dos próprios órfãos, faxina de jobs de
réplicas que sumiram (heartbeat), avaliações de código e códigos de uso único compartilhados pelo banco."""
from datetime import timedelta

from app import config, shared
from app import services as svc
from app.models import Job, now
from app.services import jobs

from .test_jobs import _harness_agent


class _OtherReplica(dict):
    """O callback chega a outra réplica: o Event em memória desta nunca é acionado (get devolve None)."""

    def get(self, key, default=None):
        return None


def test_job_callback_on_another_replica(db, uniq, fake_docker, monkeypatch):
    monkeypatch.setattr(jobs, "_callback", _OtherReplica())
    monkeypatch.setattr(jobs, "POLL_S", 0.1)
    a = _harness_agent(db, uniq)
    job = svc.run_harness_job(db, a.slug, "x", "stage", 30, "t", "api")
    assert job.status == "passed" and job.duration_ms < 10_000 and job.worker == config.REPLICA_ID


def _stuck(db, agent_id, worker, age_s=0):
    j = Job(agent_id=agent_id, version=1, env="stage", task="t", status="running", token="x", container_name="",
            worker=worker, created_at=now() - timedelta(seconds=age_s))
    db.add(j)
    db.commit()
    return j.id


def test_orphans_and_abandoned_jobs(db, uniq, monkeypatch):
    a = _harness_agent(db, uniq)
    alive, dead, mine = uniq("pod-vivo"), uniq("pod-morto"), config.REPLICA_ID
    shared.put(f"replica:{alive}", {}, 60)
    ids = {"alive": _stuck(db, a.id, alive), "dead": _stuck(db, a.id, dead), "mine": _stuck(db, a.id, mine),
           "dead_recent": _stuck(db, a.id, uniq("pod-morto"), 0)}
    removed = []
    monkeypatch.setattr(svc.jobs.deploy, "cleanup_job_containers", lambda keep=frozenset(), min_age_s=0: removed.append(keep))
    jobs.recover_orphans()
    st = {k: db.get(Job, v) for k, v in ids.items()}
    for j in st.values():
        db.refresh(j)
    assert st["mine"].status == "error" and st["dead"].status == "error"   # reiniciei / réplica sem heartbeat
    assert st["alive"].status == "running"                                 # outra réplica viva: não mexe
    # faxina periódica: réplica que sumiu depois do startup (heartbeat venceu) perde os jobs após a carência
    ghost = uniq("pod-sumiu")
    old = _stuck(db, a.id, ghost, age_s=shared.HEARTBEAT_TTL_S + 30)
    fresh = _stuck(db, a.id, ghost, age_s=0)
    monkeypatch.setattr(svc.jobs.deploy, "remove_job_container", lambda name: None)
    assert jobs.sweep_abandoned() >= 1
    db.expire_all()
    assert db.get(Job, old).status == "error" and "réplica" in db.get(Job, old).result
    assert db.get(Job, fresh).status == "running" and db.get(Job, ids["alive"]).status == "running"
    for j in (ids["alive"], fresh):
        db.get(Job, j).status = "cancelled"
    db.commit()


def test_heartbeat(monkeypatch):
    shared.beat()
    assert shared.replica_alive(config.REPLICA_ID) and not shared.replica_alive("nao-existe") and not shared.replica_alive("")


def test_code_eval_result_from_any_replica():
    """O resultado chega por /internal/eval/<token>/result em qualquer réplica: fica no banco até quem espera ler."""
    seen = {}

    def runner(env):
        token = env["EVAL_URL"].rsplit("/", 1)[-1]
        seen["session"] = svc.code_eval.session(token)
        assert svc.code_eval.complete(token, {"check_exit": 0, "rounds": 1, "check_output": "ok"})
        assert not svc.code_eval.complete(token, {"check_exit": 1})  # só o primeiro resultado vale

    ws = {"files": {"a.py": "x"}, "check": "true"}
    ok, detail = svc.code_eval.run("algum-bot", {"input": "faça", "workspace": ws, "timeout_s": 5}, runner=runner)
    assert seen["session"] == {"slug": "algum-bot"} and ok, detail
