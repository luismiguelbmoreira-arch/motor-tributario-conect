"""
schema_registry.py — Catálogo versionado dos parsers.

Cada parser (xml_nfe, xml_nfce, csv_folha, sped_ecd, sped_efd_contrib)
declara sua versão e os campos obrigatórios que extrai. O checksum é
calculado sobre a lista de campos ordenada — se alguém editar o parser
sem bump de versão, o teste de CI `test_schema_registry` falha.

USO EM RUNTIME:
    from observability.schema_registry import registrar_uso
    passo = registrar_uso("xml_nfe", passo)
    # passo ganha campo 'parser_version' = "xml_nfe@1.0.0"

USO EM CI (gate):
    def test_todos_parsers_registrados():
        for nome in ("xml_nfe", "csv_folha", "sped_ecd", ...):
            assert nome in SCHEMA_REGISTRY
"""
from __future__ import annotations

import hashlib
from typing import Any, Final


class SchemaVersionMismatch(Exception):
    """Parser foi modificado sem bump de versão."""


def _checksum(campos: list[str]) -> str:
    """SHA-256 hex da lista de campos ordenada. 16 chars suficiente."""
    canonico = "|".join(sorted(campos)).encode("utf-8")
    return hashlib.sha256(canonico).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRY — editar aqui ao adicionar ou modificar parser
# ─────────────────────────────────────────────────────────────────────────────

_XML_NFE_CAMPOS: Final[list[str]] = [
    "emit/CNPJ",
    "ide/dhEmi",
    "ide/mod",
    "total/ICMSTot/vNF",
    "total/ICMSTot/vICMSST",
    "dest/indIEDest",
]

_XML_NFCE_CAMPOS: Final[list[str]] = [
    "emit/CNPJ",
    "ide/dhEmi",
    "ide/mod",
    "total/ICMSTot/vNF",
]

_CSV_FOLHA_CAMPOS: Final[list[str]] = [
    "competencia",
    "total_bruto",
    "encargos_patronais",
]

_SPED_ECD_CAMPOS: Final[list[str]] = [
    "0000/CNPJ",
    "0000/DT_INI",
    "0000/DT_FIN",
    "I050/COD_CTA",
    "I200/VL_LCTO",
    "I250/COD_CTA",
    "I250/VL_PARTIDA",
    "I250/IND_DC",
]

_SPED_EFD_CONTRIB_CAMPOS: Final[list[str]] = [
    "0000/CNPJ",
    "0000/DT_INI",
    "0000/DT_FIN",
    "0110/IND_APRO_CRED",
    "M200/VL_TOT_CONT_NC_PER",
    "M200/VL_TOT_CRED_DESC",
    "M600/VL_TOT_CONT_NC_PER",
    "M600/VL_TOT_CRED_DESC",
]


SCHEMA_REGISTRY: Final[dict[str, dict[str, Any]]] = {
    "xml_nfe": {
        "version": "1.0.0",
        "campos_obrigatorios": _XML_NFE_CAMPOS,
        "checksum": _checksum(_XML_NFE_CAMPOS),
    },
    "xml_nfce": {
        "version": "1.0.0",
        "campos_obrigatorios": _XML_NFCE_CAMPOS,
        "checksum": _checksum(_XML_NFCE_CAMPOS),
    },
    "csv_folha": {
        "version": "1.0.0",
        "campos_obrigatorios": _CSV_FOLHA_CAMPOS,
        "checksum": _checksum(_CSV_FOLHA_CAMPOS),
    },
    "sped_ecd": {
        "version": "1.0.0",
        "campos_obrigatorios": _SPED_ECD_CAMPOS,
        "checksum": _checksum(_SPED_ECD_CAMPOS),
    },
    "sped_efd_contrib": {
        "version": "1.0.0",
        "campos_obrigatorios": _SPED_EFD_CONTRIB_CAMPOS,
        "checksum": _checksum(_SPED_EFD_CONTRIB_CAMPOS),
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# API PÚBLICA
# ─────────────────────────────────────────────────────────────────────────────

def versao(nome_parser: str) -> str:
    """Retorna 'nome@X.Y.Z' para anotar na trilha."""
    entry = SCHEMA_REGISTRY.get(nome_parser)
    if entry is None:
        raise KeyError(f"Parser '{nome_parser}' nao registrado em SCHEMA_REGISTRY.")
    return f"{nome_parser}@{entry['version']}"


def validar_campos(nome_parser: str, campos_lidos: list[str]) -> None:
    """
    Verifica que o parser leu exatamente os campos que o registry declara.
    Raise SchemaVersionMismatch se diferente (parser modificado sem bump).
    """
    entry = SCHEMA_REGISTRY.get(nome_parser)
    if entry is None:
        raise KeyError(f"Parser '{nome_parser}' nao registrado.")

    checksum_lido = _checksum(campos_lidos)
    if checksum_lido != entry["checksum"]:
        raise SchemaVersionMismatch(
            f"Parser '{nome_parser}' leu campos com checksum {checksum_lido} "
            f"mas registry esperava {entry['checksum']} (versao {entry['version']}). "
            f"Bump a versao no schema_registry.py ou reverta o parser."
        )


def registrar_uso(nome_parser: str, passo: dict[str, Any]) -> dict[str, Any]:
    """
    Anota parser_version no passo da trilha (mutação in-place).
    Retorna o próprio passo para encadeamento.
    """
    passo["parser_version"] = versao(nome_parser)
    return passo
