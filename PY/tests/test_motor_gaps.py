"""
test_motor_gaps.py — Cobertura das 22 funções descobertas em motor_tributario.py
Auditado em 08/04/2026: ratio era 1:15. Meta: ≥1:7 (CI gate 85%).

Funções cobertas aqui:
    _fracao_iva_no_das, calcular_fracao_ibs, calcular_fracao_cbs,
    _calcular_fracao_componente, _buscar_faixa, calcular_das_detalhado,
    _distancia_proxima_faixa, validar_data_transicional, validar_liquidacao,
    _validar_timeline, _instanciar_engine, obter_engine_regime,
    calcular_disparidade_anual

Executar: python -m pytest tests/test_motor_gaps.py -v
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
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def make_operacao(ano: int = 2026, valor: str = "10000.00",
                  data_liquidacao=None) -> OperacaoFiscal:
    kwargs = dict(
        data_emissao=date(ano, 6, 1),
        valor_operacao=Decimal(valor),
        ncm_nbs="84099190",
        forma_recebimento="PIX_BOLETO",
    )
    if data_liquidacao:
        kwargs["data_liquidacao"] = data_liquidacao
    return OperacaoFiscal(**kwargs)


def make_motor(
    rbt12: str = "500000.00",
    cnae: str = "4711302",
    regime: str = "SIMPLES",
    folha: str = None,
    tipo_comprador: str = "B2B_CONTRIBUINTE",
    uf: str = "SP",
    ano: int = 2026,
) -> MotorReformaTributaria:
    fornecedora = EmpresaFornecedora(
        cnpj="11.222.333/0001-81",
        razao_social="Empresa Teste Gaps Ltda",
        regime=regime,
        cnae_principal=cnae,
        uf_origem=uf,
        faturamento_12m=Decimal(rbt12),
        folha_salarios_12m=Decimal(folha) if folha else None,
    )
    compradora = EmpresaCompradora(tipo=tipo_comprador, uf_destino="SP")
    operacao = make_operacao(ano=ano)
    return MotorReformaTributaria(fornecedora, compradora, operacao)


# ─────────────────────────────────────────────────────────────────────────────
# _fracao_iva_no_das — LC 214/2025, Art. 47 §II (MAX_06 — CRÍTICO)
# ─────────────────────────────────────────────────────────────────────────────

class TestFracaoIvaNoPass:
    """
    _fracao_iva_no_das(anexo, faixa, ano) → Decimal[0, ~0.6]
    Risco: BASE do crédito B2B. Erro silencioso = cliente paga imposto errado.
    LC 214/2025 Arts. 344, 347, 348, 353, 356-360.
    """

    def test_2026_retorna_zero(self):
        """2026: Simples dispensado de destacar CBS/IBS. Sem crédito B2B. Art. 348 III 'c'."""
        motor = make_motor(rbt12="500000.00", ano=2026)
        resultado = motor._fracao_iva_no_das("I", 1, 2026)
        assert resultado == Decimal("0.0000"), (
            f"2026 deve retornar 0.0000 (sem crédito B2B). Got {resultado}"
        )

    def test_2025_retorna_zero(self):
        """Ano anterior à transição: sem CBS/IBS."""
        motor = make_motor(ano=2026)
        resultado = motor._fracao_iva_no_das("I", 1, 2025)
        assert resultado == Decimal("0.0000")

    def test_2027_retorna_decimal_positivo(self):
        """2027: CBS substitui PIS+COFINS. Deve retornar fração > 0."""
        motor = make_motor(rbt12="500000.00", ano=2026)
        resultado = motor._fracao_iva_no_das("I", 1, 2027)
        assert isinstance(resultado, Decimal), "Resultado deve ser Decimal, nunca float"
        assert resultado > Decimal("0"), "2027 deve ter CBS (PIS+COFINS do DAS)"

    def test_2033_maior_que_2027(self):
        """2033: IBS pleno (ICMS+ISS) + CBS. Deve ser maior que 2027 (só CBS)."""
        motor = make_motor(rbt12="500000.00", ano=2026)
        fracao_2027 = motor._fracao_iva_no_das("I", 1, 2027)
        fracao_2033 = motor._fracao_iva_no_das("I", 1, 2033)
        assert fracao_2033 > fracao_2027, (
            f"2033 ({fracao_2033}) deve ser > 2027 ({fracao_2027})"
        )

    def test_fase_in_2029_menor_que_2033(self):
        """2029: IBS = 10% do total ICMS+ISS. Deve ser menor que 2033 (100%)."""
        motor = make_motor(rbt12="500000.00", ano=2026)
        fracao_2029 = motor._fracao_iva_no_das("I", 1, 2029)
        fracao_2033 = motor._fracao_iva_no_das("I", 1, 2033)
        assert fracao_2029 < fracao_2033

    def test_fase_in_progressao_monotonica(self):
        """2029→2032: fração cresce 10% ao ano (monotônica). Art. 356-360."""
        motor = make_motor(rbt12="500000.00", ano=2026)
        fracoes = [motor._fracao_iva_no_das("I", 1, ano) for ano in range(2029, 2034)]
        for i in range(len(fracoes) - 1):
            assert fracoes[i] <= fracoes[i + 1], (
                f"Fração deve crescer de {2029+i} para {2030+i}"
            )

    def test_resultado_e_decimal_4_casas(self):
        """Resultado com exatamente 4 casas decimais (ROUND_HALF_UP)."""
        motor = make_motor(rbt12="500000.00", ano=2026)
        resultado = motor._fracao_iva_no_das("I", 1, 2027)
        assert resultado == resultado.quantize(Decimal("0.0001")), (
            "Resultado deve ter 4 casas decimais"
        )

    def test_resultado_nunca_negativo(self):
        """Fração é sempre não-negativa."""
        motor = make_motor(rbt12="500000.00", ano=2026)
        for ano in range(2024, 2035):
            r = motor._fracao_iva_no_das("I", 1, ano)
            assert r >= Decimal("0"), f"Fração negativa para ano {ano}: {r}"

    def test_resultado_nunca_maior_que_1(self):
        """Fração nunca excede 100% do DAS."""
        motor = make_motor(rbt12="500000.00", ano=2026)
        for ano in range(2026, 2035):
            r = motor._fracao_iva_no_das("I", 1, ano)
            assert r <= Decimal("1"), f"Fração > 1 para ano {ano}: {r}"

    def test_anexo_invalido_retorna_zero(self):
        """Anexo sem DISTRIBUICAO_DAS retorna 0 (não explode)."""
        motor = make_motor(rbt12="500000.00", ano=2026)
        resultado = motor._fracao_iva_no_das("X", 1, 2027)
        assert resultado == Decimal("0.0000")

    def test_faixa_zero_retorna_zero(self):
        """Faixa 0 (sem distribuição) retorna 0."""
        motor = make_motor(rbt12="500000.00", ano=2026)
        resultado = motor._fracao_iva_no_das("I", 0, 2027)
        assert resultado == Decimal("0.0000")


# ─────────────────────────────────────────────────────────────────────────────
# calcular_fracao_ibs / calcular_fracao_cbs
# ─────────────────────────────────────────────────────────────────────────────

class TestFracaoIbsCbs:
    """
    calcular_fracao_ibs() e calcular_fracao_cbs() → Decimal em R$
    Retorna valor monetário mensal, não percentual.
    """

    def test_fracao_ibs_retorna_decimal(self):
        motor = make_motor(rbt12="500000.00", ano=2026)
        assert isinstance(motor.fracao_ibs, Decimal)

    def test_fracao_cbs_retorna_decimal(self):
        motor = make_motor(rbt12="500000.00", ano=2026)
        assert isinstance(motor.fracao_cbs, Decimal)

    def test_fracao_ibs_nao_negativa(self):
        motor = make_motor(rbt12="500000.00", ano=2026)
        assert motor.fracao_ibs >= Decimal("0")

    def test_fracao_cbs_nao_negativa(self):
        motor = make_motor(rbt12="500000.00", ano=2026)
        assert motor.fracao_cbs >= Decimal("0")

    def test_fracao_ibs_menor_que_das_mensal(self):
        """IBS é componente do DAS — nunca maior que o DAS total."""
        motor = make_motor(rbt12="500000.00", ano=2026)
        assert motor.fracao_ibs <= motor.das_mensal

    def test_fracao_cbs_menor_que_das_mensal(self):
        motor = make_motor(rbt12="500000.00", ano=2026)
        assert motor.fracao_cbs <= motor.das_mensal

    def test_resultado_duas_casas_decimais(self):
        """Valor monetário: 2 casas decimais (centavos)."""
        motor = make_motor(rbt12="500000.00", ano=2026)
        r = motor.fracao_cbs
        assert r == r.quantize(Decimal("0.01"))


# ─────────────────────────────────────────────────────────────────────────────
# _buscar_faixa
# ─────────────────────────────────────────────────────────────────────────────

class TestBuscarFaixa:
    """
    _buscar_faixa(rbt12, anexo) → (aliquota_nominal, parcela_deduzir)
    LC 123/2006, Art. 18 — tabela de alíquotas por faixa.
    """

    def test_retorna_tupla_com_dois_decimais(self):
        motor = make_motor(rbt12="500000.00")
        aliq, pd = motor._buscar_faixa(Decimal("500000.00"), "I")
        assert isinstance(aliq, Decimal)
        assert isinstance(pd, Decimal)

    def test_aliquota_positiva(self):
        motor = make_motor(rbt12="500000.00")
        aliq, _ = motor._buscar_faixa(Decimal("500000.00"), "I")
        assert aliq > Decimal("0")

    def test_parcela_deduzir_nao_negativa(self):
        motor = make_motor(rbt12="500000.00")
        _, pd = motor._buscar_faixa(Decimal("500000.00"), "I")
        assert pd >= Decimal("0")

    def test_faixa_minima_rbt12_baixo(self):
        """RBT12 muito baixo → faixa 1 (menor alíquota)."""
        motor = make_motor(rbt12="100000.00")
        aliq_baixo, _ = motor._buscar_faixa(Decimal("100000.00"), "I")
        aliq_alto, _ = motor._buscar_faixa(Decimal("4000000.00"), "I")
        assert aliq_baixo < aliq_alto, "Alíquota cresce com RBT12"

    def test_anexo_invalido_levanta_value_error(self):
        """Anexo inexistente → ValueError."""
        motor = make_motor(rbt12="500000.00")
        with pytest.raises(ValueError, match="Anexo"):
            motor._buscar_faixa(Decimal("500000.00"), "X")

    def test_rbt12_acima_teto_levanta_value_error(self):
        """RBT12 > R$4.800.000 → ValueError (empresa deve migrar de regime)."""
        motor = make_motor(rbt12="500000.00")
        with pytest.raises(ValueError, match="teto"):
            motor._buscar_faixa(Decimal("5000000.00"), "I")


# ─────────────────────────────────────────────────────────────────────────────
# calcular_das_detalhado
# ─────────────────────────────────────────────────────────────────────────────

class TestCalcularDasDetalhado:
    """
    calcular_das_detalhado(rpa=None) → Decimal
    DAS com arredondamento per-tributo (mais preciso que calcular_das_mensal).
    """

    def test_retorna_decimal(self):
        motor = make_motor(rbt12="500000.00")
        assert isinstance(motor.calcular_das_detalhado(), Decimal)

    def test_resultado_positivo(self):
        motor = make_motor(rbt12="500000.00")
        assert motor.calcular_das_detalhado() > Decimal("0")

    def test_resultado_duas_casas_decimais(self):
        motor = make_motor(rbt12="500000.00")
        r = motor.calcular_das_detalhado()
        assert r == r.quantize(Decimal("0.01"))

    def test_rpa_explicito_altera_resultado(self):
        """RPA explícito diferente do padrão muda o DAS detalhado."""
        motor = make_motor(rbt12="1200000.00")
        das_padrao = motor.calcular_das_detalhado()
        das_rpa_alto = motor.calcular_das_detalhado(rpa=Decimal("200000.00"))
        # RPA maior → DAS maior (relação direta)
        assert das_rpa_alto != das_padrao

    def test_resultado_nunca_negativo(self):
        motor = make_motor(rbt12="500000.00")
        assert motor.calcular_das_detalhado() >= Decimal("0")


# ─────────────────────────────────────────────────────────────────────────────
# _distancia_proxima_faixa
# ─────────────────────────────────────────────────────────────────────────────

class TestDistanciaProximaFaixa:
    """
    _distancia_proxima_faixa() → Decimal | None
    Quanto falta para a próxima faixa de RBT12 (planejamento tributário).
    """

    def test_retorna_decimal_quando_nao_no_teto(self):
        motor = make_motor(rbt12="500000.00")
        resultado = motor._distancia_proxima_faixa()
        assert isinstance(resultado, Decimal)

    def test_distancia_positiva(self):
        motor = make_motor(rbt12="500000.00")
        assert motor._distancia_proxima_faixa() > Decimal("0")

    def test_resultado_duas_casas_decimais(self):
        motor = make_motor(rbt12="500000.00")
        r = motor._distancia_proxima_faixa()
        assert r == r.quantize(Decimal("0.01"))

    def test_rbt12_no_teto_exato_retorna_zero(self):
        """RBT12 igual ao teto → Decimal('0.00') (distância = zero, ainda na última faixa)."""
        motor = make_motor(rbt12="4800000.00")
        assert motor._distancia_proxima_faixa() == Decimal("0.00")

    def test_distancia_decresce_com_rbt12_maior(self):
        """Quanto maior o RBT12, menor a distância para próxima faixa."""
        motor_baixo = make_motor(rbt12="100000.00")
        motor_alto = make_motor(rbt12="170000.00")
        dist_baixo = motor_baixo._distancia_proxima_faixa()
        dist_alto = motor_alto._distancia_proxima_faixa()
        if dist_baixo is not None and dist_alto is not None:
            assert dist_baixo > dist_alto


# ─────────────────────────────────────────────────────────────────────────────
# validar_data_transicional — via OperacaoFiscal
# ─────────────────────────────────────────────────────────────────────────────

class TestValidarDataTransicional:
    """
    OperacaoFiscal.validar_data_transicional — @field_validator("data_emissao")
    LC 214/2025: período válido 2026-2033.
    """

    def test_2025_invalido(self):
        with pytest.raises(Exception, match="2026"):
            OperacaoFiscal(
                data_emissao=date(2025, 12, 31),
                valor_operacao=Decimal("10000.00"),
                ncm_nbs="84099190",
                forma_recebimento="PIX_BOLETO",
            )

    def test_2034_invalido(self):
        with pytest.raises(Exception):
            OperacaoFiscal(
                data_emissao=date(2034, 1, 1),
                valor_operacao=Decimal("10000.00"),
                ncm_nbs="84099190",
                forma_recebimento="PIX_BOLETO",
            )

    def test_2026_valido(self):
        op = make_operacao(ano=2026)
        assert op.data_emissao.year == 2026

    def test_2033_valido(self):
        op = OperacaoFiscal(
            data_emissao=date(2033, 12, 31),
            valor_operacao=Decimal("10000.00"),
            ncm_nbs="84099190",
            forma_recebimento="PIX_BOLETO",
        )
        assert op.data_emissao.year == 2033

    @pytest.mark.parametrize("ano", [2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033])
    def test_todos_anos_transicionais_validos(self, ano):
        op = OperacaoFiscal(
            data_emissao=date(ano, 6, 1),
            valor_operacao=Decimal("10000.00"),
            ncm_nbs="84099190",
            forma_recebimento="PIX_BOLETO",
        )
        assert op.data_emissao.year == ano


# ─────────────────────────────────────────────────────────────────────────────
# validar_liquidacao — via OperacaoFiscal
# ─────────────────────────────────────────────────────────────────────────────

class TestValidarLiquidacao:
    """
    OperacaoFiscal.validar_liquidacao — @model_validator
    Data de liquidação não pode ser anterior à emissão.
    """

    def test_liquidacao_anterior_a_emissao_invalida(self):
        with pytest.raises(Exception, match="liquidação"):
            OperacaoFiscal(
                data_emissao=date(2026, 6, 15),
                data_liquidacao=date(2026, 6, 14),
                valor_operacao=Decimal("10000.00"),
                ncm_nbs="84099190",
                forma_recebimento="PIX_BOLETO",
            )

    def test_liquidacao_igual_a_emissao_valida(self):
        op = OperacaoFiscal(
            data_emissao=date(2026, 6, 15),
            data_liquidacao=date(2026, 6, 15),
            valor_operacao=Decimal("10000.00"),
            ncm_nbs="84099190",
            forma_recebimento="PIX_BOLETO",
        )
        assert op.data_liquidacao == op.data_emissao

    def test_liquidacao_posterior_valida(self):
        op = OperacaoFiscal(
            data_emissao=date(2026, 6, 15),
            data_liquidacao=date(2027, 1, 1),
            valor_operacao=Decimal("10000.00"),
            ncm_nbs="84099190",
            forma_recebimento="PIX_BOLETO",
        )
        assert op.data_liquidacao > op.data_emissao

    def test_liquidacao_none_aceita(self):
        """data_liquidacao é opcional — None é válido."""
        op = make_operacao(ano=2026)
        assert op.data_liquidacao is None


# ─────────────────────────────────────────────────────────────────────────────
# _validar_timeline — MAX_FISCAL_03
# ─────────────────────────────────────────────────────────────────────────────

class TestValidarTimeline:
    """
    _validar_timeline() — chamado no __init__ do Motor.
    Registra passo "MAX_FISCAL_03" na trilha_auditoria.
    LC 214/2025, Art. 360.
    """

    def test_timeline_registrada_na_trilha(self):
        motor = make_motor(ano=2026)
        ids = [p.get("id") for p in motor.trilha_auditoria]
        assert "MAX_FISCAL_03" in ids, "Timeline deve estar na trilha_auditoria"

    def test_timeline_tem_amparo_legal(self):
        motor = make_motor(ano=2026)
        passo = next(p for p in motor.trilha_auditoria if p.get("id") == "MAX_FISCAL_03")
        assert passo.get("amparo_legal"), "MAX_FISCAL_03 deve ter amparo_legal"
        assert "LC 214" in passo["amparo_legal"], "Deve citar LC 214/2025"

    def test_status_2026_e_teste(self):
        motor = make_motor(ano=2026)
        passo = next(p for p in motor.trilha_auditoria if p.get("id") == "MAX_FISCAL_03")
        assert "TESTE" in str(passo.get("memoria") or passo.get("valor") or passo)

    def test_status_2027_e_efetivo(self):
        motor = make_motor(ano=2027)
        passo = next(p for p in motor.trilha_auditoria if p.get("id") == "MAX_FISCAL_03")
        assert "EFETIVO" in str(passo.get("memoria") or passo.get("valor") or passo)

    def test_status_2029_e_transicao(self):
        motor = make_motor(ano=2029)
        passo = next(p for p in motor.trilha_auditoria if p.get("id") == "MAX_FISCAL_03")
        assert "TRANSICAO" in str(passo.get("memoria") or passo.get("valor") or passo)


# ─────────────────────────────────────────────────────────────────────────────
# _instanciar_engine / obter_engine_regime
# ─────────────────────────────────────────────────────────────────────────────

class TestInstanciarEngine:
    """
    _instanciar_engine() — dispatcher para engines de regime.
    SIMPLES mono → None | PRESUMIDO → LucroPresumidoEngine | MEI → MEIEngine | REAL → LucroRealEngine
    """

    def test_simples_mono_retorna_none(self):
        motor = make_motor(regime="SIMPLES")
        assert motor._engine_regime is None

    def test_presumido_retorna_engine(self):
        motor = make_motor(regime="PRESUMIDO", cnae="6201501")
        assert motor._engine_regime is not None
        assert "LucroPresumido" in type(motor._engine_regime).__name__

    def test_mei_retorna_engine(self):
        motor = make_motor(
            regime="MEI",
            rbt12="50000.00",
            cnae="4711302",
        )
        assert motor._engine_regime is not None
        assert "MEI" in type(motor._engine_regime).__name__

    def test_real_retorna_engine(self):
        motor = make_motor(regime="REAL", cnae="6201501")
        assert motor._engine_regime is not None
        assert "Real" in type(motor._engine_regime).__name__

    def test_obter_engine_regime_consistente(self):
        """obter_engine_regime() retorna o mesmo objeto que _engine_regime."""
        motor = make_motor(regime="PRESUMIDO", cnae="6201501")
        assert motor.obter_engine_regime() is motor._engine_regime
