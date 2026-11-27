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
  → sobe o servidor, checa /health, /ui/login.html, o banco em %APPDATA% e
    (no exe) o backend do cofre do Windows, o PDF do relatório (weasyprint ou
    Edge headless) e, na 1ª execução, o login do admin inicial e o endpoint
    /relatorio/pdf; grava o resultado no log e sai com código 0 (ok) ou 1 (falha).

Segredos por instalação (em %APPDATA%/MotorTributario):
  jwt_secret               → JWT_SECRET_KEY (criado na 1ª execução)
  senha_inicial_admin.txt  → senha do `admin` gerada quando o banco não tem usuários

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
from typing import Optional

if __package__ in (None, ""):
    # Executado como script (PyInstaller): garante PY/ no sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from desktop import db_bootstrap, runtime  # noqa: E402

WINDOW_TITLE = "Motor Tributário Conect"
START_PATH = "/ui/login.html"
HEALTH_PATH = "/health"
LOGIN_PATH = "/auth/login"
RELATORIO_PDF_PATH = "/relatorio/pdf"
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


def _start_backend() -> tuple[object, object, int, dict, str | None]:
    """Devolve (server, thread, porta, db_info, senha_admin_inicial).

    A senha só existe na 1ª execução (banco sem usuários) e NUNCA vai para
    db_info, log ou relatório do smoke.
    """
    data_dir = runtime.user_data_dir()
    runtime.prepare_environment(data_dir=data_dir)  # inclui o JWT secret da instalação
    # cwd = pasta de dados: nenhum caminho relativo (ou .env solto) cai na pasta do .exe
    os.chdir(data_dir)
    db_info = db_bootstrap.bootstrap_database(runtime.alembic_dir())
    db_info["arquivo"] = str(runtime.database_path(data_dir))
    logger.info("Banco: %s", db_info)
    # Depois do bootstrap (tabela users existe) e antes da startup da API
    senha_admin = runtime.preparar_admin_inicial(data_dir)
    if senha_admin is not None:
        logger.info("Admin inicial preparado: %s", runtime.arquivo_senha_inicial(data_dir))

    from main import app  # import estático: PyInstaller coleta main.py e dependências

    port = runtime.find_free_port()
    server = runtime.build_server(app, port)
    thread = runtime.start_server_thread(server)
    return server, thread, port, db_info, senha_admin


def _limpar_senha_do_ambiente() -> None:
    """A API já criou o admin na startup: a senha sai do os.environ."""
    os.environ.pop(runtime.ADMIN_PASSWORD_ENV, None)


def _post_json(url: str, dados: dict, token: Optional[str] = None, timeout: int = 10):
    """POST JSON com urllib. Devolve (status, corpo) ou (None, b"") em erro de rede."""
    import urllib.error
    import urllib.request

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(dados).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except (urllib.error.URLError, OSError):
        return None, b""


def _login_token(url: str, senha: str) -> Optional[str]:
    """POST /auth/login com o admin inicial. Devolve o JWT (nunca vai para log) ou None."""
    status, corpo = _post_json(url + LOGIN_PATH, {"username": runtime.ADMIN_USERNAME, "password": senha})
    if status != 200:
        return None
    try:
        return json.loads(corpo.decode("utf-8")).get("access_token")
    except ValueError:
        return None


def _pdf_ok(url: str, token: Optional[str]) -> dict:
    """Prova que o PDF do relatório sai neste computador, com diagnóstico vazio (sem dado real).

    Sempre testa o motor direto; com token (1ª execução) também o endpoint real.
    O PDF não é gravado em disco.
    """
    from services.relatorio_pdf import gerar_pdf

    info: dict = {}
    try:
        info["pdf_motor_ok"] = gerar_pdf({}).startswith(b"%PDF")
    except RuntimeError as exc:
        info["pdf_motor_ok"] = False
        info["pdf_erro"] = str(exc)[:200]
    if token:
        status, corpo = _post_json(url + RELATORIO_PDF_PATH, {"diagnostico": {}}, token=token, timeout=90)
        info["pdf_endpoint_status"] = status
        info["pdf_endpoint_ok"] = status == 200 and corpo.startswith(b"%PDF")
    return info


def _avisar_primeiro_acesso(data_dir: Path) -> None:
    """Enquanto o arquivo da senha inicial existir, avisa ao abrir o app."""
    arquivo = runtime.arquivo_senha_inicial(data_dir)
    if sys.platform != "win32" or not arquivo.is_file():
        return
    import ctypes

    try:
        conteudo = arquivo.read_text(encoding="utf-8")
    except OSError:
        return
    mensagem = (
        f"{conteudo}\n"
        f"Arquivo: {arquivo}\n\n"
        "Dica: abra o arquivo acima no Bloco de Notas e copie e cole a senha.\n"
        "Este aviso aparece enquanto o arquivo existir."
    )
    ctypes.windll.user32.MessageBoxW(None, mensagem, WINDOW_TITLE, 0x40)


def _stop_backend(server: object, thread: object) -> None:
    server.should_exit = True  # type: ignore[attr-defined]
    thread.join(timeout=10)  # type: ignore[attr-defined]


def run_smoke() -> int:
    server, thread, port, db_info, senha_admin = _start_backend()
    url = runtime.base_url(port)
    result: dict = {"smoke": "fail", "port": port, "frozen": runtime.is_frozen(), "db": db_info}
    try:
        healthy = runtime.wait_until_healthy(url + HEALTH_PATH, timeout=60)
        _limpar_senha_do_ambiente()
        if not healthy:
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
        # Cofre da chave da Anthropic: só o nome do backend, nenhuma credencial é lida.
        # No exe exige o cofre do Windows; em dev/CI só reporta.
        from services.chave_anthropic import nome_backend

        backend = nome_backend()
        cofre_ok = backend == "WinVaultKeyring"
        result.update(cofre_backend=backend, cofre_ok=cofre_ok)
        # Admin inicial (só na 1ª execução): login real com a senha gerada.
        # Em dev/CI o auth já foi importado com outro banco → só reporta.
        admin_ok = True
        token = None
        result["admin_inicial"] = senha_admin is not None
        if senha_admin is not None:
            token = _login_token(url, senha_admin)
            admin_ok = token is not None
            result["admin_login_ok"] = admin_ok
        # PDF do relatório: no exe tem que sair (antes respondia 503 sem GTK).
        pdf = _pdf_ok(url, token)
        result.update(pdf)
        pdf_ok = pdf["pdf_motor_ok"] and pdf.get("pdf_endpoint_ok", True)
        ok = status_health == 200 and status_ui == 200 and len(corpo_ui) > 0 and db_ok
        if runtime.is_frozen():
            ok = ok and cofre_ok and admin_ok and pdf_ok
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
        server, thread, port, _db, _senha = _start_backend()
    except Exception as exc:  # noqa: BLE001
        _limpar_senha_do_ambiente()
        logger.exception("Falha ao iniciar o backend")
        _show_error(f"Falha ao preparar o banco/servidor.\nLog: {_log_path()}\n\n{type(exc).__name__}: {exc}")
        return 1
    url = runtime.base_url(port)
    healthy = runtime.wait_until_healthy(url + HEALTH_PATH, timeout=60)
    _limpar_senha_do_ambiente()
    if not healthy:
        _stop_backend(server, thread)
        _show_error(f"O servidor interno não iniciou. Veja o log em:\n{_log_path()}")
        return 1
    _avisar_primeiro_acesso(runtime.user_data_dir())

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
