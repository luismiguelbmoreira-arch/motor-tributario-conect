# -*- coding: utf-8 -*-
"""
test_alembic_baseline.py — a cadeia Alembic chega ao schema dos models.

1. Banco vazio → `upgrade head` → schema igual aos models (sem tabela,
   coluna, índice ou FK faltando).
2. Banco criado por `create_all` e carimbado em 49832cc28f45 (estado dos
   bancos existentes) → `upgrade head` não quebra e não perde linha.
3. `atividades` no formato antigo com dados → vira `atividades_legado`,
   nada é apagado.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlmodel import SQLModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import auth  # noqa: E402,F401 — registra UserDB no metadata
import database  # noqa: E402,F401 — registra os demais models

PY = Path(__file__).resolve().parent.parent
HEAD = "a1c3e5f7b9d2"
ANTES = "49832cc28f45"

# Diferenças só de tipo/nullable não são criadas nem corrigidas pela revisão
# (ver docstring de a1c3e5f7b9d2). O que importa: nada faltando ou sobrando.
_DIFS_IGNORADAS = {"modify_type", "modify_nullable", "modify_default"}


def _cfg() -> Config:
    # Sem alembic.ini: evita o fileConfig, que mexe nos loggers da suíte.
    cfg = Config()
    cfg.set_main_option("script_location", str(PY / "alembic"))
    return cfg


@pytest.fixture(name="db_url")
def db_url_fixture(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'alembic_teste.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    return url


def _diferencas(url: str) -> list:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            difs = compare_metadata(ctx, SQLModel.metadata)
    finally:
        engine.dispose()
    planas = []
    for d in difs:
        # modify_* vem como lista de tuplas; add/remove vem como tupla.
        itens = d if isinstance(d, list) else [d]
        planas.extend(i for i in itens if i[0] not in _DIFS_IGNORADAS)
    return planas


def _versao(url: str) -> str:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def test_banco_vazio_chega_ao_schema_dos_models(db_url):
    command.upgrade(_cfg(), "head")

    assert _versao(db_url) == HEAD
    assert _diferencas(db_url) == []


def test_banco_create_all_carimbado_sobe_sem_perder_linha(db_url):
    engine = sa.create_engine(db_url)
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO users (username, email, hashed_password, role, ativo,"
            " must_change_password, created_at, tema, notificacoes_email)"
            " VALUES ('ana', 'ana@teste.local', 'x', 'admin', 1, 1,"
            " '2026-01-01T00:00:00', 'auto', 1)"
        ))
    engine.dispose()
    command.stamp(_cfg(), ANTES)

    command.upgrade(_cfg(), "head")

    assert _versao(db_url) == HEAD
    assert _diferencas(db_url) == []
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            nomes = conn.execute(sa.text("SELECT username FROM users")).scalars().all()
    finally:
        engine.dispose()
    assert nomes == ["ana"]


def test_atividades_antiga_com_dados_vira_legado(db_url):
    command.upgrade(_cfg(), ANTES)
    engine = sa.create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(sa.text(
            "INSERT INTO empresas (id, cnpj, razao_social, regime, cnae_principal,"
            " uf_origem, faturamento_12m, created_at, updated_at)"
            " VALUES (1, '00.000.000/0001-00', 'Teste', 'SIMPLES', '6201-5/01',"
            " 'SP', '0', '2026-01-01', '2026-01-01')"
        ))
        conn.execute(sa.text(
            "INSERT INTO atividades (empresa_id, competencia, receita, anexo,"
            " icms_st, iss_retido, created_at)"
            " VALUES (1, '2026-01', '0', 'III', 0, 0, '2026-01-01')"
        ))
    engine.dispose()

    command.upgrade(_cfg(), "head")

    # Só sobra a tabela legado, que não está nos models.
    difs = [(d[0], d[1].name) for d in _diferencas(db_url)]
    assert difs == [("remove_table", "atividades_legado")]
    engine = sa.create_engine(db_url)
    try:
        with engine.connect() as conn:
            legado = conn.execute(sa.text("SELECT COUNT(*) FROM atividades_legado")).scalar()
            novas = conn.execute(sa.text("SELECT COUNT(*) FROM atividades")).scalar()
    finally:
        engine.dispose()
    assert legado == 1
    assert novas == 0
