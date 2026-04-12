"""
test_trilha_filtro_cliente.py — Trava o filtro de trilha exibida no PDF.

A trilha real do motor tem 20+ passos (loops de decisao, validacoes internas,
informativos "nao aplicavel"). No PDF do cliente final a gente so quer ver os
calculos que foram EFETIVAMENTE usados naquele caso — sem duplicata, sem
MAX_FISCAL, sem "DIFAL nao se aplica".
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.relatorio_pdf import _filtrar_trilha_cliente  # noqa: E402


def _passo(id_, tipo="CALCULO", titulo="", formula="x=1", memoria=None, detalhe=None):
    p = {"id": id_, "tipo": tipo, "titulo": titulo or id_, "formula": formula}
    if memoria:
        p["memoria"] = memoria
    if detalhe:
        p["detalhe"] = detalhe
    return p


# ── Deduplicacao ────────────────────────────────────────────────────────────


def test_dedup_mantem_ultima_ocorrencia_do_mesmo_id():
    trilha = [
        _passo("DECISAO_ANEXO", titulo="iteracao 1"),
        _passo("DECISAO_ANEXO", titulo="iteracao 2"),
        _passo("DECISAO_ANEXO", titulo="iteracao 3 — final"),
    ]
    r = _filtrar_trilha_cliente(trilha)
    assert len(r) == 1
    assert r[0]["titulo"] == "iteracao 3 — final"


def test_dedup_nao_afeta_ids_diferentes():
    trilha = [
        _passo("DECISAO_ANEXO"),
        _passo("AE_SIMPLES"),
        _passo("OPT_OUT_CALCULO"),
    ]
    r = _filtrar_trilha_cliente(trilha)
    assert len(r) == 3


def test_caso_canavezi_real_22_vira_3():
    """Reproduz o caso real: 22 passos (12 DECISAO_ANEXO + 5 AE_SIMPLES + ...) → 3."""
    trilha = []
    for _ in range(12):
        trilha.append(_passo("DECISAO_ANEXO"))
    for _ in range(5):
        trilha.append(_passo("AE_SIMPLES"))
    for _ in range(2):
        trilha.append(_passo("OPT_OUT_CALCULO"))
    trilha.append(_passo("MAX_FISCAL_03"))  # filtrado
    trilha.append(_passo("DIFAL_OPERACAO_INTERNA", tipo="INFO_DIFAL"))  # filtrado

    r = _filtrar_trilha_cliente(trilha)
    ids = [p["id"] for p in r]
    assert ids == ["DECISAO_ANEXO", "AE_SIMPLES", "OPT_OUT_CALCULO"]


# ── Exclusoes por prefixo/tipo ──────────────────────────────────────────────


def test_exclui_max_fiscal():
    trilha = [
        _passo("MAX_FISCAL_01"),
        _passo("MAX_FISCAL_03"),
        _passo("DECISAO_ANEXO"),
    ]
    r = _filtrar_trilha_cliente(trilha)
    assert [p["id"] for p in r] == ["DECISAO_ANEXO"]


def test_exclui_violacao_seguranca_por_tipo():
    trilha = [
        _passo("VIOLACAO_xyz", tipo="VIOLACAO_SEGURANCA"),
        _passo("DECISAO_ANEXO"),
    ]
    r = _filtrar_trilha_cliente(trilha)
    assert len(r) == 1
    assert r[0]["id"] == "DECISAO_ANEXO"


def test_exclui_violacao_por_prefixo_id():
    trilha = [
        _passo("VIOLACAO_LucroPresumido"),
        _passo("DECISAO_ANEXO"),
    ]
    r = _filtrar_trilha_cliente(trilha)
    assert [p["id"] for p in r] == ["DECISAO_ANEXO"]


def test_exclui_difal_operacao_interna():
    """UF origem == UF destino: DIFAL_OPERACAO_INTERNA e ruido pro cliente."""
    trilha = [
        _passo("DIFAL_OPERACAO_INTERNA", tipo="INFO_DIFAL"),
        _passo("DECISAO_ANEXO"),
    ]
    r = _filtrar_trilha_cliente(trilha)
    assert [p["id"] for p in r] == ["DECISAO_ANEXO"]


def test_mantem_difal_quando_aplicavel():
    """Quando ha DIFAL real, mantem."""
    trilha = [
        _passo("DECISAO_ANEXO"),
        _passo("DIFAL_BASE_UNICA", titulo="DIFAL SP->BA"),
    ]
    r = _filtrar_trilha_cliente(trilha)
    assert len(r) == 2
    assert "DIFAL_BASE_UNICA" in [p["id"] for p in r]


def test_exclui_passo_sem_formula_nem_memoria_nem_detalhe():
    trilha = [
        {"id": "VAZIO", "tipo": "CALCULO"},  # sem nada
        _passo("DECISAO_ANEXO"),
    ]
    r = _filtrar_trilha_cliente(trilha)
    assert [p["id"] for p in r] == ["DECISAO_ANEXO"]


def test_mantem_passo_com_so_detalhe():
    """Passo informativo mas relevante (so detalhe preenchido) e mantido."""
    trilha = [
        {"id": "ALERTA_CUSTOM", "tipo": "CALCULO", "detalhe": "Relevante"},
    ]
    r = _filtrar_trilha_cliente(trilha)
    assert len(r) == 1


# ── Ordenacao ───────────────────────────────────────────────────────────────


def test_ordena_anexo_aliquota_optout_difal():
    trilha = [
        _passo("DIFAL_BASE_UNICA"),
        _passo("OPT_OUT_CALCULO"),
        _passo("DECISAO_ANEXO"),
        _passo("AE_SIMPLES"),
    ]
    r = _filtrar_trilha_cliente(trilha)
    ids = [p["id"] for p in r]
    assert ids == ["DECISAO_ANEXO", "AE_SIMPLES", "OPT_OUT_CALCULO", "DIFAL_BASE_UNICA"]


def test_passos_sem_prioridade_ficam_no_final():
    trilha = [
        _passo("OUTRO_CALCULO"),
        _passo("DECISAO_ANEXO"),
        _passo("AE_SIMPLES"),
    ]
    r = _filtrar_trilha_cliente(trilha)
    ids = [p["id"] for p in r]
    assert ids[:2] == ["DECISAO_ANEXO", "AE_SIMPLES"]
    assert ids[2] == "OUTRO_CALCULO"


def test_fator_r_entra_na_ordem_certa():
    """FATOR_R vem depois de AE_SIMPLES e antes de OPT_OUT."""
    trilha = [
        _passo("OPT_OUT_CALCULO"),
        _passo("FATOR_R"),
        _passo("AE_SIMPLES"),
        _passo("DECISAO_ANEXO"),
    ]
    r = _filtrar_trilha_cliente(trilha)
    ids = [p["id"] for p in r]
    assert ids == ["DECISAO_ANEXO", "AE_SIMPLES", "FATOR_R", "OPT_OUT_CALCULO"]


# ── Robustez ────────────────────────────────────────────────────────────────


def test_lista_vazia_retorna_vazia():
    assert _filtrar_trilha_cliente([]) == []


def test_none_retorna_vazia():
    assert _filtrar_trilha_cliente(None) == []  # type: ignore[arg-type]


def test_passos_malformados_sao_ignorados():
    trilha = [
        "string",  # nao eh dict
        None,
        42,
        _passo("DECISAO_ANEXO"),
    ]
    r = _filtrar_trilha_cliente(trilha)
    assert [p["id"] for p in r] == ["DECISAO_ANEXO"]


def test_passo_sem_id_usa_titulo_como_chave():
    trilha = [
        {"tipo": "CALCULO", "titulo": "Custom A", "formula": "x"},
        {"tipo": "CALCULO", "titulo": "Custom B", "formula": "y"},
    ]
    r = _filtrar_trilha_cliente(trilha)
    assert len(r) == 2


# ── Integracao com _gerar_html ──────────────────────────────────────────────


def test_html_usa_trilha_filtrada():
    from services.relatorio_pdf import _gerar_html

    diag = {
        "empresa": {"regime": "SIMPLES"},
        "aliquotas": {"efetiva_das_total": "0.07"},
        "trilha_auditoria": [
            _passo("DECISAO_ANEXO", titulo="Anexo I"),
            _passo("DECISAO_ANEXO", titulo="Anexo I"),  # dup
            _passo("DECISAO_ANEXO", titulo="Anexo I"),  # dup
            _passo("AE_SIMPLES", titulo="Aliquota Efetiva"),
            _passo("MAX_FISCAL_03"),  # filtrado
            _passo("DIFAL_OPERACAO_INTERNA", tipo="INFO_DIFAL"),  # filtrado
        ],
    }
    html = _gerar_html(diag)
    # Gera HTML válido com doctype
    assert "<!DOCTYPE html>" in html
    assert "</html>" in html
