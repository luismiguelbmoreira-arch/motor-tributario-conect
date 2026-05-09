# MOTOR_CONECT_MASTER_KEY — Setup em Produção

Chave raiz da auditoria documental cifrada (AES-256-GCM + HKDF-SHA256).
**Perder = impossibilidade de decifrar PDFs antigos.** Cofre obrigatório
(1Password, Bitwarden, AWS Secrets Manager).

## Geração da chave

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

64 caracteres hexadecimais (256 bits).

## Fontes resolvidas em ordem (`storage_cifrado._master_key()`)

| # | Fonte | Quando usar |
|---|---|---|
| 1 | `$MOTOR_CONECT_MASTER_KEY` env var | Dev local (via `PY/.env`) |
| 2 | Arquivo protegido (`/etc/motor-conect/master.key` ou `%PROGRAMDATA%\motor-conect\master.key`) | Deploy em servidor físico/VM. Permissões: owner do usuário do serviço, mode 0600 |
| 3 | `$MOTOR_CONECT_MASTER_KEY_AWS_SECRET` | Deploy cloud AWS (ECS/EC2/Lambda com IAM role) |

**Override do path do arquivo:** `$MOTOR_CONECT_MASTER_KEY_FILE=/caminho/custom.key`

## Setup servidor Linux

```bash
sudo mkdir -p /etc/motor-conect
sudo chown motor-conect:motor-conect /etc/motor-conect
sudo chmod 700 /etc/motor-conect
echo "<sua-chave-hex-64-chars>" | sudo tee /etc/motor-conect/master.key
sudo chmod 600 /etc/motor-conect/master.key
sudo chown motor-conect:motor-conect /etc/motor-conect/master.key
```

## Setup servidor Windows

```powershell
mkdir $env:PROGRAMDATA\motor-conect
Set-Content -Path "$env:PROGRAMDATA\motor-conect\master.key" -Value "<chave>"
icacls "$env:PROGRAMDATA\motor-conect\master.key" /inheritance:r /grant:r "NT SERVICE\MotorConect:(R)"
```

## Setup AWS Secrets Manager

```bash
aws secretsmanager create-secret --name motor-conect/master-key \
  --secret-string "$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

No `.env` do servidor:
```
MOTOR_CONECT_MASTER_KEY_AWS_SECRET=motor-conect/master-key
```

Requer: `pip install boto3` + IAM role com permissão `secretsmanager:GetSecretValue`.

## Recuperação de incidente

Master key perdida → PDFs antigos **irrecuperáveis**. Dossiê de casos
novos funciona com nova key; antigos só pelos hashes ainda registrados
em `auditoria_documentos`.
