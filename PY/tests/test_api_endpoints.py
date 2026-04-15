"""
test_api_endpoints.py — Testes de integração dos endpoints principais da API.
Garante que a refatoração sob a ótica de Underengineering não quebrou contratos.
"""
import os
import sys
import pytest
from decimal import Decimal
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

# Adiciona PY ao path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
import database
from main import app, get_current_user

@pytest.fixture(name="client", scope="function")
def client_fixture(monkeypatch):
    """Configura o app para usar um banco em memória e mock de auth."""
    # Cria engine em memória e tabelas
    engine = create_engine(
        "sqlite:///:memory:", 
        connect_args={"check_same_thread": False},
        poolclass=StaticPool  # Importante para persistência na mesma thread
    )
    SQLModel.metadata.create_all(engine)
    
    # Patch GLOBAL do engine no módulo de conexão para afetar todos os repositórios
    import database.connection
    monkeypatch.setattr(database.connection, "engine", engine)
    # Também atualiza a fachada para consistência
    monkeypatch.setattr(database, "engine", engine)
    
    # Mock de autenticação
    def fake_user():
        return {"id": 1, "username": "admin", "role": "admin"}
    
    app.dependency_overrides[get_current_user] = fake_user
    
    with TestClient(app) as client:
        yield client
    
    app.dependency_overrides.clear()

@pytest.fixture(name="session")
def session_fixture(client):
    """Retorna uma sessão vinculada ao banco do client."""
    with Session(database.engine) as session:
        yield session

# ── Testes de Health ────────────────────────────────────────────────────────

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "versao" in data

# ── Testes de Validação de CNPJ ─────────────────────────────────────────────

def test_analise_manual_cnpj_invalido(client):
    payload = {
        "cnpj": "123", # Inválido
        "razao_social": "Teste",
        "regime": "SIMPLES",
        "cnae_principal": "1234567",
        "uf_origem": "SP",
        "faturamento_12m": "100000.00",
        "ano_alvo": 2026,
        "mes_alvo": 1
    }
    response = client.post("/analise/manual", json=payload)
    assert response.status_code == 422
    assert "CNPJ Invalido" in response.text

def test_analise_manual_cnpj_valido_zeros(client):
    # CNPJs com dígitos iguais devem ser barrados pelo novo validador rígido
    payload = {
        "cnpj": "00000000000000",
        "razao_social": "Teste",
        "regime": "SIMPLES",
        "cnae_principal": "1234567",
        "uf_origem": "SP",
        "faturamento_12m": "100000.00"
    }
    response = client.post("/analise/manual", json=payload)
    assert response.status_code == 422
    assert "CNPJ Invalido" in response.text

def test_analise_manual_uf_invalida(client):
    payload = {
        "cnpj": "54657895000160",
        "razao_social": "Teste",
        "regime": "SIMPLES",
        "cnae_principal": "4711300",
        "uf_origem": "ZZ", # UF Inexistente
        "faturamento_12m": "100000.00"
    }
    response = client.post("/analise/manual", json=payload)
    assert response.status_code == 422
    assert "UF Invalida" in response.text

def test_analise_manual_cnae_invalido(client):
    payload = {
        "cnpj": "54657895000160",
        "razao_social": "Teste",
        "regime": "SIMPLES",
        "cnae_principal": "123", # Curto demais
        "uf_origem": "SP",
        "faturamento_12m": "100000.00"
    }
    response = client.post("/analise/manual", json=payload)
    assert response.status_code == 422
    assert "CNAE Invalido" in response.text

# ── Testes de Dashboard Dinâmico ───────────────────────────────────────────

def test_dashboard_summary_vazio(client, session):
    response = client.get("/dashboard/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["stats"]["empresas_ativas"] == 0
    assert data["stats"]["economia_apurada"] == "0,00"

def test_dashboard_summary_com_dados(client, session):
    # 1. Cria uma empresa
    from database import EmpresaDB, DiagnosticoDB
    empresa = EmpresaDB(
        cnpj="54657895000160", # CNPJ válido Moreira
        razao_social="Moreira Comércio",
        regime="SIMPLES",
        cnae_principal="4711300",
        uf_origem="SP",
        faturamento_12m="1000000.00"
    )
    session.add(empresa)
    session.commit()
    
    # 2. Cria um diagnóstico (Economia/Delta)
    diag = DiagnosticoDB(
        empresa_id=empresa.id,
        competencia="2026-01",
        resultado_json="{}",
        das_mensal="1500.50",
        aliquota_efetiva="0.15",
        rbt12_usado="100000.00",
        regime_no_calculo="SIMPLES",
        delta="1240.50",
        status_auditoria="APROVADO"
    )
    session.add(diag)
    session.commit()

    response = client.get("/dashboard/summary")
    assert response.status_code == 200
    data = response.json()
    
    assert data["stats"]["empresas_ativas"] == 1
    assert "1.240,50" in data["stats"]["economia_apurada"]
    assert len(data["recent_audits"]) == 1
    assert data["recent_audits"][0]["empresa"] == "Moreira Comércio"
    assert data["recent_audits"][0]["delta"] == "  R$ 1.240,50"
