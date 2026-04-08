"""
test_auditoria_documento_db.py — Trava o model AuditoriaDocumentoDB e seus helpers.

Cobre persistência, idempotência, vínculo com diagnóstico, termo de aceite,
listagem por cliente/diagnóstico, log de acesso (LGPD Art. 37) e purge.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Banco em memória — isolamento total entre testes
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import database  # noqa: E402
from database import (  # noqa: E402
    AuditoriaAcessoDB,
    AuditoriaDocumentoDB,
    aceitar_documento,
    buscar_documento_por_hash,
    buscar_documentos_por_cnpj,
    buscar_documentos_por_diagnostico,
    criar_tabelas,
    listar_documentos_purgaveis,
    marcar_documento_purgado,
    registrar_acesso_documento,
    registrar_documento_auditoria,
)
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import SQLModel, create_engine  # noqa: E402


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
CNPJ_A = "54657895000160"
CNPJ_B = "08172834000100"


@pytest.fixture(autouse=True)
def db_em_memoria(monkeypatch):
    """Cada teste recebe um banco SQLite em memória limpo."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    yield engine


# ── Registro de documento ──────────────────────────────────────────────────


def test_registrar_documento_basico():
    doc = registrar_documento_auditoria(
        hash_sha256=HASH_A,
        empresa_cnpj=CNPJ_A,
        nome_original="PGDASD-EXTRATO.pdf",
        tamanho_bytes=12345,
        storage_path="auditoria/anon123/abc.bin",
    )
    assert doc.id is not None
    assert doc.hash_sha256 == HASH_A
    assert doc.empresa_cnpj == CNPJ_A
    assert doc.nome_original == "PGDASD-EXTRATO.pdf"
    assert doc.mime_type == "application/pdf"
    assert doc.tamanho_bytes == 12345
    assert doc.purged_at is None
    assert doc.aceito_em is None  # ainda não aceito


def test_registrar_documento_com_metadados_completos():
    doc = registrar_documento_auditoria(
        hash_sha256=HASH_A,
        empresa_cnpj=CNPJ_A,
        nome_original="DAS_01_2026.pdf",
        tamanho_bytes=8192,
        storage_path="auditoria/x/y.bin",
        paginas=2,
        uploaded_by_user_id=42,
        diagnostico_id=99,
    )
    assert doc.paginas == 2
    assert doc.uploaded_by_user_id == 42
    assert doc.diagnostico_id == 99


def test_registrar_documento_define_purge_after_5_anos():
    doc = registrar_documento_auditoria(
        hash_sha256=HASH_A,
        empresa_cnpj=CNPJ_A,
        nome_original="x.pdf",
        tamanho_bytes=100,
        storage_path="x.bin",
    )
    uploaded = datetime.fromisoformat(doc.uploaded_at)
    purge = datetime.fromisoformat(doc.purge_after)
    delta_dias = (purge - uploaded).days
    # 5 anos = ~1825 dias (margem para anos bissextos)
    assert 1820 <= delta_dias <= 1830


def test_registrar_documento_idempotente():
    """Re-upload do mesmo arquivo (mesmo hash) não duplica."""
    doc1 = registrar_documento_auditoria(
        hash_sha256=HASH_A,
        empresa_cnpj=CNPJ_A,
        nome_original="x.pdf",
        tamanho_bytes=100,
        storage_path="x.bin",
    )
    doc2 = registrar_documento_auditoria(
        hash_sha256=HASH_A,
        empresa_cnpj=CNPJ_A,
        nome_original="x.pdf",  # mesmo arquivo
        tamanho_bytes=100,
        storage_path="x.bin",
    )
    assert doc1.id == doc2.id


def test_re_upload_atualiza_diagnostico_id():
    """Re-upload do mesmo arquivo numa nova análise vincula o novo diagnóstico."""
    doc1 = registrar_documento_auditoria(
        hash_sha256=HASH_A,
        empresa_cnpj=CNPJ_A,
        nome_original="x.pdf",
        tamanho_bytes=100,
        storage_path="x.bin",
        diagnostico_id=10,
    )
    doc2 = registrar_documento_auditoria(
        hash_sha256=HASH_A,
        empresa_cnpj=CNPJ_A,
        nome_original="x.pdf",
        tamanho_bytes=100,
        storage_path="x.bin",
        diagnostico_id=20,  # nova análise
    )
    assert doc1.id == doc2.id
    assert doc2.diagnostico_id == 20


def test_hash_invalido_levanta():
    with pytest.raises(ValueError, match="hash_sha256 invalido"):
        registrar_documento_auditoria(
            hash_sha256="curto",
            empresa_cnpj=CNPJ_A,
            nome_original="x.pdf",
            tamanho_bytes=100,
            storage_path="x.bin",
        )


def test_cnpj_vazio_levanta():
    with pytest.raises(ValueError, match="obrigatorios"):
        registrar_documento_auditoria(
            hash_sha256=HASH_A,
            empresa_cnpj="",
            nome_original="x.pdf",
            tamanho_bytes=100,
            storage_path="x.bin",
        )


def test_tamanho_zero_levanta():
    with pytest.raises(ValueError, match="tamanho_bytes invalido"):
        registrar_documento_auditoria(
            hash_sha256=HASH_A,
            empresa_cnpj=CNPJ_A,
            nome_original="x.pdf",
            tamanho_bytes=0,
            storage_path="x.bin",
        )


# ── Termo de aceite ─────────────────────────────────────────────────────────


def test_aceitar_documento():
    doc = registrar_documento_auditoria(
        hash_sha256=HASH_A,
        empresa_cnpj=CNPJ_A,
        nome_original="x.pdf",
        tamanho_bytes=100,
        storage_path="x.bin",
    )
    assert doc.aceito_em is None

    atualizado = aceitar_documento(doc.id, aceito_por_user_id=7, aceito_ip="192.168.0.1")
    assert atualizado is not None
    assert atualizado.aceito_em is not None
    assert atualizado.aceito_por_user_id == 7
    assert atualizado.aceito_ip == "192.168.0.1"


def test_aceitar_documento_inexistente_retorna_none():
    assert aceitar_documento(99999, aceito_por_user_id=1) is None


# ── Buscas ──────────────────────────────────────────────────────────────────


def test_buscar_por_hash():
    doc = registrar_documento_auditoria(
        hash_sha256=HASH_A,
        empresa_cnpj=CNPJ_A,
        nome_original="x.pdf",
        tamanho_bytes=100,
        storage_path="x.bin",
    )
    encontrado = buscar_documento_por_hash(HASH_A)
    assert encontrado is not None
    assert encontrado.id == doc.id


def test_buscar_por_hash_inexistente_retorna_none():
    assert buscar_documento_por_hash("z" * 64) is None


def test_buscar_documentos_por_cnpj():
    registrar_documento_auditoria(
        hash_sha256=HASH_A, empresa_cnpj=CNPJ_A,
        nome_original="a.pdf", tamanho_bytes=100, storage_path="a.bin",
    )
    registrar_documento_auditoria(
        hash_sha256=HASH_B, empresa_cnpj=CNPJ_A,
        nome_original="b.pdf", tamanho_bytes=200, storage_path="b.bin",
    )
    registrar_documento_auditoria(
        hash_sha256=HASH_C, empresa_cnpj=CNPJ_B,
        nome_original="c.pdf", tamanho_bytes=300, storage_path="c.bin",
    )
    docs = buscar_documentos_por_cnpj(CNPJ_A)
    assert len(docs) == 2
    nomes = {d.nome_original for d in docs}
    assert nomes == {"a.pdf", "b.pdf"}


def test_buscar_por_cnpj_nao_retorna_purgados():
    doc = registrar_documento_auditoria(
        hash_sha256=HASH_A, empresa_cnpj=CNPJ_A,
        nome_original="x.pdf", tamanho_bytes=100, storage_path="x.bin",
    )
    marcar_documento_purgado(doc.id)
    docs = buscar_documentos_por_cnpj(CNPJ_A)
    assert len(docs) == 0


def test_buscar_documentos_por_diagnostico():
    registrar_documento_auditoria(
        hash_sha256=HASH_A, empresa_cnpj=CNPJ_A,
        nome_original="a.pdf", tamanho_bytes=100, storage_path="a.bin",
        diagnostico_id=42,
    )
    registrar_documento_auditoria(
        hash_sha256=HASH_B, empresa_cnpj=CNPJ_A,
        nome_original="b.pdf", tamanho_bytes=200, storage_path="b.bin",
        diagnostico_id=42,
    )
    registrar_documento_auditoria(
        hash_sha256=HASH_C, empresa_cnpj=CNPJ_A,
        nome_original="c.pdf", tamanho_bytes=300, storage_path="c.bin",
        diagnostico_id=99,  # outra análise
    )
    docs = buscar_documentos_por_diagnostico(42)
    assert len(docs) == 2
    assert all(d.diagnostico_id == 42 for d in docs)


# ── Log de acesso LGPD Art. 37 ──────────────────────────────────────────────


def test_registrar_acesso_documento():
    doc = registrar_documento_auditoria(
        hash_sha256=HASH_A, empresa_cnpj=CNPJ_A,
        nome_original="x.pdf", tamanho_bytes=100, storage_path="x.bin",
    )
    log = registrar_acesso_documento(
        documento_id=doc.id,
        motivo="Geracao de dossie de prova",
        acessado_por_user_id=7,
        ip="10.0.0.1",
    )
    assert log.id is not None
    assert log.documento_id == doc.id
    assert log.motivo == "Geracao de dossie de prova"
    assert log.acessado_por_user_id == 7
    assert log.ip == "10.0.0.1"
    assert log.acessado_em is not None


def test_registrar_acesso_motivo_vazio_levanta():
    with pytest.raises(ValueError, match="motivo do acesso e obrigatorio"):
        registrar_acesso_documento(documento_id=1, motivo="")


def test_registrar_acesso_motivo_truncado_a_500_chars():
    doc = registrar_documento_auditoria(
        hash_sha256=HASH_A, empresa_cnpj=CNPJ_A,
        nome_original="x.pdf", tamanho_bytes=100, storage_path="x.bin",
    )
    motivo_longo = "x" * 1000
    log = registrar_acesso_documento(documento_id=doc.id, motivo=motivo_longo)
    assert len(log.motivo) == 500


# ── Purge LGPD Art. 16 ──────────────────────────────────────────────────────


def test_listar_documentos_purgaveis_vazio_inicialmente():
    registrar_documento_auditoria(
        hash_sha256=HASH_A, empresa_cnpj=CNPJ_A,
        nome_original="x.pdf", tamanho_bytes=100, storage_path="x.bin",
    )
    # Acabou de criar — purge_after = +5 anos, nada pra purgar hoje
    assert listar_documentos_purgaveis() == []


def test_listar_documentos_purgaveis_com_referencia_futura():
    """Simula o cron rodando 6 anos no futuro."""
    registrar_documento_auditoria(
        hash_sha256=HASH_A, empresa_cnpj=CNPJ_A,
        nome_original="x.pdf", tamanho_bytes=100, storage_path="x.bin",
    )
    futuro = datetime.now() + timedelta(days=365 * 6)
    purgaveis = listar_documentos_purgaveis(referencia=futuro)
    assert len(purgaveis) == 1


def test_marcar_documento_purgado():
    doc = registrar_documento_auditoria(
        hash_sha256=HASH_A, empresa_cnpj=CNPJ_A,
        nome_original="x.pdf", tamanho_bytes=100, storage_path="x.bin",
    )
    assert doc.purged_at is None
    atualizado = marcar_documento_purgado(doc.id)
    assert atualizado is not None
    assert atualizado.purged_at is not None


def test_documento_purgado_sumido_de_listar_purgaveis():
    doc = registrar_documento_auditoria(
        hash_sha256=HASH_A, empresa_cnpj=CNPJ_A,
        nome_original="x.pdf", tamanho_bytes=100, storage_path="x.bin",
    )
    marcar_documento_purgado(doc.id)
    futuro = datetime.now() + timedelta(days=365 * 6)
    assert listar_documentos_purgaveis(referencia=futuro) == []


def test_marcar_purgado_inexistente_retorna_none():
    assert marcar_documento_purgado(99999) is None


# ── Integração com diagnóstico ──────────────────────────────────────────────


def test_documento_pode_ser_criado_sem_diagnostico_e_vinculado_depois():
    """Cenário realista: doc é cifrado primeiro, diagnóstico depois."""
    doc = registrar_documento_auditoria(
        hash_sha256=HASH_A, empresa_cnpj=CNPJ_A,
        nome_original="x.pdf", tamanho_bytes=100, storage_path="x.bin",
        # sem diagnostico_id ainda
    )
    assert doc.diagnostico_id is None

    # Depois que o motor rodar, a API chama o registrar de novo com o ID
    atualizado = registrar_documento_auditoria(
        hash_sha256=HASH_A, empresa_cnpj=CNPJ_A,
        nome_original="x.pdf", tamanho_bytes=100, storage_path="x.bin",
        diagnostico_id=55,
    )
    assert atualizado.id == doc.id
    assert atualizado.diagnostico_id == 55
