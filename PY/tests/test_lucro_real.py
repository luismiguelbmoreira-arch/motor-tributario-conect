# -*- coding: utf-8 -*-
"""
tests/test_lucro_real.py — Camada 3: Testes de Guarda e Cálculo Lucro Real
Projeto: Motor Tributário Conect 2026-2033

BASE LEGAL:
  - RIR/2018, Art. 228 (IRPJ — 15% + adicional 10%)
  - Lei 7.689/1988 + Lei 9.430/1996, Art. 29 (CSLL — 9%)
  - Lei 10.637/2002, Art. 2º (PIS não-cumulativo — 1,65%)
  - Lei 10.833/2003, Art. 2º (COFINS não-cumulativo — 7,60%)

Rode com: pytest PY/tests/test_lucro_real.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from decimal import Decimal

from motor_tributario import EmpresaFornecedora
from regimes.base import RegimeMismatchError
from regimes.lucro_real import LucroRealEngine


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def empresa_real():
    return EmpresaFornecedora(
        cnpj="11.222.444/0001-98",
        razao_social="EMPRESA LUCRO REAL TESTE",
        regime="REAL",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("12000000.00"),
    )

@pytest.fixture
def empresa_simples():
    return EmpresaFornecedora(
        cnpj="54.657.895/0001-60",
        razao_social="EMPRESA SIMPLES TESTE",
        regime="SIMPLES",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("1200000.00"),
        anexo_simples="I",
    )

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
def empresa_presumida():
    return EmpresaFornecedora(
        cnpj="11.222.333/0001-81",
        razao_social="EMPRESA PRESUMIDO TESTE",
        regime="PRESUMIDO",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("3000000.00"),
    )

@pytest.fixture
def trilha():
    return []


# ─────────────────────────────────────────────────────────────────────────────
# CAMADA 3 — GUARD CLAUSE (DEPLOY BLOQUEADO SE FALHAR)
# ─────────────────────────────────────────────────────────────────────────────

class TestLucroRealGuardClause:
    """
    Garante que a Camada 2 bloqueia uso do LucroRealEngine para regimes incorretos.
    """

    def test_real_rejeita_empresa_simples(self, empresa_simples, trilha):
        """CRÍTICO: LucroRealEngine NÃO PODE calcular empresa Simples Nacional."""
        with pytest.raises(RegimeMismatchError) as exc_info:
            LucroRealEngine(empresa_simples, trilha)

        assert "REAL" in str(exc_info.value)
        assert "SIMPLES" in str(exc_info.value)

    def test_real_rejeita_empresa_mei(self, empresa_mei, trilha):
        """CRÍTICO: LucroRealEngine NÃO PODE calcular empresa MEI."""
        with pytest.raises(RegimeMismatchError) as exc_info:
            LucroRealEngine(empresa_mei, trilha)

        assert "REAL" in str(exc_info.value)
        assert "MEI" in str(exc_info.value)

    def test_real_rejeita_empresa_presumida(self, empresa_presumida, trilha):
        """CRÍTICO: LucroRealEngine NÃO PODE calcular empresa Lucro Presumido."""
        with pytest.raises(RegimeMismatchError) as exc_info:
            LucroRealEngine(empresa_presumida, trilha)

        assert "REAL" in str(exc_info.value)
        assert "PRESUMIDO" in str(exc_info.value)

    def test_violacao_registrada_na_trilha(self, empresa_simples, trilha):
        """A violação deve ser gravada na trilha antes de lançar a exceção."""
        with pytest.raises(RegimeMismatchError):
            LucroRealEngine(empresa_simples, trilha)

        assert len(trilha) == 1
        assert trilha[0]["tipo"] == "VIOLACAO_SEGURANCA"
        assert "amparo_legal" in trilha[0]
        assert "timestamp" in trilha[0]

    def test_violacao_tem_lei_citada(self, empresa_simples, trilha):
        """MAX_FISCAL_02: toda violação deve citar a lei."""
        with pytest.raises(RegimeMismatchError):
            LucroRealEngine(empresa_simples, trilha)

        assert len(trilha[0]["amparo_legal"]) > 5

    def test_real_aceita_empresa_real(self, empresa_real, trilha):
        """LucroRealEngine DEVE aceitar empresa regime='REAL'."""
        engine = LucroRealEngine(empresa_real, trilha)
        assert engine is not None


# ─────────────────────────────────────────────────────────────────────────────
# CÁLCULOS — GOLDEN STANDARD (RIR/2018 + Leis 10.637 e 10.833)
# ─────────────────────────────────────────────────────────────────────────────

class TestLucroRealIRPJ:
    """
    IRPJ Lucro Real: 15% + adicional 10% sobre lucro > R$ 20k/mês.
    RIR/2018, Art. 228.
    """

    def test_irpj_sem_adicional(self, empresa_real, trilha):
        """Lucro R$ 10.000 → IRPJ R$ 1.500,00 (15%) — sem adicional."""
        engine = LucroRealEngine(empresa_real, trilha)
        result = engine.calcular_irpj(Decimal("10000.00"))

        # 10.000 × 15% = 1.500
        assert result["IRPJ_PRINCIPAL"] == Decimal("1500.00")
        # lucro <= 20k → sem adicional
        assert result["IRPJ_ADICIONAL"] == Decimal("0.00")
        assert result["IRPJ_TOTAL"] == Decimal("1500.00")

    def test_irpj_com_adicional(self, empresa_real, trilha):
        """Lucro R$ 30.000 → IRPJ R$ 4.500 principal + R$ 1.000 adicional."""
        engine = LucroRealEngine(empresa_real, trilha)
        result = engine.calcular_irpj(Decimal("30000.00"))

        # 30.000 × 15% = 4.500
        assert result["IRPJ_PRINCIPAL"] == Decimal("4500.00")
        # excedente: 30.000 - 20.000 = 10.000 → 10.000 × 10% = 1.000
        assert result["IRPJ_ADICIONAL"] == Decimal("1000.00")
        assert result["IRPJ_TOTAL"] == Decimal("5500.00")

    def test_irpj_lucro_exatamente_no_teto(self, empresa_real, trilha):
        """Lucro R$ 20.000 (no limite) → sem adicional."""
        engine = LucroRealEngine(empresa_real, trilha)
        result = engine.calcular_irpj(Decimal("20000.00"))

        assert result["IRPJ_ADICIONAL"] == Decimal("0.00")
        assert result["IRPJ_PRINCIPAL"] == Decimal("3000.00")  # 20.000 × 15%


class TestLucroRealCSLL:
    """
    CSLL Lucro Real: 9% sobre lucro real.
    Lei 7.689/1988, Art. 3º.
    """

    def test_csll(self, empresa_real, trilha):
        """Lucro R$ 10.000 → CSLL R$ 900,00 (9%)."""
        engine = LucroRealEngine(empresa_real, trilha)
        csll = engine.calcular_csll(Decimal("10000.00"))

        assert csll == Decimal("900.00")

    def test_csll_lucro_grande(self, empresa_real, trilha):
        """Lucro R$ 500.000 → CSLL R$ 45.000,00."""
        engine = LucroRealEngine(empresa_real, trilha)
        csll = engine.calcular_csll(Decimal("500000.00"))

        assert csll == Decimal("45000.00")


class TestLucroRealPISCOFINS:
    """
    PIS/COFINS não-cumulativo com possibilidade de créditos.
    Lei 10.637/2002 (PIS 1,65%) | Lei 10.833/2003 (COFINS 7,60%).
    """

    def test_pis_sem_credito(self, empresa_real, trilha):
        """Receita R$ 100.000 → PIS R$ 1.650,00 (1,65%)."""
        engine = LucroRealEngine(empresa_real, trilha)
        result = engine.calcular_pis_cofins(Decimal("100000.00"))

        assert result["PIS_BRUTO"] == Decimal("1650.00")
        assert result["COFINS_BRUTO"] == Decimal("7600.00")
        assert result["CREDITOS"] == Decimal("0.00")
        assert result["PIS_LIQUIDO"] == Decimal("1650.00")
        assert result["COFINS_LIQUIDO"] == Decimal("7600.00")

    def test_cofins_sem_credito(self, empresa_real, trilha):
        """Receita R$ 100.000 → COFINS R$ 7.600,00 (7,60%)."""
        engine = LucroRealEngine(empresa_real, trilha)
        result = engine.calcular_pis_cofins(Decimal("100000.00"))

        assert result["COFINS_BRUTO"] == Decimal("7600.00")

    def test_pis_cofins_com_creditos(self, empresa_real, trilha):
        """Créditos R$ 2.000 abatidos proporcionalmente de PIS e COFINS."""
        engine = LucroRealEngine(empresa_real, trilha)
        result = engine.calcular_pis_cofins(
            Decimal("100000.00"),
            creditos=Decimal("2000.00"),
        )

        # Total bruto: 1.650 + 7.600 = 9.250
        # Líquido: 9.250 - 2.000 = 7.250
        total_liquido = result["PIS_LIQUIDO"] + result["COFINS_LIQUIDO"]
        assert total_liquido == Decimal("7250.00")
        assert result["CREDITOS"] == Decimal("2000.00")


class TestLucroRealCargaTotal:
    """
    Carga total mensal: PIS + COFINS + CSLL + IRPJ.
    """

    def test_carga_total_retorna_chaves_obrigatorias(self, empresa_real, trilha):
        """Método principal deve retornar todas as chaves do contrato."""
        engine = LucroRealEngine(empresa_real, trilha)
        result = engine.calcular_carga_total_mensal(
            receita_mensal=Decimal("500000.00"),
            lucro_real_mensal=Decimal("50000.00"),
        )

        assert result["regime"] == "REAL"
        assert "receita_mensal" in result
        assert "lucro_real_mensal" in result
        assert "breakdown" in result
        assert "total_mensal" in result
        assert "aliquota_efetiva" in result
        assert "trilha_auditoria" in result

        breakdown = result["breakdown"]
        assert "PIS" in breakdown
        assert "COFINS" in breakdown
        assert "CSLL" in breakdown
        assert "IRPJ" in breakdown
        assert "IRPJ_ADICIONAL" in breakdown

    def test_trilha_auditoria_populada(self, empresa_real, trilha):
        """Todos os passos de cálculo devem estar na trilha."""
        engine = LucroRealEngine(empresa_real, trilha)
        engine.calcular_carga_total_mensal(
            receita_mensal=Decimal("500000.00"),
            lucro_real_mensal=Decimal("50000.00"),
        )

        ids = [p["id"] for p in trilha if p.get("tipo") == "CALCULO"]
        assert "PIS_COFINS_NAO_CUMULATIVO" in ids
        assert "CSLL_LUCRO_REAL" in ids
        assert "IRPJ_LUCRO_REAL" in ids
        assert "CARGA_TOTAL_REAL" in ids

    def test_max_fiscal_02_lei_em_todos_passos(self, empresa_real, trilha):
        """MAX_FISCAL_02: todo passo CALCULO deve ter amparo legal."""
        engine = LucroRealEngine(empresa_real, trilha)
        engine.calcular_carga_total_mensal(
            receita_mensal=Decimal("500000.00"),
            lucro_real_mensal=Decimal("50000.00"),
        )

        for passo in trilha:
            if passo.get("tipo") == "CALCULO":
                assert "amparo_legal" in passo, f"Passo sem lei: {passo['id']}"
                assert len(passo["amparo_legal"]) > 5, f"Lei vazia: {passo['id']}"
