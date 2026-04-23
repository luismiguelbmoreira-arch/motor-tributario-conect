# -*- coding: utf-8 -*-
"""
test_analise_buffer.py — Fase 4 Segurança/LGPD.

Cobre AnaliseBuffer (serviço) e o endpoint GET /analise/sessao/{id}:

  - Ownership: só o user_id dono do envelope recupera (ERR-018 IDOR).
  - Opacidade do analise_id: 32 hex chars, não adivinhável.
  - TTL: expira — recuperar devolve None / 404 após prazo.
  - Purge: entradas expiradas vão embora em operações subsequentes.
  - Integração do endpoint: 404 em id inexistente, 404 em id de outro user,
    200 com envelope para o dono.

LGPD Art. 6º V (minimização): PII vive só em memória, nunca no storage do
browser. Este teste garante que o backend não vaza envelope para quem não
é dono.
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from services.analise_buffer import AnaliseBuffer, get_buffer  # noqa: E402


# ─── Testes unitários do AnaliseBuffer ─────────────────────────────────────

class TestAnaliseBufferUnitario:
    """Fixtures isoladas — cria um buffer por teste para não vazar estado."""

    def test_armazenar_retorna_id_opaco(self):
        buf = AnaliseBuffer()
        envelope = {"diagnostico": {"rbt12": "100000.00"}, "pii": {"cnpj": "00000000000000"}}
        analise_id = buf.armazenar(envelope, user_id=1, ttl_segundos=60)

        # UUID opaco — 32 hex chars (16 bytes de secrets.token_hex)
        assert isinstance(analise_id, str)
        assert len(analise_id) == 32
        assert all(c in "0123456789abcdef" for c in analise_id)

    def test_armazenar_ids_unicos_mesmo_com_envelope_igual(self):
        buf = AnaliseBuffer()
        envelope = {"diagnostico": {}, "pii": {}}
        id1 = buf.armazenar(envelope, user_id=1)
        id2 = buf.armazenar(envelope, user_id=1)
        assert id1 != id2

    def test_recuperar_pelo_dono_retorna_envelope(self):
        buf = AnaliseBuffer()
        envelope = {"diagnostico": {"aliquota": "0.08"}, "pii": {"cnpj": "x"}}
        analise_id = buf.armazenar(envelope, user_id=42)

        recuperado = buf.recuperar(analise_id, user_id=42)
        assert recuperado is envelope  # mesma ref — sem cópia

    def test_ownership_usuario_diferente_nao_recupera(self):
        """ERR-018 IDOR-safe: user B não vê análise de user A."""
        buf = AnaliseBuffer()
        envelope = {"diagnostico": {}, "pii": {"cnpj": "x"}}
        analise_id = buf.armazenar(envelope, user_id=1)

        # User 2 tenta acessar → None (mesmo comportamento de id inexistente)
        assert buf.recuperar(analise_id, user_id=2) is None
        # Mas user 1 (dono) continua vendo
        assert buf.recuperar(analise_id, user_id=1) is envelope

    def test_id_inexistente_retorna_none(self):
        buf = AnaliseBuffer()
        assert buf.recuperar("0" * 32, user_id=1) is None
        assert buf.recuperar("", user_id=1) is None

    def test_ttl_expira_entrada(self):
        """Entrada com TTL zero-ish não sobrevive a uma leitura posterior."""
        import time as _time

        buf = AnaliseBuffer()
        envelope = {"diagnostico": {}, "pii": {}}
        # TTL mínimo válido é 1s — dormimos 1.1s pra garantir expiração.
        # Teste de TTL curto, mas determinístico, pra não flaky.
        analise_id = buf.armazenar(envelope, user_id=1, ttl_segundos=1)
        _time.sleep(1.1)
        assert buf.recuperar(analise_id, user_id=1) is None

    def test_purge_expirados_limpa_buffer(self):
        import time as _time

        buf = AnaliseBuffer()
        id_longo = buf.armazenar({"diagnostico": {}}, user_id=1, ttl_segundos=60)
        id_curto = buf.armazenar({"diagnostico": {}}, user_id=1, ttl_segundos=1)

        _time.sleep(1.1)
        removidos = buf.purge_expirados()
        assert removidos == 1
        assert buf.tamanho() == 1
        # O de 60s continua vivo
        assert buf.recuperar(id_longo, user_id=1) is not None
        # O curto foi embora
        assert buf.recuperar(id_curto, user_id=1) is None

    def test_remover_somente_pelo_dono(self):
        buf = AnaliseBuffer()
        analise_id = buf.armazenar({"diagnostico": {}}, user_id=1)
        # User errado: não remove
        assert buf.remover(analise_id, user_id=999) is False
        assert buf.tamanho() == 1
        # User dono: remove
        assert buf.remover(analise_id, user_id=1) is True
        assert buf.tamanho() == 0

    def test_envelope_vazio_rejeitado(self):
        buf = AnaliseBuffer()
        with pytest.raises(ValueError):
            buf.armazenar({}, user_id=1)

    def test_user_id_invalido_rejeitado(self):
        buf = AnaliseBuffer()
        with pytest.raises(ValueError):
            buf.armazenar({"diagnostico": {}}, user_id=0)
        with pytest.raises(ValueError):
            buf.armazenar({"diagnostico": {}}, user_id=-1)

    def test_singleton_retorna_mesma_instancia(self):
        """get_buffer() é singleton de processo."""
        b1 = get_buffer()
        b2 = get_buffer()
        assert b1 is b2


# ─── Integração com endpoint GET /analise/sessao/{id} ──────────────────────


@pytest.fixture(name="client_como_user")
def client_como_user_fixture(monkeypatch):
    """
    TestClient com get_current_user retornando user_id=1 (sub='1').
    Usuário impersonificado via dependency_overrides.
    """
    from main import app, get_current_user
    from services.analise_buffer import AnaliseBuffer
    import services.analise_buffer as _buffer_mod

    # Buffer isolado por teste — evita vazamento entre testes de integração
    novo_buffer = AnaliseBuffer()
    monkeypatch.setattr(_buffer_mod, "_BUFFER_SINGLETON", novo_buffer)

    def fake_user_1():
        return {"sub": "1", "username": "admin", "role": "admin"}

    app.dependency_overrides[get_current_user] = fake_user_1
    with TestClient(app) as client:
        yield client, novo_buffer
    app.dependency_overrides.clear()


def test_endpoint_id_inexistente_retorna_404(client_como_user):
    client, _ = client_como_user
    resp = client.get("/analise/sessao/" + "0" * 32)
    assert resp.status_code == 404


def test_endpoint_dono_recupera_envelope(client_como_user):
    client, buf = client_como_user
    envelope = {
        "diagnostico": {"aliquota": "0.08"},
        "pii": {"cnpj": "54657895000160", "razao_social": "Teste LTDA"},
    }
    analise_id = buf.armazenar(envelope, user_id=1, ttl_segundos=60)

    resp = client.get(f"/analise/sessao/{analise_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pii"]["cnpj"] == "54657895000160"
    assert body["diagnostico"]["aliquota"] == "0.08"


def test_endpoint_ownership_outro_user_retorna_404(client_como_user):
    """
    Análise criada pelo user_id=2 não pode ser vista pelo user_id=1 do JWT.
    Resposta é 404 (não 403) para não vazar a existência do registro.
    """
    client, buf = client_como_user
    envelope = {"diagnostico": {"aliquota": "0.15"}, "pii": {"cnpj": "x"}}
    # Criado por OUTRO usuário (user_id=2), não o 1 do override
    analise_id = buf.armazenar(envelope, user_id=2, ttl_segundos=60)

    resp = client.get(f"/analise/sessao/{analise_id}")
    assert resp.status_code == 404, resp.text
    # Body não vaza o conteúdo
    assert "aliquota" not in resp.text


def test_endpoint_id_malformado_retorna_404(client_como_user):
    """IDs com caracteres fora do alfabeto hex devem ser rejeitados cedo."""
    client, _ = client_como_user
    # id com ponto e barra — potencial path traversal; rejeição cedo
    resp = client.get("/analise/sessao/../../../../etc/passwd")
    # FastAPI pode normalizar, mas a rota final NÃO retorna 200
    assert resp.status_code in (404, 405, 422)


def test_endpoint_id_muito_longo_retorna_404(client_como_user):
    client, _ = client_como_user
    # 128 chars: maior que o limite de 64 do handler
    resp = client.get("/analise/sessao/" + "a" * 128)
    assert resp.status_code == 404


def test_endpoint_sem_auth_retorna_403(monkeypatch):
    """Sem JWT, HTTPBearer responde 403 — endpoint autenticação-gated."""
    from main import app

    # Garante que não há override residual
    app.dependency_overrides.clear()

    with TestClient(app) as client:
        resp = client.get("/analise/sessao/" + "a" * 32)
    assert resp.status_code in (401, 403)
