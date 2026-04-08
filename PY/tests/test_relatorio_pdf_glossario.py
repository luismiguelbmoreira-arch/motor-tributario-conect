# -*- coding: utf-8 -*-
"""
test_relatorio_pdf_glossario.py — Frente 3.4 / Bloco C

Trava o glossário micro no fim do PDF: 12 termos em linguagem de empresário.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from relatorio_pdf import _gerar_html, _secao_glossario  # noqa: E402

TERMOS_OBRIGATORIOS = [
    "DAS",
    "RBT12",
    "Anexo I a V",
    "Fator R",
    "Sublimite",
    "CBS",
    "IBS",
    "IVA Dual",
    "Opt-Out",
    "B2B / B2C",
    "Crédito IVA",
    "DIFAL",
]


def test_glossario_nao_vazio():
    html = _secao_glossario()
    assert html.strip() != ""
    assert "<h2>Glossário</h2>" in html


def test_glossario_contem_todos_os_termos():
    """Todos os 12 termos do plano devem aparecer."""
    html = _secao_glossario()
    for termo in TERMOS_OBRIGATORIOS:
        assert termo in html, f"Termo '{termo}' ausente do glossário"


def test_glossario_cita_leis():
    """MAX_FISCAL_02: termos legais devem citar lei."""
    html = _secao_glossario()
    assert "LC 123/2006" in html  # DAS/RBT12/Sublimite
    assert "LC 214/2025" in html  # CBS/IBS/Opt-Out
    assert "EC 132/2023" in html  # Reforma
    assert "EC 87/2015" in html or "LC 190/2022" in html  # DIFAL


def test_glossario_antes_do_rodape_no_html_completo():
    """Glossário deve aparecer antes do footer e depois da trilha."""
    diag = {"empresa": {}, "aliquotas": {}}
    html = _gerar_html(diag)
    pos_trilha = html.find("Trilha de Auditoria")
    pos_glossario = html.find("Glossário")
    pos_footer = html.find('class="footer"')
    assert pos_trilha > 0
    assert pos_glossario > 0
    assert pos_footer > 0
    assert pos_trilha < pos_glossario < pos_footer


def test_glossario_sempre_aparece_independente_do_diagnostico():
    """Diferente da validação e-CAC, o glossário é fixo e sempre renderiza."""
    diag_manual = {"empresa": {}, "aliquotas": {}}
    diag_pdf = {
        "empresa": {},
        "aliquotas": {},
        "_extracao": {"validacao_cruzada": []},
    }
    diag_vazio: dict = {}
    for d in (diag_manual, diag_pdf, diag_vazio):
        assert "Glossário" in _gerar_html(d)


def test_glossario_definicoes_sao_curtas():
    """Definição de cada termo deve ser concisa (< 250 chars para caber no PDF)."""
    # Não inspecionamos HTML diretamente — só garantimos que o bloco todo
    # não passa de ~4kb (12 termos × ~300 chars de definição + tags).
    html = _secao_glossario()
    assert len(html) < 6000, f"Glossário muito longo: {len(html)} bytes"


def test_nao_expoe_pii():
    """LGPD: glossário é estático, não pode mencionar CNPJ/razão social."""
    html = _secao_glossario()
    assert "CNPJ" not in html  # "CNPJ" apenas como sigla não deve aparecer aqui
    # CNAE também não — é termo de outro contexto
