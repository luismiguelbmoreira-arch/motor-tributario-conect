# -*- coding: utf-8 -*-
"""
test_imposto_seletivo.py — Cobertura de core/imposto_seletivo.py.

LC 214/2025 Arts. 409 § 1º + 410 + 412 + 544.
Validado por Escrivão em 30/04/2026.
"""

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.imposto_seletivo import (
    DATA_INICIO_VIGENCIA,
    NCMS_SUJEITOS,
    ExposicaoSeletivo,
    categoria_seletivo,
    detectar_exposicao,
    eh_sujeito_ao_seletivo,
    is_aplicavel_em,
)


# ── is_aplicavel_em (Art. 544 — vigência 1º/01/2027) ─────────────────────────

def test_vigencia_inicio_eh_2027_01_01():
    assert DATA_INICIO_VIGENCIA == date(2027, 1, 1)


def test_aplicavel_no_primeiro_dia_de_vigencia():
    assert is_aplicavel_em(date(2027, 1, 1)) is True


def test_nao_aplicavel_no_dia_anterior_a_vigencia():
    assert is_aplicavel_em(date(2026, 12, 31)) is False


def test_nao_aplicavel_em_2026():
    assert is_aplicavel_em(date(2026, 6, 15)) is False


def test_aplicavel_em_2028_e_seguintes():
    assert is_aplicavel_em(date(2028, 1, 1)) is True
    assert is_aplicavel_em(date(2033, 12, 31)) is True


# ── categoria_seletivo (mapeamento NCM por prefixo 4 dígitos) ────────────────

@pytest.mark.parametrize("ncm", ["24021000", "24023000", "24029000"])
def test_cigarro_cap_2402_eh_fumigeno(ncm: str):
    assert categoria_seletivo(ncm) == "PRODUTOS_FUMIGENOS"


@pytest.mark.parametrize("ncm", ["24031100", "24039100"])
def test_outros_tabacos_cap_2403_eh_fumigeno(ncm: str):
    assert categoria_seletivo(ncm) == "PRODUTOS_FUMIGENOS"


@pytest.mark.parametrize("ncm,categoria", [
    ("22030000", "BEBIDAS_ALCOOLICAS"),
    ("22041000", "BEBIDAS_ALCOOLICAS"),
    ("22051000", "BEBIDAS_ALCOOLICAS"),
    ("22060000", "BEBIDAS_ALCOOLICAS"),
    ("22071000", "BEBIDAS_ALCOOLICAS"),
    ("22082000", "BEBIDAS_ALCOOLICAS"),
])
def test_bebidas_alcoolicas_cap_2203_2208(ncm, categoria):
    assert categoria_seletivo(ncm) == categoria


def test_refrigerante_cap_2202_eh_acucarada():
    assert categoria_seletivo("22021000") == "BEBIDAS_ACUCARADAS"


def test_combustivel_2710_nao_eh_seletivo():
    """Combustíveis vão pro regime monofásico Art. 172, NÃO Imposto Seletivo."""
    assert categoria_seletivo("27109999") is None


def test_ncm_industrial_padrao_nao_eh_seletivo():
    assert categoria_seletivo("84818099") is None  # válvula industrial


def test_ncm_curto_retorna_none():
    """Strings com menos de 4 caracteres não disparam falso positivo."""
    assert categoria_seletivo("220") is None
    assert categoria_seletivo("") is None


def test_ncm_nao_string_retorna_none():
    """Defesa em camadas — entrada não-string não trava o motor."""
    assert categoria_seletivo(None) is None  # type: ignore[arg-type]
    assert categoria_seletivo(12345678) is None  # type: ignore[arg-type]


# ── eh_sujeito_ao_seletivo (atalho boolean) ──────────────────────────────────

def test_atalho_true_para_cigarro():
    assert eh_sujeito_ao_seletivo("24021000") is True


def test_atalho_false_para_combustivel():
    """Combustível NÃO é Seletivo (é monofásico)."""
    assert eh_sujeito_ao_seletivo("27109999") is False


def test_atalho_false_para_ncm_padrao():
    assert eh_sujeito_ao_seletivo("84818099") is False


# ── detectar_exposicao (output estruturado) ──────────────────────────────────

def test_detectar_em_2027_marca_vigente():
    exp = detectar_exposicao("22021000", date(2027, 6, 1))
    assert exp is not None
    assert exp.categoria == "BEBIDAS_ACUCARADAS"
    assert exp.vigente_na_data is True
    assert exp.aliquota_disponivel is False  # PLP 42/2026 não sancionada


def test_detectar_em_2026_marca_nao_vigente():
    exp = detectar_exposicao("22021000", date(2026, 6, 1))
    assert exp is not None
    assert exp.vigente_na_data is False


def test_detectar_amparo_legal_completo():
    exp = detectar_exposicao("24021000", date(2027, 6, 1))
    assert exp is not None
    assert "LC 214/2025" in exp.amparo_legal
    assert "Art. 409" in exp.amparo_legal
    assert "Art. 410" in exp.amparo_legal
    assert "Art. 544" in exp.amparo_legal


def test_detectar_ncm_fora_do_mapa_retorna_none():
    assert detectar_exposicao("84818099", date(2027, 6, 1)) is None


def test_detectar_combustivel_retorna_none():
    """Combustível 2710 NÃO é Seletivo — não retorna ExposicaoSeletivo."""
    assert detectar_exposicao("27109999", date(2027, 6, 1)) is None


def test_exposicao_eh_pydantic_frozen():
    exp = detectar_exposicao("22021000", date(2027, 6, 1))
    assert exp is not None
    with pytest.raises(Exception):
        exp.vigente_na_data = False


# ── Tabela NCMS_SUJEITOS — invariantes estruturais ───────────────────────────

def test_tabela_nao_inclui_combustivel_2710():
    """Combustível NÃO faz parte do Seletivo (é monofásico Art. 172)."""
    assert "2710" not in NCMS_SUJEITOS


def test_tabela_cobre_capitulos_validados_pelo_escrivao():
    """Capítulos confirmados em fonte secundária autoritativa (30/04/2026)."""
    esperados = {"2402", "2403", "2203", "2204", "2205", "2206", "2207", "2208", "2202"}
    assert set(NCMS_SUJEITOS.keys()) == esperados


def test_tabela_categorias_validas_apenas():
    """Toda categoria do mapa deve ser uma das 8 do Literal CategoriaSeletivo."""
    permitidas = {
        "PRODUTOS_FUMIGENOS", "BEBIDAS_ALCOOLICAS", "BEBIDAS_ACUCARADAS",
        "VEICULOS", "EMBARCACOES", "AERONAVES", "BENS_MINERAIS",
        "APOSTAS_PROGNOSTICOS",
    }
    assert all(cat in permitidas for cat in NCMS_SUJEITOS.values())


# ── Anti-extrapolação (Rail R2) — sem alíquotas hardcoded ─────────────────────

def test_modulo_nao_expoe_aliquota_alguma():
    """
    Rail R2 — alíquotas do IS estão delegadas a lei ordinária (PLP 42/2026,
    em tramitação). Motor não pode codificar nenhuma alíquota numérica.
    """
    import core.imposto_seletivo as mod

    nomes_proibidos = {"ALIQUOTA", "ALIQUOTAS", "PERCENTUAL"}
    publicos_alarmantes = [
        nome for nome in dir(mod)
        if not nome.startswith("_")
        and any(palavra in nome.upper() for palavra in nomes_proibidos)
    ]
    assert publicos_alarmantes == [], (
        f"Rail R2 violado — símbolos públicos sugerindo alíquota: {publicos_alarmantes}. "
        "Alíquotas do IS estão delegadas a lei ordinária (PLP 42/2026)."
    )
