import logging
from typing import Dict, List, Optional

from sqlalchemy.exc import IntegrityError, OperationalError

from ..connection import get_session
from ..enums import NivelAlerta
from ..models import AlertaDB
from .diagnostico_repo import validar_competencia

logger = logging.getLogger("motor_conect.database.alerta")

def salvar_alertas(empresa_id: int, competencia: str, alertas: List[Dict[str, str]]) -> None:
    competencia = validar_competencia(competencia)
    with get_session() as session:
        for alerta in alertas:
            nivel_str = alerta.get("nivel", "INFO")
            NivelAlerta(nivel_str)  # Valida

            db_alerta = AlertaDB(
                empresa_id=empresa_id,
                competencia=competencia,
                nivel=nivel_str,
                codigo=alerta.get("codigo", "DESCONHECIDO"),
                mensagem=alerta.get("mensagem", ""),
                status="ABERTO",
            )
            session.add(db_alerta)
        try:
            session.commit()
        except (IntegrityError, OperationalError) as exc:
            session.rollback()
            logger.error("Erro ao salvar alertas: %s", exc)
            raise RuntimeError("Falha na persistência dos alertas.")

def buscar_alertas_por_nivel(nivel: str) -> List[AlertaDB]:
    with get_session() as session:
        return list(
            session.query(AlertaDB)
            .filter(AlertaDB.nivel == nivel)
            .order_by(AlertaDB.created_at.desc())
            .all()
        )

def buscar_alertas_por_empresa(empresa_id: int) -> List[AlertaDB]:
    with get_session() as session:
        return list(
            session.query(AlertaDB)
            .filter(AlertaDB.empresa_id == empresa_id)
            .order_by(AlertaDB.created_at.desc())
            .all()
        )

def resolver_alerta(
    alerta_id: int,
    resolvido_por: str,
    acao_tomada: str,
    status: str = "RESOLVIDO",
) -> Optional[AlertaDB]:
    from datetime import datetime
    with get_session() as session:
        alerta = session.query(AlertaDB).filter(AlertaDB.id == alerta_id).first()
        if not alerta:
            return None
        alerta.status = status
        alerta.resolvido_em = datetime.now().isoformat()
        alerta.resolvido_por = resolvido_por.strip()
        alerta.acao_tomada = acao_tomada.strip()
        session.add(alerta)
        session.commit()
        session.refresh(alerta)
        return alerta
