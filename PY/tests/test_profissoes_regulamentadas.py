# -*- coding: utf-8 -*-
"""
test_profissoes_regulamentadas.py — Cobertura de core/profissoes_regulamentadas.py
+ campo schema EmpresaFornecedora.profissao_regulamentada
+ validar_profissao_regulamentada em validadores.py.

LC 214/2025 Art. 127 (validado por Escrivão em 30/04/2026).
"""

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.profissoes_regulamentadas import (
    PROFISSOES_ART_127,
    ProfissaoRegulamentada,
    amparo_legal_profissao,
    aplica_reducao_30,
)
from schemas.motor import EmpresaFornecedora
from validadores import validar_profissao_regulamentada


# ── Tabela PROFISSOES_ART_127 ────────────────────────────────────────────────

def test_tabela_tem_18_profissoes():
    """Art. 127 tem 18 incisos exatos."""
    assert len(PROFISSOES_ART_127) == 18


def test_tabela_incisos_unicos_e_em_ordem():
    """Cada inciso deve ser único; não pode haver duplicatas (I, II, III...XVIII)."""
    incisos = [p.inciso for p in PROFISSOES_ART_127.values()]
    assert len(incisos) == len(set(incisos))
    esperados = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX",
                 "X", "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII"]
    assert sorted(incisos, key=esperados.index) == esperados


def test_advogado_inciso_ii_oab():
    p = PROFISSOES_ART_127["ADVOGADO"]
    assert p.inciso == "II"
    assert "Lei 8.906/1994" in p.lei_conselho
    assert "OAB" in p.lei_conselho


def test_contabilista_inciso_vii_crc():
    p = PROFISSOES_ART_127["CONTABILISTA"]
    assert p.inciso == "VII"
    assert "9.295/1946" in p.lei_conselho
    assert "CRC" in p.lei_conselho or "CFC" in p.lei_conselho


def test_engenheiro_inciso_xi_crea():
    p = PROFISSOES_ART_127["ENGENHEIRO_AGRONOMO"]
    assert p.inciso == "XI"
    assert "5.194/1966" in p.lei_conselho
    assert "CREA" in p.lei_conselho or "CONFEA" in p.lei_conselho


def test_arquiteto_inciso_iii_cau():
    p = PROFISSOES_ART_127["ARQUITETO_URBANISTA"]
    assert p.inciso == "III"
    assert "12.378/2010" in p.lei_conselho
    assert "CAU" in p.lei_conselho


def test_veterinario_inciso_xiii_e_nao_medico_humano():
    """Apenas veterinários — médico humano NÃO está no Art. 127."""
    p = PROFISSOES_ART_127["MEDICO_VETERINARIO_ZOOTECNISTA"]
    assert p.inciso == "XIII"
    assert "veterinário" in p.nome.lower()
    # Confirma ausência de medicina humana na tabela
    medicos_humanos = [c for c in PROFISSOES_ART_127.keys() if c == "MEDICO" or c == "MEDICO_HUMANO"]
    assert medicos_humanos == []


def test_profissao_eh_pydantic_frozen():
    p = PROFISSOES_ART_127["ADVOGADO"]
    with pytest.raises(Exception):
        p.inciso = "X"


# ── aplica_reducao_30 ────────────────────────────────────────────────────────

def test_aplica_reducao_advogado_true():
    assert aplica_reducao_30("ADVOGADO") is True


def test_aplica_reducao_none_false():
    """Default conservador — sem profissão declarada = sem redução."""
    assert aplica_reducao_30(None) is False


def test_aplica_reducao_codigo_invalido_false():
    """MEDICO (humano) não está no Art. 127."""
    assert aplica_reducao_30("MEDICO") is False
    assert aplica_reducao_30("DENTISTA") is False
    assert aplica_reducao_30("JORNALISTA") is False


def test_aplica_reducao_string_vazia_false():
    assert aplica_reducao_30("") is False


# ── amparo_legal_profissao ───────────────────────────────────────────────────

def test_amparo_legal_advogado_cita_inciso_ii_e_oab():
    """Usa "inciso II;" (com ;) pra evitar match em "inciso III/VIII/XII/XIII/XVII/XVIII"."""
    amparo = amparo_legal_profissao("ADVOGADO")
    assert "LC 214/2025" in amparo
    assert "Art. 127" in amparo
    assert "inciso II;" in amparo
    assert "8.906/1994" in amparo


def test_amparo_legal_contabilista_cita_inciso_vii_e_crc():
    amparo = amparo_legal_profissao("CONTABILISTA")
    assert "inciso VII;" in amparo  # ; separa do nome da lei
    assert "9.295/1946" in amparo


def test_amparo_legal_codigo_invalido_levanta():
    with pytest.raises(ValueError, match="não consta no Art. 127"):
        amparo_legal_profissao("MEDICO")


# ── validar_profissao_regulamentada ──────────────────────────────────────────

def test_validar_none_aceita():
    res = validar_profissao_regulamentada(None)
    assert res.ok is True
    assert res.errors == []


def test_validar_codigo_valido_aceita():
    assert validar_profissao_regulamentada("ADVOGADO").ok is True
    assert validar_profissao_regulamentada("CONTABILISTA").ok is True


def test_validar_codigo_invalido_rejeita():
    res = validar_profissao_regulamentada("MEDICO")
    assert res.ok is False
    assert any("não consta no Art. 127" in e for e in res.errors)


def test_validar_tipo_errado_rejeita():
    res = validar_profissao_regulamentada(123)  # type: ignore[arg-type]
    assert res.ok is False
    assert any("deve ser str ou None" in e for e in res.errors)


def test_validar_lista_codigos_no_erro_pra_facilitar_correcao():
    """Erro deve listar os códigos válidos pra facilitar a correção."""
    res = validar_profissao_regulamentada("XPTO")
    assert res.ok is False
    assert any("ADVOGADO" in e for e in res.errors)
    assert any("CONTABILISTA" in e for e in res.errors)


# ── Schema EmpresaFornecedora.profissao_regulamentada ────────────────────────

def _empresa_base(profissao=None) -> EmpresaFornecedora:
    """Builder mínimo de EmpresaFornecedora pra exercitar o campo."""
    kwargs = {
        "cnpj": "11222333000181",
        "razao_social": "Escritório Teste Ltda",
        "regime": "SIMPLES",
        "cnae_principal": "6911701",
        "uf_origem": "SP",
        "faturamento_12m": Decimal("500000"),
    }
    if profissao is not None:
        kwargs["profissao_regulamentada"] = profissao
    return EmpresaFornecedora(**kwargs)


def test_schema_default_profissao_eh_none():
    empresa = _empresa_base()
    assert empresa.profissao_regulamentada is None


def test_schema_aceita_profissao_valida():
    empresa = _empresa_base(profissao="ADVOGADO")
    assert empresa.profissao_regulamentada == "ADVOGADO"


def test_schema_rejeita_profissao_invalida():
    """Pydantic Literal rejeita valores fora da lista (gate em Camada 1)."""
    with pytest.raises(Exception):  # ValidationError do Pydantic
        _empresa_base(profissao="MEDICO")


def test_schema_aceita_todas_18_profissoes_do_art_127():
    """Todas as 18 entries da tabela devem ser aceitas pelo schema."""
    for codigo in PROFISSOES_ART_127.keys():
        empresa = _empresa_base(profissao=codigo)
        assert empresa.profissao_regulamentada == codigo
