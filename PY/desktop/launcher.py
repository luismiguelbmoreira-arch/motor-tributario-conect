# -*- coding: utf-8 -*-
"""
desktop/launcher.py — Ponto de entrada do .exe Windows.

Fluxo:
  1. garante stdout/stderr (exe sem console) e prepara variáveis de ambiente
     (banco e PDFs cifrados em %APPDATA%/MotorTributario)
  2. cria/migra o banco (desktop/db_bootstrap.py) e importa a FastAPI de `main.py`
  3. sobe uvicorn numa thread em 127.0.0.1:<porta livre>
  4. espera GET /health == 200
  5. abre janela nativa (pywebview + WebView2) em /ui/login.html
  6. janela fechada → pede shutdown ao uvicorn e sai

Modo de verificação sem janela:
  MotorTributario.exe --smoke
  → sobe o servidor, checa /health, /ui/login.html e o banco em %APPDATA%,
    grava o resultado no log
    e sai com código 0 (ok) ou 1 (falha).

Dev (sem empacotar), a partir de PY/:
  python -m desktop.launcher          # abre janela
  python -m desktop.launcher --smoke  # só verificação
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    # Executado como script (PyInstaller): garante PY/ no sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from desktop import db_bootstrap, runtime  # noqa: E402

WINDOW_TITLE = "Motor Tributário Conect"
START_PATH = "/ui/login.html"
HEALTH_PATH = "/health"
WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"

logger = logging.getLogger("motor_conect.desktop")


def _log_path() -> Path:
    return runtime.user_data_dir() / "logs" / "launcher.log"


def _report(payload: dict) -> None:
    line = json.dumps(payload, ensure_ascii=False)
    print(line, flush=True)


def _show_error(message: str) -> None:
    """Caixa de erro nativa (Windows). Fora do Windows só imprime."""
    print(message, file=sys.stderr, flush=True)
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, WINDOW_TITLE, 0x10)


def _start_backend() -> tuple[object, object, int, dict]:
    data_dir = runtime.user_data_dir()
    runtime.prepare_environment(data_dir=data_dir)
    # cwd = pasta de dados: nenhum caminho relativo (ou .env solto) cai na pasta do .exe
    os.chdir(data_dir)
    db_info = db_bootstrap.bootstrap_database(runtime.alembic_dir())
    db_info["arquivo"] = str(runtime.database_path(data_dir))
    logger.info("Banco: %s", db_info)

    from main import app  # import estático: PyInstaller coleta main.py e dependências

    port = runtime.find_free_port()
    server = runtime.build_server(app, port)
    thread = runtime.start_server_thread(server)
    return server, thread, port, db_info


def _stop_backend(server: object, thread: object) -> None:
    server.should_exit = True  # type: ignore[attr-defined]
    thread.join(timeout=10)  # type: ignore[attr-defined]


def run_smoke() -> int:
    server, thread, port, db_info = _start_backend()
    url = runtime.base_url(port)
    result: dict = {"smoke": "fail", "port": port, "frozen": runtime.is_frozen(), "db": db_info}
    try:
        if not runtime.wait_until_healthy(url + HEALTH_PATH, timeout=60):
            result["erro"] = "health não respondeu em 60 s"
            return 1
        status_health, corpo_health = runtime.http_get(url + HEALTH_PATH)
        status_ui, corpo_ui = runtime.http_get(url + START_PATH)
        result.update(
            health_status=status_health,
            health=json.loads(corpo_health.decode("utf-8")),
            ui_status=status_ui,
            ui_bytes=len(corpo_ui),
        )
        db_ok = (
            Path(db_info["arquivo"]).is_file()
            and db_info["head"] is not None
            and db_info["revisao"] == db_info["head"]
        )
        result["db_ok"] = db_ok
        ok = status_health == 200 and status_ui == 200 and len(corpo_ui) > 0 and db_ok
        result["smoke"] = "ok" if ok else "fail"
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001 — smoke reporta qualquer falha
        result["erro"] = f"{type(exc).__name__}: {exc}"
        return 1
    finally:
        _stop_backend(server, thread)
        _report(result)


def run_window() -> int:
    try:
        server, thread, port, _db = _start_backend()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao iniciar o backend")
        _show_error(f"Falha ao preparar o banco/servidor.\nLog: {_log_path()}\n\n{type(exc).__name__}: {exc}")
        return 1
    url = runtime.base_url(port)
    if not runtime.wait_until_healthy(url + HEALTH_PATH, timeout=60):
        _stop_backend(server, thread)
        _show_error(f"O servidor interno não iniciou. Veja o log em:\n{_log_path()}")
        return 1

    import webview

    try:
        webview.create_window(WINDOW_TITLE, url + START_PATH, width=1280, height=820, min_size=(1024, 640))
        # edgechromium forçado: sem WebView2 falha alto em vez de cair no motor antigo (MSHTML)
        webview.start(gui="edgechromium", private_mode=False)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falha ao abrir a janela")
        _show_error(
            "Não foi possível abrir a janela (WebView2).\n"
            f"Instale o Microsoft Edge WebView2 Runtime: {WEBVIEW2_URL}\n\n"
            f"Detalhe: {type(exc).__name__}: {exc}"
        )
        return 1
    finally:
        _stop_backend(server, thread)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="MotorTributario")
    parser.add_argument("--smoke", action="store_true", help="verifica servidor + UI sem abrir janela")
    args = parser.parse_args(argv)

    log_stream = runtime.ensure_std_streams(_log_path())
    try:
        return run_smoke() if args.smoke else run_window()
    finally:
        if log_stream is not None:
            log_stream.flush()


if __name__ == "__main__":
    sys.exit(main())
