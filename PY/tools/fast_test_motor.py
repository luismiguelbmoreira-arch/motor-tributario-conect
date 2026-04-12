import json
import logging
import sys
from decimal import Decimal
from pathlib import Path

# Ajustar os paths para garantir que consigamos importar do nivel acima (PY/)
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.motor_tributario import EmpresaFornecedora, EmpresaCompradora, OperacaoFiscal, MotorReformaTributaria
from pydantic import ValidationError

logging.basicConfig(level=logging.ERROR) # Omitir logs pesados na std

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

def print_separator(char="=", length=60):    print(char * length)

def formatar_moeda(valor: Decimal) -> str:
    from motor_tributario import _fmt_brl
    return _fmt_brl(valor)

def executar_analise_mock(json_path: str):
    caminho = Path(json_path).resolve()
    base_dir = Path(__file__).parent.parent.parent.resolve()
    
    # Prevenção de Path Traversal (LFI)
    if not str(caminho).startswith(str(base_dir)):
        print(f"❌ Erro de Segurança (Path Traversal): Tentativa de acesso fora do diretório base bloqueada [{caminho.name}].")
        sys.exit(1)

    if not caminho.exists() or not caminho.is_file():
        print(f"❌ Erro: O arquivo de teste {json_path} não foi encontrado ou não é um arquivo válido.")
        sys.exit(1)
        
    with open(caminho, 'r', encoding='utf-8') as f:
        try:
            payload = json.load(f)
        except json.JSONDecodeError as e:
            print(f"❌ Erro de Formatação JSON: {e}")
            sys.exit(1)

    print_separator()
    print(f"⚙️  MOTOR OFF-LINE INICIADO  ⚙️")
    print(f"📂 Lendo Caso: {caminho.name}")
    print_separator()

    # Validação Pydantic Independente
    try:
        print(">> Instanciando Guardrails (Pydantic V2)...")
        fornecedora = EmpresaFornecedora(**payload['fornecedora'])
        compradora = EmpresaCompradora(**payload['compradora'])
        operacao = OperacaoFiscal(**payload['operacao'])
        print("✅ Dados higienizados para o Motor.")
    except ValidationError as e:
        print("\n❌ ALERTA ESTRUTURAL — O Schema rejeitou os dados:")
        for erro in e.errors():
            campo = " -> ".join([str(loc) for loc in erro['loc']])
            mensagem = erro['msg']
            print(f"  [CAMPO: {campo}] = {mensagem}")
        sys.exit(1)

    # Executando o Motor Central
    print("\n>> Computando Carga Tributária Transicional...")
    print_separator('-')
    
    # Motor suporta context_manager para LGPD purge() automatico, mas como é script vamos estanciar seco para debug
    motor = MotorReformaTributaria(fornecedora, compradora, operacao)
    
    # Executamos FASE 5: A fase 5 vai ate onde der, para debug podemos só extrair os raw metrics
    engine = motor.obter_engine_regime()
    
    print(f"📌 Regime Fornecedora: {fornecedora.regime}")
    if engine:
        print(f"📌 Engine Detectada: {engine.__class__.__name__}")
    
    try:
        diagnostico = motor.gerar_diagnostico()
        
        print("\n🏆 RESULTADO PRELIMINAR BÁSICO 🏆")
        print(f" Passos da Trilha Mapeados: {len(motor.trilha_auditoria)}")
        print("\n[DIAGNÓSTICO OFICIAL DA API]")
        print(json.dumps(diagnostico, indent=2, ensure_ascii=False))
        
    except Exception as e:
        print(f"❌ Falha massiva no Motor: {e}")
    finally:
        motor.purge()

    print_separator()
    print("DICA: Para imprimir toda a memória de cálculo de todos os cenários, edite o fast_test_motor.py para dar dump na `motor.trilha_auditoria`.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso correto:")
        print("  python fast_test_motor.py <caminho_para_payload_json>")
        print("\nExemplo:")
        print("  python PY/tools/fast_test_motor.py samples/casos_clinicos/teste1.json")
        sys.exit(0)
        
    executar_analise_mock(sys.argv[1])
