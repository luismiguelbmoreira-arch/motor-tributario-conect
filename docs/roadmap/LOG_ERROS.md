# LOG DE ERROS — Motor Tributário Conect 2026-2033
**Protocolo:** Registrar todo erro encontrado durante auditorias, testes e operações.
**Atualização:** Obrigatória ao fim de cada sessão operacional.
**Responsável:** Equipe Conect × Escritório Moreira

---

## LEGENDA

| Símbolo | Significado |
|---------|-------------|
| 🔴 | Crítico — afeta cálculo ou produção |
| 🟡 | Atenção — afeta completude ou cobertura |
| ✅ | Corrigido e fechado |
| ⏳ | Pendente de correção |
| 🔬 | Identificado em auditoria real |

---

## ERROS ATIVOS ⏳

---


---

### ERR-013 — Falta campo "Data de Inicio de Atividade" para RBT12 proporcional
**Data:** 03/04/2026
**Severidade:** 🔴 Critico
**Arquivo:** `PY/motor_tributario.py` — `EmpresaFornecedora` + formulario `analise.html`
**Descoberto em:** 🔬 Auditoria de suficiencia de campos (Luiz Moreira)

**Descricao:**
Empresas com menos de 12 meses de atividade devem ter RBT12 proporcionalizada:
`RBT12_prop = (receita_acumulada / meses_atividade) * 12`
Sem o campo `data_inicio_atividade`, o motor aceita RBT12 bruta e pode enquadrar
a empresa na faixa errada (para cima ou para baixo).

**Evidencia:**
Art. 3o, par. 2o, LC 123/2006 — "No caso de inicio de atividade no proprio
ano-calendario, os limites [...] serao proporcionais ao numero de meses [...]"

**Solucao necessaria:**
1. Adicionar `data_inicio_atividade: Optional[date]` em `EmpresaFornecedora`
2. Se `data_inicio < 12 meses atras`: motor proporcionaliza automaticamente
3. Adicionar campo no formulario `analise.html` (Step 1)

**Status:** ✅ Corrigido — campo `data_inicio_atividade` adicionado + lógica de proporcionalização implementada em `calcular_rbt12()`. Testes em `test_err_fixes.py`.

---

### ERR-014 — Salario Minimo MEI hardcoded apenas para 2026
**Data:** 03/04/2026
**Severidade:** 🟡 Atencao
**Arquivo:** `PY/regimes/mei.py` — `SALARIO_MINIMO_2026`
**Descoberto em:** 🔬 Auditoria de suficiencia de campos (Luiz Moreira)

**Descricao:**
DAS MEI = 5% do salario minimo + ICMS/ISS fixos. O SM esta hardcoded como
R$ 1.622,00 (2026). Para simulacoes 2027-2033, o DAS sera calculado com SM
desatualizado. Erro cresce a cada ano (~7% ao ano de reajuste medio).

**Evidencia:**
LC 123/2006, Art. 18-A, par. 3o, I — INSS = 5% do salario minimo vigente.

**Solucao necessaria:**
Criar tabela `SM_POR_ANO` em `tabelas_simples.py` com estimativas conservadoras.
Atualizar anualmente com decreto presidencial.

**Status:** ✅ Corrigido — `calcular_das_mensal(categoria, ano)` agora consulta `SM_POR_ANO[ano]` dinamicamente. Fallback com alerta para anos fora da tabela. Testes em `test_err_fixes.py`.

---

### ERR-015 — Lucro Presumido: transporte passageiros com presuncao 8% (deveria ser 16%)
**Data:** 03/04/2026
**Severidade:** 🔴 Critico
**Arquivo:** `PY/regimes/lucro_presumido.py` — `PRESUNCAO_IRPJ_CSLL`
**Descoberto em:** 🔬 Auditoria de suficiencia de campos (Luiz Moreira)

**Descricao:**
CNAEs 4921 (transporte passageiros municipal), 4922 (intermunicipal),
4929 (outros passageiros) e 4930 (transporte rodoviario passageiros)
tem presuncao IRPJ de 16%, nao 8%.
Motor atual mapeia todo prefixo "49" como 8% (presuncao de carga).

**Evidencia:**
Lei 9.249/1995, Art. 15, par. 1o, III, "a" — presuncao 16% para
servicos de transporte que nao sejam de carga.
RIR/2018, Art. 592.

**Solucao necessaria:**
Separar no dicionario `PRESUNCAO_IRPJ_CSLL`:
- "4921", "4922", "4929", "4930" → (0.16, 0.12)
- "49" default → (0.08, 0.12)  # carga

**Status:** ✅ Corrigido — `PRESUNCAO_IRPJ_CSLL` já mapeia CNAEs 4921/4922/4929/4930 com 16%. Método `_obter_percentual_presuncao()` busca 4 dígitos antes do fallback 2 dígitos. Testes em `test_err_fixes.py`.

---

### ERR-016 — Flag boolean `possui_reducao_cbs_ibs` insuficiente para calculo IVA
**Data:** 03/04/2026
**Severidade:** 🟡 Atencao
**Arquivo:** `PY/motor_tributario.py` — `OperacaoFiscal.possui_reducao_cbs_ibs`
**Descoberto em:** 🔬 Auditoria de suficiencia de campos (Luiz Moreira)

**Descricao:**
LC 214/2025, Arts. 258-270, preve reducoes de 30%, 60% e 100% (isencao)
conforme tipo de bem/servico. O campo boolean True/False nao permite
distinguir o percentual. Motor nao pode calcular aliquota efetiva reduzida.

**Evidencia:**
Art. 258 — reducao 60% (cesta basica, saude, educacao)
Art. 262 — reducao 30% (profissionais liberais regulamentados)
Art. 264 — isencao 100% (cesta basica nacional)

**Solucao necessaria:**
Substituir `possui_reducao_cbs_ibs: bool` por
`reducao_cbs_ibs: Literal["INTEGRAL", "REDUCAO_30", "REDUCAO_60", "ISENTO"]`
com default "INTEGRAL".

**Status:** ✅ Corrigido — campo renomeado para `reducao_cbs_ibs: Literal["INTEGRAL", "REDUCAO_30", "REDUCAO_60", "ISENTO"]`. Método `_fator_reducao_cbs_ibs()` aplica fator nos cálculos IVA. Testes em `test_err_fixes.py`.

---

### ERR-017 — Tabela PERFIL_B2B_POR_CNAE sem base legal
**Data:** 04/04/2026
**Severidade:** 🟡 Atencao
**Arquivo:** `PY/tabelas_simples.py` — `PERFIL_B2B_POR_CNAE`
**Descoberto em:** 🔬 Validacao legal (Luiz Moreira)

**Descricao:**
A tabela PERFIL_B2B_POR_CNAE estima percentual B2B/B2C por segmento CNAE
(ex: industria 90%, varejo 30%). NAO EXISTE base legal para isso — a LC 214/2025
opera NF-e por NF-e (Art. 47-48), nao por media estatistica do CNAE.

**Risco:** Se usada como dado de calculo automatico, pode gerar passivo tributario.
Art. 124, I, CTN: responsabilidade solidaria do escritorio.

**Solucao implementada:**
- Tabela rebaixada de "dado de calculo" para "sugestao de pre-selecao visual"
- Disclaimer explicito no endpoint /cnae/{cnae}/perfil
- Frontend mostra "Ajuste conforme sua realidade — sem base legal"
- Percentual real DEVE ser informado pelo contribuinte/contador
- Registrado na trilha de auditoria como "INFORMADO PELO USUARIO"

**Status:** ✅ Corrigido — tabela e sugestao visual, nao dado de calculo

---

### ERR-005 — CNAE_PARA_ANEXO incompleto (fallback errado)
**Data:** 27/03/2026
**Severidade:** 🔴 Crítico
**Arquivo:** `PY/tabelas_simples.py` — `CNAE_PARA_ANEXO`
**Descoberto em:** Auditoria e-CAC CANAVEZI (CNAE 4757100)

**Quem está errado:** O motor. O arquivo da empresa está correto.

**Descrição:**
`CNAE_PARA_ANEXO` foi criado como mapeamento parcial (~30 CNAEs de Sorocaba).
CNAEs não mapeados recebem fallback `Anexo III`, que é incorreto para a maioria
dos casos de comércio (deveriam ser Anexo I) e indústria (Anexo II).

**Evidência:**
```
CNAE 4757100 = Comércio varejista eletroeletrônicos → correto: Anexo I
Motor retornou: Anexo III (ERRADO)
Impacto: AE I faixa 5 = 9,97% vs AE III faixa 5 = ~18% → diferença brutal
```

**Solução necessária:**
1. Expandir `CNAE_PARA_ANEXO` com lista completa (Luiz Moreira fornece)
2. OU alterar fallback de `"III"` para `raise ValueError("CNAE não mapeado — informe anexo_simples explicitamente")`
3. Campo `anexo_simples` em `EmpresaFornecedora` já existe como workaround

**CNAEs confirmados hoje para adicionar:**
- `4757100` → Anexo I (CANAVEZI, comércio varejista eletroeletrônicos)
- `2539001` → Anexo II (ITANGUA, usinagem/tornearia/solda — confirmado por IPI no DAS)

**Status:** ⏳ Parcial — fallback agora levanta `ValueError` (ERR-005 Opção B implementada). Adicionar 2 CNAEs acima como próximo passo.

---

### ERR-006 — Motor não modela ICMS-ST parcial
**Data:** 27/03/2026
**Severidade:** 🟡 Atenção
**Arquivo:** `PY/motor_tributario.py` — `calcular_das_mensal()`
**Descoberto em:** 🔬 Auditoria e-CAC CANAVEZI

**Descrição:**
Empresas com duas atividades (revenda sem ST + revenda com ST de ICMS)
declaram no PGDAS-D com bases separadas:
- Parcela sem ST: ICMS entra normalmente no DAS
- Parcela com ST: ICMS = R$ 0 (já retido pelo substituto tributário)

O motor atual aplica alíquota uniforme sobre toda a RPA, superestimando o ICMS.

**Evidência — CANAVEZI 01/2026:**
```
RPA total     : R$ 180.817,99
RPA sem ST    : R$ 133.149,30  (ICMS no DAS)
RPA com ST    : R$  47.668,69  (ICMS zerado)

ICMS motor (base total)   : R$ 5.577,74
ICMS e-CAC (base sem ST)  : R$ 4.445,33
Delta ICMS                : R$ 1.132,41

DAS motor ajustado (ST manual) : R$ 16.405,12
DAS e-CAC oficial              : R$ 16.428,83
Delta após ajuste manual       : R$     23,71
```

**Solução necessária:**
Adicionar campo `receita_com_st_icms: Optional[Decimal]` em `EmpresaFornecedora`.
Quando preenchido, calcular DAS em duas partes:
- `receita_sem_st = faturamento_mensal - receita_com_st_icms`
- DAS_sem_st = receita_sem_st × AE
- DAS_com_st = receita_com_st_icms × AE × (1 - dist_ICMS)
- DAS_total  = DAS_sem_st + DAS_com_st

**Status:** ✅ Implementado — campo `receita_com_st_icms` adicionado em `EmpresaFornecedora`. Delta CANAVEZI com campo real pendente de validação com RPA mensal real (ver ERR-007).

---

### ERR-007 — Motor usa RBT12/12 como base mensal (aproximação incorreta para auditoria)
**Data:** 27/03/2026
**Severidade:** 🔴 Crítico para auditoria | 🟡 Aceitável para planejamento
**Arquivo:** `PY/motor_tributario.py` — `calcular_das_mensal()`
**Descoberto em:** 🔬 Auditoria e-CAC ITANGUA 01/2026

**Lastro Legal:**
LC 123/2006, Art. 18, §1º — *"O valor devido mensalmente pela ME ou EPP optante pelo Simples Nacional será determinado mediante aplicação das alíquotas efetivas [...] sobre a receita bruta do período de apuração."*

O período de apuração é o mês corrente (RPA), NÃO a média dos 12 meses (RBT12/12).

**Descrição:**
O motor calcula: `DAS = (RBT12 / 12) × AE`
O correto pelo PGDAS-D: `DAS = RPA_do_mes × AE`

RBT12/12 é uma estimativa que funciona bem para planejamento anual, mas gera delta sistemático em auditorias mensais onde o RPA difere da média.

**Evidência — ITANGUA 01/2026:**
```
RBT12/12 (estimativa motor): R$ 305.852,13
RPA real 01/2026:            R$ 245.531,86
AE Faixa 6 Anexo II:         10,3827%

DAS Motor(RBT12/12): R$ 31.755,71  ← Delta R$ 6.188,51 vs e-CAC
DAS Motor(RPA real): R$ 25.492,84  ← Delta R$    74,36 vs e-CAC
DAS e-CAC oficial:   R$ 25.567,20
```
Delta residual de R$ 74,36 com RPA real — causa investigada: hipótese de per-tributo rounding REFUTADA (diferença per-tributo = R$ 0,01 apenas). Causa real desconhecida: possível diferença de RBT12 no e-CAC, regra multi-atividade PGDAS-D, ou cálculo interno não documentado pela Receita.

**Solução implementada:**
- `rpa_mensal: Optional[Decimal]` adicionado a `OperacaoFiscal`
- `calcular_das_mensal()`: usa `rpa_mensal` quando disponível, senão `RBT12/12`
- `calcular_das_detalhado()`: componentes individuais para auditoria de composição

**Impacto:**
- Planejamento (sem RPA): aceitável — estimativa suficiente
- Auditoria e-CAC (com RPA): delta R$ 6.188 → R$ 74,36 (melhoria de 98,8%)
- Delta residual R$ 74,36 = 0,29% do DAS → aprovado manualmente pelo escritório

**Status:** ✅ Implementado — Bug principal (R$ 6.188) resolvido. Delta residual R$ 74,36 documentado e aceito (<0,3%).

---

## ERROS CORRIGIDOS ✅

---

### ERR-001 — DISTRIBUICAO_DAS somava 118,3% por linha
**Data:** 26/03/2026
**Severidade:** 🔴 Crítico
**Arquivo:** `PY/tabelas_simples.py` — `DISTRIBUICAO_DAS`
**Corrigido em:** 26/03/2026

**Descrição:**
Valores de COFINS (28,27%) e PIS (6,13%) da Faixa 6 foram copiados
erroneamente para as Faixas 1-5 (corretos: COFINS 12,74%, PIS 2,76%).
Cada linha somava ~118% ao invés de 100%.

**Correção:** Reescrita completa de todos os Anexos I–V com valores
oficiais da LC 123/2006, auditados por Luiz Moreira. Validado: cada
linha soma exatamente 100%.

---

### ERR-002 — CRONOGRAMA_IVA 2027 com valores errados
**Data:** 26/03/2026
**Severidade:** 🔴 Crítico
**Arquivo:** `PY/tabelas_simples.py` — `CRONOGRAMA_IVA`
**Corrigido em:** 26/03/2026

**Descrição:**
CBS 2027 estava em 4,4% (deveria ser 8,8%).
IBS 2027 estava em 2,0% (deveria ser 0,1%).
Cronograma 2029-2032 com CBS crescente (incorreto — CBS é estável em 8,8%).

**Correção:**
```python
# Antes (ERRADO):   2027: CBS 0.044, IBS 0.020
# Depois (CORRETO): 2027: CBS 0.088, IBS 0.001
```
Fonte: LC 214/2025 Arts. 344, 348, 353-360.

---

### ERR-003 — Split Payment com taxa fixa 0,9% para todos os anos
**Data:** 26/03/2026
**Severidade:** 🔴 Crítico
**Arquivos:** `PY/motor_tributario.py` + `index.html`
**Corrigido em:** 26/03/2026

**Descrição:**
`calcular_split_payment_impacto()` usava constante fixa
`ALIQUOTA_RETENCAO_SPLIT_PAYMENT = 0.009` (taxa de 2026) para todos os anos.
Para 2027: R$ 50.000 × 0,9% = R$ 450 (errado) vs correto R$ 4.450 (×10).

**Correção:** Split Payment dinamico usando `CBS + IBS` do ano da operação
via `get_aliquotas_iva_por_ano()`. Teste sentinela adicionado em
`test_fase4_optout.py` e `test_fase3_iva.py`.

---

### ERR-004 — JS mirror (index.html) não sincronizado com Python
**Data:** 26/03/2026
**Severidade:** 🔴 Crítico
**Arquivo:** `index.html` — `const IVA` e `Motor.split()`
**Corrigido em:** 27/03/2026

**Descrição:**
O `const IVA` do frontend mantinha os valores antigos (ERR-002) após
correção do Python. `Motor.split()` usava taxa fixa `0.009` (ERR-003).
Clientes atendidos no frontend recebiam cálculos 10× menores para 2027.

**Correção:** `const IVA` atualizado com cronograma correto LC 214/2025.
`Motor.split()` reescrito para usar `iva.CBS + iva.IBS` dinâmico.

---

### ERR-008 — Motor não suporta multi-atividade PGDAS-D
**Data:** 27/03/2026
**Status:** ✅ Corrigido
**Arquivo:** `PY/motor_tributario.py`

**Descrição:**
O motor não suportava o cálculo segregado por Anexo exigido pela LC 123/2006, Art. 18, §3º.

**Correção:**
Implementação da classe `Atividade` e suporte a loop em `calcular_das_mensal()` e `calcular_das_detalhado()`. Validado contra caso real CONFI-AR 01/2026 (Delta reduziu de R$ 2.783 para R$ 14,45).

---

### ERR-018 — /integracoes/ecac/sync não valida ownership de CNPJ (IDOR horizontal)
> **Nota de renumeração (23/04/2026):** originalmente registrado como ERR-013,
> em colisão com o ERR-013 de "Data de Início de Atividade" (já corrigido em
> 03/04/2026). Renumerado para ERR-018 para preservar rastreabilidade.

**Data:** 23/04/2026
**Severidade:** 🔴 Crítico
**Amparo legal violado:** CTN Art. 198 (sigilo fiscal) + LGPD Art. 48 (incidente reportável à ANPD)
**Arquivo:** `PY/api/routers/integracoes.py` — `ecac_sync_a1()`
**Descoberto em:** Review do Viciado + Parecer Luiz Moreira na Fase 1 do plano Front/Backend

**Descrição:**
Após a Fase 1 aplicar auth no router inteiro de `/integracoes/*`, o endpoint
`ecac_sync_a1` agora exige JWT — o que resolve o vetor **anônimo**. **Porém**,
o CNPJ vem do `Form(...)` e não é validado contra o `current_user`. Qualquer
usuário autenticado consegue mandar o CNPJ de OUTRO cliente do escritório e
extrair dados via certificado A1. **Autorização horizontal (IDOR)** em aberto
em endpoint que mexe com dado fiscal de terceiro via certificado Gov.br.

**Parecer Luiz Moreira:** o fato de exigir JWT mitiga apenas o vetor anônimo.
O dano possível — vazamento de PGDAS-D de cliente de outro escritório em
cenário multi-tenant — é material e configura:
- **CTN Art. 198** — violação direta do sigilo fiscal
- **LGPD Art. 48** — incidente de segurança reportável à ANPD

**Evidência:** handler aceita `cnpj: str = Form(...)` sem cross-check com
relação User↔Empresa no DB.

**Solução necessária (Fase 2.5 — Ownership Guards, fase própria):**
1. Criar relação `user_empresas` (ou usar `auditoria_documentos.uploaded_by_user_id`)
2. Helper `tem_acesso_cnpj(user_id, cnpj) -> bool`
3. No handler: `if not tem_acesso_cnpj(current_user["id"], cnpj): raise HTTPException(403)`
4. Aplicar mesmo guard em todo endpoint que aceita CNPJ como parâmetro
   (sieg_sincronizar, integra_sincronizar, dossiê de prova, etc.)

**PRAZO:** antes de qualquer deploy multi-tenant. Não pode entrar em produção
compartilhada sem isso.

**Status:** ⏳ Pendente — não bloqueia Fase 1 (vetor anônimo fechado), mas
bloqueia qualquer liberação multi-tenant.

---

### ERR-019 — Vazamento de PII entre contas via sessionStorage (analise_empresa/analise_cnpj/diagnostico)
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico
**Amparo legal violado:** LGPD Art. 46 (segurança) + Art. 6º V (minimização)
**Arquivo:** `UI/components.js:128-130` (setupLogout) + `UI/components.js:232-235` (mcFetch 401)
**Descoberto em:** Auditoria Fase 2 — O Viciado

**Descrição:**
No logout e no 401 global do mcFetch, apenas 3 chaves eram limpas: `token`,
`username`, `role`. Permaneciam vivas em `sessionStorage`:
- `analise_empresa` (razão social do cliente — gravada em `UI/resultado.html:1702`)
- `analise_cnpj` (CNPJ do cliente — gravada em `UI/resultado.html:1703`)
- `diagnostico` (JSON completo com PII + trilha de auditoria)

**Cenário de exploração:** operador A autentica com empresa X, token expira
ou ele faz logout. Operador B entra no mesmo browser (cenário real em home
office com monitor compartilhado) → ao navegar direto para `resultado.html`
vê CNPJ + razão social + diagnóstico do cliente do A.

**Evidência:** grep de `sessionStorage.setItem` em `UI/resultado.html:1702-1703`
gravando `analise_empresa` e `analise_cnpj` que nunca eram limpos no 401/logout.

**Solução aplicada (Fase 2):** trocado `removeItem` campo-a-campo por
`sessionStorage.clear()` em:
- `UI/components.js:128-130` (logout)
- `UI/components.js:232-235` (mcFetch 401 handler)

Operação atômica, imune a esquecimento de chave nova.

**Status:** ✅ Corrigido na Fase 2 — Contratos Blindados

---

### ERR-020 — Timeout mcFetch insuficiente no upload de PDF (/analise/pdf)
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção
**Arquivo:** `UI/analise_unificada.html:364`
**Descoberto em:** Auditoria Fase 2 — O Viciado

**Descrição:**
O novo `mcFetch` impôs timeout default de 30s. Já no `resultado.html` os
downloads do dossiê ZIP e geração PDF foram ajustados para 60s. Mas o
upload de `/analise/pdf` em `analise_unificada.html:364` foi migrado para
`mcFetch` sem timeout custom → pegou o default de 30s. Este endpoint executa:

1. Upload de até 20 arquivos × 50 MB = 1 GB possível
2. Extração via Claude Vision (10-40s por documento grande)
3. Parsers XML NFe/NFCe/CSV/SPED ECD/SPED EFD-Contrib
4. Motor tributário + merge + validações cruzadas + semáforo DAS
5. Cifragem AES-256-GCM + persistência `auditoria_documentos`

Em produção com 4-6 PDFs reais, 40-60s é cenário **normal**. Cliente abortava
com backend ainda no meio da cifragem → `auditoria_documentos` ficava com
linhas órfãs (arquivo cifrado em disco + metadata em DB) SEM diagnóstico
correspondente. Operador via erro, backend ficava inconsistente.

**Solução aplicada (Fase 2):** `timeout: 180000` (3 minutos) explícito no
`mcFetch` de `analise_unificada.html:364`.

**Considerar:** elevar para 300000 (5 min) se picos do Claude Vision
começarem a aparecer em monitoramento.

**Status:** ✅ Corrigido na Fase 2 — Contratos Blindados

---

### ERR-021 — Parsers em /analise/pdf com except Exception silencioso (7 pontos)
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção
**Amparo legal violado:** CTN Art. 142 (motivação do lançamento) — trilha deve refletir falhas
**Arquivo:** `PY/main.py` — linhas 1022, 1029, 1038, 1050, 1057, 1091, 1110
**Descoberto em:** Auditoria Fase 2 — O Viciado (escopo travado em linha 1170)

**Descrição:**
A Fase 2 blindou o `except Exception` do bloco de validações/anomalias
(linha 1170) com `exc_info=True` + entrada estruturada em `diagnostico._erros`.
Mas 7 try/except de parsers no mesmo endpoint `/analise/pdf` continuam no
padrão antigo:

| Linha | Origem | Problema |
|-------|--------|----------|
| 1022 | Parser XML NFe | `logger.warning(msg, exc)` sem `exc_info=True` e sem `_erros` |
| 1029 | Parser XML NFCe | idem |
| 1038 | Parser CSV folha | idem |
| 1050 | Parser SPED ECD | idem |
| 1057 | Parser SPED EFD-Contrib | idem |
| 1091 | Auditoria doc extra (cifragem XMLs/CSVs) | idem |
| 1110 | Termo de aceite (LGPD Art. 37) | idem |

**Impacto:** se um XML NFe vier corrompido, o diagnóstico roda **sem os dados
daquele XML** → Fator R calculado com `folha_12m` parcial → Anexo errado.
Auditor depois pergunta "por que Anexo III se a folha era 30%?" e a resposta
— "um XML foi descartado por erro de parse" — não está no diagnóstico.

**Solução necessária (Fase 3 ou Fase 2.5):** helper
`_registrar_erro_parser(origem: str, exc: Exception, diagnostico: dict)`
aplicando o mesmo padrão do fix de 1170:
- `logger.warning("Falha parser %s: %s — %s", origem, type(exc).__name__, exc, exc_info=True)`
- `diagnostico.setdefault("_erros", []).append({"origem": origem, "tipo": type(exc).__name__, "mensagem": str(exc)})`

Aplicar em todos os 7 pontos.

**Status:** ✅ Corrigido na Fase 2 — Contratos Blindados (ciclo Luiz→Viciado) — consolidado com ERR-025, ver abaixo.

---

### ERR-022 — Numeração duplicada de ERR-013 no LOG_ERROS.md
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção (integridade documental)
**Arquivo:** `docs/roadmap/LOG_ERROS.md`
**Descoberto em:** Auditoria Fase 2 — O Viciado

**Descrição:**
Dois erros compartilhavam o identificador ERR-013:
1. **ERR-013 (03/04/2026)** — "Falta campo Data de Inicio de Atividade"
   (corrigido).
2. **ERR-013 (23/04/2026)** — "IDOR em /integracoes/ecac/sync"
   (pendente).

Rastreabilidade comprometida — auditor externo não consegue referenciar
um ERR sem ambiguidade.

**Solução aplicada (Fase 2):** o segundo ERR-013 (IDOR) renumerado para
**ERR-018**, preservando o primeiro (corrigido). Nota de renumeração
adicionada no cabeçalho do novo ERR-018 para rastreabilidade histórica.

**Status:** ✅ Corrigido na Fase 2 — Contratos Blindados

---

### ERR-023 — `_erros`/`_anomalias` ausentes do PDF cliente (CTN Art. 142)
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico
**Amparo legal violado:** CTN Art. 142 (motivação) + LGPD Art. 37 + LC 214/2025 Art. 45 §3º
**Arquivo:** `PY/services/relatorio_pdf.py`
**Descoberto em:** Auditoria Fase 2 — Luiz Moreira (revisão do parecer do Viciado)

**Descrição:**
O PDF entregue ao cliente/fisco via `_gerar_html()` só renderizava a trilha
filtrada (`_filtrar_trilha_cliente`). Os campos `_erros` (falhas não-fatais
de parser) e `_anomalias` (alertas de `validacoes.detectar_anomalias`) nunca
eram lidos, mesmo após o fix do ERR-021 popular `_erros`. Consequência: o
contador entrega um PDF "limpo" enquanto o backend registrou falha silenciosa —
**o dossiê jurídico fica inútil para defesa** porque o auditor externo vê o
PDF do cliente, não o JSON de trilha bruta.

**Impacto:** lançamento tributário sem motivação completa (CTN Art. 142)
abre brecha de nulidade. LGPD Art. 37 exige registro de operações de
tratamento — a ausência de registro é tão grave quanto registro falso.

**Solução aplicada (Fase 2):**
- Nova função `_secao_eventos_pipeline(diagnostico)` em `relatorio_pdf.py`.
- Seção renderizada no HTML entre "Decisão Opt-Out" e "Rodapé".
- Caso sem eventos: imprime bloco verde "Pipeline executado sem ressalvas —
  Nenhuma anomalia detectada em `_anomalias` nem falha registrada em
  `_erros`. Registro de ausência também é prova — CTN Art. 142, LGPD Art. 37,
  LC 214/2025 Art. 45 §3º."
- Casos com eventos: cards coloridos (amarelo p/ anomalia, vermelho p/ erro)
  listando origem, tipo da exception e mensagem + amparo legal associado.

**Status:** ✅ Corrigido na Fase 2 — Contratos Blindados (ciclo Luiz→Viciado)

---

### ERR-024 — `AnaliseManualRequest` sem guards de consistência fiscal
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico
**Amparo legal violado:** LC 123/2006 Art. 18-A §§1º, 3º, 5º-7º + LC 214/2025 Art. 47 II + Art. 48
**Arquivo:** `PY/main.py` (classe `AnaliseManualRequest` + handler `/analise/manual` linha ~544)
**Descoberto em:** Auditoria Fase 2 — Luiz Moreira (revisão do parecer do Viciado)

**Descrição:**
O contrato do endpoint `/analise/manual` aceitava 3 combinações semanticamente
erradas sem bloquear:

| Cenário | Problema | Amparo |
|---|---|---|
| `regime=MEI + faturamento_12m > 81.000` | Rodava cálculo MEI com empresa já desenquadrada — DAS ficaria R$ 71-80 sobre receita que já exige Simples | LC 123/2006 Art. 18-A §1º + §§ 5º-7º |
| `regime=MEI + categoria_mei=None` | `main.py:544` fazia fallback silencioso `or "SERVICOS"`. Categoria errada = DAS errado (R$ 71,60 vs R$ 76,60 vs R$ 80,90 em 2026) | LC 123/2006 Art. 18-A §§3º I a III |
| `tipo_comprador=B2C ou B2B + percentual_b2b != 100` | Motor aceitava incoerência — recomendação Opt-Out calculada com base errada em operação de consumidor final | LC 214/2025 Art. 47 II + Art. 48 |

**Impacto:** diagnóstico fiscal com base errada, não detectável por testes
existentes porque o contrato aceitava. Contador que confia no motor entrega
posição fiscal incorreta.

**Solução aplicada (Fase 2):**
- Adicionado `@model_validator(mode="after") def validar_consistencia_fiscal`
  em `AnaliseManualRequest` com os 3 bloqueios + citação legal explícita
  em cada `ValueError`.
- Teto usa a constante FROZEN `core.regimes.mei.TETO_ANUAL_MEI = Decimal("81000.00")`
  — nada de hardcoded (MAX_FISCAL_02).
- Removido fallback `or ("SERVICOS" if req.regime == "MEI" else None)` em
  `main.py:544` — agora o validator garante que `categoria_mei` nunca é None
  quando regime=MEI.
- Validação manual: 3 cenários errados bloqueados com 422, 2 cenários
  legítimos (MEI SERVICOS com folha=0 / MISTO com pct_b2b=60) passam.
- Nenhum teste existente passava `regime=MEI` em `/analise/manual`, então
  nenhum teste foi ajustado.

**Status:** ✅ Corrigido na Fase 2 — Contratos Blindados (ciclo Luiz→Viciado)

---

### ERR-025 — Parsers de `/analise/pdf` com except silencioso (promovido de ERR-021)
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico (promovido de 🟡 em ERR-021)
**Amparo legal violado:** CTN Art. 142 + CTN Art. 137 + LGPD Art. 37 + LC 214/2025 Art. 45 §3º + Lei 8.137/1990 Art. 1º II
**Arquivo:** `PY/main.py` — linhas 1022, 1029, 1038, 1050, 1057, 1091, 1110
**Descoberto em:** Auditoria Fase 2 — Luiz Moreira (promoção do ERR-021)

**Descrição:**
Luiz promoveu o ERR-021 para blocker crítico após análise de impacto no
Split Payment: `tinha_st_icms` e `data_liquidacao` vindos de NFe/XML
corrompido sem registro de falha produzem split com lastro inválido —
exposição a Lei 8.137/1990 Art. 1º II (crime contra a ordem tributária
por omissão dolosa de rastro) e CTN Art. 137 (dolo eventual do contador).

**Solução aplicada (Fase 2):**
- Novo helper `_registrar_erro_parser(origem, exc, diagnostico)` em
  `PY/main.py` (logo após `_serializar_decimal`).
- Substituições nos 7 pontos, com `origem` semântica:
  - 1022 → `"parser_xml_nfe"`
  - 1029 → `"parser_xml_nfce"`
  - 1038 → `"parser_csv_folha"`
  - 1050 → `"parser_sped_ecd"`
  - 1057 → `"parser_sped_efd_contrib"`
  - 1091 → `f"auditoria_doc_extra:{nome_extra}"` (inclui nome do arquivo)
  - 1110 → `"termo_aceite_lgpd"`
- Padrão unificado: `logger.warning(..., exc_info=True)` + append
  em `diagnostico["_erros"]` com `{origem, tipo, mensagem}`.
- `diagnostico` já está atribuído (`payload["diagnostico"]` na linha ~1011)
  antes de qualquer um dos 7 pontos — sem necessidade de buffer intermediário.

**Consolidação com ERR-021:** mesmo fix. ERR-021 marcado como ✅ Corrigido
apontando para este ERR-025.

**Status:** ✅ Corrigido na Fase 2 — Contratos Blindados (ciclo Luiz→Viciado)

---

### ERR-026 — `response_model=DiagnosticoResponse` inerte por `JSONResponse`
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção
**Amparo legal violado:** MAX_FISCAL_05 (contrato ostensivo ≠ contrato executado)
**Arquivo:** `PY/main.py:509` (`/analise/manual`), `PY/main.py:874` (`/analise/pdf`), retornos em `PY/main.py:610`, `PY/main.py:1189`
**Descoberto em:** Auditoria Fase 2 — Luiz Moreira

**Descrição:**
Os handlers `/analise/manual` e `/analise/pdf` retornam
`JSONResponse(content=_serializar_decimal(payload))`. Quando o handler
devolve `Response` (ou subclasse), o FastAPI **pula a validação do
`response_model`** — o objeto já está serializado em bytes, não passa
pelo pipeline `jsonable_encoder`+Pydantic.

**Efeito prático:** o `PIIResponse(min_length=14)` e demais validações
de `DiagnosticoResponse` NUNCA são aplicadas em resposta real — só
aparecem no OpenAPI/schema. Violação do próprio MAX_FISCAL_05 (o contrato
ostensivo não é o que roda).

**Solução necessária:**
Dois caminhos alternativos:
1. Trocar `JSONResponse(...)` por `return payload` deixando o FastAPI
   executar `response_model` — requer custom encoder para Decimal.
2. Assumir que `response_model` é só para OpenAPI e aplicar validação
   explícita antes do `JSONResponse`:
   `DiagnosticoResponse.model_validate(payload).model_dump(mode="json")`.

Decisão de qual via seguir aguarda aprovação de Luiz/Chefe antes de mexer.

**Status:** ⏳ Pendente

---

### ERR-027 — `_erros` não persistido no diagnóstico do DB (LGPD Art. 37)
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção
**Amparo legal violado:** LGPD Art. 37 (registro permanente de operações de tratamento)
**Arquivo:** `PY/main.py:1183` + `PY/api/routers/auditoria.py`
**Descoberto em:** Auditoria Fase 2 — Luiz Moreira

**Descrição:**
`diagnostico.setdefault("_erros", []).append(...)` é adicionado ao
diagnóstico **após** `_finalizar_auditoria_pdf` (que é onde o diagnóstico
é persistido com HMAC). Se o diagnóstico é persistido antes do bloco de
append rodar, o `_erros` NÃO entra no registro definitivo. O dossiê
posterior (`GET /auditoria/prova/cnpj/...`) devolve PDFs cifrados + hashes,
mas `_erros` se perdeu — só existiu na sessão HTTP que já morreu.

**Impacto:** fiscalização posterior não consegue rastrear que houve falha
de parser no momento do cálculo, mesmo que o frontend tenha visto. LGPD
Art. 37 exige registro permanente.

**Solução necessária:**
Antes do `return JSONResponse(...)` final do `/analise/pdf`, atualizar o
registro de diagnóstico em DB para incluir `_erros` no JSON persistido,
ou mover o bloco de `_erros` (e `_anomalias`) para antes da persistência
assinada com HMAC.

**Status:** ⏳ Pendente

---

### ERR-028 — `PIIResponse.cnpj` sem guarda contra CPF vindo da Claude Vision
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção
**Amparo legal violado:** EC 132/2023 (separação PF/PJ no cadastro fiscal) + LGPD Art. 6 (minimização)
**Arquivo:** `PY/schemas/responses.py:35-40`
**Descoberto em:** Auditoria Fase 2 — Luiz Moreira

**Descrição:**
Extrator Claude Vision pode retornar CNPJ do destinatário em operação B2B
onde o tomador é PF — a Claude confunde e pode trazer CPF (11 dígitos) no
campo CNPJ. Aí o `min_length=14` do `PIIResponse.cnpj` estoura no response,
o usuário recebe HTTP 500 e o diagnóstico válido se perde.

**Impacto:** cálculo fiscal correto mas descartado por erro de schema
cosmético. Experiência de produção degrada quando PDFs mistos chegam.

**Solução necessária:**
Manter `min_length=14 / max_length=14` para `fornecedora.cnpj`
(fiscalmente correto), mas acrescentar `@field_validator` que rejeite
padrões típicos de CPF (11 dígitos) com mensagem explícita:
"emitente deve ter CNPJ — CPF detectado, verifique o PDF (CPFs não
emitem NF-e/CT-e em operação B2B)".

**Status:** ⏳ Pendente

---

## HISTÓRICO DE AUDITORIAS REAIS

| Data | Empresa | CNPJ | Período | DAS e-CAC | DAS Motor | Delta | Status |
|------|---------|------|---------|-----------|-----------|-------|--------|
| 27/03/2026 | REFRIGERACAO CANAVEZI LTDA | 54.657.895/0001-60 | 01/2026 | R$ 16.428,83 | R$ 13.921,28 | R$ 2.507,55 | ⚠️ Delta por ERR-007 (RBT12/12 ≠ RPA real) |
| 27/03/2026 | ITANGUA SOLDAS LTDA | 05.530.872/0001-85 | 01/2026 | R$ 25.567,20 | R$ 25.492,84† | R$ 74,36 | ✅ Aprovado com RPA real |
| 27/03/2026 | CONFI-AR CONDICIONADO LTDA | 08.172.834/0001-96 | 01/2026 | R$ 15.200,39 | R$ 15.185,94‡ | R$ 14,45 | ✅ Aprovado (cálculo multi-atividade manual) |

*CANAVEZI: motor usa RBT12/12=R$150.126 vs RPA real=R$173.774 — delta = ERR-007.
†ITANGUA: calculado com RPA real R$245.531,86 × AE 10,3827%. Delta R$74,36 = causa desconhecida (<0,3%).
‡CONFI-AR: cálculo manual multi-atividade (4 atividades: Anexo I + Anexo III + ST + ISS retido). Motor atual gera delta R$2.784 sem multi-atividade (ERR-008).

---

## PRÓXIMAS AUDITORIAS PENDENTES

| Empresa | Arquivos | Status |
|---------|----------|--------|
| CONFI-AR | `samples/doc_calculo/CONFI_AR/` | ✅ Delta R$14,45 com cálculo manual multi-atividade — APROVADO (ERR-008 identificado, aguarda impl.) |
| ITANGUA  | `samples/doc_calculo/ITANGUA/`  | ✅ Delta R$74,36 com RPA real — APROVADO (ERR-007 documentado) |

---

*Documento criado: 27/03/2026 | Motor Tributário Conect 2026-2033*
