# -*- coding: utf-8 -*-
"""
tests/test_desktop_db_bootstrap.py — Banco do .exe: criar/migrar a cada início.

Cada teste usa um SQLite novo em tmp_path (DATABASE_URL via monkeypatch).
Não toca o banco de teste da suíte nem o %APPDATA% real.
"""

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from desktop import db_bootstrap, runtime

TABELAS_ESPERADAS = {
    "users",
    "empresas",
    "atividades",
    "diagnosticos",
    "empresa_historico",
    "auditoria_documentos",
    "auditoria_acessos",
    "alertas",
    "auditoria_tentativas_acesso",
}


@pytest.fixture
def banco(monkeypatch, tmp_path):
    caminho = tmp_path / "motor_tributario.db"
    monkeypatch.setenv(db_bootstrap.DB_URL_ENV, runtime.sqlite_url(caminho))
    return caminho


def _tabelas(caminho) -> set[str]:
    with sqlite3.connect(caminho) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _versao(caminho) -> list[str]:
    with sqlite3.connect(caminho) as conn:
        return [r[0] for r in conn.execute("SELECT version_num FROM alembic_version")]


def test_head_da_cadeia_existe():
    assert db_bootstrap.head_revision(runtime.alembic_dir()) is not None


def test_banco_novo_cria_tabelas_e_marca_head(banco):
    info = db_bootstrap.bootstrap_database(runtime.alembic_dir())
    head = db_bootstrap.head_revision(runtime.alembic_dir())
    assert info["acao"] == "create_all+stamp"
    assert info["revisao_antes"] is None
    assert info["revisao"] == head == info["head"]
    assert TABELAS_ESPERADAS <= _tabelas(banco)
    assert _versao(banco) == [head]


def test_segunda_execucao_faz_upgrade_sem_erro(banco):
    db_bootstrap.bootstrap_database(runtime.alembic_dir())
    info = db_bootstrap.bootstrap_database(runtime.alembic_dir())
    assert info["acao"] == "upgrade"
    assert info["revisao_antes"] == info["revisao"] == info["head"]
    assert _versao(banco) == [info["head"]]


def test_banco_sem_versao_com_dados_e_carimbado_sem_perder_linhas(banco):
    # Banco criado só por create_all (como o app fazia antes do .exe)
    db_bootstrap._create_all(os.environ[db_bootstrap.DB_URL_ENV])
    with sqlite3.connect(banco) as conn:
        conn.execute(
            "INSERT INTO auditoria_acessos (documento_id, acessado_por_user_id, ip, motivo, acessado_em) "
            "VALUES (1, 1, '127.0.0.1', 'motivo de teste longo', '2026-01-01T00:00:00')"
        )
    assert "alembic_version" not in _tabelas(banco)

    info = db_bootstrap.bootstrap_database(runtime.alembic_dir())
    assert info["acao"] == "create_all+stamp"
    with sqlite3.connect(banco) as conn:
        assert conn.execute("SELECT COUNT(*) FROM auditoria_acessos").fetchone()[0] == 1
    assert _versao(banco) == [info["head"]]


def test_sem_database_url_falha_alto(monkeypatch):
    monkeypatch.delenv(db_bootstrap.DB_URL_ENV, raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        db_bootstrap.bootstrap_database(runtime.alembic_dir())
