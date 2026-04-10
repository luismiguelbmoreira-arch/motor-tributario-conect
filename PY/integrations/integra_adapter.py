"""
integra_adapter.py — Cliente HTTP para Integra Contador (Serpro/RFB).

Protocolo:
    - mTLS obrigatório: certificado X.509 A1 (PKCS#12 .pfx) carrega identidade
      do escritório. O .pfx é aberto em memória via `cryptography.pkcs12` e
      materializado em arquivos PEM temporários (mode 0600 no POSIX) pra ser
      passado ao `requests.Session.cert = (cert_pem, key_pem)`.
    - Bearer JWT acima do mTLS: POST /authenticate/jwt devolve token de ~1h.
      O adapter cacheia e renova transparentemente.
    - Trio de identificação no body: `contratante`, `autorPedidoDados`,
      `contribuinte` (CNPJ do cliente final).

Serviços expostos (Fase 2B.1):
    - baixar_pgdasd(cnpj, periodo) → Iterator[IntegraDocumento] (PDF assinado)
    - emitir_das(cnpj, periodo) → Iterator[IntegraDocumento] (PDF boleto)

Escopo fora da Fase 2B.1: DCTFWeb, eSocial, EFD-Reinf.

Segurança:
    - Senha do .pfx NUNCA é logada.
    - Tmpfiles PEM são apagados em `close()` / `__del__`.
    - Cert derivado é gravado com PrivateFormat.PKCS8 sem senha — por isso
      os tmpfiles são 0600 e ficam só pelo tempo de vida do adapter.

Erros que o adapter converte:
    - IntegraCertError — não conseguiu abrir o .pfx (senha errada, arquivo
      corrompido, formato inválido)
    - IntegraAuthError — 401/403 do Serpro, inclusive mensagem de procuração
      e-CAC faltando
    - IntegraRateLimitError — 429 persistente após MAX_RETRIES
    - IntegraError — qualquer outro erro lógico ou HTTP
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

import requests

from integrations.integra_credentials import IntegraCredenciais

logger = logging.getLogger(__name__)


# ─── Exceções ────────────────────────────────────────────────────────────


class IntegraError(RuntimeError):
    """Qualquer falha de contrato ou comunicação com Integra Contador."""


class IntegraAuthError(IntegraError):
    """401/403 — JWT expirado, cert inválido, procuração faltando."""


class IntegraRateLimitError(IntegraError):
    """429 persistente após MAX_RETRIES."""


class IntegraCertError(IntegraError):
    """Não conseguiu abrir o .pfx (senha errada ou arquivo corrompido)."""


# ─── Dataclass de retorno ────────────────────────────────────────────────


TipoDocumento = Literal["pgdasd", "das"]


@dataclass(frozen=True)
class IntegraDocumento:
    """Representa um documento baixado do Integra Contador."""

    tipo: TipoDocumento
    periodo: str                          # "YYYY-MM"
    cnpj_contribuinte: str                # 14 dígitos
    conteudo: bytes                       # PDF (ou JSON) decodificado de base64
    mime_type: str                        # "application/pdf"
    extensao: str                         # ".pdf"
    metadata: dict[str, Any] = field(default_factory=dict)


# ─── Adapter ─────────────────────────────────────────────────────────────


# ID de sistema Serpro — mapeamento documentado em:
# https://servicos.serpro.gov.br/integracontador/
ID_SISTEMA_PGDASD = "PGDASD"
ID_SERVICO_CONSULTAR_DECLARACAO = "CONSULTARDECLARACAO13"

ID_SISTEMA_PAGTOWEB = "PAGTOWEB"
ID_SERVICO_GERAR_DAS = "GERARDAS12"


class IntegraAdapter:
    """
    Cliente HTTP Integra Contador — single-threaded, reutilizável.

    Uso:
        with IntegraAdapter(credenciais) as a:
            for doc in a.baixar_pgdasd(cnpj="...", periodo="2025-12"):
                ...

    Ou manualmente chamando `close()` / deixando `__del__` limpar tmpfiles.
    """

    BASE_URL_DEFAULT = (
        "https://gateway.apiserpro.serpro.gov.br/integra-contador/v1"
    )
    ENDPOINT_JWT = "/authenticate/jwt"
    ENDPOINT_CONSULTAR = "/Consultar"
    ENDPOINT_EMITIR = "/Emitir"

    JWT_TTL_SEGUNDOS = 3300               # 55 min (margem de 5 min)
    RATE_LIMIT_SLEEP = 1.1                # 60 req/min ≈ 1s, margem
    MAX_RETRIES = 3
    DEFAULT_TIMEOUT = 60

    def __init__(
        self,
        credenciais: IntegraCredenciais,
        *,
        base_url: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        self._cred = credenciais
        self._base_url = (
            base_url
            or credenciais.base_url
            or self.BASE_URL_DEFAULT
        ).rstrip("/")
        self._timeout = timeout

        # tmpfiles do cert — populados no _criar_session_com_cert()
        self._tmp_cert_path: str | None = None
        self._tmp_key_path: str | None = None

        if session is not None:
            # Permite injeção de sessão mockada em testes (sem tocar cert)
            self._session = session
            self._session_injetada = True
        else:
            self._session = self._criar_session_com_cert()
            self._session_injetada = False

        # JWT cache
        self._jwt: str | None = None
        self._jwt_expira_em: float = 0.0

    # ─── Context manager ────────────────────────────────────────────────

    def __enter__(self) -> "IntegraAdapter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:  # noqa: BLE001 — destrutor nunca levanta
            pass

    def close(self) -> None:
        """Apaga os tmpfiles PEM do certificado."""
        for path_attr in ("_tmp_cert_path", "_tmp_key_path"):
            path = getattr(self, path_attr, None)
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError as exc:
                    logger.warning(
                        "Falha ao apagar tmpfile de cert (%s): %s",
                        path, exc,
                    )
            setattr(self, path_attr, None)

    # ─── Carregamento do certificado PKCS#12 ────────────────────────────

    def _criar_session_com_cert(self) -> requests.Session:
        """
        Carrega .pfx via `cryptography`, materializa PEMs em tmpfiles 0600
        e instancia a Session com mTLS client cert.
        """
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.serialization import pkcs12
        except ImportError as exc:
            raise IntegraCertError(
                f"cryptography não instalada: {exc}"
            ) from exc

        try:
            with open(self._cred.cert_path, "rb") as f:
                pfx_bytes = f.read()
        except OSError as exc:
            raise IntegraCertError(
                f"falha ao ler cert_path: {exc}"
            ) from exc

        try:
            key, cert, _cas = pkcs12.load_key_and_certificates(
                pfx_bytes,
                self._cred.cert_password.encode("utf-8"),
            )
        except Exception as exc:  # noqa: BLE001 — cryptography tem muitas
            # Nunca logar a senha nem o path completo em erro
            raise IntegraCertError(
                f"falha ao decodificar PKCS#12 (senha errada ou arquivo inválido): "
                f"{type(exc).__name__}"
            ) from exc

        if cert is None or key is None:
            raise IntegraCertError(
                "PKCS#12 não contém certificado e chave privada completos"
            )

        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        key_pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

        # Tmpfiles com permissão restrita
        tmp_cert = tempfile.NamedTemporaryFile(
            prefix="integra_cert_", suffix=".pem", delete=False
        )
        tmp_cert.write(cert_pem)
        tmp_cert.close()

        tmp_key = tempfile.NamedTemporaryFile(
            prefix="integra_key_", suffix=".pem", delete=False
        )
        tmp_key.write(key_pem)
        tmp_key.close()

        if sys.platform != "win32":
            try:
                os.chmod(tmp_cert.name, 0o600)
                os.chmod(tmp_key.name, 0o600)
            except OSError as exc:
                logger.warning("chmod 0600 falhou nos tmpfiles: %s", exc)

        self._tmp_cert_path = tmp_cert.name
        self._tmp_key_path = tmp_key.name

        session = requests.Session()
        session.cert = (tmp_cert.name, tmp_key.name)
        return session

    # ─── JWT auto-refresh ───────────────────────────────────────────────

    def _garantir_jwt(self) -> str:
        """Retorna JWT válido; renova se expirado ou inexistente."""
        agora = time.monotonic()
        if self._jwt and agora < self._jwt_expira_em:
            return self._jwt

        url = f"{self._base_url}{self.ENDPOINT_JWT}"
        try:
            resp = self._session.post(url, timeout=self._timeout)
        except requests.RequestException as exc:
            raise IntegraAuthError(
                f"falha ao autenticar no Serpro: {exc}"
            ) from exc

        if resp.status_code in (401, 403):
            raise IntegraAuthError(
                f"autenticação Serpro rejeitou o certificado "
                f"(HTTP {resp.status_code})"
            )
        if resp.status_code >= 400:
            raise IntegraAuthError(
                f"erro ao obter JWT (HTTP {resp.status_code})"
            )

        try:
            payload = resp.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise IntegraAuthError(
                f"resposta /authenticate/jwt não é JSON: {exc}"
            ) from exc

        token = (
            payload.get("access_token")
            or payload.get("accessToken")
            or payload.get("token")
        )
        if not token or not isinstance(token, str):
            raise IntegraAuthError(
                "resposta /authenticate/jwt sem campo access_token/token"
            )

        # TTL configurável via resposta, mas nunca confiamos 100% —
        # usamos o menor entre o que a API disser e o nosso limite.
        ttl = int(payload.get("expires_in", self.JWT_TTL_SEGUNDOS) or 0)
        ttl_real = min(ttl, self.JWT_TTL_SEGUNDOS) if ttl > 0 else self.JWT_TTL_SEGUNDOS

        self._jwt = token
        self._jwt_expira_em = agora + ttl_real
        logger.info("Integra JWT renovado (TTL=%ds)", ttl_real)
        return token

    def _invalidar_jwt(self) -> None:
        self._jwt = None
        self._jwt_expira_em = 0.0

    # ─── Rate limiting ──────────────────────────────────────────────────

    def _sleep_rate_limit(self) -> None:
        """Separado pra ser mockável em testes."""
        time.sleep(self.RATE_LIMIT_SLEEP)

    def _retry_after(self, resp: requests.Response, tentativa: int) -> float:
        """Calcula tempo de espera pra 429."""
        header = resp.headers.get("Retry-After")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        return float(2**tentativa)

    # ─── Body Serpro padrão ─────────────────────────────────────────────

    def _montar_pedido(
        self,
        *,
        cnpj_contribuinte: str,
        id_sistema: str,
        id_servico: str,
        dados: dict[str, Any],
    ) -> dict[str, Any]:
        """Monta o envelope canônico esperado pela Integra Contador."""
        return {
            "contratante": {
                "numero": self._cred.contratante_cnpj,
                "tipo": 2,
            },
            "autorPedidoDados": {
                "numero": self._cred.autor_pedido_dados_cnpj,
                "tipo": 2,
            },
            "contribuinte": {
                "numero": cnpj_contribuinte,
                "tipo": 2,
            },
            "pedidoDados": {
                "idSistema": id_sistema,
                "idServico": id_servico,
                "versaoSistema": "1.0",
                "dados": json.dumps(dados, separators=(",", ":")),
            },
        }

    # ─── POST genérico com retry + refresh JWT ──────────────────────────

    def _post_servico(
        self,
        *,
        endpoint: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """
        POST autenticado com JWT e retry em 429/401.

        Trata:
            - 401 no meio → invalida JWT, tenta 1x de novo
            - 403 → IntegraAuthError (procuração faltando, típico)
            - 429 → respeita Retry-After, até MAX_RETRIES
            - 200 + {status: 4xx, mensagens: [...]} → IntegraError
            - JSON malformado → IntegraError
        """
        url = f"{self._base_url}{endpoint}"
        auth_retry_disponivel = True

        for tentativa in range(self.MAX_RETRIES):
            token = self._garantir_jwt()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            try:
                resp = self._session.post(
                    url,
                    headers=headers,
                    json=body,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                raise IntegraError(
                    f"falha de rede ao chamar {endpoint}: {exc}"
                ) from exc

            # 401 — pode ser JWT expirado no meio da call; tenta 1x
            if resp.status_code == 401 and auth_retry_disponivel:
                auth_retry_disponivel = False
                self._invalidar_jwt()
                continue

            if resp.status_code == 401:
                raise IntegraAuthError(
                    "401 Unauthorized mesmo após renovar JWT"
                )

            if resp.status_code == 403:
                msg = self._extrair_mensagem_erro(resp)
                raise IntegraAuthError(
                    f"403 Forbidden — verifique procuração e-CAC: {msg}"
                )

            if resp.status_code == 429:
                wait = self._retry_after(resp, tentativa)
                logger.warning(
                    "Integra 429 rate limit — aguardando %.1fs (tentativa %d/%d)",
                    wait, tentativa + 1, self.MAX_RETRIES,
                )
                time.sleep(wait)
                continue

            if resp.status_code >= 500:
                raise IntegraError(
                    f"erro HTTP {resp.status_code} do Serpro em {endpoint}"
                )

            if resp.status_code >= 400:
                msg = self._extrair_mensagem_erro(resp)
                raise IntegraError(
                    f"HTTP {resp.status_code} em {endpoint}: {msg}"
                )

            # 200 OK — mas Integra pode devolver erro lógico no payload
            try:
                payload = resp.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise IntegraError(
                    f"resposta {endpoint} não é JSON: {exc}"
                ) from exc

            self._checar_erro_logico(payload, endpoint)
            self._sleep_rate_limit()
            return payload

        raise IntegraRateLimitError(
            f"rate limit persistente em {endpoint} após {self.MAX_RETRIES} "
            f"tentativas"
        )

    # ─── Helpers de erro ────────────────────────────────────────────────

    @staticmethod
    def _extrair_mensagem_erro(resp: requests.Response) -> str:
        try:
            payload = resp.json()
        except (ValueError, json.JSONDecodeError):
            return (resp.text or "")[:200]

        mensagens = payload.get("mensagens") if isinstance(payload, dict) else None
        if isinstance(mensagens, list) and mensagens:
            partes = []
            for m in mensagens:
                if isinstance(m, dict):
                    partes.append(
                        f"[{m.get('codigo', '')}] {m.get('texto', '')}"
                    )
                else:
                    partes.append(str(m))
            return " | ".join(partes)[:500]

        if isinstance(payload, dict):
            return str(payload.get("mensagem") or payload)[:500]
        return str(payload)[:500]

    @staticmethod
    def _checar_erro_logico(payload: Any, endpoint: str) -> None:
        """
        Integra Contador às vezes retorna 200 OK com `{status: 400, mensagens: [...]}`
        pra erros de negócio. Detecta e levanta IntegraError.
        """
        if not isinstance(payload, dict):
            return
        status = payload.get("status")
        if isinstance(status, int) and status >= 400:
            mensagens = payload.get("mensagens")
            if isinstance(mensagens, list) and mensagens:
                partes = []
                for m in mensagens:
                    if isinstance(m, dict):
                        partes.append(
                            f"[{m.get('codigo', '')}] {m.get('texto', '')}"
                        )
                    else:
                        partes.append(str(m))
                msg = " | ".join(partes)
            else:
                msg = f"status={status}"
            raise IntegraError(f"erro lógico em {endpoint}: {msg}")

    # ─── Validação de entrada ───────────────────────────────────────────

    @staticmethod
    def _normalizar_cnpj(cnpj: str) -> str:
        digitos = "".join(ch for ch in (cnpj or "") if ch.isdigit())
        if len(digitos) != 14:
            raise ValueError(
                f"cnpj inválido: esperado 14 dígitos, recebido '{cnpj}'"
            )
        return digitos

    @staticmethod
    def _validar_periodo(periodo: str) -> str:
        """Aceita 'YYYY-MM' e devolve o formato 'YYYYMM' esperado pelo Serpro."""
        if not isinstance(periodo, str) or len(periodo) != 7 or periodo[4] != "-":
            raise ValueError(
                f"periodo inválido: esperado 'YYYY-MM', recebido '{periodo}'"
            )
        ano, mes = periodo.split("-")
        try:
            ano_i = int(ano)
            mes_i = int(mes)
        except ValueError as exc:
            raise ValueError(f"periodo inválido: {exc}") from exc
        if not (2000 <= ano_i <= 2099 and 1 <= mes_i <= 12):
            raise ValueError(f"periodo fora do range: '{periodo}'")
        return f"{ano_i:04d}{mes_i:02d}"

    # ─── Decoding base64 ────────────────────────────────────────────────

    @staticmethod
    def _decodificar_pdf(b64_str: str, contexto: str) -> bytes:
        if not isinstance(b64_str, str) or not b64_str.strip():
            raise IntegraError(f"{contexto}: PDF base64 ausente na resposta")
        try:
            return base64.b64decode(b64_str, validate=False)
        except (ValueError, binascii.Error) as exc:
            raise IntegraError(
                f"{contexto}: base64 inválido ({exc})"
            ) from exc

    # ─── Serviço PGDAS-D ────────────────────────────────────────────────

    def baixar_pgdasd(
        self,
        *,
        cnpj: str,
        periodo: str,
    ) -> Iterator[IntegraDocumento]:
        """
        Consulta declarações PGDAS-D do CNPJ no período (YYYY-MM).

        Yields 0 ou mais IntegraDocumento — múltiplos se houver retificadora.
        O primeiro documento é sempre a declaração mais recente (ou única).

        Raises:
            ValueError: cnpj/periodo inválido
            IntegraAuthError: procuração faltando, JWT inválido
            IntegraError: qualquer outro erro Serpro
        """
        cnpj_limpo = self._normalizar_cnpj(cnpj)
        periodo_apuracao = self._validar_periodo(periodo)

        body = self._montar_pedido(
            cnpj_contribuinte=cnpj_limpo,
            id_sistema=ID_SISTEMA_PGDASD,
            id_servico=ID_SERVICO_CONSULTAR_DECLARACAO,
            dados={"periodoApuracao": periodo_apuracao},
        )
        payload = self._post_servico(
            endpoint=self.ENDPOINT_CONSULTAR, body=body
        )

        yield from self._extrair_documentos_pgdasd(
            payload=payload,
            cnpj_contribuinte=cnpj_limpo,
            periodo=periodo,
        )

    def _extrair_documentos_pgdasd(
        self,
        *,
        payload: dict[str, Any],
        cnpj_contribuinte: str,
        periodo: str,
    ) -> Iterator[IntegraDocumento]:
        """Navega o payload Serpro pra extrair os PDFs assinados."""
        dados_str = payload.get("dados")
        if not isinstance(dados_str, str) or not dados_str:
            logger.info(
                "Integra PGDAS-D sem declarações para %s %s",
                cnpj_contribuinte[:8], periodo,
            )
            return

        try:
            dados = json.loads(dados_str)
        except json.JSONDecodeError as exc:
            raise IntegraError(
                f"payload PGDAS-D.dados não é JSON: {exc}"
            ) from exc

        # Serpro pode devolver lista direta ou dict com 'declaracoes'
        if isinstance(dados, dict):
            declaracoes = dados.get("declaracoes") or dados.get("Declaracoes") or [dados]
        elif isinstance(dados, list):
            declaracoes = dados
        else:
            return

        for idx, decl in enumerate(declaracoes):
            if not isinstance(decl, dict):
                continue
            pdf_b64 = (
                decl.get("pdf")
                or decl.get("recibo")
                or decl.get("reciboPdf")
                or decl.get("declaracaoPdf")
            )
            if not pdf_b64:
                continue

            pdf_bytes = self._decodificar_pdf(
                pdf_b64,
                contexto=f"PGDAS-D {cnpj_contribuinte[:8]} {periodo}",
            )

            retificadora = bool(
                decl.get("retificadora")
                or decl.get("ehRetificadora")
                or idx > 0  # Segunda em diante é considerada retificadora
            )

            yield IntegraDocumento(
                tipo="pgdasd",
                periodo=periodo,
                cnpj_contribuinte=cnpj_contribuinte,
                conteudo=pdf_bytes,
                mime_type="application/pdf",
                extensao=".pdf",
                metadata={
                    "retificadora": retificadora,
                    "numero_declaracao": decl.get("numeroDeclaracao"),
                    "data_transmissao": decl.get("dataTransmissao"),
                },
            )

    # ─── Serviço DAS ────────────────────────────────────────────────────

    def emitir_das(
        self,
        *,
        cnpj: str,
        periodo: str,
    ) -> Iterator[IntegraDocumento]:
        """
        Emite o DAS (boleto) do CNPJ no período (YYYY-MM).

        Yields 1 IntegraDocumento com o PDF do boleto. Levanta IntegraError
        se o período não tiver débito apurado.
        """
        cnpj_limpo = self._normalizar_cnpj(cnpj)
        periodo_apuracao = self._validar_periodo(periodo)

        body = self._montar_pedido(
            cnpj_contribuinte=cnpj_limpo,
            id_sistema=ID_SISTEMA_PAGTOWEB,
            id_servico=ID_SERVICO_GERAR_DAS,
            dados={"periodoApuracao": periodo_apuracao},
        )
        payload = self._post_servico(
            endpoint=self.ENDPOINT_EMITIR, body=body
        )

        yield from self._extrair_documento_das(
            payload=payload,
            cnpj_contribuinte=cnpj_limpo,
            periodo=periodo,
        )

    def _extrair_documento_das(
        self,
        *,
        payload: dict[str, Any],
        cnpj_contribuinte: str,
        periodo: str,
    ) -> Iterator[IntegraDocumento]:
        dados_str = payload.get("dados")
        if not isinstance(dados_str, str) or not dados_str:
            raise IntegraError(
                f"DAS {cnpj_contribuinte[:8]} {periodo}: payload sem dados"
            )

        try:
            dados = json.loads(dados_str)
        except json.JSONDecodeError as exc:
            raise IntegraError(
                f"payload DAS.dados não é JSON: {exc}"
            ) from exc

        if isinstance(dados, list):
            dados = dados[0] if dados else {}
        if not isinstance(dados, dict):
            raise IntegraError(
                f"DAS {cnpj_contribuinte[:8]} {periodo}: formato inesperado"
            )

        pdf_b64 = (
            dados.get("pdf")
            or dados.get("documento")
            or dados.get("documentoPdf")
            or dados.get("das")
        )
        if not pdf_b64:
            raise IntegraError(
                f"DAS {cnpj_contribuinte[:8]} {periodo}: PDF ausente"
            )

        pdf_bytes = self._decodificar_pdf(
            pdf_b64,
            contexto=f"DAS {cnpj_contribuinte[:8]} {periodo}",
        )

        yield IntegraDocumento(
            tipo="das",
            periodo=periodo,
            cnpj_contribuinte=cnpj_contribuinte,
            conteudo=pdf_bytes,
            mime_type="application/pdf",
            extensao=".pdf",
            metadata={
                "valor_total": dados.get("valorTotal"),
                "data_vencimento": dados.get("dataVencimento"),
                "numero_documento": dados.get("numeroDocumento"),
            },
        )
