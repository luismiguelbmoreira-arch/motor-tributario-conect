# ATA DE CONSENSO — ERR-046

**Protocolo:** Jogada Fiscal (Skill `jogada-fiscal`)
**Data:** 23/04/2026
**Presentes:** chefe-deus, o-viciado, luiz-moreira, Orquestrador (Claude)
**Duração debate:** Fase 1 única (convergiu sem 2º round)

---

## 1. Pauta

Corrigir defeito em `cenario_opt_out()` (linhas 724-780 pré-fix, `PY/core/motor_tributario.py`) que subtraía IBS/CBS em bases matemáticas incompatíveis (R$ do DAS mensal vs R$ da operação específica). Violação de MAX_FISCAL_01 (consistência Base → Deduções → Alíquota → Valor) + MAX_FISCAL_02 (amparo legal genérico "aguardar regulamentação").

## 2. Posições originais

### POSIÇÃO_CHEFE (chefe-deus)
- Escopo cirúrgico em `cenario_opt_out`; ripple automático em `disparidade_anual` e `_gerar_recomendacao_opt_out`.
- Mesma sprint que V-13/V-14 (arquivos diferentes, zero colisão).
- Bump `MOTOR_VERSAO` 1.1.0 → 1.2.0 (MINOR SemVer).
- 4 testes ancorados (TDD reverso).
- Reescrever trilha `OPT_OUT_CALCULO`.

### POSIÇÃO_VICIADO (o-viciado)
- Fórmula: `AE × (Decimal("1") - fracao_iva_percentual)` — espelha padrão `ae_sem_icms` linha 460.
- Reutilizar `_fracao_iva_no_das(anexo, faixa, ano)` — zero função nova, DRY.
- 4 testes (TESTE 4 = linearidade canário permanente).
- Checklist de 10 passos (TDD reverso → fix → trilha → bump → suite → LOG → commit).

### POSIÇÃO_LUIZ (luiz-moreira)
- **VETO sobre a proposta do LOG:** falta simetria do `fator_reducao`.
  - Sem simetria, `REDUCAO_60` (medicamentos, Art. 262) expurgaria 100% do DAS mas pagaria 40% por fora → **viés direcional pró-opt-out**.
  - Correção: `custo_das_sem_iva = valor_operacao × AE × (1 − fração_IVA_% × fator_redução)`
- Severidade elevada **🟡 → 🔴 Crítico / P0** (3 motivos: viés direcional, MAX_01 violado, MAX_02 violado).
- Amparo legal expandido: LC 214/2025 Arts. 41-44 + 47 §II + 258-264 + 344 + 353 + 356-360 + 348 III 'c'.
- Impacto numérico estimado: R$ 162/op (6,7% do custo_total) em cenário RBT12=600k × op=20k × 2029.
- 2 testes obrigatórios extras (simetria REDUCAO_60).

## 3. Divergência resolvida

**LOG original + Chefe + Viciado** → fórmula sem `fator_reducao`.
**Luiz** → veto com prova numérica → incorporado.

**Protocolo aplicado:** consenso não é votação; 1 veto com prova retorna ao debate OU incorpora. Prova do Luiz (viés direcional em REDUCAO_60) é matematicamente superior → **fórmula final incorpora simetria**.

## 4. Fórmula final aprovada

```python
fracao_iva_pct = self._fracao_iva_no_das(anexo, faixa, ano)   # adimensional ∈ [0, 1]
fator_reducao  = self._fator_reducao_cbs_ibs()                # 1.00 / 0.70 / 0.40 / 0.00
ae_efetiva     = self.aliquota_efetiva

ae_sem_iva = (
    ae_efetiva * (Decimal("1") - fracao_iva_pct * fator_reducao)
).quantize(Decimal("0.000001"), ROUND_HALF_UP)

custo_das_sem_iva = (
    self.operacao.valor_operacao * ae_sem_iva
).quantize(Decimal("0.01"), ROUND_HALF_UP)
```

## 5. Descoberta de Fase 2

Os testes TDD reverso revelaram: `fracao_ibs` e `fracao_cbs` (linhas 591/596) pegam valores de `DISTRIBUICAO_DAS[anexo][faixa]["IBS"|"CBS"]` — colunas **zeradas em todas as faixas do motor**. O sistema real usa `_fracao_iva_no_das` (composição PIS+COFINS → CBS e ICMS+ISS×fase_in → IBS). Resultado: **o motor não expurgava NADA do DAS no Opt-Out** — dupla tributação em produção (não viés de 6,7%, defeito de 100% do expurgo).

Luiz subestimou a gravidade porque assumiu valores reais em `fracao_ibs+cbs`; esses valores eram zero. A fórmula corrigida agora expurga de verdade via `_fracao_iva_no_das`.

## 6. Amparo legal expandido (6 artigos)

| Artigo | Aplicação |
|---|---|
| LC 214/2025 Arts. 41-44 | Dispositivo de opt-out (regime opcional) |
| LC 214/2025 Art. 47 §II | Creditamento proporcional IBS/CBS do DAS |
| LC 214/2025 Arts. 258-264 | Fator de redução CBS/IBS — **aplicação isonômica (simetria)** |
| LC 214/2025 Arts. 344 e 353 | CBS substitui PIS/COFINS em 2027 |
| LC 214/2025 Arts. 356-360 | Phase-in IBS 2029-2032 + redução ICMS/ISS simétrica |
| LC 214/2025 Art. 348 III 'c' | Dispensa 2026 (fração = 0) |

## 7. Testes (TDD reverso)

Arquivo: `PY/tests/test_err046_opt_out_base.py` (8 testes em 5 classes)

| Classe | Testes | Propósito |
|---|---|---|
| `TestERR046Linearidade` | 2 | Invariante matemático (dobrar/triplicar valor_operacao) |
| `TestERR046NaoNegatividade` | 2 | Operação pequena nunca produz custo negativo |
| `TestERR046Boundary2026` | 1 | Fração IVA = 0 em 2026 (Art. 348 III 'c') |
| `TestERR046SimetriaReducao` | 2 | REDUCAO_60 expurga 40% + ISENTO expurga 0% |
| `TestERR046InvarianteSoma` | 1 | custo_total = das + iva em qualquer combinação |

**Resultado pré-fix:** 7 passaram (falso negativo por colunas zeradas em `DISTRIBUICAO_DAS`) + 1 falhou (simetria — revelou a bomba real).
**Resultado pós-fix:** 8/8 verdes.
**Suite completa:** 956 testes (948 + 8), zero regressões.

## 8. Versionamento

`MOTOR_VERSAO`: **1.1.0 → 1.2.0** (MINOR SemVer).
- MAJOR: mudança que quebra contrato de schema → não aplica.
- MINOR: mudança de regra fiscal sem quebra → aplica.
- Infra de rastreamento: campo `versao_motor` já existe no JSON do diagnóstico (commit 65b35ea).
- Diagnósticos v1.1.0 com `valor_operacao ≠ rbt12/12` são identificáveis para reprocessamento.

## 9. Lastro de decisões

| Decisão | Origem | Fundamento |
|---|---|---|
| Escopo `cenario_opt_out` apenas | Chefe #1 + Viciado #4 | Varredura independente: 4 usos de `valor_operacao ×` → só linha 740 misturava bases |
| Reutilizar `_fracao_iva_no_das` | Viciado #2 + Luiz ressalva | DRY; mesma fonte que `credito_b2b_simples` |
| Simetria `fator_reducao` | Luiz #3 (veto) | LC 214/2025 Arts. 258-264 aplicação isonômica |
| Severidade 🔴 | Luiz #5 | Viés direcional + MAX_01 + MAX_02 violados |
| Bump 1.2.0 | Chefe #2 | SemVer MINOR — mudança cálculo sem quebra schema |
| Amparo expandido | Luiz #2 | Trilha atual viola MAX_FISCAL_02 |
| 8 testes TDD reverso | Viciado #6 + Luiz #6 | Canários permanentes + teste de valor absoluto |
| Mesma sprint (não solo) | Chefe #5 | Mudança atômica, ripple automático, arquivos diferentes de V-13/V-14 |

## 10. Assinaturas

- **chefe-deus** — ✅ Aprovado com bump 1.2.0
- **o-viciado** — ✅ Aprovado com reutilização de `_fracao_iva_no_das`
- **luiz-moreira** — ✅ Aprovado com simetria incorporada
- **Usuário (Luis Miguel)** — ✅ Autorizou Fase 2 em 23/04/2026
- **Orquestrador** — ✅ Fase 2 executada, 956 testes verdes, Fase 3 (Devin) e Fase 4 (Luiz) pendentes

---

**Arquivos tocados na Fase 2:**
- `PY/core/motor_tributario.py` (cenario_opt_out + MOTOR_VERSAO)
- `PY/tests/test_err046_opt_out_base.py` (novo)
- `docs/roadmap/LOG_ERROS.md` (ERR-046 fechado)
- `docs/atas/ATA_CONSENSO_ERR046_cenario_opt_out.md` (este arquivo)

**Próximas fases:** 3 (Devin cruza) + 4 (Luiz marca gol) antes do commit final.
