---
name: verify-trilha
description: Verifica integridade HMAC de uma trilha de auditoria do Motor Tributário Conect (pós-incidente, defesa fiscal, rollback)
disable-model-invocation: true
---

# verify-trilha — Verificação HMAC da Trilha de Auditoria

Ferramenta **user-only** que valida a integridade criptográfica da trilha de
auditoria gerada pelo Motor Tributário Conect. Tampa o passo "Validar integridade
das trilhas HMAC" do `docs/rollback_rfc.md`.

## Quando usar

- Após um rollback de produção (checklist do RFC)
- Antes de apresentar um dossiê em fiscalização/defesa jurídica
- Quando auditor externo pede prova de não-adulteração
- Em scripts de CI que validam exports de diagnóstico

## Como usar

### Pré-requisitos

A variável de ambiente `MOTOR_CONECT_MASTER_KEY` deve estar setada com a mesma
chave que gerou as assinaturas (ver `PY/.env` ou cofre de produção).

### Entradas aceitas

1. **Trilha exportada** (JSON com lista de passos) — formato direto.
2. **Diagnóstico completo** (JSON com campo `trilha_auditoria`) — extrai automaticamente.

### Comandos

```bash
# A partir da pasta PY/
cd PY

# Verifica um JSON com a trilha exportada
python -m tools.verify_trilha --trilha ../data/exports/trilha_moreira.json

# Verifica a trilha embutida em um diagnóstico completo
python -m tools.verify_trilha --diagnostico ../data/exports/diagnostico_moreira.json

# Modo silencioso (só exit code — útil em CI)
python -m tools.verify_trilha --trilha ../data/exports/trilha.json --quiet
```

### Exit codes

| Código | Significado |
|---|---|
| **0** | Trilha 100% íntegra — todos os passos com HMAC válido |
| **1** | Trilha adulterada — pelo menos 1 passo com HMAC inválido (lista impressa) |
| **2** | Erro de I/O, JSON malformado ou falha ao verificar |

## Exemplo de output

### Trilha íntegra

```
Total de passos: 47
Íntegros:        47
Adulterados:     0

✓ TRILHA ÍNTEGRA — nenhuma mutação detectada.
```

### Trilha adulterada

```
Total de passos: 47
Íntegros:        45
Adulterados:     2

✗ TRILHA ADULTERADA — passos com HMAC inválido:
  [12] FASE2_ALIQUOTA — Alíquota Efetiva
  [31] SEMAFORO_DAS — Comparação DAS calculado vs pago
```

## Arquitetura

- **CLI**: `PY/tools/verify_trilha.py`
- **Engine**: `PY/observability/hmac_trilha.verificar_trilha()`
- **Chave**: HKDF derivada de `MOTOR_CONECT_MASTER_KEY` com salt `motor-conect-trilha-hmac-v1`
- **Amparo legal**: CTN Art. 142 (lançamento tributário exige prova de integridade)

## O que NÃO faz

- Não acessa o banco de dados (só arquivos JSON exportados)
- Não loga acesso em `AuditoriaAcessoDB` (responsabilidade do endpoint `/auditoria/prova/cnpj/{digitos}`)
- Não decifra PDFs — apenas valida trilha. Para baixar originais, use o endpoint REST.

## Referências

- `docs/rollback_rfc.md` — checklist pós-rollback
- `PY/observability/hmac_trilha.py` — implementação da verificação
- `CLAUDE.md` seção "Auditoria Documental"
