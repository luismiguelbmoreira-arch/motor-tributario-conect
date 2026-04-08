# -*- coding: utf-8 -*-
"""
Testes do bloqueio 422 por documentos insuficientes — PY/api_motor.py
Testa _validar_docs_por_regime() + _detectar_tipo_documento() em isolamento.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api_motor import _detectar_tipo_documento, _sniff_xml_mod, _validar_docs_por_regime

# ── Testes de detecção de tipo ────────────────────────────────────────────────

class TestDetectarTipoDocumento:
    def test_pdf_detectado(self):
        assert _detectar_tipo_documento("pgdas_d.pdf", b"%PDF-1.4") == "pgdas_d"

    def test_xml_mod55_detectado_como_nfe(self):
        xml = b"<nfeProc><NFe><infNFe><ide><mod>55</mod></ide></infNFe></NFe></nfeProc>"
        assert _detectar_tipo_documento("nfe.xml", xml) == "nfe_saida"

    def test_xml_mod65_detectado_como_nfce(self):
        xml = b"<nfeProc><NFe><infNFe><ide><mod>65</mod></ide></infNFe></NFe></nfeProc>"
        assert _detectar_tipo_documento("nfce.xml", xml) == "nfce"

    def test_csv_detectado_como_folha(self):
        assert _detectar_tipo_documento("folha.csv", b"") == "folha_csv"

    def test_txt_detectado_como_folha(self):
        assert _detectar_tipo_documento("folha_dominio.txt", b"") == "folha_csv"

    def test_xml_sem_mod_desconhecido(self):
        xml = b"<outro>sem mod aqui</outro>"
        resultado = _detectar_tipo_documento("arquivo.xml", xml)
        assert resultado == "xml_desconhecido"


class TestSniffXmlMod:
    def test_mod55_detectado(self):
        xml = b"...<mod>55</mod>..."
        assert _sniff_xml_mod(xml) == "55"

    def test_mod65_detectado(self):
        xml = b"...<mod>65</mod>..."
        assert _sniff_xml_mod(xml) == "65"

    def test_sem_mod_retorna_vazio(self):
        xml = b"<root><valor>100</valor></root>"
        assert _sniff_xml_mod(xml) == ""


# ── Testes de validação por regime ───────────────────────────────────────────

class TestValidarDocsPorRegime:

    # B2B — todos os docs presentes
    def test_b2b_completo_sem_faltando(self):
        tipos = {"pgdas_d", "nfe_saida", "folha_csv"}
        faltando = _validar_docs_por_regime("B2B_CONTRIBUINTE", tipos)
        assert faltando == []

    # B2B — falta PGDAS-D
    def test_b2b_sem_pgdas_d(self):
        tipos = {"nfe_saida", "folha_csv"}
        faltando = _validar_docs_por_regime("B2B_CONTRIBUINTE", tipos)
        assert any("PGDAS-D" in f for f in faltando)

    # B2B — falta NFe
    def test_b2b_sem_nfe(self):
        tipos = {"pgdas_d", "folha_csv"}
        faltando = _validar_docs_por_regime("B2B_CONTRIBUINTE", tipos)
        assert any("NFe" in f for f in faltando)

    # B2B — falta folha
    def test_b2b_sem_folha(self):
        tipos = {"pgdas_d", "nfe_saida"}
        faltando = _validar_docs_por_regime("B2B_CONTRIBUINTE", tipos)
        assert any("Folha" in f or "folha" in f.lower() for f in faltando)

    # B2B — só PGDAS-D: falta NFe + folha
    def test_b2b_so_pgdas_faltam_dois(self):
        tipos = {"pgdas_d"}
        faltando = _validar_docs_por_regime("B2B_CONTRIBUINTE", tipos)
        assert len(faltando) == 2

    # B2C — completo com NFCe
    def test_b2c_com_nfce_completo(self):
        tipos = {"pgdas_d", "nfce"}
        faltando = _validar_docs_por_regime("B2C_CONSUMIDOR_FINAL", tipos)
        assert faltando == []

    # B2C — completo com CSV vendas (folha_csv conta como csv_vendas B2C)
    def test_b2c_com_csv_vendas_completo(self):
        tipos = {"pgdas_d", "folha_csv"}
        faltando = _validar_docs_por_regime("B2C_CONSUMIDOR_FINAL", tipos)
        assert faltando == []

    # B2C — sem receita B2C
    def test_b2c_sem_receita_b2c(self):
        tipos = {"pgdas_d"}
        faltando = _validar_docs_por_regime("B2C_CONSUMIDOR_FINAL", tipos)
        assert len(faltando) >= 1

    # MISTO — completo
    def test_misto_completo(self):
        tipos = {"pgdas_d", "nfe_saida", "folha_csv", "nfce"}
        faltando = _validar_docs_por_regime("MISTO", tipos)
        assert faltando == []

    # MISTO — falta NFe e folha
    def test_misto_sem_nfe_e_folha(self):
        tipos = {"pgdas_d", "nfce"}
        faltando = _validar_docs_por_regime("MISTO", tipos)
        assert len(faltando) == 2

    # Mensagem de erro cita base legal
    def test_mensagem_b2b_cita_lei(self):
        tipos = {"pgdas_d"}
        faltando = _validar_docs_por_regime("B2B_CONTRIBUINTE", tipos)
        texto_total = " ".join(faltando)
        assert "LC 123" in texto_total or "Art." in texto_total
