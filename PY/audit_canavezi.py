# -*- coding: utf-8 -*-
"""
audit_canavezi.py — Auditoria e-CAC: REFRIGERACAO CANAVEZI LTDA
Certificado pela <fiscal_calculator_engine>
"""
import sys, os
import io
import json

# Força saída UTF-8 no Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))

from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from motor_tributario import (
    EmpresaFornecedora, EmpresaCompradora, OperacaoFiscal, MotorReformaTributaria
)

# ── PARAMETRIZAÇÃO DA SAÍDA (Simulação da Extração IA para Entrada Motor) ──────
# IA extraiu estes parâmetros do documento antigo para o novo formato
CONFIG_DADO_EXTRAIDO = {
    "cnpj": "54.657.895/0001-60",
    "faturamento_12m": Decimal("2014303.11"),
    "rpa_mes": Decimal("180817.99"),
    "rpa_st": Decimal("47668.69"),
    "das_pago": Decimal("16428.83")
}

# ── CONFIGURAÇÃO DO MOTOR ─────────────────────────────────────────────────────
fornecedora = EmpresaFornecedora(
    cnpj=CONFIG_DADO_EXTRAIDO["cnpj"],
    razao_social="REFRIGERACAO CANAVEZI LTDA",
    regime="SIMPLES",
    cnae_principal="4757100",
    uf_origem="SP",
    faturamento_12m=CONFIG_DADO_EXTRAIDO["faturamento_12m"],
    anexo_simples="I",
    receita_com_st_icms=CONFIG_DADO_EXTRAIDO["rpa_st"],
)
compradora = EmpresaCompradora(tipo="B2C_CONSUMIDOR_FINAL", uf_destino="SP")
operacao   = OperacaoFiscal(
    data_emissao=date(2026, 1, 1),
    valor_operacao=CONFIG_DADO_EXTRAIDO["rpa_mes"],
    rpa_mensal=CONFIG_DADO_EXTRAIDO["rpa_mes"],
    ncm_nbs="84099190",
)

motor = MotorReformaTributaria(fornecedora, compradora, operacao)

# ── CÁLCULO PRECISO (Antes do Purge) ──────────────────────────────────────────
# Capturamos o valor real considerando ST para o embate
das_motor_real = motor.calcular_das_mensal()

# ── EXECUÇÃO DO DIAGNÓSTICO (Gera Trilha de Auditoria e executa Purge) ────────
diagnostico = motor.gerar_diagnostico()

# ── EXIBIÇÃO: TRILHA DE AUDITORIA (MAX_FISCAL_01) ─────────────────────────────
print("\n" + "=" * 80)
print("  TRILHA DE AUDITORIA FISCAL - [MOTOR CERTIFICADO]")
print("=" * 80)

for passo in diagnostico["trilha_auditoria"]:
    print(f"\n[{passo['id']}] {passo['titulo']}")
    print(f"  Lei: {passo['amparo_legal']}")
    print(f"  Cálculo: {passo['formula']}")
    if passo['detalhe']:
        print(f"  Nota: {passo['detalhe']}")

print("\n" + "=" * 80)
print("  RESULTADO DO EMBATE (MOTOR vs e-CAC)")
print("=" * 80)
das_ecac = CONFIG_DADO_EXTRAIDO["das_pago"]

print(f"  DAS MOTOR CALCULADO (COM ST) : R$ {das_motor_real:>15,.2f}")
print(f"  DAS e-CAC ORIGINAL           : R$ {das_ecac:>15,.2f}")
delta = abs(das_motor_real - das_ecac)
print(f"  DELTA DE PRECISÃO            : R$ {delta:>15,.2f}")

print("\n" + "=" * 80)
print("  VEREDICTO DE CALIBRAÇÃO")
print("=" * 80)
if delta <= Decimal("50.00"): # Margem para segregação de ICMS-ST em sistemas antigos
    print("  ✅ CALIBRADO - Lógica de Reforma Tributária e Anexo I validada.")
    print("  A IA parametrizou a entrada; o Motor (auditável) garantiu a exatidão.")
else:
    print(f"  ⚠️ DESCALIBRADO - Delta de R$ {delta:,.2f}. Requer ajuste de partilha.")

print("=" * 80 + "\n")
