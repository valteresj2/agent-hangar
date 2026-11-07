"""Computadores compartilhados: a máquina de uma pessoa (o app Agent Hangar Desktop) que os Digital employees pegam
emprestada quando precisam de um passo de tela (plano: docs/platform/computer-shared-workstations-plan.md no repositório
do Desktop).

- A pessoa liga o computador pelo app (`POST /api/app/workstations`, token `wst_…` uma vez), escolhe os apps, quem pode
  usar (os funcionários que ela gerencia e/ou os de times escolhidos) e como autoriza (`ask`: pergunta a cada
  empréstimo — o padrão; `preauthorized`: só o aviso na tela).
- O funcionário continua rodando na plataforma: `computer_list` mostra as máquinas que ele pode usar e `computer_use`
  pede o empréstimo para a tarefa (com `ask`, a dona decide — no app, em Decisões ou no portal). Com o empréstimo ativo,
  os `desktop_*` de sempre vão para essa máquina: a alçada e as regras de confirmação são as mesmas
  (services/desktop.py), só o "executor" muda (`desktop.call` → `route`).
- Um empréstimo por vez por máquina; os outros esperam na fila (um pedido do sistema segura a tarefa e é liberado quando a
  máquina fica livre). O empréstimo termina com `computer_release`, no fim da tarefa, depois de IDLE_END_MIN sem passos
  ou quando a pessoa clica Parar no computador.
- A máquina pergunta à plataforma (long-poll de saída, `/hooks/workstation/*`): os pedidos de empréstimo a responder e
  o próximo passo. Os argumentos de um passo vão cifrados (podem ter o valor de um segredo) e o passo é apagado assim
  que o resultado volta.
"""
import hashlib
import json
import secrets
import time
from datetime import timedelta

from sqlalchemy import select

from .. import config, tenancy
from ..crypto import decrypt, encrypt
from ..db import SessionLocal
from ..models import (
    Agent,
    Employee,
    EmployeeTask,
    HumanRequest,
    User,
    Workstation,
    WorkstationLease,
    WorkstationStep,
    now,
)
from . import employee_tasks as tasksmod
from .common import PlatformError, audit, iso
from .decision_kinds import close, handler

ONLINE_FOR = timedelta(minutes=2)
IDLE_END_MIN = 30  # sem passos por esse tempo, o empréstimo termina (a tarefa pede de novo se precisar)
STEP_TIMEOUT_S = 90
POLL_S = 0.3
COMMANDS = ("open", "look", "click", "type_text", "key", "scroll")
AUTH_MODES = ("ask", "preauthorized")


class Unauthorized(Exception):
    pass


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _aware(dt):
    return tasksmod._aware(dt) if dt else None


def online(ws: Workstation) -> bool:
    return ws.status == "on" and bool(ws.heartbeat_at) and now() - _aware(ws.heartbeat_at) <= ONLINE_FOR


def _apps(raw) -> list[dict]:
    out, seen = [], set()
    for a in raw or []:
        if not isinstance(a, dict):
            continue
        name, proc = str(a.get("name") or "").strip()[:80], str(a.get("process") or "").strip()[:80]
        if name and proc and proc.lower() not in seen:
            seen.add(proc.lower())
            out.append({"name": name, "process": proc})
    return out[:50]


def ws_dict(db, ws: Workstation, mine: bool = False) -> dict:
    active = _active(db, ws.id)
    out = {"id": ws.id, "name": ws.name, "os": ws.os, "apps": ws.apps or [], "online": online(ws), "status": ws.status,
           "busy": active is not None, "heartbeat_at": iso(ws.heartbeat_at) if ws.heartbeat_at else None}
    if mine:
        out.update({"allow_managed": ws.allow_managed, "allow_team_ids": ws.allow_team_ids or [],
                    "auth_mode": ws.auth_mode, "token_hint": ws.token_hint})
    return out


# ------------------------------------------------------------------ a pessoa liga e configura (token do app)
def _user(db, p) -> User:
    u = db.get(User, p.user_id) if getattr(p, "user_id", None) else None
    if u is None or not u.active:
        raise PlatformError("só uma pessoa (não uma chave de serviço) liga o próprio computador")
    return u


def _settings(ws: Workstation, body: dict, u: User, db):
    if "name" in body:
        ws.name = str(body.get("name") or "").strip()[:120] or ws.name
    if "os" in body:
        ws.os = str(body.get("os") or "")[:40]
    if "apps" in body:
        ws.apps = _apps(body.get("apps"))
    if "allow_managed" in body:
        ws.allow_managed = bool(body.get("allow_managed"))
    if "allow_team_ids" in body:
        from ..models import TeamMember
        mine = set(db.scalars(select(TeamMember.team_id).where(TeamMember.user_id == u.id)))
        asked = {int(x) for x in body.get("allow_team_ids") or [] if str(x).isdigit()}
        if asked - mine:
            raise PlatformError("você só pode liberar o computador para times dos quais faz parte")
        ws.allow_team_ids = sorted(asked)
    if "auth_mode" in body:
        if body["auth_mode"] not in AUTH_MODES:
            raise PlatformError("auth_mode: ask | preauthorized")
        if body["auth_mode"] == "preauthorized" and not config.WORKSTATION_PREAUTHORIZED:
            raise PlatformError("a empresa exige perguntar a cada empréstimo (WORKSTATION_PREAUTHORIZED=0)")
        ws.auth_mode = body["auth_mode"]


def register(db, p, body: dict) -> dict:
    u = _user(db, p)
    ws = Workstation(owner_user_id=u.id, name=str(body.get("name") or "Computador")[:120], apps=[], allow_team_ids=[],
                     org_id=u.org_id or 1)
    _settings(ws, body, u, db)
    if not ws.apps:
        raise PlatformError("libere pelo menos um app")
    token = "wst_" + secrets.token_urlsafe(32)
    ws.token_hash, ws.token_hint = _hash(token), token[-4:]
    db.add(ws)
    db.commit()
    audit(db, u.email, "workstation.on", ws.name, f"#{ws.id} apps: {', '.join(a['name'] for a in ws.apps)}")
    return {**ws_dict(db, ws, mine=True), "token": token}


def _own(db, p, ws_id: int) -> tuple[Workstation, User]:
    u = _user(db, p)
    ws = db.get(Workstation, ws_id)
    if ws is None or ws.owner_user_id != u.id:
        raise PlatformError("computador não encontrado")
    return ws, u


def mine(db, p) -> list[dict]:
    u = _user(db, p)
    return [ws_dict(db, ws, mine=True) for ws in db.scalars(select(Workstation).where(
        Workstation.owner_user_id == u.id, Workstation.status == "on").order_by(Workstation.id))]


def update(db, p, ws_id: int, body: dict) -> dict:
    ws, u = _own(db, p, ws_id)
    _settings(ws, body, u, db)
    db.commit()
    audit(db, u.email, "workstation.update", ws.name, json.dumps({k: body[k] for k in body if k != "name"}, default=str)[:300])
    return ws_dict(db, ws, mine=True)


def remove(db, p, ws_id: int) -> dict:
    ws, u = _own(db, p, ws_id)
    for lease in db.scalars(select(WorkstationLease).where(WorkstationLease.workstation_id == ws.id,
                                                           WorkstationLease.status.in_(("requested", "queued", "active")))):
        end(db, lease, "o computador foi desligado pela dona")
    ws.status, ws.token_hash = "off", ""
    db.commit()
    audit(db, u.email, "workstation.off", ws.name, f"#{ws.id}")
    return {"id": ws.id, "status": "off"}


# ------------------------------------------------------------------ quem pode usar
def can_use(db, ws: Workstation, e: Employee) -> bool:
    if ws.status != "on":
        return False
    if ws.allow_managed and ws.owner_user_id in (e.manager_user_id, e.owner_user_id):
        return True
    a = db.get(Agent, e.agent_id)
    return bool(a and a.team_id and a.team_id in (ws.allow_team_ids or []))


def usable(db, e: Employee) -> list[Workstation]:
    return [ws for ws in db.scalars(select(Workstation).where(Workstation.status == "on").order_by(Workstation.id))
            if can_use(db, ws, e)]


def any_usable(db, e: Employee) -> bool:
    return bool(usable(db, e))


def _active(db, ws_id: int) -> WorkstationLease | None:
    return db.scalar(select(WorkstationLease).where(WorkstationLease.workstation_id == ws_id,
                                                    WorkstationLease.status == "active"))


def lease_of_task(db, task_id: int) -> WorkstationLease | None:
    return db.scalar(select(WorkstationLease).where(WorkstationLease.task_id == task_id,
                                                    WorkstationLease.status == "active"))


def _owner_name(db, ws: Workstation) -> str:
    u = db.get(User, ws.owner_user_id)
    return (u.name or u.email) if u else "a dona"


def _find(db, e: Employee, ref) -> Workstation:
    ref = str(ref or "").strip()
    pool = usable(db, e)
    ws = next((w for w in pool if str(w.id) == ref or w.name.lower() == ref.lower()), None)
    ws = ws or next((w for w in pool if ref and ref.lower() in w.name.lower()), None)
    if ws is None:
        names = ", ".join(w.name for w in pool) or "nenhum"
        raise PlatformError(f"computador '{ref}' não encontrado entre os que você pode usar ({names}): veja computer_list")
    return ws


# ------------------------------------------------------------------ empréstimo
def _hold(db, ctx, lease: WorkstationLease, kind: str, question: str, assigned: int | None) -> dict:
    r = HumanRequest(employee_id=ctx.e.id, task_id=ctx.task.id, kind=kind, action_type="read", mode="approve",
                     question=question[:2000], rationale=(lease.reason or ctx.rationale or "")[:4000],
                     action_payload={"workstation_id": lease.workstation_id, "lease_id": lease.id, "app": lease.app},
                     assigned_user_id=assigned, approvals=[], created_at=now(),
                     expires_at=now() + timedelta(minutes=config.DECISION_EXPIRES_MIN))
    db.add(r)
    db.flush()
    lease.request_id = r.id
    ctx.task.status = "waiting_human"
    tasksmod.event(db, ctx.task, "human_request", {"id": r.id, "kind": kind, "question": question[:300]})
    db.commit()
    if kind == "workstation":
        tasksmod._notify_request(db, ctx.e, r)
    return {"status": "waiting", "request_id": r.id, "message": question}


def _activate(db, lease: WorkstationLease, ws: Workstation):
    lease.status, lease.started_at, lease.last_step_at = "active", now(), now()
    task = db.get(EmployeeTask, lease.task_id)
    if task:
        tasksmod.event(db, task, "lease", {"action": "granted", "workstation": ws.name, "lease": lease.id, "app": lease.app})


def _ready_text(ws: Workstation) -> str:
    apps = ", ".join(a["name"] for a in ws.apps or [])
    return (f"Computador '{ws.name}' emprestado para esta tarefa (apps: {apps}). Os desktop_* agora agem nessa máquina: "
            "comece com desktop_open(app) e confira a tela depois de cada ação. A pessoa vê um aviso e pode parar a "
            "qualquer momento. Quando terminar a parte de tela, chame computer_release.")


def request(ctx, ref, app: str, reason: str) -> dict | str:
    db, e, task = ctx.db, ctx.e, ctx.task
    sweep(db)
    current = lease_of_task(db, task.id)
    if current is not None:
        ws = db.get(Workstation, current.workstation_id)
        if str(ref or "").strip() in ("", str(ws.id)) or ws.name.lower() == str(ref).strip().lower():
            return _ready_text(ws)
        raise PlatformError(f"esta tarefa já está com o computador '{ws.name}': libere com computer_release antes")
    ws = _find(db, e, ref)
    if not online(ws):
        raise PlatformError(f"o computador '{ws.name}' está desligado ou sem o app aberto agora")
    app = str(app or "").strip()
    if app and not any(app.lower() in (a["name"].lower(), a["process"].lower()) for a in ws.apps or []):
        raise PlatformError(f"'{app}' não está entre os apps liberados em '{ws.name}': "
                            + ", ".join(a["name"] for a in ws.apps or []))
    pending = db.scalar(select(WorkstationLease).where(WorkstationLease.task_id == task.id,
                                                       WorkstationLease.workstation_id == ws.id,
                                                       WorkstationLease.status.in_(("requested", "queued"))))
    if pending is not None:  # voltou de uma decisão que ainda segura (não deveria): segue esperando
        return {"status": "waiting", "request_id": pending.request_id, "message": "o empréstimo ainda está pendente"}
    lease = WorkstationLease(workstation_id=ws.id, employee_id=e.id, task_id=task.id, app=app[:120],
                             reason=str(reason or "")[:2000], org_id=ws.org_id)
    db.add(lease)
    db.flush()
    a = db.get(Agent, e.agent_id)
    who = a.name if a else "um funcionário"
    tasksmod.event(db, task, "lease", {"action": "requested", "workstation": ws.name, "lease": lease.id, "app": lease.app})
    if ws.auth_mode == "ask":
        q = (f"{who} quer usar o computador '{ws.name}' para a tarefa #{task.id} ({task.title})"
             + (f", no app {lease.app}" if lease.app else "") + (f". Motivo: {lease.reason}" if lease.reason else "")
             + ". Permitir?")
        return _hold(db, ctx, lease, "workstation", q, ws.owner_user_id)
    return _grant(db, ctx, lease, ws)


def _grant(db, ctx, lease: WorkstationLease, ws: Workstation) -> dict | str:
    """Autorizado: em uso agora se a máquina está livre; senão, na fila (um pedido do sistema segura a tarefa)."""
    busy = _active(db, ws.id)
    if busy is None or busy.id == lease.id:
        _activate(db, lease, ws)
        db.commit()
        return _ready_text(ws)
    lease.status = "queued"
    ahead = db.scalar(select(WorkstationLease.id).where(WorkstationLease.workstation_id == ws.id,
                                                        WorkstationLease.status == "queued",
                                                        WorkstationLease.id < lease.id).limit(1))
    return _hold(db, ctx, lease, "workstation_queue",
                 f"O computador '{ws.name}' está em uso por outra tarefa (#{busy.task_id}); esta tarefa entrou na fila"
                 + (" (há outras antes dela)" if ahead else "") + " e continua sozinha quando ele ficar livre.", None)


def release(ctx) -> str:
    lease = lease_of_task(ctx.db, ctx.task.id)
    if lease is None:
        return "Esta tarefa não está com nenhum computador emprestado."
    ws = ctx.db.get(Workstation, lease.workstation_id)
    end(ctx.db, lease, "liberado pelo funcionário")
    return f"Computador '{ws.name}' devolvido."


def end(db, lease: WorkstationLease, why: str):
    if lease.status in ("ended", "denied"):
        return
    was_active = lease.status == "active"
    lease.status, lease.ended_at, lease.ended_reason = "ended", now(), why[:200]
    for s in db.scalars(select(WorkstationStep).where(WorkstationStep.lease_id == lease.id)):
        db.delete(s)
    if lease.request_id:  # um pedido ainda aberto deste empréstimo não vale mais
        r = db.get(HumanRequest, lease.request_id)
        if r is not None and r.status == "open":
            r.status, r.decided_by, r.decided_at = "cancelled", "sistema", now()
    task = db.get(EmployeeTask, lease.task_id)
    ws = db.get(Workstation, lease.workstation_id)
    if task:
        tasksmod.event(db, task, "lease", {"action": "ended", "workstation": ws.name if ws else "", "lease": lease.id,
                                           "why": why[:200]})
    db.commit()
    if was_active and ws is not None:
        _promote(db, ws)


def _promote(db, ws: Workstation):
    """A máquina ficou livre: o primeiro da fila passa a usar e a tarefa dele continua."""
    if _active(db, ws.id) is not None:
        return
    nxt = db.scalar(select(WorkstationLease).where(WorkstationLease.workstation_id == ws.id,
                                                   WorkstationLease.status == "queued")
                    .order_by(WorkstationLease.id).limit(1))
    if nxt is None:
        return
    _activate(db, nxt, ws)
    task = db.get(EmployeeTask, nxt.task_id)
    r = db.get(HumanRequest, nxt.request_id) if nxt.request_id else None
    if r is not None and r.status == "open":
        close(r, "approve", "", "sistema")
    if task:
        tasksmod._resume(db, task, f"FILA: {_ready_text(ws)}")
    db.commit()


def sweep(db):
    """Fecha o que ficou para trás: empréstimo sem passos há IDLE_END_MIN, de tarefa que terminou, ou cujo pedido
    expirou."""
    limit = now() - timedelta(minutes=IDLE_END_MIN)
    for lease in list(db.scalars(select(WorkstationLease).where(WorkstationLease.status.in_(("requested", "queued", "active"))))):
        task = db.get(EmployeeTask, lease.task_id)
        if task is None or task.status in ("done", "failed", "cancelled", "expired", "review"):
            end(db, lease, "a tarefa terminou")
        elif lease.status == "active" and _aware(lease.last_step_at or lease.started_at) < limit:
            end(db, lease, f"{IDLE_END_MIN} min sem passos de tela")
        elif lease.status == "requested" and lease.request_id:
            r = db.get(HumanRequest, lease.request_id)
            if r is not None and r.status in ("expired", "cancelled"):
                lease.status, lease.ended_at, lease.ended_reason = "denied", now(), "o pedido expirou"
                db.commit()


def on_task_end(db, task: EmployeeTask):
    for lease in list(db.scalars(select(WorkstationLease).where(WorkstationLease.task_id == task.id,
                                                                WorkstationLease.status.in_(("requested", "queued", "active"))))):
        end(db, lease, "a tarefa terminou")


def _decide_lease(db, r: HumanRequest, task, allow: bool, reason: str, who: str):
    lease = db.get(WorkstationLease, (r.action_payload or {}).get("lease_id"))
    ws = db.get(Workstation, lease.workstation_id) if lease else None
    if lease is None or ws is None or lease.status != "requested":
        close(r, "reject", "o empréstimo não está mais pendente", who)
        db.commit()
        return
    if not allow:
        close(r, "reject", reason, who)
        lease.status, lease.ended_at, lease.ended_reason = "denied", now(), (reason or "recusado")[:200]
        if task:
            tasksmod.event(db, task, "decision", {"id": r.id, "decision": "reject", "by": who})
            tasksmod.event(db, task, "lease", {"action": "denied", "workstation": ws.name, "lease": lease.id})
            tasksmod._resume(db, task, f"DECISÃO #{r.id}: {who} NÃO emprestou o computador '{ws.name}'"
                                       + (f" — {reason}" if reason else "")
                                       + ". Siga sem ele, se der, ou encerre a tarefa explicando o que ficou pendente.")
        db.commit()
        return
    close(r, "approve", reason, who)
    if task:
        tasksmod.event(db, task, "decision", {"id": r.id, "decision": "approve", "by": who})
    busy = _active(db, ws.id)
    if busy is None:
        _activate(db, lease, ws)
        if task:
            tasksmod._resume(db, task, f"DECISÃO #{r.id}: {who} emprestou. {_ready_text(ws)}")
        db.commit()
        return
    # autorizado, mas a máquina está em uso: entra na fila (o pedido do sistema segura a tarefa)
    lease.status = "queued"
    q = HumanRequest(employee_id=r.employee_id, task_id=r.task_id, kind="workstation_queue", action_type="read",
                     mode="approve", question=f"O computador '{ws.name}' está em uso (tarefa #{busy.task_id}); esta "
                     "tarefa espera na fila e continua sozinha quando ele ficar livre.",
                     action_payload={"workstation_id": ws.id, "lease_id": lease.id, "app": lease.app},
                     approvals=[], created_at=now())
    db.add(q)
    db.flush()
    lease.request_id = q.id
    if task:
        tasksmod._resume(db, task, f"DECISÃO #{r.id}: {who} emprestou o computador '{ws.name}', mas ele está em uso; "
                                   "a tarefa espera na fila.")
    db.commit()


@handler("workstation")
def decide_workstation(db, acc, r: HumanRequest, e: Employee, task, decision: str, edit: dict, reason: str, who: str):
    if decision not in ("approve", "reject"):
        raise PlatformError("empréstimo do computador: decision = approve | reject")
    ws = db.get(Workstation, (r.action_payload or {}).get("workstation_id"))
    if ws is not None and acc.p.user_id != ws.owner_user_id and not acc.p.is_admin:
        raise PlatformError("só a dona do computador decide se empresta")
    _decide_lease(db, r, task, decision == "approve", reason, who)
    audit(db, who, f"workstation.lease.{decision}", ws.name if ws else "", f"#{r.id}")
    return tasksmod.request_dict(db, r, e)


@handler("workstation_queue")
def decide_queue(db, acc, r: HumanRequest, e: Employee, task, decision: str, edit: dict, reason: str, who: str):
    if decision != "reject":
        raise PlatformError("a fila anda sozinha quando o computador fica livre (reject = desistir da fila)")
    lease = db.get(WorkstationLease, (r.action_payload or {}).get("lease_id"))
    close(r, "reject", reason, who)
    if lease is not None and lease.status == "queued":
        lease.status, lease.ended_at, lease.ended_reason = "ended", now(), f"saiu da fila: {who}"
    if task:
        tasksmod._resume(db, task, f"FILA: {who} tirou esta tarefa da fila do computador"
                                   + (f" — {reason}" if reason else "") + ". Siga sem ele ou encerre explicando.")
    db.commit()
    return tasksmod.request_dict(db, r, e)


# ------------------------------------------------------------------ os passos de tela (chamado por desktop.call)
def route(task_id: int, command: str, args: dict, secret: bool = False) -> dict | None:
    """O passo vai para o computador emprestado desta tarefa (None: não há empréstimo; use o desktop da plataforma)."""
    with SessionLocal() as db:
        lease = lease_of_task(db, task_id)
        if lease is None:
            last = db.scalar(select(WorkstationLease).where(WorkstationLease.task_id == task_id)
                             .order_by(WorkstationLease.id.desc()).limit(1))
            if last is not None:  # a tarefa usava um computador: nunca cair, calada, no desktop da plataforma
                why = last.ended_reason or {"requested": "o empréstimo ainda não foi autorizado",
                                            "queued": "a tarefa está na fila do computador"}.get(last.status, last.status)
                raise PlatformError(f"esta tarefa não está com o computador agora ({why}): peça de novo com computer_use")
            return None
        return run_step(db, lease, command, args, secret)


def run_step(db, lease: WorkstationLease, command: str, args: dict, secret: bool = False) -> dict:
    if command not in COMMANDS:
        raise PlatformError(f"comando de tela desconhecido: {command}")
    ws = db.get(Workstation, lease.workstation_id)
    if not online(ws):
        raise PlatformError(f"o computador '{ws.name}' não está respondendo (desligado ou sem o app aberto)")
    payload = {k: v for k, v in (args or {}).items() if k != "allowed"}
    if secret:
        payload["secret"] = True
    step = WorkstationStep(lease_id=lease.id, workstation_id=ws.id, command=command, org_id=ws.org_id,
                           args_enc=encrypt(json.dumps(payload, ensure_ascii=False)))
    db.add(step)
    lease.last_step_at = now()
    db.commit()
    sid = step.id
    deadline = time.monotonic() + STEP_TIMEOUT_S
    while time.monotonic() < deadline:
        db.expire_all()
        s = db.get(WorkstationStep, sid)
        if s is None:  # o empréstimo terminou (Parar) enquanto o passo esperava
            raise PlatformError(f"o empréstimo do computador '{ws.name}' terminou: {db.get(WorkstationLease, lease.id).ended_reason}")
        if s.status == "done":
            result = dict(s.result or {})
            db.delete(s)
            db.commit()
            if result.get("error"):
                raise PlatformError(str(result["error"])[:500])
            return result
        time.sleep(POLL_S)
    s = db.get(WorkstationStep, sid)
    if s is not None:
        db.delete(s)
        db.commit()
    raise PlatformError(f"o computador '{ws.name}' não respondeu em {STEP_TIMEOUT_S} s")


# ------------------------------------------------------------------ o computador (token wst_)
def _ws(db, token: str) -> Workstation:
    if not token or not token.startswith("wst_"):
        raise Unauthorized("token do computador inválido")
    ws = db.scalar(tenancy.unscoped(select(Workstation).where(Workstation.token_hash == _hash(token))))
    if ws is None or ws.status != "on":
        raise Unauthorized("token do computador inválido ou computador desligado")
    tenancy.set_org(ws.org_id or 1)
    return ws


def _lease_view(db, lease: WorkstationLease) -> dict:
    e = db.get(Employee, lease.employee_id)
    a = db.get(Agent, e.agent_id) if e else None
    task = db.get(EmployeeTask, lease.task_id)
    return {"lease_id": lease.id, "request_id": lease.request_id, "employee": a.name if a else "", "employee_slug": a.slug if a else "",
            "task_id": lease.task_id, "task_title": task.title if task else "", "app": lease.app, "reason": lease.reason,
            "status": lease.status}


def heartbeat(db, token: str, info: dict | None = None, wait_s: float = 0) -> dict:
    """Estou vivo; devolve os pedidos de empréstimo para a pessoa responder, o empréstimo em uso e o próximo passo
    (long-poll: espera até wait_s por um passo ou pedido novo)."""
    ws = _ws(db, token)
    ws.heartbeat_at = now()
    if info and info.get("os"):
        ws.os = str(info["os"])[:40]
    db.commit()
    sweep(db)
    deadline = time.monotonic() + max(0.0, min(float(wait_s or 0), 25.0))
    seen = int((info or {}).get("seen_requests") or 0)
    while True:
        db.expire_all()
        asks = [_lease_view(db, x) for x in db.scalars(select(WorkstationLease).where(
            WorkstationLease.workstation_id == ws.id, WorkstationLease.status == "requested").order_by(WorkstationLease.id))]
        active = _active(db, ws.id)
        step = None
        if active is not None:
            s = db.scalar(select(WorkstationStep).where(WorkstationStep.lease_id == active.id,
                                                        WorkstationStep.status == "queued").order_by(WorkstationStep.id).limit(1))
            if s is not None:
                s.status, s.taken_at = "taken", now()
                db.commit()
                step = {"id": s.id, "command": s.command, "args": json.loads(decrypt(s.args_enc) or "{}")}
        if step or (asks and len(asks) != seen) or time.monotonic() >= deadline:
            return {"workstation": ws_dict(db, ws, mine=True), "requests": asks,
                    "active": _lease_view(db, active) if active else None, "step": step,
                    "next_s": 0 if step else 1}
        time.sleep(POLL_S)


def step_result(db, token: str, step_id: int, result: dict) -> dict:
    ws = _ws(db, token)
    s = db.get(WorkstationStep, step_id)
    if s is None or s.workstation_id != ws.id:
        raise PlatformError("passo não encontrado (o empréstimo pode ter terminado)")
    shot = (result or {}).get("screenshot") or ""
    if len(shot) > 4_000_000:
        raise PlatformError("captura grande demais")
    s.result = {k: v for k, v in (result or {}).items()
                if k in ("ok", "detail", "window", "app", "size", "elements", "dica", "screenshot", "error")}
    s.status = "done"
    db.commit()
    return {"ok": True}


def answer(db, token: str, lease_id: int, allow: bool, reason: str = "") -> dict:
    """A dona respondeu no próprio computador (o aviso do app): o mesmo efeito de decidir em Decisões."""
    ws = _ws(db, token)
    lease = db.get(WorkstationLease, lease_id)
    if lease is None or lease.workstation_id != ws.id or lease.status != "requested" or not lease.request_id:
        raise PlatformError("pedido de empréstimo não está mais aberto")
    r = db.get(HumanRequest, lease.request_id)
    if r is None or r.status != "open":
        raise PlatformError("pedido de empréstimo não está mais aberto")
    task = db.get(EmployeeTask, lease.task_id)
    who = _owner_name(db, ws)
    _decide_lease(db, r, task, bool(allow), str(reason or "")[:500], who)
    audit(db, who, f"workstation.lease.{'approve' if allow else 'reject'}", ws.name, f"#{r.id} (no computador)")
    return {"lease": _lease_view(db, lease)}


def stop(db, token: str, lease_id: int) -> dict:
    """Parar no computador: o empréstimo acaba na hora; a tarefa recebe a notícia no próximo passo."""
    ws = _ws(db, token)
    lease = db.get(WorkstationLease, lease_id)
    if lease is None or lease.workstation_id != ws.id:
        raise PlatformError("empréstimo não encontrado")
    # o próximo desktop_* da tarefa recebe "o empréstimo terminou: <dona> parou no computador"
    end(db, lease, f"{_owner_name(db, ws)} parou no computador")
    return {"lease_id": lease.id, "status": "ended"}


# ------------------------------------------------------------------ as ferramentas do funcionário
from .platform_tools import Ctx, tool  # noqa: E402  (registradas quando platform_tools carrega este módulo)


@tool("computer_list", "Lista os computadores de pessoas que você pode pegar emprestado para passos de tela (apps de "
      "desktop que só existem lá): nome, sistema, apps liberados, se está ligado agora e se está em uso.",
      {"properties": {}}, "computer", any_usable)
def computer_list(ctx: Ctx, args: dict):
    sweep(ctx.db)
    rows = [ws_dict(ctx.db, ws) for ws in usable(ctx.db, ctx.e)]
    mine = lease_of_task(ctx.db, ctx.task.id)
    return {"computers": [{**r, "owner": _owner_name(ctx.db, ctx.db.get(Workstation, r["id"]))} for r in rows],
            "in_use_by_this_task": mine.workstation_id if mine else None}


@tool("computer_use", "Pede emprestado o computador de uma pessoa para esta tarefa (veja computer_list). A dona pode "
      "ter de autorizar: a tarefa espera a resposta; se o computador estiver em uso, a tarefa espera na fila. Com o "
      "empréstimo ativo, desktop_open/desktop_look/desktop_click/desktop_type/desktop_key agem nessa máquina, com a "
      "sua alçada. Diga o app e o motivo (a dona vê).",
      {"properties": {"computer": {"type": "string", "description": "nome ou id do computador"},
                      "app": {"type": "string", "description": "o app que você vai usar lá"},
                      "reason": {"type": "string", "description": "para que, em uma frase"}},
       "required": ["computer", "reason"]}, "computer", any_usable)
def computer_use(ctx: Ctx, args: dict):
    return request(ctx, args.get("computer"), str(args.get("app") or ""), str(args.get("reason") or ctx.rationale or ""))


@tool("computer_release", "Devolve o computador emprestado a esta tarefa (quando a parte de tela terminou).",
      {"properties": {}}, "computer", any_usable)
def computer_release(ctx: Ctx, args: dict):
    return release(ctx)
