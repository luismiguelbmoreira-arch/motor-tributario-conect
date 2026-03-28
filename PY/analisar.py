"""
analisar.py — Motor Tributário Conect: Análise Interativa
==========================================================
USE: preencha os dados da empresa abaixo e rode:
  python PY/analisar.py

Resultado: diagnóstico completo + comparação cenários + alertas.
Para auditoria e-CAC: compare o campo "das_mensal" com o DAS do PGDAS-D.

LGPD: dados processados em RAM, zerados após análise (purge automático).
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from decimal import Decimal
from datetime import date
import json

from motor_tributario import (
    EmpresaFornecedora,
    EmpresaCompradora,
    OperacaoFiscal,
    MotorReformaTributaria,
)

# ═══════════════════════════════════════════════════════════════════════════════
# PREENCHA AQUI OS DADOS DO CLIENTE
# ═══════════════════════════════════════════════════════════════════════════════

EMPRESA = EmpresaFornecedora(
    cnpj="11.222.333/0001-81",          # CNPJ completo com pontuação
    razao_social="Empresa Teste Ltda",   # Razão social
    regime="SIMPLES",                    # SIMPLES | PRESUMIDO | REAL
    cnae_principal="4711302",            # CNAE 7 dígitos (sem traço/ponto)
    uf_origem="SP",                      # UF de origem
    faturamento_12m=Decimal("800000.00"),# RBT12 (faturamento acumulado 12 meses)
    folha_salarios_12m=None,             # Folha 12 meses (deixe None se não aplicável)
)

COMPRADOR = EmpresaCompradora(
    tipo="B2B_CONTRIBUINTE",             # B2B_CONTRIBUINTE | B2C_CONSUMIDOR_FINAL
    uf_destino="SP",
    regime="REAL",                       # regime do comprador (REAL | PRESUMIDO | SIMPLES)
)

OPERACAO = OperacaoFiscal(
    data_emissao=date(2026, 3, 26),      # Data da NF
    valor_operacao=Decimal("50000.00"),  # Valor da operação
    ncm_nbs="84099190",                  # NCM 8 dígitos
    forma_recebimento="PIX_BOLETO",      # DINHEIRO | PIX_BOLETO | CARTAO
)

# ═══════════════════════════════════════════════════════════════════════════════
# ANÁLISE — NÃO ALTERAR ABAIXO
# ═══════════════════════════════════════════════════════════════════════════════

def formatar_brl(valor_str: str) -> str:
    try:
        v = Decimal(valor_str)
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return valor_str


def imprimir_diagnostico(diag: dict) -> None:
    print("\n" + "=" * 65)
    print("  DIAGNÓSTICO — MOTOR TRIBUTÁRIO CONECT v1.0")
    print("=" * 65)

    emp = diag.get("empresa", {})
    print(f"\n  EMPRESA")
    print(f"  Regime: {emp.get('regime')} | Anexo: {emp.get('anexo_simples')} | Faixa: {emp.get('faixa')}")
    print(f"  RBT12:  {formatar_brl(emp.get('rbt12','0'))}")
    print(f"  Fator R: {emp.get('fator_r') or 'N/A'}")

    ali = diag.get("aliquotas", {})
    print(f"\n  ALÍQUOTAS")
    print(f"  Efetiva total:  {Decimal(ali.get('efetiva_total','0'))*100:.4f}%")
    print(f"  DAS mensal:     {formatar_brl(ali.get('das_mensal','0'))}")
    print(f"  ↳ Para e-CAC:  compare este valor com PGDAS-D")

    cen = diag.get("cenarios", {})
    sp = cen.get("simples_puro", {})
    oo = cen.get("opt_out", {})

    print(f"\n  CENÁRIOS (por operação R$ {formatar_brl(str(OPERACAO.valor_operacao))})")
    print(f"  {'Campo':<30} {'Simples Puro':>14} {'Opt-Out':>14}")
    print(f"  {'-'*58}")
    print(f"  {'Custo DAS (operação)':<30} {formatar_brl(sp.get('custo_das_por_operacao','0')):>14} {formatar_brl(oo.get('custo_das_por_operacao','0')):>14}")
    print(f"  {'IVA pago por fora':<30} {'—':>14} {formatar_brl(oo.get('iva_recolhido_por_fora','0')):>14}")
    print(f"  {'Custo total':<30} {formatar_brl(sp.get('custo_total','0')):>14} {formatar_brl(oo.get('custo_total','0')):>14}")
    print(f"  {'Crédito gerado p/ comprador':<30} {formatar_brl(sp.get('credito_gerado_para_comprador','0')):>14} {formatar_brl(oo.get('credito_gerado_para_comprador','0')):>14}")
    print(f"  {'% crédito da NF':<30} {sp.get('percentual_credito_nf','?'):>14} {oo.get('percentual_credito_nf','?'):>14}")
    print(f"  {'Risco B2B':<30} {'⚠ SIM' if sp.get('risco_b2b') else 'não':>14} {'não':>14}")

    recom = cen.get("recomendacao", "—")
    print(f"\n  RECOMENDAÇÃO: {recom}")

    split = diag.get("split_payment", {})
    print(f"\n  SPLIT PAYMENT")
    if split.get("ativo"):
        print(f"  ⚠  ATIVO — Retenção: {formatar_brl(split.get('retencao_imediata','0'))} ({split.get('percentual_retencao','?')})")
        print(f"  Impacto anual: {split.get('reducao_mensal_estimada','?')}")
    else:
        print(f"  Inativo ({split.get('motivo','—')})")

    alertas = diag.get("alertas", [])
    if alertas:
        print(f"\n  ALERTAS ({len(alertas)})")
        for a in alertas:
            nivel = a.get("nivel", "INFO")
            icone = {"CRITICO": "🔴", "ALTO": "🟠", "MEDIO": "🟡", "INFO": "🔵"}.get(nivel, "•")
            print(f"  {icone} [{nivel}] {a.get('mensagem','')}")

    meta = diag.get("meta", {})
    print(f"\n  ⚠  {meta.get('aviso_legal','Validar com profissional habilitado.')}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    print("\nMotor Tributário Conect — Iniciando análise...")

    try:
        motor = MotorReformaTributaria(EMPRESA, COMPRADOR, OPERACAO)

        # Exibir cálculos intermediários para auditoria e-CAC
        rbt12 = motor.calcular_rbt12()
        anexo = motor.determinar_anexo()
        aliq  = motor.calcular_aliquota_efetiva()
        das   = motor.calcular_das_mensal()
        fr    = motor.calcular_fator_r()

        print(f"\n  [AUDITORIA e-CAC]")
        print(f"  RBT12:              {formatar_brl(str(rbt12))}")
        print(f"  Anexo:              {anexo}")
        print(f"  Alíquota efetiva:   {aliq * 100:.6f}%")
        print(f"  DAS mensal:         {formatar_brl(str(das))}")
        if fr:
            print(f"  Fator R:            {fr:.4f} ({'Anexo III' if fr >= Decimal('0.28') else 'Anexo V'})")

        diag = motor.gerar_diagnostico()  # purge() automático após este ponto
        imprimir_diagnostico(diag)

    except Exception as e:
        print(f"\n  ERRO: {e}")
        sys.exit(1)
