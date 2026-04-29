# -*- coding: utf-8 -*-
"""
diagnostico_consolidado.py — Diagnóstico de regime sobre janela de 6 meses.

Fase 0a do Plano de Reforma Tributária. Implementa o blueprint
``~/.claude/plans/blueprint-diagnostico-consolidado.md`` (28/04/2026)
após auditoria com 4 ressalvas técnicas (R1–R4) e revisão pelo advisor
(seção "Bugs críticos no blueprint").

Decisões estruturais cravadas (Luiz Moreira, 28/04/2026):
    - **D1** — Fase 0a faz APENAS diagnóstico de regime (Simples vs Opt-Out
      vs migração). DIFAL e Split Payment ficam ``INDISPONIVEL_AGREGADO``,
      pois agregação por mês perde precisão (PGDAS-D apura por competência).
    - **D2** — Tendência e sazonalidade são **heurísticas diagnósticas**,
      não cálculo fiscal (Rail R2). Marcadas como tal nos avisos da meta.
    - **D3** — ``razao_social`` fora do schema canônico — vai num envelope
      ``DiagnosticoConsolidadoComPII`` separado. LGPD Art. 6º (minimização).
      Hash usa só CNPJ + payload fiscal.

Ressalvas aplicadas:
    - R1: ``decimal.getcontext().sqrt`` (Decimal não tem ``.sqrt`` instance)
      — implementada em ``core.historico_consolidado``.
    - R2: mediana de 6 elementos = ``(sorted[2] + sorted[3]) / 2`` (correta).
    - R3: ``model_dump(mode='json')`` serializa Decimal como string —
      determinístico em Pydantic V2 (validado por teste regressivo).
    - R4: 5/6 votos vai pra ``REVISAR_MANUALMENTE`` (operador decide).
      Inclui ``votos_individuais: Dict[str, int]`` na justificativa.

Amparo legal:
    - LC 123/2006 Art. 12 §1º (apuração mensal Simples)
    - LC 214/2025 Art. 47 (apuração mensal CBS/IBS)
    - LC 214/2025 Arts. 41–44 (dispositivo de Opt-Out)
    - CF Art. 146 III "d" (regime diferenciado Simples Nacional)
    - LGPD Art. 6º (minimização — D3)
    - CLAUDE.md MAX_03 (data base declarada)
    - Rail R7 (Opt-Out automático ≥90% teto)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class TendenciaRBT12(str, Enum):
    """Tendência detectada por OLS slope normalizado sobre faturamento mensal."""

    ASCENDENTE = "ASCENDENTE"
    DESCENDENTE = "DESCENDENTE"
    ESTAVEL = "ESTAVEL"


class RecomendacaoConsolidada(str, Enum):
    """Recomendação consolidada após reconciliação dos 6 meses."""

    MANTER_SIMPLES = "MANTER_SIMPLES"
    OPT_OUT = "OPT_OUT"
    MIGRAR_PRESUMIDO = "MIGRAR_PRESUMIDO"
    MIGRAR_REAL = "MIGRAR_REAL"
    REVISAR_MANUALMENTE = "REVISAR_MANUALMENTE"


class NivelConfianca(str, Enum):
    """Nível de confiança calibrado por reconciliação + sinais de qualidade."""

    ALTA = "ALTA"
    MEDIA = "MEDIA"
    BAIXA = "BAIXA"


# ─────────────────────────────────────────────────────────────────────────────
# Sub-schemas
# ─────────────────────────────────────────────────────────────────────────────


# Tipos de alerta de transição entre meses da janela.
TipoAlertaTransicao = Literal[
    "MUDANCA_ANEXO",
    "FATOR_R_ATRAVESSOU_028",
    "RBT12_90PCT_TETO",
    "DIVERGENCIA_ANEXO_DECLARADO",
    "OUTLIER_FATURAMENTO",
]


class AlertaTransicao(BaseModel):
    """Alerta diagnóstico não-bloqueante sobre transição entre meses."""

    model_config = ConfigDict(frozen=True)

    tipo: TipoAlertaTransicao
    competencia: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    valor_anterior: Optional[Decimal] = None
    valor_atual: Optional[Decimal] = None
    descricao: str = Field(..., min_length=10, max_length=500)
    amparo_legal: str = Field(..., min_length=10)  # MAX_02


class DiagnosticoMensalResumo(BaseModel):
    """Resumo do diagnóstico de um mês — entra na lista do consolidado."""

    model_config = ConfigDict(frozen=True)

    competencia: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    rbt12_aplicado: Decimal = Field(..., ge=0)
    faturamento_mes: Decimal = Field(..., ge=0)
    anexo_aplicado: Literal["I", "II", "III", "IV", "V"]
    fator_r: Decimal = Field(..., ge=0, le=1)
    aliquota_efetiva: Decimal = Field(
        ..., ge=0, le=1, max_digits=8, decimal_places=6
    )
    das_mensal: Decimal = Field(..., ge=0)
    recomendacao_individual: str = Field(
        ...,
        description="Código do recomendacoes_optout (ex: OPT_OUT_FORTE).",
    )
    diagnostico_completo: Dict[str, Any] = Field(
        default_factory=dict,
        description="Saída raw de gerar_diagnostico() — preservada pra trilha.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Schema principal — DiagnosticoConsolidado
# ─────────────────────────────────────────────────────────────────────────────


class DiagnosticoConsolidado(BaseModel):
    """Diagnóstico de regime consolidado sobre 6 meses sequenciais.

    Substitui análise mês-a-mês manual. Saída inclui:
        - hash de reprodutibilidade (refazer cálculo do log — Rail R6)
        - agregação fiscal (carga média + min/max)
        - heurísticas diagnósticas (D2 — tendência + sazonalidade)
        - recomendação consolidada com confiança calibrada
        - alertas de transição (mudança Anexo, Fator R cruzando 0.28, etc)
        - trilha unificada (todos os passos de cálculo dos 6 meses)

    Disponibilidade reduzida (D1):
        - DIFAL → INDISPONIVEL_AGREGADO
        - Split Payment → INDISPONIVEL_AGREGADO
    """

    model_config = ConfigDict(frozen=True)

    # ─── Identificação (sem PII — D3) ─────────────────────────────────────
    versao_schema: Literal["1.0"]
    versao_motor: str = Field(..., min_length=1)
    versao_lei: str = Field(..., min_length=1)
    cnpj: str = Field(..., pattern=r"^\d{14}$")
    competencia_referencia: date
    competencia_inicio: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    competencia_fim: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    regime_atual: Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI"]
    tipo_societario: str = Field(..., min_length=2)
    hash_reprodutibilidade: str = Field(..., pattern=r"^[a-f0-9]{64}$")

    # ─── Diagnósticos mensais ─────────────────────────────────────────────
    diagnosticos_meses: List[DiagnosticoMensalResumo] = Field(
        ..., min_length=6, max_length=6
    )

    # ─── Agregação fiscal ─────────────────────────────────────────────────
    faturamento_total_6m: Decimal = Field(..., ge=0)
    das_total_6m: Decimal = Field(..., ge=0)
    carga_tributaria_media_6m: Decimal = Field(
        ...,
        ge=0,
        le=Decimal("100"),
        description="Razão (das_total / faturamento_total) × 100, em %.",
    )
    carga_min: Decimal = Field(..., ge=0, le=Decimal("100"))
    carga_max: Decimal = Field(..., ge=0, le=Decimal("100"))
    carga_min_competencia: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    carga_max_competencia: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    # ─── Heurísticas diagnósticas (D2) ────────────────────────────────────
    tendencia_rbt12: TendenciaRBT12
    delta_rbt12_pct: Decimal = Field(
        ...,
        description="Delta percentual entre primeiro e último faturamento.",
    )
    sazonalidade_detectada: bool
    mes_pico: Optional[str] = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    mes_vale: Optional[str] = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    # ─── Recomendação consolidada ─────────────────────────────────────────
    recomendacao_regime: RecomendacaoConsolidada
    confianca: NivelConfianca
    justificativa: str = Field(..., min_length=50, max_length=1000)
    amparo_legal: List[str] = Field(..., min_length=1)
    votos_individuais: Dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Ressalva R4 — quebra dos votos por código de recomendação mensal. "
            "Inclui chave especial '_GATE_R7' quando o gate de 90%% do teto "
            "sobrescreve a votação."
        ),
    )

    # ─── Alertas e trilha ─────────────────────────────────────────────────
    alertas_transicao: List[AlertaTransicao] = Field(default_factory=list)
    trilha_unificada: List[Dict[str, Any]] = Field(default_factory=list)

    # ─── Disponibilidade reduzida (D1) ────────────────────────────────────
    difal_status: Literal["INDISPONIVEL_AGREGADO"] = "INDISPONIVEL_AGREGADO"
    split_payment_status: Literal["INDISPONIVEL_AGREGADO"] = "INDISPONIVEL_AGREGADO"

    # ─── Meta ─────────────────────────────────────────────────────────────
    meta: Dict[str, Any] = Field(default_factory=dict)

    # ─── Validators ───────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _coerencia_carga(self) -> "DiagnosticoConsolidado":
        """carga_min ≤ carga_média ≤ carga_max.

        Bug 5 do advisor: comparação Decimal exige quantize comum nas três
        pontas — ``core.historico_consolidado`` aplica ``Decimal('0.0001')``
        em todas. Aqui só verifica a invariante.
        """
        if self.carga_min > self.carga_max:
            raise ValueError(
                f"carga_min ({self.carga_min}) > carga_max ({self.carga_max}) — "
                "impossível matematicamente."
            )
        if not (self.carga_min <= self.carga_tributaria_media_6m <= self.carga_max):
            raise ValueError(
                f"Carga média {self.carga_tributaria_media_6m} fora do range "
                f"[{self.carga_min}, {self.carga_max}]."
            )
        return self

    @model_validator(mode="after")
    def _coerencia_competencias_min_max(self) -> "DiagnosticoConsolidado":
        """carga_min/max_competencia devem existir nos diagnósticos mensais."""
        comps_validas = {d.competencia for d in self.diagnosticos_meses}
        if self.carga_min_competencia not in comps_validas:
            raise ValueError(
                f"carga_min_competencia {self.carga_min_competencia} não consta "
                f"nos diagnósticos mensais ({sorted(comps_validas)})."
            )
        if self.carga_max_competencia not in comps_validas:
            raise ValueError(
                f"carga_max_competencia {self.carga_max_competencia} não consta "
                f"nos diagnósticos mensais ({sorted(comps_validas)})."
            )
        return self

    @model_validator(mode="after")
    def _coerencia_sazonalidade(self) -> "DiagnosticoConsolidado":
        """Coerência sazonalidade ↔ mes_pico/mes_vale."""
        if self.sazonalidade_detectada and (
            self.mes_pico is None or self.mes_vale is None
        ):
            raise ValueError(
                "Sazonalidade detectada exige mes_pico E mes_vale preenchidos."
            )
        if not self.sazonalidade_detectada and (
            self.mes_pico is not None or self.mes_vale is not None
        ):
            raise ValueError(
                "Sem sazonalidade, mes_pico e mes_vale devem ser None."
            )
        if (
            self.sazonalidade_detectada
            and self.mes_pico == self.mes_vale
        ):
            raise ValueError("mes_pico não pode ser igual a mes_vale.")
        return self

    @model_validator(mode="after")
    def _coerencia_tendencia(self) -> "DiagnosticoConsolidado":
        """ASCENDENTE → delta > 0; DESCENDENTE → delta < 0."""
        if (
            self.tendencia_rbt12 == TendenciaRBT12.ASCENDENTE
            and self.delta_rbt12_pct <= 0
        ):
            raise ValueError(
                f"Tendência ASCENDENTE exige delta_rbt12_pct > 0; "
                f"recebido {self.delta_rbt12_pct}."
            )
        if (
            self.tendencia_rbt12 == TendenciaRBT12.DESCENDENTE
            and self.delta_rbt12_pct >= 0
        ):
            raise ValueError(
                f"Tendência DESCENDENTE exige delta_rbt12_pct < 0; "
                f"recebido {self.delta_rbt12_pct}."
            )
        return self

    @model_validator(mode="after")
    def _coerencia_recomendacao(self) -> "DiagnosticoConsolidado":
        """REVISAR_MANUALMENTE não pode ter confianca=ALTA."""
        if (
            self.recomendacao_regime == RecomendacaoConsolidada.REVISAR_MANUALMENTE
            and self.confianca == NivelConfianca.ALTA
        ):
            raise ValueError(
                "REVISAR_MANUALMENTE não pode ter confianca=ALTA — "
                "se exige revisão, confiança não é alta por definição."
            )
        return self

    @model_validator(mode="after")
    def _coerencia_competencias_ordenadas(self) -> "DiagnosticoConsolidado":
        """competencia_inicio < competencia_fim (ordem temporal)."""
        if self.competencia_inicio >= self.competencia_fim:
            raise ValueError(
                f"competencia_inicio ({self.competencia_inicio}) deve ser "
                f"anterior a competencia_fim ({self.competencia_fim})."
            )
        return self


# ─────────────────────────────────────────────────────────────────────────────
# Envelope com PII — separado do schema canônico (D3)
# ─────────────────────────────────────────────────────────────────────────────


class DiagnosticoConsolidadoComPII(BaseModel):
    """Envelope que adiciona PII ao diagnóstico canônico.

    LGPD Art. 6º (minimização) — razão social fica fora do schema-base
    porque pode conter nome civil em MEI/SLU. Quem precisar exibir, consome
    o envelope; quem precisar persistir/hashear, consome o ``diagnostico``
    interno.

    Hash de reprodutibilidade vive em ``DiagnosticoConsolidado.hash_reprodutibilidade``
    e NÃO inclui razao_social — preservar isolamento PII.
    """

    model_config = ConfigDict(frozen=True)

    diagnostico: DiagnosticoConsolidado
    razao_social: str = Field(..., min_length=3, max_length=200)
    pii_sanitizada: bool = Field(
        default=False,
        description="Marca quando a razão social já foi mascarada/anonimizada.",
    )
