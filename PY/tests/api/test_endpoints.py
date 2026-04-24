"""
test_endpoints.py — Testes de integração HTTP do Motor Tributário Conect.

Cobre o contrato público da API via FastAPI TestClient (sem rede real).
Banco em memória isolado por sessão — nenhum dado persiste entre testes.

Rodar: python -m pytest tests/api/test_endpoints.py -v
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

os.environ.setdefault("JWT_SECRET_KEY", "test_secret_key_for_pytest_only")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-placeholder")
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "TestAdmin@2026!")
os.environ.setdefault("ENVIRONMENT", "test")

import pytest
from fastapi.testclient import TestClient

from main import app

# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    """TestClient com lifespan completo (cria tabelas + admin padrão)."""
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    """Faz login com admin padrão e devolve headers JWT."""
    resp = client.post(
        "/auth/login",
        json={"username": "admin", "password": "TestAdmin@2026!"},
    )
    assert resp.status_code == 200, f"Login falhou: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ─── GET /health ───────────────────────────────────────────────────────────


def test_health_ok(client):
    """Endpoint público deve responder 200 com status 'ok'."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "testes" in body
    assert "versao" in body


# ─── POST /auth/login ──────────────────────────────────────────────────────


def test_login_credenciais_corretas(client):
    """/auth/login com credenciais válidas deve retornar JWT."""
    resp = client.post(
        "/auth/login",
        json={"username": "admin", "password": "TestAdmin@2026!"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body.get("token_type") == "bearer"


def test_login_credenciais_erradas(client):
    """/auth/login com senha errada deve retornar 401."""
    resp = client.post(
        "/auth/login",
        json={"username": "admin", "password": "senha_errada"},
    )
    assert resp.status_code == 401


def test_login_usuario_inexistente(client):
    """/auth/login com username desconhecido deve retornar 401."""
    resp = client.post(
        "/auth/login",
        json={"username": "nao_existe", "password": "qualquer"},
    )
    assert resp.status_code == 401


# ─── Proteção de autenticação ──────────────────────────────────────────────


def test_analise_manual_sem_auth(client):
    """POST /analise/manual sem token deve retornar 401/403."""
    resp = client.post("/analise/manual", json={})
    assert resp.status_code in (401, 403)


def test_dashboard_summary_sem_auth(client):
    """GET /dashboard/summary sem token deve retornar 401/403."""
    resp = client.get("/dashboard/summary")
    assert resp.status_code in (401, 403)


# ─── POST /analise/manual (autenticado) ───────────────────────────────────


def test_analise_manual_simples_valida(client, auth_headers):
    """Análise manual de empresa Simples Nacional retorna diagnóstico 200."""
    payload = {
        "fornecedora": {
            "cnpj": "11.222.333/0001-81",
            "razao_social": "Empresa Teste Simples Ltda",
            "regime": "SIMPLES",
            "cnae_principal": "4771701",
            "uf_origem": "SP",
            "faturamento_12m": "360000.00",
            "anexo_simples": "I",
        },
        "operacao": {
            "data_emissao": "2026-06-15",
            "valor": "10000.00",
            "reducao_cbs_ibs": "INTEGRAL",
        },
        "compradora": {
            "tipo": "B2B_CONTRIBUINTE",
            "uf_destino": "SP",
        },
    }
    resp = client.post("/analise/manual", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "das_mensal" in body or "regime" in body or "trilha_auditoria" in body


def test_analise_manual_payload_invalido(client, auth_headers):
    """Payload malformado deve retornar 422 (validação Pydantic)."""
    resp = client.post(
        "/analise/manual",
        json={"fornecedora": {"regime": "INVALIDO"}},
        headers=auth_headers,
    )
    assert resp.status_code == 422


# ─── GET /dashboard/summary ───────────────────────────────────────────────


def test_dashboard_summary_autenticado(client, auth_headers):
    """Dashboard com auth deve retornar 200 com estrutura esperada."""
    resp = client.get("/dashboard/summary", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "stats" in body
    assert "projection" in body


# ─── GET /cnae/{cnae}/perfil ──────────────────────────────────────────────


def test_cnae_perfil_valido(client, auth_headers):
    """CNAE de comércio varejista retorna sugestão de anexo."""
    resp = client.get("/cnae/4757100/perfil", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "anexo_sugerido" in body or "anexo" in body or "cnae" in body


# ─── GET /auditoria/prova/cnpj/{cnpj} ────────────────────────────────────


def test_dossie_sem_motivo(client, auth_headers):
    """Dossiê sem query param 'motivo' deve retornar 422."""
    resp = client.get(
        "/auditoria/prova/cnpj/11222333000181",
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_dossie_cnpj_invalido(client, auth_headers):
    """CNPJ com dígitos insuficientes deve retornar 422."""
    resp = client.get(
        "/auditoria/prova/cnpj/00000000000",
        params={"motivo": "Teste de validacao do CNPJ"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_dossie_sem_documentos(client, auth_headers):
    """CNPJ válido mas sem documentos deve retornar 404."""
    resp = client.get(
        "/auditoria/prova/cnpj/11222333000181",
        params={"motivo": "Teste de validacao de CNPJ sem documentos"},
        headers=auth_headers,
    )
    assert resp.status_code == 404
