import logging
from decimal import Decimal

from motor_tributario import EmpresaFornecedora

# Configura logging para capturar avisos de conversão do motor
logging.basicConfig(level=logging.INFO)

def debug_fornecedora():
    """
    Script utilitário para validar se uma massa de dados é compatível
    com o esquema rigoroso de EmpresaFornecedora do Motor.
    """
    try:
        # Exemplo de massa de dados (Substitua pelos dados que deseja testar)
        d = {
            'cnpj': '06.990.590/0001-23',          # CNPJ deve ser VÁLIDO (Módulo 11)
            'razao_social': 'EMPRESA TESTE LTDA',
            'regime': 'SIMPLES',                   # SIMPLES | PRESUMIDO | REAL | MEI
            'cnae_principal': '4757100',           # 7 dígitos
            'uf_origem': 'SP',                     # 2 letras
            'faturamento_12m': Decimal('500000.00') # RBT12
        }

        print(f"--- Iniciando validação para: {d['razao_social']} ---")
        empresa = EmpresaFornecedora(**d)
        print("✅ SUCESSO: Os dados são compatíveis com o Motor.")
        print(f"Objeto instanciado: {empresa.model_dump_json(indent=2)}")

    except Exception as e:
        print("\n❌ ERRO DE VALIDAÇÃO DETECTADO:")
        print("-" * 30)
        print(e)
        print("-" * 30)
        print("Dica: Verifique se o CNPJ é real e se todos os campos obrigatórios estão presentes.")

if __name__ == "__main__":
    debug_fornecedora()
