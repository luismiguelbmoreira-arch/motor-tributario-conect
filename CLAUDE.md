# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# 🏛️ MOTOR TRIBUTÁRIO CONECT — BÍBLIA DA REFORMA TRIBUTÁRIA

**Status:** 🚀 Produção — 1021 testes passando (100%) | 4 regimes + DIFAL + Cronograma + PDF educativo + Auditoria Documental LGPD + IDOR Guard + Stack front-back sincronizada
**Âncora Legal:** EC 132/2023 | LC 123/2006 | LC 214/2025 | LC 224/2025 | EC 87/2015 | LGPD 13.709/2018 | CTN Arts. 142 e 173
**Data Certificação:** 24/04/2026 (entrega plano Front/Backend Fases 1–5 + ERR-018.b IDOR guard)

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
MOTOR_CONECT_MASTER_KEY=<64 chars hex — gere com `python -c "import secrets; print(secrets.token_hex(32))"`>
JWT_SECRET_KEY=<chave JWT>
```

**⚠️ MOTOR_CONECT_MASTER_KEY** é a chave raiz da auditoria documental cifrada.
Perder essa chave = impossibilidade de decifrar PDFs antigos. Guardar em
cofre seguro (1Password, Bitwarden). Ver seção "🔐 AUDITORIA DOCUMENTAL".

### Fontes alternativas da master key (produção)

O `storage_cifrado._master_key()` aceita 3 fontes em ordem de prioridade:

| # | Fonte | Quando usar |
|---|---|---|
| 1 | `$MOTOR_CONECT_MASTER_KEY` env var | Dev local (via `PY/.env`) |
| 2 | Arquivo protegido (`/etc/motor-conect/master.key` ou `%PROGRAMDATA%\motor-conect\master.key`) | Deploy em servidor físico/VM. Permissões: owner do usuário do serviço, mode 0600 |
| 3 | `$MOTOR_CONECT_MASTER_KEY_AWS_SECRET` | Deploy cloud AWS (ECS/EC2/Lambda com IAM role) |

**Override do path do arquivo:** `$MOTOR_CONECT_MASTER_KEY_FILE=/caminho/custom.key`

**Setup servidor Linux:**
```bash
sudo mkdir -p /etc/motor-conect
sudo chown motor-conect:motor-conect /etc/motor-conect
sudo chmod 700 /etc/motor-conect
echo "<sua-chave-hex-64-chars>" | sudo tee /etc/motor-conect/master.key
sudo chmod 600 /etc/motor-conect/master.key
sudo chown motor-conect:motor-conect /etc/motor-conect/master.key
```

**Setup servidor Windows:**
```powershell
mkdir $env:PROGRAMDATA\motor-conect
Set-Content -Path "$env:PROGRAMDATA\motor-conect\master.key" -Value "<chave>"
icacls "$env:PROGRAMDATA\motor-conect\master.key" /inheritance:r /grant:r "NT SERVICE\MotorConect:(R)"
```

**Setup AWS Secrets Manager:**
```bash
aws secretsmanager create-secret --name motor-conect/master-key \
  --secret-string "$(python -c 'import secrets; print(secrets.token_hex(32))')"
```
Depois no `.env` do servidor: `MOTOR_CONECT_MASTER_KEY_AWS_SECRET=motor-conect/master-key`
Requer: `pip install boto3` + IAM role com permissão `secretsmanager:GetSecretValue`.

---

## 🏗️ ARQUITETURA — VISÃO GERAL

```
core/motor_tributario.py    ← Orquestrador principal + Dispatcher de regime
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
│
database/                    ← Pacote modularizado (era database.py monolítico)
├── connection.py            ← Engine + get_session
├── enums.py                 ← RegimeTributario, NivelAlerta, StatusAlerta, StatusAuditoria
├── models.py                ← UserDB, EmpresaDB, AuditoriaDocumentoDB, AuditoriaAcessoDB, etc.
└── repositories/            ← auditoria_repo, diagnostico_repo, empresa_repo, alerta_repo,
                                auditoria_tentativa_repo (IDOR guard)

services/
├── extrator_pdfs.py         ← Claude Vision API — extração de PDFs de clientes
├── storage_cifrado.py       ← AES-256-GCM + HKDF — auditoria documental LGPD
├── analise_buffer.py        ← Sessão de análise (hidratação do /resultado)
└── relatorio_pdf.py         ← Geração de PDF educativo

api/routers/                 ← Endpoints FastAPI segregados por domínio
├── auth.py                  ← /auth/login, /refresh (RefreshResponse), /me
├── auditoria.py             ← /auditoria/prova/cnpj/{digitos}, /auditorias
├── usuarios.py              ← CRUD de usuários (admin)
├── integracoes.py           ← /sieg/sincronizar, /integra/sincronizar, /integracoes/ecac/sync
│                              (router-level Depends(get_current_user) + ownership guard)
├── historico.py             ← Lista paginada de diagnósticos
└── configuracoes.py         ← /settings/tema, /settings/notificacoes (Fase 5)
│
tests/                       ← 1021 testes (100% passando)
├── test_fase2_simples.py    ← RBT12, Fator R, Anexo, Alíquota Efetiva
├── test_fase3_iva.py        ← Cronograma IBS/CBS 2026-2033, Split Payment
├── test_fase4_optout.py     ← Opt-Out, cenários comparativos
├── test_regime_guard.py     ← Guard Clauses (Camada 3 — bloqueia deploy se falhar)
├── test_mei_guard.py        ← MEI guard, DAS 2026, teto, sem crédito IVA
├── test_database.py         ← CRUD, Decimal como TEXT, LGPD, ciclo alertas
├── test_validadores.py      ← CNPJ/CNAE/NCM/UF
├── test_fase1_parar_sangramento.py  ← Plano Front/Backend Fase 1 (auth, IDOR)
├── test_idor_*.py           ← IDOR guard ERR-018.b
└── api/test_endpoints.py    ← Integração HTTP do contrato público
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

## 🔐 AUDITORIA DOCUMENTAL (LGPD + CTN)

Camada que bloqueia o vetor "dado errado culpa do contador" e cumpre
LGPD Art. 16/37/46 + CTN Arts. 142/173. Ativa automaticamente em toda
chamada de `POST /analise/pdf` autenticada.

### Fluxo completo de upload

```
1. Cliente/operador sobe PDFs via POST /analise/pdf (FastAPI UploadFile)
2. API chama processar_pdfs_bytes(conteudos, arquivos_nomes, user_id, persistir_auditoria=True)
3. Extrator Claude Vision processa → descobre CNPJ, RBT12, competência
4. Motor roda → gera diagnóstico + trilha_auditoria
5. Para cada PDF:
     a. hash_documento(bytes) → SHA-256 hex do plaintext
     b. cifrar_e_persistir(bytes, cnpj) → AES-256-GCM
        chave = HKDF-SHA256(MOTOR_CONECT_MASTER_KEY, salt=cnpj)
        path = data/auditoria/{sha256(cnpj)[:16]}/{hash[:16]}.bin
     c. registrar_documento_auditoria(...) → row em auditoria_documentos
6. Cada passo da trilha_auditoria ganha { "fonte": {documentos_ids, hashes, campo_origem} }
7. Diagnóstico retorna com _extracao.documentos_auditoria + auditoria_status
```

### Arquitetura dos módulos

```
PY/services/storage_cifrado.py  ← AES-256-GCM + HKDF, puro
├── cifrar_e_persistir(bytes, cnpj) → (hash, path)
├── decifrar(path, cnpj, hash_esperado) → bytes
├── hash_documento(bytes) → sha256 hex
├── anonimizar_cnpj(cnpj) → hash16 irreversível
├── existe(cnpj, hash) → bool
└── purge(cnpj, hash) → bool (sobrescreve + unlink, LGPD Art. 16)

PY/database/models.py::AuditoriaDocumentoDB   ← metadata em SQLite
├── hash_sha256 (unique, PK lógica)
├── empresa_cnpj (indexed)
├── nome_original, mime, tamanho, paginas
├── storage_path → ponteiro para arquivo cifrado
├── uploaded_at, uploaded_by_user_id
├── aceito_em, aceito_por_user_id, aceito_ip   ← termo de aceite digital
├── diagnostico_id (soft FK)
├── purge_after (uploaded_at + 5 anos)
└── purged_at

PY/database/models.py::AuditoriaAcessoDB      ← log LGPD Art. 37
├── documento_id (FK)
├── acessado_em, acessado_por_user_id, ip
└── motivo (obrigatório, 10-500 chars)

PY/services/extrator_pdfs.py
├── processar_pdfs_bytes(conteudos, *, arquivos_nomes, user_id, persistir_auditoria)
└── _inferir_campo_origem(passo_id) → label humano do campo-fonte

PY/main.py
└── POST /analise/pdf                     ← cifra + registra no upload (router default)
PY/api/routers/auditoria.py
└── GET /auditoria/prova/cnpj/{digitos}?motivo=... ← dossiê ZIP
```

### Formato do `fonte` em cada passo da trilha

```python
{
    "tipo": "CALCULO",
    "id": "FASE2_RBT12",
    "titulo": "Receita Bruta 12 meses",
    "formula": "...",
    "amparo_legal": "LC 123/2006, Art. 12, § 1º",
    "fonte": {                                   # ← NOVO (quando persistir_auditoria)
        "tipo": "extracao_pdf",
        "documentos_ids": [1, 2, 3],
        "documentos_hashes": ["abc123...", "def456...", "fed789..."],
        "campo_origem": "RBT12 (Receita Bruta 12m)"
    },
    "timestamp": "...",
}
```

### Endpoint de dossiê de prova

```bash
# Gera ZIP binário com todos os PDFs decifrados + HASHES.txt + README.txt
curl -H "Authorization: Bearer <JWT>" \
     "http://localhost:8000/auditoria/prova/cnpj/54657895000160?motivo=Fiscalizacao%20RFB%20processo%20123-2026" \
     -o dossie.zip

unzip dossie.zip
sha256sum originais/*.pdf   # deve bater com HASHES.txt
```

Cada decifragem registra linha em `AuditoriaAcessoDB` com `user_id + IP + motivo`.
CNPJ na URL é apenas dígitos (14 chars, sem pontuação).

### Política LGPD de retenção

| Arquivo | Onde | Por quanto tempo | Purge |
|---|---|---|---|
| PDF cifrado | `data/auditoria/{hash}/{id}.bin` | 5 anos (CTN Art. 173) | `storage_cifrado.purge(cnpj, hash)` + `marcar_documento_purgado(id)` |
| Metadata em DB | `auditoria_documentos` | 5 anos + marca `purged_at` | permanente como registro histórico |
| Log de acesso | `auditoria_acessos` | Permanente (LGPD Art. 37) | nunca purga |

Cron diário deve rodar `listar_documentos_purgaveis()` e executar o purge dos que passaram do prazo.

### Backup diário do DB (OBRIGATÓRIO em produção)

Os metadados em `auditoria_documentos` são **inúteis** sem o DB.
Perda do banco = impossibilidade de gerar dossiê mesmo com os arquivos
cifrados intactos. Use `PY/scripts/backup_db.py`:

```bash
# Execução manual
python PY/scripts/backup_db.py

# Dry run (só mostra o plano)
python PY/scripts/backup_db.py --dry-run
```

**Layout gerado:**
```
data/backups/
├── diarios/
│   ├── 2026-04-08.db.gz   ← retenção 30 dias rolling
│   ├── 2026-04-09.db.gz
│   └── ...
└── mensais/
    ├── 2026-04.db.gz       ← criado automaticamente no dia 1 do mês
    └── 2026-05.db.gz       ← permanente (purge manual apenas)
```

**Implementação:**
- Usa `sqlite3.Connection.backup()` (transação-safe) em vez de `shutil.copy`
- Comprime com gzip nível 9 (tipicamente 3-6× menor)
- Escrita atômica (tmp + rename) — se falhar no meio, não corrompe backup anterior
- Retorna exit code 0/1 para integração com cron

**Setup cron (Linux):**
```
0 3 * * * cd /app && /usr/bin/python PY/scripts/backup_db.py >> /var/log/motor-backup.log 2>&1
```

**Setup Task Scheduler (Windows):**
```
schtasks /Create /SC DAILY /ST 03:00 /TN "MotorConectBackup" ^
  /TR "python C:\app\PY\scripts\backup_db.py"
```

**Restauração:**
```bash
# 1. Parar API
# 2. Descomprimir
gzip -dk data/backups/diarios/2026-04-08.db.gz
# 3. Mover para a posição
mv data/backups/diarios/2026-04-08.db data/motor_tributario.db
# 4. Reiniciar API
```

### O que fazer se algo explodir

1. **Master key perdida** → PDFs antigos **irrecuperáveis**. Dossiê de casos novos funciona com nova key, antigos só pelos hashes em DB.
2. **DB corrompido** → Arquivos cifrados em disco são inúteis sem os metadados (hash, path, cnpj). **Backup diário do DB é obrigatório.**
3. **Cliente pede direito de eliminação (LGPD Art. 18 V)** → Chamar `storage_cifrado.purge()` + `marcar_documento_purgado()` para cada doc do CNPJ. Log em `auditoria_acessos` permanece.
4. **Fiscalização exige os originais** → Chamar `GET /auditoria/prova/cnpj/{digitos}?motivo=...` com justificativa detalhada.

---

## 🛑 REGRAS MÁXIMAS — MAX_FISCAL (Inegociáveis)

| ID | Diretriz |
| :--- | :--- |
| **MAX_01** | Proibido entregar valor final sem: Base → Deduções → Alíquota → Valor |
| **MAX_02** | Toda regra, alíquota ou isenção cita explicitamente a base legal |
| **MAX_03** | Declarar a data base ANTES do cálculo (regra do ano errado invalida tudo) |
| **MAX_04** | Premissa alterada → salvar como `Cenario_Estudo_A`, nunca deletar |
| **MAX_05** | Toda análise via `/analise/pdf` deve ter os PDFs-fonte cifrados e registrados em `auditoria_documentos` — sem isso o diagnóstico não pode ser usado em defesa jurídica. Ativado por `persistir_auditoria=True`. |
| **MAX_06** | Crédito B2B de fornecedor do Simples Nacional é **fração do DAS** (não `valor_operacao × alíquota IVA`). Fórmula: `credito = DAS_mensal × _fracao_iva_no_das(anexo, faixa, ano)`. Usar `DISTRIBUICAO_DAS[anexo][faixa]` como fonte única. LC 214/2025 Art. 47 §II + Arts. 344, 353, 356-360. |

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

## 🗺️ ROADMAP — STATUS ATUAL (24/04/2026)

| Fase | Status | Bloqueador |
| --- | --- | --- |
| Simples Nacional (Anexo I) | ✅ Certificado | — |
| Lucro Presumido | ✅ Certificado | — |
| MEI | ✅ Certificado | — |
| Auditoria Documental LGPD | ✅ Certificado | — |
| Plano Front/Backend (Fases 1-5) | ✅ Entregue | — |
| IDOR Guard horizontal (ERR-018.b) | ✅ Certificado | — |
| ERR-005 (CNAE incompleto ~970 CNAEs) | 🔴 Pendente | — |
| Lucro Real | 🔵 Próxima fase | — |
| Dashboard Split Payment | 🔵 Próxima fase | — |
| DIFAL Interestadual | 🟡 Pendente | — |
| Fase 4 (relatórios PDF clientes) | 🟡 Bloqueado | Documentos reais do escritório |

**ERR ativos críticos:** ERR-005 (CNAE incompleto), ERR-012 (purge vs anonimizar LGPD). Recentes fechados: ERR-013, ERR-018.b (IDOR), ERR-049 (JWT sub vs id), ERR-050 (uploaded_by_user_id), ERR-051 (salvar_diagnostico). Ver `docs/roadmap/LOG_ERROS.md`.

---

## 🤖 AGENTES ESPECIALIZADOS

Disponíveis como subagentes Claude Code (`.claude/agents/`):

| Agente | Responsabilidade | Quando invocar |
| --- | --- | --- |
| **O Viciado** | Backend Python blindado, Decimal, Pydantic V2, testes | Código Python tributário |
| **Luiz Moreira** | Validação matemática fiscal, LC 214/2025, Fator R | Antes de congelar alíquotas |
| **Master Zen** | UX/UI, Dashboard Split Payment, glassmorphism | Interface e visualizações |
| **O CHEFE** | Decisões arquitetônicas, roadmap, conflitos de prioridade | Visão macro |
| **Escrivão** | Verificação legal anti-alucinação (planalto.gov.br) | Antes de aceitar `amparo_legal` em código |
| **Migrador** | Atualização anual de tabelas fiscais (SM, CGSN, IVA) | Quando lei nova for publicada |
| **Sentinela** | Coverage guard — ratio testes/LOC, scaffolding de testes | Antes de qualquer PR/checkpoint |

---

## ⚡ PROTOCOLO DE CENÁRIO (MAX_FISCAL_04)

Quando premissa mudar (ex: regime Lucro Presumido → Real):

```
Cenario_Atual  → preservar como Cenario_Estudo_A
Cenario_Novo   → criar do zero com novas premissas
Comparativo    → exibir lado a lado (Delta de carga tributária)
```

**"Cálculo por fora, crédito pleno, e blindagem fiscal total."** 🛡️
