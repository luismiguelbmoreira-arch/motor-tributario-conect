"""
test_fase1_parar_sangramento.py — Blindagem dos 5 bugs críticos da Fase 1.

1. /auth/refresh SEMPRE 200 com token válido, ou 401. NUNCA 304.
2. /integracoes/ecac/sync e /integracoes/sieg/sincronizar devolvem 401 sem JWT
   (auth aplicada no APIRouter inteiro — proteção herdada por todo endpoint).
3. /analise/pdf aceita tipo_comprador explícito e rejeita valor inválido com 422.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ─── /auth/refresh ─────────────────────────────────────────────────────────


def test_refresh_com_token_valido_retorna_200_nao_304(client_sem_auth):
    """Token novo (8h restantes) → 200 com renewed=false e mesmo token.
    Jamais 304 — isso quebra o contrato HTTP do frontend."""
    from auth import gerar_token_jwt

    token = gerar_token_jwt(user_id=1, username="admin", role="admin")

    resp = client_sem_auth.post(
        "/auth/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200, f"Esperado 200, veio {resp.status_code}: {resp.text}"
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["renewed"] is False
    assert data["access_token"] == token  # ainda válido, não renovou


def test_refresh_proximo_expiracao_retorna_200_com_token_novo(client_sem_auth):
    """Token com < 2h restantes → 200 com renewed=true e token novo."""
    from datetime import datetime, timedelta, timezone

    import jwt

    from auth import ALGORITHM, SECRET_KEY

    # Token que expira em 1h (dentro da janela de renovação de 2h)
    exp_curto = datetime.now(timezone.utc) + timedelta(hours=1)
    payload = {
        "sub": "1",
        "username": "admin",
        "role": "admin",
        "exp": exp_curto,
    }
    token_curto = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    resp = client_sem_auth.post(
        "/auth/refresh",
        headers={"Authorization": f"Bearer {token_curto}"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["renewed"] is True
    assert data["access_token"] != token_curto


def test_refresh_token_invalido_retorna_401(client_sem_auth):
    """Token inválido → 401 (nunca 304)."""
    resp = client_sem_auth.post(
        "/auth/refresh",
        headers={"Authorization": "Bearer token_falso_aqui"},
    )
    assert resp.status_code == 401


# ─── Router-level auth em /integracoes ─────────────────────────────────────


def test_integracoes_ecac_sem_jwt_retorna_401(client_sem_auth):
    """Router-level auth: endpoint e-CAC bloqueia requisição anônima."""
    resp = client_sem_auth.post(
        "/integracoes/ecac/sync",
        data={"cnpj": "12345678000190", "senha_cert": "x"},
    )
    # 401 (HTTPBearer) ou 403 (sem credencial detectada)
    assert resp.status_code in (401, 403), (
        f"e-CAC deveria rejeitar sem JWT, veio {resp.status_code}"
    )


def test_integracoes_sieg_sem_jwt_retorna_401(client_sem_auth):
    """Mesma regra para SIEG — auth é herdada do router."""
    resp = client_sem_auth.post(
        "/sieg/sincronizar",
        json={"cnpj": "12345678000190", "ano_base": 2026},
    )
    assert resp.status_code in (401, 403)


# ─── /analise/pdf tipo_comprador ───────────────────────────────────────────


def test_analise_pdf_tipo_comprador_invalido_retorna_422(client_autenticado):
    """tipo_comprador fora da whitelist → 422 com detalhe claro."""
    resp = client_autenticado.post(
        "/analise/pdf",
        files=[("files", ("fake.pdf", b"%PDF-1.4\n%fake\n", "application/pdf"))],
        data={"termo_aceite": "true", "tipo_comprador": "ALIENIGENA"},
    )
    assert resp.status_code == 422
    detalhe = resp.json().get("detail", "")
    assert "tipo_comprador" in str(detalhe).lower() or "ALIENIGENA" in str(detalhe)


def test_analise_pdf_tipo_comprador_valido_aceita(client_autenticado):
    """B2B_CONTRIBUINTE / B2C_CONSUMIDOR_FINAL / MISTO passam na validação do campo.

    Downstream pode rejeitar por outros motivos (documentos insuficientes,
    extrator offline). O que o teste garante: o erro NÃO é 'tipo_comprador inválido'.
    """
    for tipo in ("B2B_CONTRIBUINTE", "B2C_CONSUMIDOR_FINAL", "MISTO"):
        resp = client_autenticado.post(
            "/analise/pdf",
            files=[("files", ("fake.pdf", b"%PDF-1.4\nfake\n", "application/pdf"))],
            data={"termo_aceite": "true", "tipo_comprador": tipo},
        )
        # Se 422, não pode ser por causa do tipo_comprador.
        if resp.status_code == 422:
            detail = resp.json().get("detail", {})
            # Detail pode ser string (validação do campo) ou dict (regras de negócio)
            if isinstance(detail, str):
                assert "tipo_comprador inválido" not in detail.lower(), (
                    f"tipo={tipo} foi rejeitado no campo: {detail}"
                )
            elif isinstance(detail, dict):
                codigo = str(detail.get("codigo", "")).upper()
                # Códigos de negócio aceitáveis (documentos faltando, etc.)
                assert "TIPO_COMPRADOR" not in codigo, (
                    f"tipo={tipo} rejeitado por código {codigo}"
                )
