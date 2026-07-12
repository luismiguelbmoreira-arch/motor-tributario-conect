# -*- coding: utf-8 -*-
"""
tests/test_projecao_pipeline.py — Pipeline canônico do redesign.

Testa a função `gerar_projecao_pipeline` em isolamento, injetando
mock do extrator pra evitar dependência da API Claude Vision.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.projetor_reforma import DeltaReformaTributaria  # noqa: E402
from services.projecao_pipeline import gerar_projecao_pipeline  # noqa: E402


class _DadosExtraidosFake:
    """Mock do DadosExtraidosPDF — duck-type."""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _extrator_mock_simples(pdfs_bytes):
    """
    Mock determinístico que ignora os bytes e devolve dados fixos.
    Em produção, o extrator real chamaria Claude Vision.
    """
    return _DadosExtraidosFake(
        cnpj="12.345.678/0001-95",
        razao_social="EMPRESA TESTE LTDA",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m="1200000.00",
        rpa_referencia="100000.00",
        das_ecac_referencia="9250.00",
        competencia="06/2026",
        das_breakdown={
            "IRPJ": "0",
            "CSLL": "0",
            "PIS": "1650.00",
            "COFINS": "7600.00",
            "CPP": "0",
            "ICMS": "0",
            "ISS": "0",
            "IPI": "0",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# CONTRATO BÁSICO
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineBasico:
    def test_pipeline_retorna_delta_reforma_tributaria(self):
        r = gerar_projecao_pipeline(
            [b"fake-pdf-bytes"],
            ano_alvo=2027,
            regime_atual="SIMPLES",
            extrator=_extrator_mock_simples,
        )
        assert isinstance(r, DeltaReformaTributaria)
        assert r.ano_alvo == 2027
        assert r.cnpj == "12345678000195"

    def test_carga_atual_extraida_do_breakdown(self):
        r = gerar_projecao_pipeline(
            [b"x"],
            ano_alvo=2026,
            regime_atual="SIMPLES",
            extrator=_extrator_mock_simples,
        )
        # PIS 1650 + COFINS 7600 = 9250 (resto zero no mock)
        assert r.carga_atual == Decimal("9250.00")

    def test_competencia_propaga_do_extrator(self):
        r = gerar_projecao_pipeline(
            [b"x"],
            ano_alvo=2026,
            regime_atual="SIMPLES",
            extrator=_extrator_mock_simples,
        )
        assert r.competencia == date(2026, 6, 1)


# ─────────────────────────────────────────────────────────────────────────────
# VALIDAÇÕES (falha fechada)
# ─────────────────────────────────────────────────────────────────────────────

class TestValidacoes:
    def test_pdfs_vazio_levanta_erro_explicito(self):
        with pytest.raises(ValueError, match="vazio"):
            gerar_projecao_pipeline(
                [],
                ano_alvo=2026,
                regime_atual="SIMPLES",
                extrator=_extrator_mock_simples,
            )

    def test_extrator_que_devolve_dado_invalido_propaga_erro(self):
        # Extrator com CNPJ inválido → adapter detecta e levanta
        def extrator_quebrado(pdfs):
            return _DadosExtraidosFake(
                cnpj="123",  # inválido
                competencia="06/2026",
                rpa_referencia="100000",
                das_breakdown={},
            )
        with pytest.raises(ValueError, match="CNPJ"):
            gerar_projecao_pipeline(
                [b"x"],
                ano_alvo=2026,
                regime_atual="SIMPLES",
                extrator=extrator_quebrado,
            )

    def test_ano_fora_do_cronograma_levanta(self):
        with pytest.raises(ValueError, match="cronograma"):
            gerar_projecao_pipeline(
                [b"x"],
                ano_alvo=2025,  # fora do cronograma 2026-2033
                regime_atual="SIMPLES",
                extrator=_extrator_mock_simples,
            )


# ─────────────────────────────────────────────────────────────────────────────
# RASTREABILIDADE
# ─────────────────────────────────────────────────────────────────────────────

class TestRastreabilidade:
    def test_hash_origem_propaga_ate_delta_se_aplicavel(self):
        # documento_origem_hash é propagado pelo adapter pro DocumentoFiscal,
        # que não é exposto direto no Delta. Mas o caller pode usar pra
        # auditoria do request inteiro.
        r = gerar_projecao_pipeline(
            [b"x"],
            ano_alvo=2026,
            regime_atual="SIMPLES",
            extrator=_extrator_mock_simples,
            documento_origem_hash="abc" + "0" * 61,
        )
        # Delta tem base_legal canônica
        assert any("LC 214/2025" in s for s in r.base_legal)


# ─────────────────────────────────────────────────────────────────────────────
# EXTRATOR REAL — default deve ser o real (não testamos chamada à API)
# ─────────────────────────────────────────────────────────────────────────────

class TestComparativoPipeline:
    """gerar_comparativo_pipeline: guia extraída → melhor cenário."""

    def test_retorna_comparativo(self):
        from core.comparador_cenarios import ComparativoCenarios
        from services.projecao_pipeline import gerar_comparativo_pipeline

        r = gerar_comparativo_pipeline(
            [b"x"],
            ano_alvo=2027,
            regime_atual="SIMPLES",
            extrator=_extrator_mock_simples,
        )
        assert isinstance(r, ComparativoCenarios)
        assert r.cnpj == "12345678000195"
        assert r.regime_atual == "SIMPLES"

    def test_perfil_montado_do_proprio_extrator(self):
        # CNAE/UF/RBT12 vêm do payload do extrator — cenário MIGRAR_PRESUMIDO
        # é avaliado sem nenhum input manual.
        from services.projecao_pipeline import gerar_comparativo_pipeline

        r = gerar_comparativo_pipeline(
            [b"x"],
            ano_alvo=2027,
            regime_atual="SIMPLES",
            extrator=_extrator_mock_simples,
        )
        presumido = next(c for c in r.cenarios if c.id == "MIGRAR_PRESUMIDO")
        assert presumido.status == "AVALIADO"

    def test_override_habilita_cenario_real(self):
        from services.projecao_pipeline import gerar_comparativo_pipeline

        r = gerar_comparativo_pipeline(
            [b"x"],
            ano_alvo=2027,
            regime_atual="SIMPLES",
            extrator=_extrator_mock_simples,
            perfil_overrides={"lucro_real_mensal": Decimal("20000.00")},
        )
        real = next(c for c in r.cenarios if c.id == "MIGRAR_REAL")
        assert real.status == "AVALIADO"

    def test_sem_override_cenario_real_nao_avaliado(self):
        from services.projecao_pipeline import gerar_comparativo_pipeline

        r = gerar_comparativo_pipeline(
            [b"x"],
            ano_alvo=2027,
            regime_atual="SIMPLES",
            extrator=_extrator_mock_simples,
        )
        real = next(c for c in r.cenarios if c.id == "MIGRAR_REAL")
        assert real.status == "NAO_AVALIADO"

    def test_pdfs_vazio_levanta(self):
        from services.projecao_pipeline import gerar_comparativo_pipeline

        with pytest.raises(ValueError, match="vazio"):
            gerar_comparativo_pipeline(
                [],
                ano_alvo=2027,
                regime_atual="SIMPLES",
                extrator=_extrator_mock_simples,
            )


class TestExtratorReal:
    def test_default_extrator_eh_o_real_quando_none(self):
        # Se chamarmos sem injetar extrator, o pipeline tenta importar o real.
        # Aqui validamos só que o import funciona (sem chamar Claude Vision
        # de verdade — passamos pdfs_bytes vazio pra falhar antes).
        with pytest.raises(ValueError, match="vazio"):
            gerar_projecao_pipeline(
                [],
                ano_alvo=2026,
                regime_atual="SIMPLES",
            )  # sem extrator => default real

    def test_extrator_injetado_eh_chamado_uma_unica_vez(self):
        chamadas: list[int] = []

        def _conta(_pdfs):
            chamadas.append(len(_pdfs))
            return _DadosExtraidosFake(
                cnpj="12345678000195",
                competencia="06/2026",
                rpa_referencia="100000",
                das_breakdown={},
            )

        gerar_projecao_pipeline(
            [b"a", b"b", b"c"],
            ano_alvo=2026,
            regime_atual="SIMPLES",
            extrator=_conta,
        )
        assert chamadas == [3]
