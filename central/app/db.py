"""Engine, sessão e migrações (Alembic) do banco da central."""
import logging
import os
import time

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from . import config, crypto

log = logging.getLogger("hangar.db")

_connect_args = {"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

BASELINE = "0001_baseline"
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _alembic_config() -> Config:
    cfg = Config(os.path.join(_HERE, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_HERE, "migrations"))
    cfg.set_main_option("sqlalchemy.url", config.DATABASE_URL.replace("%", "%%"))
    return cfg


def _wait_for_db(attempts=30):
    for _ in range(attempts):
        try:
            with engine.connect():
                return
        except OperationalError:
            time.sleep(1)
    raise RuntimeError("banco de dados indisponível")


def migrate():
    """Aplica as migrações. Bancos criados antes do Alembic (create_all) são "carimbados" no baseline —
    o schema deles é exatamente o do baseline — e seguem daí."""
    _wait_for_db()
    cfg = _alembic_config()
    tables = set(inspect(engine).get_table_names())
    if "agents" in tables and "alembic_version" not in tables:
        log.info("banco pré-Alembic detectado: marcando como %s", BASELINE)
        command.stamp(cfg, BASELINE)
    command.upgrade(cfg, "head")
    _encrypt_legacy_secrets()


def _encrypt_legacy_secrets():
    """Chaves de conexão salvas em texto puro por versões anteriores passam a ficar criptografadas."""
    from .models import LlmConnection

    with SessionLocal() as db:
        changed = 0
        for c in db.scalars(select(LlmConnection)):
            if c.api_key and not crypto.is_encrypted(c.api_key):
                c.api_key = crypto.encrypt(c.api_key)
                changed += 1
        if changed:
            db.commit()
            log.info("%d chave(s) de conexão migradas para armazenamento criptografado", changed)
