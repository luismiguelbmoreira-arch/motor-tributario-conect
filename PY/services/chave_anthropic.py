# -*- coding: utf-8 -*-
"""
services/chave_anthropic.py — De onde vem a ANTHROPIC_API_KEY.

Web/servidor/testes: só da variável de ambiente (como sempre foi).
.exe desktop (MOTOR_CONECT_DESKTOP=1): primeiro o Gerenciador de Credenciais do
Windows (keyring), depois a variável de ambiente. Cada usuário do Windows guarda
a própria chave; o .exe nunca carrega chave nenhuma.

Regras:
  - a chave é lida na hora do uso e NUNCA é gravada em os.environ
  - a chave nunca vai para log nem para resposta HTTP (só os 4 últimos caracteres)
  - fora do modo desktop o cofre nunca é consultado (CI/servidor/suíte não tocam
    o Credential Manager de ninguém)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("motor_conect.chave_anthropic")

ENV_VAR = "ANTHROPIC_API_KEY"
DESKTOP_FLAG_ENV = "MOTOR_CONECT_DESKTOP"
KEYRING_SERVICE = "MotorTributario"
KEYRING_USERNAME = ENV_VAR

PREFIXO = "sk-ant-"
TAMANHO_MIN = 20
TAMANHO_MAX = 300

ORIGEM_COFRE = "cofre_windows"
ORIGEM_AMBIENTE = "ambiente"


class CofreIndisponivel(RuntimeError):
    """keyring ausente/sem backend, ou fora do modo desktop."""


class ChaveInvalida(ValueError):
    """Formato não parece chave da Anthropic. Mensagem nunca inclui a chave."""


def modo_desktop() -> bool:
    return os.environ.get(DESKTOP_FLAG_ENV) == "1"


def _backend() -> Optional[Any]:
    """Módulo `keyring` (ou None se não instalado). Testes trocam esta função."""
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def nome_backend() -> Optional[str]:
    """Classe do backend do keyring (ex.: 'WinVaultKeyring'). Não lê nenhuma credencial."""
    kr = _backend()
    if kr is None:
        return None
    try:
        return type(kr.get_keyring()).__name__
    except Exception:  # noqa: BLE001
        return None


def _ler_cofre() -> Optional[str]:
    if not modo_desktop():
        return None
    kr = _backend()
    if kr is None:
        return None
    try:
        return kr.get_password(KEYRING_SERVICE, KEYRING_USERNAME) or None
    except Exception as exc:  # noqa: BLE001 — cofre com problema = sem chave, nunca derruba
        logger.warning("Cofre de credenciais indisponível: %s", type(exc).__name__)
        return None


def _resolver() -> tuple[Optional[str], Optional[str]]:
    chave = _ler_cofre()
    if chave:
        return chave, ORIGEM_COFRE
    chave = os.environ.get(ENV_VAR) or None
    if chave:
        return chave, ORIGEM_AMBIENTE
    return None, None


def obter_chave_anthropic() -> Optional[str]:
    """Chave a usar agora (desktop: cofre → ambiente; resto: ambiente)."""
    return _resolver()[0]


def status_chave() -> dict:
    """Só metadados: nunca a chave."""
    chave, origem = _resolver()
    return {
        "configurada": chave is not None,
        "origem": origem,
        "final": chave[-4:] if chave and len(chave) >= TAMANHO_MIN else None,
        "editavel": modo_desktop() and _backend() is not None,
    }


def validar_formato(chave: str) -> str:
    chave = (chave or "").strip()
    if not chave.startswith(PREFIXO) or not (TAMANHO_MIN <= len(chave) <= TAMANHO_MAX):
        raise ChaveInvalida("Formato inválido: a chave da Anthropic começa com 'sk-ant-'.")
    if any(c.isspace() for c in chave):
        raise ChaveInvalida("Formato inválido: a chave não pode ter espaços.")
    return chave


def _backend_editavel() -> Any:
    if not modo_desktop():
        raise CofreIndisponivel("Cofre de credenciais só existe no app desktop.")
    kr = _backend()
    if kr is None:
        raise CofreIndisponivel("Pacote keyring não instalado.")
    return kr


def salvar_chave_anthropic(chave: str) -> None:
    chave = validar_formato(chave)
    kr = _backend_editavel()
    kr.set_password(KEYRING_SERVICE, KEYRING_USERNAME, chave)
    logger.info("Chave da Anthropic salva no cofre do Windows (final ...%s)", chave[-4:])


def apagar_chave_anthropic() -> bool:
    """True se havia chave no cofre."""
    kr = _backend_editavel()
    if not kr.get_password(KEYRING_SERVICE, KEYRING_USERNAME):
        return False
    kr.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    logger.info("Chave da Anthropic removida do cofre do Windows")
    return True
