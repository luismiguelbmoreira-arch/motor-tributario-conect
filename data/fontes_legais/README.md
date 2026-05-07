# `data/fontes_legais/` — Cache local de fontes normativas

Cache de leis e atos normativos consultados pelo agente **Escrivão** durante
a validação anti-alucinação (MAX_07). Resolve bloqueio operacional registrado
em 07/05/2026: WebFetch contra Planalto socket-dropping em 4+ rodadas
consecutivas.

## Por que existe

Sem fonte primária acessível pelo Escrivão, validações fiscais dependem de
fontes secundárias (doutrina, comentários de escritórios). Rail R1 (Fonte
normativa única) exige fonte primária citada literalmente — sem cache local,
qualquer fiscalização real vira frágil.

## Decisão arquitetônica (07/05/2026)

WebFetch contra Planalto falha com socket-dropping persistente (provável
limitação do tool, não do servidor). **`curl` direto contra o mesmo URL
funciona** — HTTP 200, conteúdo completo. Adotamos:

- **Captura via curl** (HTML canônico do Planalto) salvo em `planalto/`
- SHA-256 de cada arquivo registrado em `HASHES.txt`
- Escrivão lê do cache local antes de tentar WebFetch

Fontes secundárias mapeadas mas não usadas na captura inicial:
- Câmara legin: só metadados de alteração, não texto integral
- LexML: só metadados (aponta mirrors)
- Senado: SPA com texto via JS (curl pega só shell vazio)
- DOU/in.gov.br: socket-dropping também via WebFetch

Se Planalto cair pra curl no futuro, fallback é **mirror Senado** mas via
WebFetch (que renderiza JS) — texto extraído em Markdown, não bit-exato.

## Estrutura

```
data/fontes_legais/
├── README.md                                      ← este arquivo
├── HASHES.txt                                     ← registro canônico de captura
└── planalto/                                      ← snapshots HTML do Planalto
    ├── lcp123_v2026-05-07.html                    ← LC 123/2006 (Simples Nacional)
    ├── lcp214_v2026-05-07.html                    ← LC 214/2025 (IBS/CBS/IS)
    └── lcp227_v2026-05-07.html                    ← LC 227/2026 (alterações)
```

**Naming**: `lcpXXX_vYYYY-MM-DD.html` — data = data da captura, não da
publicação. Texto consolidado muda quando LCs posteriores alteram, então
o snapshot reflete o estado da norma na data da captura.

## Formato do `HASHES.txt`

Uma linha por arquivo, separada por ` | `:

```
sha256 | caminho_relativo | url_canonica | data_captura | fonte
```

`fonte` ∈ {`planalto`, `senado`, `camara`, `in_gov_br`} — origem do
snapshot. Permite priorização (Planalto > Senado > Câmara > DOU) quando
houver múltiplas versões da mesma norma.

## Protocolo de captura

### Automático (preferido — funcionou em 07/05/2026)

Via `curl` direto contra Planalto:

```bash
curl -sS -L -A "Mozilla/5.0" --max-time 120 \
    "https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm" \
    -o data/fontes_legais/planalto/lcp214_v$(date +%Y-%m-%d).html

sha256sum data/fontes_legais/planalto/lcp214_v$(date +%Y-%m-%d).html
# adicionar linha em HASHES.txt
```

### Fallback 1 — WebFetch contra Senado

Quando Planalto cair pra `curl`. Senado é SPA — `curl` retorna shell vazio,
mas WebFetch renderiza JS e extrai texto em Markdown. Salvar como `.md` em
`senado/lcpXXX_vYYYY-MM-DD.md`.

### Fallback 2 — Captura manual via browser

Quando WebFetch também falhar. Operador baixa via browser (Ctrl+S → "página
completa"), salva em `planalto/` ou `senado/` conforme origem, calcula
SHA-256, atualiza `HASHES.txt`.

## Protocolo de uso pelo Escrivão

Atualizado em `.claude/agents/escrivao.md`. Ordem de consulta:

1. **Cache local primeiro** — lê `HASHES.txt`, abre arquivo correspondente
   via Read tool. Cita URL canônica + SHA na resposta.
2. **WebFetch primária** — tenta `planalto.gov.br` se cache não tem a norma.
3. **Fallback secundário** — Senado/Câmara/DOU.
4. **Última opção** — convergência ≥3 fontes secundárias autoritativas
   (Mayer Brown, Tauil & Chequer, Mattos Filho, Conjur, etc.). Marcar
   `fonte_secundaria=True` na resposta. Apenas quando primário e mirrors
   falharem.

## Atualização periódica

Snapshots devem ser **re-capturados** quando:
- LC posterior altera dispositivos da norma (ex: LC 227/2026 alterou
  Art. 348 da LC 214/2025 — captura de LC 214 pré-LC 227 fica obsoleta).
- Migrador anual atualiza tabelas (Resoluções CGSN saem em out/nov).
- 6 meses sem re-captura — política conservadora.

Snapshot novo NÃO sobrescreve antigo: vira `lcp214_v2026-11-XX.html` ao
lado, e `HASHES.txt` registra ambos. Caller (Escrivão) escolhe a versão
vigente pela `data_captura` mais recente.

## Política LGPD

Sem dado pessoal — leis são públicas e atos normativos não contêm PII.
Cache pode ser commitado no repositório git sem restrição.

## Histórico

- **07/05/2026** — criação. Captura inicial das 3 LCs chave do projeto via
  curl direto contra Planalto (WebFetch estava falhando, curl funcionou):
  LC 123/2006 (1.6MB), LC 214/2025 (5.2MB), LC 227/2026 (1.3MB).
  Validação: 12 artigos críticos da LC 214 (47, 57, 108, 127, 138, 172,
  180, 348, 409, 410, 412, 544) confirmados presentes via grep.
