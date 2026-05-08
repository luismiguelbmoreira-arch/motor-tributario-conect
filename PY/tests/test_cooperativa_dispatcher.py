# -*- coding: utf-8 -*-
"""
tests/test_cooperativa_dispatcher.py — WS6 Etapa 5a
Integração: MotorReformaTributaria instancia CooperativaOverlay quando
tipo_societario='COOPERATIVA' e devolve via obter_overlay_cooperativa().

BASE LEGAL:
  - LC 214/2025 Art. 271 (opt-in alíquota zero IBS/CBS)
  - Lei 5.764/71 Arts. 79, 87 caput, 111 (ato cooperativo + segregação)

Rode com: pytest PY/tests/test_cooperativa_dispatcher.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.motor_tributario import MotorReformaTributaria  # noqa: E402
from core.regimes.cooperativa import CooperativaOverlay  # noqa: E402
from schemas.motor import (  # noqa: E402
    EmpresaCompradora,
    EmpresaFornecedora,
    OperacaoFiscal,
)


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def operacao():
    return OperacaoFiscal(
        data_emissao=date(2027, 6, 15),
        valor_operacao=Decimal("1000.00"),
        ncm_nbs="84713012",
    )


@pytest.fixture
def compradora():
    return EmpresaCompradora(tipo="B2B_CONTRIBUINTE", uf_destino="SP")


@pytest.fixture
def cooperativa_consumo_presumido():
    return EmpresaFornecedora(
        cnpj="33000167000101",
        razao_social="COOPERATIVA DE CONSUMO TESTE LTDA",
        regime="PRESUMIDO",
        cnae_principal="4711301",
        uf_origem="SP",
        faturamento_12m=Decimal("3000000.00"),
        tipo_societario="COOPERATIVA",
        subtipo_cooperativa="CONSUMO",
        receita_ato_cooperativo=Decimal("2400000.00"),
        receita_ato_nao_cooperativo=Decimal("600000.00"),
    )


@pytest.fixture
def cooperativa_producao_real_optante():
    return EmpresaFornecedora(
        cnpj="33000167000101",
        razao_social="COOPERATIVA DE PRODUCAO TESTE",
        regime="REAL",
        cnae_principal="1011201",
        uf_origem="SP",
        faturamento_12m=Decimal("100000000.00"),
        tipo_societario="COOPERATIVA",
        subtipo_cooperativa="PRODUCAO",
        optante_art271_cbs_ibs=True,
        data_opcao_art271=date(2026, 12, 1),
        receita_ato_cooperativo=Decimal("80000000.00"),
        receita_ato_nao_cooperativo=Decimal("20000000.00"),
    )


@pytest.fixture
def empresa_ltda_presumido():
    return EmpresaFornecedora(
        cnpj="11222333000181",
        razao_social="LTDA TESTE",
        regime="PRESUMIDO",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("3000000.00"),
        tipo_societario="LTDA",
    )


# ─────────────────────────────────────────────────────────────────────────────
# DISPATCHER — overlay instanciado para cooperativa, None pra outros
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaDispatcher:
    """MotorReformaTributaria instancia overlay quando tipo_societario=COOPERATIVA."""

    def test_motor_instancia_overlay_para_cooperativa(
        self, cooperativa_consumo_presumido, compradora, operacao
    ):
        motor = MotorReformaTributaria(
            fornecedora=cooperativa_consumo_presumido,
            compradora=compradora,
            operacao=operacao,
        )
        overlay = motor.obter_overlay_cooperativa()
        assert overlay is not None
        assert isinstance(overlay, CooperativaOverlay)

    def test_motor_nao_instancia_overlay_para_ltda(
        self, empresa_ltda_presumido, compradora, operacao
    ):
        motor = MotorReformaTributaria(
            fornecedora=empresa_ltda_presumido,
            compradora=compradora,
            operacao=operacao,
        )
        assert motor.obter_overlay_cooperativa() is None

    def test_engine_regular_continua_funcionando_com_overlay_presente(
        self, cooperativa_consumo_presumido, compradora, operacao
    ):
        # Cooperativa de consumo no Presumido → engine LucroPresumidoEngine
        # continua sendo instanciado (overlay convive, não substitui).
        motor = MotorReformaTributaria(
            fornecedora=cooperativa_consumo_presumido,
            compradora=compradora,
            operacao=operacao,
        )
        engine = motor.obter_engine_regime()
        assert engine is not None
        assert engine.REGIME_ACEITO == "PRESUMIDO"

    def test_engine_real_continua_funcionando_em_cooperativa_producao(
        self, cooperativa_producao_real_optante, compradora, operacao
    ):
        motor = MotorReformaTributaria(
            fornecedora=cooperativa_producao_real_optante,
            compradora=compradora,
            operacao=operacao,
        )
        engine = motor.obter_engine_regime()
        assert engine is not None
        assert engine.REGIME_ACEITO == "REAL"


# ─────────────────────────────────────────────────────────────────────────────
# TRILHA UNIFICADA — engine + overlay gravam na mesma lista
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaTrilhaUnificada:
    """Engine regular + overlay cooperativa gravam na mesma trilha de auditoria."""

    def test_overlay_grava_na_trilha_unica(
        self, cooperativa_consumo_presumido, compradora, operacao
    ):
        motor = MotorReformaTributaria(
            fornecedora=cooperativa_consumo_presumido,
            compradora=compradora,
            operacao=operacao,
        )
        # Simula resultado mínimo do engine regular
        resultado_eng = {
            "regime": "PRESUMIDO",
            "ibs_total": Decimal("1000"),
            "cbs_total": Decimal("500"),
            "base_calculo": Decimal("3000000"),
        }
        antes = len(motor.trilha_auditoria)
        overlay = motor.obter_overlay_cooperativa()
        overlay.aplicar(resultado_eng, data_emissao=operacao.data_emissao)
        depois = len(motor.trilha_auditoria)
        assert depois > antes, "overlay deveria adicionar eventos à trilha unificada"

    def test_trilha_contem_segregacao_e_fora_incidencia(
        self, cooperativa_producao_real_optante, compradora, operacao
    ):
        motor = MotorReformaTributaria(
            fornecedora=cooperativa_producao_real_optante,
            compradora=compradora,
            operacao=operacao,
        )
        overlay = motor.obter_overlay_cooperativa()
        overlay.aplicar(
            {"regime": "REAL", "ibs_total": Decimal("8000000"), "cbs_total": Decimal("4000000")},
            data_emissao=operacao.data_emissao,
        )
        ids = {e["id"] for e in motor.trilha_auditoria}
        assert "COOPERATIVA_SEGREGACAO_RECEITAS" in ids
        assert "ALERTA_COOPERATIVA_FORA_INCIDENCIA_ART6" in ids
        assert "AJUSTE_COOPERATIVA_ART271_ALIQUOTA_ZERO" in ids


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSÃO — IMUNE/REAL/PRESUMIDO/MEI/SIMPLES sem cooperativa não quebram
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaSemRegressao:
    """Cooperativa não pode introduzir regressão nos engines existentes."""

    def test_ltda_presumido_sem_overlay(
        self, empresa_ltda_presumido, compradora, operacao
    ):
        motor = MotorReformaTributaria(
            fornecedora=empresa_ltda_presumido,
            compradora=compradora,
            operacao=operacao,
        )
        # Sem overlay; engine regular intacto
        assert motor.obter_overlay_cooperativa() is None
        engine = motor.obter_engine_regime()
        assert engine is not None
        assert engine.REGIME_ACEITO == "PRESUMIDO"
