# -*- coding: utf-8 -*-
"""
api_motor.py — FastAPI HTTP Wrapper do Motor Tributário Conect 2026-2033
Projeto: Motor Tributário Conect — Escritório Contábil Conect, Sorocaba, SP

ENDPOINTS:
  GET  /health          → status + contagem de testes
  POST /auditar         → audita uma empresa (pasta com PDFs)
  POST /auditar/batch   → audita todas as empresas de uma pasta base

USO:
  cd PY && uvicorn api_motor:app --reload --port 8000

LGPD:
  Nenhum dado persiste. purge() já chamado dentro de auditar_empresa().
  Logs sem CNPJ ou razão social.

DÉCIMAL:
  Todos os campos monetários são Decimal internamente.
  Serializados como strings no JSON (json_encoders) — sem perda de precisão.
"""

import logging
import sys
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

# Adiciona PY/ ao path para imports relativos
sys.path.insert(0, str(Path(__file__).parent))

from audit_universal import auditar_empresa

logger = logging.getLogger("motor_conect.api")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

TOTAL_TESTES = 245  # atualizar após cada fase de testes


# ─────────────────────────────────────────────────────────────────────────────
# MODELOS DE REQUEST
# ─────────────────────────────────────────────────────────────────────────────

class AuditarRequest(BaseModel):
    pasta_empresa: str = Field(
        ...,
        description="Caminho para pasta com PDFs da empresa",
        examples=["../docs/doc calculo/CANAVEZI"],
    )


class AuditarBatchRequest(BaseModel):
    pasta_base: str = Field(
        ...,
        description="Pasta base contendo subpastas de empresas",
        examples=["../docs/doc calculo"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# MODELOS DE RESPONSE — Decimal serializado como string (sem perda de precisão)
# ─────────────────────────────────────────────────────────────────────────────

class AuditResult(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: str})

    empresa: str
    das_motor: Decimal
    das_ecac: Decimal
    delta: Decimal
    delta_pct: Decimal           # Decimal end-to-end — nunca float
    status: Literal["APROVADO", "REVISAR"]
    anexo: str                   # "I"–"V" ou "MULTI" para multi-atividade
    rbt12: Decimal
    ae: Decimal
    confianca_extracao: float    # 0.0–1.0 — metadado, não valor monetário
    campos_ausentes: list[str]


class HealthResponse(BaseModel):
    status: str
    testes: int
    versao: str


class BatchResult(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: str})

    total: int
    aprovados: int
    revisao: int
    erros_extracao: int
    resultados: list[AuditResult]
    erros: list[dict]            # {"empresa": str, "erro": str} — falhas individuais


# ─────────────────────────────────────────────────────────────────────────────
# APLICAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Motor Tributário API iniciada | testes=%d", TOTAL_TESTES)
    yield
    logger.info("Motor Tributário API encerrada")


app = FastAPI(
    title="Motor Tributário Conect 2026-2033",
    description=(
        "API de Auditoria Tributária Transicional (EC 132/2023 | LC 123/2006 | LC 214/2025). "
        "Extrai PDFs do e-CAC via Claude Vision e compara DAS calculado vs DAS pago."
    ),
    version="2.0.0",
    lifespan=lifespan,
)


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["infra"])
def health():
    """Status da API e contagem de testes certificados."""
    return HealthResponse(
        status="ok",
        testes=TOTAL_TESTES,
        versao=app.version,
    )


@app.post("/auditar", response_model=AuditResult, tags=["auditoria"])
def auditar(req: AuditarRequest):
    """
    Audita uma empresa a partir da pasta com PDFs do e-CAC.

    Pipeline:
      1. Claude Vision extrai dados dos PDFs
      2. Motor calcula DAS (Simples Nacional, multi-atividade se detectado)
      3. Compara com DAS pago no e-CAC
      4. Retorna delta + status APROVADO/REVISAR

    Erros HTTP:
      404 — pasta não encontrada
      422 — erro de configuração (RBT12 inválido, sem PDFs, etc.)
      500 — erro interno (contate o suporte)
    """
    try:
        resultado = auditar_empresa(req.pasta_empresa)
        return AuditResult(**resultado)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("Erro inesperado em POST /auditar: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Erro interno — contate o suporte.")


@app.post("/auditar/batch", response_model=BatchResult, tags=["auditoria"])
def auditar_batch(req: AuditarBatchRequest):
    """
    Audita todas as empresas (subpastas) dentro de pasta_base.

    Falhas individuais não abortam o batch — retornadas em `erros[]`.
    Útil para processar todos os clientes do escritório de uma vez.
    """
    pasta_base = Path(req.pasta_base)
    if not pasta_base.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Pasta base não encontrada: {pasta_base}",
        )

    subpastas = sorted(p for p in pasta_base.iterdir() if p.is_dir())
    if not subpastas:
        raise HTTPException(
            status_code=422,
            detail=f"Nenhuma subpasta encontrada em: {pasta_base}",
        )

    resultados: list[AuditResult] = []
    erros: list[dict] = []

    for pasta in subpastas:
        try:
            resultado = auditar_empresa(str(pasta))
            resultados.append(AuditResult(**resultado))
        except Exception as exc:
            erros.append({"empresa": pasta.name, "erro": str(exc)})
            logger.warning("Batch: falha em %s — %s", pasta.name, type(exc).__name__)

    aprovados = sum(1 for r in resultados if r.status == "APROVADO")

    return BatchResult(
        total=len(resultados) + len(erros),
        aprovados=aprovados,
        revisao=len(resultados) - aprovados,
        erros_extracao=len(erros),
        resultados=resultados,
        erros=erros,
    )
