# -*- coding: utf-8 -*-
"""
tests/test_cooperativa_overlay.py — WS6 Etapa 5a
CooperativaOverlay sobrepõe regime regular (Presumido/Real/Simples) com:
  1. Fora-de-incidência Art. 6º VI/X/XI LC 214/2025 (sempre)
  2. Alíquota zero Art. 271 IBS/CBS sobre ato cooperativo (se optante + janela)
  3. Alertas específicos por ramo (AGROPECUARIA, TRANSPORTE)

NÃO HERDA BaseRegimeEngine — é decorator/overlay, não engine.

BASE LEGAL (validada por Escrivão 2026-05-08 contra cache local):
  - LC 214/2025 Art. 6º VI/X/XI (fora de incidência)
  - LC 214/2025 Art. 169 § 8º (crédito presumido coop transporte)
  - LC 214/2025 Art. 271 caput + I, II + § 1º II + § 3º + § 4º
  - LC 214/2025 Art. 272 (transferência créditos sem aplicar Art. 55)
  - Lei 5.764/71 Art. 28 (fundos: Reserva 10% + FATES 5%)
  - Lei 5.764/71 Art. 79 (definição ato cooperativo)
  - Lei 5.764/71 Art. 87 (caput, texto único — segregação contábil)
  - Lei 5.764/71 Art. 111 (regra de incidência sobre ato não-cooperativo)

Rode com: pytest PY/tests/test_cooperativa_overlay.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.regimes.cooperativa import CooperativaOverlay  # noqa: E402
from schemas.motor import EmpresaFornecedora  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _coop(
    *,
    ramo: str = "CONSUMO",
    regime: str = "PRESUMIDO",
    optante: bool = False,
    data_opcao: date | None = None,
    receita_ato_coop: Decimal = Decimal("80000.00"),
    receita_ato_nao_coop: Decimal = Decimal("20000.00"),
    cnae: str = "4711301",
) -> EmpresaFornecedora:
    """Cooperativa fornecedora válida com sane defaults."""
    return EmpresaFornecedora(
        cnpj="33000167000101",
        razao_social=f"COOPERATIVA TESTE {ramo}",
        regime=regime,
        cnae_principal=cnae,
        uf_origem="SP",
        faturamento_12m=receita_ato_coop + receita_ato_nao_coop,
        tipo_societario="COOPERATIVA",
        subtipo_cooperativa=ramo,
        optante_art271_cbs_ibs=optante,
        data_opcao_art271=data_opcao,
        receita_ato_cooperativo=receita_ato_coop,
        receita_ato_nao_cooperativo=receita_ato_nao_coop,
    )


def _resultado_engine_fake(
    *,
    ibs: Decimal = Decimal("8000.00"),
    cbs: Decimal = Decimal("4000.00"),
    base: Decimal = Decimal("100000.00"),
) -> dict:
    """Resultado simulado de um engine regular (Presumido/Real)."""
    return {
        "regime": "PRESUMIDO",
        "ibs_total": ibs,
        "cbs_total": cbs,
        "base_calculo": base,
        "total_iva": ibs + cbs,
    }


@pytest.fixture
def trilha():
    return []


@pytest.fixture
def data_op():
    return date(2027, 6, 15)


@pytest.fixture
def data_op_anterior():
    return date(2026, 12, 1)


# ─────────────────────────────────────────────────────────────────────────────
# CONSTRUÇÃO + INVOCAÇÃO BÁSICA
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaOverlayConstrucao:
    """Overlay aceita fornecedora cooperativa válida e devolve dict ajustado."""

    def test_construcao_com_cooperativa_consumo_passa(self, trilha, data_op):
        overlay = CooperativaOverlay(_coop(ramo="CONSUMO"), trilha)
        r = overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        assert isinstance(r, dict)
        assert r["regime"] == "PRESUMIDO"  # preserva regime regular
        assert r["tipo_societario"] == "COOPERATIVA"
        assert r["subtipo_cooperativa"] == "CONSUMO"

    def test_overlay_recusa_nao_cooperativa(self, trilha, data_op):
        # Empresa não-cooperativa não pode passar pelo overlay
        emp = EmpresaFornecedora(
            cnpj="11222333000181",
            razao_social="LTDA",
            regime="PRESUMIDO",
            cnae_principal="4757100",
            uf_origem="SP",
            faturamento_12m=Decimal("100000"),
            tipo_societario="LTDA",
        )
        with pytest.raises(ValueError, match="COOPERATIVA"):
            CooperativaOverlay(emp, trilha)

    def test_overlay_devolve_breakdown_com_split(self, trilha, data_op):
        overlay = CooperativaOverlay(_coop(receita_ato_coop=Decimal("80000"),
                                          receita_ato_nao_coop=Decimal("20000")),
                                     trilha)
        r = overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        assert r["receita_ato_cooperativo"] == Decimal("80000")
        assert r["receita_ato_nao_cooperativo"] == Decimal("20000")


# ─────────────────────────────────────────────────────────────────────────────
# OPT-IN ART. 271 — zera IBS/CBS sobre ato cooperativo
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaOverlayArt271OptIn:
    """Optante + janela § 3º válida → zera IBS+CBS sobre ato cooperativo."""

    def test_optante_zera_ibs_cbs_sobre_ato_cooperativo(
        self, trilha, data_op, data_op_anterior
    ):
        overlay = CooperativaOverlay(
            _coop(
                ramo="PRODUCAO",
                regime="REAL",
                optante=True,
                data_opcao=data_op_anterior,
                receita_ato_coop=Decimal("80000"),
                receita_ato_nao_coop=Decimal("20000"),
            ),
            trilha,
        )
        r = overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        # Receita ato cooperativo zerada
        assert r["ibs_ato_cooperativo"] == Decimal("0.00")
        assert r["cbs_ato_cooperativo"] == Decimal("0.00")
        # Ato não-cooperativo permanece tributado pelo engine regular (preserva valor)
        assert r["ibs_ato_nao_cooperativo"] > Decimal("0")

    def test_optante_registra_ajuste_na_trilha(
        self, trilha, data_op, data_op_anterior
    ):
        overlay = CooperativaOverlay(
            _coop(optante=True, data_opcao=data_op_anterior),
            trilha,
        )
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        ids = {e["id"] for e in trilha}
        assert "AJUSTE_COOPERATIVA_ART271_ALIQUOTA_ZERO" in ids

    def test_optante_ajuste_cita_art_271(
        self, trilha, data_op, data_op_anterior
    ):
        overlay = CooperativaOverlay(
            _coop(optante=True, data_opcao=data_op_anterior),
            trilha,
        )
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        evento = next(
            e for e in trilha if e["id"] == "AJUSTE_COOPERATIVA_ART271_ALIQUOTA_ZERO"
        )
        amparo = evento["amparo_legal"]
        assert "Art. 271" in amparo
        assert "LC 214" in amparo


# ─────────────────────────────────────────────────────────────────────────────
# NÃO-OPTANTE — preserva tributação do engine regular sobre ato cooperativo
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaOverlayNaoOptante:
    """Não-optante: ato cooperativo permanece tributado pelo regime regular."""

    def test_nao_optante_nao_zera_ibs_cbs_ato_cooperativo(self, trilha, data_op):
        overlay = CooperativaOverlay(
            _coop(optante=False, receita_ato_coop=Decimal("80000")),
            trilha,
        )
        r = overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        # Sem opt-in, IBS/CBS sobre ato cooperativo NÃO é zerado pelo Art. 271
        assert r["ibs_ato_cooperativo"] > Decimal("0")
        assert r["cbs_ato_cooperativo"] > Decimal("0")

    def test_nao_optante_nao_registra_ajuste_art271(self, trilha, data_op):
        overlay = CooperativaOverlay(_coop(optante=False), trilha)
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        ids = {e["id"] for e in trilha}
        assert "AJUSTE_COOPERATIVA_ART271_ALIQUOTA_ZERO" not in ids


# ─────────────────────────────────────────────────────────────────────────────
# JANELA § 3º — opção tem que ser ano-calendário anterior
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaOverlayJanelaArt271:
    """Rail R8 — Art. 271 § 3º exige opção declarada no ano-calendário anterior."""

    def test_opcao_no_mesmo_ano_da_operacao_nao_zera(self, trilha):
        overlay = CooperativaOverlay(
            _coop(
                optante=True,
                data_opcao=date(2027, 1, 5),
            ),
            trilha,
        )
        r = overlay.aplicar(
            _resultado_engine_fake(),
            data_emissao=date(2027, 6, 15),  # mesmo ano da opção
        )
        assert r["ibs_ato_cooperativo"] > Decimal("0")
        ids = {e["id"] for e in trilha}
        assert "AJUSTE_COOPERATIVA_ART271_ALIQUOTA_ZERO" not in ids
        assert "ALERTA_COOPERATIVA_ART271_FORA_DE_JANELA" in ids


# ─────────────────────────────────────────────────────────────────────────────
# FORA-DE-INCIDÊNCIA — Art. 6º VI/X/XI LC 214 (sempre)
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaOverlayForaIncidencia:
    """LC 214/2025 Art. 6º VI/X/XI — não há fato gerador (sempre, independente do opt-in)."""

    def test_alerta_fora_incidencia_sempre_presente(self, trilha, data_op):
        overlay = CooperativaOverlay(_coop(optante=False), trilha)
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        ids = {e["id"] for e in trilha}
        assert "ALERTA_COOPERATIVA_FORA_INCIDENCIA_ART6" in ids

    def test_fora_incidencia_cita_art_6_incs_vi_x_xi(self, trilha, data_op):
        overlay = CooperativaOverlay(_coop(), trilha)
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        evento = next(
            e for e in trilha if e["id"] == "ALERTA_COOPERATIVA_FORA_INCIDENCIA_ART6"
        )
        amparo = evento["amparo_legal"]
        assert "Art. 6" in amparo
        # Pelo menos um dos incisos VI / X / XI deve constar
        assert "VI" in amparo or "X" in amparo or "XI" in amparo

    def test_fora_incidencia_e_distinto_de_art_271(self, trilha, data_op):
        # Fora-de-incidência (Art. 6º) ≠ alíquota zero (Art. 271).
        # Mesmo SEM opt-in, alerta de fora-de-incidência aparece.
        overlay = CooperativaOverlay(_coop(optante=False), trilha)
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        evento = next(
            e for e in trilha if e["id"] == "ALERTA_COOPERATIVA_FORA_INCIDENCIA_ART6"
        )
        # Alerta NÃO confunde com Art. 271 (que é alíquota zero)
        assert "Art. 271" not in evento["amparo_legal"]


# ─────────────────────────────────────────────────────────────────────────────
# AGROPECUARIA — alerta anulação Art. 271 § 1º II
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaOverlayAgropecuaria:
    """Cooperativa AGROPECUARIA + opt-in → alerta anulação crédito (Art. 271 § 1º II)."""

    def test_agropecuaria_optante_emite_alerta_anulacao(
        self, trilha, data_op, data_op_anterior
    ):
        overlay = CooperativaOverlay(
            _coop(
                ramo="AGROPECUARIA",
                regime="REAL",
                optante=True,
                data_opcao=data_op_anterior,
                cnae="0151201",
            ),
            trilha,
        )
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        ids = {e["id"] for e in trilha}
        assert "ALERTA_COOPERATIVA_AGROPECUARIA_ANULACAO_CREDITO" in ids

    def test_agropecuaria_alerta_cita_art_271_par1_ii(
        self, trilha, data_op, data_op_anterior
    ):
        overlay = CooperativaOverlay(
            _coop(
                ramo="AGROPECUARIA",
                regime="REAL",
                optante=True,
                data_opcao=data_op_anterior,
            ),
            trilha,
        )
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        evento = next(
            e for e in trilha
            if e["id"] == "ALERTA_COOPERATIVA_AGROPECUARIA_ANULACAO_CREDITO"
        )
        amparo = evento["amparo_legal"]
        assert "Art. 271" in amparo and ("§ 1" in amparo or "§1" in amparo)
        assert "II" in amparo

    def test_agropecuaria_nao_optante_nao_emite_alerta(
        self, trilha, data_op
    ):
        overlay = CooperativaOverlay(
            _coop(
                ramo="AGROPECUARIA",
                regime="REAL",
                optante=False,
            ),
            trilha,
        )
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        ids = {e["id"] for e in trilha}
        # Sem opt-in não há que falar em anulação proporcional do Art. 271
        assert "ALERTA_COOPERATIVA_AGROPECUARIA_ANULACAO_CREDITO" not in ids


# ─────────────────────────────────────────────────────────────────────────────
# TRANSPORTE — crédito presumido Art. 169 § 8º
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaOverlayTransporte:
    """Cooperativa TRANSPORTE → alerta crédito presumido (LC 214 Art. 169 § 8º)."""

    def test_transporte_emite_alerta_credito_presumido(
        self, trilha, data_op
    ):
        overlay = CooperativaOverlay(
            _coop(
                ramo="TRANSPORTE",
                regime="PRESUMIDO",
                cnae="4930202",
            ),
            trilha,
        )
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        ids = {e["id"] for e in trilha}
        assert "ALERTA_COOPERATIVA_TRANSPORTE_CREDITO_PRESUMIDO" in ids

    def test_transporte_alerta_cita_art_169_par8(self, trilha, data_op):
        overlay = CooperativaOverlay(
            _coop(ramo="TRANSPORTE", cnae="4930202"),
            trilha,
        )
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        evento = next(
            e for e in trilha
            if e["id"] == "ALERTA_COOPERATIVA_TRANSPORTE_CREDITO_PRESUMIDO"
        )
        amparo = evento["amparo_legal"]
        assert "Art. 169" in amparo
        assert "§ 8" in amparo or "§8" in amparo


# ─────────────────────────────────────────────────────────────────────────────
# 5b CREDITO — Arts. 188, 192 § 8º, 197 I
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaOverlayCredito:
    """Cooperativa de CRÉDITO — alertas específicos do regime financeiro."""

    def test_credito_alerta_operacoes_associado_fora_base_sempre(
        self, trilha, data_op,
    ):
        # Art. 192 § 8º — operações coop-associado fora da base SEMPRE,
        # independente do opt-in Art. 271
        emp = _coop(
            ramo="CREDITO",
            regime="REAL",
            optante=False,
            cnae="6422100",
        )
        overlay = CooperativaOverlay(emp, trilha)
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        ids = {e["id"] for e in trilha}
        assert "ALERTA_COOPERATIVA_CREDITO_OPERACOES_ASSOCIADO_FORA_BASE" in ids
        evento = next(
            e for e in trilha
            if e["id"] == "ALERTA_COOPERATIVA_CREDITO_OPERACOES_ASSOCIADO_FORA_BASE"
        )
        amparo = evento["amparo_legal"]
        assert "Art. 192" in amparo
        assert "§ 8" in amparo or "§8" in amparo

    def test_credito_optin_alerta_reversao_deducoes_art_188(
        self, trilha, data_op, data_op_anterior,
    ):
        emp = _coop(
            ramo="CREDITO",
            regime="REAL",
            optante=True,
            data_opcao=data_op_anterior,
            cnae="6422100",
        )
        overlay = CooperativaOverlay(emp, trilha)
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        ids = {e["id"] for e in trilha}
        assert "ALERTA_COOPERATIVA_CREDITO_REVERSAO_DEDUCOES_ART188" in ids
        evento = next(
            e for e in trilha
            if e["id"] == "ALERTA_COOPERATIVA_CREDITO_REVERSAO_DEDUCOES_ART188"
        )
        assert "Art. 188" in evento["amparo_legal"]

    def test_credito_optin_alerta_associado_tomador_nao_credita_art197(
        self, trilha, data_op, data_op_anterior,
    ):
        emp = _coop(
            ramo="CREDITO",
            regime="REAL",
            optante=True,
            data_opcao=data_op_anterior,
            cnae="6422100",
        )
        overlay = CooperativaOverlay(emp, trilha)
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        ids = {e["id"] for e in trilha}
        assert "ALERTA_COOPERATIVA_CREDITO_ASSOCIADO_TOMADOR_SEM_CREDITO" in ids
        evento = next(
            e for e in trilha
            if e["id"] == "ALERTA_COOPERATIVA_CREDITO_ASSOCIADO_TOMADOR_SEM_CREDITO"
        )
        amparo = evento["amparo_legal"]
        assert "Art. 197" in amparo
        assert "227" in amparo  # LC 227/2026

    def test_credito_cita_art_183_par_1_iii_nao_182(self, trilha, data_op):
        # Bloqueio MAX_07: rascunho original do Luiz citava Art. 182 § 1º III
        # (errado). Correto: Art. 183 § 1º III (entidade supervisionada SFN).
        emp = _coop(
            ramo="CREDITO",
            regime="REAL",
            optante=False,
            cnae="6422100",
        )
        overlay = CooperativaOverlay(emp, trilha)
        r = overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        leis_breakdown = " ".join(r.get("base_legal_aplicavel", ()))
        leis_trilha = " ".join(e.get("amparo_legal", "") for e in trilha)
        leis = leis_breakdown + " " + leis_trilha
        assert "Art. 183" in leis
        # Art. 182 § 1º não existe nesse contexto — bloqueio anti-alucinação
        assert "Art. 182 § 1" not in leis
        assert "Art. 182, § 1" not in leis


# ─────────────────────────────────────────────────────────────────────────────
# 5b SAUDE — regime Cap III Tít V (Arts. 234-238)
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaOverlaySaude:
    """Cooperativa operadora de plano de saúde — regime próprio."""

    def test_saude_alerta_regime_especifico_sempre(self, trilha, data_op):
        emp = _coop(
            ramo="SAUDE",
            regime="PRESUMIDO",
            optante=False,
            cnae="8650099",
        )
        overlay = CooperativaOverlay(emp, trilha)
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        ids = {e["id"] for e in trilha}
        assert "ALERTA_COOPERATIVA_SAUDE_REGIME_ESPECIFICO" in ids

    def test_saude_alerta_cita_arts_234_237_238(self, trilha, data_op):
        emp = _coop(
            ramo="SAUDE",
            regime="PRESUMIDO",
            optante=False,
            cnae="8650099",
        )
        overlay = CooperativaOverlay(emp, trilha)
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        evento = next(
            e for e in trilha
            if e["id"] == "ALERTA_COOPERATIVA_SAUDE_REGIME_ESPECIFICO"
        )
        amparo = evento["amparo_legal"]
        assert "Art. 234" in amparo
        assert "Art. 237" in amparo
        assert "Art. 238" in amparo
        # 60% redução referenciada
        assert "60" in amparo

    def test_saude_nao_zera_ibs_cbs_sobre_ato_cooperativo(
        self, trilha, data_op,
    ):
        # SAUDE não tem opt-in Art. 271 — IBS/CBS do regular fica
        emp = _coop(
            ramo="SAUDE",
            regime="PRESUMIDO",
            optante=False,
            cnae="8650099",
        )
        overlay = CooperativaOverlay(emp, trilha)
        r = overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        # Engine regular calculou IBS/CBS proporcionais ao split — SAUDE não zera
        assert r["ibs_ato_cooperativo"] > Decimal("0")
        assert r["cbs_ato_cooperativo"] > Decimal("0")


# ─────────────────────────────────────────────────────────────────────────────
# CITAÇÕES LEGAIS — anti-alucinação MAX_07
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaOverlayCitacoesLegais:
    """Citações precisam bater com Escrivão; nada inventado."""

    def test_nao_cita_art_87_paragrafo_unico_inexistente(
        self, trilha, data_op
    ):
        overlay = CooperativaOverlay(_coop(), trilha)
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        amparos = " ".join(e.get("amparo_legal", "") for e in trilha)
        # Bloqueio ERR-058 potencial: Art. 87 § único NÃO existe na Lei 5.764
        assert "Art. 87 § único" not in amparos
        assert "Art. 87, § único" not in amparos
        assert "Art. 87 parágrafo único" not in amparos

    def test_classificacao_cita_art_10_caput_par_1(
        self, trilha, data_op
    ):
        overlay = CooperativaOverlay(_coop(ramo="CONSUMO"), trilha)
        r = overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        # base_legal_aplicavel devolvido pelo overlay deve mencionar Art. 10
        leis = " ".join(r.get("base_legal_aplicavel", ()))
        assert "Art. 10" in leis

    def test_ato_cooperativo_cita_art_79_lei_5764(
        self, trilha, data_op
    ):
        overlay = CooperativaOverlay(_coop(), trilha)
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        amparos = " ".join(e.get("amparo_legal", "") for e in trilha)
        # Art. 79 (definição canônica de ato cooperativo) tem que aparecer
        assert "Art. 79" in amparos
        assert "5.764" in amparos or "5764" in amparos

    def test_segregacao_contabil_cita_art_87_caput(
        self, trilha, data_op
    ):
        # Art. 87 (caput, texto único) — NÃO citar como § único
        overlay = CooperativaOverlay(_coop(), trilha)
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        amparos = " ".join(e.get("amparo_legal", "") for e in trilha)
        assert "Art. 87" in amparos


# ─────────────────────────────────────────────────────────────────────────────
# BREAKDOWN COMPLETO + PRESERVAÇÃO DA TRILHA UNIFICADA
# ─────────────────────────────────────────────────────────────────────────────

class TestCooperativaOverlayBreakdown:
    """Breakdown completo + integração com trilha unificada."""

    def test_breakdown_inclui_split_e_resultado_engine(
        self, trilha, data_op, data_op_anterior
    ):
        overlay = CooperativaOverlay(
            _coop(
                ramo="PRODUCAO",
                regime="REAL",
                optante=True,
                data_opcao=data_op_anterior,
                receita_ato_coop=Decimal("80000"),
                receita_ato_nao_coop=Decimal("20000"),
            ),
            trilha,
        )
        r = overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        # Campos obrigatórios no breakdown
        for k in (
            "tipo_societario",
            "subtipo_cooperativa",
            "regime",
            "optante_art271_cbs_ibs",
            "receita_ato_cooperativo",
            "receita_ato_nao_cooperativo",
            "ibs_ato_cooperativo",
            "cbs_ato_cooperativo",
            "ibs_ato_nao_cooperativo",
            "cbs_ato_nao_cooperativo",
            "total_iva_ajustado",
            "base_legal_aplicavel",
        ):
            assert k in r, f"campo {k} ausente no breakdown"

    def test_trilha_unificada_recebe_eventos_do_overlay(
        self, trilha, data_op
    ):
        overlay = CooperativaOverlay(_coop(), trilha)
        overlay.aplicar(_resultado_engine_fake(), data_emissao=data_op)
        # Pelo menos 1 ALERTA + 1 ajuste/cálculo cooperativo
        tipos = {e["tipo"] for e in trilha}
        assert any(t.startswith("ALERTA_") for t in tipos) or any(
            t.startswith("CALCULO") for t in tipos
        ) or "AJUSTE_COOPERATIVA" in tipos

    def test_total_iva_ajustado_reflete_zerar_quando_optante(
        self, trilha, data_op, data_op_anterior
    ):
        overlay = CooperativaOverlay(
            _coop(
                optante=True,
                data_opcao=data_op_anterior,
                receita_ato_coop=Decimal("80000"),
                receita_ato_nao_coop=Decimal("20000"),
            ),
            trilha,
        )
        r = overlay.aplicar(
            _resultado_engine_fake(
                ibs=Decimal("8000.00"),  # 80k coop * 10%
                cbs=Decimal("4000.00"),
                base=Decimal("100000.00"),
            ),
            data_emissao=data_op,
        )
        # Engine fake assumiu IBS/CBS sobre 100k. Após overlay zerar 80% (ato coop):
        # IBS ato_não_coop = 8000 * 0.20 = 1600; CBS ato_não_coop = 4000 * 0.20 = 800
        # Total ajustado = 2400
        assert r["total_iva_ajustado"] < Decimal("3000.00")
        assert r["total_iva_ajustado"] > Decimal("2000.00")
