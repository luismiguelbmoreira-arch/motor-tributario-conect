# -*- coding: utf-8 -*-
"""
test_fontes_base.py — Cobertura do contrato core/fontes/base.py.

Garante que:
- Classes que implementam o Protocol passam isinstance check.
- Classes que NÃO implementam (faltando nome ou método) são rejeitadas.
- Exceções de domínio carregam contexto útil (faltantes na DadosInsuficientesNaFonte).
"""

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.fontes import (
    DadosInsuficientesNaFonte,
    FonteCliente,
    FonteIndisponivel,
)
from schemas.historico_seis_meses import HistoricoSeisMeses, MesHistorico
from schemas.motor import EmpresaCompradora, EmpresaFornecedora, OperacaoFiscal


# ── Fixture: histórico válido pra retorno em mocks ───────────────────────────

def _historico_minimo() -> HistoricoSeisMeses:
    fornecedora = EmpresaFornecedora(
        cnpj="11222333000181",
        razao_social="Empresa Teste Ltda",
        regime="SIMPLES",
        cnae_principal="6911701",
        uf_origem="SP",
        faturamento_12m=Decimal("600000"),
    )
    compradora = EmpresaCompradora(
        tipo="B2B_CONTRIBUINTE",
        percentual_b2b=Decimal("100"),
        uf_destino="SP",
    )
    meses = [
        MesHistorico(
            competencia=f"2026-{i + 1:02d}",
            rbt12_no_mes=Decimal("600000"),
            folha_mes=Decimal("0"),
            folha_12m_no_mes=Decimal("0"),
            operacoes=[OperacaoFiscal(
                data_emissao=date(2026, i + 1, 15),
                valor_operacao=Decimal("50000"),
                ncm_nbs="84715099",
                forma_recebimento="PIX_DIRETO",
            )],
        )
        for i in range(6)
    ]
    return HistoricoSeisMeses(
        fornecedora_base=fornecedora,
        compradora_padrao=compradora,
        meses=meses,
    )


# ── Implementações de teste ──────────────────────────────────────────────────

class FonteFakeOk:
    """Fonte que cumpre o contrato — devolve histórico fixo."""
    nome = "FAKE_OK"

    def obter_historico_seis_meses(
        self,
        cnpj: str,
        mes_inicio: str,
    ) -> HistoricoSeisMeses:
        return _historico_minimo()


class FonteFakeIndisponivel:
    nome = "FAKE_INDISPONIVEL"

    def obter_historico_seis_meses(
        self,
        cnpj: str,
        mes_inicio: str,
    ) -> HistoricoSeisMeses:
        raise FonteIndisponivel("API fora do ar — simulação")


class FonteFakeInsuficiente:
    nome = "FAKE_INSUFICIENTE"

    def obter_historico_seis_meses(
        self,
        cnpj: str,
        mes_inicio: str,
    ) -> HistoricoSeisMeses:
        raise DadosInsuficientesNaFonte(
            "Faltam 2 meses no Nibo",
            faltantes=["2026-03", "2026-04"],
        )


class FonteSemNome:
    """Não tem atributo `nome` — viola o contrato."""

    def obter_historico_seis_meses(
        self,
        cnpj: str,
        mes_inicio: str,
    ) -> HistoricoSeisMeses:
        return _historico_minimo()


class FonteSemMetodo:
    """Tem nome mas não implementa o método — viola o contrato."""
    nome = "FAKE_SEM_METODO"


# ── Contratualidade do Protocol ──────────────────────────────────────────────

def test_fonte_completa_passa_isinstance():
    fonte = FonteFakeOk()
    assert isinstance(fonte, FonteCliente)


def test_fonte_sem_metodo_falha_isinstance():
    fonte = FonteSemMetodo()
    assert not isinstance(fonte, FonteCliente)


def test_fonte_completa_devolve_historico_valido():
    fonte = FonteFakeOk()
    hist = fonte.obter_historico_seis_meses("11222333000181", "2026-01")
    assert isinstance(hist, HistoricoSeisMeses)
    assert len(hist.meses) == 6


def test_fonte_tem_nome_estavel():
    fonte = FonteFakeOk()
    assert fonte.nome == "FAKE_OK"
    assert FonteFakeOk.nome == "FAKE_OK"  # constante de classe


# ── Exceções de domínio ──────────────────────────────────────────────────────

def test_fonte_indisponivel_eh_excecao():
    assert issubclass(FonteIndisponivel, Exception)


def test_fonte_indisponivel_carrega_mensagem():
    fonte = FonteFakeIndisponivel()
    with pytest.raises(FonteIndisponivel, match="API fora do ar"):
        fonte.obter_historico_seis_meses("11222333000181", "2026-01")


def test_dados_insuficientes_eh_excecao():
    assert issubclass(DadosInsuficientesNaFonte, Exception)


def test_dados_insuficientes_carrega_faltantes():
    fonte = FonteFakeInsuficiente()
    try:
        fonte.obter_historico_seis_meses("11222333000181", "2026-01")
        pytest.fail("Deveria ter levantado DadosInsuficientesNaFonte")
    except DadosInsuficientesNaFonte as e:
        assert "Faltam 2 meses" in str(e)
        assert e.faltantes == ["2026-03", "2026-04"]


def test_dados_insuficientes_faltantes_default_vazio():
    erro = DadosInsuficientesNaFonte("sem detalhe")
    assert erro.faltantes == []


# ── Distinção entre as 2 exceções (R5 separação) ─────────────────────────────

def test_indisponivel_e_insuficiente_sao_excecoes_distintas():
    """
    Caller deve poder pegar uma sem pegar a outra (retry vs pendência ao usuário).
    """
    assert not issubclass(FonteIndisponivel, DadosInsuficientesNaFonte)
    assert not issubclass(DadosInsuficientesNaFonte, FonteIndisponivel)
