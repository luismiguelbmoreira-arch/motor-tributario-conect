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

**Status:** ⏳ Pendente

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

**Status:** ⏳ Pendente

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

**Status:** ⏳ Pendente

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

**Status:** ⏳ Pendente

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
| CONFI-AR | `docs/doc calculo/CONFI_AR/` | ✅ Delta R$14,45 com cálculo manual multi-atividade — APROVADO (ERR-008 identificado, aguarda impl.) |
| ITANGUA  | `docs/doc calculo/ITANGUA/`  | ✅ Delta R$74,36 com RPA real — APROVADO (ERR-007 documentado) |

---

*Documento criado: 27/03/2026 | Motor Tributário Conect 2026-2033*
