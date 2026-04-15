# Cirurgia de Overengineering — Relatório de Execução

**Data:** 14 de Abril de 2026
**Tipo:** Refatoração Arquitetural (Simplificação)

---

## Resumo da Operação

O backend do Motor Tributário sofria de **Overengineering** — abstrações prematuras estilo Java Enterprise para rotinas que são transações sequenciais simples.

Foram executadas 3 cirurgias:

---

## 1. Integrations SIEG: 3 arquivos → 1

| Antes | Depois |
|:---|:---|
| `sieg_adapter.py` (315 linhas) | `sieg_service.py` (290 linhas) |
| `sieg_credentials.py` (127 linhas) | *(fundido acima)* |
| `sieg_ingestor.py` (190 linhas) | *(fundido acima)* |
| **Total: 632 linhas, 3 classes** | **Total: 290 linhas, 1 classe** |

**O que mudou:**
- Padrão `Adapter(Credentials) → Ingestor(Adapter)` eliminado
- `SiegService()` carrega a API key sozinho e faz fetch + persist + auditoria no mesmo fluxo
- Sem injeção de dependência — explícito e debugável

---

## 2. Observability: 4 arquivos + 1 pacote → 1 módulo

| Antes | Depois |
|:---|:---|
| `observability/anomalias.py` (219 linhas) | `validacoes.py` (200 linhas) |
| `observability/semaforo_das.py` (100 linhas) | *(fundido acima)* |
| `observability/schema_registry.py` (150 linhas) | *(prematura — removido)* |
| `observability/__init__.py` (10 linhas) | *(desnecessário)* |
| **Total: 479 linhas, 1 pacote** | **Total: 200 linhas, 1 arquivo** |

**O que mudou:**
- Funções puras (sem estado) não justificam um pacote com `__init__.py`
- `schema_registry.py` era uma abstração prematura sobre parsers — checksums e versões de parsers que nem estão em produção. Removido.
- `import validacoes` em vez de `from observability import anomalias, hmac_trilha, semaforo_das`

---

## 3. HMAC Inline Removido do Pipeline

**Antes:** `hmac_trilha.assinar_trilha()` era chamado dentro de `/analise/pdf` em tempo real.

**Depois:** Assinatura HMAC movida para o momento de **persistência definitiva** (quando o diagnóstico for gravado no banco). Assinar dados que ainda estão em memória e não foram transacionados é desperdício de CPU e entropia.

O módulo `hmac_trilha.py` continua existindo em `observability/` para uso futuro na camada de persistência.

---

## Balanço Final

| Métrica | Antes | Depois |
|:---|:---|:---|
| `main.py` | 1.940 linhas | **1.403 linhas** (-28%) |
| Arquivos de integração SIEG | 3 | **1** |
| Pacote `observability/` | 4 módulos + init | **1 módulo plano** |
| Classes de indireção | Adapter + Ingestor + Credentials | **Service** (direto) |

**Todos os arquivos removidos estão na `.lixeira/` — zero exclusão permanente.**
