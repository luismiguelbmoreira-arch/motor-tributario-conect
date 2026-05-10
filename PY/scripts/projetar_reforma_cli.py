# -*- coding: utf-8 -*-
"""
scripts/projetar_reforma_cli.py — CLI do redesign

Roda o pipeline `gerar_projecao_pipeline` com PDFs em disco. Útil pra
testar manualmente o redesign fora da API, sem precisar de auth/JWT.

USO:
    python PY/scripts/projetar_reforma_cli.py \\
        --pdf /caminho/das_competencia.pdf \\
        --ano-alvo 2027 \\
        --regime-atual SIMPLES

    # Modo mock — não chama Claude Vision (testar pipeline sem API key):
    python PY/scripts/projetar_reforma_cli.py \\
        --pdf /caminho/qualquer.pdf \\
        --ano-alvo 2026 \\
        --regime-atual SIMPLES \\
        --mock

OPÇÕES:
    --pdf PATH        Caminho de PDF (pode repetir pra múltiplos arquivos)
    --ano-alvo N      Ano da transição (2026-2033)
    --regime-atual R  SIMPLES | PRESUMIDO | REAL | MEI | IMUNE
    --mock            Usa extrator fake determinístico (sem Claude Vision)
    --json            Saída em JSON (default: humano)

EXIT CODE:
    0  = projeção bem-sucedida
    1  = erro de validação (argumento, arquivo, etc.)
    2  = erro do pipeline (CNPJ inválido, ano fora cronograma, etc.)
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _fmt_brl(v: Decimal) -> str:
    """Formata Decimal como 'R$ 1.234,56' (BR)."""
    s = f"{v:,.2f}"  # 1,234.56 (EN)
    inteiro, dec = s.split(".")
    inteiro_br = inteiro.replace(",", ".")
    return f"R$ {inteiro_br},{dec}"


def _carregar_pdfs(paths: Sequence[Path]) -> list[bytes]:
    """Lê os PDFs do disco. Falha fechada se algum não existir."""
    bytes_list = []
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(f"PDF nao encontrado: {p}")
        if not p.is_file():
            raise ValueError(f"Caminho nao e arquivo: {p}")
        with open(p, "rb") as f:
            bytes_list.append(f.read())
    return bytes_list


def _extrator_mock(pdfs_bytes):
    """Mock determinístico — retorna dados fixos, ignora os bytes."""
    class _Fake:
        cnpj = "12.345.678/0001-95"
        razao_social = "EMPRESA MOCK CLI"
        cnae_principal = "4757100"
        uf_origem = "SP"
        faturamento_12m = "1200000.00"
        rpa_referencia = "100000.00"
        das_ecac_referencia = "9250.00"
        competencia = "06/2026"
        das_breakdown = {
            "IRPJ": "0",
            "CSLL": "0",
            "PIS": "1650.00",
            "COFINS": "7600.00",
            "CPP": "0",
            "ICMS": "0",
            "ISS": "0",
            "IPI": "0",
        }
    return _Fake()


def _imprimir_humano(delta) -> None:
    """Output formatado em PT-BR pro terminal."""
    print("=" * 70)
    print("PROJECAO DELTA REFORMA TRIBUTARIA — CLI")
    print("=" * 70)
    print(f"\nCNPJ:         {delta.cnpj}")
    print(f"Competencia:  {delta.competencia.isoformat()}")
    print(f"Ano-alvo:     {delta.ano_alvo}")
    print(f"Aliquota CBS: {delta.aliquota_cbs * 100:.4f}%")
    print(f"Aliquota IBS: {delta.aliquota_ibs * 100:.4f}%")

    print("\n— Carga ATUAL (extraida do PDF do contador) —")
    print(f"  Total: {_fmt_brl(delta.carga_atual)}")

    print("\n— Carga PROJETADA (cenario CBS/IBS no ano-alvo) —")
    print(f"  Total: {_fmt_brl(delta.carga_projetada)}")

    print("\n— Breakdown projetado —")
    for k, v in delta.breakdown_projetado.items():
        print(f"  {k:30s} {_fmt_brl(v):>20s}")

    print("\n— DELTA REFORMA —")
    sinal = "+" if delta.delta_absoluto >= 0 else ""
    print(f"  Absoluto:    {sinal}{_fmt_brl(delta.delta_absoluto)}")
    pct = delta.delta_percentual * 100
    print(f"  Percentual:  {sinal}{pct:.2f}%")

    print("\n— Base legal —")
    for amparo in delta.base_legal:
        print(f"  - {amparo}")
    print("=" * 70)


def _imprimir_json(delta) -> None:
    """Output JSON pra consumo programatico."""
    payload = {
        "cnpj": delta.cnpj,
        "competencia": delta.competencia.isoformat(),
        "ano_alvo": delta.ano_alvo,
        "aliquota_cbs": str(delta.aliquota_cbs),
        "aliquota_ibs": str(delta.aliquota_ibs),
        "carga_atual": str(delta.carga_atual),
        "carga_projetada": str(delta.carga_projetada),
        "delta_absoluto": str(delta.delta_absoluto),
        "delta_percentual": str(delta.delta_percentual),
        "breakdown_projetado": {
            k: str(v) for k, v in delta.breakdown_projetado.items()
        },
        "base_legal": list(delta.base_legal),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="projetar_reforma_cli",
        description=(
            "Projeta o Delta Reforma Tributaria (2026-2033) a partir de PDFs "
            "do contador. Pipeline: extracao Claude Vision -> adaptacao -> "
            "projecao CBS/IBS."
        ),
    )
    p.add_argument(
        "--pdf", action="append", required=True, type=Path,
        help="Caminho de PDF (pode repetir pra varios arquivos)",
    )
    p.add_argument(
        "--ano-alvo", type=int, required=True,
        choices=list(range(2026, 2034)),
        help="Ano da transicao (2026-2033) pra projetar",
    )
    p.add_argument(
        "--regime-atual", required=True,
        choices=["SIMPLES", "PRESUMIDO", "REAL", "MEI", "IMUNE"],
        help="Regime tributario declarado da empresa",
    )
    p.add_argument(
        "--mock", action="store_true",
        help="Usa extrator fake deterministico (sem chamar Claude Vision)",
    )
    p.add_argument(
        "--json", action="store_true",
        help="Saida em JSON (default: humano)",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # 1. Carrega PDFs do disco (falha fechada se faltar arquivo)
    try:
        pdfs_bytes = _carregar_pdfs(args.pdf)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 1

    # 2. Resolve extrator (mock ou real)
    extrator = _extrator_mock if args.mock else None

    # 3. Roda pipeline (import lazy pra acelerar --help)
    from services.projecao_pipeline import gerar_projecao_pipeline
    try:
        delta = gerar_projecao_pipeline(
            pdfs_bytes,
            ano_alvo=args.ano_alvo,
            regime_atual=args.regime_atual,
            extrator=extrator,
        )
    except ValueError as e:
        print(f"ERRO no pipeline: {e}", file=sys.stderr)
        return 2

    # 4. Imprime resultado
    if args.json:
        _imprimir_json(delta)
    else:
        _imprimir_humano(delta)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
