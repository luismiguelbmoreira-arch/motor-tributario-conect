#!/usr/bin/env python3
"""
Hook PreToolUse: bloqueia Edit/Write em arquivos FROZEN do Motor Tributario Conect.

Protocolo Claude Code hooks: recebe JSON no stdin com tool_input.file_path.
Exit codes:
  0 -> permitido
  2 -> BLOQUEADO (Claude Code mostra stderr ao usuario e aborta a tool call)

A lista FROZEN espelha:
- CLAUDE.md secao "Arquivos NAO tocados (garantia de estabilidade)"
- MAX_FISCAL: tabelas legais nao podem ser alteradas sem ritual
- RFC rollback: cifragem e schema sao inegociaveis

Para permitir edicao temporaria de um caminho FROZEN, remova a entrada deste
arquivo, execute a mudanca, e recoloque. Isso deixa rastro no git.
"""
from __future__ import annotations

import json
import sys
from pathlib import PurePosixPath

# Chave: substring a casar no path normalizado (forward-slash)
# Valor: (motivo curto, quem aprova)
FROZEN: dict[str, tuple[str, str]] = {
    "PY/tabelas_simples.py": (
        "FROZEN - tabelas legais do Simples Nacional (MAX_FISCAL)",
        "Luiz Moreira",
    ),
    "PY/database.py": (
        "schema intocado por politica Akita (risco de migracao)",
        "O Chefe",
    ),
    "PY/storage_cifrado.py": (
        "cifragem AES-GCM + HKDF - perda = PDFs irrecuperaveis",
        "O Viciado",
    ),
    "PY/regimes/base.py": (
        "Guard Clause central - remover quebra CI",
        "O Viciado",
    ),
    "PY/regimes/lucro_presumido.py": (
        "engine Lucro Presumido certificado",
        "Luiz Moreira",
    ),
    "PY/regimes/mei.py": (
        "engine MEI certificado",
        "Luiz Moreira",
    ),
    "/.env": (
        "segredos - contem MOTOR_CONECT_MASTER_KEY",
        "Humano (fora do agente)",
    ),
}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # sem payload valido, nao bloqueia

    tool_input = payload.get("tool_input") or {}
    raw_path = tool_input.get("file_path") or ""
    if not raw_path:
        return 0

    norm_path = PurePosixPath(raw_path.replace("\\", "/"))
    norm = str(norm_path)
    basename = norm_path.name

    for needle, (motivo, aprovador) in FROZEN.items():
        needle_base = needle.lstrip("/")
        # endswith cobre paths absolutos; `in` cobre sub-caminhos;
        # basename cobre arquivos na raiz (ex: .env)
        if norm.endswith(needle) or needle in norm or basename == needle_base:
            print(
                f"BLOQUEADO: {needle} e FROZEN.\n"
                f"Motivo: {motivo}.\n"
                f"Aprovador: {aprovador}.\n"
                f"Se for realmente necessario editar, remova temporariamente este "
                f"caminho de .claude/hooks/block_frozen.py::FROZEN.",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
