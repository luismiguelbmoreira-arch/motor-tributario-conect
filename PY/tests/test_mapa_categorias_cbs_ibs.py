# -*- coding: utf-8 -*-
"""
test_mapa_categorias_cbs_ibs.py — Cobertura subfase 2.0 do mapa-mestre.

LC 214/2025 Arts. 47 + 57. Validado por Escrivão em 30/04/2026.
Apenas categorias com confiança ALTA estão no mapa nesta subfase.
"""

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.mapa_categorias_cbs_ibs import (
    MAPA_CATEGORIAS_VERSIONADO,
    ClassificacaoCredito,
    _mapa_subfase_2_0,
    classificar,
    gera_credito,
    listar_categorias_creditaveis,
)


_DATA_2026 = date(2026, 6, 15)
_DATA_2027 = date(2027, 6, 15)


# ── Schema ClassificacaoCredito ──────────────────────────────────────────────

def test_schema_eh_pydantic_frozen():
    """Frozen=True impede mutação (Rail R5 — separação rígida)."""
    c = classificar("ENERGIA_ELETRICA", _DATA_2026)
    assert c is not None
    with pytest.raises(Exception):
        c.gera_credito = False


def test_schema_extra_forbid():
    """Schema rejeita campos não declarados — defesa contra typo."""
    with pytest.raises(Exception):
        ClassificacaoCredito(
            categoria="X",
            tipo="INSUMO_CREDITAVEL",
            gera_credito=True,
            amparo_legal="...",
            confianca="ALTA",
            campo_inventado="erro",
        )


# ── Mapa subfase 2.0 — invariantes estruturais ───────────────────────────────

def test_mapa_subfase_2_0_tem_9_categorias():
    """Subfase 2.0 entrega exatamente 9 categorias-piloto (validação Escrivão)."""
    assert len(_mapa_subfase_2_0()) == 9


def test_mapa_subfase_2_0_apenas_confianca_alta():
    """Rail R2 — apenas categorias confirmadas pelo Escrivão entram firmes."""
    for nome, c in _mapa_subfase_2_0().items():
        assert c.confianca == "ALTA", (
            f"{nome}: subfase 2.0 só aceita confiança ALTA, veio {c.confianca}"
        )


def test_mapa_categorias_versionado_cobre_2026_e_2027():
    """Migrador adiciona anos posteriores quando regulamentação mudar."""
    anos = {r.vigencia_inicio.year for r in MAPA_CATEGORIAS_VERSIONADO}
    assert 2026 in anos
    assert 2027 in anos


def test_categoria_nome_canonico_eh_uppercase():
    """Convenção: nomes canônicos em UPPER_SNAKE_CASE."""
    for nome in _mapa_subfase_2_0().keys():
        assert nome == nome.upper(), f"{nome}: deve ser UPPER_SNAKE_CASE"
        assert "_" in nome or nome.isalpha(), f"{nome}: nome não-canônico"


# ── Categorias que GERAM crédito (Art. 47 caput) ─────────────────────────────

@pytest.mark.parametrize("categoria", [
    "ENERGIA_ELETRICA",
    "AGUA_SANEAMENTO",
    "TELEFONE_INTERNET",
    "ALUGUEL_COMERCIAL",
    "MATERIAL_ESCRITORIO",
    "SOFTWARE_LICENCAS",
    "MANUTENCAO_IMOVEL_COMERCIAL",
])
def test_categorias_creditaveis_geram_credito(categoria: str):
    c = classificar(categoria, _DATA_2026)
    assert c is not None
    assert c.tipo == "INSUMO_CREDITAVEL"
    assert c.gera_credito is True
    assert "Art. 47" in c.amparo_legal


# ── Categorias VEDADAS (Art. 57) ─────────────────────────────────────────────

def test_aluguel_residencial_funcionario_vedado():
    """Imóvel residencial pra pessoa física — Art. 57 caput (uso pessoal)."""
    c = classificar("ALUGUEL_RESIDENCIAL_FUNCIONARIO", _DATA_2026)
    assert c is not None
    assert c.tipo == "USO_CONSUMO_PESSOAL"
    assert c.gera_credito is False
    assert "Art. 57" in c.amparo_legal


# ── Categorias NÃO TRIBUTADAS ────────────────────────────────────────────────

def test_salarios_nao_tributados():
    """Folha de salários — fora do escopo CBS/IBS, não é operação tributada."""
    c = classificar("SALARIOS", _DATA_2026)
    assert c is not None
    assert c.tipo == "NAO_TRIBUTADO"
    assert c.gera_credito is False


# ── classificar — comportamento de input ─────────────────────────────────────

def test_classificar_normaliza_minuscula():
    assert classificar("energia_eletrica", _DATA_2026) is not None


def test_classificar_remove_espacos():
    assert classificar("  ENERGIA_ELETRICA  ", _DATA_2026) is not None


def test_classificar_categoria_unknown_retorna_none():
    """Categoria fora do mapa retorna None — Rail R2 (sem decisão automática)."""
    assert classificar("CATEGORIA_INEXISTENTE", _DATA_2026) is None


def test_classificar_string_vazia_retorna_none():
    assert classificar("", _DATA_2026) is None
    assert classificar("   ", _DATA_2026) is None


def test_classificar_tipo_errado_retorna_none():
    """Defesa em camadas — entrada não-string não trava o motor."""
    assert classificar(None, _DATA_2026) is None  # type: ignore[arg-type]
    assert classificar(123, _DATA_2026) is None  # type: ignore[arg-type]


def test_classificar_data_fora_da_janela_levanta():
    """Anos não modelados — Rail R2 (sem fonte, sem decisão)."""
    with pytest.raises(ValueError, match="Nenhuma regra vigente"):
        classificar("ENERGIA_ELETRICA", date(2099, 1, 1))


# ── gera_credito — atalho boolean ────────────────────────────────────────────

def test_gera_credito_categoria_creditavel_true():
    assert gera_credito("ENERGIA_ELETRICA", _DATA_2026) is True


def test_gera_credito_categoria_vedada_false():
    assert gera_credito("ALUGUEL_RESIDENCIAL_FUNCIONARIO", _DATA_2026) is False


def test_gera_credito_categoria_unknown_false():
    """Conservadorismo — UNKNOWN = sem crédito por padrão."""
    assert gera_credito("CATEGORIA_INEXISTENTE", _DATA_2026) is False


# ── listar_categorias_creditaveis ────────────────────────────────────────────

def test_listar_creditaveis_retorna_apenas_creditaveis():
    creditaveis = listar_categorias_creditaveis(_DATA_2026)
    # SALARIOS não é creditável; ALUGUEL_RESIDENCIAL_FUNCIONARIO também não.
    assert "SALARIOS" not in creditaveis
    assert "ALUGUEL_RESIDENCIAL_FUNCIONARIO" not in creditaveis
    # ENERGIA_ELETRICA é.
    assert "ENERGIA_ELETRICA" in creditaveis


def test_listar_creditaveis_ordem_lexica():
    creditaveis = listar_categorias_creditaveis(_DATA_2026)
    assert creditaveis == sorted(creditaveis)


def test_listar_creditaveis_subfase_2_0_tem_7_itens():
    """7 das 9 categorias-piloto geram crédito (2 são vedação/não-tributada)."""
    creditaveis = listar_categorias_creditaveis(_DATA_2026)
    assert len(creditaveis) == 7


# ── Anti-extrapolação — citações banidas (Rail R2) ───────────────────────────

def test_amparo_legal_nao_cita_paragrafo_ii_errado():
    """REGRESSÃO ERR-057: 'Art. 47 §II' como base de creditamento Simples não pode aparecer."""
    for c in _mapa_subfase_2_0().values():
        assert "§II" not in c.amparo_legal, (
            f"{c.categoria}: amparo legal NÃO pode citar Art. 47 §II "
            f"(citação errada — ver ERR-057). Veio: {c.amparo_legal}"
        )


def test_amparo_legal_nao_cita_arts_inventados():
    """REGRESSÃO: Arts. 344/353/356-360 são CRONOGRAMA, não creditamento."""
    for c in _mapa_subfase_2_0().values():
        # Esses artigos não devem aparecer no amparo do mapa de CRÉDITO.
        for art_proibido in ["Art. 344", "Art. 353", "Art. 356", "Art. 357",
                             "Art. 358", "Art. 359", "Art. 360"]:
            assert art_proibido not in c.amparo_legal, (
                f"{c.categoria}: amparo NÃO pode citar {art_proibido} como base "
                f"de crédito (são cronograma). Veio: {c.amparo_legal}"
            )
