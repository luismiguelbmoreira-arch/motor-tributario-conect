# -*- coding: utf-8 -*-
"""
test_calendario_legal.py — Cobertura de core/calendario_legal.py.

Janelas firmes:
- Renúncia ao Simples Nacional (LC 123/2006 Art. 30 + § 1º + Art. 31).
- Opt-in CBS/IBS — 1º sem/2027 (LC 214/2025 Art. 348 §§ 3º-4º + Res. CGSN 186/2026).

Validado por Escrivão em fonte primária (planalto.gov.br + DOU CGSN 186/2026).
"""

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.calendario_legal import (
    JANELA_OPT_IN_CBS_IBS_SET_2026,
    JANELAS_PENDENTES_REGULAMENTACAO,
    AlertaJanelaLegal,
    JanelaLegal,
    _janela_renuncia_simples,
    _ultimo_dia_util_mes,
    alertar_janelas_proximas,
    dias_restantes_para_janela,
    janela_aberta_hoje,
    listar_janelas_firmes,
    proxima_janela_optout,
)


# ── _ultimo_dia_util_mes ─────────────────────────────────────────────────────

def test_ultimo_dia_util_janeiro_2026_recua_pra_sexta():
    """31/01/2026 cai num sábado. Último dia útil = 30/01/2026 (sexta)."""
    assert _ultimo_dia_util_mes(2026, 1) == date(2026, 1, 30)


def test_ultimo_dia_util_janeiro_2027_recua_pra_sexta():
    """31/01/2027 cai num domingo. Último dia útil = 29/01/2027 (sexta)."""
    assert _ultimo_dia_util_mes(2027, 1) == date(2027, 1, 29)


def test_ultimo_dia_util_setembro_2026_eh_quarta():
    """30/09/2026 cai numa quarta-feira — dia útil normal."""
    assert _ultimo_dia_util_mes(2026, 9) == date(2026, 9, 30)


def test_ultimo_dia_util_fevereiro_2026_termina_em_sabado():
    """28/02/2026 é sábado. Último dia útil = 27/02 (sexta)."""
    assert _ultimo_dia_util_mes(2026, 2) == date(2026, 2, 27)


def test_ultimo_dia_util_funciona_em_ano_bissexto():
    """29/02/2028 é uma terça-feira (ano bissexto)."""
    assert _ultimo_dia_util_mes(2028, 2) == date(2028, 2, 29)


# ── Schema JanelaLegal ───────────────────────────────────────────────────────

def test_janela_firme_requer_data_inicio_e_fim():
    with pytest.raises(ValueError, match="Janela firme requer data_inicio e data_fim"):
        JanelaLegal(
            nome="Janela inválida",
            tipo="RENUNCIA_SIMPLES",
            pendente_regulamentacao=False,
            amparo_legal="LC 123/2006",
        )


def test_janela_firme_data_inicio_maior_que_fim_falha():
    with pytest.raises(ValueError, match=r"data_inicio .* deve ser ≤ data_fim"):
        JanelaLegal(
            nome="Inversa",
            tipo="RENUNCIA_SIMPLES",
            pendente_regulamentacao=False,
            data_inicio=date(2026, 1, 31),
            data_fim=date(2026, 1, 1),
            amparo_legal="LC 123/2006, Art. 30",
        )


def test_janela_pendente_aceita_datas_none():
    janela = JanelaLegal(
        nome="Pendente teste",
        tipo="OPT_IN_REGULAR_CBS_IBS",
        pendente_regulamentacao=True,
        janela_aproximada="Esperada 1º trim/2027",
        amparo_legal="LC 214/2025 — aguardando CGSN",
    )
    assert janela.data_inicio is None
    assert janela.data_fim is None


def test_janela_legal_eh_frozen():
    """Pydantic V2 frozen=True deve impedir mutação."""
    janela = _janela_renuncia_simples(2026)
    with pytest.raises(Exception):  # ValidationError ou TypeError dependendo da versão
        janela.nome = "outro nome"


# ── Constantes firmes ────────────────────────────────────────────────────────

def test_janela_opt_in_cbs_ibs_set_2026_dados_corretos():
    j = JANELA_OPT_IN_CBS_IBS_SET_2026
    assert j.tipo == "OPT_IN_REGULAR_CBS_IBS"
    assert j.pendente_regulamentacao is False
    assert j.data_inicio == date(2026, 9, 1)
    assert j.data_fim == date(2026, 9, 30)
    assert j.data_efeitos_inicio == date(2027, 1, 1)
    assert j.data_efeitos_fim == date(2027, 6, 30)
    assert j.cancelamento_irrevogavel_ate == date(2026, 11, 30)
    assert "LC 214/2025" in j.amparo_legal
    assert "LC 227/2026" in j.amparo_legal
    assert "Resolução CGSN nº 186/2026" in j.amparo_legal


def test_janelas_pendentes_lista_vazia_por_padrao():
    """Sem fonte primária, lista é vazia. Migrador acrescenta quando CGSN sair."""
    assert JANELAS_PENDENTES_REGULAMENTACAO == []


def test_renuncia_simples_2027_amparo_correto():
    j = _janela_renuncia_simples(2027)
    assert j.tipo == "RENUNCIA_SIMPLES"
    assert j.pendente_regulamentacao is False
    assert j.data_inicio == date(2027, 1, 1)
    assert j.data_fim == date(2027, 1, 29)  # último dia útil
    assert j.data_efeitos_inicio == date(2027, 1, 1)
    assert j.data_efeitos_fim is None  # vigência indefinida
    assert "LC 123/2006, Art. 30" in j.amparo_legal
    assert "Art. 31" in j.amparo_legal


# ── janela_aberta_hoje ───────────────────────────────────────────────────────

def test_janela_aberta_hoje_dentro_da_janela_setembro():
    assert janela_aberta_hoje(date(2026, 9, 15), JANELA_OPT_IN_CBS_IBS_SET_2026) is True


def test_janela_aberta_hoje_no_primeiro_dia():
    assert janela_aberta_hoje(date(2026, 9, 1), JANELA_OPT_IN_CBS_IBS_SET_2026) is True


def test_janela_aberta_hoje_no_ultimo_dia():
    assert janela_aberta_hoje(date(2026, 9, 30), JANELA_OPT_IN_CBS_IBS_SET_2026) is True


def test_janela_aberta_hoje_antes_da_abertura():
    assert janela_aberta_hoje(date(2026, 8, 31), JANELA_OPT_IN_CBS_IBS_SET_2026) is False


def test_janela_aberta_hoje_apos_fechamento():
    assert janela_aberta_hoje(date(2026, 10, 1), JANELA_OPT_IN_CBS_IBS_SET_2026) is False


def test_janela_aberta_hoje_pendente_sempre_falsa():
    pendente = JanelaLegal(
        nome="Pendente",
        tipo="OPT_IN_REGULAR_CBS_IBS",
        pendente_regulamentacao=True,
        amparo_legal="aguardando CGSN",
    )
    assert janela_aberta_hoje(date(2026, 9, 15), pendente) is False


# ── dias_restantes_para_janela ───────────────────────────────────────────────

def test_dias_restantes_janela_aberta_hoje_zero():
    assert dias_restantes_para_janela(date(2026, 9, 15), JANELA_OPT_IN_CBS_IBS_SET_2026) == 0


def test_dias_restantes_janela_futura_positivo():
    assert dias_restantes_para_janela(date(2026, 8, 1), JANELA_OPT_IN_CBS_IBS_SET_2026) == 31


def test_dias_restantes_janela_passada_none():
    assert dias_restantes_para_janela(date(2026, 10, 1), JANELA_OPT_IN_CBS_IBS_SET_2026) is None


def test_dias_restantes_janela_pendente_none():
    pendente = JanelaLegal(
        nome="P",
        tipo="OPT_IN_REGULAR_CBS_IBS",
        pendente_regulamentacao=True,
        amparo_legal="x",
    )
    assert dias_restantes_para_janela(date(2026, 9, 15), pendente) is None


# ── proxima_janela_optout ────────────────────────────────────────────────────

def test_proxima_janela_em_julho_2026_eh_setembro():
    proxima = proxima_janela_optout(date(2026, 7, 1))
    assert proxima is not None
    assert proxima.tipo == "OPT_IN_REGULAR_CBS_IBS"
    assert proxima.data_inicio == date(2026, 9, 1)


def test_proxima_janela_apos_setembro_2026_eh_renuncia_2027():
    """Em outubro/2026 a janela CBS/IBS já fechou; próxima é Renúncia Simples 2027."""
    proxima = proxima_janela_optout(date(2026, 10, 5))
    assert proxima is not None
    assert proxima.tipo == "RENUNCIA_SIMPLES"
    assert proxima.data_inicio == date(2027, 1, 1)


def test_proxima_janela_filtrada_por_tipo_renuncia():
    """Mesmo em julho/2026, se filtrar por RENUNCIA_SIMPLES, traz janeiro/2027."""
    proxima = proxima_janela_optout(date(2026, 7, 1), tipo_filtro="RENUNCIA_SIMPLES")
    assert proxima is not None
    assert proxima.tipo == "RENUNCIA_SIMPLES"
    assert proxima.data_inicio == date(2027, 1, 1)


def test_proxima_janela_sem_janelas_disponiveis_retorna_none():
    """Após janeiro/2099 com anos_futuro=0 → nenhuma janela firme disponível."""
    proxima = proxima_janela_optout(date(2099, 2, 1), anos_futuro=0)
    assert proxima is None


# ── listar_janelas_firmes ────────────────────────────────────────────────────

def test_listar_janelas_em_abril_2026_inclui_setembro_e_renuncias():
    janelas = listar_janelas_firmes(date(2026, 4, 29), anos_futuro=2)
    tipos = [j.tipo for j in janelas]
    assert "OPT_IN_REGULAR_CBS_IBS" in tipos
    assert tipos.count("RENUNCIA_SIMPLES") >= 1


def test_listar_janelas_ordem_cronologica():
    janelas = listar_janelas_firmes(date(2026, 4, 29), anos_futuro=2)
    inicios = [j.data_inicio for j in janelas]
    assert inicios == sorted(inicios)


def test_listar_janelas_filtra_passado():
    """Janelas com data_fim < hoje não aparecem."""
    janelas = listar_janelas_firmes(date(2026, 12, 1), anos_futuro=1)
    for j in janelas:
        assert j.data_fim is not None
        assert j.data_fim >= date(2026, 12, 1)


def test_listar_janelas_anos_futuro_negativo_falha():
    with pytest.raises(ValueError, match="anos_futuro deve ser >= 0"):
        listar_janelas_firmes(date(2026, 1, 1), anos_futuro=-1)


def test_listar_janelas_sem_pendentes():
    """Pendentes nunca devem aparecer no output das funções públicas."""
    janelas = listar_janelas_firmes(date(2026, 4, 29), anos_futuro=10)
    for j in janelas:
        assert j.pendente_regulamentacao is False


# ── alertar_janelas_proximas ─────────────────────────────────────────────────

def test_alerta_janela_aberta_hoje():
    alertas = alertar_janelas_proximas(date(2026, 9, 15), n_dias_aviso=30)
    abertas = [a for a in alertas if a.dias_restantes == 0]
    assert len(abertas) == 1
    assert "ABERTA HOJE" in abertas[0].mensagem


def test_alerta_janela_em_15_dias():
    alertas = alertar_janelas_proximas(date(2026, 8, 17), n_dias_aviso=30)
    proximas = [a for a in alertas if a.dias_restantes == 15]
    assert len(proximas) == 1
    assert "ABRE em 15 dia" in proximas[0].mensagem


def test_alerta_fora_do_aviso_nao_dispara():
    """Janela em 60 dias com aviso de 30 dias → sem alerta."""
    alertas = alertar_janelas_proximas(date(2026, 7, 1), n_dias_aviso=30)
    cbs = [a for a in alertas if a.janela.tipo == "OPT_IN_REGULAR_CBS_IBS"]
    assert cbs == []


def test_alerta_n_dias_aviso_negativo_falha():
    with pytest.raises(ValueError, match="n_dias_aviso deve ser >= 0"):
        alertar_janelas_proximas(date(2026, 9, 15), n_dias_aviso=-1)


def test_alerta_carrega_amparo_legal():
    alertas = alertar_janelas_proximas(date(2026, 9, 15), n_dias_aviso=30)
    for a in alertas:
        assert a.amparo_legal == a.janela.amparo_legal
        assert len(a.amparo_legal) > 10


def test_alerta_renuncia_simples_em_dezembro_dispara():
    """Em dezembro de 2026, janela de renúncia 2027 abre em poucos dias."""
    alertas = alertar_janelas_proximas(date(2026, 12, 15), n_dias_aviso=30)
    renuncia = [a for a in alertas if a.janela.tipo == "RENUNCIA_SIMPLES"]
    assert len(renuncia) == 1
    assert renuncia[0].dias_restantes == (date(2027, 1, 1) - date(2026, 12, 15)).days
