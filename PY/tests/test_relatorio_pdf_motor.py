# -*- coding: utf-8 -*-
"""tests/test_relatorio_pdf_motor.py — escolha do motor de PDF (weasyprint → Edge headless).

Os testes de unidade não abrem o Edge: subprocess.Popen é trocado por um falso.
Só `test_edge_real_gera_pdf` abre o Edge de verdade, e só no Windows com Edge.
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from services import relatorio_pdf as rp  # noqa: E402

PII_FICTICIA = {"razao_social": "Empresa Fictícia Ação Ltda", "cnpj": "11.222.333/0001-81"}


@pytest.fixture
def sem_weasyprint(monkeypatch):
    monkeypatch.setattr(rp, "_tentar_importar_weasyprint", lambda: False)
    monkeypatch.setattr(rp, "_WeasyprintHTML", None)


def _popen_falso(registro, conteudo=b"%PDF-1.7 falso", estoura=False):
    """subprocess.Popen falso: guarda o comando e o HTML e grava o PDF pedido.

    Com estoura=True, o 1º wait() levanta TimeoutExpired (Edge travado).
    """

    class PopenFalso:
        pid = 4321

        def __init__(self, cmd, **kwargs):
            registro["cmd"] = cmd
            registro["kwargs"] = kwargs
            html = Path(url2pathname(urlparse(cmd[-1]).path))
            registro["html_bytes"] = html.read_bytes()
            registro["pasta"] = html.parent
            saida = next(a.split("=", 1)[1] for a in cmd if a.startswith("--print-to-pdf="))
            if conteudo is not None and not estoura:
                Path(saida).write_bytes(conteudo)

        def wait(self, timeout=None):
            registro.setdefault("waits", []).append(timeout)
            if estoura and len(registro["waits"]) == 1:
                raise subprocess.TimeoutExpired(registro["cmd"], timeout)
            return 0

        def kill(self):
            registro["kill"] = True

    return PopenFalso


class TestAcharNavegador:
    def test_fora_do_windows_nao_procura(self, monkeypatch):
        monkeypatch.setattr(rp.sys, "platform", "linux")
        assert rp._achar_navegador_pdf() is None

    def test_windows_acha_pelas_pastas_padrao(self, monkeypatch, tmp_path):
        edge = tmp_path / rp._EDGE_RELATIVO
        edge.parent.mkdir(parents=True)
        edge.write_bytes(b"")
        monkeypatch.setattr(rp.sys, "platform", "win32")
        monkeypatch.setattr(rp, "_edge_no_registro", lambda: None)
        for var in ("ProgramFiles(x86)", "ProgramFiles"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert rp._achar_navegador_pdf() == str(edge)

    def test_windows_sem_edge(self, monkeypatch, tmp_path):
        monkeypatch.setattr(rp.sys, "platform", "win32")
        monkeypatch.setattr(rp, "_edge_no_registro", lambda: None)
        for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
            monkeypatch.setenv(var, str(tmp_path / "vazio"))
        assert rp._achar_navegador_pdf() is None


class TestGerarPdfFallback:
    def test_sem_motor_nenhum_diz_nao_instalado(self, sem_weasyprint, monkeypatch):
        # main.py responde 503 (não 500) quando a mensagem tem "não instalado"
        monkeypatch.setattr(rp, "_achar_navegador_pdf", lambda: None)
        with pytest.raises(RuntimeError, match="não instalado"):
            rp.gerar_pdf({})

    def test_sem_weasyprint_usa_edge(self, sem_weasyprint, monkeypatch):
        registro = {}
        monkeypatch.setattr(rp, "_achar_navegador_pdf", lambda: "C:/fake/msedge.exe")
        monkeypatch.setattr(rp.subprocess, "Popen", _popen_falso(registro))
        assert rp.gerar_pdf({}, pii=PII_FICTICIA) == b"%PDF-1.7 falso"
        cmd = registro["cmd"]
        assert cmd[0] == "C:/fake/msedge.exe"
        assert "--headless" in cmd and "--no-pdf-header-footer" in cmd
        perfil = next(a.split("=", 1)[1] for a in cmd if a.startswith("--user-data-dir="))
        assert Path(perfil).parent == registro["pasta"]  # perfil descartável, não o do usuário
        assert registro["waits"] == [rp.TIMEOUT_NAVEGADOR_S]
        kwargs = registro["kwargs"]
        assert kwargs["stdout"] is subprocess.DEVNULL and kwargs["stderr"] is subprocess.DEVNULL
        assert "shell" not in kwargs
        # HTML em UTF-8 com BOM e com os acentos intactos
        assert registro["html_bytes"].startswith(b"\xef\xbb\xbf")
        assert "Fictícia Ação" in registro["html_bytes"].decode("utf-8-sig")

    def test_pasta_temporaria_com_dado_do_cliente_e_apagada(self, sem_weasyprint, monkeypatch):
        registro = {}
        monkeypatch.setattr(rp, "_achar_navegador_pdf", lambda: "msedge.exe")
        monkeypatch.setattr(rp.subprocess, "Popen", _popen_falso(registro))
        rp.gerar_pdf({}, pii=PII_FICTICIA)
        assert not registro["pasta"].exists()

    def test_edge_sem_arquivo_vira_falha_500(self, sem_weasyprint, monkeypatch):
        registro = {}
        monkeypatch.setattr(rp, "_achar_navegador_pdf", lambda: "msedge.exe")
        monkeypatch.setattr(rp.subprocess, "Popen", _popen_falso(registro, conteudo=None))
        with pytest.raises(RuntimeError) as exc:
            rp.gerar_pdf({})
        assert "não instalado" not in str(exc.value)
        assert not registro["pasta"].exists()

    def test_saida_que_nao_e_pdf_falha(self, sem_weasyprint, monkeypatch):
        monkeypatch.setattr(rp, "_achar_navegador_pdf", lambda: "msedge.exe")
        monkeypatch.setattr(rp.subprocess, "Popen", _popen_falso({}, conteudo=b"<html>erro"))
        with pytest.raises(RuntimeError, match="Falha"):
            rp.gerar_pdf({})

    def test_timeout_encerra_arvore_pelo_pid_e_apaga_pasta(self, sem_weasyprint, monkeypatch, caplog):
        registro = {}
        chamadas_run = []
        monkeypatch.setattr(rp.sys, "platform", "win32")
        monkeypatch.setattr(rp, "_achar_navegador_pdf", lambda: "msedge.exe")
        monkeypatch.setattr(rp.subprocess, "Popen", _popen_falso(registro, estoura=True))
        monkeypatch.setattr(rp.subprocess, "run", lambda cmd, **kw: chamadas_run.append(cmd))
        with pytest.raises(RuntimeError, match="Falha"):
            rp.gerar_pdf({}, pii=PII_FICTICIA)
        # árvore inteira, pelo PID que o código abriu — nunca por nome (/IM)
        assert chamadas_run == [["taskkill", "/PID", "4321", "/T", "/F"]]
        assert registro.get("kill") is True
        assert not registro["pasta"].exists()  # HTML com dado do cliente não fica em temp
        assert "motor-pdf-" not in caplog.text and "Fictícia" not in caplog.text
        assert "TimeoutExpired" in caplog.text

    def test_pasta_presa_gera_aviso_sem_caminho(self, monkeypatch, tmp_path):
        # registro direto: outros testes da suíte mudam o nível/propagação do logger
        avisos = []
        pasta = tmp_path / "motor-pdf-presa"
        pasta.mkdir()
        monkeypatch.setattr(rp.shutil, "rmtree", lambda *a, **k: None)  # arquivo "em uso"
        monkeypatch.setattr(rp.time, "sleep", lambda s: None)
        monkeypatch.setattr(rp.logger, "warning", lambda msg, *a: avisos.append(msg % a if a else msg))
        rp._apagar_pasta(pasta)
        assert len(avisos) == 1 and "não pôde ser apagada" in avisos[0]
        assert "motor-pdf-" not in avisos[0]


@pytest.mark.skipif(
    sys.platform != "win32" or rp._achar_navegador_pdf() is None,
    reason="precisa de Windows com Microsoft Edge",
)
def test_edge_real_gera_pdf(sem_weasyprint):
    pdf = rp.gerar_pdf({}, pii=PII_FICTICIA)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
