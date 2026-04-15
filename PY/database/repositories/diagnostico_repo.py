import json
import re
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy.exc import IntegrityError, OperationalError
from ..connection import get_session
from ..models import DiagnosticoDB
from ..enums import RegimeTributario, StatusAuditoria

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
) -> DiagnosticoDB:
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

def buscar_diagnosticos_por_empresa(empresa_id: int) -> List[DiagnosticoDB]:
    with get_session() as session:
        return list(
            session.query(DiagnosticoDB)
            .filter(DiagnosticoDB.empresa_id == empresa_id)
            .order_by(DiagnosticoDB.created_at.desc())
            .all()
        )
