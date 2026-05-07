# -*- coding: utf-8 -*-
"""
test_diagnostico_consolidado.py — Testes de invariantes do DiagnosticoConsolidado.

Todos os números vêm do motor rodando (MAX_08).
Testes verificam invariantes algébricos e estruturais — NUNCA hardcodam output do motor.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from datetime import date
from decimal import Decimal

from core.historico_consolidado import gerar_diagnostico_consolidado
from core.motor_tributario import MOTOR_VERSAO
from core.tabelas_simples import ALERTA_90_PERCENT_TETO, TETO_SIMPLES_NACIONAL
from schemas.historico_seis_meses import HistoricoSeisMeses, MesHistorico
from schemas.motor import EmpresaCompradora, EmpresaFornecedora, OperacaoFiscal


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _historico_padaria() -> HistoricoSeisMeses:
    """Arquétipo A — Padaria B2C, SIMPLES, Anexo I, RBT12 crescente."""
    fornecedora = EmpresaFornecedora(
        cnpj="54657895000160",
        razao_social="Padaria Sao Joao Ltda",
        regime="SIMPLES",
        cnae_principal="1091101",
        uf_origem="SP",
        faturamento_12m=Decimal("1200000.00"),
        folha_salarios_12m=Decimal("180000.00"),
    )
    compradora = EmpresaCompradora(tipo="B2C_CONSUMIDOR_FINAL", percentual_b2b=Decimal("0"), uf_destino="SP")
    meses_data = [
        (Decimal("1100000"), Decimal("165000"), Decimal("13750"), Decimal("90000")),
        (Decimal("1120000"), Decimal("168000"), Decimal("14000"), Decimal("92000")),
        (Decimal("1140000"), Decimal("171000"), Decimal("14250"), Decimal("94000")),
        (Decimal("1160000"), Decimal("174000"), Decimal("14500"), Decimal("96000")),
        (Decimal("1180000"), Decimal("177000"), Decimal("14750"), Decimal("98000")),
        (Decimal("1200000"), Decimal("180000"), Decimal("15000"), Decimal("100000")),
    ]
    meses = [
        MesHistorico(
            competencia=f"2026-{i + 1:02d}",
            rbt12_no_mes=rbt12,
            folha_mes=folha_mes,
            folha_12m_no_mes=folha12,
            operacoes=[OperacaoFiscal(
                data_emissao=date(2026, i + 1, 15),
                valor_operacao=val,
                ncm_nbs="19059090",
                forma_recebimento="PIX_DIRETO",
            )],
        )
        for i, (rbt12, folha12, folha_mes, val) in enumerate(meses_data)
    ]
    return HistoricoSeisMeses(fornecedora_base=fornecedora, compradora_padrao=compradora, meses=meses)


def _historico_sublimite() -> HistoricoSeisMeses:
    """Arquétipo E — Sublimite, próximo do teto, aciona TETO_90PCT."""
    fornecedora = EmpresaFornecedora(
        cnpj="55666777000181",
        razao_social="Industria Metalurgica Borges ME",
        regime="SIMPLES",
        cnae_principal="2511000",
        uf_origem="SP",
        faturamento_12m=Decimal("4500000.00"),
        folha_salarios_12m=Decimal("540000.00"),
    )
    compradora = EmpresaCompradora(tipo="B2B_CONTRIBUINTE", percentual_b2b=Decimal("70"), uf_destino="SP")
    meses_data = [
        (Decimal("4100000"), Decimal("492000"), Decimal("41000"), Decimal("340000")),
        (Decimal("4200000"), Decimal("504000"), Decimal("42000"), Decimal("350000")),
        (Decimal("4250000"), Decimal("510000"), Decimal("42500"), Decimal("354000")),
        (Decimal("4320000"), Decimal("518400"), Decimal("43200"), Decimal("360000")),
        (Decimal("4400000"), Decimal("528000"), Decimal("44000"), Decimal("367000")),
        (Decimal("4500000"), Decimal("540000"), Decimal("45000"), Decimal("375000")),
    ]
    meses = [
        MesHistorico(
            competencia=f"2026-{i + 1:02d}",
            rbt12_no_mes=rbt12,
            folha_mes=folha_mes,
            folha_12m_no_mes=folha12,
            operacoes=[OperacaoFiscal(
                data_emissao=date(2026, i + 1, 15),
                valor_operacao=val,
                ncm_nbs="73261000",
                forma_recebimento="BOLETO",
            )],
        )
        for i, (rbt12, folha12, folha_mes, val) in enumerate(meses_data)
    ]
    return HistoricoSeisMeses(fornecedora_base=fornecedora, compradora_padrao=compradora, meses=meses)


# ── Invariantes estruturais ───────────────────────────────────────────────────

class TestDiagnosticoEstrutura:
    def test_seis_resumos_mensais(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        assert len(d.resumos_mensais) == 6

    def test_periodo_formato_correto(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        assert d.periodo == "2026-01 a 2026-06"

    def test_regime_preservado(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        assert d.regime == "SIMPLES"

    def test_motor_versao_atual(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        assert d.motor_versao == MOTOR_VERSAO

    def test_hash_nao_vazio(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        assert len(d.hash_reprodutibilidade) == 64  # SHA-256 hex = 64 chars

    def test_cnpj_anonimizado_16_chars(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        assert len(d.cnpj_anonimizado) == 16

    def test_gerado_em_nao_vazio(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        assert len(d.gerado_em) > 10

    def test_competencias_ordenadas(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        comps = [r.competencia for r in d.resumos_mensais]
        assert comps == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]


# ── Invariantes algébricos ────────────────────────────────────────────────────

class TestDiagnosticoAlgebra:
    def test_carga_total_igual_soma_mensais(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        soma = sum(r.carga_tributaria_mes for r in d.resumos_mensais)
        assert d.carga_total_periodo == soma.quantize(Decimal("0.01"))

    def test_carga_media_igual_total_dividido_seis(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        esperado = (d.carga_total_periodo / Decimal("6")).quantize(Decimal("0.01"))
        assert d.carga_media_mensal == esperado

    def test_aliquota_min_lte_consolidada_lte_max(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        assert d.aliquota_efetiva_min <= d.aliquota_efetiva_consolidada
        assert d.aliquota_efetiva_consolidada <= d.aliquota_efetiva_max

    def test_aliquota_min_igual_menor_mensal(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        assert d.aliquota_efetiva_min == min(r.aliquota_efetiva_mes for r in d.resumos_mensais)

    def test_aliquota_max_igual_maior_mensal(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        assert d.aliquota_efetiva_max == max(r.aliquota_efetiva_mes for r in d.resumos_mensais)

    def test_aliquota_consolidada_e_media_ponderada(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        total_imposto = sum(r.carga_tributaria_mes for r in d.resumos_mensais)
        total_fat = sum(r.valor_operacoes_mes for r in d.resumos_mensais)
        esperado = (total_imposto / total_fat).quantize(Decimal("0.000001"))
        assert d.aliquota_efetiva_consolidada == esperado

    def test_meses_optout_entre_0_e_6(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        assert 0 <= d.meses_recomendando_optout <= 6

    def test_indice_confianca_entre_0_e_10(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        assert 0 <= d.indice_confianca <= 10

    def test_cargas_mensais_positivas(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        for r in d.resumos_mensais:
            assert r.carga_tributaria_mes > Decimal("0")

    def test_aliquotas_mensais_positivas(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        for r in d.resumos_mensais:
            assert r.aliquota_efetiva_mes > Decimal("0")


# ── Reprodutibilidade do hash ─────────────────────────────────────────────────

class TestHash:
    def test_hash_determinístico(self):
        """Mesmo input → mesmo hash. Garante reprodutibilidade (MAX_08)."""
        h = _historico_padaria()
        d1 = gerar_diagnostico_consolidado(h)
        d2 = gerar_diagnostico_consolidado(h)
        assert d1.hash_reprodutibilidade == d2.hash_reprodutibilidade

    def test_hash_diferente_para_inputs_diferentes(self):
        d_a = gerar_diagnostico_consolidado(_historico_padaria())
        d_e = gerar_diagnostico_consolidado(_historico_sublimite())
        assert d_a.hash_reprodutibilidade != d_e.hash_reprodutibilidade


# ── Alertas de transição ──────────────────────────────────────────────────────

class TestAlertasTransicao:
    def test_teto_90pct_dispara_quando_rbt12_ge_limiar(self):
        d = gerar_diagnostico_consolidado(_historico_sublimite())
        alertas_teto = [a for a in d.alertas_transicao if a.tipo == "TETO_90PCT"]
        # Meses com rbt12 >= ALERTA_90_PERCENT_TETO (4320000): meses 4, 5, 6
        rbt12_acima = [m for m in _historico_sublimite().meses if m.rbt12_no_mes >= ALERTA_90_PERCENT_TETO]
        assert len(alertas_teto) == len(rbt12_acima)

    def test_teto_90pct_nao_dispara_para_rbt12_baixo(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        alertas_teto = [a for a in d.alertas_transicao if a.tipo == "TETO_90PCT"]
        assert alertas_teto == []

    def test_alerta_teto_amparo_legal_correto(self):
        d = gerar_diagnostico_consolidado(_historico_sublimite())
        alertas_teto = [a for a in d.alertas_transicao if a.tipo == "TETO_90PCT"]
        assert len(alertas_teto) > 0
        for a in alertas_teto:
            assert "LC 123/2006" in a.amparo_legal
            assert "Art. 3º" in a.amparo_legal


# ── Recomendacao_regime ───────────────────────────────────────────────────────

class TestRecomendacaoRegime:
    def test_manter_simples_quando_zero_meses_optout(self):
        d = gerar_diagnostico_consolidado(_historico_padaria())
        if d.meses_recomendando_optout <= 2:
            assert d.recomendacao_regime == "MANTER_SIMPLES"

    def test_opt_out_forte_quando_5_ou_mais_meses(self):
        """Se o motor recomendar opt-out em ≥5 meses, regime = OPT_OUT_FORTE."""
        d = gerar_diagnostico_consolidado(_historico_padaria())
        if d.meses_recomendando_optout >= 5:
            assert d.recomendacao_regime == "OPT_OUT_FORTE"

    def test_logica_recomendacao_consistente(self):
        """meses_recomendando_optout → recomendacao_regime é determinístico."""
        d = gerar_diagnostico_consolidado(_historico_padaria())
        n = d.meses_recomendando_optout
        if n >= 5:
            assert d.recomendacao_regime == "OPT_OUT_FORTE"
        elif n >= 4:
            assert d.recomendacao_regime == "AVALIAR_OPT_OUT"
        elif n <= 2:
            assert d.recomendacao_regime == "MANTER_SIMPLES"
        else:
            assert d.recomendacao_regime == "INCONCLUSIVO"


# ── Método estático no motor ──────────────────────────────────────────────────

class TestMotorStaticMethod:
    def test_gerar_via_motor_static_method(self):
        """MotorReformaTributaria.gerar_diagnostico_consolidado delega corretamente."""
        from core.motor_tributario import MotorReformaTributaria
        h = _historico_padaria()
        d = MotorReformaTributaria.gerar_diagnostico_consolidado(h)
        assert d.regime == "SIMPLES"
        assert len(d.resumos_mensais) == 6

    def test_resultados_identicos_entre_static_e_direto(self):
        h = _historico_padaria()
        from core.motor_tributario import MotorReformaTributaria
        d1 = gerar_diagnostico_consolidado(h)
        d2 = MotorReformaTributaria.gerar_diagnostico_consolidado(h)
        assert d1.hash_reprodutibilidade == d2.hash_reprodutibilidade
        assert d1.carga_total_periodo == d2.carga_total_periodo
