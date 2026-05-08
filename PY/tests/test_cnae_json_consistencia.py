# -*- coding: utf-8 -*-
"""
tests/test_cnae_json_consistencia.py — WS12 etapa final (ERR-005 fechado)

Anti-drift entre `data/cnae_completo.json` (artefato gerado) e a fonte
canônica de regras `core.regras_cnae.obter_regra()` + `core.cnae_excecoes`.

Se o JSON sair de sincronia com a fonte canônica (alguém editar manual,
ou regenerar com schema diferente), este teste vermelha — antes do bug
fiscal aparecer em produção.

POLÍTICA: o JSON é REGENERADO via `python PY/scripts/gerar_mapa_cnae.py`.
Edição manual é proibida — quebra o anti-drift.

Rode com: pytest PY/tests/test_cnae_json_consistencia.py -v
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.regras_cnae import obter_regra  # noqa: E402

JSON_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "cnae_completo.json"
)


@pytest.fixture(scope="module")
def json_data() -> dict:
    """Carrega o JSON gerado uma vez por módulo."""
    if not JSON_PATH.exists():
        pytest.skip(f"JSON não gerado: {JSON_PATH}. Rode gerar_mapa_cnae.py.")
    with open(JSON_PATH, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA + METADADOS
# ─────────────────────────────────────────────────────────────────────────────

class TestCnaeJsonSchema:
    """Schema do JSON gerado pelo gerador WS12."""

    def test_top_level_tem_metadata_e_cnaes(self, json_data):
        assert "_metadata" in json_data
        assert "cnaes" in json_data

    def test_metadata_tem_versao_2_0(self, json_data):
        assert json_data["_metadata"]["schema_versao"] == "2.0"

    def test_metadata_tem_data_geracao(self, json_data):
        assert "data_geracao" in json_data["_metadata"]

    def test_metadata_aponta_consumidor_canonico(self, json_data):
        assert (
            json_data["_metadata"]["consumidor_canonico"]
            == "core.regras_cnae.obter_regra"
        )

    def test_metadata_tem_sha256_da_fonte_ibge(self, json_data):
        sha = json_data["_metadata"]["fonte_ibge_sha256"]
        assert isinstance(sha, str)
        assert len(sha) == 64  # SHA-256 hex


# ─────────────────────────────────────────────────────────────────────────────
# CONSISTÊNCIA JSON × obter_regra (ANTI-DRIFT)
# ─────────────────────────────────────────────────────────────────────────────

class TestCnaeJsonConsistencia:
    """
    Cada CNAE no JSON deve bater 1:1 com o que obter_regra() devolve.
    Se quebrar, é sinal de drift — JSON foi editado à mão ou gerador
    está com lógica diferente da fonte canônica.
    """

    def test_total_de_cnaes_e_positivo(self, json_data):
        assert len(json_data["cnaes"]) > 1000  # IBGE tem ~1332

    def test_todo_cnae_no_json_bate_com_obter_regra(self, json_data):
        """
        Para cada CNAE listado no JSON, ou:
          - obter_regra() retorna a MESMA categoria/anexo/depende_fator_r, OU
          - JSON marca categoria=None + base_legal=FALLBACK_NAO_MAPEADO
            (e obter_regra() retorna None)
        """
        divergencias = []
        for cnae, entrada_json in json_data["cnaes"].items():
            regra = obter_regra(cnae)

            if regra is None:
                if entrada_json["categoria"] is not None:
                    divergencias.append(
                        f"{cnae}: JSON tem categoria={entrada_json['categoria']}, "
                        f"obter_regra() retornou None"
                    )
                continue

            # obter_regra() devolve regra; JSON precisa bater
            if entrada_json["categoria"] != regra.categoria:
                divergencias.append(
                    f"{cnae}: JSON categoria={entrada_json['categoria']} "
                    f"≠ obter_regra().categoria={regra.categoria}"
                )
                continue

            if entrada_json["anexo_padrao"] != regra.anexo_padrao:
                divergencias.append(
                    f"{cnae}: JSON anexo_padrao={entrada_json['anexo_padrao']} "
                    f"≠ obter_regra().anexo_padrao={regra.anexo_padrao}"
                )
                continue

            if entrada_json["depende_fator_r"] != regra.depende_fator_r:
                divergencias.append(
                    f"{cnae}: JSON depende_fator_r={entrada_json['depende_fator_r']} "
                    f"≠ obter_regra().depende_fator_r={regra.depende_fator_r}"
                )

        assert not divergencias, (
            f"{len(divergencias)} CNAEs divergem entre JSON e obter_regra(). "
            f"JSON foi editado à mão ou gerador está dessincronizado. "
            f"Rode `python PY/scripts/gerar_mapa_cnae.py` pra regenerar. "
            f"Primeiras 5 divergências: {divergencias[:5]}"
        )

    def test_categorias_validas(self, json_data):
        """Categoria deve ser uma das 5 do schema WS12, ou None (fallback)."""
        validas = {
            "A_FIXO", "B_ANEXO_III", "C_FATOR_R",
            "D_ESPECIAL", "E_VEDADO", None,
        }
        for cnae, entrada in json_data["cnaes"].items():
            assert entrada["categoria"] in validas, (
                f"{cnae}: categoria inválida {entrada['categoria']!r}"
            )

    def test_anexos_validos(self, json_data):
        """anexo_padrao deve ser I-V ou None (E_VEDADO/C_FATOR_R/fallback)."""
        validos = {"I", "II", "III", "IV", "V", None}
        for cnae, entrada in json_data["cnaes"].items():
            assert entrada["anexo_padrao"] in validos, (
                f"{cnae}: anexo_padrao inválido {entrada['anexo_padrao']!r}"
            )

    def test_cnae_4757100_canavezi_anexo_i(self, json_data):
        """Caso CANAVEZI (ERR-005 original): comércio varejista — Anexo I."""
        e = json_data["cnaes"].get("4757100")
        assert e is not None
        assert e["categoria"] == "A_FIXO"
        assert e["anexo_padrao"] == "I"

    def test_cnae_6911701_advocacia_anexo_iv(self, json_data):
        """Advocacia: D_ESPECIAL → Anexo IV."""
        e = json_data["cnaes"].get("6911701")
        assert e is not None
        assert e["categoria"] == "D_ESPECIAL"
        assert e["anexo_padrao"] == "IV"

    def test_cnae_5611201_restaurante_c_fator_r(self, json_data):
        """Restaurante: C_FATOR_R (depende do Fator R)."""
        e = json_data["cnaes"].get("5611201")
        assert e is not None
        assert e["categoria"] == "C_FATOR_R"
        assert e["depende_fator_r"] is True
        assert e["anexo_padrao"] is None  # depende de Fator R

    def test_cnae_6422100_caixa_e_vedado(self, json_data):
        """Caixa Econômica Federal: E_VEDADO."""
        e = json_data["cnaes"].get("6422100")
        assert e is not None
        assert e["categoria"] == "E_VEDADO"
