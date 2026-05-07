# -*- coding: utf-8 -*-
"""
diagnostico_consolidado.py — Schema de saída da análise histórica 6 meses.
LC 123/2006 | LC 214/2025

Sem valores hardcoded — é schema de output puro.
"""

from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class DiagnosticoMensalResumo(BaseModel):
    """Resumo de um único mês dentro do DiagnosticoConsolidado."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    competencia: str = Field(..., description="Competência YYYY-MM")
    rbt12: Decimal = Field(..., description="RBT12 vigente no mês (LC 123/2006, Art. 3º, §1º)")
    fator_r: Optional[Decimal] = Field(default=None, description="Fator R do mês (LC 123/2006, Art. 18, § 24) — None se não aplicável")
    carga_tributaria_mes: Decimal = Field(..., description="Carga tributária total do mês (DAS ou equivalente)")
    valor_operacoes_mes: Decimal = Field(..., description="Soma dos valores de todas as operações do mês")
    aliquota_efetiva_mes: Decimal = Field(..., description="Alíquota efetiva do mês = carga / valor_operacoes")
    num_operacoes: int = Field(..., ge=1, description="Número de operações originais no mês")
    recomendacao_codigo: str = Field(..., description="Código de recomendação do motor (ex: OPT_OUT_FORTE, MANTER_SIMPLES)")
    alertas_mes: List[str] = Field(default_factory=list, description="Tipos de alertas do motor para este mês")
    anexo_simples: Optional[str] = Field(default=None, description="Anexo Simples Nacional do mês (I-V) — None para regimes não-Simples")


class AlertaTransicao(BaseModel):
    """Alerta detectado na transição entre meses consecutivos."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    tipo: Literal[
        "ANEXO_MUDOU",
        "FATOR_R_ZONA_RISCO",
        "TETO_90PCT",
        "FATOR_R_MUDOU_ANEXO",
        "CRESCIMENTO_ACELERADO",
    ] = Field(..., description="Tipo do alerta de transição")
    competencia: str = Field(..., description="Competência YYYY-MM em que o alerta ocorreu")
    detalhe: str = Field(..., description="Descrição do alerta com valores específicos")
    amparo_legal: str = Field(..., description="Base legal ou nota heurística")


class DiagnosticoConsolidado(BaseModel):
    """
    Consolidação de 6 meses de histórico fiscal.
    Todo campo numérico desta classe foi produzido pelo motor rodando.
    LC 123/2006 | LC 214/2025 | MAX_08.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    periodo: str = Field(..., description="Período coberto, ex: '2026-01 a 2026-06'")
    cnpj_anonimizado: str = Field(..., description="SHA-256(CNPJ)[:16] — LGPD Art. 12")
    regime: Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI"] = Field(..., description="Regime tributário da empresa")

    resumos_mensais: List[DiagnosticoMensalResumo] = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Resumo mês a mês — sempre 6 itens",
    )

    carga_total_periodo: Decimal = Field(..., description="Soma da carga tributária dos 6 meses")
    carga_media_mensal: Decimal = Field(..., description="Média aritmética da carga mensal")
    aliquota_efetiva_consolidada: Decimal = Field(
        ...,
        description="Média ponderada pelo faturamento — SUM(imposto_6m) / SUM(faturamento_6m). LC 123/2006, Art. 18, §1º",
    )
    aliquota_efetiva_min: Decimal = Field(..., description="Menor alíquota efetiva mensal no período")
    aliquota_efetiva_max: Decimal = Field(..., description="Maior alíquota efetiva mensal no período")

    tendencia: Literal["CRESCENTE", "DECRESCENTE", "ESTAVEL"] = Field(
        ...,
        description="Tendência da carga tributária — regressão linear sobre 6 meses. Heurística interna.",
    )

    alertas_transicao: List[AlertaTransicao] = Field(
        default_factory=list,
        description="Alertas de transição detectados entre meses",
    )

    recomendacao_regime: Literal[
        "OPT_OUT_FORTE",
        "AVALIAR_OPT_OUT",
        "MANTER_SIMPLES",
        "INCONCLUSIVO",
        "NAO_APLICAVEL",
    ] = Field(..., description="Recomendação consolidada para o regime tributário")

    meses_recomendando_optout: int = Field(
        ...,
        ge=0,
        le=6,
        description=(
            "Meses com recomendação OPT_OUT_FORTE ou OPT_OUT_VANTAJOSO. "
            "OPT_OUT_CONDICIONAL excluído — conservadorismo: opt-out é irretratável (LC 123/2006, Arts. 30-31)."
        ),
    )

    indice_confianca: int = Field(
        ...,
        ge=0,
        le=10,
        description="Índice de confiança 0-10 — concentração da recomendação. Heurística interna.",
    )

    hash_reprodutibilidade: str = Field(
        ...,
        description="SHA-256(historico_json + motor_versao + tabelas_hash) — garante reprodutibilidade",
    )
    motor_versao: str = Field(..., description="Versão do motor que gerou este diagnóstico")
    gerado_em: str = Field(..., description="ISO datetime de geração")
