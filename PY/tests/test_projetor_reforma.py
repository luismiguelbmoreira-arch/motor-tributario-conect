# -*- coding: utf-8 -*-
"""
tests/test_projetor_reforma.py — Componente do redesign extrator+projetor.

Valida que o projetor da Reforma Tributária:
  - Aceita DocumentoFiscalExtraido (origem: PDF do contador)
  - Aplica CRONOGRAMA_IVA do ano-alvo
  - Calcula carga atual, projetada e Δ
  - Produz breakdown auditável

NÃO testa cálculo de IRPJ/CSLL do zero — esse é trabalho do contador.
Motor APENAS projeta o Δ Reforma usando os tributos pagos como input.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.projetor_reforma import (  # noqa: E402
    DeltaReformaTributaria,
    DocumentoFiscalExtraido,
    projetar_delta_reforma,
)
from core.tabelas_simples import CRONOGRAMA_IVA  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

def _doc_simples_basico(
    *,
    cnpj: str = "12345678000195",
    receita: Decimal = Decimal("100000.00"),
    irpj: Decimal = Decimal("0"),
    csll: Decimal = Decimal("0"),
    pis: Decimal = Decimal("0"),
    cofins: Decimal = Decimal("0"),
    icms: Decimal = Decimal("0"),
    iss: Decimal = Decimal("0"),
    cpp: Decimal = Decimal("0"),
    competencia: date = date(2026, 6, 1),
) -> DocumentoFiscalExtraido:
    return DocumentoFiscalExtraido(
        cnpj=cnpj,
        competencia=competencia,
        regime_atual="SIMPLES",
        receita_bruta_mensal=receita,
        irpj_pago=irpj,
        csll_paga=csll,
        pis_pago=pis,
        cofins_paga=cofins,
        icms_pago=icms,
        iss_pago=iss,
        cpp_pago=cpp,
    )


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA
# ─────────────────────────────────────────────────────────────────────────────

class TestSchema:
    def test_documento_eh_frozen(self):
        d = _doc_simples_basico()
        with pytest.raises(Exception):
            d.cnpj = "outro"  # type: ignore[misc]

    def test_documento_extra_forbidden(self):
        # extra="forbid" garante que campos novos quebram (anti-drift)
        with pytest.raises(Exception):
            DocumentoFiscalExtraido(
                cnpj="12345678000195",
                competencia=date(2026, 6, 1),
                regime_atual="SIMPLES",
                receita_bruta_mensal=Decimal("100"),
                campo_inventado=42,  # type: ignore[call-arg]
            )

    def test_delta_eh_frozen(self):
        d = _doc_simples_basico(receita=Decimal("100000"), pis=Decimal("1650"))
        r = projetar_delta_reforma(documento=d, ano_alvo=2026)
        with pytest.raises(Exception):
            r.delta_absoluto = Decimal("0")  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# CRONOGRAMA_IVA
# ─────────────────────────────────────────────────────────────────────────────

class TestCronogramaIVA:
    def test_ano_fora_do_cronograma_levanta(self):
        d = _doc_simples_basico()
        with pytest.raises(ValueError, match="cronograma"):
            projetar_delta_reforma(documento=d, ano_alvo=2025)  # type: ignore[arg-type]

    def test_aliquotas_2026_baixissimas(self):
        # 2026 = ano-teste: CBS 0,9% + IBS 0,1% (Cronograma)
        d = _doc_simples_basico(receita=Decimal("100000"))
        r = projetar_delta_reforma(documento=d, ano_alvo=2026)
        assert r.aliquota_cbs == Decimal(str(CRONOGRAMA_IVA[2026]["CBS"]))
        assert r.aliquota_ibs == Decimal(str(CRONOGRAMA_IVA[2026]["IBS"]))

    def test_aliquotas_2033_plenas(self):
        d = _doc_simples_basico(receita=Decimal("100000"))
        r = projetar_delta_reforma(documento=d, ano_alvo=2033)
        # 2033 = ano da carga plena
        assert r.aliquota_cbs >= Decimal("0.05")  # plenário > 5%
        assert r.aliquota_ibs >= Decimal("0.10")  # plenário > 10%


# ─────────────────────────────────────────────────────────────────────────────
# PROJEÇÃO — cálculo do Δ
# ─────────────────────────────────────────────────────────────────────────────

class TestProjecaoDelta:
    def test_simples_puro_so_pis_cofins_substituidos_por_cbs_ibs(self):
        # Empresa Simples paga PIS R$ 1.650 + COFINS R$ 7.600 (sobre R$ 100k)
        # No ano-alvo, esses tributos viram CBS+IBS sobre a receita.
        d = _doc_simples_basico(
            receita=Decimal("100000.00"),
            pis=Decimal("1650.00"),
            cofins=Decimal("7600.00"),
        )
        r = projetar_delta_reforma(documento=d, ano_alvo=2027)
        assert r.carga_atual == Decimal("9250.00")  # 1650 + 7600
        # Carga projetada = receita * (CBS + IBS) (modelagem v1)
        cbs_2027 = Decimal(str(CRONOGRAMA_IVA[2027]["CBS"]))
        ibs_2027 = Decimal(str(CRONOGRAMA_IVA[2027]["IBS"]))
        esperado = (Decimal("100000") * (cbs_2027 + ibs_2027))
        assert abs(r.carga_projetada - esperado) < Decimal("0.10")

    def test_irpj_csll_cpp_ipi_permanecem_inalterados(self):
        # Reforma 2026-2033 NÃO mexe em IRPJ/CSLL/CPP/IPI.
        d = _doc_simples_basico(
            receita=Decimal("100000"),
            irpj=Decimal("3000"),
            csll=Decimal("2000"),
            cpp=Decimal("5000"),
        )
        r = projetar_delta_reforma(documento=d, ano_alvo=2026)
        assert r.breakdown_projetado["irpj_inalterado"] == Decimal("3000")
        assert r.breakdown_projetado["csll_inalterada"] == Decimal("2000")
        assert r.breakdown_projetado["cpp_inalterada"] == Decimal("5000")

    def test_pis_cofins_icms_iss_zerados_no_ano_alvo(self):
        # Modelagem v1: PIS/COFINS/ICMS/ISS extintos integralmente no ano-alvo.
        # (Em iteração futura, modelar transição gradual conforme Art. 344.)
        d = _doc_simples_basico(
            receita=Decimal("100000"),
            pis=Decimal("1650"),
            cofins=Decimal("7600"),
            icms=Decimal("18000"),
            iss=Decimal("5000"),
        )
        r = projetar_delta_reforma(documento=d, ano_alvo=2026)
        assert r.breakdown_projetado["pis_residual"] == Decimal("0")
        assert r.breakdown_projetado["cofins_residual"] == Decimal("0")
        assert r.breakdown_projetado["icms_residual"] == Decimal("0")
        assert r.breakdown_projetado["iss_residual"] == Decimal("0")

    def test_delta_absoluto_e_percentual_calculados(self):
        d = _doc_simples_basico(
            receita=Decimal("100000"),
            pis=Decimal("1000"),
            cofins=Decimal("9000"),
        )
        r = projetar_delta_reforma(documento=d, ano_alvo=2027)
        # carga_atual = 10.000
        assert r.carga_atual == Decimal("10000.00")
        # delta_absoluto = projetada - atual
        assert r.delta_absoluto == r.carga_projetada - r.carga_atual
        # delta_percentual coerente
        if r.carga_atual > 0:
            esperado_pct = (r.delta_absoluto / r.carga_atual).quantize(Decimal("0.0001"))
            assert r.delta_percentual == esperado_pct

    def test_carga_atual_zero_evita_divisao_por_zero(self):
        d = _doc_simples_basico(receita=Decimal("100000"))  # tudo zero
        r = projetar_delta_reforma(documento=d, ano_alvo=2026)
        assert r.carga_atual == Decimal("0")
        assert r.delta_percentual == Decimal("0")  # não explode


# ─────────────────────────────────────────────────────────────────────────────
# RASTREABILIDADE — origem do documento + base legal
# ─────────────────────────────────────────────────────────────────────────────

class TestRastreabilidade:
    def test_documento_aceita_hash_origem(self):
        d = DocumentoFiscalExtraido(
            cnpj="12345678000195",
            competencia=date(2026, 6, 1),
            regime_atual="SIMPLES",
            receita_bruta_mensal=Decimal("100000"),
            documento_origem_hash="a" * 64,
        )
        assert d.documento_origem_hash == "a" * 64

    def test_delta_traz_base_legal(self):
        d = _doc_simples_basico(receita=Decimal("100000"))
        r = projetar_delta_reforma(documento=d, ano_alvo=2026)
        amparos = " | ".join(r.base_legal)
        assert "LC 214/2025" in amparos
        assert "EC 132/2023" in amparos


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSÃO — ano-alvo válido pra cada ano da transição
# ─────────────────────────────────────────────────────────────────────────────

class TestAnosTransicao:
    @pytest.mark.parametrize("ano", [2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033])
    def test_cada_ano_da_transicao_projeta(self, ano):
        d = _doc_simples_basico(
            receita=Decimal("100000"),
            pis=Decimal("1650"),
            cofins=Decimal("7600"),
        )
        r = projetar_delta_reforma(documento=d, ano_alvo=ano)
        assert isinstance(r, DeltaReformaTributaria)
        assert r.ano_alvo == ano
