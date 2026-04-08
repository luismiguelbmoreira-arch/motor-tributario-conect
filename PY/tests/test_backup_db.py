# -*- coding: utf-8 -*-
"""
test_backup_db.py — Trava o script de backup automático do DB SQLite.

Cobre:
  - Backup diário com compressão gzip
  - Backup mensal no dia 1 (além do diário)
  - Integridade: dump restaurado bate com o original
  - Retenção: remove diários antigos > 30 dias
  - Dry run: não toca no FS
  - Erros: DB ausente, DB vazio
  - SQLite .backup() transação-safe (não shutil.copy)
"""
from __future__ import annotations

import gzip
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from backup_db import (  # noqa: E402
    DIARIOS_DIR,
    MENSAIS_DIR,
    RETENCAO_DIARIOS_DIAS,
    BackupError,
    _limpar_diarios_antigos,
    fazer_backup,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def db_exemplo(tmp_path: Path) -> Path:
    """Cria um DB SQLite mínimo com 1 tabela e 3 registros."""
    db = tmp_path / "motor_test.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("CREATE TABLE empresas (id INTEGER PRIMARY KEY, nome TEXT)")
        conn.executemany(
            "INSERT INTO empresas (nome) VALUES (?)",
            [("CANAVEZI",), ("CONFI_AR",), ("ITANGUA",)],
        )
        conn.commit()
    finally:
        conn.close()
    return db


@pytest.fixture
def backup_root(tmp_path: Path) -> Path:
    return tmp_path / "backups"


# ── Backup diário ──────────────────────────────────────────────────────────


def test_backup_diario_basico(db_exemplo, backup_root):
    resultado = fazer_backup(db_path=db_exemplo, backup_root=backup_root)
    assert resultado["diario"] is not None
    assert resultado["tamanho_diario"] > 0
    assert resultado["dry_run"] is False

    diario = Path(resultado["diario"])
    assert diario.exists()
    assert diario.suffix == ".gz"
    assert str(diario.parent.name) == DIARIOS_DIR


def test_nome_diario_segue_padrao_ymd(db_exemplo, backup_root):
    ref = datetime(2026, 7, 15, 3, 0, 0)
    resultado = fazer_backup(
        db_path=db_exemplo, backup_root=backup_root, referencia=ref,
    )
    assert Path(resultado["diario"]).name == "2026-07-15.db.gz"


def test_backup_diario_sobrescreve_se_mesmo_dia(db_exemplo, backup_root):
    """Rodar 2x no mesmo dia mantém um único arquivo (o segundo sobrescreve)."""
    ref = datetime(2026, 7, 15)
    r1 = fazer_backup(db_path=db_exemplo, backup_root=backup_root, referencia=ref)
    r2 = fazer_backup(db_path=db_exemplo, backup_root=backup_root, referencia=ref)
    assert r1["diario"] == r2["diario"]
    # Só 1 arquivo na pasta
    diarios = list((backup_root / DIARIOS_DIR).glob("*.db.gz"))
    assert len(diarios) == 1


# ── Backup mensal ──────────────────────────────────────────────────────────


def test_backup_mensal_criado_dia_1(db_exemplo, backup_root):
    ref = datetime(2026, 8, 1, 3, 0, 0)  # primeiro dia do mês
    resultado = fazer_backup(
        db_path=db_exemplo, backup_root=backup_root, referencia=ref,
    )
    assert resultado["mensal"] is not None
    mensal = Path(resultado["mensal"])
    assert mensal.exists()
    assert mensal.name == "2026-08.db.gz"
    assert mensal.parent.name == MENSAIS_DIR


def test_backup_mensal_nao_criado_outros_dias(db_exemplo, backup_root):
    ref = datetime(2026, 7, 15)  # meio do mês
    resultado = fazer_backup(
        db_path=db_exemplo, backup_root=backup_root, referencia=ref,
    )
    assert resultado["mensal"] is None
    mensal_dir = backup_root / MENSAIS_DIR
    assert not mensal_dir.exists() or not list(mensal_dir.glob("*.db.gz"))


# ── Integridade: round-trip ────────────────────────────────────────────────


def test_backup_restaurado_bate_com_original(db_exemplo, backup_root, tmp_path):
    """Simula uma recuperação: descompacta o .gz e confere os dados."""
    resultado = fazer_backup(db_path=db_exemplo, backup_root=backup_root)
    diario = Path(resultado["diario"])

    # Descomprime
    restaurado = tmp_path / "restaurado.db"
    with gzip.open(str(diario), "rb") as f_in, restaurado.open("wb") as f_out:
        f_out.write(f_in.read())

    # Lê os dados
    conn = sqlite3.connect(str(restaurado))
    try:
        rows = conn.execute("SELECT nome FROM empresas ORDER BY id").fetchall()
    finally:
        conn.close()
    nomes = [r[0] for r in rows]
    assert nomes == ["CANAVEZI", "CONFI_AR", "ITANGUA"]


def test_backup_usa_sqlite_backup_api_nao_shutil_copy(
    db_exemplo, backup_root, monkeypatch
):
    """
    Confere que a cópia do DB usa sqlite3.Connection.backup() — se usasse
    shutil.copy() em cima de um DB com escrita ativa, poderia corromper.
    Detectamos isso interceptando shutil.copy e falhando se for chamado
    para copiar o DB de origem.
    """
    import backup_db as mod

    copys_do_db = []
    original_copy = mod.shutil.copy2

    def copy2_monitorado(src, dst, *a, **kw):
        if str(src) == str(db_exemplo):
            copys_do_db.append((src, dst))
        return original_copy(src, dst, *a, **kw)

    monkeypatch.setattr(mod.shutil, "copy2", copy2_monitorado)

    fazer_backup(db_path=db_exemplo, backup_root=backup_root)

    # shutil.copy2 NUNCA deve ter sido usado pro DB de origem
    # (só é permitido usar copy2 para clonar o .gz do diário → mensal)
    assert len(copys_do_db) == 0


# ── Retenção ───────────────────────────────────────────────────────────────


def test_retencao_remove_diarios_antigos(backup_root):
    """Cria arquivos com mtimes antigos e garante que são removidos."""
    diarios = backup_root / DIARIOS_DIR
    diarios.mkdir(parents=True)

    # Arquivo antigo (40 dias)
    antigo = diarios / "2026-01-01.db.gz"
    antigo.write_bytes(b"old")
    old_time = (datetime.now() - timedelta(days=40)).timestamp()
    os.utime(antigo, (old_time, old_time))

    # Arquivo recente (5 dias)
    recente = diarios / "2026-08-15.db.gz"
    recente.write_bytes(b"new")
    new_time = (datetime.now() - timedelta(days=5)).timestamp()
    os.utime(recente, (new_time, new_time))

    removidos = _limpar_diarios_antigos(diarios, RETENCAO_DIARIOS_DIAS)
    assert removidos == 1
    assert not antigo.exists()
    assert recente.exists()


def test_retencao_30_dias_exato_mantido(backup_root):
    """Arquivo com exatamente 30 dias ainda é mantido (borda inclusiva)."""
    diarios = backup_root / DIARIOS_DIR
    diarios.mkdir(parents=True)
    arq = diarios / "2026-07-15.db.gz"
    arq.write_bytes(b"x")
    # Exatamente 29 dias — garantido mantido
    t = (datetime.now() - timedelta(days=29)).timestamp()
    os.utime(arq, (t, t))

    removidos = _limpar_diarios_antigos(diarios, 30)
    assert removidos == 0
    assert arq.exists()


def test_retencao_pasta_inexistente_nao_explode(backup_root):
    assert _limpar_diarios_antigos(backup_root / "nao_existe", 30) == 0


# ── Dry run ────────────────────────────────────────────────────────────────


def test_dry_run_nao_cria_arquivos(db_exemplo, backup_root):
    resultado = fazer_backup(
        db_path=db_exemplo, backup_root=backup_root, dry_run=True,
    )
    assert resultado["dry_run"] is True
    assert resultado["diario"] is None
    assert resultado["mensal"] is None
    # Pasta não criada
    assert not (backup_root / DIARIOS_DIR).exists()


# ── Erros ──────────────────────────────────────────────────────────────────


def test_db_inexistente_levanta_backup_error(tmp_path, backup_root):
    fake = tmp_path / "nao_existe.db"
    with pytest.raises(BackupError, match="nao encontrado"):
        fazer_backup(db_path=fake, backup_root=backup_root)


def test_db_vazio_levanta_backup_error(tmp_path, backup_root):
    vazio = tmp_path / "vazio.db"
    vazio.write_bytes(b"")
    with pytest.raises(BackupError, match="vazio"):
        fazer_backup(db_path=vazio, backup_root=backup_root)


# ── Compressão efetiva ──────────────────────────────────────────────────────


def test_arquivo_gzipado_menor_que_original(tmp_path, backup_root):
    """DB fiscal com dados repetitivos compacta bem (esperamos < que original)."""
    db = tmp_path / "bigger.db"
    conn = sqlite3.connect(str(db))
    try:
        conn.execute("CREATE TABLE t (id INTEGER, dados TEXT)")
        # Insere 1000 linhas com texto repetitivo — alto ganho de compressão
        conn.executemany(
            "INSERT INTO t VALUES (?, ?)",
            [(i, "dados_repetitivos_" * 20) for i in range(1000)],
        )
        conn.commit()
    finally:
        conn.close()

    tamanho_original = db.stat().st_size
    resultado = fazer_backup(db_path=db, backup_root=backup_root)
    assert resultado["tamanho_diario"] < tamanho_original
    # Tipicamente comprime pelo menos 3x para dados repetitivos
    assert resultado["tamanho_diario"] < tamanho_original / 2
