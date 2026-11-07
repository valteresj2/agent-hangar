"""Digital employee externo: o trabalho roda num agente seu (qualquer linguagem, qualquer máquina) e a plataforma
continua dona da fila, da alçada, das decisões, do orçamento e do histórico.

O worker se autentica com o token do funcionário (ewk_…, mostrado uma vez) e conversa por quatro chamadas:

- POST /hooks/worker/heartbeat — "estou vivo"; devolve a próxima tarefa (já reservada para ele) ou nada.
- POST /hooks/worker/tasks/{id}/gate — antes de uma ação que muda algo fora: a mesma alçada dos agentes da plataforma.
  allowed: execute; waiting: pare (a tarefa volta pelo heartbeat quando alguém decidir — peça a mesma ação de novo e
  ela vem liberada); denied: não execute; simulated: modo sombra, siga como se tivesse feito.
- POST /hooks/worker/tasks/{id}/progress — nota na linha do tempo e custo parcial.
- POST /hooks/worker/tasks/{id}/result — done | failed | waiting, com o texto, o custo e os tokens.
- POST /hooks/worker/tasks/{id}/agui — opcional: o "cérebro" do próprio funcionário por AG-UI (instruções, skills,
  MCPs, memória), com as ferramentas do worker como ferramentas do app. É o que a extensão do VS Code usa.

Uma tarefa reservada que fica sem resultado além do limite de tempo do funcionário volta para a fila (a mesma
varredura das tarefas internas); a plataforma nunca chama o worker — ele é quem pergunta.
"""
import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select, update

from .. import config, tenancy
from ..models import Agent, Employee, EmployeeTask, HumanRequest, now
from . import employee_tasks as tasksmod
from .access import Access, Forbidden
from .common import PlatformError, audit, iso

ONLINE_FOR = timedelta(minutes=2)  # sem heartbeat há mais que isso: o worker aparece como offline


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def info(e: Employee) -> dict:
    seen = e.heartbeat_at
    online = bool(seen and now() - tasksmod._aware(seen) <= ONLINE_FOR)
    return {"runtime": e.runtime or "hangar", "token_hint": e.worker_token_hint or "", "heartbeat_at": iso(seen) if seen else None,
            "online": online, "worker": (e.worker_info or {}),
            "heartbeat_url": f"{config.PUBLIC_BASE_URL}/hooks/worker/heartbeat"}


def set_runtime(db, acc: Access, slug: str, runtime: str, rotate: bool = False) -> dict:
    """hangar (a plataforma roda o agente) | external (um worker seu busca as tarefas). Ligar o externo, ou rotate,
    gera um token novo — que só aparece nesta resposta; o anterior deixa de valer."""
    from .employees import find
    if runtime not in ("hangar", "external"):
        raise PlatformError("runtime: hangar | external")
    e, a = find(db, acc, slug, "manage")
    out = {}
    if runtime == "external" and (rotate or e.runtime != "external" or not e.worker_token_hash):
        token = "ewk_" + secrets.token_urlsafe(32)
        e.worker_token_hash, e.worker_token_hint = _hash(token), token[-4:]
        out["token"] = token
    if runtime == "hangar":
        e.worker_token_hash, e.worker_token_hint = "", ""
        # o que o worker tinha reservado volta para a fila da plataforma
        for t in db.scalars(select(EmployeeTask).where(EmployeeTask.employee_id == e.id, EmployeeTask.status == "in_progress",
                                                       EmployeeTask.worker.like("external%"))):
            t.status, t.worker = "new", ""
    changed = (e.runtime or "hangar") != runtime
    e.runtime = runtime
    db.commit()
    if changed or out:
        audit(db, acc.p.name, "employee.runtime", a.slug, runtime + (f" token …{e.worker_token_hint}" if out else ""))
    return {**info(e), **out}


def _employee(db, token: str) -> tuple[Employee, Agent]:
    if not token or not token.startswith("ewk_"):
        raise Forbidden("token do worker inválido")
    e = db.scalar(tenancy.unscoped(select(Employee).where(Employee.worker_token_hash == _hash(token))))
    if e is None or e.runtime != "external":
        raise Forbidden("token do worker inválido")
    tenancy.set_org(e.org_id or 1)  # o worker age na empresa do funcionário
    return e, db.get(Agent, e.agent_id)


def _task(db, e: Employee, task_id: int) -> EmployeeTask:
    t = db.get(EmployeeTask, task_id)
    if t is None or t.employee_id != e.id:
        raise Forbidden("tarefa de outro Digital employee")
    if t.status != "in_progress" or not (t.worker or "").startswith("external"):
        raise PlatformError(f"a tarefa #{t.id} não está com o worker (status {t.status}): busque a próxima no heartbeat")
    return t


def _claim(db, e: Employee, a: Agent) -> dict | None:
    q = (select(EmployeeTask).where(EmployeeTask.employee_id == e.id, EmployeeTask.status == "new")
         .order_by(EmployeeTask.priority, EmployeeTask.created_at))
    for t in db.scalars(q).all():
        if t.not_before and tasksmod._aware(t.not_before) > now():
            continue
        if e.status == "active" and t.probation:
            continue
        res = db.execute(update(EmployeeTask).where(EmployeeTask.id == t.id, EmployeeTask.status == "new")
                         .values(status="in_progress", worker="external", started_at=now(), updated_at=now()))
        db.commit()
        if res.rowcount != 1:
            continue  # outro heartbeat levou
        db.refresh(t)
        limit = config.EMPLOYEE_MAX_RUNS + (t.extra_runs or 0)
        if t.runs >= limit:
            tasksmod._finish(db, t, "failed", error=f"limite de {limit} rodadas atingido")
            continue
        if t.cost_usd > e.task_budget_usd:
            tasksmod._finish(db, t, "failed", error=f"orçamento da tarefa (US$ {e.task_budget_usd}) estourado")
            continue
        from . import budgets
        stop = budgets.stopped(db, a, t.project_id)
        if stop:
            t.status, t.worker = "waiting_budget", ""
            tasksmod.event(db, t, "budget", stop)
            db.commit()
            continue
        lang = tasksmod.lang_of(e)
        cp = tasksmod.last_checkpoint(db, t)
        messages = list(cp.messages if cp else [{"role": "user", "content": tasksmod.task_prompt(t, lang)}])
        from . import task_thread
        delivered = task_thread.deliver(db, t, messages, lang)
        if len(delivered) != len(messages) or cp is None:
            messages = delivered
            tasksmod.checkpoint(db, t, messages)
        t.runs += 1
        tasksmod.event(db, t, "run", {"run": t.runs, "env": "external"})
        db.commit()
        decided = [{"id": r.id, "kind": r.kind, "status": r.status, "decision": (r.decision or ""), "tool": r.tool_name}
                   for r in db.scalars(select(HumanRequest).where(HumanRequest.task_id == t.id,
                                                                  HumanRequest.status != "open")
                                       .order_by(HumanRequest.id))]
        return {"id": t.id, "title": t.title, "body": t.body or "", "priority": t.priority, "run": t.runs,
                "due_at": iso(t.due_at) if t.due_at else None, "probation": bool(t.probation),
                "budget_usd": e.task_budget_usd, "cost_usd": t.cost_usd, "time_limit_min": e.task_time_limit_min,
                "messages": messages, "decisions": decided, "language": lang,
                "url": f"{config.PUBLIC_BASE_URL}/app/#/tasks/{t.id}"}
    return None


def heartbeat(db, token: str, worker: dict | None = None, want_task: bool = True) -> dict:
    e, a = _employee(db, token)
    e.heartbeat_at = now()
    if worker:
        e.worker_info = {k: str(v)[:120] for k, v in list(worker.items())[:10]}
    db.commit()
    working = e.status in ("probation", "active")
    task = _claim(db, e, a) if want_task and working else None
    return {"employee": a.slug, "name": a.name, "status": e.status, "shadow": bool(e.shadow), "task": task,
            "next_heartbeat_s": 5 if task is None and working else 30}


def gate(db, token: str, task_id: int, tool: str, args: dict, rationale: str = "", kind: str = "tool",
         screenshot: str = "") -> dict:
    """desktop:<ação>: o computador da pessoa (o app Agent Hangar Desktop como posto) — as regras do desktop
    governado, com a captura que o posto manda (services/desktop_local.py)."""
    e, a = _employee(db, token)
    t = _task(db, e, task_id)
    if kind not in ("tool", "ask_human", "capability"):
        raise PlatformError("kind: tool | ask_human | capability")
    if kind == "tool" and not (tool or "").strip():
        raise PlatformError("diga a ação (tool), ex.: crm.update_deal")
    if kind == "tool" and tool.startswith("desktop:"):
        from . import desktop_local
        out = desktop_local.gate(db, e, a, t, tool.split(":", 1)[1], args or {}, rationale, screenshot)
    else:
        ref = tool if ":" in (tool or "") else f"external:{tool}"
        out = tasksmod.gate(db, a, t.id, tool, ref, args or {}, rationale, kind)
    if out.get("status") == "waiting":  # a tarefa sai do worker até alguém decidir; volta pelo heartbeat
        db.refresh(t)
        t.worker = ""
        db.commit()
    return out


def progress(db, token: str, task_id: int, note: str = "", cost_usd: float = 0, tokens: int = 0,
             tool: dict | None = None, job: dict | None = None, desktop: dict | None = None) -> dict:
    """Notícia do posto: uma nota, o custo, a ferramenta que acabou de rodar (um passo na linha do tempo), o progresso
    de um trabalho longo (um evento `job` por trabalho, atualizado no lugar, com o tempo que falta) e, no computador da
    pessoa, a janela depois de uma ação (desktop: {event, after})."""
    e, a = _employee(db, token)
    t = _task(db, e, task_id)
    _spend(t, cost_usd, tokens)
    if desktop:
        from . import desktop_local
        desktop_local.after(db, t, desktop)
    if note:
        tasksmod.event(db, t, "note", {"worker": note[:1000]})
    if tool and str(tool.get("name") or "").strip():
        tasksmod.event(db, t, "tool", {"tool": str(tool["name"])[:80], "summary": str(tool.get("summary") or "")[:300],
                                       "ok": bool(tool.get("ok", True)), "ms": max(0, int(tool.get("ms") or 0)),
                                       "worker": True})
    if job and str(job.get("id") or "").strip():
        _job(db, t, job)
    t.started_at = now()  # quem dá notícia não está preso: o prazo da rodada recomeça
    db.commit()
    return {"id": t.id, "status": t.status, "cost_usd": t.cost_usd, "stop": t.cost_usd > e.task_budget_usd}


JOB_STATES = ("running", "done", "failed")


def _job(db, t: EmployeeTask, job: dict) -> None:
    """O progresso de um trabalho longo: o evento `job` desse trabalho é atualizado no lugar (a linha do tempo não
    enche de porcentagens) e quem acompanha a tarefa recebe task.updated a cada atualização."""
    from ..models import TaskEvent

    def num(v):
        try:
            return max(0.0, float(v)) if v is not None else None
        except (TypeError, ValueError):
            return None
    jid = str(job["id"]).strip()[:60]
    total = num(job.get("total"))
    eta = num(job.get("eta_s"))
    payload = {"id": jid, "label": str(job.get("label") or "")[:120], "done": num(job.get("done")) or 0.0,
               "total": total or None, "unit": str(job.get("unit") or "")[:20],
               "eta_s": int(eta) if eta is not None else None,
               "state": job.get("state") if job.get("state") in JOB_STATES else "running", "at": iso(now())}
    recent = db.scalars(select(TaskEvent).where(TaskEvent.task_id == t.id, TaskEvent.kind == "job")
                        .order_by(TaskEvent.id.desc()).limit(50))
    ev = next((x for x in recent if (x.payload or {}).get("id") == jid), None)
    if ev is None:
        tasksmod.event(db, t, "job", {**payload, "started": payload["at"]})
        return
    ev.payload = {**payload, "started": (ev.payload or {}).get("started") or payload["at"]}
    t.updated_at = now()


def agui_round(db, token: str, task_id: int, body: dict) -> dict:
    """Uma rodada AG-UI do worker com o cérebro do próprio funcionário: o worker manda a conversa e as ferramentas
    dele (ex.: o VS Code com arquivos e terminal) e o runtime do agente responde com as instruções, skills, MCPs e
    memória do cargo. As ferramentas da plataforma passam pela alçada da tarefa (X-Hangar-Task), como numa rodada
    interna; as do worker ele executa depois de perguntar no /gate. Devolve para onde mandar e o corpo já com DLP."""
    e, a = _employee(db, token)
    t = _task(db, e, task_id)
    if t.cost_usd > e.task_budget_usd:
        raise PlatformError(f"orçamento da tarefa (US$ {e.task_budget_usd}) estourado")
    from . import governance
    from .catalog import code_allowed
    from .common import spec_of
    why = governance.llm_blocked(db, t, a)
    if why:
        raise PlatformError(why)
    env = "stage" if (t.probation or e.status == "probation") else "prod"
    if body.get("tools"):
        ok, msg = code_allowed(db, spec_of(a), env)
        if not ok:  # o worker mandaria arquivos e saídas de terminal para esse LLM
            raise PlatformError(msg)
    body = {**body, "messages": governance.mask_messages(db, t, [m for m in body.get("messages") or [] if isinstance(m, dict)])}
    t.started_at = now()  # a rodada está viva: o prazo recomeça
    db.commit()
    return {"slug": a.slug, "agent_id": a.id, "env": env, "task_id": t.id, "body": body}


def agui_done(db, task_id: int, agent_id: int, env: str, usage: dict | None, ok: bool, latency_ms: int) -> dict:
    """Depois da rodada: tokens e custo na tarefa e nas métricas do agente; se uma ferramenta da plataforma parou na
    alçada, a tarefa sai do worker até alguém decidir (volta pelo heartbeat, como no /gate)."""
    from .usage import record_usage
    t = db.get(EmployeeTask, task_id)
    record_usage(db, agent_id, env, "employee", "agui", latency_ms, ok, {"usage": usage} if usage else None)
    if usage:
        _spend(t, usage.get("cost_usd"), usage.get("total_tokens"))
    waiting = db.scalar(select(HumanRequest.id).where(HumanRequest.task_id == t.id, HumanRequest.status == "open",
                                                      HumanRequest.kind.in_(tasksmod.BLOCKING)))
    if waiting and t.status == "in_progress":
        t.status, t.worker = "waiting_human", ""
    db.commit()
    return {"id": t.id, "status": t.status, "cost_usd": t.cost_usd, "request": waiting}


def _nudge(db, t: EmployeeTask, text: str) -> bool:
    """A "entrega" que só anuncia uma ação ("vou tentar a página da Receita") volta para a fila com o lembrete na
    conversa, no máximo MAX_NUDGES vezes por tarefa (o mesmo da rodada interna)."""
    from sqlalchemy import func

    from ..models import TaskEvent
    nudges = db.scalar(select(func.count()).select_from(TaskEvent).where(TaskEvent.task_id == t.id,
                                                                        TaskEvent.kind == "nudge")) or 0
    if nudges >= tasksmod.MAX_NUDGES or not tasksmod.announced_only(text, True):
        return False
    cp = tasksmod.last_checkpoint(db, t)
    tasksmod.checkpoint(db, t, [*(cp.messages if cp else []), {"role": "user", "content": (
        "Você anunciou o próximo passo mas encerrou sem executá-lo. Continue agora: chame a ferramenta necessária "
        "ou, se o trabalho já terminou, responda com o resultado final completo.")}])
    tasksmod.event(db, t, "nudge", {"why": "anunciou o próximo passo sem executar", "said": text[-200:]})
    t.status = "new"
    db.commit()
    return True


def _spend(t: EmployeeTask, cost_usd, tokens):
    t.cost_usd = round(t.cost_usd + max(0.0, float(cost_usd or 0)), 6)
    t.tokens += max(0, int(tokens or 0))


def result(db, token: str, task_id: int, status: str, text: str = "", error: str = "", cost_usd: float = 0,
           tokens: int = 0, findings: bool | None = None, summary: str = "") -> dict:
    e, a = _employee(db, token)
    t = _task(db, e, task_id)
    if status not in ("done", "failed", "waiting"):
        raise PlatformError("status: done | failed | waiting")
    if findings is not None and status == "done":  # laço: "sem achados" ou achado, com a mesma checagem da plataforma
        from . import task_findings
        d = task_findings.declare(db, t, findings, summary, tasksmod.lang_of(e))
        if d["status"] != "allowed":
            raise PlatformError(d["message"])
    _spend(t, cost_usd, tokens)
    from . import task_thread
    if text:
        cp = tasksmod.last_checkpoint(db, t)
        tasksmod.checkpoint(db, t, [*(cp.messages if cp else []), {"role": "assistant", "content": text[:20000]}])
        task_thread.agent_said(db, t, text)
    t.worker = ""
    if status == "failed":
        tasksmod._finish(db, t, "failed", error=(error or text or "o worker informou falha")[:2000])
    elif status == "waiting":
        open_req = db.scalar(select(HumanRequest.id).where(HumanRequest.task_id == t.id, HumanRequest.status == "open",
                                                           HumanRequest.kind.in_(tasksmod.BLOCKING)))
        t.status = "waiting_human" if open_req else "new"
        db.commit()
    elif task_thread.pending(db, t):  # chegou mensagem na conversa: mais uma rodada antes de concluir
        t.status = "new"
        tasksmod.event(db, t, "note", {"continue": "mensagem nova na conversa"})
        db.commit()
    elif status == "done" and _nudge(db, t, text):  # anunciou o próximo passo e parou: mais uma rodada, como nas internas
        pass
    else:
        from . import task_flow
        if task_flow.needs_review(t, e):
            task_flow.send_to_review(db, t, e, text)
        else:
            tasksmod._finish(db, t, "done", result=text)
    audit(db, f"worker:{a.slug}", "employee.task.result", a.slug, f"#{t.id} {status}")
    return {"id": t.id, "status": t.status}
