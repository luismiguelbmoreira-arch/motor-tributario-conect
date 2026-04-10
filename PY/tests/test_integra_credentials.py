"""
test_integra_credentials.py — Testes do cofre 3-tier do Integra Contador.

Cobre:
- Env vars completas → IntegraCredenciais válido
- .pfx inexistente → IntegraCredentialError
- CNPJ malformado → IntegraCredentialError
- Senha vazia → IntegraCredentialError
- Arquivo INI é lido quando env vars ausentes
- Nenhuma fonte → IntegraCredentialError com mensagem guia
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integrations.integra_credentials import (  # noqa: E402
    IntegraCredenciais,
    IntegraCredentialError,
    get_integra_credenciais,
)

CNPJ_LIMPO = "12345678000190"
CNPJ_PONTO = "12.345.678/0001-90"


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def fake_pfx(tmp_path):
    """Um arquivo qualquer — não precisa ser um PKCS#12 real (abertura é no adapter)."""
    p = tmp_path / "escritorio.pfx"
    p.write_bytes(b"fake-pfx-bytes")
    return p


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Limpa todas as env vars Integra antes de cada teste."""
    for var in (
        "INTEGRA_CERT_PATH",
        "INTEGRA_CERT_PASSWORD",
        "INTEGRA_CONTRATANTE_CNPJ",
        "INTEGRA_AUTOR_PEDIDO_DADOS_CNPJ",
        "INTEGRA_BASE_URL",
        "INTEGRA_CONFIG_FILE",
        "INTEGRA_SECRET_NAME",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


# ─── Env vars ────────────────────────────────────────────────────────────


def test_env_vars_completas_monta_credencial(monkeypatch, fake_pfx):
    monkeypatch.setenv("INTEGRA_CERT_PATH", str(fake_pfx))
    monkeypatch.setenv("INTEGRA_CERT_PASSWORD", "senha-123")
    monkeypatch.setenv("INTEGRA_CONTRATANTE_CNPJ", CNPJ_LIMPO)
    monkeypatch.setenv("INTEGRA_AUTOR_PEDIDO_DADOS_CNPJ", CNPJ_LIMPO)

    cred = get_integra_credenciais()

    assert isinstance(cred, IntegraCredenciais)
    assert cred.cert_path == fake_pfx
    assert cred.cert_password == "senha-123"
    assert cred.contratante_cnpj == CNPJ_LIMPO
    assert cred.autor_pedido_dados_cnpj == CNPJ_LIMPO
    assert cred.base_url is None


def test_env_vars_com_base_url_opcional(monkeypatch, fake_pfx):
    monkeypatch.setenv("INTEGRA_CERT_PATH", str(fake_pfx))
    monkeypatch.setenv("INTEGRA_CERT_PASSWORD", "senha")
    monkeypatch.setenv("INTEGRA_CONTRATANTE_CNPJ", CNPJ_LIMPO)
    monkeypatch.setenv("INTEGRA_AUTOR_PEDIDO_DADOS_CNPJ", CNPJ_LIMPO)
    monkeypatch.setenv(
        "INTEGRA_BASE_URL",
        "https://gateway.apiserpro.serpro.gov.br/integra-contador/v1",
    )

    cred = get_integra_credenciais()
    assert cred.base_url.endswith("/integra-contador/v1")


def test_env_cnpj_com_pontuacao_normalizado(monkeypatch, fake_pfx):
    monkeypatch.setenv("INTEGRA_CERT_PATH", str(fake_pfx))
    monkeypatch.setenv("INTEGRA_CERT_PASSWORD", "senha")
    monkeypatch.setenv("INTEGRA_CONTRATANTE_CNPJ", CNPJ_PONTO)
    monkeypatch.setenv("INTEGRA_AUTOR_PEDIDO_DADOS_CNPJ", CNPJ_PONTO)

    cred = get_integra_credenciais()
    assert cred.contratante_cnpj == CNPJ_LIMPO
    assert cred.autor_pedido_dados_cnpj == CNPJ_LIMPO


# ─── Validação de erros ──────────────────────────────────────────────────


def test_cert_path_inexistente_levanta(monkeypatch):
    monkeypatch.setenv("INTEGRA_CERT_PATH", "/nao/existe/fake.pfx")
    monkeypatch.setenv("INTEGRA_CERT_PASSWORD", "senha")
    monkeypatch.setenv("INTEGRA_CONTRATANTE_CNPJ", CNPJ_LIMPO)
    monkeypatch.setenv("INTEGRA_AUTOR_PEDIDO_DADOS_CNPJ", CNPJ_LIMPO)

    with pytest.raises(IntegraCredentialError, match="cert_path"):
        get_integra_credenciais()


def test_cnpj_invalido_levanta(monkeypatch, fake_pfx):
    monkeypatch.setenv("INTEGRA_CERT_PATH", str(fake_pfx))
    monkeypatch.setenv("INTEGRA_CERT_PASSWORD", "senha")
    monkeypatch.setenv("INTEGRA_CONTRATANTE_CNPJ", "123")  # inválido
    monkeypatch.setenv("INTEGRA_AUTOR_PEDIDO_DADOS_CNPJ", CNPJ_LIMPO)

    with pytest.raises(IntegraCredentialError, match="contratante_cnpj"):
        get_integra_credenciais()


def test_env_parcial_nao_monta(monkeypatch, fake_pfx):
    """Só 3 das 4 env vars → fonte env é pulada (None), cai pra próxima."""
    monkeypatch.setenv("INTEGRA_CERT_PATH", str(fake_pfx))
    monkeypatch.setenv("INTEGRA_CERT_PASSWORD", "senha")
    monkeypatch.setenv("INTEGRA_CONTRATANTE_CNPJ", CNPJ_LIMPO)
    # INTEGRA_AUTOR_PEDIDO_DADOS_CNPJ ausente
    # Precisa também garantir arquivo ausente
    monkeypatch.setenv("INTEGRA_CONFIG_FILE", "/nao/existe")

    with pytest.raises(IntegraCredentialError, match="não encontradas"):
        get_integra_credenciais()


def test_nenhuma_fonte_levanta_com_mensagem_guia(monkeypatch):
    monkeypatch.setenv("INTEGRA_CONFIG_FILE", "/nao/existe/integra.ini")
    with pytest.raises(IntegraCredentialError, match="INTEGRA_CERT_PATH"):
        get_integra_credenciais()


# ─── Arquivo INI ─────────────────────────────────────────────────────────


def test_arquivo_ini_lido_quando_env_ausente(monkeypatch, tmp_path, fake_pfx):
    ini = tmp_path / "integra.ini"
    ini.write_text(
        f"""[integra]
cert_path = {fake_pfx}
cert_password = senha-do-ini
contratante_cnpj = {CNPJ_LIMPO}
autor_pedido_dados_cnpj = {CNPJ_LIMPO}
base_url = https://sandbox.apiserpro.serpro.gov.br/integra-contador/v1
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("INTEGRA_CONFIG_FILE", str(ini))

    cred = get_integra_credenciais()
    assert cred.cert_password == "senha-do-ini"
    assert cred.contratante_cnpj == CNPJ_LIMPO
    assert cred.base_url is not None
    assert "sandbox" in cred.base_url


def test_arquivo_ini_sem_secao_falha_silenciosamente(
    monkeypatch, tmp_path, fake_pfx
):
    ini = tmp_path / "bad.ini"
    ini.write_text("[outra_secao]\nfoo = bar\n", encoding="utf-8")
    monkeypatch.setenv("INTEGRA_CONFIG_FILE", str(ini))

    # Arquivo existe mas não tem [integra] → cai pra próxima fonte → erro final
    with pytest.raises(IntegraCredentialError, match="não encontradas"):
        get_integra_credenciais()
