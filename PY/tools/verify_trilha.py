"""
verify_trilha — CLI de verificação de integridade HMAC da trilha de auditoria.

Tampa a lacuna do RFC de rollback (docs/rollback_rfc.md): "Validar integridade
das trilhas HMAC" pós-incidente.

Uso:
    # Verifica um JSON com a trilha exportada do diagnóstico
    python -m tools.verify_trilha --trilha path/to/trilha.json

    # Verifica a trilha embutida em um diagnóstico completo (campo trilha_auditoria)
    python -m tools.verify_trilha --diagnostico path/to/diagnostico.json

    # Saída silenciosa (só exit code)
    python -m tools.verify_trilha --trilha trilha.json --quiet

Exit codes:
    0 — trilha íntegra (todos os passos com HMAC válido)
    1 — trilha adulterada (pelo menos 1 passo com HMAC inválido)
    2 — erro de I/O ou formato (arquivo inexistente, JSON malformado)

Requer: MOTOR_CONECT_MASTER_KEY (mesma fonte de storage_cifrado._master_key)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Garante import do pacote observability quando rodar como script
_PY_ROOT = Path(__file__).resolve().parent.parent
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))

from observability import hmac_trilha  # noqa: E402


def _carregar_trilha(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Carrega trilha de --trilha ou extrai de --diagnostico."""
    if args.trilha:
        path = Path(args.trilha)
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "trilha_auditoria" in data:
            return data["trilha_auditoria"]
        raise ValueError(
            f"Arquivo {path} não contém uma lista nem campo 'trilha_auditoria'."
        )

    if args.diagnostico:
        path = Path(args.diagnostico)
        with path.open("r", encoding="utf-8") as f:
            diag = json.load(f)
        if not isinstance(diag, dict):
            raise ValueError(f"Diagnóstico {path} deve ser um objeto JSON.")
        trilha = diag.get("trilha_auditoria") or diag.get("diagnostico", {}).get(
            "trilha_auditoria"
        )
        if not isinstance(trilha, list):
            raise ValueError(f"Diagnóstico {path} sem campo 'trilha_auditoria'.")
        return trilha

    raise ValueError("Passe --trilha ou --diagnostico.")


def _imprimir_relatorio(
    trilha: list[dict[str, Any]],
    invalidos: list[int],
    quiet: bool,
) -> None:
    if quiet:
        return
    total = len(trilha)
    ok = total - len(invalidos)
    print(f"Total de passos: {total}")
    print(f"Íntegros:        {ok}")
    print(f"Adulterados:     {len(invalidos)}")
    if not invalidos:
        print()
        print("✓ TRILHA ÍNTEGRA — nenhuma mutação detectada.")
        return

    print()
    print("✗ TRILHA ADULTERADA — passos com HMAC inválido:")
    for idx in invalidos:
        passo = trilha[idx]
        pid = passo.get("id") or passo.get("tipo") or f"#{idx}"
        titulo = passo.get("titulo") or passo.get("detalhe") or ""
        print(f"  [{idx}] {pid} — {titulo}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify_trilha",
        description="Verifica integridade HMAC da trilha de auditoria do Motor Tributário Conect.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--trilha",
        help="Caminho para JSON contendo a trilha (lista ou dict com campo trilha_auditoria).",
    )
    group.add_argument(
        "--diagnostico",
        help="Caminho para JSON de diagnóstico completo (campo trilha_auditoria).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Saída silenciosa — só exit code (útil em scripts de CI).",
    )
    args = parser.parse_args(argv)

    try:
        trilha = _carregar_trilha(args)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2

    try:
        invalidos = hmac_trilha.verificar_trilha(trilha)
    except Exception as exc:
        print(f"ERRO ao verificar HMAC: {exc}", file=sys.stderr)
        return 2

    _imprimir_relatorio(trilha, invalidos, args.quiet)
    return 0 if not invalidos else 1


if __name__ == "__main__":
    sys.exit(main())
