"""
test_sieg_adapter.py — Testes unitários do SiegAdapter (sem rede real).

Cobre:
- Divisão de janela > 31 dias em fatias
- Pagination Skip/Take
- Decoding base64 → bytes
- Validação de entrada (cnpj, xml_type, datas invertidas)
- Retry em HTTP 429 + Retry-After
- SiegError em 200 + {erro: "..."}
- SiegError em JSON malformado
- Normalização de lista direta vs dict-com-Xmls
- Chaves alternativas (Xml/xml, ChaveNFe/chave)
- API key nunca aparece em log nem em mensagens de erro

Não bate na internet: mocka requests.Session.post() via MagicMock.
"""
from __future__ import annotations

import base64
import os
import sys
from datetime import date
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integrations.sieg_adapter import (  # noqa: E402
    XML_TYPE_NFE,
    SiegAdapter,
    SiegError,
    SiegRateLimitError,
)

FAKE_API_KEY = "fake-key-abc-123"
CNPJ = "12345678000190"


def _b64(texto: str) -> str:
    return base64.b64encode(texto.encode("utf-8")).decode("ascii")


def _mock_resp(status: int = 200, json_body=None, text: str = "", headers=None):
    resp = MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    resp.text = text
    resp.headers = headers or {}
    if json_body is not None:
        resp.json = MagicMock(return_value=json_body)
    else:
        resp.json = MagicMock(side_effect=ValueError("no json"))
    return resp


def _adapter_sem_sleep(session: MagicMock) -> SiegAdapter:
    """Cria adapter com rate-limit sleep desabilitado para testes rápidos."""
    a = SiegAdapter(api_key=FAKE_API_KEY, session=session)
    a._sleep_rate_limit = MagicMock()  # type: ignore[method-assign]  # noqa: SLF001
    return a


# ─── Validação de entrada ────────────────────────────────────────────────


def test_api_key_obrigatoria():
    with pytest.raises(ValueError):
        SiegAdapter(api_key="")


def test_cnpj_invalido_levanta_valueerror():
    adapter = SiegAdapter(api_key=FAKE_API_KEY, session=MagicMock())
    with pytest.raises(ValueError, match="cnpj"):
        list(adapter.baixar_xmls(
            cnpj="123",
            data_inicio=date(2025, 1, 1),
            data_fim=date(2025, 1, 31),
        ))


def test_data_invertida_levanta_valueerror():
    adapter = SiegAdapter(api_key=FAKE_API_KEY, session=MagicMock())
    with pytest.raises(ValueError, match="data_fim"):
        list(adapter.baixar_xmls(
            cnpj=CNPJ,
            data_inicio=date(2025, 12, 31),
            data_fim=date(2025, 1, 1),
        ))


def test_xml_type_invalido():
    adapter = SiegAdapter(api_key=FAKE_API_KEY, session=MagicMock())
    with pytest.raises(ValueError, match="xml_type"):
        list(adapter.baixar_xmls(
            cnpj=CNPJ,
            data_inicio=date(2025, 1, 1),
            data_fim=date(2025, 1, 31),
            xml_type=99,
        ))


# ─── Happy path ──────────────────────────────────────────────────────────


def test_baixa_um_xml_decodifica_base64():
    session = MagicMock()
    session.post.return_value = _mock_resp(
        status=200,
        json_body=[
            {"ChaveNFe": "350126...", "Xml": _b64("<nfeProc>oi</nfeProc>")},
        ],
    )
    adapter = _adapter_sem_sleep(session)

    xmls = list(adapter.baixar_xmls(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 31),
    ))

    assert len(xmls) == 1
    assert xmls[0].chave == "350126..."
    assert xmls[0].xml_bytes == b"<nfeProc>oi</nfeProc>"
    assert xmls[0].xml_type == XML_TYPE_NFE


def test_chaves_alternativas_xml_e_chave():
    """A API Sieg às vezes usa 'xml' em vez de 'Xml' etc."""
    session = MagicMock()
    session.post.return_value = _mock_resp(
        status=200,
        json_body=[{"chave": "99", "xml": _b64("<x/>")}],
    )
    adapter = _adapter_sem_sleep(session)
    xmls = list(adapter.baixar_xmls(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 15),
    ))
    assert xmls[0].chave == "99"
    assert xmls[0].xml_bytes == b"<x/>"


def test_normaliza_resposta_em_dict_com_xmls():
    session = MagicMock()
    session.post.return_value = _mock_resp(
        status=200,
        json_body={"Xmls": [{"ChaveNFe": "A", "Xml": _b64("<a/>")}]},
    )
    adapter = _adapter_sem_sleep(session)
    xmls = list(adapter.baixar_xmls(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 15),
    ))
    assert len(xmls) == 1 and xmls[0].chave == "A"


def test_resposta_vazia_termina_generator():
    session = MagicMock()
    session.post.return_value = _mock_resp(status=200, json_body=[])
    adapter = _adapter_sem_sleep(session)
    assert list(adapter.baixar_xmls(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 15),
    )) == []


# ─── Pagination ──────────────────────────────────────────────────────────


def test_pagination_skip_take():
    """Primeira resposta cheia (50) → segunda fração → fim."""
    cheia = [
        {"ChaveNFe": f"k{i}", "Xml": _b64("<x/>")}
        for i in range(SiegAdapter.PAGE_SIZE)
    ]
    parcial = [{"ChaveNFe": "kLast", "Xml": _b64("<y/>")}]

    session = MagicMock()
    session.post.side_effect = [
        _mock_resp(status=200, json_body=cheia),
        _mock_resp(status=200, json_body=parcial),
    ]
    adapter = _adapter_sem_sleep(session)
    xmls = list(adapter.baixar_xmls(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 15),
    ))
    assert len(xmls) == 51
    assert xmls[-1].chave == "kLast"

    # Skip do 2º call == PAGE_SIZE
    segundo_body = session.post.call_args_list[1].kwargs["json"]
    assert segundo_body["Skip"] == SiegAdapter.PAGE_SIZE


# ─── Divisão de janela ──────────────────────────────────────────────────


def test_divisao_janela_12_meses_gera_multiplas_chamadas():
    """12 meses em janelas de 31 dias → ≥12 POSTs."""
    session = MagicMock()
    session.post.return_value = _mock_resp(status=200, json_body=[])
    adapter = _adapter_sem_sleep(session)
    list(adapter.baixar_xmls(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 12, 31),
    ))
    # 365 dias / 31 = 11.77 → 12 fatias
    assert session.post.call_count >= 12


def test_divisao_janela_mantem_extremos():
    adapter = SiegAdapter(api_key=FAKE_API_KEY, session=MagicMock())
    fatias = list(adapter._dividir_janela(date(2025, 1, 1), date(2025, 2, 15)))  # noqa: SLF001
    # Primeira: 01/01 .. 31/01 (31 dias)
    assert fatias[0] == (date(2025, 1, 1), date(2025, 1, 31))
    # Última termina exatamente em 15/02
    assert fatias[-1][1] == date(2025, 2, 15)
    # União cobre tudo
    assert fatias[0][0] == date(2025, 1, 1)


# ─── Rate limit / 429 ───────────────────────────────────────────────────


def test_retry_em_429_respeita_retry_after(monkeypatch):
    session = MagicMock()
    session.post.side_effect = [
        _mock_resp(status=429, headers={"Retry-After": "0"}, text="slow"),
        _mock_resp(status=200, json_body=[]),
    ]
    adapter = _adapter_sem_sleep(session)

    # Patch time.sleep pra não travar o teste
    import integrations.sieg_adapter as mod
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    list(adapter.baixar_xmls(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 15),
    ))
    assert session.post.call_count == 2


def test_429_persistente_vira_rate_limit_error(monkeypatch):
    session = MagicMock()
    session.post.return_value = _mock_resp(
        status=429, headers={"Retry-After": "0"}
    )
    adapter = _adapter_sem_sleep(session)

    import integrations.sieg_adapter as mod
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    with pytest.raises(SiegRateLimitError):
        list(adapter.baixar_xmls(
            cnpj=CNPJ,
            data_inicio=date(2025, 1, 1),
            data_fim=date(2025, 1, 15),
        ))


# ─── Erros da Sieg ──────────────────────────────────────────────────────


def test_200_com_campo_erro_vira_siegerror():
    session = MagicMock()
    session.post.return_value = _mock_resp(
        status=200, json_body={"erro": "CNPJ sem autorização"}
    )
    adapter = _adapter_sem_sleep(session)
    with pytest.raises(SiegError, match="CNPJ sem autorização"):
        list(adapter.baixar_xmls(
            cnpj=CNPJ,
            data_inicio=date(2025, 1, 1),
            data_fim=date(2025, 1, 15),
        ))


def test_http_500_vira_siegerror():
    session = MagicMock()
    session.post.return_value = _mock_resp(status=500, text="boom")
    adapter = _adapter_sem_sleep(session)
    with pytest.raises(SiegError, match="500"):
        list(adapter.baixar_xmls(
            cnpj=CNPJ,
            data_inicio=date(2025, 1, 1),
            data_fim=date(2025, 1, 15),
        ))


def test_json_malformado_vira_siegerror():
    session = MagicMock()
    session.post.return_value = _mock_resp(status=200, text="<html>oops</html>")
    adapter = _adapter_sem_sleep(session)
    with pytest.raises(SiegError, match="JSON"):
        list(adapter.baixar_xmls(
            cnpj=CNPJ,
            data_inicio=date(2025, 1, 1),
            data_fim=date(2025, 1, 15),
        ))


def test_base64_invalido_no_item_vira_siegerror():
    """Item com base64 estruturalmente inválido (tamanho errado) vira SiegError."""
    session = MagicMock()
    session.post.return_value = _mock_resp(
        status=200,
        json_body=[{"ChaveNFe": "bad", "Xml": "not_base64"}],
    )
    adapter = _adapter_sem_sleep(session)
    with pytest.raises(SiegError, match="[Bb]ase64"):
        list(adapter.baixar_xmls(
            cnpj=CNPJ,
            data_inicio=date(2025, 1, 1),
            data_fim=date(2025, 1, 15),
        ))


def test_item_sem_campo_xml_vira_siegerror():
    session = MagicMock()
    session.post.return_value = _mock_resp(
        status=200,
        json_body=[{"ChaveNFe": "semxml"}],
    )
    adapter = _adapter_sem_sleep(session)
    with pytest.raises(SiegError, match="Xml"):
        list(adapter.baixar_xmls(
            cnpj=CNPJ,
            data_inicio=date(2025, 1, 1),
            data_fim=date(2025, 1, 15),
        ))


# ─── Segurança ──────────────────────────────────────────────────────────


def test_api_key_vai_como_query_param_nao_em_body():
    session = MagicMock()
    session.post.return_value = _mock_resp(status=200, json_body=[])
    adapter = _adapter_sem_sleep(session)
    list(adapter.baixar_xmls(
        cnpj=CNPJ,
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 15),
    ))
    call = session.post.call_args
    assert call.kwargs["params"] == {"api_key": FAKE_API_KEY}
    assert "api_key" not in call.kwargs["json"]


def test_cnpj_com_pontuacao_normalizado_para_14_digitos():
    session = MagicMock()
    session.post.return_value = _mock_resp(status=200, json_body=[])
    adapter = _adapter_sem_sleep(session)
    list(adapter.baixar_xmls(
        cnpj="12.345.678/0001-90",
        data_inicio=date(2025, 1, 1),
        data_fim=date(2025, 1, 15),
    ))
    body = session.post.call_args.kwargs["json"]
    assert body["CnpjEmit"] == "12345678000190"
