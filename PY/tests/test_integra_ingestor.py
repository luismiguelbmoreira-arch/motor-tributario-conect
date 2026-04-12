"""
test_integra_ingestor.py — Testes do IntegraIngestor.

Usa AdapterFake (não mTLS) + storage real em tmpdir + SQLite in-memory.
Cobre:
    - 12 meses PGDAS-D novos → 12 rows com nome_original correto
    - Re-sincronizar mesma janela → total_duplicados=12
    - PGDAS-D + DAS juntos → 24 docs, 2 tipos
    - 1 período com erro Serpro → outros continuam
    - uploaded_by_user_id propaga
    - CNPJ com pontuação → normalizado
    - to_dict serializável, hashes 16 chars prefix
    - Retificadora → nome com _ret1 sufixo
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Setup ANTES dos imports do projeto
os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import database  # noqa: E402
import services.storage_cifrado as storage_cifrado  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine, select  # noqa: E402

from integrations.integra_adapter import (  # noqa: E402
    IntegraDocumento,
    IntegraError,
)
from integrations.integra_ingestor import (  # noqa: E402
    IntegraIngestor,
    IntegraSyncResult,
)


CNPJ = "12345678000190"
CNPJ_PONTUADO = "12.345.678/0001-90"
PERIODOS_12M = [f"2025-{m:02d}" for m in range(1, 13)]


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def storage_e_db_isolados(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_cifrado, "STORAGE_ROOT", tmp_path / "auditoria")
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    yield


# ─── Adapter Fake ────────────────────────────────────────────────────────


def _pdf_fake(tag: str) -> bytes:
    return f"%PDF-1.4\n%{tag}\n".encode() + tag.encode() * 64


class AdapterFake:
    """Adapter determinístico para teste — não toca rede nem cert."""

    def __init__(self):
        self.erros_pgdasd: dict[str, Exception] = {}
        self.erros_das: dict[str, Exception] = {}
        self.retificadoras: set[str] = set()  # períodos que têm 2 docs PGDAS-D

    def baixar_pgdasd(self, *, cnpj: str, periodo: str):
        if periodo in self.erros_pgdasd:
            raise self.erros_pgdasd[periodo]
        yield IntegraDocumento(
            tipo="pgdasd",
            periodo=periodo,
            cnpj_contribuinte=cnpj,
            conteudo=_pdf_fake(f"pgdasd-{periodo}-orig"),
            mime_type="application/pdf",
            extensao=".pdf",
            metadata={"retificadora": False},
        )
        if periodo in self.retificadoras:
            yield IntegraDocumento(
                tipo="pgdasd",
                periodo=periodo,
                cnpj_contribuinte=cnpj,
                conteudo=_pdf_fake(f"pgdasd-{periodo}-ret"),
                mime_type="application/pdf",
                extensao=".pdf",
                metadata={"retificadora": True},
            )

    def emitir_das(self, *, cnpj: str, periodo: str):
        if periodo in self.erros_das:
            raise self.erros_das[periodo]
        yield IntegraDocumento(
            tipo="das",
            periodo=periodo,
            cnpj_contribuinte=cnpj,
            conteudo=_pdf_fake(f"das-{periodo}"),
            mime_type="application/pdf",
            extensao=".pdf",
            metadata={},
        )


def _listar_docs_integra() -> list[database.AuditoriaDocumentoDB]:
    with Session(database.engine) as sess:
        rows = sess.exec(
            select(database.AuditoriaDocumentoDB).where(
                database.AuditoriaDocumentoDB.nome_original.like("integra::%")
            )
        ).all()
        return list(rows)


# ─── Testes ──────────────────────────────────────────────────────────────


def test_sincroniza_12_meses_pgdasd_novos():
    ingestor = IntegraIngestor(AdapterFake())
    res = ingestor.sincronizar(
        cnpj=CNPJ, periodos=PERIODOS_12M, tipos=("pgdasd",)
    )

    assert res.total_baixados == 12
    assert res.total_novos == 12
    assert res.total_duplicados == 0
    assert res.erros == []
    assert len(res.hashes_novos) == 12

    rows = _listar_docs_integra()
    assert len(rows) == 12
    nomes = sorted(r.nome_original for r in rows)
    assert nomes[0] == "integra::pgdasd_2025-01.pdf"
    assert nomes[-1] == "integra::pgdasd_2025-12.pdf"
    assert all(r.mime_type == "application/pdf" for r in rows)
    assert all(r.empresa_cnpj == CNPJ for r in rows)


def test_re_sincronizacao_marca_como_duplicados():
    ingestor = IntegraIngestor(AdapterFake())
    ingestor.sincronizar(cnpj=CNPJ, periodos=PERIODOS_12M, tipos=("pgdasd",))

    res2 = ingestor.sincronizar(
        cnpj=CNPJ, periodos=PERIODOS_12M, tipos=("pgdasd",)
    )
    assert res2.total_baixados == 12
    assert res2.total_novos == 0
    assert res2.total_duplicados == 12
    assert res2.hashes_novos == []
    assert len(_listar_docs_integra()) == 12


def test_pgdasd_e_das_juntos_produzem_24_docs():
    ingestor = IntegraIngestor(AdapterFake())
    res = ingestor.sincronizar(
        cnpj=CNPJ, periodos=PERIODOS_12M, tipos=("pgdasd", "das")
    )
    assert res.total_baixados == 24
    assert res.total_novos == 24

    rows = _listar_docs_integra()
    assert len(rows) == 24
    pgdasd = [r for r in rows if r.nome_original.startswith("integra::pgdasd_")]
    das = [r for r in rows if r.nome_original.startswith("integra::das_")]
    assert len(pgdasd) == 12
    assert len(das) == 12


def test_erro_em_um_periodo_nao_aborta_outros():
    adapter = AdapterFake()
    adapter.erros_pgdasd["2025-06"] = IntegraError("Serpro 500 BOOM")

    ingestor = IntegraIngestor(adapter)
    res = ingestor.sincronizar(
        cnpj=CNPJ, periodos=PERIODOS_12M, tipos=("pgdasd",)
    )

    assert res.total_novos == 11
    assert len(res.erros) == 1
    assert "2025-06" in res.erros[0]
    assert "Serpro 500" in res.erros[0]


def test_uploaded_by_user_id_propaga():
    ingestor = IntegraIngestor(AdapterFake())
    ingestor.sincronizar(
        cnpj=CNPJ,
        periodos=["2025-12"],
        tipos=("pgdasd",),
        uploaded_by_user_id=42,
    )
    rows = _listar_docs_integra()
    assert len(rows) == 1
    assert rows[0].uploaded_by_user_id == 42


def test_cnpj_com_pontuacao_normalizado():
    ingestor = IntegraIngestor(AdapterFake())
    res = ingestor.sincronizar(
        cnpj=CNPJ_PONTUADO, periodos=["2025-12"], tipos=("pgdasd",)
    )
    assert res.cnpj == CNPJ
    rows = _listar_docs_integra()
    assert rows[0].empresa_cnpj == CNPJ


def test_cnpj_invalido_levanta():
    ingestor = IntegraIngestor(AdapterFake())
    with pytest.raises(ValueError, match="cnpj inválido"):
        ingestor.sincronizar(cnpj="123", periodos=["2025-12"], tipos=("pgdasd",))


def test_tipos_invalidos_levanta():
    ingestor = IntegraIngestor(AdapterFake())
    with pytest.raises(ValueError, match="tipos inválidos"):
        ingestor.sincronizar(
            cnpj=CNPJ, periodos=["2025-12"], tipos=("dctfweb",)
        )


def test_to_dict_serializavel_com_hashes_prefix_16():
    import json

    ingestor = IntegraIngestor(AdapterFake())
    res = ingestor.sincronizar(
        cnpj=CNPJ, periodos=["2025-12"], tipos=("pgdasd",)
    )
    payload = res.to_dict()
    # Round-trip JSON
    json.dumps(payload)

    assert payload["cnpj"] == CNPJ
    assert payload["total_novos"] == 1
    assert len(payload["hashes_novos_prefix"]) == 1
    assert len(payload["hashes_novos_prefix"][0]) == 16


def test_retificadora_gera_sufixo_ret1():
    adapter = AdapterFake()
    adapter.retificadoras.add("2025-12")

    ingestor = IntegraIngestor(adapter)
    res = ingestor.sincronizar(
        cnpj=CNPJ, periodos=["2025-12"], tipos=("pgdasd",)
    )
    assert res.total_novos == 2

    rows = _listar_docs_integra()
    nomes = sorted(r.nome_original for r in rows)
    assert nomes == [
        "integra::pgdasd_2025-12.pdf",
        "integra::pgdasd_2025-12_ret1.pdf",
    ]


def test_result_dataclass_tipos_tupla():
    res = IntegraSyncResult(
        cnpj=CNPJ, periodos=["2025-12"], tipos=("pgdasd",)
    )
    assert isinstance(res.tipos, tuple)
    assert res.total_baixados == 0
    assert res.erros == []
