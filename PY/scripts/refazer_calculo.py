# -*- coding: utf-8 -*-
"""
scripts/refazer_calculo.py — WS5 (Rail R6 — logs refazíveis)

CLI wrapper sobre core.refazer.verificar_diagnostico().

Carrega um diagnóstico persistido por ID, executa a verificação Rail R6
(estrutura mínima + citação legal + aritmética + violações de segurança)
e devolve relatório JSON.

USO:
  python PY/scripts/refazer_calculo.py --diagnostico-id 42
  python PY/scripts/refazer_calculo.py --diagnostico-id 42 --output report.json
  python PY/scripts/refazer_calculo.py --diagnostico-id 42 --strict

EXIT CODES:
  0 — diagnóstico consistente (Rail R6 cumprido)
  1 — divergência aritmética / violação / amparo legal faltando
  2 — diagnóstico não encontrado / erro de DB / estrutura corrompida

CONTRATO Rail R6: "python PY/scripts/refazer_calculo.py --diagnostico-id N
reconstroi o número apenas do log."

Quando trilha tem alíquota textual ("0,0% IBS + 0,0% CBS (imune)") ou
campos compostos não-numéricos, marca como NAO_VERIFICAVEL_AUTOMATICO
sem bloquear consistência (operador audita manual). É comportamento
esperado pra IMUNE e overlays — Rail R2 (sem extrapolação).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

# Permite rodar como script com `python PY/scripts/refazer_calculo.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.refazer import RelatorioVerificacao, verificar_diagnostico  # noqa: E402

logger = logging.getLogger("refazer_calculo")


def _serializar_decimal(o):
    if isinstance(o, Decimal):
        return str(o)
    raise TypeError(f"Não serializável: {type(o)}")


def _carregar_diagnostico(diagnostico_id: int) -> dict:
    """
    Carrega o diagnóstico do DB e devolve dict resultado (com trilha_auditoria).

    Importa lazy o repository pra não exigir SQLAlchemy quando rodando
    apenas testes unitários.
    """
    from database.connection import get_session  # noqa: PLC0415
    from database.models import DiagnosticoDB  # noqa: PLC0415

    session = next(get_session())
    try:
        diag = session.query(DiagnosticoDB).filter(
            DiagnosticoDB.id == diagnostico_id
        ).first()
        if diag is None:
            raise FileNotFoundError(
                f"Diagnóstico id={diagnostico_id} não encontrado no banco."
            )
        return diag.get_resultado()
    finally:
        session.close()


def _formatar_relatorio_humano(rel: RelatorioVerificacao) -> str:
    """Formata o relatório pra leitura humana (stdout)."""
    linhas = []
    linhas.append("=" * 70)
    linhas.append(f"RELATÓRIO Rail R6 — total_eventos={rel.total_eventos}")
    linhas.append("=" * 70)
    linhas.append(f"Consistente: {'SIM' if rel.consistente else 'NÃO'}")
    linhas.append(f"Por tipo:    {rel.por_tipo}")
    linhas.append(
        f"Divergências aritméticas: {len(rel.divergencias)} | "
        f"Não-verificáveis: {len(rel.nao_verificaveis)} | "
        f"Sem amparo: {len(rel.eventos_sem_amparo)} | "
        f"Malformados: {len(rel.eventos_malformados)} | "
        f"Violações: {len(rel.violacoes_seguranca)}"
    )
    if rel.divergencias:
        linhas.append("")
        linhas.append("--- DIVERGÊNCIAS ARITMÉTICAS ---")
        for d in rel.divergencias:
            linhas.append(
                f"  [{d.id}] esperado={d.esperado_recalculado} "
                f"declarado={d.declarado} delta={d.delta}"
            )
    if rel.violacoes_seguranca:
        linhas.append("")
        linhas.append("--- VIOLAÇÕES DE SEGURANÇA ---")
        for v in rel.violacoes_seguranca:
            linhas.append(f"  [{v}]")
    if rel.eventos_sem_amparo:
        linhas.append("")
        linhas.append("--- EVENTOS SEM AMPARO LEGAL ---")
        for e in rel.eventos_sem_amparo:
            linhas.append(f"  [{e}]")
    if rel.eventos_malformados:
        linhas.append("")
        linhas.append("--- EVENTOS MALFORMADOS ---")
        for e in rel.eventos_malformados:
            linhas.append(f"  [{e}]")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verifica integridade Rail R6 de um diagnóstico persistido.",
    )
    parser.add_argument(
        "--diagnostico-id", type=int, required=True,
        help="ID do diagnóstico (DiagnosticoDB.id) a verificar.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Arquivo JSON pra salvar relatório (default: stdout).",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit code != 0 mesmo pra eventos NAO_VERIFICAVEL_AUTOMATICO.",
    )
    parser.add_argument(
        "--input-file", type=Path, default=None,
        help=(
            "Bypass DB: lê dict resultado de arquivo JSON em vez de "
            "consultar DiagnosticoDB. Útil pra auditoria offline."
        ),
    )
    args = parser.parse_args(argv)

    try:
        if args.input_file is not None:
            with open(args.input_file, encoding="utf-8") as f:
                resultado = json.load(f)
        else:
            resultado = _carregar_diagnostico(args.diagnostico_id)
    except FileNotFoundError as e:
        logger.error("%s", e)
        return 2
    except Exception as e:  # noqa: BLE001 — CLI, queremos catch-all com log
        logger.exception("Erro ao carregar diagnóstico: %s", e)
        return 2

    rel = verificar_diagnostico(resultado)

    payload = {
        "diagnostico_id": args.diagnostico_id,
        "data_verificacao": datetime.now().isoformat(timespec="seconds"),
        "relatorio": rel.model_dump(),
    }

    if args.output is not None:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False, default=_serializar_decimal)
        print(f"Relatório salvo em {args.output}")
    else:
        print(_formatar_relatorio_humano(rel))

    if not rel.consistente:
        return 1
    if args.strict and rel.nao_verificaveis:
        return 1
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )
    sys.exit(main())
