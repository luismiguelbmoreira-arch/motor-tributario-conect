# -*- coding: utf-8 -*-
"""
tests/test_simples_duplo.py — Camada 3: Simples Nacional Multi-Atividade
Projeto: Motor Tributário Conect 2026-2033

BASE LEGAL:
  - LC 123/2006, Art. 18, § 3º — multi-atividade: cada atividade no Anexo correto
  - LC 123/2006, Art. 13, § 1º, VII — ICMS-ST zerado no DAS
  - LC 123/2006, Art. 18, §§ 1º e 24 — fórmula AE + Fator R

GOLDEN STANDARD (RBT12 = R$ 720.000,00 — faixa 3 exata):
  Anexo I  AE = (720000 × 0,095 - 13.860) / 720000 = 0,075750 (7,575%)
  Anexo III AE = (720000 × 0,135 - 17.640) / 720000 = 0,110500 (11,050%)

Rode com: pytest PY/tests/test_simples_duplo.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from decimal import Decimal

from motor_tributario import EmpresaFornecedora, Atividade
from regimes.base import RegimeMismatchError
from regimes.simples_multi import SimplesMultiAtividadeEngine


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def empresa_duplo():
    """Empresa Simples com 2 atividades: Comércio (Anexo I) + Serviços (Anexo III)."""
    return EmpresaFornecedora(
        cnpj="33.333.333/0001-91",
        razao_social="EMPRESA SIMPLES DUPLO TESTE",
        regime="SIMPLES",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("720000.00"),
        atividades=[
            Atividade(receita=Decimal("50000.00"), anexo="I"),
            Atividade(receita=Decimal("10000.00"), anexo="III"),
        ],
    )

@pytest.fixture
def empresa_duplo_com_st():
    """Empresa com Anexo I + ICMS-ST na primeira atividade."""
    return EmpresaFornecedora(
        cnpj="55.555.555/0001-91",
        razao_social="EMPRESA SIMPLES ST TESTE",
        regime="SIMPLES",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("720000.00"),
        atividades=[
            Atividade(receita=Decimal("50000.00"), anexo="I", icms_st=True),
        ],
    )

@pytest.fixture
def empresa_duplo_com_iss_retido():
    """Empresa com Anexo III + ISS retido."""
    return EmpresaFornecedora(
        cnpj="55.555.555/0001-91",
        razao_social="EMPRESA SIMPLES ISS RETIDO TESTE",
        regime="SIMPLES",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("720000.00"),
        atividades=[
            Atividade(receita=Decimal("10000.00"), anexo="III", iss_retido=True),
        ],
    )

@pytest.fixture
def empresa_simples_sem_atividades():
    """Empresa SIMPLES sem atividades — SimplesMultiAtividadeEngine deve rejeitar."""
    return EmpresaFornecedora(
        cnpj="33.333.333/0001-91",
        razao_social="EMPRESA SIMPLES SEM ATIVIDADES",
        regime="SIMPLES",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("720000.00"),
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
def trilha():
    return []


# ─────────────────────────────────────────────────────────────────────────────
# CAMADA 3 — GUARD CLAUSE (DEPLOY BLOQUEADO SE FALHAR)
# ─────────────────────────────────────────────────────────────────────────────

class TestSimplesDuploGuardClause:
    """
    Garante que SimplesMultiAtividadeEngine rejeita regimes incorretos
    e empresas SIMPLES sem atividades preenchidas.
    """

    def test_rejeita_regime_presumido(self, empresa_presumida, trilha):
        """CRÍTICO: engine NÃO PODE calcular empresa Lucro Presumido."""
        with pytest.raises(RegimeMismatchError) as exc_info:
            SimplesMultiAtividadeEngine(empresa_presumida, trilha)

        assert "SIMPLES" in str(exc_info.value)
        assert "PRESUMIDO" in str(exc_info.value)

    def test_rejeita_regime_mei(self, empresa_mei, trilha):
        """CRÍTICO: engine NÃO PODE calcular empresa MEI."""
        with pytest.raises(RegimeMismatchError) as exc_info:
            SimplesMultiAtividadeEngine(empresa_mei, trilha)

        assert "SIMPLES" in str(exc_info.value)
        assert "MEI" in str(exc_info.value)

    def test_rejeita_regime_real(self, empresa_real, trilha):
        """CRÍTICO: engine NÃO PODE calcular empresa Lucro Real."""
        with pytest.raises(RegimeMismatchError) as exc_info:
            SimplesMultiAtividadeEngine(empresa_real, trilha)

        assert "SIMPLES" in str(exc_info.value)
        assert "REAL" in str(exc_info.value)

    def test_rejeita_simples_sem_atividades(self, empresa_simples_sem_atividades, trilha):
        """Engine exige atividades[] — SIMPLES sem atividades → ValueError."""
        with pytest.raises(ValueError, match="atividades"):
            SimplesMultiAtividadeEngine(empresa_simples_sem_atividades, trilha)

    def test_aceita_simples_com_atividades(self, empresa_duplo, trilha):
        """SimplesMultiAtividadeEngine DEVE aceitar empresa SIMPLES com atividades."""
        engine = SimplesMultiAtividadeEngine(empresa_duplo, trilha)
        assert engine is not None

    def test_violacao_registrada_na_trilha(self, empresa_presumida, trilha):
        """Violação de regime deve ser gravada na trilha antes de lançar exceção."""
        with pytest.raises(RegimeMismatchError):
            SimplesMultiAtividadeEngine(empresa_presumida, trilha)

        assert len(trilha) == 1
        assert trilha[0]["tipo"] == "VIOLACAO_SEGURANCA"
        assert "amparo_legal" in trilha[0]
        assert "timestamp" in trilha[0]

    def test_violacao_tem_lei_citada(self, empresa_presumida, trilha):
        """MAX_FISCAL_02: toda violação deve citar a lei."""
        with pytest.raises(RegimeMismatchError):
            SimplesMultiAtividadeEngine(empresa_presumida, trilha)

        assert len(trilha[0]["amparo_legal"]) > 5


# ─────────────────────────────────────────────────────────────────────────────
# GOLDEN STANDARD — CÁLCULO DAS POR ATIVIDADE
# ─────────────────────────────────────────────────────────────────────────────

class TestSimplesDuploDASCalculo:
    """
    DAS por atividade — RBT12 R$ 720.000 (faixa 3 exata).

    Anexo I  faixa 3: aliq=9,5%, PD=R$13.860  → AE = 7,5750%
    Anexo III faixa 3: aliq=13,5%, PD=R$17.640 → AE = 11,0500%
    """

    def test_ae_anexo_i_rbt12_720k(self, empresa_duplo, trilha):
        """AE Anexo I @ RBT12 720k = 0,075750 (7,5750%)."""
        engine = SimplesMultiAtividadeEngine(empresa_duplo, trilha)
        ae = engine._calcular_ae_por_anexo(Decimal("720000.00"), "I")

        assert ae == Decimal("0.075750")

    def test_ae_anexo_iii_rbt12_720k(self, empresa_duplo, trilha):
        """AE Anexo III @ RBT12 720k = 0,110500 (11,0500%)."""
        engine = SimplesMultiAtividadeEngine(empresa_duplo, trilha)
        ae = engine._calcular_ae_por_anexo(Decimal("720000.00"), "III")

        assert ae == Decimal("0.110500")

    def test_das_atividade_comercio(self, empresa_duplo, trilha):
        """Comércio R$50k receita × 7,5750% = DAS R$3.787,50."""
        engine = SimplesMultiAtividadeEngine(empresa_duplo, trilha)
        resultado = engine.calcular_das_multi_atividade()

        item_i = next(i for i in resultado["itens"] if i["anexo"] == "I")
        assert item_i["das"] == Decimal("3787.50")

    def test_das_atividade_servicos(self, empresa_duplo, trilha):
        """Serviços R$10k receita × 11,0500% = DAS R$1.105,00."""
        engine = SimplesMultiAtividadeEngine(empresa_duplo, trilha)
        resultado = engine.calcular_das_multi_atividade()

        item_iii = next(i for i in resultado["itens"] if i["anexo"] == "III")
        assert item_iii["das"] == Decimal("1105.00")

    def test_das_total_duplo(self, empresa_duplo, trilha):
        """Total DAS = R$3.787,50 + R$1.105,00 = R$4.892,50."""
        engine = SimplesMultiAtividadeEngine(empresa_duplo, trilha)
        resultado = engine.calcular_das_multi_atividade()

        assert resultado["total_das"] == Decimal("4892.50")

    def test_aliquota_efetiva_total(self, empresa_duplo, trilha):
        """AE efetiva total = R$4.892,50 / R$60.000 = 0,081542."""
        engine = SimplesMultiAtividadeEngine(empresa_duplo, trilha)
        resultado = engine.calcular_das_multi_atividade()

        # 4892.50 / 60000.00 = 0.0815416... → 0.081542
        esperado = (Decimal("4892.50") / Decimal("60000.00")).quantize(Decimal("0.000001"))
        assert resultado["aliquota_efetiva"] == esperado

    def test_das_com_icms_st_abatimento(self, empresa_duplo_com_st, trilha):
        """
        ICMS-ST Anexo I faixa 3 (ICMS=34%) abate da AE.
        AE bruta=0,075750 → AE líquida=0,075750×(1-0,34)=0,049995
        DAS = R$50k × 0,049995 = R$2.499,75
        """
        engine = SimplesMultiAtividadeEngine(empresa_duplo_com_st, trilha)
        resultado = engine.calcular_das_multi_atividade()

        item = resultado["itens"][0]
        assert item["icms_st"] is True
        assert item["ae_liquida"] == Decimal("0.049995")
        assert item["das"] == Decimal("2499.75")

    def test_das_com_iss_retido_abatimento(self, empresa_duplo_com_iss_retido, trilha):
        """
        ISS retido Anexo III faixa 3 (ISS=32,5%) abate da AE.
        AE bruta=0,110500 → AE líquida=0,110500×(1-0,325)=0,074588
        DAS = R$10k × 0,074588 = R$745,88
        """
        engine = SimplesMultiAtividadeEngine(empresa_duplo_com_iss_retido, trilha)
        resultado = engine.calcular_das_multi_atividade()

        item = resultado["itens"][0]
        assert item["iss_retido"] is True
        assert item["ae_liquida"] == Decimal("0.074588")
        assert item["das"] == Decimal("745.88")


# ─────────────────────────────────────────────────────────────────────────────
# CARGA TOTAL + TRILHA DE AUDITORIA
# ─────────────────────────────────────────────────────────────────────────────

class TestSimplesDuploCargaTotal:
    """
    calcular_carga_total_mensal: contrato + trilha + MAX_FISCAL_02.
    """

    def test_retorna_chaves_obrigatorias(self, empresa_duplo, trilha):
        """Contrato de retorno: regime, atividades, total_mensal, aliquota_efetiva, trilha."""
        engine = SimplesMultiAtividadeEngine(empresa_duplo, trilha)
        result = engine.calcular_carga_total_mensal()

        assert result["regime"] == "SIMPLES"
        assert "atividades" in result
        assert "receita_total" in result
        assert "total_mensal" in result
        assert "aliquota_efetiva" in result
        assert "trilha_auditoria" in result
        assert len(result["atividades"]) == 2

    def test_trilha_auditoria_populada(self, empresa_duplo, trilha):
        """IDs obrigatórios devem estar na trilha após calcular_carga_total_mensal."""
        engine = SimplesMultiAtividadeEngine(empresa_duplo, trilha)
        engine.calcular_carga_total_mensal()

        ids = [p["id"] for p in trilha if p.get("tipo") == "CALCULO"]
        assert "DAS_MULTI_ATIVIDADE" in ids
        assert "CARGA_TOTAL_SIMPLES_MULTI" in ids

    def test_max_fiscal_02_lei_em_todos_passos(self, empresa_duplo, trilha):
        """MAX_FISCAL_02: todo passo CALCULO deve ter amparo legal."""
        engine = SimplesMultiAtividadeEngine(empresa_duplo, trilha)
        engine.calcular_carga_total_mensal()

        for passo in trilha:
            if passo.get("tipo") == "CALCULO":
                assert "amparo_legal" in passo, f"Passo sem lei: {passo['id']}"
                assert len(passo["amparo_legal"]) > 5, f"Lei vazia: {passo['id']}"
