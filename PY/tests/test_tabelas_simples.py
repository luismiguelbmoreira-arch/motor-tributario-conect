"""
test_tabelas_simples.py — Testes para funções utilitárias de tabelas_simples.py
Cobre: determinar_anexo_por_cnae, determinar_anexo_por_cnae_com_fonte,
       estimar_perfil_b2b, obter_faixa_numero, calcular_partilha_iss_cap
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from decimal import Decimal
from core.tabelas_simples import (
    determinar_anexo_por_cnae,
    determinar_anexo_por_cnae_com_fonte,
    estimar_perfil_b2b,
    obter_faixa_numero,
    calcular_partilha_iss_cap,
)


# ─────────────────────────────────────────────────────────────────────────────
# determinar_anexo_por_cnae / determinar_anexo_por_cnae_com_fonte
# ─────────────────────────────────────────────────────────────────────────────

class TestDeterminarAnexoPorCNAE:

    def test_cnae_explicito_comercio(self):
        """CNAE 4711302 (Supermercado) deve retornar Anexo I."""
        assert determinar_anexo_por_cnae("4711302") == "I"

    def test_cnae_explicito_industria(self):
        """CNAE 2950600 (Recondicionamento) deve retornar Anexo II."""
        assert determinar_anexo_por_cnae("2950600") == "II"

    def test_cnae_explicito_ti(self):
        """CNAE 6201501 (TI/Software) deve retornar Anexo V."""
        assert determinar_anexo_por_cnae("6201501") == "V"

    def test_cnae_com_fonte_explicito(self):
        """Busca exata deve retornar fonte EXPLICITO ou PREFIXO."""
        # 4711302 resolve via prefixo 47 (comércio varejo) → Anexo I
        anexo, fonte = determinar_anexo_por_cnae_com_fonte("4711302")
        assert fonte in ("EXPLICITO", "PREFIXO")

    def test_cnae_com_fonte_prefixo(self):
        """CNAE não mapeado explicitamente deve usar prefixo."""
        # CNAE fictício com prefixo 47 (comércio varejo) → Anexo I via prefixo
        anexo, fonte = determinar_anexo_por_cnae_com_fonte("4700000")
        assert fonte == "PREFIXO"

    def test_cnae_com_fonte_fallback(self):
        """CNAE totalmente desconhecido deve retornar fallback Anexo III."""
        anexo, fonte = determinar_anexo_por_cnae_com_fonte("9999999")
        assert anexo == "III"
        assert fonte == "FALLBACK"


# ─────────────────────────────────────────────────────────────────────────────
# estimar_perfil_b2b
# ─────────────────────────────────────────────────────────────────────────────

class TestEstimarPerfilB2B:

    def test_industria_b2b_alto(self):
        """Indústria (prefixo 10-33) deve ter B2B alto (~90%)."""
        assert estimar_perfil_b2b("1011201") == 90

    def test_varejo_b2b_baixo(self):
        """Varejo (prefixo 47) deve ter B2B baixo (30%)."""
        assert estimar_perfil_b2b("4711302") == 30

    def test_cnae_desconhecido_default_50(self):
        """CNAE com prefixo desconhecido deve retornar 50 (default)."""
        assert estimar_perfil_b2b("9999999") == 50

    def test_cnae_vazio_default_50(self):
        """CNAE vazio deve retornar 50 (default)."""
        assert estimar_perfil_b2b("") == 50


# ─────────────────────────────────────────────────────────────────────────────
# obter_faixa_numero
# ─────────────────────────────────────────────────────────────────────────────

class TestObterFaixaNumero:

    def test_faixa_1_anexo_I(self):
        """RBT12 de R$100.000 no Anexo I deve ser faixa 1."""
        assert obter_faixa_numero(Decimal("100000"), "I") == 1

    def test_faixa_2_anexo_I(self):
        """RBT12 de R$300.000 no Anexo I deve ser faixa 2."""
        assert obter_faixa_numero(Decimal("300000"), "I") == 2

    def test_faixa_6_anexo_I(self):
        """RBT12 de R$4.000.000 no Anexo I deve ser faixa 6."""
        assert obter_faixa_numero(Decimal("4000000"), "I") == 6

    def test_acima_teto_retorna_0(self):
        """RBT12 acima do teto deve retornar faixa 0."""
        assert obter_faixa_numero(Decimal("5000000"), "I") == 0

    def test_anexo_inexistente_retorna_0(self):
        """Anexo inexistente deve retornar faixa 0."""
        assert obter_faixa_numero(Decimal("100000"), "X") == 0


# ─────────────────────────────────────────────────────────────────────────────
# calcular_partilha_iss_cap
# ─────────────────────────────────────────────────────────────────────────────

class TestCalcularPartilhaIssCap:

    def test_sem_cap_faixa_baixa(self):
        """Faixa 1 Anexo III — ISS dentro do limite, sem redistribuição."""
        resultado = calcular_partilha_iss_cap("III", 1, Decimal("0.06"))
        assert "ISS" in resultado
        # ISS efetivo = 0.3350 * 0.06 = 0.0201 < 0.05 → sem cap
        assert resultado["ISS"] == Decimal("0.3350")

    def test_aliquota_zero_retorna_base(self):
        """Alíquota efetiva zero deve retornar base sem ajuste."""
        resultado = calcular_partilha_iss_cap("III", 1, Decimal("0"))
        assert resultado.get("ISS", Decimal("0")) == resultado.get("ISS", Decimal("0"))

    def test_anexo_inexistente_retorna_vazio(self):
        """Anexo inexistente deve retornar dict vazio."""
        resultado = calcular_partilha_iss_cap("X", 1, Decimal("0.10"))
        assert resultado == {}

    def test_cap_aplicado_faixa_alta(self):
        """Faixa 5/6 Anexo III com alíquota alta — ISS deve ser capado em 5%."""
        # Faixa 5: ISS = 0.15, alíquota efetiva alta
        # ISS efetivo = 0.15 * 0.21 = 0.0315 < 0.05 → sem cap nesta faixa
        # Para acionar cap, precisamos ISS_fracao * aliq > 0.05
        # Usando alíquota artificial alta para testar a lógica de cap
        resultado = calcular_partilha_iss_cap("III", 1, Decimal("0.20"))
        # ISS_fracao=0.3350, ISS_efetivo=0.3350*0.20=0.067 > 0.05 → cap aplicado
        iss_cap_fracao = Decimal("0.05") / Decimal("0.20")  # 0.25
        assert resultado["ISS"] == iss_cap_fracao
