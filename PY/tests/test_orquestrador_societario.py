# -*- coding: utf-8 -*-
"""
tests/test_orquestrador_societario.py — WS6 Etapa 6
Orquestrador `validar_combinacao()` consolida WS6 + WS10 + WS12 num único
resultado.

OBJETIVO:
  AND lógico de:
    1. Matriz societária 13×4 (core/elegibilidade_societaria.py)
    2. Sub-validador MEI (core/validador_mei.py)
    3. Sub-validador COOPERATIVA (core/validador_cooperativa.py)
    4. Resolução CNAE × Anexo (core/regras_cnae.py)
    5. Limites versionados (core/versioned_rule.py)

  CONCATENA TODAS AS FALHAS — não para na primeira. Operador vê tudo.
  NÃO levanta exceção — caller decide tratamento.

BASE LEGAL:
  - Rails R1, R3, R5, R7, R8 (ver CLAUDE.md)
  - LC 123/2006 + LC 214/2025 + Lei 5.764/71 (delegado aos sub-validadores)

Rode com: pytest PY/tests/test_orquestrador_societario.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.orquestrador_societario import (  # noqa: E402
    Bloqueio,
    ResultadoOrquestracaoSocietaria,
    validar_combinacao,
)
from schemas.motor import EmpresaFornecedora  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _ltda_presumido(
    *,
    cnae: str = "4757100",
    faturamento: Decimal = Decimal("3000000.00"),
) -> EmpresaFornecedora:
    return EmpresaFornecedora(
        cnpj="11222333000181",
        razao_social="LTDA TESTE",
        regime="PRESUMIDO",
        cnae_principal=cnae,
        uf_origem="SP",
        faturamento_12m=faturamento,
        tipo_societario="LTDA",
    )


def _mei(
    *,
    cnae: str = "4757100",
    faturamento: Decimal = Decimal("60000.00"),
) -> EmpresaFornecedora:
    return EmpresaFornecedora(
        cnpj="07526557000100",
        razao_social="MEI TESTE",
        regime="MEI",
        cnae_principal=cnae,
        uf_origem="SP",
        faturamento_12m=faturamento,
        tipo_societario="EI",
        enquadramento_simples="MEI",
    )


def _coop_consumo(
    *,
    cnae: str = "4711301",
    faturamento: Decimal = Decimal("3000000.00"),
    receita_coop: Decimal = Decimal("2400000.00"),
    receita_nao_coop: Decimal = Decimal("600000.00"),
) -> EmpresaFornecedora:
    return EmpresaFornecedora(
        cnpj="33000167000101",
        razao_social="COOP CONSUMO TESTE",
        regime="PRESUMIDO",
        cnae_principal=cnae,
        uf_origem="SP",
        faturamento_12m=faturamento,
        tipo_societario="COOPERATIVA",
        subtipo_cooperativa="CONSUMO",
        receita_ato_cooperativo=receita_coop,
        receita_ato_nao_cooperativo=receita_nao_coop,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CASO FELIZ — combinação válida sem alertas
# ─────────────────────────────────────────────────────────────────────────────

class TestOrquestradorCasoFeliz:
    """Combinação plenamente válida."""

    def test_ltda_presumido_dentro_do_teto_passa(self):
        r = validar_combinacao(
            fornecedora=_ltda_presumido(),
            data_emissao=date(2027, 6, 15),
        )
        assert isinstance(r, ResultadoOrquestracaoSocietaria)
        assert r.valido is True
        assert r.bloqueios == ()
        assert r.engine_recomendado == "PRESUMIDO"
        assert r.overlay_aplicavel is None

    def test_mei_dentro_do_teto_passa(self):
        r = validar_combinacao(
            fornecedora=_mei(faturamento=Decimal("60000")),
            data_emissao=date(2027, 6, 15),
        )
        assert r.valido is True
        assert r.engine_recomendado == "MEI"

    def test_cooperativa_consumo_passa(self):
        r = validar_combinacao(
            fornecedora=_coop_consumo(),
            data_emissao=date(2027, 6, 15),
        )
        assert r.valido is True
        assert r.engine_recomendado == "PRESUMIDO"
        assert r.overlay_aplicavel == "COOPERATIVA"


# ─────────────────────────────────────────────────────────────────────────────
# AND LÓGICO — concatena TODAS as falhas
# ─────────────────────────────────────────────────────────────────────────────

class TestOrquestradorConcatenaFalhas:
    """Bloqueios de múltiplas origens aparecem todos no resultado."""

    def test_mei_com_tipo_societario_errado_e_acima_do_teto_concatena(self):
        # Combinação fiscalmente impossível pra forçar DOIS bloqueios:
        #   1. tipo_societario=LTDA com enquadramento_simples=MEI
        #      (MEI exige EI — Lei 14.195/2021 Art. 11)
        #   2. faturamento R$ 100k acima do teto MEI 81k
        #      (LC 123/2006 Art. 18-A § 1º)
        # Schema não bloqueia LTDA+MEI (validator cruzado é WS6 etapa 6
        # justamente pra isso). Orquestrador detecta os 2 e CONCATENA.
        emp = EmpresaFornecedora(
            cnpj="07526557000100",
            razao_social="LTDA COM ENQUADRAMENTO MEI ERRADO",
            regime="MEI",
            cnae_principal="4757100",
            uf_origem="SP",
            faturamento_12m=Decimal("100000.00"),
            tipo_societario="LTDA",
            enquadramento_simples="MEI",
        )
        r = validar_combinacao(
            fornecedora=emp,
            data_emissao=date(2027, 6, 15),
        )
        assert r.valido is False
        # Pelo menos 2 bloqueios — concatenação real (não pára na 1ª)
        assert len(r.bloqueios) >= 2, (
            f"Esperava >= 2 bloqueios concatenados, recebi {len(r.bloqueios)}: "
            f"{[b.mensagem for b in r.bloqueios]}"
        )
        msgs = " ".join(b.mensagem for b in r.bloqueios)
        # Bloqueio do teto MEI (faturamento > 81k)
        assert "teto" in msgs.lower() or "81" in msgs
        # Bloqueio do tipo societário errado (MEI exige EI)
        assert "EI" in msgs and "MEI" in msgs


# ─────────────────────────────────────────────────────────────────────────────
# MATRIZ SOCIETÁRIA — combinação inválida
# ─────────────────────────────────────────────────────────────────────────────

class TestOrquestradorMatrizSocietaria:
    """Combinação tipo×regime inválida pela matriz."""

    def test_associacao_simples_bloqueia(self):
        # ASSOCIACAO + SIMPLES = vedado pela matriz (não tem fins lucrativos)
        emp = EmpresaFornecedora(
            cnpj="12345678000195",
            razao_social="ASSOC TESTE",
            regime="SIMPLES",
            cnae_principal="9430800",
            uf_origem="SP",
            faturamento_12m=Decimal("100000"),
            tipo_societario="ASSOCIACAO",
        )
        r = validar_combinacao(
            fornecedora=emp,
            data_emissao=date(2027, 6, 15),
        )
        assert r.valido is False
        bloqueios_matriz = [b for b in r.bloqueios if b.origem == "MATRIZ_SOCIETARIA"]
        assert len(bloqueios_matriz) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# SUB-VALIDADOR MEI — chamado quando enquadramento=MEI
# ─────────────────────────────────────────────────────────────────────────────

class TestOrquestradorMEI:
    """Quando enquadramento_simples=MEI, validador MEI roda."""

    def test_mei_acima_do_teto_bloqueia(self):
        emp = _mei(faturamento=Decimal("100000.00"))  # acima 81k
        r = validar_combinacao(
            fornecedora=emp,
            data_emissao=date(2027, 6, 15),
        )
        assert r.valido is False
        bloqueios_mei = [b for b in r.bloqueios if b.origem == "VALIDADOR_MEI"]
        assert len(bloqueios_mei) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# SUB-VALIDADOR COOPERATIVA — chamado quando tipo_societario=COOPERATIVA
# ─────────────────────────────────────────────────────────────────────────────

class TestOrquestradorCooperativa:
    """Quando tipo_societario=COOPERATIVA, validador cooperativa roda."""

    def test_cooperativa_trabalho_no_simples_bloqueia(self):
        # Schema barra esse antes mesmo de chegar no orquestrador (model_validator).
        # Fica como guarda — orquestrador também detecta se passar.
        with pytest.raises(ValueError, match="3.{0,2}.{0,2}4"):
            EmpresaFornecedora(
                cnpj="33000167000101",
                razao_social="COOP TRABALHO SIMPLES",
                regime="SIMPLES",
                cnae_principal="8211300",
                uf_origem="SP",
                faturamento_12m=Decimal("1000000"),
                tipo_societario="COOPERATIVA",
                subtipo_cooperativa="TRABALHO",
                receita_ato_cooperativo=Decimal("800000"),
                receita_ato_nao_cooperativo=Decimal("200000"),
            )

    def test_cooperativa_passa_com_resultado_aplicavel_true(self):
        r = validar_combinacao(
            fornecedora=_coop_consumo(),
            data_emissao=date(2027, 6, 15),
        )
        # Validador cooperativa marcou aplicavel=True
        assert r.overlay_aplicavel == "COOPERATIVA"
        # Validador concatena base legal Lei 5.764
        amparos = " ".join(r.base_legal_aplicavel)
        assert "5.764" in amparos or "5764" in amparos


# ─────────────────────────────────────────────────────────────────────────────
# CNAE — vedação ou indeterminado
# ─────────────────────────────────────────────────────────────────────────────

class TestOrquestradorCNAE:
    """Resolução CNAE × Anexo via core.regras_cnae."""

    def test_cnae_resolvido_anexo_aparece_no_resultado(self):
        r = validar_combinacao(
            fornecedora=_ltda_presumido(cnae="4757100"),
            data_emissao=date(2027, 6, 15),
        )
        # PRESUMIDO não usa Anexo, mas resolução CNAE roda mesmo assim
        # como informação contextual. Pode ou não popular o campo.
        # Apenas testa que não quebra.
        assert isinstance(r, ResultadoOrquestracaoSocietaria)


# ─────────────────────────────────────────────────────────────────────────────
# LIMITES VERSIONADOS (Rail R3 + R7) — alerta migração obrigatória
# ─────────────────────────────────────────────────────────────────────────────

class TestOrquestradorLimitesRailR7:
    """Rail R7 — RBT12 ≥ 90% do teto Simples dispara alerta de migração."""

    def test_simples_proximo_do_teto_dispara_alerta_migracao(self):
        # Teto Simples ME/EPP: R$ 4.800.000. 90% = R$ 4.320.000.
        emp = EmpresaFornecedora(
            cnpj="11222333000181",
            razao_social="LTDA SIMPLES NO LIMITE",
            regime="SIMPLES",
            cnae_principal="4757100",
            uf_origem="SP",
            faturamento_12m=Decimal("4500000.00"),  # > 90% do teto
            tipo_societario="LTDA",
            anexo_simples="I",
        )
        r = validar_combinacao(
            fornecedora=emp,
            data_emissao=date(2027, 6, 15),
        )
        # Alerta presente, valido pode ser True (ainda dentro do teto)
        ids_alertas = {a.id for a in r.alertas}
        assert any("MIGRACAO" in i or "TETO" in i for i in ids_alertas)

    def test_presumido_acima_do_teto_78m_bloqueia(self):
        # Lucro Presumido: teto R$ 78M (Lei 12.814/13). Acima → Real obrigatório.
        emp = EmpresaFornecedora(
            cnpj="11222333000181",
            razao_social="LTDA PRESUMIDO ACIMA",
            regime="PRESUMIDO",
            cnae_principal="4757100",
            uf_origem="SP",
            faturamento_12m=Decimal("100000000.00"),  # 100M > 78M
            tipo_societario="LTDA",
        )
        r = validar_combinacao(
            fornecedora=emp,
            data_emissao=date(2027, 6, 15),
        )
        assert r.valido is False
        bloqueios_limite = [b for b in r.bloqueios if b.origem == "LIMITE_VERSIONADO"]
        assert len(bloqueios_limite) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# CRONOGRAMA TEMPORAL (Rail R8)
# ─────────────────────────────────────────────────────────────────────────────

class TestOrquestradorCronograma:
    """Schema já valida 2026-2033 em OperacaoFiscal; orquestrador é defensivo."""

    def test_data_em_2027_passa(self):
        r = validar_combinacao(
            fornecedora=_ltda_presumido(),
            data_emissao=date(2027, 6, 15),
        )
        assert r.valido is True

    def test_data_em_2026_passa(self):
        r = validar_combinacao(
            fornecedora=_ltda_presumido(),
            data_emissao=date(2026, 1, 15),
        )
        assert r.valido is True


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE_RECOMENDADO + OVERLAY_APLICAVEL
# ─────────────────────────────────────────────────────────────────────────────

class TestOrquestradorEngineRecomendado:
    """Resultado indica qual engine instanciar."""

    @pytest.mark.parametrize(
        "regime,esperado",
        [
            ("SIMPLES", "SIMPLES"),
            ("PRESUMIDO", "PRESUMIDO"),
            ("REAL", "REAL"),
            ("MEI", "MEI"),
        ],
    )
    def test_engine_recomendado_segue_regime(self, regime, esperado):
        kwargs_extras = (
            {"tipo_societario": "EI", "enquadramento_simples": "MEI"}
            if regime == "MEI"
            else {"tipo_societario": "LTDA"}
        )
        emp = EmpresaFornecedora(
            cnpj="11222333000181",
            razao_social="TESTE",
            regime=regime,
            cnae_principal="4757100",
            uf_origem="SP",
            faturamento_12m=Decimal("60000"),
            **kwargs_extras,
        )
        r = validar_combinacao(
            fornecedora=emp,
            data_emissao=date(2027, 6, 15),
        )
        assert r.engine_recomendado == esperado

    def test_overlay_cooperativa_quando_tipo_societario_eh_cooperativa(self):
        r = validar_combinacao(
            fornecedora=_coop_consumo(),
            data_emissao=date(2027, 6, 15),
        )
        assert r.overlay_aplicavel == "COOPERATIVA"

    def test_sem_overlay_quando_tipo_e_ltda(self):
        r = validar_combinacao(
            fornecedora=_ltda_presumido(),
            data_emissao=date(2027, 6, 15),
        )
        assert r.overlay_aplicavel is None


# ─────────────────────────────────────────────────────────────────────────────
# IMUTABILIDADE
# ─────────────────────────────────────────────────────────────────────────────

class TestOrquestradorImutabilidade:
    """ResultadoOrquestracaoSocietaria é frozen (Pydantic V2)."""

    def test_resultado_e_frozen(self):
        r = validar_combinacao(
            fornecedora=_ltda_presumido(),
            data_emissao=date(2027, 6, 15),
        )
        with pytest.raises(Exception):
            r.valido = False  # type: ignore[misc]

    def test_bloqueios_e_alertas_sao_tuple(self):
        r = validar_combinacao(
            fornecedora=_ltda_presumido(),
            data_emissao=date(2027, 6, 15),
        )
        assert isinstance(r.bloqueios, tuple)
        assert isinstance(r.alertas, tuple)
        assert isinstance(r.pendencias, tuple)
        assert isinstance(r.base_legal_aplicavel, tuple)

    def test_bloqueio_e_frozen(self):
        emp = _mei(faturamento=Decimal("100000"))
        r = validar_combinacao(
            fornecedora=emp,
            data_emissao=date(2027, 6, 15),
        )
        if r.bloqueios:
            b = r.bloqueios[0]
            assert isinstance(b, Bloqueio)
            with pytest.raises(Exception):
                b.mensagem = "alterado"  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRAÇÃO COM MOTOR — caller real (WS6 etapa 6)
# ─────────────────────────────────────────────────────────────────────────────

class TestMotorIntegracaoOrquestrador:
    """MotorReformaTributaria executa orquestrador no __init__ e expõe via getter."""

    def _operacao(self):
        from schemas.motor import OperacaoFiscal
        return OperacaoFiscal(
            data_emissao=date(2027, 6, 15),
            valor_operacao=Decimal("1000.00"),
            ncm_nbs="84713012",
        )

    def _compradora(self):
        from schemas.motor import EmpresaCompradora
        return EmpresaCompradora(tipo="B2B_CONTRIBUINTE", uf_destino="SP")

    def test_motor_expoe_validacao_societaria(self):
        from core.motor_tributario import MotorReformaTributaria

        motor = MotorReformaTributaria(
            fornecedora=_ltda_presumido(),
            compradora=self._compradora(),
            operacao=self._operacao(),
        )
        validacao = motor.obter_validacao_societaria()
        assert isinstance(validacao, ResultadoOrquestracaoSocietaria)
        assert validacao.valido is True
        assert validacao.engine_recomendado == "PRESUMIDO"

    def test_motor_registra_alerta_rail_r7_na_trilha_quando_proximo_teto(self):
        from core.motor_tributario import MotorReformaTributaria

        emp = EmpresaFornecedora(
            cnpj="11222333000181",
            razao_social="LTDA SIMPLES NO LIMITE",
            regime="SIMPLES",
            cnae_principal="4757100",
            uf_origem="SP",
            faturamento_12m=Decimal("4500000.00"),
            tipo_societario="LTDA",
            anexo_simples="I",
        )
        motor = MotorReformaTributaria(
            fornecedora=emp,
            compradora=self._compradora(),
            operacao=self._operacao(),
        )
        ids = {e["id"] for e in motor.trilha_auditoria}
        assert "ALERTA_TETO_SIMPLES_PROXIMO" in ids

    def test_motor_registra_bloqueio_na_trilha_quando_orquestrador_falha(self):
        from core.motor_tributario import MotorReformaTributaria

        # MEI acima do teto → orquestrador detecta
        emp = _mei(faturamento=Decimal("150000.00"))
        motor = MotorReformaTributaria(
            fornecedora=emp,
            compradora=self._compradora(),
            operacao=self._operacao(),
        )
        validacao = motor.obter_validacao_societaria()
        assert validacao.valido is False
        ids = {e["id"] for e in motor.trilha_auditoria}
        assert any(i.startswith("ALERTA_VALIDACAO_SOCIETARIA_BLOQUEIO_") for i in ids)

    def test_motor_cooperativa_marca_overlay_aplicavel(self):
        from core.motor_tributario import MotorReformaTributaria

        motor = MotorReformaTributaria(
            fornecedora=_coop_consumo(),
            compradora=self._compradora(),
            operacao=self._operacao(),
        )
        validacao = motor.obter_validacao_societaria()
        assert validacao.overlay_aplicavel == "COOPERATIVA"
        # Coexiste com obter_overlay_cooperativa() (etapa 5a)
        assert motor.obter_overlay_cooperativa() is not None
