# -*- coding: utf-8 -*-
"""
versioned_rule.py — Versionamento Normativo de Constantes Fiscais

WS10 do Plano de Refinamento Final. Implementa Rail R3 (versão normativa)
e Rail R8 (consistência temporal).

PROBLEMA QUE RESOLVE:
  Constantes fiscais mudam ao longo do tempo (Lei 12.814/13 alterou o teto
  do Lucro Presumido; LC 155/2016 alterou o teto do Simples). Se o motor
  for usado em 2027 para refazer cálculo de operação 2025, a constante
  precisa ser a vigente em 2025 — não a atual.

DECISÃO ARQUITETURAL:
  - VersionedRule[T] mantém valor + vigência + lei
  - Função lookup() encontra o item vigente em uma data
  - Sem norma vigente na data, levanta ValueError (Rail R2 — sem extrapolação)
  - Janela coberta: 2024-01-01 a 2033-12-31 (decisão Q12)

INTERAÇÃO COM API ANTIGA:
  Constantes monetárias do tabelas_simples.py podem permanecer como
  Decimal direto (valor de hoje) e adicionar VersionedRule paralelo. O
  caller que precisa precisão temporal usa lookup(); o resto continua
  funcionando.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Generic, Optional, Sequence, TypeVar

from pydantic import BaseModel, ConfigDict, model_validator

T = TypeVar("T")


class VersionedRule(BaseModel, Generic[T]):
    """Constante fiscal com vigência declarada."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    valor: T
    vigencia_inicio: date
    vigencia_fim: Optional[date] = None
    lei: str
    url_planalto: Optional[str] = None
    observacao: Optional[str] = None

    @model_validator(mode="after")
    def _vigencia_coerente(self):
        if self.vigencia_fim is not None and self.vigencia_fim < self.vigencia_inicio:
            raise ValueError(
                f"vigencia_fim ({self.vigencia_fim}) anterior a "
                f"vigencia_inicio ({self.vigencia_inicio})"
            )
        return self

    def vigente_em(self, data: date) -> bool:
        if data < self.vigencia_inicio:
            return False
        if self.vigencia_fim is not None and data > self.vigencia_fim:
            return False
        return True


def lookup(versionados: Sequence[VersionedRule[T]], data: date) -> VersionedRule[T]:
    """
    Retorna a regra vigente em `data`.

    Se houver mais de uma vigente (sobreposição), escolhe a com
    `vigencia_inicio` mais recente — fonte mais nova vence.

    Raises:
        ValueError: se nenhuma regra estiver vigente em `data`.
                    Rail R2: sem norma publicada, não há cálculo.
    """
    candidatos = [r for r in versionados if r.vigente_em(data)]
    if not candidatos:
        raise ValueError(
            f"Nenhuma regra vigente em {data.isoformat()}. "
            f"Verifique se a data está dentro da janela 2024-2033 (Q12 do plano) "
            f"e se a lei aplicável foi cadastrada."
        )
    return max(candidatos, key=lambda r: r.vigencia_inicio)


def valor_em(versionados: Sequence[VersionedRule[T]], data: date) -> T:
    """Atalho: retorna apenas o valor da regra vigente em `data`."""
    return lookup(versionados, data).valor


# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES VERSIONADAS — PILOTO WS10
# Cada lista declara o histórico legislativo da constante. Janela alvo:
# 2024-01-01 a 2033-12-31 (Q12). Vigências anteriores (2018+) preservadas
# para cobrir PGDAS-D antigos que ainda possam ser auditados.
# ─────────────────────────────────────────────────────────────────────────────

# Teto do Simples Nacional (LC 123/2006 Art. 3º II)
# LC 155/2016 elevou o teto de R$ 3,6M para R$ 4,8M, vigência 01/01/2018.
TETO_SIMPLES_NACIONAL_VERSIONADO: list[VersionedRule[Decimal]] = [
    VersionedRule(
        valor=Decimal("4800000.00"),
        vigencia_inicio=date(2018, 1, 1),
        vigencia_fim=None,
        lei="LC 123/2006 Art. 3º II (redação LC 155/2016)",
        url_planalto="https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp155.htm",
    ),
]

# Sublimite ICMS/ISS (LC 123/2006 Art. 13 § 1º)
# Estados com RBT12 acima do sublimite saem do regime unificado em ICMS/ISS.
SUBLIMITE_ICMS_ISS_VERSIONADO: list[VersionedRule[Decimal]] = [
    VersionedRule(
        valor=Decimal("3600000.00"),
        vigencia_inicio=date(2018, 1, 1),
        vigencia_fim=None,
        lei="LC 123/2006 Art. 13 § 1º (redação LC 155/2016)",
        url_planalto="https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp155.htm",
    ),
]

# Teto MEI (LC 123/2006 Art. 18-A § 1º)
# Mantido em R$ 81.000 desde 2018; PLP 108/2021 propõe reajuste mas não foi
# sancionado até 25/04/2026.
TETO_MEI_VERSIONADO: list[VersionedRule[Decimal]] = [
    VersionedRule(
        valor=Decimal("81000.00"),
        vigencia_inicio=date(2018, 1, 1),
        vigencia_fim=None,
        lei="LC 123/2006 Art. 18-A § 1º (redação LC 155/2016)",
        url_planalto="https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp155.htm",
    ),
]

# Limite do Lucro Presumido (Lei 9.718/98 Art. 13)
# Lei 12.814/13 elevou de R$ 48M para R$ 78M, vigência 01/01/2014.
LIMITE_LUCRO_PRESUMIDO_VERSIONADO: list[VersionedRule[Decimal]] = [
    VersionedRule(
        valor=Decimal("78000000.00"),
        vigencia_inicio=date(2014, 1, 1),
        vigencia_fim=None,
        lei="Lei 9.718/98 Art. 13 (redação Lei 12.814/13)",
        url_planalto="https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2013/lei/l12814.htm",
    ),
]


def alerta_90_percent_teto_em(data: date) -> Decimal:
    """
    Zona de alerta: 90% do teto Simples vigente na data.
    Derivado do TETO_SIMPLES_NACIONAL_VERSIONADO — não duplica vigência.
    """
    teto = valor_em(TETO_SIMPLES_NACIONAL_VERSIONADO, data)
    return (teto * Decimal("0.90"))
