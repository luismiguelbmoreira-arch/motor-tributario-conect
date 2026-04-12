# -*- coding: utf-8 -*-
"""
test_master_key_fallback.py — Trava a cadeia de fallback da master key.

Ordem de prioridade esperada:
  1. env var MOTOR_CONECT_MASTER_KEY (dev local)
  2. arquivo $MOTOR_CONECT_MASTER_KEY_FILE (override explícito)
  3. arquivo /etc/motor-conect/master.key (Linux deploy)
  4. arquivo %PROGRAMDATA%/motor-conect/master.key (Windows deploy)
  5. AWS Secrets Manager via MOTOR_CONECT_MASTER_KEY_AWS_SECRET
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.storage_cifrado as storage_cifrado  # noqa: E402
from services.storage_cifrado import (  # noqa: E402
    MasterKeyAusente,
    _ler_key_de_arquivo,
    _master_key,
    _validar_e_normalizar_key,
)


HEX_32 = "a" * 64  # 32 bytes em hex
HEX_INVALIDO_CURTO = "ab" * 10  # 10 bytes, menos que 32


@pytest.fixture(autouse=True)
def limpa_env(monkeypatch):
    """Remove qualquer master key do ambiente antes de cada teste."""
    for var in (
        "MOTOR_CONECT_MASTER_KEY",
        "MOTOR_CONECT_MASTER_KEY_FILE",
        "MOTOR_CONECT_MASTER_KEY_AWS_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    # Zera os caminhos padrão para evitar pegar arquivo real do sistema
    monkeypatch.setattr(
        storage_cifrado, "_caminhos_padrao_arquivo", lambda: []
    )
    # Evita poluição cross-test de sys.modules["boto3"] mockado
    _boto3_original = sys.modules.get("boto3")
    yield
    if _boto3_original is None:
        sys.modules.pop("boto3", None)
    else:
        sys.modules["boto3"] = _boto3_original


# ── Validação de formato ───────────────────────────────────────────────────


class TestValidarKey:
    def test_hex_32_bytes_aceito(self):
        key = _validar_e_normalizar_key(HEX_32, "teste")
        assert len(key) == 32

    def test_hex_maior_que_32_truncado(self):
        raw = "a" * 128  # 64 bytes
        key = _validar_e_normalizar_key(raw, "teste")
        assert len(key) == 32

    def test_texto_puro_32_chars_aceito(self):
        """String não-hex também funciona se tiver ≥ 32 bytes."""
        raw = "motor-conect-prod-key-cliente-0001"  # 35 chars
        key = _validar_e_normalizar_key(raw, "teste")
        assert len(key) == 32

    def test_curto_demais_levanta(self):
        with pytest.raises(MasterKeyAusente, match="32"):
            _validar_e_normalizar_key(HEX_INVALIDO_CURTO, "teste")

    def test_vazio_levanta(self):
        with pytest.raises(MasterKeyAusente, match="vazia"):
            _validar_e_normalizar_key("", "teste")

    def test_so_espacos_levanta(self):
        with pytest.raises(MasterKeyAusente, match="vazia"):
            _validar_e_normalizar_key("   \n\t  ", "teste")

    def test_origem_aparece_na_mensagem_de_erro(self):
        with pytest.raises(MasterKeyAusente, match="arquivo /tmp/xyz"):
            _validar_e_normalizar_key("", "arquivo /tmp/xyz")


# ── Fonte 1: env var ───────────────────────────────────────────────────────


class TestFonteEnvVar:
    def test_env_var_valida_funciona(self, monkeypatch):
        monkeypatch.setenv("MOTOR_CONECT_MASTER_KEY", HEX_32)
        assert len(_master_key()) == 32

    def test_env_var_invalida_tenta_proxima_fonte(self, monkeypatch):
        """
        Se env var está presente mas inválida, a fallback chain continua.
        Se não há mais nada, deve levantar listando as tentativas.
        """
        monkeypatch.setenv("MOTOR_CONECT_MASTER_KEY", HEX_INVALIDO_CURTO)
        with pytest.raises(MasterKeyAusente) as exc_info:
            _master_key()
        # A mensagem deve citar a fonte que falhou
        assert "env var" in str(exc_info.value)


# ── Fonte 2: arquivo ───────────────────────────────────────────────────────


class TestFonteArquivo:
    def test_arquivo_por_env_var_file(self, tmp_path, monkeypatch):
        key_file = tmp_path / "master.key"
        key_file.write_text(HEX_32)
        monkeypatch.setenv("MOTOR_CONECT_MASTER_KEY_FILE", str(key_file))
        # Restaura a função real para usar o env var
        import services.storage_cifrado as mod
        monkeypatch.setattr(mod, "_caminhos_padrao_arquivo", lambda: [key_file])
        assert len(_master_key()) == 32

    def test_ler_arquivo_com_newline_trailing(self, tmp_path):
        """Arquivos editados em editores geralmente tem \\n no final."""
        key_file = tmp_path / "master.key"
        key_file.write_text(HEX_32 + "\n\n")
        assert len(_ler_key_de_arquivo(key_file)) == 32

    def test_ler_arquivo_sem_permissao_levanta(self, tmp_path):
        key_file = tmp_path / "inexistente.key"
        with pytest.raises(MasterKeyAusente, match="Nao foi possivel ler"):
            _ler_key_de_arquivo(key_file)

    def test_ler_arquivo_vazio_levanta(self, tmp_path):
        key_file = tmp_path / "vazia.key"
        key_file.write_text("")
        with pytest.raises(MasterKeyAusente, match="vazia"):
            _ler_key_de_arquivo(key_file)

    def test_ler_arquivo_conteudo_invalido_levanta(self, tmp_path):
        key_file = tmp_path / "curta.key"
        key_file.write_text("abc")  # 3 bytes
        with pytest.raises(MasterKeyAusente, match="32"):
            _ler_key_de_arquivo(key_file)


# ── Caminhos padrão ─────────────────────────────────────────────────────────


# Guarda referencia pra funcao real ANTES do autouse monkeypatch-ar
_CAMINHOS_PADRAO_REAL = storage_cifrado._caminhos_padrao_arquivo


class TestCaminhosPadrao:
    """
    Testa a função real _caminhos_padrao_arquivo SEM depender do autouse.
    Guardamos a referência no topo do módulo antes do fixture substituir.
    """

    def test_caminhos_padrao_retorna_lista(self, monkeypatch):
        monkeypatch.delenv("MOTOR_CONECT_MASTER_KEY_FILE", raising=False)
        monkeypatch.delenv("PROGRAMDATA", raising=False)
        paths = _CAMINHOS_PADRAO_REAL()
        assert isinstance(paths, list)

    def test_override_env_var_file_tem_prioridade(self, tmp_path, monkeypatch):
        """MOTOR_CONECT_MASTER_KEY_FILE é o primeiro candidato."""
        key_file = tmp_path / "custom.key"
        key_file.write_text(HEX_32)
        monkeypatch.setenv("MOTOR_CONECT_MASTER_KEY_FILE", str(key_file))
        paths = _CAMINHOS_PADRAO_REAL()
        assert key_file in paths
        assert paths[0] == key_file

    def test_override_inexistente_nao_listado(self, tmp_path, monkeypatch):
        """
        Se o arquivo apontado por MOTOR_CONECT_MASTER_KEY_FILE não existir,
        ele é filtrado (não causa erro).
        """
        fantasma = tmp_path / "nao_existe.key"
        monkeypatch.setenv("MOTOR_CONECT_MASTER_KEY_FILE", str(fantasma))
        paths = _CAMINHOS_PADRAO_REAL()
        assert fantasma not in paths


# ── Fonte 3: AWS Secrets Manager ───────────────────────────────────────────


class TestFonteAWS:
    def test_aws_sem_boto3_mensagem_clara(self, monkeypatch):
        monkeypatch.setenv("MOTOR_CONECT_MASTER_KEY_AWS_SECRET", "motor/master")
        # Bloqueia import do boto3
        import builtins

        orig_import = builtins.__import__

        def fake_import(name, *args, **kw):
            if name == "boto3":
                raise ImportError("No module named 'boto3'")
            return orig_import(name, *args, **kw)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(MasterKeyAusente) as exc_info:
            _master_key()
        assert "boto3" in str(exc_info.value)

    def test_aws_com_boto3_mockado(self, monkeypatch):
        """Simula boto3 com MagicMock devolvendo chave valida."""
        from unittest.mock import MagicMock

        fake_client = MagicMock()
        fake_client.get_secret_value.return_value = {"SecretString": HEX_32}
        fake_boto3 = MagicMock()
        fake_boto3.client.return_value = fake_client

        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        monkeypatch.setenv("MOTOR_CONECT_MASTER_KEY_AWS_SECRET", "motor/master")

        assert len(_master_key()) == 32
        fake_boto3.client.assert_called_once_with("secretsmanager")
        fake_client.get_secret_value.assert_called_once_with(SecretId="motor/master")

    def test_aws_erro_api_cai_para_proxima_tentativa(self, monkeypatch):
        """Se o AWS falhar, levanta listando tentativas."""
        from unittest.mock import MagicMock

        fake_client = MagicMock()
        fake_client.get_secret_value.side_effect = RuntimeError("access denied")
        fake_boto3 = MagicMock()
        fake_boto3.client.return_value = fake_client

        monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
        monkeypatch.setenv("MOTOR_CONECT_MASTER_KEY_AWS_SECRET", "motor/master")

        with pytest.raises(MasterKeyAusente, match="AWS Secrets Manager"):
            _master_key()


# ── Cadeia de fallback completa ────────────────────────────────────────────


class TestCadeiaFallback:
    def test_env_tem_prioridade_sobre_arquivo(self, tmp_path, monkeypatch):
        """Se env var está setada e válida, nem tenta o arquivo."""
        key_file = tmp_path / "master.key"
        key_file.write_text("b" * 64)  # chave diferente no arquivo

        env_hex = "a" * 64  # chave A na env
        monkeypatch.setenv("MOTOR_CONECT_MASTER_KEY", env_hex)
        monkeypatch.setattr(
            storage_cifrado, "_caminhos_padrao_arquivo", lambda: [key_file]
        )

        key = _master_key()
        assert key == bytes.fromhex(env_hex)

    def test_env_vazia_fallback_para_arquivo(self, tmp_path, monkeypatch):
        key_file = tmp_path / "master.key"
        key_file.write_text(HEX_32)

        # Env ausente
        monkeypatch.delenv("MOTOR_CONECT_MASTER_KEY", raising=False)
        monkeypatch.setattr(
            storage_cifrado, "_caminhos_padrao_arquivo", lambda: [key_file]
        )

        assert len(_master_key()) == 32

    def test_nenhuma_fonte_mensagem_explicativa(self, monkeypatch):
        """Sem nada configurado, mensagem de erro deve listar as opções."""
        monkeypatch.delenv("MOTOR_CONECT_MASTER_KEY", raising=False)
        monkeypatch.delenv("MOTOR_CONECT_MASTER_KEY_AWS_SECRET", raising=False)
        monkeypatch.setattr(
            storage_cifrado, "_caminhos_padrao_arquivo", lambda: []
        )

        with pytest.raises(MasterKeyAusente) as exc_info:
            _master_key()
        msg = str(exc_info.value)
        # Deve mencionar as 3 opções
        assert "MOTOR_CONECT_MASTER_KEY" in msg
        assert "master.key" in msg
        assert "AWS" in msg or "AWS_SECRET" in msg

    def test_multipla_tentativas_falhas_listadas(self, tmp_path, monkeypatch):
        """
        Se env var inválida + arquivo inválido + AWS ausente → erro com
        todas as tentativas listadas.
        """
        monkeypatch.setenv("MOTOR_CONECT_MASTER_KEY", "curto")
        key_file = tmp_path / "master.key"
        key_file.write_text("tambem_curto")
        monkeypatch.setattr(
            storage_cifrado, "_caminhos_padrao_arquivo", lambda: [key_file]
        )

        with pytest.raises(MasterKeyAusente) as exc_info:
            _master_key()
        msg = str(exc_info.value)
        assert "env var" in msg
        assert "master.key" in msg or "arquivo" in msg
