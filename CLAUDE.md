# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# 🏛️ MOTOR TRIBUTÁRIO CONECT — BÍBLIA DA REFORMA TRIBUTÁRIA

**Status:** 🚀 Produção — 1881 testes passando (100%) | 4 regimes + IMUNE + DIFAL + PDF educativo + Auditoria LGPD + IDOR Guard + Fase 0a/0b + Fase 2 (mapa-mestre 34 categorias) + Fase 3' subfase 0 (FonteCliente) + WS6 etapas 4/5a/5b/6 + WS12 (ERR-005 fechado) + WS5 (Rail R6 logs refazíveis) + WS7 (obrigações Simples + alertas) + WS7b/WS7c parcial (ECF + ECD + DCTFWeb pra Presumido/Real/Imune) + Cache local de fontes
**Âncora Legal:** EC 132/2023 | LC 123/2006 | LC 214/2025 | LC 224/2025 | LC 227/2026 | EC 87/2015 | LGPD 13.709/2018 | Lei 5.764/71 | Lei 9.718/98 | Lei 9.430/96 | Lei 8.218/91 | Lei 10.426/2002 | Lei 12.973/2014 | Lei 9.532/97 | Lei 14.689/2023 | Lei 4.502/64 | Decreto-Lei 1.598/77 | CTN Arts. 142 e 173
**Última certificação:** 09/05/2026 (WS7c parcial — DCTFWeb offset revertido 2→1 conservador por ERR-058.c + ECD adicionada ao Lucro Real; 6 normas RFB ainda sem texto literal — sijut2 SPA falha)

---

## ⚡ COMANDOS ESSENCIAIS

Comandos a partir de `PY/`:

```bash
python -m pytest tests/ -v                                          # todos os testes
python -m pytest tests/test_fase2_simples.py -v                     # arquivo específico
python -m pytest tests/test_database.py::TestEmpresaDB::test_X -v   # teste específico
pip install -r requirements.txt
python -c "from database import criar_tabelas; criar_tabelas()"     # init DB
alembic upgrade head
alembic revision --autogenerate -m "descricao"
```

**`PY/.env`** (nunca commitar):
```
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=sqlite:///motor_tributario.db
MOTOR_CONECT_MASTER_KEY=<64 hex chars — gere com `python -c "import secrets; print(secrets.token_hex(32))"`>
JWT_SECRET_KEY=<chave JWT>
```

**MOTOR_CONECT_MASTER_KEY** = chave raiz da auditoria documental cifrada. Perder = PDFs antigos irrecuperáveis. Cofre obrigatório (1Password/Bitwarden).

**Fontes alternativas em produção** (`storage_cifrado._master_key()` resolve em ordem):
1. `$MOTOR_CONECT_MASTER_KEY` (dev local)
2. Arquivo protegido (`/etc/motor-conect/master.key` Linux 0600 / `%PROGRAMDATA%\motor-conect\master.key` Windows)
3. `$MOTOR_CONECT_MASTER_KEY_AWS_SECRET` (AWS Secrets Manager + boto3 + IAM role)

Override path: `$MOTOR_CONECT_MASTER_KEY_FILE`. Setup detalhado em `docs/deploy/master_key.md`.

---

## 🏗️ ARQUITETURA — VISÃO GERAL

```
core/motor_tributario.py    ← Orquestrador + Dispatcher de regime
├── EmpresaFornecedora       ← regime: SIMPLES|PRESUMIDO|REAL|MEI|IMUNE; tipo_societario: ...|COOPERATIVA|...
├── EmpresaCompradora        ← tipo: B2B_CONTRIBUINTE|B2C_CONSUMIDOR_FINAL
├── OperacaoFiscal           ← data_emissao: date (2026-2033), valor: Decimal
├── MotorReformaTributaria   ← Engine principal
│   ├── trilha_auditoria[]   ← TRILHA UNIFICADA — todos os engines + overlays
│   ├── _instanciar_engine() ← Dispatcher → LucroPresumido|LucroReal|MEI|Imune|SimplesMulti
│   └── _instanciar_overlay_cooperativa()
│
core/regimes/                ← base.py + lucro_presumido + lucro_real + mei + simples_multi + imune + cooperativa (overlay)
core/fontes/base.py          ← Protocol FonteCliente (Fase 3' subfase 0)
core/obrigacoes_acessorias.py ← WS7 — DASN-SIMEI/DEFIS/PGDAS-D + alertas vencimento (LC 123 Art. 38/38-A)
tabelas_simples.py           ← FROZEN — Anexos I-V, CNAE→Anexo, cronograma IVA 2026-2033
validadores.py               ← CNPJ Mod.11, CNAE, NCM, UF
database/                    ← connection + enums + models + repositories/
services/                    ← extrator_pdfs (Claude Vision) + storage_cifrado (AES-256-GCM) + analise_buffer + relatorio_pdf
api/routers/                 ← auth + auditoria + usuarios + integracoes + historico + configuracoes
tests/                       ← 1881 testes (100%)
```

---

## 🔌 DECISÃO ARQUITETÔNICA — DESACOPLAMENTO DE FONTE (30/04/2026)

**Decisão:** motor consome interface `FonteCliente`; fontes implementam.

```
Motor (core/) ──► FonteCliente (interface)
                       ▲
            ┌──────────┼──────────────┐
   FontePDFManual   FonteNibo     FonteSistemaProprio
   (Claude Vision   (parqueada)   (futura)
    + extrator_pdfs)
```

**Consequência:** Fase 1 (sonda Nibo) sai do caminho crítico. Quando Nibo entrar, é 1 arquivo novo (`FonteNibo`) implementando a interface — zero refactor do motor.

**Princípio R5 estendido:** fonte de dados ≠ motor. Motor não conhece Nibo, e-CAC, sistema próprio nem PDF — só consome `FonteCliente.obter_periodo(cnpj, mes_inicio, mes_fim)`.

---

## 🔐 PROTEÇÃO DE REGIME (3 Camadas — NÃO REMOVER)

```
Camada 1 (Pydantic V2)   → entrada inválida rejeitada antes de entrar no motor
Camada 2 (Guard Clause)  → engine errado = RegimeMismatchError + log na trilha
Camada 3 (pytest)        → Guard removida = CI quebra, deploy bloqueado
                                      ↓
                           TRILHA_UNIFICADA (log único pro auditor)
```

**Adicionar novo engine de regime:**
1. `core/regimes/novo_regime.py` herdando `BaseRegimeEngine`
2. Declarar `REGIME_ACEITO = "NOVO"`
3. `super().__init__(fornecedora, trilha)` no `__init__`
4. Adicionar branch em `_instanciar_engine()` de `motor_tributario.py`
5. `tests/test_novo_guard.py` (template: `test_regime_guard.py`)
6. `"NOVO"` ao `Literal` em `EmpresaFornecedora.regime`

---

## 📊 FORMATO DA TRILHA DE AUDITORIA

```python
# CALCULO
{
    "tipo": "CALCULO",
    "id": "FASE2_RBT12",                      # snake_UPPER único
    "titulo": "Receita Bruta 12 meses",
    "formula": "Base [X] - Deduções [Y] * Alíquota [Z] = W",
    "memoria": {"base": "...", "aliquota": "...", "valor_final": "..."},
    "amparo_legal": "LC 123/2006, Art. 12, § 1º",   # OBRIGATÓRIO — MAX_02
    "timestamp": "2026-03-29T02:45:30.123456",
}

# VIOLAÇÃO DE REGIME
{
    "tipo": "VIOLACAO_SEGURANCA",
    "id": "VIOLACAO_LucroPresumidoEngine_SIMPLES",
    "amparo_legal": "LC 123/2006 Art. 13 | RIR/2018 Art. 214",
    "memoria": {"regime_empresa": "SIMPLES", "modulo_chamado": "LucroPresumidoEngine"},
}

# ALERTA não-bloqueante
{
    "tipo": "ALERTA_MEI_TETO",
    "id": "ALERTA_TETO_MEI",
    "detalhe": "Receita R$ 82.000 excede teto R$ 81.000...",
    "amparo_legal": "LC 123/2006, Art. 18-A, caput",
}
```

---

## 🔐 AUDITORIA DOCUMENTAL (LGPD + CTN)

Bloqueia o vetor "dado errado culpa do contador" e cumpre LGPD Art. 16/37/46 + CTN Arts. 142/173. Ativa em toda chamada de `POST /analise/pdf` autenticada.

### Fluxo de upload

```
1. Cliente sobe PDFs via POST /analise/pdf
2. processar_pdfs_bytes(conteudos, arquivos_nomes, user_id, persistir_auditoria=True)
3. Claude Vision → CNPJ, RBT12, competência
4. Motor → diagnóstico + trilha_auditoria
5. Para cada PDF:
     a. hash_documento(bytes) → SHA-256 hex
     b. cifrar_e_persistir → AES-256-GCM, chave = HKDF-SHA256(MASTER_KEY, salt=cnpj)
        path = data/auditoria/{sha256(cnpj)[:16]}/{hash[:16]}.bin
     c. registrar_documento_auditoria → row em auditoria_documentos
6. Cada passo da trilha ganha {"fonte": {documentos_ids, hashes, campo_origem}}
```

### Módulos

```
services/storage_cifrado.py        ← AES-256-GCM + HKDF puro
  cifrar_e_persistir / decifrar / hash_documento / anonimizar_cnpj / existe / purge

database/models.py
  AuditoriaDocumentoDB             ← hash, cnpj, storage_path, uploaded_by, aceito_em, purge_after
  AuditoriaAcessoDB                ← log LGPD Art. 37 (motivo obrigatório 10-500 chars)

services/extrator_pdfs.py
  processar_pdfs_bytes(..., persistir_auditoria) / _inferir_campo_origem(passo_id)

api/routers/auditoria.py
  GET /auditoria/prova/cnpj/{digitos}?motivo=...  ← dossiê ZIP
```

### Endpoint de dossiê

```bash
curl -H "Authorization: Bearer <JWT>" \
  "http://localhost:8000/auditoria/prova/cnpj/54657895000160?motivo=Fiscalizacao%20RFB%20123-2026" \
  -o dossie.zip
# unzip + sha256sum originais/*.pdf bate com HASHES.txt
```

CNPJ na URL = só dígitos (14 chars). Cada decifragem registra `user_id + IP + motivo` em `auditoria_acessos`.

### Política LGPD de retenção

| Item | Onde | Prazo | Purge |
|---|---|---|---|
| PDF cifrado | `data/auditoria/{hash}/...bin` | 5 anos (CTN 173) | `storage_cifrado.purge()` + `marcar_documento_purgado()` |
| Metadata DB | `auditoria_documentos` | 5 anos + `purged_at` | permanente como histórico |
| Log de acesso | `auditoria_acessos` | Permanente (LGPD 37) | nunca purga |

Cron diário: `listar_documentos_purgaveis()` → purge dos vencidos.

### Backup diário (OBRIGATÓRIO em produção)

`PY/scripts/backup_db.py` — `sqlite3.Connection.backup()` + gzip nível 9 + escrita atômica. Perda do DB = dossiê inviável mesmo com PDFs cifrados intactos.

```
data/backups/diarios/YYYY-MM-DD.db.gz   ← retenção 30 dias rolling
data/backups/mensais/YYYY-MM.db.gz      ← permanente (purge manual)
```

Setup cron/Task Scheduler + restauração detalhada: `docs/deploy/backup.md`.

### Recuperação de incidentes

| Situação | Ação |
|---|---|
| Master key perdida | PDFs antigos irrecuperáveis. Casos novos com nova key. |
| DB corrompido | Restaurar do backup. Sem backup = arquivos cifrados inúteis. |
| Cliente pede LGPD Art. 18 V | `purge()` + `marcar_documento_purgado()` por doc. Log permanece. |
| Fiscalização exige originais | `GET /auditoria/prova/cnpj/{digitos}?motivo=...` |

---

## 📊 PARAMETRIZAÇÃO POR TIPO SOCIETÁRIO (WS6)

Motor distingue **regime** tributário de **tipo_societario** (LTDA pode estar no Simples; SA geralmente é forçada pra Real).

| Tipo | Limite | Regimes permitidos | Extrapolação |
|---|---|---|---|
| MEI | R$ 81 mil/ano | Simples (DAS fixo) | → ME |
| ME | R$ 360 mil/ano | Simples, Presumido, Real | → EPP |
| EPP | R$ 4,8 mi/ano | Simples, Presumido, Real | → Presumido/Real obrigatório |
| Lucro Presumido | R$ 78 mi/ano | Presumido | → Real obrigatório (Lei 9.718/98 Art. 13) |
| Lucro Real | Sem limite | Real | — |
| LTDA / SA | Conforme porte | Simples, Presumido, Real | SA geralmente Real |
| Cooperativas | Sem teto | Geralmente Real | Perde benefício se não segregar atos (Lei 5.764/71 Art. 79) |
| Imunes (CF 150 VI c) | Sem limite | Imunidade | Tributada se descumprir requisitos |

**Fonte atual (descentralizada):** limites distribuídos em `tabelas_simples.py` + `alertas_motor.py` + `historico_consolidado.py` + `motor_tributario.py` + `orquestrador_societario.py`. WS10 introduziu `VersionedRule[T]` como padrão; centralização em `core/limites_societarios.py` é **débito técnico** (WS10b — sob R9, adiado por decisão arquitetônica). Validação Escrivão obrigatória antes de hardcoding novo limite, em qualquer um desses 5 pontos.

**Alerta migração obrigatória (R7-extended):** RBT12 ≥ 90% do limite → `ALERTA_MIGRACAO_OBRIGATORIA` na trilha.

---

## ⚖️ RAILS DE IMPLEMENTAÇÃO SEGURA (meta-MAX)

Os 9 rails são **invioláveis** acima das MAX_FISCAL. Conflito entre Rail e MAX → Rail vence.

| Rail | Diretriz |
|---|---|
| **R1 — Fonte normativa única** | Toda alíquota/limite/regra de doc oficial (planalto.gov.br, IN, manual RFB) com SHA-256 e `campo_origem`. Sem fonte → não vira código. |
| **R2 — Proibição de extrapolação** | Sem lei publicada, sem cálculo. Lacuna → conservadorismo fiscal. Premissas econômicas só com fonte oficial (BCB Focus, IBGE SIDRA). |
| **R3 — Versões normativas** | Cada cálculo registra lei vigente na `data_emissao`. `VersionedRule` em todas as constantes. Janela: 2024-01-01 a 2033-12-31. |
| **R4 — Validação cruzada** | Motor compara contra PGDAS-D, ECF, SPED. Divergência → revisão manual. Tolerância < 0,5%. |
| **R5 — Separação rígida de regimes** | Sistema **impede** aplicar MEI a SA, imunidade a empresa comercial. Guard 3 camadas. Estende-se a `tipo_societario × regime`. |
| **R6 — Logs refazíveis** | Cada cálculo gera log auto-suficiente. `python PY/scripts/refazer_calculo.py --diagnostico-id N` reconstrói o número apenas do log. |
| **R7 — Opt-Out automático ≥ 90% do teto** | RBT12 ≥ 90% (R$ 4,32M de R$ 4,8M) força análise Opt-Out. Sem cenário comparado, PDF não emite. |
| **R8 — Consistência temporal** | Norma vigente na data da operação. CBS/IBS não em 2025 (entra 2026 — LC 214/2025). |
| **R9 — Ampla Visão** | Antes de mudança arquitetônica (módulo novo, schema novo, refactor multi-arquivo): **Ontem** (estado atual, reuso, falhas históricas) → **Amanhã** (escala 200 CNPJs, manutenibilidade) → **Hoje** (versão enxuta). Fix pontual e bug isolado isentos. |

---

## 🛑 REGRAS MÁXIMAS — MAX_FISCAL (Inegociáveis)

| ID | Diretriz |
|---|---|
| **MAX_01** | Proibido valor final sem: Base → Deduções → Alíquota → Valor |
| **MAX_02** | Toda regra/alíquota/isenção cita base legal explícita |
| **MAX_03** | Declarar a data base ANTES do cálculo |
| **MAX_04** | Premissa alterada → salvar como `Cenario_Estudo_A`, nunca deletar |
| **MAX_05** | Toda análise via `/analise/pdf` deve ter PDFs cifrados em `auditoria_documentos`. Sem isso, diagnóstico não vale em defesa jurídica. |
| **MAX_06** | Crédito B2B de Simples = **fração do DAS** (não `valor_operacao × alíquota IVA`). Fórmula: `credito = DAS_mensal × _fracao_iva_no_das(anexo, faixa, ano)`. **LC 214/2025 Art. 47 § 9º**. |
| **MAX_07** | **Anti-alucinação de citação legal**. Toda menção a Solução de Consulta COSIT, Acórdão CARF, súmula STJ/STF, ato normativo RFB **passa pelo Escrivão antes do commit**. SC COSIT 174/2019 foi inventada num código que passou nos testes — só Escrivão pegou (ERR-017.b). |
| **MAX_08** | **Todo número passa pelo motor.** Não existe simulação hipotética — existem inputs hipotéticos que o motor calcula. Cálculo mental = BLOQUEIO. Estimativa = BLOQUEIO. |
| **MAX_09** | **Nunca declarar feito o que não foi feito.** Sem evidência real (pytest -v, log da API, output do script), proibido afirmar "validado/passou/conferido". Fingir execução > erro de cálculo em gravidade. |

---

## 🔍 PMD — GATE OBRIGATÓRIO ANTES DE TODO COMMIT

**Agente:** `.claude/agents/pmd.md` — PutaMadre de Documentação.

Nenhum commit sem PMD aprovar. Vale pra qualquer fase, hotfix, refactor.

**MAX_08 + MAX_09 são as travas centrais.** Todo número calculável pelo motor DEVE vir do motor.

**Sequência:**
1. Código/doc pronto → invocar PMD (`subagent_type: pmd`)
2. PMD verifica estrutura + valida que todo número tem evidência de execução real
3. Reporta achados com `arquivo:linha`
4. Fix os críticos/altos
5. PMD aprova → commit

PMD não invocado = commit não acontece. Sem exceção.

---

## ⚙️ CONVENÇÕES DE CÓDIGO

- **Nunca `float` em dinheiro.** Sempre `Decimal` com `ROUND_HALF_UP`.
- **Pydantic V2** em modelos de entrada. Campos monetários: `Decimal`.
- **Constantes fiscais FROZEN**: topo do arquivo, comentário com lei. Não alterar sem Luiz Moreira.
- `tabelas_simples.py` é **FROZEN** — nenhuma edição sem aprovação explícita.
- Imports de teste: `sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))` antes dos imports do projeto.
- `competencia` em DB: ISO `"YYYY-MM"` (nunca `"MM/YYYY"`).

---

## 🗄️ BANCO DE DADOS

**ORM:** SQLModel + SQLite (WAL). Schema modularizado em `database/`.

**Enums obrigatórios** (strings mágicas rejeitadas):
- `RegimeTributario`: SIMPLES, PRESUMIDO, REAL, MEI
- `NivelAlerta`: CRITICO, ALTO, MEDIO, BAIXO
- `StatusAlerta`: ABERTO, RESOLVIDO, IGNORADO
- `StatusAuditoria`: PENDENTE, APROVADO, REJEITADO

**LGPD:** `purge(cnpj)` remove dados do CNPJ. Bloqueio ERR-012: substituição por `anonimizar()` aguarda decisão jurídica (CTN 173 — retenção 5 anos).

---

## 🗺️ ROADMAP — STATUS ATUAL (09/05/2026)

**Suite:** **1881 testes verdes** | **0 regressão** (total confirmado em mensagem do commit `9852a41`: "Suite total: 1881 passed").
**Branch ativo:** `fase-2-mapa-mestre` (não mergeado em main).

Histórico detalhado de commits e ERRs fechados: `docs/roadmap/HISTORICO.md` + `docs/roadmap/LOG_ERROS.md` + `git log`.

### ✅ Concluído neste ciclo

- **Fase 0a** — Schema HistoricoSeisMeses + DiagnosticoConsolidado (MAX_08 compliant)
- **Fase 0b** — 5 módulos especiais: Fator R, Calendário Legal, Sublimites UF, Profissões Regulamentadas, Imposto Seletivo + Rail R9
- **Fase 2 subfases 2.0/2.1/2.2** — `core/mapa_categorias_cbs_ibs.py` 9→34 categorias (LC 214/2025 Arts. 47 + 57 + 108 + 180 + 271)
- **Fase 3' subfase 0** — Protocol `FonteCliente` + exceções `FonteIndisponivel` / `DadosInsuficientesNaFonte`
- **WS6 etapas 1-6** — schema ampliado (13 tipos societários) + matriz societária 13×4 + sub-validador MEI + engine IMUNE + overlay COOPERATIVA (5 ramos OCB) + cooperativa CRÉDITO/SAÚDE + orquestrador societário
- **WS10** — `VersionedRule[T]` em 4 constantes (Teto Simples, Sublimite ICMS/ISS, Teto MEI, Limite Presumido)
- **WS12** — `core/regras_cnae.py` + `cnae_excecoes.py` + `cnae_completo.json` regenerado (ERR-005 fechado em 08/05/2026)
- **WS5** — Rail R6 logs refazíveis: `core/refazer.py` (função pura) + `scripts/refazer_calculo.py` (CLI parser BR, R$ + vírgula decimal, tolerância R$ 0,02)
- **WS7 (parcial)** — `core/obrigacoes_acessorias.py`. 3 obrigações Simples cobertas pelo cache LC 123/2006: DASN-SIMEI (Art. 38 § 6º — mín R$ 50), DEFIS (Art. 38 § 3º — mín R$ 200), PGDAS-D (Art. 38-A redação LC 214/2025 — mín R$ 50/mês-ref). Multa máxima 20% (NÃO 10% — bloqueio MAX_07 do plano original prevenido). 4 bloqueios MAX_07 prevenidos antes do código. ANUAL+MENSAL implementadas; SEMESTRAL/TRIMESTRAL pendentes. 30 testes
- **WS7b + WS7c parcial** — Capturados Lei 9.430/96, Lei 8.218/91, Lei 10.426/2002, Lei 12.973/2014, Lei 9.532/97, Lei 14.689/2023, **Decreto-Lei 1.598/77**, Lei 4.502/64. Matriz estendida pra Presumido/Real/Imune: **ECF** (DL 1.598/77 Art. 8º-A — 0,25% LL/mês máx 10%) + **ECD** (Real apenas; Lei 8.218/91 Art. 11 + DL 1.598/77 Art. 8º-A) + **DCTFWeb** (Lei 10.426 Art. 7º — mín R$ 500 demais regimes; `offset_meses=1` conservador após ERR-058.c; era 2 no plano original mas WebSearch retornou 3 versões conflitantes). Schema Obrigacao ganhou `prazo_offset_meses` + `prazo_n_dia_util`. **3 bloqueios MAX_07 prevenidos**: ERR-058 (Art. 8º-A está no DL 1.598/77, não Lei 9.430/96), ERR-058.b (Lei 8.218/91 Art. 12 não tem piso "R$ 500-1500"), ERR-058.c (DCTFWeb offset 2→1 sem texto literal IN RFB 2.005). Suite 1858 → 1881 (+23 testes acumulados nos commits `0befc8d` (WS7) → `3689851` → `7c1500c` → `4ddc89f` (WS7b) → `9852a41` (WS7c parcial); total final 1881 declarado na mensagem do `9852a41`)
- **Cache fontes legais** — `data/fontes_legais/` com LC 123/214/227 + 7 leis WS7b + Lei 4.502/64 capturadas via curl (WebFetch socket-dropping); protocolo Escrivão cache-first

### ⏸️ Próximas etapas

| Fase | Estado | Próxima ação |
|---|---|---|
| **WS6 etapa 7 — regimes específicos IBS/CBS** | ⏸️ **RETOMAR AQUI** | Cálculo automático cooperativa crédito (LC 214 Cap II Tít V, Arts. 181-208) e saúde (Arts. 234-238, alíquota referência −60%). Hoje só registra alertas. Faltam alíquotas referência por ano (2027-2033), redução 60% saúde, base Art. 235, vedações Art. 238. Plan-First obrigatório. |
| ~~WS7b + WS7c parcial — Planalto + ECF/ECD/DCTFWeb~~ | ✅ **Fechado parcial em 09/05/2026** | Ver bloco "Concluído neste ciclo" acima. ERR-058 + 058.b + 058.c prevenidos. **6 normas RFB ainda pendentes** (IN RFB 2.003-2.005/2021, IN RFB 1.252/2012, IN RFB 1.371/2013, Resolução CGSN 140/2018) — sijut2 SPA falha + sped.rfb ECONNREFUSED + WebFetch falha. Caminhos remanescentes: Playwright/Selenium, Migrador manual, PDF Imprensa Nacional. Plus: caller de produção pra `gerar_alertas_obrigacoes()`. |
| WS10 extensão | 🔵 | `TABELAS_ANEXOS` + `CRONOGRAMA_IVA` versionados |
| **WS10b — centralização limites societários** | 🔵 Débito técnico (R9) | Hoje limites em 5 arquivos: `tabelas_simples`, `alertas_motor`, `historico_consolidado`, `motor_tributario`, `orquestrador_societario`. Criar `core/limites_societarios.py` consolidando Teto MEI/ME/EPP/Presumido + Sublimites UF + Teto Fator R sob `VersionedRule`. Plan-First fiscal obrigatório. Trigger pra fazer: próximo reajuste legal de teto OU 4º caller adicionado. |
| **WS6.b — Lucro Real refinado** | ⏸️ **GATE PARCIAL em 09/05/2026** | Aurora v2 (refeita por Luiz Moreira contra cache validado) rodou pelo motor real (`scripts/rodar_aurora_pelo_motor.py`). **3/5 itens bateram** (IRPJ principal, PIS líquido, COFINS líquido); **2/5 expostos como gaps reais** do `LucroRealEngine`: (a) IRPJ adicional usa teto MENSAL R$ 20k mesmo com input anual → delta R$ 22.000; (b) CSLL calculada sobre o MESMO `lucro_real_mensal` do IRPJ → não distingue base CSLL (que não adiciona a si própria) de base IRPJ → delta R$ 25.185. Aurora cumpriu papel pedagógico. Carga LÍQUIDA Aurora = 13,67% (vs 21,25% bruta). Validação societária OK |
| **WS6.b1 — refactor LucroRealEngine** | 🔵 Pendente | Endereçar 2 gaps expostos pela Aurora v2: (a) `calcular_carga_total_mensal` aceitar `periodicidade: Literal["MENSAL","TRIMESTRAL","ANUAL"]` ajustando `TETO_IRPJ_SEM_ADICIONAL` proporcionalmente; (b) aceitar `lucro_csll_mensal` separado OU módulo de adições/exclusões pra calcular ambas as bases internamente |
| WS2 — Matriz 3×3 cenários 2026-2033 | 🔵 | Depende de WS6+WS10. Fonte oficial premissas (BCB Focus, IBGE) |
| WS4 — ERR-026/027/028 | 🟡 | response_model inerte, _erros perdido, CPF em campo CNPJ |
| WS3 — PDF refundido dual | 🔵 | Template genérico Conect |
| WS5b — Dossiê integrado | 🔵 | Empacotar verificação Rail R6 + dossiê de prova num único PDF |
| WS8 — Hook jurisprudência | 🔵 | — |
| WS11 — CLAUDE.md final + Teste do Legado | 🔵 | Última peça do refinamento |

### ⚪ Fora deste ciclo

- Elasticidade econômica (WS9) — projeção econômica vira projeto separado
- ISS municipal completo (5570 cidades) — sem fonte oficial unificada
- IPI/TIPI completo (10k NCMs) — sem API machine-readable
- Benefícios estaduais (27 UFs) — sem catálogo unificado
- Jurisprudência indexada CARF/STJ/STF — curadoria humana especializada

### 🔴 ERR ativos

| ID | Severidade | Status |
|---|---|---|
| ERR-012 (purge vs anonimizar LGPD) | 🟡 | Decisão jurídica pendente — LGPD Art. 19 §1º |
| ERR-026 (response_model inerte) | 🟡 | WS4 |
| ERR-027 (_erros perdido na persistência) | 🟡 | WS4 |
| ERR-028 (CPF em campo CNPJ via Vision) | 🟡 | WS4 |

ERRs fechados/prevenidos (ERR-005, 013, 017.b, 018.b, 049-058, 058.b, 058.c): `docs/roadmap/LOG_ERROS.md`.

### 🤖 Protocolo de auditoria multi-agente

Sequência defensável quando há decisão fiscal complexa:

1. Implementação inicial (assistente principal ou Viciado)
2. Auditoria arquitetônica (Chefe Deus — Teste do Legado)
3. Auditoria fiscal célula-a-célula (Luiz Moreira)
4. **Anti-alucinação obrigatória** (Escrivão — toda menção SC COSIT/Acórdão/súmula)
5. Correção blindada (Viciado — Pydantic V2/Decimal/frozen)
6. Re-auditoria Escrivão dos pontos onde Viciado tocou em citação

**Caso real (ERR-017.b):** WS6 etapa 2 v1 reprovada → reescrita → introduziu citação inventada (SC COSIT 174/2019) → bloqueada por Escrivão antes do commit.

Plano completo: `.claude/plans/revisar-o-plano-e-twinkling-hennessy.md` — 11 workstreams, 9 Rails.

---

## 🤖 AGENTES ESPECIALIZADOS

`.claude/agents/`:

| Agente | Responsabilidade | Quando invocar |
|---|---|---|
| **O Viciado** | Backend Python blindado, Decimal, Pydantic V2, testes | Código Python tributário |
| **Luiz Moreira** | Validação matemática fiscal, LC 214/2025, Fator R | Antes de congelar alíquotas |
| **Master Zen** | UX/UI, Dashboard Split Payment, glassmorphism | Interface |
| **O CHEFE** | Decisões arquitetônicas, roadmap | Visão macro |
| **Escrivão** | Verificação legal anti-alucinação (planalto.gov.br) | Antes de aceitar `amparo_legal` |
| **Migrador** | Atualização anual de tabelas (SM, CGSN, IVA) | Lei nova publicada |
| **Sentinela** | Coverage guard — ratio testes/LOC | Antes de PR/checkpoint |

---

## ⚡ PROTOCOLO DE CENÁRIO (MAX_FISCAL_04)

Premissa mudou (ex: Presumido → Real):

```
Cenario_Atual  → preservar como Cenario_Estudo_A
Cenario_Novo   → criar do zero com novas premissas
Comparativo    → exibir lado a lado (Delta de carga)
```

**"Cálculo por fora, crédito pleno, e blindagem fiscal total."** 🛡️
