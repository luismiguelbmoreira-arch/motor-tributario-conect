# Gap P0 — Auditoria Documental + LGPD

**Data:** 2026-04-08
**Disparado por:** observação do usuário logo após merge do PR #9
**Status:** Identificado, NÃO implementado. Item P0 da próxima sessão.
**Bloqueia:** qualquer expansão funcional do motor.

---

## O problema

A trilha de auditoria atual (`motor_tributario.py::trilha_auditoria[]`) prova
**como** o motor calculou (fórmula + amparo legal), mas **não prova**:

1. De **qual documento** veio cada número
2. **Qual hash** o documento tinha quando foi analisado
3. **Quem** subiu o documento e quando
4. **Que o cliente concordou** que aquele era o documento oficial

Isso cria 3 riscos concretos:

### Risco 1 — LGPD (Lei 13.709/2018)
Os PDFs originais (e-CAC, PGDAS-D, declarações) contêm PII pesada:
- CNPJ + razão social
- Faturamento mensal e anual detalhado
- Folha de pagamento
- Valores de tributos pagos

Hoje o pipeline é: upload → extrator Claude Vision → JSON → motor → diagnóstico → PDF → **arquivo descartado**.

- **Se descarta:** perde a prova do que foi analisado
- **Se retém para sempre:** viola LGPD Art. 16 (descarte após finalidade)

Precisa de retenção controlada com cifra + log de acesso + purge automático.

### Risco 2 — Responsabilização do contador (CTN Art. 142)
Cenário típico:
1. Cliente sobe PGDAS-D do mês errado
2. Motor calcula DAS errado
3. Receita autua o cliente
4. Cliente vira: "o contador disse que estava certo"

**Sem prova do arquivo-fonte com hash + termo de aceite, a culpa cai no contador.**
A trilha atual cita lei e fórmula, mas não cita o documento.

### Risco 3 — Erro de extração via Claude Vision
A extração via LLM tem margem de erro (>0% em qualquer modelo). Se o motor
extraiu R$ 1.158.950,86 mas o PDF original tinha R$ 1.158.950,68, sem o
PDF persistido não dá pra reconstruir o que foi visto.

---

## Esboço arquitetônico (próxima sessão)

### 1. Tabela `auditoria_documentos` (SQLModel)
```python
class AuditoriaDocumento(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    cnpj: str = Field(index=True)
    hash_sha256: str = Field(unique=True, index=True)
    nome_original: str
    mime_type: str
    tamanho_bytes: int
    paginas: int | None = None
    storage_path: str  # caminho relativo ao bucket cifrado
    uploaded_at: datetime
    uploaded_by_user_id: int = Field(foreign_key="users.id")
    analise_id: int = Field(foreign_key="analises.id", index=True)
    purge_after: datetime  # uploaded_at + 5 anos
    purged_at: datetime | None = None
```

### 2. Storage cifrado
```
storage/cliente/{cnpj_anonimizado}/{hash_curto}.pdf.enc
```
- AES-256-GCM
- Chave derivada por cliente (HKDF-SHA256 a partir de master key + cnpj)
- Master key em variável de ambiente (não no DB)
- Acesso só via função `decifrar_documento(hash, requester_user_id)` que loga em `auditoria_acessos`

### 3. Termo de aceite no upload
No fluxo `/analise/pdf`:
1. Usuário do escritório (ou cliente via portal) anexa PDFs
2. Sistema calcula hash de cada um
3. Tela mostra: "Confirmo que estes são os documentos oficiais que devem ser
   analisados para a competência X" + checkbox + assinatura digital (nome +
   timestamp + IP + user_id)
4. Só depois de aceito, processa

### 4. Trilha de auditoria com fonte
Cada passo do `trilha_auditoria` que dependeu de extração ganha:
```python
{
    "tipo": "CALCULO",
    "id": "FASE2_RBT12",
    "titulo": "Receita Bruta 12 meses",
    "formula": "...",
    "amparo_legal": "LC 123/2006, Art. 12, § 1º",
    "fonte_documento": {                          # NOVO
        "hash_sha256": "abc123...",
        "nome_original": "PGDASD-EXTRATO-...pdf",
        "pagina": 2,
        "campo_extraido": "Receita Bruta Acumulada (12m)",
    },
    "timestamp": "...",
}
```

### 5. Política de retenção (LGPD Art. 16 vs CTN Art. 173)
- **Reter:** 5 anos (CTN Art. 173 — prazo decadencial fiscal)
- **Cifrado o tempo todo** (LGPD Art. 46 — proteção)
- **Log de cada acesso** ao documento original (LGPD Art. 37)
- **Purge automático** após 5 anos via cron diário
- **Direito de eliminação** (LGPD Art. 18 V) — endpoint que purga
  imediatamente se o cliente solicitar formalmente

### 6. Endpoint `/auditoria/prova/{analise_id}`
Gera "dossiê de prova" exportável:
```
dossie_prova_{analise_id}.zip
├── 01_termo_aceite.pdf (assinado digitalmente)
├── 02_documentos_originais/
│   ├── PGDASD-EXTRATO.pdf  (decifrado on-the-fly)
│   ├── DAS_01_2026.pdf
│   └── ...
├── 03_diagnostico.json
├── 04_trilha_auditoria.json
├── 05_relatorio_cliente.pdf
├── HASHES.txt
└── README.txt
```

ZIP assinado com SHA-256 + chave do escritório.

---

## Tasks da próxima sessão (ordem sugerida)

1. **[1h]** Criar SQLModel `AuditoriaDocumento` + migration Alembic
2. **[1h]** Módulo `PY/storage_cifrado.py` (AES-GCM + HKDF + log)
3. **[30min]** Hook no `/analise/pdf` para calcular hash + persistir + retornar IDs
4. **[1h]** UI de termo de aceite no `analise_pdf.html`
5. **[2h]** Refactor da trilha de auditoria para incluir `fonte_documento` em cada passo extraído
6. **[1h]** Endpoint `/auditoria/prova/{analise_id}` + serialização ZIP
7. **[1h]** Cron de purge + endpoint manual de eliminação LGPD
8. **[1h]** Testes de integração end-to-end + golden standards
9. **[30min]** Documentação no README + atualização do CLAUDE.md

**Total estimado:** ~9h. Pode ser quebrado em 2-3 sessões.

---

## Bases legais que justificam o trabalho

| Base | Diz |
|---|---|
| **LGPD Art. 16** | Dados devem ser eliminados após o fim do tratamento |
| **LGPD Art. 18, V** | Titular pode pedir eliminação a qualquer momento |
| **LGPD Art. 37** | Necessário registro de operações de tratamento |
| **LGPD Art. 46** | Medidas técnicas de segurança são obrigatórias |
| **CTN Art. 173** | Prazo decadencial de 5 anos para constituição do crédito tributário |
| **CTN Art. 142** | Constituição do crédito tributário exige prova documental |
| **CFC NBC TG 1000** | Contador deve manter documentação que suporte cada lançamento |

---

## Não esquecer

Este gap **bloqueia** a expansão funcional do motor. Antes de adicionar:
- Simulador de margem
- Classificação automática de créditos IBS/CBS
- Tratamento setorial profundo
- Módulo Imposto Seletivo

...precisa garantir que o que **já existe** está auditavelmente provável.
Senão estamos construindo mais valor sobre uma fundação que pode ruir
na primeira fiscalização real do escritório.
