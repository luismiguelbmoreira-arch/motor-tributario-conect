# -*- coding: utf-8 -*-
"""
tests/test_err_fixes.py — Testes para ERR-013, ERR-014, ERR-015, ERR-016
Projeto: Motor Tributario Conect 2026-2033

Rode com: pytest PY/tests/test_err_fixes.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from core.motor_tributario import (
    EmpresaFornecedora,
    EmpresaCompradora,
    OperacaoFiscal,
    MotorReformaTributaria,
)
from core.regimes.mei import MEIEngine, SM_POR_ANO
from core.regimes.lucro_presumido import LucroPresumidoEngine


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def empresa_mei():
    return EmpresaFornecedora(
        cnpj="07.526.557/0001-00",
        razao_social="MEI TESTE",
        regime="MEI",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("60000.00"),
    )


@pytest.fixture
def empresa_presumida_passageiros():
    """Empresa transporte passageiros — CNAE 4921."""
    return EmpresaFornecedora(
        cnpj="11.222.333/0001-81",
        razao_social="TRANSPORTE PASSAGEIROS LTDA",
        regime="PRESUMIDO",
        cnae_principal="4921301",
        uf_origem="SP",
        faturamento_12m=Decimal("2000000.00"),
    )


@pytest.fixture
def empresa_presumida_carga():
    """Empresa transporte carga — CNAE 4930."""
    return EmpresaFornecedora(
        cnpj="11.222.333/0001-81",
        razao_social="TRANSPORTE CARGA LTDA",
        regime="PRESUMIDO",
        cnae_principal="4911600",
        uf_origem="SP",
        faturamento_12m=Decimal("2000000.00"),
    )


@pytest.fixture
def empresa_simples_nova():
    """Empresa Simples com menos de 12 meses de atividade."""
    return EmpresaFornecedora(
        cnpj="54.657.895/0001-60",
        razao_social="EMPRESA NOVA TESTE",
        regime="SIMPLES",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("300000.00"),
        anexo_simples="I",
        data_inicio_atividade=date(2026, 7, 1),
    )


@pytest.fixture
def empresa_simples():
    return EmpresaFornecedora(
        cnpj="54.657.895/0001-60",
        razao_social="EMPRESA SIMPLES TESTE",
        regime="SIMPLES",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("500000.00"),
        anexo_simples="I",
    )


@pytest.fixture
def compradora():
    return EmpresaCompradora(
        razao_social="COMPRADORA TESTE",
        tipo="B2B_CONTRIBUINTE",
        uf_destino="SP",
    )


@pytest.fixture
def trilha():
    return []


# ─────────────────────────────────────────────────────────────────────────────
# ERR-015 — Presuncao transporte passageiros 16% (nao 8%)
# ─────────────────────────────────────────────────────────────────────────────

class TestERR015PresuncaoPassageiros:
    """
    Valida que CNAEs de transporte de passageiros (4921, 4922, 4929, 4930)
    usam presuncao 16% IRPJ, enquanto transporte carga usa 8%.
    Lei 9.249/1995, Art. 15, par. 1o, III, 'a'.
    """

    def test_cnae_4921_passageiros_16_porcento(self, empresa_presumida_passageiros, trilha):
        """CNAE 4921 (transporte municipal passageiros) = 16% IRPJ."""
        engine = LucroPresumidoEngine(empresa_presumida_passageiros, trilha)
        perc_irpj, perc_csll = engine._obter_percentual_presuncao()
        assert perc_irpj == Decimal("0.16"), f"Esperado 16%, obteve {perc_irpj*100}%"
        assert perc_csll == Decimal("0.12")

    def test_cnae_4922_passageiros_16_porcento(self, trilha):
        """CNAE 4922 (transporte intermunicipal passageiros) = 16% IRPJ."""
        emp = EmpresaFornecedora(
            cnpj="11.222.333/0001-81", razao_social="TESTE", regime="PRESUMIDO",
            cnae_principal="4922101", uf_origem="SP", faturamento_12m=Decimal("1000000"),
        )
        engine = LucroPresumidoEngine(emp, trilha)
        perc_irpj, _ = engine._obter_percentual_presuncao()
        assert perc_irpj == Decimal("0.16")

    def test_cnae_4929_passageiros_16_porcento(self, trilha):
        """CNAE 4929 (outros passageiros) = 16% IRPJ."""
        emp = EmpresaFornecedora(
            cnpj="11.222.333/0001-81", razao_social="TESTE", regime="PRESUMIDO",
            cnae_principal="4929999", uf_origem="SP", faturamento_12m=Decimal("1000000"),
        )
        engine = LucroPresumidoEngine(emp, trilha)
        perc_irpj, _ = engine._obter_percentual_presuncao()
        assert perc_irpj == Decimal("0.16")

    def test_cnae_4930_passageiros_16_porcento(self, trilha):
        """CNAE 4930 (transporte rodoviario passageiros) = 16% IRPJ."""
        emp = EmpresaFornecedora(
            cnpj="11.222.333/0001-81", razao_social="TESTE", regime="PRESUMIDO",
            cnae_principal="4930202", uf_origem="SP", faturamento_12m=Decimal("1000000"),
        )
        engine = LucroPresumidoEngine(emp, trilha)
        perc_irpj, _ = engine._obter_percentual_presuncao()
        assert perc_irpj == Decimal("0.16")

    def test_cnae_49_carga_8_porcento(self, empresa_presumida_carga, trilha):
        """CNAE 49xx (transporte carga - fallback) = 8% IRPJ."""
        engine = LucroPresumidoEngine(empresa_presumida_carga, trilha)
        perc_irpj, _ = engine._obter_percentual_presuncao()
        assert perc_irpj == Decimal("0.08"), f"Carga deveria ser 8%, obteve {perc_irpj*100}%"

    def test_irpj_passageiros_usa_16_porcento(self, empresa_presumida_passageiros, trilha):
        """IRPJ trimestral com receita R$100k deve usar base 16% (R$16k)."""
        engine = LucroPresumidoEngine(empresa_presumida_passageiros, trilha)
        result = engine.calcular_irpj(Decimal("100000.00"), meses=3)
        # Base = 300k * 16% = 48k. IRPJ = 48k * 15% = 7200
        assert result["IRPJ_PRINCIPAL"] == Decimal("7200.00")


# ─────────────────────────────────────────────────────────────────────────────
# ERR-014 — SM_POR_ANO dinamico para MEI
# ─────────────────────────────────────────────────────────────────────────────

class TestERR014MEISalarioMinimo:
    """
    Valida que calcular_das_mensal() usa SM dinamico por ano.
    LC 123/2006, Art. 18-A, par. 3o, I.
    """

    def test_das_2026_default(self, empresa_mei, trilha):
        """Sem argumento ano, usa 2026 (default). SM = R$1621."""
        engine = MEIEngine(empresa_mei, trilha)
        result = engine.calcular_das_mensal("COMERCIO")
        esperado_inss = (SM_POR_ANO[2026] * Decimal("0.05")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        assert result["INSS"] == esperado_inss

    def test_das_2030_sm_diferente(self, empresa_mei, trilha):
        """Ano 2030: SM = R$2124. INSS = 5% * 2124 = R$106.20."""
        engine = MEIEngine(empresa_mei, trilha)
        result = engine.calcular_das_mensal("COMERCIO", ano=2030)
        esperado_inss = (SM_POR_ANO[2030] * Decimal("0.05")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        assert result["INSS"] == esperado_inss
        assert result["DAS_TOTAL"] == esperado_inss + Decimal("5.00")  # + ICMS

    def test_das_2033_ultimo_ano(self, empresa_mei, trilha):
        """Ano 2033: SM = R$2602. INSS = 5% * 2602 = R$130.10."""
        engine = MEIEngine(empresa_mei, trilha)
        result = engine.calcular_das_mensal("SERVICOS", ano=2033)
        esperado_inss = (SM_POR_ANO[2033] * Decimal("0.05")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        assert result["INSS"] == esperado_inss
        assert result["DAS_TOTAL"] == esperado_inss + Decimal("5.00")  # + ISS

    def test_ano_fora_tabela_usa_fallback(self, empresa_mei, trilha):
        """Ano 2040 (fora da tabela): usa ultimo disponivel com alerta."""
        engine = MEIEngine(empresa_mei, trilha)
        result = engine.calcular_das_mensal("COMERCIO", ano=2040)
        # Deve usar SM de 2033 (ultimo disponivel)
        esperado_inss = (SM_POR_ANO[2033] * Decimal("0.05")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        assert result["INSS"] == esperado_inss
        alertas = [e for e in trilha if e.get("tipo") == "ALERTA_SM_EXTRAPOLADO"]
        assert len(alertas) >= 1

    def test_carga_total_usa_ano(self, empresa_mei, trilha):
        """calcular_carga_total_mensal com ano=2030 deve usar SM 2030."""
        engine = MEIEngine(empresa_mei, trilha)
        result = engine.calcular_carga_total_mensal(
            receita_mensal=Decimal("5000.00"),
            categoria="COMERCIO",
            ano=2030,
        )
        esperado_inss = (SM_POR_ANO[2030] * Decimal("0.05")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        assert result["breakdown"]["INSS"] == esperado_inss


# ─────────────────────────────────────────────────────────────────────────────
# ERR-013 — RBT12 proporcionalizada para empresas novas
# ─────────────────────────────────────────────────────────────────────────────

class TestERR013RBT12Proporcional:
    """
    Valida que empresas com < 12 meses de atividade tem RBT12 proporcionalizada.
    LC 123/2006, Art. 3o, par. 2o.
    """

    def test_rbt12_proporcionalizada_6_meses(self, empresa_simples_nova, compradora):
        """Empresa com 6 meses: RBT12 proporcional = (300k/6)*12 = 600k."""
        operacao = OperacaoFiscal(
            data_emissao=date(2027, 1, 15),
            valor_operacao=Decimal("10000.00"),
            ncm_nbs="84818099",
        )
        motor = MotorReformaTributaria(empresa_simples_nova, compradora, operacao)
        rbt12 = motor.rbt12
        # 6 meses de atividade (Jul 2026 -> Jan 2027)
        # RBT12 prop = (300000 / 6) * 12 = 600000
        assert rbt12 == Decimal("600000.00")

    def test_rbt12_sem_proporcionalizar_empresa_antiga(self, empresa_simples, compradora):
        """Empresa sem data_inicio_atividade: RBT12 = valor informado."""
        operacao = OperacaoFiscal(
            data_emissao=date(2027, 1, 15),
            valor_operacao=Decimal("10000.00"),
            ncm_nbs="84818099",
        )
        motor = MotorReformaTributaria(empresa_simples, compradora, operacao)
        rbt12 = motor.rbt12
        assert rbt12 == Decimal("500000.00")

    def test_trilha_registra_proporcionalizacao(self, empresa_simples_nova, compradora):
        """Trilha deve registrar passo RBT12_PROPORCIONAL."""
        operacao = OperacaoFiscal(
            data_emissao=date(2027, 1, 15),
            valor_operacao=Decimal("10000.00"),
            ncm_nbs="84818099",
        )
        motor = MotorReformaTributaria(empresa_simples_nova, compradora, operacao)
        motor.rbt12
        ids = [p.get("id") for p in motor.trilha_auditoria]
        assert "RBT12_PROPORCIONAL" in ids


# ─────────────────────────────────────────────────────────────────────────────
# ERR-016 — Reducao CBS/IBS com Literal
# ─────────────────────────────────────────────────────────────────────────────

class TestERR016ReducaoCBSIBS:
    """
    Valida que o fator de reducao CBS/IBS e aplicado nos calculos IVA.
    LC 214/2025, Arts. 258, 262, 264.
    """

    def _criar_motor(self, reducao: str = "INTEGRAL") -> MotorReformaTributaria:
        fornecedora = EmpresaFornecedora(
            cnpj="54.657.895/0001-60",
            razao_social="TESTE REDUCAO",
            regime="SIMPLES",
            cnae_principal="4757100",
            uf_origem="SP",
            faturamento_12m=Decimal("500000.00"),
            anexo_simples="I",
        )
        compradora = EmpresaCompradora(
            razao_social="COMPRADORA",
            tipo="B2B_CONTRIBUINTE",
            uf_destino="SP",
        )
        operacao = OperacaoFiscal(
            data_emissao=date(2027, 6, 15),
            valor_operacao=Decimal("10000.00"),
            ncm_nbs="84818099",
            reducao_cbs_ibs=reducao,
        )
        return MotorReformaTributaria(fornecedora, compradora, operacao)

    def test_integral_sem_reducao(self):
        """INTEGRAL: credito B2B = 100% do IVA."""
        motor = self._criar_motor("INTEGRAL")
        credito = motor.credito_b2b_simples
        assert credito > Decimal("0")

    def test_reducao_30_reduz_credito(self):
        """REDUCAO_30: credito = 70% do integral."""
        motor_integral = self._criar_motor("INTEGRAL")
        motor_red30 = self._criar_motor("REDUCAO_30")
        credito_integral = motor_integral.credito_b2b_simples
        credito_red30 = motor_red30.credito_b2b_simples
        esperado = (credito_integral * Decimal("0.70")).quantize(Decimal("0.01"), ROUND_HALF_UP)
        assert credito_red30 == esperado

    def test_reducao_60_reduz_credito(self):
        """REDUCAO_60: credito = 40% do integral."""
        motor_integral = self._criar_motor("INTEGRAL")
        motor_red60 = self._criar_motor("REDUCAO_60")
        credito_integral = motor_integral.credito_b2b_simples
        credito_red60 = motor_red60.credito_b2b_simples
        esperado = (credito_integral * Decimal("0.40")).quantize(Decimal("0.01"), ROUND_HALF_UP)
        assert credito_red60 == esperado

    def test_isento_credito_zero(self):
        """ISENTO: credito = R$ 0,00."""
        motor = self._criar_motor("ISENTO")
        credito = motor.credito_b2b_simples
        assert credito == Decimal("0.00")

    def test_trilha_registra_reducao(self):
        """Trilha deve registrar passo REDUCAO_CBS_IBS quando nao INTEGRAL."""
        motor = self._criar_motor("REDUCAO_60")
        motor.credito_b2b_simples
        ids = [p.get("id") for p in motor.trilha_auditoria]
        assert "REDUCAO_CBS_IBS" in ids

    def test_integral_nao_registra_passo(self):
        """INTEGRAL nao deve registrar passo de reducao."""
        motor = self._criar_motor("INTEGRAL")
        motor.credito_b2b_simples
        ids = [p.get("id") for p in motor.trilha_auditoria]
        assert "REDUCAO_CBS_IBS" not in ids
