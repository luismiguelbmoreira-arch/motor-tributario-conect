"""
test_validadores.py — TDD Fase 1
Testa: validar_cnpj, validar_ncm, validar_uf, validar_cnae

Padrão: Cada caso documentado com a lei/regra que verifica.
Executar: python -m pytest PY/tests/test_validadores.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from validadores import validar_cnpj, validar_ncm, validar_uf, validar_cnae, ValidationResult


# ─────────────────────────────────────────────────────────────────────────────
# CNPJ — Módulo 11
# ─────────────────────────────────────────────────────────────────────────────

class TestValidarCNPJ:

    def test_cnpj_valido_sem_pontuacao(self):
        """CNPJ real válido — deve aceitar."""
        resultado = validar_cnpj("11222333000181")
        assert resultado.ok is True
        assert resultado.errors == []

    def test_cnpj_valido_com_pontuacao(self):
        """CNPJ com máscara XX.XXX.XXX/XXXX-XX — deve aceitar."""
        resultado = validar_cnpj("11.222.333/0001-81")
        assert resultado.ok is True

    def test_cnpj_zerado_rejeitado(self):
        """CNPJ 00000000000000 — todos dígitos iguais — REJEITAR."""
        resultado = validar_cnpj("00000000000000")
        assert resultado.ok is False
        assert len(resultado.errors) > 0

    def test_cnpj_11111111111111_rejeitado(self):
        """CNPJ 11111111111111 — todos dígitos iguais — REJEITAR."""
        resultado = validar_cnpj("11111111111111")
        assert resultado.ok is False

    def test_cnpj_com_menos_digitos(self):
        """CNPJ com 13 dígitos — REJEITAR."""
        resultado = validar_cnpj("1122233300018")
        assert resultado.ok is False
        assert any("14 dígitos" in e or "dígitos" in e for e in resultado.errors)

    def test_cnpj_com_mais_digitos(self):
        """CNPJ com 15 dígitos — REJEITAR."""
        resultado = validar_cnpj("112223330001810")
        assert resultado.ok is False

    def test_cnpj_com_letras(self):
        """CNPJ com letras — REJEITAR."""
        resultado = validar_cnpj("1122233300018X")
        assert resultado.ok is False

    def test_cnpj_vazio(self):
        """CNPJ vazio — REJEITAR."""
        resultado = validar_cnpj("")
        assert resultado.ok is False

    def test_cnpj_none_como_string(self):
        """CNPJ None-like — REJEITAR."""
        resultado = validar_cnpj(None)
        assert resultado.ok is False

    def test_cnpj_digito_verificador_errado(self):
        """CNPJ com dígito verificador inválido — REJEITAR."""
        resultado = validar_cnpj("11222333000199")  # Dígitos finais trocados
        assert resultado.ok is False

    def test_cnpj_retorna_validation_result(self):
        """Deve sempre retornar ValidationResult (nunca raise direto)."""
        resultado = validar_cnpj("invalido")
        assert isinstance(resultado, ValidationResult)


# ─────────────────────────────────────────────────────────────────────────────
# NCM — 8 dígitos
# ─────────────────────────────────────────────────────────────────────────────

class TestValidarNCM:

    def test_ncm_valido_8_digitos(self):
        """NCM 84099190 — Motor de pistão — deve aceitar."""
        assert validar_ncm("84099190").ok is True

    def test_ncm_valido_com_pontuacao(self):
        """NCM com pontos 8409.91.90 — deve aceitar (normaliza pontuação)."""
        assert validar_ncm("8409.91.90").ok is True

    def test_ncm_6_digitos_rejeitado(self):
        """NCM com 6 dígitos — REJEITAR (padrão é 8)."""
        resultado = validar_ncm("840991")
        assert resultado.ok is False
        assert any("8 dígitos" in e for e in resultado.errors)

    def test_ncm_10_digitos_rejeitado(self):
        """NCM com 10 dígitos — REJEITAR."""
        assert validar_ncm("8409919000").ok is False

    def test_ncm_com_letras_rejeitado(self):
        """NCM com letras — REJEITAR."""
        assert validar_ncm("8409919X").ok is False

    def test_ncm_vazio_rejeitado(self):
        """NCM vazio — REJEITAR."""
        assert validar_ncm("").ok is False

    def test_ncm_produtos_comuns_aceitos(self):
        """NCMs comuns de Sorocaba — todos devem aceitar."""
        ncms_sorocaba = [
            "84099190",  # Motor de combustão interna
            "87089990",  # Peças para veículos
            "39269090",  # Artefatos de plástico
            "73269090",  # Artefatos de ferro/aço
            "84831040",  # Engrenagens e polias
        ]
        for ncm in ncms_sorocaba:
            assert validar_ncm(ncm).ok is True, f"NCM {ncm} deveria ser aceito"

    def test_ncm_retorna_validation_result(self):
        resultado = validar_ncm("invalido")
        assert isinstance(resultado, ValidationResult)


# ─────────────────────────────────────────────────────────────────────────────
# UF — 27 estados brasileiros
# ─────────────────────────────────────────────────────────────────────────────

class TestValidarUF:

    def test_sp_valido(self):
        """SP — São Paulo — deve aceitar."""
        assert validar_uf("SP").ok is True

    def test_uf_lowercase_aceita(self):
        """sp (minúsculo) — deve aceitar (normaliza)."""
        assert validar_uf("sp").ok is True

    def test_todos_estados_validos(self):
        """Todos os 26 estados + DF devem ser aceitos."""
        ufs = [
            "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
            "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
            "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
        ]
        for uf in ufs:
            assert validar_uf(uf).ok is True, f"UF {uf} deveria ser aceita"

    def test_uf_inexistente_rejeitada(self):
        """UF 'ZZ' não existe — REJEITAR."""
        assert validar_uf("ZZ").ok is False

    def test_uf_3_letras_rejeitada(self):
        """UF com 3 letras — REJEITAR."""
        assert validar_uf("SPA").ok is False

    def test_uf_vazia_rejeitada(self):
        assert validar_uf("").ok is False

    def test_uf_numero_rejeitado(self):
        assert validar_uf("11").ok is False


# ─────────────────────────────────────────────────────────────────────────────
# CNAE — 7 dígitos
# ─────────────────────────────────────────────────────────────────────────────

class TestValidarCNAE:

    def test_cnae_valido_7_digitos(self):
        """CNAE 4711302 — Supermercado — deve aceitar."""
        assert validar_cnae("4711302").ok is True

    def test_cnae_com_hifen_aceito(self):
        """CNAE 4711-3/02 — deve aceitar (normaliza pontuação)."""
        assert validar_cnae("4711-3/02").ok is True

    def test_cnae_6_digitos_rejeitado(self):
        """CNAE com 6 dígitos — REJEITAR."""
        assert validar_cnae("471130").ok is False

    def test_cnae_8_digitos_rejeitado(self):
        """CNAE com 8 dígitos — REJEITAR."""
        assert validar_cnae("47113020").ok is False

    def test_cnae_vazio_rejeitado(self):
        assert validar_cnae("").ok is False

    def test_cnaes_sorocaba_comuns(self):
        """CNAEs mais comuns de Sorocaba — devem aceitar."""
        cnaes = [
            "4711302",  # Supermercado
            "4520001",  # Mecânica
            "2950600",  # Recondicionamento motores
            "6201501",  # TI / Software
            "6920601",  # Contabilidade
        ]
        for cnae in cnaes:
            assert validar_cnae(cnae).ok is True, f"CNAE {cnae} deveria ser aceito"


# ─────────────────────────────────────────────────────────────────────────────
# ValidationResult — Comportamento base
# ─────────────────────────────────────────────────────────────────────────────

class TestValidationResult:

    def test_resultado_ok_inicializa_sem_erros(self):
        r = ValidationResult(ok=True)
        assert r.ok is True
        assert r.errors == []

    def test_adicionar_erro_muda_ok_para_false(self):
        r = ValidationResult(ok=True)
        r.adicionar_erro("Erro de teste")
        assert r.ok is False
        assert "Erro de teste" in r.errors

    def test_bool_true_quando_ok(self):
        r = ValidationResult(ok=True)
        assert bool(r) is True

    def test_bool_false_quando_nao_ok(self):
        r = ValidationResult(ok=False, errors=["algo errado"])
        assert bool(r) is False

    def test_multiplos_erros_acumulados(self):
        r = ValidationResult(ok=True)
        r.adicionar_erro("Erro 1")
        r.adicionar_erro("Erro 2")
        assert len(r.errors) == 2
        assert r.ok is False
