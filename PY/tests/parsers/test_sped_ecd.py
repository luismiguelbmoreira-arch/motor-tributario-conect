# -*- coding: utf-8 -*-
"""
test_sped_ecd.py — Parser SPED ECD (Domínio Contábil).
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from parsers.sped_ecd import (  # noqa: E402
    SPEDEcdParserError,
    SPEDEcdParsedData,
    parsear_sped_ecd,
)


CNPJ_TESTE = "12345678000195"


def _build_sped_ecd(
    *,
    cnpj: str = CNPJ_TESTE,
    dt_ini: str = "01012026",
    dt_fin: str = "31012026",
    razao: str = "EMPRESA TESTE LTDA",
    lancamentos: list[tuple[str, str, str, list[tuple[str, str, str]]]] = None,
    incluir_plano: bool = True,
) -> bytes:
    """
    Gera um arquivo SPED ECD mínimo válido.

    lancamentos: lista de (numero, data DDMMAAAA, valor, partidas)
        partidas: lista de (conta, valor, 'D'|'C')
    """
    linhas = [
        f"|0000|LECD|{dt_ini}|{dt_fin}|{razao}|{cnpj}|SP|12345678|3550308|||||",
        "|0001|0|",
    ]
    if incluir_plano:
        linhas += [
            "|I050|01012026||A|1|1.1.01.001|1.1.01|Caixa|",
            "|I050|01012026||A|1|3.1.01.001|3.1.01|Receita de Vendas|",
        ]

    for numero, dt, valor, partidas in (lancamentos or []):
        linhas.append(f"|I200|{numero}|{dt}|{valor}|N|")
        for conta, pvalor, dc in partidas:
            linhas.append(f"|I250|{conta}||{pvalor}|{dc}|0001||Venda do dia|")

    linhas.append("|9999|")
    # Encoding latin-1 (padrão SPED)
    return "\n".join(linhas).encode("latin-1")


# ─── Cabeçalho 0000 ─────────────────────────────────────────────────────────


def test_parsear_header_0000_extrai_cnpj_periodo():
    conteudo = _build_sped_ecd(lancamentos=[])
    data = parsear_sped_ecd(conteudo)

    assert data.cnpj_empresa == CNPJ_TESTE
    assert data.periodo_inicio == date(2026, 1, 1)
    assert data.periodo_fim == date(2026, 1, 31)
    assert data.razao_social == "EMPRESA TESTE LTDA"


def test_arquivo_sem_bloco_0000_raise():
    conteudo = b"|I050|01012026||A|1|1.1.01|1.1|Caixa|\n"
    with pytest.raises(SPEDEcdParserError, match="0000"):
        parsear_sped_ecd(conteudo)


def test_arquivo_vazio_raise():
    with pytest.raises(SPEDEcdParserError, match="vazio"):
        parsear_sped_ecd(b"")


def test_cnpj_invalido_no_header_raise():
    conteudo = (
        "|0000|LECD|01012026|31012026|EMP|12345|SP|12345678|3550308|||||\n|9999|"
    ).encode("latin-1")
    with pytest.raises(SPEDEcdParserError, match="CNPJ"):
        parsear_sped_ecd(conteudo)


# ─── Plano de contas I050 ───────────────────────────────────────────────────


def test_parsear_plano_contas_I050():
    conteudo = _build_sped_ecd(lancamentos=[])
    data = parsear_sped_ecd(conteudo)

    assert len(data.plano_contas) == 2
    codigos = {c["codigo"] for c in data.plano_contas}
    assert "1.1.01.001" in codigos
    assert "3.1.01.001" in codigos


# ─── Lançamentos I200/I250 ──────────────────────────────────────────────────


def test_parsear_lancamentos_I200_I250_agrupados():
    lancs = [
        ("1", "15012026", "5000,00", [
            ("1.1.01.001", "5000,00", "D"),  # Caixa D
            ("3.1.01.001", "5000,00", "C"),  # Receita C
        ]),
    ]
    conteudo = _build_sped_ecd(lancamentos=lancs)
    data = parsear_sped_ecd(conteudo)

    assert len(data.lancamentos) == 1
    lanc = data.lancamentos[0]
    assert lanc.numero == "1"
    assert lanc.data == date(2026, 1, 15)
    assert lanc.valor_total == Decimal("5000.00")
    assert len(lanc.partidas) == 2


def test_total_debitos_igual_total_creditos_partida_dobrada():
    lancs = [
        ("1", "15012026", "1000,00", [
            ("1.1.01.001", "1000,00", "D"),
            ("3.1.01.001", "1000,00", "C"),
        ]),
        ("2", "20012026", "2500,00", [
            ("1.1.01.001", "2500,00", "D"),
            ("3.1.01.001", "2500,00", "C"),
        ]),
    ]
    conteudo = _build_sped_ecd(lancamentos=lancs)
    data = parsear_sped_ecd(conteudo)

    assert data.total_debitos == Decimal("3500.00")
    assert data.total_creditos == Decimal("3500.00")
    assert data.total_debitos == data.total_creditos
    # Sem avisos de partida dobrada quebrada
    assert not any("Partida dobrada" in a for a in data.avisos)


def test_partida_dobrada_quebrada_gera_aviso():
    lancs = [
        ("1", "15012026", "1000,00", [
            ("1.1.01.001", "1000,00", "D"),
            ("3.1.01.001", "900,00", "C"),  # Quebrado!
        ]),
    ]
    conteudo = _build_sped_ecd(lancamentos=lancs)
    data = parsear_sped_ecd(conteudo)

    assert any("Partida dobrada" in a for a in data.avisos)


# ─── Encoding ───────────────────────────────────────────────────────────────


def test_encoding_latin1_com_acentos():
    conteudo = _build_sped_ecd(
        razao="EMPRESA AÇÚCAR LTDA",
        lancamentos=[],
    )
    data = parsear_sped_ecd(conteudo)
    assert "AÇÚCAR" in data.razao_social


def test_encoding_utf8_fallback():
    linhas = [
        f"|0000|LECD|01012026|31012026|EMPRESA TESTE|{CNPJ_TESTE}|SP|12345678|3550308|||||",
        "|9999|",
    ]
    conteudo = "\n".join(linhas).encode("utf-8")
    data = parsear_sped_ecd(conteudo)
    assert data.cnpj_empresa == CNPJ_TESTE


# ─── Tipo de retorno ────────────────────────────────────────────────────────


def test_retorno_eh_pydantic_model():
    data = parsear_sped_ecd(_build_sped_ecd(lancamentos=[]))
    assert isinstance(data, SPEDEcdParsedData)
