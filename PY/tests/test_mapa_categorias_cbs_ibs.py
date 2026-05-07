# -*- coding: utf-8 -*-
"""
test_mapa_categorias_cbs_ibs.py — Cobertura subfase 2.2 do mapa-mestre.

LC 214/2025 Arts. 47 + 57 + 108 + LC 227/2026. Validado por Escrivão em
30/04/2026 e 07/05/2026 (2 rodadas).
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
    _mapa_subfase_2_2,
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


# ── Mapa subfase 2.2 — invariantes estruturais ───────────────────────────────

def test_mapa_subfase_2_2_tem_33_categorias():
    """Subfase 2.2 entrega 33 categorias = 25 da subfase 2.1 + 8 novas."""
    assert len(_mapa_subfase_2_2()) == 33


def test_mapa_subfase_2_2_apenas_confianca_alta():
    """Rail R2 — apenas categorias confirmadas pelo Escrivão entram firmes."""
    for nome, c in _mapa_subfase_2_2().items():
        assert c.confianca == "ALTA", (
            f"{nome}: subfase 2.2 só aceita confiança ALTA, veio {c.confianca}"
        )


def test_mapa_categorias_versionado_cobre_2026_e_2027():
    """Migrador adiciona anos posteriores quando regulamentação mudar."""
    anos = {r.vigencia_inicio.year for r in MAPA_CATEGORIAS_VERSIONADO}
    assert 2026 in anos
    assert 2027 in anos


def test_categoria_nome_canonico_eh_uppercase():
    """Convenção: nomes canônicos em UPPER_SNAKE_CASE."""
    for nome in _mapa_subfase_2_2().keys():
        assert nome == nome.upper(), f"{nome}: deve ser UPPER_SNAKE_CASE"


# ── Subfase 2.0 (9 piloto) — categorias que GERAM crédito (Art. 47 caput) ───

@pytest.mark.parametrize("categoria", [
    "ENERGIA_ELETRICA",
    "AGUA_SANEAMENTO",
    "TELEFONE_INTERNET",
    "ALUGUEL_COMERCIAL",
    "MATERIAL_ESCRITORIO",
    "SOFTWARE_LICENCAS",
    "MANUTENCAO_IMOVEL_COMERCIAL",
])
def test_categorias_creditaveis_subfase_2_0(categoria: str):
    c = classificar(categoria, _DATA_2026)
    assert c is not None
    assert c.tipo == "INSUMO_CREDITAVEL"
    assert c.gera_credito is True
    assert "Art. 47" in c.amparo_legal


# ── Subfase 2.1 (11 novos insumos) — categorias que GERAM crédito ───────────

@pytest.mark.parametrize("categoria", [
    "LIMPEZA_TERCEIRIZADA",
    "SEGURANCA_VIGILANCIA",
    "CORREIO_FRETE",
    "HOSPEDAGEM_CLOUD",
    "ASSESSORIA_JURIDICA",
    "ASSESSORIA_CONTABIL",
    "AUDITORIA_EXTERNA",
    "CARTORIO_REGISTRO_PUBLICO",
    "ASSINATURA_SOFTWARE_SAAS",
    "MARKETING_DIGITAL",
    "TELEFONIA_MOVEL_CORPORATIVA",
])
def test_categorias_creditaveis_subfase_2_1(categoria: str):
    c = classificar(categoria, _DATA_2026)
    assert c is not None
    assert c.tipo == "INSUMO_CREDITAVEL"
    assert c.gera_credito is True
    assert c.confianca == "ALTA"
    assert "Art. 47" in c.amparo_legal


# ── Categorias VEDADAS (Art. 57 caput) ───────────────────────────────────────

@pytest.mark.parametrize("categoria", [
    "ALUGUEL_RESIDENCIAL_FUNCIONARIO",  # subfase 2.0
    "JOIAS_METAIS_PRECIOSOS",            # subfase 2.1
    "OBRAS_ARTE_ANTIGUIDADES",           # subfase 2.1
    "ARMAS_MUNICOES",                    # subfase 2.1
    "RECREACAO_ESPORTE_ESTETICA",        # subfase 2.1
])
def test_categorias_vedadas_uso_pessoal(categoria: str):
    """Imóvel residencial / joias / arte / armas / recreação — Art. 57 caput."""
    c = classificar(categoria, _DATA_2026)
    assert c is not None
    assert c.tipo == "USO_CONSUMO_PESSOAL"
    assert c.gera_credito is False
    assert "Art. 57" in c.amparo_legal


# ── Categorias NÃO TRIBUTADAS (folha + encargos) ─────────────────────────────

@pytest.mark.parametrize("categoria", [
    "SALARIOS",            # subfase 2.0
    "INSS_PATRONAL_FGTS",  # subfase 2.1
])
def test_categorias_nao_tributadas(categoria: str):
    """Folha e encargos — fora do escopo CBS/IBS (não são operação tributada)."""
    c = classificar(categoria, _DATA_2026)
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
    assert gera_credito("ASSESSORIA_CONTABIL", _DATA_2026) is True  # subfase 2.1


def test_gera_credito_categoria_vedada_false():
    assert gera_credito("ALUGUEL_RESIDENCIAL_FUNCIONARIO", _DATA_2026) is False
    assert gera_credito("JOIAS_METAIS_PRECIOSOS", _DATA_2026) is False  # subfase 2.1


def test_gera_credito_categoria_unknown_false():
    """Conservadorismo — UNKNOWN = sem crédito por padrão."""
    assert gera_credito("CATEGORIA_INEXISTENTE", _DATA_2026) is False


# ── listar_categorias_creditaveis ────────────────────────────────────────────

def test_listar_creditaveis_retorna_apenas_creditaveis():
    creditaveis = listar_categorias_creditaveis(_DATA_2026)
    # Vedadas/não-tributadas ficam fora.
    nao_creditaveis = [
        "SALARIOS", "INSS_PATRONAL_FGTS", "ANUIDADE_CONSELHO_PJ",
        "ALUGUEL_RESIDENCIAL_FUNCIONARIO", "JOIAS_METAIS_PRECIOSOS",
        "OBRAS_ARTE_ANTIGUIDADES", "ARMAS_MUNICOES", "RECREACAO_ESPORTE_ESTETICA",
    ]
    for nome in nao_creditaveis:
        assert nome not in creditaveis, f"{nome} não deveria estar em creditáveis"
    # Insumos / bens de capital creditáveis aparecem.
    assert "ENERGIA_ELETRICA" in creditaveis
    assert "ASSESSORIA_CONTABIL" in creditaveis
    assert "VALE_REFEICAO" in creditaveis
    assert "COMPUTADOR_NOTEBOOK_ATIVO" in creditaveis


def test_listar_creditaveis_ordem_lexica():
    creditaveis = listar_categorias_creditaveis(_DATA_2026)
    assert creditaveis == sorted(creditaveis)


def test_listar_creditaveis_subfase_2_2_tem_25_itens():
    """7 da 2.0 + 11 da 2.1 + 3 vales + 4 bens de capital = 25 creditáveis."""
    creditaveis = listar_categorias_creditaveis(_DATA_2026)
    assert len(creditaveis) == 25


# ── Subfase 2.2 — bens de capital (Art. 108) ────────────────────────────────

@pytest.mark.parametrize("categoria", [
    "COMPUTADOR_NOTEBOOK_ATIVO",
    "IMPRESSORA_EQUIPAMENTO_ESCRITORIO",
    "MOBILIARIO_ESCRITORIO",
    "MAQUINARIO_INDUSTRIAL",
])
def test_bens_de_capital_subfase_2_2(categoria: str):
    """Bens de capital — crédito integral e imediato (Art. 108)."""
    c = classificar(categoria, _DATA_2026)
    assert c is not None
    assert c.tipo == "BEM_DE_CAPITAL"
    assert c.gera_credito is True
    assert "Art. 108" in c.amparo_legal


# ── Subfase 2.2 — vales (Art. 57 § 3º + LC 227/2026) ────────────────────────

@pytest.mark.parametrize("categoria", [
    "VALE_REFEICAO",
    "VALE_ALIMENTACAO",
    "VALE_TRANSPORTE",
])
def test_vales_subfase_2_2_creditaveis_sem_acordo_coletivo(categoria: str):
    """LC 227/2026 dispensou requisito de acordo coletivo pra os 3 vales."""
    c = classificar(categoria, _DATA_2026)
    assert c is not None
    assert c.tipo == "INSUMO_CREDITAVEL"
    assert c.gera_credito is True
    assert "LC 227/2026" in c.amparo_legal
    assert "Art. 57" in c.amparo_legal


# ── Subfase 2.2 — anuidade conselho profissional (CF Art. 149) ──────────────

def test_anuidade_conselho_pj_nao_tributada():
    """
    Anuidade de conselho profissional é contribuição parafiscal (CF Art. 149),
    fora do escopo CBS/IBS. Conselho não emite débito → PJ não tem crédito.
    """
    c = classificar("ANUIDADE_CONSELHO_PJ", _DATA_2026)
    assert c is not None
    assert c.tipo == "NAO_TRIBUTADO"
    assert c.gera_credito is False
    assert "CF Art. 149" in c.amparo_legal


# ── Pendências documentadas — categorias que dependem de refactor/flag ──────

@pytest.mark.parametrize("categoria_pendente", [
    # Validadas ALTA mas dependem de refactor/flag schema:
    "COMBUSTIVEL_FROTA_EMPRESARIAL",   # exige refactor de NCMS_MONOFASICAS_BLOQUEADAS
    "PLANO_SAUDE_FUNCIONARIO",          # exige flag `existe_acordo_coletivo` no input
    "BRINDES_MARKETING",                # exige flag `destinatario_brinde` no input
])
def test_categorias_pendentes_ficam_fora_do_mapa(categoria_pendente: str):
    """
    Rail R2 — categorias que dependem de extensão de schema ou refactor
    arquitetônico ficam fora desta subfase. Subfase 2.3+ acrescenta quando
    o motor tiver os campos necessários.
    """
    assert classificar(categoria_pendente, _DATA_2026) is None


# ── Anti-extrapolação — citações banidas (Rail R2) ───────────────────────────

def test_amparo_legal_nao_cita_paragrafo_ii_errado():
    """REGRESSÃO ERR-057: 'Art. 47 §II' como base de creditamento Simples não pode aparecer."""
    for c in _mapa_subfase_2_2().values():
        assert "§II" not in c.amparo_legal, (
            f"{c.categoria}: amparo legal NÃO pode citar Art. 47 §II "
            f"(citação errada — ver ERR-057). Veio: {c.amparo_legal}"
        )


def test_amparo_legal_nao_cita_arts_inventados():
    """REGRESSÃO: Arts. 344/353/356-360 são CRONOGRAMA, não creditamento."""
    for c in _mapa_subfase_2_2().values():
        for art_proibido in ["Art. 344", "Art. 353", "Art. 356", "Art. 357",
                             "Art. 358", "Art. 359", "Art. 360"]:
            assert art_proibido not in c.amparo_legal, (
                f"{c.categoria}: amparo NÃO pode citar {art_proibido} como base "
                f"de crédito (são cronograma). Veio: {c.amparo_legal}"
            )
