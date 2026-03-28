
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from decimal import Decimal
from datetime import date
from motor_tributario import (
    EmpresaFornecedora,
    EmpresaCompradora,
    OperacaoFiscal,
    MotorReformaTributaria,
    Atividade,
)

def test_err008_multi_atividade_confiar():
    """
    Reproduz o caso CONFI-AR 01/2026.
    RBT12: R$ 1.158.957,45 (resulta em AE I=8.7586% e AE III=12.9248%)
    
    Atividade 1: RPA R$ 4.929,43  | Anexo I   | Sem ST
    Atividade 2: RPA R$ 32.970,57 | Anexo I   | Com ST ICMS
    Atividade 3: RPA R$ 95.594,08 | Anexo III | Sem ISS retido
    Atividade 4: RPA R$ 5.650,00  | Anexo III | Com ISS retido
    
    DAS e-CAC: R$ 15.200,39
    DAS esperado (manual): R$ 15.185,94
    """
    rbt12 = Decimal("1158957.45")
    
    atividades = [
        Atividade(receita=Decimal("4929.43"),  anexo="I"),
        Atividade(receita=Decimal("32970.57"), anexo="I",   icms_st=True),
        Atividade(receita=Decimal("95594.08"), anexo="III"),
        Atividade(receita=Decimal("5650.00"),  anexo="III", iss_retido=True),
    ]
    
    fornecedora = EmpresaFornecedora(
        cnpj="08.172.834/0001-96",
        razao_social="CONFI-AR CONDICIONADO LTDA",
        regime="SIMPLES",
        cnae_principal="4321500", # CNAE fictício para teste
        uf_origem="SP",
        faturamento_12m=rbt12,
        atividades=atividades,
        anexo_simples="III"
    )
    
    compradora = EmpresaCompradora(tipo="B2C_CONSUMIDOR_FINAL", uf_destino="SP")
    
    operacao = OperacaoFiscal(
        data_emissao=date(2026, 1, 15),
        valor_operacao=Decimal("139144.08"), # Soma das receitas
        ncm_nbs="84151011",
        rpa_mensal=Decimal("139144.08")
    )
    
    motor = MotorReformaTributaria(fornecedora, compradora, operacao)
    
    # Atualmente o motor ignora o campo 'atividades' no cálculo do DAS
    das_atual = motor.calcular_das_mensal()
    print(f"\nDAS atual: R$ {das_atual}")
    
    # O esperado com multi-atividade é ~15185.94
    # Se falhar (retornando ~17984), o bug está presente.
    assert das_atual == Decimal("15185.94")

if __name__ == "__main__":
    test_err008_multi_atividade_confiar()
