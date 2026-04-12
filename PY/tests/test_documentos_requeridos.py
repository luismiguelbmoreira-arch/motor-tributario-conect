"""
test_documentos_requeridos.py — Testes do endpoint GET /documentos-requeridos.

Cobre:
- 200: resposta bem-formada para (ano_alvo, perfil, regime)
- 200: período bate com o derivado pela calculadora
- 200: cards trocam quando perfil muda (B2B vs B2C vs MISTO)
- 200: MEI → apenas 1 card (DAS-SIMEI)
- 422: ano_alvo fora da faixa 2026..2033
- 422: perfil inválido
- 422: regime inválido
- 422: mes_corte inválido
- Endpoint é público (sem JWT)
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(app)


# ─── 200 — casos felizes ────────────────────────────────────────────────


def test_200_simples_b2b_padrao(client):
    r = client.get(
        "/documentos-requeridos",
        params={
            "ano_alvo": 2026,
            "perfil": "B2B_CONTRIBUINTE",
            "regime": "SIMPLES",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ano_alvo"] == 2026
    assert body["perfil"] == "B2B_CONTRIBUINTE"
    assert body["regime"] == "SIMPLES"
    assert body["periodo_base"]["rbt12_inicio"] == "2025-01"
    assert body["periodo_base"]["rbt12_fim"] == "2025-12"
    assert body["periodo_base"]["das_referencia"] == "2025-12"

    ids = [c["id"] for c in body["cards"]]
    assert "pgdas_d" in ids
    assert "nfe_saida" in ids
    assert "folha_csv" in ids


def test_200_periodo_labels_humanos_presentes(client):
    r = client.get(
        "/documentos-requeridos",
        params={"ano_alvo": 2026, "perfil": "B2B_CONTRIBUINTE", "regime": "SIMPLES"},
    )
    body = r.json()
    nfe = next(c for c in body["cards"] if c["id"] == "nfe_saida")
    assert nfe["periodo_label"] == "01/2025 a 12/2025"
    assert nfe["periodo_iso"] == "2025-01..2025-12"
    assert "LC 123" in nfe["amparo_legal"]


def test_200_b2c_nao_pede_nfe_saida(client):
    r = client.get(
        "/documentos-requeridos",
        params={
            "ano_alvo": 2026,
            "perfil": "B2C_CONSUMIDOR_FINAL",
            "regime": "SIMPLES",
        },
    )
    body = r.json()
    ids = [c["id"] for c in body["cards"]]
    assert "nfce" in ids
    assert "nfe_saida" not in ids


def test_200_mei_apenas_das_simei(client):
    r = client.get(
        "/documentos-requeridos",
        params={"ano_alvo": 2026, "perfil": "B2B_CONTRIBUINTE", "regime": "MEI"},
    )
    body = r.json()
    assert len(body["cards"]) == 1
    assert body["cards"][0]["id"] == "das"
    assert "Art. 18-A" in body["cards"][0]["amparo_legal"]


def test_200_intra_ano_mes_corte_3(client):
    r = client.get(
        "/documentos-requeridos",
        params={
            "ano_alvo": 2026,
            "perfil": "B2B_CONTRIBUINTE",
            "regime": "SIMPLES",
            "mes_corte": 3,
        },
    )
    body = r.json()
    assert body["periodo_base"]["rbt12_inicio"] == "2025-04"
    assert body["periodo_base"]["rbt12_fim"] == "2026-03"
    nfe = next(c for c in body["cards"] if c["id"] == "nfe_saida")
    assert nfe["periodo_label"] == "04/2025 a 03/2026"


def test_200_presumido_obriga_sped(client):
    r = client.get(
        "/documentos-requeridos",
        params={"ano_alvo": 2026, "perfil": "B2B_CONTRIBUINTE", "regime": "PRESUMIDO"},
    )
    body = r.json()
    sped_ecd = next(c for c in body["cards"] if c["id"] == "sped_ecd")
    assert sped_ecd["obrigatorio"] is True
    assert sped_ecd["periodo_label"] == "Exercício 2025"


# ─── 422 — validação ────────────────────────────────────────────────────


def test_422_ano_abaixo_do_minimo(client):
    r = client.get(
        "/documentos-requeridos",
        params={"ano_alvo": 2025, "perfil": "B2B_CONTRIBUINTE", "regime": "SIMPLES"},
    )
    assert r.status_code == 422


def test_422_ano_acima_do_maximo(client):
    r = client.get(
        "/documentos-requeridos",
        params={"ano_alvo": 2034, "perfil": "B2B_CONTRIBUINTE", "regime": "SIMPLES"},
    )
    assert r.status_code == 422


def test_422_perfil_invalido(client):
    r = client.get(
        "/documentos-requeridos",
        params={"ano_alvo": 2026, "perfil": "LIXO", "regime": "SIMPLES"},
    )
    assert r.status_code == 422


def test_422_regime_invalido(client):
    r = client.get(
        "/documentos-requeridos",
        params={"ano_alvo": 2026, "perfil": "B2B_CONTRIBUINTE", "regime": "LIXO"},
    )
    assert r.status_code == 422


def test_422_mes_corte_invalido(client):
    r = client.get(
        "/documentos-requeridos",
        params={
            "ano_alvo": 2026,
            "perfil": "B2B_CONTRIBUINTE",
            "regime": "SIMPLES",
            "mes_corte": 13,
        },
    )
    assert r.status_code == 422


# ─── Endpoint público (sem JWT) ─────────────────────────────────────────


def test_endpoint_nao_exige_autenticacao(client):
    """Não passa header Authorization e ainda assim obtém 200."""
    r = client.get(
        "/documentos-requeridos",
        params={"ano_alvo": 2026, "perfil": "B2B_CONTRIBUINTE", "regime": "SIMPLES"},
    )
    assert r.status_code == 200
