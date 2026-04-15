import os
import re
from pathlib import Path

def setup_imports(path):
    for root, dirs, files in os.walk(path):
        if '.venv' in dirs:
            dirs.remove('.venv')
        if '__pycache__' in dirs:
            dirs.remove('__pycache__')
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Substituições base
                content = re.sub(r'^from motor_tributario import', 'from core.motor_tributario import', content, flags=re.MULTILINE)
                content = re.sub(r'^import motor_tributario', 'import core.motor_tributario as motor_tributario', content, flags=re.MULTILINE)
                
                content = re.sub(r'^from planejamento_tributario import', 'from core.planejamento_tributario import', content, flags=re.MULTILINE)
                content = re.sub(r'^from tabelas_simples import', 'from core.tabelas_simples import', content, flags=re.MULTILINE)
                content = re.sub(r'^from difal import', 'from core.difal import', content, flags=re.MULTILINE)
                content = re.sub(r'^from guardrails import', 'from core.guardrails import', content, flags=re.MULTILINE)
                
                content = re.sub(r'^from regimes\.', 'from core.regimes.', content, flags=re.MULTILINE)
                content = re.sub(r'^import regimes\.', 'import core.regimes.', content, flags=re.MULTILINE)
                
                content = re.sub(r'^from extrator_pdfs import', 'from services.extrator_pdfs import', content, flags=re.MULTILINE)
                content = re.sub(r'^from relatorio_pdf import', 'from services.relatorio_pdf import', content, flags=re.MULTILINE)
                content = re.sub(r'^from storage_cifrado import', 'from services.storage_cifrado import', content, flags=re.MULTILINE)
                
                # Check for absolute intra-module core imports inside core
                # No issue if all files reference from core.*
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)

if __name__ == "__main__":
    setup_imports(r'c:\Users\EL PUTO MACABRO\Desktop\motor-tributario-conect\PY')
    print("Imports reescritos.")
