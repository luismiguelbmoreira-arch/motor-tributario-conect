# -*- coding: utf-8 -*-
"""
tests/test_aurora_pdfs_simulados.py — Pipeline end-to-end com fixture Aurora redesenhada.

Substitui o antigo `rodar_aurora_pelo_motor.py` (que comparava com fixture
calculadora). Agora roda o pipeline canônico do redesign:

  JSON (simulando DadosExtraidosPDF) → adapter → projetar_delta_reforma

Fixture: samples/casos_clinicos/aurora_pdfs_simulados/das_competencia_2026-06.json
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.projetor_reforma import DeltaReformaTributaria  # noqa: E402
from services.projecao_pipeline import gerar_projecao_pipeline  # noqa: E402

FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "samples" / "casos_clinicos" / "aurora_pdfs_simulados"
)


@pytest.fixture(scope="module")
def aurora_extrato():
    """Carrega o JSON simulando DadosExtraidosPDF."""
    with open(FIXTURE_DIR / "das_competencia_2026-06.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def aurora_delta_esperado():
    """Carrega o Δ esperado projetando 2027."""
    with open(FIXTURE_DIR / "expected_delta_2027.json", encoding="utf-8") as f:
        return json.load(f)


def _fazer_extrator(payload: dict):
    """Cria função extrator que ignora bytes e devolve objeto duck-typed do JSON."""
    class _Fake:
        pass

    def _extrator(_pdfs_bytes):
        d = _Fake()
        for k, v in payload.items():
            if not k.startswith("_"):
                setattr(d, k, v)
        return d

    return _extrator


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURE EXISTE E TEM SCHEMA ESPERADO
# ─────────────────────────────────────────────────────────────────────────────

class TestFixtureExiste:
    def test_pasta_existe(self):
        assert FIXTURE_DIR.exists()
        assert FIXTURE_DIR.is_dir()

    def test_arquivos_principais_existem(self):
        assert (FIXTURE_DIR / "das_competencia_2026-06.json").exists()
        assert (FIXTURE_DIR / "expected_delta_2027.json").exists()
        assert (FIXTURE_DIR / "README.md").exists()

    def test_extrato_tem_campos_obrigatorios(self, aurora_extrato):
        for campo in (
            "cnpj", "razao_social", "cnae_principal", "uf_origem",
            "faturamento_12m", "rpa_referencia", "das_ecac_referencia",
            "competencia", "das_breakdown",
        ):
            assert campo in aurora_extrato, f"campo {campo!r} ausente"

    def test_das_breakdown_tem_8_tributos(self, aurora_extrato):
        for tributo in ("IRPJ", "CSLL", "PIS", "COFINS", "CPP", "ICMS", "ISS", "IPI"):
            assert tributo in aurora_extrato["das_breakdown"], (
                f"tributo {tributo!r} ausente no breakdown"
            )


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE END-TO-END
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineAurora:
    def test_pipeline_2027_devolve_delta_valido(self, aurora_extrato):
        delta = gerar_projecao_pipeline(
            [b"placeholder-bytes"],
            ano_alvo=2027,
            regime_atual="REAL",
            extrator=_fazer_extrator(aurora_extrato),
        )
        assert isinstance(delta, DeltaReformaTributaria)
        assert delta.ano_alvo == 2027
        assert delta.cnpj == "15644601000104"
        assert delta.competencia == date(2026, 6, 1)

    def test_carga_atual_bate_soma_breakdown(self, aurora_extrato):
        delta = gerar_projecao_pipeline(
            [b"x"],
            ano_alvo=2027,
            regime_atual="REAL",
            extrator=_fazer_extrator(aurora_extrato),
        )
        soma = sum(Decimal(v) for v in aurora_extrato["das_breakdown"].values())
        assert delta.carga_atual == soma.quantize(Decimal("0.01"))

    def test_pis_cofins_zerados_em_2027(self, aurora_extrato):
        delta = gerar_projecao_pipeline(
            [b"x"],
            ano_alvo=2027,
            regime_atual="REAL",
            extrator=_fazer_extrator(aurora_extrato),
        )
        assert delta.breakdown_projetado["pis_residual"] == Decimal("0.00")
        assert delta.breakdown_projetado["cofins_residual"] == Decimal("0.00")

    def test_icms_iss_integrais_em_2027(self, aurora_extrato):
        delta = gerar_projecao_pipeline(
            [b"x"],
            ano_alvo=2027,
            regime_atual="REAL",
            extrator=_fazer_extrator(aurora_extrato),
        )
        # 2027: ICMS/ISS ainda 100%
        assert delta.breakdown_projetado["icms_residual"] == Decimal("485000.00")
        assert delta.breakdown_projetado["iss_residual"] == Decimal("0.00")  # mock ISS=0

    def test_irpj_csll_ipi_inalterados_em_2027(self, aurora_extrato):
        delta = gerar_projecao_pipeline(
            [b"x"],
            ano_alvo=2027,
            regime_atual="REAL",
            extrator=_fazer_extrator(aurora_extrato),
        )
        bk = delta.breakdown_projetado
        assert bk["irpj_inalterado"] == Decimal("42363.79")
        assert bk["csll_inalterada"] == Decimal("23319.51")
        assert bk["ipi_inalterado"] == Decimal("62716.67")


# ─────────────────────────────────────────────────────────────────────────────
# BATIMENTO COM EXPECTATIVA EXPLÍCITA DO JSON
# ─────────────────────────────────────────────────────────────────────────────

class TestBateComEsperado:
    def test_aliquotas_cbs_ibs_batem_com_esperado(
        self, aurora_extrato, aurora_delta_esperado,
    ):
        delta = gerar_projecao_pipeline(
            [b"x"],
            ano_alvo=2027,
            regime_atual="REAL",
            extrator=_fazer_extrator(aurora_extrato),
        )
        assert delta.aliquota_cbs == Decimal(aurora_delta_esperado["aliquota_cbs"])
        assert delta.aliquota_ibs == Decimal(aurora_delta_esperado["aliquota_ibs"])

    def test_carga_atual_bate_com_esperado(
        self, aurora_extrato, aurora_delta_esperado,
    ):
        delta = gerar_projecao_pipeline(
            [b"x"],
            ano_alvo=2027,
            regime_atual="REAL",
            extrator=_fazer_extrator(aurora_extrato),
        )
        esperado = Decimal(aurora_delta_esperado["carga_atual"])
        # Tolerância R$ 0,02 (arredondamentos)
        assert abs(delta.carga_atual - esperado) < Decimal("0.02"), (
            f"carga_atual: motor={delta.carga_atual} vs esperado={esperado}"
        )

    def test_delta_percentual_aproximado(
        self, aurora_extrato, aurora_delta_esperado,
    ):
        delta = gerar_projecao_pipeline(
            [b"x"],
            ano_alvo=2027,
            regime_atual="REAL",
            extrator=_fazer_extrator(aurora_extrato),
        )
        esperado = Decimal(aurora_delta_esperado["delta_percentual_aproximado"])
        # Tolerância 0,5pp (arredondamento + modelagem aproximada)
        assert abs(delta.delta_percentual - esperado) < Decimal("0.005"), (
            f"delta_pct: motor={delta.delta_percentual} vs esperado={esperado}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# PROJEÇÃO POR ANO — cobertura 2026-2033 com a fixture
# ─────────────────────────────────────────────────────────────────────────────

class TestProjecaoPorAno:
    @pytest.mark.parametrize("ano", [2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033])
    def test_cada_ano_projeta_sem_erro(self, aurora_extrato, ano):
        delta = gerar_projecao_pipeline(
            [b"x"],
            ano_alvo=ano,
            regime_atual="REAL",
            extrator=_fazer_extrator(aurora_extrato),
        )
        assert delta.ano_alvo == ano
        # carga projetada nunca é negativa
        assert delta.carga_projetada >= Decimal("0")

    def test_2033_icms_zerado_total_extincao(self, aurora_extrato):
        delta = gerar_projecao_pipeline(
            [b"x"],
            ano_alvo=2033,
            regime_atual="REAL",
            extrator=_fazer_extrator(aurora_extrato),
        )
        assert delta.breakdown_projetado["icms_residual"] == Decimal("0.00")
        assert delta.breakdown_projetado["iss_residual"] == Decimal("0.00")
