# ATA DE CONSENSO — ERR-018.b: IDOR Guard nos Endpoints de Integração

**Data:** 24/04/2026
**Protocolo:** Jogada Fiscal v2.1
**ERR:** ERR-018.b
**Status:** GOL ✅

---

## Pauta

POST /integracoes/ecac/sync (e endpoints irmãos) aceitava qualquer CNPJ de
qualquer usuário autenticado — violação de acesso horizontal (IDOR). Verificar
corretude do fix implementado na Fase 5 e fechar o ERR com cobertura de testes.

---

## Descoberta Pré-Consenso

O guard `_verificar_ownership_cnpj` já estava implementado nos 3 endpoints de
integração (Fase 5). A Fase 1 identificou 4 itens pendentes antes do fechamento.

---

## Posições Originais

### Chefe — BLOQUEIA

**Achado 1 — Bomba do NULL (ERR resolvido por decisão):**
Registros pré-Fase 5 têm `uploaded_by_user_id = NULL`. A query `WHERE
uploaded_by_user_id = user_id` nunca casa com NULL em SQL, bloqueando usuários
legítimos com dados antigos com 403 e rotulando-os como atacantes na tabela de
auditoria.

**Decisão tomada:** Admin-only para dados pré-Fase 5. Usuários com dados antigos
precisam rodar nova análise. Documentado com comentário explícito no código.

**Achado 2 — GET /auditoria/prova/cnpj/{cnpj_digitos} sem guard:**
Endpoint de dossiê ZIP permitia acesso a documentos de qualquer CNPJ por
qualquer usuário autenticado. Ripple não coberto pelo fix original.

**Ação:** Guard adicionado neste ERR.

### Viciado — PASSA (com ressalvas)

Código tecnicamente correto. Sem bug bloqueante. Identificou:
- Sem bug de race condition, exception swallowing ou tipo errado
- Double-normalização de CNPJ é intencional (defesa em camadas)
- `request.client.host` protegido por try/except
- 11 testes HTTP de integração ausentes → obrigatórios nesta entrega
- Admin bypass sem log (incorporado por decisão do usuário)

### Luiz Moreira — IMPEDIMENTO PARCIAL

**LGPD Art. 48 incorreto como fundamento de bloqueio preventivo:**
Art. 48 regula notificação pós-incidente à ANPD, não autorização de medida
preventiva. Correto apenas no repo/model onde a tabela serve como prova para
notificação.

**Correções documentais implementadas:**
- `_verificar_ownership_cnpj`: substituído Art. 48 por Art. 46 §1º + Art. 6º VII
- `AuditoriaTentativaAcessoDB`: Art. 48 mantido (uso correto — base de prova)
- `tem_acesso_cnpj`: Art. 6º V mantido (minimização — correto)
- `user_id_dono=None`: expandido com Art. 37 + Art. 46 §1º

---

## Divergências e Resolução

| Divergência | Resolução |
|---|---|
| Bomba NULL: fallback permissivo vs. admin-only | Usuário decidiu: admin-only. Sem mudança de código, apenas comentário. |
| Admin bypass sem log | Incorporado nesta entrega: `logger.info("ADMIN_CNPJ_ACCESS")` |
| ERR-052 (admin log): diferir ou incluir | Incluído como 3 linhas + 1 teste, sem nova tabela |

---

## Solução Consensada

### Arquivos modificados

| Arquivo | Mudança |
|---|---|
| `PY/api/routers/integracoes.py` | logger movido para antes da função; docstring corrigida (Art. 46 §1º + Art. 6º VII); admin bypass log adicionado |
| `PY/api/routers/auditoria.py` | Guard de ownership adicionado em `gerar_dossie_prova` (+ imports `tem_acesso_cnpj` e `registrar_tentativa_acesso`) |
| `PY/database/models.py` | Comentário de `user_id_dono` expandido com Art. 37 + Art. 46 §1º |
| `PY/database/repositories/diagnostico_repo.py` | Docstring `tem_acesso_cnpj` expandida: NULL = admin-only intencional |
| `PY/tests/test_integracoes_idor_guard.py` | 13 testes novos criados (TDD reverso) |

### Amparo Legal Final

| Ponto | Artigo |
|---|---|
| Guard de bloqueio preventivo | LGPD Art. 46 §1º + Art. 6º VII |
| Sigilo fiscal (subsidiário) | CTN Art. 198 |
| Registro de tentativas (log IP) | LGPD Art. 7º VI + Art. 10 + Art. 37 |
| `user_id_dono=None` sem FK | LGPD Art. 37 + Art. 46 §1º |
| Minimização em `tem_acesso_cnpj` | LGPD Art. 6º V |
| Tabela como prova de incidente ANPD | LGPD Art. 48 |
| Admin bypass com log (Art. 37) | LGPD Art. 37 |

### NULL = Admin-Only (decisão de 24/04/2026)

Registros com `uploaded_by_user_id = NULL` (pré-Fase 5) retornam False em
`tem_acesso_cnpj`. Admin bypass garante acesso. Usuários com dados antigos
recebem 403 até refazerem análise (estabelece ownership). Documentado em
comentário no código.

---

## Testes Implementados (13)

| Classe | Teste | O que valida |
|---|---|---|
| `TestIDORGuardBloqueio` | `test_sieg_cnpj_alheio_retorna_403` | 403 sem ownership |
| `TestIDORGuardBloqueio` | `test_sieg_cnpj_alheio_persiste_tentativa_auditoria` | linha em AuditoriaTentativaAcessoDB |
| `TestIDORGuardBloqueio` | `test_sieg_cnpj_proprio_via_diagnostico_passa_guard` | ownership via DiagnosticoDB |
| `TestIDORGuardBloqueio` | `test_sieg_cnpj_proprio_via_documento_passa_guard` | ownership via AuditoriaDocumentoDB (raw) |
| `TestIDORGuardBloqueio` | `test_sieg_cnpj_formatado_no_documento_passa_guard` | CNPJ formatado no doc, raw na request |
| `TestIDORGuardBloqueio` | `test_sieg_cnpj_formatado_na_request_resolve_igual_raw` | equivalência de formatos |
| `TestIDORGuardOutrosEndpoints` | `test_integra_sincronizar_cnpj_alheio_retorna_403` | guard em /integra/sincronizar |
| `TestIDORGuardOutrosEndpoints` | `test_ecac_sync_cnpj_alheio_retorna_403_form_data` | guard em /ecac/sync (multipart) |
| `TestIDORGuardOutrosEndpoints` | `test_auditoria_prova_cnpj_alheio_retorna_403` | guard em /auditoria/prova/cnpj |
| `TestAdminBypass` | `test_admin_bypassa_guard_qualquer_cnpj` | admin nunca recebe 403 |
| `TestAdminBypass` | `test_admin_bypass_nao_polui_auditoria` | bypass não gera linha de tentativa |
| `TestAdminBypass` | `test_admin_bypass_gera_log_sem_pii` | ADMIN_CNPJ_ACCESS sem CNPJ no log |
| `TestJwtSemSubOuId` | `test_jwt_sem_sub_sem_id_retorna_403_sem_tentativa` | JWT sem sub → 403 sem auditoria |

**Resultado TDD reverso:** 2 falhas antes dos fixes (test 12 e 13), 13 passando após.
**Suite completa:** 1012 testes passando, 0 regressões introduzidas.

---

## ERRs Derivados (abertos separadamente)

- **ERR-051.b:** refatorar `_verificar_ownership_cnpj` para `api/dependencies.py` (DRY entre routers)
- **ERR-053:** validação de pattern CNPJ nos schemas Pydantic (`SiegSincronizarRequest`, `IntegraSincronizarRequest`)

---

## Assinaturas

| Agente | Voto | Data |
|---|---|---|
| O Chefe | ✅ APROVADO (após incorporação dos 2 achados) | 24/04/2026 |
| O Viciado | ✅ APROVADO | 24/04/2026 |
| Luiz Moreira | ✅ GOL | 24/04/2026 |
| Usuário (Luis Miguel) | ✅ APROVADO (plano + decisão NULL) | 24/04/2026 |

---

**GOL ✅ — ERR-018.b fechado.**
