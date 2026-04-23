import logging
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from auth import (
    criar_usuario,
    listar_usuarios,
    desativar_usuario,
    resetar_senha,
)
from api.dependencies import require_admin, limiter

logger = logging.getLogger("motor_conect.api")

router = APIRouter(prefix="/admin/usuarios", tags=["admin"])

class CriarUsuarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    email: EmailStr
    password: str
    role: Literal["admin", "usuario"] = "usuario"

class UsuarioResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    ativo: bool
    created_at: str
    ultimo_acesso: Optional[str]

class ResetSenhaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nova_senha: str = Field(..., min_length=8, description="Nova senha (mínimo 8 caracteres)")

@router.post("", response_model=UsuarioResponse)
@limiter.limit("10/minute")
def criar_usuario_endpoint(
    request: Request,
    req: CriarUsuarioRequest,
    _admin: dict = Depends(require_admin),
):
    try:
        novo = criar_usuario(
            username=req.username,
            email=req.email,
            senha_plain=req.password,
            role=req.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return UsuarioResponse(
        id=novo.id,
        username=novo.username,
        email=novo.email,
        role=novo.role,
        ativo=novo.ativo,
        created_at=novo.created_at,
        ultimo_acesso=novo.ultimo_acesso,
    )

@router.get("", response_model=list[UsuarioResponse])
def listar_usuarios_endpoint(_admin: dict = Depends(require_admin)):
    usuarios = listar_usuarios()
    return [
        UsuarioResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            role=u.role,
            ativo=u.ativo,
            created_at=u.created_at,
            ultimo_acesso=u.ultimo_acesso,
        )
        for u in usuarios
    ]

@router.post("/{user_id}/desativar")
def desativar_usuario_endpoint(
    user_id: int,
    admin: dict = Depends(require_admin),
):
    todos = listar_usuarios()
    admins_ativos = [u for u in todos if u.role == "admin" and u.ativo]
    alvo = next((u for u in todos if u.id == user_id), None)
    if alvo and alvo.role == "admin" and alvo.ativo and len(admins_ativos) <= 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "Operação bloqueada: você é o único administrador ativo. "
                "Promova outro usuário a admin antes de se desativar."
            ),
        )
    sucesso = desativar_usuario(user_id)
    if not sucesso:
        raise HTTPException(
            status_code=404,
            detail=f"Usuário id={user_id} não encontrado.",
        )
    return {"detail": f"Usuário id={user_id} desativado com sucesso."}

@router.post("/{user_id}/reset-senha")
def reset_senha_endpoint(
    user_id: int,
    req: ResetSenhaRequest,
    _admin: dict = Depends(require_admin),
):
    try:
        sucesso = resetar_senha(user_id, req.nova_senha)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not sucesso:
        raise HTTPException(status_code=404, detail=f"Usuário id={user_id} não encontrado.")
    return {"detail": f"Senha do usuário id={user_id} redefinida com sucesso."}
