import logging
from datetime import datetime
from typing import List, Optional
from sqlalchemy.exc import IntegrityError, OperationalError
from ..connection import get_session
from ..models import AuditoriaDocumentoDB, AuditoriaAcessoDB

logger = logging.getLogger("motor_conect.database.auditoria")

def registrar_documento_auditoria(
    hash_sha256: str,
    empresa_cnpj: str,
    nome_original: str,
    tamanho_bytes: int,
    storage_path: str,
    mime_type: str = "application/pdf",
    paginas: Optional[int] = None,
    uploaded_by_user_id: Optional[int] = None,
    diagnostico_id: Optional[int] = None,
) -> AuditoriaDocumentoDB:
    # Validações do contrato original
    if not hash_sha256 or len(hash_sha256) != 64:
        raise ValueError(f"hash_sha256 invalido: '{hash_sha256}' (esperado 64 chars hex)")
    if not empresa_cnpj or not nome_original:
        raise ValueError("empresa_cnpj e nome_original sao obrigatorios")
    if tamanho_bytes <= 0:
        raise ValueError(f"tamanho_bytes invalido: {tamanho_bytes}")

    with get_session() as session:
        existente = session.query(AuditoriaDocumentoDB).filter(
            AuditoriaDocumentoDB.hash_sha256 == hash_sha256
        ).first()

        if existente:
            if diagnostico_id and existente.diagnostico_id != diagnostico_id:
                existente.diagnostico_id = diagnostico_id
                session.add(existente)
                session.commit()
                session.refresh(existente)
            return existente

        novo = AuditoriaDocumentoDB(
            hash_sha256=hash_sha256,
            empresa_cnpj=empresa_cnpj,
            nome_original=nome_original,
            mime_type=mime_type,
            tamanho_bytes=tamanho_bytes,
            paginas=paginas,
            storage_path=storage_path,
            uploaded_by_user_id=uploaded_by_user_id,
            diagnostico_id=diagnostico_id,
        )
        try:
            session.add(novo)
            session.commit()
            session.refresh(novo)
            return novo
        except IntegrityError as exc:
            session.rollback()
            raise RuntimeError(f"Falha ao registrar documento de auditoria: {exc.orig}")

def buscar_documentos_por_cnpj(empresa_cnpj: str) -> List[AuditoriaDocumentoDB]:
    with get_session() as session:
        return list(
            session.query(AuditoriaDocumentoDB)
            .filter(AuditoriaDocumentoDB.empresa_cnpj == empresa_cnpj)
            .filter(AuditoriaDocumentoDB.purged_at.is_(None))
            .order_by(AuditoriaDocumentoDB.uploaded_at.desc())
            .all()
        )

def buscar_documentos_por_diagnostico(diagnostico_id: int) -> List[AuditoriaDocumentoDB]:
    with get_session() as session:
        return list(
            session.query(AuditoriaDocumentoDB)
            .filter(AuditoriaDocumentoDB.diagnostico_id == diagnostico_id)
            .filter(AuditoriaDocumentoDB.purged_at.is_(None))
            .order_by(AuditoriaDocumentoDB.uploaded_at.asc())
            .all()
        )

def buscar_documento_por_hash(hash_sha256: str) -> Optional[AuditoriaDocumentoDB]:
    with get_session() as session:
        return session.query(AuditoriaDocumentoDB).filter(
            AuditoriaDocumentoDB.hash_sha256 == hash_sha256
        ).first()

def aceitar_documento(
    documento_id: int,
    aceito_por_user_id: int,
    aceito_ip: Optional[str] = None,
) -> Optional[AuditoriaDocumentoDB]:
    with get_session() as session:
        doc = session.query(AuditoriaDocumentoDB).filter(
            AuditoriaDocumentoDB.id == documento_id
        ).first()
        if not doc:
            return None
        doc.aceito_em = datetime.now().isoformat()
        doc.aceito_por_user_id = aceito_por_user_id
        doc.aceito_ip = aceito_ip
        session.add(doc)
        session.commit()
        session.refresh(doc)
        return doc

def marcar_documento_purgado(documento_id: int) -> Optional[AuditoriaDocumentoDB]:
    with get_session() as session:
        doc = session.query(AuditoriaDocumentoDB).filter(
            AuditoriaDocumentoDB.id == documento_id
        ).first()
        if not doc:
            return None
        doc.purged_at = datetime.now().isoformat()
        session.add(doc)
        session.commit()
        session.refresh(doc)
        return doc

def registrar_acesso_documento(
    documento_id: int,
    motivo: str,
    acessado_por_user_id: Optional[int] = None,
    ip: Optional[str] = None,
) -> AuditoriaAcessoDB:
    if not motivo or not motivo.strip():
        raise ValueError("motivo do acesso e obrigatorio (LGPD Art. 37)")
    
    log = AuditoriaAcessoDB(
        documento_id=documento_id,
        acessado_por_user_id=acessado_por_user_id,
        motivo=motivo.strip()[:500],
        ip=ip,
    )
    with get_session() as session:
        session.add(log)
        session.commit()
        session.refresh(log)
        return log

def listar_documentos_purgaveis(referencia: Optional[datetime] = None) -> List[AuditoriaDocumentoDB]:
    ref = (referencia or datetime.now()).isoformat()
    with get_session() as session:
        return list(
            session.query(AuditoriaDocumentoDB)
            .filter(AuditoriaDocumentoDB.purge_after <= ref)
            .filter(AuditoriaDocumentoDB.purged_at.is_(None))
            .all()
        )
