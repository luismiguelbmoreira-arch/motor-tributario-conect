# -*- coding: utf-8 -*-
"""
historico_consolidado.py — Agregação de 6 meses para DiagnosticoConsolidado.

Funções privadas consumidas pelo método público
``MotorReformaTributaria.gerar_diagnostico_consolidado``. Mantidas neste
módulo separado pra evitar inflar ``motor_tributario.py`` e permitir
testes unitários isolados (cada função é puro).

Ressalvas técnicas (blueprint):
    - **R1** — ``decimal.getcontext().sqrt`` em CoV (Decimal não tem ``.sqrt``).
    - **R2** — mediana de 6 elementos = ``(sorted[2] + sorted[3]) / 2``.
    - **R3** — ``model_dump(mode='json')`` serializa Decimal como string;
      hash usa JSON canônico com ``sort_keys`` + ``separators`` compactos.
    - **R4** — 5/6 votos vai pra REVISAR_MANUALMENTE (operador decide).

Bugs do advisor corrigidos:
    - Ordem ``(fornecedora, compradora, operacao)`` no construtor do motor.
    - ``ncm_nbs`` default ``"61091000"`` (camiseta algodão — fora monofásico).
    - Sem ``historico_uf_origem`` (não existe no schema); fallback "SP".
    - Mapeamento ``tipo_societario`` Histórico → EmpresaFornecedora.
    - ``carga_min/max`` quantizados a 4 casas para coerência com média.

Amparo legal:
    - LC 123/2006 Art. 12 §1º (apuração mensal Simples)
    - LC 123/2006 Art. 18 §1º (alíquota efetiva)
    - LC 123/2006 Art. 3º §9 (exclusão obrigatória)
    - LC 214/2025 Art. 47 (apuração mensal CBS/IBS)
    - LC 214/2025 Arts. 41–44 (Opt-Out)
    - Plano R7 (gate ≥90% do teto)
"""
from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from collections import Counter
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, getcontext
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from core.versioned_rule import TETO_SIMPLES_NACIONAL_VERSIONADO, valor_em
from schemas.diagnostico_consolidado import (
    AlertaTransicao,
    DiagnosticoMensalResumo,
    NivelConfianca,
    RecomendacaoConsolidada,
    TendenciaRBT12,
)
from schemas.historico_seis_meses import (
    HistoricoSeisMeses,
    MesFiscal,
    OperacaoMensal,
)
from schemas.motor import EmpresaCompradora, EmpresaFornecedora, OperacaoFiscal

if TYPE_CHECKING:  # pragma: no cover
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────────────────────

# NCM default para agregação mensal — camiseta de algodão, posição 6109.10.00.
# Fora do bloqueio de regime monofásico (NCMS_MONOFASICAS_BLOQUEADAS) e
# trata-se de mercadoria comum no comércio varejista. Qualquer NCM concreto
# precisa vir do extrator; aqui é apenas placeholder para o motor não
# bloquear na ausência do dado, com entrada na trilha registrando o uso.
_NCM_AGREGADO_DEFAULT = "61091000"

# UF fallback quando vendas do mês não trazem uf_destino (todas internas
# sem informação ou mês só com compras). "SP" é o maior emissor histórico.
_UF_FALLBACK = "SP"

# Limites das heurísticas D2 (advisor: documentadas em ``aviso_heuristicas``).
_LIMIAR_TENDENCIA_SLOPE = Decimal("0.02")   # 2%/mês ≈ 12% em 6 meses
_LIMIAR_SAZONALIDADE_COV = Decimal("0.25")  # CoV > 25%
_LIMIAR_SAZONALIDADE_RATIO = Decimal("1.5")  # max/mediana > 1.5

# Gate Rail R7 — RBT12 ≥ 90% do teto Simples força análise Opt-Out.
_GATE_R7_FRACAO_TETO = Decimal("0.90")

# Outlier: faturamento > 3× mediana ou < 1/3 mediana.
_LIMIAR_OUTLIER_ALTO = Decimal("3")
_LIMIAR_OUTLIER_BAIXO = Decimal("3")  # divisor → mediana / 3


# ─────────────────────────────────────────────────────────────────────────────
# Mapeamento societário Histórico → EmpresaFornecedora
# ─────────────────────────────────────────────────────────────────────────────


def _mapear_tipo_societario(
    tipo_historico: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Retorna ``(tipo_societario_motor, enquadramento_simples)``.

    HistoricoSeisMeses.tipo_societario tem 15 valores incluindo MEI/ME/EPP
    (que são porte/enquadramento, não forma jurídica). EmpresaFornecedora
    distingue tipo (forma jurídica) de enquadramento.

    Mapeamento conservador: quando o histórico declara ``ME``/``EPP`` sem
    forma jurídica subjacente, ``tipo_societario_motor`` fica None
    (Optional) e enquadramento carrega o porte. ``MEI`` aproveita o alias
    UX-friendly do EmpresaFornecedora (``_expandir_alias_mei``) que vira
    ``EI`` + ``MEI``.

    Casos:
        | Histórico              | Motor (tipo)     | Enquadramento     |
        |------------------------|------------------|-------------------|
        | MEI                    | "MEI" (alias)    | (auto via alias)  |
        | MEI_CAMINHONEIRO       | "MEI_CAMINHONEIRO" (alias) | (auto)  |
        | ME                     | None             | "ME"              |
        | EPP                    | None             | "EPP"             |
        | LTDA/SA/SLU/SCP/ESC/   | passa direto     | None              |
        |   CONSORCIO/PRODUTOR_  |                  |                   |
        |   RURAL_PF/COOPERATIVA/|                  |                   |
        |   ASSOCIACAO/FUNDACAO  |                  |                   |
        | ORG_RELIGIOSA          | "ORGANIZACAO_RELIGIOSA" | None       |
    """
    if tipo_historico in {"MEI", "MEI_CAMINHONEIRO"}:
        # EmpresaFornecedora aceita alias UX-friendly e expande para EI +
        # enquadramento_simples correspondente em ``_expandir_alias_mei``.
        return tipo_historico, None
    if tipo_historico in {"ME", "EPP"}:
        return None, tipo_historico
    if tipo_historico == "ORG_RELIGIOSA":
        return "ORGANIZACAO_RELIGIOSA", None
    # LTDA, SA, SLU, COOPERATIVA, ASSOCIACAO, FUNDACAO, SCP, ESC,
    # CONSORCIO, PRODUTOR_RURAL_PF — passam direto.
    return tipo_historico, None


# ─────────────────────────────────────────────────────────────────────────────
# Adapter: MesFiscal → tripla (Fornecedora, Compradora, Operacao) do motor
# ─────────────────────────────────────────────────────────────────────────────


def _predominante(
    items: List[OperacaoMensal],
    key: str,
) -> Optional[str]:
    """Retorna o atributo ``key`` mais frequente ponderado por ``valor_total``.

    Determinismo: empate resolve por ordem alfabética crescente da chave —
    cravado na lambda de sort. Risco #8 do blueprint.
    """
    contagem: Dict[str, Decimal] = {}
    for it in items:
        valor = getattr(it, key)
        if valor is None:
            continue
        contagem[valor] = contagem.get(valor, Decimal("0")) + it.valor_total
    if not contagem:
        return None
    # Maior valor desc, depois chave asc — empate determinístico.
    ordenado = sorted(contagem.items(), key=lambda x: (-x[1], x[0]))
    return ordenado[0][0]


def _adaptar_mes_para_motor(
    historico: HistoricoSeisMeses,
    mes: MesFiscal,
) -> Tuple[
    EmpresaFornecedora,
    EmpresaCompradora,
    OperacaoFiscal,
    List[Dict[str, Any]],
]:
    """Constrói tripla (fornecedora, compradora, operacao) + entradas de trilha.

    Ordem de retorno casa com o construtor real do motor
    (``MotorReformaTributaria(fornecedora, compradora, operacao)`` —
    bug 1 do advisor). A quarta posição traz entradas de trilha pra
    documentar perda de granularidade na agregação (D1).
    """
    entradas_trilha: List[Dict[str, Any]] = []

    # 1) Mix B2B/B2C real no mês.
    receita_b2b = sum(
        (op.valor_total for op in mes.operacoes if op.tipo == "VENDA_B2B"),
        Decimal("0"),
    )
    receita_b2c = sum(
        (op.valor_total for op in mes.operacoes if op.tipo == "VENDA_B2C"),
        Decimal("0"),
    )
    devolucoes = sum(
        (op.valor_total for op in mes.operacoes if op.tipo == "DEVOLUCAO_VENDA"),
        Decimal("0"),
    )
    receita_liquida = receita_b2b + receita_b2c - devolucoes

    if receita_liquida <= 0:
        # Mês degenerado (sem receita) — assume pior caso B2B contribuinte.
        pct_b2b = Decimal("100")
        tipo_comprador = "B2B_CONTRIBUINTE"
    elif receita_b2c <= 0:
        pct_b2b = Decimal("100")
        tipo_comprador = "B2B_CONTRIBUINTE"
    elif receita_b2b <= 0:
        pct_b2b = Decimal("0")
        tipo_comprador = "B2C_CONSUMIDOR_FINAL"
    else:
        pct_b2b = (receita_b2b / receita_liquida * Decimal("100")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        tipo_comprador = "MISTO"

    # 2) CNAE / UF / forma de recebimento predominantes — só vendas
    #    (em compras o CNAE é do fornecedor, não da empresa).
    vendas = [op for op in mes.operacoes if op.tipo.startswith("VENDA_")]
    cnae_predominante_mes = _predominante(vendas, "cnae_predominante")
    uf_destino_pred = _predominante(vendas, "uf_destino")
    forma_pred = _predominante(vendas, "forma_recebimento")

    # CNAE da empresa: usa o predominante de vendas do mês ou cai pro CNAE
    # principal da empresa (vindo pelo schema). Ausência total → bloqueio.
    cnae_empresa = cnae_predominante_mes
    if cnae_empresa is None:
        # Mês só com compras/ajustes — usa CNAE histórico do primeiro mês
        # com vendas como fallback. Sem isso, dá ValidationError.
        for outro_mes in historico.meses:
            outras_vendas = [
                op for op in outro_mes.operacoes if op.tipo.startswith("VENDA_")
            ]
            cnae_empresa = _predominante(outras_vendas, "cnae_predominante")
            if cnae_empresa is not None:
                break

    if cnae_empresa is None:
        # Janela inteira sem nenhuma venda — não temos CNAE pra fundamentar
        # cálculo. Isso é diagnóstico inválido.
        raise ValueError(
            f"Janela {historico.cnpj} sem nenhuma operação de VENDA — "
            "impossível inferir CNAE principal da empresa."
        )

    # 3) Heterogeneidade — registra trilha quando há mais de 1 valor descartado.
    cnaes_unicos = sorted({
        op.cnae_predominante for op in vendas if op.cnae_predominante
    })
    ufs_unicas = sorted({op.uf_destino for op in vendas if op.uf_destino})
    formas_unicas = sorted({
        op.forma_recebimento for op in vendas if op.forma_recebimento
    })

    if len(cnaes_unicos) > 1 or len(ufs_unicas) > 1 or len(formas_unicas) > 1:
        entradas_trilha.append({
            "tipo": "AGREGACAO_MES_HETEROGENEA",
            "competencia": mes.competencia,
            "cnaes_descartados": [c for c in cnaes_unicos if c != cnae_empresa],
            "ufs_descartadas": [u for u in ufs_unicas if u != uf_destino_pred],
            "formas_descartadas": [
                f for f in formas_unicas if f != forma_pred
            ],
            "amparo_legal": (
                "Decisão D1 — agregação mensal perde granularidade fina; "
                "DIFAL e Split Payment ficam INDISPONIVEL_AGREGADO."
            ),
        })

    # 4) Mapeamento societário.
    tipo_motor, enquadramento = _mapear_tipo_societario(historico.tipo_societario)

    # 5) Constrói schemas do motor.
    ano, mes_num = map(int, mes.competencia.split("-"))
    ultimo_dia = monthrange(ano, mes_num)[1]
    data_real = date(ano, mes_num, ultimo_dia)

    # OperacaoFiscal exige data_emissao em [2026-01-01, 2033-12-31]
    # (LC 214/2025 Art. 348 — período transicional). Quando o histórico
    # contém meses anteriores a 2026 (RBT12 móvel olha 12 meses pra trás),
    # clampamos a data para 2026-01-31 e registramos na trilha — não há
    # cálculo fiscal pra mês anterior à vigência da LC, mas o diagnóstico
    # consolidado precisa rodar o motor pra cada mês da janela mesmo assim.
    if data_real < date(2026, 1, 1):
        data_emissao = date(2026, 1, 31)
        entradas_trilha.append({
            "tipo": "DATA_CLAMPADA_PRE_2026",
            "competencia": mes.competencia,
            "data_real": data_real.isoformat(),
            "data_aplicada": data_emissao.isoformat(),
            "amparo_legal": (
                "LC 214/2025 Art. 348 — período transicional inicia em "
                "2026. Mês pré-2026 é base histórica (RBT12 móvel "
                "LC 123/2006 Art. 12 §1º) e não gera cálculo CBS/IBS — "
                "data clampada para a primeira data válida da janela."
            ),
        })
    else:
        data_emissao = data_real

    uf_origem = uf_destino_pred or _UF_FALLBACK
    uf_destino = uf_destino_pred or _UF_FALLBACK

    # NCM agregado default — registra na trilha (MAX_FISCAL_02).
    entradas_trilha.append({
        "tipo": "NCM_AGREGADO_DEFAULT",
        "competencia": mes.competencia,
        "ncm_aplicado": _NCM_AGREGADO_DEFAULT,
        "amparo_legal": (
            "Decisão D1 — NCM real exige granularidade nota-a-nota. "
            "Diagnóstico consolidado usa NCM neutro (camiseta algodão, "
            "fora de regime monofásico LC 214/2025 Arts. 172-174)."
        ),
    })

    fornecedora = EmpresaFornecedora(
        cnpj=historico.cnpj,
        razao_social=historico.razao_social,
        regime=historico.regime_atual,
        cnae_principal=cnae_empresa,
        uf_origem=uf_origem,
        faturamento_12m=mes.rbt12_declarado,
        folha_salarios_12m=mes.folha_12m,
        anexo_simples=mes.anexo_aplicado,
        tipo_societario=tipo_motor,
        enquadramento_simples=enquadramento,
    )

    compradora = EmpresaCompradora(
        tipo=tipo_comprador,
        percentual_b2b=pct_b2b,
        uf_destino=uf_destino,
    )

    valor_operacao = (
        mes.faturamento_mes if mes.faturamento_mes > 0 else Decimal("0.01")
    )

    operacao = OperacaoFiscal(
        valor_operacao=valor_operacao,
        data_emissao=data_emissao,
        ncm_nbs=_NCM_AGREGADO_DEFAULT,
        forma_recebimento=forma_pred or "PIX_DIRETO",
        rpa_mensal=mes.faturamento_mes if mes.faturamento_mes > 0 else None,
    )

    return fornecedora, compradora, operacao, entradas_trilha


# ─────────────────────────────────────────────────────────────────────────────
# Funções de agregação
# ─────────────────────────────────────────────────────────────────────────────


def _calcular_carga_tributaria_media(
    diagnosticos: List[DiagnosticoMensalResumo],
) -> Tuple[Decimal, Decimal, str, Decimal, str]:
    """Carga média ponderada + min/max por mês.

    Retorna ``(carga_media, carga_min, comp_min, carga_max, comp_max)``,
    todos quantizados a 4 casas (bug 5 do advisor — coerência com a média).

    Amparo: LC 123/2006 Art. 18 §1º (alíquota efetiva = razão).
    """
    soma_das = sum((d.das_mensal for d in diagnosticos), Decimal("0"))
    soma_fat = sum((d.faturamento_mes for d in diagnosticos), Decimal("0"))
    if soma_fat <= 0:
        raise ValueError(
            "Faturamento 6m zerado — diagnóstico consolidado inválido."
        )

    quant = Decimal("0.0001")
    carga_media = (soma_das / soma_fat * Decimal("100")).quantize(
        quant, ROUND_HALF_UP
    )

    cargas_mensais: List[Tuple[str, Decimal]] = []
    for d in diagnosticos:
        if d.faturamento_mes > 0:
            carga = (d.das_mensal / d.faturamento_mes * Decimal("100")).quantize(
                quant, ROUND_HALF_UP
            )
        else:
            carga = Decimal("0").quantize(quant)
        cargas_mensais.append((d.competencia, carga))

    # Determinismo: ordem alfabética da competência desempata.
    comp_min, carga_min = min(cargas_mensais, key=lambda x: (x[1], x[0]))
    comp_max, carga_max = max(cargas_mensais, key=lambda x: (x[1], x[0]))
    return carga_media, carga_min, comp_min, carga_max, comp_max


def _detectar_tendencia(
    meses: List[MesFiscal],
) -> Tuple[TendenciaRBT12, Decimal]:
    """Heurística D2: OLS slope normalizado sobre faturamento mensal.

    Limiar ±2%/mês ≈ ±12% em 6 meses (sensibilidade típica PGDAS-D pra
    mudança de faixa). Marcada como heurística diagnóstica (Rail R2).

    Retorna ``(tendencia, delta_pct)`` — delta é a variação percentual entre
    primeiro e último mês.
    """
    valores = [m.faturamento_mes for m in meses]
    n = len(valores)
    media = sum(valores, Decimal("0")) / Decimal(n)

    if media <= 0:
        return TendenciaRBT12.ESTAVEL, Decimal("0.00")

    # OLS: slope = Σ(x_i − x̄)(y_i − ȳ) / Σ(x_i − x̄)²
    x_bar = (Decimal(n) - Decimal("1")) / Decimal("2")  # média de [0..n-1]
    num = sum(
        (Decimal(i) - x_bar) * (v - media) for i, v in enumerate(valores)
    )
    den = sum((Decimal(i) - x_bar) ** 2 for i in range(n))
    if den == 0:  # pragma: no cover - n=1
        return TendenciaRBT12.ESTAVEL, Decimal("0.00")
    slope_normalizado = (num / den) / media

    primeiro = valores[0]
    if primeiro <= 0:
        delta_total = Decimal("0.00")
    else:
        delta_total = (
            (valores[-1] - primeiro) / primeiro * Decimal("100")
        ).quantize(Decimal("0.01"), ROUND_HALF_UP)

    if slope_normalizado > _LIMIAR_TENDENCIA_SLOPE:
        # ASCENDENTE exige delta > 0 — se slope positivo mas delta total
        # ≤ 0 (oscilação), rebaixa para ESTAVEL pra não quebrar validator.
        if delta_total > 0:
            return TendenciaRBT12.ASCENDENTE, delta_total
        return TendenciaRBT12.ESTAVEL, delta_total
    if slope_normalizado < -_LIMIAR_TENDENCIA_SLOPE:
        if delta_total < 0:
            return TendenciaRBT12.DESCENDENTE, delta_total
        return TendenciaRBT12.ESTAVEL, delta_total
    return TendenciaRBT12.ESTAVEL, delta_total


def _detectar_sazonalidade(
    meses: List[MesFiscal],
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Heurística D2: CoV > 0.25 + ratio_max/mediana > 1.5.

    Ressalva R1: ``getcontext().sqrt(var)`` (Decimal não tem ``.sqrt``).
    Ressalva R2: mediana de 6 elementos = ``(sorted[2] + sorted[3]) / 2``.

    Retorna ``(detectada, mes_pico, mes_vale)``. Se ``detectada=False``,
    pico e vale ficam ``None`` (validator do schema exige).
    """
    valores = [(m.competencia, m.faturamento_mes) for m in meses]
    fats = [v for _, v in valores]
    n = len(fats)
    media = sum(fats, Decimal("0")) / Decimal(n)
    if media <= 0:
        return False, None, None

    var = sum((f - media) ** 2 for f in fats) / Decimal(n)
    desvio = getcontext().sqrt(var)  # R1
    cov = desvio / media

    ordenados = sorted(fats)
    if n == 6:
        mediana = (ordenados[2] + ordenados[3]) / Decimal("2")  # R2
    else:  # pragma: no cover - schema fixa em 6
        mediana = ordenados[n // 2]
    if mediana <= 0:
        return False, None, None

    ratio_max = max(fats) / mediana

    if cov > _LIMIAR_SAZONALIDADE_COV and ratio_max > _LIMIAR_SAZONALIDADE_RATIO:
        # Determinismo: se há empate em max/min de faturamento, a primeira
        # competência (ordem cronológica) vence.
        pico = max(valores, key=lambda x: x[1])[0]
        vale = min(valores, key=lambda x: x[1])[0]
        if pico == vale:
            # Variância > 0 mas pico/vale colapsam — não há sazonalidade real.
            return False, None, None
        return True, pico, vale
    return False, None, None


# ─────────────────────────────────────────────────────────────────────────────
# Reconciliação de recomendações (5 funções privadas)
# ─────────────────────────────────────────────────────────────────────────────


_MAPA_CODIGO_PARA_CONSOLIDADA: Dict[str, RecomendacaoConsolidada] = {
    "OPT_OUT_FORTE": RecomendacaoConsolidada.OPT_OUT,
    "OPT_OUT_VANTAJOSO": RecomendacaoConsolidada.OPT_OUT,
    "OPT_OUT_CONDICIONAL": RecomendacaoConsolidada.OPT_OUT,
    "MANTER_SIMPLES": RecomendacaoConsolidada.MANTER_SIMPLES,
    "ZONA_CINZA": RecomendacaoConsolidada.REVISAR_MANUALMENTE,
    "DADOS_INSUFICIENTES": RecomendacaoConsolidada.REVISAR_MANUALMENTE,
}


def _mapear_codigo_para_consolidada(codigo: str) -> RecomendacaoConsolidada:
    """Mapeia código mensal de recomendacoes_optout para consolidado."""
    return _MAPA_CODIGO_PARA_CONSOLIDADA.get(
        codigo, RecomendacaoConsolidada.REVISAR_MANUALMENTE
    )


def _gerar_justificativa(
    votos: Dict[str, int],
    freq_majoritaria: int,
    tendencia: TendenciaRBT12,
) -> str:
    """Texto da justificativa consolidada (50–1000 chars do schema)."""
    detalhe_votos = ", ".join(
        f"{k}: {v}" for k, v in sorted(votos.items())
    )
    if freq_majoritaria == 6:
        base = (
            f"Os 6 meses analisados convergem para a mesma recomendação. "
            f"Quebra dos votos: {detalhe_votos}. Tendência da janela: "
            f"{tendencia.value}. Confiança ALTA — operador pode aplicar "
            f"a recomendação após confirmar premissas com o contador."
        )
    elif freq_majoritaria == 5:
        base = (
            f"5 dos 6 meses indicam a mesma recomendação, mas 1 mês diverge. "
            f"Quebra dos votos: {detalhe_votos}. Tendência: {tendencia.value}. "
            f"Por conservadorismo fiscal (Ressalva R4), a divergência empurra "
            f"a recomendação para REVISAR_MANUALMENTE — operador deve avaliar "
            f"o mês divergente antes de decidir entre Simples Puro e Opt-Out."
        )
    else:
        base = (
            f"Os 6 meses não convergem para uma única recomendação majoritária "
            f"(maior frequência: {freq_majoritaria}/6). Quebra: {detalhe_votos}. "
            f"Tendência: {tendencia.value}. Recomendação consolidada é "
            f"REVISAR_MANUALMENTE — análise individual indispensável antes "
            f"da janela semestral de Opt-Out (abr/set, Res. CGSN 183/2025)."
        )
    return base


def _consolidar_recomendacao(
    historico: HistoricoSeisMeses,
    diagnosticos: List[DiagnosticoMensalResumo],
    tendencia: TendenciaRBT12,
) -> Tuple[
    RecomendacaoConsolidada,
    NivelConfianca,
    str,
    List[str],
    Dict[str, int],
]:
    """Reconciliação por unanimidade + gate Rail R7.

    Gate R7 sobrescreve qualquer voto: RBT12 ≥ 90% do teto Simples vigente
    no mês força REVISAR_MANUALMENTE com confiança BAIXA.

    Retorna ``(recomendacao, confianca, justificativa, amparo, votos)``.
    """
    # Gate R7 — usa teto vigente no ano da competência mais recente.
    competencia_recente = historico.meses[-1].competencia
    ano_recente, _ = map(int, competencia_recente.split("-"))
    teto_recente = valor_em(
        TETO_SIMPLES_NACIONAL_VERSIONADO, date(ano_recente, 1, 1)
    )
    gate_90pct = teto_recente * _GATE_R7_FRACAO_TETO

    if any(m.rbt12_declarado >= gate_90pct for m in historico.meses):
        return (
            RecomendacaoConsolidada.REVISAR_MANUALMENTE,
            NivelConfianca.BAIXA,
            (
                "Gate Rail R7 disparado: RBT12 cruzou 90% do teto Simples "
                f"(R$ {gate_90pct:.2f}) em pelo menos um mês da janela. "
                "Empresa em zona de exclusão obrigatória — análise Opt-Out "
                "é mandatória, mas decisão final exige revisão contábil "
                "completa antes da janela semestral (abr/set)."
            ),
            [
                "LC 123/2006 Art. 3º §9 (exclusão obrigatória ao exceder teto)",
                "LC 214/2025 Arts. 41-44 (dispositivo de Opt-Out)",
                "Plano R7 — gate ≥90% do teto força revisão manual",
            ],
            {"_GATE_R7": 1},
        )

    # Reconciliação por unanimidade (cf. blueprint advisor #5).
    recs = [d.recomendacao_individual for d in diagnosticos]
    contagem = Counter(recs)
    mais_comum, freq = contagem.most_common(1)[0]
    votos = dict(contagem)

    if freq == 6:
        confianca = NivelConfianca.ALTA
        recomendacao_final = _mapear_codigo_para_consolidada(mais_comum)
        # Edge case: se mapeou pra REVISAR_MANUALMENTE (todos ZONA_CINZA),
        # rebaixa confiança pra MEDIA — coerência com validator.
        if recomendacao_final == RecomendacaoConsolidada.REVISAR_MANUALMENTE:
            confianca = NivelConfianca.MEDIA
    elif freq == 5:
        # Ressalva R4 — operador decide divergência.
        confianca = NivelConfianca.MEDIA
        recomendacao_final = RecomendacaoConsolidada.REVISAR_MANUALMENTE
    else:
        confianca = NivelConfianca.BAIXA
        recomendacao_final = RecomendacaoConsolidada.REVISAR_MANUALMENTE

    justificativa = _gerar_justificativa(votos, freq, tendencia)
    amparo = [
        "LC 123/2006 Art. 18 §1º (alíquota efetiva)",
        "LC 214/2025 Arts. 41-44 (Opt-Out)",
        "CF Art. 146 III 'd' (regime diferenciado)",
        "Res. CGSN 183/2025 (janelas semestrais abr/set)",
    ]
    return recomendacao_final, confianca, justificativa, amparo, votos


def _calcular_confianca_final(
    confianca_inicial: NivelConfianca,
    historico: HistoricoSeisMeses,
    diagnosticos: List[DiagnosticoMensalResumo],
) -> NivelConfianca:
    """Rebaixa confiança por sinais de baixa qualidade dos dados.

    Sinais (cumulativos):
        1. ``historico.warnings`` não vazio (oscilação RBT12, etc).
        2. Algum mês com ``_anexo_divergencia`` (CNAE não bate com Anexo).
        3. Outlier de faturamento (>3× ou <1/3 da mediana).
    """
    niveis = [NivelConfianca.ALTA, NivelConfianca.MEDIA, NivelConfianca.BAIXA]
    rebaixos = 0

    if historico.warnings:
        rebaixos += 1

    if any(getattr(m, "_anexo_divergencia", None) for m in historico.meses):
        rebaixos += 1

    fats = [m.faturamento_mes for m in historico.meses]
    if fats:
        ordenados = sorted(fats)
        if len(ordenados) >= 4:
            mediana = (ordenados[2] + ordenados[3]) / Decimal("2")
        else:  # pragma: no cover
            mediana = ordenados[len(ordenados) // 2]
        if mediana > 0:
            for f in fats:
                if (
                    f > _LIMIAR_OUTLIER_ALTO * mediana
                    or f < mediana / _LIMIAR_OUTLIER_BAIXO
                ):
                    rebaixos += 1
                    break

    idx_atual = niveis.index(confianca_inicial)
    idx_final = min(idx_atual + rebaixos, len(niveis) - 1)
    return niveis[idx_final]


# ─────────────────────────────────────────────────────────────────────────────
# Alertas de transição
# ─────────────────────────────────────────────────────────────────────────────


def _detectar_alertas_transicao(
    historico: HistoricoSeisMeses,
    diagnosticos: List[DiagnosticoMensalResumo],
) -> List[AlertaTransicao]:
    """Detecta transições relevantes entre meses consecutivos."""
    alertas: List[AlertaTransicao] = []

    # Mudança de Anexo entre meses consecutivos.
    for i in range(1, len(diagnosticos)):
        ant = diagnosticos[i - 1]
        atu = diagnosticos[i]
        if ant.anexo_aplicado != atu.anexo_aplicado:
            alertas.append(
                AlertaTransicao(
                    tipo="MUDANCA_ANEXO",
                    competencia=atu.competencia,
                    descricao=(
                        f"Anexo mudou de {ant.anexo_aplicado} ({ant.competencia}) "
                        f"para {atu.anexo_aplicado} ({atu.competencia}). Verifique "
                        "se a mudança reflete operação real ou erro de declaração."
                    ),
                    amparo_legal=(
                        "LC 123/2006 Art. 18 §§1º e 24 (Anexo varia por "
                        "atividade e Fator R)"
                    ),
                )
            )

    # Fator R cruzando o limiar de 0.28 entre meses consecutivos.
    LIMIAR_FATOR_R = Decimal("0.28")
    for i in range(1, len(diagnosticos)):
        ant = diagnosticos[i - 1]
        atu = diagnosticos[i]
        # Cruzamento: um lado < limiar e outro >= limiar.
        if (ant.fator_r < LIMIAR_FATOR_R) != (atu.fator_r < LIMIAR_FATOR_R):
            alertas.append(
                AlertaTransicao(
                    tipo="FATOR_R_ATRAVESSOU_028",
                    competencia=atu.competencia,
                    valor_anterior=ant.fator_r,
                    valor_atual=atu.fator_r,
                    descricao=(
                        f"Fator R cruzou o limiar de 0.28 entre {ant.competencia} "
                        f"(F_R={ant.fator_r}) e {atu.competencia} (F_R={atu.fator_r}). "
                        "Migração entre Anexo III e Anexo V pode estar em "
                        "ciclo — monitorar mensalmente."
                    ),
                    amparo_legal=(
                        "LC 123/2006 Art. 18 §24 (Fator R define Anexo III "
                        "ou V para serviços)"
                    ),
                )
            )

    # RBT12 ≥ 90% do teto em algum mês.
    for mes in historico.meses:
        ano, _ = map(int, mes.competencia.split("-"))
        teto = valor_em(TETO_SIMPLES_NACIONAL_VERSIONADO, date(ano, 1, 1))
        gate = teto * _GATE_R7_FRACAO_TETO
        if mes.rbt12_declarado >= gate:
            alertas.append(
                AlertaTransicao(
                    tipo="RBT12_90PCT_TETO",
                    competencia=mes.competencia,
                    valor_atual=mes.rbt12_declarado,
                    descricao=(
                        f"RBT12 R$ {mes.rbt12_declarado} ≥ 90% do teto Simples "
                        f"(R$ {gate}) em {mes.competencia}. Empresa em risco "
                        "de exclusão obrigatória — Opt-Out deve ser avaliado "
                        "antes da janela semestral."
                    ),
                    amparo_legal=(
                        "LC 123/2006 Art. 3º §9 + Plano R7 (gate ≥90% força "
                        "análise Opt-Out)"
                    ),
                )
            )

    # Divergência entre Anexo declarado e Anexo esperado pelo CNAE.
    for mes in historico.meses:
        div = getattr(mes, "_anexo_divergencia", None)
        if div:
            alertas.append(
                AlertaTransicao(
                    tipo="DIVERGENCIA_ANEXO_DECLARADO",
                    competencia=mes.competencia,
                    descricao=(
                        f"CNAE {div['cnae']} (categoria {div['fonte_categoria']}) "
                        f"resolve para Anexo {div['anexo_esperado']}, mas mês "
                        f"declarou Anexo {div['anexo_declarado']}. Confirme "
                        "atividade real com contador."
                    ),
                    amparo_legal=(
                        "LC 123/2006 Art. 18 §1º + Res. CGSN 140/2018 "
                        "(CNAE → Anexo)"
                    ),
                )
            )

    # Outlier de faturamento (>3× ou <1/3 da mediana).
    fats = [m.faturamento_mes for m in historico.meses]
    if len(fats) >= 4 and all(f >= 0 for f in fats):
        ordenados = sorted(fats)
        mediana = (ordenados[2] + ordenados[3]) / Decimal("2")
        if mediana > 0:
            for mes in historico.meses:
                if (
                    mes.faturamento_mes > _LIMIAR_OUTLIER_ALTO * mediana
                    or mes.faturamento_mes < mediana / _LIMIAR_OUTLIER_BAIXO
                ):
                    alertas.append(
                        AlertaTransicao(
                            tipo="OUTLIER_FATURAMENTO",
                            competencia=mes.competencia,
                            valor_anterior=mediana,
                            valor_atual=mes.faturamento_mes,
                            descricao=(
                                f"Faturamento R$ {mes.faturamento_mes} em "
                                f"{mes.competencia} é outlier vs mediana "
                                f"R$ {mediana} (>3× ou <1/3). Confirme se "
                                "não há erro de lançamento ou nota duplicada."
                            ),
                            amparo_legal=(
                                "LC 123/2006 Art. 12 §1º (apuração mensal — "
                                "consistência da série temporal)"
                            ),
                        )
                    )

    return alertas


# ─────────────────────────────────────────────────────────────────────────────
# Hash de reprodutibilidade (Rail R6)
# ─────────────────────────────────────────────────────────────────────────────


def _calcular_hash_reprodutibilidade(
    historico: HistoricoSeisMeses,
    versao_motor: str,
    versao_lei: str,
    versao_schema: str = "1.0",
) -> str:
    """SHA-256 sobre input canônico + versões.

    Exclui:
        - ``razao_social`` (PII — D3)
        - ``warnings`` (não-determinístico — depende de estado interno mutável)

    Inclui:
        - ``_anexo_divergencia`` por mês (atributo interno via getattr) —
          re-anexado depois do model_dump pra entrar no hash sem aparecer
          na serialização padrão.

    Ressalva R3: ``model_dump(mode='json')`` serializa Decimal como string —
    determinístico em Pydantic V2. ``json.dumps`` com ``sort_keys=True`` +
    ``separators=(",", ":")`` garante representação canônica.

    Bug 7 do advisor: ``_anexo_divergencia`` NÃO entra em ``model_dump``
    (não é Pydantic field) — re-anexa explicitamente.
    """
    payload = historico.model_dump(
        mode="json",
        exclude={"warnings", "razao_social"},
    )
    # Re-anexa _anexo_divergencia em cada mês (atributo via object.__setattr__).
    for i, mes in enumerate(historico.meses):
        div = getattr(mes, "_anexo_divergencia", None)
        if div:
            payload["meses"][i]["_anexo_divergencia"] = div

    canonico = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    semente = f"{versao_schema}|{versao_motor}|{versao_lei}|{canonico}"
    return hashlib.sha256(semente.encode("utf-8")).hexdigest()
