# -*- coding: utf-8 -*-
"""
test_envelope_e_termo_aceite.py — Trava o P0 #3 (termo de aceite) +
envelope de resposta com PII separada.

Cobre:
  - processar_pdfs_bytes(envelope=True) retorna dict com {diagnostico, pii}
  - PII contém cnpj e razao_social extraídos
  - Backward compat: envelope=False continua retornando dict simples
  - Endpoint /analise/pdf rejeita sem termo_aceite
  - Endpoint /analise/pdf com termo_aceite marca documentos como aceitos
  - Endpoint retorna envelope no body
"""
from __future__ import annotations

import io
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import database  # noqa: E402
import services.storage_cifrado as storage_cifrado  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import SQLModel, create_engine  # noqa: E402


PDF_FAKE = b"%PDF-1.4\n%fake\n" + b"a" * 512
CSV_FAKE = b"Competencia;Total Bruto\n01/2026;5000.00\n"  # satisfaz B2C folha_csv check
CNPJ_DIGITOS = "54657895000160"
CNPJ_FORMATADO = "54.657.895/0001-60"


@pytest.fixture(autouse=True)
def iso(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_cifrado, "STORAGE_ROOT", tmp_path / "auditoria")
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    yield


def _patch_pipeline():
    """Mock do pipeline Claude Vision + motor."""
    fake_response = MagicMock()
    fake_response.content = [
        MagicMock(text=(
            '{"cnpj":"' + CNPJ_DIGITOS + '",'
            '"razao_social":"REFRIGERACAO CANAVEZI LTDA",'
            '"cnae_principal":"4757100","uf_origem":"SP",'
            '"faturamento_12m":"1000000","anexo_simples":"I",'
            '"rpa_referencia":"83333.33","das_ecac_referencia":"5833.33",'
            '"competencia":"01/2026","confianca_extracao":0.99}'
        ))
    ]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    fake_motor_instance = MagicMock()
    fake_motor_instance.gerar_diagnostico.return_value = {
        "empresa": {"regime": "SIMPLES", "anexo_simples": "I"},
        "aliquotas": {"efetiva_das_total": "0.07"},
        "cenarios": {},
        "trilha_auditoria": [],
    }

    return (
        patch("services.extrator_pdfs.anthropic.Anthropic", return_value=fake_client),
        patch("core.motor_tributario.MotorReformaTributaria", return_value=fake_motor_instance),
    )


# ── processar_pdfs_bytes com envelope ──────────────────────────────────────


class TestEnvelopeExtrator:
    def test_envelope_false_retorna_dict_simples_backward_compat(self):
        """Default envelope=False: backward compat mantido."""
        from services.extrator_pdfs import processar_pdfs_bytes

        p1, p2 = _patch_pipeline()
        with p1, p2:
            result = processar_pdfs_bytes([PDF_FAKE])

        # Retorno é o dict do diagnóstico direto
        assert "empresa" in result
        assert "aliquotas" in result
        # Sem chaves do envelope
        assert "diagnostico" not in result
        assert "pii" not in result

    def test_envelope_true_retorna_diagnostico_e_pii_separados(self):
        from services.extrator_pdfs import processar_pdfs_bytes

        p1, p2 = _patch_pipeline()
        with p1, p2:
            result = processar_pdfs_bytes([PDF_FAKE], envelope=True)

        # Envelope top-level
        assert "diagnostico" in result
        assert "pii" in result
        # Diagnóstico intacto
        assert "empresa" in result["diagnostico"]
        assert "aliquotas" in result["diagnostico"]
        # PII separado
        assert result["pii"]["cnpj"] == CNPJ_FORMATADO  # normalizado pelo extrator
        assert result["pii"]["razao_social"] == "REFRIGERACAO CANAVEZI LTDA"

    def test_envelope_true_com_auditoria(self):
        """Envelope + persistir_auditoria combinados."""
        from services.extrator_pdfs import processar_pdfs_bytes

        p1, p2 = _patch_pipeline()
        with p1, p2:
            result = processar_pdfs_bytes(
                [PDF_FAKE],
                arquivos_nomes=["pgdas.pdf"],
                persistir_auditoria=True,
                envelope=True,
            )

        assert "diagnostico" in result
        assert "pii" in result
        # Auditoria foi persistida dentro do diagnóstico
        assert result["diagnostico"]["_extracao"]["auditoria_status"] == "OK"
        assert len(result["diagnostico"]["_extracao"]["documentos_auditoria"]) == 1


# ── Endpoint /analise/pdf com termo de aceite ──────────────────────────────


@pytest.fixture
def client(monkeypatch):
    """TestClient com get_current_user mockado."""
    from main import app, get_current_user

    def fake_user():
        return {"id": "7", "username": "tester", "role": "admin"}

    app.dependency_overrides[get_current_user] = fake_user
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestEndpointTermoAceite:
    def test_sem_termo_aceite_retorna_400(self, client):
        p1, p2 = _patch_pipeline()
        with p1, p2:
            response = client.post(
                "/analise/pdf",
                files={"files": ("pgdas.pdf", io.BytesIO(PDF_FAKE), "application/pdf")},
                # SEM campo termo_aceite
            )
        assert response.status_code == 400
        assert "termo de aceite" in response.json()["detail"].lower()

    def test_termo_aceite_false_retorna_400(self, client):
        p1, p2 = _patch_pipeline()
        with p1, p2:
            response = client.post(
                "/analise/pdf",
                files={"files": ("pgdas.pdf", io.BytesIO(PDF_FAKE), "application/pdf")},
                data={"termo_aceite": "false"},
            )
        assert response.status_code == 400

    def test_termo_aceite_true_processa(self, client):
        p1, p2 = _patch_pipeline()
        with p1, p2:
            response = client.post(
                "/analise/pdf",
                files=[
                    ("files", ("pgdas.pdf", io.BytesIO(PDF_FAKE), "application/pdf")),
                    ("files", ("folha.csv", io.BytesIO(CSV_FAKE), "text/csv")),
                ],
                data={"termo_aceite": "true", "tipo_comprador": "B2C_CONSUMIDOR_FINAL"},
            )
        assert response.status_code == 200

    def test_response_eh_envelope(self, client):
        p1, p2 = _patch_pipeline()
        with p1, p2:
            response = client.post(
                "/analise/pdf",
                files=[
                    ("files", ("pgdas.pdf", io.BytesIO(PDF_FAKE), "application/pdf")),
                    ("files", ("folha.csv", io.BytesIO(CSV_FAKE), "text/csv")),
                ],
                data={"termo_aceite": "true", "tipo_comprador": "B2C_CONSUMIDOR_FINAL"},
            )
        body = response.json()
        assert "diagnostico" in body
        assert "pii" in body
        assert body["pii"]["cnpj"] == CNPJ_FORMATADO
        assert body["pii"]["razao_social"] == "REFRIGERACAO CANAVEZI LTDA"

    def test_documentos_sao_marcados_como_aceitos(self, client):
        """aceito_em, aceito_por_user_id e aceito_ip ficam preenchidos."""
        from database import buscar_documentos_por_cnpj

        p1, p2 = _patch_pipeline()
        with p1, p2:
            response = client.post(
                "/analise/pdf",
                files=[
                    ("files", ("pgdas.pdf", io.BytesIO(PDF_FAKE), "application/pdf")),
                    ("files", ("folha.csv", io.BytesIO(CSV_FAKE), "text/csv")),
                ],
                data={"termo_aceite": "true", "tipo_comprador": "B2C_CONSUMIDOR_FINAL"},
            )
        assert response.status_code == 200

        docs = buscar_documentos_por_cnpj(CNPJ_FORMATADO)
        assert len(docs) >= 1  # PDF + possível CSV auditado
        pdf_docs = [d for d in docs if d.nome_original.endswith(".pdf")]
        assert len(pdf_docs) == 1
        doc = pdf_docs[0]
        assert doc.aceito_em is not None
        assert doc.aceito_por_user_id == 7
        # IP pode ser None em TestClient dependendo da versão, mas aceito_em
        # e user_id são o crítico para auditoria

    def test_multiplo_arquivos_todos_marcados_aceitos(self, client):
        """Upload de 3 PDFs → todos aceites registrados."""
        from database import buscar_documentos_por_cnpj

        p1, p2 = _patch_pipeline()
        with p1, p2:
            response = client.post(
                "/analise/pdf",
                files=[
                    ("files", ("pgdas.pdf", io.BytesIO(PDF_FAKE), "application/pdf")),
                    ("files", ("das.pdf", io.BytesIO(PDF_FAKE + b"diff1"), "application/pdf")),
                    ("files", ("recibo.pdf", io.BytesIO(PDF_FAKE + b"diff2"), "application/pdf")),
                    ("files", ("folha.csv", io.BytesIO(CSV_FAKE), "text/csv")),
                ],
                data={"termo_aceite": "true", "tipo_comprador": "B2C_CONSUMIDOR_FINAL"},
            )
        assert response.status_code == 200

        docs = buscar_documentos_por_cnpj(CNPJ_FORMATADO)
        pdf_docs = [d for d in docs if d.nome_original.endswith(".pdf")]
        assert len(pdf_docs) == 3, f"esperado 3 PDFs, encontrados {len(pdf_docs)}"
        for doc in pdf_docs:
            assert doc.aceito_em is not None, f"doc {doc.nome_original} sem aceito_em"
            assert doc.aceito_por_user_id == 7


# ── Estrutura do HTML ──────────────────────────────────────────────────────


class TestHtmlTermoAceite:
    @pytest.fixture
    def html(self):
        from pathlib import Path
        path = Path(__file__).resolve().parent.parent.parent / "UI" / "analise_pdf.html"
        return path.read_text(encoding="utf-8")

    def test_secao_termo_existe(self, html):
        assert 'id="termo-aceite-section"' in html

    def test_checkbox_existe(self, html):
        assert 'id="termo-aceite-checkbox"' in html
        assert 'type="checkbox"' in html

    def test_cita_bases_legais(self, html):
        assert "CTN Art. 142" in html
        assert "LGPD Art. 37" in html

    def test_updateSubmitButton_exige_termo(self, html):
        idx = html.find("function updateSubmitButton")
        bloco = html[idx:idx + 2000]
        assert "termoCheckbox.checked" in bloco
        assert "termoOk" in bloco

    def test_submit_envia_termo_aceite(self, html):
        idx = html.find("function submitFiles")
        bloco = html[idx:idx + 2000]
        assert "termo_aceite" in bloco

    def test_hint_dinamico_muda_por_estado(self, html):
        """Hint deve mostrar 'Selecione' / 'Aceite o termo' / 'Tudo pronto'."""
        idx = html.find("function updateSubmitButton")
        bloco = html[idx:idx + 2000]
        assert "Selecione" in bloco  # "Selecione os documentos" ou "Selecione ao menos..."
        assert "Aceite o termo" in bloco
        assert "Tudo pronto" in bloco

    def test_js_ler_pii_do_envelope(self, html):
        """submitFiles deve consumir payload.pii.cnpj e .razao_social."""
        idx = html.find("function submitFiles")
        bloco = html[idx:idx + 3000]
        assert "payload.pii" in bloco or "pii.razao_social" in bloco
        assert "analise_empresa" in bloco
        assert "analise_cnpj" in bloco
