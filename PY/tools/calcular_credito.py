"""
calcular_credito — CLI standalone do caller `core.calculo_credito_cbs_ibs`.

Materializa o consumidor real do mapa-mestre CBS/IBS (PR #37). Recebe um
arquivo JSON com despesas categorizadas + data de referência + alíquota
combinada, calcula o crédito total, imprime o relatório.

Uso:
    cd PY
    python -m tools.calcular_credito \\
        --despesas ../data/exemplos/despesas_lanchonete_2027.json \\
        --data 2027-03-15 \\
        --aliquota 0.265

    # Modo silencioso (só exit code — útil em scripts/CI)
    python -m tools.calcular_credito --despesas X.json --data Y --aliquota Z --quiet

Formato do JSON:
    {
      "despesas": [
        {"categoria": "ENERGIA_ELETRICA", "valor": "1500.00"},
        {"categoria": "VALE_REFEICAO",    "valor": "2400.00"}
      ]
    }

    OU lista direta:
    [
      {"categoria": "ENERGIA_ELETRICA", "valor": "1500.00"}
    ]

    `valor` aceito como string (preferido — Decimal-safe) ou número.
    Chaves com prefixo `_` (ex: `_descricao`, `_amparo_legal`) são ignoradas.

Exit codes:
    0 — cálculo realizado (mesmo com despesas ignoradas — é resultado válido)
    1 — erro de validação (alíquota negativa, valor negativo, formato inválido)
    2 — erro de I/O ou JSON malformado

Caller passa alíquota explícita (Rail R5 estendido — separação fonte ≠ motor)
— esta CLI não consulta CRONOGRAMA_IVA. Quem decide qual alíquota vigente é
o operador.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

_PY_ROOT = Path(__file__).resolve().parent.parent
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))

from core.calculo_credito_cbs_ibs import (  # noqa: E402
    ResultadoCredito,
    calcular_credito_total,
)


def _parse_data(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(
            f"--data inválida: {raw!r}. Use formato ISO YYYY-MM-DD."
        ) from exc


def _parse_aliquota(raw: str) -> Decimal:
    try:
        valor = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(
            f"--aliquota inválida: {raw!r}. Use decimal (ex: 0.265 para 26,5%)."
        ) from exc
    return valor


def _carregar_despesas(path: Path) -> list[tuple[str, Decimal]]:
    """Lê JSON e devolve lista de (categoria, valor)."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        # Aceita envelope com chave `despesas` (formato preferido — permite metadata)
        if "despesas" not in data:
            raise ValueError(
                f"{path} é dict mas não tem campo 'despesas'. "
                "Use {\"despesas\": [...]} ou lista direta."
            )
        itens = data["despesas"]
    elif isinstance(data, list):
        itens = data
    else:
        raise ValueError(f"{path} deve conter dict ou lista no topo.")

    if not isinstance(itens, list):
        raise ValueError(f"Campo 'despesas' em {path} deve ser uma lista.")

    despesas: list[tuple[str, Decimal]] = []
    for i, item in enumerate(itens):
        if not isinstance(item, dict):
            raise ValueError(
                f"Item #{i} em {path} deve ser objeto com 'categoria' e 'valor'."
            )
        categoria = item.get("categoria")
        valor_raw = item.get("valor")
        if not isinstance(categoria, str) or not categoria.strip():
            raise ValueError(f"Item #{i} sem 'categoria' válida.")
        if valor_raw is None:
            raise ValueError(f"Item #{i} ('{categoria}') sem 'valor'.")
        try:
            valor = Decimal(str(valor_raw))
        except InvalidOperation as exc:
            raise ValueError(
                f"Item #{i} ('{categoria}'): valor {valor_raw!r} não é Decimal válido."
            ) from exc
        despesas.append((categoria, valor))

    return despesas


def _imprimir_relatorio(resultado: ResultadoCredito, quiet: bool) -> None:
    if quiet:
        return

    print(f"Data referência:  {resultado.data_referencia.isoformat()}")
    print(f"Alíquota CBS+IBS: {resultado.aliquota_aplicada}")
    print(f"Crédito total:    R$ {resultado.total_credito}")
    print(f"Ignoradas:        {len(resultado.despesas_ignoradas)}")

    if not resultado.despesas_ignoradas:
        return

    print()
    print("Despesas que NÃO geraram crédito:")
    for d in resultado.despesas_ignoradas:
        print(f"  [{d.motivo:18s}] {d.categoria:30s} R$ {d.valor}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="calcular_credito",
        description=(
            "Calcula crédito CBS+IBS de uma lista de despesas categorizadas. "
            "Caller real do mapa-mestre (LC 214/2025)."
        ),
    )
    parser.add_argument(
        "--despesas",
        required=True,
        help="Caminho para JSON com despesas (envelope {\"despesas\":[...]} ou lista direta).",
    )
    parser.add_argument(
        "--data",
        required=True,
        help="Data de referência ISO YYYY-MM-DD (define versão vigente do mapa).",
    )
    parser.add_argument(
        "--aliquota",
        required=True,
        help="Alíquota CBS+IBS combinada (decimal, ex: 0.265 para 26,5%%).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Saída silenciosa — só exit code (útil em scripts/CI).",
    )
    args = parser.parse_args(argv)

    # Parse de argumentos primitivos (erro = exit 1)
    try:
        data_ref = _parse_data(args.data)
        aliquota = _parse_aliquota(args.aliquota)
    except ValueError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1

    # I/O do arquivo JSON (erro = exit 2)
    path = Path(args.despesas)
    try:
        despesas = _carregar_despesas(path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERRO de I/O: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        # Formato malformado dentro do JSON (estrutura)
        print(f"ERRO de formato: {exc}", file=sys.stderr)
        return 2

    # Cálculo (erro de regra de negócio = exit 1)
    try:
        resultado = calcular_credito_total(despesas, data_ref, aliquota)
    except ValueError as exc:
        print(f"ERRO de validação: {exc}", file=sys.stderr)
        return 1

    _imprimir_relatorio(resultado, args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
