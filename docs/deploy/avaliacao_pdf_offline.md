# Avaliação — leitura local de PDF (offline) com pdfplumber

Pergunta: o exe consegue ler os PDFs do cliente sem internet (sem Claude Vision)?

Resposta curta: **só os PDFs que já têm texto** (PGDAS-D gerado pelo portal). Cartão CNPJ e
comprovante chegam como imagem e continuam precisando de Vision ou OCR.

**Decisão deste PR: só avaliação.** `pdfplumber` não entra em `requirements*.txt` e o extrator
(`services/extrator_pdfs.py`) não mudou.

## Como foi medido

- Script: `PY/scripts/avaliar_pdf_texto.py`. Imprime só páginas, caracteres, tabelas, tempo e a
  **presença** de rótulos por campo de `DadosExtraidosPDF`. Não imprime valores, CNPJ nem nomes.
- Ambiente: venv descartável, Python 3.12, pdfplumber 0.11.11 (pdfminer.six 20260107,
  pypdfium2 5.15.2). Windows 11.
- Amostra: os 4 PDFs de `samples/uploads_clientes/` (dados reais de cliente; aqui só a forma).

```
cd PY
uv venv ..\..\eval_venv && uv pip install --python ..\..\eval_venv pdfplumber
..\..\eval_venv\Scripts\python.exe scripts\avaliar_pdf_texto.py ..\samples\uploads_clientes
```

## Resultado (saída do script, 25/11/2026)

| Documento | Páginas | Sem texto | Caracteres | Tabelas | Tempo |
|---|---|---|---|---|---|
| Cartão CNPJ | 1 | 1 | 0 | 1 | 1,19 s |
| Comprovante de pagamento | 1 | 1 | 0 | 0 | 1,95 s |
| PGDAS-D declaração | 3 | 0 | 4058 | 9 | 0,33 s |
| PGDAS-D extrato | 3 | 0 | 4221 | 12 | 0,35 s |

Rótulos encontrados (✓) por campo:

| Campo | Cartão CNPJ | Comprovante | PGDAS-D declaração | PGDAS-D extrato |
|---|---|---|---|---|
| cnpj | — | — | ✓ | ✓ |
| razao_social | — | — | ✓ | ✓ |
| cnae_principal | — | — | — | — |
| uf_origem | — | — | ✓ | ✓ |
| faturamento_12m (RBT12) | — | — | ✓ | ✓ |
| rpa_referencia (RPA) | — | — | ✓ | ✓ |
| competencia (PA) | — | — | — | ✓ |
| das_ecac_referencia | — | — | — | ✓ |
| das_breakdown (IRPJ… ISS) | — | — | ✓ | ✓ |
| folha_salarios_12m | — | — | ✓ | ✓ |

## O que isso quer dizer

1. **Cartão CNPJ e comprovante são imagem.** 0 caracteres. Sem OCR, nada sai offline. O
   **CNAE** (que decide o Anexo do Simples) vem do Cartão CNPJ, então não sai offline.
2. **PGDAS-D tem texto e é rápido** (~0,3 s para 3 páginas). Os rótulos dos campos principais
   aparecem, mas o **valor quase sempre está na linha seguinte ou numa tabela**, não ao lado do
   rótulo. Um parser teria que usar `extract_tables()` e posições, não só regex de linha.
3. Nenhum dos PGDAS-D traz CNAE nem Anexo explícito.

## Recomendação

Híbrido, em PR futuro e só com aprovação:

- Texto local como **pré-checagem** (o PDF tem texto? é PGDAS-D? CNPJ do PDF bate com o da
  empresa?) e como **fallback offline** só para PGDAS-D com texto.
- Claude Vision (com a chave do usuário, PR #48) continua para documentos escaneados e para o CNAE.
- OCR local (Tesseract etc.) não foi avaliado: é dependência grande e binária.

Bloqueios antes de implementar:

- Adicionar `pdfplumber` (e `pypdfium2`, `pillow`, `cryptography` que vêm junto) precisa de
  sim explícito.
- Qualquer parser que extraia **valores fiscais** (RBT12, RPA, DAS por tributo) precisa de
  validação da skill `conecte-se-team:luiz-moreira` e de testes contra o motor. Este PR não
  extrai valor nenhum.

## Não verificado

- PDFs de outros clientes, outros anos ou PGDAS-D retificador.
- PDFs protegidos por senha.
- Tamanho que o pdfplumber somaria ao exe do PyInstaller.
