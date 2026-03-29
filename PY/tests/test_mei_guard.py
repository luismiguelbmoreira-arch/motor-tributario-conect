# -*- coding: utf-8 -*-
"""
tests/test_mei_guard.py — Camada 3: Testes de Guarda e Cálculo MEI
Projeto: Motor Tributário Conect 2026-2033

PROPÓSITO: Garantir que o MEIEngine funciona corretamente e que
a Guard Clause bloqueia uso indevido do engine para outros regimes.
Se qualquer teste falhar, o deploy é bloqueado.

BASE LEGAL:
  - LC 123/2006, Art. 18-A (MEI)
  - Resolução CGSN nº 140/2018 (DAS MEI)
  - LC 214/2025, Art. 4º (MEI sem crédito CBS/IBS)

Rode com: pytest PY/tests/test_mei_guard.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from decimal import Decimal

from motor_tributario import EmpresaFornecedora
from regimes.base import RegimeMismatchError
from regimes.mei import MEIEngine


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def empresa_mei():
    return EmpresaFornecedora(
        cnpj="07.526.557/0001-00",
        razao_social="MEI COMERCIO TESTE",
        regime="MEI",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("60000.00"),
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
# CAMADA 2 — TESTES DE GUARD CLAUSE MEI
# ─────────────────────────────────────────────────────────────────────────────

class TestMEIGuardClause:
    """
    Garante que a Camada 2 bloqueia uso do MEIEngine para regimes incorretos.
    Se qualquer teste aqui falhar, a Guard Clause foi removida — DEPLOY BLOQUEADO.
    """

    def test_mei_rejeita_empresa_simples(self, empresa_simples, trilha):
        """CRÍTICO: MEIEngine NÃO PODE calcular empresa Simples Nacional."""
        with pytest.raises(RegimeMismatchError) as exc_info:
            MEIEngine(empresa_simples, trilha)

        assert "MEI" in str(exc_info.value)
        assert "SIMPLES" in str(exc_info.value)

    def test_mei_rejeita_empresa_presumida(self, empresa_presumida, trilha):
        """CRÍTICO: MEIEngine NÃO PODE calcular empresa Lucro Presumido."""
        with pytest.raises(RegimeMismatchError) as exc_info:
            MEIEngine(empresa_presumida, trilha)

        assert "MEI" in str(exc_info.value)
        assert "PRESUMIDO" in str(exc_info.value)

    def test_violacao_registrada_na_trilha_mei(self, empresa_simples, trilha):
        """A violação deve ser gravada na trilha antes de lançar a exceção."""
        with pytest.raises(RegimeMismatchError):
            MEIEngine(empresa_simples, trilha)

        assert len(trilha) == 1
        assert trilha[0]["tipo"] == "VIOLACAO_SEGURANCA"
        assert "amparo_legal" in trilha[0]
        assert "timestamp" in trilha[0]

    def test_violacao_tem_lei_citada_mei(self, empresa_simples, trilha):
        """MAX_FISCAL_02: toda violação deve citar a lei. Trilha sem lei = reprovado."""
        with pytest.raises(RegimeMismatchError):
            MEIEngine(empresa_simples, trilha)

        lei = trilha[0]["amparo_legal"]
        assert len(lei) > 5

    def test_mei_aceita_empresa_mei(self, empresa_mei, trilha):
        """MEIEngine DEVE aceitar empresa corretamente enquadrada como MEI."""
        engine = MEIEngine(empresa_mei, trilha)
        assert engine is not None


# ─────────────────────────────────────────────────────────────────────────────
# TESTES DE CÁLCULO DAS — MEI 2026
# ─────────────────────────────────────────────────────────────────────────────

class TestMEIDASCalculo:
    """
    Valida os valores do DAS MEI 2026.
    Base: salário mínimo R$ 1.622,00 (2026) — LC 123/2006, Art. 18-A.
    INSS MEI: 5% × R$ 1.622,00 = R$ 81,10.
    Aprovado: SM2026 confirmado pelo usuário em 29/03/2026.
    """

    def test_das_comercio_2026(self, empresa_mei, trilha):
        """COMERCIO: INSS R$ 81,10 + ICMS R$ 5,00 = R$ 86,10."""
        engine = MEIEngine(empresa_mei, trilha)
        result = engine.calcular_das_mensal("COMERCIO")

        assert result["INSS"] == Decimal("81.10")
        assert result["ICMS"] == Decimal("5.00")
        assert result["ISS"] == Decimal("0.00")
        assert result["DAS_TOTAL"] == Decimal("86.10")

    def test_das_industria_2026(self, empresa_mei, trilha):
        """INDUSTRIA: INSS R$ 81,10 + ICMS R$ 5,00 = R$ 86,10."""
        engine = MEIEngine(empresa_mei, trilha)
        result = engine.calcular_das_mensal("INDUSTRIA")

        assert result["INSS"] == Decimal("81.10")
        assert result["ICMS"] == Decimal("5.00")
        assert result["ISS"] == Decimal("0.00")
        assert result["DAS_TOTAL"] == Decimal("86.10")

    def test_das_servicos_2026(self, empresa_mei, trilha):
        """SERVICOS: INSS R$ 81,10 + ISS R$ 5,00 = R$ 86,10."""
        engine = MEIEngine(empresa_mei, trilha)
        result = engine.calcular_das_mensal("SERVICOS")

        assert result["INSS"] == Decimal("81.10")
        assert result["ICMS"] == Decimal("0.00")
        assert result["ISS"] == Decimal("5.00")
        assert result["DAS_TOTAL"] == Decimal("86.10")

    def test_das_comercio_servicos_2026(self, empresa_mei, trilha):
        """COMERCIO_SERVICOS: INSS R$ 81,10 + ICMS R$ 5,00 + ISS R$ 5,00 = R$ 91,10."""
        engine = MEIEngine(empresa_mei, trilha)
        result = engine.calcular_das_mensal("COMERCIO_SERVICOS")

        assert result["INSS"] == Decimal("81.10")
        assert result["ICMS"] == Decimal("5.00")
        assert result["ISS"] == Decimal("5.00")
        assert result["DAS_TOTAL"] == Decimal("91.10")

    def test_categoria_invalida_levanta_erro(self, empresa_mei, trilha):
        """Categoria desconhecida deve levantar ValueError com mensagem clara."""
        engine = MEIEngine(empresa_mei, trilha)

        with pytest.raises(ValueError) as exc_info:
            engine.calcular_das_mensal("EXPORTACAO")

        assert "EXPORTACAO" in str(exc_info.value)


# ─────────────────────────────────────────────────────────────────────────────
# TESTES DE TETO E IVA
# ─────────────────────────────────────────────────────────────────────────────

class TestMEITetoEIVA:
    """
    Valida controles de teto anual e ausência de crédito IVA.
    """

    def test_alerta_teto_excedido(self, empresa_mei, trilha):
        """Receita acumulada > R$ 81.000 deve gerar alerta na trilha (não bloqueia cálculo)."""
        engine = MEIEngine(empresa_mei, trilha)
        engine.calcular_carga_total_mensal(
            receita_mensal=Decimal("7000.00"),
            categoria="COMERCIO",
            receita_acumulada_ano=Decimal("82000.00"),  # acima do teto
        )

        alertas = [e for e in trilha if e.get("tipo") == "ALERTA_MEI_TETO"]
        assert len(alertas) >= 1
        assert "81.000" in alertas[0]["detalhe"] or "81000" in str(alertas[0])

    def test_sem_alerta_dentro_do_teto(self, empresa_mei, trilha):
        """Receita acumulada <= R$ 81.000 NÃO deve gerar alerta de teto."""
        engine = MEIEngine(empresa_mei, trilha)
        engine.calcular_carga_total_mensal(
            receita_mensal=Decimal("5000.00"),
            categoria="COMERCIO",
            receita_acumulada_ano=Decimal("60000.00"),  # dentro do teto
        )

        alertas = [e for e in trilha if e.get("tipo") == "ALERTA_MEI_TETO"]
        assert len(alertas) == 0

    def test_sem_credito_iva(self, empresa_mei, trilha):
        """MEI não gera crédito CBS/IBS para tomadores — LC 214/2025, Art. 4º."""
        engine = MEIEngine(empresa_mei, trilha)
        result = engine.calcular_carga_total_mensal(
            receita_mensal=Decimal("5000.00"),
            categoria="COMERCIO",
        )

        assert result["credito_iva"] == Decimal("0.00")

    def test_trilha_auditoria_populada(self, empresa_mei, trilha):
        """Método principal deve registrar passos na trilha de auditoria."""
        engine = MEIEngine(empresa_mei, trilha)
        engine.calcular_carga_total_mensal(
            receita_mensal=Decimal("5000.00"),
            categoria="COMERCIO",
        )

        ids = [p["id"] for p in trilha if p.get("tipo") == "CALCULO"]
        assert "DAS_MEI" in ids
        assert "CARGA_TOTAL_MEI" in ids

    def test_aliquota_efetiva_calculada(self, empresa_mei, trilha):
        """Alíquota efetiva = DAS / receita_mensal."""
        engine = MEIEngine(empresa_mei, trilha)
        result = engine.calcular_carga_total_mensal(
            receita_mensal=Decimal("5000.00"),
            categoria="COMERCIO",
        )

        # DAS COMERCIO = R$ 86,10 / R$ 5.000,00 = 0,01722 = 1,722%
        esperado = (Decimal("86.10") / Decimal("5000.00")).quantize(Decimal("0.000001"))
        assert result["aliquota_efetiva"] == esperado

    def test_max_fiscal_02_lei_em_todos_passos(self, empresa_mei, trilha):
        """MAX_FISCAL_02: todo passo CALCULO na trilha deve ter amparo legal."""
        engine = MEIEngine(empresa_mei, trilha)
        engine.calcular_carga_total_mensal(
            receita_mensal=Decimal("5000.00"),
            categoria="COMERCIO",
        )

        for passo in trilha:
            if passo.get("tipo") == "CALCULO":
                assert "amparo_legal" in passo, f"Passo sem lei: {passo['id']}"
                assert len(passo["amparo_legal"]) > 5, f"Lei vazia: {passo['id']}"
