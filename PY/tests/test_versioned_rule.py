# -*- coding: utf-8 -*-
"""
test_versioned_rule.py — Testes WS10 do versionamento normativo

Cobre Rails R3 (versão normativa) e R8 (consistência temporal):
  - VersionedRule com vigência fechada e aberta
  - lookup() retorna vigente, levanta ValueError fora de qualquer vigência
  - lookup() escolhe vigência mais recente em sobreposição
  - vigencia_fim < vigencia_inicio é rejeitada pelo Pydantic
  - Constantes piloto (TETO Simples, Sublimite, MEI, Lucro Presumido)
    funcionam em datas chave (2024, hoje, 2030, 2033)
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.versioned_rule import (
    LIMITE_LUCRO_PRESUMIDO_VERSIONADO,
    SUBLIMITE_ICMS_ISS_VERSIONADO,
    TETO_MEI_VERSIONADO,
    TETO_SIMPLES_NACIONAL_VERSIONADO,
    VersionedRule,
    alerta_90_percent_teto_em,
    lookup,
    valor_em,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Schema VersionedRule
# ─────────────────────────────────────────────────────────────────────────────

class TestVersionedRuleSchema:

    def test_vigencia_aberta_aceita_fim_none(self):
        regra = VersionedRule(
            valor=Decimal("100"),
            vigencia_inicio=date(2024, 1, 1),
            vigencia_fim=None,
            lei="Lei X",
        )
        assert regra.vigencia_fim is None
        assert regra.vigente_em(date(2026, 6, 15)) is True

    def test_vigencia_fechada(self):
        regra = VersionedRule(
            valor=Decimal("50"),
            vigencia_inicio=date(2018, 1, 1),
            vigencia_fim=date(2023, 12, 31),
            lei="Lei Y",
        )
        assert regra.vigente_em(date(2020, 1, 1)) is True
        assert regra.vigente_em(date(2024, 1, 1)) is False
        assert regra.vigente_em(date(2017, 12, 31)) is False

    def test_vigencia_fim_anterior_a_inicio_rejeita(self):
        with pytest.raises((ValueError,)):
            VersionedRule(
                valor=Decimal("1"),
                vigencia_inicio=date(2026, 1, 1),
                vigencia_fim=date(2025, 12, 31),
                lei="Lei inválida",
            )

    def test_borda_vigencia_inicio_inclusiva(self):
        """vigente_em(vigencia_inicio) deve ser True."""
        regra = VersionedRule(
            valor=Decimal("1"),
            vigencia_inicio=date(2024, 1, 1),
            lei="Lei",
        )
        assert regra.vigente_em(date(2024, 1, 1)) is True

    def test_borda_vigencia_fim_inclusiva(self):
        """vigente_em(vigencia_fim) deve ser True (último dia ainda vale)."""
        regra = VersionedRule(
            valor=Decimal("1"),
            vigencia_inicio=date(2018, 1, 1),
            vigencia_fim=date(2023, 12, 31),
            lei="Lei",
        )
        assert regra.vigente_em(date(2023, 12, 31)) is True

    def test_frozen_imutavel(self):
        regra = VersionedRule(
            valor=Decimal("1"),
            vigencia_inicio=date(2024, 1, 1),
            lei="Lei",
        )
        with pytest.raises((ValueError, TypeError)):
            regra.valor = Decimal("2")  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# 2. lookup() — Rail R8 consistência temporal
# ─────────────────────────────────────────────────────────────────────────────

class TestLookup:

    def _historico_teto_fictício(self) -> list[VersionedRule[Decimal]]:
        return [
            VersionedRule(
                valor=Decimal("3600000.00"),
                vigencia_inicio=date(2012, 1, 1),
                vigencia_fim=date(2017, 12, 31),
                lei="LC 123/2006 (redação original)",
            ),
            VersionedRule(
                valor=Decimal("4800000.00"),
                vigencia_inicio=date(2018, 1, 1),
                vigencia_fim=None,
                lei="LC 123/2006 (LC 155/2016)",
            ),
        ]

    def test_lookup_retorna_vigente(self):
        hist = self._historico_teto_fictício()
        regra = lookup(hist, date(2026, 4, 25))
        assert regra.valor == Decimal("4800000.00")
        assert "155/2016" in regra.lei

    def test_lookup_retorna_vigente_em_periodo_antigo(self):
        hist = self._historico_teto_fictício()
        regra = lookup(hist, date(2015, 6, 15))
        assert regra.valor == Decimal("3600000.00")

    def test_lookup_data_anterior_a_qualquer_vigencia_levanta(self):
        hist = self._historico_teto_fictício()
        with pytest.raises(ValueError, match="Nenhuma regra vigente"):
            lookup(hist, date(2010, 1, 1))

    def test_lookup_lista_vazia_levanta(self):
        with pytest.raises(ValueError):
            lookup([], date(2026, 4, 25))

    def test_lookup_sobreposicao_escolhe_mais_recente(self):
        """Se 2 vigências cobrem a data, vence a com vigencia_inicio mais nova."""
        hist = [
            VersionedRule(
                valor=Decimal("100"),
                vigencia_inicio=date(2020, 1, 1),
                vigencia_fim=None,
                lei="Lei A",
            ),
            VersionedRule(
                valor=Decimal("200"),
                vigencia_inicio=date(2024, 1, 1),
                vigencia_fim=None,
                lei="Lei B (mais nova)",
            ),
        ]
        regra = lookup(hist, date(2026, 1, 1))
        assert regra.valor == Decimal("200")

    def test_valor_em_atalho(self):
        hist = self._historico_teto_fictício()
        assert valor_em(hist, date(2020, 1, 1)) == Decimal("4800000.00")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Constantes piloto migradas
# ─────────────────────────────────────────────────────────────────────────────

class TestConstantesPiloto:

    def test_teto_simples_hoje(self):
        teto = valor_em(TETO_SIMPLES_NACIONAL_VERSIONADO, date(2026, 4, 25))
        assert teto == Decimal("4800000.00")

    def test_teto_simples_em_2024(self):
        teto = valor_em(TETO_SIMPLES_NACIONAL_VERSIONADO, date(2024, 1, 1))
        assert teto == Decimal("4800000.00")

    def test_teto_simples_em_2033_fim_transicao(self):
        teto = valor_em(TETO_SIMPLES_NACIONAL_VERSIONADO, date(2033, 12, 31))
        assert teto == Decimal("4800000.00")

    def test_teto_simples_data_pre_lc155_levanta(self):
        """Antes de 01/01/2018 o teto era R$ 3,6M (LC 155/2016 ainda não vigorava)."""
        with pytest.raises(ValueError):
            valor_em(TETO_SIMPLES_NACIONAL_VERSIONADO, date(2017, 12, 31))

    def test_sublimite_icms_iss_hoje(self):
        sublimite = valor_em(SUBLIMITE_ICMS_ISS_VERSIONADO, date(2026, 4, 25))
        assert sublimite == Decimal("3600000.00")

    def test_teto_mei_hoje(self):
        teto = valor_em(TETO_MEI_VERSIONADO, date(2026, 4, 25))
        assert teto == Decimal("81000.00")

    def test_limite_lucro_presumido_hoje(self):
        limite = valor_em(LIMITE_LUCRO_PRESUMIDO_VERSIONADO, date(2026, 4, 25))
        assert limite == Decimal("78000000.00")

    def test_limite_presumido_em_2013_pre_lei_12814_levanta(self):
        """Antes de 01/01/2014 o limite era R$ 48M."""
        with pytest.raises(ValueError):
            valor_em(LIMITE_LUCRO_PRESUMIDO_VERSIONADO, date(2013, 12, 31))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Derivado: alerta 90% do teto
# ─────────────────────────────────────────────────────────────────────────────

class TestAlerta90PercentTeto:

    def test_alerta_hoje(self):
        alerta = alerta_90_percent_teto_em(date(2026, 4, 25))
        assert alerta == Decimal("4320000.00")

    def test_alerta_em_2030(self):
        """Mesmo valor enquanto LC 155/2016 vigorar."""
        alerta = alerta_90_percent_teto_em(date(2030, 6, 15))
        assert alerta == Decimal("4320000.00")

    def test_alerta_pre_lc155_levanta(self):
        with pytest.raises(ValueError):
            alerta_90_percent_teto_em(date(2017, 1, 1))


# ─────────────────────────────────────────────────────────────────────────────
# 5. Compatibilidade — variável legada do tabelas_simples.py
# ─────────────────────────────────────────────────────────────────────────────

class TestCompatibilidadeAPILegada:

    def test_constante_legada_bate_com_versionada_hoje(self):
        """A constante TETO_SIMPLES_NACIONAL antiga deve bater com a versão
        de hoje, garantindo que migração não introduz drift.
        """
        from core.tabelas_simples import TETO_SIMPLES_NACIONAL

        atual = valor_em(TETO_SIMPLES_NACIONAL_VERSIONADO, date(2026, 4, 25))
        assert TETO_SIMPLES_NACIONAL == atual

    def test_sublimite_legado_bate(self):
        from core.tabelas_simples import SUBLIMITE_ICMS_ISS

        atual = valor_em(SUBLIMITE_ICMS_ISS_VERSIONADO, date(2026, 4, 25))
        assert SUBLIMITE_ICMS_ISS == atual

    def test_alerta_legado_bate(self):
        from core.tabelas_simples import ALERTA_90_PERCENT_TETO

        atual = alerta_90_percent_teto_em(date(2026, 4, 25))
        assert ALERTA_90_PERCENT_TETO == atual
