"""
Alembic env.py — Motor Tributario Conect
Usa SQLModel metadata de database.py + auth.py para autogenerate.
DATABASE_URL lida do ambiente (mesma variavel do app).
"""
import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from alembic import context

# Adiciona PY/ ao path para imports do projeto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importa modelos para registrar no metadata do SQLModel
import database  # noqa: F401 — EmpresaDB, DiagnosticoDB, AlertaDB, etc.
import auth      # noqa: F401 — UserDB

config = context.config

# Logging do alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata unificado — SQLModel registra todas as tabelas aqui
target_metadata = SQLModel.metadata

# DATABASE_URL do ambiente (mesma do database.py e auth.py)
_db_url = os.environ.get("DATABASE_URL", "sqlite:///motor_tributario.db")
config.set_main_option("sqlalchemy.url", _db_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite nao suporta ALTER TABLE — batch mode
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite batch mode
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
