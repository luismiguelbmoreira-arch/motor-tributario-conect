# -*- coding: utf-8 -*-
"""
test_schema_registry.py — Gate de CI do versionamento de parsers.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from observability import schema_registry  # noqa: E402
from observability.schema_registry import (  # noqa: E402
    SCHEMA_REGISTRY,
    SchemaVersionMismatch,
    registrar_uso,
    validar_campos,
    versao,
)


def test_todos_parsers_obrigatorios_registrados():
    """Qualquer parser novo precisa entrar no registry antes de mergear."""
    esperados = {
        "xml_nfe",
        "xml_nfce",
        "csv_folha",
        "sped_ecd",
        "sped_efd_contrib",
    }
    assert esperados.issubset(SCHEMA_REGISTRY.keys())


def test_cada_entry_tem_version_campos_checksum():
    for nome, entry in SCHEMA_REGISTRY.items():
        assert "version" in entry, f"{nome} sem version"
        assert "campos_obrigatorios" in entry, f"{nome} sem campos"
        assert "checksum" in entry, f"{nome} sem checksum"
        assert len(entry["checksum"]) == 16, f"{nome} checksum tamanho errado"


def test_versao_retorna_string_formatada():
    assert versao("xml_nfe") == "xml_nfe@1.0.0"
    assert versao("sped_ecd") == "sped_ecd@1.0.0"


def test_versao_parser_desconhecido_levanta_keyerror():
    with pytest.raises(KeyError):
        versao("parser_inexistente")


def test_validar_campos_correto_nao_levanta():
    campos_nfe = list(SCHEMA_REGISTRY["xml_nfe"]["campos_obrigatorios"])
    # Não pode levantar
    validar_campos("xml_nfe", campos_nfe)


def test_validar_campos_modificado_levanta_mismatch():
    campos_modificados = list(SCHEMA_REGISTRY["xml_nfe"]["campos_obrigatorios"])
    campos_modificados.append("campo_novo_nao_registrado")

    with pytest.raises(SchemaVersionMismatch) as exc_info:
        validar_campos("xml_nfe", campos_modificados)

    assert "xml_nfe" in str(exc_info.value)
    assert "Bump a versao" in str(exc_info.value)


def test_registrar_uso_anota_parser_version_no_passo():
    passo = {"tipo": "EXTRACAO", "id": "PARSE_NFE"}
    registrar_uso("xml_nfe", passo)

    assert passo["parser_version"] == "xml_nfe@1.0.0"


def test_checksum_estavel_para_mesmo_conjunto():
    """Mudar ordem dos campos não deve mudar o checksum."""
    from observability.schema_registry import _checksum

    c1 = _checksum(["a", "b", "c"])
    c2 = _checksum(["c", "a", "b"])
    assert c1 == c2
