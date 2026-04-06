# MATRIZ DE RISCO OPERACIONAL — Motor Tributário Conect 2026-2033
**Responsável:** O CHEFE (aprovação) + Luiz Moreira (risco tributário) + O Viciado (risco técnico)
**Criado:** 27/03/2026 | **Revisão:** A cada auditoria real ou novo erro identificado

> **Protocolo:** Quando novo risco for identificado em auditoria real, registrar aqui ANTES de fechar o erro no LOG_ERROS.md.

---

## LEGENDA

| Símbolo | Significado |
|---------|-------------|
| 🔴 | CRÍTICO — impacto direto em cálculo ou conformidade |
| 🟡 | ALTO — afeta completude, cobertura ou experiência |
| 🟢 | MÉDIO — risco de manutenção ou operacional |
| ⚪ | BAIXO — monitoramento preventivo |
| ✅ | Mitigado |
| ⏳ | Pendente de mitigação |
| 🔬 | Identificado em auditoria real |

---

## CATEGORIA 1 — RISCOS DE CÁLCULO TRIBUTÁRIO

### R01 — CNAE não mapeado → Anexo errado
**Nível:** 🔴 CRÍTICO | **Status:** ✅ Mitigado (ERR-005)
**Descrição:** CNAE fora de CNAE_PARA_ANEXO causa enquadramento errado.
**Impacto:** AE I faixa 5 = 9,97% vs AE III faixa 5 = ~18% → diferença brutal.
**Evidência:** CANAVEZI CNAE 4757100 retornava Anexo III (errado) em vez de Anexo I.
**Mitigação:** `raise ValueError` obriga informar `anexo_simples` explicitamente.
**Risco residual:** ~1.270 CNAEs ainda não mapeados. Workaround: campo `anexo_simples`.

### R02 — Base mensal estimada (RBT12/12) vs RPA real
**Nível:** 🔴 CRÍTICO para auditoria | 🟡 ALTO para planejamento | **Status:** ✅ Mitigado (ERR-007)
**Descrição:** Motor usava RBT12/12 (estimativa); PGDAS-D usa RPA do mês (base legal).
**Impacto:** ITANGUA 01/2026 → delta R$ 6.188,51 (24,2% do DAS).
**Evidência:** RBT12/12=R$305.852 vs RPA real=R$245.532 → AE×RPA real delta ≤ R$75.
**Mitigação:** Campo `rpa_mensal` em `OperacaoFiscal`. Quando preenchido, usa RPA.
**Risco residual:** Delta residual ~R$74 (0,29% do DAS) — causa desconhecida, aceito.

### R03 — ICMS-ST não segregado
**Nível:** 🔴 CRÍTICO | **Status:** ✅ Mitigado (ERR-006)
**Descrição:** Empresas com Substituição Tributária de ICMS têm base dupla no PGDAS-D.
**Impacto:** CANAVEZI → superestimativa ICMS de R$ 1.132,41 por mês.
**Evidência:** Motor: R$ 5.577,74 | e-CAC: R$ 4.445,33 → Delta R$ 1.132,41.
**Mitigação:** Campo `receita_com_st_icms` + lógica de segregação em `calcular_das_mensal()`.

### R04 — Cronograma IVA desatualizado
**Nível:** 🔴 CRÍTICO | **Status:** ✅ Mitigado (ERR-002)
**Descrição:** Alíquotas CBS/IBS erradas impactam todos os cálculos de Opt-Out e Split Payment.
**Impacto:** 2027 Split: R$ 450 calculado vs R$ 4.450 correto (erro 10×).
**Mitigação:** CRONOGRAMA_IVA corrigido com valores LC 214/2025, Arts. 344, 348, 353-360.
**Risco residual:** Alíquotas 2027+ sujeitas a Resolução do Senado — monitorar DOU.

### R05 — Fator R zona de risco (0,27-0,29)
**Nível:** 🟡 ALTO | **Status:** ⏳ Monitoramento ativo
**Descrição:** Fator R = Folha/RBT12 nesta faixa → pequena variação muda de Anexo V para III.
**Impacto:** Mudança de AE poderia reduzir DAS em 5-8 pontos percentuais.
**Mitigação:** Alerta automático `FATOR_R_ZONA_RISCO` em `_gerar_alertas()`.
**Ação recomendada:** Luiz monitora mensalmente quando Fator R estiver em 0,27-0,29.

### R06 — RBT12 próximo do teto (>90%)
**Nível:** 🟡 ALTO | **Status:** ⏳ Monitoramento ativo
**Descrição:** RBT12 > R$4.320.000 → risco de exclusão do Simples Nacional.
**Impacto:** Migração abrupta para Lucro Presumido → aumento de carga tributária.
**Mitigação:** Alerta automático `RBT12_PROXIMO_TETO` em `_gerar_alertas()`.

---

## CATEGORIA 2 — RISCOS DE DADOS E EXTRAÇÃO

### R07 — PDF ilegível → campos não extraídos
**Nível:** 🟡 ALTO | **Status:** ⏳ Aguarda ANTHROPIC_API_KEY
**Descrição:** PDFs scaneados (Tipo B) podem ter qualidade insuficiente para extração.
**Impacto:** Campos obrigatórios ausentes → auditoria não pode ser concluída.
**Mitigação planejada:** Campo `confianca_extracao` em `DadosExtraidosPDF`. Se < 0,7 → alerta.
**Dependência:** `ANTHROPIC_API_KEY` configurada + pipeline `extrator_pdfs.py` ativo.

### R08 — CNPJ inválido na entrada
**Nível:** 🟡 ALTO | **Status:** ✅ Mitigado
**Descrição:** CNPJ com dígito verificador errado contamina todos os cálculos subsequentes.
**Mitigação:** `validar_cnpj()` com Módulo 11 em `EmpresaFornecedora` (Pydantic V2).

### R09 — Float em valor monetário
**Nível:** 🔴 CRÍTICO | **Status:** ✅ Mitigado
**Descrição:** Float causa erros de precisão que se acumulam em múltiplas operações.
**Mitigação:** `Decimal` obrigatório em todos os campos monetários. Float detectado → `logger.warning`.

### R10 — CNPJ/Razão Social em log
**Nível:** 🟡 ALTO (LGPD) | **Status:** ✅ Mitigado
**Descrição:** Dados pessoais em log violam LGPD Art. 15 e expõem o escritório.
**Mitigação:** Todos os logs usam regime e tipo (nunca CNPJ). `purge()` após uso.

---

## CATEGORIA 3 — RISCOS DE LEGISLAÇÃO

### R11 — Resolução do Senado altera alíquotas IBS 2027+
**Nível:** 🔴 CRÍTICO | **Status:** ⏳ Monitoramento obrigatório
**Descrição:** LC 214/2025, Art. 18 — alíquotas IBS/CBS 2027+ fixadas por Resolução do Senado.
**Impacto:** Qualquer mudança torna CRONOGRAMA_IVA desatualizado automaticamente.
**Ação requerida:** Luiz monitora DOU mensalmente. Toda alteração → atualizar tabelas_simples.py + notificar Chefe.
**Responsável:** Luiz Moreira

### R12 — ICMS/ISS extintos antes de 2033
**Nível:** 🟡 ALTO | **Status:** ⏳ Monitoramento
**Descrição:** LC 214/2025 prevê extinção gradual 2029-2033. Legislação estadual pode antecipar.
**Impacto:** DISTRIBUICAO_DAS Faixa 6 precisa ser atualizada se antecipação ocorrer.
**Ação requerida:** Monitorar legislação estadual de SP (ICMS) e municipal de Sorocaba (ISS).

### R13 — Opt-Out sem regulamentação definitiva
**Nível:** 🟡 ALTO | **Status:** ⏳ Aguarda regulamentação
**Descrição:** O mecanismo de Opt-Out do IBS/CBS pelo Simples Nacional depende de regulamentação da Receita Federal.
**Impacto:** `cenario_opt_out()` pode precisar ser revisado quando sair IN regulamentadora.
**Ação requerida:** Luiz monitora publicação de IN complementar à LC 214/2025.

---

## CATEGORIA 4 — RISCOS OPERACIONAIS QA (Stress Test)

### R14 — Conciliação de datas (Emissão ≠ Liquidação em meses diferentes)
**Nível:** 🟡 ALTO | **Status:** ⏳ Alerta a implementar
**Descrição:** Nota emitida em dez/2026 com pagamento em jan/2027 → competência e Split Payment divergem.
**Impacto:** Split Payment ativo no pagamento (jan/2027) mas não na emissão (dez/2026).
**Alerta a criar:** `CONCILIACAO_RISCO` em `_gerar_alertas()`.
**Bloqueante:** `test_fase5_stress.py` cenário C1 — Fantasma do Ano Novo.

### R15 — Cruzamento do Sublimite na operação
**Nível:** 🟡 ALTO | **Status:** ⏳ Alerta a implementar
**Descrição:** RBT12 + valor da nota cruza R$ 3.600.000 → parte do DAS muda de faixa no mês.
**Impacto:** Empresa pode estar em Faixa 5 (ICMS no DAS) e cruzar para Faixa 6 (ICMS fora) a qualquer operação.
**Alerta a criar:** `SUBLIMITE_CRITICO` em `_gerar_alertas()`.
**Bloqueante:** `test_fase5_stress.py` cenário C2 — Explosão do Sublimite.

### R16 — NF com muitos itens (> 50 NCMs)
**Nível:** 🟢 MÉDIO | **Status:** ⏳ Alerta a implementar
**Descrição:** NF com > 50 itens pode causar timeout na API do CGIBS (Split Payment).
**Impacto:** Retenção pode ser calculada na alíquota máxima (26,5%) em caso de timeout.
**Alerta a criar:** `RISCO_TIMEOUT_API` em `_gerar_alertas()`.
**Bloqueante:** `test_fase5_stress.py` cenário C3 — Salada de Frutas.

### R17 — Estorno com Split Payment já retido
**Nível:** 🟡 ALTO | **Status:** ⏳ Alerta a implementar
**Descrição:** Devolução de mercadoria após Split Payment retido cria crédito de difícil recuperação.
**Impacto:** Capital de giro comprometido; prazo de restituição undefined.
**Alerta a criar:** `CAPITAL_GIRO_COMPROMETIDO` em `_gerar_alertas()`.
**Bloqueante:** `test_fase5_stress.py` cenário C4 — Estorno do Medo.

---

## CATEGORIA 5 — RISCOS DE DESENVOLVIMENTO

### R18 — JS mirror (index.html) divergindo do Python
**Nível:** 🟡 ALTO | **Status:** ✅ Mitigado (ERR-003, ERR-004)
**Descrição:** Frontend usa mirror JS do motor Python. Divergências causam cálculos errados ao cliente.
**Evidência:** Split Payment 2027 → R$ 450 (JS) vs R$ 4.450 (Python) → erro 10×.
**Mitigação:** Protocolo: JS SEGUE Python, nunca lidera. Deploy checklist com validação manual.
**Risco residual:** 4 novos alertas de stress test ainda não espelhados no JS.

### R19 — Testes insuficientes para novos métodos
**Nível:** 🟡 ALTO | **Status:** ⏳ Parcial
**Descrição:** `calcular_das_detalhado()`, alertas stress, multi-atividade — sem cobertura de teste.
**Mitigação:** TDD obrigatório. Novo método → teste antes.
**Pendente:** `test_fase5_stress.py` (16+ testes) a criar.

### R20 — ANTHROPIC_API_KEY não configurada
**Nível:** 🟡 ALTO | **Status:** ⏳ Bloqueante externo
**Descrição:** Pipeline `extrator_pdfs.py` e `audit_universal.py` dependem da chave.
**Impacto:** Auditorias CONFI-AR e futuras bloqueadas para automação.
**Ação:** Chefe precisa provisionar chave. Nunca comitar em código ou log.

---

## SCORECARD DE RISCO

```
Riscos CRÍTICOS (🔴):    6 identificados | 5 mitigados ✅ | 1 monitoramento ativo
Riscos ALTOS (🟡):      10 identificados | 5 mitigados ✅ | 5 pendentes ⏳
Riscos MÉDIOS (🟢):      4 identificados | 0 mitigados | 4 pendentes ⏳
Riscos BAIXOS (⚪):       0 identificados

Risco residual crítico ativo: R11 (Resolução do Senado)
Próximos a mitigar: R14, R15, R16, R17 (stress test), R20 (API key)
```

---

## PLANO DE MITIGAÇÃO — PRÓXIMOS 30 DIAS

| Prioridade | Risco | Ação | Responsável |
|------------|-------|------|-------------|
| 1 | R14-R17 | Criar `test_fase5_stress.py` + 4 alertas em `_gerar_alertas()` | O Viciado |
| 2 | R20 | Provisionar `ANTHROPIC_API_KEY` | O CHEFE |
| 3 | R01 | Mapa completo CNAE_PARA_ANEXO (~1.300 CNAEs) | Luiz Moreira |
| 4 | R11-R13 | Monitoramento DOU mensal | Luiz Moreira |
| 5 | R18 | Espelhar 4 alertas stress no `index.html` | Master Zen |

---

*Motor Tributário Conect 2026-2033 | Escritório Contábil Conect — Sorocaba, SP*
*Criado: 27/03/2026 | Atualizar a cada auditoria real ou erro identificado*
