"""
test_err049_extrair_user_id.py — Regressão ERR-049 (Fase 5).

Contexto:
  O JWT real emitido por `auth.gerar_token_jwt()` põe o user_id na claim "sub"
  (padrão RFC 7519). Antes da Fase 5, vários endpoints faziam
  `current_user.get("id")` — que sempre retornava None em produção porque
  "id" não é claim do JWT.

  A fixture legada de testes usava {"id": 1, ...} (sem "sub"), mascarando
  o bug. Este módulo valida que o helper universal `extrair_user_id` lê
  tanto "sub" (formato real) quanto "id" (fixture legada).
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.dependencies import extrair_user_id


# ── Unit tests do helper ────────────────────────────────────────────────────

def test_extrai_de_sub_string_jwt_real():
    """Formato JWT: sub='1' (string). ERR-049: era o caso quebrado."""
    assert extrair_user_id({"sub": "1", "username": "x", "role": "admin"}) == 1


def test_extrai_de_sub_string_grande():
    assert extrair_user_id({"sub": "987654"}) == 987654


def test_extrai_de_id_fixture_legada():
    """Fixture antiga usava {"id": 1, ...} — ainda aceito."""
    assert extrair_user_id({"id": 1, "username": "x"}) == 1


def test_prefere_sub_sobre_id_quando_ambos_presentes():
    """Payload misto (migração fixture) — sub ganha. Garante determinismo."""
    assert extrair_user_id({"sub": "42", "id": 1}) == 42


def test_retorna_none_sem_sub_nem_id():
    assert extrair_user_id({"username": "x", "role": "admin"}) is None


def test_retorna_none_dict_vazio():
    assert extrair_user_id({}) is None


def test_retorna_none_dict_none():
    assert extrair_user_id(None) is None


def test_retorna_none_user_id_zero_ou_negativo():
    """user_id <= 0 não é válido."""
    assert extrair_user_id({"sub": "0"}) is None
    assert extrair_user_id({"sub": "-1"}) is None


def test_retorna_none_id_nao_inteiro():
    """Formato inválido não estoura — retorna None (fail-safe)."""
    assert extrair_user_id({"sub": "abc"}) is None
    assert extrair_user_id({"sub": ""}) is None
    assert extrair_user_id({"id": {"nested": 1}}) is None


# ── Integração nos 3 routers (formato JWT real) ────────────────────────────

@pytest.fixture(name="client_sub_only")
def client_sub_only_fixture(monkeypatch):
    """
    TestClient onde get_current_user devolve SÓ a claim "sub" (JWT real).
    Valida que os fixes ERR-049 nos handlers funcionam sem o legado "id".

    Reproduz a unificação de engines do conftest (auth._auth_engine ==
    database.engine) pra que UserDB e DiagnosticoDB vivam no mesmo DB em memória.
    """
    import auth
    import database
    import database.connection
    from sqlmodel import SQLModel, create_engine
    from sqlalchemy.pool import StaticPool
    from fastapi.testclient import TestClient

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database.connection, "engine", engine)
    monkeypatch.setattr(auth, "_auth_engine", engine)
    try:
        from api.routers import configuracoes as _conf_mod
        monkeypatch.setattr(_conf_mod, "_auth_engine", engine)
    except ImportError:
        pass
    SQLModel.metadata.create_all(engine)

    from main import app, get_current_user

    def _fake_user_sub():
        # ⚠️ SEM "id" — como o JWT real. Se algum handler ainda usa
        # current_user.get("id"), o valor vai ser None e o teste pega.
        return {"sub": "7", "username": "operador", "role": "usuario"}

    app.dependency_overrides[get_current_user] = _fake_user_sub

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


def test_historico_funciona_com_payload_sub_only(client_sub_only):
    """
    Regressão: GET /auditorias extrai user_id de "sub" corretamente.
    Antes do fix, teria vindo lista vazia por user_id=None ou HTTPException.
    """
    r = client_sub_only.get("/auditorias")
    # Lista vazia é 200 — o ponto é que não quebra/401 por causa do sub.
    assert r.status_code == 200


def test_settings_funciona_com_payload_sub_only(client_sub_only):
    """
    GET /settings com "sub" only — antes do fix, _resolver_user_id
    levantaria 401 porque get("id") era None.
    """
    # Cria o user id=7 primeiro (conftest do client_autenticado usa id=1)
    from auth import UserDB, _auth_engine, _hash_senha
    from sqlmodel import Session
    with Session(_auth_engine) as session:
        if session.get(UserDB, 7) is None:
            session.add(UserDB(
                id=7, username="u7", email="u7@test.local",
                hashed_password=_hash_senha("senha12345"),
                role="usuario", ativo=True, tema="auto", notificacoes_email=True,
            ))
            session.commit()

    r = client_sub_only.get("/settings")
    assert r.status_code == 200
    assert r.json()["tema"] in ("claro", "escuro", "auto")
