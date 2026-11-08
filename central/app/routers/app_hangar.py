"""API do app Hangar (desktop): /api/app com o token OAuth de escopo `app`, e /api/app/admin para o console
(contrato em docs/app-hangar.md; regras em services/app_hangar.py)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .. import auth
from ..services import app_events, app_llm
from ..services import app_hangar as ah
from .deps import actor, db_dep, guard, principal, require_admin

router = APIRouter(prefix="/api/app")


def _guard(fn):
    def run():
        try:
            return fn()
        except ah.NotFound as e:
            raise HTTPException(404, str(e)) from None
    return guard(run)


class DeviceBody(BaseModel):
    device_id: str
    name: str = ""
    os: str = ""
    os_version: str = ""
    app_version: str = ""
    channel: str = ""


class HeartbeatBody(BaseModel):
    app_version: str = ""


@router.get("/me")
def me(request: Request, db=Depends(db_dep)):
    return guard(lambda: ah.me(db, principal(request)))


@router.post("/devices")
def register_device(body: DeviceBody, request: Request, db=Depends(db_dep)):
    return _guard(lambda: ah.register_device(db, principal(request), body.model_dump()))


@router.post("/devices/{device_id}/heartbeat")
def heartbeat(device_id: str, request: Request, body: HeartbeatBody | None = None, db=Depends(db_dep)):
    """Também atende o token de uma autorização já encerrada (o middleware deixa passar): responde `revoked`."""
    p = request.scope.get("state", {}).get("principal")
    token = auth.token_from_headers({k.lower(): v for k, v in request.headers.items()})
    try:
        return _guard(lambda: ah.heartbeat(db, p, token, device_id, body.app_version if body else ""))
    except ah.Unauthorized as e:
        raise HTTPException(401, str(e)) from None


@router.post("/devices/{device_id}/llm-key")
def llm_key(device_id: str, request: Request, db=Depends(db_dep)):
    """Gera ou troca a chave do proxy de LLM do dispositivo (ahl_…, aparece só aqui): a anterior deixa de valer."""
    return _guard(lambda: app_llm.rotate_key(db, principal(request), device_id))


@router.get("/models")
def models(request: Request, db=Depends(db_dep)):
    """Os modelos de token sincronizados com o Hangar desktop (docs/app-hangar-models.md)."""
    return guard(lambda: app_llm.models_for_app(db, principal(request)))


# ------------------------------------------------------------------ computadores compartilhados (services/workstations.py)
class WorkstationBody(BaseModel):
    name: str | None = None
    os: str | None = None
    apps: list[dict] | None = None
    allow_managed: bool | None = None
    allow_team_ids: list[int] | None = None
    auth_mode: str | None = None  # ask | preauthorized

    def fields(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None}


@router.get("/workstations")
def my_workstations(request: Request, db=Depends(db_dep)):
    from ..services import workstations
    return guard(lambda: workstations.mine(db, principal(request)))


@router.post("/workstations")
def register_workstation(body: WorkstationBody, request: Request, db=Depends(db_dep)):
    """Liga este computador para os funcionários pegarem emprestado; o token wst_… aparece só nesta resposta."""
    from ..services import workstations
    return guard(lambda: workstations.register(db, principal(request), body.fields()))


@router.patch("/workstations/{ws_id}")
def update_workstation(ws_id: int, body: WorkstationBody, request: Request, db=Depends(db_dep)):
    from ..services import workstations
    return guard(lambda: workstations.update(db, principal(request), ws_id, body.fields()))


@router.delete("/workstations/{ws_id}")
def remove_workstation(ws_id: int, request: Request, db=Depends(db_dep)):
    from ..services import workstations
    return guard(lambda: workstations.remove(db, principal(request), ws_id))


# ------------------------------------------------------------------ gravar uma tarefa (services/recordings.py)
class TranscribeBody(BaseModel):
    audio: str
    mime: str = "audio/webm"


class DraftBody(BaseModel):
    draft: dict


class RecordingHireBody(BaseModel):
    draft: dict
    workstation_id: int | None = None


@router.post("/recordings/transcribe")
def transcribe_recording(body: TranscribeBody, request: Request, db=Depends(db_dep)):
    """A explicação gravada vira texto (modelo de fala da empresa); o áudio não fica guardado."""
    from ..services import recordings
    return guard(lambda: recordings.transcribe(db, principal(request), body.model_dump()))


@router.get("/recordings")
def my_recordings(request: Request, db=Depends(db_dep)):
    from ..services import recordings
    return guard(lambda: recordings.mine(db, principal(request)))


@router.post("/recordings")
def create_recording(body: dict, request: Request, db=Depends(db_dep)):
    """O pacote da gravação (passos, explicação, até 12 capturas) vira o rascunho do funcionário."""
    from ..services import recordings
    return guard(lambda: recordings.create(db, principal(request), body))


@router.get("/recordings/{rec_id}")
def get_recording(rec_id: int, request: Request, db=Depends(db_dep)):
    from ..services import recordings
    return guard(lambda: recordings.get(db, principal(request), rec_id))


@router.post("/recordings/{rec_id}/redraft")
def redraft_recording(rec_id: int, body: dict, request: Request, db=Depends(db_dep)):
    from ..services import recordings
    return guard(lambda: recordings.redraft(db, principal(request), rec_id, body))


@router.put("/recordings/{rec_id}/draft")
def save_recording_draft(rec_id: int, body: DraftBody, request: Request, db=Depends(db_dep)):
    from ..services import recordings
    return guard(lambda: recordings.save_draft(db, principal(request), rec_id, body.draft))


@router.post("/recordings/{rec_id}/hire")
def hire_from_recording(rec_id: int, body: RecordingHireBody, request: Request, db=Depends(db_dep)):
    """O rascunho revisado vira um Digital employee em modo sombra e período de experiência."""
    from ..services import recordings
    return guard(lambda: recordings.hire(db, principal(request), rec_id, body.draft, body.workstation_id))


@router.delete("/recordings/{rec_id}")
def delete_recording(rec_id: int, request: Request, db=Depends(db_dep)):
    from ..services import recordings
    return guard(lambda: recordings.remove(db, principal(request), rec_id))


@router.get("/events")
async def events(request: Request):
    """Eventos da pessoa em SSE (docs/app-hangar-workspace.md, seção 2): retoma com Last-Event-ID, keepalive a cada
    25 s, fecha depois de 30 min (o cliente reconecta)."""
    p = principal(request)
    if not p.user_id:
        raise HTTPException(403, "os eventos são de uma pessoa (entre com a sua conta)")
    headers = {k.lower(): v for k, v in request.headers.items()}
    token = auth.token_from_headers(headers) or auth.cookie(headers, auth.SESSION_COOKIE)
    last = request.headers.get("last-event-id") or request.query_params.get("last_event_id")
    return StreamingResponse(app_events.stream(request, p, token, last), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/design-tokens")
def design_tokens():
    return ah.design_tokens()


# ------------------------------------------------------------------ console (admin)
@router.get("/admin/overview", dependencies=[Depends(require_admin)])
def admin_overview(db=Depends(db_dep)):
    return ah.admin_overview(db)


@router.get("/admin/devices", dependencies=[Depends(require_admin)])
def admin_devices(db=Depends(db_dep)):
    return ah.admin_devices(db)


@router.post("/admin/devices/{device_pk}/revoke", dependencies=[Depends(require_admin)])
def admin_revoke(device_pk: int, request: Request, db=Depends(db_dep)):
    return _guard(lambda: ah.admin_revoke(db, actor(request), device_pk))
