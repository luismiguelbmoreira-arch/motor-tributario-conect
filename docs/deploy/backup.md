# Backup Diário do DB — OBRIGATÓRIO em Produção

Os metadados em `auditoria_documentos` são **inúteis** sem o DB. Perda
do banco = impossibilidade de gerar dossiê mesmo com os arquivos
cifrados intactos.

Use `PY/scripts/backup_db.py`:

```bash
# Execução manual
python PY/scripts/backup_db.py

# Dry run (só mostra o plano)
python PY/scripts/backup_db.py --dry-run
```

## Layout gerado

```
data/backups/
├── diarios/
│   ├── 2026-04-08.db.gz   ← retenção 30 dias rolling
│   ├── 2026-04-09.db.gz
│   └── ...
└── mensais/
    ├── 2026-04.db.gz       ← criado automaticamente no dia 1 do mês
    └── 2026-05.db.gz       ← permanente (purge manual apenas)
```

## Implementação

- `sqlite3.Connection.backup()` (transação-safe) em vez de `shutil.copy`
- Compressão gzip nível 9 (tipicamente 3-6× menor)
- Escrita atômica (tmp + rename) — falha no meio não corrompe backup anterior
- Exit code 0/1 para integração com cron

## Setup cron (Linux)

```
0 3 * * * cd /app && /usr/bin/python PY/scripts/backup_db.py >> /var/log/motor-backup.log 2>&1
```

## Setup Task Scheduler (Windows)

```
schtasks /Create /SC DAILY /ST 03:00 /TN "MotorConectBackup" ^
  /TR "python C:\app\PY\scripts\backup_db.py"
```

## Restauração

```bash
# 1. Parar API
# 2. Descomprimir
gzip -dk data/backups/diarios/2026-04-08.db.gz
# 3. Mover para a posição
mv data/backups/diarios/2026-04-08.db data/motor_tributario.db
# 4. Reiniciar API
```

## Política LGPD de retenção dos PDFs cifrados

Cron diário separado deve rodar `listar_documentos_purgaveis()` e
executar `storage_cifrado.purge(cnpj, hash)` + `marcar_documento_purgado(id)`
para os documentos que passaram do `purge_after` (5 anos — CTN Art. 173).

Metadados em `auditoria_documentos` permanecem com `purged_at`
preenchido (registro histórico). Logs em `auditoria_acessos` nunca
purgam (LGPD Art. 37).
