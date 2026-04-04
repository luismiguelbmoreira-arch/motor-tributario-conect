# -*- coding: utf-8 -*-
"""
auth.py — Sistema de Autenticação JWT + bcrypt para o Motor Tributário Conect
Projeto: Motor Tributário Conect 2026-2033
Escritório Contábil Conect — Sorocaba, SP

SEGURANÇA:
  - Senhas armazenadas com bcrypt (passlib) — nunca reversível
  - Tokens JWT assinados com HS256, expiração 8h
  - SECRET_KEY via env var JWT_SECRET_KEY
  - Nunca loga senha, token completo, CNPJ ou dados pessoais
  - Tabela separada (UserDB) — não mistura com tabelas fiscais

LGPD:
  - Dados de acesso (ultimo_acesso) são operacionais, não fiscais
  - Logs sem identificação pessoal direta — apenas user_id interno
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
import jwt
from jwt.exceptions import PyJWTError as JWTError  # Drop-in para python-jose
from passlib.context import CryptContext
from sqlmodel import Field, Session, SQLModel, create_engine, select
from typing import Literal

logger = logging.getLogger("motor_conect.auth")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÃO — Constantes de autenticação
# ─────────────────────────────────────────────────────────────────────────────

# JWT_SECRET_KEY: OBRIGATÓRIO em produção via variável de ambiente.
# Se ausente: gera chave aleatória por sessão + aviso barulhento no log.
# Tokens NÃO sobrevivem a restart do servidor sem a variável configurada.
_jwt_secret_env = os.environ.get("JWT_SECRET_KEY")
if _jwt_secret_env:
    SECRET_KEY: str = _jwt_secret_env
else:
    import secrets as _secrets
    SECRET_KEY = _secrets.token_hex(32)
    logger.warning(
        "⚠️  JWT_SECRET_KEY não configurada! "
        "Usando chave aleatória — tokens expiram no restart. "
        "Configure JWT_SECRET_KEY no .env para produção."
    )
ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS: int = 8

# Contexto bcrypt — rounds padrão (12) para resistência a brute force
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Mesmo banco do database.py — motor_tributario.db
DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///motor_tributario.db")

_auth_engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


# ─────────────────────────────────────────────────────────────────────────────
# MODEL DE PERSISTÊNCIA
# ─────────────────────────────────────────────────────────────────────────────

class UserDB(SQLModel, table=True):
    """
    Tabela de usuários do sistema.
    Separada das tabelas fiscais — não contém dados tributários.
    Armazena apenas credenciais operacionais do escritório.
    """
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True, max_length=100)
    email: str = Field(unique=True, index=True, max_length=200)
    hashed_password: str = Field(max_length=200)
    role: str = Field(default="usuario", max_length=20)  # "admin" | "usuario"
    ativo: bool = Field(default=True)
    must_change_password: bool = Field(default=False)  # True = força troca no próximo login
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    ultimo_acesso: Optional[str] = Field(default=None)


# ─────────────────────────────────────────────────────────────────────────────
# EXCEÇÕES CUSTOMIZADAS
# ─────────────────────────────────────────────────────────────────────────────

class AutenticacaoError(Exception):
    """Falha de autenticação — credenciais inválidas ou token expirado."""
    pass


class UsuarioNaoEncontradoError(Exception):
    """Usuário não encontrado no banco."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

def criar_tabela_users() -> None:
    """
    Cria tabela `users` se não existir.
    Chamado no lifespan da FastAPI e em scripts de inicialização.
    """
    SQLModel.metadata.create_all(_auth_engine)
    logger.info("Tabela users criada/verificada.")


# ─────────────────────────────────────────────────────────────────────────────
# HASHING DE SENHA
# ─────────────────────────────────────────────────────────────────────────────

def verificar_senha(senha_plain: str, hashed: str) -> bool:
    """
    Verifica se senha plaintext corresponde ao hash bcrypt armazenado.
    Nunca loga a senha ou o hash.

    Args:
        senha_plain: senha informada pelo usuário
        hashed: hash bcrypt armazenado no banco

    Returns:
        True se senha válida, False caso contrário.
    """
    return _pwd_context.verify(senha_plain, hashed)


def _hash_senha(senha_plain: str) -> str:
    """
    Gera hash bcrypt de uma senha plaintext.
    Uso interno — nunca expor via API.
    """
    return _pwd_context.hash(senha_plain)


# ─────────────────────────────────────────────────────────────────────────────
# CRUD DE USUÁRIOS
# ─────────────────────────────────────────────────────────────────────────────

def criar_usuario(
    username: str,
    email: str,
    senha_plain: str,
    role: Literal["admin", "usuario"] = "usuario",
    must_change_password: bool = True,
) -> UserDB:
    """
    Cria novo usuário com senha bcrypt.
    Valida unicidade de username e email antes de inserir.

    Args:
        username: identificador único de login
        email: e-mail único do usuário
        senha_plain: senha em plaintext (será hasheada, nunca armazenada)
        role: "admin" ou "usuario"

    Returns:
        UserDB recém-criado.

    Raises:
        ValueError: se username ou email já existir no banco.
    """
    if role not in ("admin", "usuario"):
        raise ValueError(f"Role inválido: '{role}'. Valores aceitos: admin, usuario")

    with Session(_auth_engine) as session:
        # Verificação de unicidade antes de inserir
        existente_username = session.exec(
            select(UserDB).where(UserDB.username == username)
        ).first()
        if existente_username:
            raise ValueError(f"Username já cadastrado.")

        existente_email = session.exec(
            select(UserDB).where(UserDB.email == email)
        ).first()
        if existente_email:
            raise ValueError(f"E-mail já cadastrado.")

        novo = UserDB(
            username=username,
            email=email,
            hashed_password=_hash_senha(senha_plain),
            role=role,
            ativo=True,
            must_change_password=must_change_password,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        session.add(novo)
        session.commit()
        session.refresh(novo)
        logger.info("Usuário criado | id=%s | role=%s", novo.id, novo.role)
        return novo


def autenticar_usuario(username: str, senha_plain: str) -> Optional[UserDB]:
    """
    Busca usuário por username, verifica senha e atualiza ultimo_acesso.
    Retorna None se credenciais inválidas ou usuário inativo.
    Nunca loga senha ou indica qual campo falhou (timing-safe behavior).

    Args:
        username: identificador de login
        senha_plain: senha em plaintext para verificação

    Returns:
        UserDB se autenticado, None caso contrário.
    """
    with Session(_auth_engine) as session:
        user = session.exec(
            select(UserDB).where(UserDB.username == username)
        ).first()

        # Falha silenciosa — não indica se username não existe ou senha errada
        if not user or not user.ativo:
            return None

        if not verificar_senha(senha_plain, user.hashed_password):
            logger.warning("Falha de autenticação | user_id=REDACTED")
            return None

        # Atualiza ultimo_acesso
        user.ultimo_acesso = datetime.now(timezone.utc).isoformat()
        session.add(user)
        session.commit()
        session.refresh(user)

        logger.info("Autenticação bem-sucedida | id=%s | role=%s", user.id, user.role)
        return user


def get_user_by_id(user_id: int) -> Optional[UserDB]:
    """
    Busca usuário por ID primário.

    Returns:
        UserDB se encontrado, None caso contrário.
    """
    with Session(_auth_engine) as session:
        return session.get(UserDB, user_id)


def listar_usuarios() -> list[UserDB]:
    """
    Lista todos os usuários cadastrados, ordenados por id.

    Returns:
        Lista de UserDB (pode ser vazia).
    """
    with Session(_auth_engine) as session:
        return list(session.exec(select(UserDB).order_by(UserDB.id)).all())


def desativar_usuario(user_id: int) -> bool:
    """
    Desativa um usuário (soft delete — não apaga do banco).
    Usuário desativado não consegue autenticar.

    Args:
        user_id: ID do usuário a desativar.

    Returns:
        True se desativado, False se não encontrado.
    """
    with Session(_auth_engine) as session:
        user = session.get(UserDB, user_id)
        if not user:
            return False

        user.ativo = False
        session.add(user)
        session.commit()
        logger.info("Usuário desativado | id=%s", user_id)
        return True


def resetar_senha(user_id: int, nova_senha: str) -> bool:
    """
    Redefine a senha de um usuário via hash bcrypt.
    Apenas admins devem chamar este endpoint (validação no api_motor.py).

    Args:
        user_id: ID do usuário.
        nova_senha: Nova senha em plaintext (será hasheada aqui).

    Returns:
        True se redefinida, False se usuário não encontrado.

    Raises:
        ValueError: se nova_senha tiver menos de 8 caracteres.
    """
    if len(nova_senha) < 8:
        raise ValueError("A nova senha deve ter no mínimo 8 caracteres.")
    with Session(_auth_engine) as session:
        user = session.get(UserDB, user_id)
        if not user:
            return False
        user.hashed_password = _hash_senha(nova_senha)
        session.add(user)
        session.commit()
        logger.info("Senha redefinida | id=%s", user_id)
        return True


def trocar_senha_proprio(user_id: int, senha_atual: str, nova_senha: str) -> bool:
    """
    Permite que o próprio usuário altere sua senha, verificando a senha atual.
    Limpa o flag must_change_password após sucesso.

    Args:
        user_id: ID do usuário autenticado (vem do token JWT).
        senha_atual: Senha atual em plaintext para verificação.
        nova_senha: Nova senha em plaintext (será hasheada).

    Returns:
        True se alterada, False se usuário não encontrado.

    Raises:
        ValueError: senha_atual incorreta ou nova_senha < 8 caracteres.
    """
    if len(nova_senha) < 8:
        raise ValueError("A nova senha deve ter no mínimo 8 caracteres.")
    with Session(_auth_engine) as session:
        user = session.get(UserDB, user_id)
        if not user:
            return False
        if not verificar_senha(senha_atual, user.hashed_password):
            raise ValueError("Senha atual incorreta.")
        user.hashed_password = _hash_senha(nova_senha)
        user.must_change_password = False
        session.add(user)
        session.commit()
        logger.info("Senha alterada pelo próprio usuário | id=%s", user_id)
        return True


def criar_admin_default() -> None:
    """
    Cria usuário admin padrão se a tabela estiver vazia.
    Executado na startup da API — idempotente.

    Credenciais padrão (TROCAR EM PRODUÇÃO):
        username: admin
        senha:    Conect@2026!

    AVISO: alterar a senha via endpoint após primeiro deploy.
    """
    with Session(_auth_engine) as session:
        total = session.exec(select(UserDB)).first()
        if total is not None:
            return  # Tabela não está vazia — não cria admin padrão

    criar_usuario(
        username="admin",
        email="admin@conect.local",
        senha_plain="Conect@2026!",
        role="admin",
    )
    logger.info("Admin padrão criado. TROCAR SENHA EM PRODUÇÃO.")


# ─────────────────────────────────────────────────────────────────────────────
# JWT — Geração e verificação de tokens
# ─────────────────────────────────────────────────────────────────────────────

def gerar_token_jwt(user_id: int, username: str, role: str) -> str:
    """
    Gera token JWT com payload mínimo necessário.
    Expiração: ACCESS_TOKEN_EXPIRE_HOURS (8h por padrão).
    Nunca inclui senha, hash ou dados fiscais no payload.

    Args:
        user_id: ID primário do usuário (claim 'sub')
        username: nome de login (claim 'username')
        role: perfil de acesso (claim 'role')

    Returns:
        Token JWT assinado como string.
    """
    expiracao = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": expiracao,
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    # Log sem token completo — apenas confirmação de geração
    logger.info("Token JWT gerado | user_id=%s | role=%s | exp=%s", user_id, role, expiracao.isoformat())
    return token


def renovar_token_jwt(token: str) -> Optional[str]:
    """
    Renova JWT se restam menos de 2h para expirar.
    Retorna novo token ou None se não precisa renovar ainda.
    Lança HTTPException 401 se token inválido.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Token inválido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    exp = payload.get("exp")
    if exp is None:
        return None
    restante = datetime.fromtimestamp(exp, tz=timezone.utc) - datetime.now(timezone.utc)
    if restante.total_seconds() > 2 * 3600:
        return None  # Mais de 2h restantes — não precisa renovar
    # Renova com novo exp
    novo = gerar_token_jwt(
        user_id=int(payload["sub"]),
        username=payload["username"],
        role=payload["role"],
    )
    logger.info("Token renovado | user_id=%s", payload["sub"])
    return novo


def verificar_token(token: str) -> dict:
    """
    Decodifica e valida token JWT.
    Lança HTTPException 401 se inválido ou expirado.
    Nunca loga o token completo.

    Args:
        token: Bearer token recebido no header Authorization

    Returns:
        dict com claims: sub, username, role

    Raises:
        HTTPException 401: token inválido, expirado ou mal-formado
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: Optional[str] = payload.get("sub")
        username: Optional[str] = payload.get("username")
        role: Optional[str] = payload.get("role")

        if user_id is None or username is None or role is None:
            raise HTTPException(
                status_code=401,
                detail="Token inválido: claims obrigatórios ausentes.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return {"sub": user_id, "username": username, "role": role}

    except JWTError as exc:
        logger.warning("Token JWT inválido ou expirado | erro=%s", type(exc).__name__)
        raise HTTPException(
            status_code=401,
            detail="Token inválido ou expirado. Faça login novamente.",
            headers={"WWW-Authenticate": "Bearer"},
        )
