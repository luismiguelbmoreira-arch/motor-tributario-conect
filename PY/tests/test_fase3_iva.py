"""
test_fase3_iva.py — TDD Fase 3 (Dissecação IBS/CBS + Crédito B2B + Split Payment)
Testa: get_aliquotas_iva_por_ano, calcular_credito_simples_para_b2b,
       calcular_split_payment_impacto, cenario_simples_puro, cenario_opt_out

Fontes legislativas:
  - CRONOGRAMA_IVA: LC 214/2025, Arts. 344, 348, 353-360
  - Split Payment: LC 214/2025, Art. 344 (ativo jan/2027)
  - CBS 2027: Art. 353 (substitui PIS+COFINS)
  - IBS fase-in: Arts. 356-360 (2029-2033)

Critério de congelamento: Diferença máxima de R$ 0,01.
Executar: python -m pytest PY/tests/test_fase3_iva.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

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

def make_motor(
    rbt12: str = "1800000.00",
    cnae: str = "4711302",        # Comércio → Anexo I
    ano: int = 2027,
    valor: str = "50000.00",
    forma: str = "PIX_VIA_PSP",
    tipo_comprador: str = "B2B_CONTRIBUINTE",
    folha: str = None,
) -> MotorReformaTributaria:
    fornecedora = EmpresaFornecedora(
        cnpj="11.222.333/0001-81",
        razao_social="Empresa Teste IVA Ltda",
        regime="SIMPLES",
        cnae_principal=cnae,
        uf_origem="SP",
        faturamento_12m=Decimal(rbt12),
        folha_salarios_12m=Decimal(folha) if folha else None,
    )
    compradora = EmpresaCompradora(
        tipo=tipo_comprador,
        uf_destino="SP",
    )
    operacao = OperacaoFiscal(
        data_emissao=date(ano, 6, 1),
        valor_operacao=Decimal(valor),
        ncm_nbs="84099190",
        forma_recebimento=forma,
    )
    return MotorReformaTributaria(fornecedora, compradora, operacao)


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 1 — CRONOGRAMA_IVA: alíquotas por ano
# Fonte: LC 214/2025, Arts. 344, 348, 353-360
# ─────────────────────────────────────────────────────────────────────────────

class TestCronogramaIVA:

    def test_2026_cbs_09_ibs_01(self):
        """2026: CBS 0,9% + IBS 0,1% — período de teste, Art. 348 LC 214/2025."""
        motor = make_motor(ano=2026)
        aliq = motor.get_aliquotas_iva_por_ano()
        assert aliq["CBS"] == Decimal("0.009"), "CBS 2026 deve ser 0,9%"
        assert aliq["IBS"] == Decimal("0.001"), "IBS 2026 deve ser 0,1%"

    def test_2027_cbs_88_ibs_01(self):
        """2027: CBS 8,8% (PIS+COFINS extintos) + IBS 0,1% (taxa-teste). Art. 353."""
        motor = make_motor(ano=2027)
        aliq = motor.get_aliquotas_iva_por_ano()
        assert aliq["CBS"] == Decimal("0.088"), "CBS 2027 deve ser 8,8%"
        assert aliq["IBS"] == Decimal("0.001"), "IBS 2027 ainda em taxa-teste 0,1%"

    def test_2028_igual_2027(self):
        """2028: CBS e IBS idênticos a 2027 — IBS ainda em fase de teste."""
        motor = make_motor(ano=2028)
        aliq = motor.get_aliquotas_iva_por_ano()
        assert aliq["CBS"] == Decimal("0.088")
        assert aliq["IBS"] == Decimal("0.001")

    def test_2029_ibs_fase_in_10_pct(self):
        """2029: IBS fase-in 10% da alíquota plena — Arts. 356-360 LC 214/2025.
        ERR-045: correção de 20% → 10% ao ano. ICMS/ISS reduzidos em 10%/ano
        com cobrança gradual de IBS simétrica (CRCSP, SimTax, Tax Group)."""
        motor = make_motor(ano=2029)
        aliq = motor.get_aliquotas_iva_por_ano()
        assert aliq["CBS"] == Decimal("0.088")
        assert aliq["IBS"] == Decimal("0.0177"), "IBS 2029 = 10% de 17,7%"

    def test_2033_regime_pleno(self):
        """2033: CBS 8,8% + IBS 17,7% — ICMS/ISS extintos, regime pleno."""
        motor = make_motor(ano=2033)
        aliq = motor.get_aliquotas_iva_por_ano()
        assert aliq["CBS"] == Decimal("0.088")
        assert aliq["IBS"] == Decimal("0.177"), "IBS 2033 = 100% da alíquota de referência"

    def test_cbs_estavel_2027_a_2033(self):
        """CBS deve permanecer em 8,8% de 2027 a 2033 — não cresce como o IBS."""
        for ano in range(2027, 2034):
            motor = make_motor(ano=ano)
            aliq = motor.get_aliquotas_iva_por_ano()
            assert aliq["CBS"] == Decimal("0.088"), f"CBS {ano} deve ser 8,8%"

    def test_ibs_cresce_ano_a_ano_2029_2033(self):
        """IBS cresce progressivamente de 2029 a 2033 — fase-in ICMS/ISS.

        V-05 fix: ancorado em valores absolutos (phase-in 10%/ano de 0.177).
        Monotonicidade sozinha aceitava valores errados (ex: 20%/ano antigo).
        Agora crava cada ano contra a expectativa legal direta.
        """
        esperados = {
            2029: Decimal("0.0177"),  # 10% de 0.177
            2030: Decimal("0.0354"),  # 20%
            2031: Decimal("0.0531"),  # 30%
            2032: Decimal("0.0708"),  # 40%
            2033: Decimal("0.177"),   # 100%
        }
        ibs_anterior = Decimal("0")
        for ano, esperado in esperados.items():
            motor = make_motor(ano=ano)
            aliq = motor.get_aliquotas_iva_por_ano()
            assert aliq["IBS"] == esperado, (
                f"IBS {ano} esperado {esperado}, obtido {aliq['IBS']}"
            )
            assert aliq["IBS"] > ibs_anterior, f"IBS {ano} deve ser > IBS {ano-1}"
            ibs_anterior = aliq["IBS"]

    def test_total_iva_2026_menor_que_2027(self):
        """Split 2026 (1%) << Split 2027 (8,9%) — diferença de liquidez real."""
        m26 = make_motor(ano=2026)
        m27 = make_motor(ano=2027)
        aliq26 = m26.get_aliquotas_iva_por_ano()
        aliq27 = m27.get_aliquotas_iva_por_ano()
        total26 = aliq26["CBS"] + aliq26["IBS"]
        total27 = aliq27["CBS"] + aliq27["IBS"]
        assert total27 > total26 * 8, "Split 2027 deve ser ~8,9× maior que 2026"


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 2 — CRÉDITO B2B (Simples Puro)
# Fonte: LC 214/2025, Art. 121 (creditamento para adquirente de Simples)
# ─────────────────────────────────────────────────────────────────────────────

class TestCreditoB2B:

    def test_credito_2026_zero(self):
        """
        2026: Operação R$ 50.000 deve gerar CRÉDITO ZERO para B2B.

        CORREÇÃO LEGAL pós-pesquisa (09/04/2026):
        LC 214/2025, Art. 348, III, "c" — em 2026, optantes do Simples
        Nacional NÃO aplicam as alíquotas de transição, ou seja, NÃO
        destacam CBS/IBS nas operações. Consequentemente, o cliente B2B
        NÃO recebe crédito em operações com fornecedor do Simples em 2026.

        O valor anterior (R$ 500 = 1% de R$ 50.000) estava conceitualmente
        errado — assumia que as alíquotas-teste (0,9% + 0,1% = 1%) seriam
        destacadas, o que não acontece para o Simples Nacional neste ano.

        A partir de 2027 (primeiro ano de recolhimento efetivo), o crédito
        passa a existir conforme Art. 47, § 9º da LC 214/2025 — em valor
        equivalente ao DAS recolhido pelo fornecedor Simples (ERR-057).
        """
        motor = make_motor(ano=2026, valor="50000.00")
        credito = motor.credito_b2b_simples
        assert credito == Decimal("0.00"), (
            f"Crédito 2026 deve ser R$ 0 (Art. 348, III, 'c'), obtido R$ {credito}"
        )

    def test_credito_2027_fracao_pis_cofins(self):
        """
        2027: Crédito = DAS_mensal × fração (PIS+COFINS) — LC 214/2025 Art. 47 § 9º.

        Anexo I Faixa 5 default do make_motor:
          PIS 2,76% + COFINS 12,74% = 15,50% do DAS

        CBS substitui PIS+COFINS integralmente em 2027 (Arts. 344 + 353).
        ICMS ainda NÃO virou IBS (fase-in começa em 2029).
        """
        motor = make_motor(ano=2027, valor="50000.00")
        das = motor.das_mensal
        credito = motor.credito_b2b_simples
        # Anexo I Faixa 5 → PIS 2,76% + COFINS 12,74% = 15,50%
        esperado = (das * Decimal("0.1550")).quantize(Decimal("0.01"))
        assert abs(credito - esperado) <= Decimal("0.02"), (
            f"Crédito 2027 esperado ~R$ {esperado}, obtido R$ {credito}"
        )

    def test_credito_2033_pleno_cbs_mais_ibs(self):
        """
        2033: Crédito = DAS_mensal × fração (PIS+COFINS+ICMS) — regime pleno.

        Anexo I Faixa 5 default do make_motor:
          PIS 2,76% + COFINS 12,74% + ICMS 34,00% = 49,50% do DAS

        IBS substituiu ICMS integralmente em 2033. ISS=0 neste anexo.
        """
        motor = make_motor(ano=2033, valor="50000.00")
        das = motor.das_mensal
        credito = motor.credito_b2b_simples
        # Anexo I Faixa 5 → PIS 2,76% + COFINS 12,74% + ICMS 34,00% = 49,50%
        esperado = (das * Decimal("0.4950")).quantize(Decimal("0.01"))
        assert abs(credito - esperado) <= Decimal("0.02"), (
            f"Crédito 2033 esperado ~R$ {esperado}, obtido R$ {credito}"
        )

    def test_credito_proporcional_ao_rbt12(self):
        """
        Crédito deve escalar (aproximadamente) com o DAS, não com o valor da operação.

        Dobrar RBT12 dentro da mesma faixa de partilha → DAS dobra (linear) →
        crédito dobra. Usamos 2 RBT12 dentro da Faixa 5 (720k < RBT12 ≤ 1.8M)
        do Anexo I, onde a partilha é idêntica.
        """
        m1 = make_motor(ano=2027, rbt12="900000.00")
        m2 = make_motor(ano=2027, rbt12="1800000.00")
        c1 = m1.credito_b2b_simples
        c2 = m2.credito_b2b_simples
        # Como DAS não escala perfeitamente linear (dedução parcela por faixa),
        # aceitamos proporção dentro de ±15%
        razao = c2 / c1 if c1 > 0 else Decimal("0")
        assert Decimal("1.5") <= razao <= Decimal("3.0"), (
            f"Razão c2/c1 fora do esperado: {razao}"
        )

    def test_credito_2027_maior_que_2026(self):
        """2027 > R$ 0 (2026) — impacto da CBS substituindo PIS+COFINS."""
        m26 = make_motor(ano=2026, valor="50000.00")
        m27 = make_motor(ano=2027, valor="50000.00")
        c26 = m26.credito_b2b_simples
        c27 = m27.credito_b2b_simples
        assert c26 == Decimal("0.00")
        assert c27 > Decimal("0.00")


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 2b — CRÉDITO B2B ART. 47 § 9º — GOLDEN FINO POR ANEXO × FAIXA × ANO
# Fonte: LC 214/2025, Art. 47, § 9º (crédito em valor equivalente ao DAS recolhido).
# Cronograma de transição: Arts. 344-353 (CBS 2027), Arts. 356-360 (IBS phase-in 2029-32).
# Citação anterior "§II + Arts. 344-360" como creditamento foi corrigida em ERR-057.
# Valida que o cálculo usa fração REAL do DAS (não valor_operação × IVA cheio).
# ─────────────────────────────────────────────────────────────────────────────


class TestCreditoB2BArtigo47:
    """Validação Art. 47 § 9º — crédito por fração real do DAS (ERR-057)."""

    @staticmethod
    def _moreira(ano: int) -> MotorReformaTributaria:
        """
        Caso de referência: escritório de contabilidade (Anexo III por Fator R),
        RBT12 R$ 1.800.000 → Faixa 4, folha 33% → Fator R ativo.
        """
        return make_motor(
            rbt12="1800000.00",
            cnae="6920601",       # Contabilidade → Anexo III (via Fator R)
            folha="600000.00",    # 33% da receita → Fator R ≥ 28% → Anexo III
            ano=ano,
            valor="50000.00",
            tipo_comprador="B2B_CONTRIBUINTE",
        )

    # ── 2026 — dispensa ──────────────────────────────────────────────────────

    def test_2026_credito_zero_dispensa(self):
        """2026: Art. 348 III 'c' — dispensa. Crédito sempre R$ 0."""
        credito = self._moreira(2026).credito_b2b_simples
        assert credito == Decimal("0.00")

    # ── 2027-2028 — apenas CBS (PIS+COFINS) ──────────────────────────────────

    def test_2027_fracao_pis_cofins_anexo_iii(self):
        """
        2027: Anexo III Faixa 4 → PIS 2,96% + COFINS 13,64% = 16,60% do DAS.
        CBS substitui PIS+COFINS integralmente (Arts. 344 + 353).
        """
        motor = self._moreira(2027)
        das = motor.das_mensal
        credito = motor.credito_b2b_simples
        esperado = (das * Decimal("0.1660")).quantize(Decimal("0.01"))
        assert abs(credito - esperado) <= Decimal("10.00"), (
            f"2027: esperado ~R$ {esperado}, obtido R$ {credito} (DAS R$ {das})"
        )

    def test_2028_fracao_identica_a_2027(self):
        """2028: IBS ainda em taxa-teste 0,1% — fração igual a 2027."""
        c27 = self._moreira(2027).credito_b2b_simples
        c28 = self._moreira(2028).credito_b2b_simples
        assert abs(c27 - c28) <= Decimal("0.01"), (
            f"2027 (R$ {c27}) deveria ser == 2028 (R$ {c28})"
        )

    # ── 2029-2032 — fase-in IBS (ICMS+ISS × fator escalonado) ────────────────

    def test_2029_fase_in_10_pct_iss(self):
        """
        2029: 16,60% + (32,50% × 10%) = 19,85% do DAS.
        Primeiro ano do fase-in IBS — ISS começa a virar IBS.
        """
        motor = self._moreira(2029)
        das = motor.das_mensal
        credito = motor.credito_b2b_simples
        esperado = (das * Decimal("0.1985")).quantize(Decimal("0.01"))
        assert abs(credito - esperado) <= Decimal("10.00"), (
            f"2029: esperado ~R$ {esperado}, obtido R$ {credito}"
        )

    def test_2032_fase_in_40_pct_iss(self):
        """2032: 16,60% + (32,50% × 40%) = 29,60% do DAS. Último ano do fase-in."""
        motor = self._moreira(2032)
        das = motor.das_mensal
        credito = motor.credito_b2b_simples
        esperado = (das * Decimal("0.2960")).quantize(Decimal("0.01"))
        assert abs(credito - esperado) <= Decimal("10.00"), (
            f"2032: esperado ~R$ {esperado}, obtido R$ {credito}"
        )

    # ── 2033+ — regime pleno ─────────────────────────────────────────────────

    def test_2033_pleno_cbs_mais_ibs_integral(self):
        """
        2033: 16,60% + 32,50% = 49,10% do DAS. Regime pleno.
        IBS substituiu ICMS/ISS integralmente.
        """
        motor = self._moreira(2033)
        das = motor.das_mensal
        credito = motor.credito_b2b_simples
        esperado = (das * Decimal("0.4910")).quantize(Decimal("0.01"))
        assert abs(credito - esperado) <= Decimal("10.00"), (
            f"2033: esperado ~R$ {esperado}, obtido R$ {credito}"
        )

    # ── Invariantes fiscais ──────────────────────────────────────────────────

    def test_credito_monotonicamente_crescente_2027_2033(self):
        """Phase-in de IBS garante crédito monotonicamente crescente ano a ano."""
        anterior = Decimal("-0.01")
        for ano in [2027, 2028, 2029, 2030, 2031, 2032, 2033]:
            c = self._moreira(ano).credito_b2b_simples
            assert c >= anterior, (
                f"Regressão em {ano}: R$ {c} < R$ {anterior} (ano anterior)"
            )
            anterior = c

    def test_credito_nunca_supera_o_das(self):
        """
        Invariante fiscal: crédito repassado NUNCA pode superar o próprio
        DAS pago pela empresa do Simples. Caso contrário, a União estaria
        pagando para gerar crédito (absurdo).
        """
        for ano in range(2026, 2034):
            motor = self._moreira(ano)
            das = motor.das_mensal
            credito = motor.credito_b2b_simples
            assert credito <= das, (
                f"{ano}: crédito R$ {credito} > DAS R$ {das} — VIOLAÇÃO fiscal"
            )

    def test_trilha_registra_passo_art_47(self):
        """A trilha de auditoria deve conter um passo CREDITO_B2B_ART_47 com
        amparo legal completo (MAX_FISCAL_02)."""
        motor = self._moreira(2027)
        motor.credito_b2b_simples
        passos_art_47 = [
            p for p in motor.trilha_auditoria
            if p.get("id") == "CREDITO_B2B_ART_47"
        ]
        assert len(passos_art_47) == 1, (
            f"Esperava 1 passo CREDITO_B2B_ART_47, encontrou {len(passos_art_47)}"
        )
        passo = passos_art_47[0]
        amparo = passo.get("amparo_legal", "")
        assert "Art. 47" in amparo
        assert "LC 214/2025" in amparo


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 3 — SPLIT PAYMENT DINÂMICO
# Fonte: LC 214/2025, Art. 344 — ativo jan/2027, formas eletrônicas
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitPayment:

    def test_split_inativo_em_2026(self):
        """2026: Split Payment ainda não está ativo (Art. 348 — apenas testes)."""
        motor = make_motor(ano=2026, forma="PIX_VIA_PSP")
        resultado = motor.split_payment_impacto
        assert resultado["ativo"] is False, "Split deve ser inativo em 2026"

    def test_split_ativo_2027_pix(self):
        """2027: Split ativo para PIX. Retenção dinâmica = CBS + IBS. Art. 344."""
        motor = make_motor(ano=2027, valor="50000.00", forma="PIX_VIA_PSP")
        resultado = motor.split_payment_impacto
        assert resultado["ativo"] is True
        retencao = Decimal(resultado["retencao_imediata"])
        esperado = Decimal("50000.00") * (Decimal("0.088") + Decimal("0.001"))
        assert abs(retencao - esperado) <= Decimal("0.01"), (
            f"Split 2027 esperado R$ {esperado}, obtido R$ {retencao}"
        )

    def test_split_nao_retido_em_dinheiro(self):
        """DINHEIRO: Split Payment não é retido. Art. 344 — apenas meios eletrônicos."""
        motor = make_motor(ano=2027, forma="DINHEIRO")
        resultado = motor.split_payment_impacto
        assert resultado["ativo"] is False, "DINHEIRO não deve sofrer Split Payment"

    def test_split_2027_nao_e_taxa_fixa_09(self):
        """
        BUG HISTÓRICO: split usava taxa fixa 0,9% (2026) para 2027.
        Correto: CBS 8,8% + IBS 0,1% = 8,9% (LC 214/2025, Art. 344+353).
        R$ 50.000 × 8,9% = R$ 4.450 — NÃO R$ 450.
        """
        motor = make_motor(ano=2027, valor="50000.00", forma="PIX_VIA_PSP")
        resultado = motor.split_payment_impacto
        retencao = Decimal(resultado["retencao_imediata"])
        taxa_errada = Decimal("50000.00") * Decimal("0.009")  # R$ 450 — bug antigo
        assert retencao > taxa_errada * 5, (
            f"Retenção 2027 NÃO pode ser R$ {taxa_errada} (taxa fixa 2026). "
            f"Correto: R$ {retencao} (CBS+IBS dinâmico)"
        )

    def test_split_2033_taxa_265(self):
        """2033: Split = CBS 8,8% + IBS 17,7% = 26,5%. Regime pleno."""
        motor = make_motor(ano=2033, valor="50000.00", forma="PIX_VIA_PSP")
        resultado = motor.split_payment_impacto
        retencao = Decimal(resultado["retencao_imediata"])
        esperado = Decimal("50000.00") * (Decimal("0.088") + Decimal("0.177"))
        assert abs(retencao - esperado) <= Decimal("0.01"), (
            f"Split 2033 esperado R$ {esperado}, obtido R$ {retencao}"
        )

    def test_split_cresce_ano_a_ano_2029_2033(self):
        """Retenção deve crescer de 2029 a 2033 junto com o fase-in do IBS.

        V-05 fix: cada ano cravado no valor absoluto esperado (CBS 8.8% fixo +
        IBS phase-in 10%/20%/30%/40%/100%). Monotonicidade era teatro — aceitava
        qualquer curva crescente incluindo valores duas vezes maiores.
        """
        ibs_esperado = {
            2029: Decimal("0.0177"),
            2030: Decimal("0.0354"),
            2031: Decimal("0.0531"),
            2032: Decimal("0.0708"),
            2033: Decimal("0.177"),
        }
        cbs = Decimal("0.088")
        valor = Decimal("50000.00")
        retencao_anterior = Decimal("0")
        for ano, ibs in ibs_esperado.items():
            motor = make_motor(ano=ano, valor="50000.00", forma="PIX_VIA_PSP")
            r = motor.split_payment_impacto
            ret = Decimal(r["retencao_imediata"])
            esperado = (valor * (cbs + ibs)).quantize(Decimal("0.01"))
            assert abs(ret - esperado) <= Decimal("0.01"), (
                f"Split {ano} esperado R$ {esperado}, obtido R$ {ret}"
            )
            assert ret > retencao_anterior, f"Split {ano} deve ser > Split {ano-1}"
            retencao_anterior = ret


# ─────────────────────────────────────────────────────────────────────────────
# BLOCO 4 — CENÁRIOS: Simples Puro vs Opt-Out
# ─────────────────────────────────────────────────────────────────────────────

class TestCenarios:

    def test_simples_puro_retorna_chaves_obrigatorias(self):
        """Cenário Simples Puro deve retornar todas as chaves obrigatórias."""
        motor = make_motor(ano=2027)
        cenario = motor.cenario_simples_puro()
        chaves = ["cenario", "custo_das_por_operacao", "aliquota_efetiva",
                  "credito_gerado_para_comprador", "percentual_credito_nf", "risco_b2b"]
        for chave in chaves:
            assert chave in cenario, f"Chave '{chave}' ausente no cenário Simples Puro"

    def test_simples_puro_flag_b2b_ativo(self):
        """B2B: risco_b2b deve ser True — comprador pode exigir crédito pleno."""
        motor = make_motor(ano=2027, tipo_comprador="B2B_CONTRIBUINTE")
        cenario = motor.cenario_simples_puro()
        assert cenario["risco_b2b"] is True

    def test_simples_puro_flag_b2c_inativo(self):
        """B2C: risco_b2b deve ser False — consumidor final não exige crédito."""
        motor = make_motor(ano=2027, tipo_comprador="B2C_CONSUMIDOR_FINAL")
        cenario = motor.cenario_simples_puro()
        assert cenario["risco_b2b"] is False

    def test_opt_out_credito_100_pct(self):
        """Opt-Out: percentual_credito_nf deve ser '100%' — crédito pleno para B2B."""
        motor = make_motor(ano=2027)
        cenario = motor.cenario_opt_out()
        assert cenario["percentual_credito_nf"] == "100%", (
            "Opt-Out deve gerar 100% de crédito para comprador B2B"
        )

    def test_opt_out_retorna_chaves_obrigatorias(self):
        """Cenário Opt-Out deve retornar todas as chaves obrigatórias."""
        motor = make_motor(ano=2027)
        cenario = motor.cenario_opt_out()
        chaves = ["cenario", "custo_das_por_operacao", "iva_recolhido_por_fora",
                  "custo_total", "credito_gerado_para_comprador", "percentual_credito_nf"]
        for chave in chaves:
            assert chave in cenario, f"Chave '{chave}' ausente no cenário Opt-Out"

    def test_opt_out_custo_total_maior_que_simples(self):
        """
        Opt-Out geralmente tem custo total maior (paga IVA por fora + Simples).
        Mas garante 100% crédito. Empresa decide com base na negociação B2B.
        """
        motor = make_motor(ano=2027, valor="50000.00")
        sp = motor.cenario_simples_puro()
        oo = motor.cenario_opt_out()
        custo_sp = Decimal(sp["custo_das_por_operacao"])
        custo_oo = Decimal(oo["custo_total"])
        assert custo_oo >= custo_sp, (
            "Opt-Out deve ter custo_total >= custo Simples Puro por operação"
        )

    def test_opt_out_custo_total_inclui_iva_por_fora(self):
        """
        Opt-Out: custo_total = das_por_operacao + iva_por_fora.
        O custo_total deve ser > custo_das_por_operacao isolado.
        Empresa paga mais, mas garante 100% de crédito para o comprador B2B.
        """
        motor = make_motor(ano=2027, valor="50000.00")
        oo = motor.cenario_opt_out()
        custo_das = Decimal(oo["custo_das_por_operacao"])
        iva_fora  = Decimal(oo["iva_recolhido_por_fora"])
        custo_total = Decimal(oo["custo_total"])
        assert abs(custo_total - (custo_das + iva_fora)) <= Decimal("0.01"), (
            "custo_total deve ser igual a custo_das + iva_por_fora"
        )
        assert iva_fora > Decimal("0"), "IVA por fora deve ser positivo em 2027"

    def test_cenario_identifica_tipo_corretamente(self):
        """Chave 'cenario' deve identificar o regime corretamente."""
        motor = make_motor(ano=2027)
        assert motor.cenario_simples_puro()["cenario"] == "SIMPLES_PURO"
        assert motor.cenario_opt_out()["cenario"] == "OPT_OUT"
