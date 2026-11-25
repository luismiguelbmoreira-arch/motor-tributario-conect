"""
Testes do launcher desktop (PY/desktop/launcher.py).

Rodam sem pywebview e sem subir servidor: só as funções puras de porta,
caminhos e ambiente. A integração real é `python desktop/launcher.py --smoke`.
"""
from __future__ import annotations

import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from desktop import launcher  # noqa: E402


def test_import_nao_puxa_webview():
    # CI não instala requirements-desktop.txt: webview só é importado dentro de open_window()
    assert not hasattr(launcher, "webview")
    assert not hasattr(launcher, "uvicorn")


def test_find_free_port_devolve_porta_bindavel():
    porta = launcher.find_free_port()
    assert 1024 <= porta <= 65535
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((launcher.HOST, porta))


def test_host_e_so_loopback():
    assert launcher.HOST == "127.0.0.1"


def test_bundle_dir_em_dev_e_raiz_do_repo():
    raiz = launcher.bundle_dir()
    assert (raiz / "UI" / "login.html").is_file()
    assert (raiz / "PY" / "main.py").is_file()


def test_bundle_dir_frozen_usa_meipass(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert launcher.bundle_dir() == tmp_path


def test_runtime_dir_frozen_fica_ao_lado_do_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "MotorTributario.exe"))
    assert launcher.runtime_dir() == tmp_path / "dados"


_VARS = ("MOTOR_CONECT_UI_DIR", "DATABASE_URL", "MOTOR_CONECT_STORAGE_DIR", "LOG_LEVEL")


@pytest.fixture
def env_limpo(monkeypatch):
    for chave in _VARS:
        monkeypatch.delenv(chave, raising=False)
    return monkeypatch


def test_configure_environment_frozen_define_tudo(env_limpo, tmp_path):
    runtime = tmp_path / "dados"
    definidas = launcher.configure_environment(tmp_path, runtime, frozen=True)

    assert set(definidas) == set(_VARS)
    assert os.environ["MOTOR_CONECT_UI_DIR"] == str(tmp_path / "UI")
    assert os.environ["DATABASE_URL"] == "sqlite:///" + (runtime / "motor_tributario.db").as_posix()
    assert os.environ["MOTOR_CONECT_STORAGE_DIR"] == str(runtime / "auditoria")
    assert runtime.is_dir()


def test_configure_environment_dev_so_define_ui(env_limpo, tmp_path):
    definidas = launcher.configure_environment(tmp_path, tmp_path / "rt", frozen=False)
    assert set(definidas) == {"MOTOR_CONECT_UI_DIR"}
    assert "DATABASE_URL" not in os.environ


def test_configure_environment_nao_sobrescreve(env_limpo, tmp_path):
    env_limpo.setenv("DATABASE_URL", "sqlite:///meu.db")
    definidas = launcher.configure_environment(tmp_path, tmp_path / "rt", frozen=True)
    assert "DATABASE_URL" not in definidas
    assert os.environ["DATABASE_URL"] == "sqlite:///meu.db"


def test_configure_environment_nunca_define_chave_anthropic(env_limpo, tmp_path):
    env_limpo.delenv("ANTHROPIC_API_KEY", raising=False)
    definidas = launcher.configure_environment(tmp_path, tmp_path / "rt", frozen=True)
    assert "ANTHROPIC_API_KEY" not in definidas
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_redirect_std_streams_quando_none(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    log = tmp_path / "sub" / "app.log"
    launcher.redirect_std_streams(log)
    try:
        print("linha de teste")
        sys.stdout.flush()
        assert "linha de teste" in log.read_text(encoding="utf-8")
    finally:
        sys.stdout.close()


def test_redirect_std_streams_nao_mexe_com_console(tmp_path):
    antes = (sys.stdout, sys.stderr)
    launcher.redirect_std_streams(tmp_path / "app.log")
    assert (sys.stdout, sys.stderr) == antes
    assert not (tmp_path / "app.log").exists()


def test_wait_until_ready_falha_rapido_sem_servidor():
    porta = launcher.find_free_port()
    assert launcher.wait_until_ready(f"http://127.0.0.1:{porta}", timeout=0.5, interval=0.1) is False


def test_wait_until_ready_para_se_thread_do_servidor_morreu():
    import threading
    import time

    morta = threading.Thread(target=lambda: None)
    morta.start()
    morta.join()
    porta = launcher.find_free_port()
    inicio = time.monotonic()
    assert launcher.wait_until_ready(f"http://127.0.0.1:{porta}", timeout=10, thread=morta) is False
    assert time.monotonic() - inicio < 2


def test_parse_args():
    args = launcher.parse_args(["--smoke", "--port", "8123"])
    assert args.smoke is True
    assert args.port == 8123
    assert launcher.parse_args([]).port == 0
