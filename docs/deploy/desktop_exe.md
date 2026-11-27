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
| `PY/desktop/launcher.py` | entrada do exe: sobe uvicorn numa thread, espera `/health`, abre a janela; fechar a janela encerra o servidor |
| `PY/desktop/motor_tributario.spec` | PyInstaller onedir; inclui só código alcançável + `UI/` (nada de `.env`, `*.db`, `data/`) |
| `PY/desktop/build_exe.ps1` | build + smoke |
| `PY/requirements-desktop.txt` | pywebview + pyinstaller, versões fixas; fora do `requirements.txt` (CI Linux não instala) |

Log do exe: `%APPDATA%\MotorTributario\logs\launcher.log`.

## Requisitos da máquina

- Windows 10/11 com **Microsoft Edge WebView2 Runtime** (já vem no Windows 11).
  Sem ele o launcher mostra uma caixa de erro com o link de instalação (não cai no motor antigo MSHTML).

## Limitações conhecidas (próximos PRs)

- UI ainda carrega Inter (Google Fonts), lucide, chart.js e tailwind de CDN → sem internet a UI quebra.
- Banco: `auth.py` e `database/connection.py` têm caminhos padrão diferentes; vai para `%APPDATA%\MotorTributario` com Alembic no start.
- `ANTHROPIC_API_KEY`, `JWT_SECRET_KEY` e `MOTOR_CONECT_MASTER_KEY` ainda vêm de `.env`/ambiente.
- weasyprint sem GTK no bundle → `/relatorio/pdf` responde 503 no exe.
- Sem assinatura de código: o SmartScreen avisa na primeira execução.
