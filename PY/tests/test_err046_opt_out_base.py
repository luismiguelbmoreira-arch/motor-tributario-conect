"""
test_err046_opt_out_base.py — ERR-046 TDD Reverso (Protocolo Jogada Fiscal)

ERR-046: cenario_opt_out subtraía IBS/CBS em R$ do DAS mensal de um custo
calculado sobre valor_operacao — bases incompatíveis, viola MAX_FISCAL_01.

Fix consensado na ATA (Chefe + Viciado + Luiz):
    custo_das_sem_iva = valor_operacao * AE * (1 - fracao_iva_pct * fator_reducao)

Simetria do fator_reducao foi incluída por veto do Luiz: sem ela, REDUCAO_60
deixaria IVA por fora a 40% mas o DAS expurgaria 100% da fração — viés pró-opt-out.

Fontes legislativas:
  - LC 214/2025 Arts. 41-44 (dispositivo opt-out)
  - LC 214/2025 Art. 47 §II (creditamento proporcional)
  - LC 214/2025 Arts. 258-264 (fator de redução CBS/IBS — aplicação isonômica)
  - LC 214/2025 Arts. 344, 353, 356-360 (cronograma IVA 2027-2033)
  - LC 214/2025 Art. 348 III 'c' (dispensa 2026)

Executar:
    python -m pytest PY/tests/test_err046_opt_out_base.py -v

Os testes 1, 2, 4, 5 FALHAM na versão pré-fix. Teste 3 (boundary 2026) passa
em ambas porque a fração de IVA é zero nesse ano.
"""

import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.motor_tributario import (
    EmpresaCompradora,
    EmpresaFornecedora,
    MotorReformaTributaria,
    OperacaoFiscal,
)


def _motor(
    rbt12: str,
    valor: str,
    ano: int,
    reducao: str = "INTEGRAL",
    tipo_comprador: str = "B2B_CONTRIBUINTE",
) -> MotorReformaTributaria:
    fornecedora = EmpresaFornecedora(
        cnpj="11.222.333/0001-81",
        razao_social="Empresa Teste ERR-046 Ltda",
        regime="SIMPLES",
        cnae_principal="4711302",  # Comércio → Anexo I
        uf_origem="SP",
        faturamento_12m=Decimal(rbt12),
    )
    compradora = EmpresaCompradora(tipo=tipo_comprador, uf_destino="SP")
    operacao = OperacaoFiscal(
        data_emissao=date(ano, 6, 1),
        valor_operacao=Decimal(valor),
        ncm_nbs="84099190",
        forma_recebimento="PIX_VIA_PSP",
        reducao_cbs_ibs=reducao,
    )
    return MotorReformaTributaria(fornecedora, compradora, operacao)


# ─────────────────────────────────────────────────────────────────────────────
# TESTE 1 — Linearidade em valor_operacao (canário permanente)
# Se dobrar valor_operacao mantendo rbt12 fixo, custo_das_sem_iva DEVE dobrar
# exato. Com a fórmula ERRADA (subtração de R$ mensal constante), NÃO dobra.
# ─────────────────────────────────────────────────────────────────────────────

class TestERR046Linearidade:

    def test_dobrar_valor_operacao_dobra_custo_das(self):
        """Invariante matemático — fórmula correta é linear em valor_operacao."""
        m_a = _motor(rbt12="600000", valor="10000", ano=2029)
        m_b = _motor(rbt12="600000", valor="20000", ano=2029)
        custo_a = Decimal(m_a.cenario_opt_out()["custo_das_por_operacao"])
        custo_b = Decimal(m_b.cenario_opt_out()["custo_das_por_operacao"])
        # Tolerância 2 centavos (2 quantizes na cadeia)
        assert abs(custo_b - custo_a * 2) <= Decimal("0.02"), (
            f"ERR-046 regressão: custo_das_sem_iva não é linear em valor_operacao. "
            f"op=10k → {custo_a}, op=20k → {custo_b}, esperado ~{custo_a * 2}."
        )

    def test_triplicar_valor_operacao_triplica_custo_das(self):
        """Mesma invariante em fator maior (3×) — garante estabilidade em escala."""
        m_a = _motor(rbt12="600000", valor="10000", ano=2030)
        m_b = _motor(rbt12="600000", valor="30000", ano=2030)
        custo_a = Decimal(m_a.cenario_opt_out()["custo_das_por_operacao"])
        custo_b = Decimal(m_b.cenario_opt_out()["custo_das_por_operacao"])
        assert abs(custo_b - custo_a * 3) <= Decimal("0.03"), (
            f"ERR-046 regressão: triplicar valor_operacao não triplicou custo_das. "
            f"op=10k → {custo_a}, op=30k → {custo_b}."
        )


# ─────────────────────────────────────────────────────────────────────────────
# TESTE 2 — Operação pequena nunca produz custo negativo
# Com fórmula ERRADA, operação << RBT12/12 pode dar custo_das_sem_iva < 0
# (fracao_iva em R$ do DAS mensal maior que custo AE da operação pequena).
# ─────────────────────────────────────────────────────────────────────────────

class TestERR046NaoNegatividade:

    def test_operacao_pequena_custo_nunca_negativo(self):
        """RBT12=1.2M (média mensal 100k) × operação=2k (1/50 da média).
        Com fórmula errada, fracao_iva do DAS mensal (~R$ ??) pode ultrapassar
        o custo AE da operação pequena, gerando valor absurdamente negativo."""
        motor = _motor(rbt12="1200000", valor="2000", ano=2032)
        resultado = motor.cenario_opt_out()
        custo_das = Decimal(resultado["custo_das_por_operacao"])
        assert custo_das >= Decimal("0"), (
            f"ERR-046 violação: custo_das_por_operacao={custo_das} é negativo. "
            f"Subtração de R$ mensal excedeu o custo AE da operação."
        )

    def test_operacao_pequena_custo_total_coerente(self):
        """custo_total = custo_das + iva_por_fora. Ambos positivos, soma positiva."""
        motor = _motor(rbt12="1200000", valor="2000", ano=2032)
        resultado = motor.cenario_opt_out()
        custo_total = Decimal(resultado["custo_total"])
        iva = Decimal(resultado["iva_recolhido_por_fora"])
        das = Decimal(resultado["custo_das_por_operacao"])
        assert custo_total > Decimal("0"), "custo_total deve ser positivo"
        assert iva >= Decimal("0"), "IVA por fora deve ser não-negativo"
        assert das >= Decimal("0"), "DAS sem IVA deve ser não-negativo"


# ─────────────────────────────────────────────────────────────────────────────
# TESTE 3 — Boundary 2026 (fração IVA = 0)
# Em 2026, _fracao_iva_no_das retorna 0 (Art. 348 III 'c'). Fórmula antiga e
# nova convergem: custo_das_sem_iva == valor_operacao * AE.
# Este teste PASSA em ambas versões — prova que o fix não quebra boundary.
# ─────────────────────────────────────────────────────────────────────────────

class TestERR046Boundary2026:

    def test_2026_custo_das_igual_valor_vezes_ae(self):
        """2026: fração IVA no DAS = 0 (Art. 348 III 'c'). custo_das_sem_iva
        deve ser exatamente valor_operacao × AE — nem fórmula antiga nem nova
        subtrai nada."""
        motor = _motor(rbt12="600000", valor="20000", ano=2026)
        resultado = motor.cenario_opt_out()
        custo_das = Decimal(resultado["custo_das_por_operacao"])
        ae = motor.aliquota_efetiva
        esperado = (Decimal("20000") * ae).quantize(Decimal("0.01"))
        assert abs(custo_das - esperado) <= Decimal("0.02"), (
            f"2026 boundary: custo_das={custo_das} deve ser {esperado} "
            f"(valor × AE, sem subtração de fração IVA)."
        )


# ─────────────────────────────────────────────────────────────────────────────
# TESTE 4 — Simetria do fator_reducao (veto do Luiz)
# Em REDUCAO_60, o IVA por fora paga 40% da alíquota cheia. A fração do DAS
# expurgada deve simetricamente ser apenas 40% (fracao × fator_reducao).
# Sem simetria: das_reducao < das_integral (errado, viés pró-opt-out).
# Com simetria: das_reducao > das_integral (correto).
# ─────────────────────────────────────────────────────────────────────────────

class TestERR046SimetriaReducao:

    def test_reducao_60_expurga_menos_que_integral(self):
        """Veto do Luiz: fator_reducao aplica nas DUAS pontas (DAS e por fora).
        Em REDUCAO_60, das_sem_iva deve ser MAIOR que em INTEGRAL porque a
        fração IVA do DAS é reduzida simetricamente a 40%."""
        ano = 2031  # fase-in ativo, efeito visível
        m_integral = _motor(rbt12="600000", valor="20000", ano=ano, reducao="INTEGRAL")
        m_reducao = _motor(rbt12="600000", valor="20000", ano=ano, reducao="REDUCAO_60")
        das_integral = Decimal(m_integral.cenario_opt_out()["custo_das_por_operacao"])
        das_reducao = Decimal(m_reducao.cenario_opt_out()["custo_das_por_operacao"])
        assert das_reducao > das_integral, (
            f"ERR-046 simetria: REDUCAO_60 deveria expurgar menos do DAS "
            f"(fator 40%), logo das_reducao={das_reducao} > das_integral={das_integral}. "
            f"Se estiver invertido, o fator_reducao não foi aplicado simetricamente."
        )

    def test_isento_nao_expurga_nada_do_das(self):
        """ISENTO: fator_reducao = 0. Fração IVA × 0 = 0. custo_das_sem_iva
        é igual ao custo_das completo (valor_operacao × AE)."""
        motor = _motor(rbt12="600000", valor="20000", ano=2031, reducao="ISENTO")
        resultado = motor.cenario_opt_out()
        custo_das = Decimal(resultado["custo_das_por_operacao"])
        esperado = (Decimal("20000") * motor.aliquota_efetiva).quantize(Decimal("0.01"))
        assert abs(custo_das - esperado) <= Decimal("0.02"), (
            f"ISENTO: custo_das_sem_iva deve ser igual a custo_das_completo "
            f"(fator_reducao=0 zera a subtração). Obtido {custo_das}, esperado {esperado}."
        )


# ─────────────────────────────────────────────────────────────────────────────
# TESTE 5 — Invariante de soma (blindagem contra regressão)
# custo_total == custo_das_sem_iva + iva_por_fora, para qualquer combinação
# de RBT12 / valor_operacao / ano / reducao.
# ─────────────────────────────────────────────────────────────────────────────

class TestERR046InvarianteSoma:

    def test_soma_das_mais_iva_igual_total(self):
        """Invariante estrutural: custo_total deve ser soma exata de das + iva."""
        casos = [
            ("600000", "20000", 2029, "INTEGRAL"),
            ("1200000", "50000", 2030, "REDUCAO_30"),
            ("600000", "5000", 2031, "REDUCAO_60"),
            ("2000000", "100000", 2033, "INTEGRAL"),
        ]
        for rbt12, valor, ano, red in casos:
            motor = _motor(rbt12=rbt12, valor=valor, ano=ano, reducao=red)
            r = motor.cenario_opt_out()
            das = Decimal(r["custo_das_por_operacao"])
            iva = Decimal(r["iva_recolhido_por_fora"])
            total = Decimal(r["custo_total"])
            assert abs(total - (das + iva)) <= Decimal("0.02"), (
                f"Invariante soma quebrado em RBT12={rbt12}, valor={valor}, "
                f"ano={ano}, red={red}: {das}+{iva}≠{total}"
            )
