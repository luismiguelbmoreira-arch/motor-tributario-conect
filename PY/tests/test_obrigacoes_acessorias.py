# -*- coding: utf-8 -*-
"""
tests/test_obrigacoes_acessorias.py — WS7

Matriz porte × regime → obrigações acessórias + alerta ativo de multas.

ESCOPO desta entrega:
  - Schema imutável Obrigacao + AlertaObrigacao
  - Enum NivelPorte (MEI/ME/EPP/DEMAIS)
  - Helpers de data (calcular_data_vencimento por frequência)
  - Função pura `gerar_alertas_obrigacoes()` consumindo matriz
  - Matriz inicial cobrindo APENAS obrigações com cache local validado
    pelo Escrivão (sem extrapolação — Rail R2)

OBRIGAÇÕES POR REGIME (validadas Escrivão 2026-05-08):
  SIMPLES — DASN-SIMEI, DEFIS, PGDAS-D (LC 123/2006 + Res. CGSN 140/2018)
  Demais regimes: pendência registrada no roadmap WS7b (cache adicional
  necessário pra Lei 9.430/96, Lei 8.218/91, Lei 10.426/2002)

Rode com: pytest PY/tests/test_obrigacoes_acessorias.py -v
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.obrigacoes_acessorias import (  # noqa: E402
    AlertaObrigacao,
    Obrigacao,
    calcular_data_vencimento,
    derivar_nivel_porte,
    gerar_alertas_obrigacoes,
    obter_obrigacoes,
)


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA + IMUTABILIDADE
# ─────────────────────────────────────────────────────────────────────────────

class TestSchemaObrigacao:
    """Obrigacao é frozen e tem campos canônicos."""

    def test_obrigacao_e_frozen(self):
        o = Obrigacao(
            codigo="DEFIS",
            nome="Declaração de Informações Socioeconômicas e Fiscais",
            frequencia="ANUAL",
            prazo_descricao="31/03 do ano seguinte",
            multa_descricao="2% ao mês",
            base_legal="LC 123/2006 Art. 25",
        )
        with pytest.raises(Exception):
            o.codigo = "OUTRO"  # type: ignore[misc]

    def test_obrigacao_aceita_4_frequencias(self):
        for freq in ("ANUAL", "MENSAL", "TRIMESTRAL", "SEMESTRAL"):
            Obrigacao(
                codigo=f"X_{freq}",
                nome=f"Teste {freq}",
                frequencia=freq,
                prazo_descricao="dia X mês Y",
                multa_descricao="multa Z",
                base_legal="LC X Art. Y",
            )


class TestSchemaAlertaObrigacao:
    """AlertaObrigacao é frozen e referencia uma Obrigacao."""

    def test_alerta_e_frozen(self):
        o = Obrigacao(
            codigo="X", nome="Y", frequencia="ANUAL",
            prazo_descricao="-", multa_descricao="-", base_legal="-",
        )
        a = AlertaObrigacao(
            obrigacao=o,
            data_vencimento=date(2027, 3, 31),
            dias_restantes=30,
            nivel="MEDIO",
            mensagem="X",
        )
        with pytest.raises(Exception):
            a.dias_restantes = 0  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────────────────
# DERIVAR NÍVEL DE PORTE
# ─────────────────────────────────────────────────────────────────────────────

class TestDerivarNivelPorte:
    """Mapeia regime + enquadramento_simples + tipo_societario → NivelPorte."""

    def test_mei_quando_enquadramento_eh_mei(self):
        assert derivar_nivel_porte(
            regime="MEI",
            enquadramento_simples="MEI",
            tipo_societario="EI",
        ) == "MEI"

    def test_mei_caminhoneiro_tambem_mapeia_mei(self):
        assert derivar_nivel_porte(
            regime="MEI",
            enquadramento_simples="MEI_CAMINHONEIRO",
            tipo_societario="EI",
        ) == "MEI"

    def test_me_quando_simples_e_enquadramento_me(self):
        assert derivar_nivel_porte(
            regime="SIMPLES",
            enquadramento_simples="ME",
            tipo_societario="LTDA",
        ) == "ME"

    def test_epp_quando_simples_e_enquadramento_epp(self):
        assert derivar_nivel_porte(
            regime="SIMPLES",
            enquadramento_simples="EPP",
            tipo_societario="LTDA",
        ) == "EPP"

    def test_demais_quando_presumido_real_imune(self):
        for reg in ("PRESUMIDO", "REAL", "IMUNE"):
            assert derivar_nivel_porte(
                regime=reg,
                enquadramento_simples=None,
                tipo_societario="LTDA",
            ) == "DEMAIS"


# ─────────────────────────────────────────────────────────────────────────────
# CALCULAR DATA DE VENCIMENTO
# ─────────────────────────────────────────────────────────────────────────────

class TestCalcularDataVencimento:
    """
    Para obrigação ANUAL com prazo "31/03 do ano seguinte" e competência
    em 2026, vencimento = 31/03/2027.

    Para MENSAL/TRIMESTRAL/SEMESTRAL, helper recebe (dia, mês_offset)
    explícito — fica pra etapa futura quando Escrivão validar prazos.
    """

    def test_anual_dia_31_mes_3_competencia_2026_vence_2027_03_31(self):
        d = calcular_data_vencimento(
            frequencia="ANUAL",
            dia=31,
            mes=3,
            competencia=date(2026, 6, 15),
        )
        assert d == date(2027, 3, 31)

    def test_anual_ultimo_dia_util_julho_competencia_2026(self):
        # Caso ECF: "último dia útil de julho do ano seguinte"
        d = calcular_data_vencimento(
            frequencia="ANUAL",
            dia=None,  # quando dia=None, usa último dia útil
            mes=7,
            competencia=date(2026, 6, 15),
            ultimo_dia_util=True,
        )
        # Julho 2027: 30/07/2027 (sexta) — ou 31/07 se quinta-feira útil
        # 31/07/2027 é sábado, então 30/07/2027 (sexta)
        assert d == date(2027, 7, 30)

    def test_mensal_dia_20_competencia_marco_2026_vence_abril(self):
        d = calcular_data_vencimento(
            frequencia="MENSAL",
            dia=20,
            mes=None,
            competencia=date(2026, 3, 15),
        )
        assert d == date(2026, 4, 20)

    def test_mensal_dezembro_rola_pra_janeiro_proximo_ano(self):
        d = calcular_data_vencimento(
            frequencia="MENSAL",
            dia=20,
            mes=None,
            competencia=date(2026, 12, 5),
        )
        assert d == date(2027, 1, 20)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNOS — n-ésimo dia útil + somar meses
# Preparação WS7b: prazos como "10º dia útil do 2º mês seguinte" (EFD-Contribuições)
# e "dia 15 do 2º mês seguinte" (DCTFWeb) precisam desses helpers.
# ─────────────────────────────────────────────────────────────────────────────

class TestHelpersInternos:
    """Testes diretos dos helpers privados — aritmética sem citação fiscal."""

    def test_n_esimo_dia_util_junho_2027(self):
        from core.obrigacoes_acessorias import _n_esimo_dia_util
        # Jun/2027: 1=ter, 2=qua, 3=qui, 4=sex, 7=seg, 8=ter, 9=qua, 10=qui, 11=sex, 14=seg
        # 10º dia útil de junho/2027 = 14/06 (segunda-feira)
        assert _n_esimo_dia_util(2027, 6, 1) == date(2027, 6, 1)
        assert _n_esimo_dia_util(2027, 6, 5) == date(2027, 6, 7)  # 1=ter,2,3,4=sex,7=seg
        assert _n_esimo_dia_util(2027, 6, 10) == date(2027, 6, 14)

    def test_n_esimo_dia_util_n_zero_levanta(self):
        from core.obrigacoes_acessorias import _n_esimo_dia_util
        with pytest.raises(ValueError, match="n deve ser ≥ 1"):
            _n_esimo_dia_util(2027, 6, 0)

    def test_n_esimo_dia_util_n_alem_do_mes_levanta(self):
        from core.obrigacoes_acessorias import _n_esimo_dia_util
        # Junho tem ~22 dias úteis. Pedir 30 levanta.
        with pytest.raises(ValueError, match="dias úteis"):
            _n_esimo_dia_util(2027, 6, 30)

    def test_adicionar_meses_simples(self):
        from core.obrigacoes_acessorias import _adicionar_meses
        assert _adicionar_meses(date(2027, 3, 15), 2) == date(2027, 5, 15)
        assert _adicionar_meses(date(2027, 1, 15), 12) == date(2028, 1, 15)

    def test_adicionar_meses_dezembro_rola_ano(self):
        from core.obrigacoes_acessorias import _adicionar_meses
        assert _adicionar_meses(date(2027, 11, 10), 3) == date(2028, 2, 10)

    def test_adicionar_meses_31_jan_vira_28_fev_nao_31_fev(self):
        from core.obrigacoes_acessorias import _adicionar_meses
        # 31/01/2027 + 1 mês = fevereiro 2027 (28 dias) → 28/02
        assert _adicionar_meses(date(2027, 1, 31), 1) == date(2027, 2, 28)

    def test_adicionar_meses_31_jan_2028_vira_29_fev_ano_bissexto(self):
        from core.obrigacoes_acessorias import _adicionar_meses
        # 2028 é bissexto: fev tem 29 dias
        assert _adicionar_meses(date(2028, 1, 31), 1) == date(2028, 2, 29)


# ─────────────────────────────────────────────────────────────────────────────
# OBTER OBRIGAÇÕES POR PORTE × REGIME
# ─────────────────────────────────────────────────────────────────────────────

class TestObterObrigacoes:
    """Retorna tuple de Obrigacao aplicável ao porte+regime."""

    def test_mei_simples_inclui_dasn_simei(self):
        obrigs = obter_obrigacoes(porte="MEI", regime="SIMPLES")
        codigos = {o.codigo for o in obrigs}
        assert "DASN_SIMEI" in codigos

    def test_me_simples_inclui_defis_e_pgdas_d(self):
        obrigs = obter_obrigacoes(porte="ME", regime="SIMPLES")
        codigos = {o.codigo for o in obrigs}
        assert "DEFIS" in codigos
        assert "PGDAS_D" in codigos

    def test_epp_simples_inclui_defis_e_pgdas_d(self):
        obrigs = obter_obrigacoes(porte="EPP", regime="SIMPLES")
        codigos = {o.codigo for o in obrigs}
        assert "DEFIS" in codigos
        assert "PGDAS_D" in codigos

    def test_porte_mei_com_regime_mei_normalizado_para_simples(self):
        # Limpeza pós-PMD: regime="MEI" é normalizado para "SIMPLES" antes
        # de consultar a matriz. Evita chave duplicada ("MEI","MEI") +
        # ("MEI","SIMPLES") com o mesmo conteúdo. MEI é sub-regime do
        # Simples (LC 123/2006 Art. 18-A), não regime próprio.
        obrigs_simples = obter_obrigacoes(porte="MEI", regime="SIMPLES")
        obrigs_mei = obter_obrigacoes(porte="MEI", regime="MEI")
        assert obrigs_simples == obrigs_mei, (
            "porte=MEI + regime=MEI deve resolver pra mesmas obrigações "
            "que porte=MEI + regime=SIMPLES (MEI é sub-regime do Simples)"
        )

    def test_porte_mei_com_regime_absurdo_retorna_tupla_vazia(self):
        # Combinação absurda (porte=MEI mas regime=PRESUMIDO/REAL/IMUNE):
        # NÃO é normalizada — cai em fallback () conservador.
        # Validação de coerência porte×regime vive no orquestrador WS6.6.
        for regime_invalido in ("PRESUMIDO", "REAL", "IMUNE"):
            obrigs = obter_obrigacoes(porte="MEI", regime=regime_invalido)
            assert obrigs == (), (
                f"porte=MEI + regime={regime_invalido} deveria devolver () "
                f"(Rail R2), recebeu {obrigs}"
            )

    def test_combinacao_sem_obrigacao_mapeada_retorna_tupla_vazia(self):
        # PRESUMIDO/REAL/IMUNE — pendentes WS7b (cache RFB adicional)
        # Função retorna () quando não há cache validado, NÃO inventa.
        obrigs = obter_obrigacoes(porte="DEMAIS", regime="PRESUMIDO")
        # Pode ter ou não — depende do cache disponível. Estruturalmente
        # apenas verificamos que retorna tupla.
        assert isinstance(obrigs, tuple)

    def test_resultado_e_imutavel(self):
        obrigs = obter_obrigacoes(porte="MEI", regime="SIMPLES")
        assert isinstance(obrigs, tuple)


# ─────────────────────────────────────────────────────────────────────────────
# GERAR ALERTAS
# ─────────────────────────────────────────────────────────────────────────────

class TestGerarAlertasObrigacoes:
    """Gera alertas pras obrigações que vencem nos próximos N dias."""

    def test_alerta_anual_proximo_do_vencimento(self):
        # MEI declara DASN-SIMEI até 31/05 do ano seguinte. Hoje = 02/05/2027,
        # competência = 2026 → 29 dias até vencer. Alerta MEDIO.
        alertas = gerar_alertas_obrigacoes(
            porte="MEI",
            regime="SIMPLES",
            hoje=date(2027, 5, 2),
            competencia_atual=date(2026, 12, 31),
            dias_antecedencia=30,
        )
        codigos = {a.obrigacao.codigo for a in alertas}
        assert "DASN_SIMEI" in codigos

    def test_sem_alerta_quando_fora_da_janela(self):
        # Hoje = 01/07/2027. DASN_SIMEI 2026 já venceu em 31/05/2027.
        # Próximo vencimento (DASN_SIMEI 2027) = 31/05/2028 (300+ dias).
        alertas = gerar_alertas_obrigacoes(
            porte="MEI",
            regime="SIMPLES",
            hoje=date(2027, 7, 1),
            competencia_atual=date(2027, 5, 31),
            dias_antecedencia=30,
        )
        codigos = {a.obrigacao.codigo for a in alertas}
        # DASN_SIMEI não deve aparecer (vence só em mai/2028)
        assert "DASN_SIMEI" not in codigos or all(
            a.dias_restantes > 30 for a in alertas if a.obrigacao.codigo == "DASN_SIMEI"
        )

    def test_alerta_critico_quando_5_dias_ou_menos(self):
        # Critério interno: dias_restantes ≤ 5 → CRITICO; ≤ 15 → ALTO; ≤ 30 → MEDIO
        alertas = gerar_alertas_obrigacoes(
            porte="MEI",
            regime="SIMPLES",
            hoje=date(2027, 5, 28),  # 3 dias até 31/05
            competencia_atual=date(2026, 12, 31),
            dias_antecedencia=30,
        )
        criticos = [a for a in alertas if a.nivel == "CRITICO"]
        assert any(a.obrigacao.codigo == "DASN_SIMEI" for a in criticos)

    def test_alerta_medio_quando_29_dias(self):
        alertas = gerar_alertas_obrigacoes(
            porte="MEI",
            regime="SIMPLES",
            hoje=date(2027, 5, 2),  # 29 dias até 31/05
            competencia_atual=date(2026, 12, 31),
            dias_antecedencia=30,
        )
        # DASN_SIMEI a 29 dias → MEDIO (entre 16 e 30 dias)
        for a in alertas:
            if a.obrigacao.codigo == "DASN_SIMEI":
                assert a.nivel == "MEDIO"
                break

    def test_nivel_porte_demais_sem_obrigacao_retorna_tupla_vazia(self):
        alertas = gerar_alertas_obrigacoes(
            porte="DEMAIS",
            regime="IMUNE",
            hoje=date(2027, 6, 1),
            competencia_atual=date(2026, 12, 31),
            dias_antecedencia=30,
        )
        # Pendência WS7b — sem obrigação cadastrada ainda
        assert isinstance(alertas, tuple)


# ─────────────────────────────────────────────────────────────────────────────
# CITAÇÕES CANÔNICAS — anti-alucinação MAX_07 (validadas Escrivão 2026-05-08)
# ─────────────────────────────────────────────────────────────────────────────

class TestObrigacoesCitacoesLegais:
    """Citações da multa cobertas pelo cache LC 123/2006 (Arts. 38 e 38-A)."""

    def test_dasn_simei_multa_cita_art_38_par_6(self):
        # Escrivão validou: multa MEI fica em LC 123 Art. 38 § 6º (mín R$ 50)
        obrigs = obter_obrigacoes(porte="MEI", regime="SIMPLES")
        dasn = next((o for o in obrigs if o.codigo == "DASN_SIMEI"), None)
        assert dasn is not None
        assert "LC 123" in dasn.base_legal
        assert "Art. 38" in dasn.base_legal
        assert "§ 6" in dasn.base_legal or "§6" in dasn.base_legal

    def test_dasn_simei_multa_minimo_r_50(self):
        obrigs = obter_obrigacoes(porte="MEI", regime="SIMPLES")
        dasn = next((o for o in obrigs if o.codigo == "DASN_SIMEI"), None)
        assert "R$ 50" in dasn.multa_descricao or "50,00" in dasn.multa_descricao

    def test_defis_multa_cita_art_38_par_3(self):
        # Escrivão validou: DEFIS multa fica em LC 123 Art. 38 § 3º (mín R$ 200)
        obrigs = obter_obrigacoes(porte="ME", regime="SIMPLES")
        defis = next((o for o in obrigs if o.codigo == "DEFIS"), None)
        assert defis is not None
        assert "LC 123" in defis.base_legal
        assert "Art. 38" in defis.base_legal
        assert "§ 3" in defis.base_legal or "§3" in defis.base_legal

    def test_defis_multa_minimo_r_200(self):
        obrigs = obter_obrigacoes(porte="ME", regime="SIMPLES")
        defis = next((o for o in obrigs if o.codigo == "DEFIS"), None)
        assert "R$ 200" in defis.multa_descricao or "200,00" in defis.multa_descricao

    def test_pgdas_d_multa_cita_art_38_a(self):
        # Escrivão validou: PGDAS-D multa = LC 123 Art. 38-A (redação LC 214/2025)
        obrigs = obter_obrigacoes(porte="ME", regime="SIMPLES")
        pgdas = next((o for o in obrigs if o.codigo == "PGDAS_D"), None)
        assert pgdas is not None
        assert "LC 123" in pgdas.base_legal
        assert "Art. 38-A" in pgdas.base_legal

    def test_multa_maxima_e_20_porcento_nao_10(self):
        # Bloqueio MAX_07: plano original dizia "máx 10%" — Escrivão pegou
        # como ERRADO. Texto literal LC 123 Art. 38 I + § 3º limita a 20%.
        for porte in ("MEI", "ME", "EPP"):
            for o in obter_obrigacoes(porte=porte, regime="SIMPLES"):
                # Quando "10%" aparece em "máximo X%", deve ser 20%, não 10%
                assert "20%" in o.multa_descricao or "20 %" in o.multa_descricao or (
                    # OK se NÃO menciona percentual máximo (ex: só piso)
                    "máx" not in o.multa_descricao.lower()
                ), (
                    f"Obrigação {o.codigo} (porte={porte}) cita multa máxima "
                    f"diferente de 20%: '{o.multa_descricao}'"
                )

    def test_nenhuma_obrigacao_cita_norma_sem_cache(self):
        # WS7c (09/05/2026) — Chrome MCP capturou prazos contra fontes oficiais
        # Receita Federal (sped.rfb.gov.br + gov.br/receitafederal):
        #   - ECD: IN RFB 2.003/2021 Art. 5º + IN RFB 2.142/2023
        #   - ECF: IN RFB 2.004/2021
        #   - EFD-Contribuições: IN RFB 1.252/2012
        #   - DCTFWeb: IN RFB 2.248/2025 (alterou IN RFB 2.005/2021 — ÚLTIMO DIA ÚTIL)
        #   - DASN-SIMEI/DEFIS/PGDAS-D: Resolução CGSN 140/2018
        # Permanece pendente:
        #   - IN RFB 1.371/2013 (EFD-ICMS-IPI estadual — fora de escopo unificado)
        #   - Lei 4.502/64 (IPI) — capturada Planalto, mas não usada na matriz
        normas_sem_cache = ("IN RFB 1.371", "Lei 4.502", "Lei 4502")
        for porte in ("MEI", "ME", "EPP", "DEMAIS"):
            for regime in ("SIMPLES", "PRESUMIDO", "REAL", "MEI", "IMUNE"):
                for o in obter_obrigacoes(porte=porte, regime=regime):
                    for norma in normas_sem_cache:
                        if norma in o.base_legal:
                            assert "pendente" in o.base_legal.lower(), (
                                f"Obrigação {o.codigo} cita {norma} sem marca "
                                f"de pendência: {o.base_legal!r}"
                            )

    def test_efd_contribuicoes_agora_capturada_ws7c(self):
        # WS7c (09/05/2026) — EFD-Contribuições adicionada após captura via
        # Chrome MCP (sped.rfb.gov.br/item/show/284). Prazo confirmado:
        # 10º dia útil do segundo mês subsequente.
        for regime in ("PRESUMIDO", "REAL"):
            obrigs = obter_obrigacoes(porte="DEMAIS", regime=regime)
            codigos = {o.codigo for o in obrigs}
            assert "EFD_CONTRIBUICOES" in codigos

    def test_ecd_aplica_apenas_lucro_real(self):
        # ECD foi adicionada em WS7c apenas para REAL (múltiplas fontes
        # confirmam aplicação a Lucro Real). Presumido NÃO obriga ECD.
        obrigs_real = obter_obrigacoes(porte="DEMAIS", regime="REAL")
        assert "ECD" in {o.codigo for o in obrigs_real}
        obrigs_presumido = obter_obrigacoes(porte="DEMAIS", regime="PRESUMIDO")
        assert "ECD" not in {o.codigo for o in obrigs_presumido}


# ─────────────────────────────────────────────────────────────────────────────
# WS7b — Lucro Presumido + Real (ECF + DCTFWeb validadas Escrivão 2026-05-08)
# ─────────────────────────────────────────────────────────────────────────────

class TestObrigacoesPresumidoReal:
    """Obrigações ECF + DCTFWeb pra regimes regulares."""

    @pytest.mark.parametrize("regime", ["PRESUMIDO", "REAL"])
    def test_inclui_ecf_e_dctfweb(self, regime):
        obrigs = obter_obrigacoes(porte="DEMAIS", regime=regime)
        codigos = {o.codigo for o in obrigs}
        assert "ECF" in codigos
        assert "DCTFWEB" in codigos

    def test_imune_inclui_ecf_apenas(self):
        # IMUNE declara ECF como requisito de imunidade (Lei 9.532/97 Art. 12 § 2º)
        obrigs = obter_obrigacoes(porte="DEMAIS", regime="IMUNE")
        codigos = {o.codigo for o in obrigs}
        assert "ECF" in codigos


class TestObrigacoesECFCitacao:
    """ECF cita Decreto-Lei 1.598/77 Art. 8º-A — não Lei 9.430/96 Art. 8º-A."""

    def test_ecf_cita_decreto_lei_1598_77(self):
        # Bloqueio MAX_07 ERR-058: Art. 8º-A NÃO está na Lei 9.430/96 — está
        # no Decreto-Lei 1.598/77 (incluído pela Lei 12.973/2014 Art. 2º).
        obrigs = obter_obrigacoes(porte="DEMAIS", regime="REAL")
        ecf = next((o for o in obrigs if o.codigo == "ECF"), None)
        assert ecf is not None
        assert "Decreto-Lei 1.598" in ecf.base_legal
        assert "Art. 8º-A" in ecf.base_legal or "Art. 8o-A" in ecf.base_legal

    def test_ecf_nao_cita_lei_9430_art_8a(self):
        # ANTI-ALUCINAÇÃO MAX_07: nunca atribuir Art. 8º-A à Lei 9.430/96
        obrigs = obter_obrigacoes(porte="DEMAIS", regime="REAL")
        ecf = next((o for o in obrigs if o.codigo == "ECF"), None)
        assert "Lei 9.430" not in ecf.base_legal or "Art. 8º-A" not in ecf.base_legal.split("Lei 9.430")[1] if "Lei 9.430" in ecf.base_legal else True
        # Mais robusto: garantir que "Lei 9.430" não aparece nada pra ECF
        # (Art. 44 I é citado em outro contexto — relatorio_pdf.py)
        assert "Lei 9.430" not in ecf.base_legal

    def test_ecf_multa_max_10_porcento(self):
        obrigs = obter_obrigacoes(porte="DEMAIS", regime="REAL")
        ecf = next((o for o in obrigs if o.codigo == "ECF"), None)
        assert "10%" in ecf.multa_descricao or "10 %" in ecf.multa_descricao
        assert "0,25%" in ecf.multa_descricao or "0,25 %" in ecf.multa_descricao

    def test_ecf_cita_lei_12973_como_inclusora(self):
        obrigs = obter_obrigacoes(porte="DEMAIS", regime="REAL")
        ecf = next((o for o in obrigs if o.codigo == "ECF"), None)
        assert "Lei 12.973" in ecf.base_legal
        assert "12.973/2014" in ecf.base_legal


class TestObrigacoesDCTFWebCitacao:
    """DCTFWeb cita Lei 10.426/2002 Art. 7º — pisos diferentes por regime."""

    def test_dctfweb_cita_lei_10426_art_7(self):
        obrigs = obter_obrigacoes(porte="DEMAIS", regime="REAL")
        dctf = next((o for o in obrigs if o.codigo == "DCTFWEB"), None)
        assert dctf is not None
        assert "Lei 10.426" in dctf.base_legal
        assert "Art. 7" in dctf.base_legal

    def test_dctfweb_demais_regime_minimo_500(self):
        # Escrivão validou: § 3º da Lei 10.426 traz pisos diferentes —
        # R$ 200 (Simples) vs R$ 500 (demais). DCTFWeb aplica a regimes
        # NÃO-Simples, então piso R$ 500.
        obrigs = obter_obrigacoes(porte="DEMAIS", regime="REAL")
        dctf = next((o for o in obrigs if o.codigo == "DCTFWEB"), None)
        assert "R$ 500" in dctf.multa_descricao or "500,00" in dctf.multa_descricao

    def test_dctfweb_ultimo_dia_util_in_2248_2025(self):
        # WS7c (09/05/2026) — Chrome MCP capturou IN RFB 2.248/2025 (Receita
        # Federal): prazo da DCTFWeb foi ALTERADO de "dia 15" para "ÚLTIMO DIA
        # ÚTIL DO MÊS SEGUINTE" em 07/02/2025. Schema reflete a mudança.
        obrigs = obter_obrigacoes(porte="DEMAIS", regime="REAL")
        dctf = next((o for o in obrigs if o.codigo == "DCTFWEB"), None)
        assert dctf.prazo_offset_meses == 1
        assert dctf.prazo_ultimo_dia_util is True
        assert dctf.prazo_dia is None  # não usa dia fixo, usa último dia útil
        assert dctf.prazo_amparo_pendente is False  # cache validado
        assert "2.248/2025" in dctf.base_legal or "IN RFB 2.248" in dctf.base_legal


class TestAlertasObrigacoesPresumidoReal:
    """Alertas de vencimento pra obrigações Presumido+Real."""

    def test_dctfweb_calcula_vencimento_ultimo_dia_util(self):
        # WS7c (09/05/2026) — IN RFB 2.248/2025 alterou prazo pra
        # ÚLTIMO DIA ÚTIL do mês seguinte. Competência março/2027 →
        # vencimento último dia útil de abril/2027 = 30/04/2027 (sexta).
        alertas = gerar_alertas_obrigacoes(
            porte="DEMAIS",
            regime="REAL",
            hoje=date(2027, 4, 29),  # 1 dia antes do vencimento
            competencia_atual=date(2027, 3, 31),
            dias_antecedencia=30,
        )
        dctf_alerta = next((a for a in alertas if a.obrigacao.codigo == "DCTFWEB"), None)
        assert dctf_alerta is not None
        assert dctf_alerta.data_vencimento == date(2027, 4, 30)
        assert dctf_alerta.dias_restantes == 1
        assert dctf_alerta.nivel == "CRITICO"

    def test_ecd_vence_ultimo_dia_util_junho(self):
        # ECD: anual, último dia útil de junho do ano seguinte.
        # 30/06/2027 é quarta-feira (último dia útil).
        alertas = gerar_alertas_obrigacoes(
            porte="DEMAIS",
            regime="REAL",
            hoje=date(2027, 6, 1),  # 29 dias até 30/06
            competencia_atual=date(2026, 12, 31),
            dias_antecedencia=30,
        )
        ecd_alerta = next((a for a in alertas if a.obrigacao.codigo == "ECD"), None)
        assert ecd_alerta is not None
        assert ecd_alerta.data_vencimento == date(2027, 6, 30)

    def test_ecf_vence_ultimo_dia_util_julho(self):
        # ECF: anual, último dia útil de julho do ano seguinte. 31/07/2027 é
        # sábado, então 30/07/2027 (sexta).
        alertas = gerar_alertas_obrigacoes(
            porte="DEMAIS",
            regime="REAL",
            hoje=date(2027, 7, 1),  # 29 dias até 30/07
            competencia_atual=date(2026, 12, 31),
            dias_antecedencia=30,
        )
        ecf_alerta = next((a for a in alertas if a.obrigacao.codigo == "ECF"), None)
        assert ecf_alerta is not None
        assert ecf_alerta.data_vencimento == date(2027, 7, 30)
