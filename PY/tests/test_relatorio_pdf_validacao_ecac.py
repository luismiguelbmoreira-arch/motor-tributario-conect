# -*- coding: utf-8 -*-
"""
test_relatorio_pdf_validacao_ecac.py — Frente 3.5 / Bloco D

Garante que a seção "Validação contra o e-CAC" do PDF expõe corretamente
o delta DAS calculado vs DAS pago, com semáforo de cor por faixa de delta.

Hoje a validação cruzada vive em diagnostico["_extracao"]["validacao_cruzada"]
mas nunca aparecia para o cliente. Estes testes travam o comportamento novo.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from services.relatorio_pdf import _gerar_html, _secao_validacao_ecac  # noqa: E402


def _diag_com_validacao(das_calc: str, das_ecac: str, delta: str, delta_pct: str) -> dict:
    """Helper: monta diagnóstico mínimo com validação cruzada injetada."""
    return {
        "empresa": {"regime": "SIMPLES", "anexo_simples": "I", "rbt12": "1000000.00"},
        "aliquotas": {"efetiva_das_total": "0.07"},
        "_extracao": {
            "validacao_cruzada": [
                {
                    "tipo": "DAS_CALCULADO_VS_ECAC",
                    "das_calculado": das_calc,
                    "das_ecac": das_ecac,
                    "delta": delta,
                    "delta_pct": delta_pct,
                    "status": "OK",
                }
            ]
        },
    }


# ── 1. Sem validação cruzada (PDF de análise manual) ───────────────────


def test_sem_extracao_secao_oculta():
    """Análise manual não tem _extracao — seção não deve aparecer."""
    diag = {"empresa": {}, "aliquotas": {}}
    assert _secao_validacao_ecac(diag) == ""


def test_extracao_vazia_secao_oculta():
    """Se _extracao.validacao_cruzada vazio, seção não aparece."""
    diag = {"_extracao": {"validacao_cruzada": []}}
    assert _secao_validacao_ecac(diag) == ""


def test_apenas_breakdown_secao_oculta():
    """Se só tem BREAKDOWN_VS_DAS_TOTAL (sem DAS_CALCULADO_VS_ECAC), oculta."""
    diag = {
        "_extracao": {
            "validacao_cruzada": [
                {"tipo": "BREAKDOWN_VS_DAS_TOTAL", "soma_breakdown": "100", "das_ecac": "100"}
            ]
        }
    }
    assert _secao_validacao_ecac(diag) == ""


# ── 2. Semáforo verde — delta < 0,5% ───────────────────────────────────


def test_delta_zero_card_verde():
    """ITANGUA: delta 0,29% → verde."""
    diag = _diag_com_validacao("25492.84", "25567.20", "74.36", "0.29")
    html = _secao_validacao_ecac(diag)
    assert "Aprovado" in html
    assert "#10b981" in html  # cor borda verde
    assert "#065f46" in html  # cor texto verde
    assert "0,29%" in html


def test_delta_zero_absoluto_verde():
    """Valores idênticos → verde."""
    diag = _diag_com_validacao("12000.00", "12000.00", "0.00", "0.00")
    html = _secao_validacao_ecac(diag)
    assert "Aprovado" in html
    assert "#10b981" in html


# ── 3. Semáforo amarelo — 0,5% ≤ delta < 5% ────────────────────────────


def test_delta_pequeno_card_amarelo():
    """Delta 2% → amarelo."""
    diag = _diag_com_validacao("12200.00", "12000.00", "200.00", "1.67")
    html = _secao_validacao_ecac(diag)
    assert "Diferença pequena" in html
    assert "#f59e0b" in html  # borda amarela
    assert "#92400e" in html  # texto amarelo


def test_delta_borda_inferior_amarelo():
    """Delta exatamente 0,5% → amarelo (não verde)."""
    diag = _diag_com_validacao("12060.00", "12000.00", "60.00", "0.50")
    html = _secao_validacao_ecac(diag)
    assert "Diferença pequena" in html
    assert "#f59e0b" in html


# ── 4. Semáforo vermelho — delta ≥ 5% ──────────────────────────────────


def test_confi_ar_card_vermelho():
    """CONFI_AR: delta 19,8% → vermelho."""
    diag = _diag_com_validacao("12187.07", "15200.39", "3013.32", "19.82")
    html = _secao_validacao_ecac(diag)
    assert "Diferença significativa" in html
    assert "#ef4444" in html  # borda vermelha
    assert "#991b1b" in html  # texto vermelho
    assert "19,82%" in html
    # Lista possíveis causas
    assert "ICMS-ST" in html or "multi-atividade" in html or "CNAE" in html


def test_canavezi_card_vermelho_borda():
    """CANAVEZI: delta 9,7% → vermelho (>5%)."""
    diag = _diag_com_validacao("18020.32", "16428.83", "1591.49", "9.69")
    html = _secao_validacao_ecac(diag)
    assert "Diferença significativa" in html
    assert "#ef4444" in html


def test_delta_exato_5pct_vermelho():
    """Delta exatamente 5% → vermelho (limite inclusivo)."""
    diag = _diag_com_validacao("12600.00", "12000.00", "600.00", "5.00")
    html = _secao_validacao_ecac(diag)
    assert "Diferença significativa" in html


# ── 5. Integração com _gerar_html ───────────────────────────────────────


def test_gerar_html_renderiza_validacao_quando_existe():
    """O HTML completo deve incluir a seção quando há validação."""
    diag = _diag_com_validacao("12187.07", "15200.39", "3013.32", "19.82")
    html = _gerar_html(diag)
    assert "Validação contra o e-CAC" in html
    assert "Diferença significativa" in html


def test_gerar_html_sem_validacao_nao_quebra():
    """PDF de análise manual continua funcionando sem a seção."""
    diag = {"empresa": {}, "aliquotas": {}}
    html = _gerar_html(diag)
    assert "Validação contra o e-CAC" not in html
    # Mas o resto do PDF é gerado normalmente
    assert "Situação Atual" in html


def test_validacao_aparece_antes_dos_alertas():
    """Ordem importa: validação antes de alertas (foi a decisão do plano)."""
    diag = _diag_com_validacao("12000", "12000", "0.00", "0.00")
    html = _gerar_html(diag)
    pos_validacao = html.find("Validação contra o e-CAC")
    pos_alertas = html.find("Alertas de Risco")
    assert pos_validacao > 0
    assert pos_alertas > 0
    assert pos_validacao < pos_alertas


# ── 6. Robustez ─────────────────────────────────────────────────────────


def test_valores_malformados_nao_quebram():
    """delta_pct inválido → seção oculta sem exception."""
    diag = {
        "_extracao": {
            "validacao_cruzada": [
                {
                    "tipo": "DAS_CALCULADO_VS_ECAC",
                    "das_calculado": "abc",
                    "das_ecac": "xyz",
                    "delta": "?",
                    "delta_pct": "?",
                }
            ]
        }
    }
    # Não levanta — retorna string vazia
    assert _secao_validacao_ecac(diag) == ""


def test_amparo_legal_citado():
    """MAX_FISCAL_02: toda seção cita lei."""
    diag = _diag_com_validacao("12000", "12000", "0.00", "0.00")
    html = _secao_validacao_ecac(diag)
    assert "LC 123/2006" in html
    assert "Art. 18" in html
