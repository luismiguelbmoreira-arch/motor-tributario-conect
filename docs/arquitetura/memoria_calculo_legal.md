# 🧮 MEMÓRIA DE CÁLCULO LEGAL — reFIN (Motor Tributário)

**Versão:** 1.0.0 (Transicional 2026-2033)  
**Status:** DETERMINÍSTICO / CONFIANÇA ZERO  
**Referência:** LC 123/2006, LC 214/2025, EC 132/2023

---

## 💎 1. REGRAS DE OURO DE PROCESSAMENTO (PRECISÃO)

| Regra | Especificação | Motivação Legal |
| :--- | :--- | :--- |
| **Tipo de Dado** | `decimal.Decimal` (Precisão 12+ casas) | Obstar anomalias de vírgula flutuante (float) |
| **Arredondamento** | Truncamento e Arredondamento Per-Tributo | Art. 18, § 1º LC 123/2006 (Divisão de alíquotas) |
| **Fator R** | `(Folha_12m / RBT12) >= 0.28` | Diferenciação Anexo III vs V |
| **Split Payment** | Retenção imediata na liquidação financeira | EC 132/2023 + LC 214/2025 |

---

## 📈 2. FÓRMULAS VITAIS

### A. RBT12 (Receita Bruta Acumulada)

$$RBT12 = \sum_{n=1}^{12} Faturamento[mês_{atual}-n]$$

* **Nota:** Deve considerar devoluções e exclusões conforme Art. 3º, § 1º da LC 123.

### B. Alíquota Efetiva (Simples Nacional)

$$AE = \frac{(RBT12 \times AN) - PD}{RBT12}$$

* **AN:** Alíquota Nominal da Faixa.
* **PD:** Parcela a Deduzir da Faixa.
* **Validação:** Se RBT12 > R$ 3.600.000,00, o ICMS/ISS é calculado por fora (Sublimite).

### C. Split Payment (Fração IVA Dual)

| Período | Alíquota Split (Calculada sobre DAS) | Fonte Legal |
| :--- | :--- | :--- |
| **2026 (Teste)** | 1,0% (0,9% CBS + 0,1% IBS) | EC 132/2023 |
| **2027+ (Pleno)** | 8,9% (8,8% CBS + 0,1% IBS) | LC 214/2025 |

---

## ❌ 3. VETOS RESTRITIVOS (ZERO TRUST)

1. **PROIBIDO** faturamento mensal negativo (lançar como estorno/crédito subsequente).
2. **PROIBIDO** uso de constantes fixas para alíquotas sem validação de Faixa RBT12.
3. **PROIBIDO** persistência de dados de filiais em memória após a geração do Payload JSON.

---
*Documento gerado sob supervisão de Luiz Moreira (FAACAS '70)*
