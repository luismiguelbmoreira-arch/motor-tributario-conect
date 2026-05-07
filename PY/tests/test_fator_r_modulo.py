# -*- coding: utf-8 -*-
"""
test_fator_r_modulo.py — Cobertura do core/fator_r_modulo.py.

LC 123/2006, Art. 18, § 24.

Inclui teste regressivo do bug NameError em historico_consolidado.py
(símbolo `_FATOR_R_ZONA_RISCO_MIN` que jamais existiu — quebrava sempre que
um mês caía na zona de risco). Fix: extração da lógica para módulo dedicado.
"""

import os
import sys
from datetime import date
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.fator_r_modulo import (
    alertar_migracao_anexo,
    calcular_fator_r_serie,
    projetar_fator_r,
)
from core.historico_consolidado import gerar_diagnostico_consolidado
from schemas.historico_seis_meses import HistoricoSeisMeses, MesHistorico
from schemas.motor import EmpresaCompradora, EmpresaFornecedora, OperacaoFiscal


# ── Fixtures ──────────────────────────────────────────────────────────────────

CNAE_TI_ELEGIVEL = "6201501"          # Desenvolvimento de software (Fator R aplicável)
CNAE_PADARIA_INELEGIVEL = "1091101"   # Padaria (Fator R não aplicável)


def _build_historico(
    cnae: str,
    rbt12_por_mes: list,
    folha12m_por_mes: list,
) -> HistoricoSeisMeses:
    """Constrói HistoricoSeisMeses a partir de duas listas paralelas de Decimals."""
    assert len(rbt12_por_mes) == 6
    assert len(folha12m_por_mes) == 6
    fornecedora = EmpresaFornecedora(
        cnpj="11222333000181",
        razao_social="Software House Teste Ltda",
        regime="SIMPLES",
        cnae_principal=cnae,
        uf_origem="SP",
        faturamento_12m=rbt12_por_mes[-1],
        folha_salarios_12m=folha12m_por_mes[-1],
    )
    compradora = EmpresaCompradora(
        tipo="B2B_CONTRIBUINTE",
        percentual_b2b=Decimal("100"),
        uf_destino="SP",
    )
    meses = []
    for i in range(6):
        meses.append(MesHistorico(
            competencia=f"2026-{i + 1:02d}",
            rbt12_no_mes=rbt12_por_mes[i],
            folha_mes=folha12m_por_mes[i] / Decimal("12"),
            folha_12m_no_mes=folha12m_por_mes[i],
            operacoes=[OperacaoFiscal(
                data_emissao=date(2026, i + 1, 15),
                valor_operacao=Decimal("50000.00"),
                ncm_nbs="84715099",
                forma_recebimento="PIX_DIRETO",
            )],
        ))
    return HistoricoSeisMeses(
        fornecedora_base=fornecedora,
        compradora_padrao=compradora,
        meses=meses,
    )


# ── calcular_fator_r_serie ────────────────────────────────────────────────────

def test_calcular_serie_cnae_inelegivel_retorna_todos_none():
    historico = _build_historico(
        cnae=CNAE_PADARIA_INELEGIVEL,
        rbt12_por_mes=[Decimal("1000000")] * 6,
        folha12m_por_mes=[Decimal("280000")] * 6,
    )
    serie = calcular_fator_r_serie(historico)
    assert serie == [None] * 6


def test_calcular_serie_cnae_elegivel_retorna_decimais():
    historico = _build_historico(
        cnae=CNAE_TI_ELEGIVEL,
        rbt12_por_mes=[Decimal("1000000")] * 6,
        folha12m_por_mes=[Decimal("280000")] * 6,
    )
    serie = calcular_fator_r_serie(historico)
    assert all(v == Decimal("0.2800") for v in serie)


def test_calcular_serie_quantize_quatro_casas():
    historico = _build_historico(
        cnae=CNAE_TI_ELEGIVEL,
        rbt12_por_mes=[Decimal("1000000")] * 6,
        folha12m_por_mes=[Decimal("273456")] * 6,
    )
    serie = calcular_fator_r_serie(historico)
    # 273456 / 1000000 = 0.273456 → quantize a 4 casas = 0.2735
    assert all(v == Decimal("0.2735") for v in serie)


def test_calcular_serie_meses_independentes():
    """Cada mês usa seu próprio rbt12 e folha — sem mistura."""
    rbt12 = [Decimal("900000"), Decimal("950000"), Decimal("1000000"),
             Decimal("1050000"), Decimal("1100000"), Decimal("1150000")]
    folha = [Decimal("250000"), Decimal("260000"), Decimal("270000"),
             Decimal("280000"), Decimal("290000"), Decimal("300000")]
    historico = _build_historico(CNAE_TI_ELEGIVEL, rbt12, folha)
    serie = calcular_fator_r_serie(historico)
    esperado = [(folha[i] / rbt12[i]).quantize(Decimal("0.0001")) for i in range(6)]
    assert serie == esperado


def test_calcular_serie_folha_zero_retorna_zero():
    """Folha zero não invalida o cálculo — Fator R legítimo é 0."""
    historico = _build_historico(
        cnae=CNAE_TI_ELEGIVEL,
        rbt12_por_mes=[Decimal("1000000")] * 6,
        folha12m_por_mes=[Decimal("0")] * 6,
    )
    serie = calcular_fator_r_serie(historico)
    assert serie == [Decimal("0.0000")] * 6


# ── projetar_fator_r ──────────────────────────────────────────────────────────

def test_projetar_serie_vazia_retorna_lista_vazia():
    assert projetar_fator_r([], n_meses=6) == []


def test_projetar_um_ponto_retorna_lista_vazia():
    """Regressão linear precisa de pelo menos 2 pontos — conservadorismo."""
    assert projetar_fator_r([Decimal("0.28")], n_meses=6) == []


def test_projetar_todos_none_retorna_lista_vazia():
    assert projetar_fator_r([None] * 6, n_meses=6) == []


def test_projetar_n_meses_zero_retorna_lista_vazia():
    assert projetar_fator_r([Decimal("0.28")] * 6, n_meses=0) == []


def test_projetar_serie_constante_devolve_constante():
    """Se a série é constante, projeção também é constante (slope=0)."""
    serie = [Decimal("0.30")] * 6
    projecao = projetar_fator_r(serie, n_meses=3)
    assert len(projecao) == 3
    assert all(v == Decimal("0.3000") for v in projecao)


def test_projetar_serie_crescente_devolve_crescente():
    serie = [Decimal("0.20"), Decimal("0.22"), Decimal("0.24"),
             Decimal("0.26"), Decimal("0.28"), Decimal("0.30")]
    projecao = projetar_fator_r(serie, n_meses=3)
    assert len(projecao) == 3
    assert projecao[0] < projecao[1] < projecao[2]
    assert projecao[0] > Decimal("0.30")  # primeiro mês projetado supera o último observado


def test_projetar_ignora_pontos_none():
    serie = [None, Decimal("0.25"), None, Decimal("0.27"), None, Decimal("0.29")]
    projecao = projetar_fator_r(serie, n_meses=2)
    assert len(projecao) == 2
    assert all(isinstance(v, Decimal) for v in projecao)


# ── alertar_migracao_anexo ────────────────────────────────────────────────────

def test_alertar_serie_vazia_retorna_lista_vazia():
    assert alertar_migracao_anexo([], []) == []


def test_alertar_serie_fora_da_zona_retorna_lista_vazia():
    serie = [Decimal("0.10"), Decimal("0.20"), Decimal("0.40"),
             Decimal("0.50"), Decimal("0.15"), Decimal("0.35")]
    competencias = [f"2026-{i + 1:02d}" for i in range(6)]
    assert alertar_migracao_anexo(serie, competencias) == []


def test_alertar_um_mes_na_zona_de_risco():
    serie = [Decimal("0.10"), Decimal("0.20"), Decimal("0.28"),
             Decimal("0.50"), Decimal("0.15"), Decimal("0.35")]
    competencias = [f"2026-{i + 1:02d}" for i in range(6)]
    alertas = alertar_migracao_anexo(serie, competencias)
    assert len(alertas) == 1
    assert alertas[0].tipo == "FATOR_R_ZONA_RISCO"
    assert alertas[0].competencia == "2026-03"


def test_alertar_multiplos_meses_na_zona():
    serie = [Decimal("0.27"), Decimal("0.28"), Decimal("0.29"),
             Decimal("0.30"), Decimal("0.10"), Decimal("0.275")]
    competencias = [f"2026-{i + 1:02d}" for i in range(6)]
    alertas = alertar_migracao_anexo(serie, competencias)
    assert len(alertas) == 4
    assert {a.competencia for a in alertas} == {"2026-01", "2026-02", "2026-03", "2026-06"}


def test_alertar_ignora_none():
    serie = [None, Decimal("0.28"), None, None, None, None]
    competencias = [f"2026-{i + 1:02d}" for i in range(6)]
    alertas = alertar_migracao_anexo(serie, competencias)
    assert len(alertas) == 1
    assert alertas[0].competencia == "2026-02"


def test_alertar_limites_inclusivos():
    """Limites 0,27 e 0,29 são inclusivos — empate vai pra zona de risco."""
    serie = [Decimal("0.27"), Decimal("0.29"), Decimal("0.2699"), Decimal("0.2901"),
             Decimal("0.28"), Decimal("0.30")]
    competencias = [f"2026-{i + 1:02d}" for i in range(6)]
    alertas = alertar_migracao_anexo(serie, competencias)
    competencias_alertadas = {a.competencia for a in alertas}
    assert "2026-01" in competencias_alertadas  # 0.27 inclusivo
    assert "2026-02" in competencias_alertadas  # 0.29 inclusivo
    assert "2026-03" not in competencias_alertadas  # 0.2699 fora
    assert "2026-04" not in competencias_alertadas  # 0.2901 fora
    assert "2026-05" in competencias_alertadas      # 0.28 dentro
    assert "2026-06" not in competencias_alertadas  # 0.30 fora


def test_alertar_tamanhos_diferentes_levanta_value_error():
    with pytest.raises(ValueError, match="Tamanho da série"):
        alertar_migracao_anexo(
            serie=[Decimal("0.28")] * 3,
            competencias=["2026-01", "2026-02"],
        )


def test_alertar_amparo_legal_correto():
    serie = [Decimal("0.28")]
    competencias = ["2026-01"]
    alertas = alertar_migracao_anexo(serie, competencias)
    assert "LC 123/2006, Art. 18, § 24" in alertas[0].amparo_legal


# ── Regressão do bug NameError em historico_consolidado ──────────────────────

def test_regressao_bug_fator_r_zona_risco_nao_quebra_diagnostico():
    """
    Bug original (anterior ao Fase 0b): historico_consolidado.py:153 referenciava
    `_FATOR_R_ZONA_RISCO_MIN` (com underscore), símbolo que jamais existiu — o
    import era `FATOR_R_ZONA_RISCO_MIN` sem underscore. Toda vez que um mês
    do diagnóstico caía na zona [0,27 - 0,29], o motor levantava NameError.

    A suite anterior de 1360 testes não cobria esse caminho.
    Após Fase 0b, a lógica foi extraída para core/fator_r_modulo.py e o bug
    morreu por construção. Este teste prova que o caminho voltou a funcionar.
    """
    historico = _build_historico(
        cnae=CNAE_TI_ELEGIVEL,
        rbt12_por_mes=[Decimal("1000000")] * 6,
        folha12m_por_mes=[Decimal("280000")] * 6,  # Fator R = 0.28 (zona de risco)
    )
    diagnostico = gerar_diagnostico_consolidado(historico)
    # Não levantou NameError — primeiro requisito.
    # Segundo: o alerta FATOR_R_ZONA_RISCO deve estar presente nos 6 meses.
    tipos_alertas = [a.tipo for a in diagnostico.alertas_transicao]
    assert tipos_alertas.count("FATOR_R_ZONA_RISCO") == 6
