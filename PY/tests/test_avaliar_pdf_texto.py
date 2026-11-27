# -*- coding: utf-8 -*-
"""tests/test_avaliar_pdf_texto.py — sonda de texto local em PDF (sem pdfplumber no CI)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import builtins

from scripts import avaliar_pdf_texto as av

# Texto fictício no formato do extrato PGDAS-D (sem dado real de cliente)
EXTRATO_FICTICIO = """
CNPJ Estabelecimento: 11.222.333/0001-81
Nome Empresarial: EMPRESA EXEMPLO LTDA
Período de Apuração (PA): 01/2026
Receita Bruta do PA (RPA) - Competência 1.000,00 0,00 1.000,00
(RBT12)
Município: EXEMPLO UF: SP
IRPJ CSLL COFINS PIS/Pasep INSS/CPP ICMS IPI ISS Total
4) Informações sobre DAS Gerado na apuração: 00000000000000000
"""


def test_rotulos_do_extrato_ficticio():
    r = av.rotulos_presentes(EXTRATO_FICTICIO)
    for campo in ("cnpj", "razao_social", "uf_origem", "faturamento_12m", "rpa_referencia",
                  "competencia", "das_ecac_referencia", "das_breakdown"):
        assert r[campo], campo
    assert r["cnae_principal"] is False  # extrato PGDAS-D não traz CNAE


def test_pagina_escaneada_conta_como_sem_texto():
    r = av.avaliar_textos(["", "   ", EXTRATO_FICTICIO])
    assert r["paginas"] == 3 and r["paginas_sem_texto"] == 2
    assert r["caracteres"] > 0


def test_sem_pdfplumber_sai_com_2(monkeypatch, tmp_path, capsys):
    original = builtins.__import__

    def sem_pdfplumber(nome, *a, **k):
        if nome == "pdfplumber":
            raise ImportError(nome)
        return original(nome, *a, **k)

    monkeypatch.setattr(builtins, "__import__", sem_pdfplumber)
    assert av.main([str(tmp_path)]) == 2
    assert "pdfplumber" in capsys.readouterr().err
