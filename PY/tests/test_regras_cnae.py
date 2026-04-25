# -*- coding: utf-8 -*-
"""
test_regras_cnae.py — Testes WS12 do schema CNAE -> Anexo Simples Nacional

Cobre:
  - 5 categorias (A_FIXO, B_ANEXO_III, C_FATOR_R, D_ESPECIAL, E_VEDADO)
  - 14 casos cirurgicos (override de divisao)
  - Fator R no limiar 0.28 (LC 123/2006 §5º-J)
  - Casos reais do projeto: CANAVEZI (4757100=I), CONFI_AR (2539001=II), MOREIRA (6920601=III)
  - Vedacoes (Art. 17): Bancos (6491300), Factoring (6435201)
  - Coerencia do Pydantic (model_validator)

Fonte: docs/especificacoes/WS12_schema_cnae_luiz_moreira.md
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.regras_cnae import (
    FATOR_R_LIMIAR,
    RegraCNAE,
    is_vedado,
    obter_regra,
    resolve_anexo,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Casos cirurgicos (override por CNAE 7-digitos)
# ─────────────────────────────────────────────────────────────────────────────

class TestCasosCirurgicos:

    def test_contabilidade_anexo_iii_sempre(self):
        """6920601 (Contabilidade) -> III SEMPRE, §5º-B XIV. Caso MOREIRA."""
        regra = obter_regra("6920601")
        assert regra is not None
        assert regra.categoria == "B_ANEXO_III"
        assert regra.anexo_padrao == "III"
        assert regra.depende_fator_r is False
        assert "§5º-B" in regra.base_legal
        # Resolve sem fator_r ainda da III
        anexo, fonte = resolve_anexo("6920601")
        assert anexo == "III"
        assert fonte == "B_ANEXO_III"

    def test_advocacia_anexo_iv_sempre(self):
        """6911701 (Advocacia) -> IV SEMPRE, §5º-C V. ATENCAO: nao e III nem V."""
        regra = obter_regra("6911701")
        assert regra is not None
        assert regra.categoria == "D_ESPECIAL"
        assert regra.anexo_padrao == "IV"
        assert regra.depende_fator_r is False
        assert "§5º-C" in regra.base_legal
        anexo, fonte = resolve_anexo("6911701")
        assert anexo == "IV"
        assert fonte == "D_ESPECIAL"

    def test_canavezi_comercio_anexo_i(self):
        """4757100 (CANAVEZI — eletroeletronicos) -> I."""
        anexo, fonte = resolve_anexo("4757100")
        assert anexo == "I"
        assert fonte == "A_FIXO"

    def test_confi_ar_industria_anexo_ii(self):
        """2539001 (CONFI_AR — tempera de metais) -> II."""
        anexo, fonte = resolve_anexo("2539001")
        assert anexo == "II"
        assert fonte == "A_FIXO"

    def test_academia_anexo_iii_sempre(self):
        """9311500 (Academia) -> III SEMPRE, §5º-B IX (LC 155/2016)."""
        regra = obter_regra("9311500")
        assert regra.categoria == "B_ANEXO_III"
        assert regra.anexo_padrao == "III"

    def test_construcao_subcontratada_anexo_iv(self):
        """4399103 (Construcao subcontratada) -> IV."""
        anexo, fonte = resolve_anexo("4399103")
        assert anexo == "IV"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Fator R (C_FATOR_R)
# ─────────────────────────────────────────────────────────────────────────────

class TestFatorR:

    def test_restaurante_fator_r_alto_anexo_iii(self):
        """5611201 (Restaurante) com Fator R 0.30 -> III."""
        anexo, fonte = resolve_anexo("5611201", fator_r=Decimal("0.30"))
        assert anexo == "III"
        assert fonte == "C_FATOR_R_ALTO"

    def test_restaurante_fator_r_baixo_anexo_v(self):
        """5611201 (Restaurante) com Fator R 0.20 -> V."""
        anexo, fonte = resolve_anexo("5611201", fator_r=Decimal("0.20"))
        assert anexo == "V"
        assert fonte == "C_FATOR_R_BAIXO"

    def test_ti_fator_r_limiar_exato_028(self):
        """6201501 (TI) com Fator R = 0.28 (limiar) -> III (>=)."""
        anexo, fonte = resolve_anexo("6201501", fator_r=Decimal("0.28"))
        assert anexo == "III"
        assert fonte == "C_FATOR_R_ALTO"

    def test_ti_fator_r_logo_abaixo_limiar(self):
        """6201501 (TI) com Fator R = 0.2799 -> V (<0.28)."""
        anexo, fonte = resolve_anexo("6201501", fator_r=Decimal("0.2799"))
        assert anexo == "V"
        assert fonte == "C_FATOR_R_BAIXO"

    def test_ti_fator_r_zero_anexo_v(self):
        """6201501 (TI) sem folha (Fator R=0) -> V."""
        anexo, fonte = resolve_anexo("6201501", fator_r=Decimal("0"))
        assert anexo == "V"

    def test_medicina_ambulatorial_fator_r(self):
        """8630501 (Medico ambulatorial) com Fator R 0.50 -> III."""
        anexo, fonte = resolve_anexo("8630501", fator_r=Decimal("0.50"))
        assert anexo == "III"

    def test_c_fator_r_sem_fator_r_e_conservador(self):
        """C_FATOR_R sem fator_r informado -> V (conservador, Constraint 6 Luiz)."""
        anexo, fonte = resolve_anexo("6201501")  # sem fator_r
        assert anexo == "V"
        assert fonte == "C_FATOR_R_CONSERVADOR"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Vedacoes (E_VEDADO)
# ─────────────────────────────────────────────────────────────────────────────

class TestVedacoes:

    def test_banco_vedado(self):
        """6491300 (Bancos) -> E_VEDADO, Art. 17 I."""
        assert is_vedado("6491300") is True
        regra = obter_regra("6491300")
        assert regra.categoria == "E_VEDADO"
        assert regra.anexo_padrao is None
        assert "Art. 17" in regra.base_legal

    def test_factoring_vedado(self):
        """6435201 (Factoring) -> E_VEDADO, Art. 17 VI."""
        assert is_vedado("6435201") is True

    def test_vedado_resolve_com_fonte_explicita(self):
        """E_VEDADO retorna III com fonte E_VEDADO_FALLBACK_III pra trilha auditar."""
        anexo, fonte = resolve_anexo("6491300")
        assert anexo == "III"  # fallback pra nao quebrar caller
        assert fonte == "E_VEDADO_FALLBACK_III"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Fallback e edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestFallbacks:

    def test_cnae_invalido_curto(self):
        """CNAE com menos de 7 digitos -> None."""
        assert obter_regra("12345") is None
        anexo, fonte = resolve_anexo("12345")
        assert fonte == "FALLBACK_NAO_MAPEADO"

    def test_cnae_invalido_letras(self):
        """CNAE com letras -> None."""
        assert obter_regra("ABC1234") is None

    def test_cnae_nao_mapeado_fallback_iii(self):
        """CNAE com divisao desconhecida -> Anexo III conservador."""
        anexo, fonte = resolve_anexo("0099999")  # divisao 00 inexistente
        assert anexo == "III"
        assert fonte == "FALLBACK_NAO_MAPEADO"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Coerencia do schema Pydantic
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaPydantic:

    def test_c_fator_r_exige_anexos_alto_baixo(self):
        """C_FATOR_R sem anexo_fator_r_alto/baixo deve falhar."""
        with pytest.raises((AssertionError, ValueError)):
            RegraCNAE(
                cnae="6201501",
                categoria="C_FATOR_R",
                anexo_padrao=None,
                depende_fator_r=True,
                # falta anexo_fator_r_alto e baixo
                base_legal="LC 123/2006 §5º-D I",
            )

    def test_a_fixo_nao_aceita_anexo_fator_r(self):
        """A_FIXO com anexo_fator_r_alto setado deve falhar."""
        with pytest.raises((AssertionError, ValueError)):
            RegraCNAE(
                cnae="4757100",
                categoria="A_FIXO",
                anexo_padrao="I",
                depende_fator_r=False,
                anexo_fator_r_alto="III",  # ilegal
                base_legal="LC 123/2006 §4º I",
            )

    def test_e_vedado_nao_tem_anexo_padrao(self):
        """E_VEDADO com anexo_padrao setado deve falhar."""
        with pytest.raises((AssertionError, ValueError)):
            RegraCNAE(
                cnae="6491300",
                categoria="E_VEDADO",
                anexo_padrao="I",  # ilegal
                depende_fator_r=False,
                base_legal="LC 123/2006 Art. 17 I",
            )

    def test_categoria_nao_vedado_exige_anexo_padrao(self):
        """A_FIXO/B/D sem anexo_padrao deve falhar."""
        with pytest.raises((AssertionError, ValueError)):
            RegraCNAE(
                cnae="4757100",
                categoria="A_FIXO",
                anexo_padrao=None,  # ilegal pra A_FIXO
                depende_fator_r=False,
                base_legal="LC 123/2006 §4º I",
            )


# ─────────────────────────────────────────────────────────────────────────────
# 6. Constantes de referencia
# ─────────────────────────────────────────────────────────────────────────────

class TestConstantes:

    def test_fator_r_limiar_e_028(self):
        """Limiar do Fator R deve ser 0.28 (LC 123/2006 §5º-J)."""
        assert FATOR_R_LIMIAR == Decimal("0.28")
