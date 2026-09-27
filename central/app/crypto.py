"""Criptografia em repouso dos segredos guardados no banco (api keys das conexões de LLM)."""
from cryptography.fernet import Fernet, InvalidToken

from . import config

PREFIX = "enc:v1:"


class SecretKeyMissing(RuntimeError):
    pass


def _fernet() -> Fernet:
    if not config.SECRET_KEY:
        raise SecretKeyMissing(
            "HANGAR_SECRET_KEY não definida. Gere com `python -c \"from cryptography.fernet import Fernet;"
            "print(Fernet.generate_key().decode())\"` (ou rode scripts/setup.sh) e coloque no .env.")
    return Fernet(config.SECRET_KEY.encode())


def check_key():
    """Falha cedo, no startup, em vez de na primeira conexão salva."""
    _fernet()


def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt(value: str) -> str:
    if not value or is_encrypted(value):
        return value or ""
    return PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Valores legados em texto puro (de antes da criptografia) passam direto — o startup os migra."""
    if not value:
        return ""
    if not is_encrypted(value):
        return value
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("Não foi possível decriptar um segredo: HANGAR_SECRET_KEY mudou?") from e
