# RFC: Rollback Automático e Playbook de Incidente

**Status:** Draft
**Autor:** O Viciado + O Chefe
**Data:** 2026-04-08
**Revisão:** Luiz Moreira (compliance), SRE

## Objetivo
Definir gatilhos e procedimentos para reverter deploys do Motor Tributário Conect
que causem risco legal ou falha de contrato de parser, protegendo o legado do
escritório e evitando responsabilização por diagnóstico incorreto.

## Princípio Akita
> "Observability first. Contratos imutáveis. Reverter é mais barato que explicar."

## Gatilhos automáticos
1. **Gate CI Schema Registry** — Falha em `tests/observability/test_schema_registry.py`
   após merge (drift não detectado pré-merge).
2. **Semáforo DAS vermelho em massa** — `>5%` dos clientes com `semaforo_das == "vermelho"`
   em janela de 24h.
3. **Anomaly spike** — `anomaly.count` > 3× baseline dos últimos 7 dias, em janela de 1h.
4. **Teste legal vermelho** — Qualquer caso em `tests/test_fase2_simples.py`,
   `tests/test_fase3_iva.py`, `tests/test_fase4_optout.py`, `tests/test_regime_guard.py`,
   `tests/test_mei_guard.py` falhando em produção pós-deploy.
5. **Alerta manual de compliance** — Auditor fiscal reporta divergência de amparo legal
   via canal `#compliance`.
6. **HMAC trilha inválida** — `verificar_trilha()` retorna índices inválidos em um
   dossiê de prova (vetor de adulteração).

## Ações automáticas
1. CI detecta falha legal → bloquear deploy, abrir issue severidade P0, notificar `#incidentes`.
2. Produção com gatilho (2)–(6):
   - Reverter `main` para o último commit verde (tag `release-last-stable`).
   - Desabilitar feature flag de rollout gradual.
   - Notificar: `#incidentes`, `#compliance`, `#sre`, `#produto`.
   - Congelar merges em `main` até postmortem.

## Playbook manual
**Responsáveis:** On-call SRE | Engenheiro de Plataforma | Auditor Fiscal

**Tempo-alvo de rollback:** 60 minutos desde detecção.

**Passos:**
1. **Confirmar gatilho** — coletar logs, métricas, trilhas HMAC afetadas.
2. **Rollback** — `git revert <merge-sha>` ou redeploy da tag `release-last-stable`.
3. **Validação local** — rodar `python -m pytest tests/ -q` antes de publicar.
4. **Deploy reverso** — pipeline padrão, com freeze de feature flag.
5. **Comunicação** — e-mail para clientes afetados + nota em `#clientes`.
6. **Postmortem** — documento em `docs/postmortems/YYYY-MM-DD-<slug>.md` com:
   - Causa raiz
   - Por que o gate de CI não pegou
   - Ação corretiva (novo teste, nova regra de anomalia, etc.)

## Checklist pós-rollback
- [ ] Validar integridade das trilhas HMAC (`verificar_trilha()` para amostra de clientes)
- [ ] Validar semáforo DAS para amostra de 20 clientes
- [ ] Rodar suite completa em produção (`tests/ -q`)
- [ ] Confirmar métricas voltaram ao baseline
- [ ] Atualizar este RFC com lições aprendidas
- [ ] Abrir PR corretivo na branch `hotfix/...`

## Contatos
| Papel | Responsável | Contato |
|---|---|---|
| SRE lead | `<preencher>` | `<email>` |
| Auditor fiscal | Luiz Moreira | `<email>` |
| Engenheiro de plataforma | O Viciado | `<email>` |
| Compliance (externo) | `<preencher>` | `<email>` |

## Aprovações necessárias
- [ ] SRE
- [ ] Compliance / Auditor fiscal
- [ ] Arquiteto (O Chefe)

## Referências
- CTN Art. 142 (lançamento tributário — prova de integridade)
- CTN Art. 173 (decadência — 5 anos)
- LGPD Art. 37 (log de acesso)
- Plano Akita: `C:\Users\EL PUTO MACABRO\.claude\plans\indexed-waddling-breeze.md`
