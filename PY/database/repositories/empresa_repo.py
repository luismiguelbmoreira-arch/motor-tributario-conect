import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy.exc import IntegrityError, OperationalError
from ..connection import get_session
from ..models import EmpresaDB, EmpresaHistoricoDB, AlertaDB, DiagnosticoDB, AtividadeDB

logger = logging.getLogger("motor_conect.database.empresa")

def salvar_empresa(empresa_domain: Any) -> EmpresaDB:
    with get_session() as session:
        existente = session.query(EmpresaDB).filter(
            EmpresaDB.cnpj == empresa_domain.cnpj
        ).first()

        try:
            if existente:
                existente.razao_social = empresa_domain.razao_social
                existente.regime = empresa_domain.regime
                existente.cnae_principal = empresa_domain.cnae_principal
                existente.uf_origem = empresa_domain.uf_origem
                existente.faturamento_12m = str(empresa_domain.faturamento_12m)
                existente.folha_salarios_12m = (
                    str(empresa_domain.folha_salarios_12m)
                    if empresa_domain.folha_salarios_12m is not None else None
                )
                existente.anexo_simples = empresa_domain.anexo_simples
                existente.updated_at = datetime.now().isoformat()
                session.add(existente)
                session.commit()
                session.refresh(existente)
                return existente
            else:
                nova = EmpresaDB.from_domain(empresa_domain)
                session.add(nova)
                session.commit()
                session.refresh(nova)
                return nova
        except (IntegrityError, OperationalError) as exc:
            session.rollback()
            logger.error("Erro ao salvar empresa: %s", exc)
            raise RuntimeError("Erro na persistência da empresa.") from exc

def registrar_historico_empresa(
    empresa_id: int,
    campo_alterado: str,
    valor_novo: str,
    alterado_por: str,
    valor_anterior: Optional[str] = None,
    motivo: Optional[str] = None,
) -> EmpresaHistoricoDB:
    registro = EmpresaHistoricoDB(
        empresa_id=empresa_id,
        campo_alterado=campo_alterado,
        valor_anterior=valor_anterior,
        valor_novo=valor_novo,
        alterado_por=alterado_por,
        motivo=motivo,
    )
    with get_session() as session:
        try:
            session.add(registro)
            session.commit()
            session.refresh(registro)
            return registro
        except Exception as exc:
            session.rollback()
            raise RuntimeError(f"Erro ao registrar histórico: {exc}")

def buscar_empresa_por_cnpj(cnpj: str) -> Optional[EmpresaDB]:
    with get_session() as session:
        return session.query(EmpresaDB).filter(EmpresaDB.cnpj == cnpj).first()

def listar_empresas() -> List[EmpresaDB]:
    with get_session() as session:
        return list(session.query(EmpresaDB).all())

def buscar_historico_empresa(empresa_id: int) -> List[EmpresaHistoricoDB]:
    with get_session() as session:
        return list(
            session.query(EmpresaHistoricoDB)
            .filter(EmpresaHistoricoDB.empresa_id == empresa_id)
            .order_by(EmpresaHistoricoDB.alterado_em.desc())
            .all()
        )

def purge_empresa(cnpj: str) -> bool:
    with get_session() as session:
        empresa = session.query(EmpresaDB).filter(EmpresaDB.cnpj == cnpj).first()
        if not empresa:
            return False
        session.query(AlertaDB).filter(AlertaDB.empresa_id == empresa.id).delete()
        session.query(DiagnosticoDB).filter(DiagnosticoDB.empresa_id == empresa.id).delete()
        session.query(AtividadeDB).filter(AtividadeDB.empresa_id == empresa.id).delete()
        session.delete(empresa)
        session.commit()
        return True
