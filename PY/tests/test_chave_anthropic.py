# -*- coding: utf-8 -*-
"""
tests/test_chave_anthropic.py — ANTHROPIC_API_KEY por usuário (cofre do Windows).

Nenhum teste toca o Credential Manager real: `_backend` é trocado por um cofre
em memória. Fora do modo desktop o cofre nunca é consultado.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services import chave_anthropic as ca

CHAVE = "sk-ant-api03-" + "A" * 40 + "wXyZ"
CHAVE_ENV = "sk-ant-api03-" + "B" * 40 + "eNvV"


class CofreFake:
    def __init__(self):
        self.dados: dict[tuple[str, str], str] = {}
        self.leituras = 0

    def get_password(self, servico, usuario):
        self.leituras += 1
        return self.dados.get((servico, usuario))

    def set_password(self, servico, usuario, valor):
        self.dados[(servico, usuario)] = valor

    def delete_password(self, servico, usuario):
        del self.dados[(servico, usuario)]


class CofreQuebrado(CofreFake):
    def get_password(self, servico, usuario):
        raise OSError("cofre travado")

    def set_password(self, servico, usuario, valor):
        raise OSError("cofre travado")


@pytest.fixture
def cofre(monkeypatch):
    fake = CofreFake()
    monkeypatch.setattr(ca, "_backend", lambda: fake)
    monkeypatch.delenv(ca.ENV_VAR, raising=False)
    monkeypatch.delenv(ca.DESKTOP_FLAG_ENV, raising=False)
    return fake


@pytest.fixture
def desktop(cofre, monkeypatch):
    monkeypatch.setenv(ca.DESKTOP_FLAG_ENV, "1")
    return cofre


class TestResolucao:
    def test_fora_do_desktop_so_ambiente_e_nunca_le_cofre(self, cofre, monkeypatch):
        cofre.dados[(ca.KEYRING_SERVICE, ca.KEYRING_USERNAME)] = CHAVE
        assert ca.obter_chave_anthropic() is None
        monkeypatch.setenv(ca.ENV_VAR, CHAVE_ENV)
        assert ca.obter_chave_anthropic() == CHAVE_ENV
        assert cofre.leituras == 0

    def test_desktop_cofre_vence_ambiente(self, desktop, monkeypatch):
        monkeypatch.setenv(ca.ENV_VAR, CHAVE_ENV)
        desktop.dados[(ca.KEYRING_SERVICE, ca.KEYRING_USERNAME)] = CHAVE
        assert ca.obter_chave_anthropic() == CHAVE

    def test_desktop_sem_cofre_cai_no_ambiente(self, desktop, monkeypatch):
        monkeypatch.setenv(ca.ENV_VAR, CHAVE_ENV)
        assert ca.obter_chave_anthropic() == CHAVE_ENV

    def test_cofre_quebrado_nao_derruba(self, monkeypatch, caplog):
        monkeypatch.setattr(ca, "_backend", lambda: CofreQuebrado())
        monkeypatch.setenv(ca.DESKTOP_FLAG_ENV, "1")
        monkeypatch.delenv(ca.ENV_VAR, raising=False)
        with caplog.at_level(logging.WARNING):
            assert ca.obter_chave_anthropic() is None
        assert "OSError" in caplog.text

    def test_nunca_grava_em_os_environ(self, desktop):
        desktop.dados[(ca.KEYRING_SERVICE, ca.KEYRING_USERNAME)] = CHAVE
        ca.obter_chave_anthropic()
        assert ca.ENV_VAR not in os.environ

    def test_sem_keyring_instalado(self, monkeypatch):
        monkeypatch.setattr(ca, "_backend", lambda: None)
        monkeypatch.setenv(ca.DESKTOP_FLAG_ENV, "1")
        monkeypatch.delenv(ca.ENV_VAR, raising=False)
        assert ca.obter_chave_anthropic() is None
        assert ca.status_chave()["editavel"] is False
        with pytest.raises(ca.CofreIndisponivel):
            ca.salvar_chave_anthropic(CHAVE)


class TestStatus:
    def test_status_so_metadados(self, desktop):
        desktop.dados[(ca.KEYRING_SERVICE, ca.KEYRING_USERNAME)] = CHAVE
        st = ca.status_chave()
        assert st == {"configurada": True, "origem": "cofre_windows", "final": "wXyZ", "editavel": True}
        assert CHAVE not in repr(st)

    def test_status_ambiente_fora_do_desktop(self, cofre, monkeypatch):
        monkeypatch.setenv(ca.ENV_VAR, CHAVE_ENV)
        st = ca.status_chave()
        assert st["origem"] == "ambiente" and st["editavel"] is False

    def test_chave_curta_nao_mostra_final(self, cofre, monkeypatch):
        monkeypatch.setenv(ca.ENV_VAR, "sk-fake")
        assert ca.status_chave()["final"] is None


class TestSalvarApagar:
    def test_salvar_e_apagar(self, desktop, caplog):
        with caplog.at_level(logging.DEBUG):
            ca.salvar_chave_anthropic("  " + CHAVE + "\n")
        assert desktop.dados[(ca.KEYRING_SERVICE, ca.KEYRING_USERNAME)] == CHAVE
        assert CHAVE not in caplog.text
        assert ca.apagar_chave_anthropic() is True
        assert ca.apagar_chave_anthropic() is False

    @pytest.mark.parametrize("ruim", ["", "abc", "sk-ant-curta", "sk-ant-" + "x" * 400, "sk-ant-api03 com espaco xxxxxxxx"])
    def test_formato_invalido_nao_ecoa(self, desktop, ruim):
        with pytest.raises(ca.ChaveInvalida) as exc:
            ca.salvar_chave_anthropic(ruim)
        if ruim:
            assert ruim not in str(exc.value)
        assert not desktop.dados

    def test_fora_do_desktop_recusa(self, cofre):
        with pytest.raises(ca.CofreIndisponivel):
            ca.salvar_chave_anthropic(CHAVE)
        with pytest.raises(ca.CofreIndisponivel):
            ca.apagar_chave_anthropic()


class TestExtrator:
    def test_extrator_usa_cofre_no_desktop(self, desktop, monkeypatch):
        from services import extrator_pdfs

        desktop.dados[(ca.KEYRING_SERVICE, ca.KEYRING_USERNAME)] = CHAVE
        recebido = {}

        class Parar(Exception):
            pass

        def cliente_fake(api_key):
            recebido["api_key"] = api_key
            raise Parar

        monkeypatch.setattr(extrator_pdfs.anthropic, "Anthropic", cliente_fake)
        with pytest.raises(Parar):
            extrator_pdfs.processar_pdfs_bytes([b"%PDF-1.4"])
        assert recebido["api_key"] == CHAVE

    def test_extrator_sem_chave_mensagem_mantem_nome_da_variavel(self, desktop):
        from services import extrator_pdfs

        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            extrator_pdfs.processar_pdfs_bytes([b"%PDF-1.4"])


# ── Rotas /settings/anthropic-key ────────────────────────────────────────


class TestRotas:
    def test_get_404_fora_do_desktop(self, cofre, client_autenticado, monkeypatch):
        monkeypatch.setenv(ca.ENV_VAR, CHAVE_ENV)
        r = client_autenticado.get("/settings/anthropic-key")
        assert r.status_code == 404
        assert "eNvV" not in r.text

    def test_get_desktop_sem_chave(self, desktop, client_autenticado):
        r = client_autenticado.get("/settings/anthropic-key")
        assert r.status_code == 200
        assert r.json() == {"configurada": False, "origem": None, "final": None, "editavel": True}

    def test_put_delete_404_fora_do_desktop(self, cofre, client_autenticado):
        assert client_autenticado.put("/settings/anthropic-key", json={"chave": CHAVE}).status_code == 404
        assert client_autenticado.delete("/settings/anthropic-key").status_code == 404
        assert not cofre.dados

    def test_sem_token(self, cofre, client_sem_auth):
        assert client_sem_auth.get("/settings/anthropic-key").status_code in (401, 403)
        assert client_sem_auth.put("/settings/anthropic-key", json={"chave": CHAVE}).status_code in (401, 403)

    def test_put_get_delete_no_desktop_sem_vazar(self, desktop, client_autenticado, caplog):
        with caplog.at_level(logging.DEBUG):
            r = client_autenticado.put("/settings/anthropic-key", json={"chave": CHAVE})
            assert r.status_code == 200, r.text
            assert CHAVE not in r.text
            assert r.json() == {"configurada": True, "origem": "cofre_windows", "final": "wXyZ", "editavel": True}

            g = client_autenticado.get("/settings/anthropic-key")
            assert CHAVE not in g.text and g.json()["final"] == "wXyZ"

            d = client_autenticado.delete("/settings/anthropic-key")
            assert d.status_code == 200 and d.json()["configurada"] is False
        assert CHAVE not in caplog.text

    @pytest.mark.parametrize(
        "corpo",
        [
            {"chave": "sk-ant-curta-demais"},
            {"chave": "nao-e-chave-" + "Z" * 30},
            {"chave": "sk-ant-api03-" + "Q" * 30, "extra": "x"},
        ],
    )
    def test_put_invalido_nao_ecoa_chave(self, desktop, client_autenticado, corpo, caplog):
        with caplog.at_level(logging.DEBUG):
            r = client_autenticado.put("/settings/anthropic-key", json=corpo)
        assert r.status_code == 422
        assert corpo["chave"] not in r.text
        assert corpo["chave"] not in caplog.text
        assert not desktop.dados

    def test_put_cofre_quebrado_503_generico(self, monkeypatch, client_autenticado):
        monkeypatch.setattr(ca, "_backend", lambda: CofreQuebrado())
        monkeypatch.setenv(ca.DESKTOP_FLAG_ENV, "1")
        r = client_autenticado.put("/settings/anthropic-key", json={"chave": CHAVE})
        assert r.status_code == 503
        assert CHAVE not in r.text
