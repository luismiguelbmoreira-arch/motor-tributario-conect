# -*- coding: utf-8 -*-
"""
diagnosticar_moreira.py — WS1.a Diagnostico empirico Vision API

Roda os 4 PDFs reais do Escritorio Moreira contra extrair_dados_pdfs e
captura comportamento real do pipeline para classificar a falha em uma das
3 categorias (WS1.a -> WS1.b ou WS1.c do plano):

  WS1.b — Bug real do extrator (corrigir):
      - ERR-028 (CPF em campo CNPJ)
      - confianca_extracao < 0.8 sistematica
      - parser BR/US errando

  WS1.c — Documentos faltantes (NAO e bug):
      - Sem PGDAS-D, sem RBT12, sem folha — guardiao 422 funciona
      - Acao: voltar e pedir os arquivos faltantes (Q6 ja respondida: subir)

Uso:
    python PY/scripts/diagnosticar_moreira.py

Saida:
    Tabela por arquivo + diagnostico classificado.
    Exit 0 se todos os PDFs passaram sem 500.
    Exit 1 se algum PDF gerou 500 (bug real).
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("diagnostico_moreira")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.extrator_pdfs import extrair_dados_pdfs  # noqa: E402

PASTA_MOREIRA = ROOT.parent / "samples" / "uploads_clientes" / "MOREIRA"

CENARIOS = {
    "1_todos_4_pdfs": {
        "descricao": "4 PDFs juntos (cenario que o usuario relata falhar)",
        "arquivos": [
            "CARTAO CNPJ.pdf",
            "COMPROVANTE DE PAGAMENTO 022026.pdf",
            "PGDASD-DECLARACAO-50803014202602002.pdf",
            "PGDASD-EXTRATO-07202606344955448.pdf",
        ],
    },
    "2_so_pgdas_d": {
        "descricao": "Apenas os 2 PGDAS-D (minimo viavel para RBT12)",
        "arquivos": [
            "PGDASD-DECLARACAO-50803014202602002.pdf",
            "PGDASD-EXTRATO-07202606344955448.pdf",
        ],
    },
    "3_cartao_e_comprovante": {
        "descricao": "Cartao CNPJ + Comprovante (sem RBT12 — espera 422)",
        "arquivos": [
            "CARTAO CNPJ.pdf",
            "COMPROVANTE DE PAGAMENTO 022026.pdf",
        ],
    },
}


def rodar_cenario(nome: str, descricao: str, arquivos: list[str]) -> dict:
    log.info("=" * 70)
    log.info("CENARIO %s: %s", nome, descricao)
    log.info("=" * 70)
    caminhos = [PASTA_MOREIRA / nome_arq for nome_arq in arquivos]
    faltantes = [str(c) for c in caminhos if not c.exists()]
    if faltantes:
        return {
            "cenario": nome,
            "status": "ERRO_PRE",
            "motivo": f"Arquivos nao encontrados: {faltantes}",
        }
    try:
        dados = extrair_dados_pdfs(caminhos)
        return {
            "cenario": nome,
            "status": "OK",
            "cnpj": dados.cnpj,
            "razao_social": dados.razao_social,
            "cnae_principal": dados.cnae_principal,
            "uf_origem": dados.uf_origem,
            "faturamento_12m": str(dados.faturamento_12m) if dados.faturamento_12m else None,
            "rpa_referencia": str(dados.rpa_referencia) if dados.rpa_referencia else None,
            "das_ecac_referencia": str(dados.das_ecac_referencia) if dados.das_ecac_referencia else None,
            "competencia": dados.competencia,
            "anexo_simples": dados.anexo_simples,
            "folha_salarios_12m": str(dados.folha_salarios_12m) if dados.folha_salarios_12m else None,
            "confianca_extracao": dados.confianca_extracao,
            "campos_nao_encontrados": list(dados.campos_nao_encontrados or []),
            "observacoes": dados.observacoes,
        }
    except ValueError as e:
        return {
            "cenario": nome,
            "status": "VALIDATION_ERROR",
            "tipo": type(e).__name__,
            "mensagem": str(e),
            "classificacao": "WS1.b ou WS1.c — analisar mensagem",
        }
    except RuntimeError as e:
        return {
            "cenario": nome,
            "status": "RUNTIME_ERROR",
            "tipo": type(e).__name__,
            "mensagem": str(e)[:500],
            "classificacao": "WS1.b — possivel bug ou documento errado",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "cenario": nome,
            "status": "EXCEPTION",
            "tipo": type(e).__name__,
            "mensagem": str(e)[:500],
            "traceback": traceback.format_exc()[:2000],
            "classificacao": "WS1.b — bug real (500 esperado)",
        }


def main() -> int:
    if not PASTA_MOREIRA.exists():
        log.error("Pasta MOREIRA nao encontrada em %s", PASTA_MOREIRA)
        return 2

    log.info("Diretorio de PDFs: %s", PASTA_MOREIRA)
    log.info("PDFs disponiveis: %s", sorted(p.name for p in PASTA_MOREIRA.glob("*.pdf")))

    resultados = {}
    for nome, cfg in CENARIOS.items():
        resultados[nome] = rodar_cenario(nome, cfg["descricao"], cfg["arquivos"])

    log.info("\n" + "=" * 70)
    log.info("RELATORIO FINAL")
    log.info("=" * 70)
    print(json.dumps(resultados, indent=2, ensure_ascii=False, default=str))

    teve_500 = any(r.get("status") == "EXCEPTION" for r in resultados.values())
    return 1 if teve_500 else 0


if __name__ == "__main__":
    sys.exit(main())
