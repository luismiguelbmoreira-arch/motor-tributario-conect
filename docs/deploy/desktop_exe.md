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
| `PY/services/chave_anthropic.py` | de onde vem a `ANTHROPIC_API_KEY` (abaixo) |
| `PY/requirements-desktop.txt` | pywebview + pyinstaller + keyring, versões fixas; fora do `requirements.txt` (CI Linux não instala) |

Log do exe: `%APPDATA%\MotorTributario\logs\launcher.log`.

## Dados do usuário (`%APPDATA%\MotorTributario`)

| Item | Caminho |
|---|---|
| Banco SQLite | `motor_tributario.db` |
| PDFs cifrados da auditoria | `auditoria\` |
| Log | `logs\launcher.log` |
| Secret JWT desta instalação | `jwt_secret` |
| Senha inicial do `admin` (só na 1ª execução) | `senha_inicial_admin.txt` |

O launcher força `DATABASE_URL`, `MOTOR_CONECT_STORAGE_DIR` e `JWT_SECRET_KEY` para essa
pasta, define `MOTOR_CONECT_DESKTOP=1` (o `.env` não sobrescreve) e usa a pasta como
diretório atual. Atualizar o exe não apaga esses dados.

### Segredos por instalação

- **JWT**: `jwt_secret` (64 hex, `secrets.token_hex(32)`) é criado na 1ª execução e
  reaproveitado depois; vence qualquer `JWT_SECRET_KEY` do ambiente. Apagar o arquivo só
  derruba os logins abertos (tokens de 8 h).
- **Admin inicial**: se o banco não tem usuário nenhum, o launcher gera uma senha aleatória
  (`secrets.token_urlsafe(12)`), passa para `auth.criar_admin_default` via
  `DEFAULT_ADMIN_PASSWORD` (tirada do ambiente depois da startup) e grava
  `senha_inicial_admin.txt`. Ao abrir, uma caixa mostra usuário, senha e o caminho do
  arquivo enquanto ele existir. A senha não vai para o log nem para o resultado do `--smoke`.
- Os dois arquivos ficam em texto puro no perfil do usuário do Windows, com a mesma
  proteção do `motor_tributario.db` (que também não é cifrado).
- O `--smoke` do `build_exe.ps1` roda numa `APPDATA` temporária (apagada no fim): o build
  não cria banco, secret nem admin no seu perfil.

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

## Chave da Anthropic (por usuário do Windows)

O `.exe` não carrega chave nenhuma. Cada usuário cadastra a própria em
**Configurações → Chave da Anthropic**; ela vai para o Gerenciador de Credenciais do
Windows (`keyring`, serviço `MotorTributario`, usuário `ANTHROPIC_API_KEY`).

| Onde roda | De onde vem a chave |
|---|---|
| `.exe` (`MOTOR_CONECT_DESKTOP=1`) | cofre do Windows → senão variável `ANTHROPIC_API_KEY` |
| servidor / CI / testes | só a variável `ANTHROPIC_API_KEY` (o cofre nunca é lido) |

- `GET /settings/anthropic-key` → `{configurada, origem, final (4 últimos), editavel}`; nunca a chave.
- `GET`, `PUT` (`{"chave": "sk-ant-..."}`) e `DELETE` só existem no modo desktop (404 fora dele).
- Precedência no exe: chave do cofre vence a variável de ambiente (cadastrar na tela substitui a do ambiente).
- A chave é lida na hora do uso; não vai para `os.environ`, log nem resposta.
- O cofre é do **usuário do Windows**: quem usa a mesma conta do Windows usa a mesma chave,
  qualquer que seja o login no app.
- Apagar à mão: Painel de Controle → Gerenciador de Credenciais → Credenciais do Windows → `MotorTributario`.

## Requisitos da máquina

- Windows 10/11 com **Microsoft Edge WebView2 Runtime** (já vem no Windows 11).
  Sem ele o launcher mostra uma caixa de erro com o link de instalação (não cai no motor antigo MSHTML).
- **Microsoft Edge** (navegador) para o PDF do relatório. Vem no Windows 10/11.

## PDF do relatório

`services/relatorio_pdf.gerar_pdf` tenta, em ordem:

1. **weasyprint**: precisa de GTK/Pango, que o exe não leva;
2. **Edge headless** (`msedge.exe --headless --print-to-pdf`): é o mesmo Chromium do WebView2,
   e o HTML é o mesmo.

- O caminho do Edge vem do registro (App Paths) ou das pastas padrão de Program Files/LocalAppData.
- O runtime do WebView2 (`msedgewebview2.exe`) não serve para isso: rodado sozinho em headless,
  sai com código 13. Por isso o PDF depende do Edge navegador.
- O HTML, que tem dado do cliente, fica numa pasta temporária própria (`motor-pdf-*`) que é apagada
  no fim. Ele roda com um perfil descartável e sem cabeçalho nem rodapé (nem data nem caminho do
  arquivo). Timeout de 60 s.
- No log entram só o tamanho do PDF e o tipo do erro.
- Sem weasyprint e sem Edge, `/relatorio/pdf` responde 503.
- O smoke do exe testa o motor de PDF e, na 1ª execução, também `POST /relatorio/pdf` com o
  token do admin. Usa um diagnóstico vazio e não grava o PDF.

## Limitações conhecidas (próximos PRs)

- UI ainda carrega Inter (Google Fonts), lucide, chart.js e tailwind de CDN → sem internet a UI quebra.
- `MOTOR_CONECT_MASTER_KEY` ainda vem de `.env`/ambiente (decisão aberta).
- A UI não tem tela de troca de senha e ignora `must_change_password`: o admin fica com a senha inicial.
- O layout do PDF do Edge (quebras de página, métricas de fonte) não foi comparado visualmente
  com o do weasyprint.
- Sem assinatura de código: o SmartScreen avisa na primeira execução.
