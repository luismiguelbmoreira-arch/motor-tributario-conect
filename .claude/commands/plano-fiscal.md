---
description: Plan-First obrigatório para qualquer mudança de regra fiscal. Gera plano com lei + fórmula + impacto + testes ANTES de qualquer código.
allowed-tools: Read, Glob, Grep, Agent
---

Você foi invocado com o protocolo **Plan-First Fiscal** para:

**Regra:** $ARGUMENTS

---

## PROTOCOLO ANTI-VIBE FISCAL — Execute EM ORDEM. Zero código antes do Passo 5.

### Passo 1 — Leitura de Contexto

Leia os arquivos relevantes para entender o que já existe:

- Arquivos do regime afetado em `PY/regimes/`
- `PY/motor_tributario.py` — busque funções relacionadas à regra
- `PY/tabelas_simples.py` — constantes que podem ser afetadas (FROZEN — não editar)
- `PY/tests/` — testes existentes relacionados à regra

Identifique:
- O que já está implementado
- O que precisa mudar
- Quais testes já cobrem o caminho afetado

---

### Passo 2 — Validação Legal (Luiz Moreira)

Invoque o agente **luiz-moreira** com a seguinte instrução:

> "Valide a regra fiscal: $ARGUMENTS
> Preciso de: (1) artigo de lei exato, (2) fórmula matemática em Decimal, (3) impacto de caixa estimado em R$, (4) riscos fiscais."

Não prossiga sem a validação de Luiz Moreira.

---

### Passo 3 — Plano Estruturado

Com base no contexto (Passo 1) e validação legal (Passo 2), produza este documento:

```
═══════════════════════════════════════════════════════
PLANO FISCAL — $ARGUMENTS
Data: [hoje]
Status: AGUARDANDO APROVAÇÃO
═══════════════════════════════════════════════════════

1. AMPARO LEGAL
   ├── Lei principal: [ex: LC 123/2006, Art. 18, § 24]
   ├── Leis complementares: [se houver]
   └── Validado por: Luiz Moreira ✓

2. FÓRMULA (Decimal)
   [pseudocódigo com Decimal, sem float]
   ex:
   resultado = (base * Decimal("0.107") - parcela) / base
   resultado = resultado.quantize(Decimal("0.0001"), ROUND_HALF_UP)

3. ARQUIVOS A MODIFICAR
   ┌─ Arquivo              │ O que muda
   ├─ PY/regimes/X.py      │ [descrição]
   ├─ PY/motor_tributario.py│ [descrição]
   └─ NÃO TOCAR: tabelas_simples.py (FROZEN)

4. TESTES NECESSÁRIOS (ratio mínimo 1:7 para módulos críticos)
   LOC estimado da mudança: ~[N] linhas
   Testes mínimos necessários: ~[N/7] testes
   [ ] test_[nome]_caso_basico
   [ ] test_[nome]_limite_superior
   [ ] test_[nome]_limite_inferior
   [ ] test_[nome]_guard_clause
   [ ] test_[nome]_decimal_precision
   [ ] test_[nome]_amparo_legal_na_trilha
   [ ] test_[nome]_integracao_motor

5. DELTA TRIBUTÁRIO
   Impacto para caso real (exemplo numérico):
   Antes: R$ [X]
   Depois: R$ [Y]
   Delta: R$ [Z] ([+/-]%)

6. RISCOS
   [ ] Guard clause necessária?
   [ ] tabelas_simples.py precisa de atualização? (requer aprovação separada)
   [ ] Compatibilidade com cronograma 2026-2033?
   [ ] Impacto em outros regimes?

7. SEQUÊNCIA DE IMPLEMENTAÇÃO
   1. Escrever testes primeiro (TDD)
   2. Implementar fórmula (O Viciado)
   3. Confirmar ratio teste/LOC
   4. Confirmar amparo_legal na trilha_auditoria
   5. Rodar pytest completo
═══════════════════════════════════════════════════════
```

---

### Passo 4 — PAUSA OBRIGATÓRIA

**PARE AQUI.** Apresente o plano completo ao usuário.

Aguarde o usuário digitar **APROVADO** explicitamente.

- Se resposta for "APROVADO": execute o Passo 5
- Se resposta trouxer ajustes: revise o plano e repita o Passo 4
- Se não houver resposta clara: aguarde — não presuma aprovação

---

### Passo 5 — Implementação (só após APROVADO)

1. Escrever testes primeiro (TDD obrigatório)
2. Invocar agente **o-viciado** com o plano aprovado como contexto
3. O Viciado implementa com:
   - `Decimal` + `ROUND_HALF_UP` (proibido float)
   - `amparo_legal` preenchido em cada passo da `trilha_auditoria`
   - Guard clause se aplicável
4. Rodar `python -m pytest tests/ -q --tb=short` e confirmar 100% passando
5. Confirmar ratio teste/LOC no módulo afetado

**Sem APROVADO explícito, nenhuma linha de código é escrita.**
