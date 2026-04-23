"""
auditoria_tentativa_repo.py — Repositório de tentativas de acesso bloqueadas (IDOR).

Persiste registros de vetores IDOR horizontal detectados no runtime
(ERR-018.a em `/analise/sessao`, futuramente ERR-018.b em integrações).
A tabela subjacente (`AuditoriaTentativaAcessoDB`) guarda o suficiente
para correlação em incidente — prefixo do id tentado, user_id tentando,
user_id dono, IP, endpoint, timestamp — sem vazar o id completo (para
não recriar o vetor via dump).

Amparo legal:
  - LGPD Art. 37   — registro de operações de tratamento.
  - LGPD Art. 46 §1º — medidas de segurança obrigatórias.
  - LGPD Art. 48   — evidência de incidente (72h ANPD).
  - CTN  Art. 195  — retenção mínima de 5 anos (consistência com
                     `auditoria_documentos`).

Princípios:
  - Qualquer falha na persistência NÃO pode propagar para o handler —
    a resposta 404 ao atacante é mais importante que o log perfeito.
  - Nunca exportar método que lê tentativas sem motivo + user logado
    (futuro endpoint admin fica em outro módulo).
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError

from ..connection import get_session
from ..models import AuditoriaTentativaAcessoDB

logger = logging.getLogger("motor_conect.database.auditoria_tentativa")


def registrar_tentativa_acesso(
    *,
    analise_id_prefix: str,
    user_id_tentando: int,
    user_id_dono: Optional[int],
    ip: str,
    endpoint: str,
) -> Optional[AuditoriaTentativaAcessoDB]:
    """
    Persiste uma tentativa de acesso cruzado (IDOR horizontal) na auditoria.

    Args:
        analise_id_prefix: prefixo (até 8 chars) do id do recurso tentado.
        user_id_tentando: user_id autenticado que tentou o acesso.
        user_id_dono: user_id dono do recurso. `None` só quando o id não
            existia — nesses casos o handler NÃO deve chamar este helper
            (não é IDOR, é 404 legítimo). Mantido na assinatura por
            compatibilidade futura (Fase 5 — ecac/sync pode ter dono
            desconhecido até resolver o CNPJ).
        ip: endereço IP de origem (cleartext, LGPD Art. 7º VI).
        endpoint: rota HTTP que disparou a tentativa.

    Returns:
        Linha persistida, ou `None` se a persistência falhou. Nunca lança.

    LGPD Art. 46 §1º + 48: tabela é a base de prova em incidente. Retenção
    5 anos (CTN Art. 195) alinhada a `auditoria_documentos`.
    """
    # Validação mínima — não podemos gravar lixo na tabela de prova.
    if not analise_id_prefix:
        logger.warning("Tentativa de registrar tentativa sem id_prefix — ignorada.")
        return None
    if not isinstance(user_id_tentando, int) or user_id_tentando <= 0:
        logger.warning(
            "user_id_tentando inválido=%r — tentativa não registrada.",
            user_id_tentando,
        )
        return None
    if not ip:
        ip = "unknown"
    if not endpoint:
        logger.warning("endpoint vazio — tentativa não registrada.")
        return None

    # Prefixo fica limitado a 8 chars — coerente com o schema aprovado.
    prefix_seguro = analise_id_prefix[:8]
    # IP pode vir em qualquer formato; schema aceita até 45 chars (IPv6-mapped).
    ip_seguro = ip[:45]
    # Endpoint pode ser mais longo; schema aceita 255.
    endpoint_seguro = endpoint[:255]

    try:
        with get_session() as session:
            registro = AuditoriaTentativaAcessoDB(
                analise_id_prefix=prefix_seguro,
                user_id_tentando=user_id_tentando,
                user_id_dono=user_id_dono,
                ip=ip_seguro,
                endpoint=endpoint_seguro,
            )
            session.add(registro)
            session.commit()
            session.refresh(registro)
            return registro
    except SQLAlchemyError as exc:
        # Nunca propaga. O warning em analise_buffer.recuperar() já deixou
        # rastro — e o handler deve continuar devolvendo 404 ao atacante.
        logger.exception(
            "Falha ao persistir tentativa de acesso | user_id_tentando=%s | "
            "endpoint=%s | erro=%s",
            user_id_tentando, endpoint_seguro, type(exc).__name__,
        )
        return None
