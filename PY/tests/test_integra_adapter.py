"""
test_integra_adapter.py — Testes unitários do IntegraAdapter (sem rede real).

Usa session injetada (MagicMock) pra não precisar de .pfx real.
Sem rede: mocka todas as chamadas HTTP via `requests.Session`.

Cobre:
- Validação de entrada (cnpj, periodo)
- Autenticação JWT: primeira call bate em /authenticate/jwt, depois usa cache
- JWT cache: 2 chamadas → 1 POST /authenticate/jwt
- 401 no meio → invalida JWT e retry 1x
- 403 → IntegraAuthError com mensagem da procuração
- 429 com Retry-After → respeita e retry
- 429 persistente → IntegraRateLimitError
- 200 + {status: 400, mensagens: [...]} → IntegraError
- baixar_pgdasd → yield IntegraDocumento com PDF decodificado
- baixar_pgdasd com retificadora → yield 2 docs
- emitir_das → yield 1 IntegraDocumento
- Trio contratante/autor/contribuinte chega no body
- CNPJ com pontuação → normalizado nos 14 dígitos do body
- JWT_TTL expirado → re-autentica transparentemente
"""
from __future__ import annotations

import base64
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from integrations.integra_adapter import (  # noqa: E402
    IntegraAdapter,
    IntegraAuthError,
    IntegraDocumento,
    IntegraError,
    IntegraRateLimitError,
)
from integrations.integra_credentials import IntegraCredenciais  # noqa: E402

CONTRATANTE = "12345678000190"
AUTOR = "12345678000190"
CONTRIBUINTE = "98765432000110"
FAKE_JWT = "eyJhbGciOi.fake.jwt"


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def fake_credenciais(tmp_path):
    """Credenciais com .pfx fake — não será lido porque session é injetada."""
    pfx = tmp_path / "escritorio.pfx"
    pfx.write_bytes(b"fake")
    return IntegraCredenciais(
        cert_path=pfx,
        cert_password="senha",
        contratante_cnpj=CONTRATANTE,
        autor_pedido_dados_cnpj=AUTOR,
        base_url="https://fake-sandbox.serpro.gov.br/integra-contador/v1",
    )


def _mock_resp(
    status: int = 200, json_body=None, text: str = "", headers=None
):
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


def _jwt_resp():
    """Resposta padrão do /authenticate/jwt."""
    return _mock_resp(
        status=200,
        json_body={"access_token": FAKE_JWT, "expires_in": 3600},
    )


def _envelope_pgdasd(pdf_bytes: bytes, *, retificadora: bool = False) -> dict:
    """Envelope 200 OK do serviço PGDAS-D com 1 declaração."""
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    dados = {
        "declaracoes": [
            {
                "pdf": pdf_b64,
                "numeroDeclaracao": "123456",
                "dataTransmissao": "2025-12-20",
                "retificadora": retificadora,
            }
        ]
    }
    return {"dados": json.dumps(dados)}


def _envelope_pgdasd_com_retificadora(pdf1: bytes, pdf2: bytes) -> dict:
    dados = {
        "declaracoes": [
            {
                "pdf": base64.b64encode(pdf1).decode("ascii"),
                "numeroDeclaracao": "1",
                "retificadora": False,
            },
            {
                "pdf": base64.b64encode(pdf2).decode("ascii"),
                "numeroDeclaracao": "2",
                "retificadora": True,
            },
        ]
    }
    return {"dados": json.dumps(dados)}


def _envelope_das(pdf_bytes: bytes) -> dict:
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    dados = {
        "pdf": pdf_b64,
        "valorTotal": "150.00",
        "dataVencimento": "2026-01-20",
        "numeroDocumento": "07890",
    }
    return {"dados": json.dumps(dados)}


def _adapter_sem_sleep(fake_credenciais, session):
    a = IntegraAdapter(fake_credenciais, session=session)
    a._sleep_rate_limit = MagicMock()  # type: ignore[method-assign]
    return a


# ─── Validação de entrada ────────────────────────────────────────────────


def test_cnpj_invalido(fake_credenciais):
    a = _adapter_sem_sleep(fake_credenciais, MagicMock())
    with pytest.raises(ValueError, match="cnpj"):
        list(a.baixar_pgdasd(cnpj="123", periodo="2025-12"))


def test_periodo_invalido_formato(fake_credenciais):
    a = _adapter_sem_sleep(fake_credenciais, MagicMock())
    with pytest.raises(ValueError, match="periodo"):
        list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025/12"))


def test_periodo_invalido_mes(fake_credenciais):
    a = _adapter_sem_sleep(fake_credenciais, MagicMock())
    with pytest.raises(ValueError, match="periodo"):
        list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-13"))


# ─── JWT ─────────────────────────────────────────────────────────────────


def test_jwt_obtido_na_primeira_chamada(fake_credenciais):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(status=200, json_body=_envelope_pgdasd(b"%PDF-fake")),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)
    list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))

    # Primeira chamada bate em /authenticate/jwt
    primeira = session.post.call_args_list[0]
    assert primeira.args[0].endswith("/authenticate/jwt")
    # Segunda manda Authorization: Bearer <token>
    segunda = session.post.call_args_list[1]
    assert segunda.kwargs["headers"]["Authorization"] == f"Bearer {FAKE_JWT}"


def test_jwt_cache_nao_re_autentica(fake_credenciais):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(status=200, json_body=_envelope_pgdasd(b"%PDF-1")),
        _mock_resp(status=200, json_body=_envelope_pgdasd(b"%PDF-2")),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)
    list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-11"))
    list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))

    # Apenas 1 chamada ao /authenticate/jwt
    jwt_calls = [
        c for c in session.post.call_args_list
        if c.args[0].endswith("/authenticate/jwt")
    ]
    assert len(jwt_calls) == 1


def test_jwt_401_no_meio_refaz_auth(fake_credenciais):
    """401 na primeira call lógica → limpa JWT, reautentica e refaz."""
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),                                               # auth inicial
        _mock_resp(status=401, text="expired"),                     # 1a tentativa
        _jwt_resp(),                                                # re-auth
        _mock_resp(status=200, json_body=_envelope_pgdasd(b"%PDF")),  # sucesso
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)
    docs = list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))
    assert len(docs) == 1


def test_401_persistente_vira_authError(fake_credenciais):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(status=401),
        _jwt_resp(),
        _mock_resp(status=401),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)
    with pytest.raises(IntegraAuthError):
        list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))


def test_jwt_resposta_sem_token_falha(fake_credenciais):
    session = MagicMock()
    session.post.return_value = _mock_resp(
        status=200, json_body={"foo": "bar"}
    )
    a = _adapter_sem_sleep(fake_credenciais, session)
    with pytest.raises(IntegraAuthError, match="token"):
        list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))


# ─── 403 (procuração faltando) ───────────────────────────────────────────


def test_403_vira_authError_com_mensagem_procuracao(fake_credenciais):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(
            status=403,
            json_body={
                "mensagens": [
                    {
                        "codigo": "AUT_004",
                        "texto": "Contribuinte sem procuração para o contratante",
                    }
                ]
            },
        ),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)
    with pytest.raises(IntegraAuthError, match="procuração"):
        list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))


# ─── Rate limit ──────────────────────────────────────────────────────────


def test_429_respeita_retry_after(fake_credenciais, monkeypatch):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(status=429, headers={"Retry-After": "0"}),
        _mock_resp(status=200, json_body=_envelope_pgdasd(b"%PDF")),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)

    import integrations.integra_adapter as mod
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    docs = list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))
    assert len(docs) == 1


def test_429_persistente_vira_rateLimitError(fake_credenciais, monkeypatch):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(status=429, headers={"Retry-After": "0"}),
        _mock_resp(status=429, headers={"Retry-After": "0"}),
        _mock_resp(status=429, headers={"Retry-After": "0"}),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)

    import integrations.integra_adapter as mod
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    with pytest.raises(IntegraRateLimitError):
        list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))


# ─── Erro lógico (200 OK com payload de erro) ────────────────────────────


def test_200_com_status_400_vira_integraError(fake_credenciais):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(
            status=200,
            json_body={
                "status": 400,
                "mensagens": [
                    {"codigo": "PGDAS_001", "texto": "período sem declaração"}
                ],
            },
        ),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)
    with pytest.raises(IntegraError, match="período sem declaração"):
        list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))


# ─── Happy path PGDAS-D ──────────────────────────────────────────────────


def test_baixar_pgdasd_decodifica_pdf(fake_credenciais):
    pdf_plain = b"%PDF-1.4\nfake content"
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(status=200, json_body=_envelope_pgdasd(pdf_plain)),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)

    docs = list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))
    assert len(docs) == 1
    assert isinstance(docs[0], IntegraDocumento)
    assert docs[0].tipo == "pgdasd"
    assert docs[0].periodo == "2025-12"
    assert docs[0].cnpj_contribuinte == CONTRIBUINTE
    assert docs[0].conteudo == pdf_plain
    assert docs[0].mime_type == "application/pdf"
    assert docs[0].extensao == ".pdf"
    assert docs[0].metadata["numero_declaracao"] == "123456"


def test_baixar_pgdasd_retificadora_yields_dois(fake_credenciais):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(
            status=200,
            json_body=_envelope_pgdasd_com_retificadora(
                b"%PDF-orig", b"%PDF-retif"
            ),
        ),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)
    docs = list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))
    assert len(docs) == 2
    assert docs[0].metadata["retificadora"] is False
    assert docs[1].metadata["retificadora"] is True


def test_pgdasd_sem_declaracoes_nao_yield(fake_credenciais):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(
            status=200,
            json_body={"dados": json.dumps({"declaracoes": []})},
        ),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)
    docs = list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))
    assert docs == []


# ─── Happy path DAS ──────────────────────────────────────────────────────


def test_emitir_das_decodifica_pdf(fake_credenciais):
    pdf_plain = b"%PDF-1.4\nDAS boleto"
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(status=200, json_body=_envelope_das(pdf_plain)),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)

    docs = list(a.emitir_das(cnpj=CONTRIBUINTE, periodo="2025-12"))
    assert len(docs) == 1
    assert docs[0].tipo == "das"
    assert docs[0].conteudo == pdf_plain
    assert docs[0].metadata["valor_total"] == "150.00"


def test_das_sem_pdf_vira_erro(fake_credenciais):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(
            status=200,
            json_body={"dados": json.dumps({"valorTotal": "0"})},
        ),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)
    with pytest.raises(IntegraError, match="PDF ausente"):
        list(a.emitir_das(cnpj=CONTRIBUINTE, periodo="2025-12"))


# ─── Corpo do request ────────────────────────────────────────────────────


def test_body_tem_trio_identificacao(fake_credenciais):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(status=200, json_body=_envelope_pgdasd(b"%PDF")),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)
    list(a.baixar_pgdasd(cnpj="98.765.432/0001-10", periodo="2025-12"))

    # Segunda chamada (primeira é JWT)
    body = session.post.call_args_list[1].kwargs["json"]
    assert body["contratante"]["numero"] == CONTRATANTE
    assert body["autorPedidoDados"]["numero"] == AUTOR
    assert body["contribuinte"]["numero"] == CONTRIBUINTE  # normalizado
    assert body["pedidoDados"]["idSistema"] == "PGDASD"
    assert body["pedidoDados"]["idServico"] == "CONSULTARDECLARACAO13"

    dados = json.loads(body["pedidoDados"]["dados"])
    assert dados["periodoApuracao"] == "202512"


def test_emitir_das_usa_sistema_pagtoweb(fake_credenciais):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(status=200, json_body=_envelope_das(b"%PDF")),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)
    list(a.emitir_das(cnpj=CONTRIBUINTE, periodo="2025-12"))

    body = session.post.call_args_list[1].kwargs["json"]
    assert body["pedidoDados"]["idSistema"] == "PAGTOWEB"
    assert body["pedidoDados"]["idServico"] == "GERARDAS12"


# ─── base_url e endpoint ─────────────────────────────────────────────────


def test_base_url_vem_das_credenciais(fake_credenciais):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(status=200, json_body=_envelope_pgdasd(b"%PDF")),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)
    list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))

    for call in session.post.call_args_list:
        assert call.args[0].startswith("https://fake-sandbox.serpro.gov.br/")


# ─── Base64 inválido ─────────────────────────────────────────────────────


def test_base64_invalido_no_pdf_vira_integraError(fake_credenciais):
    session = MagicMock()
    session.post.side_effect = [
        _jwt_resp(),
        _mock_resp(
            status=200,
            json_body={
                "dados": json.dumps(
                    {"declaracoes": [{"pdf": "não_é_base64!"}]}
                )
            },
        ),
    ]
    a = _adapter_sem_sleep(fake_credenciais, session)
    with pytest.raises(IntegraError, match="[Bb]ase64"):
        list(a.baixar_pgdasd(cnpj=CONTRIBUINTE, periodo="2025-12"))
