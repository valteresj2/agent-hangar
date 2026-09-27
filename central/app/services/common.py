"""Peças usadas por todos os módulos de serviço."""
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Agent, AuditLog


class PlatformError(Exception):
    """Erro de regra de negócio — vira HTTP 400 na API e erro de tool no MCP."""


def audit(db: Session, actor: str, action: str, target: str = "", detail: str = ""):
    db.add(AuditLog(actor=actor, action=action, target=target, detail=detail[:2000]))
    db.commit()


def iso(dt):
    return dt.isoformat() if dt else None


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower().strip()).strip("-")
    return s[:60] or "agent"


def find_agent(db: Session, slug: str) -> Agent | None:
    return db.scalar(select(Agent).where(Agent.slug == slug))


def get_agent(db: Session, slug: str) -> Agent:
    a = find_agent(db, slug)
    if not a:
        raise PlatformError(f"Agente '{slug}' não encontrado")
    return a


def spec_of(agent: Agent, version: int | None = None) -> dict:
    v = version or agent.current_version
    for av in agent.versions:
        if av.version == v:
            return av.spec
    raise PlatformError(f"Versão {v} inexistente")
