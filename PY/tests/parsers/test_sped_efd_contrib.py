# -*- coding: utf-8 -*-
"""
test_sped_efd_contrib.py — Parser SPED EFD-Contribuicoes (Dominio Escrita Fiscal).
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from parsers.sped_efd_contrib import (  # noqa: E402
    SPEDEfdContribParsedData,
    SPEDEfdContribParserError,
    parsear_sped_efd_contrib,
)


CNPJ_TESTE = "12345678000195"


def _build_efd_contrib(
    *,
    cnpj: str = CNPJ_TESTE,
    dt_ini: str = "01012026",
    dt_fin: str = "31012026",
    regime_codigo: str = "3",  # 3 = cumulativo
    pis_m200: Optional[list[str]] = None,
    cofins_m600: Optional[list[str]] = None,
    incluir_0110: bool = True,
) -> bytes:
    """
    Gera EFD-Contribuicoes minimo.

    pis_m200: lista de 13 campos depois do 'M200'. Se None, bloco nao incluido.
    cofins_m600: idem para M600.
    """
    linhas = [
        f"|0000|010|0|0||{dt_ini}|{dt_fin}|EMPRESA TESTE|{cnpj}|SP|3550308||02|0|",
    ]
    if incluir_0110:
        linhas.append(f"|0110|1|{regime_codigo}|1|1|")

    if pis_m200 is not None:
        linhas.append("|M200|" + "|".join(pis_m200) + "|")

    if cofins_m600 is not None:
        linhas.append("|M600|" + "|".join(cofins_m600) + "|")

    linhas.append("|9999|")
    return "\n".join(linhas).encode("latin-1")


from typing import Optional  # noqa: E402  (após uso no type hint acima)


# ─── Cabecalho 0000 ─────────────────────────────────────────────────────────


def test_parsear_header_identifica_cnpj_e_periodo():
    data = parsear_sped_efd_contrib(_build_efd_contrib())
    assert data.cnpj_empresa == CNPJ_TESTE
    assert data.periodo == "2026-01"
    assert data.periodo_inicio == date(2026, 1, 1)
    assert data.periodo_fim == date(2026, 1, 31)


def test_arquivo_vazio_raise():
    with pytest.raises(SPEDEfdContribParserError, match="vazio"):
        parsear_sped_efd_contrib(b"")


def test_sem_bloco_0000_raise():
    conteudo = b"|M200|0|0|0|0|0|0|0|0|0|0|0|0|\n|9999|"
    with pytest.raises(SPEDEfdContribParserError, match="0000"):
        parsear_sped_efd_contrib(conteudo)


# ─── Regime 0110 ────────────────────────────────────────────────────────────


def test_regime_cumulativo_detectado():
    data = parsear_sped_efd_contrib(_build_efd_contrib(regime_codigo="3"))
    assert data.regime == "cumulativo"


def test_regime_nao_cumulativo_detectado():
    data = parsear_sped_efd_contrib(_build_efd_contrib(regime_codigo="1"))
    assert data.regime == "nao_cumulativo"


def test_regime_misto_detectado():
    data = parsear_sped_efd_contrib(_build_efd_contrib(regime_codigo="2"))
    assert data.regime == "misto"


def test_sem_0110_regime_desconhecido_com_aviso():
    data = parsear_sped_efd_contrib(_build_efd_contrib(incluir_0110=False))
    assert data.regime == "desconhecido"
    assert any("Regime" in a for a in data.avisos)


# ─── M200 PIS ───────────────────────────────────────────────────────────────


def test_parsear_M200_pis_cumulativo():
    # Campos: vl_tot_cont_nc_per, vl_tot_cred_desc, vl_tot_cred_desc_ant,
    #         vl_tot_cont_nc_dev, vl_ret_nc, vl_out_ded_nc, vl_cont_nc_rec,
    #         vl_tot_cont_cum_per, vl_ret_cum, vl_out_ded_cum, vl_cont_cum_rec,
    #         vl_tot_cont_rec
    pis_campos = [
        "0",      # nc_per
        "0",      # cred_desc
        "0",      # cred_desc_ant
        "0",      # nc_dev
        "0",      # ret_nc
        "0",      # out_ded_nc
        "0",      # cont_nc_rec
        "1500,00",  # cum_per
        "0",      # ret_cum
        "0",      # out_ded_cum
        "1500,00",  # cont_cum_rec
        "1500,00",  # cont_rec
    ]
    data = parsear_sped_efd_contrib(_build_efd_contrib(pis_m200=pis_campos))
    assert data.pis_total_contribuicao == Decimal("1500.00")
    assert data.pis_valor_devido == Decimal("1500.00")


def test_parsear_M600_cofins_cumulativo():
    cofins_campos = [
        "0", "0", "0", "0", "0", "0", "0",
        "6900,00",  # cum_per
        "0", "0",
        "6900,00",  # cont_cum_rec
        "6900,00",  # cont_rec
    ]
    data = parsear_sped_efd_contrib(_build_efd_contrib(cofins_m600=cofins_campos))
    assert data.cofins_total_contribuicao == Decimal("6900.00")
    assert data.cofins_valor_devido == Decimal("6900.00")


def test_parsear_pis_e_cofins_juntos():
    pis_campos = ["0"] * 7 + ["500,00", "0", "0", "500,00", "500,00"]
    cofins_campos = ["0"] * 7 + ["2300,00", "0", "0", "2300,00", "2300,00"]
    data = parsear_sped_efd_contrib(_build_efd_contrib(
        pis_m200=pis_campos,
        cofins_m600=cofins_campos,
    ))
    assert data.pis_valor_devido == Decimal("500.00")
    assert data.cofins_valor_devido == Decimal("2300.00")
    assert data.tributo_total == Decimal("2800.00")


def test_sem_M200_pis_zerado_sem_raise():
    """Empresa sem movimento PIS eh valido."""
    data = parsear_sped_efd_contrib(_build_efd_contrib())
    assert data.pis_total_contribuicao == Decimal("0")
    assert data.cofins_total_contribuicao == Decimal("0")


# ─── Encoding ───────────────────────────────────────────────────────────────


def test_encoding_latin1_com_acentos_no_nome():
    conteudo = (
        f"|0000|010|0|0||01012026|31012026|EMPRESA AÇÚCAR|{CNPJ_TESTE}|SP|3550308||02|0|\n"
        "|0110|1|3|1|1|\n"
        "|9999|"
    ).encode("latin-1")
    data = parsear_sped_efd_contrib(conteudo)
    assert data.cnpj_empresa == CNPJ_TESTE


# ─── Tipo de retorno ────────────────────────────────────────────────────────


def test_retorno_eh_pydantic_model():
    data = parsear_sped_efd_contrib(_build_efd_contrib())
    assert isinstance(data, SPEDEfdContribParsedData)
    assert hasattr(data, "tributo_total")
