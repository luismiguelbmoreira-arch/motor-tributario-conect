# -*- coding: utf-8 -*-
"""
core/projetor_reforma.py — Projetor da Reforma Tributária 2026-2033

POSICIONAMENTO ARQUITETURAL (project_visao_saas.md):
  Motor Tributário Conect NÃO é calculadora de IRPJ/CSLL do zero.
  É EXTRATOR + PARAMETRIZADOR + PROJETOR:
    1. EXTRAI valores prontos dos PDFs do contador (Claude Vision —
       services/extrator_pdfs.py)
    2. PARAMETRIZA o cenário fiscal atual (regime, porte, ativid., CNAE)
    3. PROJETA o Δ Reforma Tributária 2026-2033 (CBS/IBS/IS/Split Payment)
       conforme CRONOGRAMA_IVA + LC 214/2025 Arts. 344, 348, 353-360

Este módulo é o caller canônico do CRONOGRAMA_IVA (já existente em
core/tabelas_simples.py, validado por Luiz Moreira em 2026-04-25).

PEÇAS REUSADAS:
  - DadosExtraidosPDF (services/extrator_pdfs.py) — origem dos números
  - CRONOGRAMA_IVA (core/tabelas_simples.py) — alíquotas CBS/IBS por ano
  - HistoricoSeisMeses (schemas/historico_seis_meses.py) — 6 meses validados
  - DiagnosticoConsolidado (core/historico_consolidado.py) — projeção mensal

ENGINES DE REGIME (LucroReal/Presumido/MEI/Imune/SimplesMulti) são usados
como VALIDADORES SECUNDÁRIOS do extrato — confirmam batimento entre número
declarado pelo contador e cálculo independente. Não são fonte primária do
diagnóstico (Rail R5: separação fonte ≠ motor).

BASE LEGAL:
  - LC 214/2025 Art. 344 (transição CBS/IBS)
  - LC 214/2025 Art. 348 (cronograma)
  - LC 214/2025 Arts. 353-360 (Split Payment + crédito B2B)
  - EC 132/2023 (Reforma Tributária)
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.tabelas_simples import CRONOGRAMA_IVA

# ─────────────────────────────────────────────────────────────────────────────
# TIPOS
# ─────────────────────────────────────────────────────────────────────────────

AnoTransicao = Literal[2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033]
RegimeAtual = Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI", "IMUNE"]


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA — Documento extraído (origem: PDFs do contador)
# ─────────────────────────────────────────────────────────────────────────────

class DocumentoFiscalExtraido(BaseModel):
    """
    Carga tributária consolidada extraída de documentos do contador.

    Origem canônica: services.extrator_pdfs.DadosExtraidosPDF + breakdown DAS.
    Schema mínimo necessário pra projetar Δ Reforma Tributária.

    Cada campo numérico é Decimal (Rail "nunca float em dinheiro" — CLAUDE.md).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cnpj: str = Field(description="CNPJ 14 dígitos sem pontuação.")
    competencia: date = Field(
        description="Mês de referência da apuração (data do 1º dia do mês)."
    )
    regime_atual: RegimeAtual
    receita_bruta_mensal: Decimal = Field(
        ge=Decimal("0"),
        description="Receita bruta da competência (extraída do PDF do contador).",
    )

    # Breakdown da carga ATUAL (extraída do DAS / DARF / ECF / balancete)
    irpj_pago: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    csll_paga: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    pis_pago: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    cofins_paga: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    icms_pago: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"),
        description="ICMS efetivamente recolhido (já líquido de créditos).",
    )
    iss_pago: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    ipi_pago: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"),
        description="IPI efetivamente recolhido (já líquido de créditos).",
    )
    cpp_pago: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"),
        description="Contribuição Previdenciária Patronal sobre folha.",
    )

    # Rastreabilidade (LGPD + auditoria)
    documento_origem_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 do PDF de origem (auditoria_documentos.hash).",
    )
    fonte_extracao: str = Field(
        default="extracao_pdf_claude_vision",
        description="Origem da extração (ex: extracao_pdf_claude_vision, fonte_nibo).",
    )


class DeltaReformaTributaria(BaseModel):
    """
    Resultado da projeção Δ Reforma Tributária.

    Compara carga ATUAL (extraída do PDF) vs carga PROJETADA no ano-alvo
    (aplicando CRONOGRAMA_IVA + extinção gradual PIS/COFINS/ICMS/ISS).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    competencia: date
    ano_alvo: int
    cnpj: str

    carga_atual: Decimal = Field(
        description="Soma dos tributos pagos hoje (IRPJ + CSLL + PIS + COFINS + ICMS + ISS + IPI + CPP)."
    )
    carga_projetada: Decimal = Field(
        description="Soma projetada no cenário CBS/IBS do ano-alvo."
    )
    delta_absoluto: Decimal = Field(
        description="carga_projetada - carga_atual (positivo = aumento)."
    )
    delta_percentual: Decimal = Field(
        description="delta_absoluto / carga_atual (Decimal, ex: 0.15 = +15%)."
    )

    breakdown_projetado: dict[str, Decimal] = Field(
        description=(
            "Componentes da projeção: cbs, ibs, pis_residual, cofins_residual, "
            "icms_residual, iss_residual, irpj_csll (não mudam pela Reforma), etc."
        )
    )

    aliquota_cbs: Decimal = Field(description="CBS vigente no ano-alvo (Cronograma).")
    aliquota_ibs: Decimal = Field(description="IBS vigente no ano-alvo (Cronograma).")
    base_legal: tuple[str, ...] = Field(
        default=(
            "LC 214/2025 Art. 344 (transição CBS/IBS)",
            "LC 214/2025 Art. 348 (cronograma)",
            "EC 132/2023 (Reforma Tributária)",
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# API PÚBLICA
# ─────────────────────────────────────────────────────────────────────────────

def projetar_delta_reforma(
    *,
    documento: DocumentoFiscalExtraido,
    ano_alvo: AnoTransicao,
) -> DeltaReformaTributaria:
    """
    Projeta o Δ Reforma Tributária para o documento extraído.

    Aplica o CRONOGRAMA_IVA do ano-alvo (alíquotas CBS/IBS validadas por
    Luiz Moreira contra LC 214/2025) sobre a receita bruta do documento,
    mantendo IRPJ/CSLL/CPP inalterados (não são afetados pela Reforma) e
    reduzindo PIS/COFINS/ICMS/ISS conforme o cronograma de extinção.

    NOTA: nesta primeira iteração, modelagem é SIMPLIFICADA — assume que:
      - PIS+COFINS são totalmente substituídos por CBS no ano alvo (Art. 344)
      - ICMS+ISS são totalmente substituídos por IBS (transição gradual
        deveria atenuar isso pra anos < 2033 — pendência etapa futura)
      - IRPJ/CSLL/CPP/IPI permanecem
      - Sem cálculo de crédito B2B nem Split Payment (etapas futuras)

    Args:
        documento: DocumentoFiscalExtraido (origem: PDF do contador).
        ano_alvo: ano da transição (2026-2033) pra projetar.

    Returns:
        DeltaReformaTributaria frozen com carga atual, projetada, delta, breakdown.

    Raises:
        ValueError: ano_alvo fora do cronograma vigente.
    """
    if ano_alvo not in CRONOGRAMA_IVA:
        raise ValueError(
            f"Ano {ano_alvo} fora do cronograma vigente. "
            f"Anos disponíveis: {sorted(CRONOGRAMA_IVA.keys())}. "
            f"LC 214/2025 Art. 348."
        )

    aliquotas = CRONOGRAMA_IVA[ano_alvo]
    aliq_cbs = Decimal(str(aliquotas["CBS"]))
    aliq_ibs = Decimal(str(aliquotas["IBS"]))

    # Carga atual = soma dos tributos pagos (já líquidos, extraídos do PDF)
    carga_atual = (
        documento.irpj_pago
        + documento.csll_paga
        + documento.pis_pago
        + documento.cofins_paga
        + documento.icms_pago
        + documento.iss_pago
        + documento.ipi_pago
        + documento.cpp_pago
    ).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # Projeção CBS/IBS sobre receita bruta (modelagem v1 — sem créditos)
    cbs_projetado = (documento.receita_bruta_mensal * aliq_cbs).quantize(
        Decimal("0.01"), ROUND_HALF_UP,
    )
    ibs_projetado = (documento.receita_bruta_mensal * aliq_ibs).quantize(
        Decimal("0.01"), ROUND_HALF_UP,
    )

    # IRPJ/CSLL/CPP/IPI permanecem (não mudam com Reforma)
    breakdown = {
        "cbs": cbs_projetado,
        "ibs": ibs_projetado,
        "irpj_inalterado": documento.irpj_pago,
        "csll_inalterada": documento.csll_paga,
        "ipi_inalterado": documento.ipi_pago,
        "cpp_inalterada": documento.cpp_pago,
        # PIS/COFINS/ICMS/ISS extintos no ano-alvo (modelagem v1 simplificada)
        "pis_residual": Decimal("0"),
        "cofins_residual": Decimal("0"),
        "icms_residual": Decimal("0"),
        "iss_residual": Decimal("0"),
    }

    carga_projetada = sum(breakdown.values())
    if not isinstance(carga_projetada, Decimal):
        carga_projetada = Decimal(str(carga_projetada))
    carga_projetada = carga_projetada.quantize(Decimal("0.01"), ROUND_HALF_UP)

    delta_absoluto = (carga_projetada - carga_atual).quantize(
        Decimal("0.01"), ROUND_HALF_UP,
    )
    delta_percentual = (
        (delta_absoluto / carga_atual).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        if carga_atual > 0
        else Decimal("0")
    )

    return DeltaReformaTributaria(
        competencia=documento.competencia,
        ano_alvo=ano_alvo,
        cnpj=documento.cnpj,
        carga_atual=carga_atual,
        carga_projetada=carga_projetada,
        delta_absoluto=delta_absoluto,
        delta_percentual=delta_percentual,
        breakdown_projetado=breakdown,
        aliquota_cbs=aliq_cbs,
        aliquota_ibs=aliq_ibs,
    )
