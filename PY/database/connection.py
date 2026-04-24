import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

logger = logging.getLogger("motor_conect.database")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///" + str(Path(__file__).resolve().parent.parent.parent / "data" / "motor_tributario.db"),
)

# SQLite: ativar PRAGMA strict e WAL mode na conexão
@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_conn: Any, connection_record: Any) -> None:
    """Ativa strict mode e WAL no SQLite."""
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA busy_timeout=5000;")
    except Exception as e:
        logger.warning("[database] PRAGMA setup ignorado: %s", e)
    finally:
        cursor.close()

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

def criar_tabelas() -> None:
    """Cria tabelas se DB_SKIP_INIT não estiver setado."""
    if os.environ.get("DB_SKIP_INIT") == "1":
        logger.info("Pulo inicialização automática do banco (DB_SKIP_INIT=1).")
        return

    SQLModel.metadata.create_all(engine)
    logger.info("Tabelas verificadas.")

def get_session() -> Session:
    """Retorna uma nova sessão do banco."""
    return Session(engine)
