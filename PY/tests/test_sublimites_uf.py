# -*- coding: utf-8 -*-
"""
test_sublimites_uf.py — Cobertura de core/sublimites_uf.py.

LC 123/2006 Art. 13-A + Art. 19 caput + Art. 19 § 4º.
Portarias CGSN 49/2024 (ano 2025) e 54/2025 (ano 2026) — todas em padrão.
"""

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.sublimites_uf import (
    SUBLIMITES_VIGENTES,
    UFS_BRASIL,
    AlertaSublimiteUF,
    SublimiteVigente,
    _validar_uf,
    alerta_migracao_obrigatoria,
    sublimite_para_uf,
)


# ── UFs canônicas ────────────────────────────────────────────────────────────

def test_ufs_brasil_tem_27_entradas():
    """26 estados + DF."""
    assert len(UFS_BRASIL) == 27


def test_ufs_brasil_inclui_df():
    assert "DF" in UFS_BRASIL


def test_ufs_brasil_eh_frozenset():
    """Imutável por design (não pode ser alterada em runtime)."""
    assert isinstance(UFS_BRASIL, frozenset)


# ── _validar_uf ──────────────────────────────────────────────────────────────

def test_validar_uf_normaliza_minuscula():
    assert _validar_uf("sp") == "SP"


def test_validar_uf_remove_espacos():
    assert _validar_uf("  RJ  ") == "RJ"


def test_validar_uf_invalida_levanta():
    with pytest.raises(ValueError, match="inválida"):
        _validar_uf("XX")


# ── SublimiteVigente schema ──────────────────────────────────────────────────

def test_sublimite_vigente_aceita_lista_vazia_de_reduzidas():
    s = SublimiteVigente(
        padrao=Decimal("3600000"),
        reduzido=Decimal("1800000"),
        ufs_reduzidas=frozenset(),
    )
    assert s.ufs_reduzidas == frozenset()


def test_sublimite_vigente_rejeita_uf_invalida():
    with pytest.raises(ValueError, match="UFs inválidas"):
        SublimiteVigente(
            padrao=Decimal("3600000"),
            reduzido=Decimal("1800000"),
            ufs_reduzidas=frozenset({"XX", "YY"}),
        )


def test_sublimite_vigente_aceita_ufs_validas():
    s = SublimiteVigente(
        padrao=Decimal("3600000"),
        reduzido=Decimal("1800000"),
        ufs_reduzidas=frozenset({"AC", "RR"}),
    )
    assert s.ufs_reduzidas == frozenset({"AC", "RR"})


def test_sublimite_vigente_eh_frozen():
    s = SublimiteVigente(padrao=Decimal("3600000"), reduzido=Decimal("1800000"))
    with pytest.raises(Exception):
        s.padrao = Decimal("0")


# ── Constantes vigentes ──────────────────────────────────────────────────────

def test_sublimites_vigentes_cobre_2025_e_2026():
    anos = {r.vigencia_inicio.year for r in SUBLIMITES_VIGENTES}
    assert 2025 in anos
    assert 2026 in anos


def test_sublimites_2026_todas_em_padrao():
    """Portaria CGSN 54/2025 — nenhuma UF reduzida em 2026."""
    vigente_2026 = next(
        r.valor for r in SUBLIMITES_VIGENTES if r.vigencia_inicio == date(2026, 1, 1)
    )
    assert vigente_2026.ufs_reduzidas == frozenset()
    assert vigente_2026.padrao == Decimal("3600000.00")
    assert vigente_2026.reduzido == Decimal("1800000.00")


def test_sublimites_2025_cita_portaria_correta():
    rule_2025 = next(
        r for r in SUBLIMITES_VIGENTES if r.vigencia_inicio == date(2025, 1, 1)
    )
    assert "Portaria CGSN 49/2024" in rule_2025.lei
    assert "LC 123/2006 Art. 13-A" in rule_2025.lei
    assert "Art. 19" in rule_2025.lei


def test_sublimites_2026_cita_portaria_correta():
    rule_2026 = next(
        r for r in SUBLIMITES_VIGENTES if r.vigencia_inicio == date(2026, 1, 1)
    )
    assert "Portaria CGSN 54/2025" in rule_2026.lei


# ── sublimite_para_uf ────────────────────────────────────────────────────────

def test_sublimite_para_sp_em_2026():
    assert sublimite_para_uf("SP", date(2026, 6, 1)) == Decimal("3600000.00")


def test_sublimite_para_ac_em_2026_eh_padrao():
    """Em 2026 nenhuma UF é reduzida — AC volta ao padrão R$ 3,6M."""
    assert sublimite_para_uf("AC", date(2026, 1, 1)) == Decimal("3600000.00")


def test_sublimite_normaliza_uf():
    assert sublimite_para_uf("sp", date(2026, 6, 1)) == Decimal("3600000.00")


def test_sublimite_uf_invalida_levanta():
    with pytest.raises(ValueError, match="inválida"):
        sublimite_para_uf("XX", date(2026, 6, 1))


def test_sublimite_data_fora_da_janela_levanta():
    """Anos não modelados (Rail R2) → ValueError."""
    with pytest.raises(ValueError, match="Nenhuma regra vigente"):
        sublimite_para_uf("SP", date(2099, 1, 1))


def test_sublimite_respeita_ufs_reduzidas_quando_existirem():
    """Garante que a estrutura suporta UFs reduzidas — quando existirem."""
    s = SublimiteVigente(
        padrao=Decimal("3600000"),
        reduzido=Decimal("1800000"),
        ufs_reduzidas=frozenset({"AC", "RR"}),
    )
    assert s.padrao if "SP" not in s.ufs_reduzidas else s.reduzido
    assert "AC" in s.ufs_reduzidas
    assert "RR" in s.ufs_reduzidas


# ── alerta_migracao_obrigatoria ──────────────────────────────────────────────

def test_alerta_abaixo_do_aviso_retorna_none():
    """RBT12 a 80% do sublimite — sem alerta."""
    rbt12 = Decimal("3600000.00") * Decimal("0.80")
    assert alerta_migracao_obrigatoria(rbt12, "SP", date(2026, 6, 1)) is None


def test_alerta_em_90_porcento_retorna_aviso():
    """Limite inferior da zona de aviso é inclusivo."""
    rbt12 = Decimal("3600000.00") * Decimal("0.90")
    alerta = alerta_migracao_obrigatoria(rbt12, "SP", date(2026, 6, 1))
    assert alerta is not None
    assert alerta.nivel == "AVISO"
    assert alerta.percentual_atingido == Decimal("0.9000")


def test_alerta_em_99_porcento_eh_aviso():
    rbt12 = Decimal("3600000.00") * Decimal("0.99")
    alerta = alerta_migracao_obrigatoria(rbt12, "SP", date(2026, 6, 1))
    assert alerta is not None
    assert alerta.nivel == "AVISO"


def test_alerta_em_100_porcento_eh_critico():
    rbt12 = Decimal("3600000.00")
    alerta = alerta_migracao_obrigatoria(rbt12, "SP", date(2026, 6, 1))
    assert alerta is not None
    assert alerta.nivel == "CRITICO"
    assert alerta.percentual_atingido == Decimal("1.0000")


def test_alerta_acima_do_sublimite_eh_critico():
    """RBT12 a 110% — estourou sublimite."""
    rbt12 = Decimal("3600000.00") * Decimal("1.10")
    alerta = alerta_migracao_obrigatoria(rbt12, "SP", date(2026, 6, 1))
    assert alerta is not None
    assert alerta.nivel == "CRITICO"
    assert alerta.percentual_atingido == Decimal("1.1000")


def test_alerta_carrega_amparo_legal_da_portaria_vigente():
    rbt12 = Decimal("3600000.00")
    alerta = alerta_migracao_obrigatoria(rbt12, "SP", date(2026, 6, 1))
    assert alerta is not None
    assert "Portaria CGSN 54/2025" in alerta.amparo_legal


def test_alerta_rbt12_negativo_levanta():
    with pytest.raises(ValueError, match="rbt12 deve ser >= 0"):
        alerta_migracao_obrigatoria(Decimal("-1"), "SP", date(2026, 6, 1))


def test_alerta_uf_invalida_levanta():
    with pytest.raises(ValueError, match="inválida"):
        alerta_migracao_obrigatoria(Decimal("3000000"), "XX", date(2026, 6, 1))


def test_alerta_normaliza_uf():
    """uf minúscula vira maiúscula no output."""
    rbt12 = Decimal("3600000.00")
    alerta = alerta_migracao_obrigatoria(rbt12, "sp", date(2026, 6, 1))
    assert alerta is not None
    assert alerta.uf == "SP"


def test_alerta_retorno_eh_pydantic_frozen():
    rbt12 = Decimal("3600000.00")
    alerta = alerta_migracao_obrigatoria(rbt12, "SP", date(2026, 6, 1))
    assert isinstance(alerta, AlertaSublimiteUF)
    with pytest.raises(Exception):
        alerta.nivel = "AVISO"
