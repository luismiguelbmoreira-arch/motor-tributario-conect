# -*- coding: utf-8 -*-
"""
tests/test_comparador_cenarios.py — Comparador de Cenários Fiscais.

Peça final do redesign: guia extraída (carga real) + perfil da empresa
→ ranking do melhor cenário fiscal por ano-alvo, no perímetro comparável.

VALORES ESPERADOS: todos gerados pelo MOTOR rodando (MAX_08/MAX_09) em
12/07/2026 — smoke-runs registrados na mensagem do commit. Nenhum número
calculado de cabeça.

Referências do motor (caso comércio, RPA 150k, RBT12 1,8M, Anexo I faixa 4):
  AE Simples = 9,45% → DAS 14.175,00
  Partilha federal (IRPJ 5,5 + CSLL 3,5 + COFINS 12,74 + PIS 2,76 = 24,5%)
    → perímetro MIGRAR_SIMPLES = 3.472,88
  ICMS no DAS (34%) = 4.819,50 | CPP (41,5%) = 5.882,63
  MANTER_PRESUMIDO 2026 = 8.830,20 federais + 1.500,00 CBS/IBS = 10.330,20
  MANTER_PRESUMIDO 2027 = 3.355,20 federais + 13.350,00 CBS/IBS = 16.705,20
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.comparador_cenarios import (  # noqa: E402
    AVISO_CSLL_BASE_IRPJ,
    AVISO_DEBITO_BRUTO,
    NAO_QUANTIFICADO,
    CenarioFiscal,
    ComparativoCenarios,
    PerfilEmpresa,
    comparar_cenarios,
)
from core.projetor_reforma import DocumentoFiscalExtraido  # noqa: E402

_AURORA_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "samples", "casos_clinicos", "aurora_pdfs_simulados",
)


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

def _doc_presumido(**kw) -> DocumentoFiscalExtraido:
    """Guia DARF de comércio no Presumido (valores de guia, não calculados)."""
    base = dict(
        cnpj="11222333000181",
        competencia=date(2026, 6, 1),
        regime_atual="PRESUMIDO",
        receita_bruta_mensal=Decimal("150000.00"),
        irpj_pago=Decimal("1800.00"),
        csll_paga=Decimal("1555.20"),
        pis_pago=Decimal("975.00"),
        cofins_paga=Decimal("4500.00"),
        icms_pago=Decimal("9000.00"),
    )
    base.update(kw)
    return DocumentoFiscalExtraido(**base)


def _doc_simples(**kw) -> DocumentoFiscalExtraido:
    """Guia DAS (partilha real paga — Anexo I faixa 4)."""
    base = dict(
        cnpj="11222333000181",
        competencia=date(2026, 6, 1),
        regime_atual="SIMPLES",
        receita_bruta_mensal=Decimal("150000.00"),
        irpj_pago=Decimal("779.63"),
        csll_paga=Decimal("496.13"),
        pis_pago=Decimal("391.23"),
        cofins_paga=Decimal("1805.90"),
        cpp_pago=Decimal("5882.63"),
        icms_pago=Decimal("4819.50"),
    )
    base.update(kw)
    return DocumentoFiscalExtraido(**base)


def _perfil_comercio(**kw) -> PerfilEmpresa:
    base = dict(
        cnae_principal="4711302",
        uf_origem="SP",
        faturamento_12m=Decimal("1800000.00"),
        folha_salarios_12m=Decimal("300000.00"),
    )
    base.update(kw)
    return PerfilEmpresa(**base)


def _cenario(r: ComparativoCenarios, id_: str) -> CenarioFiscal:
    return next(c for c in r.cenarios if c.id == id_)


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemas:
    def test_perfil_eh_frozen(self):
        p = _perfil_comercio()
        with pytest.raises(Exception):
            p.uf_origem = "RJ"  # type: ignore[misc]

    def test_perfil_extra_forbidden(self):
        with pytest.raises(Exception):
            PerfilEmpresa(
                cnae_principal="4711302", uf_origem="SP",
                faturamento_12m=Decimal("1"), campo_inventado=1,  # type: ignore[call-arg]
            )

    def test_perfil_faturamento_zero_rejeitado(self):
        with pytest.raises(Exception):
            _perfil_comercio(faturamento_12m=Decimal("0"))

    def test_comparativo_eh_frozen(self):
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        with pytest.raises(Exception):
            r.resultado = "INCONCLUSIVO"  # type: ignore[misc]

    def test_perfil_from_dados_extraidos(self):
        class Fake:
            cnae_principal = "4711302"
            uf_origem = "SP"
            faturamento_12m = "1.800.000,00"
            razao_social = "COMERCIO TESTE LTDA"
            folha_salarios_12m = "300000.00"

        p = PerfilEmpresa.from_dados_extraidos_pdf(Fake())
        assert p.faturamento_12m == Decimal("1800000.00")
        assert p.folha_salarios_12m == Decimal("300000.00")
        assert p.razao_social == "COMERCIO TESTE LTDA"

    def test_perfil_from_dados_com_override(self):
        class Fake:
            cnae_principal = "4711302"
            uf_origem = "SP"
            faturamento_12m = "1800000.00"
            folha_salarios_12m = None

        p = PerfilEmpresa.from_dados_extraidos_pdf(
            Fake(), lucro_real_mensal=Decimal("50000"),
        )
        assert p.lucro_real_mensal == Decimal("50000")
        assert p.folha_salarios_12m is None

    def test_insumos_creditaveis_reservado_aceito(self):
        # Campo reservado v2 (LC 214 Art. 47) — aceito no schema, não usado.
        p = _perfil_comercio(insumos_creditaveis_mensal=Decimal("10000"))
        assert p.insumos_creditaveis_mensal == Decimal("10000")


# ─────────────────────────────────────────────────────────────────────────────
# CENÁRIO MANTER — carga da guia, nunca recalculada
# ─────────────────────────────────────────────────────────────────────────────

class TestCenarioManter:
    def test_manter_usa_carga_da_guia(self):
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        manter = _cenario(r, "MANTER_PRESUMIDO")
        assert manter.origem_carga == "GUIA_EXTRAIDA"
        assert manter.status == "AVALIADO"
        # Motor 12/07/2026: 8.830,20 federais + 1.500,00 CBS/IBS (2026)
        assert manter.perimetro_comparavel_mensal == Decimal("10330.20")

    def test_manter_presumido_2027_pis_cofins_extintos(self):
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2027,
        )
        manter = _cenario(r, "MANTER_PRESUMIDO")
        # Motor: 3.355,20 (IRPJ+CSLL) + 13.350,00 (CBS 8,8% + IBS 0,1%)
        assert manter.perimetro_comparavel_mensal == Decimal("16705.20")
        assert manter.breakdown_perimetro["PIS_RESIDUAL"] == Decimal("0.00")
        assert manter.breakdown_perimetro["COFINS_RESIDUAL"] == Decimal("0.00")

    def test_manter_simples_perimetro_e_a_fracao_federal_da_guia(self):
        r = comparar_cenarios(
            documento=_doc_simples(), perfil=_perfil_comercio(), ano_alvo=2027,
        )
        manter = _cenario(r, "MANTER_SIMPLES")
        # Parcelas federais da guia: 779,63+496,13+391,23+1.805,90 = 3.472,89
        assert manter.perimetro_comparavel_mensal == Decimal("3472.89")
        assert manter.origem_carga == "GUIA_EXTRAIDA"

    def test_manter_simples_icms_conhecido_fora_do_perimetro(self):
        r = comparar_cenarios(
            documento=_doc_simples(), perfil=_perfil_comercio(), ano_alvo=2027,
        )
        manter = _cenario(r, "MANTER_SIMPLES")
        assert manter.fora_do_perimetro["ICMS"] == "4819.50"
        assert manter.fora_do_perimetro["CPP_EXCLUIDA_DO_RANKING"] == "5882.63"

    def test_manter_regime_normal_icms_residual_conhecido(self):
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2030,
        )
        manter = _cenario(r, "MANTER_PRESUMIDO")
        # ICMS residual 2030 = 9.000 × 0,8 (motor/projetor)
        assert manter.fora_do_perimetro["ICMS_RESIDUAL"] == "7200.00"

    def test_cpp_da_guia_nunca_entra_no_perimetro(self):
        r = comparar_cenarios(
            documento=_doc_simples(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        manter = _cenario(r, "MANTER_SIMPLES")
        assert "CPP" not in manter.breakdown_perimetro
        assert "CPP_EXCLUIDA_DO_RANKING" in manter.fora_do_perimetro


# ─────────────────────────────────────────────────────────────────────────────
# CENÁRIO MIGRAR_SIMPLES — motor (AE × RPA + partilha oficial)
# ─────────────────────────────────────────────────────────────────────────────

class TestMigrarSimples:
    def test_perimetro_via_motor_e_partilha(self):
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        mig = _cenario(r, "MIGRAR_SIMPLES")
        assert mig.status == "AVALIADO"
        assert mig.origem_carga == "MOTOR_PROJETADO"
        # Motor 12/07/2026: DAS 14.175,00 × 24,5% (fração federal Anexo I) = 3.472,88
        assert mig.perimetro_comparavel_mensal == Decimal("3472.88")
        assert mig.anexo_simples == "I"

    def test_icms_do_das_conhecido_e_fora_do_ranking(self):
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        mig = _cenario(r, "MIGRAR_SIMPLES")
        # Motor: DAS 14.175,00 × 34% = 4.819,50
        assert mig.fora_do_perimetro["ICMS"] == "4819.50"
        assert mig.fora_do_perimetro["CPP_EXCLUIDA_DO_RANKING"] == "5882.63"

    def test_breakdown_perimetro_soma_igual_ao_total(self):
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        mig = _cenario(r, "MIGRAR_SIMPLES")
        soma = sum(mig.breakdown_perimetro.values(), Decimal("0"))
        # Tolerância de arredondamento por parcela: R$ 0,02
        assert abs(soma - mig.perimetro_comparavel_mensal) <= Decimal("0.02")

    def test_aviso_aproximacao_partilha_em_2027(self):
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2027,
        )
        mig = _cenario(r, "MIGRAR_SIMPLES")
        assert any("APROXIMACAO_PARTILHA_LC155" in a for a in mig.avisos)

    def test_sem_aviso_aproximacao_em_2026(self):
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        mig = _cenario(r, "MIGRAR_SIMPLES")
        assert not any("APROXIMACAO_PARTILHA_LC155" in a for a in mig.avisos)

    def test_folha_ausente_gera_aviso_anexo_nao_confirmado(self):
        r = comparar_cenarios(
            documento=_doc_presumido(),
            perfil=_perfil_comercio(folha_salarios_12m=None),
            ano_alvo=2026,
        )
        mig = _cenario(r, "MIGRAR_SIMPLES")
        assert any("ANEXO_NAO_CONFIRMADO" in a for a in mig.avisos)

    def test_sublimite_icms_iss_vira_nao_quantificado(self):
        # RBT12 4,5M > sublimite 3,6M — ICMS/ISS por fora do DAS
        # (LC 123/2006, Arts. 13-A e 19, § 4º) → simetria com regimes normais.
        r = comparar_cenarios(
            documento=_doc_presumido(),
            perfil=_perfil_comercio(faturamento_12m=Decimal("4500000.00")),
            ano_alvo=2026,
        )
        mig = _cenario(r, "MIGRAR_SIMPLES")
        assert mig.fora_do_perimetro["ICMS"] == NAO_QUANTIFICADO
        assert mig.fora_do_perimetro["ISS"] == NAO_QUANTIFICADO
        assert any("SUBLIMITE" in a for a in mig.avisos)

    def test_acima_do_teto_simples_bloqueado_com_lei(self):
        r = comparar_cenarios(
            documento=_doc_presumido(),
            perfil=_perfil_comercio(faturamento_12m=Decimal("6000000.00")),
            ano_alvo=2026,
        )
        mig = _cenario(r, "MIGRAR_SIMPLES")
        assert mig.status == "BLOQUEADO"
        assert "4800000" in mig.motivo.replace(".", "").replace(",", "") or \
            "LC 123" in " ".join(mig.base_legal)

    # ── Anexos II/III/V — fix do achado CRITICO do PMD (KeyError) ────────
    # Cada anexo só traz as chaves dos SEUS tributos na partilha:
    # II tem ICMS+IPI (sem ISS); III/IV/V têm ISS (sem ICMS).
    # Valores esperados: motor rodando em 12/07/2026 (smoke-run pós-fix).

    def test_anexo_ii_industria_nao_explode_e_traz_ipi(self):
        r = comparar_cenarios(
            documento=_doc_presumido(),
            perfil=_perfil_comercio(cnae_principal="1091101"),
            ano_alvo=2027,
        )
        mig = _cenario(r, "MIGRAR_SIMPLES")
        assert mig.status == "AVALIADO"
        assert mig.anexo_simples == "II"
        assert mig.perimetro_comparavel_mensal == Decimal("3432.75")
        assert mig.fora_do_perimetro["ICMS"] == "4776.00"
        assert mig.fora_do_perimetro["ISS"] == "0.00"   # II não tem ISS
        assert mig.fora_do_perimetro["IPI"] == "1119.38"  # IPI na partilha II

    def test_anexo_iii_servico_fator_r_alto(self):
        # Folha 600k / RBT12 1,8M → Fator R 33% ≥ 28% → Anexo III
        r = comparar_cenarios(
            documento=_doc_presumido(),
            perfil=_perfil_comercio(
                cnae_principal="6201501",
                folha_salarios_12m=Decimal("600000.00"),
            ),
            ano_alvo=2027,
        )
        mig = _cenario(r, "MIGRAR_SIMPLES")
        assert mig.status == "AVALIADO"
        assert mig.anexo_simples == "III"
        assert mig.perimetro_comparavel_mensal == Decimal("5068.23")
        assert mig.fora_do_perimetro["ISS"] == "6834.75"
        assert mig.fora_do_perimetro["ICMS"] == "0.00"  # III não tem ICMS

    def test_anexo_v_servico_fator_r_baixo(self):
        # Folha 300k / RBT12 1,8M → Fator R 16,7% < 28% → Anexo V
        r = comparar_cenarios(
            documento=_doc_presumido(),
            perfil=_perfil_comercio(cnae_principal="6201501"),
            ano_alvo=2027,
        )
        mig = _cenario(r, "MIGRAR_SIMPLES")
        assert mig.status == "AVALIADO"
        assert mig.anexo_simples == "V"
        assert mig.perimetro_comparavel_mensal == Decimal("16172.74")
        assert mig.fora_do_perimetro["ISS"] == "6158.25"

    def test_servico_sem_folha_cai_no_anexo_v_conservador(self):
        r = comparar_cenarios(
            documento=_doc_presumido(),
            perfil=_perfil_comercio(
                cnae_principal="6201501", folha_salarios_12m=None,
            ),
            ano_alvo=2027,
        )
        mig = _cenario(r, "MIGRAR_SIMPLES")
        assert mig.status == "AVALIADO"
        assert mig.anexo_simples == "V"
        assert mig.fator_r is None
        assert any("ANEXO_NAO_CONFIRMADO" in a for a in mig.avisos)

    def test_nao_gera_cenario_migrar_pro_proprio_regime(self):
        r = comparar_cenarios(
            documento=_doc_simples(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        assert all(c.id != "MIGRAR_SIMPLES" for c in r.cenarios)
        assert any(c.id == "MANTER_SIMPLES" for c in r.cenarios)


# ─────────────────────────────────────────────────────────────────────────────
# CENÁRIOS MIGRAR_PRESUMIDO / MIGRAR_REAL — engines + projetor
# ─────────────────────────────────────────────────────────────────────────────

class TestMigrarRegimesNormais:
    def test_migrar_presumido_avaliado_com_rotulo_bruto(self):
        r = comparar_cenarios(
            documento=_doc_simples(), perfil=_perfil_comercio(), ano_alvo=2027,
        )
        mig = _cenario(r, "MIGRAR_PRESUMIDO")
        assert mig.status == "AVALIADO"
        # Motor 12/07/2026: engine Presumido + CBS/IBS 2027 = 16.770,00
        assert mig.perimetro_comparavel_mensal == Decimal("16770.00")
        assert AVISO_DEBITO_BRUTO in mig.avisos

    def test_migrar_presumido_icms_iss_cpp_nao_quantificados(self):
        r = comparar_cenarios(
            documento=_doc_simples(), perfil=_perfil_comercio(), ano_alvo=2027,
        )
        mig = _cenario(r, "MIGRAR_PRESUMIDO")
        assert mig.fora_do_perimetro["ICMS"] == NAO_QUANTIFICADO
        assert mig.fora_do_perimetro["ISS"] == NAO_QUANTIFICADO
        assert NAO_QUANTIFICADO in mig.fora_do_perimetro["CPP_EXCLUIDA_DO_RANKING"]

    def test_migrar_real_sem_dre_nao_avaliado(self):
        # Anti-chute (Rail R2): sem DRE, cenário Real NÃO é estimado.
        r = comparar_cenarios(
            documento=_doc_simples(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        mig = _cenario(r, "MIGRAR_REAL")
        assert mig.status == "NAO_AVALIADO"
        assert "DRE" in mig.motivo
        assert mig.perimetro_comparavel_mensal is None

    def test_migrar_real_com_dre_avaliado_e_carimbado(self):
        r = comparar_cenarios(
            documento=_doc_simples(),
            perfil=_perfil_comercio(lucro_real_mensal=Decimal("30000.00")),
            ano_alvo=2026,
        )
        mig = _cenario(r, "MIGRAR_REAL")
        assert mig.status == "AVALIADO"
        assert AVISO_CSLL_BASE_IRPJ in mig.avisos
        assert AVISO_DEBITO_BRUTO in mig.avisos

    def test_documento_sintetico_projetado_pelo_mesmo_projetor(self):
        # 2033: cenário Presumido tem CBS+IBS plenos no perímetro
        r = comparar_cenarios(
            documento=_doc_simples(), perfil=_perfil_comercio(), ano_alvo=2033,
        )
        mig = _cenario(r, "MIGRAR_PRESUMIDO")
        # CBS+IBS 2033 = 150.000 × 26,5% = 39.750 (CRONOGRAMA_IVA — motor)
        assert mig.breakdown_perimetro["CBS"] + mig.breakdown_perimetro["IBS"] == \
            Decimal("39750.00")


# ─────────────────────────────────────────────────────────────────────────────
# VIABILIDADE SOCIETÁRIA — bloqueios exibidos com lei, nunca omitidos
# ─────────────────────────────────────────────────────────────────────────────

class TestViabilidadeSocietaria:
    def test_cenario_bloqueado_permanece_na_lista(self):
        r = comparar_cenarios(
            documento=_doc_presumido(),
            perfil=_perfil_comercio(faturamento_12m=Decimal("6000000.00")),
            ano_alvo=2026,
        )
        ids = [c.id for c in r.cenarios]
        assert "MIGRAR_SIMPLES" in ids  # bloqueado ≠ omitido (MAX_04)

    def test_bloqueio_carrega_base_legal(self):
        r = comparar_cenarios(
            documento=_doc_presumido(),
            perfil=_perfil_comercio(faturamento_12m=Decimal("6000000.00")),
            ano_alvo=2026,
        )
        mig = _cenario(r, "MIGRAR_SIMPLES")
        assert mig.status == "BLOQUEADO"
        assert mig.motivo  # mensagem nunca vazia

    def test_bloqueados_ordenados_depois_dos_avaliados(self):
        r = comparar_cenarios(
            documento=_doc_presumido(),
            perfil=_perfil_comercio(faturamento_12m=Decimal("6000000.00")),
            ano_alvo=2026,
        )
        status_seq = [c.status for c in r.cenarios]
        primeiro_nao_avaliado = next(
            (i for i, s in enumerate(status_seq) if s != "AVALIADO"),
            len(status_seq),
        )
        assert all(s == "AVALIADO" for s in status_seq[:primeiro_nao_avaliado])


# ─────────────────────────────────────────────────────────────────────────────
# RANKING + GUARDA ANTI-FALSO-VENCEDOR
# ─────────────────────────────────────────────────────────────────────────────

class TestRankingEGuarda:
    def test_vencedor_definido_quando_delta_supera_piso(self):
        # Motor 12/07/2026: manter 10.330,20 vs migrar 3.472,88 →
        # Δ 6.857,32 > piso 4.819,50 (ICMS do DAS) → vencedor declarado.
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        assert r.resultado == "VENCEDOR_DEFINIDO"
        assert r.melhor_cenario_id == "MIGRAR_SIMPLES"
        assert r.economia_mensal_vs_manter == Decimal("6857.32")
        assert r.economia_anual_vs_manter == Decimal("82287.84")
        assert r.piso_nao_comparado_mensal == Decimal("4819.50")

    def test_inconclusivo_quando_delta_menor_que_piso(self):
        # Guia com federais baixos: manter 5.700,00 vs migrar 3.472,88 →
        # Δ 2.227,12 < piso 4.819,50 → INCONCLUSIVO (motor 12/07/2026).
        doc = _doc_presumido(
            irpj_pago=Decimal("1200.00"),
            csll_paga=Decimal("1000.00"),
            pis_pago=Decimal("500.00"),
            cofins_paga=Decimal("1500.00"),
        )
        r = comparar_cenarios(
            documento=doc, perfil=_perfil_comercio(), ano_alvo=2026,
        )
        assert r.resultado == "INCONCLUSIVO"
        assert r.melhor_cenario_id is None
        assert r.economia_mensal_vs_manter is None
        assert any(a["id"] == "ALERTA_RANKING_INCONCLUSIVO" for a in r.alertas)

    def test_manter_vencedor_economia_zero(self):
        # Simples atual mais barato que migrar → manter vence, economia 0.
        r = comparar_cenarios(
            documento=_doc_simples(), perfil=_perfil_comercio(), ano_alvo=2027,
        )
        assert r.resultado == "VENCEDOR_DEFINIDO"
        assert r.melhor_cenario_id == "MANTER_SIMPLES"
        assert r.economia_mensal_vs_manter == Decimal("0.00")
        # Sem migração não há guarda a aplicar
        assert r.piso_nao_comparado_mensal == Decimal("0.00")

    def test_sem_comparacao_quando_so_um_avaliado(self):
        # Aurora-like: migrações bloqueadas → só MANTER avaliado.
        r = comparar_cenarios(
            documento=_doc_presumido(
                receita_bruta_mensal=Decimal("7916666.67"),
            ),
            perfil=_perfil_comercio(faturamento_12m=Decimal("95000000.00")),
            ano_alvo=2027,
        )
        assert r.resultado == "SEM_COMPARACAO"
        assert r.melhor_cenario_id == "MANTER_PRESUMIDO"

    def test_avaliados_ordenados_por_perimetro_crescente(self):
        r = comparar_cenarios(
            documento=_doc_simples(),
            perfil=_perfil_comercio(lucro_real_mensal=Decimal("30000.00")),
            ano_alvo=2027,
        )
        perimetros = [
            c.perimetro_comparavel_mensal
            for c in r.cenarios if c.status == "AVALIADO"
        ]
        assert perimetros == sorted(perimetros)

    def test_piso_conta_so_o_lado_simples_da_comparacao(self):
        # Comparação PRESUMIDO(manter) × SIMPLES(migrar): piso = ICMS+ISS
        # do DAS do lado Simples (4.819,50 + 0,00) — motor 12/07/2026.
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        assert r.piso_nao_comparado_mensal == Decimal("4819.50")


# ─────────────────────────────────────────────────────────────────────────────
# ALERTAS NÃO SUPRESSÍVEIS
# ─────────────────────────────────────────────────────────────────────────────

class TestAlertas:
    def test_ranking_parcial_quando_ha_cenario_simples(self):
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        assert any(a["id"] == "ALERTA_RANKING_PARCIAL" for a in r.alertas)

    def test_debito_bruto_quando_ha_cenario_normal_projetado(self):
        r = comparar_cenarios(
            documento=_doc_simples(), perfil=_perfil_comercio(), ano_alvo=2027,
        )
        assert any(
            a["id"] == "ALERTA_DEBITO_BRUTO_SEM_CREDITOS" for a in r.alertas
        )

    def test_ipi_pos_2027_alertado(self):
        doc = _doc_presumido(ipi_pago=Decimal("5000.00"))
        r = comparar_cenarios(
            documento=doc, perfil=_perfil_comercio(), ano_alvo=2027,
        )
        alerta = next(a for a in r.alertas if a["id"] == "ALERTA_IPI_POS_2027")
        assert "Zona Franca" in alerta["detalhe"]
        assert "ADCT" in alerta["amparo_legal"]

    def test_sem_alerta_ipi_em_2026(self):
        doc = _doc_presumido(ipi_pago=Decimal("5000.00"))
        r = comparar_cenarios(
            documento=doc, perfil=_perfil_comercio(), ano_alvo=2026,
        )
        assert not any(a["id"] == "ALERTA_IPI_POS_2027" for a in r.alertas)

    def test_todo_alerta_tem_amparo_legal(self):
        r = comparar_cenarios(
            documento=_doc_presumido(ipi_pago=Decimal("100")),
            perfil=_perfil_comercio(),
            ano_alvo=2027,
        )
        assert r.alertas
        assert all(a.get("amparo_legal") for a in r.alertas)


# ─────────────────────────────────────────────────────────────────────────────
# TRILHA DE AUDITORIA — MAX_01/MAX_02
# ─────────────────────────────────────────────────────────────────────────────

class TestTrilhaAuditoria:
    def test_todo_passo_calculo_tem_amparo_legal(self):
        r = comparar_cenarios(
            documento=_doc_presumido(),
            perfil=_perfil_comercio(lucro_real_mensal=Decimal("30000.00")),
            ano_alvo=2027,
        )
        passos = [p for p in r.trilha_auditoria if p.get("tipo") == "CALCULO"]
        assert passos
        assert all(p.get("amparo_legal") for p in passos)

    def test_trilha_tem_perimetro_de_cada_cenario_avaliado(self):
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        ids = {p["id"] for p in r.trilha_auditoria}
        assert "COMPARADOR_PERIMETRO_MANTER_PRESUMIDO" in ids
        assert "COMPARADOR_PERIMETRO_MIGRAR_SIMPLES" in ids
        assert "COMPARADOR_RANKING" in ids

    def test_formula_do_perimetro_traz_valores(self):
        # MAX_01: Base → Alíquota → Valor visíveis na fórmula
        r = comparar_cenarios(
            documento=_doc_presumido(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        passo = next(
            p for p in r.trilha_auditoria
            if p["id"] == "COMPARADOR_PERIMETRO_MIGRAR_SIMPLES"
        )
        assert "DAS" in passo["formula"]
        assert "14175.00" in passo["formula"]

    def test_engine_do_regime_normal_registra_na_trilha_unificada(self):
        r = comparar_cenarios(
            documento=_doc_simples(), perfil=_perfil_comercio(), ano_alvo=2026,
        )
        ids = {p.get("id") for p in r.trilha_auditoria}
        assert "CARGA_TOTAL_PRESUMIDO" in ids  # trilha do engine incorporada


# ─────────────────────────────────────────────────────────────────────────────
# AURORA — caso clínico end-to-end (fixture do redesign)
# ─────────────────────────────────────────────────────────────────────────────

class _FakeDados:
    def __init__(self, d: dict):
        for k, v in d.items():
            setattr(self, k, v)


@pytest.fixture()
def aurora_doc_e_perfil():
    with open(os.path.join(_AURORA_DIR, "das_competencia_2026-06.json")) as f:
        dados = _FakeDados(json.load(f))
    doc = DocumentoFiscalExtraido.from_dados_extraidos_pdf(dados, regime_atual="REAL")
    perfil = PerfilEmpresa.from_dados_extraidos_pdf(
        dados, lucro_real_mensal=Decimal("200000.00"),
    )
    return doc, perfil


class TestAuroraEndToEnd:
    def test_manter_real_perimetro_bate_com_parecer(self, aurora_doc_e_perfil):
        # Parecer Luiz Moreira 12/07/2026 (rodado pelo motor):
        # perímetro comparável MANTER_REAL 2027 = 770.266,64
        doc, perfil = aurora_doc_e_perfil
        r = comparar_cenarios(documento=doc, perfil=perfil, ano_alvo=2027)
        manter = _cenario(r, "MANTER_REAL")
        assert manter.perimetro_comparavel_mensal == Decimal("770266.64")

    def test_migracoes_bloqueadas_com_lei(self, aurora_doc_e_perfil):
        doc, perfil = aurora_doc_e_perfil
        r = comparar_cenarios(documento=doc, perfil=perfil, ano_alvo=2027)
        simples = _cenario(r, "MIGRAR_SIMPLES")
        presumido = _cenario(r, "MIGRAR_PRESUMIDO")
        assert simples.status == "BLOQUEADO"
        assert presumido.status == "BLOQUEADO"
        assert "4800000" in simples.motivo.replace(".", "")
        assert "78000000" in presumido.motivo.replace(".", "")

    def test_resultado_sem_comparacao(self, aurora_doc_e_perfil):
        doc, perfil = aurora_doc_e_perfil
        r = comparar_cenarios(documento=doc, perfil=perfil, ano_alvo=2027)
        assert r.resultado == "SEM_COMPARACAO"
        assert r.melhor_cenario_id == "MANTER_REAL"

    @pytest.mark.parametrize("ano", [2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033])
    def test_todos_os_anos_da_transicao(self, aurora_doc_e_perfil, ano):
        doc, perfil = aurora_doc_e_perfil
        r = comparar_cenarios(documento=doc, perfil=perfil, ano_alvo=ano)
        assert r.ano_alvo == ano
        assert isinstance(r, ComparativoCenarios)
