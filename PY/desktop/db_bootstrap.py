# -*- coding: utf-8 -*-
"""
desktop/db_bootstrap.py — Banco SQLite do .exe: criar/migrar a cada início.

Regra (roda antes de importar `main`):
  - banco SEM linha em `alembic_version` (novo, ou criado só por create_all):
        SQLModel.metadata.create_all  →  alembic stamp head
  - banco COM `alembic_version`:
        alembic upgrade head

Por que não `upgrade head` direto num banco vazio: a cadeia em `alembic/versions`
não cria o schema atual do zero (a 1ª migration usa `sqlmodel` sem importar, a
`users` nunca é criada por migration e `atividades` diverge dos modelos). O app
sempre dependeu de `create_all`. Os modelos são a fonte do schema; o Alembic
passa a cuidar só das mudanças daqui pra frente.

`alembic/env.py` lê `DATABASE_URL` do ambiente (não do Config). Por isso este
módulo também lê de lá — uma URL só.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

DB_URL_ENV = "DATABASE_URL"


def alembic_config(script_location: Path, url: str):
    """Config do Alembic sem `alembic.ini`.

    Sem ini, `env.py` não chama `fileConfig()` — que desligaria os loggers do app
    (`disable_existing_loggers=True`).
    """
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(script_location))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def head_revision(script_location: Path) -> Optional[str]:
    from alembic.script import ScriptDirectory

    return ScriptDirectory(str(script_location)).get_current_head()


def current_revision(url: str) -> Optional[str]:
    """Revisão gravada no banco (None se não houver `alembic_version` ou linha)."""
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def _create_all(url: str) -> None:
    from sqlalchemy import create_engine
    from sqlmodel import SQLModel

    import auth  # noqa: F401 — registra UserDB no metadata
    import database  # noqa: F401 — registra os demais modelos

    engine = create_engine(url, connect_args={"check_same_thread": False})
    try:
        SQLModel.metadata.create_all(engine)
    finally:
        engine.dispose()


def bootstrap_database(script_location: Path) -> dict:
    """Garante o schema e a revisão Alembic. Devolve um resumo para log/smoke.

    Lê a URL só de `os.environ` — o mesmo lugar que `alembic/env.py` lê. Um
    parâmetro separado deixaria create_all e stamp/upgrade em bancos diferentes.
    """
    from alembic import command

    url = os.environ.get(DB_URL_ENV)
    if not url:
        raise RuntimeError(f"{DB_URL_ENV} não definida antes do bootstrap do banco")

    cfg = alembic_config(script_location, url)
    antes = current_revision(url)
    if antes is None:
        _create_all(url)
        command.stamp(cfg, "head")
        acao = "create_all+stamp"
    else:
        command.upgrade(cfg, "head")
        acao = "upgrade"

    depois = current_revision(url)
    return {"acao": acao, "revisao_antes": antes, "revisao": depois, "head": head_revision(script_location)}
