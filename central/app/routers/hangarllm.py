"""Hub HangarLLM (/api/hangarllm): ligar, ver, sincronizar (modelos, MCPs e skills) e desligar. Só admins."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from .. import services as svc
from .deps import actor, db_dep, guard, require_admin

router = APIRouter(prefix="/api/hangarllm", dependencies=[Depends(require_admin)])


class HubBody(BaseModel):
    url: str = ""  # como a central e os agentes chegam nele (ex.: http://hangarllm:4000); vazio = procurar no Docker
    admin_key: str = ""  # chave mestra ou de gestão; vazio mantém a atual
    ui_url: str = ""  # o painel, para os links da tela (ex.: https://localhost:4400/ui)
    budget_usd: float | None = None  # orçamento de cada chave de agente, por período
    budget_period: str | None = None  # 1d | 7d | 30d
    share_skills: bool | None = None  # publicar as skills da empresa no Skill Hub


class NetworkBody(BaseModel):
    container: str = "hangarllm-hangarllm-1"


@router.get("")
def hub_status(db=Depends(db_dep)):
    return guard(lambda: svc.hangarllm.status(db))


@router.put("")
def hub_connect(b: HubBody, request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.hangarllm.connect(db, b.url, b.admin_key, b.ui_url, b.budget_usd, b.budget_period,
                                               actor(request), b.share_skills))


@router.delete("")
def hub_disconnect(request: Request, db=Depends(db_dep)):
    return guard(lambda: svc.hangarllm.disconnect(db, actor(request)))


@router.post("/refresh")
def hub_refresh(request: Request, db=Depends(db_dep)):
    """Renova as chaves, lê o gasto real e sincroniza MCPs e skills agora (o agendador faz isso de hora em hora)."""
    return guard(lambda: {**svc.hangarllm.refresh(db, actor(request)), **svc.hangarllm.status(db)})


@router.get("/discover")
def hub_discover():
    """Instalação local: os HangarLLM que a central enxerga no Docker (para ligar só com a chave)."""
    return {"found": svc.hangarllm.discover()}


@router.post("/network")
def hub_network(b: NetworkBody, request: Request):
    """Instalação local com Docker: põe o HangarLLM na rede dos agentes, como http://hangarllm:4000."""
    return guard(lambda: svc.hangarllm.attach_network(b.container, actor(request)))
