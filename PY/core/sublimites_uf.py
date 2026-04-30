# -*- coding: utf-8 -*-
"""
sublimites_uf.py — Sublimite ICMS/ISS por UF, versionado por ano-calendário.

Base legal:
- LC 123/2006, Art. 13-A: teto ICMS/ISS no Simples = R$ 3.600.000,00.
- LC 123/2006, Art. 19, caput: UFs com PIB ≤ 1% podem optar por R$ 1.800.000,00.
- LC 123/2006, Art. 19, § 4º: UF omissa fica obrigatoriamente em R$ 3.600.000,00.

Quem decide ano-a-ano: CGSN, via Portaria publicada em out/nov do ano anterior.
Validação Escrivão (29/04/2026):
- Ano 2025: Portaria CGSN 49/2024 (DOU 27/11/2024) — todas as 27 UFs em padrão.
- Ano 2026: Portaria CGSN 54/2025 (DOU 19/11/2025) — todas as 27 UFs em padrão.

Anos 2027+ não modelados (Rail R2 — sem Portaria publicada, sem código).
"""

from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.versioned_rule import VersionedRule, lookup

UFS_BRASIL: frozenset = frozenset({
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR",
    "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
})

# Heurística operacional R7-extended: zona de aviso quando RBT12 ≥ 90% do sublimite.
_PERCENTUAL_AVISO = Decimal("0.90")


class SublimiteVigente(BaseModel):
    """
    Sublimite ICMS/ISS vigente num ano-calendário.

    `ufs_reduzidas` lista quais UFs optaram pelo R$ 1,8M naquele ano. Default
    (Art. 19 § 4º) = todas as outras ficam em `padrao` (R$ 3,6M).
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    padrao: Decimal = Field(..., description="LC 123/2006 Art. 13-A + Art. 19 § 4º")
    reduzido: Decimal = Field(..., description="LC 123/2006 Art. 19 caput (PIB ≤ 1%)")
    ufs_reduzidas: frozenset = Field(
        default_factory=frozenset,
        description="UFs que optaram pelo reduzido naquele ano-calendário",
    )

    @field_validator("ufs_reduzidas")
    @classmethod
    def _ufs_validas(cls, v: frozenset) -> frozenset:
        invalidas = v - UFS_BRASIL
        if invalidas:
            raise ValueError(f"UFs inválidas em ufs_reduzidas: {sorted(invalidas)}.")
        return v


# Sublimites firmes ano-a-ano. Histórico de Portarias CGSN.
SUBLIMITES_VIGENTES: List[VersionedRule[SublimiteVigente]] = [
    VersionedRule(
        valor=SublimiteVigente(
            padrao=Decimal("3600000.00"),
            reduzido=Decimal("1800000.00"),
            ufs_reduzidas=frozenset(),
        ),
        vigencia_inicio=date(2025, 1, 1),
        vigencia_fim=date(2025, 12, 31),
        lei="LC 123/2006 Art. 13-A + Art. 19 § 4º; Portaria CGSN 49/2024 (DOU 27/11/2024)",
        url_planalto="https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp123.htm",
        observacao="Todas as 27 UFs em sublimite padrão R$ 3.600.000.",
    ),
    VersionedRule(
        valor=SublimiteVigente(
            padrao=Decimal("3600000.00"),
            reduzido=Decimal("1800000.00"),
            ufs_reduzidas=frozenset(),
        ),
        vigencia_inicio=date(2026, 1, 1),
        vigencia_fim=date(2026, 12, 31),
        lei="LC 123/2006 Art. 13-A + Art. 19 § 4º; Portaria CGSN 54/2025 (DOU 19/11/2025)",
        url_planalto="https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp123.htm",
        observacao="Todas as 27 UFs em sublimite padrão R$ 3.600.000.",
    ),
]


class AlertaSublimiteUF(BaseModel):
    """Alerta R7-extended: RBT12 atingiu zona de aviso (≥ 90%) ou estourou."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    uf: str = Field(..., min_length=2, max_length=2)
    rbt12: Decimal
    sublimite_aplicavel: Decimal
    percentual_atingido: Decimal
    nivel: Literal["AVISO", "CRITICO"]
    amparo_legal: str


def _validar_uf(uf: str) -> str:
    uf_norm = uf.upper().strip()
    if uf_norm not in UFS_BRASIL:
        raise ValueError(f"UF '{uf}' inválida.")
    return uf_norm


def sublimite_para_uf(uf: str, data: date) -> Decimal:
    """
    Sublimite ICMS/ISS aplicável à UF na data.

    LC 123/2006 Art. 13-A (padrão) + Art. 19 caput (reduzido) + Art. 19 § 4º (default).
    """
    uf_norm = _validar_uf(uf)
    vigente = lookup(SUBLIMITES_VIGENTES, data).valor
    return vigente.reduzido if uf_norm in vigente.ufs_reduzidas else vigente.padrao


def alerta_migracao_obrigatoria(
    rbt12: Decimal,
    uf: str,
    data: date,
) -> Optional[AlertaSublimiteUF]:
    """
    Alerta quando RBT12 ≥ 90% do sublimite da UF.

    AVISO: 90% ≤ percentual < 100%.
    CRITICO: percentual ≥ 100% (ICMS/ISS sai do DAS no mês subsequente).

    Retorna None se RBT12 abaixo da zona de aviso.
    """
    if rbt12 < Decimal("0"):
        raise ValueError(f"rbt12 deve ser >= 0, recebido {rbt12}.")

    uf_norm = _validar_uf(uf)
    sublimite = sublimite_para_uf(uf_norm, data)
    percentual = (rbt12 / sublimite).quantize(Decimal("0.0001"))

    if percentual < _PERCENTUAL_AVISO:
        return None

    nivel: Literal["AVISO", "CRITICO"] = "CRITICO" if percentual >= Decimal("1.0") else "AVISO"
    return AlertaSublimiteUF(
        uf=uf_norm,
        rbt12=rbt12,
        sublimite_aplicavel=sublimite,
        percentual_atingido=percentual,
        nivel=nivel,
        amparo_legal=lookup(SUBLIMITES_VIGENTES, data).lei,
    )
