"""Ritmo das mensagens de um Digital employee para as pessoas: funcionários que trabalham sozinhos não podem virar ruído.

Cada funcionário tem o seu ritmo (`Employee.pacing`, editado pelo gestor):

- `quiet`: `off` (padrão) ou `business` — fora do expediente da empresa (dias úteis, feriados e horário do calendário em
  *Calendário*), as mensagens esperam o próximo expediente.
- `max_per_hour`: teto de mensagens dele para uma mesma pessoa por hora (0 = sem teto). O que passa espera a hora virar.
- `low`: `now` (padrão) ou `digest` — pedidos de tarefas de baixa prioridade esperam o resumo diário (na hora do resumo
  da empresa, `digest_hour`).

Urgente nunca espera: pedido prestes a expirar ou escalado, tarefa de prioridade alta, prazo vencido.

O que esperou sai **num resumo só** por pessoa e funcionário ("enquanto você estava fora do expediente: 3 pedidos…"),
com o link do portal; pedidos já decididos nesse meio-tempo ficam de fora. O pedido continua aberto na caixa de
Decisões o tempo todo, e o prazo de expiração dele não muda: quem precisa que nada expire fora do expediente usa o
`quiet` junto com prazos maiores ou deixa a expiração escalar (escalado é urgente).
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from ..models import Agent, Employee, EmployeeTask, HumanRequest, PacedMessage, User, now
from . import bizcal
from .common import PlatformError, audit

DEFAULT = {"quiet": "off", "max_per_hour": 0, "low": "now"}
REASON = {"quiet": ("fora do expediente", "outside business hours"), "cap": ("acima do limite por hora", "over the hourly limit"),
          "low": ("baixa prioridade, para o resumo", "low priority, for the digest")}


def settings(e: Employee) -> dict:
    return {**DEFAULT, **(e.pacing or {})}


def set_pacing(db, acc, slug: str, changes: dict) -> dict:
    from .employees import find
    e, a = find(db, acc, slug, "manage")
    p = settings(e)
    if changes.get("quiet") is not None:
        if changes["quiet"] not in ("off", "business"):
            raise PlatformError("quiet: off | business")
        p["quiet"] = changes["quiet"]
    if changes.get("max_per_hour") is not None:
        n = int(changes["max_per_hour"])
        if not 0 <= n <= 60:
            raise PlatformError("max_per_hour: de 0 (sem teto) a 60")
        p["max_per_hour"] = n
    if changes.get("low") is not None:
        if changes["low"] not in ("now", "digest"):
            raise PlatformError("low: now | digest")
        p["low"] = changes["low"]
    e.pacing = p
    db.commit()
    audit(db, acc.p.name, "employee.pacing", a.slug, f"quiet={p['quiet']} max={p['max_per_hour']} low={p['low']}")
    return {"pacing": p, "held": held_count(db, e)}


def in_quiet(db, at: datetime | None = None) -> bool:
    """Fora do expediente da empresa: dia que não é útil, ou fora do horário do calendário."""
    cal = bizcal.of(db)
    local = (at or now()).astimezone(ZoneInfo(cal.tz))
    start, end = cal.hours()
    return not cal.is_business_day(local.date()) or not (start <= local.time().replace(tzinfo=None) < end)


def _sent_last_hour(db, e: Employee, user_id: int, at: datetime) -> int:
    """Mensagens dele para a pessoa na última hora: cada envio conta um, e um resumo de seguradas conta um só."""
    since = at - timedelta(hours=1)
    base = (PacedMessage.employee_id == e.id, PacedMessage.user_id == user_id)
    sent = db.scalar(select(func.count()).select_from(PacedMessage).where(
        *base, PacedMessage.status == "sent", PacedMessage.created_at > since)) or 0
    bundles = db.scalar(select(func.count(func.distinct(PacedMessage.released_at))).where(
        *base, PacedMessage.status == "released", PacedMessage.released_at > since)) or 0
    return sent + bundles


def allow(db, e: Employee, user_id: int, kind: str, ref_id: int, priority: str = "normal", detail: str = "",
          at: datetime | None = None) -> bool:
    """Pode mandar agora? Se não, a mensagem fica segurada (e sai depois, no resumo). Sempre registra o que foi."""
    at = at or now()
    p, reason = settings(e), ""
    if priority != "urgent":
        if priority == "low" and p["low"] == "digest":
            reason = "low"
        elif p["quiet"] == "business" and in_quiet(db, at):
            reason = "quiet"
        elif p["max_per_hour"] and _sent_last_hour(db, e, user_id, at) >= p["max_per_hour"]:
            reason = "cap"
    db.add(PacedMessage(user_id=user_id, employee_id=e.id, kind=kind, ref_id=ref_id, detail=detail[:300],
                        status="held" if reason else "sent", reason=reason, created_at=at))
    db.commit()
    return not reason


def request_priority(db, r: HumanRequest, why: str) -> str:
    if why in ("expiring", "escalated"):
        return "urgent"
    task = db.get(EmployeeTask, r.task_id) if r.task_id else None
    if task is not None and task.priority == 1:
        return "urgent"
    return "low" if task is not None and task.priority == 3 else "normal"


def held_count(db, e: Employee) -> int:
    return db.scalar(select(func.count()).select_from(PacedMessage).where(
        PacedMessage.employee_id == e.id, PacedMessage.status == "held")) or 0


def _digest_moment(db, at: datetime) -> datetime | None:
    """O horário do resumo diário de hoje (fuso da empresa), se já passou; None se o resumo está desligado."""
    from . import notify
    hour = notify.org_cfg(db)["digest_hour"]
    if hour < 0:
        return None
    local = at.astimezone(ZoneInfo(bizcal.of(db).tz))
    moment = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    return moment if local >= moment else moment - timedelta(days=1)


def _due(db, e: Employee, rows: list[PacedMessage], at: datetime) -> list[PacedMessage]:
    """As seguradas que já podem sair: baixa prioridade na hora do resumo (de um dia anterior ou de hoje antes da hora);
    as do expediente quando ele começa; as do teto quando a hora vira."""
    p, quiet = settings(e), in_quiet(db, at)
    digest = _digest_moment(db, at)
    out = []
    for m in rows:
        if m.reason == "low":  # uma vez por dia: o que chegou antes do último horário do resumo
            from . import employee_tasks as tasksmod
            ok = digest is not None and tasksmod._aware(m.created_at) < digest
        elif m.reason == "quiet":
            ok = not quiet or p["quiet"] != "business"
        else:  # cap: quando a hora virar (e, com expediente ligado, dentro dele)
            ok = not (p["quiet"] == "business" and quiet) and (
                not p["max_per_hour"] or _sent_last_hour(db, e, m.user_id, at) < p["max_per_hour"])
        if ok:
            out.append(m)
    return out


def _line(db, m: PacedMessage, en: bool) -> str | None:
    if m.kind == "request":
        r = db.get(HumanRequest, m.ref_id)
        if r is None or r.status != "open":
            return None  # decidido no meio-tempo: não incomoda
        return f"• #{r.id} " + (m.detail or r.kind)
    task = db.get(EmployeeTask, m.ref_id)
    if task is None or task.status in ("done", "cancelled", "expired"):
        return None
    return f"• {'task' if en else 'tarefa'} #{task.id} " + (m.detail or task.title)


def sweep(db, at: datetime | None = None) -> int:
    """Entrega o que esperou e já pode sair: um resumo por pessoa e funcionário."""
    from . import employee_tasks as tasksmod
    from . import notify
    at = at or now()
    held = db.scalars(select(PacedMessage).where(PacedMessage.status == "held").order_by(PacedMessage.id)).all()
    groups: dict[tuple[int, int], list[PacedMessage]] = {}
    for m in held:
        groups.setdefault((m.user_id, m.employee_id), []).append(m)
    sent = 0
    for (uid, eid), rows in groups.items():
        e, u = db.get(Employee, eid), db.get(User, uid)
        if e is None or u is None or not u.active:
            for m in rows:
                m.status, m.released_at = "dropped", at
            db.commit()
            continue
        ready = _due(db, e, rows, at)
        if not ready:
            continue
        en = tasksmod.lang_of(e) == "en"
        lines = []
        for m in ready:
            line = _line(db, m, en)  # decidido ou concluído no meio-tempo: sai da fila sem incomodar
            m.status, m.released_at = ("released" if line else "dropped"), at
            if line:
                lines.append(line)
        db.commit()
        if not lines:
            continue
        a = db.get(Agent, e.agent_id)
        name = a.name if a else e.title
        why = sorted({REASON[m.reason][1 if en else 0] for m in ready})
        title = (f"{name}: {len(lines)} message(s) that waited ({', '.join(why)})" if en else
                 f"{name}: {len(lines)} mensagem(ns) que esperaram ({', '.join(why)})")
        cfg = notify.org_cfg(db)
        via = notify.route(cfg, u)
        if via:
            try:
                notify._send_text(db, cfg, u, via, title, lines[:20], notify.portal(), "Open decisions" if en else "Abrir decisões")
                sent += 1
            except Exception:  # noqa: BLE001 — um destinatário com problema não impede os outros
                notify.log.exception("resumo do ritmo para %s", u.email)
    return sent
