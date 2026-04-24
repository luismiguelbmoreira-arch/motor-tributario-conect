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

### ERR-018 — IDOR horizontal em endpoints que aceitam CNPJ (análise + integrações)
> **Nota de renumeração (23/04/2026):** originalmente registrado como ERR-013,
> em colisão com o ERR-013 de "Data de Início de Atividade" (já corrigido em
> 03/04/2026). Renumerado para ERR-018 para preservar rastreabilidade.
>
> **Nota de desmembramento (Fase 4 — 23/04/2026):** o ERR-018 original tratava
> de um único endpoint (`/integracoes/ecac/sync`). Durante a Fase 4
> Segurança/LGPD, um vetor IDOR **análogo** foi identificado e corrigido em
> `/analise/sessao` (hidratação do resultado a partir do buffer in-memory).
> Para manter a rastreabilidade separada por superfície de ataque, o item
> foi desmembrado em **ERR-018.a** (`/analise/sessao` — ✅ corrigido na Fase 4)
> e **ERR-018.b** (`/integracoes/ecac/sync` — ⏳ pendente para Fase 5).
> O cabeçalho original abaixo permanece intacto como contexto histórico.

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

**Status:** 🔀 Desmembrado — ver ERR-018.a (corrigido Fase 4) e ERR-018.b (pendente Fase 5) abaixo.

---

### ERR-018.a — IDOR em `/analise/sessao/{analise_id}` (hidratação do resultado)
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico
**Amparo legal violado:** LGPD Art. 46 (segurança) + Art. 6º V (minimização) + CTN Art. 198 (sigilo fiscal)
**Arquivo:** `PY/services/analise_buffer.py::AnaliseBuffer.recuperar()` + `PY/main.py::obter_analise_sessao()`
**Descoberto em:** Derivação do ERR-018 durante a implementação da Fase 4 Segurança/LGPD

**Descrição:**
O endpoint `GET /analise/sessao/{analise_id}` devolve o envelope
`{diagnostico, pii}` de uma análise ativa. Sem ownership server-side, qualquer
usuário autenticado que obtivesse um `analise_id` (por reuso do mesmo browser,
log compartilhado, vazamento via referer, etc.) leria o diagnóstico +
`pii.cnpj` + `pii.razao_social` de análise de **outro operador**. Vetor IDOR
horizontal equivalente ao ERR-018 original, porém no pipeline de análise
(não nas integrações externas).

**Evidência:** antes da Fase 4, o buffer só validava existência/TTL do id;
não comparava `user_id` do JWT com `user_id` dono do envelope.

**Solução aplicada (Fase 4 — 22/04/2026, commit `67fcb01`):**
1. `AnaliseBuffer` reescrito com `user_id` obrigatório em `armazenar()` e
   `recuperar()`; envelope gravado em `_EntradaBuffer` junto do dono.
2. `recuperar()` devolve `None` silenciosamente quando `user_id != dono` —
   mesmo comportamento de id inexistente, para não vazar a existência do
   registro (IDOR-safe).
3. Handler `obter_analise_sessao` extrai `user_id` via `_extrair_user_id` e
   chama `get_buffer().recuperar(analise_id, user_id)` — resposta é `404`
   tanto para id inexistente quanto para ownership falha.
4. Cobertura em `test_analise_buffer.py` (unit + integração).

**Status:** ✅ Corrigido na Fase 4 Segurança/LGPD.

---

### ERR-018.b — IDOR em `/integracoes/ecac/sync` (CNPJ do Form não cross-check)
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico
**Amparo legal violado:** CTN Art. 198 (sigilo fiscal) + LGPD Art. 48 (incidente reportável à ANPD)
**Arquivo:** `PY/api/routers/integracoes.py` — `ecac_sync_a1()` + demais endpoints com CNPJ em `Form/Query` (sieg_sincronizar, integra_sincronizar, dossiê de prova)
**Descoberto em:** Review do Viciado + Parecer Luiz Moreira na Fase 1 do plano Front/Backend

**Descrição:** idêntica ao cabeçalho do ERR-018 original acima. Qualquer
usuário autenticado submete o CNPJ de outro cliente do escritório e extrai
dados via certificado A1/Gov.br. Vetor multi-tenant.

**Solução necessária (Fase 5 — Ownership Guards):**
1. Criar relação `user_empresas` (ou reaproveitar `auditoria_documentos.uploaded_by_user_id`).
2. Helper `tem_acesso_cnpj(user_id, cnpj) -> bool`.
3. No handler de cada endpoint: `if not tem_acesso_cnpj(...): raise HTTPException(403)`.
4. Persistir tentativa em `AuditoriaTentativaAcessoDB` (infraestrutura já
   criada na Fase 4.1, ver helper `registrar_tentativa_acesso`) — só falta
   o wiring no handler quando o guard de CNPJ for implementado.
5. Aplicar o mesmo padrão em `sieg_sincronizar`, `integra_sincronizar`,
   `/auditoria/prova/cnpj/{...}` (já exige CNPJ mas valida só autenticação).

**PRAZO:** antes de qualquer deploy multi-tenant. Não pode entrar em produção
compartilhada sem isso.

**Status:** ⏳ Pendente — Fase 5. A tabela de auditoria da tentativa já está
disponível (Fase 4.1), resta o guard de ownership propriamente dito.

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

### ERR-029 — Smart flow `finishAnalysis` descartava payload real e mostrava HTML fake
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico
**Arquivo:** `UI/analise_unificada.html` — `submitFiles()` + `finishAnalysis()`
**Descoberto em:** Auditoria Fase 3 — durante mapeamento do fluxo manual

**Descrição:**
O handler de upload PDF (`submitFiles`) fazia `mcFetch('/analise/pdf')`, recebia o envelope `{diagnostico, pii}` real do backend e passava para `finishAnalysis(payload.diagnostico || payload)`. A função `finishAnalysis()` ignorava o parâmetro e renderizava HTML estático com números Lorem Ipsum (R$ 42.900, 12.42%, 9.85%). O contador via sempre o mesmo resultado independente do PDF — regressão grave de confiança.

**Evidência:** `finishAnalysis()` sem parâmetro nomeado, `content.innerHTML = '...texto fixo...'`. Nenhuma chamada a `sessionStorage.setItem('diagnostico', ...)` no arquivo inteiro.

**Solução aplicada (Fase 3):** `submitFiles` agora persiste `sessionStorage.setItem('diagnostico', JSON.stringify(payload.diagnostico))` e redireciona para `resultado.html`, padrão unificado com o novo `submitManual`. Função `finishAnalysis` legada removida do fluxo pós-upload.

**Status:** ✅ Corrigido na Fase 3 — Modo Manual de Verdade

---

### ERR-030 — Redirect quebrado em resultado.html: `analise.html` não existe
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção
**Arquivo:** `UI/resultado.html` — linhas 711, 719, 1674
**Descoberto em:** Auditoria Fase 3

**Descrição:**
Três pontos de fallback em `resultado.html` redirecionavam para `analise.html` (sem token, sem diagnóstico, ou JSON corrompido). Arquivo `analise.html` não existe — foi renomeado para `analise_unificada.html` em refactor anterior. Usuário em estado degradado caía em 404 do static files.

**Solução aplicada (Fase 3):** `replace_all` global trocando `analise.html` → `analise_unificada.html` nos 3 pontos.

**Status:** ✅ Corrigido na Fase 3 — Modo Manual de Verdade

---

### ERR-031 — Handler `/analise/manual` quebrava com 500 ao serializar erros Pydantic
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico (reclassificado em 23/04/2026 pelo parecer Luiz Moreira Fase 3)
**Amparo legal violado:** LGPD Art. 37 (registro de operações) + CTN Art. 142 (motivação do lançamento)
**Arquivo:** `PY/main.py` — `except PydanticValidationError` no `analise_manual`
**Descoberto em:** Testes `test_analise_manual_endpoint.py` (Fase 3)

**Nota de reclassificação (Luiz Moreira, 23/04/2026):**
Severidade elevada de 🟡 para 🔴 Crítico. Motivo: o handler devolvia 500 sem
corpo estruturado quando um erro de **caminho feliz semântico** (ex.: MEI>81k,
data fora do período transicional) era levantado via `@model_validator`. Resultado
prático: **a auditoria do usuário quebra silenciosamente** — nenhum `_erros[]`
chega ao dossiê porque o diagnóstico nem chegou a ser criado. Em fiscalização,
o registro é "cliente tentou rodar análise e sistema caiu" — LGPD Art. 37 exige
log de tentativa, o 500 jogava tudo pra trace-stack sem persistência.

**Descrição:**
Quando um `@model_validator` de `OperacaoFiscal` levantava `ValueError` (ex.: `data_emissao=2025-12-31` fora do período LC 214/2025 Art. 348), o handler fazia `raise HTTPException(status_code=422, detail=exc.errors())`. Pydantic V2 inclui em `ctx.error` a exception original (`ValueError` ou `date` object) não-serializável via `json.dumps`. Resultado: o cliente recebia **500 TypeError "Object of type ValueError is not JSON serializable"** em vez de 422 claro com mensagem de erro.

**Evidência:** traceback na suite nova `test_data_emissao_fora_periodo_transicional_retorna_422`.

**Solução aplicada (Fase 3):** sanitizar erros via `jsonable_encoder(exc.errors(include_url=False, include_input=False))` antes de montar o `HTTPException.detail`. Ruído (URLs de docs Pydantic + input_value potencialmente PII) eliminado.

**Status:** ✅ Corrigido na Fase 3 — Modo Manual de Verdade

---

### ERR-032 — `dataset.tocado` perdido no re-render do form manual após 422
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção
**Arquivo:** `UI/analise_unificada.html` — `renderInputForm` + listener global `input` capture
**Descoberto em:** Auditoria Viciado pós-Fase 3

**Descrição:**
O listener global em capture marcava `dataset.tocado='1'` em `m-tipo-comprador` e
`m-percentual-b2b` quando o usuário mexia nesses campos — flag usada pelo
`onCnaeBlur` para não sobrescrever escolha explícita. Problema: quando
`submitManual` pegava 422 do backend, `goToPhase(2)` reinjetava o form via
`container.innerHTML`, descartando todos os nós antigos (e o `dataset.tocado`
junto). Usuário retentava o submit, CNAE autofill sobrescrevia silenciosamente
campos que ele havia ajustado antes. Efeito "o sistema me ignora".

**Amparo:** não há lei específica, mas viola MAX_FISCAL_02 indiretamente
(operador perde controle sobre decisões com base legal — auto-preencher
indicação B2B/Anexo sem respeitar override manual).

**Evidência:** listener em `analise_unificada.html:575-580` tocando em nós que
viram fantasmas após `container.innerHTML = renderFormularioManual()` em `:270`.

**Solução aplicada (Fase 3.1):**
- Objeto `manualFormState = { tocado: Set, valores: {} }` em escopo de módulo
- Listener captura valor + "tocado" a cada input/change e persiste em memória
- `bindFormularioManual()` restaura valores e reaplica `dataset.tocado` no
  render após re-inject, ANTES dos handlers condicionais (`onRegimeChange`,
  `onTipoCompradorChange`) para não sobrepor seleção já feita.
- Listener passou a filtrar por prefixo `m-` (evita contaminar outros forms).

**Status:** ✅ Corrigido na Fase 3.1

---

### ERR-033 — `lista.innerHTML = erros.map(...)` com template literal — XSS latente
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção
**Amparo legal:** LGPD Art. 46 (segurança da informação) + OWASP A03:2021 (Injection)
**Arquivo:** `UI/analise_unificada.html` — `submitManual()` linha 710 (antes do fix)
**Descoberto em:** Auditoria Viciado pós-Fase 3

**Descrição:**
`lista.innerHTML = erros.map(e => '<li>${e}</li>').join('')`. Hoje as mensagens
do array são hardcoded (strings fixas dos validators). **Risco imediato: zero.**
Mas é armadilha latente: qualquer refactor futuro que interpole input do usuário
(ex.: `'CNPJ ${cnpjRaw} inválido'`) vira XSS refletido — payload
`<img src=x onerror=fetch('/exfil?t='+sessionStorage.token)>` no campo CNPJ
exfiltra JWT.

**Solução aplicada (Fase 3.1):**
DOM builder puro — `document.createElement('li')` + `textContent = mensagem`
+ `appendChild`. `textContent` é imune a injeção por definição. Mesmo padrão
já usado em `components.js::mcToast` (consistência).

**Status:** ✅ Corrigido na Fase 3.1

---

### ERR-034 — `test_decimal_serializado_como_string_no_envelope` era falso-positivo-tolerante
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção
**Amparo:** MAX_FISCAL_01 — Decimal end-to-end
**Arquivo:** `PY/tests/test_analise_manual_endpoint.py` — linhas 226-228 (antes do fix)
**Descoberto em:** Auditoria Viciado pós-Fase 3

**Descrição:**
Loop `for chave in ("das_calculado", "das_mensal", "rbt12"): if chave in diag ...`
passava mesmo se NENHUMA das 3 chaves existisse. Se o motor amanhã renomear
(ex.: `das_calculado` → `das_apurado`), teste continua verde enquanto o contrato
Decimal-como-string está quebrado.

**Solução aplicada (Fase 3.1):**
1. Walk recursivo `_walk_sem_float(obj)` varre TODO o envelope e falha se
   encontrar QUALQUER `float` — drift silencioso impossível.
2. Busca recursiva por chaves monetárias canônicas (ampliada: `das_calculado`,
   `das_mensal`, `das_total`, `aliquota_efetiva`, `valor_devido`, `rbt12`) e
   asserta que ao menos UMA foi encontrada (falso-positivo fechado).
3. Caminho completo relatado no assertion error para debug rápido
   (`"$.empresa.rbt12 = 1234.56 deveria ser string..."`).

**Status:** ✅ Corrigido na Fase 3.1

---

### ERR-035 — Template HTML do formulário manual em string JS (~130 linhas inline)
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção (manutenibilidade)
**Arquivo:** `UI/analise_unificada.html` — `renderFormularioManual()` linhas ~281-490
**Descoberto em:** Auditoria Viciado pós-Fase 3

**Descrição:**
O HTML do formulário está colado em template string dentro de JS. Sem lint
de HTML, sem highlight adequado, cada campo novo exige edição em 2 pontos
(Pydantic `AnaliseManualRequest` + template string). Quando adicionarmos
Lucro Real completo, DIFAL interestadual, regime_comprador (Luiz pode pedir),
etc., a manutenção fica cara e propensa a erro.

**Solução necessária (roadmap — não P0):**
Extrair para `UI/templates/formulario_manual.html`, carregar via fetch sob
demanda na primeira entrada da Fase 2 (modo manual). Permite lint/validação
HTML e revisão de markup fora do noise do JS.

**Status:** ⏳ Pendente — próxima fase de UI (baixa prioridade).

---

### ERR-036 — `beneficio_fiscal_antigo` é campo DECORATIVO — viola MAX_FISCAL_01 e MAX_FISCAL_02
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico
**Amparo legal:** ADCT Art. 92-A §§ 3º e 4º (EC 132/2023) + LC 214/2025 Arts. 384-388 (Fundo de Compensação de Benefícios Fiscais)
**Arquivo:** `PY/core/motor_tributario.py:1204-1213` + `UI/analise_unificada.html` (label do campo)
**Descoberto em:** Auditoria Luiz Moreira pós-Fase 3

**Descrição:**
O frontend aceita valor monetário para `beneficio_fiscal_antigo`, a label diz
"Isenção/benefício eliminado até 2032", e o usuário preenche esperando que o
motor modele o cronograma de phase-out (20% ao ano a partir de 2029, ADCT
Art. 92-A §3º). **Mas o valor nunca entra em cálculo.** Só dispara um alerta
textual:

```python
if self.operacao.beneficio_fiscal_antigo > Decimal("0"):
    alertas.append({..., "codigo": "BENEFICIO_FISCAL_EXTINCAO",
        "mensagem": f"... será eliminado gradualmente até 2032 (LC 214/2025, Art. X)..."})
```

Duas violações graves:
1. **MAX_FISCAL_01** — campo aceita "dedução" que o motor ignora. Base → Deduções → Alíquota → Valor quebrado: o usuário vê a dedução na entrada, zero dedução no cálculo.
2. **MAX_FISCAL_02** — `Art. X` literal dentro da string de alerta. Base legal real é **LC 214/2025 Arts. 384-388 + ADCT Art. 92-A §§ 3º e 4º**. Placeholder sem amparo.

**Impacto em fiscalização:** em cenário real onde o contador apresenta o parecer
do motor como justificativa de recolhimento, a Receita pergunta "qual o valor do
benefício fiscal antigo considerado no cálculo?" — resposta honesta: "zero, o
campo é decorativo". Alegação de cálculo enganoso (Lei 8.137/1990 Art. 1º II) à
vista.

**Solução necessária (Fase 3.2 — sanitização fiscal):**
Opção A (implementar phase-out):
1. Modelar cronograma ADCT 92-A §3º (redução 20% ao ano a partir de 2029)
2. Aplicar fator de redução sobre `beneficio_fiscal_antigo` conforme ano de `data_emissao`
3. Subtrair do DAS/IVA calculado, registrar em `trilha_auditoria` com amparo
4. Citar `LC 214/2025 Arts. 384-388 + ADCT Art. 92-A §3º` (substituir `Art. X`)

Opção B (remover do escopo):
1. Remover o campo de `AnaliseManualRequest` e da UI
2. Deixar claro no disclaimer que o motor não modela benefícios fiscais extintos
3. Apontar para consultoria especializada

**Status:** ✅ Corrigido — Fase 3.2 (23/04/2026)

**Resolução:** Opção B (remoção).
- Campo `beneficio_fiscal_antigo` removido de `PY/schemas/motor.py::OperacaoFiscal`, de `PY/main.py::AnaliseManualRequest`, dos samples JSON e do demo `planejamento_tributario.py`.
- Alerta `BENEFICIO_FISCAL_EXTINCAO` removido de `PY/core/motor_tributario.py` (bloco ~1203 na versão anterior).
- Input e script da UI (`UI/analise_unificada.html`) também removidos.
- Pydantic `extra="forbid"` agora retorna 422 se o campo for enviado (regressão blindada em `tests/test_fase32_sanitizacao.py::TestErr036BeneficioFiscalRemovido`).
- Implementação do phase-out real (ADCT Art. 92-A §3º — redução 20%/ano a partir de 2029) adiada para fase posterior, quando for possível modelar com tabela FROZEN por ano + validação fiscal específica do Luiz Moreira.

---

### ERR-037 — `regime_comprador` é campo ZUMBI no Pydantic
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico
**Amparo legal:** LC 214/2025 Art. 47 §2º (crédito por regime do adquirente)
**Arquivo:** `UI/analise_unificada.html:741` (hardcoded "NAO_INFORMADO") + `PY/main.py:642` + `PY/schemas/motor.py::EmpresaCompradora`
**Descoberto em:** Auditoria Luiz Moreira pós-Fase 3

**Descrição:**
Frontend envia `regime_comprador: "NAO_INFORMADO"` fixo. Backend aceita como
string livre (`regime_comprador: str`), passa para `EmpresaCompradora.regime`,
e **o motor nunca ramifica por esse campo** (`grep self.compradora.regime` em
`PY/core/` → zero hits de lógica de cálculo).

**Impacto fiscal:** **LC 214/2025 Art. 47 §2º** diferencia tratamento de crédito
IBS/CBS conforme regime do adquirente:
- Adquirente **Simples Nacional** → não apropria crédito
- Adquirente **Lucro Real** → apropria integral
- Adquirente **Lucro Presumido** → apropria parcial conforme hipótese

Com "NAO_INFORMADO" fixo, o motor assume um caminho único. **Isso não é
conservador — é omisso.** "NAO_INFORMADO" não tem assento em lei.

**Solução necessária (Fase 3.2):**
Opção A (expor na UI):
1. Dropdown `regime_comprador` no bloco "Perfil do Comprador" com opções
   SIMPLES | PRESUMIDO | REAL | MEI | NAO_INFORMADO
2. Implementar lógica de crédito no motor conforme LC 214/2025 Art. 47 §2º
3. Registrar em trilha_auditoria com amparo

Opção B (explicitar pior caso):
1. Manter "NAO_INFORMADO" no schema mas documentar que implica "sem crédito"
   no cálculo (Art. 47 §2º aplicado de forma conservadora)
2. Registrar na trilha: "regime_comprador não informado → assumido pior caso
   (sem crédito) para proteção do emitente"

**Status:** ✅ Corrigido parcialmente — Fase 3.2 (23/04/2026)

**Resolução:** Opção A parcial (exposição sem lógica de cálculo).
- `EmpresaCompradora.regime` virou `Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI", "NAO_INFORMADO"]` (fim da string livre).
- `AnaliseManualRequest.regime_comprador` segue o mesmo Literal.
- Frontend (`UI/analise_unificada.html`) ganhou dropdown real no bloco "Perfil do Comprador" — fim do valor fixo `"NAO_INFORMADO"` no payload.
- Motor registra o valor na `trilha_auditoria` em passo novo `REGIME_COMPRADOR_CAPTURADO` com amparo `LC 214/2025 Art. 47 §2º`. Quando `NAO_INFORMADO`, o passo avisa explicitamente que o motor assume PIOR CASO (sem crédito cruzado).
- **Lógica de ramificação de crédito por regime do adquirente (Art. 47 §2º completo: Simples=zero, Real=integral, Presumido=parcial) fica para Fase 4+** — escopo desta Fase 3.2 era alinhar superfície, não introduzir feature nova. O dado já chega ao motor e fica disponível para quando a Fase 4 for aberta.
- Regressão blindada em `tests/test_fase32_sanitizacao.py::TestErr037RegimeCompradorLiteral`.

---

### ERR-038 — `forma_recebimento` não distingue PIX-via-PSP de PIX-direto (Split Payment)
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção (vira 🔴 em Ago/2026 com Ato CGIS)
**Amparo legal:** LC 214/2025 Art. 353 caput + §§ 1º-3º + Art. 360 (regulamentação pendente)
**Arquivo:** `PY/core/motor_tributario.py:911` + `PY/schemas/motor.py::OperacaoFiscal::forma_recebimento`
**Descoberto em:** Auditoria Luiz Moreira pós-Fase 3

**Descrição:**
Motor classifica binariamente: eletrônico (`PIX_BOLETO`, `CARTAO`) vs `DINHEIRO`.
Dispara Split Payment em todos os eletrônicos quando `ano >= 2027`. Mas
LC 214/2025 Art. 353 caput prevê split apenas para "prestadores de serviços de
pagamento" (PSPs — Mercado Pago, PagSeguro, Nubank PJ, etc.). PIX **direto
banco-a-banco sem PSP** (conta-corrente empresarial) **não dispara split** até
regulamentação específica.

**Hoje o motor acerta por cima:** `PIX_BOLETO` dispara split em 2027+
independentemente de ter PSP. Em cenário de PIX puro banco-a-banco, motor
**superestima retenção** — o tomador vai reter mais do que devia.

**Severidade:** 🟡 hoje porque Ato CGIS do Art. 360 ainda está pendente
(prazo estimado Ago/2026). Após regulamentação, operadores vão poder provar
ausência de PSP e motor virará passivo concreto — escala para 🔴.

**Solução necessária (Fase 4 ou antes de Ago/2026):**
1. Granular `forma_recebimento`: `DINHEIRO | PIX_DIRETO | PIX_VIA_PSP | BOLETO | CARTAO`
2. Split só quando forma in {PIX_VIA_PSP, BOLETO_VIA_PSP, CARTAO} E ano >= 2027
3. Registrar em trilha com amparo Art. 353 §1º e Ato CGIS (quando publicado)

**Status:** ✅ Corrigido — Fase 3.2 (23/04/2026) — reclassificado para 🔴 por Luiz Moreira

**Resolução:** granularização completa.
- `OperacaoFiscal.forma_recebimento` (e `AnaliseManualRequest.forma_recebimento`) migraram para o Literal `["DINHEIRO", "PIX_DIRETO", "PIX_VIA_PSP", "BOLETO", "CARTAO"]`. O valor legado `PIX_BOLETO` não é mais aceito (422).
- Constante FROZEN `FORMAS_PAGAMENTO_COM_PSP = frozenset({"PIX_VIA_PSP", "BOLETO", "CARTAO"})` em `PY/schemas/motor.py`.
- `motor_tributario.split_payment_impacto` agora dispara retenção **só** quando `ano >= ANO_INICIO_SPLIT_PAYMENT` **e** `forma in FORMAS_PAGAMENTO_COM_PSP`. `PIX_DIRETO` e `DINHEIRO` escapam.
- Trilha: o passo `SPLIT_PAYMENT` cita `LC 214/2025, Art. 344 + Art. 353 §1º` no campo `lei`, com detalhe identificando que a forma passa por PSP. Quando inativo, o `motivo` é granular: separa "ano anterior ao início", "dinheiro" e "PIX direto banco-a-banco".
- Retorno de `split_payment_impacto` ganhou `intermediado_por_psp: bool` (independente de ativo/inativo).
- Frontend expandiu o `<select>` com as 5 opções.
- Testes existentes (test_fase2_simples, test_fase3_iva, test_fase4_optout, test_motor_gaps) migraram de `PIX_BOLETO` para `PIX_VIA_PSP` — intenção semântica preservada.
- Regressão blindada em `tests/test_fase32_sanitizacao.py::TestErr038FormaRecebimentoPSP`.

---

### ERR-039 — `reducao_cbs_ibs` não cobre regime monofásico (combustíveis, cigarros, bebidas)
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção
**Amparo legal:** LC 214/2025 Arts. 172-174 (regime monofásico) + Art. 149 §2º III CF/88 (redação EC 132/2023)
**Arquivo:** `PY/main.py:283` (Literal do campo) + `PY/core/motor_tributario.py:581-608` + `PY/schemas/motor.py::OperacaoFiscal`
**Descoberto em:** Auditoria Luiz Moreira pós-Fase 3

**Descrição:**
O Literal atual é fechado em 4 opções: INTEGRAL, REDUCAO_30, REDUCAO_60, ISENTO.
Cobre Arts. 258 (60%), 262 (30%), 264 (100%).

**Não cobre regime monofásico** (Arts. 172-174 LC 214/2025 — combustíveis
NCM 2710.xx, tabacos NCM 2402-2403, bebidas alcoólicas NCM 2203-2208, ativos
financeiros). Monofásico é **regime próprio**: alíquota uniforme cobrada uma
única vez no fornecedor/importador, não se encaixa em "INTEGRAL nem REDUCAO_X
nem ISENTO".

**Impacto em produção:** usuário de posto de combustível, distribuidora de
bebidas ou tabacaria usa o formulário manual, escolhe "INTEGRAL" (única opção
que parece fazer sentido) e recebe cálculo **radicalmente errado** — o motor
aplica CBS/IBS cumulativo quando deveria ser monofásico no distribuidor.

**Solução necessária (Fase 3.2):**
1. Bloqueio preventivo: se `ncm_nbs` iniciar com NCMs monofásicas (prefixos
   2710, 2402, 2403, 2203, 2204, 2205, 2206, 2207, 2208), levantar erro
   explícito: "Regime monofásico — consulte regra específica LC 214/2025
   Arts. 172-174. Este formulário não modela cálculo monofásico."
2. Disclaimer no topo do formulário manual esclarecendo o escopo (Simples +
   Presumido + Real + MEI, **exceto monofásicos**).
3. Roadmap: implementar engine `regimes/monofasico.py` seguindo padrão dos
   demais regimes com Guard Clause.

**Status:** ✅ Corrigido — Fase 3.2 (23/04/2026)

**Resolução:** bloqueio preventivo no Pydantic.
- Constante FROZEN `NCMS_MONOFASICAS_BLOQUEADAS: frozenset[str]` em `PY/schemas/motor.py` cobrindo prefixos de capítulo `2710`, `2402`, `2403`, `2203`, `2204`, `2205`, `2206`, `2207`, `2208` — cada entrada com comentário de amparo (LC 214/2025 Art. 172 I/II/III).
- `OperacaoFiscal.validar_campo_ncm` agora compara `limpo[:4]` contra o frozenset e levanta `ValueError` com mensagem citando **LC 214/2025 Arts. 172-174**. Retorna 422 antes de qualquer cálculo — não entra na trilha porque é erro de entrada.
- Frontend (`UI/analise_unificada.html`) recebeu disclaimer no bloco "Operação Fiscal (NF-e)" listando os capítulos rejeitados.
- Engine monofásica (`regimes/monofasico.py`) segue roadmap de fase posterior.
- Regressão blindada em `tests/test_fase32_sanitizacao.py::TestErr039NcmMonofasicoBloqueado` (parametrizado em todos os 9 prefixos).

---

### ERR-040 — BOLETO em `FORMAS_PAGAMENTO_COM_PSP` não distingue registrado vs carteira simples
**Data:** 23/04/2026
**Severidade:** 🟢 Baixa (resíduo operacional — Circular Bacen 3.598/2012 tornou registro quase universal)
**Amparo legal:** LC 214/2025 Art. 353 §1º + Circular Bacen 3.598/2012 (obrigatoriedade de registro de boletos)
**Arquivo:** `PY/schemas/motor.py::FORMAS_PAGAMENTO_COM_PSP`
**Descoberto em:** Auditoria Luiz Moreira pós-Fase 3.2

**Descrição:**
A constante FROZEN `FORMAS_PAGAMENTO_COM_PSP = frozenset({"PIX_VIA_PSP", "BOLETO", "CARTAO"})` hoje agrupa **todo boleto** como tendo PSP — dispara Split Payment a partir de 2027 sem exceção. Boleto de **carteira simples** (sem registro no banco, emitido diretamente pelo sacador) **não tem PSP no caminho** e, em leitura estrita do LC 214/2025 Art. 353 §1º, não deveria disparar retenção automática.

**Impacto hoje:** baixíssimo. Circular Bacen 3.598/2012 tornou o registro de boletos **praticamente obrigatório** desde 2018 — Febraban reporta adoção > 99% no mercado. Boleto carteira simples é resquício operacional (pequenas cooperativas, sistemas legados). **Falha fechada = conservador = correto para o cliente** (retenção a mais retorna na apuração, retenção a menos vira passivo).

**Quando vira relevante:** caso algum cliente real do escritório em 2027+ emita boleto carteira simples e o dossiê apresente retenção que o banco não aplicou, vira divergência de conciliação. Luiz sinaliza que é cenário **possível mas raro**.

**Solução necessária (roadmap Fase 4+):**
1. Granular o Literal de `forma_recebimento`: separar `BOLETO_REGISTRADO` (dispara Split) de `BOLETO_CARTEIRA` (não dispara).
2. Ajustar `FORMAS_PAGAMENTO_COM_PSP` excluindo `BOLETO_CARTEIRA`.
3. UI oferecer os 2 tipos de boleto no select.

**Status:** ⏳ Pendente — baixa prioridade (sem frequência estatística relevante antes de 2027).

---

### ERR-041 — PII do cliente persistia em sessionStorage entre páginas
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico — LGPD Art. 6º V (minimização), Art. 46 (segurança), Art. 48 (incidente)
**Arquivo:** `UI/analise_unificada.html`, `UI/resultado.html`
**Descoberto em:** Auditoria de Segurança Fase 4 (Viciado)
**Descrição:** `submitManual` e `submitFiles` gravavam `analise_empresa` (razão social) e `analise_cnpj` em sessionStorage — disponível para qualquer script da mesma origem, violando minimização. `resultado.html` lia direto de sessionStorage.
**Evidência:** `UI/analise_unificada.html:872-875,926-929` com `sessionStorage.setItem('analise_cnpj', ...)`. `UI/resultado.html:709,778,790,1163,1683,1702-1703` com `sessionStorage.getItem('diagnostico'|'analise_empresa'|'analise_cnpj')`.
**Solução implementada (Fase 4):**
1. Novo `PY/services/analise_buffer.py` — buffer in-memory com TTL 10min, ownership por user_id (IDOR-safe), id opaco hex 32 chars via `secrets.token_hex`.
2. Novo `GET /analise/sessao/{analise_id}` em `PY/main.py` — devolve 404 em id inexistente, expirado ou de outro user (não vaza existência).
3. `/analise/manual` e `/analise/pdf` retornam `analise_id` no envelope (além de `diagnostico` e `pii`).
4. Frontend (`components.js`, `analise_unificada.html`, `resultado.html`) guarda só `analise_id` em sessionStorage; PII vive em `window.__MC_SESSION__` (memória).
5. Helpers `mcSessionSet/Get/Clear` centralizam o acesso — impede regressão.
6. `resultado.html` hidrata via `GET /analise/sessao/{id}` no DOMContentLoaded.
**Status:** ✅ Corrigido (933 testes verdes — +17 buffer + endpoint + 6 refresh).

---

### ERR-042 — JWT expirava silenciosamente; operador era deslogado no meio de análise
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico — UX + LGPD Art. 46 (segurança de sessão)
**Arquivo:** `UI/components.js`
**Descoberto em:** Auditoria de Segurança Fase 4 (Viciado)
**Descrição:** JWT expirava em 8h sem mecanismo de refresh antes do prazo. Operador em análise longa era deslogado no próximo clique — perda de trabalho, risco de digitar PII no login errado, possível tentação de armazenar senha em local inseguro.
**Evidência:** Ausência de chamada a `/auth/refresh` em qualquer página. `renovar_token_jwt` existia mas nunca era disparado pelo frontend.
**Solução implementada (Fase 4):**
1. `components.js::setupJwtRefreshLoop()` — `setInterval` 60s + `visibilitychange` listener (para aba inativa throttled).
2. `mcCheckAndRefreshToken()` decodifica `exp` do JWT client-side; se restam <5min chama `POST /auth/refresh`.
3. Atualiza `sessionStorage.token` quando `renewed=true`.
4. `mcLogoutLimpar()` faz `clearInterval` do timer — sem leak em logout.
5. Novo `PY/tests/test_auth_refresh.py` — 6 testes: token recente (não renova), token <2h (renova), token inválido (401), token expirado (401), sem Authorization (≠304), schema do response.
**Status:** ✅ Corrigido.

---

### ERR-043 — Logs do frontend vazavam objetos de erro crus
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção — LGPD Art. 37 (registro)
**Arquivo:** `UI/dashboard.html`
**Descoberto em:** Auditoria de Segurança Fase 4 (Viciado)
**Descrição:** `dashboard.html:214,280` fazia `console.error("Falha ao carregar dashboard:", res?.status)` e `console.error("Falha ao carregar dashboard:", err)`. Em produção, `err` cru pode conter URL + headers (potencial token JWT) + payload com PII.
**Evidência:** Grep `console\.(error|log|warn)\s*\(` encontrou 4 logs com variáveis cruas em `UI/**`.
**Solução implementada:** Padronização em `motor-conect: <descrição neutra> — ver suporte`, sem emissão de `err`/`res` crus.
**Status:** ✅ Corrigido — todos os `console.error` agora seguem padrão neutro.

---

### ERR-044 — Alerts técnicos em resultado.html com copy não-humano
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção — UX + profissionalização
**Arquivo:** `UI/resultado.html`
**Descoberto em:** Auditoria de Segurança Fase 4 (Viciado)
**Descrição:** 5 ocorrências de `alert(...)` em `baixarDossieProva` e `downloadPDF` — UX inferior + impossibilidade de styling + trava thread do browser. Copy com "HTTP" e "Falha" cru.
**Evidência:** Grep `alert\s*\(` encontrou `UI/resultado.html:1166,1179,1198,1214,1730`.
**Solução implementada:** Migração pra `mcToast(msg, type)` com copy amigável.
**Status:** ✅ Corrigido — zero `alert()` em `UI/**`.

---

### ERR-045 — `_fracao_iva_no_das` usa phase-in 10%/ano enquanto `CRONOGRAMA_IVA` usa 20%/ano
**Data:** 23/04/2026
**Severidade:** 🔴 Critico
**Status:** ✅ **CORRIGIDO — commit 4caf82c (23/04/2026)**
**Arquivo:** `PY/core/motor_tributario.py` — `_fracao_iva_no_das()` linha 627 | `PY/core/tabelas_simples.py` — `CRONOGRAMA_IVA` linhas 297-300
**Descoberto em:** Auditoria matematica Luiz Moreira pos-refatoracao

**Descricao:**
Dois blocos do motor modelam o mesmo fenomeno — crescimento do IBS no periodo 2029-2032 — com cronogramas inconsistentes:

- `_fracao_iva_no_das(ano)` (linha 627): `Decimal(ano - 2028) * Decimal("0.10")`
  - 2029 = 10%, 2030 = 20%, 2031 = 30%, 2032 = 40% da fracao ICMS+ISS no DAS

- `CRONOGRAMA_IVA` (tabelas_simples.py):
  - 2029: IBS 0.035 (~20% de 0.177)
  - 2030: IBS 0.071 (~40%)
  - 2031: IBS 0.106 (~60%)
  - 2032: IBS 0.142 (~80%)

**Impacto:**
`_fracao_iva_no_das` e consequentemente `credito_b2b_simples` usam 10/20/30/40%.
`split_payment_impacto` e `cenario_opt_out` usam CBS+IBS do `CRONOGRAMA_IVA` com phase-in de 20/40/60/80%.
Em 2029, o credito B2B calculado sera metade do que o motor calcula para o custo de Split Payment — inconsistencia interna detectavel por comparacao direta dos dois cenarios.

**Evidencia:**
```
Empresa Anexo I Faixa 1, DAS R$ 1.000, 2029:
- credito_b2b_simples = 1.000 * (ICMS+ISS no DAS) * 10% = credito X
- taxa_retencao split_payment = (CBS 0.088 + IBS 0.035) * fator = taxa Y
O percentual ICMS+ISS extinto em 2029 nao e 10% — e 20% conforme CRONOGRAMA_IVA
```

**Nota legal:** LC 214/2025 Art. 360 remete o cronograma exato para regulamentacao posterior (Resolucao do Senado). Nenhum dos dois percentuais e definitivamente correto — mas o motor precisa ser internamente consistente. A decisao de qual usar deve ser unica e documentada.

**Solucao adotada (commit 4caf82c):**
Alinhado a 10%/ano em ambos os blocos. `_fracao_iva_no_das` ja estava correto (`Decimal(ano-2028) * Decimal("0.10")`). `CRONOGRAMA_IVA` foi corrigido:
- 2029: IBS 0.0177 (10% de 0.177)
- 2030: IBS 0.0354 (20%)
- 2031: IBS 0.0531 (30%)
- 2032: IBS 0.0708 (40%)

**Fundamento legal:** LC 214/2025 Arts. 356-360 — ICMS/ISS reduzidos em 10% ao ano simetricamente ao crescimento do IBS. Validado via 4 fontes independentes (CRCSP, SimTax, Tax Group, Trad & Cavalcanti): *"as aliquotas de ICMS e de ISS serao reduzidas em 10% ao ano, com cobranca gradual de IBS"*.

**Impacto retroativo:** diagnosticos gerados antes de 4caf82c para anos 2029-2032 usavam IBS inflado em 2x. Versionamento do motor (`MOTOR_VERSAO`) adicionado ao JSON do diagnostico (commit pos-fissura) para permitir identificar e reprocessar diagnosticos afetados.

---

### ERR-046 — `cenario_opt_out` subtrai IBS/CBS em bases diferentes (DAS mensal vs operacao)
**Data:** 23/04/2026
**Severidade:** 🔴 Critico (reclassificado de 🟡 em 23/04/2026 na auditoria pos-fissura Luiz)
**Status:** ✅ **CORRIGIDO — Protocolo Jogada Fiscal (Fases 1-4) commit pos-65b35ea (23/04/2026)**
**Arquivo:** `PY/core/motor_tributario.py` — `cenario_opt_out()` linhas 734-737
**Descoberto em:** Auditoria matematica Luiz Moreira pos-refatoracao

**Descricao:**
A subtracao para evitar dupla contagem de IBS/CBS no cenario Opt-Out mistura duas bases de calculo diferentes:

```python
fracao_iva_no_das = (ibs_no_das + cbs_no_das)           # R$ absolutos do DAS MENSAL
custo_das_por_operacao_completo = valor_operacao * AE   # R$ da OPERACAO especifica
custo_das_sem_iva = custo_das_por_operacao_completo - fracao_iva_no_das  # BASES DIFERENTES
```

`ibs_no_das` e `cbs_no_das` sao calculados via `_calcular_fracao_componente()` que usa `das_mensal` como base (RBT12/12 ou rpa_mensal). `custo_das_por_operacao_completo` usa `valor_operacao` como base — que pode ser diferente do RPA mensal.

**Exemplo concreto:**
- RBT12 R$ 600.000, DAS mensal R$ 4.750, operacao R$ 20.000
- `custo_das_por_operacao_completo` = 20.000 x AE (base: operacao)
- `ibs_no_das` = R$ X (base: DAS mensal de R$ 4.750)
- Subtracao: custo_operacao - fracao_do_das_mensal — grandezas incompativeis

**Impacto:** a diferenca e pequena em valor absoluto (ambas sao fracao pequena dos respectivos totais), mas a base matematica e conceitualmente incorreta. O correto seria:

```python
fracao_iva_percentual = (fracao_ibs_pct + fracao_cbs_pct)  # % do DAS
custo_das_sem_iva = valor_operacao * (AE - AE * fracao_iva_percentual)
```

**Descoberta adicional na Fase 1 do Protocolo Jogada Fiscal:**
Os testes TDD reverso revelaram que o defeito era MAIS GRAVE do que o LOG original documentava. `fracao_ibs` e `fracao_cbs` usavam `DISTRIBUICAO_DAS[anexo][faixa]["IBS"|"CBS"]` — mas essas colunas estao **zeradas** em TODAS as faixas do motor (o sistema real usa `_fracao_iva_no_das` com composicao PIS+COFINS → CBS e ICMS+ISS × fase_in → IBS). Resultado: **o motor nao expurgava NADA do DAS no cenario Opt-Out** — dupla tributacao silenciosa em produçao. Nao era vies pequeno, era expurgo zerado.

**Solucao adotada (ATA Fase 1 + veto Luiz item 3):**
```python
fracao_iva_pct = self._fracao_iva_no_das(anexo, faixa, ano)     # % adimensional
fator_reducao  = self._fator_reducao_cbs_ibs()
ae_sem_iva     = ae_efetiva * (Decimal("1") - fracao_iva_pct * fator_reducao)
custo_das_sem_iva = valor_operacao * ae_sem_iva
```

Principais mudancas sobre a proposta original do LOG:
1. **Reutiliza `_fracao_iva_no_das`** em vez de criar funcao nova (DRY, fonte unica com `credito_b2b_simples`)
2. **Simetria do `fator_reducao`** aplicada nas duas pontas (veto Luiz): sem isso, `REDUCAO_60` deixaria IVA por fora a 40% mas expurgaria 100% do DAS → vies pro-opt-out. Fundamento: LC 214/2025 Arts. 258-264 aplicam isonomicamente.
3. **Amparo legal expandido**: antes citava apenas "LC 214/2025 (aguardar regulamentacao)". Agora cita 6 artigos (41-44 + 47 §II + 344 + 353 + 356-360 + 348 III 'c').
4. **Trilha `OPT_OUT_CALCULO` reescrita** com base/deducoes/aliquota coerentes (MAX_FISCAL_01 restaurado).

**Testes canario (`tests/test_err046_opt_out_base.py`):**
- **Linearidade** — dobrar valor_operacao dobra custo_das_sem_iva (invariante permanente)
- **Nao-negatividade** — operacao pequena nunca gera valor negativo
- **Boundary 2026** — fracao IVA = 0 → custo_das_sem_iva = valor × AE (Art. 348 III 'c')
- **Simetria fator_reducao** — REDUCAO_60 expurga 40%, nao 100%
- **Invariante soma** — custo_total = custo_das + iva_por_fora em qualquer combinacao

**Versionamento:** bump `MOTOR_VERSAO` 1.1.0 → 1.2.0 (MINOR — mudança de regra fiscal). Diagnosticos v1.1.0 com `valor_operacao ≠ rbt12/12` foram entregues sem expurgo de IVA no DAS — identificaveis via campo `versao_motor` no JSON.

---

### ERR-047 — Thresholds de recomendacao Opt-Out (70%/5%, 50%/10%, <30%) sem amparo legal
**Data:** 23/04/2026
**Severidade:** 🟡 Atencao
**Status:** ✅ **CORRIGIDO — fix V-12 auditoria pos-fissura (23/04/2026)**
**Arquivo:** `PY/core/recomendacoes_optout.py` — linhas 41, 68, 83 | campo `amparo_legal` linha 112-115
**Descoberto em:** Auditoria matematica Luiz Moreira pos-refatoracao

**Descricao:**
Os thresholds de conveniencia economica para recomendacao de Opt-Out (B2B >= 70% + custo <= 5% = OPT_OUT_FORTE; B2B >= 50% + custo <= 10% = OPT_OUT_VANTAJOSO; B2B < 30% = MANTER_SIMPLES) nao tem base em lei, instrucao normativa ou resolucao do CGSN.

O campo `amparo_legal` do retorno (linha 112) cita "LC 214/2025, Arts. 41-44 | Resolucao CGSN 183/2025" — esses dispositivos definem o mecanismo de opt-out e as janelas semestrais, nao os criterios de conveniencia economica.

**Risco:** o parecer entregue ao contribuinte cita base legal que nao embase os percentuais usados na tomada de decisao. Se o contribuinte contestar a recomendacao invocando a lei citada, nao encontrara os thresholds nela.

**Solucao adotada (fix V-12):**
Campo `amparo_legal` reestruturado em dois blocos explicitos:
1. "Dispositivo legal do Opt-Out: LC 214/2025 Arts. 41-44 | CF Art. 146, III, 'd' | Resolucao CGSN 183/2025 (janelas semestrais abr/set)"
2. "Criterio de conveniencia economica (thresholds 70%/50%/30% de B2B e 5%/10% de disparidade): heuristica interna do Escritorio Conect — sem amparo normativo especifico. Avaliar caso a caso."

Aprovado por Luiz Moreira: cumpre MAX_FISCAL_02 integralmente. Auditor RFB lendo o parecer distingue o que foi lei do que foi juizo do escritorio.

---

### ERR-048 — Alerta admin de IDOR cruzado (3×24h) sem dashboard ops
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção — observabilidade de incidentes
**Amparo legal:** LGPD Art. 48 (dever de comunicar incidente à ANPD em 72h)
**Arquivo:** TBD — precisa decisão sobre canal (e-mail, painel admin, webhook).
**Descoberto em:** Ressalva Luiz Fase 4.1 #3 — escopo aperto do Chefe

**Descrição:**
A Fase 4.1 persiste toda tentativa de IDOR horizontal em
`auditoria_tentativas_acesso` (helper `registrar_tentativa_acesso` +
wiring em `/analise/sessao`). Entretanto, **ninguém é avisado em tempo
real** quando um mesmo `user_id_tentando` dispara 3 ou mais tentativas
em 24h — padrão clássico de operador malicioso ou credencial
comprometida tentando varrer ids.

A regra de threshold (3×24h) é a mais adequada ao perfil multi-tenant de
escritório contábil: dedos gordos geram 1 tentativa; atacante consistente
gera 3+. A contagem vai feita com uma janela deslizante por
`user_id_tentando` olhando para `tentado_em`.

**Escopo cortado da Fase 4.1** (decisão do Chefe): apenas a persistência
das tentativas foi entregue. O alerta em tempo real fica como item de
backlog do dashboard ops.

**Solução necessária (backlog — sem deadline):**
1. Job ou trigger ao inserir linha em `auditoria_tentativas_acesso`.
2. `COUNT(user_id_tentando)` na janela `tentado_em >= now() - 24h`.
3. Se ≥ 3, notificar admins via canal escolhido (slack/email/webhook/
   painel ops). Idempotente — não spamar no 4º, 5º... dentro da mesma
   janela.
4. Tela no dashboard ops com lista de tentativas por dia + destaque
   para os que cruzaram o threshold.

**Status:** ⏳ Pendente (backlog do dashboard ops, sem deadline).

---

### ERR-049 — `current_user.get("id")` sempre None em produção (JWT usa claim "sub")
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico — ownership latente em 4 endpoints
**Amparo legal:** LGPD Art. 46 §1º (segurança) + LGPD Art. 6º V (minimização) + RFC 7519 (claim "sub" padrão JWT)
**Arquivo:**
  - `PY/api/routers/integracoes.py:70,126` — `uploaded_by_user_id=current_user.get("id")`
  - `PY/api/routers/auditoria.py:59` — dossiê de prova sem rastro do solicitante
  - `PY/main.py:1244` — handler `/analise/pdf` sem user_id na auditoria documental
**Descoberto em:** Exploração arquitetural Fase 5 (antes de adicionar o router `/auditorias`).

**Descrição:**
O JWT real emitido por `auth.gerar_token_jwt()` põe o `user_id` na claim
`"sub"` (padrão RFC 7519). Porém 4 endpoints faziam `current_user.get("id")`
diretamente — que sempre retornava `None` em produção porque `"id"` não é
claim do JWT.

A fixture histórica de testes usava `{"id": 1, "username": "admin", "role": "admin"}`
(sem `"sub"`), mascarando o bug — todos os testes verdes e em produção
`uploaded_by_user_id` virava `None`.

Conseqüências concretas:
  - SIEG e Integra registravam documentos anônimos (sem dono no banco).
  - Dossiê de prova e-CAC gerava `AuditoriaAcessoDB` com `user_id=None`
    — cadeia de prova quebrada para fiscalização.
  - `/analise/pdf` cifrava PDFs e marcava `uploaded_by_user_id=None` em
    `AuditoriaDocumentoDB` → o endpoint `GET /auditoria/prova/cnpj/...`
    nunca teria como filtrar por dono.

**Evidência:**
```python
# Antes (PY/api/routers/integracoes.py:70)
uploaded_by_user_id=current_user.get("id"),  # → None sempre

# Depois (Fase 5)
uploaded_by_user_id=extrair_user_id(current_user),  # → lê "sub" OU "id"
```

**Solução aplicada (Fase 5):**
1. Criado helper universal `api.dependencies.extrair_user_id(current_user)`
   que aceita `"sub"` (JWT real) OU `"id"` (fixture legada), retornando
   `int > 0` ou `None`. `_extrair_user_id` em `main.py` virou alias.
2. Trocados todos os `current_user.get("id")` dos 4 arquivos pelo helper.
3. Teste de regressão `tests/test_err049_extrair_user_id.py` (11 testes):
   unitários do helper + integração com fixture que passa SOMENTE `"sub"`
   (formato JWT real) para `/auditorias` e `/settings`.
4. Fixture de conftest (`client_autenticado`) já tinha `"sub"` + `"id"` —
   mantida para cobertura retroativa de testes antigos.

**Status:** ✅ Corrigido na Fase 5 (commit pós d06e999).

---

### ERR-050 — `DiagnosticoDB` sem `uploaded_by_user_id` impedia `/auditorias`
**Data:** 23/04/2026
**Severidade:** 🔴 Crítico — sem essa coluna o endpoint do histórico seria IDOR horizontal
**Amparo legal:** LGPD Art. 6º V (minimização) + Art. 46 §1º (segurança)
**Arquivo:**
  - `PY/database/models.py::DiagnosticoDB` — faltava coluna
  - `PY/alembic/versions/49832cc28f45_fase5_paginas_fantasmas_ownership_e_settings.py` — migração nova
**Descoberto em:** Exploração arquitetural Fase 5 (desenho do router `/auditorias`).

**Descrição:**
`DiagnosticoDB` tinha apenas `empresa_id` como chave relacional — nenhum
campo identificava o usuário que disparou a análise. Consequência: se o
endpoint `GET /auditorias` fosse criado sem essa coluna, a única opção
seria retornar **todos os diagnósticos do sistema** para qualquer
autenticado. IDOR horizontal com CNPJs de clientes de outros contadores
sendo listados publicamente.

**Evidência:**
Schema antigo:
```python
class DiagnosticoDB(SQLModel, table=True):
    empresa_id: int = Field(foreign_key="empresas.id", index=True)
    # ... sem uploaded_by_user_id
```

**Solução aplicada (Fase 5):**
1. Migração Alembic `49832cc28f45`:
   - Coluna `diagnosticos.uploaded_by_user_id` (INTEGER, nullable, FK
     `users.id`, indexed). Nullable para preservar registros pré-Fase 5
     que não têm dono conhecido — esses ficam fora da listagem.
   - Ciclo `upgrade → downgrade → upgrade` validado manualmente no DB
     físico `motor_tributario.db`.
2. `DiagnosticoDB` Pydantic/SQLModel atualizado com a coluna.
3. `salvar_diagnostico` ganhou parâmetro `uploaded_by_user_id: Optional[int]`.
4. Novo método `listar_por_user(user_id, skip, limit)` em
   `diagnostico_repo.py` — filtra SEMPRE por dono. Nunca devolve registros
   de terceiros.
5. Router `/auditorias` (`PY/api/routers/historico.py`) usa o método com
   o `user_id` extraído via `extrair_user_id(current_user)` (ERR-049).
6. Testes em `tests/test_historico_endpoint.py` (7 testes) incluindo:
   - Regressão de ownership: user A nunca vê diagnóstico de user B.
   - Regressão LGPD: response não contém `cnpj`, `razao_social`,
     `resultado_json` (minimização).

**Status:** ✅ Corrigido na Fase 5.

---

### ERR-051 — `salvar_diagnostico` nunca era chamado nos handlers de análise
**Data:** 23/04/2026
**Severidade:** 🟡 Atenção — não era bug de segurança, era funcionalidade ausente
**Amparo legal:** MAX_FISCAL_05 (rastreabilidade) + LGPD Art. 37 (registro operacional) + CTN Art. 173 (retenção 5 anos)
**Arquivo:**
  - `PY/main.py` handlers `/analise/manual` e `/analise/pdf` (pré-Fase 5)
**Descoberto em:** Exploração arquitetural Fase 5 — rastrear por que o histórico estava sempre vazio.

**Descrição:**
A função `salvar_diagnostico` em `PY/database/repositories/diagnostico_repo.py`
existia, tinha testes próprios, mas **nunca era chamada por nenhum handler
de produção**. Em 948 testes verdes, o fluxo end-to-end `/analise/manual`
→ DB → `/auditorias` teria retornado lista vazia em produção **para sempre**.

Impacto isolado (histórico do cliente), mas combinado com ERR-050
transformaria o endpoint `/auditorias` novo em feature natimorta.

**Solução aplicada (Fase 5):**
1. Helper privado `_persistir_diagnostico_best_effort(fornecedora, diagnostico, user_id, periodo)`
   em `PY/main.py`. Best-effort (`try/except Exception` absorve falhas
   de DB, FK, etc — não derruba o endpoint).
2. Wire em `/analise/manual`: após gerar diagnóstico, chama o helper.
3. Wire em `/analise/pdf`: reconstrói `EmpresaFornecedora` a partir da
   extração (CNPJ + campos do `_extracao`) e chama o helper.
4. Falha na persistência só loga `logger.warning` — o cliente vê a
   análise normalmente. Essa escolha é intencional: o endpoint fiscal
   NÃO pode ser refém da disponibilidade do DB.

**Status:** ✅ Corrigido na Fase 5.

---

### PENDÊNCIA — Fase Fiscal posterior: Hardening Luiz #7 (guarda rpa_mensal vs faturamento_12m/12)
**Registrada em:** 23/04/2026
**Origem:** Luiz classificou como "blocker Fase 4" antes do Luis Miguel redefinir Fase 4 como Segurança/LGPD.
**Descrição:** Validar que `rpa_mensal <= faturamento_12m/12 * 1.5` — hoje nada bloqueia operador a digitar RPA inconsistente com o RBT12.
**Escopo:** Fiscal, NÃO de segurança. Aguarda fase fiscal posterior (após blindar ERR-005, ERR-037, ERR-039).
**Status:** ⏳ Pendente.

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
