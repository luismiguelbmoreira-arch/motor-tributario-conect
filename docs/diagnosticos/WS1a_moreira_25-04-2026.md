# Diagnóstico Empírico WS1.a — PDFs Organização Contábil Moreira

**Data:** 25/04/2026 14:00 BRT
**Operador:** Refinamento Final — Sprint 1 (auto mode)
**Pipeline:** `services/extrator_pdfs.extrair_dados_pdfs` (Claude Vision API, modelo `claude-sonnet-4-6`, prompt v2.2-2026-04-02)
**Script:** `PY/scripts/diagnosticar_moreira.py`

---

## TL;DR

**O pipeline NÃO está falhando com os PDFs reais da Moreira.** Quando os 4 PDFs (Cartão CNPJ + Comprovante + 2 PGDAS-D) são submetidos juntos, a Vision API extrai todos os campos obrigatórios com **97% de confiança**.

A percepção de "API está falhando" provavelmente vem de uma das hipóteses:
1. Teste anterior aos fixes ERR-054 (load_dotenv) e ERR-051 (persistência), agora resolvidos
2. Teste via UI `/analise/pdf` que tem camada adicional de guardião 422 (main.py:1105-1137)
3. Submissão de subconjunto incompleto (Cartão sem PGDAS-D, ou PGDAS-D sem Cartão)

**Recomendação:** WS1 muda foco de "consertar bug" para "refinar mensagem 422" (WS1.c) — quando faltar documento, dizer EXATAMENTE qual.

---

## Cenário 1 — 4 PDFs juntos (caso real)

| Campo | Valor extraído | Validação |
|---|---|---|
| CNPJ | `50.803.014/0001-11` | ✅ 14 dígitos |
| Razão social | `ORGANIZACAO CONTABIL MOREIRA - SOCIEDADE SIMPLES LTDA` | ✅ |
| CNAE principal | `6920601` (Contabilidade) | ✅ |
| UF | `SP` | ✅ |
| Faturamento 12m (RBT12) | `R$ 3.563.681,62` | ✅ Anexo III aplicável |
| RPA referência | `R$ 251.304,00` | ✅ |
| DAS e-CAC pago | `R$ 29.202,78` | ✅ |
| Competência | `02/2026` | ✅ |
| Anexo | `III` (Fator R aplicável a Contabilidade) | ✅ |
| Folha salários 12m | `null` | 🟡 **Não encontrada** — não veio nos PDFs (cliente precisa subir) |
| Receita com ST ICMS | `null` | 🟡 Não declarado (provavelmente não tem) |
| Atividades detalhadas | `null` | 🟡 Mono-atividade |
| **Confiança extração** | **0.97** | ✅ Acima de 0.8 (limiar `EXTRATOR_CONFIANCA_MINIMA`) |

**Status:** ✅ OK — todos os campos obrigatórios extraídos.

**Observação da Vision (texto integral):**
> "Empresa optante pelo Simples Nacional, atividade principal de escritório de serviços contábeis (CNAE 69.20-6-01), enquadrada no Anexo III. ISS recolhido em valor fixo em guia do Município (zerado no DAS). Fator r não se aplica. Declaração retificadora transmitida em 04/03/2026, com pagamento realizado em 20/03/2026 via Banco Itaú (341), agência 0076, estabelecimento 0124. Todos os valores consistentes entre PGDAS-D, Extrato do Simples Nacional e Comprovante de Arrecadação."

---

## Cenário 2 — Apenas os 2 PGDAS-D (sem Cartão CNPJ)

**Status:** ❌ ValidationError — `cnae_principal: None`

**Diagnóstico:** **NÃO É BUG.** PGDAS-D não traz CNAE; ele vem do Cartão CNPJ. Sem o Cartão, IA retorna null e Pydantic rejeita corretamente.

**Categoria:** WS1.c (documento insuficiente, guardião funcionando).

**Refinamento necessário:** mensagem 422 hoje fala "Input should be a valid string" — pouco útil pro operador. Trocar por: `"Cartão CNPJ ausente — não foi possível inferir CNAE principal. Suba o Cartão CNPJ junto com o PGDAS-D."`

---

## Cenário 3 — Cartão CNPJ + Comprovante de Pagamento

**Status:** ❌ ValidationError — `faturamento_12m: None`, `rpa_referencia: None`

**Diagnóstico:** **NÃO É BUG.** Nem Cartão CNPJ nem Comprovante de Pagamento contêm RBT12 ou RPA. Esses vêm do PGDAS-D (Declaração ou Extrato). Sem PGDAS-D, IA retorna null e Pydantic rejeita.

**Categoria:** WS1.c (documento insuficiente, guardião funcionando).

**Refinamento necessário:** mensagem 422 deveria dizer: `"PGDAS-D ausente — não foi possível extrair RBT12. Suba a Declaração ou Extrato do PGDAS-D do e-CAC."`

---

## Hipóteses sobre "API está falhando" reportada pelo usuário

A. **Teste anterior aos fixes recentes** (ERR-054 load_dotenv, ERR-051 persistência) — pode ter sido confundido com "API falha", mas era bug de wire que está resolvido.

B. **Endpoint `/analise/pdf` (camada acima do extrator)** tem guardião adicional em `main.py:1105-1137` que rejeita SIMPLES + B2B sem NFe + Folha. Se o user está testando via UI, esse guardião pode estar respondendo. **Q6 já decidiu subir NFe + folha.**

C. **Subconjunto incompleto** — se o user subiu só 2-3 PDFs num teste, caiu nos cenários 2 ou 3 (que falharam por documento faltante).

D. **Bug ERR-028 (CPF em campo CNPJ)** — não reproduzido neste teste (CNPJ veio correto), mas pode acontecer em PDFs de MEI ou em layouts diferentes.

---

## Próximas ações

| Ação | Workstream | Prioridade |
|---|---|---|
| Refinar mensagens 422 do extrator e do guardião `/analise/pdf` | **WS1.c** | Alta |
| Testar via endpoint web `/analise/pdf` (FastAPI rodando) com cenário 1 | **WS1.a** (extensão) | Média |
| Adicionar `samples/uploads_clientes/MOREIRA/` como fixture E2E | **WS1.a** | Alta |
| Pedir ao usuário NFe + folha 12m da Moreira (Q6) | **Externo** | Média |
| Endurecer ERR-028 (Pydantic field_validator no CNPJ) | **WS4** | Alta |

---

## Arquivos relevantes

- [PY/services/extrator_pdfs.py](../../PY/services/extrator_pdfs.py)
- [PY/main.py:1105-1137](../../PY/main.py) (guardião 422 por regime)
- [PY/scripts/diagnosticar_moreira.py](../../PY/scripts/diagnosticar_moreira.py) (script reproduzível)
- [samples/uploads_clientes/MOREIRA/](../../samples/uploads_clientes/MOREIRA/) (4 PDFs reais)

---

## Custo da chamada

3 chamadas Claude Vision API (sonnet-4-6), 4 + 2 + 2 PDFs = **8 documentos processados**. Custo estimado: ~$0.05-0.10 USD.
