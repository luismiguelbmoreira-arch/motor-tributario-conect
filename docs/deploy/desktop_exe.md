# .exe Windows (single-computer)

App empacotado como janela nativa: FastAPI roda dentro do processo em
`127.0.0.1:<porta livre>` e a UI abre num WebView2 (pywebview).

## Build

```powershell
cd PY
python -m venv .venv            # ou: uv venv .venv --python 3.12
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-desktop.txt
powershell -ExecutionPolicy Bypass -File desktop\build_exe.ps1
```

Saída: `PY\dist\MotorTributario\MotorTributario.exe` (onedir — a pasta inteira é o app).
O script roda o `.exe --smoke` no fim e mostra a última linha do log.

## Rodar sem empacotar (dev)

```powershell
cd PY
.venv\Scripts\python -m desktop.launcher          # abre janela
.venv\Scripts\python -m desktop.launcher --smoke  # só verifica /health e /ui/login.html
```

## Peças

| Arquivo | Papel |
|---|---|
| `PY/desktop/runtime.py` | porta livre, caminhos (bundle × dev), stdout/stderr num exe sem console, uvicorn com loop/http fixos, polling do `/health` — sem importar `webview` (testável no CI) |
| `PY/desktop/launcher.py` | entrada do exe: prepara o banco, sobe uvicorn numa thread, espera `/health`, abre a janela; fechar a janela encerra o servidor |
| `PY/desktop/db_bootstrap.py` | cria/migra o SQLite do usuário a cada início (abaixo) |
| `PY/desktop/motor_tributario.spec` | PyInstaller onedir; inclui só código alcançável + `UI/` + `alembic/` (nada de `.env`, `*.db`, `data/`) |
| `PY/desktop/build_exe.ps1` | build + smoke |
| `PY/requirements-desktop.txt` | pywebview + pyinstaller, versões fixas; fora do `requirements.txt` (CI Linux não instala) |

Log do exe: `%APPDATA%\MotorTributario\logs\launcher.log`.

## Dados do usuário (`%APPDATA%\MotorTributario`)

| Item | Caminho |
|---|---|
| Banco SQLite | `motor_tributario.db` |
| PDFs cifrados da auditoria | `auditoria\` |
| Log | `logs\launcher.log` |

O launcher força `DATABASE_URL` e `MOTOR_CONECT_STORAGE_DIR` para essa pasta, define
`MOTOR_CONECT_DESKTOP=1` (o `.env` não sobrescreve) e usa a pasta como diretório atual.
Atualizar o exe não apaga esses dados.

### Banco a cada início (`PY/desktop/db_bootstrap.py`)

```
sem alembic_version (banco novo ou antigo criado por create_all)
    → SQLModel.metadata.create_all → alembic stamp head
com alembic_version
    → alembic upgrade head
```

Por que não `upgrade head` num banco vazio: a cadeia de `PY/alembic/versions` não
monta o schema atual do zero (a 1ª migration usa `sqlmodel` sem importar; a tabela
`users` nunca é criada por migration; `atividades` diverge dos modelos). O app sempre
dependeu de `create_all`. **Migrations novas devem partir do schema dos modelos**
(`alembic revision --autogenerate` contra um banco criado por `create_all`).

## Requisitos da máquina

- Windows 10/11 com **Microsoft Edge WebView2 Runtime** (já vem no Windows 11).
  Sem ele o launcher mostra uma caixa de erro com o link de instalação (não cai no motor antigo MSHTML).

## Limitações conhecidas (próximos PRs)

- UI ainda carrega Inter (Google Fonts), lucide, chart.js e tailwind de CDN → sem internet a UI quebra.
- `ANTHROPIC_API_KEY`, `JWT_SECRET_KEY` e `MOTOR_CONECT_MASTER_KEY` ainda vêm de `.env`/ambiente.
- weasyprint sem GTK no bundle → `/relatorio/pdf` responde 503 no exe.
- Sem assinatura de código: o SmartScreen avisa na primeira execução.
