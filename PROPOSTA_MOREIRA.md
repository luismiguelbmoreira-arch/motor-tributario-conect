# Motor Tributário Conect — Proposta Técnica
**Destinatário: Organização Contábil Moreira — CNPJ 50.803.014/0001-11**
**Data: 28 de Abril de 2026**

---

## 1. Já rodamos seus dados

Antes de qualquer contrato, submetemos os 4 PDFs da Moreira ao motor (Cartão CNPJ + Comprovante + 2 PGDAS-D do e-CAC). Resultado da extração automática:

| Campo | Valor extraído | Status |
| :--- | :--- | :--- |
| CNPJ | 50.803.014/0001-11 | ✅ Mod-11 válido |
| Razão social | ORGANIZACAO CONTABIL MOREIRA - SOCIEDADE SIMPLES LTDA | ✅ |
| CNAE principal | 6920601 (escritório de serviços contábeis) | ✅ |
| UF | SP | ✅ |
| RBT12 (fev/2026) | R$ 3.563.681,62 | ✅ Anexo III — Fator R aplicável |
| RPA de referência | R$ 251.304,00 | ✅ |
| DAS pago (e-CAC) | R$ 29.202,78 | ✅ |
| Competência | 02/2026 | ✅ |
| Anexo | III | ✅ |
| Folha salários 12m | não encontrada | 🟡 Precisa ser enviada pelo cliente |
| **Confiança da extração** | **97%** | ✅ Acima do limiar de 80% |

Com RBT12 de R$ 3,56M e o teto Simples em R$ 4,8M, a Moreira está em **74% do teto**. Abaixo do gate de 90% (R$ 4,32M), mas próximo o suficiente para monitoramento mensal ser obrigatório.

**O que falta para completar o diagnóstico:** folha de salários acumulada 12m (pró-labore + salários + encargos). Sem esse número o Fator R fica incalculável e a recomendação de Opt-Out não pode ser emitida com confiança.

---

## 2. O que o produto entrega

A entrada padrão é um `HistoricoSeisMeses` — 6 meses sequenciais de dados fiscais da empresa. A saída é um `DiagnosticoConsolidado` com:

**Recomendação consolidada** (uma de três):
- `MANTER_SIMPLES` — Simples puro é mais vantajoso na janela analisada
- `OPT_OUT` — Separar apuração CBS/IBS do DAS é vantajoso; acionar antes da janela semestral (abril ou setembro)
- `REVISAR_MANUALMENTE` — Dados divergentes ou empresa em zona limítrofe; decisão exige contador

**Nível de confiança** (ALTA / MEDIA / BAIXA) calculado por unanimidade de votos mensais. Se 6/6 meses apontam para a mesma recomendação → ALTA. Se 5/6 → MEDIA. Abaixo disso → BAIXA, e o operador é obrigado a revisar antes de agir.

**Alertas automáticos detectados na janela:**
- Fator R cruzando o limiar de 0,28 entre meses consecutivos (migração Anexo III ↔ V)
- Mudança de Anexo declarado entre meses
- RBT12 ≥ 90% do teto Simples — gate Rail R7, análise Opt-Out obrigatória (LC 123/2006 Art. 3º §9)
- Sazonalidade detectada: CoV > 25% + pico > 1,5× mediana
- Outlier de faturamento: mês com > 3× ou < 1/3 da mediana (sinaliza erro de lançamento)
- Divergência entre Anexo declarado e Anexo esperado pelo CNAE (Res. CGSN 140/2018)

**Tendência da janela:** ASCENDENTE / DESCENDENTE / ESTAVEL calculada por regressão linear sobre os 6 meses.

---

## 3. Como os dados entram

O fluxo atual:

```
e-CAC → PDFs (PGDAS-D + Cartão CNPJ + Comprovante)
           ↓
    Claude Vision API  →  extrator automático
           ↓
    HistoricoSeisMeses (schema validado — Pydantic V2)
           ↓
    Motor Tributário  →  DiagnosticoConsolidado
```

A extração é automática — o operador sobe os PDFs, o motor lê. Não há digitação manual de valores. Cada passo da extração gera trilha de auditoria com hash SHA-256 do documento original, base legal citada e timestamp.

O que **não** existe hoje: sincronização automática com o Nibo. Quando a parceria com o Nibo fechar, a entrada passa a ser via API deles (sem upload manual de PDF). A arquitetura já tem o slot reservado no pacote `integrations/`.

---

## 4. Compliance que já está pronto

**LGPD:** cada PDF subido é cifrado com AES-256-GCM (chave derivada por CNPJ via HKDF-SHA256) e armazenado em disco. Retenção de 5 anos conforme CTN Art. 173. Eliminação via `purge()` — sobrescreve o arquivo e marca como purgado no banco.

**Trilha refazível (CTN Art. 142):** cada cálculo registra base → deduções → alíquota → valor final + artigo de lei. O script `refazer_calculo.py` reconstrói qualquer número apenas a partir do log — sem precisar rodar o motor de novo. Útil em fiscalização.

**Auditoria de acesso:** cada vez que um PDF é decifrado para gerar dossiê de prova, o acesso é registrado com user_id + IP + motivo obrigatório. Log permanente, nunca purgável (LGPD Art. 37).

**Reforma Tributária 2026-2033:** o motor já tem o cronograma de transição IBS/CBS por ano implementado. Split Payment entra em vigor em 2026 — o módulo Tesoureiro projeta o impacto no fluxo de caixa mês a mês até 2033.

---

## 5. Estado atual do motor

- **1.297 testes passando (100%)** — 4 regimes (Simples, Presumido, MEI, Lucro Real)
- Guard Clauses em 3 camadas: Pydantic V2 + engine + pytest. Guard removida = CI quebra, deploy bloqueado.
- Constantes fiscais versionadas por data (teto Simples, limite MEI, sublimite ICMS/ISS): lookup por data de competência, não por "ano corrente".
- Resolução CNAE → Anexo: 5 categorias semânticas testadas, 14 casos cirúrgicos cobertos.
- Matriz societária 13 tipos × 4 regimes: 52 combinações com elegibilidade e amparo legal por célula.

---

## 6. Roadmap real

| Fase | O que entrega | Status |
| :--- | :--- | :--- |
| **0a** | `HistoricoSeisMeses` + `DiagnosticoConsolidado` + 5 arquétipos de cliente | ✅ Em finalização |
| **1** | Conectar extrator PDF → `HistoricoSeisMeses` automaticamente | 🔵 Próxima |
| **2** | Dashboard SaaS: painel por cliente, série histórica, alertas visuais de transição | 🔵 Pendente |
| **3** | Integração Nibo via API — substitui upload manual de PDF | 🟡 Pendente parceria |
| **4–5** | Alertas ativos de multas, obrigações acessórias por regime, configurações por escritório | 🔵 Pendente |

---

## 7. O que a Moreira precisa enviar agora

Para gerar o `DiagnosticoConsolidado` completo dos últimos 6 meses:

1. **PDFs já testados e funcionando:** Cartão CNPJ + Comprovante de Pagamento + PGDAS-D (Declaração ou Extrato) — para cada mês da janela (6 meses)
2. **Folha de salários 12m** (pró-labore + CLT + encargos) — qualquer documento contábil ou planilha serve. Sem esse número o Fator R fica em aberto.

Com esses dados em mãos, o diagnóstico consolidado de 6 meses roda em menos de 1 minuto.

---

**Motor Tributário Conect**
Diagnóstico parcial (1 mês) rodado em 25/04/2026 — confiança 97%
