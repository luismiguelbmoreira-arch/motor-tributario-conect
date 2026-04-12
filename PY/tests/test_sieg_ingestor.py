"""
test_sieg_ingestor.py — Testes do SiegIngestor (adapter fake + DB in-memory).

Cobre:
- XML novo vira linha em auditoria_documentos com nome_original "sieg::{chave}.xml"
- Idempotência: mesmo XML duas vezes → 1 novo + 1 duplicado
- Erro parcial em um XML não aborta os outros
- SincronizacaoResult contém contadores corretos
- to_dict() do resultado é serializável
- XML cifrado no storage (existe em disco)
- ValueError do adapter propaga; SiegError propaga
- uploaded_by_user_id chega no registro
"""
from __future__ import annotations

import base64
import os
import sys
from datetime import date
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Master key antes de importar storage_cifrado
os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)

import database  # noqa: E402
import services.storage_cifrado as storage_cifrado  # noqa: E402
from integrations.sieg_adapter import (  # noqa: E402
    XML_TYPE_NFE,
    SiegAdapter,
    SiegError,
    SiegXml,
)
from integrations.sieg_ingestor import (  # noqa: E402
    NOME_ORIGINAL_PREFIX,
    SiegIngestor,
)
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import SQLModel, create_engine  # noqa: E402

CNPJ = "12345678000190"
XML_A = b"<nfeProc>AAA</nfeProc>"
XML_B = b"<nfeProc>BBB</nfeProc>"
XML_C = b"<nfeProc>CCC</nfeProc>"


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def db_em_memoria(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    yield engine


@pytest.fixture
def storage_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_cifrado, "STORAGE_ROOT", tmp_path / "auditoria")
    yield tmp_path / "auditoria"


class AdapterFake:
    """SiegAdapter stub com API compatível — retorna lista fixa de SiegXml."""

    def __init__(self, xmls: list[SiegXml]) -> None:
        self._xmls = xmls
        self.chamadas = 0

    def baixar_xmls(self, *, cnpj, data_inicio, data_fim, xml_type=XML_TYPE_NFE):
        self.chamadas += 1
        yield from self._xmls


def _fazer_xmls(*pares: tuple[str, bytes]) -> list[SiegXml]:
    return [
        SiegXml(chave=chave, xml_bytes=bytes_, xml_type=XML_TYPE_NFE)
        for chave, bytes_ in pares
    ]


# ─── Happy path ──────────────────────────────────────────────────────────


def test_sincronizar_3_xmls_novos(db_em_memoria, storage_isolado):
    adapter = AdapterFake(_fazer_xmls(
        ("chaveA", XML_A),
        ("chaveB", XML_B),
        ("chaveC", XML_C),
    ))
    ingestor = SiegIngestor(adapter)  # type: ignore[arg-type]

    res = ingestor.sincronizar(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 31),
    )

    assert res.total_baixados == 3
    assert res.total_novos == 3
    assert res.total_duplicados == 0
    assert res.erros == []
    assert len(res.hashes_novos) == 3


def test_nome_original_usa_prefixo_sieg(db_em_memoria, storage_isolado):
    adapter = AdapterFake(_fazer_xmls(("chaveXYZ", XML_A)))
    ingestor = SiegIngestor(adapter)  # type: ignore[arg-type]
    res = ingestor.sincronizar(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 31),
    )
    hash_hex = res.hashes_novos[0]
    doc = database.buscar_documento_por_hash(hash_hex)
    assert doc is not None
    assert doc.nome_original == f"{NOME_ORIGINAL_PREFIX}chaveXYZ.xml"
    assert doc.mime_type == "application/xml"
    assert doc.empresa_cnpj == CNPJ


def test_xml_fica_cifrado_no_storage(db_em_memoria, storage_isolado):
    adapter = AdapterFake(_fazer_xmls(("k1", XML_A)))
    ingestor = SiegIngestor(adapter)  # type: ignore[arg-type]
    res = ingestor.sincronizar(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 31),
    )
    hash_hex = res.hashes_novos[0]
    assert storage_cifrado.existe(CNPJ, hash_hex)
    # Round-trip: decifrar bate com o plaintext original
    path = storage_cifrado._path_para(CNPJ, hash_hex)
    plain = storage_cifrado.decifrar(path, CNPJ, hash_hex)
    assert plain == XML_A


def test_uploaded_by_user_id_propaga(db_em_memoria, storage_isolado):
    adapter = AdapterFake(_fazer_xmls(("k1", XML_A)))
    ingestor = SiegIngestor(adapter)  # type: ignore[arg-type]
    res = ingestor.sincronizar(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 31),
        uploaded_by_user_id=42,
    )
    doc = database.buscar_documento_por_hash(res.hashes_novos[0])
    assert doc.uploaded_by_user_id == 42


# ─── Idempotência ────────────────────────────────────────────────────────


def test_idempotencia_mesmo_xml_2x(db_em_memoria, storage_isolado):
    """Rodar duas vezes a mesma janela: segunda não cria novos."""
    adapter = AdapterFake(_fazer_xmls(("k1", XML_A), ("k2", XML_B)))
    ingestor = SiegIngestor(adapter)  # type: ignore[arg-type]

    res1 = ingestor.sincronizar(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 31),
    )
    assert res1.total_novos == 2

    # Recria o gerador (AdapterFake reutiliza a lista)
    adapter2 = AdapterFake(_fazer_xmls(("k1", XML_A), ("k2", XML_B)))
    ingestor2 = SiegIngestor(adapter2)  # type: ignore[arg-type]
    res2 = ingestor2.sincronizar(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 31),
    )
    assert res2.total_baixados == 2
    assert res2.total_novos == 0
    assert res2.total_duplicados == 2


def test_xml_repetido_na_mesma_chamada(db_em_memoria, storage_isolado):
    """Dois itens com o mesmo plaintext → 1 novo + 1 duplicado no mesmo run."""
    adapter = AdapterFake(_fazer_xmls(("k1", XML_A), ("k2", XML_A)))
    ingestor = SiegIngestor(adapter)  # type: ignore[arg-type]
    res = ingestor.sincronizar(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 31),
    )
    assert res.total_baixados == 2
    assert res.total_novos == 1
    assert res.total_duplicados == 1


# ─── Erros parciais ──────────────────────────────────────────────────────


def test_erro_parcial_nao_aborta_restante(db_em_memoria, storage_isolado, monkeypatch):
    """Falha na cifragem de um XML não deve impedir os outros."""
    adapter = AdapterFake(_fazer_xmls(
        ("ok1", XML_A),
        ("bad", XML_B),
        ("ok2", XML_C),
    ))
    ingestor = SiegIngestor(adapter)  # type: ignore[arg-type]

    original = storage_cifrado.cifrar_e_persistir

    def cifrar_que_explode(plaintext, cnpj):
        if plaintext == XML_B:
            raise RuntimeError("disco cheio fingido")
        return original(plaintext, cnpj)

    monkeypatch.setattr(storage_cifrado, "cifrar_e_persistir", cifrar_que_explode)

    res = ingestor.sincronizar(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 31),
    )
    assert res.total_baixados == 3
    assert res.total_novos == 2
    assert len(res.erros) == 1
    assert "bad" in res.erros[0]


def test_siegerror_no_inicio_propaga(db_em_memoria, storage_isolado):
    class AdapterExplode:
        def baixar_xmls(self, **kwargs):
            raise SiegError("API key inválida")

    ingestor = SiegIngestor(AdapterExplode())  # type: ignore[arg-type]
    with pytest.raises(SiegError, match="inválida"):
        ingestor.sincronizar(
            cnpj=CNPJ,
            data_inicio=date(2025, 1, 1),
            data_fim=date(2025, 1, 31),
        )


# ─── Serialização ────────────────────────────────────────────────────────


def test_resultado_to_dict_serializavel(db_em_memoria, storage_isolado):
    import json

    adapter = AdapterFake(_fazer_xmls(("k1", XML_A)))
    ingestor = SiegIngestor(adapter)  # type: ignore[arg-type]
    res = ingestor.sincronizar(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 31),
    )
    d = res.to_dict()
    # json.dumps não pode falhar
    texto = json.dumps(d)
    assert "k1" not in texto  # chave não aparece; apenas hashes prefixados
    assert d["total_novos"] == 1
    assert d["cnpj"] == CNPJ
    assert d["data_inicio"] == "2025-01-01"
    assert len(d["hashes_novos_prefix"][0]) == 16  # primeiros 16 chars


# ─── Normalização de CNPJ ────────────────────────────────────────────────


def test_cnpj_com_pontuacao_normalizado(db_em_memoria, storage_isolado):
    adapter = AdapterFake(_fazer_xmls(("k1", XML_A)))
    ingestor = SiegIngestor(adapter)  # type: ignore[arg-type]
    res = ingestor.sincronizar(
        cnpj="12.345.678/0001-90",
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 31),
    )
    assert res.cnpj == "12345678000190"
    doc = database.buscar_documento_por_hash(res.hashes_novos[0])
    assert doc.empresa_cnpj == "12345678000190"
