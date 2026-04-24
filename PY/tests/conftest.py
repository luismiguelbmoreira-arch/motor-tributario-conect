"""
conftest.py — Fixtures compartilhadas de teste.

Duas fixtures-chave para testes de endpoints:

    client_autenticado  → TestClient com get_current_user mockado (admin).
                          Use quando o teste foca em lógica de negócio do endpoint.

    client_sem_auth     → TestClient sem override. Depends(get_current_user)
                          roda o fluxo real e devolve 401/403 se não houver JWT.
                          Use quando o teste foca em verificar a proteção de auth.

Ambas isolam o DB em SQLite em memória com StaticPool (mesma thread).
LGPD: MOTOR_CONECT_MASTER_KEY é setada pra um valor dev-only, nunca toca prod.
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Setup ANTES dos imports do projeto (masterkey obrigatória)
os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"


def _make_engine_memoria():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _unificar_engines_e_criar_tabelas(monkeypatch, engine):
    """
    Patcha `auth._auth_engine` pro MESMO engine que `database.engine` e
    cria todas as tabelas nele.

    Motivo: em produção `_auth_engine` e `database.engine` são engines
    distintos apontando pro mesmo banco físico. Em testes com
    `sqlite:///:memory:` + StaticPool, cada engine seria um banco
    independente — UserDB ficaria em um, DiagnosticoDB em outro, e as
    FKs quebram. Unificando os dois engines no teste, ambas vivem no
    mesmo schema e a FK `diagnosticos.uploaded_by_user_id → users.id` funciona.
    """
    import auth
    monkeypatch.setattr(auth, "_auth_engine", engine)
    # Agora também monkeypatch do módulo configuracoes — ele faz
    # `from auth import _auth_engine` no topo, portanto captura o valor ORIGINAL
    # no momento do import. Fazemos patch direto no ref cacheado do módulo.
    try:
        from api.routers import configuracoes as _conf_mod
        monkeypatch.setattr(_conf_mod, "_auth_engine", engine)
    except ImportError:
        # Módulo pode não estar importado ainda em testes antigos.
        pass
    SQLModel.metadata.create_all(engine)


@pytest.fixture(name="client_autenticado", scope="function")
def client_autenticado_fixture(monkeypatch):
    """TestClient com usuário admin mockado em get_current_user."""
    import database
    import database.connection

    engine = _make_engine_memoria()
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database.connection, "engine", engine)
    _unificar_engines_e_criar_tabelas(monkeypatch, engine)

    from main import app, get_current_user

    def _fake_admin():
        return {"id": 1, "sub": "1", "username": "admin", "role": "admin"}

    app.dependency_overrides[get_current_user] = _fake_admin

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture(name="client_sem_auth", scope="function")
def client_sem_auth_fixture(monkeypatch):
    """TestClient sem override — endpoints protegidos devolvem 401/403."""
    import database
    import database.connection

    engine = _make_engine_memoria()
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database.connection, "engine", engine)
    _unificar_engines_e_criar_tabelas(monkeypatch, engine)

    from main import app

    # Garante que não há override residual de outro teste
    app.dependency_overrides.clear()

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
