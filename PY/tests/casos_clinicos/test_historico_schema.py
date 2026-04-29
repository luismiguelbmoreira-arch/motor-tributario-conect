# -*- coding: utf-8 -*-
"""
test_historico_schema.py — Testes de validação do schema HistoricoSeisMeses.
Cobre: formato competencia, meses consecutivos, folha_12m >= folha_mes,
data_emissao dentro da competencia, coerência rbt12 com fornecedora_base.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from datetime import date
from decimal import Decimal

from pydantic import ValidationError

from schemas.historico_seis_meses import HistoricoSeisMeses, MesHistorico, _next_competencia
from schemas.motor import EmpresaCompradora, EmpresaFornecedora, OperacaoFiscal


# ── Fixtures base ─────────────────────────────────────────────────────────────

def _fornecedora(rbt12=Decimal("1200000"), folha=Decimal("180000")):
    return EmpresaFornecedora(
        cnpj="54657895000160",
        razao_social="Padaria Sao Joao Ltda",
        regime="SIMPLES",
        cnae_principal="1091101",
        uf_origem="SP",
        faturamento_12m=rbt12,
        folha_salarios_12m=folha,
    )


def _compradora():
    return EmpresaCompradora(tipo="B2C_CONSUMIDOR_FINAL", percentual_b2b=Decimal("0"), uf_destino="SP")


def _op(year: int, month: int, val=Decimal("100000")):
    return OperacaoFiscal(
        data_emissao=date(year, month, 15),
        valor_operacao=val,
        ncm_nbs="19059090",
        forma_recebimento="PIX_DIRETO",
    )


def _seis_meses(rbt12_final=Decimal("1200000"), folha_final=Decimal("180000")):
    """Gera lista de 6 MesHistorico consecutivos a partir de 2026-01."""
    meses = []
    for i in range(6):
        step = Decimal(str(i)) / Decimal("5")
        rbt12_i = rbt12_final * (Decimal("0.917") + step * Decimal("0.083"))
        rbt12_i = rbt12_i.quantize(Decimal("1"))
        if i == 5:
            rbt12_i = rbt12_final
        folha_i = folha_final
        meses.append(MesHistorico(
            competencia=f"2026-{i + 1:02d}",
            rbt12_no_mes=rbt12_i,
            folha_mes=folha_final / 12,
            folha_12m_no_mes=folha_i,
            operacoes=[_op(2026, i + 1)],
        ))
    return meses


# ── _next_competencia ─────────────────────────────────────────────────────────

class TestNextCompetencia:
    def test_mes_normal(self):
        assert _next_competencia("2026-01") == "2026-02"

    def test_virada_de_ano(self):
        assert _next_competencia("2026-12") == "2027-01"

    def test_dezembro_extremo(self):
        assert _next_competencia("2033-12") == "2034-01"


# ── MesHistorico ──────────────────────────────────────────────────────────────

class TestMesHistorico:
    def test_valido(self):
        m = MesHistorico(
            competencia="2026-03",
            rbt12_no_mes=Decimal("500000"),
            folha_mes=Decimal("10000"),
            folha_12m_no_mes=Decimal("120000"),
            operacoes=[_op(2026, 3)],
        )
        assert m.competencia == "2026-03"

    def test_competencia_invalida_formato(self):
        with pytest.raises(ValidationError, match="Competência"):
            MesHistorico(
                competencia="03/2026",
                rbt12_no_mes=Decimal("100000"),
                folha_mes=Decimal("0"),
                folha_12m_no_mes=Decimal("0"),
                operacoes=[_op(2026, 3)],
            )

    def test_competencia_fora_da_janela_2026_2033(self):
        with pytest.raises(ValidationError, match="Competência"):
            MesHistorico(
                competencia="2025-12",
                rbt12_no_mes=Decimal("100000"),
                folha_mes=Decimal("0"),
                folha_12m_no_mes=Decimal("0"),
                operacoes=[_op(2026, 3)],  # data_emissao dentro da janela, competencia fora
            )

    def test_folha_12m_menor_que_folha_mes_rejeitada(self):
        with pytest.raises(ValidationError, match="folha_12m"):
            MesHistorico(
                competencia="2026-06",
                rbt12_no_mes=Decimal("100000"),
                folha_mes=Decimal("20000"),
                folha_12m_no_mes=Decimal("10000"),  # menor que folha_mes
                operacoes=[_op(2026, 6)],
            )

    def test_folha_12m_igual_folha_mes_aceita(self):
        m = MesHistorico(
            competencia="2026-01",
            rbt12_no_mes=Decimal("100000"),
            folha_mes=Decimal("8333"),
            folha_12m_no_mes=Decimal("8333"),  # igual — empresa nova
            operacoes=[_op(2026, 1)],
        )
        assert m.folha_12m_no_mes == m.folha_mes

    def test_operacao_fora_da_competencia_rejeitada(self):
        with pytest.raises(ValidationError, match="competência"):
            MesHistorico(
                competencia="2026-03",
                rbt12_no_mes=Decimal("100000"),
                folha_mes=Decimal("0"),
                folha_12m_no_mes=Decimal("0"),
                operacoes=[_op(2026, 4)],  # abril, não março
            )

    def test_sem_operacoes_rejeitado(self):
        with pytest.raises(ValidationError):
            MesHistorico(
                competencia="2026-03",
                rbt12_no_mes=Decimal("100000"),
                folha_mes=Decimal("0"),
                folha_12m_no_mes=Decimal("0"),
                operacoes=[],
            )

    def test_rbt12_zero_rejeitado(self):
        with pytest.raises(ValidationError):
            MesHistorico(
                competencia="2026-03",
                rbt12_no_mes=Decimal("0"),
                folha_mes=Decimal("0"),
                folha_12m_no_mes=Decimal("0"),
                operacoes=[_op(2026, 3)],
            )


# ── HistoricoSeisMeses ────────────────────────────────────────────────────────

class TestHistoricoSeisMeses:
    def test_historico_valido(self):
        h = HistoricoSeisMeses(
            fornecedora_base=_fornecedora(),
            compradora_padrao=_compradora(),
            meses=_seis_meses(),
        )
        assert len(h.meses) == 6
        assert h.meses[0].competencia == "2026-01"
        assert h.meses[-1].competencia == "2026-06"

    def test_menos_de_seis_meses_rejeitado(self):
        with pytest.raises(ValidationError):
            HistoricoSeisMeses(
                fornecedora_base=_fornecedora(),
                compradora_padrao=_compradora(),
                meses=_seis_meses()[:5],
            )

    def test_mais_de_seis_meses_rejeitado(self):
        meses = _seis_meses()
        extra = MesHistorico(
            competencia="2026-07",
            rbt12_no_mes=Decimal("1200000"),
            folha_mes=Decimal("15000"),
            folha_12m_no_mes=Decimal("180000"),
            operacoes=[_op(2026, 7)],
        )
        with pytest.raises(ValidationError):
            HistoricoSeisMeses(
                fornecedora_base=_fornecedora(),
                compradora_padrao=_compradora(),
                meses=meses + [extra],
            )

    def test_meses_nao_consecutivos_rejeitados(self):
        meses = _seis_meses()
        # Substitui mês 3 por mês 5 — cria lacuna
        meses[2] = MesHistorico(
            competencia="2026-05",
            rbt12_no_mes=Decimal("1100000"),
            folha_mes=Decimal("15000"),
            folha_12m_no_mes=Decimal("180000"),
            operacoes=[_op(2026, 5)],
        )
        with pytest.raises(ValidationError, match="consecutivos"):
            HistoricoSeisMeses(
                fornecedora_base=_fornecedora(),
                compradora_padrao=_compradora(),
                meses=meses,
            )

    def test_rbt12_ultimo_mes_diverge_de_fornecedora_rejeitado(self):
        meses = _seis_meses(rbt12_final=Decimal("1200000"))
        with pytest.raises(ValidationError, match="faturamento_12m"):
            HistoricoSeisMeses(
                fornecedora_base=_fornecedora(rbt12=Decimal("999999")),  # diferente
                compradora_padrao=_compradora(),
                meses=meses,
            )

    def test_frozen_nao_permite_mutacao(self):
        h = HistoricoSeisMeses(
            fornecedora_base=_fornecedora(),
            compradora_padrao=_compradora(),
            meses=_seis_meses(),
        )
        with pytest.raises(Exception):
            h.meses = []  # type: ignore
