# -*- coding: utf-8 -*-
"""
test_auditoria_tentativa_acesso.py — Fase 4.1 (ressalva Luiz #3).

Cobre:
  1. Helper `registrar_tentativa_acesso` persiste linha com schema aprovado.
  2. `AnaliseBuffer.get_dono` distingue id inexistente, id expirado, dono.
  3. GET /analise/sessao — caso IDOR persiste na tabela de auditoria.
  4. GET /analise/sessao — id inexistente NÃO persiste (404 legítimo).
  5. GET /analise/sessao — id expirado NÃO persiste (404 legítimo).
  6. Log estruturado HIDRATACAO_SESSAO sem PII.

Amparo:
  - LGPD Art. 7º VI (IP cleartext) + Art. 37 + Art. 46 §1º + Art. 48
  - CTN  Art. 195  (retenção 5 anos)
"""
from __future__ import annotations

import logging
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("JWT_SECRET_KEY", "test-fase41-idor-audit")

import database  # noqa: E402
from database import AuditoriaTentativaAcessoDB  # noqa: E402
from database.repositories.auditoria_tentativa_repo import (  # noqa: E402
    registrar_tentativa_acesso,
)


@pytest.fixture(autouse=True)
def db_em_memoria(monkeypatch):
    """
    Cada teste recebe um SQLite em memória limpo — padrão do projeto.

    Semeia UserDB com ids 1 e 2 porque `auditoria_tentativas_acesso` tem
    FK para `users.id`. Sem isso, SQLite (com FK pragma ativo) recusa
    INSERT com erro de integridade.
    """
    # Garante registro de UserDB no metadata (import antes de create_all)
    import auth  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    import database.connection
    monkeypatch.setattr(database.connection, "engine", engine)
    monkeypatch.setattr(database, "engine", engine)

    # Semeia usuários 1 e 2 para satisfazer FKs dos testes
    from sqlmodel import Session
    from auth import UserDB
    with Session(engine) as session:
        session.add(UserDB(
            id=1, username="user_a", email="a@test.local",
            hashed_password="x", role="usuario", ativo=True,
        ))
        session.add(UserDB(
            id=2, username="user_b", email="b@test.local",
            hashed_password="x", role="usuario", ativo=True,
        ))
        session.add(UserDB(
            id=5, username="user_e", email="e@test.local",
            hashed_password="x", role="usuario", ativo=True,
        ))
        session.commit()

    yield engine


def _contar_tentativas():
    from database.connection import get_session
    with get_session() as session:
        return session.query(AuditoriaTentativaAcessoDB).count()


def _listar_tentativas():
    from database.connection import get_session
    with get_session() as session:
        return session.query(AuditoriaTentativaAcessoDB).all()


# ─── Helper unit tests ──────────────────────────────────────────────────────

class TestRegistrarTentativaAcesso:
    """Contrato do repositório — persistência blindada, nunca lança."""

    def test_registrar_tentativa_acesso_persiste_linha(self):
        registro = registrar_tentativa_acesso(
            analise_id_prefix="abcdef12",
            user_id_tentando=2,
            user_id_dono=1,
            ip="192.168.0.10",
            endpoint="/analise/sessao",
        )
        assert registro is not None
        assert registro.id is not None
        assert registro.analise_id_prefix == "abcdef12"
        assert registro.user_id_tentando == 2
        assert registro.user_id_dono == 1
        assert registro.ip == "192.168.0.10"
        assert registro.endpoint == "/analise/sessao"
        assert registro.tentado_em is not None

    def test_registrar_aceita_dono_none(self):
        """user_id_dono=None é válido (caso de id órfão em endpoints futuros)."""
        registro = registrar_tentativa_acesso(
            analise_id_prefix="cafebabe",
            user_id_tentando=5,
            user_id_dono=None,
            ip="10.0.0.1",
            endpoint="/integracoes/ecac/sync",
        )
        assert registro is not None
        assert registro.user_id_dono is None

    def test_registrar_trunca_prefix_e_ip_e_endpoint(self):
        """Inputs longos não quebram — são truncados aos limites do schema."""
        registro = registrar_tentativa_acesso(
            analise_id_prefix="abcdefghij1234567890",  # > 8
            user_id_tentando=1,
            user_id_dono=2,
            ip="x" * 100,  # > 45
            endpoint="y" * 500,  # > 255
        )
        assert registro is not None
        assert len(registro.analise_id_prefix) == 8
        assert len(registro.ip) == 45
        assert len(registro.endpoint) == 255

    def test_registrar_rejeita_user_id_invalido(self):
        """user_id <= 0 ou não-int é rejeitado silenciosamente (retorna None)."""
        assert registrar_tentativa_acesso(
            analise_id_prefix="abc", user_id_tentando=0,
            user_id_dono=None, ip="1.1.1.1", endpoint="/x",
        ) is None
        assert registrar_tentativa_acesso(
            analise_id_prefix="abc", user_id_tentando=-1,
            user_id_dono=None, ip="1.1.1.1", endpoint="/x",
        ) is None


# ─── AnaliseBuffer.get_dono ──────────────────────────────────────────────────

class TestGetDono:
    def test_get_dono_id_existente(self):
        from services.analise_buffer import AnaliseBuffer
        buf = AnaliseBuffer()
        analise_id = buf.armazenar({"diagnostico": {}, "pii": {}}, user_id=42)
        assert buf.get_dono(analise_id) == 42

    def test_get_dono_id_inexistente(self):
        from services.analise_buffer import AnaliseBuffer
        buf = AnaliseBuffer()
        assert buf.get_dono("0" * 32) is None

    def test_get_dono_id_expirado(self):
        from services.analise_buffer import AnaliseBuffer
        buf = AnaliseBuffer()
        analise_id = buf.armazenar(
            {"diagnostico": {}, "pii": {}}, user_id=1, ttl_segundos=1,
        )
        time.sleep(1.1)
        assert buf.get_dono(analise_id) is None

    def test_get_dono_id_invalido_nao_lanca(self):
        from services.analise_buffer import AnaliseBuffer
        buf = AnaliseBuffer()
        assert buf.get_dono("") is None
        assert buf.get_dono(None) is None  # type: ignore[arg-type]


# ─── Wiring completo: /analise/sessao → persistência ────────────────────────

@pytest.fixture(name="client_como_user1")
def client_como_user1_fixture(monkeypatch):
    """TestClient impersonado como user_id=1 + buffer isolado."""
    from main import app, get_current_user
    from services.analise_buffer import AnaliseBuffer
    import services.analise_buffer as _buffer_mod

    novo_buffer = AnaliseBuffer()
    monkeypatch.setattr(_buffer_mod, "_BUFFER_SINGLETON", novo_buffer)

    def fake_user_1():
        return {"sub": "1", "username": "user_a", "role": "usuario"}

    app.dependency_overrides[get_current_user] = fake_user_1
    with TestClient(app) as client:
        yield client, novo_buffer
    app.dependency_overrides.clear()


def test_sessao_idor_persiste_em_auditoria_tentativa_acesso(client_como_user1):
    """
    Análise criada pelo user_id=2; user_id=1 (JWT override) tenta acessar.
    Esperado: 404 + linha em AuditoriaTentativaAcessoDB.
    """
    client, buf = client_como_user1
    analise_id = buf.armazenar(
        {"diagnostico": {}, "pii": {"cnpj": "x"}}, user_id=2, ttl_segundos=60,
    )
    antes = _contar_tentativas()

    resp = client.get(f"/analise/sessao/{analise_id}")
    assert resp.status_code == 404

    depois = _contar_tentativas()
    assert depois == antes + 1, "Tentativa IDOR deveria ter sido persistida"

    linhas = _listar_tentativas()
    linha = linhas[-1]
    assert linha.analise_id_prefix == analise_id[:8]
    assert linha.user_id_tentando == 1
    assert linha.user_id_dono == 2
    assert linha.endpoint == "/analise/sessao"
    # IP do TestClient é 127.0.0.1 ou testclient
    assert linha.ip in ("127.0.0.1", "testclient", "testserver")


def test_sessao_id_inexistente_nao_persiste_tentativa(client_como_user1):
    """id que nunca existiu → 404 legítimo, NÃO persiste tentativa."""
    client, _ = client_como_user1
    antes = _contar_tentativas()

    resp = client.get("/analise/sessao/" + "0" * 32)
    assert resp.status_code == 404

    depois = _contar_tentativas()
    assert depois == antes, "id inexistente não deve gerar tentativa"


def test_sessao_expirada_nao_persiste_tentativa(client_como_user1):
    """id expirado → 404 legítimo, NÃO persiste tentativa."""
    client, buf = client_como_user1
    analise_id = buf.armazenar(
        {"diagnostico": {}, "pii": {}}, user_id=1, ttl_segundos=1,
    )
    time.sleep(1.1)

    antes = _contar_tentativas()
    resp = client.get(f"/analise/sessao/{analise_id}")
    assert resp.status_code == 404
    depois = _contar_tentativas()
    assert depois == antes, "id expirado não deve gerar tentativa"


def test_sessao_dono_correto_nao_persiste_tentativa(client_como_user1):
    """Sanity: dono correto acessa sem gerar linha de auditoria."""
    client, buf = client_como_user1
    analise_id = buf.armazenar(
        {"diagnostico": {"x": "1"}, "pii": {"cnpj": "x"}},
        user_id=1,
        ttl_segundos=60,
    )
    antes = _contar_tentativas()

    resp = client.get(f"/analise/sessao/{analise_id}")
    assert resp.status_code == 200

    depois = _contar_tentativas()
    assert depois == antes, "acesso legítimo não gera linha de tentativa"


# ─── Log estruturado de hidratação (ressalva Luiz #2) ────────────────────────

def test_hidratacao_sessao_loga_evento_sem_pii(client_como_user1, caplog):
    """
    Hidratação bem-sucedida deve emitir logger.info com:
      - HIDRATACAO_SESSAO
      - prefixo do id (8 chars)
      - user_id=1
      - ip
    E NUNCA deve conter CNPJ ou razão social.
    LGPD Art. 5º X + Art. 37.
    """
    client, buf = client_como_user1
    envelope = {
        "diagnostico": {"aliquota": "0.08"},
        "pii": {"cnpj": "54657895000160", "razao_social": "Alvo PII LTDA"},
    }
    analise_id = buf.armazenar(envelope, user_id=1, ttl_segundos=60)

    with caplog.at_level(logging.INFO, logger="motor_conect.api"):
        resp = client.get(f"/analise/sessao/{analise_id}")

    assert resp.status_code == 200

    mensagens = [r.getMessage() for r in caplog.records]
    hidratacoes = [m for m in mensagens if "HIDRATACAO_SESSAO" in m]
    assert hidratacoes, f"HIDRATACAO_SESSAO não foi logado. Logs: {mensagens}"

    log_msg = hidratacoes[0]
    assert analise_id[:8] in log_msg
    assert "user_id=1" in log_msg
    # NADA de PII vazando
    assert "54657895000160" not in log_msg
    assert "Alvo PII LTDA" not in log_msg
    assert "razao_social" not in log_msg
    assert "cnpj" not in log_msg.lower()
