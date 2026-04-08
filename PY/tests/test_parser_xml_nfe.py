# -*- coding: utf-8 -*-
"""
Testes do parser XML NFe 4.0 — PY/parsers/xml_nfe.py
"""
import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parsers.xml_nfe import (
    NFeParsedData,
    NFeParserError,
    MODELO_NFE,
    MODELO_NFCE,
    parsear_xml_nfe,
    parsear_lote_nfe,
)

NS = "http://www.portalfiscal.inf.br/nfe"


def _xml_nfe(
    cnpj_emit="12345678000190",
    dh_emi="2026-01-15T10:00:00-03:00",
    v_nf="149404.00",
    v_icms_st="5000.00",
    ind_ie_dest="1",
    mod="55",
    chave="12345678901234567890123456789012345678901234",
) -> bytes:
    """Gera XML NFe 4.0 mínimo válido como bytes."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="{NS}" versao="4.00">
  <NFe xmlns="{NS}">
    <infNFe Id="NFe{chave}">
      <ide>
        <mod>{mod}</mod>
        <dhEmi>{dh_emi}</dhEmi>
      </ide>
      <emit>
        <CNPJ>{cnpj_emit}</CNPJ>
        <xNome>Empresa Teste Ltda</xNome>
      </emit>
      <dest>
        <CNPJ>98765432000100</CNPJ>
        <indIEDest>{ind_ie_dest}</indIEDest>
      </dest>
      <total>
        <ICMSTot>
          <vNF>{v_nf}</vNF>
          <vICMSST>{v_icms_st}</vICMSST>
          <vPIS>0.00</vPIS>
          <vCOFINS>0.00</vCOFINS>
        </ICMSTot>
      </total>
    </infNFe>
  </NFe>
</nfeProc>""".encode("utf-8")


# ── Testes básicos ────────────────────────────────────────────────────────────

class TestParsearXmlNfe:
    def test_retorna_nfe_parsed_data(self):
        resultado = parsear_xml_nfe(_xml_nfe())
        assert isinstance(resultado, NFeParsedData)

    def test_cnpj_emitente(self):
        resultado = parsear_xml_nfe(_xml_nfe(cnpj_emit="12345678000190"))
        assert resultado.cnpj_emitente == "12345678000190"

    def test_competencia_formato_yyyy_mm(self):
        resultado = parsear_xml_nfe(_xml_nfe(dh_emi="2026-01-15T10:00:00-03:00"))
        assert resultado.competencia == "2026-01"

    def test_valor_total_decimal(self):
        resultado = parsear_xml_nfe(_xml_nfe(v_nf="149404.50"))
        assert resultado.valor_total_mes == Decimal("149404.50")

    def test_icms_st_segregado(self):
        resultado = parsear_xml_nfe(_xml_nfe(v_icms_st="5000.00"))
        assert resultado.receita_st_icms == Decimal("5000.00")

    def test_contribuinte_b2b_ind_1(self):
        resultado = parsear_xml_nfe(_xml_nfe(ind_ie_dest="1"))
        assert resultado.pct_clientes_b2b == Decimal("1")

    def test_consumidor_final_ind_9(self):
        resultado = parsear_xml_nfe(_xml_nfe(ind_ie_dest="9"))
        assert resultado.pct_clientes_b2b == Decimal("0")

    def test_modelo_55(self):
        resultado = parsear_xml_nfe(_xml_nfe(mod="55"))
        assert resultado.modelo == "55"

    def test_uma_nota_processada(self):
        resultado = parsear_xml_nfe(_xml_nfe())
        assert resultado.notas_processadas == 1

    def test_xml_invalido_levanta_erro(self):
        with pytest.raises(NFeParserError):
            parsear_xml_nfe(b"nao_e_xml")

    def test_root_errado_levanta_erro(self):
        xml_errado = b'<?xml version="1.0"?><nota><valor>100</valor></nota>'
        with pytest.raises(NFeParserError):
            parsear_xml_nfe(xml_errado)

    def test_sem_cnpj_levanta_erro(self):
        xml_sem_cnpj = f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="{NS}" versao="4.00">
  <NFe xmlns="{NS}">
    <infNFe Id="NFe123">
      <ide><mod>55</mod><dhEmi>2026-01-01T00:00:00-03:00</dhEmi></ide>
      <emit><xNome>Sem CNPJ</xNome></emit>
      <total><ICMSTot><vNF>1000.00</vNF><vICMSST>0.00</vICMSST></ICMSTot></total>
    </infNFe>
  </NFe>
</nfeProc>""".encode()
        with pytest.raises(NFeParserError, match="CNPJ"):
            parsear_xml_nfe(xml_sem_cnpj)


# ── Testes de lote ────────────────────────────────────────────────────────────

class TestParsearLoteNfe:
    def test_consolida_dois_xmls(self):
        xml1 = _xml_nfe(v_nf="100000.00", chave="A" * 44)
        xml2 = _xml_nfe(v_nf="49404.00", chave="B" * 44)
        resultado = parsear_lote_nfe([xml1, xml2])
        assert resultado.valor_total_mes == Decimal("149404.00")
        assert resultado.notas_processadas == 2

    def test_soma_icms_st(self):
        xml1 = _xml_nfe(v_icms_st="3000.00", chave="A" * 44)
        xml2 = _xml_nfe(v_icms_st="2000.00", chave="B" * 44)
        resultado = parsear_lote_nfe([xml1, xml2])
        assert resultado.receita_st_icms == Decimal("5000.00")

    def test_cnpjs_diferentes_levanta_erro(self):
        xml1 = _xml_nfe(cnpj_emit="11111111000111", chave="A" * 44)
        xml2 = _xml_nfe(cnpj_emit="22222222000122", chave="B" * 44)
        with pytest.raises(NFeParserError, match="CNPJ"):
            parsear_lote_nfe([xml1, xml2])

    def test_meses_diferentes_levanta_erro(self):
        xml1 = _xml_nfe(dh_emi="2026-01-15T10:00:00-03:00", chave="A" * 44)
        xml2 = _xml_nfe(dh_emi="2026-02-10T10:00:00-03:00", chave="B" * 44)
        with pytest.raises(NFeParserError, match="meses"):
            parsear_lote_nfe([xml1, xml2])

    def test_lote_vazio_levanta_erro(self):
        with pytest.raises(NFeParserError):
            parsear_lote_nfe([])

    def test_pct_b2b_ponderado(self):
        # xml1 = R$ 100k para contribuinte, xml2 = R$ 100k para consumidor
        xml1 = _xml_nfe(v_nf="100000.00", ind_ie_dest="1", chave="A" * 44)
        xml2 = _xml_nfe(v_nf="100000.00", ind_ie_dest="9", chave="B" * 44)
        resultado = parsear_lote_nfe([xml1, xml2])
        assert resultado.pct_clientes_b2b == Decimal("0.5000")

    def test_chaves_consolidadas(self):
        xml1 = _xml_nfe(chave="A" * 44)
        xml2 = _xml_nfe(chave="B" * 44)
        resultado = parsear_lote_nfe([xml1, xml2])
        assert len(resultado.chaves_nfe) == 2
