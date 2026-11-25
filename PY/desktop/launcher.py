# -*- coding: utf-8 -*-
"""
launcher.py — abre o Motor Tributário Conect como app desktop (um computador).

Fluxo:
  1. Escolhe uma porta livre em 127.0.0.1 (nunca expõe na rede).
  2. Sobe o FastAPI de `main.py` com uvicorn numa thread do mesmo processo.
  3. Espera GET /health responder.
  4. Abre uma janela nativa (pywebview + WebView2) em /ui/login.html.
  5. Ao fechar a janela, encerra o servidor e sai.

Uso:
  python desktop/launcher.py            # janela
  python desktop/launcher.py --smoke    # sem janela: sobe, testa 3 rotas, sai (código 0 = ok)

Este módulo não toca em cálculo tributário. `webview` e `uvicorn` são
importados só dentro das funções, para os testes rodarem sem pywebview.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

APP_TITLE = "Motor Tributário Conect"
HOST = "127.0.0.1"
LOG_FILE_NAME = "motor_tributario_desktop.log"

logger = logging.getLogger("motor_conect.desktop")


# ─────────────────────────────────────────────────────────────────────────────
# Caminhos
# ─────────────────────────────────────────────────────────────────────────────

def is_frozen() -> bool:
    """True quando rodando de dentro do .exe gerado pelo PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Raiz onde ficam `UI/` e o código.

    .exe  → pasta temporária/_internal do PyInstaller (`sys._MEIPASS`).
    dev   → raiz do repositório (PY/desktop/launcher.py → ../../).
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent.parent


def runtime_dir() -> Path:
    """Pasta gravável para banco, PDFs cifrados e log.

    Provisório (etapa 1): pasta `dados/` ao lado do .exe. A etapa 4 move
    para %APPDATA%\\MotorTributario e roda Alembic a cada início.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent / "dados"
    return Path(__file__).resolve().parent / ".runtime"


# ─────────────────────────────────────────────────────────────────────────────
# Ambiente
# ─────────────────────────────────────────────────────────────────────────────

def configure_environment(bundle: Path, runtime: Path, frozen: bool) -> dict[str, str]:
    """Define variáveis que `main.py` lê no import. Nunca sobrescreve valor já setado.

    Retorna só as variáveis que este launcher definiu (para log e teste).
    """
    definidas: dict[str, str] = {}

    def _set(chave: str, valor: str) -> None:
        if chave not in os.environ:
            os.environ[chave] = valor
            definidas[chave] = valor

    _set("MOTOR_CONECT_UI_DIR", str(bundle / "UI"))
    if frozen:
        runtime.mkdir(parents=True, exist_ok=True)
        # main.py e auth.py precisam apontar para o MESMO arquivo — sem a
        # variável, cada um tem um default diferente.
        _set("DATABASE_URL", "sqlite:///" + (runtime / "motor_tributario.db").as_posix())
        _set("MOTOR_CONECT_STORAGE_DIR", str(runtime / "auditoria"))
        # WARNING para a senha do admin gerada no 1º início ir para o log.
        # Provisório: a etapa 8 troca isso por senha definida na instalação.
        _set("LOG_LEVEL", "WARNING")
    return definidas


def redirect_std_streams(log_path: Path) -> None:
    """No .exe sem console, sys.stdout/stderr são None e quebram logging/uvicorn."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Fica aberto até o fim do processo, de propósito.
    stream = open(log_path, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def ensure_import_path(bundle: Path, frozen: bool) -> None:
    """Em dev, `main` está em PY/; no .exe já está no PYZ."""
    if frozen:
        return
    py_dir = str(bundle / "PY")
    if py_dir not in sys.path:
        sys.path.insert(0, py_dir)


# ─────────────────────────────────────────────────────────────────────────────
# Servidor
# ─────────────────────────────────────────────────────────────────────────────

def find_free_port(host: str = HOST) -> int:
    """Pede ao sistema uma porta TCP livre no host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def build_server(port: int, host: str = HOST) -> Any:
    """Cria o uvicorn.Server do app. Opções fixas evitam imports dinâmicos que o PyInstaller perde."""
    import uvicorn

    from main import app

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
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    return thread


def stop_server(server: Any, thread: threading.Thread, timeout: float = 10.0) -> bool:
    """Pede para o uvicorn sair e espera. True se a thread terminou."""
    server.should_exit = True
    thread.join(timeout)
    return not thread.is_alive()


def wait_until_ready(
    base_url: str,
    timeout: float = 30.0,
    interval: float = 0.2,
    thread: threading.Thread | None = None,
) -> bool:
    """Faz GET /health até responder 200, estourar o tempo ou a thread do servidor morrer."""
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if thread is not None and not thread.is_alive():
            return False  # startup falhou (ex.: banco inacessível) — não esperar à toa
        try:
            with urllib.request.urlopen(base_url + "/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            pass
        time.sleep(interval)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Smoke test (sem janela)
# ─────────────────────────────────────────────────────────────────────────────

def _http(method: str, url: str, body: dict[str, Any] | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read(4096).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(4096).decode("utf-8", "replace")


def run_smoke(base_url: str) -> dict[str, Any]:
    """Confere API, UI estática e bcrypt (login com senha errada = 401)."""
    checks: dict[str, Any] = {}

    status, _ = _http("GET", base_url + "/health")
    checks["health_200"] = status == 200

    status, corpo = _http("GET", base_url + "/ui/login.html")
    checks["ui_login_200"] = status == 200 and "<html" in corpo.lower()

    status, _ = _http(
        "POST",
        base_url + "/auth/login",
        {"username": "admin", "password": "senha-errada-smoke-test"},
    )
    checks["login_errado_401"] = status == 401

    checks["ok"] = all(v for k, v in checks.items() if k != "ok")
    return checks


# ─────────────────────────────────────────────────────────────────────────────
# Janela
# ─────────────────────────────────────────────────────────────────────────────

def _mostrar_erro(mensagem: str) -> None:
    """Caixa de erro nativa do Windows (sem dependência extra)."""
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, mensagem, APP_TITLE, 0x10)
    except Exception:  # fora do Windows ou sem user32
        pass


def open_window(url: str) -> None:
    import webview

    webview.create_window(APP_TITLE, url, width=1280, height=820, min_size=(1024, 680))
    webview.start()


# ─────────────────────────────────────────────────────────────────────────────
# Entrada
# ─────────────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_TITLE + " — desktop")
    parser.add_argument("--smoke", action="store_true", help="sobe o servidor, testa 3 rotas e sai")
    parser.add_argument("--port", type=int, default=0, help="porta fixa (padrão: livre)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    frozen = is_frozen()
    bundle = bundle_dir()
    runtime = runtime_dir()

    redirect_std_streams(runtime / LOG_FILE_NAME)
    configure_environment(bundle, runtime, frozen)
    ensure_import_path(bundle, frozen)

    port = args.port or find_free_port()
    base_url = f"http://{HOST}:{port}"

    server = build_server(port)
    thread = start_server_thread(server)

    if not wait_until_ready(base_url, thread=thread):
        stop_server(server, thread)
        msg = f"O servidor interno não respondeu em {base_url}. Veja {runtime / LOG_FILE_NAME}."
        print(msg, file=sys.stderr)
        if not args.smoke:
            _mostrar_erro(msg)
        return 2

    if args.smoke:
        resultado = run_smoke(base_url)
        resultado["parou_limpo"] = stop_server(server, thread)
        print(json.dumps(resultado, ensure_ascii=False))
        return 0 if resultado["ok"] and resultado["parou_limpo"] else 1

    try:
        open_window(base_url + "/ui/login.html")
    except Exception as exc:
        logger.error("Falha ao abrir a janela: %s", exc)
        _mostrar_erro(
            "Não foi possível abrir a janela do app.\n\n"
            "Instale o Microsoft Edge WebView2 Runtime e tente de novo.\n\n"
            f"Detalhe: {exc}"
        )
        stop_server(server, thread)
        return 3

    stop_server(server, thread)
    return 0


if __name__ == "__main__":
    sys.exit(main())
