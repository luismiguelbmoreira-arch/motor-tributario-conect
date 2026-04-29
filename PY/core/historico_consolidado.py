# -*- coding: utf-8 -*-
"""
historico_consolidado.py — Consolidação de diagnóstico histórico 6 meses.
LC 123/2006 | LC 214/2025

Regras MAX_08: todo número vem do motor rodando.
Imports locais dentro da função para evitar circularidade com motor_tributario.py.
Constantes normativas: tabelas_simples.py (FROZEN).
Limiares não-normativos marcados explicitamente.
"""

import hashlib
import json
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from statistics import linear_regression
from typing import List

from core.fator_r_modulo import alertar_migracao_anexo, calcular_fator_r_serie
from core.tabelas_simples import ALERTA_90_PERCENT_TETO, TETO_SIMPLES_NACIONAL
from schemas.diagnostico_consolidado import (
    AlertaTransicao,
    DiagnosticoConsolidado,
    DiagnosticoMensalResumo,
)
from schemas.historico_seis_meses import HistoricoSeisMeses, MesHistorico

# ─── Limiares heurísticos (não normativos) ───────────────────────────────────
# Heurística interna — não é valor normativo. Crescimento > 15% mensal.
_CRESCIMENTO_ACELERADO_THRESHOLD = Decimal("0.15")

# Heurística interna — não é valor normativo. Slope normalizado para tendência.
_SLOPE_THRESHOLD = 0.01

# Tamanho fixo do histórico — HistoricoSeisMeses.meses max_length=6.
# Heurística interna — não é valor normativo.
_N_MESES = 6

# OPT_OUT_CONDICIONAL excluído da contagem de meses opt-out:
# opt-out é irretratável anualmente (LC 123/2006, Arts. 30-31). Recomendação
# condicional não justifica irreversibilidade. Conservadorismo fiscal.
_CODIGOS_OPTOUT_DEFINITIVO = frozenset({"OPT_OUT_FORTE", "OPT_OUT_VANTAJOSO"})


def _rodar_motor_mes(historico: HistoricoSeisMeses, mes_idx: int) -> dict:
    """
    Roda o motor para o mês indicado com receita mensal agregada.

    Agrega todas as operações do mês em uma operação sintética (valor = soma),
    usando a primeira operação como referência para metadata (NCM, forma_recebimento).
    Simplificação documentada: análise histórica prioriza tendência, não per-operação.
    """
    from core.motor_tributario import MotorReformaTributaria
    from schemas.motor import OperacaoFiscal

    mes = historico.meses[mes_idx]

    fornecedora_mes = historico.fornecedora_base.model_copy(
        update={
            "faturamento_12m": mes.rbt12_no_mes,
            "folha_salarios_12m": mes.folha_12m_no_mes,
        }
    )

    receita_mes = sum(op.valor_operacao for op in mes.operacoes)
    op_ref = mes.operacoes[0]

    op_mensal = OperacaoFiscal(
        data_emissao=op_ref.data_emissao,
        valor_operacao=receita_mes,
        ncm_nbs=op_ref.ncm_nbs,
        forma_recebimento=op_ref.forma_recebimento,
        tinha_st_icms=op_ref.tinha_st_icms,
        reducao_cbs_ibs=op_ref.reducao_cbs_ibs,
        produto_importado=op_ref.produto_importado,
    )

    motor = MotorReformaTributaria(fornecedora_mes, historico.compradora_padrao, op_mensal)
    diag = motor.gerar_diagnostico()
    motor.purge()
    return diag


def _extrair_carga_mensal(diag: dict, regime: str, receita_mes: Decimal) -> Decimal:
    """Extrai a carga tributária mensal do output do motor."""
    cenarios = diag.get("cenarios", {})
    if regime in ("SIMPLES", "MEI") and cenarios and "simples_puro" in cenarios:
        return Decimal(cenarios["simples_puro"]["custo_das_por_operacao"])
    total_mensal = diag.get("aliquotas", {}).get("total_mensal")
    if total_mensal is not None:
        return Decimal(total_mensal)
    # Fallback: alíquota × receita
    aliquota = Decimal(diag.get("aliquotas", {}).get("efetiva_das_total", "0"))
    return (aliquota * receita_mes).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _extrair_resumo_mensal(
    mes: MesHistorico,
    diag: dict,
    receita_mes: Decimal,
    regime: str,
) -> DiagnosticoMensalResumo:
    carga = _extrair_carga_mensal(diag, regime, receita_mes)

    if receita_mes > Decimal("0"):
        aliquota_efetiva = (carga / receita_mes).quantize(Decimal("0.000001"), ROUND_HALF_UP)
    else:
        aliquota_efetiva = Decimal("0")

    fator_r_str = diag.get("empresa", {}).get("fator_r")
    fator_r = Decimal(fator_r_str) if fator_r_str else None

    cenarios = diag.get("cenarios", {})
    if regime in ("SIMPLES", "MEI") and cenarios and "recomendacao_inteligente" in cenarios:
        rec_codigo = cenarios["recomendacao_inteligente"]["codigo"]
    else:
        rec_codigo = "NAO_APLICAVEL"

    alertas_mes = [a.get("tipo", "") for a in diag.get("alertas", []) if a.get("tipo")]

    return DiagnosticoMensalResumo(
        competencia=mes.competencia,
        rbt12=mes.rbt12_no_mes,
        fator_r=fator_r,
        carga_tributaria_mes=carga,
        valor_operacoes_mes=receita_mes,
        aliquota_efetiva_mes=aliquota_efetiva,
        num_operacoes=len(mes.operacoes),
        recomendacao_codigo=rec_codigo,
        alertas_mes=alertas_mes,
        anexo_simples=diag.get("empresa", {}).get("anexo_simples"),
    )


def _gerar_alertas_transicao(
    resumos: List[DiagnosticoMensalResumo],
    historico: HistoricoSeisMeses,
) -> List[AlertaTransicao]:
    alertas: List[AlertaTransicao] = []

    # Alertas de zona de risco do Fator R — delegado ao módulo dedicado.
    # Série calculada direto do histórico (folha_12m / rbt12) — fonte única.
    # LC 123/2006, Art. 18, § 24.
    serie_fator_r = calcular_fator_r_serie(historico)
    alertas.extend(alertar_migracao_anexo(
        serie=serie_fator_r,
        competencias=[mes.competencia for mes in historico.meses],
    ))

    for i, r in enumerate(resumos):
        # TETO_90PCT — normativo (LC 123/2006, Art. 3º, II)
        if r.rbt12 >= ALERTA_90_PERCENT_TETO:
            alertas.append(AlertaTransicao(
                tipo="TETO_90PCT",
                competencia=r.competencia,
                detalhe=(
                    f"RBT12 R$ {r.rbt12:,.2f} ≥ 90% do teto Simples "
                    f"(R$ {ALERTA_90_PERCENT_TETO:,.2f} de R$ {TETO_SIMPLES_NACIONAL:,.2f}). "
                    "Risco de extrapolação do Simples Nacional."
                ),
                amparo_legal="LC 123/2006, Art. 3º, II — teto R$ 4.800.000,00",
            ))

        if i == 0:
            continue

        prev = resumos[i - 1]

        # CRESCIMENTO_ACELERADO — heurística interna
        if prev.valor_operacoes_mes > Decimal("0"):
            crescimento = (r.valor_operacoes_mes - prev.valor_operacoes_mes) / prev.valor_operacoes_mes
            if crescimento > _CRESCIMENTO_ACELERADO_THRESHOLD:
                alertas.append(AlertaTransicao(
                    tipo="CRESCIMENTO_ACELERADO",
                    competencia=r.competencia,
                    detalhe=(
                        f"Faturamento cresceu {crescimento:.1%} em {r.competencia} "
                        f"(R$ {prev.valor_operacoes_mes:,.2f} → R$ {r.valor_operacoes_mes:,.2f}). "
                        "Heurística interna — sem amparo normativo. Planejamento preventivo."
                    ),
                    amparo_legal="Heurística interna — sem amparo normativo. Planejamento tributário preventivo.",
                ))

        # FATOR_R_MUDOU_ANEXO — normativo (LC 123/2006, Art. 18, § 24)
        if (
            prev.fator_r is not None
            and r.fator_r is not None
            and prev.anexo_simples is not None
            and r.anexo_simples is not None
            and prev.fator_r != r.fator_r
            and prev.anexo_simples != r.anexo_simples
        ):
            alertas.append(AlertaTransicao(
                tipo="FATOR_R_MUDOU_ANEXO",
                competencia=r.competencia,
                detalhe=(
                    f"Fator R mudou ({prev.fator_r:.4f} → {r.fator_r:.4f}) e causou "
                    f"mudança de Anexo ({prev.anexo_simples} → {r.anexo_simples}) "
                    f"em {r.competencia}."
                ),
                amparo_legal="LC 123/2006, Art. 18, § 24 — Fator R determina Anexo III vs V",
            ))

        # ANEXO_MUDOU (sem mudança de Fator R) — normativo
        elif (
            prev.anexo_simples is not None
            and r.anexo_simples is not None
            and prev.anexo_simples != r.anexo_simples
        ):
            alertas.append(AlertaTransicao(
                tipo="ANEXO_MUDOU",
                competencia=r.competencia,
                detalhe=(
                    f"Anexo mudou de {prev.anexo_simples} para {r.anexo_simples} "
                    f"em {r.competencia}. Impacto direto na alíquota DAS."
                ),
                amparo_legal="LC 123/2006, Art. 18, §§ 1º e 3º — tributação por Anexo",
            ))

    return alertas


def _calcular_hash_reproducibilidade(historico: HistoricoSeisMeses, motor_versao: str) -> str:
    """SHA-256 determinístico: historico + motor_versao + tabelas. Garante reprodutibilidade."""
    from core.tabelas_simples import CRONOGRAMA_IVA, TABELAS_ANEXOS

    tabelas_hash = hashlib.sha256(
        json.dumps(
            {"anexos": str(dict(TABELAS_ANEXOS)), "cronograma": str(dict(CRONOGRAMA_IVA))},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    payload = json.dumps({
        "historico_sha256": hashlib.sha256(
            historico.model_dump_json().encode("utf-8")
        ).hexdigest(),
        "motor_versao": motor_versao,
        "tabelas_sha256": tabelas_hash,
    }, sort_keys=True)

    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def gerar_diagnostico_consolidado(historico: HistoricoSeisMeses) -> DiagnosticoConsolidado:
    """
    Consolida 6 meses de histórico fiscal em um DiagnosticoConsolidado.

    Roda o motor para cada mês — todo número no output vem do motor. MAX_08.
    LC 123/2006 | LC 214/2025.
    """
    from core.motor_tributario import MOTOR_VERSAO

    regime = historico.fornecedora_base.regime
    resumos: List[DiagnosticoMensalResumo] = []

    for i, mes in enumerate(historico.meses):
        diag = _rodar_motor_mes(historico, i)
        receita_mes = sum((op.valor_operacao for op in mes.operacoes), Decimal("0"))
        resumo = _extrair_resumo_mensal(mes, diag, receita_mes, regime)
        resumos.append(resumo)

    # Agregações — todos os valores vêm dos resumos que vieram do motor
    carga_total = sum((r.carga_tributaria_mes for r in resumos), Decimal("0")).quantize(Decimal("0.01"), ROUND_HALF_UP)
    carga_media = (carga_total / Decimal(str(_N_MESES))).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # Alíquota efetiva consolidada — média ponderada pelo faturamento (LC 123/2006, Art. 18, §1º)
    total_faturamento = sum((r.valor_operacoes_mes for r in resumos), Decimal("0"))
    if total_faturamento > Decimal("0"):
        aliquota_consolidada = (carga_total / total_faturamento).quantize(Decimal("0.000001"), ROUND_HALF_UP)
    else:
        aliquota_consolidada = Decimal("0")

    aliquota_min = min(r.aliquota_efetiva_mes for r in resumos)
    aliquota_max = max(r.aliquota_efetiva_mes for r in resumos)

    # Tendência — regressão linear sobre cargas mensais (heurística interna — não é valor normativo)
    x = [float(j) for j in range(_N_MESES)]
    y = [float(r.carga_tributaria_mes) for r in resumos]
    slope, _ = linear_regression(x, y)
    media_y = sum(y) / _N_MESES
    slope_norm = slope / media_y if media_y > 0 else 0.0

    if slope_norm > _SLOPE_THRESHOLD:
        tendencia = "CRESCENTE"
    elif slope_norm < -_SLOPE_THRESHOLD:
        tendencia = "DECRESCENTE"
    else:
        tendencia = "ESTAVEL"

    alertas_transicao = _gerar_alertas_transicao(resumos, historico)

    # Contagem de meses opt-out (OPT_OUT_CONDICIONAL excluído — conservadorismo fiscal)
    meses_optout = sum(1 for r in resumos if r.recomendacao_codigo in _CODIGOS_OPTOUT_DEFINITIVO)

    # Heurística interna — não é valor normativo. Limiares 5/4/2 de 6 meses.
    if meses_optout >= 5:
        rec_regime = "OPT_OUT_FORTE"
    elif meses_optout >= 4:
        rec_regime = "AVALIAR_OPT_OUT"
    elif meses_optout <= 2:
        rec_regime = "MANTER_SIMPLES"
    else:
        rec_regime = "INCONCLUSIVO"

    # Índice de confiança — concentração da recomendação (heurística interna — não é valor normativo)
    all_recs = [r.recomendacao_codigo for r in resumos]
    rec_mais_frequente = max(set(all_recs), key=all_recs.count)
    indice_confianca = min(10, int(all_recs.count(rec_mais_frequente) / _N_MESES * 10))

    # CNPJ anonimizado (LGPD Art. 12)
    cnpj_anonimizado = hashlib.sha256(
        historico.fornecedora_base.cnpj.encode("utf-8")
    ).hexdigest()[:16]

    return DiagnosticoConsolidado(
        periodo=f"{historico.meses[0].competencia} a {historico.meses[-1].competencia}",
        cnpj_anonimizado=cnpj_anonimizado,
        regime=regime,
        resumos_mensais=resumos,
        carga_total_periodo=carga_total,
        carga_media_mensal=carga_media,
        aliquota_efetiva_consolidada=aliquota_consolidada,
        aliquota_efetiva_min=aliquota_min,
        aliquota_efetiva_max=aliquota_max,
        tendencia=tendencia,
        alertas_transicao=alertas_transicao,
        recomendacao_regime=rec_regime,
        meses_recomendando_optout=meses_optout,
        indice_confianca=indice_confianca,
        hash_reprodutibilidade=_calcular_hash_reproducibilidade(historico, MOTOR_VERSAO),
        motor_versao=MOTOR_VERSAO,
        gerado_em=datetime.now().isoformat(),
    )
