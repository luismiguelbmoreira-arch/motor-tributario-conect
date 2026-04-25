import json
import logging
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError, OperationalError

from ..connection import get_session
from ..enums import RegimeTributario
from ..models import AuditoriaDocumentoDB, DiagnosticoDB, EmpresaDB

logger = logging.getLogger("motor_conect.database.diagnostico")

def validar_competencia(competencia: str) -> str:
    """Valida formato ISO YYYY-MM."""
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", competencia):
        raise ValueError(f"Competencia '{competencia}' invalida. Use YYYY-MM.")
    return competencia

def salvar_diagnostico(
    empresa_id: int,
    competencia: str,
    resultado: Dict[str, Any],
    das_mensal: Decimal,
    aliquota_efetiva: Decimal,
    rbt12: Decimal,
    regime: str,
    das_ecac: Optional[Decimal] = None,
    uploaded_by_user_id: Optional[int] = None,
) -> DiagnosticoDB:
    """
    Persiste DiagnosticoDB.

    uploaded_by_user_id (Fase 5 / ERR-050): id do usuário autenticado que
    disparou a análise. Nullable para compatibilidade com registros antigos
    criados antes da migração 49832cc28f45. Sempre que o handler tiver um
    user_id válido, deve passar aqui — caso contrário o registro fica fora
    da listagem do /auditorias (LGPD Art. 46 — ownership).
    """
    competencia = validar_competencia(competencia)
    RegimeTributario(regime)

    delta = None
    status = None
    if das_ecac is not None:
        delta = abs(das_ecac - das_mensal)
        status = "APROVADO" if delta <= das_ecac * Decimal("0.01") else "PENDENTE"

    diag = DiagnosticoDB(
        empresa_id=empresa_id,
        competencia=competencia,
        resultado_json=json.dumps(resultado, default=str),
        das_mensal=str(das_mensal),
        aliquota_efetiva=str(aliquota_efetiva),
        rbt12_usado=str(rbt12),
        regime_no_calculo=regime,
        das_ecac_referencia=str(das_ecac) if das_ecac else None,
        delta=str(delta) if delta else None,
        status_auditoria=status,
        uploaded_by_user_id=uploaded_by_user_id,
    )

    with get_session() as session:
        try:
            session.add(diag)
            session.commit()
            session.refresh(diag)
            return diag
        except (IntegrityError, OperationalError) as exc:
            session.rollback()
            logger.error("Erro ao salvar diagnóstico: %s", exc)
            raise RuntimeError("Falha na persistência do diagnóstico.")

def tem_acesso_cnpj(user_id: int, cnpj: str) -> bool:
    """
    Verifica se user_id tem ao menos um diagnóstico ou documento vinculado ao CNPJ.

    Amparo: LGPD Art. 6º V (minimização) + CTN Art. 198 (sigilo fiscal).
    Usado como guard de ownership em endpoints de integração (ERR-018.b).

    Aceita CNPJ com ou sem pontuação — normaliza internamente para 14 dígitos.
    Admin bypass deve ser feito ANTES de chamar esta função.

    Registros com uploaded_by_user_id = NULL (pré-Fase 5) são intencionalmente
    excluídos — admin-only por design (decisão ERR-018.b, 24/04/2026).
    Usuários com dados antigos precisam rodar nova análise para estabelecer ownership.
    """
    apenas_digitos = re.sub(r"\D", "", cnpj or "")
    if len(apenas_digitos) != 14:
        return False

    with get_session() as session:
        # 1. Checa via DiagnosticoDB → EmpresaDB (CNPJ armazenado sem pontuação)
        tem_diag = (
            session.query(DiagnosticoDB)
            .join(EmpresaDB, DiagnosticoDB.empresa_id == EmpresaDB.id)
            .filter(
                EmpresaDB.cnpj == apenas_digitos,
                DiagnosticoDB.uploaded_by_user_id == user_id,
            )
            .first()
        )
        if tem_diag:
            return True

        # 2. Checa via AuditoriaDocumentoDB (empresa_cnpj pode ser formatado ou raw)
        cnpj_formatado = (
            f"{apenas_digitos[:2]}.{apenas_digitos[2:5]}.{apenas_digitos[5:8]}"
            f"/{apenas_digitos[8:12]}-{apenas_digitos[12:]}"
        )
        tem_doc = (
            session.query(AuditoriaDocumentoDB)
            .filter(
                AuditoriaDocumentoDB.empresa_cnpj.in_([apenas_digitos, cnpj_formatado]),
                AuditoriaDocumentoDB.uploaded_by_user_id == user_id,
            )
            .first()
        )
        return tem_doc is not None


def buscar_diagnosticos_por_empresa(empresa_id: int) -> List[DiagnosticoDB]:
    with get_session() as session:
        return list(
            session.query(DiagnosticoDB)
            .filter(DiagnosticoDB.empresa_id == empresa_id)
            .order_by(DiagnosticoDB.created_at.desc())
            .all()
        )


def listar_por_user(
    user_id: int,
    skip: int = 0,
    limit: int = 20,
) -> List[DiagnosticoDB]:
    """
    Lista diagnósticos do próprio usuário (ownership Fase 5).

    Filtra SEMPRE por uploaded_by_user_id — o endpoint público nunca
    devolve diagnóstico de terceiros (LGPD Art. 6º V + Art. 46).

    limit clampado a [0, 100] pelo próprio chamador/endpoint; aqui
    aceitamos qualquer int ≥ 0 e confiamos no clamp externo.

    skip < 0 ou limit < 0 devolvem lista vazia (defensivo, sem 500).
    """
    if skip < 0 or limit <= 0:
        return []
    with get_session() as session:
        return list(
            session.query(DiagnosticoDB)
            .filter(DiagnosticoDB.uploaded_by_user_id == user_id)
            .order_by(DiagnosticoDB.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
