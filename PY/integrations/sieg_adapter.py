"""
sieg_adapter.py — Cliente HTTP para a API Sieg (BaixarXmls).

Responsabilidades PURAS de I/O + decoding:
    - Autenticação via API Key estática (query parameter)
    - POST /BaixarXmls com pagination Skip/Take
    - Divisão automática de janelas > 31 dias em fatias mensais
    - Rate limit 30 req/min (sleep entre chamadas)
    - Retry com backoff em HTTP 429
    - Decoding base64 → bytes

NÃO FAZ:
    - Persistência em disco (é job do sieg_ingestor)
    - Cifragem (é job do storage_cifrado via ingestor)
    - Validação do XML (é job do parser xml_nfe downstream)
    - Gravação em DB (é job do ingestor via database)

API Sieg (spec confirmada):
    POST https://api.sieg.com/BaixarXmls?api_key=<KEY>
    Body: {
        "XmlType": 1 | 2 | 3 | 4,          # 1=NFe, 2=CTe, 3=NFSe, 4=NFCe
        "Take": 1..50,                     # page size (máx 50)
        "Skip": 0..N,                      # offset
        "DataEmissaoInicio": "YYYY-MM-DD",
        "DataEmissaoFim": "YYYY-MM-DD",
        "CnpjEmit": "00000000000000",      # 14 dígitos
        "Downloadevent": false
    }
    Resposta: JSON array de itens { "Xml": "<base64>", "ChaveNFe": "..." }
    Rate limit: 30 req/min
    Deadline: 31/07/2026 — base URL atual some, migrar para a nova REST API .NET

Amparo LGPD:
    Art. 37 — toda chamada deve virar linha em auditoria_acessos (via ingestor)
    Art. 46 — API key nunca em log, nunca em DB
"""
from __future__ import annotations

import base64
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)


class SiegError(RuntimeError):
    """Falha de comunicação ou contrato com Sieg."""


class SiegRateLimitError(SiegError):
    """429 persistente — esgotou retries."""


@dataclass(frozen=True)
class SiegXml:
    """XML decodificado retornado pelo adapter."""

    chave: str        # chave NFe (44 dígitos) ou identificador devolvido pela Sieg
    xml_bytes: bytes  # plaintext decodificado de base64
    xml_type: int     # 1=NFe, 2=CTe, 3=NFSe, 4=NFCe


# XmlType codes (Sieg spec)
XML_TYPE_NFE = 1
XML_TYPE_CTE = 2
XML_TYPE_NFSE = 3
XML_TYPE_NFCE = 4

XML_TYPES_VALIDOS = (XML_TYPE_NFE, XML_TYPE_CTE, XML_TYPE_NFSE, XML_TYPE_NFCE)


class SiegAdapter:
    """
    Cliente HTTP Sieg. Instanciar uma vez por sincronização.

    Exemplo:
        adapter = SiegAdapter(api_key="abc123...")
        for item in adapter.baixar_xmls(
            cnpj="12345678000190",
            data_inicio=date(2025, 1, 1),
            data_fim=date(2025, 12, 31),
            xml_type=1,
        ):
            print(item.chave, len(item.xml_bytes))
    """

    BASE_URL = "https://api.sieg.com"
    ENDPOINT_BAIXAR = "/BaixarXmls"
    RATE_LIMIT_SLEEP = 2.1   # s entre chamadas (30 req/min ≈ 2s)
    PAGE_SIZE = 50           # máx permitido pela Sieg
    JANELA_DIAS_MAX = 31     # Sieg recomenda não ultrapassar
    MAX_RETRIES = 3
    DEFAULT_TIMEOUT = 30     # s

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        if not api_key or not isinstance(api_key, str):
            raise ValueError("api_key obrigatória")
        self.api_key = api_key
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.timeout = timeout
        self._session = session or requests.Session()

    # ─── API pública ─────────────────────────────────────────────────────

    def baixar_xmls(
        self,
        *,
        cnpj: str,
        data_inicio: date,
        data_fim: date,
        xml_type: int = XML_TYPE_NFE,
    ) -> Iterator[SiegXml]:
        """
        Generator que emite XMLs decodificados.

        Pagina internamente via Skip += PAGE_SIZE até a resposta voltar vazia.
        Divide a janela em fatias de ≤ JANELA_DIAS_MAX dias e aplica sleep
        RATE_LIMIT_SLEEP entre chamadas.

        Raises:
            ValueError: parâmetros inválidos.
            SiegError: body com `erro` lógico, 4xx não-429, ou JSON malformado.
            SiegRateLimitError: HTTP 429 persistente após MAX_RETRIES.
        """
        if xml_type not in XML_TYPES_VALIDOS:
            raise ValueError(
                f"xml_type inválido: {xml_type}. Esperado um de {XML_TYPES_VALIDOS}"
            )
        cnpj_limpo = "".join(filter(str.isdigit, cnpj or ""))
        if len(cnpj_limpo) != 14:
            raise ValueError(f"cnpj inválido: {cnpj!r} (14 dígitos esperados)")
        if data_fim < data_inicio:
            raise ValueError(
                f"data_fim ({data_fim}) anterior a data_inicio ({data_inicio})"
            )

        for fatia_ini, fatia_fim in self._dividir_janela(data_inicio, data_fim):
            yield from self._paginar_fatia(
                cnpj=cnpj_limpo,
                data_inicio=fatia_ini,
                data_fim=fatia_fim,
                xml_type=xml_type,
            )

    # ─── Helpers internos ────────────────────────────────────────────────

    def _dividir_janela(
        self,
        inicio: date,
        fim: date,
    ) -> Iterator[tuple[date, date]]:
        """Fatias de até JANELA_DIAS_MAX dias, inclusive nos dois extremos."""
        cursor = inicio
        while cursor <= fim:
            fatia_fim = min(cursor + timedelta(days=self.JANELA_DIAS_MAX - 1), fim)
            yield (cursor, fatia_fim)
            cursor = fatia_fim + timedelta(days=1)

    def _paginar_fatia(
        self,
        *,
        cnpj: str,
        data_inicio: date,
        data_fim: date,
        xml_type: int,
    ) -> Iterator[SiegXml]:
        """Pagina via Skip/Take numa única fatia de janela."""
        skip = 0
        while True:
            body = {
                "XmlType": xml_type,
                "Take": self.PAGE_SIZE,
                "Skip": skip,
                "DataEmissaoInicio": data_inicio.isoformat(),
                "DataEmissaoFim": data_fim.isoformat(),
                "CnpjEmit": cnpj,
                "Downloadevent": False,
            }
            payload = self._post(body)
            if not payload:
                return

            for item in payload:
                yield self._decodificar_item(item, xml_type=xml_type)

            if len(payload) < self.PAGE_SIZE:
                return  # última página
            skip += self.PAGE_SIZE

    def _post(self, body: dict) -> list[dict]:
        """
        POST /BaixarXmls com retry em 429 e sleep de rate-limit após sucesso.

        Sieg às vezes responde 200 OK com `{"erro": "..."}` em vez de 4xx.
        Esta função detecta esse caso e eleva SiegError.
        """
        url = f"{self.base_url}{self.ENDPOINT_BAIXAR}"
        params = {"api_key": self.api_key}

        for tentativa in range(self.MAX_RETRIES):
            try:
                resp = self._session.post(
                    url,
                    params=params,
                    json=body,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise SiegError(f"Falha de rede contra {url}: {exc}") from exc

            if resp.status_code == 429:
                wait = self._retry_after(resp, tentativa)
                logger.warning(
                    "Sieg 429 (tentativa %d/%d) — aguardando %ds",
                    tentativa + 1, self.MAX_RETRIES, wait,
                )
                time.sleep(wait)
                continue

            if not resp.ok:
                raise SiegError(
                    f"Sieg HTTP {resp.status_code}: {resp.text[:500]}"
                )

            try:
                payload = resp.json()
            except ValueError as exc:
                raise SiegError(
                    f"Sieg devolveu JSON inválido: {resp.text[:500]}"
                ) from exc

            self._check_erro_logico(payload)
            self._sleep_rate_limit()
            return self._normalizar_lista(payload)

        raise SiegRateLimitError(
            f"Sieg 429 persistente após {self.MAX_RETRIES} tentativas"
        )

    @staticmethod
    def _retry_after(resp: requests.Response, tentativa: int) -> int:
        """Respeita o header Retry-After ou faz backoff exponencial."""
        header = resp.headers.get("Retry-After", "")
        if header.isdigit():
            return int(header)
        return 4 ** tentativa  # 1, 4, 16, 64 ...

    def _sleep_rate_limit(self) -> None:
        """Isolado em método pra facilitar mock nos testes."""
        time.sleep(self.RATE_LIMIT_SLEEP)

    @staticmethod
    def _check_erro_logico(payload: object) -> None:
        """
        Sieg devolve 200 + {erro: "..."} em casos como CNPJ sem autorização.
        Elevamos como SiegError para o chamador tratar.
        """
        if isinstance(payload, dict):
            if "erro" in payload or "Erro" in payload:
                msg = payload.get("erro") or payload.get("Erro")
                raise SiegError(f"Sieg erro lógico: {msg}")

    @staticmethod
    def _normalizar_lista(payload: object) -> list[dict]:
        """
        Sieg às vezes devolve lista direta, às vezes dict com chave 'Xmls'.
        Normaliza para lista de dicts.
        """
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for chave in ("Xmls", "xmls", "Data", "data"):
                if chave in payload and isinstance(payload[chave], list):
                    return payload[chave]
            # Dict sem lista conhecida e sem erro — trata como vazio
            return []
        raise SiegError(f"Sieg devolveu tipo inesperado: {type(payload).__name__}")

    @staticmethod
    def _decodificar_item(item: dict, *, xml_type: int) -> SiegXml:
        """Extrai (chave, xml_bytes) de um item da resposta."""
        xml_b64 = (
            item.get("Xml")
            or item.get("xml")
            or item.get("XmlBase64")
            or ""
        )
        chave = (
            item.get("ChaveNFe")
            or item.get("chaveNFe")
            or item.get("Chave")
            or item.get("chave")
            or ""
        )
        if not xml_b64:
            raise SiegError(f"Item sem campo Xml base64: {list(item.keys())}")
        try:
            xml_bytes = base64.b64decode(xml_b64, validate=False)
        except (ValueError, TypeError) as exc:
            raise SiegError(f"Base64 inválido no item {chave!r}: {exc}") from exc

        return SiegXml(chave=str(chave), xml_bytes=xml_bytes, xml_type=xml_type)
