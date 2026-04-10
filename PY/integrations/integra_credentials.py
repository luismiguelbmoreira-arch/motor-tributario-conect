"""
integra_credentials.py — Cofre das credenciais do Integra Contador (Serpro/RFB).

Mesma estratégia 3-tier do MOTOR_CONECT_MASTER_KEY e SIEG_API_KEY:
    1. Env vars: INTEGRA_CERT_PATH, INTEGRA_CERT_PASSWORD,
       INTEGRA_CONTRATANTE_CNPJ, INTEGRA_AUTOR_PEDIDO_DADOS_CNPJ
       (base URL opcional via INTEGRA_BASE_URL, útil para sandbox)
    2. Arquivo INI protegido:
       - Linux: /etc/motor-conect/integra.ini (mode 0600 esperado)
       - Windows: %PROGRAMDATA%\\motor-conect\\integra.ini
    3. AWS Secrets Manager via INTEGRA_SECRET_NAME → JSON com os 4 campos

Diferente do Sieg (uma única string), Integra Contador exige um pacote:
    - cert_path:             .pfx (PKCS#12, A1)
    - cert_password:         senha do PKCS#12
    - contratante_cnpj:      CNPJ do escritório que contratou Serpro (14 dígitos)
    - autor_pedido_dados_cnpj: CNPJ do autor do pedido (geralmente == contratante)

Nenhuma fonte persiste no DB. Nenhuma fonte é logada com senha/path.

A abertura real do .pfx fica no adapter — aqui só carregamos metadados.
"""
from __future__ import annotations

import configparser
import json
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class IntegraCredentialError(RuntimeError):
    """Falha ao obter as credenciais do Integra Contador."""


@dataclass(frozen=True)
class IntegraCredenciais:
    """
    Pacote de credenciais para um contratante Serpro.

    Validação: todos os 4 campos obrigatórios, CNPJs com 14 dígitos,
    senha não-vazia, cert_path existente. base_url é opcional.
    """

    cert_path: Path
    cert_password: str
    contratante_cnpj: str
    autor_pedido_dados_cnpj: str
    base_url: str | None = None


def _normalizar_cnpj(valor: str, campo: str) -> str:
    digitos = "".join(ch for ch in (valor or "") if ch.isdigit())
    if len(digitos) != 14:
        raise IntegraCredentialError(
            f"{campo} inválido: esperado 14 dígitos, recebido '{valor}'"
        )
    return digitos


def _montar(
    *,
    cert_path: str,
    cert_password: str,
    contratante_cnpj: str,
    autor_pedido_dados_cnpj: str,
    base_url: str | None = None,
) -> IntegraCredenciais:
    if not cert_path:
        raise IntegraCredentialError("cert_path vazio")
    if not cert_password:
        raise IntegraCredentialError("cert_password vazio")

    path = Path(cert_path).expanduser()
    if not path.exists():
        raise IntegraCredentialError(
            f"cert_path não encontrado: {path} (confira INTEGRA_CERT_PATH)"
        )

    return IntegraCredenciais(
        cert_path=path,
        cert_password=cert_password,
        contratante_cnpj=_normalizar_cnpj(contratante_cnpj, "contratante_cnpj"),
        autor_pedido_dados_cnpj=_normalizar_cnpj(
            autor_pedido_dados_cnpj, "autor_pedido_dados_cnpj"
        ),
        base_url=(base_url or None),
    )


def _path_arquivo_padrao() -> Path:
    """Path do arquivo-cofre padrão por SO."""
    if sys.platform == "win32":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(base) / "motor-conect" / "integra.ini"
    return Path("/etc/motor-conect/integra.ini")


def _ler_env() -> IntegraCredenciais | None:
    """Fonte 1 — variáveis de ambiente."""
    cert_path = os.environ.get("INTEGRA_CERT_PATH", "").strip()
    cert_password = os.environ.get("INTEGRA_CERT_PASSWORD", "").strip()
    contratante = os.environ.get("INTEGRA_CONTRATANTE_CNPJ", "").strip()
    autor = os.environ.get("INTEGRA_AUTOR_PEDIDO_DADOS_CNPJ", "").strip()
    base_url = os.environ.get("INTEGRA_BASE_URL", "").strip() or None

    # Todos os 4 obrigatórios precisam estar presentes pra declarar a fonte
    if not (cert_path and cert_password and contratante and autor):
        return None

    return _montar(
        cert_path=cert_path,
        cert_password=cert_password,
        contratante_cnpj=contratante,
        autor_pedido_dados_cnpj=autor,
        base_url=base_url,
    )


def _ler_arquivo() -> IntegraCredenciais | None:
    """
    Fonte 2 — arquivo INI protegido no sistema de arquivos.

    Formato esperado:
        [integra]
        cert_path = /etc/motor-conect/escritorio.pfx
        cert_password = ...
        contratante_cnpj = 12345678000190
        autor_pedido_dados_cnpj = 12345678000190
        base_url = https://gateway.apiserpro.serpro.gov.br/integra-contador/v1

    Override do path via INTEGRA_CONFIG_FILE. Em Linux, verifica mode 0600.
    """
    override = os.environ.get("INTEGRA_CONFIG_FILE", "").strip()
    path = Path(override) if override else _path_arquivo_padrao()

    if not path.exists():
        return None

    if sys.platform != "win32":
        try:
            modo = path.stat().st_mode & 0o777
            if modo & 0o077:
                logger.warning(
                    "INTEGRA_CONFIG_FILE com permissões frouxas (%o) — esperado 0600",
                    modo,
                )
        except OSError:
            pass

    try:
        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError) as exc:
        logger.error("Falha ao ler INTEGRA_CONFIG_FILE: %s", exc)
        return None

    if "integra" not in parser:
        logger.error(
            "INTEGRA_CONFIG_FILE sem seção [integra]: %s", path
        )
        return None

    sec = parser["integra"]
    return _montar(
        cert_path=sec.get("cert_path", "").strip(),
        cert_password=sec.get("cert_password", "").strip(),
        contratante_cnpj=sec.get("contratante_cnpj", "").strip(),
        autor_pedido_dados_cnpj=sec.get("autor_pedido_dados_cnpj", "").strip(),
        base_url=(sec.get("base_url", "").strip() or None),
    )


def _ler_aws_secret() -> IntegraCredenciais | None:
    """
    Fonte 3 — AWS Secrets Manager.

    Requer boto3 instalado e IAM role com `secretsmanager:GetSecretValue`.
    O secret é um JSON com as chaves: cert_path, cert_password,
    contratante_cnpj, autor_pedido_dados_cnpj, base_url (opcional).

    Silencioso se INTEGRA_SECRET_NAME não estiver setado.
    """
    secret_name = os.environ.get("INTEGRA_SECRET_NAME", "").strip()
    if not secret_name:
        return None

    try:
        import boto3  # type: ignore
    except ImportError:
        logger.error(
            "INTEGRA_SECRET_NAME setado mas boto3 não instalado."
        )
        return None

    try:
        client = boto3.client("secretsmanager")
        resp = client.get_secret_value(SecretId=secret_name)
        payload_str = resp.get("SecretString", "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.error("Falha ao buscar secret no AWS: %s", type(exc).__name__)
        return None

    if not payload_str:
        return None

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError as exc:
        logger.error("INTEGRA_SECRET_NAME não é JSON válido: %s", exc)
        return None

    return _montar(
        cert_path=payload.get("cert_path", ""),
        cert_password=payload.get("cert_password", ""),
        contratante_cnpj=payload.get("contratante_cnpj", ""),
        autor_pedido_dados_cnpj=payload.get("autor_pedido_dados_cnpj", ""),
        base_url=payload.get("base_url"),
    )


def get_integra_credenciais() -> IntegraCredenciais:
    """
    Retorna o pacote de credenciais do Integra Contador seguindo a ordem
    de prioridade das 3 fontes.

    Raises:
        IntegraCredentialError: nenhuma fonte retornou credenciais válidas.
    """
    for fonte, funcao in (
        ("env", _ler_env),
        ("arquivo", _ler_arquivo),
        ("aws", _ler_aws_secret),
    ):
        try:
            cred = funcao()
        except IntegraCredentialError as exc:
            # Fonte respondeu mas com dado inválido — propaga erro com contexto
            raise IntegraCredentialError(
                f"Credenciais Integra Contador inválidas na fonte '{fonte}': {exc}"
            ) from exc

        if cred is not None:
            logger.info(
                "Credenciais Integra Contador carregadas via fonte '%s' (contratante=%s...)",
                fonte,
                cred.contratante_cnpj[:8],
            )
            return cred

    raise IntegraCredentialError(
        "Credenciais Integra Contador não encontradas. Configure via env vars "
        "(INTEGRA_CERT_PATH, INTEGRA_CERT_PASSWORD, INTEGRA_CONTRATANTE_CNPJ, "
        "INTEGRA_AUTOR_PEDIDO_DADOS_CNPJ), arquivo INI protegido "
        "(INTEGRA_CONFIG_FILE) ou AWS Secrets Manager (INTEGRA_SECRET_NAME)."
    )
