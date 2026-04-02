#!/usr/bin/env python3
"""
run_demo.py — Launcher da demo do Motor Tributário Conect
Uso: python run_demo.py
     python run_demo.py --port 8080

Sobe a API FastAPI + serve a UI em /ui/
Abre o browser automaticamente em http://localhost:<porta>/ui/login.html

Credenciais padrão:
  Usuário: admin
  Senha:   Conect@2026!
"""

import argparse
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# ── Diretórios ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.resolve()
PY_DIR = ROOT / "PY"

# ── Argumentos ────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Demo Motor Tributário Conect")
parser.add_argument("--port", type=int, default=8000, help="Porta do servidor (padrão: 8000)")
parser.add_argument("--no-browser", action="store_true", help="Não abrir o browser automaticamente")
args = parser.parse_args()
PORT = args.port


def porta_livre(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def aguardar_servidor(port: int, timeout: int = 20) -> bool:
    """Aguarda até a API responder no /health."""
    import urllib.request
    url = f"http://127.0.0.1:{port}/health"
    inicio = time.time()
    while time.time() - inicio < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main():
    print("=" * 60)
    print("  Motor Tributário Conect 2026-2033 — Demo")
    print("=" * 60)

    if not porta_livre(PORT):
        print(f"\n[ERRO] Porta {PORT} já está em uso.")
        print(f"       Tente: python run_demo.py --port 8080")
        sys.exit(1)

    # Variável de ambiente para o banco de dados ficar em PY/
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{PY_DIR / 'motor_tributario.db'}"}

    print(f"\n  Iniciando servidor na porta {PORT}...")
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "api_motor:app",
            "--host", "0.0.0.0",
            "--port", str(PORT),
            "--log-level", "warning",
        ],
        cwd=str(PY_DIR),
        env=env,
    )

    # Aguarda servidor subir
    url_base = f"http://localhost:{PORT}"
    url_ui = f"{url_base}/ui/login.html"
    if not aguardar_servidor(PORT):
        print("\n[ERRO] Servidor não respondeu em 20s. Verifique se as dependências estão instaladas:")
        print(f"       pip install -r {ROOT / 'PY' / 'requirements.txt'}")
        proc.terminate()
        sys.exit(1)

    print(f"\n  Servidor ativo em {url_base}")
    print(f"\n  Acesse a interface:")
    print(f"    {url_ui}")
    print(f"\n  Credenciais de acesso:")
    print(f"    Usuário: admin")
    print(f"    Senha:   Conect@2026!")
    print(f"\n  API docs: {url_base}/docs")
    print(f"\n  Pressione Ctrl+C para encerrar.")
    print("=" * 60)

    if not args.no_browser:
        time.sleep(0.5)
        webbrowser.open(url_ui)

    try:
        proc.wait()
    except KeyboardInterrupt:
        print("\n\n  Encerrando servidor...")
        proc.terminate()
        proc.wait()
        print("  Servidor encerrado. Até logo!")


if __name__ == "__main__":
    main()
