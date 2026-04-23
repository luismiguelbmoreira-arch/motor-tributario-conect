import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from auth import (
    autenticar_usuario,
    gerar_token_jwt,
    renovar_token_jwt,
    trocar_senha_proprio,
)
from api.dependencies import get_current_user, security, limiter

logger = logging.getLogger("motor_conect.api")

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    must_change_password: bool = False

class TrocarSenhaRequest(BaseModel):
    senha_atual: str = Field(..., min_length=1)
    nova_senha: str = Field(..., min_length=8)

@router.post("/login", response_model=LoginResponse)
@limiter.limit("5/minute")
def login(request: Request, req: LoginRequest):
    user = autenticar_usuario(req.username, req.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Credenciais inválidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = gerar_token_jwt(
        user_id=user.id,
        username=user.username,
        role=user.role,
    )
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        username=user.username,
        role=user.role,
        must_change_password=user.must_change_password,
    )

@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    return {
        "user_id": current_user.get("sub"),
        "username": current_user.get("username"),
        "role": current_user.get("role"),
    }

class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    renewed: bool

@router.post("/refresh", response_model=RefreshResponse)
def refresh_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Renovação de JWT — sempre 200 com token válido, ou 401 se inválido.

    - Se token tem < 2h para expirar: emite novo token (renewed=true).
    - Se token ainda tem > 2h: devolve o mesmo token (renewed=false).
    - Se token inválido/expirado: 401 (via renovar_token_jwt).

    Nunca retorna 304. 304 em POST quebra o contrato HTTP e faz o frontend
    interpretar como "sessão morta" sem necessidade.
    """
    novo = renovar_token_jwt(credentials.credentials)
    if novo is None:
        return RefreshResponse(
            access_token=credentials.credentials,
            token_type="bearer",
            renewed=False,
        )
    return RefreshResponse(
        access_token=novo,
        token_type="bearer",
        renewed=True,
    )

@router.post("/change-password")
def change_password(
    req: TrocarSenhaRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = int(current_user["sub"])
    try:
        sucesso = trocar_senha_proprio(user_id, req.senha_atual, req.nova_senha)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not sucesso:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    logger.info("Troca de senha confirmada | user_id=%s", user_id)
    return {"detail": "Senha alterada com sucesso."}
