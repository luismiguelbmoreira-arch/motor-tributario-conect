---
description: Relatório on-demand de cobertura por módulo. Mostra ratio LOC:teste, funções descobertas e status vs metas do CI.
allowed-tools: Bash
---

Execute os comandos abaixo em sequência e produza o relatório final.

## Passo 1 — Rodar testes com cobertura

```bash
cd PY && python -m pytest tests/ -q --tb=no -p no:warnings \
  --cov=. \
  --cov-config=.coveragerc \
  --cov-report=term-missing \
  2>&1 | tail -40
```

## Passo 2 — Cobertura por módulo crítico

```bash
cd PY && coverage report \
  --include="motor_tributario.py,regimes/*.py,storage_cifrado.py,validadores.py,tabelas_simples.py" \
  --show-missing \
  --sort=cover \
  2>&1
```

## Passo 3 — Funções sem referência nos testes

```bash
cd PY && python -c "
import ast, os

def get_funcs(path):
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    return [(n.name, n.lineno) for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

test_corpus = ''
for f in os.listdir('tests'):
    if f.endswith('.py'):
        test_corpus += open(f'tests/{f}', encoding='utf-8').read()

modulos = {
    'motor_tributario.py': get_funcs('motor_tributario.py'),
    'regimes/lucro_presumido.py': get_funcs('regimes/lucro_presumido.py'),
    'regimes/lucro_real.py': get_funcs('regimes/lucro_real.py'),
    'regimes/mei.py': get_funcs('regimes/mei.py'),
    'storage_cifrado.py': get_funcs('storage_cifrado.py'),
}

print('FUNÇÕES SEM REFERÊNCIA NOS TESTES')
print('='*50)
for modulo, funcs in modulos.items():
    gaps = [(n, l) for n, l in funcs if n not in test_corpus and not n.startswith('__')]
    pct = len(gaps) / len(funcs) * 100 if funcs else 0
    status = '🔴' if pct > 40 else '🟡' if pct > 20 else '✅'
    print(f'{status} {modulo}: {len(gaps)}/{len(funcs)} descobertas ({pct:.0f}%)')
    for name, line in gaps:
        print(f'   L{line}: {name}')
    print()
"
```

## Passo 4 — Relatório Final

Com base nos resultados acima, produza este resumo:

```
══════════════════════════════════════════════
AUDITORIA DE COBERTURA — Motor Tributário
Data: [hoje]
══════════════════════════════════════════════

COBERTURA DE LINHAS (pytest-cov)
  Módulo                  │ Cobertura │ Meta CI │ Status
  motor_tributario.py     │    XX%    │   ≥85%  │ ✅/❌
  regimes/*.py            │    XX%    │   ≥90%  │ ✅/❌
  storage_cifrado.py      │    XX%    │   ≥80%  │ ✅/❌
  validadores.py          │    XX%    │   ≥80%  │ ✅/❌

FUNÇÕES DESCOBERTAS (referência em testes)
  motor_tributario.py     │  X/41   │ 🔴/🟡/✅
  regimes/lucro_real.py   │  X/XX   │ 🔴/🟡/✅
  regimes/mei.py          │  X/XX   │ 🔴/🟡/✅

TOP 3 GAPS PRIORITÁRIOS
  1. [função] L[N] — [módulo] — por que é crítica
  2. [função] L[N] — [módulo]
  3. [função] L[N] — [módulo]

AÇÃO RECOMENDADA
  [próximo teste a escrever para maior impacto no ratio]
══════════════════════════════════════════════
```
