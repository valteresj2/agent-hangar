"""Autenticação e autorização.

Três tipos de credencial, cada uma com um alcance mínimo:
- ADMIN_TOKEN (bootstrap) e chaves de API com escopo "admin": administram tudo (/api, /mcp, /gw).
- Chaves de API com escopo "invoke": só chamam agentes pelo gateway /gw (opcionalmente só alguns slugs).
  É esta que vai para LibreChat, Slack, OpenCode… — nunca a de admin.
- Token interno por agente (HMAC do slug): o container de um agente só consegue se identificar como ele
  mesmo, e a central só deixa chamar os sub_agents dele (e o dashboard, se a tool estiver na spec).
"""
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import ApiKey, now

KEY_PREFIX = "ah_"
SCOPES = ("admin", "invoke")


@dataclass
class Principal:
    name: str
    scopes: set = field(default_factory=set)
    agents: list = field(default_factory=list)  # vazio = todos (para o escopo invoke)

    @property
    def is_admin(self) -> bool:
        return "admin" in self.scopes

    def can_invoke(self, slug: str) -> bool:
        if self.is_admin:
            return True
        return "invoke" in self.scopes and (not self.agents or slug in self.agents)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_api_key(db: Session, name: str, scopes: list[str], agents: list[str] | None = None,
                   actor: str = "admin") -> tuple[ApiKey, str]:
    """Devolve (registro, valor em texto) — o valor só existe aqui; no banco fica apenas o hash."""
    bad = [s for s in scopes if s not in SCOPES]
    if not scopes or bad:
        raise ValueError(f"scopes inválidos: {bad or scopes}. Opções: {list(SCOPES)}")
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    row = ApiKey(name=name, prefix=raw[:11], key_hash=hash_key(raw), scopes=sorted(set(scopes)),
                 agents=sorted(set(agents or [])), created_by=actor)
    db.add(row)
    db.commit()
    _CACHE.clear()
    return row, raw


def revoke_api_key(db: Session, key_id: int):
    row = db.get(ApiKey, key_id)
    if not row:
        raise ValueError(f"chave {key_id} não encontrada")
    row.revoked_at = now()
    db.commit()
    _CACHE.clear()


def api_key_dict(k: ApiKey) -> dict:
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "scopes": k.scopes, "agents": k.agents,
            "created_by": k.created_by, "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "revoked": k.revoked_at is not None}


# Cache curto: evita um SELECT por request no gateway. Revogação limpa o cache.
_CACHE: dict[str, tuple[float, Principal | None]] = {}
_TTL = 30.0


def authenticate(db: Session, token: str) -> Principal | None:
    if not token:
        return None
    if config.ADMIN_TOKEN and hmac.compare_digest(token, config.ADMIN_TOKEN):
        return Principal("admin-token", {"admin"})
    if not token.startswith(KEY_PREFIX):
        return None
    h = hash_key(token)
    hit = _CACHE.get(h)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    row = db.scalar(select(ApiKey).where(ApiKey.key_hash == h))
    principal = None
    if row and row.revoked_at is None:
        principal = Principal(f"key:{row.name}", set(row.scopes or []), list(row.agents or []))
        row.last_used_at = now()
        db.commit()
    _CACHE[h] = (time.monotonic(), principal)
    return principal


def token_from_headers(headers: dict) -> str:
    return headers.get("x-api-key") or headers.get("authorization", "").removeprefix("Bearer ").strip()


# ------------------------------------------------------------------ tokens internos (agente -> central)
def agent_token(slug: str) -> str:
    if not config.INTERNAL_SECRET:
        raise RuntimeError("INTERNAL_SECRET não definido")
    return hmac.new(config.INTERNAL_SECRET.encode(), f"agent:{slug}".encode(), hashlib.sha256).hexdigest()


def verify_agent_token(slug: str, token: str) -> bool:
    return bool(slug and token and config.INTERNAL_SECRET) and hmac.compare_digest(agent_token(slug), token)
