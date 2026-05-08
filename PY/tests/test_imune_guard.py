# -*- coding: utf-8 -*-
"""
tests/test_imune_guard.py — Camada 3: Testes do Engine IMUNE
Projeto: Motor Tributário Conect 2026-2033

PROPÓSITO: Garantir que o ImuneEngine funciona corretamente, que a Guard
Clause bloqueia uso indevido para outros regimes, e que toda análise IMUNE
gera os 3 ALERTAS críticos da LC 214/2025 (Arts. 9º §4º, 49 e 51 §1º) +
o ALERTA de receita não amparada quando aplicável.

BASE LEGAL (validada por Escrivão 2026-05-07 contra cache local):
  - LC 214/2025 Art. 9º caput + §§ 3º e 4º (cache lcp214 linhas 775-852)
  - LC 214/2025 Art. 49 (cache linhas 3973-3976)
  - LC 214/2025 Art. 51 caput + §1º (cache linhas 3992-3999)
  - CF/88 Art. 150 VI b/c (red. EC 132/2023) + §4º (cache cf linhas 18263-18265)
  - CTN Art. 14 incs. I-III + §§ 1º e 2º (cache ctn linhas 243-267)
  - STF RE 325.822/SP (Rel. Ilmar Galvão / Red. p/ acórdão Gilmar Mendes, j. 18/12/2002)
  - STF SV 52 (alínea c — IPTU; aplicável por analogia jurisprudencial a IBS/CBS)

Rode com: pytest PY/tests/test_imune_guard.py -v
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.motor_tributario import EmpresaFornecedora  # noqa: E402
from core.regimes.base import RegimeMismatchError  # noqa: E402
from core.regimes.imune import (  # noqa: E402
    ImunidadeNaoConfiguradaError,
    ImuneEngine,
)


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def trilha():
    return []


def _empresa_imune(
    *,
    subtipo: str,
    tipo_societario: str = "ORGANIZACAO_RELIGIOSA",
    receita_amparada: Decimal = Decimal("50000.00"),
    receita_nao_amparada: Decimal = Decimal("0.00"),
    requisitos_ctn14: tuple[bool, bool, bool] | None = None,
    vinculada_religiosa: bool = False,
):
    """Helper pra montar EmpresaFornecedora IMUNE com sane defaults."""
    return EmpresaFornecedora(
        cnpj="12345678000195",
        razao_social=f"ENTIDADE TESTE {subtipo}",
        regime="IMUNE",
        cnae_principal="9491000",
        uf_origem="SP",
        faturamento_12m=receita_amparada + receita_nao_amparada,
        tipo_societario=tipo_societario,
        subtipo_imune=subtipo,
        receita_amparada=receita_amparada,
        receita_nao_amparada=receita_nao_amparada,
        requisitos_ctn14_atendidos=requisitos_ctn14,
        vinculada_a_entidade_religiosa=vinculada_religiosa,
    )


@pytest.fixture
def empresa_simples():
    return EmpresaFornecedora(
        cnpj="54657895000160",
        razao_social="EMPRESA SIMPLES TESTE",
        regime="SIMPLES",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("1200000.00"),
        anexo_simples="I",
    )


@pytest.fixture
def empresa_presumida():
    return EmpresaFornecedora(
        cnpj="11222333000181",
        razao_social="EMPRESA PRESUMIDO TESTE",
        regime="PRESUMIDO",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("3000000.00"),
    )


@pytest.fixture
def empresa_real():
    return EmpresaFornecedora(
        cnpj="11222333000181",
        razao_social="EMPRESA REAL TESTE",
        regime="REAL",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("100000000.00"),
    )


@pytest.fixture
def empresa_mei():
    return EmpresaFornecedora(
        cnpj="07526557000100",
        razao_social="MEI TESTE",
        regime="MEI",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("60000.00"),
    )


@pytest.fixture
def empresa_imune_associacao_inciso_iii():
    """Associação inciso III com CTN 14 cumprido (caso feliz default)."""
    return EmpresaFornecedora(
        cnpj="12345678000195",
        razao_social="ASSOCIACAO ASSISTENCIAL TESTE",
        regime="IMUNE",
        cnae_principal="9430800",
        uf_origem="SP",
        faturamento_12m=Decimal("100000.00"),
        tipo_societario="ASSOCIACAO",
        subtipo_imune="ENTIDADE_ASSISTENCIAL",
        receita_amparada=Decimal("100000.00"),
        receita_nao_amparada=Decimal("0.00"),
        requisitos_ctn14_atendidos=(True, True, True),
        vinculada_a_entidade_religiosa=False,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CAMADA 2 — TESTES DE GUARD CLAUSE
# ─────────────────────────────────────────────────────────────────────────────

class TestImuneGuardClause:
    """Bloqueia uso do ImuneEngine para regimes incorretos."""

    def test_engine_rejeita_simples(self, empresa_simples, trilha):
        with pytest.raises(RegimeMismatchError) as exc:
            ImuneEngine(empresa_simples, trilha)
        assert "ImuneEngine" in str(exc.value)
        assert "SIMPLES" in str(exc.value)

    def test_engine_rejeita_presumido(self, empresa_presumida, trilha):
        with pytest.raises(RegimeMismatchError) as exc:
            ImuneEngine(empresa_presumida, trilha)
        assert "PRESUMIDO" in str(exc.value)

    def test_engine_rejeita_real(self, empresa_real, trilha):
        with pytest.raises(RegimeMismatchError) as exc:
            ImuneEngine(empresa_real, trilha)
        assert "REAL" in str(exc.value)

    def test_engine_rejeita_mei(self, empresa_mei, trilha):
        with pytest.raises(RegimeMismatchError) as exc:
            ImuneEngine(empresa_mei, trilha)
        assert "MEI" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────────────
# CÁLCULO BASE — IBS+CBS = R$ 0 sobre receita amparada
# ─────────────────────────────────────────────────────────────────────────────

class TestImuneCalculoBase:
    """LC 214/2025 Art. 9º caput — IBS+CBS = R$ 0 sobre receita amparada."""

    def test_templo_religioso_zera_ibs_cbs_sobre_amparada(self, trilha):
        emp = _empresa_imune(subtipo="TEMPLO_RELIGIOSO")
        engine = ImuneEngine(emp, trilha)
        r = engine.calcular_carga_total_mensal()
        assert r["regime"] == "IMUNE"
        assert r["ibs_amparada"] == Decimal("0.00")
        assert r["cbs_amparada"] == Decimal("0.00")
        assert r["total_mensal"] == Decimal("0.00")

    def test_partido_politico_zera_ibs_cbs(self, trilha):
        emp = _empresa_imune(
            subtipo="PARTIDO_POLITICO",
            tipo_societario="ASSOCIACAO",
            requisitos_ctn14=(True, True, True),
        )
        engine = ImuneEngine(emp, trilha)
        r = engine.calcular_carga_total_mensal()
        assert r["total_mensal"] == Decimal("0.00")

    def test_sindicato_trabalhador_zera_ibs_cbs(self, trilha):
        emp = _empresa_imune(
            subtipo="SINDICATO_TRABALHADOR",
            tipo_societario="ASSOCIACAO",
            requisitos_ctn14=(True, True, True),
        )
        engine = ImuneEngine(emp, trilha)
        r = engine.calcular_carga_total_mensal()
        assert r["total_mensal"] == Decimal("0.00")

    def test_entidade_educacional_zera_ibs_cbs(self, trilha):
        emp = _empresa_imune(
            subtipo="ENTIDADE_EDUCACIONAL_SEM_FINS_LUCRATIVOS",
            tipo_societario="FUNDACAO",
            requisitos_ctn14=(True, True, True),
        )
        engine = ImuneEngine(emp, trilha)
        r = engine.calcular_carga_total_mensal()
        assert r["total_mensal"] == Decimal("0.00")

    def test_entidade_assistencial_zera_ibs_cbs(self, trilha):
        emp = _empresa_imune(
            subtipo="ENTIDADE_ASSISTENCIAL",
            tipo_societario="ASSOCIACAO",
            requisitos_ctn14=(True, True, True),
        )
        engine = ImuneEngine(emp, trilha)
        r = engine.calcular_carga_total_mensal()
        assert r["total_mensal"] == Decimal("0.00")


# ─────────────────────────────────────────────────────────────────────────────
# RECEITA NÃO AMPARADA — engine NÃO calcula, só ALERTA (Rail R5)
# ─────────────────────────────────────────────────────────────────────────────

class TestImuneAtividadeMeio:
    """Engine não calcula receita não amparada — alerta + delegação externa."""

    def test_receita_nao_amparada_gera_alerta_sem_calcular(self, trilha):
        emp = _empresa_imune(
            subtipo="TEMPLO_RELIGIOSO",
            receita_amparada=Decimal("50000.00"),
            receita_nao_amparada=Decimal("5000.00"),
        )
        engine = ImuneEngine(emp, trilha)
        engine.calcular_carga_total_mensal()
        ids = {evento["id"] for evento in trilha}
        assert "ALERTA_IMUNE_NAO_AMPARADA_REQUER_ANALISE" in ids
        # Nada calculado sobre não-amparada
        evento_alerta = next(e for e in trilha if e["id"] == "ALERTA_IMUNE_NAO_AMPARADA_REQUER_ANALISE")
        assert "5000" in str(evento_alerta.get("memoria", {})) or "5000" in evento_alerta.get("detalhe", "")

    def test_receita_nao_amparada_zero_nao_emite_alerta(self, trilha):
        emp = _empresa_imune(
            subtipo="TEMPLO_RELIGIOSO",
            receita_amparada=Decimal("50000.00"),
            receita_nao_amparada=Decimal("0.00"),
        )
        engine = ImuneEngine(emp, trilha)
        engine.calcular_carga_total_mensal()
        ids = {evento["id"] for evento in trilha}
        assert "ALERTA_IMUNE_NAO_AMPARADA_REQUER_ANALISE" not in ids

    def test_alerta_cita_cf_art_150_par4(self, trilha):
        emp = _empresa_imune(
            subtipo="TEMPLO_RELIGIOSO",
            receita_nao_amparada=Decimal("1000.00"),
        )
        ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        evento = next(e for e in trilha if e["id"] == "ALERTA_IMUNE_NAO_AMPARADA_REQUER_ANALISE")
        amparo = evento.get("amparo_legal", "")
        assert "CF" in amparo and "150" in amparo and "§4" in amparo


# ─────────────────────────────────────────────────────────────────────────────
# 3 ALERTAS OBRIGATÓRIOS — sempre presentes em toda análise IMUNE
# ─────────────────────────────────────────────────────────────────────────────

class TestImuneAlertasObrigatorios:
    """Toda análise IMUNE precisa registrar os 3 ALERTAS críticos."""

    def test_alerta_aquisicao_nao_imune_sempre_presente(self, trilha):
        emp = _empresa_imune(subtipo="TEMPLO_RELIGIOSO")
        ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        ids = {e["id"] for e in trilha}
        assert "ALERTA_IMUNE_AQUISICAO_NAO_IMUNE" in ids
        evento = next(e for e in trilha if e["id"] == "ALERTA_IMUNE_AQUISICAO_NAO_IMUNE")
        assert "Art. 9" in evento.get("amparo_legal", "")
        assert "§ 4" in evento.get("amparo_legal", "") or "§4" in evento.get("amparo_legal", "")

    def test_alerta_anulacao_credito_proporcional_quando_ha_nao_amparada(self, trilha):
        emp = _empresa_imune(
            subtipo="TEMPLO_RELIGIOSO",
            receita_amparada=Decimal("50000.00"),
            receita_nao_amparada=Decimal("5000.00"),
        )
        ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        ids = {e["id"] for e in trilha}
        assert "ALERTA_IMUNE_ANULACAO_CREDITO_PROPORCIONAL" in ids
        evento = next(e for e in trilha if e["id"] == "ALERTA_IMUNE_ANULACAO_CREDITO_PROPORCIONAL")
        assert "Art. 51" in evento.get("amparo_legal", "")

    def test_alerta_b2b_nao_credita_sempre_presente(self, trilha):
        emp = _empresa_imune(subtipo="TEMPLO_RELIGIOSO")
        ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        ids = {e["id"] for e in trilha}
        assert "ALERTA_IMUNE_B2B_NAO_CREDITA" in ids
        evento = next(e for e in trilha if e["id"] == "ALERTA_IMUNE_B2B_NAO_CREDITA")
        assert "Art. 49" in evento.get("amparo_legal", "")


# ─────────────────────────────────────────────────────────────────────────────
# REQUISITOS CTN 14 — só inciso III (LC 214 Art. 9º §3º)
# ─────────────────────────────────────────────────────────────────────────────

class TestImuneRequisitosCTN14:
    """LC 214 Art. 9º §3º — CTN 14 vinculado APENAS ao inciso III."""

    def test_templo_dispensa_ctn14(self, trilha):
        # Templo é inciso II — não exige CTN 14 (requisitos_ctn14_atendidos=None)
        emp = _empresa_imune(subtipo="TEMPLO_RELIGIOSO", requisitos_ctn14=None)
        engine = ImuneEngine(emp, trilha)
        r = engine.calcular_carga_total_mensal()
        assert r["total_mensal"] == Decimal("0.00")

    def test_inciso_iii_sem_ctn14_levanta_imunidade_nao_configurada(self, trilha):
        # Partido (inciso III) sem requisitos_ctn14_atendidos → bloqueio
        emp = _empresa_imune(
            subtipo="PARTIDO_POLITICO",
            tipo_societario="ASSOCIACAO",
            requisitos_ctn14=None,
        )
        with pytest.raises(ImunidadeNaoConfiguradaError):
            ImuneEngine(emp, trilha).calcular_carga_total_mensal()

    def test_inciso_iii_com_ctn14_completo_passa(self, trilha):
        emp = _empresa_imune(
            subtipo="ENTIDADE_EDUCACIONAL_SEM_FINS_LUCRATIVOS",
            tipo_societario="FUNDACAO",
            requisitos_ctn14=(True, True, True),
        )
        r = ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        assert r["total_mensal"] == Decimal("0.00")

    def test_inciso_iii_com_ctn14_parcial_levanta(self, trilha):
        # Qualquer False = bloqueio (requisitos cumulativos)
        emp = _empresa_imune(
            subtipo="ENTIDADE_ASSISTENCIAL",
            tipo_societario="ASSOCIACAO",
            requisitos_ctn14=(True, False, True),
        )
        with pytest.raises(ImunidadeNaoConfiguradaError):
            ImuneEngine(emp, trilha).calcular_carga_total_mensal()

    def test_entidade_assistencial_vinculada_dispensa_ctn14(self, trilha):
        # Assistencial vinculada a templo cai no inciso II — dispensa CTN 14
        emp = _empresa_imune(
            subtipo="ENTIDADE_ASSISTENCIAL",
            tipo_societario="ORGANIZACAO_RELIGIOSA",
            vinculada_religiosa=True,
            requisitos_ctn14=None,
        )
        r = ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        assert r["total_mensal"] == Decimal("0.00")


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA — model_validator cruzado IMUNE × subtipo × tipo_societario
# ─────────────────────────────────────────────────────────────────────────────

class TestImuneSchemaValidator:
    """EmpresaFornecedora valida combinações IMUNE × tipo societário."""

    def test_regime_imune_sem_subtipo_levanta_erro(self):
        with pytest.raises(ValueError, match="subtipo_imune"):
            EmpresaFornecedora(
                cnpj="12345678000195", razao_social="ASSOC TESTE",
                regime="IMUNE", cnae_principal="9430800", uf_origem="SP",
                faturamento_12m=Decimal("1000"),
                tipo_societario="ASSOCIACAO",
            )

    def test_regime_imune_com_tipo_societario_ltda_levanta_erro(self):
        with pytest.raises(ValueError, match="incompatível"):
            EmpresaFornecedora(
                cnpj="12345678000195", razao_social="LTDA TESTE",
                regime="IMUNE", cnae_principal="4757100", uf_origem="SP",
                faturamento_12m=Decimal("1000"),
                tipo_societario="LTDA",
                subtipo_imune="ENTIDADE_ASSISTENCIAL",
            )

    def test_regime_imune_com_associacao_passa(self):
        emp = EmpresaFornecedora(
            cnpj="12345678000195", razao_social="ASSOC TESTE",
            regime="IMUNE", cnae_principal="9430800", uf_origem="SP",
            faturamento_12m=Decimal("1000"),
            tipo_societario="ASSOCIACAO",
            subtipo_imune="ENTIDADE_ASSISTENCIAL",
        )
        assert emp.regime == "IMUNE"

    def test_regime_imune_com_organizacao_religiosa_passa(self):
        emp = EmpresaFornecedora(
            cnpj="12345678000195", razao_social="IGREJA TESTE",
            regime="IMUNE", cnae_principal="9491000", uf_origem="SP",
            faturamento_12m=Decimal("1000"),
            tipo_societario="ORGANIZACAO_RELIGIOSA",
            subtipo_imune="TEMPLO_RELIGIOSO",
        )
        assert emp.tipo_societario == "ORGANIZACAO_RELIGIOSA"

    def test_regime_imune_com_fundacao_passa(self):
        emp = EmpresaFornecedora(
            cnpj="12345678000195", razao_social="FUNDACAO TESTE",
            regime="IMUNE", cnae_principal="9430800", uf_origem="SP",
            faturamento_12m=Decimal("1000"),
            tipo_societario="FUNDACAO",
            subtipo_imune="ENTIDADE_EDUCACIONAL_SEM_FINS_LUCRATIVOS",
        )
        assert emp.subtipo_imune == "ENTIDADE_EDUCACIONAL_SEM_FINS_LUCRATIVOS"


# ─────────────────────────────────────────────────────────────────────────────
# CITAÇÕES LEGAIS — anti-alucinação MAX_07
# ─────────────────────────────────────────────────────────────────────────────

class TestImuneCitacoesLegais:
    """Trilha precisa citar os artigos certos pra cada subtipo (MAX_07)."""

    def test_amparo_legal_templo_cita_re_325822_e_relator_correto(self, trilha):
        emp = _empresa_imune(subtipo="TEMPLO_RELIGIOSO")
        ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        amparos = " ".join(e.get("amparo_legal", "") for e in trilha)
        assert "RE 325.822" in amparos
        assert "Ilmar Galvão" in amparos
        assert "Gilmar Mendes" in amparos

    def test_amparo_legal_inciso_iii_cita_sv52_e_ctn14(self, trilha):
        emp = _empresa_imune(
            subtipo="ENTIDADE_EDUCACIONAL_SEM_FINS_LUCRATIVOS",
            tipo_societario="FUNDACAO",
            requisitos_ctn14=(True, True, True),
        )
        ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        amparos = " ".join(e.get("amparo_legal", "") for e in trilha)
        assert "SV 52" in amparos
        assert "CTN Art. 14" in amparos
        # SV 52 deve ser citada COMO ANALOGIA, não direta
        assert "analogia" in amparos.lower()

    def test_amparo_legal_aquisicao_cita_lc214_art9_par4(self, trilha):
        emp = _empresa_imune(subtipo="TEMPLO_RELIGIOSO")
        ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        evento = next(e for e in trilha if e["id"] == "ALERTA_IMUNE_AQUISICAO_NAO_IMUNE")
        amparo = evento["amparo_legal"]
        assert "LC 214/2025" in amparo
        assert "Art. 9" in amparo
        assert "§ 4" in amparo or "§4" in amparo

    def test_amparo_legal_anulacao_cita_lc214_art51_par1(self, trilha):
        emp = _empresa_imune(
            subtipo="TEMPLO_RELIGIOSO",
            receita_nao_amparada=Decimal("1000"),
        )
        ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        evento = next(e for e in trilha if e["id"] == "ALERTA_IMUNE_ANULACAO_CREDITO_PROPORCIONAL")
        amparo = evento["amparo_legal"]
        assert "LC 214/2025" in amparo
        assert "Art. 51" in amparo
        assert "§ 1" in amparo or "§1" in amparo

    def test_amparo_legal_b2b_cita_lc214_art49(self, trilha):
        emp = _empresa_imune(subtipo="TEMPLO_RELIGIOSO")
        ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        evento = next(e for e in trilha if e["id"] == "ALERTA_IMUNE_B2B_NAO_CREDITA")
        assert "LC 214/2025" in evento["amparo_legal"]
        assert "Art. 49" in evento["amparo_legal"]


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRAÇÃO COM O MOTOR — dispatcher + trilha unificada
# ─────────────────────────────────────────────────────────────────────────────

class TestImuneIntegracaoMotor:
    """ImuneEngine integra com MotorReformaTributaria via _instanciar_engine."""

    def test_dispatcher_instancia_imune_engine_para_regime_imune(
        self, empresa_imune_associacao_inciso_iii
    ):
        from datetime import date

        from core.motor_tributario import MotorReformaTributaria
        from schemas.motor import EmpresaCompradora, OperacaoFiscal

        compradora = EmpresaCompradora(tipo="B2B_CONTRIBUINTE", uf_destino="SP")
        operacao = OperacaoFiscal(
            data_emissao=date(2027, 1, 15),
            valor_operacao=Decimal("1000"),
            ncm_nbs="84713012",
        )
        motor = MotorReformaTributaria(
            fornecedora=empresa_imune_associacao_inciso_iii,
            compradora=compradora,
            operacao=operacao,
        )
        engine = motor.obter_engine_regime()
        assert engine is not None
        assert isinstance(engine, ImuneEngine)
        assert engine.REGIME_ACEITO == "IMUNE"

    def test_trilha_unificada_recebe_eventos_do_engine_imune(self, trilha):
        # Fixture com receita não-amparada > 0 pra disparar os 3 ALERTAS:
        # AQUISICAO + B2B (sempre) + ANULACAO_CREDITO (só com não-amparada)
        emp = _empresa_imune(
            subtipo="TEMPLO_RELIGIOSO",
            receita_amparada=Decimal("50000.00"),
            receita_nao_amparada=Decimal("5000.00"),
        )
        engine = ImuneEngine(emp, trilha)
        engine.calcular_carga_total_mensal()
        tipos = {e["tipo"] for e in trilha}
        assert "CALCULO" in tipos  # passo principal
        ids_alertas = {e["id"] for e in trilha if e.get("id", "").startswith("ALERTA_IMUNE_")}
        assert len(ids_alertas) >= 3
        assert "ALERTA_IMUNE_AQUISICAO_NAO_IMUNE" in ids_alertas
        assert "ALERTA_IMUNE_B2B_NAO_CREDITA" in ids_alertas
        assert "ALERTA_IMUNE_ANULACAO_CREDITO_PROPORCIONAL" in ids_alertas

    def test_violacao_levantada_via_registrar_violacao_da_base(
        self, empresa_simples
    ):
        # Engine errado → trilha registra VIOLACAO_SEGURANCA (Camada 2)
        trilha_local: list = []
        with pytest.raises(RegimeMismatchError):
            ImuneEngine(empresa_simples, trilha_local)
        # Mesmo com exceção, evento foi registrado antes
        tipos = {e["tipo"] for e in trilha_local}
        assert "VIOLACAO_SEGURANCA" in tipos


# ─────────────────────────────────────────────────────────────────────────────
# EDGE CASES — função pura, defaults, semântica fina
# ─────────────────────────────────────────────────────────────────────────────

class TestImuneEdgeCases:
    """Bordas do engine + helper puro `_inciso_aplicavel`."""

    def test_inciso_aplicavel_templo_sempre_ii(self):
        from core.regimes.imune import _inciso_aplicavel
        assert _inciso_aplicavel("TEMPLO_RELIGIOSO", False) == "II"
        assert _inciso_aplicavel("TEMPLO_RELIGIOSO", True) == "II"  # flag irrelevante

    def test_inciso_aplicavel_partido_sempre_iii(self):
        from core.regimes.imune import _inciso_aplicavel
        assert _inciso_aplicavel("PARTIDO_POLITICO", False) == "III"
        assert _inciso_aplicavel("PARTIDO_POLITICO", True) == "III"

    def test_inciso_aplicavel_assistencial_depende_da_flag(self):
        from core.regimes.imune import _inciso_aplicavel
        assert _inciso_aplicavel("ENTIDADE_ASSISTENCIAL", True) == "II"
        assert _inciso_aplicavel("ENTIDADE_ASSISTENCIAL", False) == "III"

    def test_templo_com_ctn14_extra_aceita(self, trilha):
        """Templo (II) não exige CTN 14, mas se cliente declarar não bloqueia."""
        emp = _empresa_imune(
            subtipo="TEMPLO_RELIGIOSO",
            requisitos_ctn14=(True, True, True),  # extra, ignorado
        )
        r = ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        assert r["total_mensal"] == Decimal("0.00")
        assert r["inciso_aplicavel"] == "II"

    def test_resultado_inclui_breakdown_completo(self, trilha):
        emp = _empresa_imune(
            subtipo="ENTIDADE_ASSISTENCIAL",
            tipo_societario="ASSOCIACAO",
            requisitos_ctn14=(True, True, True),
            receita_amparada=Decimal("100000.00"),
            receita_nao_amparada=Decimal("10000.00"),
        )
        r = ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        # Breakdown completo
        assert r["regime"] == "IMUNE"
        assert r["subtipo_imune"] == "ENTIDADE_ASSISTENCIAL"
        assert r["inciso_aplicavel"] == "III"
        assert r["receita_amparada"] == Decimal("100000.00")
        assert r["receita_nao_amparada"] == Decimal("10000.00")
        assert r["ibs_amparada"] == Decimal("0.00")
        assert r["cbs_amparada"] == Decimal("0.00")
        assert r["credito_iva_b2b_cliente"] == Decimal("0.00")  # Art. 49
        assert "trilha_auditoria" in r

    def test_violacao_ctn14_grava_evento_na_trilha_antes_de_levantar(self, trilha):
        emp = _empresa_imune(
            subtipo="PARTIDO_POLITICO",
            tipo_societario="ASSOCIACAO",
            requisitos_ctn14=(True, True, False),
        )
        with pytest.raises(ImunidadeNaoConfiguradaError):
            ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        ids = {e["id"] for e in trilha}
        assert "VIOLACAO_ImuneEngine_CTN14_NAO_ATENDIDO" in ids

    def test_proporcao_imunidade_calculada_corretamente_no_alerta(self, trilha):
        # 50k amparada / 5k não-amparada → proporção imune = 10/11 ≈ 0.909...
        emp = _empresa_imune(
            subtipo="TEMPLO_RELIGIOSO",
            receita_amparada=Decimal("50000.00"),
            receita_nao_amparada=Decimal("5000.00"),
        )
        ImuneEngine(emp, trilha).calcular_carga_total_mensal()
        evento = next(
            e for e in trilha
            if e["id"] == "ALERTA_IMUNE_ANULACAO_CREDITO_PROPORCIONAL"
        )
        proporcao = Decimal(evento["memoria"]["proporcao_imunidade"])
        # 50000 / 55000 = 0.9090909...
        assert proporcao > Decimal("0.90")
        assert proporcao < Decimal("0.91")
