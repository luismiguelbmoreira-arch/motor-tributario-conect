# Validação Falsificável — Fase 0a (Diagnóstico Consolidado)

**Data:** 29/04/2026 | **Branch:** `fase-0a-historico-seis-meses`
**Origem:** Luiz Moreira crava cenários (28/04/2026); Caso-Clínico consolida com correções.
**Suite atual:** 1360 testes verdes.

## 🎯 Objetivo

Validar o motor de diagnóstico consolidado (`gerar_diagnostico_consolidado`) contra **planilha numérica replicável em Excel**. A regra é simples e foi cravada na PARTE F.5 do plano-mestre:

> Compara o motor vs a **planilha**, não vs a **intuição**.
> CBS/IBS é nova — nem o contador experiente tem intuição calibrada ainda.

Cada cenário tem inputs claros, **cálculo passo a passo replicável** e resultado esperado. Se motor diverge da planilha em qualquer campo numérico → investigar antes de aceitar diagnóstico em produção.

## 📋 Convenção fiscal

- **Fórmula da alíquota efetiva (LC 123/2006 Art. 18 §1º):**
  `((RBT12 × Alíq_Nominal) − Parcela_Deduzir) ÷ RBT12`
- **DAS mensal:** `Faturamento_Mês × Alíq_Efetiva`
- **Decimal sempre, ROUND_HALF_UP, alíquota com 6 casas, DAS com 2 casas.**
- Tabelas consultadas: **Resolução CGSN 140/2018** (Anexos I-V) — valores em `PY/core/tabelas_simples.py`.

---

## 📊 Tabela Síntese — 15 Cenários (+ 1 extra)

| # | Arquétipo | Mês | Faturamento | RBT12 | Anexo | Alíq Efet | DAS | Recomendação | Confiança |
|---|---|---|---|---|---|---|---|---|---|
| **1A** | Boutique | Nov/2025 | 75.000,00 | 1.040.000,00 | I (F4) | 0,085365 | **6.402,38** | MANTER_SIMPLES | ALTA |
| **1B** | Boutique | Dez/2025 | 375.000,00 | 1.115.000,00 | I (F4) | 0,086821 | **32.557,84** | MANTER_SIMPLES | ALTA |
| **1C** | Boutique | Jan/2026 | 60.000,00 | 1.330.000,00 | I (F4) | 0,090083 | **5.405,00** | MANTER_SIMPLES | ALTA |
| **2A** | Vértice | Mar/2026 | 240.000,00 | 2.850.000,00 | III (F5) FR=0,2850 | 0,165915 | **39.819,60** | MANTER_SIMPLES | ALTA |
| **2B** | Vértice | Mai/2026 | 235.000,00 | 2.870.000,00 | V (F5) FR=0,2787 | 0,208362 | **48.965,07** | REVISAR_OPT_OUT | MEDIA |
| **2C** | Vértice | Hipotético FR=0,2800 | 240.000,00 | 2.860.000,00 | III (F5) — desempate | 0,166070 | **39.856,80** | MANTER_SIMPLES | ALTA |
| **3A** | Padaria | Fev/2026 | 165.000,00 | 1.980.000,00 | I (F5) | 0,098909 | **16.320,00** | MANTER_SIMPLES | ALTA |
| **3B** | Padaria | Dez/2025 | 280.000,00 | 2.020.000,00 | I (F5) | 0,099782 | **27.939,01** | MANTER_SIMPLES | ALTA |
| **3C** | Padaria | Hipotético mix 80/20 | 165.000,00 | 1.980.000,00 | I (F5) | 0,098909 | **16.320,00** = 3A | MANTER_SIMPLES | ALTA |
| **4A** | Aço Forte | Mar/2026 | 335.000,00 | 4.020.000,00 | V (F6) FR=0,2611 | 0,170672 | **57.175,12** | REVISAR_OPT_OUT | ALTA |
| **4B** | Aço Forte | Hipotético FR=0,30 | 335.000,00 | 4.020.000,00 | III (F6) — Fator R cruza | 0,168806 | **56.549,93** | MANTER_SIMPLES | ALTA |
| **4C** | Aço Forte | Estresse RBT12=4,9M | 410.000,00 | 4.900.000,00 | — | n/a | n/a | EXCLUSÃO_PROGRAMADA_2027 | ALTA |
| **5A** | Trovão | Mês 4 | 350.000,00 | 4.180.000,00 | I (F6) | 0,099569 | **34.849,28** | MANTER_SIMPLES | ALTA |
| **5B** | Trovão | Mês 5 ⚠️ | 380.000,00 | 4.350.000,00 | I (F6) | 0,103103 | **39.179,31** | REVISAR_OPT_OUT | ALTA |
| **5C** | Trovão | Hipotético RBT12=5,5M (excesso 14,58%) | 450.000,00 | 5.500.000,00 | — | n/a | n/a | EXCLUSÃO_PROGRAMADA_2027 | ALTA |
| **5D** | Trovão | Hipotético RBT12=6,0M (excesso 25%) | 500.000,00 | 6.000.000,00 | — | n/a | n/a | EXCLUSÃO_RETROATIVA | ALTA |

> **F = Faixa do Anexo (Resolução CGSN 140/2018).** F4 = R$ 720k–1,8M; F5 = 1,8M–3,6M; F6 = 3,6M–4,8M.

---

## 🔢 Detalhamento (passo a passo — replicável em Excel)

### Cenário 1A — Boutique fora do pico (Nov/2025)

| Input | Valor |
|---|---|
| RBT12 | 1.040.000,00 |
| Faturamento Mês | 75.000,00 |
| Anexo | I (CNAE 4781400) |
| Comprador | 100% B2C |

```
Passo 1: RBT12 (1,04M) → Faixa 4 do Anexo I (720k a 1,8M)
Passo 2: Alíq nominal 10,70% | Parcela deduzir R$ 22.500,00
Passo 3: ((1.040.000 × 0,1070) − 22.500) ÷ 1.040.000
       = (111.280 − 22.500) ÷ 1.040.000
       = 88.780 ÷ 1.040.000
       = 0,085365 (8,5365%)
Passo 4: DAS = 75.000 × 0,085365 = R$ 6.402,38
```

**Esperado motor:** Alíq=0,085365 | DAS=6.402,38 | recomendacao=MANTER_SIMPLES | confianca=ALTA.

---

### Cenário 1B — Boutique pico Dezembro (5× média)

```
RBT12 1.115.000 → Faixa 4 Anexo I
Alíq 10,70% / Parcela 22.500
((1.115.000 × 0,1070) − 22.500) ÷ 1.115.000
= (119.305 − 22.500) ÷ 1.115.000
= 96.805 ÷ 1.115.000
= 0,086821
DAS = 375.000 × 0,086821 = R$ 32.557,84
```

**Esperado:** Alíq=0,086821 | DAS=32.557,84 | MANTER_SIMPLES | ALTA + alerta `SAZONALIDADE_PICO_DETECTADA`.

---

### Cenário 1C — Boutique pós-pico Jan/2026

```
RBT12 1.330.000 → Faixa 4 Anexo I (ainda < 1,8M)
((1.330.000 × 0,1070) − 22.500) ÷ 1.330.000
= (142.310 − 22.500) ÷ 1.330.000
= 119.810 ÷ 1.330.000
= 0,090083
DAS = 60.000 × 0,090083 = R$ 5.405,00
```

**Esperado:** Alíq=0,090083 | DAS=5.405,00 | MANTER_SIMPLES | ALTA. RBT12 ainda 26% abaixo do gate 90% (1,62M).

---

### Cenário 2A — Vértice Fator R 0,2850 (DENTRO do Anexo III)

> **Regra-chave:** LC 123/2006 §5-J — Fator R ≥ 0,28 → Anexo III; senão Anexo V.

```
RBT12 2.850.000 → Faixa 5 Anexo III (1,8M a 3,6M)
Alíq nominal 21,00% | Parcela 125.640
((2.850.000 × 0,2100) − 125.640) ÷ 2.850.000
= (598.500 − 125.640) ÷ 2.850.000
= 472.860 ÷ 2.850.000
= 0,165915
DAS = 240.000 × 0,165915 = R$ 39.819,60
```

---

### Cenário 2B — Vértice Fator R 0,2787 (FORA → Anexo V)

```
RBT12 2.870.000 → Faixa 5 Anexo V
Alíq nominal 23,00% | Parcela 62.100 (CGSN 140/2018 Anexo V)
((2.870.000 × 0,2300) − 62.100) ÷ 2.870.000
= (660.100 − 62.100) ÷ 2.870.000
= 598.000 ÷ 2.870.000
= 0,208362
DAS = 235.000 × 0,208362 = R$ 48.965,07
```

**Δ vs 2A (mesmo RBT12 mas Anexo III):** ~R$ 9.146/mês a mais por estar em Anexo V — efeito de 1 freelancer PJ a menos no mês. Aumentar pró-labore em ~R$ 1.500/mês fecha conta para Fator R.

---

### Cenário 2C — Vértice Fator R 0,2800 EXATO (desempate)

> **Teste regressivo crítico:** se motor usa `>` em vez de `>=` na fronteira 0,28 → bug.

```
FR = 0,2800 → "igual ou superior" → Anexo III
Mesma fórmula do 2A com RBT12 ligeiramente maior:
((2.860.000 × 0,2100) − 125.640) ÷ 2.860.000 = 0,166070
DAS = 240.000 × 0,166070 = R$ 39.856,80
```

---

### Cenário 3A — Padaria Misto 50/50 normal

```
RBT12 1.980.000 → Faixa 5 Anexo I (1,8M-3,6M)
Alíq nominal 14,30% | Parcela 87.300
((1.980.000 × 0,1430) − 87.300) ÷ 1.980.000
= (283.140 − 87.300) ÷ 1.980.000
= 195.840 ÷ 1.980.000
= 0,098909
DAS = 165.000 × 0,098909 = R$ 16.320,00
```

---

### Cenário 3B — Padaria pico Dezembro

```
RBT12 2.020.000 → Faixa 5 Anexo I
((2.020.000 × 0,1430) − 87.300) ÷ 2.020.000 = 0,099782
DAS = 280.000 × 0,099782 = R$ 27.939,01
```

---

### Cenário 3C — Padaria hipotético mix 80/20

> **Teste regressivo de adapter:** Simples NÃO diferencia DAS por mix de comprador. Se motor calcular DAS diferente entre 3A (50/50) e 3C (80/20) com mesmo RBT12/faturamento → bug.

```
DAS = idêntico ao Cenário 3A = R$ 16.320,00
Diferença: só no crédito CBS/IBS REPASSADO ao comprador (B2B credita, B2C não — MAX_06).
```

---

### Cenário 4A — Aço Forte (Anexo V Faixa 6)

```
RBT12 4.020.000 → Faixa 6 Anexo V (3,6M-4,8M)
Alíq nominal 30,50% | Parcela 540.000
((4.020.000 × 0,3050) − 540.000) ÷ 4.020.000
= (1.226.100 − 540.000) ÷ 4.020.000
= 686.100 ÷ 4.020.000
= 0,170672
DAS = 335.000 × 0,170672 = R$ 57.175,12
```

---

### Cenário 4B — Aço Forte hipotético Fator R = 0,30 (cruza para Anexo III)

```
FR 0,30 ≥ 0,28 → Anexo III
RBT12 4.020.000 → Faixa 6 Anexo III
Alíq nominal 33,00% | Parcela 648.000
((4.020.000 × 0,3300) − 648.000) ÷ 4.020.000 = 0,168806
DAS = 335.000 × 0,168806 = R$ 56.549,93
```

**Δ vs 4A:** R$ 625,19/mês de economia. **Lição:** Fator R perde poder na Faixa 6 (Anexo III e V convergem).

---

### Cenário 4C — Aço Forte estresse RBT12 = 4,9M

> **Regra-chave:** LC 123/2006 Art. 3º §9 — RBT12 > 4,8M.
> Excesso = (4,9M − 4,8M) ÷ 4,8M = 2,08% → ≤ 20% → exclusão **ano seguinte** (Art. 3º §9-A).

```
RBT12 4.900.000 → Sem alíquota Simples calculável.
EXCLUSÃO PROGRAMADA pra 2027 (não retroativa).
```

**Esperado motor:** sem DAS calculável; recomendação=EXCLUSAO_PROGRAMADA_2027 + alerta `RBT12_ACIMA_TETO_4_8M`.

---

### Cenário 5A — Trovão Mês 4 (abaixo do gate 4,32M)

```
RBT12 4.180.000 → Faixa 6 Anexo I
Alíq nominal 19,00% | Parcela 378.000
((4.180.000 × 0,1900) − 378.000) ÷ 4.180.000
= (794.200 − 378.000) ÷ 4.180.000
= 416.200 ÷ 4.180.000
= 0,099569
DAS = 350.000 × 0,099569 = R$ 34.849,28
```

**Esperado:** sem alerta `RBT12_90PCT_TETO` (4,18M < 4,32M). MANTER_SIMPLES + ALTA.

---

### Cenário 5B — Trovão Mês 5 ⚠️ CRUZA o gate

```
RBT12 4.350.000 ≥ 4.320.000 (90% × 4.8M) → ALERTA DISPARA
((4.350.000 × 0,1900) − 378.000) ÷ 4.350.000 = 0,103103
DAS = 380.000 × 0,103103 = R$ 39.179,31
```

**Esperado:** alerta `RBT12_90PCT_TETO` na lista de alertas_transicao. Recomendação=REVISAR_OPT_OUT.

---

### Cenário 5C — Trovão hipotético RBT12 = 5,5M (excesso 14,58%)

> **Regra-chave:** Excesso = (5,5M − 4,8M) ÷ 4,8M = 14,58% → ≤ 20% → **exclusão ano seguinte**, NÃO retroativa.

```
EXCLUSÃO PROGRAMADA 2027 (Art. 3º §9-A — excesso ≤ 20%)
```

---

### Cenário 5D — Trovão hipotético RBT12 = 6,0M (excesso 25%) ⚠️ NOVO

> **Regra-chave:** Excesso = (6,0M − 4,8M) ÷ 4,8M = 25,00% → > 20% → **exclusão RETROATIVA** ao mês do excesso (Art. 3º §9).

```
EXCLUSÃO RETROATIVA — empresa não estava no Simples desde o mês do excesso.
Motor deve devolver: recomendacao=EXCLUSAO_RETROATIVA + alerta CRÍTICO.
```

---

## ✅ Tabela de Validação (preencher em Excel)

| # | Campo principal | Esperado planilha | Produzido motor | Diferença | OK/Δ |
|---|---|---|---|---|---|
| 1A | DAS | 6.402,38 | _____ | _____ | _____ |
| 1B | DAS | 32.557,84 | _____ | _____ | _____ |
| 1C | DAS | 5.405,00 | _____ | _____ | _____ |
| 2A | DAS | 39.819,60 | _____ | _____ | _____ |
| 2B | DAS | 48.965,07 | _____ | _____ | _____ |
| 2C | Anexo aplicado | III (FR=0,28 exato) | _____ | _____ | _____ |
| 3A | DAS | 16.320,00 | _____ | _____ | _____ |
| 3B | DAS | 27.939,01 | _____ | _____ | _____ |
| 3C | DAS = 3A | 16.320,00 | _____ | _____ | _____ |
| 4A | DAS | 57.175,12 | _____ | _____ | _____ |
| 4B | DAS | 56.549,93 | _____ | _____ | _____ |
| 4C | Recomendação | EXCLUSAO_PROGRAMADA_2027 | _____ | _____ | _____ |
| 5A | Alerta `RBT12_90PCT_TETO` | NÃO dispara | _____ | _____ | _____ |
| 5B | Alerta `RBT12_90PCT_TETO` | DISPARA | _____ | _____ | _____ |
| 5C | Recomendação | EXCLUSAO_PROGRAMADA_2027 (excesso 14,58%) | _____ | _____ | _____ |
| 5D | Recomendação | EXCLUSAO_RETROATIVA (excesso 25%) | _____ | _____ | _____ |

---

## ⚠️ 8 Riscos Detectados pelo Luiz Moreira (28/04/2026)

1. **Erros aritméticos na 1ª passada**: o próprio Luiz divergiu na tabela síntese vs detalhe. Já evidência empírica de que **planilha falsificável > intuição**. Tabela síntese acima já está alinhada com detalhamento.

2. **PGDAS-D vs CGSN — janela RBT12**: PGDAS-D real usa RBT12 dos 12 meses **anteriores** (não inclui o próprio mês). Resolução CGSN 140/2018 Art. 21, §1º. Se motor estiver incluindo o mês corrente → divergência ~1-2%.

3. **Cenário 5C corrigido**: 5,5M = excesso 14,58% (≤ 20%) → exclusão programada. Pra cravar exclusão retroativa, **Cenário 5D** adicionado com RBT12=6,0M (excesso 25%).

4. **Faixa 6 do Anexo V**: minha leitura saltou direto pra faixa 6 sem confirmar limites. Confirmar em `core/tabelas_simples.py` que faixa 6 V = (3,6M-4,8M, 30,5%, 540.000). Sentinela validar.

5. **CBS/IBS em 2025**: cenários 1A, 1B, 3B (datas 2025) **não geram crédito CBS/IBS** (LC 214/2025 vigência 01/01/2026). Motor não pode aplicar `_fracao_iva_no_das` a competência 2025 — se aplicar, bug crítico (MAX_06 + R8 consistência temporal).

6. **Cenário 2C (FR = 0,2800 exato)**: teste de fronteira mais sutil. Se motor usa `>` em vez de `>=` na comparação `fator_r >= 0,28` → classifica errado como Anexo V. Bug R$ 9k/mês a mais. Vale teste regressivo dedicado.

7. **Confiança ALTA vs MEDIA**: minha decisão pode ser conservadora demais quando há alerta crítico não-bloqueante (FR zona limite, RBT12 90% teto). Motor pode ter régua diferente.

8. **Cenário 3C (mix 80/20 vs 50/50)**: crítico pro adapter. DAS DEVE ser idêntico entre 3A e 3C com mesmo RBT12/faturamento. Se diferente → bug.

---

## 🎯 Próximos Passos

1. **Caso-Clínico** roda os 16 cenários (15 + 5D) no motor real e preenche a tabela acima. Output em commit separado.
2. **Luiz Moreira** investiga toda divergência > 0,01% como bug fiscal.
3. Validação humana do dono (Luis Miguel): replicar 3-5 cenários em Excel, conferir os totais.
4. Após 100% verde, **gate de fechamento da Fase 0a** está satisfeito.

---

## 📐 Fórmulas-Resumo (replicar em Excel)

```excel
=ARREDONDAR.PARA.CIMA(((RBT12 * Aliq_Nominal) - Parcela_Deduzir) / RBT12, 6)   # Alíq efetiva (6 casas)
=ARREDONDAR.PARA.CIMA(Faturamento * Aliq_Efetiva, 2)                            # DAS (2 casas)
```

**Regra ROUND_HALF_UP** (mesma do motor): `ARREDONDAR(x; n)` em PT-BR padrão Excel ≈ ROUND_HALF_UP quando `x` é positivo.

**Constantes que vão a Excel via VLOOKUP** (copiar de `PY/core/tabelas_simples.py`):

| Anexo | Faixa | RBT12 até | Alíq Nominal | Parcela Deduzir |
|---|---|---|---|---|
| I | 1 | 180.000 | 4,00% | 0 |
| I | 2 | 360.000 | 7,30% | 5.940 |
| I | 3 | 720.000 | 9,50% | 13.860 |
| I | 4 | 1.800.000 | 10,70% | 22.500 |
| I | 5 | 3.600.000 | 14,30% | 87.300 |
| I | 6 | 4.800.000 | 19,00% | 378.000 |
| III | 1 | 180.000 | 6,00% | 0 |
| III | 2 | 360.000 | 11,20% | 9.360 |
| III | 3 | 720.000 | 13,50% | 17.640 |
| III | 4 | 1.800.000 | 16,00% | 35.640 |
| III | 5 | 3.600.000 | 21,00% | 125.640 |
| III | 6 | 4.800.000 | 33,00% | 648.000 |
| V | 5 | 3.600.000 | 23,00% | 62.100 |
| V | 6 | 4.800.000 | 30,50% | 540.000 |
