"""
test_storage_cifrado.py — Trava o módulo de cifra/storage AES-256-GCM.

Cobre cifragem, decifragem, integridade, isolamento entre clientes,
purge LGPD e edge cases (master key ausente, CNPJ inválido).
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Master key e diretório de testes precisam estar setados ANTES de importar o módulo,
# senão STORAGE_ROOT vai apontar pro diretório real.
os.environ.setdefault(
    "MOTOR_CONECT_MASTER_KEY",
    "0" * 64,  # 32 bytes hex = 64 chars; 0x00 * 32 só pra testes
)

import storage_cifrado  # noqa: E402
from storage_cifrado import (  # noqa: E402
    IntegridadeViolada,
    MasterKeyAusente,
    StorageCifradoError,
    anonimizar_cnpj,
    cifrar_e_persistir,
    decifrar,
    existe,
    hash_documento,
    purge,
)


CNPJ_A = "54657895000160"  # CANAVEZI fictício
CNPJ_B = "08172834000100"  # CONFI_AR fictício
PDF_FAKE_A = b"%PDF-1.4\n%fakedoc-A\n" + b"x" * 1024
PDF_FAKE_B = b"%PDF-1.4\n%fakedoc-B\n" + b"y" * 2048


@pytest.fixture(autouse=True)
def storage_isolado(tmp_path, monkeypatch):
    """Isola cada teste em pasta tmp própria, sem tocar storage real."""
    monkeypatch.setattr(storage_cifrado, "STORAGE_ROOT", tmp_path / "auditoria")
    yield tmp_path / "auditoria"


# ── Hash determinístico ─────────────────────────────────────────────────────


def test_hash_documento_deterministico():
    h1 = hash_documento(PDF_FAKE_A)
    h2 = hash_documento(PDF_FAKE_A)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_hash_documento_diferente_para_arquivos_diferentes():
    assert hash_documento(PDF_FAKE_A) != hash_documento(PDF_FAKE_B)


def test_hash_bate_com_sha256_padrao():
    assert hash_documento(PDF_FAKE_A) == hashlib.sha256(PDF_FAKE_A).hexdigest()


# ── Anonimização do CNPJ ────────────────────────────────────────────────────


def test_anonimizar_cnpj_irreversivel_e_curto():
    anon = anonimizar_cnpj(CNPJ_A)
    assert len(anon) == 16
    assert CNPJ_A not in anon
    assert all(c in "0123456789abcdef" for c in anon)


def test_anonimizar_cnpj_deterministico():
    assert anonimizar_cnpj(CNPJ_A) == anonimizar_cnpj(CNPJ_A)


def test_anonimizar_cnpj_normaliza_formatacao():
    """CNPJ formatado e cru devem produzir o mesmo hash."""
    formatado = "54.657.895/0001-60"
    cru = "54657895000160"
    assert anonimizar_cnpj(formatado) == anonimizar_cnpj(cru)


def test_anonimizar_cnpjs_diferentes_resultam_em_pastas_diferentes():
    assert anonimizar_cnpj(CNPJ_A) != anonimizar_cnpj(CNPJ_B)


# ── Round-trip cifrar → decifrar ────────────────────────────────────────────


def test_cifrar_e_decifrar_round_trip():
    h, path = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    assert path.exists()
    recuperado = decifrar(path, CNPJ_A, hash_esperado=h)
    assert recuperado == PDF_FAKE_A


def test_arquivo_em_disco_nao_e_o_plaintext():
    """Garantia básica de que cifra está acontecendo."""
    h, path = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    blob = path.read_bytes()
    assert PDF_FAKE_A not in blob  # plaintext NÃO aparece no disco
    assert len(blob) >= len(PDF_FAKE_A) + 12 + 16  # nonce + tag


def test_cifrar_idempotente_para_mesmo_arquivo():
    """Cifrar o mesmo arquivo 2x não duplica nem corrompe."""
    h1, path1 = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    h2, path2 = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    assert h1 == h2
    assert path1 == path2
    # E o conteúdo continua decodificável
    assert decifrar(path2, CNPJ_A, hash_esperado=h2) == PDF_FAKE_A


# ── Isolamento entre clientes ───────────────────────────────────────────────


def test_decifrar_com_cnpj_errado_falha():
    """Cliente A não decifra arquivo do cliente B (chave HKDF é por CNPJ)."""
    h, path = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    with pytest.raises(IntegridadeViolada):
        decifrar(path, CNPJ_B, hash_esperado=h)


def test_arquivos_de_clientes_diferentes_em_pastas_diferentes():
    _, path_a = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    _, path_b = cifrar_e_persistir(PDF_FAKE_B, CNPJ_B)
    assert path_a.parent != path_b.parent
    assert anonimizar_cnpj(CNPJ_A) in str(path_a)
    assert anonimizar_cnpj(CNPJ_B) in str(path_b)


def test_mesmo_arquivo_2_clientes_2_paths_distintos():
    """O mesmo PDF subido por 2 clientes vira 2 arquivos cifrados separados."""
    h_a, path_a = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    h_b, path_b = cifrar_e_persistir(PDF_FAKE_A, CNPJ_B)
    assert h_a == h_b  # hash do plaintext é o mesmo
    assert path_a != path_b  # mas as pastas são distintas
    assert decifrar(path_a, CNPJ_A, hash_esperado=h_a) == PDF_FAKE_A
    assert decifrar(path_b, CNPJ_B, hash_esperado=h_b) == PDF_FAKE_A


# ── Integridade (auth tag) ──────────────────────────────────────────────────


def test_arquivo_adulterado_falha_decifragem():
    h, path = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    blob = bytearray(path.read_bytes())
    blob[20] ^= 0xFF  # flip um byte no meio do ciphertext
    path.write_bytes(bytes(blob))
    with pytest.raises(IntegridadeViolada):
        decifrar(path, CNPJ_A, hash_esperado=h)


def test_hash_esperado_errado_falha():
    h, path = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    fake_hash = "0" * 64
    with pytest.raises(IntegridadeViolada):
        decifrar(path, CNPJ_A, hash_esperado=fake_hash)


def test_decifrar_sem_hash_levanta():
    """Modo estrito: decifrar exige hash esperado pra validação cruzada."""
    h, path = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    with pytest.raises(StorageCifradoError):
        decifrar(path, CNPJ_A, hash_esperado=None)


def test_arquivo_inexistente_levanta_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        decifrar(tmp_path / "naoexiste.bin", CNPJ_A, hash_esperado="x" * 64)


# ── Existência ──────────────────────────────────────────────────────────────


def test_existe_retorna_true_apos_persistir():
    h, _ = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    assert existe(CNPJ_A, h) is True


def test_existe_retorna_false_quando_nao_persistiu():
    h = hash_documento(PDF_FAKE_A)
    assert existe(CNPJ_A, h) is False


# ── Purge LGPD Art. 16 ──────────────────────────────────────────────────────


def test_purge_remove_arquivo():
    h, path = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    assert path.exists()
    assert purge(CNPJ_A, h) is True
    assert not path.exists()


def test_purge_arquivo_inexistente_retorna_false():
    h = hash_documento(PDF_FAKE_A)
    assert purge(CNPJ_A, h) is False


def test_purge_sobrescreve_antes_de_unlink():
    """
    Defesa contra recuperação de setor: o purge sobrescreve com aleatório
    antes de unlink. Como o arquivo é deletado, não dá pra inspecionar
    diretamente — mas garantimos que purge() não falha em cima de FS válido.
    """
    h, path = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    tamanho_antes = path.stat().st_size
    assert tamanho_antes > 0
    assert purge(CNPJ_A, h) is True


def test_purge_remove_pasta_vazia():
    h, path = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    pasta = path.parent
    assert pasta.exists()
    purge(CNPJ_A, h)
    assert not pasta.exists()


def test_purge_preserva_pasta_se_outros_arquivos_existem():
    h_a, path_a = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    h_b, path_b = cifrar_e_persistir(PDF_FAKE_B, CNPJ_A)  # mesmo cliente
    assert path_a.parent == path_b.parent
    purge(CNPJ_A, h_a)
    assert path_b.parent.exists()
    assert path_b.exists()


# ── Erros de configuração ───────────────────────────────────────────────────


def test_master_key_ausente_levanta(monkeypatch):
    monkeypatch.delenv("MOTOR_CONECT_MASTER_KEY", raising=False)
    with pytest.raises(MasterKeyAusente):
        cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)


def test_master_key_curta_levanta(monkeypatch):
    monkeypatch.setenv("MOTOR_CONECT_MASTER_KEY", "abc")  # 3 bytes, muito pouco
    with pytest.raises(MasterKeyAusente):
        cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)


def test_cnpj_invalido_levanta():
    with pytest.raises(StorageCifradoError):
        cifrar_e_persistir(PDF_FAKE_A, "123")


def test_plaintext_vazio_levanta():
    with pytest.raises(StorageCifradoError):
        cifrar_e_persistir(b"", CNPJ_A)


# ── PII protection ──────────────────────────────────────────────────────────


def test_path_nao_contem_cnpj_em_claro():
    """LGPD: nenhum CNPJ raw deve aparecer no caminho do arquivo."""
    _, path = cifrar_e_persistir(PDF_FAKE_A, CNPJ_A)
    path_str = str(path)
    assert CNPJ_A not in path_str
    assert "54.657.895" not in path_str
    assert "/0001-60" not in path_str
