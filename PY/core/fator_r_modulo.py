# -*- coding: utf-8 -*-
"""
fator_r_modulo.py — Módulo dedicado ao Fator R em séries históricas.

LC 123/2006, Art. 18, § 24 — Fator R determina migração Anexo V → Anexo III
quando folha_12m / RBT12 ≥ 0,28.

Funções:
- calcular_fator_r_serie: Fator R mês-a-mês a partir de HistoricoSeisMeses.
- projetar_fator_r: regressão linear sobre série histórica (heurística).
- alertar_migracao_anexo: alertas de zona de risco (0,27 ≤ x ≤ 0,29).

Constantes normativas (FATOR_R_LIMIAR) e elegibilidade de CNAE (CNAES_FATOR_R)
permanecem em motor_tributario.py — fonte única. Este módulo apenas consome.
"""

from decimal import ROUND_HALF_UP, Decimal
from statistics import linear_regression
from typing import List, Optional

from core.motor_tributario import (
    CNAES_FATOR_R,
    FATOR_R_ZONA_RISCO_MAX,
    FATOR_R_ZONA_RISCO_MIN,
)
from schemas.diagnostico_consolidado import AlertaTransicao
from schemas.historico_seis_meses import HistoricoSeisMeses

# Quantização do Fator R: 4 casas decimais, mesmo padrão do diagnóstico mensal.
_QUANT_FATOR_R = Decimal("0.0001")


def calcular_fator_r_serie(historico: HistoricoSeisMeses) -> List[Optional[Decimal]]:
    """
    Calcula o Fator R mês-a-mês como folha_12m_no_mes / rbt12_no_mes.

    Retorna [None] * n quando o CNAE da fornecedora_base não consta em CNAES_FATOR_R.
    O schema MesHistorico já garante rbt12_no_mes > 0, então não há divisão por zero.

    LC 123/2006, Art. 18, § 24.
    """
    n = len(historico.meses)
    if historico.fornecedora_base.cnae_principal not in CNAES_FATOR_R:
        return [None] * n

    return [
        (mes.folha_12m_no_mes / mes.rbt12_no_mes).quantize(_QUANT_FATOR_R, ROUND_HALF_UP)
        for mes in historico.meses
    ]


def projetar_fator_r(
    serie: List[Optional[Decimal]],
    n_meses: int = 6,
) -> List[Decimal]:
    """
    Projeta os próximos n_meses do Fator R via regressão linear sobre a série histórica.

    Pontos None (CNAE inelegível ou ausência de dado) são ignorados.
    Requer pelo menos 2 pontos válidos. Caso contrário retorna lista vazia
    — não extrapolar com pouca evidência é conservadorismo fiscal (Rail R2).

    HEURÍSTICA INTERNA — projeção linear é simplificação. Decisões fiscais
    devem usar valores observados, não projetados.

    Consumidor previsto:
    - Fase 4 — relatório PDF cliente (gráfico "tendência do Fator R nos próximos 6m").
    - Fase 5 — dashboard de carteira (alerta antecipado de migração de Anexo).
    """
    if n_meses <= 0:
        return []

    pontos = [(idx, float(valor)) for idx, valor in enumerate(serie) if valor is not None]
    if len(pontos) < 2:
        return []

    xs = [p[0] for p in pontos]
    ys = [p[1] for p in pontos]
    slope, intercept = linear_regression(xs, ys)

    base = len(serie)
    projecao: List[Decimal] = []
    for k in range(n_meses):
        x_proj = base + k
        y_proj = slope * x_proj + intercept
        projecao.append(Decimal(str(y_proj)).quantize(_QUANT_FATOR_R, ROUND_HALF_UP))
    return projecao


def alertar_migracao_anexo(
    serie: List[Optional[Decimal]],
    competencias: List[str],
) -> List[AlertaTransicao]:
    """
    Detecta zona de risco do Fator R em cada mês da série.

    Limiar normativo é apenas FATOR_R_LIMIAR=0,28 (LC 123/2006, Art. 18, § 24).
    A janela [0,27 - 0,29] é HEURÍSTICA INTERNA: sinaliza oscilação iminente
    entre Anexos III e V quando pequena variação na folha pode mudar de Anexo.

    Retorna lista vazia quando nenhum mês está em zona de risco.
    """
    if len(serie) != len(competencias):
        raise ValueError(
            f"Tamanho da série ({len(serie)}) deve coincidir com competências ({len(competencias)})."
        )

    alertas: List[AlertaTransicao] = []
    for fator_r, competencia in zip(serie, competencias):
        if fator_r is None:
            continue
        if FATOR_R_ZONA_RISCO_MIN <= fator_r <= FATOR_R_ZONA_RISCO_MAX:
            alertas.append(AlertaTransicao(
                tipo="FATOR_R_ZONA_RISCO",
                competencia=competencia,
                detalhe=(
                    f"Fator R {fator_r:.4f} na zona de risco "
                    f"[{FATOR_R_ZONA_RISCO_MIN}, {FATOR_R_ZONA_RISCO_MAX}]. "
                    "Pequena variação na folha pode mudar de Anexo V para III. "
                    "Heurística interna — não é valor normativo."
                ),
                amparo_legal="LC 123/2006, Art. 18, § 24 — Fator R determina migração Anexo V → III",
            ))
    return alertas
