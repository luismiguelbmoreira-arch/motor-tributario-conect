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
    --comparar        Roda o COMPARADOR DE CENÁRIOS (melhor regime no
                      ano-alvo) em vez da projeção simples
    --lucro-real-mensal R$   DRE mensal — habilita o cenário Lucro Real
    --tipo-societario T      Forma jurídica RFB (LTDA, SA, EI, ...)

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


def _decimal_arg(s: str) -> Decimal:
    """Converte argumento monetário; erro amigável em vez de traceback."""
    try:
        return Decimal(s)
    except Exception:
        raise argparse.ArgumentTypeError(f"valor monetario invalido: {s!r}")


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
    p.add_argument(
        "--comparar", action="store_true",
        help="Roda o comparador de cenarios (melhor regime no ano-alvo)",
    )
    p.add_argument(
        "--lucro-real-mensal", type=_decimal_arg, default=None,
        help="Lucro real MENSAL comprovado por DRE (habilita cenario REAL)",
    )
    p.add_argument(
        "--tipo-societario", default=None,
        help="Forma juridica RFB (LTDA, SA, EI, SLU, SS, COOPERATIVA...)",
    )
    return p


def _imprimir_comparativo_humano(comp) -> None:
    """Output do comparador em PT-BR pro terminal."""
    print("=" * 70)
    print("COMPARADOR DE CENARIOS FISCAIS — CLI")
    print("=" * 70)
    print(f"\nCNPJ:          {comp.cnpj}")
    print(f"Competencia:   {comp.competencia.isoformat()}")
    print(f"Ano-alvo:      {comp.ano_alvo}")
    print(f"Regime atual:  {comp.regime_atual}")
    print(f"\nRESULTADO:     {comp.resultado}")
    if comp.melhor_cenario_id:
        print(f"Melhor cenario: {comp.melhor_cenario_id}")
    if comp.economia_mensal_vs_manter is not None:
        print(f"Economia vs manter: {_fmt_brl(comp.economia_mensal_vs_manter)}/mes "
              f"({_fmt_brl(comp.economia_anual_vs_manter)}/ano)")

    print("\n— Cenarios (perimetro comparavel: federal + CBS/IBS) —")
    for c in comp.cenarios:
        perim = (
            _fmt_brl(c.perimetro_comparavel_mensal)
            if c.perimetro_comparavel_mensal is not None else "—"
        )
        print(f"  {c.id:20s} {c.status:12s} {perim:>18s}  [{c.origem_carga}]")
        if c.motivo:
            print(f"    motivo: {c.motivo}")
        for trib, valor in c.fora_do_perimetro.items():
            print(f"    fora do ranking: {trib} = {valor}")

    print("\n— Alertas (nao supressiveis) —")
    for a in comp.alertas:
        print(f"  [{a['id']}] {a['titulo']}")
        print(f"    {a['detalhe']}")
        print(f"    Amparo: {a['amparo_legal']}")

    print("\n— Base legal —")
    for amparo in comp.base_legal:
        print(f"  - {amparo}")
    print("=" * 70)


def _imprimir_comparativo_json(comp) -> None:
    payload = {
        "cnpj": comp.cnpj,
        "competencia": comp.competencia.isoformat(),
        "ano_alvo": comp.ano_alvo,
        "regime_atual": comp.regime_atual,
        "resultado": comp.resultado,
        "melhor_cenario_id": comp.melhor_cenario_id,
        "economia_mensal_vs_manter": (
            str(comp.economia_mensal_vs_manter)
            if comp.economia_mensal_vs_manter is not None else None
        ),
        "economia_anual_vs_manter": (
            str(comp.economia_anual_vs_manter)
            if comp.economia_anual_vs_manter is not None else None
        ),
        "piso_nao_comparado_mensal": str(comp.piso_nao_comparado_mensal),
        "cenarios": [
            {
                "id": c.id,
                "regime": c.regime,
                "status": c.status,
                "origem_carga": c.origem_carga,
                "motivo": c.motivo,
                "perimetro_comparavel_mensal": (
                    str(c.perimetro_comparavel_mensal)
                    if c.perimetro_comparavel_mensal is not None else None
                ),
                "breakdown_perimetro": {
                    k: str(v) for k, v in c.breakdown_perimetro.items()
                },
                "fora_do_perimetro": dict(c.fora_do_perimetro),
                "anexo_simples": c.anexo_simples,
                "fator_r": c.fator_r,
                "avisos": list(c.avisos),
                "base_legal": list(c.base_legal),
            }
            for c in comp.cenarios
        ],
        "alertas": [dict(a) for a in comp.alertas],
        "base_legal": list(comp.base_legal),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


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
    if args.comparar:
        from services.projecao_pipeline import gerar_comparativo_pipeline

        overrides = {}
        if args.lucro_real_mensal is not None:
            overrides["lucro_real_mensal"] = args.lucro_real_mensal
        if args.tipo_societario is not None:
            overrides["tipo_societario"] = args.tipo_societario
        try:
            comp = gerar_comparativo_pipeline(
                pdfs_bytes,
                ano_alvo=args.ano_alvo,
                regime_atual=args.regime_atual,
                extrator=extrator,
                perfil_overrides=overrides or None,
            )
        except ValueError as e:
            print(f"ERRO no pipeline: {e}", file=sys.stderr)
            return 2
        if args.json:
            _imprimir_comparativo_json(comp)
        else:
            _imprimir_comparativo_humano(comp)
        return 0

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
