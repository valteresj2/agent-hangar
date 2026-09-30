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
import threading
import time
import uuid

from .. import config, deploy
from .common import PlatformError

_EVALS: dict[str, dict] = {}
_LOCK = threading.Lock()
DEFAULT_TIMEOUT_S = 600


def session(token: str) -> dict | None:
    with _LOCK:
        e = _EVALS.get(token or "")
    return e if e and e["expires"] > time.monotonic() else None


def complete(token: str, result: dict) -> bool:
    e = session(token)
    if not e or e["event"].is_set():
        return False
    e["result"] = result
    e["event"].set()
    return True


def run(slug: str, case: dict, runner=None) -> tuple[bool, str]:
    """Roda um caso com workspace contra o stage do agente. `runner` (testes) substitui o container."""
    ws = case["workspace"]
    timeout = min(int(case.get("timeout_s") or DEFAULT_TIMEOUT_S), config.JOB_MAX_TIMEOUT_S)
    token = secrets.token_urlsafe(24)
    entry = {"slug": slug, "event": threading.Event(), "result": None, "expires": time.monotonic() + timeout + 60}
    with _LOCK:
        _EVALS[token] = entry
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
        got = entry["event"].wait(timeout)
        if not got:
            return False, f"tempo esgotado ({timeout}s) sem resultado do sandbox" + (
                "" if runner else f"\n{deploy.job_logs(name, 20)[-600:]}")
        return verdict(entry["result"] or {}, ws)
    except deploy.ImageMissing as e:
        raise PlatformError(str(e)) from None
    finally:
        with _LOCK:
            _EVALS.pop(token, None)
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
