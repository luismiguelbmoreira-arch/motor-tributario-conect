"""
sieg_ingestor.py — Orquestra Sieg ↔ storage_cifrado ↔ auditoria_documentos.

Fluxo por XML:
    1. SiegAdapter.baixar_xmls() devolve SiegXml(chave, xml_bytes)
    2. storage_cifrado.hash_documento(xml_bytes) → sha256 hex
    3. Se já existe em auditoria_documentos pelo hash → pula (idempotente)
    4. storage_cifrado.cifrar_e_persistir(xml_bytes, cnpj) → (hash, path)
    5. database.registrar_documento_auditoria(hash, cnpj, nome_original, ...)
       com nome_original = "sieg::{chave}.xml" (marca de fonte sem
       alterar o schema FROZEN)

Retorna um SincronizacaoResult com contadores, primeiros/últimos hashes
e erros parciais (não quebra a sincronização inteira se 1 XML falhar).

LGPD / auditoria:
    - Cada XML novo vira linha em auditoria_documentos (LGPD Art. 37)
    - API key nunca persiste em DB nem em log
    - O prefixo "sieg::" em nome_original é a marca que o dossiê de prova
      usa pra identificar que o original veio da Sieg (não foi upload manual)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

import database
import services.storage_cifrado as storage_cifrado
from integrations.sieg_adapter import (
    SiegAdapter,
    SiegError,
    SiegXml,
    XML_TYPE_NFE,
)

logger = logging.getLogger(__name__)

NOME_ORIGINAL_PREFIX = "sieg::"


@dataclass
class SincronizacaoResult:
    """Resumo de uma chamada sincronizar()."""

    cnpj: str
    data_inicio: date
    data_fim: date
    xml_type: int
    total_baixados: int = 0       # quantos XMLs o Sieg devolveu
    total_novos: int = 0          # quantos entraram pela primeira vez
    total_duplicados: int = 0     # quantos já estavam em DB (idempotência)
    erros: list[str] = field(default_factory=list)
    hashes_novos: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "cnpj": self.cnpj,
            "data_inicio": self.data_inicio.isoformat(),
            "data_fim": self.data_fim.isoformat(),
            "xml_type": self.xml_type,
            "total_baixados": self.total_baixados,
            "total_novos": self.total_novos,
            "total_duplicados": self.total_duplicados,
            "erros": self.erros,
            "hashes_novos_prefix": [h[:16] for h in self.hashes_novos],
        }


class SiegIngestor:
    """
    Orquestra sincronização Sieg → storage_cifrado → DB.

    Instanciar com um SiegAdapter (ou deixar a fábrica criar um).
    """

    def __init__(self, adapter: SiegAdapter) -> None:
        self.adapter = adapter

    def sincronizar(
        self,
        *,
        cnpj: str,
        data_inicio: date,
        data_fim: date,
        xml_type: int = XML_TYPE_NFE,
        uploaded_by_user_id: int | None = None,
    ) -> SincronizacaoResult:
        """
        Baixa todos os XMLs do Sieg na janela e persiste os novos.

        Idempotente: re-executar a mesma janela não duplica registros.
        Tolera falhas parciais: um XML ruim não aborta a sincronização.

        Raises:
            SiegError: se a primeira chamada HTTP já falhar catastroficamente
                (ex: API key inválida — erro 401/403).
        """
        cnpj_limpo = "".join(filter(str.isdigit, cnpj or ""))
        resultado = SincronizacaoResult(
            cnpj=cnpj_limpo,
            data_inicio=data_inicio,
            data_fim=data_fim,
            xml_type=xml_type,
        )

        try:
            gerador = self.adapter.baixar_xmls(
                cnpj=cnpj_limpo,
                data_inicio=data_inicio,
                data_fim=data_fim,
                xml_type=xml_type,
            )
        except (SiegError, ValueError) as exc:
            logger.error("Sieg sincronizar abortou antes de iniciar: %s", exc)
            raise

        for item in gerador:
            resultado.total_baixados += 1
            try:
                foi_novo, hash_hex = self._processar_xml(
                    item=item,
                    cnpj=cnpj_limpo,
                    uploaded_by_user_id=uploaded_by_user_id,
                )
                if foi_novo:
                    resultado.total_novos += 1
                    resultado.hashes_novos.append(hash_hex)
                else:
                    resultado.total_duplicados += 1
            except Exception as exc:  # noqa: BLE001 - XML ruim não deve abortar
                msg = f"chave={item.chave[:20]!r}: {type(exc).__name__}: {exc}"
                resultado.erros.append(msg)
                logger.error("Sieg ingestor erro parcial | %s", msg)

        logger.info(
            "Sieg sincronizado | cnpj=%s | novos=%d | dup=%d | erros=%d",
            cnpj_limpo[:8] + "...",
            resultado.total_novos,
            resultado.total_duplicados,
            len(resultado.erros),
        )
        return resultado

    # ─── Internals ────────────────────────────────────────────────────────

    def _processar_xml(
        self,
        *,
        item: SiegXml,
        cnpj: str,
        uploaded_by_user_id: int | None,
    ) -> tuple[bool, str]:
        """
        Persiste um único XML. Retorna (foi_novo, hash_hex).

        Idempotência: se o hash já existe em auditoria_documentos, pula
        cifragem e retorna foi_novo=False.
        """
        hash_hex = storage_cifrado.hash_documento(item.xml_bytes)

        # Fast-path: já temos esse hash em DB? pula cifragem + I/O
        if database.buscar_documento_por_hash(hash_hex) is not None:
            return (False, hash_hex)

        # Idempotência no disco também (DB pode ter sido recriado em dev)
        if not storage_cifrado.existe(cnpj, hash_hex):
            storage_cifrado.cifrar_e_persistir(item.xml_bytes, cnpj)

        storage_path = str(storage_cifrado._path_para(cnpj, hash_hex))  # noqa: SLF001

        database.registrar_documento_auditoria(
            hash_sha256=hash_hex,
            empresa_cnpj=cnpj,
            nome_original=f"{NOME_ORIGINAL_PREFIX}{item.chave}.xml",
            tamanho_bytes=len(item.xml_bytes),
            storage_path=storage_path,
            mime_type="application/xml",
            uploaded_by_user_id=uploaded_by_user_id,
        )
        return (True, hash_hex)


def criar_ingestor_padrao() -> SiegIngestor:
    """Factory: instancia adapter com SIEG_API_KEY das 3 fontes canônicas."""
    from integrations.sieg_credentials import get_sieg_api_key

    adapter = SiegAdapter(api_key=get_sieg_api_key())
    return SiegIngestor(adapter)
