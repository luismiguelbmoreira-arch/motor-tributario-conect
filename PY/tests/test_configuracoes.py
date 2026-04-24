"""
test_configuracoes.py — /settings (Fase 5).

Cobre:
  - GET /settings com defaults em user novo.
  - POST /settings/tema com "escuro" atualiza.
  - POST /settings/tema com valor inválido → 422.
  - POST /settings/* com campo desconhecido → 422 (extra="forbid").
  - 401 sem token.
  - Persistência: POST + GET devolve o valor salvo.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _seed_user_basico(user_id: int = 1) -> None:
    """
    Garante que existe um UserDB com o id esperado pelo fixture.
    Os fixtures de conftest já setam user_id=1 via dependency override,
    mas o banco em memória começa vazio — precisamos criar o row.
    """
    from auth import UserDB, _auth_engine, _hash_senha
    from sqlmodel import Session
    with Session(_auth_engine) as session:
        if session.get(UserDB, user_id) is not None:
            return
        user = UserDB(
            id=user_id,
            username=f"user{user_id}",
            email=f"user{user_id}@test.local",
            hashed_password=_hash_senha("senha12345"),
            role="admin",
            ativo=True,
            tema="auto",
            notificacoes_email=True,
        )
        session.add(user)
        session.commit()


def test_settings_sem_token(client_sem_auth):
    r = client_sem_auth.get("/settings")
    assert r.status_code in (401, 403)


def test_settings_defaults_em_user_novo(client_autenticado):
    """User novo (acabou de ser criado) → tema='auto' + notificacoes_email=True."""
    _seed_user_basico(user_id=1)
    r = client_autenticado.get("/settings")
    assert r.status_code == 200
    body = r.json()
    assert body == {"tema": "auto", "notificacoes_email": True}


def test_settings_atualizar_tema_escuro(client_autenticado):
    _seed_user_basico(user_id=1)
    r = client_autenticado.post("/settings/tema", json={"tema": "escuro"})
    assert r.status_code == 200, r.text
    assert r.json()["tema"] == "escuro"


def test_settings_tema_invalido_rejeitado(client_autenticado):
    """Literal['claro','escuro','auto'] — outro valor → 422."""
    _seed_user_basico(user_id=1)
    r = client_autenticado.post("/settings/tema", json={"tema": "neon"})
    assert r.status_code == 422


def test_settings_tema_campo_desconhecido_rejeitado(client_autenticado):
    """extra='forbid' — payload com campo extra → 422."""
    _seed_user_basico(user_id=1)
    r = client_autenticado.post(
        "/settings/tema",
        json={"tema": "claro", "notificacoes_email": False},
    )
    assert r.status_code == 422


def test_settings_persistencia_tema_e_notificacoes(client_autenticado):
    """POST /tema + POST /notificacoes + GET devolve valores salvos."""
    _seed_user_basico(user_id=1)
    r1 = client_autenticado.post("/settings/tema", json={"tema": "claro"})
    assert r1.status_code == 200

    r2 = client_autenticado.post(
        "/settings/notificacoes", json={"notificacoes_email": False},
    )
    assert r2.status_code == 200

    r3 = client_autenticado.get("/settings")
    assert r3.status_code == 200
    body = r3.json()
    assert body == {"tema": "claro", "notificacoes_email": False}
