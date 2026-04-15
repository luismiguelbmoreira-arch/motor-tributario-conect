# -*- coding: utf-8 -*-
"""
test_akita_end_to_end.py — Pipeline Akita Rails + SPED Dominio Contabil.
Simplificado: removido HMAC (overengineering) e consolidado em validadores.py.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from validadores import rbt12_vs_rpa, folha_inconsistente, avaliar_das
from parsers.sped_ecd import parsear_sped_ecd
from parsers.sped_efd_contrib import parsear_sped_efd_contrib

CNPJ_MOREIRA = "54657895000160"

def _sped_ecd_minimo() -> bytes:
    linhas = [
        f"|0000|LECD|01012026|31012026|MOREIRA COMERCIO LTDA|{CNPJ_MOREIRA}|SP|12345678|3550308|||||",
        "|0001|0|",
        "|I050|01012026||A|1|1.1.01.001|1.1.01|Caixa|",
        "|I050|01012026||A|1|3.1.01.001|3.1.01|Receita de Vendas|",
        "|I200|1|15012026|5000,00|N|",
        "|I250|1.1.01.001||5000,00|D|0001||Venda|",
        "|I250|3.1.01.001||5000,00|C|0001||Venda|",
        "|9999|",
    ]
    return "\n".join(linhas).encode("latin-1")

def _sped_efd_contrib_minimo() -> bytes:
    pis = ["0"] * 7 + ["500,00", "0", "0", "500,00", "500,00"]
    cofins = ["0"] * 7 + ["2300,00", "0", "0", "2300,00", "2300,00"]
    linhas = [
        f"|0000|010|0|0||01012026|31012026|MOREIRA|{CNPJ_MOREIRA}|SP|3550308||02|0|",
        "|0110|1|3|1|1|",
        "|M200|" + "|".join(pis) + "|",
        "|M600|" + "|".join(cofins) + "|",
        "|9999|",
    ]
    return "\n".join(linhas).encode("latin-1")

def test_pipeline_completo_sem_anomalia():
    ecd = parsear_sped_ecd(_sped_ecd_minimo())
    efd = parsear_sped_efd_contrib(_sped_efd_contrib_minimo())

    assert ecd.cnpj_empresa == CNPJ_MOREIRA
    assert ecd.total_debitos == ecd.total_creditos == Decimal("5000.00")
    assert efd.pis_valor_devido == Decimal("500.00")

    rbt12 = Decimal("1793000")
    rpa = rbt12 / Decimal("12")
    
    # Valida RBT12 vs RPA (Sem anomalia se ratio < 20x)
    alerta = rbt12_vs_rpa(rbt12, rpa)
    assert alerta is None

    # Valida DAS pago vs calculado
    semaforo = avaliar_das(Decimal("1500.00"), Decimal("1500.50"))
    assert semaforo["semaforo"] == "verde"

def test_pipeline_detecta_rbt12_desproporcional():
    alerta = rbt12_vs_rpa(Decimal("2500000"), Decimal("100000"))
    assert alerta is not None
    assert "ALERTA_ANOMALIA_RBT12_DESPROPORCIONAL" in alerta["tipo"]

def test_pipeline_semaforo_vermelho_dispara_em_delta_maior_5pct():
    sem = avaliar_das(Decimal("1000.00"), Decimal("1500.00"))
    assert sem["semaforo"] == "vermelho"
