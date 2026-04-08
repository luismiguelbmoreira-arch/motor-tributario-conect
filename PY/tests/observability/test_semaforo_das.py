# -*- coding: utf-8 -*-
"""
test_semaforo_das.py — Crosscheck DAS calculado vs pago.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from observability.semaforo_das import SemaforoDAS, avaliar  # noqa: E402


def test_verde_quando_delta_menor_meio_pct():
    # R$ 10.000,00 calc vs R$ 10.040,00 pago → 0.40%
    resultado = avaliar(Decimal("10000.00"), Decimal("10040.00"))
    assert resultado["semaforo"] == SemaforoDAS.VERDE.value
    assert resultado["memoria"]["delta_pct"] == "0.40"


def test_verde_quando_valores_iguais():
    resultado = avaliar(Decimal("5000.00"), Decimal("5000.00"))
    assert resultado["semaforo"] == "verde"
    assert resultado["memoria"]["delta_abs"] == "0.00"


def test_amarelo_quando_delta_entre_meio_e_cinco_pct():
    # R$ 10.000 calc vs R$ 10.200 pago → 2%
    resultado = avaliar(Decimal("10000.00"), Decimal("10200.00"))
    assert resultado["semaforo"] == "amarelo"
    assert resultado["memoria"]["delta_pct"] == "2.00"


def test_amarelo_no_limite_inferior_meio_pct():
    # Exatamente 0.5% → verde (≤ tolerancia)
    resultado = avaliar(Decimal("10000.00"), Decimal("10050.00"))
    assert resultado["semaforo"] == "verde"


def test_vermelho_quando_delta_maior_cinco_pct():
    # R$ 10.000 calc vs R$ 11.000 pago → 10%
    resultado = avaliar(Decimal("10000.00"), Decimal("11000.00"))
    assert resultado["semaforo"] == "vermelho"
    assert resultado["memoria"]["delta_pct"] == "10.00"


def test_vermelho_quando_das_pago_zero_e_calc_positivo():
    resultado = avaliar(Decimal("1500.00"), Decimal("0"))
    assert resultado["semaforo"] == "vermelho"


def test_verde_quando_ambos_zero():
    resultado = avaliar(Decimal("0"), Decimal("0"))
    assert resultado["semaforo"] == "verde"


def test_vermelho_quando_das_calc_zero_mas_pago_positivo():
    resultado = avaliar(Decimal("0"), Decimal("500"))
    assert resultado["semaforo"] == "vermelho"


def test_amparo_legal_citado_no_resultado():
    resultado = avaliar(Decimal("1000"), Decimal("1000"))
    assert "LC 123/2006" in resultado["amparo_legal"]
    assert "Art. 21" in resultado["amparo_legal"]


def test_resultado_segue_schema_trilha():
    resultado = avaliar(Decimal("1000"), Decimal("1050"))
    # Deve ter os campos obrigatórios de um passo da trilha
    assert resultado["tipo"] == "SEMAFORO_DAS"
    assert "id" in resultado
    assert "memoria" in resultado
    assert "amparo_legal" in resultado
