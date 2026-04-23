# -*- coding: utf-8 -*-
"""
test_sieg_service.py — Testes unitários do SiegService (sem rede real).

Usa requests.Session mockada — zero chamada HTTP real.

Cobre:
- get_api_key: env var, arquivo, AWS ausente → SiegCredentialError
- SiegService.__init__: chave explícita vs ausente
- _baixar_xmls: xml_type inválido, CNPJ inválido, data invertida
- Divisão de janela > 31 dias em fatias
- Paginação Skip/Take: para quando resultado < PAGE_SIZE
- HTTP 429 + Retry-After → respeita e retry
- HTTP 429 persistente → SiegRateLimitError
- HTTP 200 + {"erro": "..."} → SiegError
- HTTP não-200 → SiegError
- JSON inválido → SiegError
- Normalização de payload dict com chave "Xmls"
- _decodificar: base64 válido, campo Xml ausente, base64 inválido, chave alternativa XmlBase64
- SincronizacaoResult.to_dict() serializável e hash truncado em 16 chars
- sincronizar: XML novo, duplicado, erro parcial não aborta os demais
"""
from __future__ import annotations

import base64
import json
import os
import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)

from integrations.sieg_service import (  # noqa: E402
    SiegCredentialError,
    SiegError,
    SiegRateLimitError,
    SiegService,
    SiegXml,
    SincronizacaoResult,
    XML_TYPE_NFE,
    get_api_key,
)

CNPJ = "12345678000190"
DATA_INI = date(2026, 1, 1)
DATA_FIM = date(2026, 1, 31)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _xml_fake(chave: str = "CHAVE123") -> bytes:
    return f"<nfeProc><chNFe>{chave}</chNFe></nfeProc>".encode("utf-8")


def _item_sieg(xml_bytes: bytes, chave: str = "CHAVE123") -> dict:
    return {
        "Xml": base64.b64encode(xml_bytes).decode("ascii"),
        "ChaveNFe": chave,
    }


def _resp_ok(json_data) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.ok = True
    resp.json.return_value = json_data
    resp.text = str(json_data)[:500]
    resp.headers = {}
    return resp


def _resp_err(status_code: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = False
    resp.text = f"erro {status_code}"
    resp.headers = {}
    return resp


# ─── get_api_key ─────────────────────────────────────────────────────────────


class TestGetApiKey:
    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("SIEG_API_KEY", "chave-env")
        monkeypatch.delenv("SIEG_API_KEY_FILE", raising=False)
        monkeypatch.delenv("SIEG_API_KEY_AWS_SECRET", raising=False)
        assert get_api_key() == "chave-env"

    def test_arquivo(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SIEG_API_KEY", raising=False)
        monkeypatch.delenv("SIEG_API_KEY_AWS_SECRET", raising=False)
        key_file = tmp_path / "sieg.key"
        key_file.write_text("chave-arquivo\n", encoding="utf-8")
        monkeypatch.setenv("SIEG_API_KEY_FILE", str(key_file))
        assert get_api_key() == "chave-arquivo"

    def test_arquivo_vazio_levanta_credential_error(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SIEG_API_KEY", raising=False)
        monkeypatch.delenv("SIEG_API_KEY_AWS_SECRET", raising=False)
        key_file = tmp_path / "sieg.key"
        key_file.write_text("   \n", encoding="utf-8")
        monkeypatch.setenv("SIEG_API_KEY_FILE", str(key_file))
        with pytest.raises(SiegCredentialError):
            get_api_key()

    def test_nenhuma_fonte_levanta_credential_error(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SIEG_API_KEY", raising=False)
        monkeypatch.delenv("SIEG_API_KEY_AWS_SECRET", raising=False)
        monkeypatch.setenv("SIEG_API_KEY_FILE", str(tmp_path / "nao_existe.key"))
        with pytest.raises(SiegCredentialError):
            get_api_key()


# ─── __init__ ────────────────────────────────────────────────────────────────


class TestSiegServiceInit:
    def test_chave_explicita(self):
        svc = SiegService(api_key="chave-ok")
        assert svc.api_key == "chave-ok"

    def test_sem_chave_levanta_credential_error(self, monkeypatch):
        monkeypatch.delenv("SIEG_API_KEY", raising=False)
        monkeypatch.delenv("SIEG_API_KEY_FILE", raising=False)
        monkeypatch.delenv("SIEG_API_KEY_AWS_SECRET", raising=False)
        with pytest.raises(SiegCredentialError):
            SiegService()


# ─── Validações de entrada ────────────────────────────────────────────────────


class TestValidacoes:
    @pytest.fixture
    def svc(self):
        return SiegService(api_key="fake")

    def test_xml_type_invalido(self, svc):
        with pytest.raises(ValueError, match="xml_type"):
            list(svc.baixar_xmls_raw(cnpj=CNPJ, data_inicio=DATA_INI, data_fim=DATA_FIM, xml_type=99))

    def test_cnpj_menos_de_14_digitos(self, svc):
        with pytest.raises(ValueError, match="CNPJ"):
            list(svc.baixar_xmls_raw(cnpj="123", data_inicio=DATA_INI, data_fim=DATA_FIM))

    def test_data_fim_anterior_a_inicio(self, svc):
        with pytest.raises(ValueError, match="data_fim"):
            list(svc.baixar_xmls_raw(cnpj=CNPJ, data_inicio=DATA_FIM, data_fim=DATA_INI))

    def test_cnpj_com_pontuacao_normalizado(self, svc):
        # Pontuação removida antes de chegar ao _baixar_xmls
        with patch.object(svc, "_paginar", return_value=iter([])):
            result = list(svc.baixar_xmls_raw(
                cnpj="12.345.678/0001-90",
                data_inicio=DATA_INI,
                data_fim=DATA_FIM,
            ))
        assert result == []


# ─── Divisão de janela ────────────────────────────────────────────────────────


class TestJanelaDias:
    def test_janela_maior_31_dias_gera_multiplas_fatias(self):
        svc = SiegService(api_key="fake")
        fatias: list[tuple[date, date]] = []

        def _spy(cnpj, dt_ini, dt_fim, xml_type):
            fatias.append((dt_ini, dt_fim))
            return iter([])

        with patch.object(svc, "_paginar", side_effect=_spy):
            list(svc.baixar_xmls_raw(
                cnpj=CNPJ,
                data_inicio=date(2026, 1, 1),
                data_fim=date(2026, 3, 1),  # 59 dias → 2 fatias
            ))

        assert len(fatias) == 2
        assert fatias[0] == (date(2026, 1, 1), date(2026, 1, 31))
        assert fatias[1][0] == date(2026, 2, 1)

    def test_janela_exatamente_31_dias_gera_1_fatia(self):
        svc = SiegService(api_key="fake")
        fatias: list = []

        def _spy(cnpj, dt_ini, dt_fim, xml_type):
            fatias.append((dt_ini, dt_fim))
            return iter([])

        with patch.object(svc, "_paginar", side_effect=_spy):
            list(svc.baixar_xmls_raw(
                cnpj=CNPJ,
                data_inicio=date(2026, 1, 1),
                data_fim=date(2026, 1, 31),
            ))

        assert len(fatias) == 1


# ─── Paginação ────────────────────────────────────────────────────────────────


class TestPaginacao:
    def test_para_quando_resultado_menor_que_page_size(self):
        svc = SiegService(api_key="fake")
        xml_b = _xml_fake()
        pagina1 = [_item_sieg(xml_b, f"CH{i:04d}") for i in range(50)]
        pagina2 = [_item_sieg(xml_b, "CH_LAST")]
        respostas = iter([_resp_ok(pagina1), _resp_ok(pagina2)])

        with patch.object(svc._session, "post", side_effect=lambda *a, **kw: next(respostas)), \
             patch("integrations.sieg_service.time.sleep"):
            resultado = list(svc._paginar(CNPJ, DATA_INI, DATA_FIM, XML_TYPE_NFE))

        assert len(resultado) == 51

    def test_pagina_vazia_para_imediatamente(self):
        svc = SiegService(api_key="fake")
        with patch.object(svc._session, "post", return_value=_resp_ok([])), \
             patch("integrations.sieg_service.time.sleep"):
            resultado = list(svc._paginar(CNPJ, DATA_INI, DATA_FIM, XML_TYPE_NFE))
        assert resultado == []


# ─── HTTP 429 ────────────────────────────────────────────────────────────────


class TestRateLimit:
    def test_429_retry_after_respeitado(self):
        svc = SiegService(api_key="fake")
        xml_b = _xml_fake()

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.ok = False
        resp_429.headers = {"Retry-After": "3"}

        respostas = iter([resp_429, _resp_ok([_item_sieg(xml_b)])])
        sleeps: list = []

        with patch.object(svc._session, "post", side_effect=lambda *a, **kw: next(respostas)), \
             patch("integrations.sieg_service.time.sleep", side_effect=sleeps.append):
            resultado = list(svc._paginar(CNPJ, DATA_INI, DATA_FIM, XML_TYPE_NFE))

        assert len(resultado) == 1
        assert 3 in sleeps

    def test_429_persistente_levanta_rate_limit_error(self):
        svc = SiegService(api_key="fake")
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.ok = False
        resp_429.headers = {}

        with patch.object(svc._session, "post", return_value=resp_429), \
             patch("integrations.sieg_service.time.sleep"):
            with pytest.raises(SiegRateLimitError):
                list(svc._paginar(CNPJ, DATA_INI, DATA_FIM, XML_TYPE_NFE))


# ─── Erros HTTP ──────────────────────────────────────────────────────────────


class TestErrosHttp:
    def test_http_500_levanta_sieg_error(self):
        svc = SiegService(api_key="fake")
        with patch.object(svc._session, "post", return_value=_resp_err(500)), \
             patch("integrations.sieg_service.time.sleep"):
            with pytest.raises(SiegError, match="500"):
                list(svc._paginar(CNPJ, DATA_INI, DATA_FIM, XML_TYPE_NFE))

    def test_200_com_campo_erro_levanta_sieg_error(self):
        svc = SiegService(api_key="fake")
        with patch.object(svc._session, "post", return_value=_resp_ok({"erro": "chave inválida"})), \
             patch("integrations.sieg_service.time.sleep"):
            with pytest.raises(SiegError, match="chave inválida"):
                list(svc._paginar(CNPJ, DATA_INI, DATA_FIM, XML_TYPE_NFE))

    def test_json_invalido_levanta_sieg_error(self):
        svc = SiegService(api_key="fake")
        resp = MagicMock()
        resp.status_code = 200
        resp.ok = True
        resp.json.side_effect = ValueError("not json")
        resp.text = "not json"
        resp.headers = {}
        with patch.object(svc._session, "post", return_value=resp), \
             patch("integrations.sieg_service.time.sleep"):
            with pytest.raises(SiegError, match="JSON"):
                list(svc._paginar(CNPJ, DATA_INI, DATA_FIM, XML_TYPE_NFE))

    def test_payload_dict_com_chave_xmls_normalizado(self):
        svc = SiegService(api_key="fake")
        xml_b = _xml_fake()
        payload = {"Xmls": [_item_sieg(xml_b)], "total": 1}
        with patch.object(svc._session, "post", return_value=_resp_ok(payload)), \
             patch("integrations.sieg_service.time.sleep"):
            resultado = list(svc._paginar(CNPJ, DATA_INI, DATA_FIM, XML_TYPE_NFE))
        assert len(resultado) == 1


# ─── _decodificar ────────────────────────────────────────────────────────────


class TestDecodificar:
    def test_xml_valido(self):
        xml_b = _xml_fake("KEY001")
        result = SiegService._decodificar(_item_sieg(xml_b, "KEY001"), XML_TYPE_NFE)
        assert result.xml_bytes == xml_b
        assert result.chave == "KEY001"
        assert result.xml_type == XML_TYPE_NFE

    def test_sem_campo_xml_levanta_sieg_error(self):
        with pytest.raises(SiegError, match="Xml"):
            SiegService._decodificar({"ChaveNFe": "X"}, XML_TYPE_NFE)

    def test_base64_invalido_levanta_sieg_error(self):
        # Caracteres não-ASCII forçam UnicodeEncodeError → ValueError → SiegError
        with pytest.raises(SiegError, match="Base64"):
            SiegService._decodificar({"Xml": "não-é-base64-válido", "ChaveNFe": "X"}, XML_TYPE_NFE)

    def test_campo_alternativo_xml_base64(self):
        xml_b = _xml_fake()
        item = {"XmlBase64": base64.b64encode(xml_b).decode(), "chave": "ALT"}
        result = SiegService._decodificar(item, XML_TYPE_NFE)
        assert result.xml_bytes == xml_b


# ─── SincronizacaoResult ─────────────────────────────────────────────────────


class TestSincronizacaoResult:
    def test_to_dict_serializavel(self):
        r = SincronizacaoResult(
            cnpj=CNPJ,
            data_inicio=DATA_INI,
            data_fim=DATA_FIM,
            xml_type=XML_TYPE_NFE,
            total_baixados=5,
            total_novos=3,
            total_duplicados=2,
            erros=["chave=X: SiegError: falha"],
            hashes_novos=["abc123def456789012345678901234567890123456789012345678901234abcd"],
        )
        d = r.to_dict()
        assert json.dumps(d)  # sem exceção
        assert d["total_novos"] == 3
        assert d["hashes_novos_prefix"][0] == "abc123def4567890"  # 16 chars

    def test_hash_truncado_em_16_chars(self):
        r = SincronizacaoResult(CNPJ, DATA_INI, DATA_FIM, XML_TYPE_NFE)
        r.hashes_novos = ["a" * 64]
        assert r.to_dict()["hashes_novos_prefix"] == ["a" * 16]


# ─── sincronizar ─────────────────────────────────────────────────────────────


class TestSincronizar:
    @pytest.fixture
    def svc(self):
        return SiegService(api_key="fake")

    def test_xml_novo_incrementa_total_novos(self, svc):
        item = SiegXml(chave="NOVO1", xml_bytes=_xml_fake("NOVO1"), xml_type=XML_TYPE_NFE)
        with patch.object(svc, "_baixar_xmls", return_value=iter([item])), \
             patch("integrations.sieg_service.SiegService._persistir_xml",
                   return_value=(True, "hash_novo_fake")):
            r = svc.sincronizar(cnpj=CNPJ, data_inicio=DATA_INI, data_fim=DATA_FIM)

        assert r.total_novos == 1
        assert r.total_duplicados == 0
        assert "hash_novo_fake" in r.hashes_novos

    def test_xml_duplicado_incrementa_total_duplicados(self, svc):
        item = SiegXml(chave="DUP1", xml_bytes=_xml_fake("DUP1"), xml_type=XML_TYPE_NFE)
        with patch.object(svc, "_baixar_xmls", return_value=iter([item])), \
             patch("integrations.sieg_service.SiegService._persistir_xml",
                   return_value=(False, "hash_dup_fake")):
            r = svc.sincronizar(cnpj=CNPJ, data_inicio=DATA_INI, data_fim=DATA_FIM)

        assert r.total_novos == 0
        assert r.total_duplicados == 1

    def test_erro_parcial_nao_aborta_sincronizacao(self, svc):
        item_ok = SiegXml(chave="OK", xml_bytes=_xml_fake("OK"), xml_type=XML_TYPE_NFE)
        item_err = SiegXml(chave="ERR", xml_bytes=_xml_fake("ERR"), xml_type=XML_TYPE_NFE)

        def persistir(*, item, cnpj, uploaded_by_user_id):
            if item.chave == "ERR":
                raise RuntimeError("falha simulada")
            return (True, "hash_ok")

        with patch.object(svc, "_baixar_xmls", return_value=iter([item_ok, item_err])), \
             patch("integrations.sieg_service.SiegService._persistir_xml", side_effect=persistir):
            r = svc.sincronizar(cnpj=CNPJ, data_inicio=DATA_INI, data_fim=DATA_FIM)

        assert r.total_baixados == 2
        assert r.total_novos == 1
        assert len(r.erros) == 1
        assert "falha simulada" in r.erros[0]

    def test_resultado_to_dict_apos_sincronizacao(self, svc):
        item = SiegXml(chave="K", xml_bytes=_xml_fake(), xml_type=XML_TYPE_NFE)
        with patch.object(svc, "_baixar_xmls", return_value=iter([item])), \
             patch("integrations.sieg_service.SiegService._persistir_xml",
                   return_value=(True, "h" * 64)):
            r = svc.sincronizar(cnpj=CNPJ, data_inicio=DATA_INI, data_fim=DATA_FIM)

        d = r.to_dict()
        assert json.dumps(d)
        assert d["cnpj"] == CNPJ
        assert d["data_inicio"] == "2026-01-01"
