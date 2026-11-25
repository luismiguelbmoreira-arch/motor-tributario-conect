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


@pytest.fixture(autouse=True)
def temp_isolado(request, monkeypatch, tmp_path):
    """Temp próprio do teste (a varredura de sobras não toca no %TEMP% real).

    Nos testes com Popen falso, sem Job Object: o falso não tem handle de processo.
    """
    if request.node.name == "test_edge_real_gera_pdf":
        return
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(rp.tempfile, "tempdir", str(temp))
    monkeypatch.setattr(rp, "_criar_job", lambda: None)


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


class TestHtmlSeguroNoEdge:
    """O Edge roda JS e lê file://: texto do diagnóstico não pode virar HTML."""

    def test_formatadores_escapam_texto_que_nao_e_numero(self):
        assert rp._fmt_moeda("<script>x</script>") == "&lt;script&gt;x&lt;/script&gt;"
        assert rp._fmt_pct('<img src="a">') == "&lt;img src=&quot;a&quot;&gt;"
        assert rp._fmt_moeda("1234.5") == "R$ 1.234,50"  # número segue igual

    def test_campo_numerico_com_html_sai_escapado(self):
        html = rp._gerar_html({"empresa": {"rbt12": "<script>alert(1)</script>"}}, pii=None)
        assert "<script>alert(1)" not in html
        assert "&lt;script&gt;alert(1)" in html

    def test_html_do_edge_tem_csp_logo_apos_head(self, sem_weasyprint, monkeypatch):
        registro = {}
        monkeypatch.setattr(rp, "_achar_navegador_pdf", lambda: "msedge.exe")
        monkeypatch.setattr(rp.subprocess, "Popen", _popen_falso(registro))
        rp.gerar_pdf({}, pii=PII_FICTICIA)
        html = registro["html_bytes"].decode("utf-8-sig")
        assert html.count("Content-Security-Policy") == 1
        assert "default-src 'none'; style-src 'unsafe-inline'" in html
        assert html.index("<head>") < html.index("Content-Security-Policy") < html.index("<style")

    def test_csp_sem_head_vai_no_comeco(self):
        assert rp._com_csp("<p>x</p>").startswith(rp._CSP_EDGE)


class TestSobrasDeAppMorto:
    def _pasta(self, nome, idade_s):
        pasta = Path(rp.tempfile.gettempdir()) / nome
        pasta.mkdir()
        (pasta / "relatorio.html").write_text("dado fictício", encoding="utf-8")
        momento = rp.time.time() - idade_s
        os.utime(pasta, (momento, momento))
        return pasta

    def test_apaga_so_pastas_motor_pdf_antigas(self):
        antiga = self._pasta("motor-pdf-antiga", rp.IDADE_SOBRA_TEMP_S + 60)
        recente = self._pasta("motor-pdf-recente", 5)  # pode ser geração em andamento
        alheia = self._pasta("outro-app-antiga", rp.IDADE_SOBRA_TEMP_S + 60)
        assert rp._varrer_sobras_temp() == 1
        assert not antiga.exists()
        assert recente.exists() and alheia.exists()

    def test_gerar_pdf_varre_antes_de_criar_a_pasta(self, sem_weasyprint, monkeypatch):
        antiga = self._pasta("motor-pdf-sobra", rp.IDADE_SOBRA_TEMP_S + 60)
        registro = {}
        monkeypatch.setattr(rp, "_achar_navegador_pdf", lambda: "msedge.exe")
        monkeypatch.setattr(rp.subprocess, "Popen", _popen_falso(registro))
        rp.gerar_pdf({})
        assert not antiga.exists()


def _cmd_falso():
    """Comando mínimo para o Popen falso: HTML existente no temp do teste."""
    temp = Path(rp.tempfile.gettempdir())
    html = temp / "a.html"
    html.write_text("<p>x</p>", encoding="utf-8")
    return ["msedge.exe", f"--print-to-pdf={temp / 'a.pdf'}", html.as_uri()]


class _JobFalso:
    def __init__(self, entra=True, erro=False):
        self.entra, self.erro = entra, erro
        self.colocados, self.fechado = [], 0

    def colocar_e_retomar(self, proc):
        if self.erro:
            raise OSError("falhou")
        self.colocados.append(proc.pid)
        return self.entra

    def fechar(self):
        self.fechado += 1


class TestJobObject:
    def _preparar(self, monkeypatch, job, **popen):
        registro = {}
        monkeypatch.setattr(rp, "_criar_job", lambda: job)
        monkeypatch.setattr(rp.subprocess, "Popen", _popen_falso(registro, **popen))
        monkeypatch.setattr(rp.subprocess, "run", lambda cmd, **kw: registro.setdefault("run", []).append(cmd))
        return registro

    def test_edge_nasce_suspenso_entra_no_job_e_job_fecha_no_fim(self, monkeypatch):
        job = _JobFalso()
        registro = self._preparar(monkeypatch, job)
        rp._rodar_edge(_cmd_falso())
        assert registro["kwargs"]["creationflags"] & rp._CREATE_SUSPENDED
        assert job.colocados == [4321] and job.fechado == 1

    def test_timeout_com_job_ainda_encerra_arvore_e_fecha_job(self, monkeypatch):
        monkeypatch.setattr(rp.sys, "platform", "win32")
        job = _JobFalso()
        registro = self._preparar(monkeypatch, job, estoura=True)
        with pytest.raises(subprocess.TimeoutExpired):
            rp._rodar_edge(_cmd_falso())
        assert registro["run"] == [["taskkill", "/PID", "4321", "/T", "/F"]]
        assert job.fechado == 1

    def test_sem_entrar_no_job_segue_sem_ele(self, monkeypatch):
        job = _JobFalso(entra=False)
        self._preparar(monkeypatch, job)
        rp._rodar_edge(_cmd_falso())
        assert job.fechado == 1  # fechado uma vez, na hora que não entrou

    def test_erro_ao_retomar_mata_o_processo_suspenso(self, monkeypatch):
        job = _JobFalso(erro=True)
        registro = self._preparar(monkeypatch, job)
        with pytest.raises(OSError):
            rp._rodar_edge(_cmd_falso())
        assert registro.get("kill") is True and job.fechado == 1

    def test_sem_job_nao_cria_suspenso(self, monkeypatch):
        registro = self._preparar(monkeypatch, None)
        rp._rodar_edge(_cmd_falso())
        assert not registro["kwargs"]["creationflags"] & rp._CREATE_SUSPENDED


def test_endpoint_gera_pdf_fora_do_loop_de_eventos(monkeypatch):
    """/relatorio/pdf não pode travar o servidor: a geração roda numa thread."""
    import asyncio

    import main

    vistos = []

    def gerar_falso(diagnostico, pii=None):
        try:
            asyncio.get_running_loop()
            vistos.append("no loop")
        except RuntimeError:
            vistos.append("fora do loop")
        return b"%PDF-1.7 falso"

    monkeypatch.setattr(main, "_RELATORIO_DISPONIVEL", True)
    monkeypatch.setattr(main, "_gerar_pdf", gerar_falso)
    resp = asyncio.run(main.gerar_relatorio_pdf({"diagnostico": {}}, current_user={}))
    assert resp.body == b"%PDF-1.7 falso"
    assert vistos == ["fora do loop"]


@pytest.mark.skipif(
    sys.platform != "win32" or rp._achar_navegador_pdf() is None,
    reason="precisa de Windows com Microsoft Edge",
)
def test_edge_real_gera_pdf(sem_weasyprint):
    pdf = rp.gerar_pdf({}, pii=PII_FICTICIA)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1000
