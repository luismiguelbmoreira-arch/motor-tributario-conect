# -*- coding: utf-8 -*-
"""
tests/test_regime_guard.py — Camada 3: Testes de Guarda de Regime
Projeto: Motor Tributário Conect 2026-2033

PROPÓSITO: Garantir que as Guard Clauses (Camada 2) nunca sejam removidas.
Se algum teste falhar, o deploy é bloqueado.

Rode com: pytest PY/tests/test_regime_guard.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from decimal import Decimal

from motor_tributario import EmpresaFornecedora
from regimes.base import RegimeMismatchError
from regimes.lucro_presumido import LucroPresumidoEngine


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

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
# CAMADA 2 — TESTES DE GUARD CLAUSE
# ─────────────────────────────────────────────────────────────────────────────

class TestGuardClause:
    """
    Garante que a Camada 2 bloqueia chamadas de módulo errado.
    Se qualquer teste aqui falhar, a Guard Clause foi removida — DEPLOY BLOQUEADO.
    """

    def test_presumido_rejeita_empresa_simples(self, empresa_simples, trilha):
        """CRÍTICO: LucroPresumidoEngine NÃO PODE calcular empresa Simples Nacional."""
        with pytest.raises(RegimeMismatchError) as exc_info:
            LucroPresumidoEngine(empresa_simples, trilha)

        assert "PRESUMIDO" in str(exc_info.value)
        assert "SIMPLES" in str(exc_info.value)

    def test_violacao_registrada_na_trilha(self, empresa_simples, trilha):
        """A violação deve ser gravada na trilha antes de lançar a exceção."""
        with pytest.raises(RegimeMismatchError):
            LucroPresumidoEngine(empresa_simples, trilha)

        assert len(trilha) == 1
        assert trilha[0]["tipo"] == "VIOLACAO_SEGURANCA"
        assert "amparo_legal" in trilha[0]
        assert "timestamp" in trilha[0]

    def test_violacao_tem_lei_citada(self, empresa_simples, trilha):
        """MAX_FISCAL_02: toda violação deve citar a lei. Trilha sem lei = reprovado."""
        with pytest.raises(RegimeMismatchError):
            LucroPresumidoEngine(empresa_simples, trilha)

        lei = trilha[0]["amparo_legal"]
        assert "LC 123/2006" in lei or "RIR" in lei

    def test_presumido_aceita_empresa_presumida(self, empresa_presumida, trilha):
        """LucroPresumidoEngine DEVE aceitar empresa corretamente enquadrada."""
        engine = LucroPresumidoEngine(empresa_presumida, trilha)
        assert engine is not None

    def test_guard_clause_nao_pode_ser_burlada_por_subclasse(self, empresa_simples, trilha):
        """Subclasse que não declara REGIME_ACEITO deve levantar NotImplementedError."""
        class EngineOrfao(LucroPresumidoEngine):
            REGIME_ACEITO = NotImplemented  # type: ignore

        with pytest.raises((NotImplementedError, RegimeMismatchError)):
            EngineOrfao(empresa_simples, trilha)


# ─────────────────────────────────────────────────────────────────────────────
# CAMADA 2 — TESTES DE CÁLCULO (Presumido)
# ─────────────────────────────────────────────────────────────────────────────

class TestLucroPresumidoCalculo:
    """
    Valida os cálculos do Lucro Presumido com valores reais conhecidos.
    Golden standard aprovado por Luiz Moreira (CRC-SP).
    """

    def test_pis_cofins_cumulativo(self, empresa_presumida, trilha):
        engine = LucroPresumidoEngine(empresa_presumida, trilha)
        result = engine.calcular_pis_cofins(Decimal("250000.00"))

        # PIS: 250.000 × 0,65% = 1.625,00
        assert result["PIS"] == Decimal("1625.00")
        # COFINS: 250.000 × 3% = 7.500,00
        assert result["COFINS"] == Decimal("7500.00")

    def test_csll_comercio(self, empresa_presumida, trilha):
        engine = LucroPresumidoEngine(empresa_presumida, trilha)
        # CNAE 4757100 (comércio varejista) → presunção CSLL 12% × 9%
        csll = engine.calcular_csll(Decimal("250000.00"))
        # Base: 250.000 × 12% = 30.000 → CSLL: 30.000 × 9% = 2.700
        assert csll == Decimal("2700.00")

    def test_irpj_sem_adicional(self, empresa_presumida, trilha):
        engine = LucroPresumidoEngine(empresa_presumida, trilha)
        # Receita mensal de R$50k → trimestral R$150k
        # Base IRPJ: 150.000 × 8% = 12.000 < 60.000 → sem adicional
        result = engine.calcular_irpj(Decimal("50000.00"), meses=3)
        assert result["IRPJ_ADICIONAL"] == Decimal("0.00")
        assert result["IRPJ_PRINCIPAL"] == Decimal("1800.00")  # 12.000 × 15%

    def test_irpj_com_adicional(self, empresa_presumida, trilha):
        engine = LucroPresumidoEngine(empresa_presumida, trilha)
        # Receita trimestral R$1.500.000 → Base 8% = R$120.000
        # Adicional: (120.000 - 60.000) × 10% = R$6.000
        result = engine.calcular_irpj(Decimal("500000.00"), meses=3)
        assert result["IRPJ_ADICIONAL"] > Decimal("0.00")

    def test_trilha_registra_todos_passos(self, empresa_presumida, trilha):
        engine = LucroPresumidoEngine(empresa_presumida, trilha)
        engine.calcular_carga_total_mensal(Decimal("250000.00"))

        ids = [p["id"] for p in trilha]
        assert "PIS_COFINS_CUMULATIVO" in ids
        assert "CSLL_PRESUMIDO" in ids
        assert "IRPJ_PRESUMIDO" in ids
        assert "CARGA_TOTAL_PRESUMIDO" in ids

    def test_max_fiscal_01_toda_entrada_tem_lei(self, empresa_presumida, trilha):
        """MAX_FISCAL_02: todo passo na trilha deve ter amparo legal."""
        engine = LucroPresumidoEngine(empresa_presumida, trilha)
        engine.calcular_carga_total_mensal(Decimal("250000.00"))

        for passo in trilha:
            assert "amparo_legal" in passo, f"Passo sem lei: {passo['id']}"
            assert len(passo["amparo_legal"]) > 5, f"Lei vazia no passo: {passo['id']}"
