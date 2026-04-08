# -*- coding: utf-8 -*-
"""
test_relatorio_pdf_pii.py — Trava arquitetural LGPD para o gerador de PDF.

PRINCIPIO: o diagnostico retornado por gerar_diagnostico() e despersonalizado
(sem cnpj/razao_social) por exigencia LGPD. PII (cnpj, razao_social) so e
entregue no momento de gerar o PDF para o cliente, via parametro separado.

Estes testes garantem que essa separacao nao quebre.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import date  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402

from motor_tributario import (  # noqa: E402
    EmpresaCompradora,
    EmpresaFornecedora,
    MotorReformaTributaria,
    OperacaoFiscal,
)
from relatorio_pdf import _gerar_html  # noqa: E402


@pytest.fixture
def diagnostico_canavezi():
    """Diagnostico real (despersonalizado) de uma empresa fixture."""
    f = EmpresaFornecedora(
        cnpj="54657895000160",
        razao_social="REFRIGERACAO CANAVEZI LTDA",
        regime="SIMPLES",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("2014303.11"),
        anexo_simples="I",
    )
    c = EmpresaCompradora(tipo="B2C_CONSUMIDOR_FINAL", uf_destino="SP")
    o = OperacaoFiscal(
        data_emissao=date(2026, 1, 1),
        valor_operacao=Decimal("150000"),
        ncm_nbs="00000000",
    )
    motor = MotorReformaTributaria(fornecedora=f, compradora=c, operacao=o)
    return motor.gerar_diagnostico()


def test_gerar_html_sem_pii_nao_vaza_razao_social(diagnostico_canavezi):
    """LGPD: sem o parametro pii, o HTML NAO pode conter razao social."""
    html = _gerar_html(diagnostico_canavezi)
    assert "REFRIGERACAO CANAVEZI" not in html
    assert "CANAVEZI" not in html


def test_gerar_html_sem_pii_nao_vaza_cnpj(diagnostico_canavezi):
    """LGPD: sem o parametro pii, o HTML NAO pode conter CNPJ."""
    html = _gerar_html(diagnostico_canavezi)
    assert "54657895000160" not in html
    assert "54.657.895/0001-60" not in html


def test_gerar_html_com_pii_injeta_razao_social(diagnostico_canavezi):
    """Com pii fornecido, a razao social aparece no header do PDF."""
    pii = {
        "razao_social": "REFRIGERACAO CANAVEZI LTDA",
        "cnpj": "54.657.895/0001-60",
    }
    html = _gerar_html(diagnostico_canavezi, pii=pii)
    assert "REFRIGERACAO CANAVEZI LTDA" in html


def test_gerar_html_com_pii_injeta_cnpj(diagnostico_canavezi):
    """Com pii fornecido, o CNPJ aparece no header do PDF."""
    pii = {
        "razao_social": "REFRIGERACAO CANAVEZI LTDA",
        "cnpj": "54.657.895/0001-60",
    }
    html = _gerar_html(diagnostico_canavezi, pii=pii)
    assert "54.657.895/0001-60" in html


def test_gerar_html_pii_none_mostra_traco(diagnostico_canavezi):
    """Sem pii e sem dados em diagnostico.empresa, header mostra '—' (traco)."""
    html = _gerar_html(diagnostico_canavezi, pii=None)
    # O header existe e tem placeholder
    assert "<h1>—</h1>" in html or '<h1>\u2014</h1>' in html


def test_diagnostico_continua_despersonalizado(diagnostico_canavezi):
    """Garantia adicional: o dict diagnostico nao tem PII em lugar nenhum."""
    diag_str = str(diagnostico_canavezi)
    assert "54657895000160" not in diag_str
    assert "54.657.895/0001-60" not in diag_str
    assert "REFRIGERACAO CANAVEZI" not in diag_str


def test_diagnostico_lucro_real_tambem_despersonalizado():
    """LGPD: Lucro Real tinha bug latente — razao_social vazava no dict empresa.

    Este teste garante que o fix pegue tambem o caminho de gerar_diagnostico()
    quando o regime e REAL (que delega para _diagnostico_lucro_real).
    """
    f = EmpresaFornecedora(
        cnpj="11222333000181",
        razao_social="EMPRESA LUCRO REAL TESTE LTDA",
        regime="REAL",
        cnae_principal="6201500",
        uf_origem="SP",
        faturamento_12m=Decimal("8000000.00"),
    )
    c = EmpresaCompradora(tipo="B2B_CONTRIBUINTE", uf_destino="SP")
    o = OperacaoFiscal(
        data_emissao=date(2026, 1, 1),
        valor_operacao=Decimal("100000"),
        ncm_nbs="00000000",
    )
    motor = MotorReformaTributaria(fornecedora=f, compradora=c, operacao=o)
    diag = motor.gerar_diagnostico()
    diag_str = str(diag)

    # Nenhuma PII deve vazar — nem no caminho do Simples, nem no do Lucro Real
    assert "11222333000181" not in diag_str
    assert "11.222.333/0001-81" not in diag_str
    assert "EMPRESA LUCRO REAL TESTE" not in diag_str
