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
  - garantir stdout/stderr válidos num .exe sem console
  - montar o servidor uvicorn com loop/http explícitos (sem imports dinâmicos)
  - esperar o /health responder antes de abrir a janela
"""

from __future__ import annotations

import os
import socket
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
