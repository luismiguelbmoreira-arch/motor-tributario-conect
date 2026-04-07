# -*- coding: utf-8 -*-
"""
tests/test_difal.py — Testes DIFAL Interestadual
Projeto: Motor Tributário Conect 2026-2033

BASE LEGAL:
  - EC 87/2015 (DIFAL consumidor final)
  - LC 190/2022 (regulamentação pós-STF)
  - LC 87/1996, Art. 13 (base "por dentro")
  - Res. SF 22/1989 (alíquotas 7% e 12%)
  - Res. SF 13/2012 (4% importado)

Rode com: pytest PY/tests/test_difal.py -v
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import date
from decimal import Decimal

from difal import (
    ALIQUOTA_ICMS_INTERNA,
    UFS_SUL_SUDESTE_REMETENTE,
    calcular_difal,
    obter_aliquota_interestadual,
    obter_aliquota_interna,
)
from motor_tributario import (
    EmpresaCompradora,
    EmpresaFornecedora,
    MotorReformaTributaria,
    OperacaoFiscal,
)


# ─────────────────────────────────────────────────────────────────────────────
# TABELA DE ALÍQUOTAS INTERNAS
# ─────────────────────────────────────────────────────────────────────────────

class TestTabelaAliquotas:
    """Verifica integridade da tabela de alíquotas ICMS internas."""

    def test_27_ufs_presentes(self):
        """Tabela deve ter exatamente 27 UFs (26 estados + DF)."""
        assert len(ALIQUOTA_ICMS_INTERNA) == 27

    def test_sp_18_pct(self):
        assert obter_aliquota_interna("SP") == Decimal("0.18")

    def test_rj_22_pct(self):
        """RJ tem FECP 2% (20% + 2%)."""
        assert obter_aliquota_interna("RJ") == Decimal("0.22")

    def test_ba_205_pct(self):
        assert obter_aliquota_interna("BA") == Decimal("0.205")

    def test_ma_23_pct(self):
        """MA tem a maior alíquota interna do Brasil."""
        assert obter_aliquota_interna("MA") == Decimal("0.23")

    def test_case_insensitive(self):
        assert obter_aliquota_interna("sp") == Decimal("0.18")

    def test_uf_invalida_levanta_erro(self):
        with pytest.raises(ValueError):
            obter_aliquota_interna("XX")


# ─────────────────────────────────────────────────────────────────────────────
# ALÍQUOTAS INTERESTADUAIS (Res. SF 22/1989 + 13/2012)
# ─────────────────────────────────────────────────────────────────────────────

class TestAliquotaInterestadual:
    def test_sp_para_ba_7pct(self):
        """SP (Sul/Sudeste remetente) → BA (N/NE/CO/ES) = 7%."""
        assert obter_aliquota_interestadual("SP", "BA") == Decimal("0.07")

    def test_sp_para_rj_12pct(self):
        """SP → RJ: ambos Sul/Sudeste remetentes = 12%."""
        assert obter_aliquota_interestadual("SP", "RJ") == Decimal("0.12")

    def test_rj_para_mg_12pct(self):
        """RJ → MG: ambos Sul/Sudeste = 12%."""
        assert obter_aliquota_interestadual("RJ", "MG") == Decimal("0.12")

    def test_ba_para_sp_12pct(self):
        """BA → SP: BA não é Sul/Sudeste remetente = 12%."""
        assert obter_aliquota_interestadual("BA", "SP") == Decimal("0.12")

    def test_es_como_remetente_12pct(self):
        """ES é Sudeste mas EXCLUÍDO do bloco Sul/Sudeste remetente da Res. SF 22/1989."""
        assert obter_aliquota_interestadual("ES", "BA") == Decimal("0.12")
        assert obter_aliquota_interestadual("ES", "RJ") == Decimal("0.12")

    def test_sp_para_es_7pct(self):
        """SP → ES: ES aparece como destino N/NE/CO/ES, recebe com 7%."""
        assert obter_aliquota_interestadual("SP", "ES") == Decimal("0.07")

    def test_importado_4pct(self):
        """Produto importado = 4% independente de origem/destino."""
        assert obter_aliquota_interestadual("SP", "BA", produto_importado=True) == Decimal("0.04")
        assert obter_aliquota_interestadual("BA", "SP", produto_importado=True) == Decimal("0.04")

    def test_es_nao_esta_no_bloco_remetente(self):
        """ES não deve estar em UFS_SUL_SUDESTE_REMETENTE."""
        assert "ES" not in UFS_SUL_SUDESTE_REMETENTE
        assert "SP" in UFS_SUL_SUDESTE_REMETENTE


# ─────────────────────────────────────────────────────────────────────────────
# CÁLCULO B2C — BASE ÚNICA
# ─────────────────────────────────────────────────────────────────────────────

class TestDifalB2C:
    """
    B2C: DIFAL = Base × (Alíq.Interna − Alíq.Inter)
    Responsável: REMETENTE (CF Art. 155, §2º, VII, 'b')
    """

    def test_sp_ba_b2c_5000(self):
        """SP→BA B2C R$5.000: 5000 × (20,5% − 7%) = R$675,00"""
        r = calcular_difal(Decimal("5000"), "SP", "BA", "B2C_CONSUMIDOR_FINAL")
        assert r["aplicavel"] is True
        assert r["difal_valor"] == Decimal("675.00")
        assert r["responsavel"] == "REMETENTE"
        assert r["metodo"] == "BASE_UNICA"

    def test_sp_rj_b2c_10000(self):
        """SP→RJ B2C R$10.000: 10000 × (22% − 12%) = R$1.000,00"""
        r = calcular_difal(Decimal("10000"), "SP", "RJ", "B2C_CONSUMIDOR_FINAL")
        assert r["difal_valor"] == Decimal("1000.00")

    def test_sp_ma_b2c_5000(self):
        """SP→MA B2C R$5.000: 5000 × (23% − 7%) = R$800,00"""
        r = calcular_difal(Decimal("5000"), "SP", "MA", "B2C_CONSUMIDOR_FINAL")
        assert r["difal_valor"] == Decimal("800.00")

    def test_es_sp_b2c_5000(self):
        """ES→SP B2C R$5.000: inter=12% (ES excluído), SP=18% → 5000 × 6% = R$300,00"""
        r = calcular_difal(Decimal("5000"), "ES", "SP", "B2C_CONSUMIDOR_FINAL")
        assert r["difal_valor"] == Decimal("300.00")

    def test_importado_sp_mg_b2c_5000(self):
        """Importado SP→MG B2C R$5.000: inter=4%, MG=18% → 5000 × 14% = R$700,00"""
        r = calcular_difal(
            Decimal("5000"), "SP", "MG", "B2C_CONSUMIDOR_FINAL",
            produto_importado=True,
        )
        assert r["difal_valor"] == Decimal("700.00")
        assert r["produto_importado"] is True
        assert r["aliquota_interestadual"] == Decimal("0.04")

    def test_misto_tambem_usa_base_unica(self):
        """MISTO deve ser tratado como B2C (base única)."""
        r = calcular_difal(Decimal("5000"), "SP", "BA", "MISTO")
        assert r["metodo"] == "BASE_UNICA"
        assert r["responsavel"] == "REMETENTE"


# ─────────────────────────────────────────────────────────────────────────────
# CÁLCULO B2B — BASE DUPLA "POR DENTRO"
# ─────────────────────────────────────────────────────────────────────────────

class TestDifalB2B:
    """
    B2B: base dupla "por dentro".
    Responsável: DESTINATÁRIO (CF Art. 155, §2º, VII, 'a')
    """

    def test_b2b_base_dupla_maior_que_b2c(self):
        """Base dupla sempre gera DIFAL MAIOR que base única no mesmo cenário."""
        r_b2b = calcular_difal(Decimal("5000"), "SP", "BA", "B2B_CONTRIBUINTE")
        r_b2c = calcular_difal(Decimal("5000"), "SP", "BA", "B2C_CONSUMIDOR_FINAL")
        assert r_b2b["difal_valor"] > r_b2c["difal_valor"]
        assert r_b2b["responsavel"] == "DESTINATARIO"
        assert r_b2b["metodo"] == "BASE_DUPLA"

    def test_sp_rj_b2b_10000(self):
        """SP→RJ B2B R$10.000 calcula por dentro (inter=12%, RJ=22%)."""
        r = calcular_difal(Decimal("10000"), "SP", "RJ", "B2B_CONTRIBUINTE")
        assert r["aplicavel"] is True
        assert r["metodo"] == "BASE_DUPLA"
        # Base dupla é sempre > base única (1000)
        assert r["difal_valor"] > Decimal("1000.00")


# ─────────────────────────────────────────────────────────────────────────────
# OPERAÇÃO INTERNA — SEM DIFAL
# ─────────────────────────────────────────────────────────────────────────────

class TestDifalOperacaoInterna:
    def test_sp_sp_sem_difal(self):
        r = calcular_difal(Decimal("5000"), "SP", "SP", "B2C_CONSUMIDOR_FINAL")
        assert r["aplicavel"] is False
        assert r["difal_valor"] == Decimal("0.00")

    def test_rj_rj_b2b_sem_difal(self):
        r = calcular_difal(Decimal("10000"), "RJ", "RJ", "B2B_CONTRIBUINTE")
        assert r["aplicavel"] is False


# ─────────────────────────────────────────────────────────────────────────────
# TRILHA DE AUDITORIA (MAX_FISCAL_02)
# ─────────────────────────────────────────────────────────────────────────────

class TestDifalTrilha:
    def test_trilha_b2c_cita_lei(self):
        trilha = []
        calcular_difal(Decimal("5000"), "SP", "BA", "B2C_CONSUMIDOR_FINAL", trilha=trilha)
        assert len(trilha) == 1
        assert "amparo_legal" in trilha[0]
        assert "EC 87/2015" in trilha[0]["amparo_legal"]

    def test_trilha_operacao_interna_cita_cf(self):
        trilha = []
        calcular_difal(Decimal("5000"), "SP", "SP", "B2C_CONSUMIDOR_FINAL", trilha=trilha)
        assert len(trilha) == 1
        assert trilha[0]["id"] == "DIFAL_OPERACAO_INTERNA"
        assert "CF" in trilha[0]["amparo_legal"]


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRAÇÃO COM gerar_diagnostico()
# ─────────────────────────────────────────────────────────────────────────────

class TestDifalIntegracaoMotor:
    """DIFAL integrado no diagnóstico completo do MotorReformaTributaria."""

    def _motor_sp_ba_b2c(self):
        f = EmpresaFornecedora(
            cnpj="54657895000160",
            razao_social="TESTE DIFAL",
            regime="SIMPLES",
            cnae_principal="4757100",
            uf_origem="SP",
            faturamento_12m=Decimal("1800000"),
            anexo_simples="I",
        )
        c = EmpresaCompradora(tipo="B2C_CONSUMIDOR_FINAL", uf_destino="BA")
        o = OperacaoFiscal(
            data_emissao=date(2026, 6, 15),
            valor_operacao=Decimal("5000"),
            ncm_nbs="39201099",
        )
        return MotorReformaTributaria(fornecedora=f, compradora=c, operacao=o)

    def _motor_sp_sp_interna(self):
        f = EmpresaFornecedora(
            cnpj="54657895000160",
            razao_social="TESTE INTERNA",
            regime="SIMPLES",
            cnae_principal="4757100",
            uf_origem="SP",
            faturamento_12m=Decimal("1800000"),
            anexo_simples="I",
        )
        c = EmpresaCompradora(tipo="B2B_CONTRIBUINTE", uf_destino="SP")
        o = OperacaoFiscal(
            data_emissao=date(2026, 6, 15),
            valor_operacao=Decimal("5000"),
            ncm_nbs="39201099",
        )
        return MotorReformaTributaria(fornecedora=f, compradora=c, operacao=o)

    def test_diagnostico_tem_chave_difal(self):
        motor = self._motor_sp_ba_b2c()
        diag = motor.gerar_diagnostico()
        assert "difal" in diag

    def test_diagnostico_interestadual_sp_ba_675(self):
        """SP→BA B2C deve gerar DIFAL R$ 675,00 no diagnóstico completo."""
        motor = self._motor_sp_ba_b2c()
        diag = motor.gerar_diagnostico()
        assert diag["difal"]["aplicavel"] is True
        assert Decimal(str(diag["difal"]["difal_valor"])) == Decimal("675.00")
        assert diag["difal"]["responsavel"] == "REMETENTE"

    def test_diagnostico_interna_difal_inaplicavel(self):
        motor = self._motor_sp_sp_interna()
        diag = motor.gerar_diagnostico()
        assert diag["difal"]["aplicavel"] is False
        assert Decimal(str(diag["difal"]["difal_valor"])) == Decimal("0.00")

    def test_diagnostico_difal_tem_base_legal(self):
        """Campo base_legal obrigatório no dict DIFAL."""
        motor = self._motor_sp_ba_b2c()
        diag = motor.gerar_diagnostico()
        assert "base_legal" in diag["difal"]
        assert len(diag["difal"]["base_legal"]) > 10

    def test_produto_importado_default_false(self):
        """produto_importado default deve ser False."""
        motor = self._motor_sp_ba_b2c()
        assert motor.operacao.produto_importado is False
