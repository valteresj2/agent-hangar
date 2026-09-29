"""Agendamentos de agentes (/api): criar, listar, editar, excluir, rodar agora e histórico."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .. import services as svc
from .deps import acc, db_dep, guard

router = APIRouter(prefix="/api")


class ScheduleBody(BaseModel):
    message: str
    cron: str | None = None  # recorrente, 5 campos: "0 9 * * 1-5"
    run_at: str | None = None  # uma vez: "2026-10-05T09:00" (no fuso do agendamento)
    timezone: str | None = None  # padrão: o da empresa
    name: str = ""
    notify_url: str = ""
    enabled: bool = True


class SchedulePatch(BaseModel):
    message: str | None = None
    cron: str | None = None
    run_at: str | None = None
    timezone: str | None = None
    name: str | None = None
    notify_url: str | None = None
    enabled: bool | None = None


@router.get("/agents/{slug}/schedules")
def agent_schedules(slug: str, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.schedules.list_for(db, acc(request, db), slug))


@router.post("/agents/{slug}/schedules")
def create_schedule(slug: str, body: ScheduleBody, request: Request, db=Depends(db_dep)):
    def go():
        s = svc.schedules.create(db, acc(request, db), slug, body.message, body.cron, body.run_at, body.timezone,
                                 body.name, body.notify_url, body.enabled)
        return svc.schedules.schedule_dict(db, s)
    return guard(go)


@router.get("/schedules")
def all_schedules(request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.schedules.list_for(db, acc(request, db)))


@router.patch("/schedules/{sid}")
def patch_schedule(sid: int, body: SchedulePatch, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.schedules.schedule_dict(db, svc.schedules.update_schedule(
        db, acc(request, db), sid, **body.model_dump(exclude_unset=True))))


@router.delete("/schedules/{sid}")
def delete_schedule(sid: int, request: Request, db=Depends(db_dep)):
    guard(lambda: svc.schedules.delete(db, acc(request, db), sid))
    return {"ok": True}


@router.post("/schedules/{sid}/run")
def run_schedule(sid: int, request: Request, db=Depends(db_dep)):
    """Roda agora (espera terminar) — útil para testar o agendamento sem esperar o horário."""
    return guard(lambda: svc.schedules.run_now(db, acc(request, db), sid))


@router.get("/schedules/{sid}/runs")
def schedule_runs(sid: int, request: Request, limit: int = 20, db=Depends(db_dep)):
    return guard(lambda: svc.schedules.runs(db, acc(request, db), sid, min(limit, 100)))
