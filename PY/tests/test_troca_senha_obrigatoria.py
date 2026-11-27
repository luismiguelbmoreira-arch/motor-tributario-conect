# -*- coding: utf-8 -*-
"""
test_troca_senha_obrigatoria.py — fluxo da troca de senha no 1º acesso.

Backend: /auth/login devolve must_change_password; /auth/change-password
troca a senha, zera a flag e o token atual continua válido (a UI redireciona
para o dashboard com ele — 401 aqui derrubaria o usuário para o login).

UI: login.html leva para trocar_senha.html quando a flag vem true e
components.js prende o usuário nessa página até trocar.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-troca-senha")

import auth as auth_mod  # noqa: E402
from main import app  # noqa: E402

UI = Path(__file__).resolve().parent.parent.parent / "UI"
SENHA_INICIAL = "senha-inicial-123"
SENHA_NOVA = "senha-nova-456789"


@pytest.fixture(name="client")
def client_fixture(monkeypatch):
    """Banco em memória único para auth e database (mesmo padrão do conftest)."""
    import database
    import database.connection
    from api.routers import configuracoes as conf_mod

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for modulo, nome in (
        (database, "engine"),
        (database.connection, "engine"),
        (auth_mod, "_auth_engine"),
        (conf_mod, "_auth_engine"),
    ):
        monkeypatch.setattr(modulo, nome, engine)
    SQLModel.metadata.create_all(engine)
    # /auth/login tem 5/minuto; zera a janela por teste (padrão de test_auth_refresh).
    from api.dependencies import limiter

    limiter.reset()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        limiter.reset()


@pytest.fixture(name="usuario")
def usuario_fixture(client):
    nome = f"troca_{uuid.uuid4().hex[:10]}"
    auth_mod.criar_usuario(
        username=nome,
        email=f"{nome}@teste.local",
        senha_plain=SENHA_INICIAL,
        role="usuario",
    )
    return nome


def _login(client, username, senha):
    return client.post("/auth/login", json={"username": username, "password": senha})


def _trocar(client, token, atual, nova):
    return client.post(
        "/auth/change-password",
        json={"senha_atual": atual, "nova_senha": nova},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_usuario_novo_recebe_flag_de_troca(client, usuario):
    resp = _login(client, usuario, SENHA_INICIAL)
    assert resp.status_code == 200, resp.text
    assert resp.json()["must_change_password"] is True


def test_troca_zera_flag_e_token_segue_valido(client, usuario):
    token = _login(client, usuario, SENHA_INICIAL).json()["access_token"]

    resp = _trocar(client, token, SENHA_INICIAL, SENHA_NOVA)
    assert resp.status_code == 200, resp.text

    # Mesmo token ainda abre rota autenticada (UI vai ao dashboard com ele).
    assert client.get("/settings", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    novo = _login(client, usuario, SENHA_NOVA)
    assert novo.status_code == 200, novo.text
    assert novo.json()["must_change_password"] is False
    assert _login(client, usuario, SENHA_INICIAL).status_code == 401


def test_senha_atual_errada_da_400_com_texto(client, usuario):
    token = _login(client, usuario, SENHA_INICIAL).json()["access_token"]
    resp = _trocar(client, token, "senha-errada-000", SENHA_NOVA)
    assert resp.status_code == 400
    assert isinstance(resp.json()["detail"], str)


def test_senha_curta_da_422(client, usuario):
    token = _login(client, usuario, SENHA_INICIAL).json()["access_token"]
    assert _trocar(client, token, SENHA_INICIAL, "curta").status_code == 422


def test_troca_sem_token_e_negada(client):
    resp = client.post(
        "/auth/change-password",
        json={"senha_atual": SENHA_INICIAL, "nova_senha": SENHA_NOVA},
    )
    assert resp.status_code in (401, 403)


# ── UI ───────────────────────────────────────────────────────────────────────

def test_login_redireciona_para_troca_quando_flag_true():
    texto = (UI / "login.html").read_text(encoding="utf-8")
    assert "data.must_change_password" in texto
    assert "trocar_senha.html" in texto


def test_components_prende_usuario_na_troca():
    texto = (UI / "components.js").read_text(encoding="utf-8")
    assert "PAGINAS_LIVRES_TROCA_SENHA = ['login.html', 'trocar_senha.html']" in texto
    assert "if (trocaSenhaGuard()) return;" in texto


def test_pagina_troca_chama_endpoint_e_limpa_flag():
    texto = (UI / "trocar_senha.html").read_text(encoding="utf-8")
    assert "/auth/change-password" in texto
    assert "sessionStorage.removeItem('must_change_password')" in texto
    # Sem sidebar: página isolada como o login.
    assert "app-container" not in texto
    # config.js antes de components.js (mcFetch usa MC_CONFIG).
    assert texto.index('src="config.js"') < texto.index('src="components.js"')
    # Mensagem do backend entra como texto, nunca como HTML.
    assert "innerHTML" not in texto


def test_configuracoes_tem_atalho_para_troca():
    texto = (UI / "configuracoes.html").read_text(encoding="utf-8")
    assert 'href="trocar_senha.html"' in texto
