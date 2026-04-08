"""
test_catalogo_documentos.py — Testes snapshot do catálogo por perfil × regime.

Cobre:
- Simples B2B_CONTRIBUINTE → PGDAS-D + NFe + Folha (obrigatórios)
- Simples B2C_CONSUMIDOR_FINAL → PGDAS-D + NFCe (sem NFe 55)
- Simples MISTO → NFe + NFCe + Folha
- MEI → apenas DAS-SIMEI (sem folha, sem SPED)
- PRESUMIDO → SPED ECD + EFD-Contrib obrigatórios
- Perfil/regime inválidos → ValueError
- Formatação do período (intra-ano e padrão)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas.catalogo_documentos import montar_cards
from utils.periodo_base import derivar

# ─── Helpers ─────────────────────────────────────────────────────────────


def _ids(cards):
    return [c.id for c in cards]


def _obrigatorios(cards):
    return {c.id for c in cards if c.obrigatorio}


# ─── Simples Nacional ────────────────────────────────────────────────────


def test_simples_b2b_contribuinte_contem_nfe_e_folha():
    p = derivar(2026)
    cards = montar_cards("B2B_CONTRIBUINTE", "SIMPLES", p)
    ids = _ids(cards)
    assert "pgdas_d" in ids
    assert "nfe_saida" in ids
    assert "folha_csv" in ids
    assert "nfce" not in ids  # B2B puro não renderiza NFCe


def test_simples_b2c_nao_contem_nfe_saida():
    p = derivar(2026)
    cards = montar_cards("B2C_CONSUMIDOR_FINAL", "SIMPLES", p)
    ids = _ids(cards)
    assert "pgdas_d" in ids
    assert "nfce" in ids
    assert "nfe_saida" not in ids


def test_simples_misto_contem_nfe_e_nfce():
    p = derivar(2026)
    cards = montar_cards("MISTO", "SIMPLES", p)
    ids = _ids(cards)
    assert "nfe_saida" in ids
    assert "nfce" in ids
    assert "folha_csv" in ids


def test_simples_obrigatorios_b2b():
    p = derivar(2026)
    cards = montar_cards("B2B_CONTRIBUINTE", "SIMPLES", p)
    obrig = _obrigatorios(cards)
    # PGDAS-D, NFe e Folha são obrigatórios em Simples B2B
    assert "pgdas_d" in obrig
    assert "nfe_saida" in obrig
    assert "folha_csv" in obrig
    # DAS e SPED ECD são recomendados (não bloqueantes) no Simples
    assert "das" not in obrig
    assert "sped_ecd" not in obrig


# ─── MEI ─────────────────────────────────────────────────────────────────


def test_mei_apenas_das_simei():
    p = derivar(2026)
    cards = montar_cards("B2B_CONTRIBUINTE", "MEI", p)
    assert len(cards) == 1
    assert cards[0].id == "das"
    assert cards[0].obrigatorio is True
    assert "Art. 18-A" in cards[0].amparo_legal
    assert "folha_csv" not in _ids(cards)
    assert "pgdas_d" not in _ids(cards)


# ─── Lucro Presumido / Real ──────────────────────────────────────────────


def test_presumido_obriga_sped_ecd_e_efd_contrib():
    p = derivar(2026)
    cards = montar_cards("B2B_CONTRIBUINTE", "PRESUMIDO", p)
    obrig = _obrigatorios(cards)
    assert "sped_ecd" in obrig
    assert "sped_efd_contrib" in obrig
    # PGDAS-D NÃO aparece fora do Simples
    assert "pgdas_d" not in _ids(cards)


def test_real_b2c_nao_tem_nfe_saida():
    p = derivar(2026)
    cards = montar_cards("B2C_CONSUMIDOR_FINAL", "REAL", p)
    ids = _ids(cards)
    assert "nfce" in ids
    assert "nfe_saida" not in ids
    assert "sped_ecd" in ids


# ─── Formatação do período ───────────────────────────────────────────────


def test_periodo_label_padrao_dezembro():
    p = derivar(2026)
    cards = montar_cards("B2B_CONTRIBUINTE", "SIMPLES", p)
    nfe = next(c for c in cards if c.id == "nfe_saida")
    assert nfe.periodo_label == "01/2025 a 12/2025"
    assert nfe.periodo_iso == "2025-01..2025-12"


def test_periodo_label_intra_ano():
    p = derivar(2026, mes_corte=3)
    cards = montar_cards("B2B_CONTRIBUINTE", "SIMPLES", p)
    nfe = next(c for c in cards if c.id == "nfe_saida")
    assert nfe.periodo_label == "04/2025 a 03/2026"
    assert nfe.periodo_iso == "2025-04..2026-03"


def test_das_label_humano():
    p = derivar(2026)
    cards = montar_cards("B2B_CONTRIBUINTE", "SIMPLES", p)
    das = next(c for c in cards if c.id == "das")
    assert das.periodo_label == "Dezembro/2025"
    assert das.periodo_iso == "2025-12"


def test_sped_label_exercicio():
    p = derivar(2026)
    cards = montar_cards("B2B_CONTRIBUINTE", "PRESUMIDO", p)
    ecd = next(c for c in cards if c.id == "sped_ecd")
    assert ecd.periodo_label == "Exercício 2025"
    assert ecd.periodo_iso == "2025"


# ─── Validações de entrada ───────────────────────────────────────────────


def test_perfil_invalido_levanta_valueerror():
    p = derivar(2026)
    with pytest.raises(ValueError, match="perfil inválido"):
        montar_cards("LIXO", "SIMPLES", p)


def test_regime_invalido_levanta_valueerror():
    p = derivar(2026)
    with pytest.raises(ValueError, match="regime inválido"):
        montar_cards("B2B_CONTRIBUINTE", "LIXO", p)


# ─── Amparo legal presente em todos os cards ─────────────────────────────


def test_todos_cards_tem_amparo_legal():
    p = derivar(2026)
    for perfil in ("B2B_CONTRIBUINTE", "B2C_CONSUMIDOR_FINAL", "MISTO"):
        for regime in ("SIMPLES", "PRESUMIDO", "REAL", "MEI"):
            cards = montar_cards(perfil, regime, p)
            for c in cards:
                assert c.amparo_legal, f"{perfil}/{regime}/{c.id} sem amparo"
                assert c.periodo_label, f"{perfil}/{regime}/{c.id} sem periodo_label"
                assert c.periodo_iso, f"{perfil}/{regime}/{c.id} sem periodo_iso"
