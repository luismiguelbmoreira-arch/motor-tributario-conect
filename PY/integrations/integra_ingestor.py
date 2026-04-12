"""
integra_ingestor.py — Orquestra Integra Contador → storage cifrado → auditoria DB.

Fluxo por documento:
    1. adapter yields IntegraDocumento(tipo, periodo, cnpj, conteudo, mime, ext)
    2. hash = storage_cifrado.hash_documento(doc.conteudo)
    3. Se database.buscar_documento_por_hash(hash) existe → pula (duplicado)
    4. Senão: storage_cifrado.cifrar_e_persistir(doc.conteudo, cnpj)
    5. database.registrar_documento_auditoria(
           hash, cnpj, nome_original="integra::pgdasd_2025-12.pdf",
           mime_type=doc.mime_type, ...
       )

Idempotente por SHA-256. Tolera falhas parciais: um PGDAS-D quebrado
não aborta os outros 11 meses.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from integrations.integra_adapter import (
    IntegraAdapter,
    IntegraDocumento,
    IntegraError,
)

import database
import services.storage_cifrado as storage_cifrado

logger = logging.getLogger(__name__)


NOME_ORIGINAL_PREFIX = "integra::"
TIPOS_SUPORTADOS: tuple[str, ...] = ("pgdasd", "das")


@dataclass
class IntegraSyncResult:
    """Resultado agregado de uma sincronização Integra Contador."""

    cnpj: str
    periodos: list[str]
    tipos: tuple[str, ...]
    total_baixados: int = 0
    total_novos: int = 0
    total_duplicados: int = 0
    erros: list[str] = field(default_factory=list)
    hashes_novos: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "cnpj": self.cnpj,
            "periodos": list(self.periodos),
            "tipos": list(self.tipos),
            "total_baixados": self.total_baixados,
            "total_novos": self.total_novos,
            "total_duplicados": self.total_duplicados,
            "erros": list(self.erros),
            "hashes_novos_prefix": [h[:16] for h in self.hashes_novos],
        }


def _normalizar_cnpj(valor: str) -> str:
    digitos = "".join(ch for ch in (valor or "") if ch.isdigit())
    if len(digitos) != 14:
        raise ValueError(
            f"cnpj inválido: esperado 14 dígitos, recebido '{valor}'"
        )
    return digitos


class IntegraIngestor:
    """Orquestrador Integra Contador → storage cifrado + DB auditoria."""

    def __init__(self, adapter: IntegraAdapter) -> None:
        self.adapter = adapter

    # ─── API pública ────────────────────────────────────────────────────

    def sincronizar(
        self,
        *,
        cnpj: str,
        periodos: list[str],
        tipos: Sequence[str] = TIPOS_SUPORTADOS,
        uploaded_by_user_id: int | None = None,
    ) -> IntegraSyncResult:
        """
        Puxa do Integra Contador os documentos (tipo × periodo) pro CNPJ.

        Args:
            cnpj: 14 dígitos do cliente (aceita pontuação, normaliza).
            periodos: lista de "YYYY-MM".
            tipos: subconjunto de ("pgdasd", "das").
            uploaded_by_user_id: id do operador autenticado (opcional).

        Returns:
            IntegraSyncResult com contadores e hashes dos novos docs.
        """
        cnpj_limpo = _normalizar_cnpj(cnpj)
        tipos_validos = tuple(t for t in tipos if t in TIPOS_SUPORTADOS)
        if not tipos_validos:
            raise ValueError(
                f"tipos inválidos: {tipos!r}. Use subconjunto de {TIPOS_SUPORTADOS}"
            )

        resultado = IntegraSyncResult(
            cnpj=cnpj_limpo,
            periodos=list(periodos),
            tipos=tipos_validos,
        )

        # Contador de retificadoras por (tipo, periodo) — evita colisão
        # de nome_original quando PGDAS-D tem 2+ declarações pro mesmo mês.
        ret_counter: dict[tuple[str, str], int] = {}

        for tipo in tipos_validos:
            for periodo in periodos:
                try:
                    docs_iter = self._puxar(
                        tipo=tipo, cnpj=cnpj_limpo, periodo=periodo
                    )
                    for doc in docs_iter:
                        resultado.total_baixados += 1
                        try:
                            self._processar_doc(
                                doc=doc,
                                cnpj_limpo=cnpj_limpo,
                                ret_counter=ret_counter,
                                uploaded_by_user_id=uploaded_by_user_id,
                                resultado=resultado,
                            )
                        except Exception as exc:  # noqa: BLE001
                            msg = (
                                f"[{tipo} {periodo}] falha ao persistir: "
                                f"{type(exc).__name__}: {exc}"
                            )
                            logger.exception(msg)
                            resultado.erros.append(msg)
                except IntegraError as exc:
                    msg = f"[{tipo} {periodo}] Integra: {exc}"
                    logger.warning(msg)
                    resultado.erros.append(msg)
                except Exception as exc:  # noqa: BLE001
                    msg = (
                        f"[{tipo} {periodo}] erro inesperado: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    logger.exception(msg)
                    resultado.erros.append(msg)

        logger.info(
            "Integra sync cnpj=%s periodos=%d tipos=%s "
            "baixados=%d novos=%d duplicados=%d erros=%d",
            cnpj_limpo[:8] + "...",
            len(periodos),
            ",".join(tipos_validos),
            resultado.total_baixados,
            resultado.total_novos,
            resultado.total_duplicados,
            len(resultado.erros),
        )
        return resultado

    # ─── Internals ──────────────────────────────────────────────────────

    def _puxar(self, *, tipo: str, cnpj: str, periodo: str):
        if tipo == "pgdasd":
            return self.adapter.baixar_pgdasd(cnpj=cnpj, periodo=periodo)
        if tipo == "das":
            return self.adapter.emitir_das(cnpj=cnpj, periodo=periodo)
        raise ValueError(f"tipo desconhecido: {tipo!r}")

    def _processar_doc(
        self,
        *,
        doc: IntegraDocumento,
        cnpj_limpo: str,
        ret_counter: dict[tuple[str, str], int],
        uploaded_by_user_id: int | None,
        resultado: IntegraSyncResult,
    ) -> None:
        hash_sha = storage_cifrado.hash_documento(doc.conteudo)

        existente = database.buscar_documento_por_hash(hash_sha)
        if existente is not None:
            resultado.total_duplicados += 1
            return

        _, path_abs = storage_cifrado.cifrar_e_persistir(doc.conteudo, cnpj_limpo)

        nome_original = self._montar_nome_original(
            doc=doc, ret_counter=ret_counter
        )

        database.registrar_documento_auditoria(
            hash_sha256=hash_sha,
            empresa_cnpj=cnpj_limpo,
            nome_original=nome_original,
            tamanho_bytes=len(doc.conteudo),
            storage_path=str(path_abs),
            mime_type=doc.mime_type,
            uploaded_by_user_id=uploaded_by_user_id,
        )

        resultado.total_novos += 1
        resultado.hashes_novos.append(hash_sha)

    @staticmethod
    def _montar_nome_original(
        *,
        doc: IntegraDocumento,
        ret_counter: dict[tuple[str, str], int],
    ) -> str:
        """
        Gera nome_original único por (tipo, periodo), lidando com retificadoras.

        - Primeira declaração:   integra::pgdasd_2025-12.pdf
        - Retificadora 1:        integra::pgdasd_2025-12_ret1.pdf
        - Retificadora 2:        integra::pgdasd_2025-12_ret2.pdf
        """
        chave = (doc.tipo, doc.periodo)
        eh_retificadora = bool(doc.metadata.get("retificadora"))

        ext = doc.extensao if doc.extensao.startswith(".") else f".{doc.extensao}"
        base = f"{NOME_ORIGINAL_PREFIX}{doc.tipo}_{doc.periodo}"

        if not eh_retificadora and chave not in ret_counter:
            ret_counter[chave] = 0
            return f"{base}{ext}"

        ret_counter[chave] = ret_counter.get(chave, 0) + 1
        return f"{base}_ret{ret_counter[chave]}{ext}"
