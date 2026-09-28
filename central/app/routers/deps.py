"""Peças comuns dos routers: sessão de banco, quem está chamando, permissões e erros -> HTTP."""
from fastapi import HTTPException, Request

from .. import auth
from .. import services as svc
from ..db import SessionLocal
from ..services import access


def db_dep():
    with SessionLocal() as db:
        yield db


def principal(request: Request) -> auth.Principal:
    p = request.scope.get("state", {}).get("principal")
    if p is None:
        raise HTTPException(401, "não autenticado")
    return p


def actor(request: Request) -> str:
    p = request.scope.get("state", {}).get("principal")
    return p.name if p else "admin"


def acc(request: Request, db) -> access.Access:
    return access.of(db, principal(request))


def guard(fn):
    try:
        return fn()
    except access.Forbidden as e:
        raise HTTPException(403, str(e)) from None
    except svc.PlatformError as e:
        raise HTTPException(400, str(e)) from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


def require_admin(request: Request):
    if not principal(request).is_admin:
        raise HTTPException(403, "só admins da plataforma")


def require_auditor(request: Request):
    if not principal(request).is_auditor:
        raise HTTPException(403, "só admins e auditores")
