"""Jobs de agentes-com-harness: assíncronos, 1 container efêmero por job.

Fluxo: submit_job grava o job (queued) e o entrega a um pool de workers -> o worker sobe o container ->
o container chama /internal/jobs/<id>/callback -> complete_job acorda o worker por um Event em memória
(sem polling do banco) -> o worker finaliza, registra uso/custo e remove o container.

Estado dos eventos fica no processo da central (1 worker uvicorn). Para várias réplicas, trocar por uma
fila externa (Redis) — está no roadmap.
"""
import json
import logging
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session

from .. import config, deploy
from ..db import SessionLocal
from ..models import Job, now
from .catalog import cost_usd, resolve_harness
from .common import PlatformError, audit, get_agent, iso
from .runtime import resolve_spec
from .usage import record_usage

log = logging.getLogger("hangar.jobs")

TERMINAL = ("passed", "failed", "timeout", "error", "cancelled")
_pool = ThreadPoolExecutor(max_workers=config.JOB_WORKERS, thread_name_prefix="job")
_callback: dict[int, threading.Event] = {}   # container respondeu
_done: dict[int, threading.Event] = {}       # job finalizado (qualquer estado terminal)
_meta: dict[int, dict] = {}                   # dados que não vão para o banco (preços, canal)


def job_dict(j: Job) -> dict:
    return {"id": j.id, "version": j.version, "env": j.env, "harness_id": j.harness_id,
            "connection": j.connection, "task": j.task, "status": j.status, "result": j.result,
            "diff": j.diff, "logs": j.logs, "duration_ms": j.duration_ms, "tokens_in": j.tokens_in,
            "tokens_out": j.tokens_out, "cost_usd": j.cost_usd,
            "created_at": iso(j.created_at), "finished_at": iso(j.finished_at)}


def submit_job(db: Session, slug: str, task: str, env="stage", timeout_s=None, actor="admin",
               channel="api") -> Job:
    """Valida, grava como `queued` e devolve na hora. A execução roda num worker."""
    if not task or not task.strip():
        raise PlatformError("task vazia")
    a = get_agent(db, slug)
    spec = resolve_spec(db, a, env)
    hconf = resolve_harness(db, spec, env)
    timeout_s = min(max(int(timeout_s or config.JOB_TIMEOUT_S), 10), config.JOB_MAX_TIMEOUT_S)
    skills_txt = "\n\n".join(f"## {s['name']}\n{s['content']}" for s in spec.get("skills_resolved", []))
    system_prompt = "\n\n".join(x for x in (spec.get("instructions", ""), skills_txt) if x)
    mcp_servers = {m["name"]: {"type": "http", "url": m["url"]} for m in spec.get("mcps", [])}

    job = Job(agent_id=a.id, version=a.current_version, env=env, harness_id=hconf["harness_id"],
              connection=hconf["connection"], task=task, status="queued", token=secrets.token_hex(24),
              result="", diff="", logs="", container_name="", duration_ms=0)
    db.add(job)
    db.commit()
    job.container_name = deploy.job_container_name(job.id)
    db.commit()
    image = config.harness_image("base" if hconf["mock"] else hconf["harness_id"])
    environment = {
        "HARNESS_ID": hconf["harness_id"],  # sem LLM_API_KEY o entrypoint roda em modo mock
        "TASK": task, "SYSTEM_PROMPT": system_prompt, "MCP_CONFIG_JSON": json.dumps(mcp_servers),
        # nomes genéricos; o entrypoint mapeia para a env var de cada harness (ANTHROPIC_API_KEY, …)
        "LLM_BASE_URL": hconf["base_url"], "LLM_API_KEY": hconf["api_key"], "LLM_MODEL": hconf["model"],
        "JOB_CALLBACK_URL": f"{config.INTERNAL_BASE_URL}/internal/jobs/{job.id}/callback",
        "JOB_TOKEN": job.token,
    }
    _callback[job.id], _done[job.id] = threading.Event(), threading.Event()
    _meta[job.id] = {"prices": hconf["prices"], "channel": channel}
    audit(db, actor, "job.submit", slug, f"#{job.id} v{a.current_version} {task[:120]}")
    _pool.submit(_execute, job.id, image, environment, timeout_s, actor)
    return job


def _execute(job_id: int, image: str, environment: dict, timeout_s: int, actor: str):
    t0 = time.time()
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job.status == "cancelled":
            return _finish(db, job, t0, actor)
        job.status = "running"
        db.commit()
        try:
            deploy.run_job_container(job.container_name, image, environment, config.JOB_MEM_LIMIT, config.JOB_CPUS)
        except Exception as e:
            job.status, job.result = "error", f"Falha ao iniciar o container do job: {e}"
            return _finish(db, job, t0, actor)
        got = _callback[job_id].wait(timeout_s)
        db.expire_all()
        job = db.get(Job, job_id)
        if not got and job.status == "running":
            job.status, job.result = "timeout", f"Job excedeu o limite de {timeout_s}s."
        return _finish(db, job, t0, actor)


def _finish(db: Session, job: Job, t0: float, actor: str):
    meta = _meta.pop(job.id, {})
    job.duration_ms = int((time.time() - t0) * 1000)
    prices = meta.get("prices") or (None, None)
    # preço do catálogo tem prioridade; sem ele, vale a estimativa que o próprio harness reportou
    job.cost_usd = (cost_usd(job.tokens_in, job.tokens_out, prices) if any(prices)
                    else round(float(meta.get("reported_cost") or 0), 6))
    if not job.logs and job.container_name:
        job.logs = deploy.job_logs(job.container_name, 200)
    job.finished_at = job.finished_at or now()
    db.commit()
    if job.container_name:
        deploy.remove_job_container(job.container_name)
    record_usage(db, job.agent_id, job.env, meta.get("channel", "api"), "harness-job", job.duration_ms,
                 job.status == "passed", tokens_in=job.tokens_in, tokens_out=job.tokens_out, cost=job.cost_usd)
    audit(db, actor, "job.finish", str(job.agent_id), f"#{job.id} [{job.status}] {job.duration_ms}ms")
    ev = _done.pop(job.id, None)
    _callback.pop(job.id, None)
    if ev:
        ev.set()


def complete_job(db: Session, job: Job, status: str, result: str, diff: str, logs: str, usage: dict | None):
    """Chamado pelo callback do container (já autenticado pelo token do job)."""
    if job.status not in ("running", "queued"):
        return
    usage = usage or {}
    job.status, job.result, job.diff, job.logs = status, result[:20000], diff[:50000], logs[:20000]
    job.tokens_in = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    job.tokens_out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    if job.id in _meta and isinstance(usage.get("reported_cost_usd"), (int, float)):
        _meta[job.id]["reported_cost"] = usage["reported_cost_usd"]
    job.finished_at = now()
    db.commit()
    ev = _callback.get(job.id)
    if ev:
        ev.set()


def cancel_job(db: Session, job_id: int, actor="admin") -> Job:
    job = db.get(Job, job_id)
    if not job:
        raise PlatformError(f"job {job_id} não encontrado")
    if job.status in TERMINAL:
        return job
    job.status, job.result, job.finished_at = "cancelled", "Cancelado.", now()
    db.commit()
    if job.container_name:
        deploy.remove_job_container(job.container_name)
    ev = _callback.get(job.id)
    if ev:
        ev.set()
    audit(db, actor, "job.cancel", str(job.agent_id), f"#{job.id}")
    return job


def wait_job(job_id: int, timeout_s: float) -> Job:
    ev = _done.get(job_id)
    if ev:
        ev.wait(timeout_s)
    with SessionLocal() as db:
        return db.get(Job, job_id)


def run_harness_job(db: Session, slug: str, task: str, env="stage", timeout_s=None, actor="admin",
                    channel="api") -> Job:
    """Versão síncrona (MCP, testes, gateway): submete e espera terminar."""
    job = submit_job(db, slug, task, env, timeout_s, actor, channel)
    limit = min(max(int(timeout_s or config.JOB_TIMEOUT_S), 10), config.JOB_MAX_TIMEOUT_S) + 30
    return wait_job(job.id, limit)


def recover_orphans():
    """No startup: jobs que estavam em fila/rodando quando a central caiu não têm mais worker esperando por
    eles — marca como erro e remove containers de job que sobraram."""
    from sqlalchemy import select

    with SessionLocal() as db:
        orphans = db.scalars(select(Job).where(Job.status.in_(("queued", "running")))).all()
        for j in orphans:
            j.status, j.result, j.finished_at = "error", "Interrompido: a central reiniciou durante o job.", now()
        if orphans:
            db.commit()
            log.warning("%d job(s) órfão(s) marcados como erro", len(orphans))
    deploy.cleanup_job_containers()


def job_events(job_id: int, poll=1.0):
    """Gerador de eventos para SSE: status, novas linhas de log do container enquanto roda, e o resultado."""
    sent_status, sent_logs = None, ""
    while True:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if not job:
                yield {"event": "error", "data": {"message": "job não encontrado"}}
                return
            if job.status != sent_status:
                sent_status = job.status
                yield {"event": "status", "data": {"status": job.status}}
            if job.status == "running" and job.container_name:
                current = deploy.job_logs(job.container_name, 400)
                if current.startswith("(sem logs"):
                    current = sent_logs
                if current != sent_logs:
                    new = current[len(sent_logs):] if current.startswith(sent_logs) else current
                    sent_logs = current
                    if new.strip():
                        yield {"event": "log", "data": {"text": new}}
            if job.status in TERMINAL and job_id not in _done:
                yield {"event": "done", "data": job_dict(job)}
                return
        time.sleep(poll)
