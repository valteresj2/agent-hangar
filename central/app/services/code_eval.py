"""Avaliação de código em stage (casos de teste com `workspace`).

Cada caso vira um container efêmero da imagem harness-base (o mesmo isolamento dos jobs: sem socket do Docker,
limites de memória/CPU/PIDs, rede de jobs) rodando harness/eval_runner.js, que faz o papel do editor:
1. monta o mini-projeto do caso;
2. conversa com a versão em STAGE do agente pelo proxy interno `/internal/eval/<token>/…`, oferecendo ferramentas de
   arquivo e terminal (as mesmas de um cliente de código como o VS Code), e as executa DENTRO do sandbox;
3. roda o `check` e devolve o resultado em `/internal/eval/<token>/result`.
O caso passa só se o `check` sair com 0 e nenhum arquivo `protected` (ex.: os testes) tiver mudado. O token é de uso
único por avaliação e só vale para o proxy do agente avaliado, em stage.
"""
import json
import secrets
import time
import uuid

from .. import config, deploy, shared
from .common import PlatformError

DEFAULT_TIMEOUT_S = 600
POLL_S = 0.5
# sessão e resultado ficam no banco (tabela ephemeral): o sandbox chama /internal/eval/<token>/… e, com várias
# réplicas, cada chamada pode cair numa réplica diferente da que espera o resultado


def session(token: str) -> dict | None:
    return shared.get(f"eval:{token}") if token else None


def complete(token: str, result: dict) -> bool:
    e = session(token)
    if not e or not shared.take_once(f"eval-done:{token}", config.JOB_MAX_TIMEOUT_S + 120):
        return False
    shared.put(f"eval-result:{token}", {"result": result}, config.JOB_MAX_TIMEOUT_S + 120)
    return True


def _wait_result(token: str, timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = shared.get(f"eval-result:{token}")
        if r is not None:
            return r.get("result") or {}
        time.sleep(POLL_S)
    return None


def run(slug: str, case: dict, runner=None) -> tuple[bool, str]:
    """Roda um caso com workspace contra o stage do agente. `runner` (testes) substitui o container."""
    ws = case["workspace"]
    timeout = min(int(case.get("timeout_s") or DEFAULT_TIMEOUT_S), config.JOB_MAX_TIMEOUT_S)
    token = secrets.token_urlsafe(24)
    shared.put(f"eval:{token}", {"slug": slug}, timeout + 60)
    name = f"eval-{slug[:40]}-{uuid.uuid4().hex[:6]}"
    env = {"EVAL_URL": f"{config.INTERNAL_BASE_URL}/internal/eval/{token}", "EVAL_TASK": case["input"],
           "EVAL_FILES": json.dumps(ws["files"]), "EVAL_CHECK": ws["check"],
           "EVAL_PROTECTED": json.dumps(ws.get("protected") or []), "EVAL_MAX_ROUNDS": str(ws.get("max_rounds") or 30)}
    try:
        if runner:
            runner(env)
        else:
            deploy.run_job_container(name, config.harness_image("base"), env, config.JOB_MEM_LIMIT, config.JOB_CPUS,
                                     command=["node", "/srv/eval_runner.js"], labels={"central.eval": slug})
        result = _wait_result(token, timeout)
        if result is None:
            return False, f"tempo esgotado ({timeout}s) sem resultado do sandbox" + (
                "" if runner else f"\n{deploy.job_logs(name, 20)[-600:]}")
        return verdict(result, ws)
    except deploy.ImageMissing as e:
        raise PlatformError(str(e)) from None
    finally:
        for k in (f"eval:{token}", f"eval-result:{token}"):
            shared.pop(k)
        if not runner:
            deploy.remove_job_container(name)


def verdict(r: dict, ws: dict) -> tuple[bool, str]:
    tools = r.get("tool_calls") or []
    head = f"{r.get('rounds', 0)} rodada(s), {len(tools)} ferramenta(s)"
    if tools:
        head += ": " + ", ".join(tools[:12]) + ("…" if len(tools) > 12 else "")
    changed = r.get("changed_files") or []
    head += f" | alterou: {', '.join(changed[:8]) or 'nada'}"
    if r.get("error") and r.get("check_exit") is None:
        return False, f"{head} | erro no sandbox: {r['error']}"
    if r.get("protected_changed"):
        return False, f"{head} | alterou arquivo protegido: {', '.join(r['protected_changed'])} (não vale mudar os testes)"
    ok = r.get("check_exit") == 0
    tail = (r.get("check_output") or "").strip().splitlines()[-3:]
    detail = f"{head} | `{ws['check']}` → exit {r.get('check_exit')}" + (f": {' / '.join(tail)}" if tail else "")
    if r.get("error"):
        detail += f" | aviso: {r['error']}"
    return ok, detail
