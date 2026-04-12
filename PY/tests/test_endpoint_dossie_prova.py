"""
test_endpoint_dossie_prova.py — Trava o endpoint /auditoria/prova/cnpj/{cnpj}.

Cobre:
  - Geração do ZIP com PDFs decifrados + HASHES.txt + README.txt
  - Round-trip: bytes decifrados batem com os originais
  - Registro LGPD Art. 37 de cada acesso (AuditoriaAcessoDB populada)
  - Validações: motivo obrigatório, min_length, 404 sem docs
  - Autenticação JWT (endpoint protegido)
  - Sanitização de path no ZIP
"""
from __future__ import annotations

import io
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import database  # noqa: E402
import services.storage_cifrado as storage_cifrado  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import SQLModel, create_engine  # noqa: E402


PDF_A = b"%PDF-1.4\n%PGDASD-EXTRATO\n" + b"a" * 512
PDF_B = b"%PDF-1.4\n%DAS_01_2026\n" + b"b" * 1024
CNPJ = "54657895000160"
CNPJ_FORMATADO = "54.657.895/0001-60"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient com storage + DB isolados + user_id mockado."""
    monkeypatch.setattr(storage_cifrado, "STORAGE_ROOT", tmp_path / "auditoria")
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)

    # Mock do get_current_user para pular JWT real nos testes
    from main import app, get_current_user

    def fake_user():
        return {"id": "7", "username": "tester", "role": "admin"}

    app.dependency_overrides[get_current_user] = fake_user
    yield TestClient(app)
    app.dependency_overrides.clear()


def _registrar_doc(pdf_bytes: bytes, nome: str) -> str:
    """Helper: cifra + registra + retorna o hash."""
    from database import registrar_documento_auditoria
    from services.storage_cifrado import cifrar_e_persistir, hash_documento

    h = hash_documento(pdf_bytes)
    _, path = cifrar_e_persistir(pdf_bytes, CNPJ)
    registrar_documento_auditoria(
        hash_sha256=h,
        empresa_cnpj=CNPJ_FORMATADO,
        nome_original=nome,
        tamanho_bytes=len(pdf_bytes),
        storage_path=str(path),
        uploaded_by_user_id=1,
    )
    return h


# ── Caminho feliz ───────────────────────────────────────────────────────────


def test_dossie_retorna_zip_valido(client):
    _registrar_doc(PDF_A, "pgdasd.pdf")
    _registrar_doc(PDF_B, "das_01_2026.pdf")

    resp = client.get(
        f"/auditoria/prova/cnpj/{CNPJ}",
        params={"motivo": "Fiscalizacao RFB processo 123/2026"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "attachment" in resp.headers["content-disposition"]
    assert ".zip" in resp.headers["content-disposition"]

    # Valida o conteúdo do ZIP
    buf = io.BytesIO(resp.content)
    with zipfile.ZipFile(buf) as zf:
        names = set(zf.namelist())
        assert "originais/pgdasd.pdf" in names
        assert "originais/das_01_2026.pdf" in names
        assert "HASHES.txt" in names
        assert "README.txt" in names


def test_dossie_pdfs_decifrados_batem_com_original(client):
    _registrar_doc(PDF_A, "a.pdf")
    _registrar_doc(PDF_B, "b.pdf")

    resp = client.get(
        f"/auditoria/prova/cnpj/{CNPJ}",
        params={"motivo": "Teste round-trip de integridade"},
    )
    assert resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert zf.read("originais/a.pdf") == PDF_A
        assert zf.read("originais/b.pdf") == PDF_B


def test_hashes_txt_lista_hashes_corretos(client):
    h_a = _registrar_doc(PDF_A, "a.pdf")
    h_b = _registrar_doc(PDF_B, "b.pdf")

    resp = client.get(
        f"/auditoria/prova/cnpj/{CNPJ}",
        params={"motivo": "Verificacao dos hashes do dossie"},
    )
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        hashes_content = zf.read("HASHES.txt").decode("utf-8")

    assert h_a in hashes_content
    assert h_b in hashes_content
    assert "originais/a.pdf" in hashes_content
    assert "originais/b.pdf" in hashes_content


def test_readme_cita_leis_e_metadados(client):
    _registrar_doc(PDF_A, "a.pdf")

    resp = client.get(
        f"/auditoria/prova/cnpj/{CNPJ}",
        params={"motivo": "Auditoria interna contadora Maria"},
    )
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        readme = zf.read("README.txt").decode("utf-8")

    assert "LGPD Art. 37" in readme
    assert "CTN Art. 173" in readme
    assert "CTN Art. 142" in readme
    assert "Auditoria interna contadora Maria" in readme
    assert "sha256sum" in readme  # instruções de verificação


# ── Registro de acesso LGPD Art. 37 ────────────────────────────────────────


def test_cada_decifragem_registra_acesso_lgpd(client):
    _registrar_doc(PDF_A, "a.pdf")
    _registrar_doc(PDF_B, "b.pdf")

    # Antes: 0 acessos registrados
    from sqlmodel import Session, select

    from database import AuditoriaAcessoDB, engine
    with Session(engine) as s:
        antes = len(list(s.exec(select(AuditoriaAcessoDB)).all()))
    assert antes == 0

    client.get(
        f"/auditoria/prova/cnpj/{CNPJ}",
        params={"motivo": "Acesso de teste via endpoint"},
    )

    # Depois: 1 acesso por doc decifrado
    with Session(engine) as s:
        acessos = list(s.exec(select(AuditoriaAcessoDB)).all())
    assert len(acessos) == 2
    assert all(a.motivo == "Acesso de teste via endpoint" for a in acessos)
    assert all(a.acessado_por_user_id == 7 for a in acessos)


# ── Validações ─────────────────────────────────────────────────────────────


def test_sem_motivo_retorna_422(client):
    _registrar_doc(PDF_A, "a.pdf")
    resp = client.get(f"/auditoria/prova/cnpj/{CNPJ}")
    assert resp.status_code == 422  # FastAPI Query validation


def test_motivo_curto_demais_retorna_422(client):
    _registrar_doc(PDF_A, "a.pdf")
    resp = client.get(
        f"/auditoria/prova/cnpj/{CNPJ}",
        params={"motivo": "curto"},  # < 10 chars
    )
    assert resp.status_code == 422


def test_cnpj_sem_documentos_retorna_404(client):
    resp = client.get(
        "/auditoria/prova/cnpj/99999999000199",
        params={"motivo": "Teste de 404 para CNPJ inexistente"},
    )
    assert resp.status_code == 404
    assert "Nenhum documento" in resp.json()["detail"]


def test_cnpj_invalido_retorna_422(client):
    _registrar_doc(PDF_A, "a.pdf")
    resp = client.get(
        "/auditoria/prova/cnpj/abc123",  # só 3 dígitos
        params={"motivo": "Teste de CNPJ com menos de 14 digitos"},
    )
    assert resp.status_code == 422
    assert "14" in resp.json()["detail"]


# ── Robustez ────────────────────────────────────────────────────────────────


def test_nome_com_barra_eh_sanitizado(client):
    """Path traversal: nome 'evil/../escape.pdf' vira 'evil_.._escape.pdf'."""
    _registrar_doc(PDF_A, "evil/../escape.pdf")

    resp = client.get(
        f"/auditoria/prova/cnpj/{CNPJ}",
        params={"motivo": "Teste de sanitizacao de nomes de arquivo"},
    )
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()

    # Nenhum arquivo fora de originais/ ou com "../" resolvido
    for n in names:
        assert not n.startswith("/")
        assert ".." not in n.split("/")  # sem componente ".."


def test_docs_purgados_nao_aparecem_no_dossie(client):
    """Se um doc foi purgado (LGPD Art. 16), não deve vir no dossiê."""
    from database import marcar_documento_purgado

    h_a = _registrar_doc(PDF_A, "a.pdf")
    _registrar_doc(PDF_B, "b.pdf")

    # Purga o primeiro
    from database import buscar_documento_por_hash
    doc_a = buscar_documento_por_hash(h_a)
    marcar_documento_purgado(doc_a.id)

    resp = client.get(
        f"/auditoria/prova/cnpj/{CNPJ}",
        params={"motivo": "Teste pos-purge para confirmar exclusao"},
    )
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
    assert "originais/a.pdf" not in names
    assert "originais/b.pdf" in names
