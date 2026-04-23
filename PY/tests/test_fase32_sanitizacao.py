# -*- coding: utf-8 -*-
"""
test_fase32_sanitizacao.py — Fase 3.2 (sanitização fiscal da UI manual).

Cobre os 4 ERRs fechados por O Viciado:
  - ERR-036: beneficio_fiscal_antigo era DECORATIVO → removido.
             Envio do campo agora dispara 422 extra_forbidden.
  - ERR-037: regime_comprador vira Literal fechado.
             Valor inválido → 422; NAO_INFORMADO default aceito;
             valor válido registrado na trilha_auditoria.
  - ERR-038: forma_recebimento ganha granularidade PSP.
             "PIX_BOLETO" (legado) → 422.
             PIX_DIRETO + 2028 → Split Payment INATIVO (sem PSP).
             PIX_VIA_PSP + 2028 → Split Payment ATIVO.
  - ERR-039: NCM monofásico bloqueado no validator.
             NCM "27101234" (combustível) → 422 com amparo LC 214/2025
             Arts. 172-174. NCM "84818099" (padrão) continua aceito.

Fontes legislativas:
  - LC 214/2025 Arts. 47 §2º, 172-174, 344, 353 §1º
  - CF/88 Art. 149 §2º III
  - MAX_FISCAL_01 e MAX_FISCAL_02 (zero cálculo sem amparo; sem campo fantasma)
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


# ─────────────────────────────────────────────────────────────────────────────
# Fixture compartilhada — espelha test_analise_manual_endpoint.py para manter
# o mesmo contrato de auth/engine.
# ─────────────────────────────────────────────────────────────────────────────

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
    """Payload válido de Simples — usado como base para as variações."""
    return {
        "cnpj": CNPJ_VALIDO,
        "razao_social": "Empresa Fase 3.2 LTDA",
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
# ERR-036 — beneficio_fiscal_antigo removido do schema
# ─────────────────────────────────────────────────────────────────────────────

class TestErr036BeneficioFiscalRemovido:

    def test_campo_legado_rejeitado_com_extra_forbidden(self, client):
        """Envio do campo fantasma agora é 422 (Pydantic extra='forbid')."""
        payload = {**_payload_base(), "beneficio_fiscal_antigo": "1000.00"}
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 422
        detalhes = str(resp.json().get("detail", ""))
        assert "extra_forbidden" in detalhes or "beneficio_fiscal_antigo" in detalhes, (
            f"422 esperado com extra_forbidden, veio: {detalhes}"
        )

    def test_sem_o_campo_continua_funcionando(self, client):
        """Payload sem o campo fantasma segue válido — regressão do happy path."""
        resp = client.post("/analise/manual", json=_payload_base())
        assert resp.status_code == 200, resp.text

    def test_motor_nao_emite_mais_alerta_BENEFICIO_FISCAL_EXTINCAO(self, client):
        """O alerta BENEFICIO_FISCAL_EXTINCAO foi removido do motor."""
        resp = client.post("/analise/manual", json=_payload_base())
        assert resp.status_code == 200
        diag = resp.json()["diagnostico"]
        # Varre alertas e trilha procurando a string — deve estar ausente
        blob = str(diag).upper()
        assert "BENEFICIO_FISCAL_EXTINCAO" not in blob


# ─────────────────────────────────────────────────────────────────────────────
# ERR-037 — regime_comprador como Literal + registro na trilha
# ─────────────────────────────────────────────────────────────────────────────

class TestErr037RegimeCompradorLiteral:

    def test_default_nao_informado_e_aceito(self, client):
        """Sem informar regime_comprador, default NAO_INFORMADO é válido."""
        resp = client.post("/analise/manual", json=_payload_base())
        assert resp.status_code == 200, resp.text

    def test_valor_invalido_rejeitado(self, client):
        """String arbitrária fora do Literal → 422."""
        payload = {**_payload_base(), "regime_comprador": "SIMPLES_PLUS"}
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 422

    def test_todos_regimes_validos_aceitos(self, client):
        """Os 5 valores canônicos do Literal são aceitos."""
        for regime in ("SIMPLES", "PRESUMIDO", "REAL", "MEI", "NAO_INFORMADO"):
            payload = {**_payload_base(), "regime_comprador": regime}
            resp = client.post("/analise/manual", json=payload)
            assert resp.status_code == 200, (
                f"regime_comprador={regime} deveria ser aceito — status {resp.status_code}"
            )

    def test_registro_na_trilha_com_regime_conhecido(self, client):
        """Regime conhecido vai para a trilha com amparo LC 214/2025 Art. 47 §2º."""
        payload = {**_payload_base(), "regime_comprador": "REAL"}
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 200
        trilha = resp.json()["diagnostico"].get("trilha_auditoria") or []
        passo = next(
            (p for p in trilha if p.get("id") == "REGIME_COMPRADOR_CAPTURADO"), None
        )
        assert passo is not None, (
            "Passo REGIME_COMPRADOR_CAPTURADO ausente da trilha. "
            f"IDs presentes: {[p.get('id') for p in trilha]}"
        )
        # O valor capturado entra em memoria.valor_final (formato padrão _registrar_passo).
        mem = passo.get("memoria") or {}
        assert mem.get("valor_final") == "REAL", (
            f"memoria.valor_final esperado 'REAL', veio: {mem.get('valor_final')!r}"
        )
        lei = str(passo.get("lei") or passo.get("amparo_legal") or "")
        assert "47" in lei, f"amparo legal deveria citar Art. 47 §2º, veio: {lei}"

    def test_registro_na_trilha_nao_informado_avisa_pior_caso(self, client):
        """Quando NAO_INFORMADO, a trilha sinaliza pior caso assumido."""
        resp = client.post("/analise/manual", json=_payload_base())
        assert resp.status_code == 200
        trilha = resp.json()["diagnostico"].get("trilha_auditoria") or []
        passo = next(
            (p for p in trilha if p.get("id") == "REGIME_COMPRADOR_CAPTURADO"), None
        )
        assert passo is not None
        detalhe = (passo.get("detalhe") or "").upper()
        assert "PIOR CASO" in detalhe or "PIOR" in detalhe


# ─────────────────────────────────────────────────────────────────────────────
# ERR-038 — forma_recebimento granular (PSP gating)
# ─────────────────────────────────────────────────────────────────────────────

class TestErr038FormaRecebimentoPSP:

    def test_valor_legado_pix_boleto_rejeitado(self, client):
        """PIX_BOLETO deixou de existir — deve dar 422."""
        payload = {**_payload_base(), "forma_recebimento": "PIX_BOLETO"}
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 422

    def test_pix_direto_em_2028_nao_dispara_split(self, client):
        """PIX direto banco-a-banco, sem PSP — Split Payment INATIVO (Art. 353 §1º)."""
        payload = {
            **_payload_base(),
            "data_emissao": "2028-06-15",
            "forma_recebimento": "PIX_DIRETO",
        }
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 200, resp.text
        diag = resp.json()["diagnostico"]
        split = diag.get("split_payment_impacto") or diag.get("split_payment") or {}
        assert split.get("ativo") is False, (
            f"PIX_DIRETO em 2028 não pode disparar Split Payment. Got: {split}"
        )

    def test_pix_via_psp_em_2028_dispara_split(self, client):
        """PIX via PSP em 2028 (ano >= 2027) → Split ATIVO."""
        payload = {
            **_payload_base(),
            "data_emissao": "2028-06-15",
            "forma_recebimento": "PIX_VIA_PSP",
        }
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 200, resp.text
        diag = resp.json()["diagnostico"]
        split = diag.get("split_payment_impacto") or diag.get("split_payment") or {}
        assert split.get("ativo") is True, (
            f"PIX_VIA_PSP em 2028 deveria disparar Split Payment. Got: {split}"
        )

    def test_dinheiro_em_2028_nao_dispara_split(self, client):
        """Regressão — DINHEIRO nunca dispara Split (não passa por PSP)."""
        payload = {
            **_payload_base(),
            "data_emissao": "2028-06-15",
            "forma_recebimento": "DINHEIRO",
        }
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 200
        diag = resp.json()["diagnostico"]
        split = diag.get("split_payment_impacto") or diag.get("split_payment") or {}
        assert split.get("ativo") is False

    def test_boleto_e_cartao_em_2028_disparam_split(self, client):
        """BOLETO e CARTAO passam por PSP → disparam Split."""
        for forma in ("BOLETO", "CARTAO"):
            payload = {
                **_payload_base(),
                "data_emissao": "2028-06-15",
                "forma_recebimento": forma,
            }
            resp = client.post("/analise/manual", json=payload)
            assert resp.status_code == 200, f"{forma}: {resp.text}"
            diag = resp.json()["diagnostico"]
            split = diag.get("split_payment_impacto") or diag.get("split_payment") or {}
            assert split.get("ativo") is True, (
                f"{forma} em 2028 deveria disparar Split. Got: {split}"
            )

    def test_trilha_split_cita_art_353_1(self, client):
        """Quando Split ativo, a trilha cita Art. 353 §1º."""
        payload = {
            **_payload_base(),
            "data_emissao": "2028-06-15",
            "forma_recebimento": "CARTAO",
        }
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 200
        trilha = resp.json()["diagnostico"].get("trilha_auditoria") or []
        passo_split = next(
            (p for p in trilha if p.get("id") == "SPLIT_PAYMENT"), None
        )
        assert passo_split is not None, "Passo SPLIT_PAYMENT deveria estar na trilha"
        lei = str(passo_split.get("lei") or passo_split.get("amparo_legal") or "")
        assert "353" in lei, f"lei deveria citar Art. 353, veio: {lei}"


# ─────────────────────────────────────────────────────────────────────────────
# ERR-039 — NCM monofásico bloqueado no validator Pydantic
# ─────────────────────────────────────────────────────────────────────────────

class TestErr039NcmMonofasicoBloqueado:

    @pytest.mark.parametrize(
        "ncm, capitulo_lei",
        [
            ("27101234", "2710"),  # combustível
            ("24021000", "2402"),  # charuto
            ("24031100", "2403"),  # fumo
            ("22030000", "2203"),  # cerveja
            ("22041000", "2204"),  # vinho
            ("22051000", "2205"),  # vermute
            ("22060000", "2206"),  # fermentadas
            ("22071000", "2207"),  # álcool etílico
            ("22082000", "2208"),  # destilados
        ],
    )
    def test_ncm_monofasico_bloqueado_422(self, client, ncm, capitulo_lei):
        """Qualquer NCM dos capítulos monofásicos retorna 422 com amparo legal."""
        payload = {**_payload_base(), "ncm_nbs": ncm}
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 422, f"NCM {ncm} deveria ser bloqueado"
        detalhes = str(resp.json().get("detail", ""))
        # Mensagem deve citar LC 214/2025 Arts. 172-174
        assert "214/2025" in detalhes or "172" in detalhes, (
            f"NCM {ncm}: mensagem de erro deveria citar LC 214/2025 Arts. 172-174, "
            f"veio: {detalhes}"
        )

    def test_ncm_padrao_industria_continua_aceito(self, client):
        """NCM 84818099 (válvulas industriais) não é monofásico — aceito."""
        payload = {**_payload_base(), "ncm_nbs": "84818099"}
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 200, resp.text

    def test_ncm_00000000_placeholder_continua_aceito(self, client):
        """NCM placeholder 00000000 (serviços sem NCM) não bate com capítulos bloqueados."""
        payload = {**_payload_base(), "ncm_nbs": "00000000"}
        resp = client.post("/analise/manual", json=payload)
        assert resp.status_code == 200, resp.text
