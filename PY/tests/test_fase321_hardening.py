# -*- coding: utf-8 -*-
"""
test_fase321_hardening.py — Fase 3.2.1 (achados menores do Luiz + hardening).

Cobre:
  - Achado #2 do Luiz: fronteira 2026→2027 no Split Payment
    (emissão em 2026-12-28, liquidação em 2027-01-05). Motor hoje já detecta
    a transição via data_liquidacao; teste blinda para que a trilha continue
    coerente se a regra for alterada.
  - Achado #3 do Luiz: MEI + tipo=B2B_CONTRIBUINTE é semanticamente
    inconsistente (LC 123/2006 Art. 18-A §4º V — MEI não é contribuinte de
    IBS/CBS). Motor agora emite ALERTA_MEI_NAO_CONTRIBUINTE.
  - Hardening #2 do Viciado: percentual_b2b="100.00" (com duas casas
    decimais) deve ser tratado como equivalente a "100" no guard de
    consistência (ERR-024 — @model_validator de AnaliseManualRequest).
    Garante que Decimal normaliza corretamente.

Fontes legislativas:
  - LC 123/2006 Art. 18-A §4º V (MEI não contribuinte)
  - LC 214/2025 Arts. 47 §2º, 344, 353 §1º, 348 (transição)
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


CNPJ_VALIDO = "54657895000160"


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


def _payload_base() -> dict:
    return {
        "cnpj": CNPJ_VALIDO,
        "razao_social": "Empresa Fase 3.2.1 LTDA",
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


# ─────────────────────────────────────────────────────────────────────────────
# Achado #2 do Luiz — Fronteira temporal 2026 → 2027 no Split Payment
# ─────────────────────────────────────────────────────────────────────────────

class TestFronteiraSplitPayment2026_2027:
    """
    Emissão em dezembro/2026 + liquidação em janeiro/2027.
    Regra atual: Split Payment liga em 1º/jan/2027 (LC 214/2025 Art. 344).
    Motor deve registrar a transição na trilha — ou via step explícito,
    ou via motivo granular de "inativo por ano < 2027" no retorno do
    split_payment_impacto.
    """

    def _payload_fronteira(self) -> dict:
        return {
            **_payload_base(),
            "data_emissao": "2026-12-28",
            "forma_recebimento": "PIX_VIA_PSP",
        }

    def test_emissao_2026_dezembro_split_inativo_por_ano(self, client):
        """Mesmo com PSP, emissão em 2026 não dispara split — Art. 344."""
        resp = client.post("/analise/manual", json=self._payload_fronteira())
        assert resp.status_code == 200, resp.text
        diag = resp.json()["diagnostico"]
        split = diag.get("split_payment") or {}
        # Motor deve relatar split inativo com motivo citando ano < 2027
        assert split.get("ativo") is False, f"split deveria ser inativo em 2026: {split}"
        motivo = str(split.get("motivo", ""))
        assert "2027" in motivo or "Art. 344" in motivo or "não ativo" in motivo.lower(), (
            f"motivo da inativação deveria citar Art. 344 ou 2027: {motivo}"
        )

    def test_emissao_2026_dezembro_intermediado_por_psp_registrado(self, client):
        """Mesmo inativo, a flag intermediado_por_psp deve refletir o PSP."""
        resp = client.post("/analise/manual", json=self._payload_fronteira())
        assert resp.status_code == 200
        split = resp.json()["diagnostico"].get("split_payment") or {}
        assert split.get("intermediado_por_psp") is True, (
            f"PIX_VIA_PSP sempre tem PSP, mesmo com split inativo: {split}"
        )

    def test_emissao_2027_janeiro_split_ativo(self, client):
        """Janeiro/2027 com PSP dispara Split Payment — confirma fronteira."""
        payload = {
            **_payload_base(),
            "data_emissao": "2027-01-05",
            "forma_recebimento": "PIX_VIA_PSP",
        }
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 200
        split = resp.json()["diagnostico"].get("split_payment") or {}
        assert split.get("ativo") is True, f"split deveria estar ativo em 2027: {split}"


# ─────────────────────────────────────────────────────────────────────────────
# Achado #3 do Luiz — MEI + B2B_CONTRIBUINTE é inconsistente
# ─────────────────────────────────────────────────────────────────────────────

class TestAlertaMeiNaoContribuinte:
    """
    LC 123/2006 Art. 18-A §4º V — MEI NÃO é contribuinte de IBS/CBS.
    Combinação tipo_comprador=B2B_CONTRIBUINTE + regime_comprador=MEI é
    semanticamente incoerente: motor deve alertar via trilha de auditoria.
    Sem esse alerta, auditor poderia inferir (erroneamente) direito a crédito
    cruzado que não existe.
    """

    def _payload_mei_b2b(self) -> dict:
        return {
            **_payload_base(),
            "tipo_comprador": "B2B_CONTRIBUINTE",
            "regime_comprador": "MEI",
        }

    def test_alerta_mei_nao_contribuinte_presente_na_trilha(self, client):
        resp = client.post("/analise/manual", json=self._payload_mei_b2b())
        assert resp.status_code == 200, resp.text
        diag = resp.json()["diagnostico"]
        trilha = diag.get("trilha_auditoria") or []
        alertas_mei = [p for p in trilha if p.get("tipo") == "ALERTA_MEI_NAO_CONTRIBUINTE"]
        assert len(alertas_mei) == 1, (
            f"esperava 1 alerta ALERTA_MEI_NAO_CONTRIBUINTE, veio {len(alertas_mei)}: "
            f"{[p.get('tipo') for p in trilha]}"
        )

    def test_alerta_mei_cita_amparo_legal_completo(self, client):
        resp = client.post("/analise/manual", json=self._payload_mei_b2b())
        trilha = resp.json()["diagnostico"].get("trilha_auditoria") or []
        alerta = next(p for p in trilha if p.get("tipo") == "ALERTA_MEI_NAO_CONTRIBUINTE")
        amparo = alerta.get("amparo_legal", "")
        # Amparo obrigatório em ambas as leis (LC 123 para o MEI, LC 214 para o crédito)
        assert "18-A" in amparo, f"falta LC 123/2006 Art. 18-A em '{amparo}'"
        assert "214/2025" in amparo or "47" in amparo, f"falta LC 214/2025 em '{amparo}'"

    def test_mei_com_tipo_b2c_nao_dispara_alerta(self, client):
        """Regressão: MEI + B2C é combinação legítima, NÃO deve alertar."""
        payload = {
            **_payload_base(),
            "tipo_comprador": "B2C_CONSUMIDOR_FINAL",
            "regime_comprador": "MEI",
            "percentual_b2b": "100",  # valor default quando não é MISTO
        }
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 200
        trilha = resp.json()["diagnostico"].get("trilha_auditoria") or []
        alertas_mei = [p for p in trilha if p.get("tipo") == "ALERTA_MEI_NAO_CONTRIBUINTE"]
        assert not alertas_mei, (
            f"MEI+B2C é legítimo — não deveria haver alerta MEI. veio {alertas_mei}"
        )

    def test_b2b_contribuinte_com_regime_real_nao_dispara_alerta(self, client):
        """Regressão: B2B + REAL é combinação ideal, NÃO deve alertar."""
        payload = {
            **_payload_base(),
            "tipo_comprador": "B2B_CONTRIBUINTE",
            "regime_comprador": "REAL",
        }
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 200
        trilha = resp.json()["diagnostico"].get("trilha_auditoria") or []
        alertas_mei = [p for p in trilha if p.get("tipo") == "ALERTA_MEI_NAO_CONTRIBUINTE"]
        assert not alertas_mei


# ─────────────────────────────────────────────────────────────────────────────
# Hardening #2 do Viciado — Decimal normaliza "100.00" e "100"
# ─────────────────────────────────────────────────────────────────────────────

class TestPercentualB2bNormalizacaoDecimal:
    """
    ERR-024 — @model_validator de AnaliseManualRequest bloqueia
    tipo != MISTO quando percentual_b2b != 100. A comparação é feita em
    Decimal; Decimal("100.00") == Decimal("100") deve ser True. Testa
    ambas as representações para blindar contra drift futuro que trocasse
    comparação Decimal por string.
    """

    def test_percentual_b2b_string_100_aceito(self, client):
        payload = {**_payload_base(), "percentual_b2b": "100"}
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 200, (
            f"'100' deveria ser aceito: {resp.text[:200]}"
        )

    def test_percentual_b2b_string_100_00_aceito(self, client):
        """Decimal('100.00') == Decimal('100') → passa sem bloqueio ERR-024."""
        payload = {**_payload_base(), "percentual_b2b": "100.00"}
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 200, (
            f"'100.00' deveria ser aceito (Decimal normaliza): {resp.text[:200]}"
        )

    def test_percentual_b2b_string_100_000_aceito(self, client):
        """Paranoia: 3 casas decimais também — Decimal não faz regex match."""
        payload = {**_payload_base(), "percentual_b2b": "100.000"}
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 200

    def test_percentual_b2b_99_bloqueado_em_b2b_contribuinte(self, client):
        """Sanidade: a validação ainda bloqueia valor diferente de 100."""
        payload = {**_payload_base(), "percentual_b2b": "99"}
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 422
