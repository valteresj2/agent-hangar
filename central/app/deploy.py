"""Engine de deploy: 1 container Docker isolado por agente/ambiente e 1 efêmero por job de harness.

A central fala com o Docker por um socket proxy (DOCKER_HOST=tcp://docker-proxy:2375) que só libera
criar/parar/remover containers e ler logs — sem exec, build, pull ou acesso ao resto do daemon.
"""
import json
import threading
import time
import uuid

import docker
import httpx

from . import auth, config

_client = None
_lock = threading.Lock()


def client():
    global _client
    with _lock:
        if _client is None:
            _client = docker.from_env()
        return _client


def container_name(slug: str, env: str) -> str:
    return f"agent-{slug}-{env}"


def internal_url(slug: str, env: str) -> str:
    return f"http://{container_name(slug, env)}:8000"


def public_url(slug: str, env: str) -> str:
    prefix = "gw" if env == "prod" else "gw-stage"
    return f"{config.PUBLIC_BASE_URL}/{prefix}/{slug}"


class ImageMissing(RuntimeError):
    pass


def _explain(e: Exception, image: str) -> Exception:
    msg = str(e)
    if isinstance(e, docker.errors.ImageNotFound) or "No such image" in msg or "403" in msg:
        return ImageMissing(
            f"imagem '{image}' não encontrada. Construa com `docker compose --profile harness build` "
            f"(ou `--profile hermes` para o Hermes) ou baixe as imagens publicadas (HANGAR_REGISTRY).")
    return e


def run_agent(slug: str, env: str, resolved_spec: dict, llm_conf: dict):
    """llm_conf: {base_url, api_key, model} já resolvido a partir de uma LlmConnection do catálogo
    (ou vazio/mock). Nenhum LLM roda aqui: é sempre uma chamada HTTP para fora."""
    name = container_name(slug, env)
    c = client()
    try:
        c.containers.get(name).remove(force=True)
    except docker.errors.NotFound:
        pass
    environment = {"AGENT_SPEC": json.dumps(resolved_spec), "AGENT_SLUG": slug, "AGENT_ENV": env,
                   "PUBLIC_URL": public_url(slug, env), "INTERNAL_BASE_URL": config.INTERNAL_BASE_URL,
                   # token só deste agente: ele não consegue se passar por outro ao chamar a central
                   "INTERNAL_TOKEN": auth.agent_token(slug),
                   "INTERNAL_ENV_TOKEN": auth.agent_env_token(slug, env),
                   "LLM_BASE_URL": llm_conf.get("base_url", ""), "LLM_API_KEY": llm_conf.get("api_key", "")}
    try:
        return c.containers.run(
            config.RUNTIME_IMAGE, name=name, detach=True, environment=environment,
            network=config.AGENTS_NETWORK, hostname=name,
            labels={"central.agent": slug, "central.env": env, "central.version": str(resolved_spec["version"])},
            volumes={f"{name}-data": {"bind": "/data", "mode": "rw"}},
            mem_limit=config.AGENT_MEM_LIMIT, nano_cpus=int(config.AGENT_CPUS * 1e9), pids_limit=256,
            read_only=True, tmpfs={"/tmp": "size=64m"}, cap_drop=["ALL"],
            security_opt=["no-new-privileges"], restart_policy={"Name": "unless-stopped"},
        )
    except docker.errors.APIError as e:
        raise _explain(e, config.RUNTIME_IMAGE) from e


def wait_healthy(slug: str, env: str, timeout=60):
    """None se saudável; senão a mensagem de erro (com logs)."""
    deadline = time.time() + timeout
    url = internal_url(slug, env) + "/health"
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return None
        except Exception:
            pass
        time.sleep(1)
    return "Agente não ficou saudável.\n" + logs(slug, env, 30)


def logs(slug: str, env: str, tail=200) -> str:
    try:
        return client().containers.get(container_name(slug, env)).logs(tail=tail).decode(errors="replace")
    except Exception as e:
        return f"(sem logs: {e})"


_states_cache: tuple[float, dict] = (0.0, {})


def states(max_age=3.0) -> dict | None:
    """{nome_do_container: status} de todos os containers de agente, numa única chamada à API do Docker
    (antes era uma chamada por agente a cada listagem da UI). Cache curto para a UI não martelar o daemon.
    None = Docker indisponível agora (quem chama não deve concluir que os agentes caíram)."""
    global _states_cache
    ts, data = _states_cache
    if time.monotonic() - ts < max_age:
        return data
    try:
        found = client().containers.list(all=True, filters={"label": "central.agent"})
    except Exception:
        return None
    data = {c.name: c.status for c in found}
    _states_cache = (time.monotonic(), data)
    return data


def invalidate_states():
    global _states_cache
    _states_cache = (0.0, {})


def state(slug: str, env: str) -> str:
    """running | exited | … | missing (container não existe) | unknown (Docker indisponível)."""
    s = states()
    if s is None:
        return "unknown"
    return s.get(container_name(slug, env), "missing")


def stop_agent(slug: str, env: str):
    try:
        client().containers.get(container_name(slug, env)).remove(force=True)
    except docker.errors.NotFound:
        pass
    invalidate_states()


# ------------------------------------------------------------------ jobs (agentes com harness)
def job_container_name(job_id: int) -> str:
    return f"job-{job_id}-{uuid.uuid4().hex[:6]}"


def run_job_container(name: str, image: str, environment: dict, mem_limit: str, cpus: float,
                      command: list[str] | None = None, labels: dict | None = None):
    """Container efêmero, um por job: sem socket do Docker, sem restart, sem volume persistente, numa
    rede própria (JOBS_NETWORK) — alcança a central (callback) e a internet, não os outros agentes."""
    try:
        return client().containers.run(
            image, command=command, name=name, detach=True, environment=environment, network=config.JOBS_NETWORK,
            hostname=name, labels={"central.job": name, **(labels or {})},
            mem_limit=mem_limit, nano_cpus=int(cpus * 1e9), pids_limit=512,
            cap_drop=["ALL"], security_opt=["no-new-privileges"], restart_policy={"Name": "no"},
        )
    except docker.errors.APIError as e:
        raise _explain(e, image) from e


def job_logs(name: str, tail=200) -> str:
    try:
        return client().containers.get(name).logs(tail=tail).decode(errors="replace")
    except Exception as e:
        return f"(sem logs: {e})"


def remove_job_container(name: str):
    try:
        client().containers.get(name).remove(force=True)
    except docker.errors.NotFound:
        pass
    except Exception:
        pass


def cleanup_job_containers(keep: set[str] | frozenset = frozenset(), min_age_s: float = 0):
    """Remove containers de job que sobraram (ex.: a central reiniciou no meio de um job). Preserva `keep` (jobs
    ativos de outras réplicas) e, com `min_age_s`, as avaliações recentes (que não ficam no banco)."""
    from datetime import UTC, datetime
    try:
        for c in client().containers.list(all=True, filters={"label": "central.job"}):
            if c.name in keep:
                continue
            if min_age_s and "central.eval" in (c.labels or {}):
                created = datetime.fromisoformat(c.attrs.get("Created", "")[:26].rstrip("Z") + "+00:00")
                if (datetime.now(UTC) - created).total_seconds() < min_age_s:
                    continue
            c.remove(force=True)
    except Exception:
        pass


# ---------------------------------------------------------------- backend
# RUNTIME_BACKEND=kubernetes troca a implementação inteira (mesmo contrato): agentes viram Deployment + Service,
# jobs e avaliações viram Jobs do Kubernetes. Ver deploy_k8s.py.
if config.RUNTIME_BACKEND == "kubernetes":
    from . import deploy_k8s as _k8s

    client = _k8s.client
    container_name = _k8s.container_name
    internal_url = _k8s.internal_url
    run_agent = _k8s.run_agent
    wait_healthy = _k8s.wait_healthy
    logs = _k8s.logs
    states = _k8s.states
    invalidate_states = _k8s.invalidate_states
    state = _k8s.state
    stop_agent = _k8s.stop_agent
    run_job_container = _k8s.run_job_container
    job_logs = _k8s.job_logs
    remove_job_container = _k8s.remove_job_container
    cleanup_job_containers = _k8s.cleanup_job_containers
