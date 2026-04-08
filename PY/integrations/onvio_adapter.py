"""
onvio_adapter.py — Thomson Reuters Onvio (Domínio Contábil cloud).

Responsabilidades:
    - OAuth2 client_credentials flow com cache de token
    - Listar arquivos SPED ECD / EFD-Contribuições via REST
    - Download idempotente via checksum SHA-256
    - Retries com exponential backoff
    - Paginação via header 'next'

Uso esperado (Fase 2):
    adapter = OnvioAdapter(base_url=..., client_id=..., client_secret=..., token_url=...)
    for item in adapter.list_sped_files(since="2026-01-01"):
        if not database.existe_documento_auditoria(item["checksum"]):
            conteudo = adapter.download_file(item["id"])
            # alimenta pipeline /analise/pdf
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Iterator, Optional

import requests

logger = logging.getLogger(__name__)


class OnvioError(RuntimeError):
    """Falha de comunicação ou contrato com Onvio."""


class OnvioAdapter:
    """Cliente Onvio com OAuth2 client_credentials, pagination e retries."""

    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        token_url: str,
        *,
        max_retries: int = 3,
        timeout: int = 15,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self.max_retries = max_retries
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0
        self._session = requests.Session()

    # ─── OAuth2 ─────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        """Retorna token válido, renovando 60s antes da expiração."""
        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        try:
            resp = self._session.post(
                self.token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise OnvioError(f"Falha ao obter token Onvio: {exc}") from exc

        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = time.time() + int(payload.get("expires_in", 3600))
        return self._token

    # ─── HTTP com retry + backoff ───────────────────────────────────────────

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict] = None,
        stream: bool = False,
    ) -> requests.Response:
        last_exc: Optional[Exception] = None
        for tentativa in range(self.max_retries):
            try:
                headers = {"Authorization": f"Bearer {self._get_token()}"}
                resp = self._session.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    timeout=self.timeout,
                    stream=stream,
                )
                if resp.status_code == 429:
                    # Rate limit — respeitar Retry-After
                    wait = int(resp.headers.get("Retry-After", 2 ** tentativa))
                    logger.warning("Onvio 429 rate limit — aguardando %ss", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                last_exc = exc
                backoff = 2 ** tentativa
                logger.warning(
                    "Onvio %s %s falhou (tentativa %d/%d): %s — backoff %ds",
                    method, url, tentativa + 1, self.max_retries, exc, backoff,
                )
                time.sleep(backoff)
        raise OnvioError(f"Onvio {method} {url} falhou após {self.max_retries} tentativas: {last_exc}")

    # ─── Endpoints de negócio ───────────────────────────────────────────────

    def list_sped_files(
        self,
        *,
        since: Optional[str] = None,
        tipo: str = "all",
    ) -> Iterator[dict[str, Any]]:
        """
        Lista arquivos SPED disponíveis.

        Args:
            since: filtro ISO date 'YYYY-MM-DD' — só arquivos modificados após
            tipo: 'ecd' | 'efd_contrib' | 'all'

        Yields:
            dict com {id, nome, tipo, checksum, modificado_em, download_url}
        """
        url: Optional[str] = f"{self.base_url}/sped/files"
        params: Optional[dict] = {}
        if since:
            params["since"] = since
        if tipo != "all":
            params["tipo"] = tipo

        while url:
            resp = self._request("GET", url, params=params)
            payload = resp.json()
            for item in payload.get("items", []):
                yield item
            # Onvio paginação: campo 'next' ou header 'Link'
            url = payload.get("next")
            params = None  # só no primeiro request

    def download_file(self, file_id: str) -> bytes:
        """Baixa conteúdo binário de um arquivo SPED."""
        url = f"{self.base_url}/sped/files/{file_id}/download"
        resp = self._request("GET", url, stream=True)
        return resp.content

    def download_file_idempotente(
        self,
        file_id: str,
        checksum_esperado: str,
    ) -> bytes:
        """
        Baixa e valida checksum. Se não bater, RAISE — evita ingestão corrompida.
        """
        conteudo = self.download_file(file_id)
        checksum_real = self.checksum(conteudo)
        if checksum_real != checksum_esperado:
            raise OnvioError(
                f"Checksum mismatch em Onvio file_id={file_id}: "
                f"esperado={checksum_esperado} real={checksum_real}"
            )
        return conteudo

    # ─── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def checksum(content: bytes) -> str:
        """SHA-256 hex — mesma convenção de `storage_cifrado.hash_documento()`."""
        return hashlib.sha256(content).hexdigest()
