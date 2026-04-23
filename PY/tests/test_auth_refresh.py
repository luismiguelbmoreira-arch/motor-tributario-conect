# -*- coding: utf-8 -*-
"""
test_auth_refresh.py — Contrato do POST /auth/refresh (Fase 4 Segurança/LGPD)

Missão: garantir que o endpoint de refresh de JWT devolve 200/401 com
schema estável e NUNCA 304 (brief explícito — 304 em POST quebra o
contrato HTTP e confunde o client).

Cobertura:
  - Token recente (> 2h de vida): mantém mesmo token, renewed=False, 200.
  - Token próximo da expiração (< 2h): novo token emitido, renewed=True, 200.
  - Token inválido/expirado: 401.
  - Sem Authorization: 403 (HTTPBearer) — ainda é negação de acesso, nunca 304.
  - Schema do response: {access_token, token_type="bearer", renewed}.

Amparo:
  LGPD Art. 46 (segurança) — sessão não pode cair silenciosamente.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-refresh-fase4"

import auth as auth_mod  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(name="client")
def client_fixture():
    with TestClient(app) as client:
        yield client


def _gerar_token_com_exp(user_id: int, username: str, role: str, horas: float) -> str:
    """Gera JWT com exp customizada (horas restantes) — usa mesma SECRET_KEY."""
    expiracao = datetime.now(timezone.utc) + timedelta(hours=horas)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": expiracao,
    }
    return jwt.encode(payload, auth_mod.SECRET_KEY, algorithm=auth_mod.ALGORITHM)


# ── Caminho feliz: token recente — não renova ────────────────────────────────

def test_token_com_mais_de_2h_nao_renova_mas_responde_200(client):
    """
    Token com 7h de vida → renewed=False, mesmo token devolvido, status 200.
    NUNCA 304.
    """
    token_original = _gerar_token_com_exp(1, "admin", "admin", horas=7.0)
    resp = client.post(
        "/auth/refresh",
        headers={"Authorization": f"Bearer {token_original}"},
    )
    assert resp.status_code == 200, f"Esperado 200, veio {resp.status_code}: {resp.text}"
    assert resp.status_code != 304, "POST /auth/refresh NUNCA pode retornar 304 (contrato)"

    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["renewed"] is False
    # Token retornado é o mesmo (não renovou)
    assert body["access_token"] == token_original


# ── Caminho feliz: token próximo da expiração — renova ──────────────────────

def test_token_com_menos_de_2h_emite_novo_token(client):
    """
    Token com 1h de vida → renewed=True, novo access_token, status 200.
    """
    token_quase_expirado = _gerar_token_com_exp(1, "admin", "admin", horas=1.0)
    resp = client.post(
        "/auth/refresh",
        headers={"Authorization": f"Bearer {token_quase_expirado}"},
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["renewed"] is True
    assert body["access_token"] != token_quase_expirado
    # Novo token é válido e decodifica com mesmas claims
    novo_payload = jwt.decode(
        body["access_token"],
        auth_mod.SECRET_KEY,
        algorithms=[auth_mod.ALGORITHM],
    )
    assert novo_payload["sub"] == "1"
    assert novo_payload["username"] == "admin"
    assert novo_payload["role"] == "admin"


# ── Falha: token inválido ────────────────────────────────────────────────────

def test_token_invalido_retorna_401(client):
    """Token assinado com chave errada → 401, nunca 304."""
    outro_token = jwt.encode(
        {
            "sub": "1",
            "username": "admin",
            "role": "admin",
            "exp": datetime.now(timezone.utc) + timedelta(hours=5),
        },
        "chave-errada-diferente-da-config",
        algorithm="HS256",
    )
    resp = client.post(
        "/auth/refresh",
        headers={"Authorization": f"Bearer {outro_token}"},
    )
    assert resp.status_code == 401, resp.text
    assert resp.status_code != 304


def test_token_expirado_retorna_401(client):
    """Token já expirado → 401."""
    token_expirado = _gerar_token_com_exp(1, "admin", "admin", horas=-1.0)
    resp = client.post(
        "/auth/refresh",
        headers={"Authorization": f"Bearer {token_expirado}"},
    )
    assert resp.status_code == 401, resp.text
    assert resp.status_code != 304


# ── Falha: sem header ────────────────────────────────────────────────────────

def test_sem_authorization_nao_retorna_304(client):
    """
    Sem Authorization: HTTPBearer devolve 403 (Not authenticated).
    O que importa aqui é garantir que NUNCA é 304 — esse é o contrato
    frontend ↔ backend da Fase 4.
    """
    resp = client.post("/auth/refresh")
    assert resp.status_code != 304
    assert resp.status_code in (401, 403), resp.text


# ── Schema do response ───────────────────────────────────────────────────────

def test_response_schema_tem_campos_esperados(client):
    """Garantia de contrato com o frontend: access_token, token_type, renewed."""
    token = _gerar_token_com_exp(1, "admin", "admin", horas=5.0)
    resp = client.post(
        "/auth/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )
    body = resp.json()
    assert set(body.keys()) == {"access_token", "token_type", "renewed"}
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert body["token_type"] == "bearer"
    assert isinstance(body["renewed"], bool)
