"""
test_historico_endpoint.py — GET /auditorias (Fase 5).

Cobre:
  - Lista vazia quando usuário não tem diagnósticos.
  - Paginação (skip/limit).
  - Ownership rigoroso: user A nunca vê diagnóstico de user B.
  - Response sem PII (sem cnpj, sem razao_social, sem resultado_json).
  - Validação de limites de paginação (limit=0 → 422 pelo Query(ge=1)).
  - 401 sem token.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Helpers ────────────────────────────────────────────────────────────────

def _garantir_user(user_id: int) -> None:
    """Cria UserDB se não existir. Necessário por causa da FK uploaded_by_user_id."""
    from auth import UserDB, _auth_engine, _hash_senha
    from sqlmodel import Session
    with Session(_auth_engine) as session:
        if session.get(UserDB, user_id) is not None:
            return
        session.add(UserDB(
            id=user_id,
            username=f"user{user_id}",
            email=f"user{user_id}@test.local",
            hashed_password=_hash_senha("senha12345"),
            role="usuario",
            ativo=True,
            tema="auto",
            notificacoes_email=True,
        ))
        session.commit()


def _seed_diagnostico(cnpj: str, razao: str, user_id: int, competencia: str = "2026-03") -> int:
    """
    Cria empresa + diagnóstico para um user_id específico. Retorna diagnostico.id.
    FK `diagnosticos.uploaded_by_user_id → users.id` exige user existente — cria se faltar.
    """
    _garantir_user(user_id)
    from database import salvar_empresa, salvar_diagnostico
    from core.motor_tributario import EmpresaFornecedora

    emp = EmpresaFornecedora(
        cnpj=cnpj,
        razao_social=razao,
        regime="SIMPLES",
        cnae_principal="4711301",
        uf_origem="SP",
        faturamento_12m=Decimal("240000.00"),
        anexo_simples="I",
    )
    empresa_db = salvar_empresa(emp)
    diag = salvar_diagnostico(
        empresa_id=empresa_db.id,
        competencia=competencia,
        resultado={"tipo": "seed"},
        das_mensal=Decimal("1500.00"),
        aliquota_efetiva=Decimal("0.075"),
        rbt12=Decimal("240000.00"),
        regime="SIMPLES",
        uploaded_by_user_id=user_id,
    )
    return diag.id


# ── Testes ─────────────────────────────────────────────────────────────────

def test_auditorias_lista_vazia_usuario_novo(client_autenticado):
    """User sem diagnósticos recebe []."""
    r = client_autenticado.get("/auditorias")
    assert r.status_code == 200
    assert r.json() == []


def test_auditorias_lista_propria(client_autenticado):
    """Retorna apenas os diagnósticos do próprio user (id=1 no mock)."""
    _seed_diagnostico("12345678000195", "Cliente A", user_id=1, competencia="2026-03")
    _seed_diagnostico("98765432000198", "Cliente B", user_id=1, competencia="2026-04")

    r = client_autenticado.get("/auditorias")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    competencias = sorted(item["competencia"] for item in body)
    assert competencias == ["2026-03", "2026-04"]


def test_auditorias_ownership_rigoroso(client_autenticado):
    """
    User A (id=1, mock) NÃO vê diagnóstico de user B (id=99).
    Guard de regressão do ERR-050.
    """
    _seed_diagnostico("12345678000195", "Cliente do User99", user_id=99)
    _seed_diagnostico("98765432000198", "Cliente do User1", user_id=1)

    r = client_autenticado.get("/auditorias")
    assert r.status_code == 200
    body = r.json()
    # Só o do user 1 (mock do fixture) deve aparecer
    assert len(body) == 1


def test_auditorias_response_sem_pii(client_autenticado):
    """
    Response NÃO pode conter cnpj, razao_social, resultado_json.
    Guard de regressão LGPD Art. 6º V (minimização).
    """
    _seed_diagnostico("12345678000195", "Razao Super Sigilosa Ltda", user_id=1)

    r = client_autenticado.get("/auditorias")
    assert r.status_code == 200
    body_raw = r.text.lower()

    # Nenhum desses campos ou valores pode estar no response body
    proibidos = ("cnpj", "razao_social", "razao sigilosa", "resultado_json", "12345678000195")
    for termo in proibidos:
        assert termo.lower() not in body_raw, f"PII vazou: {termo!r}"


def test_auditorias_paginacao(client_autenticado):
    """Paginação skip/limit respeitada."""
    # CNPJs válidos pré-calculados (DVs corretos)
    cnpjs_validos = [
        "12345678000195",
        "98765432000198",
        "20080010000191",
        "30090010000126",
        "40050010000156",
    ]
    for i, cnpj in enumerate(cnpjs_validos):
        _seed_diagnostico(cnpj, f"Empresa {i}", user_id=1, competencia=f"2026-0{i + 1}")

    # Primeira página
    r1 = client_autenticado.get("/auditorias?skip=0&limit=2")
    assert r1.status_code == 200
    assert len(r1.json()) == 2

    # Segunda página
    r2 = client_autenticado.get("/auditorias?skip=2&limit=2")
    assert r2.status_code == 200
    assert len(r2.json()) == 2

    # Última (restante)
    r3 = client_autenticado.get("/auditorias?skip=4&limit=2")
    assert r3.status_code == 200
    assert len(r3.json()) == 1


def test_auditorias_limit_zero_rejeitado(client_autenticado):
    """limit=0 violaria ge=1 da Query → 422."""
    r = client_autenticado.get("/auditorias?limit=0")
    assert r.status_code == 422


def test_auditorias_sem_token_nao_autenticado(client_sem_auth):
    """Sem JWT → 401/403."""
    r = client_sem_auth.get("/auditorias")
    assert r.status_code in (401, 403)
