# -*- coding: utf-8 -*-
"""
storage_cifrado.py — Storage cifrado AES-256-GCM para documentos do cliente.
Simplificado: remove overengineering de AWS e shredding de disco (Phase 1).
"""

import hashlib
import logging
import os
import secrets
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger("motor_conect.storage_cifrado")

NONCE_BYTES = 12
KEY_BYTES = 32
HASH_TRUNCATE = 16

STORAGE_ROOT = Path(
    os.environ.get(
        "MOTOR_CONECT_STORAGE_DIR",
        str(Path(__file__).resolve().parent.parent / "data" / "auditoria"),
    )
)

class StorageCifradoError(Exception): """Erro genérico."""
class MasterKeyAusente(StorageCifradoError): """Master key não encontrada."""
class IntegridadeViolada(StorageCifradoError): """Falha na integridade (AES-GCM tag)."""

def _master_key() -> bytes:
    """Lê master key da env var MOTOR_CONECT_MASTER_KEY. Zero fallback — falha ruidosa."""
    key_hex = os.environ.get("MOTOR_CONECT_MASTER_KEY")
    if not key_hex:
        raise MasterKeyAusente(
            "MOTOR_CONECT_MASTER_KEY não definida. "
            "Defina a variável de ambiente antes de usar o storage cifrado."
        )
    try:
        key = bytes.fromhex(key_hex)
    except ValueError:
        key = key_hex.encode("utf-8")
    if len(key) < 32:
        raise MasterKeyAusente(
            f"MOTOR_CONECT_MASTER_KEY muito curta ({len(key)} bytes). Mínimo: 32 bytes (64 hex chars)."
        )
    return key[:32]

def _derivar_chave_cnpj(cnpj: str) -> bytes:
    cnpj_norm = "".join(c for c in cnpj if c.isdigit())
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=cnpj_norm.encode("utf-8"),
        info=b"motor-conect-auditoria-documental-v1",
    )
    return hkdf.derive(_master_key())

def anonimizar_cnpj(cnpj: str) -> str:
    cnpj_norm = "".join(c for c in cnpj if c.isdigit())
    return hashlib.sha256(cnpj_norm.encode("utf-8")).hexdigest()[:HASH_TRUNCATE]

def hash_documento(plaintext: bytes) -> str:
    return hashlib.sha256(plaintext).hexdigest()

def _path_para(cnpj: str, hash_completo: str) -> Path:
    return STORAGE_ROOT / anonimizar_cnpj(cnpj) / f"{hash_completo[:HASH_TRUNCATE]}.bin"

def cifrar_e_persistir(plaintext: bytes, cnpj: str) -> tuple[str, Path]:
    if not plaintext:
        raise StorageCifradoError("plaintext não pode ser vazio.")
    cnpj_digits = "".join(c for c in cnpj if c.isdigit())
    if len(cnpj_digits) != 14:
        raise StorageCifradoError(f"CNPJ inválido: '{cnpj}' — esperado 14 dígitos.")
    hash_completo = hash_documento(plaintext)
    destino = _path_para(cnpj, hash_completo)

    if destino.exists():
        return hash_completo, destino

    chave = _derivar_chave_cnpj(cnpj)
    aesgcm = AESGCM(chave)
    nonce = secrets.token_bytes(NONCE_BYTES)
    aad = hash_completo.encode("ascii")
    ciphertext = aesgcm.encrypt(nonce, plaintext, aad)

    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(nonce + ciphertext)
    return hash_completo, destino

def decifrar(path: Path, cnpj: str, hash_esperado: str) -> bytes:
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    blob = path.read_bytes()
    nonce = blob[:NONCE_BYTES]
    ciphertext = blob[NONCE_BYTES:]
    chave = _derivar_chave_cnpj(cnpj)
    aesgcm = AESGCM(chave)
    if not hash_esperado:
        raise StorageCifradoError("hash_esperado é obrigatório para decifrar.")
    aad = hash_esperado.encode("ascii")

    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, aad)
    except InvalidTag:
        raise IntegridadeViolada("Falha na autenticação do arquivo.")

    if hashlib.sha256(plaintext).hexdigest() != hash_esperado:
        raise IntegridadeViolada("Hash do conteúdo não confere.")

    return plaintext

def purge(cnpj: str, hash_completo: str) -> bool:
    """Remove o arquivo do disco (simplificado, sem shredding)."""
    path = _path_para(cnpj, hash_completo)
    if not path.exists():
        return False
    path.unlink()
    try:
        path.parent.rmdir()
    except OSError:
        pass
    return True

def existe(cnpj: str, hash_completo: str) -> bool:
    """Verifica se um documento já existe no storage."""
    return _path_para(cnpj, hash_completo).exists()
