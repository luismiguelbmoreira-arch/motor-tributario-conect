# PR Template — Motor Tributário Conect

## Resumo das mudanças
- **Tipo**: feature / fix / docs / tests / refactor
- **Módulos afetados**: listar arquivos e parsers

## Motivo
Descreva o problema que este PR resolve e o impacto esperado.

## Parsers e Schema Registry
> Preencha SOMENTE se tocou em `PY/parsers/**`. Caso contrário, marque "N/A".

- **Parser modificado/novo**: `<nome>`
- **Versão anterior**: `x.y.z`
- **Versão nova**: `x.y.z`
- **Checksum antigo**: `<sha256[:16]>`
- **Checksum novo**: `<sha256[:16]>`
- **Ação requerida**: atualizar `PY/observability/schema_registry.py` com nova versão e checksum.

## Testes executados localmente
- [ ] `python -m pytest tests/observability/ -q`
- [ ] `python -m pytest tests/parsers/ -q`
- [ ] `python -m pytest tests/ -q` (regressão completa)

Resultado: `<N passed, M failed>`

## Compliance e Legal
- Mudança com impacto legal? **sim / não**
- Aprovação de auditoria fiscal necessária? **sim / não**
- Auditor que revisou: `________`
- Amparo legal citado (MAX_FISCAL_02): `________`

## Observability Akita
- [ ] Trilha de auditoria recebe `hmac_trilha.assinar_passo()` quando aplicável
- [ ] Novo alerta registrado em `observability/anomalias.py`? Citar regra
- [ ] Telemetria atualizada (anomaly.count, semaforo.status, ingest.success/failure)

## Checklist antes do merge
- [ ] Bump de versão no parser e registro no schema registry (quando aplicável)
- [ ] Testes unitários adicionados/atualizados
- [ ] Contract tests passam localmente
- [ ] CI verde — incluindo **Schema Registry Gate**
- [ ] Revisão por SRE e Auditor Fiscal (para mudanças críticas)

## Notas de deploy
- Rollout gradual recomendado para clientes piloto
- Monitorar métricas: `anomaly.count`, `semaforo.status`
- Gatilhos de rollback: ver [`docs/rollback_rfc.md`](../docs/rollback_rfc.md)

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
