# -*- coding: utf-8 -*-
"""
sieg_service.py — Serviço unificado Sieg (antes: adapter + credentials + ingestor).

Faz TUDO em um fluxo sequencial e explícito:
    1. Carrega API key (env → arquivo → AWS)
    2. POST /BaixarXmls com paginação + rate limit
    3. Cifra e persiste cada XML novo
    4. Registra em auditoria_documentos (idempotente por hash)

Razão da fusão: o padrão Adapter/Ingestor/Credentials forçava 3 arquivos
e injeção de dependência para o que é uma operação transacional direta.
Complexidade desnecessária — quebrando o princípio Explicit > Implicit.

API Sieg (spec confirmada):
    POST https://api.sieg.com/BaixarXmls?api_key=<KEY>
    Rate limit: 30 req/min
    Deadline: 31/07/2026 — migrar para nova REST API .NET
"""
from __future__ import annotations

import base64
import logging
import os
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)


# ─── Exceções ────────────────────────────────────────────────────────────────

class SiegError(RuntimeError):
    """Falha de comunicação ou contrato com Sieg."""

class SiegRateLimitError(SiegError):
    """429 persistente — esgotou retries."""

class SiegCredentialError(RuntimeError):
    """Falha ao obter a API key do Sieg."""


# ─── Constantes ──────────────────────────────────────────────────────────────

XML_TYPE_NFE = 1
XML_TYPE_CTE = 2
XML_TYPE_NFSE = 3
XML_TYPE_NFCE = 4
XML_TYPES_VALIDOS = (XML_TYPE_NFE, XML_TYPE_CTE, XML_TYPE_NFSE, XML_TYPE_NFCE)

_BASE_URL = "https://api.sieg.com"
_ENDPOINT = "/BaixarXmls"
_RATE_LIMIT_SLEEP = 2.1  # ~30 req/min
_PAGE_SIZE = 50
_JANELA_DIAS_MAX = 31
_MAX_RETRIES = 3
_TIMEOUT = 30


# ─── Dataclasses ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SiegXml:
    """XML decodificado retornado pela Sieg."""
    chave: str
    xml_bytes: bytes
    xml_type: int


@dataclass
class SincronizacaoResult:
    """Resumo de uma sincronização."""
    cnpj: str
    data_inicio: date
    data_fim: date
    xml_type: int
    total_baixados: int = 0
    total_novos: int = 0
    total_duplicados: int = 0
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


# ─── Carregar API Key (3 fontes canônicas) ───────────────────────────────────

def _path_arquivo_padrao() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(base) / "motor-conect" / "sieg.key"
    return Path("/etc/motor-conect/sieg.key")


def get_api_key() -> str:
    """
    Carrega SIEG_API_KEY na ordem: env var → arquivo protegido → AWS Secrets Manager.
    Raises SiegCredentialError se nenhuma fonte retornar chave.
    """
    # Fonte 1: env var
    valor = os.environ.get("SIEG_API_KEY", "").strip()
    if valor:
        return valor

    # Fonte 2: arquivo protegido
    override = os.environ.get("SIEG_API_KEY_FILE", "").strip()
    path = Path(override) if override else _path_arquivo_padrao()
    if path.exists():
        try:
            conteudo = path.read_text(encoding="utf-8").strip()
            if conteudo:
                return conteudo
        except OSError as exc:
            logger.error("Falha ao ler SIEG_API_KEY_FILE: %s", exc)

    # Fonte 3: AWS Secrets Manager
    secret_name = os.environ.get("SIEG_API_KEY_AWS_SECRET", "").strip()
    if secret_name:
        try:
            import boto3  # type: ignore
            client = boto3.client("secretsmanager")
            resp = client.get_secret_value(SecretId=secret_name)
            valor = resp.get("SecretString", "").strip()
            if valor:
                return valor
        except Exception as exc:  # noqa: BLE001
            logger.error("Falha ao buscar secret no AWS: %s", type(exc).__name__)

    raise SiegCredentialError(
        "SIEG_API_KEY não encontrada. Configure via env var, arquivo ou AWS."
    )


# ─── Serviço Unificado ──────────────────────────────────────────────────────

class SiegService:
    """
    Serviço direto: busca XMLs na Sieg, cifra e persiste.

    Uso:
        svc = SiegService()  # carrega API key automaticamente
        resultado = svc.sincronizar(cnpj="12345678000190", ...)
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or get_api_key()
        self._session = requests.Session()

    # ─── API Pública ─────────────────────────────────────────────────────

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
        Baixa XMLs da Sieg, cifra e persiste os novos. Idempotente por hash.
        """
        cnpj_limpo = "".join(filter(str.isdigit, cnpj or ""))
        resultado = SincronizacaoResult(
            cnpj=cnpj_limpo,
            data_inicio=data_inicio,
            data_fim=data_fim,
            xml_type=xml_type,
        )

        for item in self._baixar_xmls(
            cnpj=cnpj_limpo,
            data_inicio=data_inicio,
            data_fim=data_fim,
            xml_type=xml_type,
        ):
            resultado.total_baixados += 1
            try:
                foi_novo, hash_hex = self._persistir_xml(
                    item=item,
                    cnpj=cnpj_limpo,
                    uploaded_by_user_id=uploaded_by_user_id,
                )
                if foi_novo:
                    resultado.total_novos += 1
                    resultado.hashes_novos.append(hash_hex)
                else:
                    resultado.total_duplicados += 1
            except Exception as exc:  # noqa: BLE001
                msg = f"chave={item.chave[:20]!r}: {type(exc).__name__}: {exc}"
                resultado.erros.append(msg)
                logger.error("Sieg erro parcial | %s", msg)

        logger.info(
            "Sieg sincronizado | cnpj=%s | novos=%d | dup=%d | erros=%d",
            cnpj_limpo[:8] + "...",
            resultado.total_novos,
            resultado.total_duplicados,
            len(resultado.erros),
        )
        return resultado

    def baixar_xmls_raw(
        self,
        *,
        cnpj: str,
        data_inicio: date,
        data_fim: date,
        xml_type: int = XML_TYPE_NFE,
    ) -> Iterator[SiegXml]:
        """Acesso direto ao generator de XMLs sem persistência."""
        cnpj_limpo = "".join(filter(str.isdigit, cnpj or ""))
        yield from self._baixar_xmls(
            cnpj=cnpj_limpo,
            data_inicio=data_inicio,
            data_fim=data_fim,
            xml_type=xml_type,
        )

    # ─── HTTP + Paginação ────────────────────────────────────────────────

    def _baixar_xmls(
        self, *, cnpj: str, data_inicio: date, data_fim: date, xml_type: int,
    ) -> Iterator[SiegXml]:
        if xml_type not in XML_TYPES_VALIDOS:
            raise ValueError(f"xml_type inválido: {xml_type}")
        if len(cnpj) != 14:
            raise ValueError(f"CNPJ inválido: {cnpj!r} (14 dígitos esperados)")
        if data_fim < data_inicio:
            raise ValueError(f"data_fim ({data_fim}) anterior a data_inicio ({data_inicio})")

        # Divide janelas > 31 dias em fatias
        cursor = data_inicio
        while cursor <= data_fim:
            fatia_fim = min(cursor + timedelta(days=_JANELA_DIAS_MAX - 1), data_fim)
            yield from self._paginar(cnpj, cursor, fatia_fim, xml_type)
            cursor = fatia_fim + timedelta(days=1)

    def _paginar(
        self, cnpj: str, dt_ini: date, dt_fim: date, xml_type: int,
    ) -> Iterator[SiegXml]:
        skip = 0
        while True:
            body = {
                "XmlType": xml_type,
                "Take": _PAGE_SIZE,
                "Skip": skip,
                "DataEmissaoInicio": dt_ini.isoformat(),
                "DataEmissaoFim": dt_fim.isoformat(),
                "CnpjEmit": cnpj,
                "Downloadevent": False,
            }
            payload = self._post(body)
            if not payload:
                return
            for item in payload:
                yield self._decodificar(item, xml_type)
            if len(payload) < _PAGE_SIZE:
                return
            skip += _PAGE_SIZE

    def _post(self, body: dict) -> list[dict]:
        url = f"{_BASE_URL}{_ENDPOINT}"
        params = {"api_key": self.api_key}

        for tentativa in range(_MAX_RETRIES):
            try:
                resp = self._session.post(url, params=params, json=body, timeout=_TIMEOUT)
            except requests.RequestException as exc:
                raise SiegError(f"Falha de rede: {exc}") from exc

            if resp.status_code == 429:
                wait = 4 ** tentativa
                header = resp.headers.get("Retry-After", "")
                if header.isdigit():
                    wait = int(header)
                logger.warning("Sieg 429 (tentativa %d/%d) — %ds", tentativa + 1, _MAX_RETRIES, wait)
                time.sleep(wait)
                continue

            if not resp.ok:
                raise SiegError(f"Sieg HTTP {resp.status_code}: {resp.text[:500]}")

            try:
                payload = resp.json()
            except ValueError as exc:
                raise SiegError(f"JSON inválido: {resp.text[:500]}") from exc

            # Sieg às vezes retorna 200 + {"erro": "..."}
            if isinstance(payload, dict) and ("erro" in payload or "Erro" in payload):
                raise SiegError(f"Sieg erro lógico: {payload.get('erro') or payload.get('Erro')}")

            time.sleep(_RATE_LIMIT_SLEEP)

            # Normaliza resposta para lista
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                for k in ("Xmls", "xmls", "Data", "data"):
                    if k in payload and isinstance(payload[k], list):
                        return payload[k]
                return []
            raise SiegError(f"Tipo inesperado: {type(payload).__name__}")

        raise SiegRateLimitError(f"429 persistente após {_MAX_RETRIES} tentativas")

    @staticmethod
    def _decodificar(item: dict, xml_type: int) -> SiegXml:
        xml_b64 = item.get("Xml") or item.get("xml") or item.get("XmlBase64") or ""
        chave = item.get("ChaveNFe") or item.get("chaveNFe") or item.get("Chave") or item.get("chave") or ""
        if not xml_b64:
            raise SiegError(f"Item sem campo Xml base64: {list(item.keys())}")
        try:
            xml_bytes = base64.b64decode(xml_b64, validate=False)
        except (ValueError, TypeError) as exc:
            raise SiegError(f"Base64 inválido no item {chave!r}: {exc}") from exc
        return SiegXml(chave=str(chave), xml_bytes=xml_bytes, xml_type=xml_type)

    # ─── Persistência ────────────────────────────────────────────────────

    @staticmethod
    def _persistir_xml(
        *, item: SiegXml, cnpj: str, uploaded_by_user_id: int | None,
    ) -> tuple[bool, str]:
        """Cifra e registra um XML. Retorna (foi_novo, hash_hex)."""
        import database
        import services.storage_cifrado as storage_cifrado

        hash_hex = storage_cifrado.hash_documento(item.xml_bytes)

        # Idempotência: já existe?
        if database.buscar_documento_por_hash(hash_hex) is not None:
            return (False, hash_hex)

        if not storage_cifrado.existe(cnpj, hash_hex):
            storage_cifrado.cifrar_e_persistir(item.xml_bytes, cnpj)

        storage_path = str(storage_cifrado._path_para(cnpj, hash_hex))  # noqa: SLF001

        database.registrar_documento_auditoria(
            hash_sha256=hash_hex,
            empresa_cnpj=cnpj,
            nome_original=f"sieg::{item.chave}.xml",
            tamanho_bytes=len(item.xml_bytes),
            storage_path=storage_path,
            mime_type="application/xml",
            uploaded_by_user_id=uploaded_by_user_id,
        )
        return (True, hash_hex)
