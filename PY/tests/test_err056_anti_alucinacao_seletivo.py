# -*- coding: utf-8 -*-
"""
test_err056_anti_alucinacao_seletivo.py — Regressão MAX_07.

ERR-056: a constante NCMS_MONOFASICAS_BLOQUEADAS atribuía cigarros
(2402-2403) e bebidas alcoólicas (2203-2208) ao Art. 172 II/III da
LC 214/2025 — citação INVENTADA. Art. 172 lista TAXATIVAMENTE apenas
combustíveis. Cigarros e bebidas vão pro Imposto Seletivo
(LC 214/2025 Arts. 409 § 1º + 410) — tributo diferente, mesmo gate.

Validação Escrivão (30/04/2026) com 5+ fontes secundárias autoritativas
(Fazenda RJ, Câmara, Jusbrasil, IBET, Mayer Brown, Modelo Inicial).

Mesma classe de erro do ERR-017.b (citação inventada SC COSIT 174/2019)
— se permitida em produção, contamina trilha de auditoria fiscal.

Este teste BLOQUEIA o redo. Quem editar a constante voltando à citação
errada quebra o teste.
"""

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas.motor import NCMS_MONOFASICAS_BLOQUEADAS, OperacaoFiscal


def _operacao_com_ncm(ncm: str) -> OperacaoFiscal:
    return OperacaoFiscal(
        data_emissao=date(2026, 6, 1),
        valor_operacao=Decimal("1000.00"),
        ncm_nbs=ncm,
        forma_recebimento="PIX_DIRETO",
    )


# ── NCMs do conjunto bloqueado seguem rejeitados ──────────────────────────────

@pytest.mark.parametrize("ncm", [
    "27109999",  # combustível (capítulo 2710)
    "24021000",  # charuto (Imposto Seletivo)
    "24031100",  # fumo (Imposto Seletivo)
    "22030000",  # cerveja (Imposto Seletivo)
    "22041000",  # vinho (Imposto Seletivo)
    "22051000",  # vermute (Imposto Seletivo)
    "22060000",  # outras fermentadas
    "22071000",  # álcool ≥ 80%
    "22082000",  # destilados
])
def test_ncm_bloqueado_levanta_value_error(ncm: str):
    """Cada NCM dos capítulos bloqueados continua rejeitado pelo Pydantic."""
    with pytest.raises(Exception):
        _operacao_com_ncm(ncm)


# ── Citações por categoria — Art. 172 só pra combustível, Art. 409 pro resto ──

def test_combustivel_2710_cita_artigo_172_e_nao_409():
    """Combustíveis vão pro regime monofásico (Art. 172) — não pro Seletivo."""
    try:
        _operacao_com_ncm("27109999")
        pytest.fail("Deveria ter levantado erro de NCM bloqueado.")
    except Exception as e:
        msg = str(e)
        assert "Art. 172" in msg, f"Mensagem deveria citar Art. 172, veio: {msg}"
        assert "monofásico" in msg.lower() or "monofasico" in msg.lower()
        assert "409" not in msg, (
            f"Combustível NÃO vai pro Imposto Seletivo (Art. 409). Mensagem: {msg}"
        )


@pytest.mark.parametrize("ncm", ["24021000", "24031100"])
def test_cigarro_cita_artigo_409_e_nao_172(ncm: str):
    """Cigarros e tabaco vão pro Imposto Seletivo Art. 409 — NÃO pro Art. 172."""
    try:
        _operacao_com_ncm(ncm)
        pytest.fail("Deveria ter levantado erro de NCM bloqueado.")
    except Exception as e:
        msg = str(e)
        assert "409" in msg, (
            f"Cigarro deveria citar Imposto Seletivo Art. 409, veio: {msg}"
        )
        assert "Seletivo" in msg, f"Mensagem deveria citar 'Imposto Seletivo', veio: {msg}"
        # Bloqueio do Art. 172 antigo era citação inventada — não pode voltar.
        assert "Art. 172" not in msg, (
            f"REGRESSÃO ERR-056: cigarro NÃO está no Art. 172 (só combustíveis). "
            f"Mensagem: {msg}"
        )


@pytest.mark.parametrize("ncm", ["22030000", "22041000", "22051000",
                                  "22060000", "22071000", "22082000"])
def test_bebida_alcoolica_cita_artigo_409_e_nao_172(ncm: str):
    """Bebidas alcoólicas vão pro Imposto Seletivo Art. 409 — NÃO pro Art. 172."""
    try:
        _operacao_com_ncm(ncm)
        pytest.fail("Deveria ter levantado erro de NCM bloqueado.")
    except Exception as e:
        msg = str(e)
        assert "409" in msg
        assert "Seletivo" in msg
        assert "Art. 172" not in msg, (
            f"REGRESSÃO ERR-056: bebida alcoólica NÃO está no Art. 172. "
            f"Mensagem: {msg}"
        )


# ── NCM padrão continua aceito — gate não derrubou usuários legítimos ─────────

def test_ncm_padrao_continua_aceito():
    """NCM fora dos capítulos bloqueados continua passando."""
    op = _operacao_com_ncm("84818099")  # válvula industrial — aceito
    assert op.ncm_nbs == "84818099"


# ── Conjunto canônico não pode ser inflado sem decisão arquitetônica ──────────

def test_conjunto_bloqueado_tem_exatamente_9_capitulos():
    """
    Quem adicionar NCM ao conjunto deve passar por análise (categoria + base
    legal). Mudar esse total dispara revisão.

    Atual (validado por Escrivão 30/04/2026):
    - 2710 (combustível, Art. 172)
    - 2402, 2403 (tabaco, Art. 409)
    - 2203, 2204, 2205, 2206, 2207, 2208 (bebidas alcoólicas, Art. 409)
    """
    assert len(NCMS_MONOFASICAS_BLOQUEADAS) == 9
