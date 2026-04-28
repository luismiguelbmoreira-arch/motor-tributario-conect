"""
test_arquetipo_3_misto.py — Testes do Arquétipo 3 (Misto 50/50).

PROVA DE CONCEITO da Fase 0a — se este arquétipo virar verde, os outros 4
ficam triviais (são casos de borda em vez de centro).

Fixture: tests/casos_clinicos/fixtures_arquetipos.py::arquetipo_3_misto_5050

Estado: TDD red phase. Schema schemas.historico_seis_meses ainda não existe
até O Viciado implementar. Este arquivo ESPECIFICA o comportamento esperado.

Curador: Caso-Clínico (.claude/agents/caso-clinico.md)
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Schema ainda não existe — testes ficam SKIP até Viciado implementar.
# Quando schema chegar, importorskip vira import normal e testes rodam.
pytest.importorskip(
    "schemas.historico_seis_meses",
    reason="Schema HistoricoSeisMeses pendente — Fase 0a item 7 do todo",
)

from tests.casos_clinicos.fixtures_arquetipos import arquetipo_3_misto_5050  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# 1. ESTRUTURA: fixture é construível e respeita validators
# ─────────────────────────────────────────────────────────────────────────────


def test_arquetipo_3_e_construivel():
    """Fixture do Arquétipo 3 não pode falhar na construção."""
    historico = arquetipo_3_misto_5050()
    assert historico is not None
    assert historico.cnpj == "54657895000160"
    assert historico.razao_social == "Padaria Doce Manhã LTDA"


def test_arquetipo_3_tem_exatamente_6_meses():
    historico = arquetipo_3_misto_5050()
    assert len(historico.meses) == 6


def test_arquetipo_3_meses_sao_sequenciais():
    """Validator _meses_sequenciais_sem_buraco deve aceitar nov/2025 → abr/2026."""
    historico = arquetipo_3_misto_5050()
    competencias_esperadas = [
        "2025-11", "2025-12", "2026-01",
        "2026-02", "2026-03", "2026-04",
    ]
    competencias_real = [m.competencia for m in historico.meses]
    assert competencias_real == competencias_esperadas


def test_arquetipo_3_competencia_referencia_consistente():
    """competencia_referencia (MAX_03) é o último dia do último mês da janela."""
    historico = arquetipo_3_misto_5050()
    # Último mês = 2026-04 → último dia = 2026-04-30
    assert historico.competencia_referencia.year == 2026
    assert historico.competencia_referencia.month == 4
    assert historico.competencia_referencia.day == 30


# ─────────────────────────────────────────────────────────────────────────────
# 2. SEMÂNTICA: dados respeitam realidade fiscal de padaria Anexo I
# ─────────────────────────────────────────────────────────────────────────────


def test_arquetipo_3_anexo_e_sempre_I():
    """Padaria comércio = Anexo I em todos os 6 meses."""
    historico = arquetipo_3_misto_5050()
    for mes in historico.meses:
        assert mes.anexo_aplicado == "I", (
            f"{mes.competencia}: padaria deve estar em Anexo I, "
            f"recebido {mes.anexo_aplicado}"
        )


def test_arquetipo_3_rbt12_oscila_dentro_do_normal():
    """RBT12 oscila <50% entre meses (validator _rbt12_oscilacao_alerta).
    Empresa estável não dispara warning."""
    historico = arquetipo_3_misto_5050()
    for i in range(1, 6):
        anterior = historico.meses[i-1].rbt12_declarado
        atual = historico.meses[i].rbt12_declarado
        delta_pct = abs(atual - anterior) / anterior * 100
        assert delta_pct < Decimal("50"), (
            f"Mês {historico.meses[i].competencia}: RBT12 oscilou {delta_pct}% "
            f"vs mês anterior — fixture deveria ser estável"
        )


def test_arquetipo_3_rbt12_dentro_do_teto_simples():
    """Empresa Simples: RBT12 nunca pode estourar R$ 4.8M (validator
    _teto_simples_continuo). Padaria de R$ 2M está bem longe."""
    historico = arquetipo_3_misto_5050()
    for mes in historico.meses:
        assert mes.rbt12_declarado < Decimal("4800000.00"), (
            f"{mes.competencia}: fixture com RBT12 R$ {mes.rbt12_declarado} "
            f"estoura teto Simples — vai bloquear"
        )


def test_arquetipo_3_folha_12m_maior_que_folha_mes():
    """Validator _folha_12m_sanity: folha_12m sempre ≥ folha_pagamento_mes."""
    historico = arquetipo_3_misto_5050()
    for mes in historico.meses:
        assert mes.folha_12m >= mes.folha_pagamento_mes, (
            f"{mes.competencia}: folha_12m R$ {mes.folha_12m} < "
            f"folha_mes R$ {mes.folha_pagamento_mes} — impossível"
        )


def test_arquetipo_3_dezembro_tem_pico_sazonal():
    """Padaria sobe em dezembro (panetones, ceia). Faturamento de dez ≥ 30%
    acima da média dos outros 5 meses."""
    historico = arquetipo_3_misto_5050()
    dez_2025 = next(m for m in historico.meses if m.competencia == "2025-12")
    outros = [m for m in historico.meses if m.competencia != "2025-12"]
    media_outros = sum(m.faturamento_mes for m in outros) / len(outros)
    delta = (dez_2025.faturamento_mes - media_outros) / media_outros * 100
    assert delta >= Decimal("30"), (
        f"Sazonalidade dezembro deveria ser ≥30%, fixture entregou {delta}%"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. MIX 50/50: cada mês tem VENDA_B2B e VENDA_B2C com valores iguais
# ─────────────────────────────────────────────────────────────────────────────


def test_arquetipo_3_mix_50_50_em_todos_meses():
    """Misto 50/50 — em cada mês, VENDA_B2B e VENDA_B2C devem somar
    valores iguais (tolerância 1 centavo)."""
    historico = arquetipo_3_misto_5050()
    for mes in historico.meses:
        b2b = sum(
            (op.valor_total for op in mes.operacoes if op.tipo == "VENDA_B2B"),
            Decimal("0"),
        )
        b2c = sum(
            (op.valor_total for op in mes.operacoes if op.tipo == "VENDA_B2C"),
            Decimal("0"),
        )
        assert abs(b2b - b2c) <= Decimal("0.01"), (
            f"{mes.competencia}: B2B R$ {b2b} ≠ B2C R$ {b2c}, "
            f"mix deveria ser 50/50"
        )


def test_arquetipo_3_b2b_usa_boleto_b2c_usa_pix():
    """Realidade operacional: padaria B2B fatura por boleto (prazo 30d
    com restaurantes); B2C balcão é Pix instantâneo."""
    historico = arquetipo_3_misto_5050()
    for mes in historico.meses:
        for op in mes.operacoes:
            if op.tipo == "VENDA_B2B":
                assert op.forma_recebimento == "BOLETO", (
                    f"{mes.competencia}: B2B deveria ser BOLETO, "
                    f"recebido {op.forma_recebimento}"
                )
            elif op.tipo == "VENDA_B2C":
                assert op.forma_recebimento == "PIX_DIRETO", (
                    f"{mes.competencia}: B2C deveria ser PIX_DIRETO, "
                    f"recebido {op.forma_recebimento}"
                )


def test_arquetipo_3_soma_operacoes_bate_com_faturamento():
    """Validator _coerencia_faturamento_operacoes: soma das operações ≈
    faturamento_mes (tolerância 1%). Aqui esperamos bate exato."""
    historico = arquetipo_3_misto_5050()
    for mes in historico.meses:
        soma = sum((op.valor_total for op in mes.operacoes), Decimal("0"))
        assert soma == mes.faturamento_mes, (
            f"{mes.competencia}: soma operações R$ {soma} ≠ "
            f"faturamento_mes R$ {mes.faturamento_mes}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. CNAE: padaria usa 1091102 sem hífen (formato projeto)
# ─────────────────────────────────────────────────────────────────────────────


def test_arquetipo_3_cnae_e_padaria_formato_projeto():
    """CNAE 1091102 (Fabricação de produtos de panificação industrial) com
    7 dígitos sem hífen — formato do projeto (ver tabelas_simples.py:55)."""
    historico = arquetipo_3_misto_5050()
    for mes in historico.meses:
        for op in mes.operacoes:
            assert op.cnae_predominante == "1091102", (
                f"{mes.competencia}: CNAE {op.cnae_predominante} ≠ '1091102'"
            )
            assert len(op.cnae_predominante) == 7
            assert op.cnae_predominante.isdigit()
