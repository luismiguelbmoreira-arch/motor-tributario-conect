# -*- coding: utf-8 -*-
"""
test_elegibilidade_societaria.py — Testes WS6 Etapa 2

Cobre os 36 cruzamentos da matriz (9 tipos × 4 regimes) + funções helper.
Garante que cada combinação tem base legal e que vetadas têm motivo.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.elegibilidade_societaria import (
    Elegibilidade,
    elegibilidade,
    regimes_permitidos,
    tipos_para_regime,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Combinações VÁLIDAS (esperadas pelo user em sua matriz)
# ─────────────────────────────────────────────────────────────────────────────

class TestCombinacoesValidas:

    @pytest.mark.parametrize("tipo,regime", [
        ("EI", "SIMPLES"), ("EI", "PRESUMIDO"), ("EI", "REAL"),
        ("SLU", "SIMPLES"), ("SLU", "PRESUMIDO"), ("SLU", "REAL"),
        ("LTDA", "SIMPLES"), ("LTDA", "PRESUMIDO"), ("LTDA", "REAL"),
        ("SS", "SIMPLES"), ("SS", "PRESUMIDO"), ("SS", "REAL"),
        ("SA", "PRESUMIDO"), ("SA", "REAL"),
        ("COOPERATIVA", "PRESUMIDO"), ("COOPERATIVA", "REAL"),
        ("ASSOCIACAO", "REAL"), ("ASSOCIACAO", "IMUNE"),
        ("FUNDACAO", "REAL"), ("FUNDACAO", "IMUNE"),
        ("ORGANIZACAO_RELIGIOSA", "REAL"), ("ORGANIZACAO_RELIGIOSA", "IMUNE"),
    ])
    def test_combinacao_valida(self, tipo, regime):
        e = elegibilidade(tipo, regime)
        assert e.valido is True
        assert e.base_legal != ""
        assert e.motivo is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Combinações VEDADAS — cada vedação cita lei
# ─────────────────────────────────────────────────────────────────────────────

class TestCombinacoesVedadas:

    @pytest.mark.parametrize("tipo,regime,fragmento_lei", [
        ("EI", "IMUNE", "150 VI c"),
        ("SLU", "IMUNE", "150 VI c"),
        ("LTDA", "IMUNE", "150 VI c"),
        ("SS", "IMUNE", "150 VI c"),
        ("SA", "SIMPLES", "Art. 3º §4º X"),
        ("SA", "IMUNE", "150 VI c"),
        ("COOPERATIVA", "SIMPLES", "Art. 3º"),
        ("COOPERATIVA", "IMUNE", "5.764/71"),
        ("ASSOCIACAO", "SIMPLES", "Art. 3º"),
        ("ASSOCIACAO", "PRESUMIDO", "9.718/98"),
        ("FUNDACAO", "SIMPLES", "Art. 3º"),
        ("FUNDACAO", "PRESUMIDO", "9.718/98"),
        ("ORGANIZACAO_RELIGIOSA", "SIMPLES", "Art. 3º"),
        ("ORGANIZACAO_RELIGIOSA", "PRESUMIDO", "9.718/98"),
    ])
    def test_combinacao_vedada_tem_motivo_e_lei(self, tipo, regime, fragmento_lei):
        e = elegibilidade(tipo, regime)
        assert e.valido is False
        assert e.motivo is not None and len(e.motivo) > 10
        assert fragmento_lei in e.base_legal


# ─────────────────────────────────────────────────────────────────────────────
# 3. Casos cirúrgicos da matriz do user (linha-a-linha)
# ─────────────────────────────────────────────────────────────────────────────

class TestMatrizUserExata:

    def test_sa_no_simples_eh_vedada(self):
        e = elegibilidade("SA", "SIMPLES")
        assert e.valido is False
        assert "ações" in e.motivo.lower() or "vedada" in e.motivo.lower()

    def test_cooperativa_no_simples_aponta_excecao_consumo(self):
        e = elegibilidade("COOPERATIVA", "SIMPLES")
        assert e.valido is False
        assert e.observacao is not None
        assert "consumo" in e.observacao.lower()

    def test_associacao_imune_lista_ctn_art14(self):
        e = elegibilidade("ASSOCIACAO", "IMUNE")
        assert e.valido is True
        assert any("CTN Art. 14" in c for c in e.condicoes)
        assert "150 VI c" in e.base_legal

    def test_fundacao_imune_lista_finalidade_estatutaria(self):
        e = elegibilidade("FUNDACAO", "IMUNE")
        assert e.valido is True
        assert any("CC Art. 62" in c for c in e.condicoes)

    def test_organizacao_religiosa_imune_cita_150_vi_b(self):
        e = elegibilidade("ORGANIZACAO_RELIGIOSA", "IMUNE")
        assert e.valido is True
        assert "150 VI b" in e.base_legal

    def test_ltda_real_observa_obrigatoriedade(self):
        e = elegibilidade("LTDA", "REAL")
        assert e.valido is True
        assert e.observacao is not None
        assert "78M" in e.observacao or "Art. 14" in e.observacao


# ─────────────────────────────────────────────────────────────────────────────
# 4. Imutabilidade do schema Pydantic
# ─────────────────────────────────────────────────────────────────────────────

class TestImutabilidade:

    def test_elegibilidade_eh_frozen(self):
        e = elegibilidade("EI", "SIMPLES")
        with pytest.raises((ValueError, TypeError)):
            e.valido = False  # type: ignore[misc]

    def test_combinacao_invalida_levanta_keyerror(self):
        with pytest.raises(KeyError, match="não mapeada"):
            elegibilidade("FOO", "BAR")  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Helpers: regimes_permitidos / tipos_para_regime
# ─────────────────────────────────────────────────────────────────────────────

class TestHelpers:

    def test_regimes_permitidos_ei(self):
        regimes = regimes_permitidos("EI")
        assert set(regimes) == {"SIMPLES", "PRESUMIDO", "REAL"}
        assert "IMUNE" not in regimes

    def test_regimes_permitidos_sa(self):
        regimes = regimes_permitidos("SA")
        assert set(regimes) == {"PRESUMIDO", "REAL"}
        assert "SIMPLES" not in regimes

    def test_regimes_permitidos_associacao(self):
        regimes = regimes_permitidos("ASSOCIACAO")
        assert set(regimes) == {"REAL", "IMUNE"}

    def test_tipos_para_regime_simples(self):
        tipos = tipos_para_regime("SIMPLES")
        assert set(tipos) == {"EI", "SLU", "LTDA", "SS"}
        assert "SA" not in tipos
        assert "COOPERATIVA" not in tipos
        assert "ASSOCIACAO" not in tipos

    def test_tipos_para_regime_imune(self):
        tipos = tipos_para_regime("IMUNE")
        assert set(tipos) == {"ASSOCIACAO", "FUNDACAO", "ORGANIZACAO_RELIGIOSA"}

    def test_tipos_para_regime_presumido(self):
        tipos = tipos_para_regime("PRESUMIDO")
        # Empresas com fins lucrativos (não imunes/cooperativas-vedadas-no-simples)
        assert {"EI", "SLU", "LTDA", "SS", "SA", "COOPERATIVA"}.issubset(set(tipos))
        # Sem fins lucrativos não vão pra Presumido
        assert "ASSOCIACAO" not in tipos
        assert "FUNDACAO" not in tipos
        assert "ORGANIZACAO_RELIGIOSA" not in tipos


# ─────────────────────────────────────────────────────────────────────────────
# 6. Cobertura completa (36 células — todas mapeadas)
# ─────────────────────────────────────────────────────────────────────────────

class TestCoberturaTotal:

    def test_todas_36_combinacoes_mapeadas(self):
        tipos = ("EI", "SLU", "LTDA", "SS", "SA", "COOPERATIVA",
                 "ASSOCIACAO", "FUNDACAO", "ORGANIZACAO_RELIGIOSA")
        regimes = ("SIMPLES", "PRESUMIDO", "REAL", "IMUNE")
        for tipo in tipos:
            for regime in regimes:
                resultado = elegibilidade(tipo, regime)  # type: ignore[arg-type]
                assert isinstance(resultado, Elegibilidade)
                assert resultado.base_legal  # não vazio
