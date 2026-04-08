"""
hmac_trilha.py — Assinatura HMAC-SHA256 dos passos da trilha de auditoria.

Fecha o vetor "trilha adulterada": um auditor ou falha em disco não pode
mutar um passo sem invalidar a assinatura. Fiscalização exige prova de
integridade (CTN Art. 142 — lançamento tributário deve ser auditável).

ARQUITETURA:
    - Chave HMAC derivada de MOTOR_CONECT_MASTER_KEY via HKDF-SHA256
      com salt=b"motor-conect-trilha-hmac-v1" (distinta da chave AES-GCM
      dos documentos — comprometer uma não compromete a outra)
    - JSON canônico (keys ordenadas, sem o próprio campo 'hmac') como entrada
    - HMAC-SHA256 hex (64 chars) anexado ao campo 'hmac' do passo
    - Verificação recalcula e compara — mutação de qualquer campo invalida
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from storage_cifrado import _master_key

# Salt distinto da cifragem de documentos (storage_cifrado usa salt=cnpj).
# Se alguém recuperar a chave HMAC da trilha, não consegue decifrar PDFs.
_HKDF_SALT = b"motor-conect-trilha-hmac-v1"
_HKDF_INFO = b"hmac-sha256-trilha-passo"
_KEY_BYTES = 32

# Cache em memória da chave derivada (evita rederivar a cada passo)
_cached_key: bytes | None = None


def hmac_chave() -> bytes:
    """
    Deriva a chave HMAC da master key via HKDF-SHA256.

    Cacheado em memória após primeira chamada. Reset via reset_cache()
    em testes que trocam MOTOR_CONECT_MASTER_KEY em runtime.
    """
    global _cached_key
    if _cached_key is None:
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=_KEY_BYTES,
            salt=_HKDF_SALT,
            info=_HKDF_INFO,
        )
        _cached_key = hkdf.derive(_master_key())
    return _cached_key


def reset_cache() -> None:
    """Limpa cache da chave derivada. Usar em testes."""
    global _cached_key
    _cached_key = None


def _canonicalizar(passo: dict[str, Any]) -> bytes:
    """
    Serializa o passo em JSON canônico (keys ordenadas, sem whitespace
    supérfluo, sem o campo 'hmac' se presente).

    Canonical JSON é crítico: qualquer variação de whitespace, ordem de
    chaves ou representação de floats mudaria a assinatura.
    """
    passo_sem_hmac = {k: v for k, v in passo.items() if k != "hmac"}
    return json.dumps(
        passo_sem_hmac,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,  # Decimal, datetime, etc. viram str
    ).encode("utf-8")


def assinar_passo(passo: dict[str, Any]) -> dict[str, Any]:
    """
    Adiciona campo 'hmac' ao passo (in-place) e retorna o mesmo dict.

    Idempotente: chamar 2x com o mesmo passo produz a mesma assinatura.
    Se o passo já tinha 'hmac' de uma versão anterior, ele é recalculado.
    """
    canonico = _canonicalizar(passo)
    assinatura = hmac.new(hmac_chave(), canonico, hashlib.sha256).hexdigest()
    passo["hmac"] = assinatura
    return passo


def assinar_trilha(trilha: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Assina todos os passos da trilha in-place.

    Chame UMA vez no final de cada entry point do motor — não precisa
    interceptar cada append individual.
    """
    for passo in trilha:
        assinar_passo(passo)
    return trilha


def verificar_passo(passo: dict[str, Any]) -> bool:
    """
    True se o HMAC do passo é válido.

    Retorna False se:
    - campo 'hmac' ausente
    - HMAC recalculado difere do armazenado
    """
    armazenado = passo.get("hmac")
    if not armazenado:
        return False
    canonico = _canonicalizar(passo)
    esperado = hmac.new(hmac_chave(), canonico, hashlib.sha256).hexdigest()
    return hmac.compare_digest(armazenado, esperado)


def verificar_trilha(trilha: list[dict[str, Any]]) -> list[int]:
    """
    Verifica toda a trilha. Retorna lista de índices com HMAC inválido.

    Lista vazia = trilha 100% íntegra.
    Usado pelo endpoint /auditoria/prova/cnpj/{digitos} para incluir
    status de integridade no HASHES.txt do dossiê ZIP.
    """
    return [i for i, passo in enumerate(trilha) if not verificar_passo(passo)]
