"""
historico.py — Router GET /auditorias (Fase 5).

Lista paginada de diagnósticos do próprio usuário (ownership rigoroso).

SEGURANÇA:
  - Autenticação obrigatória via dependency do router.
  - Filtro por `uploaded_by_user_id == current_user.id` — sempre.
  - Admin NÃO tem bypass nesta fase (feature futura, ver plano).
  - Response sem PII: sem CNPJ, sem razão social, sem resultado_json.
    Só o mínimo pra popular a tabela do histórico.

LGPD:
  - Art. 6º V (minimização): devolve apenas campos necessários à listagem.
  - Art. 46 §1º (segurança): filtro por dono evita vazamento IDOR horizontal.

MAX_FISCAL:
  - Decimal serializado como string (DAS mensal).
  - response_model explícito em todos os endpoints (MAX auditoria).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from api.dependencies import extrair_user_id, get_current_user
from database import listar_diagnosticos_por_user

logger = logging.getLogger("motor_conect.api")


router = APIRouter(
    tags=["Histórico"],
    dependencies=[Depends(get_current_user)],
)


class AuditoriaResumo(BaseModel):
    """
    Item da listagem de histórico — APENAS metadados sem PII.

    Proibido adicionar cnpj, razao_social, resultado_json ou qualquer
    campo que identifique terceiros (fornecedor/cliente final). O front-end
    faz drill-down por `id` se precisar do detalhe (endpoint futuro, fora
    do escopo da Fase 5).
    """
    model_config = ConfigDict(extra="forbid")

    id: int
    competencia: str = Field(..., description="ISO YYYY-MM")
    regime_no_calculo: str = Field(..., description="SIMPLES | PRESUMIDO | REAL | MEI")
    das_mensal: str = Field(..., description="Decimal serializado como string")
    status_auditoria: Optional[str] = Field(None, description="APROVADO | PENDENTE | null")
    created_at: str = Field(..., description="Timestamp ISO de criação")


@router.get(
    "/auditorias",
    response_model=List[AuditoriaResumo],
    summary="Lista auditorias do próprio usuário (histórico)",
)
def listar_auditorias_usuario(
    skip: int = Query(0, ge=0, le=10_000, description="Offset de paginação"),
    limit: int = Query(20, ge=1, le=100, description="Máx. itens por página"),
    current_user: dict = Depends(get_current_user),
) -> List[AuditoriaResumo]:
    """
    Retorna até `limit` diagnósticos do usuário autenticado, do mais
    recente pro mais antigo.

    Ownership obrigatório (ERR-050): sem user_id válido no token, retorna
    404 (tratado como "sem histórico" — não vaza existência de registros).
    """
    user_id = extrair_user_id(current_user)
    if user_id is None:
        # Sem user_id válido, ownership não faz sentido. 404 = "nada pra você".
        # Não usamos 401 aqui porque o dependency já cuidou do caso não-autenticado.
        raise HTTPException(status_code=404, detail="Histórico indisponível.")

    try:
        registros = listar_diagnosticos_por_user(user_id=user_id, skip=skip, limit=limit)
    except Exception as exc:
        logger.warning(
            "Falha ao listar historico | user_id=%s | tipo=%s",
            user_id, type(exc).__name__,
        )
        # Fail-closed — devolve lista vazia (não 500) pra não expor erro
        # de DB ao atacante. Erros reais ficam no log do servidor.
        return []

    # ACHADO-L2 (Fase 5.1 — Luiz Moreira): log estruturado por consistência
    # com o padrão Fase 4 (HIDRATACAO_SESSAO em /analise/sessao). Telemetria
    # operacional mínima — user_id, count, skip — ZERO PII (sem CNPJ, sem
    # razão social, sem resultado_json). Útil em correlação de incidente.
    # Amparo: LGPD Art. 5º X + 37 (registro de operações de tratamento).
    logger.info(
        "AUDITORIAS_LISTADAS | user_id=%s | count=%s | skip=%s | limit=%s",
        user_id, len(registros), skip, limit,
    )

    return [
        AuditoriaResumo(
            id=r.id or 0,
            competencia=r.competencia,
            regime_no_calculo=r.regime_no_calculo,
            das_mensal=str(r.das_mensal),
            status_auditoria=r.status_auditoria,
            created_at=r.created_at,
        )
        for r in registros
    ]
