"""
test_integracoes_status.py — GET /integracoes/status (Fase 5).

Cobre:
  - 401/403 sem JWT.
  - Retorna dict com as 3 chaves sieg/integra/ecac.
  - Cada item tem {ok, ultimo_sync, motivo_erro_publico}.
  - Regex-guard: response NÃO contém "senha"|"path"|"secret"|"token"|"cert"
    (sanity check contra vazamento de credencial via mensagem de erro).
  - Integração offline → ok=False + motivo público string neutra.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_status_sem_token(client_sem_auth):
    """Endpoint autenticado → sem token devolve 401/403."""
    r = client_sem_auth.get("/integracoes/status")
    assert r.status_code in (401, 403)


def test_status_retorna_tres_integracoes(client_autenticado, monkeypatch):
    """Response tem exatamente sieg/integra/ecac."""
    r = client_autenticado.get("/integracoes/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"sieg", "integra", "ecac"}
    for chave in ("sieg", "integra", "ecac"):
        item = body[chave]
        assert set(item.keys()) == {"ok", "ultimo_sync", "motivo_erro_publico"}
        assert isinstance(item["ok"], bool)


def test_status_sem_credenciais_ok_false(client_autenticado, monkeypatch):
    """
    Com env vars limpos, SIEG e Integra devem reportar offline.
    e-CAC depende do módulo nativo — não forçamos estado.
    """
    # Limpa credenciais externas se presentes no ambiente do dev
    for var in ("SIEG_API_KEY", "SIEG_API_KEY_FILE", "SIEG_API_KEY_AWS_SECRET"):
        monkeypatch.delenv(var, raising=False)

    r = client_autenticado.get("/integracoes/status")
    assert r.status_code == 200
    body = r.json()

    # SIEG sem credencial → offline + motivo string não vazio
    assert body["sieg"]["ok"] is False
    assert isinstance(body["sieg"]["motivo_erro_publico"], str)
    assert len(body["sieg"]["motivo_erro_publico"]) > 0


def test_status_sem_vazamento_credencial(client_autenticado):
    """
    Guard: response inteiro NÃO pode conter termos típicos de credencial/path.
    Se algum dia um handler mudar e colocar str(exc) direto, esse teste pega.
    """
    r = client_autenticado.get("/integracoes/status")
    assert r.status_code == 200
    body_raw = r.text.lower()

    # Termos que NÃO podem aparecer no response (nem em chave, nem em valor)
    proibidos = [
        r"\bsenha\b",
        r"\bpassword\b",
        r"\bsecret\b",
        r"\btoken\b",
        r"\bapi_key\b",
        r"api-key",
        r"\bpath\b",
        r"\bcert\b",  # certificado/cert_path
        r"\.pfx",
        r"\.pem",
        r"c:/users",
        r"/etc/",
        r"aws_secret",
        r"boto3",
    ]
    for padrao in proibidos:
        assert re.search(padrao, body_raw) is None, f"Possível vazamento: {padrao!r}"
