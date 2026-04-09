"""
sieg_credentials.py — Cofre da API key do Sieg.

Mesma estratégia de 3 camadas do MOTOR_CONECT_MASTER_KEY:
    1. Env var SIEG_API_KEY (dev local, .env)
    2. Arquivo protegido (Linux: /etc/motor-conect/sieg.key;
       Windows: %PROGRAMDATA%\\motor-conect\\sieg.key)
    3. AWS Secrets Manager via SIEG_API_KEY_AWS_SECRET (produção cloud)

Nenhuma das fontes persiste no DB. Nenhuma das fontes é logada.

A API key do Sieg é gerada em "Minha Conta → Integrações API SIEG"
(admin only, validade 5 anos). É um token opaco passado como query
parameter `?api_key=...` nas chamadas HTTP para api.sieg.com.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class SiegCredentialError(RuntimeError):
    """Falha ao obter a API key do Sieg."""


def _path_arquivo_padrao() -> Path:
    """Path do arquivo-cofre padrão por SO."""
    if sys.platform == "win32":
        base = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        return Path(base) / "motor-conect" / "sieg.key"
    return Path("/etc/motor-conect/sieg.key")


def _ler_env() -> str | None:
    """Fonte 1 — variável de ambiente direta."""
    valor = os.environ.get("SIEG_API_KEY", "").strip()
    return valor or None


def _ler_arquivo() -> str | None:
    """
    Fonte 2 — arquivo protegido no sistema de arquivos.

    Override do path via SIEG_API_KEY_FILE. Em Linux, verifica permissões
    (mode 0600 esperado); em Windows, confia na ACL herdada.
    """
    override = os.environ.get("SIEG_API_KEY_FILE", "").strip()
    path = Path(override) if override else _path_arquivo_padrao()

    if not path.exists():
        return None

    try:
        conteudo = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.error("Falha ao ler SIEG_API_KEY_FILE: %s", exc)
        return None

    if sys.platform != "win32":
        try:
            modo = path.stat().st_mode & 0o777
            if modo & 0o077:
                logger.warning(
                    "SIEG_API_KEY_FILE com permissões frouxas (%o) — esperado 0600",
                    modo,
                )
        except OSError:
            pass

    return conteudo or None


def _ler_aws_secret() -> str | None:
    """
    Fonte 3 — AWS Secrets Manager.

    Requer boto3 instalado e IAM role com `secretsmanager:GetSecretValue`.
    Silencioso se SIEG_API_KEY_AWS_SECRET não estiver setado.
    """
    secret_name = os.environ.get("SIEG_API_KEY_AWS_SECRET", "").strip()
    if not secret_name:
        return None

    try:
        import boto3  # type: ignore
    except ImportError:
        logger.error(
            "SIEG_API_KEY_AWS_SECRET setado mas boto3 não instalado."
        )
        return None

    try:
        client = boto3.client("secretsmanager")
        resp = client.get_secret_value(SecretId=secret_name)
        valor = resp.get("SecretString", "").strip()
        return valor or None
    except Exception as exc:  # noqa: BLE001 - boto3 tem muitas exceções
        logger.error("Falha ao buscar secret no AWS: %s", type(exc).__name__)
        return None


def get_sieg_api_key() -> str:
    """
    Retorna a API key do Sieg seguindo a ordem de prioridade das 3 fontes.

    Raises:
        SiegCredentialError: nenhuma fonte retornou chave válida.
    """
    for fonte, funcao in (
        ("env", _ler_env),
        ("arquivo", _ler_arquivo),
        ("aws", _ler_aws_secret),
    ):
        valor = funcao()
        if valor:
            logger.info("SIEG_API_KEY carregada via fonte '%s'", fonte)
            return valor

    raise SiegCredentialError(
        "SIEG_API_KEY não encontrada. Configure via SIEG_API_KEY env var, "
        "SIEG_API_KEY_FILE (arquivo protegido), ou SIEG_API_KEY_AWS_SECRET."
    )
