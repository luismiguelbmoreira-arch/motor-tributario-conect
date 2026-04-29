<!--
VALIDADO_POR: scripts/auditoria_revisao_critica.py
EXECUTADO_EM: 2026-04-29
SUITE_VERDE: 1360 testes
RESULTADO: 12/15 cenarios numericos da versao anterior estavam errados (80%); valores abaixo extraidos do motor real
ERRO_MATERIAL_CORRIGIDO: C02_M6 (alq 0.190329 -> 0.190350; DAS R$ 199.846,01 -> R$ 199.867,50; delta R$ 21,49)
-->

# 10 Simulações COMPLEXAS — Stress-Test Fase 0a

**Data:** 29/04/2026 | **Autor:** Luiz Moreira (cravamento intenção+lei) + Caso-Clínico (consolidação) + script de auditoria (números reais)
**Branch:** `fase-0a-historico-seis-meses` | **Suite atual:** 1360 testes verdes
**Status:** valores **EXTRAÍDOS DO MOTOR** via `scripts/auditoria_revisao_critica.py`

## ⚠️ Histórico de correção

A versão anterior deste documento (cravada em 28/04/2026) tinha **12 de 15 cenários numéricos com valores errados** (80% de erro), descobertos em auditoria automatizada em 29/04/2026.

**Erro material:** **C02_M6** — alíquota cravada `0,190329` divergia da real `0,190350`. DAS doc R$ 199.846,01 vs motor R$ 199.867,50 (**Δ R$ 21,49/mês**). Em 200 CNPJs × 12 meses, esse padrão de erro gera ~R$ 51.576/ano de descontrole.

**Demais 11 erros:** arredondamento da última casa decimal (≤ R$ 0,30/cenário), causados por sub-agente texto fazendo `quantize` manual com precisão diferente do motor.

**Regra cravada pelo dono em 29/04/2026:** *"você roda toda mudança"* → **MAX_08 (Regra da Fonte Executada)** no CLAUDE.md.

## 🎯 Diferença vs validação falsificável simples

| Documento | Cenários | Complexidade | Objetivo |
|---|---|---|---|
| `validacao_falsificavel_fase0a.md` | 13 simples + 3 estouros | 1 dimensão por cenário | Verificar fórmula básica |
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

## 📋 Meses-chave numéricos — VALORES REAIS DO MOTOR

> Todos os valores abaixo foram extraídos rodando a fórmula do motor (`tabelas_simples.py::TABELAS_ANEXOS` + `((RBT12 × Alíq_Nominal) − Parcela_Deduzir) ÷ RBT12`).

| Cenário | Mês | Anexo / Faixa | RBT12 | Faturamento | Alíq Efetiva (motor) | DAS (motor) |
|---|---|---|---|---|---|---|
| **C01_M1** | Out/2025 | I / 4 | R$ 1.420.000 | R$ 138.000 | 0,091155 | **R$ 12.579,39** |
| **C01_M3** | Dez/2025 | I / 4 | R$ 1.470.000 | R$ 175.000 | 0,091694 | **R$ 16.046,45** |
| **C02_M3** | Nov/2025 (FR=0,2841 cruza pra III) | III / 5 | R$ 3.150.000 | R$ 540.000 | 0,170114 | **R$ 91.861,56** |
| **C02_M6** ⚠️ erro material corrigido | Fev/2026 (RBT12=98,1% teto) | V / 6 | R$ 4.710.000 | R$ 1.050.000 | 0,190350 | **R$ 199.867,50** |
| **C03_M1** | Out/2025 (FR=0,15 → Anexo V) | V / 4 | R$ 1.650.000 | R$ 138.000 | 0,194636 | **R$ 26.859,77** |
| **C04_M6** | Mar/2026 (outlier — entrega obra) | IV / 5 | R$ 2.950.000 | R$ 1.450.000 | 0,157702 | **R$ 228.667,90** |
| **C05_M2** | Out/2025 (FR=0,2728) | V / 4 | R$ 940.000 | R$ 82.000 | 0,186809 | **R$ 15.318,34** |
| **C05_M3** | Nov/2025 (FR=0,2813 cruza pra III) | III / 4 | R$ 960.000 | R$ 85.000 | 0,122875 | **R$ 10.444,38** |
| **C05_M4** | Dez/2025 (FR=0,2995 alta — 13º) | III / 4 | R$ 985.000 | R$ 95.000 | 0,123817 | **R$ 11.762,62** |
| **C05_M5** | Jan/2026 (FR=0,2716 volta pra V) | V / 4 | R$ 1.020.000 | R$ 100.000 | 0,188235 | **R$ 18.823,50** |
| **C07_M1** | Out/2025 (Bazar Anexo I F3) | I / 3 | R$ 480.000 | R$ 40.000 | 0,066125 | **R$ 2.645,00** |
| **C08_M1** | Out/2025 (cooperativa SEGREGADA) | III / 3 | R$ 660.000 | R$ 55.000 | 0,108273 | **R$ 5.955,02** |
| **C08_M1_NS** | Out/2025 (sem segregação — bug) | III / 4 | R$ 1.900.000 | R$ 195.000 | 0,141242 | **R$ 27.542,19** |
| **C09_M3** | Dez/2025 (filial em F5) | I / 5 | R$ 3.580.000 | R$ 280.000 | 0,118615 | **R$ 33.212,20** |
| **C09_M4** | Jan/2026 (cruza pra F6) | I / 6 | R$ 3.640.000 | R$ 240.000 | 0,086154 | **R$ 20.676,96** |

> **C10 (Lucro Real)** não tem alíquota Simples calculável — motor delega pra `LucroRealEngine` ou retorna MIGRAR_REAL com aviso.

---

## 📋 Tabela de Validação Excel-Friendly (10 linhas críticas)

| Sim | Mês | Campo a verificar | Valor esperado | Tolerância | Lei amparo |
|---|---|---|---|---|---|
| **C01** | 2025-12 | DAS M3 (Anexo I faixa 4) | **R$ 16.046,45** | ±R$ 0,01 | LC 123 Art. 18 §1º |
| **C02** | 2025-11 | Anexo aplicado M3 (FR=0,2841) | III | exato | LC 123 Art. 18 §24 |
| **C02** | 2026-02 | Alerta `RBT12_90PCT_TETO` | DISPARA (98,125%) | exato | Rail R7 |
| **C02** | 2026-02 | DAS M6 ⚠️ | **R$ 199.867,50** | ±R$ 0,01 | LC 123 Art. 18 §1º |
| **C03** | 2025-10 | DAS M1 Anexo V F4 | **R$ 26.859,77** | ±R$ 0,01 | Lei 9.249/95 Art. 15 §1º III "a" |
| **C04** | 2026-03 | DAS M6 (outlier) | **R$ 228.667,90** | ±R$ 0,01 | LC 123 Art. 18 §5°-F |
| **C04** | 2025-11 | `difal_status` | INDISPONIVEL_AGREGADO | exato | EC 87/2015 / ADI 5464 |
| **C05** | qualquer | Recomendação consolidada | REVISAR_MANUALMENTE | exato | Bug-prevention OLS |
| **C05** | 2025-11→2026-01 | Alertas FATOR_R_ATRAVESSOU_028 | ≥2 | mín | LC 123 Art. 18 §24 |
| **C06** | 2026-03 | RBT12 vs teto MEI Caminhoneiro | 98,57% de R$ 251.600 | exato | LC 188/2021 |
| **C07** | qualquer | Recomendação | REVISAR_MANUALMENTE + BAIXA | exato | STF RE 325.822 |
| **C08** | qualquer | DAS sem segregação vs com | R$ 27.542,19 vs R$ 5.955,02 (~4,6×) | ±5% | Lei 5.764/71 Art. 79 |
| **C09** | 2026-01 | Faixa virada 5→6 (RBT12=3,64M raiz) | F6 alíq 0,086154 | ±0,000001 | LC 123 Art. 13 §1º |
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

---

## 🛡️ Como validar este documento

```bash
cd PY/
python scripts/auditoria_revisao_critica.py
```

Se output mostrar qualquer "DIVERGE" → este documento está desatualizado em relação ao motor. Reexecutar o script e atualizar.

**MAX_08 (Regra da Fonte Executada):** nenhum valor numérico Decimal entra neste documento sem ter sido executado contra o motor real.
