# -*- coding: utf-8 -*-
"""
tests/test_desktop_runtime.py — Launcher desktop (.exe Windows).

Cobre as funções de apoio (desktop/runtime.py) e o modo --smoke do launcher,
que sobe o servidor real numa thread e checa /health + /ui/login.html.
Nada aqui importa `webview`: roda no CI Linux.
"""

import os
import socket
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from desktop import launcher, runtime


class TestPorta:
    def test_find_free_port_devolve_porta_bindavel(self):
        porta = runtime.find_free_port()
        assert 1024 <= porta <= 65535
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((runtime.HOST, porta))  # não levanta = estava livre

    def test_base_url_usa_loopback(self):
        assert runtime.base_url(5123) == "http://127.0.0.1:5123"


class TestCaminhos:
    def test_dev_resource_root_e_raiz_do_repo(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert runtime.is_frozen() is False
        assert (runtime.resource_root() / "UI" / "login.html").is_file()
        assert runtime.ui_dir() == runtime.resource_root() / "UI"

    def test_frozen_usa_meipass(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert runtime.is_frozen() is True
        assert runtime.resource_root() == tmp_path
        assert runtime.ui_dir() == tmp_path / "UI"

    def test_user_data_dir_appdata(self, tmp_path):
        env = {"APPDATA": str(tmp_path)}
        assert runtime.user_data_dir(env) == tmp_path / "MotorTributario"

    def test_user_data_dir_sem_appdata_cai_no_home(self):
        assert runtime.user_data_dir({}) == Path.home() / ".motor_tributario"

    def test_prepare_environment_nao_sobrescreve(self):
        env = {runtime.UI_DIR_ENV: "X:/custom"}
        runtime.prepare_environment(env)
        assert env[runtime.UI_DIR_ENV] == "X:/custom"

    def test_prepare_environment_define_ui_dir(self):
        env: dict[str, str] = {}
        runtime.prepare_environment(env)
        assert env[runtime.UI_DIR_ENV] == str(runtime.ui_dir())


class TestStreams:
    def test_streams_existentes_nao_mudam(self, tmp_path):
        assert runtime.ensure_std_streams(tmp_path / "x.log") is None

    def test_stdout_none_vai_pro_arquivo(self, monkeypatch, tmp_path):
        log = tmp_path / "logs" / "launcher.log"
        monkeypatch.setattr(sys, "stdout", None)
        monkeypatch.setattr(sys, "stderr", None)
        stream = runtime.ensure_std_streams(log)
        try:
            assert stream is not None
            assert sys.stdout is stream and sys.stderr is stream
            print("linha de teste")
        finally:
            stream.close()
        assert "linha de teste" in log.read_text(encoding="utf-8")


class TestHealth:
    def test_espera_ate_200(self):
        respostas = iter([OSError("recusado"), (503, b""), (200, b"ok")])

        def getter(_url):
            r = next(respostas)
            if isinstance(r, Exception):
                raise r
            return r

        assert runtime.wait_until_healthy("u", timeout=10, getter=getter, sleep=lambda _s: None) is True

    def test_timeout_devolve_false(self):
        relogio = iter([0.0, 0.5, 1.0, 1.5, 2.0])

        def getter(_url):
            raise OSError("recusado")

        ok = runtime.wait_until_healthy(
            "u", timeout=1.0, getter=getter, clock=lambda: next(relogio), sleep=lambda _s: None
        )
        assert ok is False


class TestServidor:
    def test_build_server_config_sem_imports_dinamicos(self):
        server = runtime.build_server(object(), 5555)
        cfg = server.config
        assert (cfg.host, cfg.port) == ("127.0.0.1", 5555)
        assert (cfg.loop, cfg.http, cfg.ws) == ("asyncio", "h11", "none")
        assert cfg.log_config is None


class TestAmbienteDesktop:
    def test_sqlite_url_absoluta_com_barras_normais(self, tmp_path):
        url = runtime.sqlite_url(tmp_path / "x.db")
        assert url.startswith("sqlite:///")
        assert "\\" not in url
        assert Path(url[len("sqlite:///"):]) == (tmp_path / "x.db").resolve()

    def test_desktop_environment_aponta_tudo_para_data_dir(self, tmp_path):
        env = runtime.desktop_environment(tmp_path)
        assert env[runtime.DESKTOP_FLAG_ENV] == "1"
        assert env["DATABASE_URL"] == runtime.sqlite_url(tmp_path / runtime.DB_FILENAME)
        assert env[runtime.STORAGE_DIR_ENV] == str(tmp_path / "auditoria")

    def test_prepare_environment_com_data_dir_forca_banco(self, tmp_path):
        dados = tmp_path / "MotorTributario"
        env = {"DATABASE_URL": "sqlite:///outro.db"}
        runtime.prepare_environment(env, data_dir=dados)
        assert dados.is_dir()
        assert env["DATABASE_URL"] == runtime.sqlite_url(dados / runtime.DB_FILENAME)

    def test_alembic_dir_dev(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert (runtime.alembic_dir() / "env.py").is_file()
        assert list((runtime.alembic_dir() / "versions").glob("*.py"))

    def test_alembic_dir_frozen(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        assert runtime.alembic_dir() == tmp_path / "alembic"


@pytest.fixture
def desktop_isolado(monkeypatch, tmp_path):
    """O launcher muda os.environ e o cwd; tudo é desfeito no fim do teste.

    APPDATA vai para tmp: o teste nunca toca o %APPDATA% real.
    patch.dict tira snapshot do ambiente inteiro e o restaura no fim: variáveis
    que o launcher CRIA (ex.: MOTOR_CONECT_DESKTOP) somem. Sem isso a flag vazava
    para os testes seguintes e o extrator passaria a ler o cofre real do Windows.
    """
    with mock.patch.dict(os.environ):
        os.environ["APPDATA"] = str(tmp_path)
        for nome in ("DATABASE_URL", runtime.STORAGE_DIR_ENV, runtime.DESKTOP_FLAG_ENV, runtime.UI_DIR_ENV):
            os.environ.pop(nome, None)
        monkeypatch.chdir(tmp_path)
        yield tmp_path


class TestLauncherSmoke:
    def test_smoke_sobe_servidor_real_e_serve_ui(self, desktop_isolado, capsys):
        assert launcher.main(["--smoke"]) == 0
        saida = capsys.readouterr().out
        assert '"smoke": "ok"' in saida
        assert '"ui_status": 200' in saida
        assert '"db_ok": true' in saida
        assert '"cofre_backend":' in saida  # dev/CI só reporta; no exe precisa ser WinVaultKeyring
        assert (desktop_isolado / "MotorTributario" / runtime.DB_FILENAME).is_file()

    def test_smoke_falha_quando_health_nao_responde(self, desktop_isolado, monkeypatch, capsys):
        monkeypatch.setattr(runtime, "wait_until_healthy", lambda *a, **k: False)
        assert launcher.run_smoke() == 1
        assert '"smoke": "fail"' in capsys.readouterr().out
