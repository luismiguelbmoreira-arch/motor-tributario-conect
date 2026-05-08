# -*- coding: utf-8 -*-
"""
tests/test_schema_cooperativa.py — WS6 Etapa 5a
Schema de cooperativa em EmpresaFornecedora (Pydantic V2).

ESCOPO 5a: CONSUMO, TRABALHO, PRODUCAO, AGROPECUARIA, TRANSPORTE.
ESCOPO 5b: CREDITO, SAUDE — schema deve REJEITAR com mensagem específica.

BASE LEGAL:
  - LC 214/2025 Art. 271 caput + I, II + § 3º (opção alíquota zero)
  - LC 123/2006 Art. 3º § 4º VI (vedação Simples salvo cooperativa de consumo)
  - LC 123/2006 Art. 3º § 1º (exceção cooperativa de consumo)
  - Lei 5.764/71 (Política Nacional de Cooperativismo) — citações específicas
    chegam no overlay/validador após validação Escrivão

Rode com: pytest PY/tests/test_schema_cooperativa.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas.motor import EmpresaFornecedora  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — empresa cooperativa válida com sane defaults
# ─────────────────────────────────────────────────────────────────────────────

def _coop(
    *,
    subtipo: str = "CONSUMO",
    regime: str = "PRESUMIDO",
    optante_art271: bool = False,
    data_opcao: date | None = None,
    receita_ato_coop: Decimal = Decimal("80000.00"),
    receita_ato_nao_coop: Decimal = Decimal("20000.00"),
    cnae: str = "4711301",
    faturamento: Decimal | None = None,
) -> EmpresaFornecedora:
    """Helper pra montar EmpresaFornecedora COOPERATIVA com sane defaults."""
    fat = faturamento if faturamento is not None else (receita_ato_coop + receita_ato_nao_coop)
    return EmpresaFornecedora(
        cnpj="33000167000101",
        razao_social=f"COOPERATIVA TESTE {subtipo}",
        regime=regime,
        cnae_principal=cnae,
        uf_origem="SP",
        faturamento_12m=fat,
        tipo_societario="COOPERATIVA",
        subtipo_cooperativa=subtipo,
        optante_art271_cbs_ibs=optante_art271,
        data_opcao_art271=data_opcao,
        receita_ato_cooperativo=receita_ato_coop,
        receita_ato_nao_cooperativo=receita_ato_nao_coop,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CAMPOS NOVOS — aceitam todos os subtipos de 5a
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaCooperativaCamposNovos:
    """Campos novos do WS6 Etapa 5a aceitos no Pydantic."""

    @pytest.mark.parametrize(
        "subtipo",
        ["CONSUMO", "TRABALHO", "PRODUCAO", "AGROPECUARIA", "TRANSPORTE"],
    )
    def test_subtipo_5a_aceito(self, subtipo):
        emp = _coop(subtipo=subtipo)
        assert emp.subtipo_cooperativa == subtipo
        assert emp.tipo_societario == "COOPERATIVA"

    def test_default_optante_art271_false(self):
        emp = _coop()
        assert emp.optante_art271_cbs_ibs is False

    def test_default_data_opcao_art271_none(self):
        emp = _coop()
        assert emp.data_opcao_art271 is None

    def test_receitas_decimais_aceitas(self):
        emp = _coop(
            receita_ato_coop=Decimal("123456.78"),
            receita_ato_nao_coop=Decimal("9876.54"),
        )
        assert emp.receita_ato_cooperativo == Decimal("123456.78")
        assert emp.receita_ato_nao_cooperativo == Decimal("9876.54")

    def test_receitas_default_zero_quando_omitidas(self):
        # Quando tipo_societario não é COOPERATIVA, defaults preservam zero
        emp = EmpresaFornecedora(
            cnpj="11222333000181",
            razao_social="LTDA TESTE",
            regime="PRESUMIDO",
            cnae_principal="4757100",
            uf_origem="SP",
            faturamento_12m=Decimal("3000000.00"),
            tipo_societario="LTDA",
        )
        assert emp.receita_ato_cooperativo == Decimal("0")
        assert emp.receita_ato_nao_cooperativo == Decimal("0")
        assert emp.subtipo_cooperativa is None


# ─────────────────────────────────────────────────────────────────────────────
# 5b CREDITO — Real obrigatório (Lei 9.718/98 Art. 14 II)
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaCooperativa5bCredito:
    """
    Cooperativa de CRÉDITO obrigada ao Lucro Real (Lei 9.718/98 Art. 14 II).
    Schema bloqueia regime != REAL com mensagem citando a lei.
    """

    def test_credito_no_real_aceita(self):
        emp = _coop(subtipo="CREDITO", regime="REAL", cnae="6422100",
                    receita_ato_coop=Decimal("8000000"),
                    receita_ato_nao_coop=Decimal("2000000"))
        assert emp.subtipo_cooperativa == "CREDITO"
        assert emp.regime == "REAL"

    @pytest.mark.parametrize("regime_invalido", ["SIMPLES", "PRESUMIDO", "MEI"])
    def test_credito_fora_do_real_bloqueia(self, regime_invalido):
        # IMUNE não entra no parametrize — combinação cooperativa+IMUNE roda
        # antes o validator de IMUNE (subtipo_imune obrigatório), produzindo
        # mensagem diferente. Caso real é coberto por outras camadas.
        with pytest.raises(ValueError, match="9.?718"):
            _coop(subtipo="CREDITO", regime=regime_invalido,
                  receita_ato_coop=Decimal("8000000"),
                  receita_ato_nao_coop=Decimal("2000000"))

    def test_credito_mensagem_cita_lei_9718_art_14_ii(self):
        with pytest.raises(ValueError) as exc:
            _coop(subtipo="CREDITO", regime="PRESUMIDO",
                  receita_ato_coop=Decimal("8000000"),
                  receita_ato_nao_coop=Decimal("2000000"))
        msg = str(exc.value)
        assert "Lei 9.718" in msg or "9718" in msg
        assert "Art. 14" in msg or "art. 14" in msg.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 5b SAUDE — regime específico LC 214 Art. 234+ (sem opt-in Art. 271)
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaCooperativa5bSaude:
    """
    Cooperativa operadora de plano de saúde (UNIMED) cai no regime específico
    Cap III Tít V LC 214 — Arts. 234-238. Art. 271 é INAPLICÁVEL: opt-in
    pelo Art. 271 com SAUDE → bloqueio.
    """

    def test_saude_sem_optin_aceita(self):
        emp = _coop(subtipo="SAUDE", regime="PRESUMIDO", cnae="8650099",
                    receita_ato_coop=Decimal("3000000"),
                    receita_ato_nao_coop=Decimal("500000"))
        assert emp.subtipo_cooperativa == "SAUDE"

    def test_saude_no_real_aceita(self):
        emp = _coop(subtipo="SAUDE", regime="REAL", cnae="8650099",
                    receita_ato_coop=Decimal("100000000"),
                    receita_ato_nao_coop=Decimal("5000000"))
        assert emp.regime == "REAL"

    def test_saude_com_optin_art271_bloqueia(self):
        # Art. 271 não cobre Art. 234+ (regime específico de planos de saúde)
        with pytest.raises(ValueError, match="234|271"):
            _coop(
                subtipo="SAUDE",
                regime="PRESUMIDO",
                cnae="8650099",
                optante_art271=True,
                data_opcao=date(2026, 12, 1),
                receita_ato_coop=Decimal("3000000"),
                receita_ato_nao_coop=Decimal("500000"),
            )

    def test_saude_optin_mensagem_cita_art_234(self):
        with pytest.raises(ValueError) as exc:
            _coop(
                subtipo="SAUDE",
                regime="PRESUMIDO",
                cnae="8650099",
                optante_art271=True,
                data_opcao=date(2026, 12, 1),
                receita_ato_coop=Decimal("3000000"),
                receita_ato_nao_coop=Decimal("500000"),
            )
        msg = str(exc.value)
        assert "Art. 234" in msg
        # Não confundir com placeholder antigo "Art. ~12049"
        assert "12049" not in msg


# ─────────────────────────────────────────────────────────────────────────────
# CONSISTÊNCIA — tipo_societario × subtipo × receita
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaCooperativaConsistencia:
    """Validador cruzado COOPERATIVA × subtipo × receita."""

    def test_cooperativa_sem_subtipo_levanta_erro(self):
        with pytest.raises(ValueError, match="subtipo_cooperativa"):
            EmpresaFornecedora(
                cnpj="33000167000101",
                razao_social="COOP SEM SUBTIPO",
                regime="PRESUMIDO",
                cnae_principal="4711301",
                uf_origem="SP",
                faturamento_12m=Decimal("100000"),
                tipo_societario="COOPERATIVA",
                receita_ato_cooperativo=Decimal("80000"),
                receita_ato_nao_cooperativo=Decimal("20000"),
            )

    def test_cooperativa_com_soma_receitas_zero_levanta_erro(self):
        with pytest.raises(ValueError, match="receita"):
            EmpresaFornecedora(
                cnpj="33000167000101",
                razao_social="COOP SEM RECEITA",
                regime="PRESUMIDO",
                cnae_principal="4711301",
                uf_origem="SP",
                faturamento_12m=Decimal("100000"),
                tipo_societario="COOPERATIVA",
                subtipo_cooperativa="CONSUMO",
                receita_ato_cooperativo=Decimal("0"),
                receita_ato_nao_cooperativo=Decimal("0"),
            )

    def test_cooperativa_so_ato_cooperativo_aceita(self):
        emp = _coop(
            receita_ato_coop=Decimal("100000"),
            receita_ato_nao_coop=Decimal("0"),
        )
        assert emp.receita_ato_cooperativo == Decimal("100000")
        assert emp.receita_ato_nao_cooperativo == Decimal("0")

    def test_cooperativa_so_ato_nao_cooperativo_aceita(self):
        emp = _coop(
            receita_ato_coop=Decimal("0"),
            receita_ato_nao_coop=Decimal("100000"),
        )
        assert emp.receita_ato_cooperativo == Decimal("0")
        assert emp.receita_ato_nao_cooperativo == Decimal("100000")

    def test_subtipo_cooperativa_em_ltda_levanta_erro(self):
        # subtipo_cooperativa só faz sentido com tipo_societario=COOPERATIVA
        with pytest.raises(ValueError, match="subtipo_cooperativa"):
            EmpresaFornecedora(
                cnpj="11222333000181",
                razao_social="LTDA COM SUBTIPO COOP (ERRADO)",
                regime="PRESUMIDO",
                cnae_principal="4757100",
                uf_origem="SP",
                faturamento_12m=Decimal("100000"),
                tipo_societario="LTDA",
                subtipo_cooperativa="CONSUMO",
            )


# ─────────────────────────────────────────────────────────────────────────────
# VEDAÇÃO SIMPLES — LC 123/2006 Art. 3º §4º VI
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaCooperativaVedacaoSimples:
    """LC 123/2006 Art. 3º §4º VI — vedação Simples salvo cooperativa de consumo."""

    def test_consumo_no_simples_aceita(self):
        # LC 123/2006 Art. 3º §1º — exceção: cooperativa de consumo no Simples
        emp = _coop(
            subtipo="CONSUMO",
            regime="SIMPLES",
            faturamento=Decimal("1000000"),
        )
        assert emp.regime == "SIMPLES"

    @pytest.mark.parametrize(
        "subtipo_vedado",
        ["TRABALHO", "PRODUCAO", "AGROPECUARIA", "TRANSPORTE"],
    )
    def test_demais_subtipos_no_simples_rejeita(self, subtipo_vedado):
        # Art. 3º §4º VI — demais cooperativas vedadas no Simples
        with pytest.raises(ValueError, match="3.{0,2}.{0,2}4"):
            _coop(
                subtipo=subtipo_vedado,
                regime="SIMPLES",
                faturamento=Decimal("1000000"),
            )

    def test_mensagem_vedacao_cita_lc123(self):
        with pytest.raises(ValueError) as exc:
            _coop(subtipo="TRABALHO", regime="SIMPLES")
        msg = str(exc.value)
        assert "LC 123" in msg


# ─────────────────────────────────────────────────────────────────────────────
# OPT-IN ART. 271 — janela do § 3º
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaCooperativaArt271:
    """LC 214/2025 Art. 271 — opção alíquota zero (schema só captura, motor avalia)."""

    def test_optante_true_com_data_opcao_aceita(self):
        emp = _coop(
            optante_art271=True,
            data_opcao=date(2025, 12, 1),  # ano anterior ao ano-calendário 2026
        )
        assert emp.optante_art271_cbs_ibs is True
        assert emp.data_opcao_art271 == date(2025, 12, 1)

    def test_optante_false_sem_data_opcao_aceita(self):
        emp = _coop(optante_art271=False, data_opcao=None)
        assert emp.optante_art271_cbs_ibs is False
        assert emp.data_opcao_art271 is None

    def test_optante_true_sem_data_opcao_levanta_erro(self):
        # Art. 271 §3º — opção tem data certa
        with pytest.raises(ValueError, match="data_opcao_art271"):
            _coop(optante_art271=True, data_opcao=None)
