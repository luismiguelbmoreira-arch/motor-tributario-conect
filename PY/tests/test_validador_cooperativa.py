# -*- coding: utf-8 -*-
"""
tests/test_validador_cooperativa.py — WS6 Etapa 5a
Sub-validador societário de cooperativas.

Função pura `validar_cooperativa(...)` retorna ResultadoValidacaoCooperativa
imutável (Pydantic frozen). Não levanta exceção — caller decide tratamento.

ESCOPO 5a — não cobre CREDITO nem SAUDE.

BASE LEGAL (validada por Escrivão 2026-05-08 contra cache local):
  - LC 214/2025 Art. 271 caput + § 3º (opção alíquota zero IBS/CBS)
  - LC 123/2006 Art. 3º § 4º VI + § 1º (vedação Simples salvo cooperativa de consumo)
  - Lei 5.764/71 Art. 10 caput + § 1º (classificação por objeto via OCB/CGSN)
  - Lei 5.764/71 Art. 4º (sociedades de pessoas constituídas para prestar
    serviços aos associados — características I-XI)

Rode com: pytest PY/tests/test_validador_cooperativa.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.validador_cooperativa import (  # noqa: E402
    ResultadoValidacaoCooperativa,
    validar_cooperativa,
)


# ─────────────────────────────────────────────────────────────────────────────
# NÃO APLICÁVEL — tipo_societario != COOPERATIVA
# ─────────────────────────────────────────────────────────────────────────────

class TestValidadorCooperativaNaoAplicavel:
    """Validador retorna NAO_APLICAVEL pra empresa não-cooperativa."""

    def test_ltda_retorna_nao_aplicavel(self):
        r = validar_cooperativa(
            tipo_societario="LTDA",
            subtipo_cooperativa=None,
            regime="PRESUMIDO",
            cnae_principal="4757100",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        assert isinstance(r, ResultadoValidacaoCooperativa)
        assert r.aplicavel is False
        assert r.valido is None
        # Função não inventa motivo nem pendência quando não se aplica
        assert r.motivos_bloqueio == ()


# ─────────────────────────────────────────────────────────────────────────────
# CASO FELIZ — cooperativa válida
# ─────────────────────────────────────────────────────────────────────────────

class TestValidadorCooperativaCasoFeliz:
    """Caso feliz: cooperativa de consumo no Presumido sem opt-in Art. 271."""

    def test_consumo_presumido_passa(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="CONSUMO",
            regime="PRESUMIDO",
            cnae_principal="4711301",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        assert r.aplicavel is True
        assert r.valido is True
        assert r.motivos_bloqueio == ()

    def test_trabalho_real_passa(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="TRABALHO",
            regime="REAL",
            cnae_principal="8211300",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        assert r.valido is True

    def test_consumo_simples_passa(self):
        # LC 123/2006 Art. 3º § 1º — exceção
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="CONSUMO",
            regime="SIMPLES",
            cnae_principal="4711301",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        assert r.valido is True


# ─────────────────────────────────────────────────────────────────────────────
# VEDAÇÃO SIMPLES — LC 123/2006 Art. 3º § 4º VI
# ─────────────────────────────────────────────────────────────────────────────

class TestValidadorCooperativaVedacaoSimples:
    """Cooperativa diferente de consumo no Simples = bloqueio."""

    @pytest.mark.parametrize(
        "subtipo",
        ["TRABALHO", "PRODUCAO", "AGROPECUARIA", "TRANSPORTE"],
    )
    def test_subtipo_vedado_no_simples_bloqueia(self, subtipo):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa=subtipo,
            regime="SIMPLES",
            cnae_principal="4711301",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        assert r.valido is False
        assert any("Art. 3" in m and "VI" in m for m in r.motivos_bloqueio)
        assert any("LC 123" in m for m in r.motivos_bloqueio)

    def test_motivo_bloqueio_simples_cita_excecao_consumo(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="TRABALHO",
            regime="SIMPLES",
            cnae_principal="8211300",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        # Motivo deve apontar a exceção pra orientar o usuário
        msg = " ".join(r.motivos_bloqueio)
        assert "consumo" in msg.lower() or "CONSUMO" in msg


# ─────────────────────────────────────────────────────────────────────────────
# OPT-IN ART. 271 — janela do § 3º (Rail R8 — consistência temporal)
# ─────────────────────────────────────────────────────────────────────────────

class TestValidadorCooperativaArt271Janela:
    """LC 214/2025 Art. 271 § 3º — opção produz efeitos no ano-calendário subsequente."""

    def test_opcao_no_ano_anterior_passa(self):
        # Operação em 2027; opção declarada em 2026 → válido
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="AGROPECUARIA",
            regime="REAL",
            cnae_principal="0151201",
            optante_art271=True,
            data_emissao=date(2027, 3, 1),
            data_opcao_art271=date(2026, 12, 31),
        )
        assert r.valido is True

    def test_opcao_no_mesmo_ano_da_operacao_bloqueia(self):
        # Operação em 2027; opção em 2027 → produz efeitos só em 2028 → bloqueia 2027
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="AGROPECUARIA",
            regime="REAL",
            cnae_principal="0151201",
            optante_art271=True,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=date(2027, 1, 10),
        )
        assert r.valido is False
        assert any("271" in m and "§" in m for m in r.motivos_bloqueio)

    def test_opcao_apos_operacao_bloqueia(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="PRODUCAO",
            regime="PRESUMIDO",
            cnae_principal="1011201",
            optante_art271=True,
            data_emissao=date(2027, 3, 1),
            data_opcao_art271=date(2027, 12, 1),  # depois da emissão
        )
        assert r.valido is False

    def test_nao_optante_dispensa_data_opcao(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="CONSUMO",
            regime="PRESUMIDO",
            cnae_principal="4711301",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        assert r.valido is True


# ─────────────────────────────────────────────────────────────────────────────
# 5b CREDITO — Real obrigatório (Lei 9.718/98 Art. 14 II)
# ─────────────────────────────────────────────────────────────────────────────

class TestValidadorCooperativa5bCredito:
    """Cooperativa de CRÉDITO — validação fiscal específica."""

    def test_credito_real_passa(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="CREDITO",
            regime="REAL",
            cnae_principal="6422100",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        assert r.aplicavel is True
        assert r.valido is True
        assert r.ramo == "CREDITO"

    def test_credito_real_cita_lei_9718_art_14_ii(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="CREDITO",
            regime="REAL",
            cnae_principal="6422100",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        leis = " ".join(r.base_legal_aplicavel)
        assert "9.718" in leis or "9718" in leis
        assert "Art. 14" in leis or "art. 14" in leis.lower()

    def test_credito_cita_art_183_par_1_iii_nao_182(self):
        # Bloqueio MAX_07: Escrivão pegou citação errada "Art. 182 § 1º III"
        # no rascunho — o correto é Art. 183 § 1º III (cooperativas de crédito
        # como entidade supervisionada do SFN).
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="CREDITO",
            regime="REAL",
            cnae_principal="6422100",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        leis = " ".join(r.base_legal_aplicavel)
        assert "Art. 183" in leis
        # Não confundir com Art. 182 (regulou OPERAÇÕES, não ENTIDADES)
        assert "Art. 182 § 1" not in leis
        assert "Art. 182, § 1" not in leis

    def test_credito_cita_art_192_par_8(self):
        # Operações coop-associado fora da base, sempre (independe Art. 271)
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="CREDITO",
            regime="REAL",
            cnae_principal="6422100",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        leis = " ".join(r.base_legal_aplicavel)
        assert "Art. 192" in leis
        assert "§ 8" in leis or "§8" in leis


# ─────────────────────────────────────────────────────────────────────────────
# 5b SAUDE — regime específico Cap III Tít V (Arts. 234-238)
# ─────────────────────────────────────────────────────────────────────────────

class TestValidadorCooperativa5bSaude:
    """Cooperativa operadora de plano de saúde — regime Art. 234+."""

    def test_saude_sem_optin_passa(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="SAUDE",
            regime="PRESUMIDO",
            cnae_principal="8650099",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        assert r.aplicavel is True
        assert r.valido is True
        assert r.ramo == "SAUDE"

    def test_saude_cita_art_234_iii(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="SAUDE",
            regime="PRESUMIDO",
            cnae_principal="8650099",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        leis = " ".join(r.base_legal_aplicavel)
        assert "Art. 234" in leis
        # Bloqueio MAX_07: nunca usar placeholder "Art. ~12049" do rascunho original
        assert "12049" not in leis
        assert "~Art" not in leis

    def test_saude_cita_aliquota_referencia_reduzida_60(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="SAUDE",
            regime="PRESUMIDO",
            cnae_principal="8650099",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        leis = " ".join(r.base_legal_aplicavel)
        assert "Art. 237" in leis
        assert "60" in leis  # 60% de redução


# ─────────────────────────────────────────────────────────────────────────────
# CITAÇÕES LEGAIS — anti-alucinação MAX_07
# ─────────────────────────────────────────────────────────────────────────────

class TestValidadorCooperativaCitacoesLegais:
    """Resultado precisa citar leis CORRETAS e NÃO citar artigos inventados."""

    def test_citacao_classificacao_aponta_art_10_caput_par1(self):
        # Plano original errava aqui (apontava Art. 6º + Art. 7º como objeto).
        # Escrivão validou: classificação por ramo é Art. 10 caput + § 1º.
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="CONSUMO",
            regime="PRESUMIDO",
            cnae_principal="4711301",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        leis = " ".join(r.base_legal_aplicavel)
        assert "Art. 10" in leis
        assert "Lei 5.764" in leis or "5.764/71" in leis

    def test_nao_cita_art_87_paragrafo_unico_inexistente(self):
        # Escrivão bloqueou ERR-058 potencial: Art. 87 § único NÃO EXISTE.
        # Texto da segregação contábil é do CAPUT (texto único).
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="CONSUMO",
            regime="PRESUMIDO",
            cnae_principal="4711301",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        leis = " ".join(r.base_legal_aplicavel)
        # Confirma que NÃO cita parágrafo único do 87 (inexistente)
        assert "Art. 87 § único" not in leis
        assert "Art. 87, § único" not in leis
        assert "Art. 87 parágrafo único" not in leis

    def test_citacao_simples_inclui_lc123_art3_par4_vi(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="TRABALHO",
            regime="SIMPLES",
            cnae_principal="8211300",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        # Mesmo bloqueado, base legal cita o dispositivo
        leis_e_motivos = " ".join(r.base_legal_aplicavel) + " " + " ".join(r.motivos_bloqueio)
        assert "LC 123" in leis_e_motivos
        assert "Art. 3" in leis_e_motivos

    def test_citacao_optin_inclui_art_271_par_3(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="AGROPECUARIA",
            regime="REAL",
            cnae_principal="0151201",
            optante_art271=True,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=date(2026, 12, 1),
        )
        leis = " ".join(r.base_legal_aplicavel)
        assert "Art. 271" in leis
        assert "LC 214" in leis


# ─────────────────────────────────────────────────────────────────────────────
# IMUTABILIDADE + ESTABILIDADE
# ─────────────────────────────────────────────────────────────────────────────

class TestValidadorCooperativaImutabilidade:
    """ResultadoValidacaoCooperativa é frozen (Pydantic V2 ConfigDict)."""

    def test_resultado_e_frozen(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="CONSUMO",
            regime="PRESUMIDO",
            cnae_principal="4711301",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        with pytest.raises(Exception):  # ValidationError ou TypeError dependendo da versão Pydantic
            r.valido = False  # type: ignore[misc]

    def test_motivos_e_pendencias_sao_tuple(self):
        r = validar_cooperativa(
            tipo_societario="COOPERATIVA",
            subtipo_cooperativa="TRABALHO",
            regime="SIMPLES",
            cnae_principal="8211300",
            optante_art271=False,
            data_emissao=date(2027, 6, 15),
            data_opcao_art271=None,
        )
        assert isinstance(r.motivos_bloqueio, tuple)
        assert isinstance(r.pendencias, tuple)
        assert isinstance(r.base_legal_aplicavel, tuple)
