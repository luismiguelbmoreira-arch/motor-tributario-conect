"""
test_diagnostico_consolidado.py — Testes do diagnóstico consolidado (Fase 0a).

Cobre o método ``MotorReformaTributaria.gerar_diagnostico_consolidado`` +
schemas + funções de agregação. Arquétipo 3 (Misto 50/50) é a fixture
concreta; arquétipos 1, 2, 4, 5 ficam como skip pendentes (Caso-Clínico
implementa quando Misto 50/50 estiver verde).

Blueprint: ~/.claude/plans/blueprint-diagnostico-consolidado.md
Curador: O Viciado (.claude/agents/o-viciado.md)
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.historico_consolidado import (  # noqa: E402
    _calcular_carga_tributaria_media,
    _calcular_hash_reprodutibilidade,
    _consolidar_recomendacao,
    _detectar_alertas_transicao,
    _detectar_sazonalidade,
    _detectar_tendencia,
)
from core.motor_tributario import MOTOR_VERSAO, MotorReformaTributaria  # noqa: E402
from schemas.diagnostico_consolidado import (  # noqa: E402
    DiagnosticoConsolidado,
    DiagnosticoConsolidadoComPII,
    DiagnosticoMensalResumo,
    NivelConfianca,
    RecomendacaoConsolidada,
    TendenciaRBT12,
)
from schemas.motor import (  # noqa: E402
    EmpresaCompradora,
    EmpresaFornecedora,
    OperacaoFiscal,
)
from tests.casos_clinicos.fixtures_arquetipos import (  # noqa: E402
    arquetipo_3_misto_5050,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _construir_motor_dummy() -> MotorReformaTributaria:
    """Motor com dados dummy só para chamar gerar_diagnostico_consolidado.

    Os dados dummy não interferem no consolidado — cada mês instancia seu
    próprio motor via _adaptar_mes_para_motor. Mas o construtor do motor
    principal exige uma tripla válida.
    """
    from datetime import date

    fornecedora = EmpresaFornecedora(
        cnpj="54657895000160",
        razao_social="Padaria Doce Manha LTDA",
        regime="SIMPLES",
        cnae_principal="4721102",
        uf_origem="SP",
        faturamento_12m=Decimal("100000"),
    )
    compradora = EmpresaCompradora(tipo="B2C_CONSUMIDOR_FINAL", uf_destino="SP")
    operacao = OperacaoFiscal(
        valor_operacao=Decimal("1000"),
        data_emissao=date(2026, 4, 30),
        ncm_nbs="61091000",
    )
    return MotorReformaTributaria(fornecedora, compradora, operacao)


# ═════════════════════════════════════════════════════════════════════════════
# Cenário 1 — Padaria Misto 50/50 (Arquétipo 3, fixture concreta)
# ═════════════════════════════════════════════════════════════════════════════


class TestArquetipo3PadariaMisto:
    """Cenário 1 do blueprint seção 6 — Padaria Misto 50/50."""

    def test_diagnostico_consolidado_e_gerado(self):
        """Smoke: o método executa sem erros sobre o histórico do Arquétipo 3."""
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        assert isinstance(diag, DiagnosticoConsolidado)

    def test_diagnostico_tem_6_meses_individuais(self):
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        assert len(diag.diagnosticos_meses) == 6
        for d in diag.diagnosticos_meses:
            assert isinstance(d, DiagnosticoMensalResumo)

    def test_competencias_inicio_e_fim_do_arquetipo_3(self):
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        assert diag.competencia_inicio == "2025-11"
        assert diag.competencia_fim == "2026-04"

    def test_cnpj_preservado_e_sem_razao_social_no_canonico(self):
        """LGPD: CNPJ entra; razao_social NÃO entra no DiagnosticoConsolidado."""
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        assert diag.cnpj == "54657895000160"
        # razão social não é campo do schema canônico (D3)
        assert "razao_social" not in diag.model_dump()

    def test_envelope_pii_aceita_razao_social(self):
        """DiagnosticoConsolidadoComPII envolve o canônico + razão social."""
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        envelope = DiagnosticoConsolidadoComPII(
            diagnostico=diag,
            razao_social=historico.razao_social,
        )
        assert envelope.razao_social == "Padaria Doce Manhã LTDA"
        assert envelope.diagnostico.cnpj == "54657895000160"

    def test_recomendacao_pertence_ao_conjunto_valido(self):
        """Recomendação é um dos 3 esperados pra padaria estável.

        Advisor: não trave num valor específico — valida que é um dos três
        e que a confiança não viola coerência (REVISAR_MANUALMENTE+ALTA).
        """
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        valores_aceitaveis = {
            RecomendacaoConsolidada.OPT_OUT,
            RecomendacaoConsolidada.MANTER_SIMPLES,
            RecomendacaoConsolidada.REVISAR_MANUALMENTE,
        }
        assert diag.recomendacao_regime in valores_aceitaveis
        # Coerência validador: REVISAR_MANUALMENTE → confianca != ALTA
        if diag.recomendacao_regime == RecomendacaoConsolidada.REVISAR_MANUALMENTE:
            assert diag.confianca != NivelConfianca.ALTA

    def test_tendencia_estavel_em_padaria_em_recuperacao_pos_natal(self):
        """Padaria misto: nov→abr varia +3% (RBT12 quase plano) — ESTAVEL."""
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        assert diag.tendencia_rbt12 == TendenciaRBT12.ESTAVEL

    def test_carga_min_max_dentro_do_range_da_carga_media(self):
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        assert diag.carga_min <= diag.carga_tributaria_media_6m <= diag.carga_max

    def test_competencias_carga_min_e_max_existem_nos_diagnosticos(self):
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        comps = {d.competencia for d in diag.diagnosticos_meses}
        assert diag.carga_min_competencia in comps
        assert diag.carga_max_competencia in comps

    def test_difal_e_split_payment_indisponivel_agregado(self):
        """D1 — agregação por mês perde precisão de DIFAL/Split."""
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        assert diag.difal_status == "INDISPONIVEL_AGREGADO"
        assert diag.split_payment_status == "INDISPONIVEL_AGREGADO"

    def test_versoes_preservadas(self):
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        assert diag.versao_schema == "1.0"
        assert diag.versao_motor == MOTOR_VERSAO
        assert diag.versao_lei == "LC123_2006_LC214_2025"

    def test_meta_avisos_de_heuristica_e_lgpd(self):
        """Avisos D2 e D3 obrigatórios na meta."""
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        assert "aviso_heuristicas" in diag.meta
        assert "aviso_lgpd" in diag.meta
        assert "agregacao" in diag.meta

    def test_trilha_unificada_inclui_passos_dos_meses(self):
        """Trilha consolida CALCULOs dos 6 motores mensais + entradas do adapter."""
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        assert len(diag.trilha_unificada) > 6  # vários passos por mês
        # NCM_AGREGADO_DEFAULT entra 1× por mês (6 entradas mínimas).
        ncm_entries = [
            e for e in diag.trilha_unificada
            if e.get("tipo") == "NCM_AGREGADO_DEFAULT"
        ]
        assert len(ncm_entries) == 6

    def test_votos_individuais_somam_6_quando_sem_gate_r7(self):
        """Padaria estável não dispara R7; votos somam 6 (1 por mês)."""
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        if "_GATE_R7" not in diag.votos_individuais:
            assert sum(diag.votos_individuais.values()) == 6

    def test_amparo_legal_nao_vazio(self):
        historico = arquetipo_3_misto_5050()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        assert len(diag.amparo_legal) >= 1
        for amparo in diag.amparo_legal:
            assert len(amparo) >= 10  # citação minimamente útil


# ═════════════════════════════════════════════════════════════════════════════
# Cenário 6 — Determinismo do hash de reprodutibilidade (Rail R6)
# ═════════════════════════════════════════════════════════════════════════════


class TestDeterminismoHash:
    """Hash de reprodutibilidade deve ser byte-a-byte estável.

    Advisor (bug 6): só o hash é determinístico — o objeto ``DiagnosticoConsolidado``
    inteiro NÃO é (timestamps via ``datetime.now`` na trilha). Comparar
    apenas ``hash_reprodutibilidade`` entre runs.
    """

    def test_hash_e_estavel_em_2_invocacoes_da_funcao_isolada(self):
        """Função pura — duas chamadas com fixture fresca dão o mesmo hash."""
        h1 = arquetipo_3_misto_5050()
        h2 = arquetipo_3_misto_5050()
        hash_1 = _calcular_hash_reprodutibilidade(
            h1, MOTOR_VERSAO, "LC123_2006_LC214_2025"
        )
        hash_2 = _calcular_hash_reprodutibilidade(
            h2, MOTOR_VERSAO, "LC123_2006_LC214_2025"
        )
        assert hash_1 == hash_2

    def test_hash_e_estavel_via_diagnostico_consolidado_completo(self):
        """End-to-end: gerar 2× o diagnóstico → hash igual."""
        historico_1 = arquetipo_3_misto_5050()
        motor_1 = _construir_motor_dummy()
        diag_1 = motor_1.gerar_diagnostico_consolidado(historico_1)

        historico_2 = arquetipo_3_misto_5050()
        motor_2 = _construir_motor_dummy()
        diag_2 = motor_2.gerar_diagnostico_consolidado(historico_2)

        assert diag_1.hash_reprodutibilidade == diag_2.hash_reprodutibilidade
        assert len(diag_1.hash_reprodutibilidade) == 64
        assert all(c in "0123456789abcdef" for c in diag_1.hash_reprodutibilidade)

    def test_hash_muda_quando_input_muda(self):
        """Sensibilidade: alterar 1 valor do input deve mudar o hash."""
        h1 = arquetipo_3_misto_5050()
        h2 = arquetipo_3_misto_5050()

        hash_1 = _calcular_hash_reprodutibilidade(
            h1, MOTOR_VERSAO, "LC123_2006_LC214_2025"
        )
        # Versão diferente → hash diferente.
        hash_diferente = _calcular_hash_reprodutibilidade(
            h2, "9.9.9", "LC123_2006_LC214_2025"
        )
        assert hash_1 != hash_diferente

    def test_hash_nao_inclui_razao_social_pii(self):
        """D3/LGPD: hash não vaza razão social."""
        h1 = arquetipo_3_misto_5050()
        hash_1 = _calcular_hash_reprodutibilidade(
            h1, MOTOR_VERSAO, "LC123_2006_LC214_2025"
        )

        # Constrói histórico com mesma estrutura mas razão social diferente.
        from copy import deepcopy
        h2 = arquetipo_3_misto_5050()
        h2_dump = h2.model_dump()
        h2_dump["razao_social"] = "Outra Empresa LTDA"
        from schemas.historico_seis_meses import HistoricoSeisMeses
        h2_modificado = HistoricoSeisMeses(**h2_dump)

        hash_2 = _calcular_hash_reprodutibilidade(
            h2_modificado, MOTOR_VERSAO, "LC123_2006_LC214_2025"
        )
        # Diferentes razões sociais, mesmo hash (PII excluída).
        assert hash_1 == hash_2


# ═════════════════════════════════════════════════════════════════════════════
# Cenário 7 — Validators de coerência do schema
# ═════════════════════════════════════════════════════════════════════════════


class TestValidadoresCoerenciaSchema:
    """Schema rejeita combinações fiscalmente impossíveis."""

    def _diag_minimo_valido(self) -> dict:
        """Constrói payload mínimo válido pra modificar nos testes."""
        from datetime import date

        meses = []
        for i, comp in enumerate([
            "2026-01", "2026-02", "2026-03",
            "2026-04", "2026-05", "2026-06",
        ]):
            meses.append(
                DiagnosticoMensalResumo(
                    competencia=comp,
                    rbt12_aplicado=Decimal("2000000"),
                    faturamento_mes=Decimal("160000"),
                    anexo_aplicado="I",
                    fator_r=Decimal("0.17"),
                    aliquota_efetiva=Decimal("0.099840"),
                    das_mensal=Decimal("16000.00"),
                    recomendacao_individual="MANTER_SIMPLES",
                )
            )

        return {
            "versao_schema": "1.0",
            "versao_motor": "1.2.0",
            "versao_lei": "LC123_2006_LC214_2025",
            "cnpj": "54657895000160",
            "competencia_referencia": date(2026, 6, 30),
            "competencia_inicio": "2026-01",
            "competencia_fim": "2026-06",
            "regime_atual": "SIMPLES",
            "tipo_societario": "ME",
            "hash_reprodutibilidade": "0" * 64,
            "diagnosticos_meses": meses,
            "faturamento_total_6m": Decimal("960000"),
            "das_total_6m": Decimal("96000"),
            "carga_tributaria_media_6m": Decimal("10.0000"),
            "carga_min": Decimal("10.0000"),
            "carga_max": Decimal("10.0000"),
            "carga_min_competencia": "2026-01",
            "carga_max_competencia": "2026-06",
            "tendencia_rbt12": TendenciaRBT12.ESTAVEL,
            "delta_rbt12_pct": Decimal("0.00"),
            "sazonalidade_detectada": False,
            "mes_pico": None,
            "mes_vale": None,
            "recomendacao_regime": RecomendacaoConsolidada.MANTER_SIMPLES,
            "confianca": NivelConfianca.ALTA,
            "justificativa": (
                "Padaria estável com perfil B2C predominante — manter regime "
                "Simples Nacional. Os 6 meses convergem para a mesma "
                "recomendação."
            ),
            "amparo_legal": ["LC 123/2006 Art. 18 §1º"],
            "votos_individuais": {"MANTER_SIMPLES": 6},
        }

    def test_sazonalidade_detectada_exige_pico_e_vale(self):
        """Coerência sazonalidade: True → ambos preenchidos."""
        payload = self._diag_minimo_valido()
        payload["sazonalidade_detectada"] = True
        # mes_pico/vale ainda None → deve falhar
        with pytest.raises(ValueError, match="mes_pico"):
            DiagnosticoConsolidado(**payload)

    def test_sem_sazonalidade_proibe_pico_e_vale(self):
        """Coerência sazonalidade: False → ambos None."""
        payload = self._diag_minimo_valido()
        payload["sazonalidade_detectada"] = False
        payload["mes_pico"] = "2026-03"
        with pytest.raises(ValueError, match="None"):
            DiagnosticoConsolidado(**payload)

    def test_pico_diferente_de_vale_quando_sazonal(self):
        payload = self._diag_minimo_valido()
        payload["sazonalidade_detectada"] = True
        payload["mes_pico"] = "2026-03"
        payload["mes_vale"] = "2026-03"
        with pytest.raises(ValueError, match="igual"):
            DiagnosticoConsolidado(**payload)

    def test_tendencia_ascendente_exige_delta_positivo(self):
        payload = self._diag_minimo_valido()
        payload["tendencia_rbt12"] = TendenciaRBT12.ASCENDENTE
        payload["delta_rbt12_pct"] = Decimal("-1.0")
        with pytest.raises(ValueError, match="ASCENDENTE"):
            DiagnosticoConsolidado(**payload)

    def test_tendencia_descendente_exige_delta_negativo(self):
        payload = self._diag_minimo_valido()
        payload["tendencia_rbt12"] = TendenciaRBT12.DESCENDENTE
        payload["delta_rbt12_pct"] = Decimal("5.0")
        with pytest.raises(ValueError, match="DESCENDENTE"):
            DiagnosticoConsolidado(**payload)

    def test_revisar_manualmente_nao_pode_ser_alta(self):
        payload = self._diag_minimo_valido()
        payload["recomendacao_regime"] = RecomendacaoConsolidada.REVISAR_MANUALMENTE
        payload["confianca"] = NivelConfianca.ALTA
        with pytest.raises(ValueError, match="REVISAR_MANUALMENTE"):
            DiagnosticoConsolidado(**payload)

    def test_carga_media_dentro_do_range_min_max(self):
        payload = self._diag_minimo_valido()
        payload["carga_min"] = Decimal("5.0000")
        payload["carga_max"] = Decimal("9.0000")
        payload["carga_tributaria_media_6m"] = Decimal("10.0000")  # fora
        with pytest.raises(ValueError, match="fora do range"):
            DiagnosticoConsolidado(**payload)

    def test_competencia_inicio_anterior_a_fim(self):
        payload = self._diag_minimo_valido()
        payload["competencia_inicio"] = "2026-06"
        payload["competencia_fim"] = "2026-01"
        with pytest.raises(ValueError, match="anterior"):
            DiagnosticoConsolidado(**payload)


# ═════════════════════════════════════════════════════════════════════════════
# Funções de agregação isoladas (testes unitários)
# ═════════════════════════════════════════════════════════════════════════════


class TestFuncoesAgregacao:
    """Funções privadas testadas isoladamente — sem rodar o motor."""

    def _diag_mes(self, comp: str, fat: str, das: str, codigo: str = "MANTER_SIMPLES"):
        return DiagnosticoMensalResumo(
            competencia=comp,
            rbt12_aplicado=Decimal("2000000"),
            faturamento_mes=Decimal(fat),
            anexo_aplicado="I",
            fator_r=Decimal("0.17"),
            aliquota_efetiva=Decimal("0.099840"),
            das_mensal=Decimal(das),
            recomendacao_individual=codigo,
        )

    def test_carga_tributaria_media_calcula_corretamente(self):
        diags = [
            self._diag_mes("2026-01", "100000", "5000"),
            self._diag_mes("2026-02", "100000", "5000"),
            self._diag_mes("2026-03", "100000", "5000"),
            self._diag_mes("2026-04", "100000", "5000"),
            self._diag_mes("2026-05", "100000", "5000"),
            self._diag_mes("2026-06", "100000", "5000"),
        ]
        media, c_min, c_min_comp, c_max, c_max_comp = (
            _calcular_carga_tributaria_media(diags)
        )
        # 5000 / 100000 = 5%
        assert media == Decimal("5.0000")
        assert c_min == Decimal("5.0000")
        assert c_max == Decimal("5.0000")

    def test_carga_min_max_em_meses_diferentes(self):
        diags = [
            self._diag_mes("2026-01", "100000", "10000"),  # 10%
            self._diag_mes("2026-02", "100000", "5000"),   # 5% min
            self._diag_mes("2026-03", "100000", "8000"),
            self._diag_mes("2026-04", "100000", "12000"),  # 12% max
            self._diag_mes("2026-05", "100000", "8000"),
            self._diag_mes("2026-06", "100000", "9000"),
        ]
        _, c_min, c_min_comp, c_max, c_max_comp = (
            _calcular_carga_tributaria_media(diags)
        )
        assert c_min_comp == "2026-02"
        assert c_max_comp == "2026-04"

    def test_consolidar_recomendacao_unanime_da_alta(self):
        from datetime import date

        from schemas.historico_seis_meses import (
            HistoricoSeisMeses,
            MesFiscal,
            OperacaoMensal,
        )

        # Histórico stub mínimo — RBT12 longe do gate R7.
        meses = []
        for i, comp in enumerate([
            "2026-01", "2026-02", "2026-03",
            "2026-04", "2026-05", "2026-06",
        ]):
            meses.append(
                MesFiscal(
                    competencia=comp,
                    rbt12_declarado=Decimal("500000"),
                    faturamento_mes=Decimal("50000"),
                    folha_pagamento_mes=Decimal("5000"),
                    folha_12m=Decimal("60000"),
                    anexo_aplicado="I",
                    fator_r_calculado=Decimal("0.12"),
                    operacoes=[
                        OperacaoMensal(
                            tipo="VENDA_B2C",
                            valor_total=Decimal("50000"),
                            quantidade_notas=100,
                            cnae_predominante="4721102",
                            forma_recebimento="PIX_DIRETO",
                        )
                    ],
                )
            )
        historico = HistoricoSeisMeses(
            cnpj="54657895000160",
            razao_social="Padaria Stub",
            regime_atual="SIMPLES",
            tipo_societario="ME",
            competencia_referencia=date(2026, 6, 30),
            meses=meses,
        )

        diags = [
            self._diag_mes(m.competencia, "50000", "2500", "MANTER_SIMPLES")
            for m in meses
        ]

        rec, conf, _, _, votos = _consolidar_recomendacao(
            historico, diags, TendenciaRBT12.ESTAVEL
        )
        assert rec == RecomendacaoConsolidada.MANTER_SIMPLES
        assert conf == NivelConfianca.ALTA
        assert votos == {"MANTER_SIMPLES": 6}

    def test_consolidar_recomendacao_5_6_vai_pra_revisar(self):
        """Ressalva R4: 5/6 votos vai pra REVISAR_MANUALMENTE."""
        from datetime import date

        from schemas.historico_seis_meses import (
            HistoricoSeisMeses,
            MesFiscal,
            OperacaoMensal,
        )

        meses = [
            MesFiscal(
                competencia=comp,
                rbt12_declarado=Decimal("500000"),
                faturamento_mes=Decimal("50000"),
                folha_pagamento_mes=Decimal("5000"),
                folha_12m=Decimal("60000"),
                anexo_aplicado="I",
                fator_r_calculado=Decimal("0.12"),
                operacoes=[
                    OperacaoMensal(
                        tipo="VENDA_B2C",
                        valor_total=Decimal("50000"),
                        quantidade_notas=100,
                        cnae_predominante="4721102",
                        forma_recebimento="PIX_DIRETO",
                    )
                ],
            )
            for comp in [
                "2026-01", "2026-02", "2026-03",
                "2026-04", "2026-05", "2026-06",
            ]
        ]
        historico = HistoricoSeisMeses(
            cnpj="54657895000160",
            razao_social="Padaria Stub",
            regime_atual="SIMPLES",
            tipo_societario="ME",
            competencia_referencia=date(2026, 6, 30),
            meses=meses,
        )

        # 5 OPT_OUT_FORTE + 1 MANTER_SIMPLES.
        codigos = ["OPT_OUT_FORTE"] * 5 + ["MANTER_SIMPLES"]
        diags = [
            self._diag_mes(m.competencia, "50000", "2500", c)
            for m, c in zip(meses, codigos)
        ]

        rec, conf, _, _, _ = _consolidar_recomendacao(
            historico, diags, TendenciaRBT12.ESTAVEL
        )
        assert rec == RecomendacaoConsolidada.REVISAR_MANUALMENTE
        assert conf == NivelConfianca.MEDIA

    def test_gate_r7_sobrescreve_votos(self):
        """Gate R7: RBT12 ≥ 90% teto → REVISAR_MANUALMENTE + BAIXA."""
        from datetime import date

        from schemas.historico_seis_meses import (
            HistoricoSeisMeses,
            MesFiscal,
            OperacaoMensal,
        )

        # 90% de R$ 4.8M = R$ 4.32M. Forçar 1 mês acima desse limiar
        # (e demais com RBT12 abaixo pra não estourar teto).
        meses = []
        for i, comp in enumerate([
            "2026-01", "2026-02", "2026-03",
            "2026-04", "2026-05", "2026-06",
        ]):
            rbt = Decimal("4400000") if i == 5 else Decimal("4000000")
            meses.append(
                MesFiscal(
                    competencia=comp,
                    rbt12_declarado=rbt,
                    faturamento_mes=Decimal("400000"),
                    folha_pagamento_mes=Decimal("30000"),
                    folha_12m=Decimal("360000"),
                    anexo_aplicado="I",
                    fator_r_calculado=Decimal("0.09"),
                    operacoes=[
                        OperacaoMensal(
                            tipo="VENDA_B2C",
                            valor_total=Decimal("400000"),
                            quantidade_notas=1000,
                            cnae_predominante="4721102",
                            forma_recebimento="PIX_DIRETO",
                        )
                    ],
                )
            )
        historico = HistoricoSeisMeses(
            cnpj="54657895000160",
            razao_social="Distribuidora Stub",
            regime_atual="SIMPLES",
            tipo_societario="EPP",
            competencia_referencia=date(2026, 6, 30),
            meses=meses,
        )

        diags = [
            self._diag_mes(m.competencia, "400000", "20000", "MANTER_SIMPLES")
            for m in meses
        ]
        rec, conf, _, amparo, votos = _consolidar_recomendacao(
            historico, diags, TendenciaRBT12.ESTAVEL
        )
        assert rec == RecomendacaoConsolidada.REVISAR_MANUALMENTE
        assert conf == NivelConfianca.BAIXA
        assert votos == {"_GATE_R7": 1}
        assert any("R7" in a for a in amparo)


# ═════════════════════════════════════════════════════════════════════════════
# Cenários 2-5 do blueprint — pendentes (Caso-Clínico cria fixtures depois)
# ═════════════════════════════════════════════════════════════════════════════


class TestCenariosPendentesBlueprint:
    """Cenários do blueprint seção 6 que dependem de fixtures que ainda
    não existem. Caso-Clínico implementa quando Misto 50/50 estiver verde."""

    @pytest.mark.skip(
        reason="Fixture arquetipo_5_proximo_sublimite pendente — Caso-Clínico"
    )
    def test_cenario_2_distribuidora_cruza_432m_no_mes_5(self):
        """Distribuidora cruza R$ 4.32M no mês 5 → REVISAR_MANUALMENTE BAIXA."""
        from tests.casos_clinicos.fixtures_arquetipos import (
            arquetipo_5_proximo_sublimite,
        )

        historico = arquetipo_5_proximo_sublimite()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        assert diag.recomendacao_regime == RecomendacaoConsolidada.REVISAR_MANUALMENTE
        assert diag.confianca == NivelConfianca.BAIXA
        tipos_alertas = [a.tipo for a in diag.alertas_transicao]
        assert "RBT12_90PCT_TETO" in tipos_alertas

    @pytest.mark.skip(
        reason="Fixture arquetipo_2_b2b_anexo_iii_fator_r pendente — Caso-Clínico"
    )
    def test_cenario_3_clinica_oscilando_fator_r(self):
        """Clínica oscilando F_R 0.27↔0.29 → ≥2 alertas FATOR_R_ATRAVESSOU_028."""
        from tests.casos_clinicos.fixtures_arquetipos import (
            arquetipo_2_b2b_anexo_iii_fator_r,
        )

        historico = arquetipo_2_b2b_anexo_iii_fator_r()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        alertas_fator_r = [
            a for a in diag.alertas_transicao
            if a.tipo == "FATOR_R_ATRAVESSOU_028"
        ]
        assert len(alertas_fator_r) >= 2

    @pytest.mark.skip(
        reason="Fixture arquetipo_4_b2b_anexo_v pendente — Caso-Clínico"
    )
    def test_cenario_4_software_house_b2b_60_b2c_40(self):
        """Software house MISTO → percentual_b2b adapter ~60.00."""
        from tests.casos_clinicos.fixtures_arquetipos import arquetipo_4_b2b_anexo_v

        historico = arquetipo_4_b2b_anexo_v()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        # Adapter calcula percentual_b2b mensal — verifica que o motor
        # rodou para mix B2B.
        assert diag is not None

    @pytest.mark.skip(
        reason="Fixture arquetipo_1_b2c_puro com pico sazonal pendente — Caso-Clínico"
    )
    def test_cenario_5_loja_sazonal_pico_dezembro(self):
        """Loja com dezembro = 5× média → sazonalidade=True, pico=dez."""
        from tests.casos_clinicos.fixtures_arquetipos import arquetipo_1_b2c_puro

        historico = arquetipo_1_b2c_puro()
        motor = _construir_motor_dummy()
        diag = motor.gerar_diagnostico_consolidado(historico)
        assert diag.sazonalidade_detectada is True
        assert diag.mes_pico is not None
        assert "12" in diag.mes_pico  # dezembro
