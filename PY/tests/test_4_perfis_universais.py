# -*- coding: utf-8 -*-
"""
test_4_perfis_universais.py — Trava o motor contra os 4 perfis-chave de
empresa que o escritório atende. Garante que NENHUM perfil cai na recomendação
errada por causa de bug de hardcoded ou matriz simplista.

Os 4 perfis cobrem o espaço:
  - Indústria (90% B2B) → OPT_OUT_FORTE ou CONDICIONAL
  - Contabilidade/serviços profissionais (85% B2B) → OPT_OUT_FORTE ou CONDICIONAL
  - Varejo (30% B2B) → ZONA_CINZA ou MANTER_SIMPLES
  - Saúde PF/varejo puro (10% B2B) → MANTER_SIMPLES

Plus: rails fiscal — formato BR sempre, Decimal sempre, sem float.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from motor_tributario import (  # noqa: E402
    EmpresaCompradora,
    EmpresaFornecedora,
    MotorReformaTributaria,
    OperacaoFiscal,
    _fmt_brl,
)
from tabelas_simples import estimar_perfil_b2b  # noqa: E402


CNPJ_VALIDO = "54657895000160"


def _rodar_motor(cnae: str, rbt12: str, anexo_hint: str = None):
    """Helper: monta empresa + comprador (B2B inferido por CNAE) + roda diagnóstico."""
    pct = estimar_perfil_b2b(cnae)
    tipo = "B2B_CONTRIBUINTE" if pct >= 90 else ("B2C_CONSUMIDOR_FINAL" if pct <= 10 else "MISTO")
    f = EmpresaFornecedora(
        cnpj=CNPJ_VALIDO,
        razao_social="EMPRESA TESTE",
        regime="SIMPLES",
        cnae_principal=cnae,
        uf_origem="SP",
        faturamento_12m=Decimal(rbt12),
        folha_salarios_12m=Decimal("100000"),
        anexo_simples=anexo_hint,
    )
    c = EmpresaCompradora(tipo=tipo, uf_destino="SP", percentual_b2b=Decimal(str(pct)))
    o = OperacaoFiscal(
        data_emissao=date(2026, 1, 15),
        valor_operacao=Decimal(rbt12) / 12,
        ncm_nbs="00000000",
    )
    return MotorReformaTributaria(fornecedora=f, compradora=c, operacao=o).gerar_diagnostico()


# ── _fmt_brl helper ─────────────────────────────────────────────────────────


class TestFmtBrl:
    def test_milhar_com_ponto_decimal_com_virgula(self):
        assert _fmt_brl(Decimal("30156.48")) == "R$ 30.156,48"

    def test_milhao(self):
        assert _fmt_brl(Decimal("1234567.89")) == "R$ 1.234.567,89"

    def test_centena_pequena(self):
        assert _fmt_brl(Decimal("99.50")) == "R$ 99,50"

    def test_zero(self):
        assert _fmt_brl(Decimal("0")) == "R$ 0,00"

    def test_negativo(self):
        assert _fmt_brl(Decimal("-1500.25")) == "R$ -1.500,25"

    def test_aceita_str(self):
        assert _fmt_brl("5000") == "R$ 5.000,00"

    def test_aceita_float_robusto(self):
        # Mesmo recebendo float, normaliza via Decimal(str())
        assert _fmt_brl(1234.56) == "R$ 1.234,56"

    def test_none_retorna_zero(self):
        assert _fmt_brl(None) == "R$ 0,00"

    def test_invalido_retorna_zero(self):
        assert _fmt_brl("abc") == "R$ 0,00"


# ── Perfil 1: Indústria (90% B2B) ───────────────────────────────────────────


class TestPerfilIndustria:
    """Indústria metalúrgica — CNAE 25xx → 90% B2B."""

    def test_inferencia_b2b_correta(self):
        assert estimar_perfil_b2b("2539001") == 90

    def test_diagnostico_recomenda_opt_out(self):
        diag = _rodar_motor("2539001", "1500000")
        rec = diag["cenarios"]["recomendacao_inteligente"]
        # Indústria com 90% B2B deve cair em algum OPT_OUT
        assert rec["codigo"].startswith("OPT_OUT_"), \
            f"Indústria 90% B2B deveria recomendar OPT_OUT, veio: {rec['codigo']}"

    def test_percentual_b2b_no_dict(self):
        diag = _rodar_motor("2539001", "1500000")
        assert diag["cenarios"]["percentual_b2b"] == "100"  # B2B_CONTRIBUINTE → 100


# ── Perfil 2: Contabilidade (85% B2B) ───────────────────────────────────────


class TestPerfilContabilidade:
    """Contabilidade — CNAE 6920 → 85% B2B (caso real do Escritório Moreira)."""

    def test_inferencia_b2b_correta(self):
        assert estimar_perfil_b2b("6920100") == 85

    def test_diagnostico_recomenda_opt_out(self):
        diag = _rodar_motor("6920100", "1200000")
        rec = diag["cenarios"]["recomendacao_inteligente"]
        # Contabilidade 85% B2B → OPT_OUT (forte ou condicional, depende do custo)
        assert rec["codigo"].startswith("OPT_OUT_"), \
            f"Contabilidade 85% B2B deveria recomendar OPT_OUT, veio: {rec['codigo']}"

    def test_pct_b2b_correto_no_dict(self):
        diag = _rodar_motor("6920100", "1200000")
        # Tipo MISTO → percentual_b2b = 85
        assert diag["cenarios"]["percentual_b2b"] == "85"


# ── Perfil 3: Varejo (30% B2B) ──────────────────────────────────────────────


class TestPerfilVarejo:
    """Comércio varejista — CNAE 47xx → 30% B2B."""

    def test_inferencia_b2b_correta(self):
        assert estimar_perfil_b2b("4757100") == 30

    def test_diagnostico_zona_cinza_ou_manter(self):
        diag = _rodar_motor("4757100", "1500000")
        rec = diag["cenarios"]["recomendacao_inteligente"]
        # Varejo 30% B2B: zona cinza (entre 30 e 50)
        assert rec["codigo"] in ("ZONA_CINZA", "MANTER_SIMPLES"), \
            f"Varejo 30% B2B não deve recomendar OPT_OUT, veio: {rec['codigo']}"


# ── Perfil 4: Saúde PF (10% B2B) ─────────────────────────────────────────────


class TestPerfilSaudePF:
    """Saúde — CNAE 86xx → 20% B2B (clínicas atendem PF predominantemente)."""

    def test_inferencia_b2b_baixa(self):
        assert estimar_perfil_b2b("8610101") == 20

    def test_diagnostico_zona_cinza_ou_manter(self):
        diag = _rodar_motor("8610101", "1200000")
        rec = diag["cenarios"]["recomendacao_inteligente"]
        # 20% B2B → ZONA_CINZA ou MANTER_SIMPLES, nunca OPT_OUT
        assert rec["codigo"] in ("ZONA_CINZA", "MANTER_SIMPLES"), \
            f"Saúde 20% B2B não deve recomendar OPT_OUT, veio: {rec['codigo']}"


# ── Justificativas usam formato BR ──────────────────────────────────────────


class TestJustificativaFormatoBr:
    """A justificativa NUNCA pode ter formato US (R$ X,XXX.YY)."""

    def test_industria_justificativa_formato_br(self):
        diag = _rodar_motor("2539001", "1500000")
        justif = diag["cenarios"]["recomendacao_inteligente"]["justificativa"]
        # Não deve ter "R$ X,XXX." (formato US — vírgula separador, ponto decimal)
        # Pattern típico US: "R$ 30,156.48"
        import re
        match_us = re.search(r"R\$ \d{1,3},\d{3}\.\d{2}", justif)
        assert match_us is None, f"Formato US encontrado: {match_us.group()}"

    def test_contabilidade_justificativa_formato_br(self):
        diag = _rodar_motor("6920100", "1200000")
        justif = diag["cenarios"]["recomendacao_inteligente"]["justificativa"]
        import re
        match_us = re.search(r"R\$ \d{1,3},\d{3}\.\d{2}", justif)
        assert match_us is None, f"Formato US encontrado: {match_us.group()}"

    def test_varejo_justificativa_formato_br(self):
        diag = _rodar_motor("4757100", "1500000")
        justif = diag["cenarios"]["recomendacao_inteligente"]["justificativa"]
        import re
        match_us = re.search(r"R\$ \d{1,3},\d{3}\.\d{2}", justif)
        assert match_us is None, f"Formato US encontrado: {match_us.group()}"


# ── Invariante DAS único ───────────────────────────────────────────────────


class TestInvarianteDasUnicoMotor:
    """
    O DAS calculado pelo motor (cenario_simples_puro.custo_das_por_operacao)
    deve ser CONSISTENTE com aliquota_efetiva × valor_operacao.

    Garantia matemática: contador não pode ver 2 valores diferentes na mesma página.
    """

    def test_simples_puro_custo_bate_com_aliq_x_valor(self):
        diag = _rodar_motor("2539001", "1500000")
        aliq = Decimal(diag["aliquotas"]["efetiva_das_total"])
        valor_op = Decimal("1500000") / 12  # RPA mensal
        custo_simples = Decimal(diag["cenarios"]["simples_puro"]["custo_das_por_operacao"])
        # Tolerância de 1 centavo por arredondamento
        diff = abs(custo_simples - (aliq * valor_op).quantize(Decimal("0.01")))
        assert diff <= Decimal("0.01"), \
            f"DAS Simples Puro ({custo_simples}) não bate com aliq × valor ({aliq * valor_op})"


# ── Threshold de custo absoluto (matriz refinada) ──────────────────────────


class TestThresholdCustoAbsoluto:
    """
    Quando o custo extra do Opt-Out passa de R$ 6k/ano (R$ 500/mês) e o B2B é
    alto, a recomendação muda de OPT_OUT_FORTE para OPT_OUT_CONDICIONAL,
    avisando que o custo sai do caixa enquanto o crédito vai pro cliente.
    """

    def test_alto_custo_alto_b2b_vira_condicional(self):
        # Indústria grande com receita alta — disparidade absoluta tende a ser alta
        diag = _rodar_motor("2539001", "4500000")
        rec = diag["cenarios"]["recomendacao_inteligente"]
        disparidade = abs(Decimal(diag["cenarios"]["disparidade_anual_estimada"]))
        if disparidade > Decimal("6000"):
            # Custo alto absoluto → deve ser CONDICIONAL (não FORTE)
            assert rec["codigo"] in ("OPT_OUT_CONDICIONAL", "OPT_OUT_VANTAJOSO", "ZONA_CINZA"), \
                f"Custo alto ({disparidade}) deveria ser CONDICIONAL, veio: {rec['codigo']}"

    def test_baixo_custo_alto_b2b_continua_forte(self):
        # Empresa pequena, custo baixo → OPT_OUT_FORTE continua válido
        diag = _rodar_motor("2539001", "180000")
        rec = diag["cenarios"]["recomendacao_inteligente"]
        disparidade = abs(Decimal(diag["cenarios"]["disparidade_anual_estimada"]))
        if disparidade <= Decimal("6000"):
            assert rec["codigo"] == "OPT_OUT_FORTE", \
                f"Custo baixo ({disparidade}) com 90% B2B deveria ser FORTE, veio: {rec['codigo']}"
