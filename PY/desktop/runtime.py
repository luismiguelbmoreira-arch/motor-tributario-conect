# -*- coding: utf-8 -*-
"""
desktop/runtime.py — Funções de apoio do launcher desktop.

Este módulo NÃO importa `webview` nem `main`: tudo aqui roda e é testável
em qualquer SO (inclusive no CI Linux). O launcher (`desktop/launcher.py`)
é quem junta as peças com a janela nativa.

Responsabilidades:
  - achar porta TCP livre em 127.0.0.1
  - localizar recursos (UI/, alembic/) dentro e fora do bundle PyInstaller
  - apontar banco e PDFs cifrados para %APPDATA%\\MotorTributario
  - JWT secret por instalação e senha inicial do admin (banco sem usuários)
  - garantir stdout/stderr válidos num .exe sem console
  - montar o servidor uvicorn com loop/http explícitos (sem imports dinâmicos)
  - esperar o /health responder antes de abrir a janela
"""

from __future__ import annotations

import os
import secrets
import socket
import sqlite3
import string
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional, TextIO

HOST = "127.0.0.1"
APP_DIR_NAME = "MotorTributario"
UI_DIR_ENV = "MOTOR_CONECT_UI_DIR"
# main.py: com esta flag, .env não sobrescreve o que o launcher definiu
DESKTOP_FLAG_ENV = "MOTOR_CONECT_DESKTOP"
# services/storage_cifrado.py lê esta variável (PDFs cifrados da auditoria)
STORAGE_DIR_ENV = "MOTOR_CONECT_STORAGE_DIR"
DB_FILENAME = "motor_tributario.db"
# auth.py lê JWT_SECRET_KEY no import e DEFAULT_ADMIN_PASSWORD na startup
JWT_SECRET_ENV = "JWT_SECRET_KEY"
JWT_SECRET_FILENAME = "jwt_secret"
_JWT_HEX_LEN = 64
ADMIN_PASSWORD_ENV = "DEFAULT_ADMIN_PASSWORD"
ADMIN_SENHA_FILENAME = "senha_inicial_admin.txt"
ADMIN_USERNAME = "admin"  # auth.criar_admin_default cria sempre este usuário
# A senha inicial é lida numa caixa do Windows e digitada à mão: sem I/l/1, O/o/0
# nem sinais, que se confundem na fonte do sistema. 55 símbolos x 16 ≈ 92 bits.
ADMIN_SENHA_ALFABETO = "".join(
    c for c in string.ascii_letters + string.digits if c not in "Il1Oo0"
)
_ADMIN_SENHA_LEN = 16


def is_frozen() -> bool:
    """True quando rodando de dentro de um bundle PyInstaller."""
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def resource_root() -> Path:
    """Raiz dos recursos empacotados.

    Frozen: `sys._MEIPASS` (pasta `_internal/` do onedir).
    Dev:    raiz do repositório (pai de `PY/`).
    """
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent


def ui_dir() -> Path:
    """Pasta `UI/` com os HTML/CSS/JS do frontend."""
    return resource_root() / "UI"


# O que da pasta UI/ entra no exe (motor_tributario.spec). Arquivo solto de outro tipo
# (rascunho, export, PDF de cliente) fica de fora. Tipo novo na UI: incluir aqui.
UI_EXTENSOES_EMPACOTADAS = frozenset({".html", ".css", ".js", ".woff2"})


def ui_arquivo_empacotado(path: Path) -> bool:
    """True para arquivo da UI que vai no exe: tipos da lista ou licença de biblioteca."""
    return path.suffix.lower() in UI_EXTENSOES_EMPACOTADAS or path.name.upper().startswith("LICENSE")


def ui_datas(ui: Path) -> list[tuple[str, str]]:
    """Pares (origem, destino) do PyInstaller para a UI, mantendo as subpastas."""
    pares = []
    for p in sorted(ui.rglob("*")):
        if p.is_file() and ui_arquivo_empacotado(p):
            pares.append((str(p), (Path("UI") / p.parent.relative_to(ui)).as_posix()))
    return pares


def user_data_dir(environ: Optional[dict[str, str]] = None) -> Path:
    """Pasta de dados do usuário: `%APPDATA%\\MotorTributario`.

    Fora do Windows (dev/CI) cai em `~/.motor_tributario`.
    """
    env = os.environ if environ is None else environ
    appdata = env.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_DIR_NAME
    return Path.home() / ".motor_tributario"


def find_free_port(host: str = HOST) -> int:
    """Pede ao SO uma porta TCP livre em `host`.

    Há uma janela curta entre fechar o socket e o uvicorn abrir a porta;
    em máquina de usuário único isso é aceitável.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def ensure_std_streams(log_path: Path) -> Optional[TextIO]:
    """Num .exe sem console, `sys.stdout`/`sys.stderr` são None.

    uvicorn e o `logging.StreamHandler(sys.stdout)` de `main.py` quebram nesse
    caso. Redireciona os dois para um arquivo de log. Retorna o arquivo aberto
    (ou None se os streams já existiam).
    """
    if sys.stdout is not None and sys.stderr is not None:
        return None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    return stream


def alembic_dir() -> Path:
    """Pasta `alembic/` (env.py + versions/). Frozen: `_internal/alembic`; dev: `PY/alembic`."""
    if is_frozen():
        return resource_root() / "alembic"
    return resource_root() / "PY" / "alembic"


def database_path(data_dir: Path) -> Path:
    return data_dir / DB_FILENAME


def sqlite_url(path: Path) -> str:
    """`sqlite:///C:/Users/.../motor_tributario.db` (barras normais, caminho absoluto)."""
    return "sqlite:///" + path.resolve().as_posix()


def desktop_environment(data_dir: Path) -> dict[str, str]:
    """Variáveis que o .exe FORÇA (não setdefault): banco e PDFs cifrados do usuário
    ficam em `data_dir`, nunca dentro do bundle nem no diretório atual."""
    return {
        DESKTOP_FLAG_ENV: "1",
        "DATABASE_URL": sqlite_url(database_path(data_dir)),
        STORAGE_DIR_ENV: str(data_dir / "auditoria"),
    }


def prepare_environment(
    environ: Optional[dict[str, str]] = None, data_dir: Optional[Path] = None
) -> None:
    """Define variáveis lidas por `main.py` ANTES de importá-lo.

    `MOTOR_CONECT_UI_DIR` só é preenchido se faltar (setdefault).
    Com `data_dir`, aplica `desktop_environment(data_dir)` por cima de tudo.
    """
    env = os.environ if environ is None else environ
    env.setdefault(UI_DIR_ENV, str(ui_dir()))
    if data_dir is not None:
        data_dir.mkdir(parents=True, exist_ok=True)
        env.update(desktop_environment(data_dir))
        # Secret da instalação vence qualquer JWT_SECRET_KEY de ambiente/.env
        env[JWT_SECRET_ENV] = garantir_jwt_secret(data_dir)


# ── Segredos por instalação ───────────────────────────────────────────────
# Ficam em `data_dir` (perfil do usuário do Windows), com a mesma proteção do
# banco. Nada aqui vai para log: só caminhos.


def _ler_jwt_secret(path: Path) -> Optional[str]:
    try:
        valor = path.read_text(encoding="ascii").strip()
    except (FileNotFoundError, UnicodeDecodeError):
        return None
    if len(valor) == _JWT_HEX_LEN and all(c in string.hexdigits for c in valor):
        return valor
    return None


def garantir_jwt_secret(data_dir: Path) -> str:
    """Secret JWT desta instalação: criado na 1ª execução e reaproveitado depois.

    Criação com O_EXCL (dois inícios simultâneos não geram secrets diferentes).
    Arquivo vazio ou corrompido é trocado por um novo: só derruba os tokens
    abertos (8 h), não afeta dados.
    """
    path = data_dir / JWT_SECRET_FILENAME
    existente = _ler_jwt_secret(path)
    if existente:
        return existente
    novo = secrets.token_hex(_JWT_HEX_LEN // 2)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        existente = _ler_jwt_secret(path)
        if existente:
            return existente
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(novo, encoding="ascii")
        os.replace(tmp, path)
        return novo
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(novo)
    return novo


def banco_sem_usuarios(db_path: Path) -> bool:
    """True se o banco não existe, não tem a tabela `users` ou ela está vazia."""
    if not db_path.is_file():
        return True
    con = sqlite3.connect(str(db_path))
    try:
        return con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    except sqlite3.OperationalError:
        return True
    finally:
        con.close()


def preparar_admin_inicial(
    data_dir: Path, environ: Optional[dict[str, str]] = None
) -> Optional[str]:
    """Banco sem usuários → senha aleatória para o `admin` desta instalação.

    Define `DEFAULT_ADMIN_PASSWORD` (lido por `auth.criar_admin_default` na
    startup; com a variável definida o auth não escreve a senha no log) e grava
    `senha_inicial_admin.txt` em `data_dir` para o usuário anotar.
    Devolve a senha (o chamador nunca a loga) ou None se já há usuários.
    """
    env = os.environ if environ is None else environ
    if not banco_sem_usuarios(database_path(data_dir)):
        return None
    senha = "".join(secrets.choice(ADMIN_SENHA_ALFABETO) for _ in range(_ADMIN_SENHA_LEN))
    texto = (
        "Motor Tributário Conect — primeiro acesso\n\n"
        f"Usuário: {ADMIN_USERNAME}\n"
        f"Senha:   {senha}\n\n"
        f"Digite o usuário exatamente assim: {ADMIN_USERNAME} (em minúsculas).\n"
        "A senha diferencia maiúsculas de minúsculas.\n"
        "Anote em lugar seguro e apague este arquivo.\n"
    )
    (data_dir / ADMIN_SENHA_FILENAME).write_text(texto, encoding="utf-8")
    env[ADMIN_PASSWORD_ENV] = senha
    return senha


def arquivo_senha_inicial(data_dir: Path) -> Path:
    return data_dir / ADMIN_SENHA_FILENAME


def build_server(app: Any, port: int, host: str = HOST) -> Any:
    """Cria um `uvicorn.Server` para `app` sem depender de imports dinâmicos.

    - recebe o objeto `app` (não string "main:app") → PyInstaller enxerga o import
    - loop/http fixos (asyncio/h11) → nada de uvloop/httptools escolhidos em runtime
    - ws="none" → a UI não usa websockets
    - log_config=None → não toca nos handlers de console
    """
    import uvicorn

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        loop="asyncio",
        http="h11",
        ws="none",
        lifespan="on",
        log_config=None,
        access_log=False,
    )
    return uvicorn.Server(config)


def start_server_thread(server: Any) -> threading.Thread:
    """Roda `server.run()` numa thread daemon e devolve a thread."""
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    return thread


def http_get(url: str, timeout: float = 2.0) -> tuple[int, bytes]:
    """GET simples com urllib (stdlib). Retorna (status, corpo)."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 — só 127.0.0.1
        return int(resp.status), resp.read()


def wait_until_healthy(
    url: str,
    timeout: float = 30.0,
    interval: float = 0.2,
    getter: Callable[[str], tuple[int, bytes]] = http_get,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Faz polling em `url` até receber HTTP 200 ou estourar `timeout` segundos."""
    deadline = clock() + timeout
    while True:
        try:
            status, _ = getter(url)
            if status == 200:
                return True
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        if clock() >= deadline:
            return False
        sleep(interval)


def base_url(port: int, host: str = HOST) -> str:
    return f"http://{host}:{port}"
