"""Estado curto compartilhado entre réplicas da central (tabela `ephemeral` do banco).

Com uma réplica só, um dicionário em memória bastaria; com várias (Kubernetes, alta disponibilidade), um callback ou
um código de uso único pode chegar a qualquer uma delas. Tudo aqui é pequeno, tem validade e é limpo pelo agendador.
"""
import contextlib
import hashlib
import threading
from datetime import UTC, timedelta

from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError

from . import db as dbmod
from .models import Ephemeral, now

_local_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


def _alive(row: Ephemeral | None) -> bool:
    if row is None:
        return False
    exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
    return exp > now()


def put(key: str, value: dict, ttl_s: float):
    exp = now() + timedelta(seconds=ttl_s)
    with dbmod.SessionLocal() as s:
        row = s.get(Ephemeral, key)
        if row:
            row.value, row.expires_at = value, exp
        else:
            s.add(Ephemeral(key=key, value=value, expires_at=exp))
        s.commit()


def get(key: str) -> dict | None:
    with dbmod.SessionLocal() as s:
        row = s.get(Ephemeral, key)
        return dict(row.value or {}) if _alive(row) else None


def pop(key: str):
    with dbmod.SessionLocal() as s:
        s.execute(delete(Ephemeral).where(Ephemeral.key == key))
        s.commit()


def take_once(key: str, ttl_s: float) -> bool:
    """True só para a primeira chamada (de qualquer réplica) que reservar a chave: códigos de uso único."""
    with dbmod.SessionLocal() as s:
        old = s.get(Ephemeral, key)
        if old is not None:
            if _alive(old):
                return False
            s.delete(old)
            s.commit()
        s.add(Ephemeral(key=key, value={}, expires_at=now() + timedelta(seconds=ttl_s)))
        try:
            s.commit()
            return True
        except IntegrityError:
            s.rollback()
            return False


def hits(key: str, window_s: float, add: bool = False) -> int:
    """Contador em janela deslizante (tentativas de login): quantos eventos houve na janela, contando este se `add`."""
    t = now().timestamp()
    with dbmod.SessionLocal() as s:
        row = s.get(Ephemeral, key)
        times = [x for x in ((row.value or {}).get("t", []) if _alive(row) else []) if t - x < window_s]
        if add:
            times.append(t)
            exp = now() + timedelta(seconds=window_s)
            if row:
                row.value, row.expires_at = {"t": times}, exp
            else:
                s.add(Ephemeral(key=key, value={"t": times}, expires_at=exp))
            try:
                s.commit()
            except IntegrityError:  # outra réplica criou no mesmo instante; a próxima tentativa conta
                s.rollback()
        return len(times)


def sweep():
    """Apaga o que venceu (o agendador chama de tempos em tempos)."""
    with dbmod.SessionLocal() as s:
        s.execute(delete(Ephemeral).where(Ephemeral.expires_at < now()))
        s.commit()


def is_postgres() -> bool:
    return dbmod.engine.dialect.name == "postgresql"


def _lock_id(name: str) -> int:
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big", signed=True)


@contextlib.contextmanager
def cluster_lock(name: str):
    """Exclusão mútua entre réplicas (advisory lock do Postgres). No SQLite (uma réplica), um lock do processo."""
    with _guard:
        local = _local_locks.setdefault(name, threading.Lock())
    with local:
        if not is_postgres():
            yield
            return
        with dbmod.engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _lock_id(name)})
            try:
                yield
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _lock_id(name)})
                conn.commit()


# ------------------------------------------------------------------ réplicas vivas (heartbeat) e faxina
HEARTBEAT_S, HEARTBEAT_TTL_S, HOUSEKEEPING_S = 20, 75, 60
_hb_stop = threading.Event()


def replica_alive(replica_id: str) -> bool:
    return bool(replica_id) and get(f"replica:{replica_id}") is not None


def beat():
    from . import config
    put(f"replica:{config.REPLICA_ID}", {"version": config.VERSION}, HEARTBEAT_TTL_S)


def start_heartbeat(housekeeping=None):
    """Marca esta réplica como viva a cada 20 s e, a cada minuto, roda a faxina (idempotente entre réplicas)."""
    import logging
    import time
    log = logging.getLogger("hangar.cluster")
    _hb_stop.clear()
    beat()

    def loop():
        last = 0.0
        while not _hb_stop.wait(HEARTBEAT_S):
            try:
                beat()
                if time.monotonic() - last > HOUSEKEEPING_S:
                    last = time.monotonic()
                    sweep()
                    if housekeeping:
                        housekeeping()
            except Exception:
                log.exception("falha no heartbeat/faxina")
    threading.Thread(target=loop, name="heartbeat", daemon=True).start()


def stop_heartbeat():
    from . import config
    _hb_stop.set()
    try:
        pop(f"replica:{config.REPLICA_ID}")  # saída limpa: as outras réplicas não esperam o TTL
    except Exception:
        pass

