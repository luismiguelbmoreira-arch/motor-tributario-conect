# -*- coding: utf-8 -*-
"""
test_calculo_credito_cbs_ibs.py — Cobertura do caller real do mapa-mestre.

Função pura `calcular_credito_total` consome `mapa_categorias_cbs_ibs` e
calcula o crédito CBS+IBS acumulado, segregando ignoradas com motivo.
"""

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.calculo_credito_cbs_ibs import (
    DespesaIgnorada,
    ResultadoCredito,
    calcular_credito_total,
)
from core.tabelas_simples import ALIQUOTA_IVA_PLENA_ESTIMADA


_DATA = date(2026, 6, 15)
# Importa fonte canônica em vez de hardcodar — evita drift se valor for revisado.
_ALIQUOTA = ALIQUOTA_IVA_PLENA_ESTIMADA  # 0.265 = 26,5% CBS+IBS combinada


# ── Comportamento básico ─────────────────────────────────────────────────────

def test_lista_vazia_retorna_zero():
    r = calcular_credito_total([], _DATA, _ALIQUOTA)
    assert r.total_credito == Decimal("0.00")
    assert r.despesas_ignoradas == []
    assert r.aliquota_aplicada == _ALIQUOTA
    assert r.data_referencia == _DATA


def test_uma_despesa_creditavel():
    despesas = [("ENERGIA_ELETRICA", Decimal("1000.00"))]
    r = calcular_credito_total(despesas, _DATA, _ALIQUOTA)
    assert r.total_credito == Decimal("265.00")  # 1000 × 0.265
    assert r.despesas_ignoradas == []


def test_multiplas_despesas_creditaveis_somadas():
    despesas = [
        ("ENERGIA_ELETRICA", Decimal("1000")),
        ("AGUA_SANEAMENTO", Decimal("500")),
        ("TELEFONE_INTERNET", Decimal("300")),
    ]
    r = calcular_credito_total(despesas, _DATA, _ALIQUOTA)
    # (1000 + 500 + 300) × 0.265 = 1800 × 0.265 = 477.00
    assert r.total_credito == Decimal("477.00")
    assert r.despesas_ignoradas == []


def test_bem_de_capital_gera_credito():
    """Bens de capital também geram crédito (Art. 108 — integral e imediato)."""
    despesas = [("COMPUTADOR_NOTEBOOK_ATIVO", Decimal("5000"))]
    r = calcular_credito_total(despesas, _DATA, _ALIQUOTA)
    assert r.total_credito == Decimal("1325.00")  # 5000 × 0.265


# ── Despesas que NÃO geram crédito ───────────────────────────────────────────

def test_uso_pessoal_vai_pra_ignoradas():
    despesas = [("ALUGUEL_RESIDENCIAL_FUNCIONARIO", Decimal("2000"))]
    r = calcular_credito_total(despesas, _DATA, _ALIQUOTA)
    assert r.total_credito == Decimal("0.00")
    assert len(r.despesas_ignoradas) == 1
    assert r.despesas_ignoradas[0].categoria == "ALUGUEL_RESIDENCIAL_FUNCIONARIO"
    assert r.despesas_ignoradas[0].motivo == "USO_CONSUMO_PESSOAL"


def test_nao_tributado_vai_pra_ignoradas():
    despesas = [("SALARIOS", Decimal("10000"))]
    r = calcular_credito_total(despesas, _DATA, _ALIQUOTA)
    assert r.total_credito == Decimal("0.00")
    assert r.despesas_ignoradas[0].motivo == "NAO_TRIBUTADO"


def test_categoria_unknown_vai_pra_ignoradas():
    despesas = [("CATEGORIA_INEXISTENTE", Decimal("500"))]
    r = calcular_credito_total(despesas, _DATA, _ALIQUOTA)
    assert r.total_credito == Decimal("0.00")
    assert r.despesas_ignoradas[0].motivo == "UNKNOWN"


# ── Mistura: creditáveis + ignoradas ─────────────────────────────────────────

def test_mistura_credito_e_ignoradas():
    despesas = [
        ("ENERGIA_ELETRICA", Decimal("1000")),                # creditável
        ("ALUGUEL_RESIDENCIAL_FUNCIONARIO", Decimal("2000")),  # uso pessoal
        ("SALARIOS", Decimal("5000")),                         # não-tributado
        ("VALE_REFEICAO", Decimal("800")),                     # creditável (LC 227/2026)
        ("XPTO_NAO_EXISTE", Decimal("100")),                   # unknown
    ]
    r = calcular_credito_total(despesas, _DATA, _ALIQUOTA)
    # Creditáveis: 1000 + 800 = 1800. Crédito = 1800 × 0.265 = 477.00
    assert r.total_credito == Decimal("477.00")
    assert len(r.despesas_ignoradas) == 3
    motivos = {d.motivo for d in r.despesas_ignoradas}
    assert motivos == {"USO_CONSUMO_PESSOAL", "NAO_TRIBUTADO", "UNKNOWN"}


# ── Arredondamento ───────────────────────────────────────────────────────────

def test_quantize_2_casas_decimais():
    """Crédito final deve ter exatamente 2 casas decimais (centavos)."""
    despesas = [("ENERGIA_ELETRICA", Decimal("333.33"))]
    r = calcular_credito_total(despesas, _DATA, _ALIQUOTA)
    # 333.33 × 0.265 = 88.33245 → quantize HALF_UP → 88.33
    assert r.total_credito == Decimal("88.33")


def test_arredondamento_half_up_no_ponto_de_inflexao():
    """
    Exercita HALF_UP no ponto exato de inflexão (3ª casa = 5).

    Caso 1: 1 × 0.005 = 0.005 → quantize(0.01):
        HALF_UP → 0.01 (5 sobe)
        HALF_EVEN → 0.00 (banker's: 0 par fica)
    Se alguém trocar ROUND_HALF_UP por HALF_EVEN, este teste QUEBRA.

    Caso 2: 1 × 0.015 = 0.015 → quantize(0.01):
        HALF_UP → 0.02 (5 sobe)
        HALF_EVEN → 0.02 (banker's: 2 par fica, 1 sobe)
    Coincidem nesse caso — útil só pra confirmar que HALF_UP não quebra.
    """
    # Caso 1 — diferencia HALF_UP de HALF_EVEN
    despesas = [("ENERGIA_ELETRICA", Decimal("1"))]
    r1 = calcular_credito_total(despesas, _DATA, Decimal("0.005"))
    assert r1.total_credito == Decimal("0.01")  # HALF_UP — falha em HALF_EVEN

    # Caso 2 — confirma sentido geral
    r2 = calcular_credito_total(despesas, _DATA, Decimal("0.015"))
    assert r2.total_credito == Decimal("0.02")


# ── Validação de input ───────────────────────────────────────────────────────

def test_aliquota_negativa_levanta():
    with pytest.raises(ValueError, match="aliquota_cbs_ibs deve ser >= 0"):
        calcular_credito_total([], _DATA, Decimal("-0.1"))


def test_valor_negativo_levanta():
    despesas = [("ENERGIA_ELETRICA", Decimal("-100"))]
    with pytest.raises(ValueError, match="Valor negativo em 'ENERGIA_ELETRICA'"):
        calcular_credito_total(despesas, _DATA, _ALIQUOTA)


def test_aliquota_zero_aceita_e_credito_zero():
    """Cenário 2026 (alíquota teste 0%): nenhum crédito gerado, sem erro."""
    despesas = [("ENERGIA_ELETRICA", Decimal("1000"))]
    r = calcular_credito_total(despesas, _DATA, Decimal("0"))
    assert r.total_credito == Decimal("0.00")
    assert r.despesas_ignoradas == []  # categoria gera crédito, só alíquota é 0


def test_valor_zero_aceito():
    """Despesa com valor 0 não trava o cálculo."""
    despesas = [("ENERGIA_ELETRICA", Decimal("0"))]
    r = calcular_credito_total(despesas, _DATA, _ALIQUOTA)
    assert r.total_credito == Decimal("0.00")


# ── Schema frozen ────────────────────────────────────────────────────────────

def test_resultado_credito_eh_frozen():
    r = calcular_credito_total([], _DATA, _ALIQUOTA)
    with pytest.raises(Exception):
        r.total_credito = Decimal("999")


def test_despesa_ignorada_eh_frozen():
    despesas = [("XPTO", Decimal("100"))]
    r = calcular_credito_total(despesas, _DATA, _ALIQUOTA)
    ignorada = r.despesas_ignoradas[0]
    with pytest.raises(Exception):
        ignorada.motivo = "OUTRO"


# ── Schema rejeita campos extras (defesa contra typo) ────────────────────────

def test_despesa_ignorada_rejeita_campo_extra():
    with pytest.raises(Exception):
        DespesaIgnorada(
            categoria="X",
            valor=Decimal("1"),
            motivo="UNKNOWN",
            campo_inventado="erro",
        )


def test_resultado_credito_rejeita_campo_extra():
    with pytest.raises(Exception):
        ResultadoCredito(
            total_credito=Decimal("0"),
            despesas_ignoradas=[],
            aliquota_aplicada=Decimal("0.1"),
            data_referencia=_DATA,
            campo_inventado="erro",
        )


# ── Datas diferentes — versão correta do mapa ────────────────────────────────

def test_data_2027_usa_versao_2027_do_mapa():
    """Mapa é versionado por ano. Categoria deve estar disponível em 2027 também."""
    despesas = [("ENERGIA_ELETRICA", Decimal("1000"))]
    r = calcular_credito_total(despesas, date(2027, 6, 15), _ALIQUOTA)
    assert r.total_credito == Decimal("265.00")


def test_data_fora_da_janela_propaga_value_error():
    """Mapa só cobre 2026-2027. Anos fora levantam ValueError do lookup."""
    despesas = [("ENERGIA_ELETRICA", Decimal("1000"))]
    with pytest.raises(ValueError, match="Nenhuma regra vigente"):
        calcular_credito_total(despesas, date(2099, 1, 1), _ALIQUOTA)


# ── Caso real: contador de pequena empresa ───────────────────────────────────

def test_caso_real_lanchonete():
    """Cenário plausível: lanchonete 2027, mistura de despesas operacionais."""
    despesas = [
        ("ENERGIA_ELETRICA", Decimal("1500")),
        ("AGUA_SANEAMENTO", Decimal("400")),
        ("TELEFONE_INTERNET", Decimal("250")),
        ("MATERIAL_ESCRITORIO", Decimal("180")),
        ("LIMPEZA_TERCEIRIZADA", Decimal("800")),
        ("MARKETING_DIGITAL", Decimal("500")),
        ("SALARIOS", Decimal("12000")),                         # ignorada
        ("INSS_PATRONAL_FGTS", Decimal("3500")),                # ignorada
        ("VALE_REFEICAO", Decimal("2400")),                     # creditável
        ("VALE_TRANSPORTE", Decimal("1200")),                   # creditável
        ("ALUGUEL_COMERCIAL", Decimal("3500")),
        ("CARTORIO_MARCA_REGISTRADA", Decimal("450")),          # UNKNOWN (não tá no mapa)
    ]
    r = calcular_credito_total(despesas, date(2027, 3, 15), _ALIQUOTA)
    # Creditáveis: 1500+400+250+180+800+500+2400+1200+3500 = 10730
    # Crédito: 10730 × 0.265 = 2843.45
    assert r.total_credito == Decimal("2843.45")
    assert len(r.despesas_ignoradas) == 3
    motivos = {d.motivo for d in r.despesas_ignoradas}
    assert motivos == {"NAO_TRIBUTADO", "UNKNOWN"}
