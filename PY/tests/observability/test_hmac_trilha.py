# -*- coding: utf-8 -*-
"""
test_hmac_trilha.py — Assinatura HMAC-SHA256 dos passos da trilha.

Fecha o vetor "trilha adulterada": qualquer mutação de campo deve
invalidar a assinatura.
"""
from __future__ import annotations

import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from observability import hmac_trilha  # noqa: E402


HEX_KEY = "a" * 64  # 32 bytes em hex


@pytest.fixture(autouse=True)
def _master_key_env(monkeypatch):
    """Fixa master key previsível e reseta cache do HMAC."""
    monkeypatch.setenv("MOTOR_CONECT_MASTER_KEY", HEX_KEY)
    hmac_trilha.reset_cache()
    yield
    hmac_trilha.reset_cache()


def _passo_exemplo() -> dict:
    return {
        "tipo": "CALCULO",
        "id": "FASE2_RBT12",
        "titulo": "Receita Bruta 12 meses",
        "formula": "Base [1000000] - Deduções [0] * Alíquota [0.06] = 60000",
        "memoria": {
            "base": "1000000",
            "deducoes": "0",
            "aliquota": "0.06",
            "valor_final": "60000",
        },
        "amparo_legal": "LC 123/2006, Art. 18",
        "timestamp": "2026-03-29T02:45:30.123456",
    }


def test_assinar_passo_adiciona_campo_hmac():
    passo = _passo_exemplo()
    assert "hmac" not in passo

    resultado = hmac_trilha.assinar_passo(passo)

    assert resultado is passo  # mutação in-place
    assert "hmac" in passo
    assert len(passo["hmac"]) == 64  # sha256 hex
    assert all(c in "0123456789abcdef" for c in passo["hmac"])


def test_verificar_passo_integro_retorna_true():
    passo = hmac_trilha.assinar_passo(_passo_exemplo())
    assert hmac_trilha.verificar_passo(passo) is True


def test_mutacao_de_memoria_invalida_hmac():
    passo = hmac_trilha.assinar_passo(_passo_exemplo())
    assert hmac_trilha.verificar_passo(passo) is True

    # Auditor mal-intencionado aumenta o valor_final
    passo["memoria"]["valor_final"] = "999999"

    assert hmac_trilha.verificar_passo(passo) is False


def test_mutacao_de_amparo_legal_invalida_hmac():
    passo = hmac_trilha.assinar_passo(_passo_exemplo())
    passo["amparo_legal"] = "Lei inventada 99/9999"

    assert hmac_trilha.verificar_passo(passo) is False


def test_assinatura_idempotente_mesmo_input_mesma_saida():
    p1 = hmac_trilha.assinar_passo(_passo_exemplo())
    p2 = hmac_trilha.assinar_passo(_passo_exemplo())
    assert p1["hmac"] == p2["hmac"]


def test_reassinar_passo_com_hmac_existente_gera_mesma_assinatura():
    """Reassinar um passo já assinado não deve mudar o HMAC."""
    passo = hmac_trilha.assinar_passo(_passo_exemplo())
    hmac_original = passo["hmac"]

    hmac_trilha.assinar_passo(passo)

    assert passo["hmac"] == hmac_original


def test_assinar_trilha_assina_todos_os_passos():
    trilha = [_passo_exemplo() for _ in range(3)]
    hmac_trilha.assinar_trilha(trilha)

    for passo in trilha:
        assert "hmac" in passo
        assert hmac_trilha.verificar_passo(passo) is True


def test_verificar_trilha_integra_retorna_lista_vazia():
    trilha = [_passo_exemplo() for _ in range(3)]
    # Dá IDs distintos pra cada passo receber HMAC diferente
    for i, p in enumerate(trilha):
        p["id"] = f"PASSO_{i}"
    hmac_trilha.assinar_trilha(trilha)

    indices_invalidos = hmac_trilha.verificar_trilha(trilha)
    assert indices_invalidos == []


def test_verificar_trilha_detecta_indice_mutado():
    trilha = [_passo_exemplo() for _ in range(3)]
    for i, p in enumerate(trilha):
        p["id"] = f"PASSO_{i}"
    hmac_trilha.assinar_trilha(trilha)

    # Audita mutação no passo do meio
    trilha[1]["memoria"]["valor_final"] = "HACKED"

    indices_invalidos = hmac_trilha.verificar_trilha(trilha)
    assert indices_invalidos == [1]


def test_passo_sem_hmac_falha_verificacao():
    passo = _passo_exemplo()
    assert hmac_trilha.verificar_passo(passo) is False


def test_chave_diferente_por_master_key(monkeypatch):
    """Trocar master key deve gerar chave HMAC diferente."""
    passo1 = hmac_trilha.assinar_passo(_passo_exemplo())
    hmac1 = passo1["hmac"]

    # Troca master key
    monkeypatch.setenv("MOTOR_CONECT_MASTER_KEY", "b" * 64)
    hmac_trilha.reset_cache()

    passo2 = hmac_trilha.assinar_passo(_passo_exemplo())
    hmac2 = passo2["hmac"]

    assert hmac1 != hmac2
