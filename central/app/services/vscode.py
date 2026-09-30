"""Login da extensão Agent Hangar do VS Code, plug and play e sem colar chave.

1. A extensão gera um verifier (PKCE) e abre no navegador `/app/#/vscode?challenge=…&state=…&device=…`.
2. A pessoa, já logada no portal (SSO ou conta local), confirma: `authorize` devolve um código assinado, de uso único,
   válido por 5 minutos, amarrado ao challenge e ao usuário. O portal manda o navegador para
   `vscode://agent-hangar.agent-hangar/auth?code=…&state=…`.
3. A extensão troca o código + verifier por um token pessoal (escopo user, marcado como cliente vscode-ext) em
   `/api/auth/vscode/token`. Sem o verifier, o código não vale nada — interceptar o redirect não basta.
O token age como a pessoa (times e papéis dela), aparece em "Minhas chaves" e é revogado quando ela sai da extensão
ou perde o acesso.
"""
import base64
import hashlib
import re
import secrets
import threading
import time

from sqlalchemy.orm import Session

from .. import auth, sso
from ..models import User
from .access import Access, Forbidden
from .common import PlatformError, audit

CODE_TTL_S = 300
CLIENT = "vscode-ext"
_USED: dict[str, float] = {}  # jti -> expiração (uso único; o código já expira sozinho em 5 min)
_LOCK = threading.Lock()


def _device(name: str) -> str:
    return re.sub(r"[^\w .@-]", "", name or "")[:60].strip() or "VS Code"


def authorize(acc: Access, challenge: str, state: str, device: str = "") -> dict:
    if not acc.p.is_user or not acc.p.user_id:
        raise Forbidden("entre com a sua conta (SSO ou usuário e senha) para conectar o VS Code")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", challenge or "") or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", state or ""):
        raise PlatformError("pedido de conexão inválido — comece de novo pelo VS Code")
    code = sso.sign_state({"u": acc.p.user_id, "c": challenge, "d": _device(device), "j": secrets.token_urlsafe(12),
                           "t": int(time.time()), "k": "vscode"})
    return {"code": code, "state": state, "redirect": "vscode://agent-hangar.agent-hangar/auth"}


def exchange(db: Session, code: str, verifier: str) -> dict:
    try:
        data = sso.read_state(code or "", max_age=CODE_TTL_S)
    except sso.AuthError as e:
        raise PlatformError(str(e)) from None
    if data.get("k") != "vscode":
        raise PlatformError("código inválido")
    expected = base64.urlsafe_b64encode(hashlib.sha256((verifier or "").encode()).digest()).decode().rstrip("=")
    if not secrets.compare_digest(expected, data.get("c", "")):
        raise PlatformError("verificação PKCE falhou — comece de novo pelo VS Code")
    now = time.time()
    with _LOCK:
        for j in [j for j, exp in _USED.items() if exp < now]:
            _USED.pop(j, None)
        if data["j"] in _USED:
            raise PlatformError("este código já foi usado — comece de novo pelo VS Code")
        _USED[data["j"]] = now + CODE_TTL_S
    u = db.get(User, data["u"])
    if not u or not u.active:
        raise PlatformError("usuário inativo")
    row, raw = auth.create_api_key(db, f"VS Code · {data['d']}", ["user"], [], u.email, client=CLIENT, user_id=u.id)
    audit(db, u.email, "vscode.connect", data["d"], f"chave #{row.id}")
    return {"token": raw, "key_id": row.id, "user": {"name": u.name, "email": u.email}}
