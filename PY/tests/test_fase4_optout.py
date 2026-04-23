"""
test_fase4_optout.py — TDD Fase 4 (Simulação Opt-Out)
Testa: cenario_simples_puro, cenario_opt_out, calcular_split_payment_impacto, gerar_diagnostico

3 cenários de Sorocaba:
  - Comércio (Anexo I, B2B, fornecedor polo industrial)
  - Serviço TI (Anexo V/III com Fator R, B2B, cliente indústria)
  - Indústria (Anexo II, B2B, grande cliente)

Executar: python -m pytest PY/tests/test_fase4_optout.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from datetime import date
from decimal import Decimal


from core.motor_tributario import (
    EmpresaCompradora,
    EmpresaFornecedora,
    MotorReformaTributaria,
    OperacaoFiscal,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def motor_comercio_b2b(ano: int = 2026) -> MotorReformaTributaria:
    """Comércio varejista Sorocaba — fornecedor do polo industrial."""
    return MotorReformaTributaria(
        EmpresaFornecedora(
            cnpj="11.222.333/0001-81",
            razao_social="Distribuidora Industrial SP Ltda",
            regime="SIMPLES",
            cnae_principal="4711302",
            uf_origem="SP",
            faturamento_12m=Decimal("1800000.00"),
        ),
        EmpresaCompradora(tipo="B2B_CONTRIBUINTE", uf_destino="SP"),
        OperacaoFiscal(
            data_emissao=date(ano, 3, 15),
            valor_operacao=Decimal("50000.00"),
            ncm_nbs="84099190",
            forma_recebimento="PIX_VIA_PSP",
        ),
    )


def motor_servico_ti(ano: int = 2026, folha: str = "140000.00") -> MotorReformaTributaria:
    """Empresa TI Sorocaba — cliente é montadora (Lucro Real)."""
    return MotorReformaTributaria(
        EmpresaFornecedora(
            cnpj="11.222.333/0001-81",
            razao_social="TechSorocaba Sistemas Ltda",
            regime="SIMPLES",
            cnae_principal="6201501",
            uf_origem="SP",
            faturamento_12m=Decimal("500000.00"),
            folha_salarios_12m=Decimal(folha),
        ),
        EmpresaCompradora(tipo="B2B_CONTRIBUINTE", uf_destino="SP", regime="REAL"),
        OperacaoFiscal(
            data_emissao=date(ano, 6, 1),
            valor_operacao=Decimal("20000.00"),
            ncm_nbs="85176290",
            forma_recebimento="PIX_VIA_PSP",
        ),
    )


def motor_industria_b2b(ano: int = 2026) -> MotorReformaTributaria:
    """Fabricante Sorocaba — cliente é grande indústria (Lucro Real)."""
    return MotorReformaTributaria(
        EmpresaFornecedora(
            cnpj="11.222.333/0001-81",
            razao_social="Metalúrgica Sorocaba Ltda",
            regime="SIMPLES",
            cnae_principal="2950600",
            uf_origem="SP",
            faturamento_12m=Decimal("3000000.00"),
        ),
        EmpresaCompradora(tipo="B2B_CONTRIBUINTE", uf_destino="SP", regime="REAL"),
        OperacaoFiscal(
            data_emissao=date(ano, 9, 1),
            valor_operacao=Decimal("100000.00"),
            ncm_nbs="73269090",
            forma_recebimento="PIX_VIA_PSP",
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Cenário Simples Puro
# ─────────────────────────────────────────────────────────────────────────────

class TestCenarioSimplesPuro:

    def test_retorna_dict_com_campos_obrigatorios(self):
        motor = motor_comercio_b2b()
        resultado = motor.cenario_simples_puro()
        campos = ["cenario", "custo_das_por_operacao", "aliquota_efetiva",
                  "credito_gerado_para_comprador", "risco_b2b"]
        for campo in campos:
            assert campo in resultado, f"Campo '{campo}' ausente no cenário"

    def test_cenario_identificado_corretamente(self):
        motor = motor_comercio_b2b()
        assert motor.cenario_simples_puro()["cenario"] == "SIMPLES_PURO"

    def test_risco_b2b_verdadeiro_para_b2b(self):
        motor = motor_comercio_b2b()
        assert motor.cenario_simples_puro()["risco_b2b"] is True

    def test_risco_b2b_falso_para_b2c(self):
        motor = MotorReformaTributaria(
            EmpresaFornecedora(
                cnpj="11.222.333/0001-81", razao_social="Loja X", regime="SIMPLES",
                cnae_principal="4711302", uf_origem="SP",
                faturamento_12m=Decimal("300000.00"),
            ),
            EmpresaCompradora(tipo="B2C_CONSUMIDOR_FINAL", uf_destino="SP"),
            OperacaoFiscal(
                data_emissao=date(2026, 1, 1), valor_operacao=Decimal("1000.00"),
                ncm_nbs="84099190",
            ),
        )
        assert motor.cenario_simples_puro()["risco_b2b"] is False

    def test_custo_das_e_decimal_string(self):
        """custo_das_por_operacao deve ser string de Decimal (não float)."""
        motor = motor_comercio_b2b()
        custo = motor.cenario_simples_puro()["custo_das_por_operacao"]
        # Deve ser conversível para Decimal sem perda
        assert Decimal(custo) > Decimal("0")


# ─────────────────────────────────────────────────────────────────────────────
# Cenário Opt-Out
# ─────────────────────────────────────────────────────────────────────────────

class TestCenarioOptOut:

    def test_retorna_dict_com_campos_obrigatorios(self):
        motor = motor_comercio_b2b()
        resultado = motor.cenario_opt_out()
        campos = ["cenario", "custo_das_por_operacao", "iva_recolhido_por_fora",
                  "custo_total", "credito_gerado_para_comprador"]
        for campo in campos:
            assert campo in resultado, f"Campo '{campo}' ausente no opt-out"

    def test_cenario_identificado_corretamente(self):
        motor = motor_comercio_b2b()
        assert motor.cenario_opt_out()["cenario"] == "OPT_OUT"

    def test_opt_out_gera_100_porcento_credito(self):
        """Opt-Out: crédito para comprador = 100% do IVA recolhido."""
        motor = motor_comercio_b2b()
        resultado = motor.cenario_opt_out()
        assert resultado["percentual_credito_nf"] == "100%"

    def test_iva_por_fora_positivo(self):
        motor = motor_comercio_b2b()
        iva = Decimal(motor.cenario_opt_out()["iva_recolhido_por_fora"])
        assert iva > Decimal("0")

    def test_risco_b2b_falso_no_opt_out(self):
        """Opt-Out resolve o problema de crédito B2B."""
        motor = motor_comercio_b2b()
        assert motor.cenario_opt_out()["risco_b2b"] is False

    def test_servico_ti_fator_r_alto_opt_out(self):
        """TI com Fator R alto (Anexo III) — Opt-Out ainda funciona."""
        motor = motor_servico_ti(folha="150000.00")
        resultado = motor.cenario_opt_out()
        assert resultado["cenario"] == "OPT_OUT"
        assert resultado["risco_b2b"] is False

    def test_industria_b2b_opt_out(self):
        """Indústria (Anexo II) — Opt-Out correto."""
        motor = motor_industria_b2b()
        resultado = motor.cenario_opt_out()
        assert resultado["cenario"] == "OPT_OUT"
        assert Decimal(resultado["iva_recolhido_por_fora"]) > Decimal("0")


# ─────────────────────────────────────────────────────────────────────────────
# Split Payment
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitPayment:

    def test_split_inativo_em_2026(self):
        """Split Payment ainda não existe em 2026."""
        motor = motor_comercio_b2b(ano=2026)
        resultado = motor.split_payment_impacto
        assert resultado["ativo"] is False

    def test_split_ativo_em_2027_com_pix(self):
        """Split Payment ativo a partir de Jan/2027 para PIX/Boleto."""
        motor = motor_comercio_b2b(ano=2027)
        resultado = motor.split_payment_impacto
        assert resultado["ativo"] is True
        assert Decimal(resultado["retencao_imediata"]) > Decimal("0")

    def test_split_inativo_em_2027_com_dinheiro(self):
        """Pagamento em DINHEIRO escapa do Split Payment (2027)."""
        motor = MotorReformaTributaria(
            EmpresaFornecedora(
                cnpj="11.222.333/0001-81", razao_social="Comercio X", regime="SIMPLES",
                cnae_principal="4711302", uf_origem="SP",
                faturamento_12m=Decimal("500000.00"),
            ),
            EmpresaCompradora(tipo="B2B_CONTRIBUINTE", uf_destino="SP"),
            OperacaoFiscal(
                data_emissao=date(2027, 3, 1), valor_operacao=Decimal("10000.00"),
                ncm_nbs="84099190", forma_recebimento="DINHEIRO",
            ),
        )
        resultado = motor.split_payment_impacto
        assert resultado["ativo"] is False

    def test_retencao_calculada_corretamente(self):
        """
        2027: CBS 8,8% + IBS 0,1% = 8,9% (Split Payment dinâmico)
        R$ 50.000 × 8,9% = R$ 4.450,00
        LC 214/2025, Art. 344 + Art. 353 (CBS substitui PIS/COFINS em 2027)
        """
        motor = motor_comercio_b2b(ano=2027)
        resultado = motor.split_payment_impacto
        retencao = Decimal(resultado["retencao_imediata"])
        esperado = Decimal("50000.00") * (Decimal("0.088") + Decimal("0.001"))
        assert abs(retencao - esperado) <= Decimal("0.01")


# ─────────────────────────────────────────────────────────────────────────────
# Diagnóstico Completo
# ─────────────────────────────────────────────────────────────────────────────

class TestGerarDiagnostico:

    def test_diagnostico_retorna_dict(self):
        motor = motor_comercio_b2b()
        diagnostico = motor.gerar_diagnostico()
        assert isinstance(diagnostico, dict)

    def test_diagnostico_tem_campos_obrigatorios(self):
        motor = motor_comercio_b2b()
        diag = motor.gerar_diagnostico()
        for campo in ["versao_schema", "versao_lei", "empresa", "aliquotas",
                      "cenarios", "alertas", "split_payment", "meta"]:
            assert campo in diag, f"Campo '{campo}' ausente no diagnóstico"

    def test_diagnostico_versao_lei_correta(self):
        motor = motor_comercio_b2b()
        diag = motor.gerar_diagnostico()
        assert diag["versao_lei"] == "LC123_2006_LC214_2025"

    def test_diagnostico_nao_contem_cnpj_claro(self):
        """LGPD: CNPJ não deve aparecer no diagnóstico."""
        motor = motor_comercio_b2b()
        diag = motor.gerar_diagnostico()
        diag_str = str(diag)
        assert "11222333000181" not in diag_str
        assert "11.222.333/0001-81" not in diag_str

    def test_diagnostico_nao_contem_razao_social(self):
        """LGPD: Razão social não deve aparecer no diagnóstico."""
        motor = motor_comercio_b2b()
        diag = motor.gerar_diagnostico()
        assert "Distribuidora Industrial SP" not in str(diag)

    def test_diagnostico_retorna_dict_valido(self):
        """gerar_diagnostico() retorna dict com chaves obrigatórias."""
        motor = motor_comercio_b2b()
        diag = motor.gerar_diagnostico()
        assert isinstance(diag, dict)
        assert "alertas" in diag
        assert "trilha_auditoria" in diag

    def test_alertas_para_b2b_simples(self):
        """Empresa Simples + B2B deve ter alerta ALTO de crédito insuficiente."""
        motor = motor_comercio_b2b()
        diag = motor.gerar_diagnostico()
        alertas = diag["alertas"]
        codigos = [a["codigo"] for a in alertas]
        assert "RISCO_B2B_CREDITO_INSUFICIENTE" in codigos

    def test_recomendacao_opt_out_para_b2b(self):
        """Diagnóstico B2B deve recomendar Opt-Out."""
        motor = motor_comercio_b2b()
        diag = motor.gerar_diagnostico()
        assert "OPT_OUT" in diag["cenarios"]["recomendacao"]

    def test_diagnostico_industria_b2b(self):
        """Cenário indústria Sorocaba — diagnóstico completo sem erros."""
        motor = motor_industria_b2b()
        diag = motor.gerar_diagnostico()
        assert diag["empresa"]["anexo_simples"] == "II"
        assert diag["cenarios"]["opt_out"]["cenario"] == "OPT_OUT"

    def test_diagnostico_servico_ti_fator_r_alto(self):
        """TI com Fator R alto → Anexo III no diagnóstico."""
        motor = motor_servico_ti(folha="150000.00")
        diag = motor.gerar_diagnostico()
        assert diag["empresa"]["anexo_simples"] == "III"

    def test_diagnostico_servico_ti_fator_r_baixo(self):
        """TI com Fator R baixo → Anexo V no diagnóstico."""
        motor = motor_servico_ti(folha="100000.00")
        diag = motor.gerar_diagnostico()
        assert diag["empresa"]["anexo_simples"] == "V"

    def test_diagnostico_aviso_validar_profissional(self):
        """Todo diagnóstico deve ter aviso de validação profissional."""
        motor = motor_comercio_b2b()
        diag = motor.gerar_diagnostico()
        assert diag["meta"]["validar_com_profissional"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Bloco A Frente 3.2 — Recomendação Inteligente Opt-Out
# ─────────────────────────────────────────────────────────────────────────────

def _motor_misto(pct_b2b: str, rbt12: str = "1800000.00") -> MotorReformaTributaria:
    """
    Empresa MISTA com percentual_b2b variável — usado para testar
    a matriz de decisão de _gerar_recomendacao_opt_out.
    """
    return MotorReformaTributaria(
        EmpresaFornecedora(
            cnpj="11.222.333/0001-81",
            razao_social="Mista Sorocaba Ltda",
            regime="SIMPLES",
            cnae_principal="4711302",
            uf_origem="SP",
            faturamento_12m=Decimal(rbt12),
        ),
        EmpresaCompradora(
            tipo="MISTO",
            percentual_b2b=Decimal(pct_b2b),
            uf_destino="SP",
        ),
        OperacaoFiscal(
            data_emissao=date(2026, 6, 15),
            valor_operacao=Decimal("50000.00"),
            ncm_nbs="84099190",
            forma_recebimento="PIX_VIA_PSP",
        ),
    )


class TestRecomendacaoInteligenteOptOut:
    """
    Matriz de decisão (LC 214/2025 Arts. 41-44 + Resolução CGSN 183/2025):

      B2B ≥ 70% E disparidade/RBT12 ≤ 5%  → OPT_OUT_FORTE
      B2B ≥ 50% E disparidade/RBT12 ≤ 10% → OPT_OUT_VANTAJOSO
      B2B < 30%                            → MANTER_SIMPLES
      Demais casos                         → ZONA_CINZA
    """

    def test_recomendacao_inteligente_presente_no_diagnostico(self):
        """O bloco 'recomendacao_inteligente' deve existir em cenarios."""
        motor = motor_comercio_b2b()
        diag = motor.gerar_diagnostico()
        assert "recomendacao_inteligente" in diag["cenarios"]
        rec = diag["cenarios"]["recomendacao_inteligente"]
        for campo in ("codigo", "titulo", "justificativa", "amparo_legal"):
            assert campo in rec, f"Campo '{campo}' ausente em recomendacao_inteligente"

    def test_b2b_100_opt_out_forte(self):
        """B2B 100% (tipo=B2B_CONTRIBUINTE) → OPT_OUT_FORTE."""
        motor = motor_comercio_b2b()
        rec = motor._gerar_recomendacao_opt_out()
        assert rec["codigo"] == "OPT_OUT_FORTE"
        assert "FORTEMENTE RECOMENDADO" in rec["titulo"]
        assert "100%" in rec["justificativa"]

    def test_misto_70_b2b_opt_out_forte(self):
        """MISTO com 70% B2B → OPT_OUT_FORTE (≥ 70% threshold)."""
        motor = _motor_misto("70.00")
        rec = motor._gerar_recomendacao_opt_out()
        assert rec["codigo"] == "OPT_OUT_FORTE"
        assert "70%" in rec["justificativa"]

    def test_misto_50_b2b_opt_out_vantajoso(self):
        """MISTO com 50% B2B → OPT_OUT_VANTAJOSO (≥ 50% mas < 70%)."""
        motor = _motor_misto("50.00")
        rec = motor._gerar_recomendacao_opt_out()
        assert rec["codigo"] == "OPT_OUT_VANTAJOSO"
        assert "VANTAJOSO" in rec["titulo"]
        assert "50%" in rec["justificativa"]

    def test_misto_30_b2b_zona_cinza(self):
        """MISTO com 30% B2B → ZONA_CINZA (≥ 30% mas < 50%)."""
        motor = _motor_misto("30.00")
        rec = motor._gerar_recomendacao_opt_out()
        assert rec["codigo"] == "ZONA_CINZA"
        assert "análise individual" in rec["justificativa"].lower() or "analise individual" in rec["justificativa"].lower()

    def test_misto_20_b2b_manter_simples(self):
        """MISTO com 20% B2B → MANTER_SIMPLES (< 30%)."""
        motor = _motor_misto("20.00")
        rec = motor._gerar_recomendacao_opt_out()
        assert rec["codigo"] == "MANTER_SIMPLES"
        assert "SIMPLES PURO" in rec["titulo"]

    def test_b2c_puro_manter_simples(self):
        """B2C puro (tipo=B2C_CONSUMIDOR_FINAL) → MANTER_SIMPLES."""
        motor = MotorReformaTributaria(
            EmpresaFornecedora(
                cnpj="11.222.333/0001-81",
                razao_social="Loja Varejo",
                regime="SIMPLES",
                cnae_principal="4711302",
                uf_origem="SP",
                faturamento_12m=Decimal("300000.00"),
            ),
            EmpresaCompradora(tipo="B2C_CONSUMIDOR_FINAL", uf_destino="SP"),
            OperacaoFiscal(
                data_emissao=date(2026, 1, 1),
                valor_operacao=Decimal("1000.00"),
                ncm_nbs="84099190",
            ),
        )
        rec = motor._gerar_recomendacao_opt_out()
        assert rec["codigo"] == "MANTER_SIMPLES"
        assert "0%" in rec["justificativa"]

    def test_justificativa_contem_valor_financeiro(self):
        """Justificativa deve citar o custo anual em R$ (transparência)."""
        motor = motor_comercio_b2b()
        rec = motor._gerar_recomendacao_opt_out()
        assert "R$" in rec["justificativa"]

    def test_amparo_legal_cita_lc_214(self):
        """MAX_FISCAL_02: toda recomendação deve citar a lei."""
        motor = motor_comercio_b2b()
        rec = motor._gerar_recomendacao_opt_out()
        assert "LC 214/2025" in rec["amparo_legal"]
        assert "Arts. 41-44" in rec["amparo_legal"]

    def test_compat_retro_string_recomendacao_existe(self):
        """Compat: chave 'recomendacao' string curta ainda existe."""
        motor = motor_comercio_b2b()
        diag = motor.gerar_diagnostico()
        assert "recomendacao" in diag["cenarios"]
        assert isinstance(diag["cenarios"]["recomendacao"], str)

    def test_b2b_puro_string_compat_menciona_opt_out(self):
        """B2B 100% → string compat deve mencionar OPT_OUT."""
        motor = motor_comercio_b2b()
        diag = motor.gerar_diagnostico()
        assert "OPT_OUT" in diag["cenarios"]["recomendacao"]

    def test_b2c_puro_string_compat_menciona_simples(self):
        """B2C puro → string compat deve mencionar SIMPLES."""
        motor = MotorReformaTributaria(
            EmpresaFornecedora(
                cnpj="11.222.333/0001-81",
                razao_social="Loja B2C",
                regime="SIMPLES",
                cnae_principal="4711302",
                uf_origem="SP",
                faturamento_12m=Decimal("300000.00"),
            ),
            EmpresaCompradora(tipo="B2C_CONSUMIDOR_FINAL", uf_destino="SP"),
            OperacaoFiscal(
                data_emissao=date(2026, 1, 1),
                valor_operacao=Decimal("1000.00"),
                ncm_nbs="84099190",
            ),
        )
        diag = motor.gerar_diagnostico()
        assert "SIMPLES" in diag["cenarios"]["recomendacao"]
