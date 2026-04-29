# -*- coding: utf-8 -*-
"""
historico_seis_meses.py — Schemas para análise histórica de 6 meses.
LC 123/2006 | LC 214/2025

Sem valores monetários hardcoded — constantes normativas vêm de tabelas_simples.py (FROZEN).
"""

import re
from decimal import Decimal
from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.motor import EmpresaCompradora, EmpresaFornecedora, OperacaoFiscal

# Janela transicional LC 214/2025 (Art. 348): 2026-2033
_COMPETENCIA_RE = re.compile(r"^(202[6-9]|203[0-3])-(0[1-9]|1[0-2])$")


def _next_competencia(competencia: str) -> str:
    """Avança exatamente um mês no formato YYYY-MM."""
    year, month = int(competencia[:4]), int(competencia[5:7])
    if month == 12:
        return f"{year + 1}-01"
    return f"{year}-{month + 1:02d}"


class MesHistorico(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    competencia: str = Field(..., description="Competência YYYY-MM — janela 2026-2033 (LC 214/2025, Art. 348)")
    rbt12_no_mes: Decimal = Field(..., gt=Decimal("0"), description="RBT12 vigente neste mês (LC 123/2006, Art. 3º, §1º)")
    folha_mes: Decimal = Field(..., ge=Decimal("0"), description="Folha de salários do mês (LC 123/2006, Art. 18, § 24)")
    folha_12m_no_mes: Decimal = Field(..., ge=Decimal("0"), description="Folha acumulada 12m vigente neste mês (base do Fator R)")
    operacoes: List[OperacaoFiscal] = Field(..., min_length=1, description="Operações fiscais do mês (mínimo 1)")

    @field_validator("competencia")
    @classmethod
    def validar_competencia(cls, v: str) -> str:
        if not _COMPETENCIA_RE.match(v):
            raise ValueError(
                f"Competência '{v}' inválida. Formato YYYY-MM, janela 2026-2033. "
                "LC 214/2025, Art. 348 — período transicional."
            )
        return v

    @model_validator(mode="after")
    def validar_consistencia_mes(self) -> "MesHistorico":
        if self.folha_12m_no_mes < self.folha_mes:
            raise ValueError(
                f"folha_12m_no_mes ({self.folha_12m_no_mes}) não pode ser menor que "
                f"folha_mes ({self.folha_mes}). Acumulado 12m >= mês corrente."
            )
        year = int(self.competencia[:4])
        month = int(self.competencia[5:7])
        for op in self.operacoes:
            if op.data_emissao.year != year or op.data_emissao.month != month:
                raise ValueError(
                    f"Operação com data_emissao {op.data_emissao} não pertence à "
                    f"competência {self.competencia}."
                )
        return self


class HistoricoSeisMeses(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fornecedora_base: EmpresaFornecedora = Field(
        ...,
        description="Dados base da empresa — representa o estado atual (último mês do histórico)",
    )
    compradora_padrao: EmpresaCompradora = Field(
        ...,
        description="Compradora padrão aplicada a todos os meses",
    )
    meses: List[MesHistorico] = Field(
        ...,
        min_length=6,
        max_length=6,
        description="Exatamente 6 meses consecutivos em ordem cronológica crescente",
    )

    @model_validator(mode="after")
    def validar_historico(self) -> "HistoricoSeisMeses":
        # Meses devem ser consecutivos sem lacunas
        for i in range(1, len(self.meses)):
            esperado = _next_competencia(self.meses[i - 1].competencia)
            if self.meses[i].competencia != esperado:
                raise ValueError(
                    f"Meses não consecutivos: esperado '{esperado}' após "
                    f"'{self.meses[i - 1].competencia}', encontrado '{self.meses[i].competencia}'."
                )
        # RBT12 do último mês deve coincidir com fornecedora_base.faturamento_12m
        ultimo_rbt12 = self.meses[-1].rbt12_no_mes
        base_rbt12 = self.fornecedora_base.faturamento_12m
        if ultimo_rbt12 != base_rbt12:
            raise ValueError(
                f"fornecedora_base.faturamento_12m ({base_rbt12}) deve ser igual ao "
                f"rbt12_no_mes do último mês ({ultimo_rbt12}). "
                "LC 123/2006, Art. 3º, §1º — RBT12 é a base de cálculo vigente."
            )
        return self
