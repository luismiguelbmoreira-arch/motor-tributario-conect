# Histórico Detalhado — Motor Tributário Conect

Este documento concentra commits, decisões arquitetônicas e ERRs já
fechados. O CLAUDE.md mantém apenas o status atual e próximas etapas.

Para ERRs detalhados ver também `docs/roadmap/LOG_ERROS.md`.

---

## Fase 0a (29/04/2026) — Schema HistoricoSeisMeses + DiagnosticoConsolidado

| Commit | Detalhe |
| --- | --- |
| `ecfcaf5` | Histórico 6 meses + DiagnosticoConsolidado — MAX_08 compliant (todo número via motor) |
| `92c6c83` | Regras MAX_08 + MAX_09 (sem simulação hipotética + nunca fingir execução) |

## Fase 0b (30/04/2026) — 5 módulos especiais + Rail R9

| Commit | Detalhe |
| --- | --- |
| `676b04d` | M1 — `core/fator_r_modulo.py` (calcular_serie + projetar + alertar_migracao) + fix bug NameError em historico_consolidado.py |
| `aecd48b` | M2 — `core/calendario_legal.py` (janelas firmes opt-out + renúncia Simples — LC 123 Art. 30 + LC 214 Art. 348 §§ 3º-4º + LC 227/2026 + Res. CGSN 186/2026) |
| `ebaf187` | M2 cleanup — schema enxugado retroativamente sob R9 |
| `020df86` | **R9 — Ampla Visão** adicionada à seção de Rails (Ontem/Amanhã/Hoje antes de mudança arquitetônica) |
| `4de26bc` | M3 — `core/sublimites_uf.py` (VersionedRule por ano + Portarias CGSN 49/2024 e 54/2025) + correção citação Art. 13§1º → Art. 13-A + Art. 19§4º |
| `6b0340c` | M4 — `core/profissoes_regulamentadas.py` (Art. 127 LC 214/2025 — 18 incisos taxativos; plano original citava Art. 138 errado) |
| `4a46f07` | **ERR-056** — citações inventadas Art. 172 II/III pra cigarro/bebida → Art. 409 § 1º + 410 (Imposto Seletivo) |
| `4d8e121` | M5 — `core/imposto_seletivo.py` (Arts. 409-434, sem alíquotas — Rail R2; vigência 2027 — Art. 544) + UI cronograma corrigida |

## Pós-Fase 0b (07/05/2026) — Desacoplamento Nibo + ERR-057 + Fase 2 + Fase 3' subfase 0

| Commit | Detalhe |
| --- | --- |
| `a556c6e` | **Decisão arquitetônica** — desacoplamento Nibo via interface `FonteCliente`. Motor consome interface; fontes implementam (PDF Manual, Nibo futuro, e-CAC futuro, Sistema próprio futuro). Reordenação do plano: Fase 1 sai do caminho crítico. |
| `35181ec` | **ERR-057** — fix MAX_06 cita "Art. 47 §II + Arts. 344/353/356-360" (errado) → "Art. 47 § 9º" (crédito de fornecedor Simples = fração do DAS). 4º bug MAX_07 detectado pelo Escrivão. |
| `9c073ab` | ERR-057 cleanup secundário — UI/agents/docs/comentários atualizados. |
| `5e014a6` | **Fase 2 subfase 2.0** — `core/mapa_categorias_cbs_ibs.py` com 9 categorias-piloto (LC 214/2025 Arts. 47 caput + 57 caput). Schema VersionedRule[Dict[str, ClassificacaoCredito]]. |
| `9196153` | **Fase 3' subfase 0** — `core/fontes/base.py` Protocol `FonteCliente` + exceções `FonteIndisponivel` e `DadosInsuficientesNaFonte`. Implementações concretas em subfases posteriores quando houver caller. |
| `f296b71` | **Fase 2 subfase 2.1** — mapa expandido 9 → 25 categorias (16 novas validadas pelo Escrivão em 07/05). 11 INSUMO + 4 USO_PESSOAL + 1 NAO_TRIBUTADO. 11 categorias pendentes documentadas. |
| `51a92dc` | **Fase 2 subfase 2.2** — mapa 25 → 33 categorias. 4 BEM_DE_CAPITAL (Art. 108) + 3 vales (Art. 57 § 3º + LC 227/2026) + 1 NAO_TRIBUTADO (ANUIDADE_CONSELHO_PJ). |
| `c1e18f8` | **Cache local de leis** — 3 LCs chave (123/2006, 214/2025, 227/2026) capturadas via curl direto contra Planalto + protocolo Escrivão cache-first. Resolve bloqueio operacional de 4 rodadas WebFetch socket-dropping. |
| `(seguinte)` | **Subfase 2.2 cont.** — COMBUSTIVEL_FROTA_EMPRESARIAL ao mapa (Art. 180 a contrario sensu). Mapa: 33 → 34. R9 análise mostrou que título do ticket "refactor `NCMS_MONOFASICAS_BLOQUEADAS`" estava enganoso — bloqueio em motor.py:54 protege OperacaoFiscal de VENDA; despesa de frota nunca passa por lá. Solução foi adicionar categoria ao mapa, sem refactor. 2 pendentes restantes: PLANO_SAUDE_FUNCIONARIO, BRINDES_MARKETING. |

## Cache local de fontes normativas (07/05/2026)

**Bloqueio operacional do Escrivão** (WebFetch contra Planalto socket-dropping em 4+ rodadas consecutivas) **resolvido** via cache local em `data/fontes_legais/`.

Descoberta: WebFetch falha mas `curl` direto funciona (limitação do tool, não do servidor).

| Lei | Tamanho | SHA-256 (12 chars) |
|---|---|---|
| LC 123/2006 (Simples) | 1.6MB | `de35b5205860...` |
| LC 214/2025 (IBS/CBS/IS) | 5.2MB | `54d4fe599cbe...` |
| LC 227/2026 (alterações) | 1.3MB | `84115b788660...` |

Estrutura:
- `data/fontes_legais/README.md` — protocolo de captura/uso
- `data/fontes_legais/HASHES.txt` — registro canônico (sha256 | path | url | data | fonte)
- `data/fontes_legais/planalto/lcpXXX_vYYYY-MM-DD.html` — snapshots HTML

Agente Escrivão (`.claude/agents/escrivao.md`) atualizado com protocolo
**cache-first**: lê arquivo local antes de tentar WebFetch. Cita URL
canônica + SHA-256 na resposta pra rastreabilidade fiscal.

Re-captura agendada quando: LC posterior altera dispositivos, Resolução
CGSN anual sai, ou 6 meses sem refresh (política conservadora).

## Entregue antes da Fase 0a (refinamento WS12/WS10/WS6)

| Fase | Commit | Detalhe |
| --- | --- | --- |
| Sprint 1 — base normativa + Aurora fixture | `2291cd6` | Rails+Parametrização Societária no CLAUDE.md; fixture Lucro Real Aurora; .bin órfãos pra `.lixeira/`; diagnóstico Vision API com Moreira (97% confiança) |
| WS12 spec — schema CNAE com Fator R (Luiz Moreira) | `57e0703` | Especificação fiscal aprovada (5 categorias semânticas) |
| WS12 implementação — `core/regras_cnae.py` + `cnae_excecoes.py` | `f60aa61` | API `resolve_anexo(cnae, fator_r)`, 14 casos cirúrgicos, 5 categorias (A_FIXO/B_ANEXO_III/C_FATOR_R/D_ESPECIAL/E_VEDADO), 24 testes |
| WS10 — VersionedRule[T] piloto | `45c177b` | 4 constantes versionadas (TETO Simples, Sublimite ICMS/ISS, Teto MEI, Limite Presumido); janela 2024-2033; 26 testes |
| WS6 etapa 1 — schema `EmpresaFornecedora` ampliado | `1dd2aee` | `tipo_societario` (9→13 tipos), `qualificacoes_especiais` (OSCIP/OS/CEBAS), `enquadramento_simples` (MEI/MEI_CAMINHONEIRO/ME/EPP); alias "MEI" UX-friendly; 20 testes |
| WS6 etapa 2 v1 — REPROVADA | `b1f2f69` | 4 críticos do Chefe + 4 erros de citação do Luiz |
| WS6 etapa 2 v2 — matriz societária 13×4 | `cc67199` | 52 células validadas por Escrivão; **ERR-017.b** (citação inventada SC COSIT 174/2019) bloqueado antes do commit; helpers retornam Elegibilidade completo; MATRIZ frozen via `MappingProxyType`; novos tipos SCP/ESC/CONSORCIO/PRODUTOR_RURAL_PF; aliases EIRELI→SLU; 130 testes |
| WS6 etapa 3 — sub-validador MEI | `4da125f` | `validar_mei(...)` valida tipo+teto+CNAE+modalidade; lista parcial conservadora ~30 CNAEs Anexo XI (anti-alucinação: fora da lista → Indeterminado, não False); MEI Caminhoneiro (LC 188/2021) modelado; 25 testes |
| WS6 etapa 4 — engine IMUNE | `b7c77fa` | LC 214/2025 Art. 9º + CF Art. 150 VI b/c + CTN Art. 14; split atividade-fim × atividade-meio (Rail R5); 3 ALERTAS obrigatórios (Art. 9º §4º + Art. 49 + Art. 51 §1º); STF RE 325.822 + SV 52 |
| WS6 etapa 5a — overlay COOPERATIVA | `ee41482` | `CooperativaOverlay` (não herda BaseRegimeEngine — overlay/decorator); 5 ramos OCB (CONSUMO/TRABALHO/PRODUCAO/AGROPECUARIA/TRANSPORTE); split ato_cooperativo × ato_não_cooperativo (Lei 5.764/71 Art. 87 caput); fora-de-incidência Art. 6º VI/X/XI (sempre) + Art. 271 alíquota zero (opt-in com janela § 3º — Rail R8); alertas AGROPECUARIA (§ 1º II) e TRANSPORTE (Art. 169 § 8º); cache Lei 5.764/71 + Lei 9.718/98; bloqueio MAX_07: Escrivão pegou citação inventada "Art. 87 § único" antes do código; 79 testes |
| WS6 etapa 6 — orquestrador societário | `1ae79a2`+`e2b21c8` | `validar_combinacao()` em `core/orquestrador_societario.py` agrega matriz societária (WS6) + sub-validador MEI + sub-validador COOPERATIVA + regras CNAE (WS12) + limites versionados (WS10). Concatena TODAS as falhas. Caller real plugado no motor: `_validacao_societaria` no `__init__` + `obter_validacao_societaria()` + eventos `ALERTA_VALIDACAO_SOCIETARIA_*` na trilha. Rail R7 (≥ 90% teto) implementado. Resultado frozen Pydantic V2. Hardening: `fornecedora: Any` → `EmpresaFornecedora` via TYPE_CHECKING. 26 testes |
| WS6 etapa 5b — cooperativa CRÉDITO + SAÚDE | (pendente PR) | **CRÉDITO**: Real obrigatório (Lei 9.718/98 Art. 14 II); regime específico de serviços financeiros (LC 214 Art. 181 caput); cooperativa de crédito como entidade supervisionada SFN (Art. 183 § 1º III — bloqueio Escrivão da citação inventada "Art. 182 § 1º III"); operações coop-associado fora da base sempre (Art. 192 § 8º, independe Art. 271); reversão de deduções proporcionais quando opt-in (Art. 188); associado tomador NÃO apropria créditos (Art. 197 I, redação LC 227/2026). **SAÚDE**: regime específico Cap III Tít V (LC 214 Arts. 234-238); base de cálculo Art. 235; alíquota referência reduzida em 60% (Art. 237); vedado crédito ao adquirente salvo PJ contratante (Art. 238 § único, redação LC 227/2026); Art. 271 inaplicável. PMD #1 fechado: criado `core/cooperativa_ramos.py` como fonte única. 17 testes novos. Cálculo automático IBS/CBS dos regimes específicos fica para etapa futura (Rail R2) |

## ERRs fechados — ver `docs/roadmap/LOG_ERROS.md`

ERR-005, ERR-013, ERR-017.b, ERR-018.b (IDOR), ERR-049 (JWT sub vs id),
ERR-050 (uploaded_by_user_id), ERR-051 (salvar_diagnostico), ERR-052
(CNAE fictício no wire), ERR-053 (log estruturado /auditorias),
ERR-054 (load_dotenv override), ERR-055 (CRLF/LF schema), ERR-056
(citações inventadas Art. 172), ERR-057 (MAX_06 Art. 47 § 9º),
ERR-058 (DL 1.598/77 Art. 8º-A vs Lei 9.430/96), ERR-058.b (Lei
8.218/91 Art. 12 sem piso fixo), ERR-058.c (DCTFWeb offset 2→1
conservador).
