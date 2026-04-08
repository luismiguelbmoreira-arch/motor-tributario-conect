# -*- coding: utf-8 -*-
"""
test_anomalias.py — Regras Akita de deteccao de padroes suspeitos.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from observability import anomalias  # noqa: E402


# ─── rbt12_vs_rpa ───────────────────────────────────────────────────────────


def test_rbt12_25x_rpa_dispara_alerta():
    alerta = anomalias.rbt12_vs_rpa(
        rbt12=Decimal("2500000"),
        rpa_mensal=Decimal("100000"),
    )
    assert alerta is not None
    assert alerta["tipo"] == "ALERTA_ANOMALIA_RBT12_DESPROPORCIONAL"
    assert alerta["memoria"]["razao"] == "25.00"


def test_rbt12_10x_rpa_nao_dispara():
    alerta = anomalias.rbt12_vs_rpa(
        rbt12=Decimal("1000000"),
        rpa_mensal=Decimal("100000"),
    )
    assert alerta is None


def test_rbt12_vs_rpa_nao_dispara_com_rpa_zero():
    """Divisao por zero seria bug — deve retornar None."""
    alerta = anomalias.rbt12_vs_rpa(
        rbt12=Decimal("1000000"),
        rpa_mensal=Decimal("0"),
    )
    assert alerta is None


# ─── confianca_extracao_baixa ──────────────────────────────────────────────


def test_confianca_70_dispara_alerta():
    alerta = anomalias.confianca_extracao_baixa(0.70)
    assert alerta is not None
    assert alerta["id"] == "ANOMALIA_CONFIANCA_EXTRACAO"


def test_confianca_90_nao_dispara():
    alerta = anomalias.confianca_extracao_baixa(0.90)
    assert alerta is None


def test_confianca_exatamente_no_limiar_nao_dispara():
    alerta = anomalias.confianca_extracao_baixa(0.75)
    assert alerta is None


# ─── folha_inconsistente ───────────────────────────────────────────────────


def test_folha_maior_que_rbt12_dispara():
    # Folha 2M, RBT12 1.8M → folha > RBT12
    alerta = anomalias.folha_inconsistente(
        folha_12m=Decimal("2000000"),
        rbt12=Decimal("1800000"),
    )
    assert alerta is not None
    assert "erro de separador decimal" in alerta["titulo"]


def test_folha_30_pct_do_rbt12_nao_dispara():
    # Caso Moreira real: folha 501k / RBT12 1.79M = 28%
    alerta = anomalias.folha_inconsistente(
        folha_12m=Decimal("501000"),
        rbt12=Decimal("1793000"),
    )
    assert alerta is None


# ─── crosscheck_pis_cofins_sped_vs_nfe ─────────────────────────────────────


def test_pis_divergencia_6_pct_dispara():
    alerta = anomalias.crosscheck_pis_cofins_sped_vs_nfe(
        pis_sped=Decimal("10000"),
        pis_nfe=Decimal("10600"),  # 5.66% delta
        tributo="PIS",
    )
    assert alerta is not None
    assert alerta["tipo"] == "ALERTA_ANOMALIA_PIS_DIVERGENTE_SPED_NFE"


def test_pis_divergencia_3_pct_nao_dispara():
    alerta = anomalias.crosscheck_pis_cofins_sped_vs_nfe(
        pis_sped=Decimal("10000"),
        pis_nfe=Decimal("10300"),
        tributo="PIS",
    )
    assert alerta is None


def test_cofins_tributo_customizado():
    alerta = anomalias.crosscheck_pis_cofins_sped_vs_nfe(
        pis_sped=Decimal("10000"),
        pis_nfe=Decimal("12000"),
        tributo="COFINS",
    )
    assert alerta is not None
    assert "COFINS" in alerta["tipo"]
    assert alerta["id"] == "ANOMALIA_CROSSCHECK_COFINS"


# ─── detectar() orchestrator ───────────────────────────────────────────────


def test_detectar_sem_inputs_retorna_lista_vazia():
    assert anomalias.detectar() == []


def test_detectar_multiplas_anomalias_retornam_lista_completa():
    alertas = anomalias.detectar(
        rbt12=Decimal("3000000"),
        rpa_mensal=Decimal("100000"),   # dispara RBT12/RPA
        folha_12m=Decimal("4000000"),   # dispara folha > RBT12
        confianca_extracao=0.60,        # dispara OCR baixa
    )
    assert len(alertas) == 3
    tipos = {a["tipo"] for a in alertas}
    assert "ALERTA_ANOMALIA_RBT12_DESPROPORCIONAL" in tipos
    assert "ALERTA_ANOMALIA_FOLHA_IMPOSSIVEL" in tipos
    assert "ALERTA_ANOMALIA_OCR_BAIXA_CONFIANCA" in tipos


def test_detectar_apenas_inputs_parciais():
    """So passa confianca → so roda essa regra."""
    alertas = anomalias.detectar(confianca_extracao=0.50)
    assert len(alertas) == 1
    assert alertas[0]["id"] == "ANOMALIA_CONFIANCA_EXTRACAO"
