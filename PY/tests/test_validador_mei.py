# -*- coding: utf-8 -*-
"""
test_validador_mei.py — Testes WS6 Etapa 3

Cobre os 4 requisitos extras do MEI (tipo, teto, Anexo XI, MEI Caminhoneiro)
+ comportamento conservador anti-alucinação (CNAE indeterminado retorna None,
não False).
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.cnae_mei_anexo_xi import (
    CNAES_MEI_CAMINHONEIRO,
    cnae_eh_mei_caminhoneiro,
    cnae_no_anexo_xi_mei,
)
from core.validador_mei import ResultadoValidacaoMEI, validar_mei


HOJE = date(2026, 4, 25)
PRE_2018 = date(2017, 12, 31)
PRE_2022 = date(2021, 12, 31)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Não aplicável (enquadramento != MEI)
# ─────────────────────────────────────────────────────────────────────────────

class TestNaoAplicavel:

    def test_enquadramento_none(self):
        r = validar_mei(
            tipo_societario="LTDA",
            enquadramento_simples=None,
            cnae_principal="4757100",
            faturamento_12m=Decimal("1000000"),
            data_emissao=HOJE,
        )
        assert r.modalidade == "NAO_APLICAVEL"
        assert r.valido is None

    def test_enquadramento_me(self):
        r = validar_mei(
            tipo_societario="LTDA",
            enquadramento_simples="ME",
            cnae_principal="4757100",
            faturamento_12m=Decimal("300000"),
            data_emissao=HOJE,
        )
        assert r.modalidade == "NAO_APLICAVEL"
        assert r.valido is None

    def test_enquadramento_epp(self):
        r = validar_mei(
            tipo_societario="LTDA",
            enquadramento_simples="EPP",
            cnae_principal="4757100",
            faturamento_12m=Decimal("4000000"),
            data_emissao=HOJE,
        )
        assert r.modalidade == "NAO_APLICAVEL"


# ─────────────────────────────────────────────────────────────────────────────
# 2. MEI tradicional — caminho feliz
# ─────────────────────────────────────────────────────────────────────────────

class TestMEIFeliz:

    def test_cabeleireira_dentro_teto(self):
        """Cabeleireira EI com R$ 60k → MEI válido (CNAE confirmado)."""
        r = validar_mei(
            tipo_societario="EI",
            enquadramento_simples="MEI",
            cnae_principal="9602501",
            faturamento_12m=Decimal("60000"),
            data_emissao=HOJE,
        )
        assert r.valido is True
        assert r.modalidade == "MEI"
        assert r.motivos_bloqueio == ()
        assert r.pendencias == ()
        assert "LC 123/2006 Art. 18-A" in r.base_legal_aplicavel

    def test_costureira_no_teto_exato(self):
        """R$ 81.000 exatos é OK (≤ é inclusivo)."""
        r = validar_mei(
            tipo_societario="EI",
            enquadramento_simples="MEI",
            cnae_principal="1411802",
            faturamento_12m=Decimal("81000.00"),
            data_emissao=HOJE,
        )
        assert r.valido is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. Bloqueios — tipo errado
# ─────────────────────────────────────────────────────────────────────────────

class TestTipoSocietarioErrado:

    def test_ltda_com_enquadramento_mei_bloqueia(self):
        r = validar_mei(
            tipo_societario="LTDA",
            enquadramento_simples="MEI",
            cnae_principal="9602501",
            faturamento_12m=Decimal("60000"),
            data_emissao=HOJE,
        )
        assert r.valido is False
        assert any("EI" in m for m in r.motivos_bloqueio)
        assert any("Lei 14.195/2021" in m for m in r.motivos_bloqueio)

    def test_sa_com_enquadramento_mei_bloqueia(self):
        r = validar_mei(
            tipo_societario="SA",
            enquadramento_simples="MEI",
            cnae_principal="9602501",
            faturamento_12m=Decimal("60000"),
            data_emissao=HOJE,
        )
        assert r.valido is False

    def test_tipo_none_bloqueia(self):
        r = validar_mei(
            tipo_societario=None,
            enquadramento_simples="MEI",
            cnae_principal="9602501",
            faturamento_12m=Decimal("60000"),
            data_emissao=HOJE,
        )
        assert r.valido is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. Bloqueios — faturamento acima do teto
# ─────────────────────────────────────────────────────────────────────────────

class TestTetoFaturamento:

    def test_acima_teto_mei_tradicional(self):
        r = validar_mei(
            tipo_societario="EI",
            enquadramento_simples="MEI",
            cnae_principal="9602501",
            faturamento_12m=Decimal("82000"),
            data_emissao=HOJE,
        )
        assert r.valido is False
        assert any("81000" in m and "82000" in m for m in r.motivos_bloqueio)

    def test_um_centavo_acima(self):
        r = validar_mei(
            tipo_societario="EI",
            enquadramento_simples="MEI",
            cnae_principal="9602501",
            faturamento_12m=Decimal("81000.01"),
            data_emissao=HOJE,
        )
        assert r.valido is False

    def test_data_pre_2018_levanta_pendencia(self):
        """LC 155/2016 só vigorou em 2018 — antes, não há teto MEI mapeado."""
        r = validar_mei(
            tipo_societario="EI",
            enquadramento_simples="MEI",
            cnae_principal="9602501",
            faturamento_12m=Decimal("60000"),
            data_emissao=PRE_2018,
        )
        # Faturamento 60k passa, mas teto indisponível → pendência
        assert r.valido is None or r.valido is False
        assert len(r.pendencias) > 0 or len(r.motivos_bloqueio) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 5. CNAE indeterminado (Rail R2 — Anti-alucinação)
# ─────────────────────────────────────────────────────────────────────────────

class TestCNAEIndeterminado:

    def test_cnae_fora_lista_parcial_retorna_pendencia_nao_bloqueia(self):
        """CNAE não confirmado NÃO bloqueia automaticamente — pede verificação."""
        r = validar_mei(
            tipo_societario="EI",
            enquadramento_simples="MEI",
            cnae_principal="9999999",  # fictício — fora da lista parcial
            faturamento_12m=Decimal("60000"),
            data_emissao=HOJE,
        )
        assert r.valido is None  # Indeterminado, não False
        assert len(r.pendencias) >= 1
        assert any("Anexo XI CGSN 140/2018" in p for p in r.pendencias)

    def test_cnae_confirmado_nao_gera_pendencia(self):
        r = validar_mei(
            tipo_societario="EI",
            enquadramento_simples="MEI",
            cnae_principal="9602501",  # cabeleireira — confirmado
            faturamento_12m=Decimal("60000"),
            data_emissao=HOJE,
        )
        assert r.pendencias == ()


# ─────────────────────────────────────────────────────────────────────────────
# 6. MEI Caminhoneiro (LC 188/2021)
# ─────────────────────────────────────────────────────────────────────────────

class TestMEICaminhoneiro:

    def test_caminhoneiro_dentro_sublimite(self):
        r = validar_mei(
            tipo_societario="EI",
            enquadramento_simples="MEI_CAMINHONEIRO",
            cnae_principal="4930202",
            faturamento_12m=Decimal("200000"),
            data_emissao=HOJE,
        )
        assert r.valido is True
        assert r.modalidade == "MEI_CAMINHONEIRO"
        assert "LC 188/2021" in r.base_legal_aplicavel

    def test_caminhoneiro_acima_sublimite_bloqueia(self):
        r = validar_mei(
            tipo_societario="EI",
            enquadramento_simples="MEI_CAMINHONEIRO",
            cnae_principal="4930202",
            faturamento_12m=Decimal("260000"),
            data_emissao=HOJE,
        )
        assert r.valido is False
        assert any("251600" in m for m in r.motivos_bloqueio)

    def test_caminhoneiro_cnae_errado_bloqueia(self):
        """MEI_CAMINHONEIRO com CNAE de cabeleireira → bloqueia."""
        r = validar_mei(
            tipo_societario="EI",
            enquadramento_simples="MEI_CAMINHONEIRO",
            cnae_principal="9602501",
            faturamento_12m=Decimal("100000"),
            data_emissao=HOJE,
        )
        assert r.valido is False
        assert any("transporte rodoviário de carga" in m for m in r.motivos_bloqueio)
        assert any("LC 188/2021" in m for m in r.motivos_bloqueio)

    def test_caminhoneiro_pre_2022_levanta_pendencia(self):
        """LC 188/2021 vigência a partir de 2022."""
        r = validar_mei(
            tipo_societario="EI",
            enquadramento_simples="MEI_CAMINHONEIRO",
            cnae_principal="4930202",
            faturamento_12m=Decimal("100000"),
            data_emissao=PRE_2022,
        )
        # Teto indisponível → pendência ou bloqueio
        assert r.valido is None or r.valido is False


# ─────────────────────────────────────────────────────────────────────────────
# 7. Helpers do módulo cnae_mei_anexo_xi
# ─────────────────────────────────────────────────────────────────────────────

class TestHelpersCNAE:

    def test_cnae_confirmado_retorna_true(self):
        assert cnae_no_anexo_xi_mei("9602501") is True
        assert cnae_no_anexo_xi_mei("4930202") is True

    def test_cnae_fora_lista_retorna_none(self):
        assert cnae_no_anexo_xi_mei("0000000") is None
        assert cnae_no_anexo_xi_mei("9999999") is None

    def test_cnae_invalido_retorna_none(self):
        assert cnae_no_anexo_xi_mei("") is None
        assert cnae_no_anexo_xi_mei("ABC") is None
        assert cnae_no_anexo_xi_mei("12345") is None  # 5 dígitos

    def test_caminhoneiro_helper(self):
        assert cnae_eh_mei_caminhoneiro("4930201") is True
        assert cnae_eh_mei_caminhoneiro("4930202") is True
        assert cnae_eh_mei_caminhoneiro("9602501") is False  # cabeleireira

    def test_set_caminhoneiro_disjunto_de_outros(self):
        outros = {"9602501", "1411802", "4399105", "5320202"}
        assert outros.isdisjoint(CNAES_MEI_CAMINHONEIRO)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Imutabilidade do resultado
# ─────────────────────────────────────────────────────────────────────────────

class TestImutabilidade:

    def test_resultado_eh_frozen(self):
        r = validar_mei(
            tipo_societario="EI",
            enquadramento_simples="MEI",
            cnae_principal="9602501",
            faturamento_12m=Decimal("60000"),
            data_emissao=HOJE,
        )
        with pytest.raises((ValueError, TypeError)):
            r.valido = False  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# 9. Combinação de bloqueios (tipo errado + faturamento acima)
# ─────────────────────────────────────────────────────────────────────────────

class TestMultiplosBloqueios:

    def test_ltda_acima_teto_bloqueia_com_dois_motivos(self):
        r = validar_mei(
            tipo_societario="LTDA",
            enquadramento_simples="MEI",
            cnae_principal="9602501",
            faturamento_12m=Decimal("100000"),
            data_emissao=HOJE,
        )
        assert r.valido is False
        assert len(r.motivos_bloqueio) >= 2  # tipo errado + teto excedido

    def test_caminhoneiro_tipo_errado_e_cnae_errado(self):
        r = validar_mei(
            tipo_societario="LTDA",
            enquadramento_simples="MEI_CAMINHONEIRO",
            cnae_principal="9602501",
            faturamento_12m=Decimal("100000"),
            data_emissao=HOJE,
        )
        assert r.valido is False
        # Espera ao menos: tipo errado + CNAE errado pra MEI_CAMINHONEIRO
        assert len(r.motivos_bloqueio) >= 2
