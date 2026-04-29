# 10 Simulações COMPLEXAS — Stress-Test Fase 0a

**Data:** 29/04/2026 | **Autor:** Luiz Moreira (cravamento) + Caso-Clínico (consolidação)
**Branch:** `fase-0a-historico-seis-meses` | **Suite atual:** 1360 testes verdes

## 🎯 Diferença vs validação falsificável simples

| Documento | Cenários | Complexidade | Objetivo |
|---|---|---|---|
| `validacao_falsificavel_fase0a.md` | 16 simples | 1 dimensão por cenário | Verificar fórmula básica |
| **`simulacoes_complexas_fase0a.md`** (este) | **10 adversariais** | **3+ dimensões combinadas** | **Stress-test + vetores RFB** |

Cada simulação aqui combina **3+ dimensões de complexidade**: mudança de regime, cruzamento de Anexo, mix heterogêneo de operações, múltiplas UFs, sazonalidade extrema, NCM monofásico, profissão regulamentada, MEI estourando teto, regimes especiais (cooperativa/igreja), Lucro Real.

---

## 📊 Tabela Síntese — 10 Simulações

| # | Nome | Complexidades combinadas | RBT12 range | Regime | Recomendação esperada | Confiança | Bug que tenta expor |
|---|---|---|---|---|---|---|---|
| **C01** | Padaria + Botijão GLP | Anexo I + monofásico + sazonalidade Páscoa + DEVOLUCAO_VENDA | 1,42M–1,55M | SIMPLES | MANTER_SIMPLES | MEDIA | Motor não trata Imposto Seletivo (LC 214/2025 Art. 409) |
| **C02** | Software cruzando R$ 4,32M | Crescimento + sublimite ICMS + Gate R7 + Fator R cruza 0,28 | 2,80M–4,71M | SIMPLES | OPT_OUT | ALTA | `>` em vez de `>=` no Fator R; cache de Anexo entre meses |
| **C03** | Restaurante pró-labore baixo | Fator R 0,15 estável + Anexo V faixa 4 + Presumido vence | 1,65M–1,82M | SIMPLES | MIGRAR_PRESUMIDO | ALTA | Cliente perdeu prazo opção janeiro |
| **C04** | Construtora multi-UF | Anexo IV + DIFAL EC 87/2015 + ISS cap + outlier 5× | 2,10M–2,95M | SIMPLES | MANTER_SIMPLES + alertas | MEDIA | ISS cap não aplicado; DIFAL B2C errôneo |
| **C05** | TI borderline 0,28 zigue-zague | FR oscila 0,275↔0,285 + 4 mudanças Anexo + 13º | 920k–1,08M | SIMPLES | REVISAR_MANUALMENTE | BAIXA | Cache de anexo entre meses; arredondamento `>=` vs `>` |
| **C06** | MEI Caminhoneiro estourando | MEI_CAMINHONEIRO + 98,57% teto R$ 251.600 + 2 picos | 215k–248k | SIMPLES (alias MEI) | OPT_OUT | ALTA | Teto único R$ 81k em vez de versionado por modalidade |
| **C07** | Igreja com bazar | ORG_RELIGIOSA + atividade-meio tributada + folha pastoral | 480k–510k | SIMPLES | REVISAR_MANUALMENTE | BAIXA | Sem segregação atividade-fim vs meio (STF RE 325.822) |
| **C08** | Cooperativa agrícola | COOPERATIVA + ato cooperativo vs terceiro + segregação imperfeita | 1,90M–2,40M | SIMPLES | REVISAR_MANUALMENTE | BAIXA | Schema sem campo ato_cooperativo (Lei 5.764/71 Art. 79) |
| **C09** | Filial vs Raiz consolidado | Filial 0002 + RBT12 raiz alto + virada faixa 5→6 + 2 UFs | 3,40M–3,72M | SIMPLES | MIGRAR_PRESUMIDO | MEDIA | Operador declara só RBT12 filial (LC 123 Art. 3º §4 I) |
| **C10** | Lucro Real com prejuízo | regime=REAL + 2 meses prejuízo + ICMS-ST + crédito imobilizado | 12,5M–14,2M | REAL | MIGRAR_REAL (manter) | MEDIA | Motor calcula como Simples por engano |

---

## 📋 Tabela de Validação Excel-Friendly (10 linhas críticas)

| Sim | Mês | Campo a verificar | Valor esperado | Tolerância | Lei amparo |
|---|---|---|---|---|---|
| **C01** | 2025-12 | DAS M3 (Anexo I faixa 4) | R$ 16.046,49 | ±R$ 0,05 | LC 123 Art. 18 §1º |
| **C02** | 2025-11 | Anexo aplicado M3 (FR=0,2841) | III | exato | LC 123 Art. 18 §24 |
| **C02** | 2026-02 | Alerta `RBT12_90PCT_TETO` | DISPARA (98,125%) | exato | Rail R7 |
| **C03** | 2025-10 | Δ Simples vs Presumido | +4,93% (R$ 6.809) | ±0,1pp | Lei 9.249/95 Art. 15 §1º III "a" |
| **C04** | 2026-03 | ISS efetivo aplicado (cap) | R$ 72.500,00 (5%) | ±R$ 0,02 | LC 123 Art. 18 §5°-F |
| **C04** | 2025-11 | `difal_status` | INDISPONIVEL_AGREGADO | exato | EC 87/2015 / ADI 5464 |
| **C05** | qualquer | Recomendação consolidada | REVISAR_MANUALMENTE | exato | Bug-prevention OLS |
| **C05** | 2025-11→2026-01 | Alertas FATOR_R_ATRAVESSOU_028 | ≥2 | mín | LC 123 Art. 18 §24 |
| **C06** | 2026-03 | RBT12 vs teto MEI Caminhoneiro | 98,57% de R$ 251.600 | exato | LC 188/2021 |
| **C07** | qualquer | Recomendação | REVISAR_MANUALMENTE + BAIXA | exato | STF RE 325.822 |
| **C08** | qualquer | DAS sem segregação vs com | Diferença ~5× | ±10% | Lei 5.764/71 Art. 79 |
| **C09** | 2026-01 | Faixa virada 5→6 (RBT12=3,64M raiz) | faixa 6, alíq 8,62% | ±0,02pp | LC 123 Art. 13 §1º |
| **C10** | 2025-12 | DEVOLUCAO_VENDA M5 (380k) coerência | delta < 1% | exato | Schema fix #1 |

---

## ⚠️ Vetores RFB / SEFAZ por Simulação

| Sim | Vetor | Severidade | Defesa |
|---|---|---|---|
| C01 | Receita monofásica (botijão) na base do DAS Anexo I | 🔴 Crítico | Segregar NF-e por CFOP; laudo CST/CSOSN |
| C02 | PGDAS-D divergente >0,5% em meses de troca de Anexo | 🔴 Crítico | Refazer cálculo do log (Rail R6) |
| C03 | Migração pra Presumido fora do prazo de janeiro | 🟡 Alto | DEFIS + comunicação até último dia útil de janeiro |
| C04 | DIFAL B2C cobrado por SEFAZ estadual indevido | 🟡 Alto | ADI 5464 STF + Convênio CONFAZ 93/2015 cláusula 9ª |
| C04 | ISS acima de 5% por motor não chamar `calcular_partilha_iss_cap` | 🔴 Crítico | Teste regressivo obrigatório no engine Anexo IV/V |
| C05 | Fator R com regra de arredondamento divergente | 🟡 Alto | ROUND_HALF_UP em todos os Decimal |
| C06 | Desenquadramento retroativo MEI (LC 123 Art. 18-A §7º) | 🔴 Crítico | DAS recalculado mês a mês com multa 20% |
| C07 | Atividade-meio sem segregação contábil — perda imunidade | 🔴 Crítico | Filial separada para bazar OU contabilidade segregada auditada |
| C08 | Cooperativa sem segregação ato-cooperativo | 🔴 Crítico | Plano de contas segregado IN RFB 2.058/2021 |
| C09 | Filial RJ sem GIA-RJ regular para ICMS por fora do DAS | 🟡 Alto | Inscrição estadual filial + GIA mensal SEFAZ-RJ |
| C10 | Lucro Real sem LALUR ou prejuízo fiscal mal apurado | 🔴 Crítico | LALUR digital + ECF anual + auditoria contábil |

---

## 📦 Dependências de Fases Posteriores (Gap explícito)

| Sim | Funcionalidade necessária | Onde mora | Status |
|---|---|---|---|
| **C01** | Segregação CFOP/CST monofásico (Imposto Seletivo) | Fase 0b — extrator NF-e item-a-item | 🔵 Pendente |
| **C03** | Cálculo Lucro Presumido comparativo intra-janela | Fase 0b — `cenarios_optout.py` | 🟡 Parcial |
| **C04** | DIFAL agregado por mês | Fase 1 — `motor_difal_consolidado.py` | 🔵 Marcado INDISPONIVEL_AGREGADO (D1) |
| **C04** | ISS cap automático (LC 123 Art. 18 §5°-F) | `calcular_partilha_iss_cap` em `tabelas_simples.py` | ✅ Disponível, falta integrar engine |
| **C05** | Sugestão de pró-labore reverso pra estabilizar Anexo III | Fase 0b — calculadora reversa Fator R | 🔵 Pendente |
| **C06** | Engine MEI com teto diferenciado por modalidade | `regimes/mei.py` + WS6 etapa 3 | ✅ Disponível |
| **C07** | Engine ORG_RELIGIOSA atividade-fim/meio | `regimes/imune.py` — **WS6 etapa 4** | 🔴 Pendente |
| **C08** | Engine COOPERATIVA com segregação ato cooperativo | `regimes/cooperativa.py` — WS6 etapa 5 | 🔵 Pendente |
| **C09** | Consolidação RBT12 raiz×filial via API CNPJ | Fase 1 — integração SIEG/eCAC | 🔵 Pendente — operador declara |
| **C10** | Engine Lucro Real com LALUR + adições/exclusões | WS6.b — Lucro Real refinado | 🟡 Em curso |

**Decisão arquitetural:** todas 10 simulações são **construíveis no schema atual** (`HistoricoSeisMeses`). C07, C08, C10 documentam comportamento esperado para futuras fases — motor deve devolver `REVISAR_MANUALMENTE` + confiança BAIXA + amparo legal explícito até que engine especializado entre.

---

## 🔬 Detalhamento — Veja `~/.claude/plans/blueprint-simulacoes-complexas-luiz-moreira.md`

O reporte completo do Luiz Moreira (passo a passo dos cálculos, justificativas, vetores RFB detalhados) está preservado no arquivo de plano externo (~3000 palavras). Este documento (`simulacoes_complexas_fase0a.md`) é a vista resumida pra navegar e bater na planilha.

---

## 🎯 Próximas Ações

1. **Dono valida 3-5 simulações em Excel** (recomendo C02, C04, C05 — mais críticas pra carteira de 200 CNPJs).
2. **Sentinela transforma em testes regressivos** — `tests/casos_clinicos/test_simulacoes_complexas.py` (1 fixture por simulação + 1 asserção por linha da Tabela de Validação).
3. **Caso-Clínico cria 4 fixtures** das simulações que não dependem de fases posteriores (C02, C05, C06, C09).
4. **Outras 6 simulações** ficam como documentação até suas fases entrarem (C01, C03, C04, C07, C08, C10).

---

## 🛡️ Invariantes de TODAS as 10 simulações

1. **Determinismo:** mesmo input → mesmo `hash_reprodutibilidade`. Se 2 execuções produzirem hashes diferentes → vazamento de timestamp/dict order/Decimal.
2. **MAX_01:** todo cálculo tem 4 elementos (Base → Deduções → Alíquota → Valor). Trilha unificada audita isso.
3. **MAX_02:** todo `amparo_legal` em alerta cita lei real verificável em planalto.gov.br.
4. **MAX_07:** sem inventar SC COSIT/Acórdão CARF/súmula. Escrivão valida toda menção.
5. **Schema V1.0 frozen:** se simulação precisa de campo novo (`faturamento_ato_cooperativo`, `cnpj_raiz`, `iss_cap_aplicado`) → abrir `ERR-XXX` em LOG_ERROS.md, **não estender schema sem revisão Chefe + Luiz + Escrivão**.
