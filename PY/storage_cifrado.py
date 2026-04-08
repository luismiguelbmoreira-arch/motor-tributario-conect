"""
storage_cifrado.py — Storage cifrado AES-256-GCM para documentos do cliente.

Motor Tributário Conect — Camada de Auditoria Documental (LGPD + CTN Art. 173).

ARQUITETURA:
  - AES-256-GCM (autenticação + confidencialidade integradas)
  - HKDF-SHA256 derivando chave por CNPJ a partir de master key
  - Master key em variável de ambiente (NUNCA persistida em DB ou repo)
  - Cada arquivo tem nonce de 12 bytes único, prepended ao ciphertext
  - Auth tag de 16 bytes anexado pelo AESGCM (parte do ciphertext)
  - Hash SHA-256 do plaintext calculado ANTES de cifrar (para auditoria)

LAYOUT EM DISCO:
  storage/auditoria/{cnpj_anonimizado}/{hash_curto}.bin

  cnpj_anonimizado = SHA-256(cnpj)[:16]   (16 chars hex, irreversível)
  hash_curto       = SHA-256(plaintext)[:16]
  conteudo         = nonce_12b || ciphertext_com_auth_tag

LGPD (Lei 13.709/2018):
  - Art. 46: medidas técnicas de segurança (cifra forte, controle acesso)
  - Art. 37: registro de operações (acesso loggado em log estruturado)
  - Art. 16: descarte após finalidade (purge() apaga arquivo + zera bytes)

CTN Art. 173: prazo decadencial 5 anos. Funções de purge respeitam isso
indiretamente — quem decide a política de retenção é o caller (database.py).
"""
from __future__ import annotations

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


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

NONCE_BYTES = 12  # AES-GCM padrão (NIST SP 800-38D)
KEY_BYTES = 32    # AES-256
HASH_TRUNCATE = 16  # 16 chars hex = 64 bits de entropia, suficiente p/ filename

# Diretório raiz do storage. Pode ser sobrescrito via env var em testes.
STORAGE_ROOT = Path(
    os.environ.get(
        "MOTOR_CONECT_STORAGE_DIR",
        str(Path(__file__).resolve().parent.parent / "data" / "auditoria"),
    )
)


class StorageCifradoError(Exception):
    """Erro genérico do módulo de storage cifrado."""


class MasterKeyAusente(StorageCifradoError):
    """MOTOR_CONECT_MASTER_KEY não definida no ambiente."""


class IntegridadeViolada(StorageCifradoError):
    """Auth tag do AES-GCM não bate — arquivo corrompido ou adulterado."""


# ─────────────────────────────────────────────────────────────────────────────
# DERIVAÇÃO DE CHAVE
# ─────────────────────────────────────────────────────────────────────────────

def _master_key() -> bytes:
    """
    Lê a master key do ambiente. Levanta MasterKeyAusente se não definida.

    A master key DEVE ter pelo menos 32 bytes de entropia (gerar via
    `python -c 'import secrets; print(secrets.token_hex(32))'` e colocar
    em PY/.env como MOTOR_CONECT_MASTER_KEY=<hex>).
    """
    raw = os.environ.get("MOTOR_CONECT_MASTER_KEY")
    if not raw:
        raise MasterKeyAusente(
            "MOTOR_CONECT_MASTER_KEY não definida. Gere uma com "
            "`python -c 'import secrets; print(secrets.token_hex(32))'` "
            "e adicione em PY/.env."
        )
    # Aceita hex (preferido) ou bytes literais
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        key = raw.encode("utf-8")
    if len(key) < 32:
        raise MasterKeyAusente(
            f"MOTOR_CONECT_MASTER_KEY tem apenas {len(key)} bytes — exige ≥ 32."
        )
    return key[:32]  # trunca se mais longa


def _derivar_chave_cnpj(cnpj: str) -> bytes:
    """
    HKDF-SHA256(master_key, salt=cnpj) → 32 bytes.

    O CNPJ funciona como salt — cada cliente tem chave única, mesmo
    compartilhando a master key. Comprometer um cliente NÃO compromete
    os outros (forward secrecy entre clientes).
    """
    cnpj_normalizado = "".join(c for c in cnpj if c.isdigit())
    if len(cnpj_normalizado) != 14:
        raise StorageCifradoError(
            f"CNPJ inválido para derivação de chave: '{cnpj}'"
        )
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=cnpj_normalizado.encode("utf-8"),
        info=b"motor-conect-auditoria-documental-v1",
    )
    return hkdf.derive(_master_key())


def anonimizar_cnpj(cnpj: str) -> str:
    """
    Retorna SHA-256(cnpj)[:16] para usar como nome de pasta.

    Irreversível: não dá para descobrir o CNPJ original a partir do hash.
    Determinístico: o mesmo CNPJ sempre gera o mesmo hash, então busca
    por cliente continua funcionando.
    """
    cnpj_normalizado = "".join(c for c in cnpj if c.isdigit())
    digest = hashlib.sha256(cnpj_normalizado.encode("utf-8")).hexdigest()
    return digest[:HASH_TRUNCATE]


# ─────────────────────────────────────────────────────────────────────────────
# HASH DO PLAINTEXT (para identificação e integridade)
# ─────────────────────────────────────────────────────────────────────────────

def hash_documento(plaintext: bytes) -> str:
    """
    Retorna SHA-256 hex completo (64 chars) do conteúdo.

    Este é o ID canônico do documento na tabela auditoria_documentos —
    se o mesmo arquivo for enviado 2 vezes, produz o mesmo hash e o
    sistema pode evitar duplicata.
    """
    return hashlib.sha256(plaintext).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# CIFRAGEM E ARMAZENAMENTO
# ─────────────────────────────────────────────────────────────────────────────

def _path_para(cnpj: str, hash_completo: str) -> Path:
    """Retorna o Path absoluto onde o arquivo cifrado deve ficar."""
    cnpj_anon = anonimizar_cnpj(cnpj)
    hash_curto = hash_completo[:HASH_TRUNCATE]
    return STORAGE_ROOT / cnpj_anon / f"{hash_curto}.bin"


def cifrar_e_persistir(plaintext: bytes, cnpj: str) -> tuple[str, Path]:
    """
    Cifra `plaintext` e grava no storage.

    Args:
        plaintext: bytes do PDF original (ou qualquer arquivo).
        cnpj: CNPJ do cliente, usado para derivar a chave e o nome da pasta.

    Returns:
        (hash_completo_sha256, path_absoluto_do_arquivo_cifrado)

    Raises:
        MasterKeyAusente: se MOTOR_CONECT_MASTER_KEY não estiver no env.
        StorageCifradoError: se CNPJ inválido ou erro de I/O.
    """
    if not plaintext:
        raise StorageCifradoError("plaintext vazio.")

    hash_completo = hash_documento(plaintext)
    destino = _path_para(cnpj, hash_completo)

    # Idempotente: se já existe e o conteúdo bate, não regrava
    if destino.exists():
        try:
            recuperado = decifrar(destino, cnpj)
            if hashlib.sha256(recuperado).hexdigest() == hash_completo:
                logger.info(
                    "Documento ja persistido | hash=%s... | path=%s",
                    hash_completo[:16], destino.name,
                )
                return hash_completo, destino
        except Exception:
            # Arquivo corrompido — vamos sobrescrever
            logger.warning("Arquivo existente corrompido, sobrescrevendo: %s", destino.name)

    chave = _derivar_chave_cnpj(cnpj)
    aesgcm = AESGCM(chave)
    nonce = secrets.token_bytes(NONCE_BYTES)

    # Associated data: hash do plaintext (impede swap de arquivos entre clientes)
    aad = hash_completo.encode("ascii")
    ciphertext = aesgcm.encrypt(nonce, plaintext, aad)

    destino.parent.mkdir(parents=True, exist_ok=True)
    # Escreve atomicamente: tmp → rename
    tmp_path = destino.with_suffix(".tmp")
    tmp_path.write_bytes(nonce + ciphertext)
    tmp_path.replace(destino)

    logger.info(
        "Documento cifrado e persistido | hash=%s... | bytes=%d | path=%s",
        hash_completo[:16], len(plaintext), destino.name,
    )
    return hash_completo, destino


def decifrar(path: Path, cnpj: str, hash_esperado: Optional[str] = None) -> bytes:
    """
    Lê e decifra um arquivo do storage.

    Args:
        path: caminho absoluto retornado por cifrar_e_persistir().
        cnpj: CNPJ do cliente (precisa ser o mesmo usado na cifragem).
        hash_esperado: SHA-256 esperado do plaintext. Se fornecido, compara
                       após decifragem (defesa em profundidade contra
                       substituição de arquivo no FS).

    Returns:
        plaintext em bytes.

    Raises:
        FileNotFoundError: se path não existe.
        IntegridadeViolada: se auth tag falhar ou hash não bater.
        MasterKeyAusente: se master key não estiver no env.
    """
    if not path.exists():
        raise FileNotFoundError(f"Arquivo cifrado não encontrado: {path}")

    blob = path.read_bytes()
    if len(blob) < NONCE_BYTES + 16:  # nonce + tag mínimo
        raise IntegridadeViolada(f"Arquivo muito pequeno: {len(blob)} bytes")

    nonce = blob[:NONCE_BYTES]
    ciphertext = blob[NONCE_BYTES:]

    chave = _derivar_chave_cnpj(cnpj)
    aesgcm = AESGCM(chave)

    # Se temos hash esperado, usamos como AAD (precisa bater com o que foi cifrado)
    if hash_esperado:
        aad = hash_esperado.encode("ascii")
    else:
        # Sem hash esperado: tentamos decifrar sem AAD primeiro (modo estrito
        # exige hash). Por enquanto, levantamos erro.
        raise StorageCifradoError(
            "decifrar() exige hash_esperado para validar integridade. "
            "Passe o SHA-256 que foi gerado em cifrar_e_persistir()."
        )

    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        logger.error(
            "Auth tag invalido — arquivo corrompido ou chave errada | path=%s",
            path.name,
        )
        raise IntegridadeViolada(
            "Auth tag inválido: arquivo corrompido, chave errada ou CNPJ errado."
        ) from exc

    # Defesa em profundidade: confere hash do plaintext recuperado
    if hashlib.sha256(plaintext).hexdigest() != hash_esperado:
        raise IntegridadeViolada(
            "Hash do plaintext recuperado não bate com o esperado."
        )

    logger.info(
        "Documento decifrado | hash=%s... | bytes=%d",
        hash_esperado[:16], len(plaintext),
    )
    return plaintext


def existe(cnpj: str, hash_completo: str) -> bool:
    """Retorna True se o documento já está armazenado."""
    return _path_para(cnpj, hash_completo).exists()


# ─────────────────────────────────────────────────────────────────────────────
# PURGE (LGPD Art. 16)
# ─────────────────────────────────────────────────────────────────────────────

def purge(cnpj: str, hash_completo: str) -> bool:
    """
    Remove o arquivo cifrado do disco de forma segura.

    Sobrescreve com bytes aleatórios antes de unlink (defesa contra
    recuperação de setores). Não é DoD 3-pass — para SSDs isso já é
    questionável devido ao wear leveling — mas é melhor que unlink puro.

    Returns:
        True se removeu, False se não existia.
    """
    path = _path_para(cnpj, hash_completo)
    if not path.exists():
        return False

    try:
        tamanho = path.stat().st_size
        # Sobrescreve uma vez com bytes aleatórios
        with path.open("r+b") as f:
            f.write(secrets.token_bytes(tamanho))
            f.flush()
            os.fsync(f.fileno())
        path.unlink()
        logger.info(
            "Documento purgado (LGPD Art. 16) | hash=%s... | bytes=%d",
            hash_completo[:16], tamanho,
        )
        # Remove pasta do cliente se ficou vazia
        try:
            path.parent.rmdir()
        except OSError:
            pass  # pasta não vazia, ok
        return True
    except OSError as exc:
        logger.error("Falha ao purgar | path=%s | %s", path.name, exc)
        raise StorageCifradoError(f"Falha ao purgar arquivo: {exc}") from exc
