# -*- coding: utf-8 -*-
"""
audit_confi_ar.py -- Auditoria e-CAC: CONFI - AR CONDICIONADO LTDA
Compara DAS calculado pelo motor vs DAS oficial PGDAS-D 01/2026.

Dados extraidos dos documentos reais (docs/doc calculo/CONFI_AR/):
  - CNPJ: 08.172.834/0001-96
  - CNAE: 4753900 (Comercio varejista eletrodomesticos) -> multi-atividade
  - RBT12: R$ 1.158.950,86
  - RPA Jan/2026: R$ 139.144,08
  - DAS e-CAC pago: R$ 15.200,39
  - Multi-atividade: 4 atividades (comercio + servicos Anexo III)
  - ICMS-ST parcial: R$ 32.970,57 com ICMS zerado

NOTA: Esta empresa tem multi-atividade (comercio + servicos).
O motor atual nao modela multi-atividade nativamente. Usamos Anexo III
como estimativa (atividade dominante por receita: 72,7% servicos).
Delta esperado: maior que CANAVEZI por limitacao de modelagem.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from motor_tributario import (
    EmpresaFornecedora, EmpresaCompradora, OperacaoFiscal, MotorReformaTributaria
)
from tabelas_simples import DISTRIBUICAO_DAS, obter_faixa_numero

# -- CONSTANTES DO CASO ---------------------------------------------------
DAS_ECAC        = Decimal("15200.39")
RPA             = Decimal("139144.08")
RBT12_REAL      = Decimal("1158950.86")
RPA_COM_ST      = Decimal("32970.57")   # revenda com ICMS-ST (ICMS zerado no DAS)

# Composicao real do DAS conforme PGDAS-D
ECAC_TRIBUTOS = {
    "IRPJ":  Decimal("706.00"),
    "CSLL":  Decimal("574.18"),
    "COFINS":Decimal("2207.78"),
    "PIS":   Decimal("478.96"),
    "CPP":   Decimal("7073.34"),
    "ICMS":  Decimal("144.64"),
    "IPI":   Decimal("0.00"),
    "ISS":   Decimal("4015.49"),
}

# Composicao da receita por atividade (extraido do PGDAS-D)
RPA_REVENDA_SEM_ST = Decimal("4929.43")     # Revenda sem ST (ICMS no DAS)
RPA_REVENDA_COM_ST = Decimal("32970.57")    # Revenda com ST (ICMS zerado)
RPA_SERVICO        = Decimal("95594.08")    # Servicos Anexo III
RPA_SERVICO_RETISS = Decimal("5650.00")     # Servicos com retencao ISS
# Total: 4929.43 + 32970.57 + 95594.08 + 5650.00 = 139.144,08

# -- CONFIGURACAO DO MOTOR ------------------------------------------------
# Tentativa 1: Anexo III (atividade dominante: 72.7% servicos)
fornecedora_iii = EmpresaFornecedora(
    cnpj="08.172.834/0001-96",
    razao_social="CONFI - AR CONDICIONADO LTDA",
    regime="SIMPLES",
    cnae_principal="4753900",
    uf_origem="SP",
    faturamento_12m=RBT12_REAL,
    folha_salarios_12m=None,
    anexo_simples="III",   # Forcado: multi-atividade, servicos dominam (72.7%)
)

# Tentativa 2: Anexo I (CNAE principal eh comercio)
fornecedora_i = EmpresaFornecedora(
    cnpj="08.172.834/0001-96",
    razao_social="CONFI - AR CONDICIONADO LTDA",
    regime="SIMPLES",
    cnae_principal="4753900",
    uf_origem="SP",
    faturamento_12m=RBT12_REAL,
    folha_salarios_12m=None,
    anexo_simples="I",   # Pelo CNAE principal (comercio varejista)
)

compradora = EmpresaCompradora(tipo="B2C_CONSUMIDOR_FINAL", uf_destino="SP")
operacao   = OperacaoFiscal(
    data_emissao=date(2026, 1, 1),
    valor_operacao=RPA,
    ncm_nbs="84159000",   # Aparelhos de ar condicionado
    forma_recebimento="PIX_BOLETO",
)

motor_iii = MotorReformaTributaria(fornecedora_iii, compradora, operacao)
motor_i   = MotorReformaTributaria(fornecedora_i,   compradora, operacao)

# -- CALCULOS -------------------------------------------------------------
rbt12    = motor_iii.calcular_rbt12()
ae_iii   = motor_iii.calcular_aliquota_efetiva()
ae_i     = motor_i.calcular_aliquota_efetiva()
faixa_iii = obter_faixa_numero(rbt12, "III")
faixa_i   = obter_faixa_numero(rbt12, "I")

das_motor_iii      = (RPA * ae_iii).quantize(Decimal("0.01"), ROUND_HALF_UP)
das_motor_i        = (RPA * ae_i).quantize(Decimal("0.01"), ROUND_HALF_UP)

# Ajuste ICMS-ST para Anexo III
dist_iii   = DISTRIBUICAO_DAS.get("III", {}).get(faixa_iii, {})
icms_pct   = dist_iii.get("ICMS", Decimal("0"))
rpa_sem_st = RPA - RPA_COM_ST
das_sem_st = (rpa_sem_st * ae_iii).quantize(Decimal("0.01"), ROUND_HALF_UP)
ae_sem_icms = (ae_iii - ae_iii * icms_pct).quantize(Decimal("0.000001"), ROUND_HALF_UP)
das_com_st  = (RPA_COM_ST * ae_sem_icms).quantize(Decimal("0.01"), ROUND_HALF_UP)
das_ajustado_iii = das_sem_st + das_com_st

# AE efetiva do e-CAC
ae_ecac = (DAS_ECAC / RPA).quantize(Decimal("0.000001"), ROUND_HALF_UP)

print("=" * 65)
print("  AUDITORIA e-CAC  |  CONFI - AR CONDICIONADO LTDA  |  01/2026")
print("=" * 65)
print(f"  CNPJ     : 08.172.834/0001-96")
print(f"  CNAE     : 4753900  (Comercio varejista eletrodomesticos)")
print(f"  RBT12    : R$ {rbt12:>12,.2f}")
print(f"  RPA      : R$ {RPA:>12,.2f}  (receita jan/2026)")
print(f"  AVISO    : MULTI-ATIVIDADE (comercio + servicos)")
print(f"    Revenda sem ST  : R$ {RPA_REVENDA_SEM_ST:>10,.2f}")
print(f"    Revenda com ST  : R$ {RPA_REVENDA_COM_ST:>10,.2f}  (ICMS ja retido)")
print(f"    Servicos Anx III: R$ {RPA_SERVICO:>10,.2f}")
print(f"    Servicos ret.ISS: R$ {RPA_SERVICO_RETISS:>10,.2f}")
print("-" * 65)
print(f"  AE Anexo I  motor  : {float(ae_i)*100:.4f}%   (Faixa {faixa_i})")
print(f"  AE Anexo III motor : {float(ae_iii)*100:.4f}%  (Faixa {faixa_iii})")
print(f"  AE e-CAC (DAS/RPA) : {float(ae_ecac)*100:.4f}%")
print("=" * 65)
print(f"  DAS motor Anexo I            : R$ {das_motor_i:>10,.2f}")
print(f"  DAS motor Anexo III          : R$ {das_motor_iii:>10,.2f}")
print(f"  DAS motor Anx III (ST ajust.): R$ {das_ajustado_iii:>10,.2f}  <- melhor est.")
print(f"  DAS e-CAC (oficial)          : R$ {DAS_ECAC:>10,.2f}  <- referencia")
print("-" * 65)
dif_i   = abs(das_motor_i   - DAS_ECAC)
dif_iii = abs(das_motor_iii - DAS_ECAC)
dif_st  = abs(das_ajustado_iii - DAS_ECAC)
print(f"  Delta Anexo I            : R$ {dif_i:,.2f}")
print(f"  Delta Anexo III          : R$ {dif_iii:,.2f}")
print(f"  Delta Anx III (ST ajust.): R$ {dif_st:,.2f}")
print("=" * 65)

# Distribuicao por tributo (usando melhor estimativa: Anexo III ajustado)
print(f"\n  DISTRIBUICAO DO DAS (Anexo III, Faixa {faixa_iii})")
print(f"  {'Tributo':<8}  {'% partilha':>10}  {'Motor R$':>10}  {'e-CAC R$':>10}  {'Delta R$':>10}")
print(f"  {'-'*8}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*10}")
for tributo in ["IRPJ","CSLL","COFINS","PIS","CPP","ICMS","IPI","ISS"]:
    pct = dist_iii.get(tributo, Decimal("0"))
    val_motor = (das_ajustado_iii * pct).quantize(Decimal("0.01"), ROUND_HALF_UP)
    val_ecac  = ECAC_TRIBUTOS.get(tributo, Decimal("0"))
    delta     = abs(val_motor - val_ecac)
    flag = " <<" if delta > Decimal("100") else ""
    print(f"  {tributo:<8}  {float(pct)*100:>9.2f}%  R${val_motor:>9,.2f}  R${val_ecac:>9,.2f}  R${delta:>8,.2f}{flag}")

print("\n" + "=" * 65)
print("  VEREDICTO")
print("=" * 65)
if dif_st <= Decimal("0.01"):
    print("  CONGELADO - Diferenca <= R$ 0,01. Motor auditavel pela Receita.")
elif dif_st <= Decimal("50.00"):
    print(f"  APROVADO COM RESSALVA - Delta R$ {dif_st:,.2f}.")
elif dif_st <= Decimal("500.00"):
    print(f"  ATENCAO - Delta R$ {dif_st:,.2f}.")
    print("  Causa esperada: motor nao modela multi-atividade.")
else:
    print(f"  FALHOU - Delta R$ {dif_st:,.2f}. Investigar formula.")

print("\n  Nota tecnica:")
print("  CONFI-AR tem 4 atividades distintas no PGDAS-D:")
print("  comercio (Anx I) + servicos (Anx III) + ICMS-ST parcial.")
print("  Motor atual suporta apenas 1 Anexo por empresa.")
print("  NOVO ERRO A REGISTRAR: motor nao modela multi-atividade.")
print("  Solucao futura: campo 'atividades: List[AtividadeSN]' com")
print("  receita, Anexo e flag_ST por atividade.")
print("=" * 65)
