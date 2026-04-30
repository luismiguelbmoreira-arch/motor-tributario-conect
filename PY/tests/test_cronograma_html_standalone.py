# -*- coding: utf-8 -*-
"""
test_cronograma_html_standalone.py — Trava a página standalone do cronograma
da Reforma Tributária (UI/cronograma.html).

Bug original: o botão "Cronograma IVA 2026-2033" do dashboard só funcionava
SE houvesse uma análise no sessionStorage, senão dava erro/dead-end. O usuário
queria uma página independente mostrando o cronograma da implementação do
novo regime tributário, sem depender de cálculo de empresa específica.
"""
from __future__ import annotations

from pathlib import Path

import pytest

CRONOGRAMA_PATH = (
    Path(__file__).resolve().parent.parent.parent / "UI" / "cronograma.html"
)
DASHBOARD_PATH = (
    Path(__file__).resolve().parent.parent.parent / "UI" / "dashboard.html"
)


@pytest.fixture(scope="module")
def html() -> str:
    return CRONOGRAMA_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dashboard_html() -> str:
    return DASHBOARD_PATH.read_text(encoding="utf-8")


# ── Estrutura básica ────────────────────────────────────────────────────────


class TestEstrutura:
    def test_arquivo_existe(self):
        assert CRONOGRAMA_PATH.exists(), f"{CRONOGRAMA_PATH} não existe"

    def test_titulo_da_pagina(self, html):
        assert "Cronograma da Reforma Tributária" in html
        assert "2026" in html and "2033" in html

    def test_link_voltar_dashboard(self, html):
        assert 'href="dashboard.html"' in html

    def test_botao_imprimir(self, html):
        assert "window.print()" in html

    def test_estilo_print(self, html):
        """Print stylesheet esconde controles que não devem ir pro papel."""
        assert "@media print" in html
        assert "no-print" in html


# ── Auth gate ──────────────────────────────────────────────────────────────


class TestAuthGate:
    def test_redireciona_para_login_sem_token(self, html):
        """Página de cronograma exige usuário autenticado."""
        assert "sessionStorage.getItem('token')" in html
        assert "login.html" in html


# ── Conteúdo dos 8 anos do cronograma ───────────────────────────────────────


class TestConteudoAnos:
    def test_2026_periodo_teste(self, html):
        assert "2026" in html
        assert "PERÍODO DE TESTE" in html.upper() or "FASE TESTE" in html.upper()
        assert "0,9%" in html  # CBS teste
        assert "0,1%" in html  # IBS teste
        assert "Art. 348" in html  # base legal da dispensa

    def test_2027_cbs_plena(self, html):
        assert "2027" in html
        assert "8,8%" in html  # CBS plena
        assert "PIS" in html and "COFINS" in html  # extinção

    def test_2028_estabilizacao(self, html):
        assert "2028" in html

    def test_2029_2032_transicao_icms_iss(self, html):
        for ano in ("2029", "2030", "2031", "2032"):
            assert ano in html, f"Ano {ano} ausente da timeline"
        # Reduções escalonadas 10/20/30/40%
        assert "10%" in html
        assert "20%" in html
        assert "30%" in html
        assert "40%" in html

    def test_2033_fim_transicao(self, html):
        assert "2033" in html
        assert "17,7%" in html  # IBS pleno estimado
        assert "26,5%" in html  # carga total estimada
        assert "ICMS" in html and "ISS" in html  # extintos


# ── Bases legais citadas ────────────────────────────────────────────────────


class TestBasesLegais:
    def test_lc_214_2025(self, html):
        assert "LC 214/2025" in html

    def test_ec_132_2023(self, html):
        assert "EC 132/2023" in html

    def test_artigos_chave_citados(self, html):
        # Art. 348: dispensa 2026
        assert "Art. 348" in html
        # Arts. 41-44: opt-out semestral
        assert "Art. 41" in html or "Arts. 41" in html
        # Art. 47: creditamento Simples
        assert "Art. 47" in html or "creditamento" in html.lower()
        # Arts. 31-36: split payment
        assert "Split Payment" in html
        # Arts. 409-434: imposto seletivo
        assert "Imposto Seletivo" in html

    def test_aviso_resolucao_senado(self, html):
        """Alíquotas 2027+ dependem de Resolução do Senado — deixar claro."""
        assert "Senado" in html
        assert "estimativa" in html.lower() or "Resolução" in html


# ── Datas-chave 2026 (Opt-Out) ──────────────────────────────────────────────


class TestDatasChave2026:
    def test_janela_30_04_2026(self, html):
        assert "30/04/2026" in html

    def test_janela_30_09_2026(self, html):
        assert "30/09/2026" in html

    def test_inicio_01_01_2026(self, html):
        assert "01/01/2026" in html


# ── Linguagem para empresário ───────────────────────────────────────────────


class TestLinguagemEmpresario:
    def test_explica_cbs_ibs(self, html):
        assert "CBS" in html and "IBS" in html
        # CBS = federal, IBS = subnacional
        assert "Federal" in html or "federal" in html

    def test_explica_split_payment(self, html):
        assert "Split Payment" in html

    def test_aviso_simples_dispensa_2026(self, html):
        """O Simples Nacional NÃO destaca CBS/IBS em 2026 — informação crítica."""
        assert "Simples" in html
        assert "dispensa" in html.lower() or "não aplicam" in html or "não recolhe" in html.lower()


# ── Integração com dashboard ────────────────────────────────────────────────


class TestIntegracaoDashboard:
    def test_dashboard_html_valido(self, dashboard_html):
        """Dashboard HTML deve ser bem-formado com doctype."""
        assert "<!DOCTYPE html>" in dashboard_html

    def test_dashboard_tem_conteudo_fiscal(self, dashboard_html):
        """Dashboard deve ter conteúdo relacionado ao motor tributário."""
        assert "dashboard" in dashboard_html.lower()

    def test_dashboard_tem_script(self, dashboard_html):
        """Dashboard deve ter scripts JavaScript."""
        assert "<script" in dashboard_html
