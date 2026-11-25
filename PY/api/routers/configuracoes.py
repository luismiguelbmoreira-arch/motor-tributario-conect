"""
configuracoes.py — Router /settings (Fase 5).

Preferências por usuário persistidas em `users.tema` e `users.notificacoes_email`
(Opção A do plano — colunas em UserDB).

SEGURANÇA:
  - Autenticação obrigatória via dependency do router.
  - Endpoint sempre atua no `current_user` (sem user_id no path — evita IDOR trivial).
  - Pydantic V2 `extra="forbid"` em todos os requests (rejeita campo desconhecido).
  - `response_model` explícito (MAX auditoria).

LGPD:
  - `tema` e `notificacoes_email` são preferências operacionais, não fiscais.
  - Não há auditoria histórica nesta fase (fora do escopo).
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from api.dependencies import extrair_user_id, get_current_user
from auth import UserDB, _auth_engine
from services import chave_anthropic

logger = logging.getLogger("motor_conect.api")


router = APIRouter(
    tags=["Configurações"],
    dependencies=[Depends(get_current_user)],
)


TemaLiteral = Literal["claro", "escuro", "auto"]


class SettingsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tema: TemaLiteral
    notificacoes_email: bool


class TemaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tema: TemaLiteral = Field(..., description="claro | escuro | auto")


class NotificacoesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    notificacoes_email: bool


def _carregar_user(user_id: int) -> UserDB:
    """
    Carrega UserDB pelo id. Usa o engine do auth.py diretamente porque
    UserDB é tabela de autenticação, não fiscal, e o módulo `auth` é
    a fonte de verdade.
    """
    with Session(_auth_engine) as session:
        user = session.get(UserDB, user_id)
        if user is None:
            # Token válido mas user sumiu do DB (delete direto, inconsistência
            # de teste etc) — trata como 404. NUNCA expor detalhe interno.
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        return user


def _resolver_user_id(current_user: dict) -> int:
    """Extrai user_id OU levanta 401 (token sem claim utilizável)."""
    user_id = extrair_user_id(current_user)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Token inválido.")
    return user_id


@router.get(
    "/settings",
    response_model=SettingsResponse,
    summary="Retorna preferências do usuário autenticado",
)
def obter_settings(current_user: dict = Depends(get_current_user)) -> SettingsResponse:
    """
    Devolve `tema` e `notificacoes_email` do próprio usuário.

    Defaults na migração: `tema='auto'`, `notificacoes_email=True`.
    User novo (nunca alterou) sempre verá esses valores.
    """
    user_id = _resolver_user_id(current_user)
    user = _carregar_user(user_id)
    # Defensivo — valores legados podem ter tema fora do Literal. Fallback 'auto'.
    tema = user.tema if user.tema in ("claro", "escuro", "auto") else "auto"
    return SettingsResponse(tema=tema, notificacoes_email=bool(user.notificacoes_email))


@router.post(
    "/settings/tema",
    response_model=SettingsResponse,
    summary="Altera tema visual do usuário",
)
def atualizar_tema(
    req: TemaRequest,
    current_user: dict = Depends(get_current_user),
) -> SettingsResponse:
    """Persiste `tema` no `UserDB` do usuário autenticado."""
    user_id = _resolver_user_id(current_user)
    with Session(_auth_engine) as session:
        user = session.get(UserDB, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        user.tema = req.tema
        session.add(user)
        session.commit()
        session.refresh(user)
        return SettingsResponse(
            tema=user.tema,  # type: ignore[arg-type]  # Literal garante validação prévia
            notificacoes_email=bool(user.notificacoes_email),
        )


@router.post(
    "/settings/notificacoes",
    response_model=SettingsResponse,
    summary="Altera preferência de notificações por email",
)
def atualizar_notificacoes(
    req: NotificacoesRequest,
    current_user: dict = Depends(get_current_user),
) -> SettingsResponse:
    """
    Persiste `notificacoes_email` no `UserDB`.

    Escopo Fase 5: só persiste a flag. Disparo real de email NÃO é
    implementado aqui (fora do escopo — ver plano).
    """
    user_id = _resolver_user_id(current_user)
    with Session(_auth_engine) as session:
        user = session.get(UserDB, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        user.notificacoes_email = bool(req.notificacoes_email)
        session.add(user)
        session.commit()
        session.refresh(user)
        tema = user.tema if user.tema in ("claro", "escuro", "auto") else "auto"
        return SettingsResponse(
            tema=tema,
            notificacoes_email=bool(user.notificacoes_email),
        )


# ── Chave da Anthropic (só no app desktop) ────────────────────────────────
# A chave fica no Gerenciador de Credenciais do Windows do usuário do Windows
# (keyring). Nunca volta na resposta, nunca vai para log: só os 4 últimos.
# Fora do modo desktop PUT/DELETE respondem 404 (servidor usa variável de ambiente).


class ChaveAnthropicStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configurada: bool
    origem: Literal["cofre_windows", "ambiente"] | None
    final: str | None
    editavel: bool


class ChaveAnthropicRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Sem restrições aqui de propósito: o 422 do Pydantic ecoaria a chave.
    # Formato validado no handler com mensagem genérica.
    chave: str


def _exigir_modo_desktop() -> None:
    if not chave_anthropic.modo_desktop():
        raise HTTPException(status_code=404, detail="Not Found")


@router.get(
    "/settings/anthropic-key",
    response_model=ChaveAnthropicStatus,
    summary="Status da chave da Anthropic (nunca devolve a chave)",
)
def status_chave_anthropic() -> ChaveAnthropicStatus:
    return ChaveAnthropicStatus(**chave_anthropic.status_chave())


@router.put(
    "/settings/anthropic-key",
    response_model=ChaveAnthropicStatus,
    summary="Salva a chave da Anthropic no cofre do Windows (app desktop)",
)
def salvar_chave(req: ChaveAnthropicRequest) -> ChaveAnthropicStatus:
    _exigir_modo_desktop()
    try:
        chave_anthropic.salvar_chave_anthropic(req.chave)
    except chave_anthropic.ChaveInvalida as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except chave_anthropic.CofreIndisponivel:
        raise HTTPException(status_code=503, detail="Cofre de credenciais indisponível.") from None
    except Exception as exc:  # noqa: BLE001 — erro do backend do cofre; nunca ecoa a chave
        logger.error("Falha ao salvar chave no cofre: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Não foi possível salvar no cofre do Windows.") from None
    return ChaveAnthropicStatus(**chave_anthropic.status_chave())


@router.delete(
    "/settings/anthropic-key",
    response_model=ChaveAnthropicStatus,
    summary="Remove a chave da Anthropic do cofre do Windows (app desktop)",
)
def apagar_chave() -> ChaveAnthropicStatus:
    _exigir_modo_desktop()
    try:
        chave_anthropic.apagar_chave_anthropic()
    except chave_anthropic.CofreIndisponivel:
        raise HTTPException(status_code=503, detail="Cofre de credenciais indisponível.") from None
    except Exception as exc:  # noqa: BLE001
        logger.error("Falha ao remover chave do cofre: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Não foi possível remover do cofre do Windows.") from None
    return ChaveAnthropicStatus(**chave_anthropic.status_chave())
