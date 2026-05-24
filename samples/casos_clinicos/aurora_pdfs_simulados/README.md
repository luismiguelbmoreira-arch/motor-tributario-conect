# Aurora — PDFs simulados (redesign 2026-05-09)

Esta pasta **substitui** `lucro_real_aurora_ficticio/fixture_completa.json`
(movida para `.lixeira/aurora_v2_calculadora_2026-05-09/`).

## Por quê

A fixture anterior tratava o motor como **calculadora primária** — definia
DRE completa, adições/exclusões, base IRPJ/CSLL, etc., e o motor
recalculava tudo do zero. Isso violava a visão SaaS
(`project_visao_saas.md`): motor é **EXTRATOR + PARAMETRIZADOR + PROJETOR**
da Reforma Tributária 2026-2033 — consome documentos do contador, **não
calcula impostos do zero**.

## Estrutura

Cada arquivo `*.json` simula o **output do extrator Claude Vision**
(`services/extrator_pdfs.py::DadosExtraidosPDF` serializado), como se um
PDF do contador tivesse sido extraído. O pipeline canônico
(`services/projecao_pipeline.py::gerar_projecao_pipeline`) consome essa
estrutura via adapter `DocumentoFiscalExtraido.from_dados_extraidos_pdf`
e gera o `DeltaReformaTributaria` (carga atual vs cenário CBS/IBS).

| Arquivo | Conteúdo |
|---|---|
| `das_competencia_2026-06.json` | DAS extraído do PDF de junho/2026 |
| `expected_delta_2027.json` | Δ Reforma esperado quando projetar 2027 |

## Como usar (CLI ou pytest)

```bash
# CLI: roda pipeline com mock que lê este JSON
python PY/scripts/projetar_reforma_cli.py \
    --pdf samples/casos_clinicos/aurora_pdfs_simulados/das_competencia_2026-06.json \
    --ano-alvo 2027 \
    --regime-atual PRESUMIDO \
    --mock
```

```python
# Em testes:
import json
from services.projecao_pipeline import gerar_projecao_pipeline

with open("samples/.../das_competencia_2026-06.json") as f:
    payload = json.load(f)

def _fake_extrator(_bytes):
    class D: pass
    d = D()
    for k, v in payload.items():
        setattr(d, k, v)
    return d

delta = gerar_projecao_pipeline(
    [b"placeholder"], ano_alvo=2027, regime_atual="PRESUMIDO",
    extrator=_fake_extrator,
)
```

## Empresa simulada

Mesma identidade ficcional da Aurora v2 anterior — INDÚSTRIA AURORA LTDA,
indústria de pré-moldados de concreto, Lucro Presumido, ~R$ 95M anual
(R$ 7.916.666,67 mensal médio). Tributos paragens extraídos via Claude
Vision conforme os PDFs reais que o contador entregaria.

Histórico completo da modelagem fiscal (DRE, ECF, adições/exclusões,
créditos PIS/COFINS, etc.) está preservado em
`.lixeira/aurora_v2_calculadora_2026-05-09/fixture_completa.json` — pode
ser consultado pra entender a aritmética por trás dos valores extraídos
nos PDFs simulados.
