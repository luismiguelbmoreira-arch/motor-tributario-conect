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


class TestUiEmpacotada:
    """motor_tributario.spec leva da UI/ só os tipos da lista (não a pasta inteira)."""

    def test_so_tipos_da_lista_e_licencas(self, tmp_path):
        ui = tmp_path / "UI"
        (ui / "vendor" / "inter").mkdir(parents=True)
        for nome in ("index.html", "app.js", "estilo.css", "vendor/inter/Inter.woff2", "vendor/inter/LICENSE",
                     "cliente.pdf", "rascunho.txt", "banco.db", ".env", "vendor/README.md"):
            (ui / nome).write_bytes(b"x")
        pares = runtime.ui_datas(ui)
        nomes = sorted(Path(origem).name for origem, _ in pares)
        assert nomes == ["Inter.woff2", "LICENSE", "app.js", "estilo.css", "index.html"]
        destinos = {Path(origem).name: destino for origem, destino in pares}
        assert destinos["Inter.woff2"] == "UI/vendor/inter"  # mantém a subpasta
        assert destinos["index.html"] == "UI"

    def test_todo_arquivo_da_ui_do_repo_entra_no_exe(self):
        # Tipo novo em UI/ (ex.: .png, .svg) quebra a tela do exe sem aviso: falha aqui antes.
        ui = Path(__file__).resolve().parents[2] / "UI"
        fora = [
            p.relative_to(ui).as_posix()
            for p in ui.rglob("*")
            if p.is_file() and not runtime.ui_arquivo_empacotado(p) and p.name != "README.md"
        ]
        assert fora == []


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


class TestSegredosPorInstalacao:
    def test_jwt_secret_persiste_entre_inicios(self, tmp_path):
        s1 = runtime.garantir_jwt_secret(tmp_path)
        s2 = runtime.garantir_jwt_secret(tmp_path)
        assert s1 == s2
        assert len(s1) == 64 and int(s1, 16) >= 0
        assert (tmp_path / runtime.JWT_SECRET_FILENAME).read_text(encoding="ascii") == s1

    def test_jwt_secret_diferente_por_instalacao(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert runtime.garantir_jwt_secret(a) != runtime.garantir_jwt_secret(b)

    @pytest.mark.parametrize("conteudo", ["", "curto", "z" * 64, "\n"])
    def test_jwt_secret_invalido_e_regerado(self, tmp_path, conteudo):
        (tmp_path / runtime.JWT_SECRET_FILENAME).write_text(conteudo, encoding="ascii")
        novo = runtime.garantir_jwt_secret(tmp_path)
        assert len(novo) == 64 and novo != conteudo
        assert runtime.garantir_jwt_secret(tmp_path) == novo

    def test_jwt_secret_com_quebra_de_linha_e_aceito(self, tmp_path):
        valor = "ab" * 32
        (tmp_path / runtime.JWT_SECRET_FILENAME).write_text(valor + "\r\n", encoding="ascii")
        assert runtime.garantir_jwt_secret(tmp_path) == valor

    def test_prepare_environment_arquivo_vence_ambiente(self, tmp_path):
        env = {runtime.JWT_SECRET_ENV: "segredo-do-env"}
        runtime.prepare_environment(env, data_dir=tmp_path)
        assert env[runtime.JWT_SECRET_ENV] != "segredo-do-env"
        assert env[runtime.JWT_SECRET_ENV] == (tmp_path / runtime.JWT_SECRET_FILENAME).read_text(encoding="ascii")

    def test_prepare_environment_sem_data_dir_nao_cria_secret(self):
        env: dict[str, str] = {}
        runtime.prepare_environment(env)
        assert runtime.JWT_SECRET_ENV not in env

    def test_desktop_environment_continua_puro(self, tmp_path):
        runtime.desktop_environment(tmp_path)
        assert not (tmp_path / runtime.JWT_SECRET_FILENAME).exists()


def _banco_com_users(path: Path, n: int) -> None:
    import sqlite3

    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
    for i in range(n):
        con.execute("INSERT INTO users (username) VALUES (?)", (f"u{i}",))
    con.commit()
    con.close()


class TestAdminInicial:
    def test_banco_inexistente_ou_sem_tabela_conta_como_vazio(self, tmp_path):
        assert runtime.banco_sem_usuarios(tmp_path / "nao_existe.db") is True
        import sqlite3

        sem_tabela = tmp_path / "x.db"
        sqlite3.connect(str(sem_tabela)).close()
        assert runtime.banco_sem_usuarios(sem_tabela) is True

    def test_banco_vazio_gera_senha_arquivo_e_env(self, tmp_path):
        _banco_com_users(tmp_path / runtime.DB_FILENAME, 0)
        env: dict[str, str] = {}
        senha = runtime.preparar_admin_inicial(tmp_path, env)
        assert senha and len(senha) >= 16
        assert env[runtime.ADMIN_PASSWORD_ENV] == senha
        texto = runtime.arquivo_senha_inicial(tmp_path).read_text(encoding="utf-8")
        assert senha in texto and "admin" in texto

    def test_senha_diferente_por_instalacao(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        assert runtime.preparar_admin_inicial(a, {}) != runtime.preparar_admin_inicial(b, {})

    def test_banco_com_usuarios_nao_mexe_em_nada(self, tmp_path):
        _banco_com_users(tmp_path / runtime.DB_FILENAME, 1)
        env: dict[str, str] = {}
        assert runtime.preparar_admin_inicial(tmp_path, env) is None
        assert runtime.ADMIN_PASSWORD_ENV not in env
        assert not runtime.arquivo_senha_inicial(tmp_path).exists()


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
        # PDF do smoke: Edge falso (o teste real do Edge fica em test_relatorio_pdf_motor.py)
        from services import relatorio_pdf

        monkeypatch.setattr(relatorio_pdf, "_tentar_importar_weasyprint", lambda: False)
        monkeypatch.setattr(relatorio_pdf, "_achar_navegador_pdf", lambda: "msedge.exe")
        monkeypatch.setattr(relatorio_pdf, "_pdf_via_navegador", lambda html, nav: b"%PDF-falso")
        yield tmp_path


class TestLauncherSmoke:
    def test_smoke_sobe_servidor_real_e_serve_ui(self, desktop_isolado, capsys):
        assert launcher.main(["--smoke"]) == 0
        saida = capsys.readouterr().out
        assert '"smoke": "ok"' in saida
        assert '"ui_status": 200' in saida
        assert '"db_ok": true' in saida
        assert '"cofre_backend":' in saida  # dev/CI só reporta; no exe precisa ser WinVaultKeyring
        dados = desktop_isolado / "MotorTributario"
        assert (dados / runtime.DB_FILENAME).is_file()
        # 1ª execução: secret e senha inicial criados; a senha nunca sai no relatório
        assert (dados / runtime.JWT_SECRET_FILENAME).is_file()
        assert '"admin_inicial": true' in saida
        senha = runtime.arquivo_senha_inicial(dados).read_text(encoding="utf-8").split("Senha:")[1].split()[0]
        assert senha not in saida
        assert runtime.ADMIN_PASSWORD_ENV not in os.environ  # limpa depois da startup
        assert '"pdf_motor_ok": true' in saida

    def test_smoke_reporta_pdf_sem_motor(self, desktop_isolado, capsys, monkeypatch):
        from services import relatorio_pdf

        monkeypatch.setattr(relatorio_pdf, "_achar_navegador_pdf", lambda: None)
        assert launcher.run_smoke() == 0  # fora do exe só reporta
        saida = capsys.readouterr().out
        assert '"pdf_motor_ok": false' in saida
        assert "não instalado" in saida

    def test_pdf_ok_com_token_chama_endpoint(self, monkeypatch, desktop_isolado):
        from services import relatorio_pdf  # noqa: F401 — fixture já trocou o Edge

        chamadas = []

        def post(url, dados, token=None, timeout=10):
            chamadas.append((url, dados, token))
            return 200, b"%PDF-falso"

        monkeypatch.setattr(launcher, "_post_json", post)
        info = launcher._pdf_ok("http://127.0.0.1:1", "tok")
        assert info == {"pdf_motor_ok": True, "pdf_endpoint_status": 200, "pdf_endpoint_ok": True}
        assert chamadas == [("http://127.0.0.1:1/relatorio/pdf", {"diagnostico": {}}, "tok")]

    def test_segundo_smoke_reaproveita_secret_e_nao_gera_senha(self, desktop_isolado, capsys, monkeypatch):
        dados = desktop_isolado / "MotorTributario"
        dados.mkdir()
        _banco_com_users(dados / runtime.DB_FILENAME, 1)
        secret = runtime.garantir_jwt_secret(dados)
        assert launcher.main(["--smoke"]) == 0
        saida = capsys.readouterr().out
        assert '"admin_inicial": false' in saida
        assert os.environ[runtime.JWT_SECRET_ENV] == secret
        assert not runtime.arquivo_senha_inicial(dados).exists()

    def test_smoke_falha_quando_health_nao_responde(self, desktop_isolado, monkeypatch, capsys):
        monkeypatch.setattr(runtime, "wait_until_healthy", lambda *a, **k: False)
        assert launcher.run_smoke() == 1
        assert '"smoke": "fail"' in capsys.readouterr().out
