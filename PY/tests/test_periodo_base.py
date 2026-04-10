"""
test_periodo_base.py — Testes da calculadora de período-base.

Cobre:
- Caso padrão (mes_corte=12) → ano-base = ano_alvo - 1, jan a dez
- Caso intra-ano (mes_corte=1..11) → janela móvel de 12 meses
- Validação de faixa (ano_alvo ∉ [2026, 2033] → ValueError)
- Validação de mes_corte (∉ [1, 12] → ValueError)
- Round-trip dict para serialização do endpoint
- Imutabilidade do dataclass (frozen)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.periodo_base import ANO_MAX, ANO_MIN, PeriodoBase, derivar

# ─── Caso padrão (corte anual em dezembro) ──────────────────────────────────


def test_derivar_2026_padrao_corte_dezembro():
    """ano_alvo=2026 (default mes_corte=12) → ano-base 2025 inteiro."""
    p = derivar(2026)
    assert p.ano_alvo == 2026
    assert p.mes_corte == 12
    assert p.rbt12_inicio == "2025-01"
    assert p.rbt12_fim == "2025-12"
    assert p.das_referencia == "2025-12"
    assert p.exercicio_sped == 2025
    assert "2025" in p.label_humano


def test_derivar_2027_padrao():
    """ano_alvo=2027 → ano-base 2026."""
    p = derivar(2027)
    assert p.rbt12_inicio == "2026-01"
    assert p.rbt12_fim == "2026-12"
    assert p.das_referencia == "2026-12"
    assert p.exercicio_sped == 2026


def test_derivar_2033_limite_superior():
    """ano_alvo=2033 (último ano do cronograma IVA) → ano-base 2032."""
    p = derivar(2033)
    assert p.rbt12_fim == "2032-12"
    assert p.exercicio_sped == 2032


# ─── Caso intra-ano (janela móvel) ──────────────────────────────────────────


def test_derivar_intra_ano_marco():
    """ano_alvo=2026, mes_corte=3 → janela 2025-04..2026-03."""
    p = derivar(2026, mes_corte=3)
    assert p.rbt12_inicio == "2025-04"
    assert p.rbt12_fim == "2026-03"
    # DAS de referência: último mês fechado = fevereiro/2026
    assert p.das_referencia == "2026-02"
    # SPED: último exercício fechado = 2025
    assert p.exercicio_sped == 2025


def test_derivar_intra_ano_janeiro():
    """ano_alvo=2026, mes_corte=1 → janela 2025-02..2026-01, DAS=2025-12."""
    p = derivar(2026, mes_corte=1)
    assert p.rbt12_inicio == "2025-02"
    assert p.rbt12_fim == "2026-01"
    assert p.das_referencia == "2025-12"
    assert p.exercicio_sped == 2025


def test_derivar_intra_ano_junho():
    """ano_alvo=2027, mes_corte=6 → janela 2026-07..2027-06, DAS=2027-05."""
    p = derivar(2027, mes_corte=6)
    assert p.rbt12_inicio == "2026-07"
    assert p.rbt12_fim == "2027-06"
    assert p.das_referencia == "2027-05"
    assert p.exercicio_sped == 2026


# ─── Validações de entrada ──────────────────────────────────────────────────


def test_derivar_ano_abaixo_do_minimo():
    """ano_alvo=2025 (antes do cronograma IVA) → ValueError."""
    with pytest.raises(ValueError, match="ano_alvo deve estar entre"):
        derivar(2025)


def test_derivar_ano_acima_do_maximo():
    """ano_alvo=2034 (depois do cronograma) → ValueError."""
    with pytest.raises(ValueError, match="ano_alvo deve estar entre"):
        derivar(2034)


def test_derivar_mes_corte_invalido_zero():
    with pytest.raises(ValueError, match="mes_corte deve estar entre 1 e 12"):
        derivar(2026, mes_corte=0)


def test_derivar_mes_corte_invalido_treze():
    with pytest.raises(ValueError, match="mes_corte deve estar entre 1 e 12"):
        derivar(2026, mes_corte=13)


# ─── Serialização / imutabilidade ───────────────────────────────────────────


def test_to_dict_roundtrip():
    """to_dict() retorna dict JSON-friendly com todos os campos."""
    p = derivar(2026)
    d = p.to_dict()
    assert d["ano_alvo"] == 2026
    assert d["mes_corte"] == 12
    assert d["rbt12_inicio"] == "2025-01"
    assert d["rbt12_fim"] == "2025-12"
    assert d["das_referencia"] == "2025-12"
    assert d["exercicio_sped"] == 2025
    assert "label_humano" in d
    assert isinstance(d["label_humano"], str)


def test_periodo_base_e_frozen():
    """PeriodoBase é imutável (dataclass frozen=True)."""
    p = derivar(2026)
    with pytest.raises((AttributeError, Exception)):
        p.ano_alvo = 9999  # type: ignore[misc]


def test_constantes_de_faixa_expostas():
    """ANO_MIN e ANO_MAX são exportados pra uso externo (Pydantic Field, etc.)."""
    assert ANO_MIN == 2026
    assert ANO_MAX == 2033
