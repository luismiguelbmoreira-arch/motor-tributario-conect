# -*- coding: utf-8 -*-
"""
tests/test_extrator_pipeline.py — Testes do Pipeline de Extração IA
Projeto: Motor Tributário Conect 2026-2033

Testa extrator_pdfs.py com mock da API Anthropic (zero custo, zero rede).
Cobre:
  - to_decimal(): formatos US, BR, misto, None, inválido
  - dados_para_motor(): mono-atividade e multi-atividade
  - Validações: RBT12 > teto, RBT12 None
  - LGPD: purge() redação de PII
  - extrair_dados_pdfs(): mock de sucesso, sem API key, JSON inválido

Rode com: pytest PY/tests/test_extrator_pipeline.py -v
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from services.extrator_pdfs import DadosExtraidosPDF, dados_para_motor, extrair_dados_pdfs


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES — JSON base para instanciar DadosExtraidosPDF sem API
# ─────────────────────────────────────────────────────────────────────────────

MONO_JSON = {
    "cnpj": "12.345.678/0001-90",
    "razao_social": "EMPRESA MONO ATIVIDADE LTDA",
    "cnae_principal": "4711302",
    "uf_origem": "SP",
    "faturamento_12m": "856430.21",
    "rpa_referencia": "71369.18",
    "das_ecac_referencia": "16428.83",
    "competencia": "01/2026",
    "das_breakdown": {},
    "campos_nao_encontrados": [],
    "confianca_extracao": 0.98,
    "observacoes": "",
}

MULTI_JSON = {
    "cnpj": "98.765.432/0001-10",
    "razao_social": "EMPRESA MULTI ATIVIDADE LTDA",
    "cnae_principal": "4757100",
    "uf_origem": "SP",
    "faturamento_12m": "720000.00",
    "rpa_referencia": "139144.08",
    "das_ecac_referencia": "15200.39",
    "competencia": "01/2026",
    "atividades_detalhadas": [
        {"receita": "95594.08", "anexo": "III", "icms_st": False, "iss_retido": False},
        {"receita": "4929.43",  "anexo": "I",   "icms_st": False, "iss_retido": False},
        {"receita": "32970.57", "anexo": "I",   "icms_st": True,  "iss_retido": False},
        {"receita": "5650.00",  "anexo": "III", "icms_st": False, "iss_retido": True},
    ],
    "das_breakdown": {},
    "campos_nao_encontrados": [],
    "confianca_extracao": 0.97,
    "observacoes": "",
}


def _make_dados(overrides: dict = None) -> DadosExtraidosPDF:
    data = dict(MONO_JSON)
    if overrides:
        data.update(overrides)
    return DadosExtraidosPDF(**data)


def _mock_api_response(json_text: str) -> MagicMock:
    """Cria resposta fake da API Anthropic."""
    msg = MagicMock()
    msg.content = [MagicMock(text=json_text)]
    return msg


# ─────────────────────────────────────────────────────────────────────────────
# 1. to_decimal() — detecção automática de formato
# ─────────────────────────────────────────────────────────────────────────────

class TestToDecimal:
    """
    to_decimal() deve detectar formato US, BR ou só-vírgula automaticamente.
    Nunca deve levantar exceção — retorna None para entradas inválidas.
    """

    def test_formato_us_ponto_decimal(self):
        """'2014303.11' (formato API) → Decimal 2014303.11 — ponto é decimal."""
        dados = _make_dados({"faturamento_12m": "2014303.11"})
        result = dados.to_decimal("faturamento_12m")
        assert result == Decimal("2014303.11")

    def test_formato_br_virgula_decimal(self):
        """'2.014.303,11' (formato BR) → Decimal 2014303.11 — pontos=milhares, vírgula=decimal."""
        dados = _make_dados({"faturamento_12m": "2.014.303,11"})
        result = dados.to_decimal("faturamento_12m")
        assert result == Decimal("2014303.11")

    def test_formato_so_virgula(self):
        """'2014303,11' (sem pontos) → Decimal 2014303.11 — vírgula é decimal."""
        dados = _make_dados({"faturamento_12m": "2014303,11"})
        result = dados.to_decimal("faturamento_12m")
        assert result == Decimal("2014303.11")

    def test_formato_inteiro(self):
        """'16428' (sem separadores) → Decimal 16428.00."""
        dados = _make_dados({"das_ecac_referencia": "16428"})
        result = dados.to_decimal("das_ecac_referencia")
        assert result == Decimal("16428.00")

    def test_campo_none_retorna_none(self):
        """Campo None → retorna None sem explodir."""
        dados = _make_dados({"folha_salarios_12m": None})
        result = dados.to_decimal("folha_salarios_12m")
        assert result is None

    def test_valor_com_rs_prefix(self):
        """'R$ 2014303.11' → strip R$ e espaço → Decimal 2014303.11."""
        dados = _make_dados({"faturamento_12m": "R$ 2014303.11"})
        result = dados.to_decimal("faturamento_12m")
        assert result == Decimal("2014303.11")

    def test_valor_invalido_retorna_none_nao_explode(self):
        """'abc' → retorna None, nunca levanta exceção."""
        dados = _make_dados({"faturamento_12m": "abc"})
        result = dados.to_decimal("faturamento_12m")
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. dados_para_motor() — path mono-atividade
# ─────────────────────────────────────────────────────────────────────────────

class TestDadosParaMotorMono:
    """
    dados_para_motor() com empresa mono-atividade:
    chaves obrigatórias, tipos Decimal, atividades=None.
    """

    @pytest.fixture
    def params(self):
        return dados_para_motor(DadosExtraidosPDF(**MONO_JSON))

    def test_retorna_chaves_obrigatorias(self, params):
        """Retorna dict com empresa, auditoria, meta."""
        assert "empresa" in params
        assert "auditoria" in params
        assert "meta" in params

    def test_faturamento_12m_e_decimal(self, params):
        """faturamento_12m é Decimal — nunca float."""
        valor = params["empresa"]["faturamento_12m"]
        assert isinstance(valor, Decimal)
        assert valor == Decimal("856430.21")

    def test_das_ecac_e_decimal(self, params):
        """das_ecac é Decimal — guarda contra vazamento de float no pipeline."""
        valor = params["auditoria"]["das_ecac"]
        assert isinstance(valor, Decimal)
        assert valor == Decimal("16428.83")

    def test_atividades_none_no_mono(self, params):
        """Empresa mono-atividade → atividades=None (não dispara SimplesMulti)."""
        assert params["empresa"]["atividades"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. dados_para_motor() — path multi-atividade
# ─────────────────────────────────────────────────────────────────────────────

class TestDadosParaMotorMulti:
    """
    dados_para_motor() com atividades_detalhadas:
    produz lista de Atividade com flags ST/ISS corretos.
    """

    @pytest.fixture
    def params(self):
        return dados_para_motor(DadosExtraidosPDF(**MULTI_JSON))

    def test_atividades_lista_populada(self, params):
        """atividades é lista com 4 itens."""
        atividades = params["empresa"]["atividades"]
        assert atividades is not None
        assert len(atividades) == 4

    def test_atividades_sao_objetos_atividade(self, params):
        """Cada item é instância de motor_tributario.Atividade (Pydantic V2)."""
        from core.motor_tributario import Atividade
        for item in params["empresa"]["atividades"]:
            assert isinstance(item, Atividade)

    def test_atividade_com_icms_st(self, params):
        """Atividade com receita R$32.970,57 e icms_st=True mapeada corretamente."""
        atividades = params["empresa"]["atividades"]
        st_item = next((a for a in atividades if a.icms_st), None)
        assert st_item is not None
        assert st_item.receita == Decimal("32970.57")
        assert st_item.anexo == "I"

    def test_atividade_com_iss_retido(self, params):
        """Atividade com receita R$5.650,00 e iss_retido=True mapeada corretamente."""
        atividades = params["empresa"]["atividades"]
        iss_item = next((a for a in atividades if a.iss_retido), None)
        assert iss_item is not None
        assert iss_item.receita == Decimal("5650.00")
        assert iss_item.anexo == "III"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Validação de RBT12
# ─────────────────────────────────────────────────────────────────────────────

class TestRBT12Validation:
    """
    dados_para_motor() rejeita RBT12 acima do teto e RBT12 ilegível.
    """

    def test_rbt12_acima_teto_levanta_value_error(self):
        """RBT12 R$5M > teto R$4.8M → ValueError com 'teto do Simples Nacional'."""
        dados = DadosExtraidosPDF(**{**MONO_JSON, "faturamento_12m": "5000000.00"})
        with pytest.raises(ValueError, match="teto do Simples Nacional"):
            dados_para_motor(dados)

    def test_rbt12_ilegivel_levanta_value_error_claro(self):
        """RBT12 ilegível (parse retorna None) → ValueError com 'nao pôde ser extraído'."""
        dados = DadosExtraidosPDF(**{**MONO_JSON, "faturamento_12m": "ILEGIVEL"})
        with pytest.raises(ValueError, match="nao pôde ser extraído"):
            dados_para_motor(dados)


# ─────────────────────────────────────────────────────────────────────────────
# 5. LGPD — purge() redação de PII
# ─────────────────────────────────────────────────────────────────────────────

class TestPurge:
    """
    purge() redige CNPJ e razão social após uso.
    LC 13.709/2018 (LGPD) — nenhum dado pessoal persiste na memória.
    """

    def test_purge_redacts_cnpj(self):
        """Após purge(), cnpj == 'REDACTED'."""
        dados = _make_dados()
        dados.purge()
        assert dados.cnpj == "REDACTED"

    def test_purge_redacts_razao_social(self):
        """Após purge(), razao_social == 'REDACTED'."""
        dados = _make_dados()
        dados.purge()
        assert dados.razao_social == "REDACTED"


# ─────────────────────────────────────────────────────────────────────────────
# 6. extrair_dados_pdfs() — mock da API Anthropic
# ─────────────────────────────────────────────────────────────────────────────

class TestExtrairPDFsMocked:
    """
    extrair_dados_pdfs() com API Anthropic mockada.
    Zero custo, zero rede — testa o fluxo de integração.
    """

    def test_retorna_dados_com_json_valido(self, tmp_path, monkeypatch):
        """API retorna JSON válido → DadosExtraidosPDF com razao_social correta."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake-key")

        pdf_fake = tmp_path / "test.pdf"
        pdf_fake.write_bytes(b"%PDF-1.0 fake")  # arquivo válido (read_bytes precisa existir)

        with patch("services.extrator_pdfs.anthropic.Anthropic") as MockAnthropic:
            MockAnthropic.return_value.messages.create.return_value = _mock_api_response(
                json.dumps(MONO_JSON)
            )
            resultado = extrair_dados_pdfs([str(pdf_fake)])

        assert isinstance(resultado, DadosExtraidosPDF)
        assert resultado.razao_social == "EMPRESA MONO ATIVIDADE LTDA"
        assert resultado.confianca_extracao == 0.98

    def test_sem_api_key_levanta_value_error(self, tmp_path, monkeypatch):
        """Sem ANTHROPIC_API_KEY → ValueError com 'ANTHROPIC_API_KEY'."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        pdf_fake = tmp_path / "test.pdf"
        pdf_fake.write_bytes(b"%PDF-1.0 fake")

        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            extrair_dados_pdfs([str(pdf_fake)])

    def test_json_invalido_levanta_runtime_error(self, tmp_path, monkeypatch):
        """IA retorna texto não-JSON → RuntimeError com 'resposta invalida'."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-fake-key")

        pdf_fake = tmp_path / "test.pdf"
        pdf_fake.write_bytes(b"%PDF-1.0 fake")

        with patch("services.extrator_pdfs.anthropic.Anthropic") as MockAnthropic:
            MockAnthropic.return_value.messages.create.return_value = _mock_api_response(
                "Desculpe, não consegui extrair os dados."  # não é JSON
            )
            with pytest.raises(RuntimeError, match="resposta invalida"):
                extrair_dados_pdfs([str(pdf_fake)])
