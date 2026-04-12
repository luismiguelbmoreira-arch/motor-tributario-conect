# -*- coding: utf-8 -*-
"""
Testes de mesclar_fontes_documentais() — PY/extrator_pdfs.py
Valida precedência de fontes: XML > PDF, CSV Folha > PDF.
"""
import os
import sys
from decimal import Decimal


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.extrator_pdfs import DadosExtraidosPDF, mesclar_fontes_documentais
from parsers.xml_nfe import NFeParsedData
from parsers.csv_folha import FolhaParsedData


def _dados_pdf_base(
    cnpj="12.345.678/0001-90",
    rpa="149404.00",
    folha=None,
    rbt12="1800000.00",
    receita_st=None,
) -> DadosExtraidosPDF:
    return DadosExtraidosPDF(
        cnpj=cnpj,
        razao_social="Empresa Teste Ltda",
        cnae_principal="6920601",
        uf_origem="SP",
        faturamento_12m=rbt12,
        folha_salarios_12m=folha,
        rpa_referencia=rpa,
        das_ecac_referencia="29202.78",
        competencia="01/2026",
        receita_com_st_icms=receita_st,
    )


def _nfe_data(
    cnpj_emitente="12345678000190",
    competencia="2026-01",
    valor_total=Decimal("149404.00"),
    receita_st=Decimal("0"),
    pct_b2b=Decimal("1"),
) -> NFeParsedData:
    return NFeParsedData(
        cnpj_emitente=cnpj_emitente,
        competencia=competencia,
        valor_total_mes=valor_total,
        receita_st_icms=receita_st,
        pct_clientes_b2b=pct_b2b,
        notas_processadas=1,
    )


def _folha_data(
    folha_12m=Decimal("501000.00"),
    meses=12,
) -> FolhaParsedData:
    return FolhaParsedData(
        folha_12m=folha_12m,
        meses_encontrados=meses,
        fonte_estimativa=False,
    )


# ── Testes de precedência NFe ────────────────────────────────────────────────

class TestMesclarNFe:
    def test_rpa_xml_sobrescreve_pdf(self):
        pdf = _dados_pdf_base(rpa="100000.00")
        nfe = _nfe_data(valor_total=Decimal("149404.00"))
        resultado = mesclar_fontes_documentais(pdf, nfe_data=nfe)
        assert resultado.rpa_referencia == "149404.00"

    def test_receita_st_xml_sobrescreve_pdf(self):
        pdf = _dados_pdf_base(receita_st="0.00")
        nfe = _nfe_data(receita_st=Decimal("5000.00"))
        resultado = mesclar_fontes_documentais(pdf, nfe_data=nfe)
        assert resultado.receita_com_st_icms == "5000.00"

    def test_cnpj_pdf_preservado(self):
        pdf = _dados_pdf_base(cnpj="12.345.678/0001-90")
        nfe = _nfe_data(cnpj_emitente="12345678000190")
        resultado = mesclar_fontes_documentais(pdf, nfe_data=nfe)
        # cnpj do PDF não deve ser sobrescrito
        assert resultado.cnpj == "12.345.678/0001-90"

    def test_cnpj_divergente_gera_aviso(self):
        pdf = _dados_pdf_base(cnpj="12.345.678/0001-90")
        nfe = _nfe_data(cnpj_emitente="99999999000100")
        resultado = mesclar_fontes_documentais(pdf, nfe_data=nfe)
        assert "CNPJ_DIVERGENTE" in resultado.observacoes

    def test_rpa_sem_divergencia_sem_aviso(self):
        pdf = _dados_pdf_base(rpa="149404.00")
        nfe = _nfe_data(valor_total=Decimal("149404.00"))
        resultado = mesclar_fontes_documentais(pdf, nfe_data=nfe)
        assert "CROSSCHECK_RPA_DIVERGENTE" not in resultado.observacoes

    def test_rpa_divergente_5pct_gera_aviso(self):
        pdf = _dados_pdf_base(rpa="100000.00")
        nfe = _nfe_data(valor_total=Decimal("110000.00"))  # +10%
        resultado = mesclar_fontes_documentais(pdf, nfe_data=nfe)
        assert "CROSSCHECK_RPA_DIVERGENTE" in resultado.observacoes

    def test_crosscheck_rbt12_divergente(self):
        # RBT12 PDF = 1.800.000, NFe × 12 = 149404 × 12 = 1.792.848 (~0.4% diff)
        pdf = _dados_pdf_base(rbt12="3100000.00")  # errado (caso Moreira pré-fix)
        nfe = _nfe_data(valor_total=Decimal("149404.00"))
        resultado = mesclar_fontes_documentais(pdf, nfe_data=nfe)
        assert "CROSSCHECK_RBT12" in resultado.observacoes


# ── Testes de precedência CSV Folha ──────────────────────────────────────────

class TestMesclarFolha:
    def test_folha_csv_sobrescreve_pdf_none(self):
        pdf = _dados_pdf_base(folha=None)
        folha = _folha_data(folha_12m=Decimal("501000.00"))
        resultado = mesclar_fontes_documentais(pdf, folha_data=folha)
        assert resultado.folha_salarios_12m == "501000.00"

    def test_folha_csv_sobrescreve_pdf_existente(self):
        pdf = _dados_pdf_base(folha="100000.00")
        folha = _folha_data(folha_12m=Decimal("501000.00"))
        resultado = mesclar_fontes_documentais(pdf, folha_data=folha)
        assert resultado.folha_salarios_12m == "501000.00"

    def test_aviso_estimativa_propagado(self):
        pdf = _dados_pdf_base()
        folha = FolhaParsedData(
            folha_12m=Decimal("501000.00"),
            meses_encontrados=1,
            fonte_estimativa=True,
            avisos=["ESTIMATIVA_FOLHA_1_MES: apenas 1 mês encontrado"],
        )
        resultado = mesclar_fontes_documentais(pdf, folha_data=folha)
        assert "ESTIMATIVA_FOLHA_1_MES" in resultado.observacoes


# ── Testes combinados ─────────────────────────────────────────────────────────

class TestMesclarCombinado:
    def test_nfe_e_folha_juntos(self):
        pdf = _dados_pdf_base(rpa="100000.00", folha=None)
        nfe = _nfe_data(valor_total=Decimal("149404.00"))
        folha = _folha_data(folha_12m=Decimal("501000.00"))
        resultado = mesclar_fontes_documentais(pdf, nfe_data=nfe, folha_data=folha)
        assert resultado.rpa_referencia == "149404.00"
        assert resultado.folha_salarios_12m == "501000.00"

    def test_sem_fontes_extras_retorna_original(self):
        pdf = _dados_pdf_base(rpa="149404.00", folha="501000.00")
        resultado = mesclar_fontes_documentais(pdf)
        assert resultado.rpa_referencia == "149404.00"
        assert resultado.folha_salarios_12m == "501000.00"

    def test_nfce_preenche_rpa(self):
        pdf = _dados_pdf_base(rpa="50000.00")
        nfce = NFeParsedData(
            cnpj_emitente="12345678000190",
            competencia="2026-01",
            valor_total_mes=Decimal("80000.00"),
            receita_st_icms=Decimal("0"),
            pct_clientes_b2b=Decimal("0"),
            notas_processadas=5,
            modelo="65",
        )
        resultado = mesclar_fontes_documentais(pdf, nfce_data=nfce)
        assert resultado.rpa_referencia == "80000.00"

    def test_fator_r_moreira_com_dados_reais(self):
        """
        Caso Moreira:
        - folha_12m = R$ 501.000 (CSV)
        - RBT12 = R$ 1.793.000 (PDF)
        - Fator R = 0.2795 → Anexo V (< 28%)
        LC 123/2006 Art. 18 §24
        """
        pdf = _dados_pdf_base(rbt12="1793000.00", folha="100000.00")  # folha errada no PDF
        folha = _folha_data(folha_12m=Decimal("501000.00"))
        resultado = mesclar_fontes_documentais(pdf, folha_data=folha)
        # Folha CSV tem precedência
        folha_real = Decimal(resultado.folha_salarios_12m)
        rbt12 = Decimal(resultado.faturamento_12m)
        fator_r = folha_real / rbt12
        assert fator_r < Decimal("0.28"), (
            f"Fator R {fator_r:.4f} deveria ser < 0.28 → Anexo V. "
            "LC 123/2006 Art. 18 §24"
        )
