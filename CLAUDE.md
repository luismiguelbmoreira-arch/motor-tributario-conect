# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# 🏛️ MOTOR TRIBUTÁRIO CONECT — BÍBLIA DA REFORMA TRIBUTÁRIA

**Status:** 🚀 Fase 2 Certificada — 188 testes passando (100%)
**Âncora Legal:** EC 132/2023 | LC 123/2006 | LC 214/2025
**Data Certificação:** 27/03/2026

---

## ⚡ COMANDOS ESSENCIAIS

Todos os comandos executam a partir da pasta `PY/`.

```bash
# Rodar todos os testes
python -m pytest tests/ -v

# Rodar arquivo específico
python -m pytest tests/test_fase2_simples.py -v

# Rodar um teste específico
python -m pytest tests/test_database.py::TestEmpresaDB::test_salvar_empresa_nova -v

# Instalar dependências
pip install -r requirements.txt

# Inicializar banco de dados (primeira vez)
python -c "from database import criar_tabelas; criar_tabelas()"

# Migrações Alembic
alembic upgrade head
alembic revision --autogenerate -m "descricao"
```

**Variáveis de ambiente** (criar `PY/.env`, nunca commitar):
```
ANTHROPIC_API_KEY=sk-ant-api03-...
DATABASE_URL=sqlite:///motor_tributario.db
```

---

## 🏗️ ARQUITETURA — VISÃO GERAL

```
motor_tributario.py         ← Orquestrador principal + Dispatcher de regime
├── EmpresaFornecedora       ← Pydantic V2 — regime: SIMPLES|PRESUMIDO|REAL|MEI
├── EmpresaCompradora        ← tipo: B2B_CONTRIBUINTE|B2C_CONSUMIDOR_FINAL
├── OperacaoFiscal           ← data_emissao: date (2026-2033), valor: Decimal
├── MotorReformaTributaria   ← Engine principal (Fases 2–4)
│   ├── trilha_auditoria[]   ← TRILHA UNIFICADA — todos os engines escrevem aqui
│   └── _instanciar_engine() ← Dispatcher → LucroPresumidoEngine | MEIEngine
│
regimes/
├── base.py                  ← BaseRegimeEngine + RegimeMismatchError + registrar_violacao()
├── lucro_presumido.py       ← PIS/COFINS/CSLL/IRPJ cumulativo (Guard Clause: PRESUMIDO)
└── mei.py                   ← DAS fixo por categoria, teto R$81k (Guard Clause: MEI)
│
tabelas_simples.py           ← FROZEN — Anexos I–V, CNAE→Anexo, cronograma IVA 2026-2033
validadores.py               ← CNPJ Mod.11, CNAE, NCM, UF → retornam ValidationResult
database.py                  ← SQLModel + SQLite, Enums, LGPD purge, ciclo de vida alertas
extrator_pdfs.py             ← Claude Vision API — extração de PDFs de clientes
│
tests/                       ← 188 testes (100% passando)
├── test_fase2_simples.py    ← RBT12, Fator R, Anexo, Alíquota Efetiva
├── test_fase3_iva.py        ← Cronograma IBS/CBS 2026-2033, Split Payment
├── test_fase4_optout.py     ← Opt-Out, cenários comparativos
├── test_regime_guard.py     ← Guard Clauses (Camada 3 — bloqueia deploy se falhar)
├── test_mei_guard.py        ← MEI guard, DAS 2026, teto, sem crédito IVA
├── test_database.py         ← CRUD, Decimal como TEXT, LGPD, ciclo alertas
└── test_validadores.py      ← CNPJ/CNAE/NCM/UF
```

---

## 🔐 PROTEÇÃO DE REGIME (3 Camadas — NÃO REMOVER)

```
Camada 1 (Pydantic V2)   → entrada inválida rejeitada antes de entrar no motor
Camada 2 (Guard Clause)  → engine errado = RegimeMismatchError + log na trilha
Camada 3 (pytest)        → se Guard removida = CI quebra, deploy bloqueado
                                      ↓
                           TRILHA_UNIFICADA (um único log para o auditor)
```

**Para adicionar novo engine de regime:**
1. Criar `regimes/novo_regime.py` herdando `BaseRegimeEngine`
2. Declarar `REGIME_ACEITO = "NOVO"` na classe
3. Chamar `super().__init__(fornecedora, trilha)` no `__init__`
4. Adicionar `if regime == "NOVO": return NovoEngine(...)` no `_instanciar_engine()` de `motor_tributario.py`
5. Criar `tests/test_novo_guard.py` com os testes de Guard Clause (ver `test_regime_guard.py` como template)
6. Adicionar `"NOVO"` ao `Literal` em `EmpresaFornecedora.regime`

---

## 📊 FORMATO DA TRILHA DE AUDITORIA

Todo evento gravado em `trilha_auditoria[]` segue este formato:

```python
# Evento de cálculo (tipo CALCULO)
{
    "tipo": "CALCULO",
    "id": "FASE2_RBT12",          # snake_UPPER único por passo
    "titulo": "Receita Bruta 12 meses",
    "formula": "Base [X] - Deduções [Y] * Alíquota [Z] = W",
    "memoria": {"base": "...", "deducoes": "...", "aliquota": "...", "valor_final": "..."},
    "amparo_legal": "LC 123/2006, Art. 12, § 1º",  # OBRIGATÓRIO — MAX_02
    "detalhe": "...",
    "timestamp": "2026-03-29T02:45:30.123456",
}

# Evento de violação de regime (tipo VIOLACAO_SEGURANCA)
{
    "tipo": "VIOLACAO_SEGURANCA",
    "id": "VIOLACAO_LucroPresumidoEngine_SIMPLES",
    "titulo": "Guard Clause — Regime Incompatível",
    "amparo_legal": "LC 123/2006 Art. 13 | RIR/2018 Art. 214",
    "memoria": {"regime_empresa": "SIMPLES", "modulo_chamado": "LucroPresumidoEngine"},
}

# Alerta não-bloqueante (tipo ALERTA_*)
{
    "tipo": "ALERTA_MEI_TETO",
    "id": "ALERTA_TETO_MEI",
    "detalhe": "Receita R$ 82.000 excede teto R$ 81.000...",
    "amparo_legal": "LC 123/2006, Art. 18-A, caput",
}
```

---

## 🛑 REGRAS MÁXIMAS — MAX_FISCAL (Inegociáveis)

| ID | Diretriz |
| :--- | :--- |
| **MAX_01** | Proibido entregar valor final sem: Base → Deduções → Alíquota → Valor |
| **MAX_02** | Toda regra, alíquota ou isenção cita explicitamente a base legal |
| **MAX_03** | Declarar a data base ANTES do cálculo (regra do ano errado invalida tudo) |
| **MAX_04** | Premissa alterada → salvar como `Cenario_Estudo_A`, nunca deletar |

---

## ⚙️ CONVENÇÕES DE CÓDIGO

- **Nunca usar `float` para valores monetários.** Sempre `Decimal` com `ROUND_HALF_UP`.
- **Pydantic V2** para todos os modelos de entrada. Campos monetários: `Decimal`.
- **Constantes fiscais FROZEN**: declarar no topo do arquivo com comentário de lei. Não alterar sem aprovação de Luiz Moreira.
- `tabelas_simples.py` é **FROZEN** — nenhuma edição sem aprovação explícita.
- Imports nos testes exigem `sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))` antes dos imports do projeto.
- `competencia` em banco de dados: sempre formato ISO `"YYYY-MM"` (nunca `"MM/YYYY"`).

---

## 🗄️ BANCO DE DADOS

**ORM:** SQLModel + SQLite (WAL mode). Schema em `database.py`.

**Enums obrigatórios** (strings mágicas são rejeitadas):
- `RegimeTributario`: SIMPLES, PRESUMIDO, REAL, MEI
- `NivelAlerta`: CRITICO, ALTO, MEDIO, BAIXO
- `StatusAlerta`: ABERTO, RESOLVIDO, IGNORADO
- `StatusAuditoria`: PENDENTE, APROVADO, REJEITADO

**LGPD:** `purge(cnpj)` remove todos os dados do CNPJ. Bloqueio ERR-012: substituição por `anonimizar()` aguarda decisão legal (CTN Art. 173 — retenção 5 anos).

---

## 🗺️ ROADMAP — STATUS ATUAL (29/03/2026)

| Fase | Status | Bloqueador |
| --- | --- | --- |
| Simples Nacional (Anexo I) | ✅ Certificado | — |
| Lucro Presumido | ✅ Certificado | — |
| MEI | ✅ Implementado | Validação Luiz Moreira (salário mínimo 2026) |
| ERR-005 (CNAE incompleto ~970 CNAEs) | 🔴 Pendente | — |
| Lucro Real | 🔵 Próxima fase | — |
| Dashboard Split Payment | 🔵 Próxima fase | — |
| DIFAL Interestadual | 🟡 Pendente | — |
| Fase 4 (relatórios PDF clientes) | 🟡 Bloqueado | Documentos reais do escritório |

**ERR ativos críticos:** ERR-005 (CNAE incompleto), ERR-012 (purge vs anonimizar LGPD). Ver `docs/LOG_ERROS.md`.

---

## 🤖 AGENTES ESPECIALIZADOS

Disponíveis como subagentes Claude Code (`.claude/agents/`):

| Agente | Responsabilidade | Quando invocar |
| --- | --- | --- |
| **O Viciado** | Backend Python blindado, Decimal, Pydantic V2, testes | Código Python tributário |
| **Luiz Moreira** | Validação matemática fiscal, LC 214/2025, Fator R | Antes de congelar alíquotas |
| **Master Zen** | UX/UI, Dashboard Split Payment, glassmorphism | Interface e visualizações |
| **O CHEFE** | Decisões arquitetônicas, roadmap, conflitos de prioridade | Visão macro |

---

## ⚡ PROTOCOLO DE CENÁRIO (MAX_FISCAL_04)

Quando premissa mudar (ex: regime Lucro Presumido → Real):

```
Cenario_Atual  → preservar como Cenario_Estudo_A
Cenario_Novo   → criar do zero com novas premissas
Comparativo    → exibir lado a lado (Delta de carga tributária)
```

**"Cálculo por fora, crédito pleno, e blindagem fiscal total."** 🛡️
