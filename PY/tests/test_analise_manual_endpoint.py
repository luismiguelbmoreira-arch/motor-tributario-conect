# -*- coding: utf-8 -*-
"""
test_analise_manual_endpoint.py — Testes de contrato do POST /analise/manual (Fase 3).

Cobertura:
- Payload válido → 200 com envelope {diagnostico, pii}
- Payload inválido (CNPJ ruim, data fora de 2026-2033, faturamento negativo) → 422
- Campo desconhecido (extra="forbid") → 422 com extra_forbidden
- Guards fiscais do @model_validator (ERR-024):
    * MEI > R$ 81.000 → 422 com citação LC 123/2006 Art. 18-A §1º
    * MEI sem categoria_mei → 422
    * tipo != MISTO + percentual_b2b != 100 → 422 com citação LC 214/2025 Art. 47
- Resposta envelope: diagnostico + pii, PII fora do diagnóstico (LGPD Art. 6º V)
- Autenticação: sem JWT → 401
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
import database  # noqa: E402
from main import app, get_current_user  # noqa: E402


# CNPJ válido (módulo 11) — mesmo da CANAVEZI usado em outros testes
CNPJ_VALIDO = "54657895000160"


def _payload_minimo_simples() -> dict:
    """Payload válido mínimo de Simples — base para os testes de variação."""
    return {
        "cnpj": CNPJ_VALIDO,
        "razao_social": "Empresa Teste LTDA",
        "regime": "SIMPLES",
        "cnae_principal": "4757100",
        "uf_origem": "SP",
        "faturamento_12m": "500000.00",
        "tipo_comprador": "B2B_CONTRIBUINTE",
        "uf_destino": "SP",
        "data_emissao": "2026-06-15",
        "valor_operacao": "10000.00",
        "ncm_nbs": "84818099",
    }


@pytest.fixture(name="client", scope="function")
def client_fixture(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    import database.connection
    monkeypatch.setattr(database.connection, "engine", engine)
    monkeypatch.setattr(database, "engine", engine)

    def fake_user():
        return {"id": 1, "username": "admin", "role": "admin"}

    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# ── Caminhos felizes ─────────────────────────────────────────────────────────

def test_payload_valido_simples_retorna_200_com_envelope(client):
    resp = client.post("/analise/manual", json=_payload_minimo_simples())
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Envelope blindado da Fase 2
    assert "diagnostico" in data
    assert "pii" in data
    # PII separada do diagnóstico (LGPD Art. 6º V — minimização)
    assert data["pii"]["cnpj"] == CNPJ_VALIDO
    assert data["pii"]["razao_social"] == "Empresa Teste LTDA"


def test_payload_misto_com_percentual_b2b_60(client):
    payload = {**_payload_minimo_simples(), "tipo_comprador": "MISTO", "percentual_b2b": "60"}
    resp = client.post("/analise/manual", json=payload)
    assert resp.status_code == 200, resp.text


# ── Validação de tipos / Pydantic padrão ─────────────────────────────────────

def test_cnpj_invalido_retorna_422(client):
    payload = {**_payload_minimo_simples(), "cnpj": "12345678901234"}
    resp = client.post("/analise/manual", json=payload)
    assert resp.status_code == 422
    assert "CNPJ" in resp.text or "cnpj" in resp.text.lower()


def test_data_emissao_fora_periodo_transicional_retorna_422(client):
    payload = {**_payload_minimo_simples(), "data_emissao": "2025-12-31"}
    resp = client.post("/analise/manual", json=payload)
    # LC 214/2025 Art. 348 — período 2026-2033
    assert resp.status_code == 422


def test_faturamento_negativo_retorna_422(client):
    payload = {**_payload_minimo_simples(), "faturamento_12m": "-100"}
    resp = client.post("/analise/manual", json=payload)
    assert resp.status_code == 422


def test_regime_invalido_retorna_422(client):
    payload = {**_payload_minimo_simples(), "regime": "LALA"}
    resp = client.post("/analise/manual", json=payload)
    assert resp.status_code == 422


def test_valor_operacao_zero_retorna_422(client):
    payload = {**_payload_minimo_simples(), "valor_operacao": "0"}
    resp = client.post("/analise/manual", json=payload)
    assert resp.status_code == 422


# ── Fase 2 — extra="forbid" ──────────────────────────────────────────────────

def test_campo_desconhecido_retorna_422_extra_forbidden(client):
    payload = {**_payload_minimo_simples(), "campo_malicioso": "x"}
    resp = client.post("/analise/manual", json=payload)
    assert resp.status_code == 422
    body = resp.json()
    detalhes = str(body.get("detail", ""))
    assert "extra_forbidden" in detalhes or "campo_malicioso" in detalhes


# ── ERR-024 — @model_validator de consistência fiscal ────────────────────────

def test_mei_acima_do_teto_bloqueado(client):
    # LC 123/2006 Art. 18-A §1º — teto MEI 2026 = R$ 81.000
    payload = {
        **_payload_minimo_simples(),
        "regime": "MEI",
        "faturamento_12m": "100000.00",
        "categoria_mei": "SERVICOS",
    }
    resp = client.post("/analise/manual", json=payload)
    assert resp.status_code == 422
    body = resp.json()
    detalhes = str(body.get("detail", ""))
    # Cita lei e valor do teto
    assert "18-A" in detalhes or "teto" in detalhes.lower() or "81" in detalhes


def test_mei_sem_categoria_bloqueado(client):
    # LC 123/2006 Art. 18-A §§3º I-III — DAS por categoria
    payload = {
        **_payload_minimo_simples(),
        "regime": "MEI",
        "faturamento_12m": "50000.00",
        # categoria_mei omitido de propósito
    }
    resp = client.post("/analise/manual", json=payload)
    assert resp.status_code == 422
    body = resp.json()
    detalhes = str(body.get("detail", ""))
    assert "categoria" in detalhes.lower()


def test_b2c_com_percentual_b2b_diferente_de_100_bloqueado(client):
    # LC 214/2025 Art. 47 II — crédito só em B2B contribuinte
    payload = {
        **_payload_minimo_simples(),
        "tipo_comprador": "B2C_CONSUMIDOR_FINAL",
        "percentual_b2b": "80",
    }
    resp = client.post("/analise/manual", json=payload)
    assert resp.status_code == 422
    body = resp.json()
    detalhes = str(body.get("detail", ""))
    assert "MISTO" in detalhes or "percentual_b2b" in detalhes


def test_b2b_contribuinte_com_percentual_b2b_diferente_de_100_bloqueado(client):
    payload = {
        **_payload_minimo_simples(),
        "tipo_comprador": "B2B_CONTRIBUINTE",
        "percentual_b2b": "50",
    }
    resp = client.post("/analise/manual", json=payload)
    assert resp.status_code == 422


# ── Auth ─────────────────────────────────────────────────────────────────────

def test_sem_auth_rejeita_acesso(client):
    # Remove o override de auth só para este teste.
    # HTTPBearer do FastAPI devolve 403 quando não há header Authorization
    # (403 = "forbidden", sem credencial); 401 só aparece quando há token
    # inválido. Para o contrato público o que importa é bloquear: 401 ou 403.
    app.dependency_overrides.clear()
    try:
        resp = client.post("/analise/manual", json=_payload_minimo_simples())
        assert resp.status_code in (401, 403), f"esperado 401/403, veio {resp.status_code}"
    finally:
        def fake_user():
            return {"id": 1, "username": "admin", "role": "admin"}
        app.dependency_overrides[get_current_user] = fake_user


# ── Decimal end-to-end ───────────────────────────────────────────────────────

def test_decimal_serializado_como_string_no_envelope(client):
    """
    MAX_FISCAL_01 — Decimal nunca vira float na resposta.

    Duas garantias (ERR-034):
      1) Walk recursivo em TODO o envelope falha se encontrar QUALQUER float.
         Protege contra drift silencioso quando motor adicionar chave nova.
      2) Asserta presença de AO MENOS UM valor monetário reconhecível entre
         as chaves canônicas, para evitar falso-positivo-tolerante (teste
         que passaria mesmo sem nenhuma das chaves existir).
    """
    resp = client.post("/analise/manual", json=_payload_minimo_simples())
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # ── 1) Walk recursivo — nenhum float escapa no envelope ────────────
    def _walk_sem_float(obj, caminho="$"):
        if isinstance(obj, float):
            raise AssertionError(
                f"Float detectado em {caminho} = {obj!r} — viola MAX_FISCAL_01. "
                "Todo valor monetário deve serializar como string Decimal."
            )
        if isinstance(obj, dict):
            for k, v in obj.items():
                _walk_sem_float(v, f"{caminho}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _walk_sem_float(v, f"{caminho}[{i}]")

    _walk_sem_float(data)

    # ── 2) Ao menos um valor monetário canônico existe e é string ──────
    diag = data["diagnostico"]
    chaves_monetarias_esperadas = (
        "das_calculado", "das_mensal", "das_total",
        "aliquota_efetiva", "valor_devido", "rbt12",
    )
    # Walk raso + busca aninhada em chaves comuns (empresa.rbt12, aliquotas.*)
    encontrados = []
    def _coletar(obj, prefixo=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in chaves_monetarias_esperadas:
                    encontrados.append((f"{prefixo}.{k}".lstrip("."), v))
                _coletar(v, f"{prefixo}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _coletar(v, f"{prefixo}[{i}]")
    _coletar(diag)

    assert encontrados, (
        f"Nenhuma chave monetária canônica ({chaves_monetarias_esperadas}) "
        "encontrada no diagnóstico. Se o motor foi renomeado, atualizar a lista."
    )
    for caminho, valor in encontrados:
        if valor is None:
            continue
        assert isinstance(valor, str), (
            f"{caminho} = {valor!r} deveria ser string Decimal, veio {type(valor).__name__}"
        )
