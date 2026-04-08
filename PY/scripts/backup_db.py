#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backup_db.py — Backup automático do DB SQLite do Motor Tributário Conect.

Motivo (gap P0 #1):
  Os metadados cifrados em `auditoria_documentos` são INÚTEIS sem o DB.
  Perda do banco = impossibilidade de gerar dossiê de prova mesmo com os
  arquivos cifrados AES-256-GCM intactos em disco. Backup diário é
  obrigatório para compliance LGPD + CTN Art. 173 (5 anos de retenção).

Comportamento:
  1. Copia `data/motor_tributario.db` → `data/backups/diarios/YYYY-MM-DD.db.gz`
  2. No primeiro dia do mês, copia também para `data/backups/mensais/YYYY-MM.db.gz`
  3. Retenção:
     - Diários: 30 dias rolling (remove os que passaram)
     - Mensais: permanente (até decisão manual de purge)
  4. Usa SQLite `.backup` API via sqlite3.Connection.backup() para garantir
     consistência transacional — nunca `cp` direto (corrompe se houver write ativo)
  5. Comprime com gzip level 9 (DB fiscal compacta bem, ~4-6x menor)
  6. Retorna exit code 0 se OK, 1 se falhar — integrável em cron/Task Scheduler

Uso:
    python PY/scripts/backup_db.py                       # backup padrão
    python PY/scripts/backup_db.py --dry-run             # só mostra o que faria
    python PY/scripts/backup_db.py --db /caminho/alt.db  # override do DB path

Deploy em produção:
    Linux  (cron):           0 3 * * * cd /app && python PY/scripts/backup_db.py
    Windows (Task Scheduler): schtasks /Create /SC DAILY /ST 03:00 /TN MotorBackup ...

Base legal do backup:
  - CTN Art. 173 — decadência fiscal de 5 anos (dados precisam sobreviver)
  - LGPD Art. 46 — medidas técnicas de segurança
  - CFC NBC TG 1000 — manutenção de documentação fiscal
"""
from __future__ import annotations

import argparse
import gzip
import logging
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("motor_conect.backup_db")

# Layout padrão (sobrescrível via env/CLI)
ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "data" / "motor_tributario.db"
DEFAULT_BACKUP_ROOT = ROOT / "data" / "backups"
DIARIOS_DIR = "diarios"
MENSAIS_DIR = "mensais"
RETENCAO_DIARIOS_DIAS = 30
GZIP_LEVEL = 9


class BackupError(Exception):
    """Erro genérico do backup."""


def _sqlite_backup(origem: Path, destino_tmp: Path) -> None:
    """
    Copia o DB usando sqlite3.Connection.backup() — transação-safe.

    Não usa shutil.copy() porque, se houver uma escrita em andamento,
    o arquivo copiado pode ficar corrompido. A API `backup` do SQLite
    faz a cópia com locks corretos.
    """
    source = sqlite3.connect(str(origem))
    try:
        dest = sqlite3.connect(str(destino_tmp))
        try:
            source.backup(dest)
        finally:
            dest.close()
    finally:
        source.close()


def _comprimir_gzip(origem: Path, destino_gz: Path) -> int:
    """
    Comprime `origem` em `destino_gz` usando gzip nível 9.
    Retorna o tamanho final em bytes.
    """
    with origem.open("rb") as f_in, gzip.open(
        str(destino_gz), "wb", compresslevel=GZIP_LEVEL
    ) as f_out:
        shutil.copyfileobj(f_in, f_out)
    return destino_gz.stat().st_size


def _limpar_diarios_antigos(diretorio: Path, manter_dias: int) -> int:
    """
    Remove backups diários com mais de `manter_dias`.
    Retorna quantos foram removidos.
    """
    if not diretorio.exists():
        return 0
    limite = datetime.now() - timedelta(days=manter_dias)
    removidos = 0
    for arq in diretorio.glob("*.db.gz"):
        try:
            mtime = datetime.fromtimestamp(arq.stat().st_mtime)
            if mtime < limite:
                arq.unlink()
                logger.info("Diario antigo removido: %s", arq.name)
                removidos += 1
        except OSError as exc:
            logger.warning("Nao foi possivel remover %s: %s", arq.name, exc)
    return removidos


def fazer_backup(
    db_path: Path = DEFAULT_DB,
    backup_root: Path = DEFAULT_BACKUP_ROOT,
    dry_run: bool = False,
    referencia: datetime | None = None,
) -> dict:
    """
    Executa o backup diário + eventual mensal.

    Args:
        db_path: caminho do DB SQLite fonte
        backup_root: pasta raiz dos backups (diarios/ e mensais/)
        dry_run: se True, não grava nada, só mostra o plano
        referencia: datetime usado para nomear os arquivos (default: now())

    Returns:
        dict com: {
            "db_origem": str,
            "diario": str | None,
            "mensal": str | None,
            "tamanho_diario": int,
            "tamanho_mensal": int,
            "diarios_removidos": int,
            "dry_run": bool,
        }

    Raises:
        BackupError: se o DB de origem nao existir ou falha de I/O.
    """
    ref = referencia or datetime.now()

    if not db_path.exists():
        raise BackupError(f"DB de origem nao encontrado: {db_path}")
    if db_path.stat().st_size == 0:
        raise BackupError(f"DB de origem esta vazio: {db_path}")

    diarios_dir = backup_root / DIARIOS_DIR
    mensais_dir = backup_root / MENSAIS_DIR

    nome_diario = f"{ref.strftime('%Y-%m-%d')}.db.gz"
    nome_mensal = f"{ref.strftime('%Y-%m')}.db.gz"
    eh_primeiro_dia_mes = ref.day == 1

    resultado = {
        "db_origem": str(db_path),
        "diario": None,
        "mensal": None,
        "tamanho_diario": 0,
        "tamanho_mensal": 0,
        "diarios_removidos": 0,
        "dry_run": dry_run,
    }

    if dry_run:
        logger.info("[DRY-RUN] Criaria diario: %s/%s", diarios_dir, nome_diario)
        if eh_primeiro_dia_mes:
            logger.info("[DRY-RUN] Criaria mensal: %s/%s", mensais_dir, nome_mensal)
        logger.info("[DRY-RUN] Removeria diarios > %d dias", RETENCAO_DIARIOS_DIAS)
        return resultado

    # Garante diretórios
    diarios_dir.mkdir(parents=True, exist_ok=True)
    if eh_primeiro_dia_mes:
        mensais_dir.mkdir(parents=True, exist_ok=True)

    # Backup transação-safe: SQLite .backup() → arquivo tmp → gzip → rename atomico
    tmp_db = diarios_dir / f".{nome_diario}.tmp"
    tmp_gz = diarios_dir / f".{nome_diario}.gz.tmp"
    diario_final = diarios_dir / nome_diario

    try:
        _sqlite_backup(db_path, tmp_db)
        tamanho_diario = _comprimir_gzip(tmp_db, tmp_gz)
        tmp_gz.replace(diario_final)
        tmp_db.unlink(missing_ok=True)
    except Exception as exc:
        # Limpeza em caso de erro
        tmp_db.unlink(missing_ok=True)
        tmp_gz.unlink(missing_ok=True)
        raise BackupError(f"Falha no backup diario: {exc}") from exc

    resultado["diario"] = str(diario_final)
    resultado["tamanho_diario"] = tamanho_diario
    logger.info(
        "Backup diario OK | %s | %d bytes",
        diario_final.name, tamanho_diario,
    )

    # Backup mensal adicional no dia 1
    if eh_primeiro_dia_mes:
        mensal_final = mensais_dir / nome_mensal
        try:
            # Reusa o .gz que acabamos de criar — só copia
            shutil.copy2(diario_final, mensal_final)
            resultado["mensal"] = str(mensal_final)
            resultado["tamanho_mensal"] = mensal_final.stat().st_size
            logger.info("Backup mensal OK | %s", mensal_final.name)
        except OSError as exc:
            logger.warning("Falha ao criar backup mensal: %s", exc)

    # Retenção: remove diários antigos
    resultado["diarios_removidos"] = _limpar_diarios_antigos(
        diarios_dir, RETENCAO_DIARIOS_DIAS
    )

    return resultado


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Backup automatico do DB SQLite do Motor Tributario Conect"
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"Caminho do DB (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=DEFAULT_BACKUP_ROOT,
        help=f"Pasta raiz dos backups (default: {DEFAULT_BACKUP_ROOT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Nao grava nada, so mostra o plano",
    )
    args = parser.parse_args()

    try:
        resultado = fazer_backup(
            db_path=args.db,
            backup_root=args.backup_root,
            dry_run=args.dry_run,
        )
    except BackupError as exc:
        logger.error("BACKUP FALHOU: %s", exc)
        return 1

    # Saída resumida para log do cron
    if resultado["dry_run"]:
        print("[DRY-RUN] Backup simulado OK")
    else:
        print(
            f"Backup OK | diario={resultado['tamanho_diario']}b"
            + (f" | mensal={resultado['tamanho_mensal']}b" if resultado["mensal"] else "")
            + f" | removidos={resultado['diarios_removidos']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
