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
