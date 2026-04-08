"""
sieg_adapter.py — Sieg (exports XML NFe via API ou ZIP).

Responsabilidades:
    - OAuth2 ou bearer token para API Sieg
    - Fetch de lotes de XMLs NFe
    - Normalização de export ZIP (CSV/JSON/XML misturados)
    - Idempotência via checksum SHA-256

Uso esperado (Fase 2):
    adapter = SiegAdapter(api_base="https://api.sieg.com.br", api_token="...")
    for export in adapter.fetch_exports(since="2026-01-01"):
        dados = adapter.normalize_export(export["conteudo"])
        # alimenta parser xml_nfe
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import time
import zipfile
from typing import Any, Iterator, Optional

import requests

logger = logging.getLogger(__name__)


class SiegError(RuntimeError):
    """Falha de comunicação ou contrato com Sieg."""


class SiegAdapter:
    """
    Cliente Sieg — suporta modo API (online) e modo ZIP (fallback offline).

    Modo API: passe api_base + api_token.
    Modo ZIP: chame `normalize_export(bytes)` diretamente com um ZIP local.
    """

    def __init__(
        self,
        *,
        api_base: Optional[str] = None,
        api_token: Optional[str] = None,
        max_retries: int = 3,
        timeout: int = 15,
    ) -> None:
        self.api_base = api_base.rstrip("/") if api_base else None
        self.api_token = api_token
        self.max_retries = max_retries
        self.timeout = timeout
        self._session = requests.Session()

    # ─── API mode ───────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict] = None,
    ) -> requests.Response:
        if not self.api_token:
            raise SiegError("api_token é obrigatório em modo API.")

        last_exc: Optional[Exception] = None
        for tentativa in range(self.max_retries):
            try:
                headers = {"Authorization": f"Bearer {self.api_token}"}
                resp = self._session.request(
                    method, url, headers=headers, params=params, timeout=self.timeout
                )
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 2 ** tentativa))
                    logger.warning("Sieg 429 rate limit — aguardando %ss", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                last_exc = exc
                backoff = 2 ** tentativa
                logger.warning(
                    "Sieg %s %s falhou (%d/%d): %s — backoff %ds",
                    method, url, tentativa + 1, self.max_retries, exc, backoff,
                )
                time.sleep(backoff)
        raise SiegError(f"Sieg {method} {url} falhou após {self.max_retries} tentativas: {last_exc}")

    def fetch_exports(
        self,
        *,
        since: Optional[str] = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Lista exports Sieg disponíveis.

        Yields:
            dict com {id, cnpj, periodo, checksum, download_url}
        """
        if not self.api_base:
            raise SiegError("api_base é obrigatório em modo API.")

        url = f"{self.api_base}/exports"
        params = {"since": since} if since else None
        resp = self._request("GET", url, params=params)
        payload = resp.json()
        for item in payload.get("exports", []):
            yield item

    def download_export(self, export_id: str) -> bytes:
        if not self.api_base:
            raise SiegError("api_base é obrigatório em modo API.")
        url = f"{self.api_base}/exports/{export_id}/download"
        return self._request("GET", url).content

    # ─── Normalização (API + ZIP) ───────────────────────────────────────────

    def normalize_export(self, export_bytes: bytes) -> dict[str, Any]:
        """
        Normaliza um export Sieg para o schema interno.

        Aceita:
            - ZIP com múltiplos arquivos (CSV/JSON/XML)
            - JSON puro
            - XML NFe único (latin-1 ou utf-8)

        Retorna:
            {"notas": [...], "livros": [...], "xmls": [bytes, ...], "raw": <fallback>}
        """
        normalized: dict[str, Any] = {"notas": [], "livros": [], "xmls": []}

        # Tenta ZIP primeiro
        try:
            with zipfile.ZipFile(io.BytesIO(export_bytes)) as z:
                for name in z.namelist():
                    conteudo = z.read(name)
                    nome_lower = name.lower()
                    if nome_lower.endswith(".json"):
                        try:
                            parsed = json.loads(conteudo.decode("utf-8"))
                            if isinstance(parsed, dict):
                                normalized.setdefault("notas", []).extend(
                                    parsed.get("notas", [])
                                )
                                normalized.setdefault("livros", []).extend(
                                    parsed.get("livros", [])
                                )
                        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                            logger.warning("Sieg JSON inválido em %s: %s", name, exc)
                    elif nome_lower.endswith(".csv"):
                        normalized["livros"].extend(self._parse_csv(conteudo))
                    elif nome_lower.endswith(".xml"):
                        normalized["xmls"].append(conteudo)
                return normalized
        except zipfile.BadZipFile:
            pass

        # Fallback: JSON puro
        try:
            return json.loads(export_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass

        # Último fallback: XML cru ou texto
        if b"<nfeProc" in export_bytes[:256] or b"<NFe" in export_bytes[:256]:
            normalized["xmls"].append(export_bytes)
            return normalized

        normalized["raw"] = export_bytes.decode("latin-1", errors="ignore")
        return normalized

    # ─── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_csv(conteudo: bytes) -> list[list[str]]:
        """
        Parser CSV tolerante — latin-1 é padrão Sieg.
        TODO Fase 2: usar `csv.DictReader` com sniff de dialeto.
        """
        try:
            texto = conteudo.decode("latin-1")
        except UnicodeDecodeError:
            texto = conteudo.decode("utf-8", errors="ignore")
        return [
            [c.strip() for c in linha.split(";" if ";" in linha else ",")]
            for linha in texto.splitlines()
            if linha.strip()
        ]

    @staticmethod
    def checksum(content: bytes) -> str:
        """SHA-256 hex — mesma convenção de `storage_cifrado.hash_documento()`."""
        return hashlib.sha256(content).hexdigest()
