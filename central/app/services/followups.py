"""Retorno marcado pelo próprio Digital employee: "confira daqui a 2h se o pagamento caiu".

Quando o trabalho depende de algo que ainda vai acontecer (um pagamento, um build, a resposta de um sistema), o
funcionário chama `set_followup` com o horário e o que conferir. A rodada termina, a tarefa dorme em `waiting_timer`
(sem gastar nada) e, na hora marcada, a varredura a acorda com uma mensagem "RETORNO MARCADO" na conversa: a próxima
rodada lê o que conferir e continua a mesma tarefa, com todo o histórico.

- Um retorno por tarefa: marcar de novo troca o anterior; `cancel_followup` desmarca.
- De 5 minutos a 30 dias. O `check` é tudo o que o funcionário lê ao acordar: escrito para quem não lembra do contexto.
- Uma mensagem de alguém na conversa da tarefa acorda antes da hora (o retorno marcado fica cancelado).
- Pausar a tarefa segura o retorno; retomar volta a esperar o horário (ou acorda, se já passou).
- Nada sai da plataforma: marcar um retorno não passa pela alçada.

O retorno fica na linha do tempo (evento `followup`, com `state`: pending | done | cancelled | early).
"""
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from ..models import EmployeeTask, TaskEvent, TaskMessage, now
from . import employee_tasks as tasksmod
from .common import PlatformError, iso
from .platform_tools import Ctx, tool

MIN_DELAY = timedelta(minutes=5)
MAX_DELAY = timedelta(days=30)
_UNITS = {"m": "minutes", "min": "minutes", "h": "hours", "d": "days", "w": "weeks"}
_DUR = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(m|min|h|d|w)\s*$", re.I)


def parse_when(args: dict, at: datetime | None = None) -> datetime:
    """`in` (30m, 2h, 3d, 1w) ou `at` (ISO 8601 com fuso) → instante em UTC, entre 5 minutos e 30 dias."""
    at = at or now()
    if args.get("in"):
        m = _DUR.match(str(args["in"]))
        if not m:
            raise PlatformError("'in' é uma duração como 30m, 2h, 3d ou 1w")
        when = at + timedelta(**{_UNITS[m.group(2).lower()]: float(m.group(1).replace(",", "."))})
    elif args.get("at"):
        try:
            when = datetime.fromisoformat(str(args["at"]).strip().replace("Z", "+00:00"))
        except ValueError as ex:
            raise PlatformError("'at' é uma data e hora ISO 8601, com fuso (ex.: 2026-12-01T09:00:00-03:00)") from ex
        if when.tzinfo is None:
            raise PlatformError("'at' precisa do fuso (ex.: -03:00)")
    else:
        raise PlatformError("diga quando: 'in' (ex.: 2h) ou 'at' (data e hora ISO 8601)")
    when = when.astimezone(UTC)
    if when - at < MIN_DELAY:
        raise PlatformError("o retorno precisa ser daqui a 5 minutos ou mais")
    if when - at > MAX_DELAY:
        raise PlatformError("o retorno pode ser em até 30 dias")
    return when


def current(db, task: EmployeeTask) -> TaskEvent | None:
    """O retorno pendente da tarefa (o último marcado, se ainda não disparou nem foi cancelado)."""
    ev = db.scalar(select(TaskEvent).where(TaskEvent.task_id == task.id, TaskEvent.kind == "followup")
                   .order_by(TaskEvent.id.desc()))
    return ev if ev is not None and (ev.payload or {}).get("state") == "pending" else None


def pending(db, task: EmployeeTask) -> bool:
    return current(db, task) is not None


def _close(ev: TaskEvent, state: str):
    ev.payload = {**(ev.payload or {}), "state": state, "closed_at": iso(now())}


@tool("set_followup", "Marca um retorno nesta tarefa: quando o trabalho depende de algo que ainda vai acontecer (um "
      "pagamento cair, um processo terminar, um sistema atualizar), a tarefa dorme sem gastar nada e você acorda na hora "
      "marcada para conferir e continuar. Use 'in' (30m, 2h, 3d, 1w) ou 'at' (ISO 8601 com fuso). 'check' é o que "
      "conferir ao acordar: escreva completo, para quem não lembra do contexto. Marcar de novo troca o retorno anterior. "
      "Depois de marcar, encerre a rodada dizendo o que vai conferir e quando.",
      {"properties": {"check": {"type": "string", "description": "o que conferir ao acordar, e o que fazer depois"},
                      "in": {"type": "string", "description": "daqui a quanto tempo: 30m, 2h, 3d, 1w"},
                      "at": {"type": "string", "description": "data e hora ISO 8601 com fuso"}},
       "required": ["check"]}, "followups")
def set_followup(ctx: Ctx, args: dict):
    check = str(args.get("check") or "").strip()
    if not check:
        raise PlatformError("diga o que conferir ao acordar ('check')")
    when = parse_when(args)
    old = current(ctx.db, ctx.task)
    if old is not None:
        _close(old, "cancelled")
    tasksmod.event(ctx.db, ctx.task, "followup", {"state": "pending", "at": iso(when), "check": check[:2000]})
    ctx.db.commit()
    return (f"Retorno marcado para {iso(when)} (UTC){' no lugar do anterior' if old else ''}. Encerre esta rodada "
            "dizendo o que vai conferir e quando; a tarefa dorme até lá e você continua daqui.")


@tool("cancel_followup", "Desmarca o retorno pendente desta tarefa (quando o que você ia conferir já aconteceu).",
      {"properties": {}}, "followups")
def cancel_followup(ctx: Ctx, args: dict):
    ev = current(ctx.db, ctx.task)
    if ev is None:
        return "Esta tarefa não tem retorno marcado."
    _close(ev, "cancelled")
    ctx.db.commit()
    return "Retorno desmarcado."


def wake(db, task: EmployeeTask, reason: str = "due"):
    """Acorda a tarefa que dorme num retorno: na hora marcada (due) ou antes, por uma mensagem (early)."""
    ev = current(db, task)
    if ev is not None:
        p = ev.payload or {}
        _close(ev, "done" if reason == "due" else "early")
        if reason == "due":
            db.add(TaskMessage(task_id=task.id, author="plataforma", status="queued", created_at=now(),
                               body=f"RETORNO MARCADO (para {p.get('at')}): {p.get('check')}\nConfira agora e continue "
                                    "a tarefa. Se ainda não aconteceu, marque outro retorno ou decida o próximo passo."))
    if task.status == "waiting_timer":
        task.status, task.not_before = "new", None
    tasksmod.event(db, task, "note", {"followup": "acordou na hora marcada" if reason == "due" else
                                      "acordou antes: chegou mensagem na conversa"})


def after_hold(db, task: EmployeeTask) -> str:
    """O status de uma tarefa que sai da pausa com um retorno pendente: volta a esperar (ou acorda, se já passou)."""
    ev = current(db, task)
    if ev is None:
        return ""
    if tasksmod._aware(datetime.fromisoformat((ev.payload or {})["at"])) <= now():
        task.status = "waiting_timer"
        wake(db, task, "due")
        return task.status
    return "waiting_timer"


def sweep(db, at: datetime | None = None) -> int:
    """As tarefas cujo retorno venceu voltam para a fila, com o que conferir na conversa."""
    at, woke = at or now(), 0
    for task in db.scalars(select(EmployeeTask).where(EmployeeTask.status == "waiting_timer")).all():
        ev = current(db, task)
        if ev is None:  # sem retorno pendente (cancelado na mão): volta para a fila
            task.status = "new"
            woke += 1
            continue
        if tasksmod._aware(datetime.fromisoformat(ev.payload["at"])) <= at:
            wake(db, task, "due")
            woke += 1
    if woke:
        db.commit()
    return woke


def info(db, task: EmployeeTask) -> dict | None:
    ev = current(db, task)
    return {"at": ev.payload.get("at"), "check": ev.payload.get("check")} if ev is not None else None
