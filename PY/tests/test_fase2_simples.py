"""
test_fase2_simples.py — TDD Fase 2 (Núcleo Simples Nacional)
Testa: calcular_rbt12, calcular_fator_r, determinar_anexo, calcular_aliquota_efetiva

Critério de congelamento: Diferença máxima de R$ 0,01 vs. cálculo manual SRF.
Executar: python -m pytest PY/tests/test_fase2_simples.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from decimal import Decimal
from datetime import date

from core.motor_tributario import (
    EmpresaFornecedora,
    EmpresaCompradora,
    OperacaoFiscal,
    MotorReformaTributaria,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures reutilizáveis
# ─────────────────────────────────────────────────────────────────────────────

def make_operacao(ano: int = 2026, valor: str = "10000.00") -> OperacaoFiscal:
    return OperacaoFiscal(
        data_emissao=date(ano, 6, 1),
        valor_operacao=Decimal(valor),
        ncm_nbs="84099190",
        forma_recebimento="PIX_BOLETO",
    )


def make_motor(
    rbt12: str,
    cnae: str = "4711302",
    regime: str = "SIMPLES",
    folha: str = None,
    tipo_comprador: str = "B2B_CONTRIBUINTE",
    uf: str = "SP",
    ano: int = 2026,
) -> MotorReformaTributaria:
    fornecedora = EmpresaFornecedora(
        cnpj="11.222.333/0001-81",
        razao_social="Empresa Teste Ltda",
        regime=regime,
        cnae_principal=cnae,
        uf_origem=uf,
        faturamento_12m=Decimal(rbt12),
        folha_salarios_12m=Decimal(folha) if folha else None,
    )
    compradora = EmpresaCompradora(
        tipo=tipo_comprador,
        uf_destino="SP",
    )
    operacao = make_operacao(ano=ano)
    return MotorReformaTributaria(fornecedora, compradora, operacao)


# ─────────────────────────────────────────────────────────────────────────────
# RBT12
# ─────────────────────────────────────────────────────────────────────────────

class TestCalcularRBT12:

    def test_rbt12_retorna_decimal(self):
        motor = make_motor("500000.00")
        resultado = motor.rbt12
        assert isinstance(resultado, Decimal)

    def test_rbt12_valor_correto(self):
        motor = make_motor("1500000.00")
        assert motor.rbt12 == Decimal("1500000.00")

    def test_rbt12_arredondamento_dois_decimais(self):
        motor = make_motor("1500000.555")
        rbt12 = motor.rbt12
        assert rbt12 == Decimal("1500000.56")  # ROUND_HALF_UP

    def test_rbt12_zero_aceito(self):
        motor = make_motor("0.00")
        assert motor.rbt12 == Decimal("0.00")


# ─────────────────────────────────────────────────────────────────────────────
# Fator R
# ─────────────────────────────────────────────────────────────────────────────

class TestCalcularFatorR:

    def test_fator_r_none_sem_folha(self):
        """Sem folha informada → Fator R = None."""
        motor = make_motor("500000.00", cnae="6201501")
        assert motor.fator_r is None

    def test_fator_r_none_cnae_comercio(self):
        """CNAE de comércio não aplica Fator R."""
        motor = make_motor("500000.00", cnae="4711302", folha="150000.00")
        assert motor.fator_r is None

    def test_fator_r_correto_28_porcento(self):
        """
        Fator R = 140000 / 500000 = 0.2800
        Resultado: >= 0.28 → migra para Anexo III
        """
        motor = make_motor("500000.00", cnae="6201501", folha="140000.00")
        fator = motor.fator_r
        assert fator == Decimal("0.2800")

    def test_fator_r_abaixo_do_limiar(self):
        """
        Fator R = 120000 / 500000 = 0.2400
        Resultado: < 0.28 → permanece Anexo V
        """
        motor = make_motor("500000.00", cnae="6201501", folha="120000.00")
        fator = motor.fator_r
        assert fator == Decimal("0.2400")

    def test_fator_r_zona_risco(self):
        """Fator R entre 0.27 e 0.29 → deve gerar alerta."""
        motor = make_motor("500000.00", cnae="6201501", folha="135000.00")
        alerta = motor.alertar_fator_r()
        assert alerta is not None
        assert "ZONA DE RISCO" in alerta

    def test_fator_r_acima_zona_risco_sem_alerta(self):
        """Fator R = 0.40 → sem alerta."""
        motor = make_motor("500000.00", cnae="6201501", folha="200000.00")
        alerta = motor.alertar_fator_r()
        assert alerta is None


# ─────────────────────────────────────────────────────────────────────────────
# Determinar Anexo
# ─────────────────────────────────────────────────────────────────────────────

class TestDeterminarAnexo:

    def test_comercio_vai_para_anexo_i(self):
        motor = make_motor("500000.00", cnae="4711302")
        assert motor.anexo_principal == "I"

    def test_industria_vai_para_anexo_ii(self):
        motor = make_motor("500000.00", cnae="2950600")
        assert motor.anexo_principal == "II"

    def test_ti_sem_fator_r_vai_para_anexo_v(self):
        """TI sem folha informada → sem Fator R → Anexo V."""
        motor = make_motor("500000.00", cnae="6201501")
        assert motor.anexo_principal == "V"

    def test_ti_com_fator_r_alto_vai_para_anexo_iii(self):
        """
        TI + Fator R >= 0.28 → migra de V para III.
        LC 123/2006, Art. 18, § 24.
        """
        motor = make_motor("500000.00", cnae="6201501", folha="150000.00")
        assert motor.anexo_principal == "III"

    def test_ti_com_fator_r_baixo_permanece_anexo_v(self):
        """TI + Fator R < 0.28 → permanece Anexo V."""
        motor = make_motor("500000.00", cnae="6201501", folha="100000.00")
        assert motor.anexo_principal == "V"

    def test_anexo_explicito_tem_precedencia(self):
        """Se anexo informado explicitamente, usa-o sem calcular."""
        fornecedora = EmpresaFornecedora(
            cnpj="11.222.333/0001-81",
            razao_social="Empresa X",
            regime="SIMPLES",
            cnae_principal="4711302",
            uf_origem="SP",
            faturamento_12m=Decimal("500000.00"),
            anexo_simples="II",  # Informado explicitamente
        )
        motor = MotorReformaTributaria(
            fornecedora,
            EmpresaCompradora(tipo="B2B_CONTRIBUINTE", uf_destino="SP"),
            make_operacao(),
        )
        assert motor.anexo_principal == "II"


# ─────────────────────────────────────────────────────────────────────────────
# Alíquota Efetiva — Auditoria Cruzada (Fórmula SRF)
# ─────────────────────────────────────────────────────────────────────────────

class TestCalcularAliquotaEfetiva:

    def test_aliquota_retorna_decimal(self):
        motor = make_motor("500000.00")
        assert isinstance(motor.aliquota_efetiva, Decimal)

    def test_aliquota_primeira_faixa_anexo_i(self):
        """
        Anexo I, Faixa 1: RBT12 <= 180.000
        Alíquota nominal: 4% | Parcela deduzir: 0
        Fórmula: ((180000 × 0.04) - 0) / 180000 = 0.04 = 4%
        Fonte: LC 123/2006, Anexo I, Faixa 1.
        """
        motor = make_motor("180000.00", cnae="4711302")
        aliquota = motor.aliquota_efetiva
        assert aliquota == Decimal("0.040000")

    def test_aliquota_segunda_faixa_anexo_i(self):
        """
        Anexo I, Faixa 2: 180.001 a 360.000
        RBT12 = 300.000 | Alíq: 7.3% | PD: 5.940
        Fórmula: ((300000 × 0.073) - 5940) / 300000 = 0.0532 = 5.32%
        Verificado: (21900 - 5940) / 300000 = 15960 / 300000 = 0.0532
        """
        motor = make_motor("300000.00", cnae="4711302")
        aliquota = motor.aliquota_efetiva
        esperado = ((Decimal("300000") * Decimal("0.073")) - Decimal("5940")) / Decimal("300000")
        assert aliquota == esperado.quantize(Decimal("0.000001"))

    def test_aliquota_quarta_faixa_anexo_i(self):
        """
        Anexo I, Faixa 4: 720.001 a 1.800.000
        RBT12 = 1.200.000 | Alíq: 10.7% | PD: 22.500
        Fórmula: ((1200000 × 0.107) - 22500) / 1200000
        """
        motor = make_motor("1200000.00", cnae="4711302")
        aliquota = motor.aliquota_efetiva
        esperado = ((Decimal("1200000") * Decimal("0.107")) - Decimal("22500")) / Decimal("1200000")
        assert abs(aliquota - esperado.quantize(Decimal("0.000001"))) <= Decimal("0.000001")

    def test_rbt12_acima_teto_levanta_value_error(self):
        """
        RBT12 > R$ 4.800.000 → empresa fora do Simples Nacional.
        Deve levantar ValueError, não retornar silencioso.
        """
        motor = make_motor("5000000.00", cnae="4711302")
        with pytest.raises(ValueError, match="teto do Simples Nacional"):
            motor.aliquota_efetiva

    def test_precisao_6_casas_decimais(self):
        """Alíquota efetiva deve ter 6 casas decimais (padrão SRF)."""
        motor = make_motor("750000.00", cnae="4711302")
        aliquota = motor.aliquota_efetiva
        # Verifica que tem exatamente 6 casas decimais
        assert aliquota == aliquota.quantize(Decimal("0.000001"))

    def test_aliquota_nao_usa_float(self):
        """Resultado nunca pode ser float. Deve ser Decimal."""
        motor = make_motor("500000.00")
        resultado = motor.aliquota_efetiva
        assert type(resultado) is Decimal, "Alíquota DEVE ser Decimal, nunca float"
