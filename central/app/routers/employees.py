"""API do Digital employee: contratação, ciclo de vida, alçada, tarefas, decisões (humano no circuito), relatórios e,
para o admin, a força de trabalho digital (catálogo de ações, piso da empresa e parada geral)."""
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import services as svc
from .deps import acc, db_dep, guard

router = APIRouter(prefix="/api")


class HireBody(BaseModel):
    request: str = ""
    name: str = ""
    title: str = ""
    mission: str = ""
    responsibilities: list[str] = Field(default_factory=list)
    manager: str = ""
    backups: list[str] = Field(default_factory=list)
    team: str = ""
    visibility: str = ""
    systems: list[str] = Field(default_factory=list)
    specialists: list[str] = Field(default_factory=list)
    base: str = ""
    skills: list[str] = Field(default_factory=list)
    new_skills: list[dict] = Field(default_factory=list)
    mcps: list[str] = Field(default_factory=list)
    tools: list[dict] = Field(default_factory=list)
    instructions: str = ""
    llm: dict | None = None
    memory: dict | None = None
    channels: list[str] = Field(default_factory=list)
    authority: list[dict] = Field(default_factory=list)
    accept_default_authority: bool = False
    autonomy_level: str = "intern"
    probation_tasks: list[dict] = Field(default_factory=list)
    kpis: list[dict] = Field(default_factory=list)
    working_hours: str = ""
    task_budget_usd: float | None = None
    task_time_limit_min: int | None = None
    report_webhook: str = ""
    report_hour: int | None = None
    plan_id: str = ""


class StatusBody(BaseModel):
    to: str
    reason: str = ""


class AuthorityBody(BaseModel):
    rules: list[dict]


class TaskBody(BaseModel):
    title: str = Field(max_length=300)
    body: str = ""
    priority: int = 2
    due_at: datetime | None = None


class DecisionBody(BaseModel):
    decision: str
    edit: dict | None = None
    reason: str = ""


class BatchDecisionBody(BaseModel):
    ids: list[int]
    decision: str
    reason: str = ""


class ClassifyBody(BaseModel):
    tool_ref: str
    action_type: str
    risk: int | None = None
    reversible: bool = False


class FloorBody(BaseModel):
    items: list[dict]


class StopBody(BaseModel):
    reason: str = ""


def _fields(b: HireBody) -> dict:
    return {k: v for k, v in b.model_dump().items() if k != "request"}


@router.get("/employees")
def employees(request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.list_employees(db, acc(request, db)))


@router.post("/employees/plan")
def plan(body: HireBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.plan(db, acc(request, db), body.request, **_fields(body)))


@router.post("/employees")
def hire(body: HireBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.hire(db, acc(request, db), body.request, **_fields(body)))


@router.get("/employees/{slug}")
def detail(slug: str, request: Request, db=Depends(db_dep)):
    def go():
        a = acc(request, db)
        e, _ = svc.employees.find(db, a, slug)
        return {**svc.employees.employee_dict(db, e, a, detail=True), "metrics": svc.employees.metrics(db, e)}
    return guard(go)


@router.patch("/employees/{slug}")
def update(slug: str, body: dict, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.update(db, acc(request, db), slug, body))


@router.post("/employees/{slug}/probation")
def probation(slug: str, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.start_probation(db, acc(request, db), slug))


@router.post("/employees/{slug}/status")
def status(slug: str, body: StatusBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.set_status(db, acc(request, db), slug, body.to, body.reason))


@router.put("/employees/{slug}/authority")
def authority(slug: str, body: AuthorityBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.set_authority(db, acc(request, db), slug, body.rules))


@router.get("/employees/{slug}/tasks")
def tasks(slug: str, request: Request, status: str | None = None, db=Depends(db_dep)):
    return guard(lambda: svc.employees.tasks_of(db, acc(request, db), slug, status))


@router.post("/employees/{slug}/tasks")
def assign(slug: str, body: TaskBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.assign(db, acc(request, db), slug, body.title, body.body, body.priority,
                                              body.due_at))


@router.get("/employees/{slug}/reports")
def reports(slug: str, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.reports_of(db, acc(request, db), slug))


@router.post("/employees/{slug}/reports")
def report_now(slug: str, request: Request, db=Depends(db_dep)):
    def go():
        e, _ = svc.employees.find(db, acc(request, db), slug, "manage")
        r = svc.employees.make_report(db, e, "daily")
        return {"id": r.id, "summary": r.summary, "delivered": r.delivered, "metrics": r.metrics}
    return guard(go)


@router.get("/tasks/{task_id}")
def task(task_id: int, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.task_detail(db, acc(request, db), task_id))


@router.post("/tasks/{task_id}/cancel")
def cancel(task_id: int, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.cancel_task(db, acc(request, db), task_id))


@router.get("/decisions")
def decisions(request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employee_tasks.pending_for(db, acc(request, db)))


@router.post("/decisions/batch")
def decide_batch(body: BatchDecisionBody, request: Request, db=Depends(db_dep)):
    def go():
        a, out = acc(request, db), []
        for i in body.ids:
            try:
                out.append(svc.employee_tasks.decide(db, a, i, body.decision, None, body.reason))
            except svc.PlatformError as e:
                out.append({"id": i, "error": str(e)})
        return out
    return guard(go)


@router.post("/decisions/{request_id}")
def decide(request_id: int, body: DecisionBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employee_tasks.decide(db, acc(request, db), request_id, body.decision, body.edit,
                                                   body.reason))


# ------------------------------------------------------------------ admin
@router.get("/admin/workforce")
def workforce(request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.workforce(db, acc(request, db)))


@router.post("/admin/workforce/stop-all")
def stop_all(body: StopBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.stop_all(db, acc(request, db), body.reason))


@router.get("/admin/action-catalog")
def action_catalog(request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.catalog(db, acc(request, db)))


@router.put("/admin/action-catalog")
def classify(body: ClassifyBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.classify_tool(db, acc(request, db), body.tool_ref, body.action_type, body.risk,
                                                     body.reversible))


@router.get("/admin/authority-floor")
def floor(request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.floor(db, acc(request, db)))


@router.put("/admin/authority-floor")
def set_floor(body: FloorBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.employees.set_floor(db, acc(request, db), body.items))
