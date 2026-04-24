from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from slowapi import Limiter
from slowapi.util import get_remote_address

from auth import verificar_token

security = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    return verificar_token(credentials.credentials)

def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Acesso restrito a administradores.",
        )
    return current_user


def extrair_user_id(current_user: Optional[dict]) -> Optional[int]:
    """
    Extrai user_id (int > 0) do dict de autenticação.

    Aceita tanto o formato nativo do verificar_token ({"sub": "1", ...})
    quanto fixtures de teste que usam {"id": 1, ...}. Retorna None se
    nenhum deles estiver presente ou for inválido — nunca lança.

    Esta tolerância é necessária porque get_current_user pode ser
    sobrescrito em testes via dependency_overrides com payload próprio.

    ERR-049 (Fase 5): movido de main.py para cá como helper universal.
    O JWT real emitido por auth.gerar_token_jwt() sempre usa claim "sub"
    (padrão RFC 7519). Chamadas antigas que faziam `current_user.get("id")`
    sempre retornavam None em produção — ownership latentemente quebrado.
    """
    if not current_user:
        return None
    candidato = current_user.get("sub") or current_user.get("id")
    if candidato is None:
        return None
    try:
        user_id = int(candidato)
    except (TypeError, ValueError):
        return None
    return user_id if user_id > 0 else None


limiter = Limiter(key_func=get_remote_address)
