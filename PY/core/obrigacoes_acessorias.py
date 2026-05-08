# -*- coding: utf-8 -*-
"""
core/obrigacoes_acessorias.py — WS7

Matriz porte × regime → obrigações acessórias + alerta ativo de multas.

ESCOPO desta entrega (validado por Escrivão 2026-05-08 contra cache local):
  - DASN-SIMEI (MEI anual)        — multa LC 123/2006 Art. 38 § 6º
  - DEFIS    (ME/EPP anual)       — multa LC 123/2006 Art. 38 § 3º
  - PGDAS-D  (ME/EPP/MEI mensal)  — multa LC 123/2006 Art. 38-A (redação LC 214/2025)

PRAZOS: LC 123/2006 Art. 25 delega ao CGSN ("observados prazo e modelo
aprovados pelo CGSN"). Os prazos canônicos (DASN-SIMEI 31/05, DEFIS 31/03,
PGDAS-D dia 20) vivem na Resolução CGSN 140/2018 — fora do cache local
hoje. Marcamos `prazo_amparo_pendente=True` para sinalização explícita
(Rail R2: motor avisa, mas declara que a citação literal do prazo aguarda
captura da Resolução CGSN 140/2018 — pendência WS7b).

PENDÊNCIAS WS7b (captura de cache + extensão de matriz):
  - ECF (Lucro Presumido + Real anual) — Lei 9.430/96 Art. 8º-A + IN RFB 2.004/2021
  - ECD (Lucro Real anual)             — Lei 8.218/91 + IN RFB 2.003/2021
  - EFD-Contribuições (mensal)         — Lei 8.218/91 Art. 12 + IN RFB 1.252/2012
  - DCTFWeb (mensal)                   — Lei 10.426/2002 Art. 7º + IN RFB 2.005/2021
  - EFD-ICMS estadual                  — Convênio ICMS 143/2006 (27 UFs — fora de escopo unificado)
  - Resolução CGSN 140/2018            — confirmar URL canônica antes de capturar

BLOQUEIOS MAX_07 prevenidos pelo Escrivão antes do código:
  1. Multa máxima é 20% (Art. 38 I + § 3º) — NÃO 10% como o plano original dizia
  2. Multa MEI fica em Art. 38 § 6º (R$ 50 mín) — citação específica
  3. Multa DEFIS fica em Art. 38 § 3º (R$ 200 mín) — não Art. 25 genérico
  4. PGDAS-D multa = Art. 38-A com redação LC 214/2025 (não Art. 38 puro)
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ─────────────────────────────────────────────────────────────────────────────
# TIPOS LITERAIS
# ─────────────────────────────────────────────────────────────────────────────

NivelPorte = Literal["MEI", "ME", "EPP", "DEMAIS"]
Regime = Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI", "IMUNE"]
Frequencia = Literal["ANUAL", "MENSAL", "TRIMESTRAL", "SEMESTRAL"]
NivelAlerta = Literal["INFO", "MEDIO", "ALTO", "CRITICO"]


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES IMUTÁVEIS
# ─────────────────────────────────────────────────────────────────────────────

class Obrigacao(BaseModel):
    """Obrigação acessória declarável por porte+regime."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    codigo: str = Field(description="Identificador snake_UPPER (ex: DEFIS).")
    nome: str = Field(description="Nome humano completo.")
    frequencia: Frequencia
    prazo_descricao: str = Field(description="Descrição humana do prazo.")
    multa_descricao: str = Field(description="Descrição humana da multa.")
    base_legal: str = Field(description="Citação legal completa (lei + artigo + §).")
    prazo_dia: Optional[int] = Field(
        default=None,
        description="Dia do mês (1-31) em que vence. None quando 'último dia útil'.",
    )
    prazo_mes: Optional[int] = Field(
        default=None,
        description=(
            "Mês de vencimento (1-12) para frequência ANUAL/SEMESTRAL/TRIMESTRAL. "
            "None para MENSAL (vence no mês seguinte)."
        ),
    )
    prazo_ultimo_dia_util: bool = Field(
        default=False,
        description="True quando vencimento é último dia útil do mês.",
    )
    prazo_offset_meses: int = Field(
        default=1,
        description=(
            "Para frequência MENSAL: número de meses entre a competência e o "
            "mês de vencimento (default 1 = mês seguinte). DCTFWeb usa 2 "
            "('segundo mês seguinte' — IN RFB 2.005/2021)."
        ),
    )
    prazo_n_dia_util: Optional[int] = Field(
        default=None,
        description=(
            "Para frequência MENSAL: K-ésimo dia útil do mês alvo. None desativa. "
            "EFD-Contribuições usa 10 ('10º dia útil do 2º mês seguinte')."
        ),
    )
    prazo_amparo_pendente: bool = Field(
        default=False,
        description=(
            "True quando o prazo aqui declarado vem de fonte ainda não cacheada "
            "(ex: Resolução CGSN 140/2018). Motor avisa mas a citação literal "
            "do prazo aguarda captura — pendência WS7b."
        ),
    )


class AlertaObrigacao(BaseModel):
    """Alerta de obrigação acessória vencendo dentro da janela."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    obrigacao: Obrigacao
    data_vencimento: date
    dias_restantes: int
    nivel: NivelAlerta
    mensagem: str


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS DE DATA
# ─────────────────────────────────────────────────────────────────────────────

def _ultimo_dia_util(ano: int, mes: int) -> date:
    """Último dia útil do mês — heurística sem feriados (ver calendario_legal.py)."""
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    d = date(ano, mes, ultimo_dia)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _n_esimo_dia_util(ano: int, mes: int, n: int) -> date:
    """
    N-ésimo dia útil do mês (1-indexed).

    Heurística sem feriados — mesmo critério de `_ultimo_dia_util`.
    Pra precisão dia-a-dia em obrigações federais, Migrador deve atualizar
    com tabela de feriados nacionais quando relevante.

    Exemplo: 10º dia útil de junho/2027 — usado em EFD-Contribuições
    (prazo "10º dia útil do 2º mês seguinte" — IN RFB 1.252/2012).
    """
    if n < 1:
        raise ValueError(f"n deve ser ≥ 1, recebido {n}")
    d = date(ano, mes, 1)
    contador = 0
    ultimo = calendar.monthrange(ano, mes)[1]
    while d.day <= ultimo:
        if d.weekday() < 5:  # útil
            contador += 1
            if contador == n:
                return d
        if d.day == ultimo:
            break
        d = date(ano, mes, d.day + 1)
    raise ValueError(
        f"Mês {mes:02d}/{ano} não tem {n} dias úteis (máximo {contador})."
    )


def _adicionar_meses(d: date, n: int) -> date:
    """
    Soma n meses a uma data, preservando o dia (ou último dia do mês quando
    o dia original não existe — ex: 31/01 + 1 mês = 28/02 ou 29/02).
    """
    mes_total = d.month + n
    ano = d.year + (mes_total - 1) // 12
    mes = ((mes_total - 1) % 12) + 1
    ultimo = calendar.monthrange(ano, mes)[1]
    return date(ano, mes, min(d.day, ultimo))


def calcular_data_vencimento(
    *,
    frequencia: Frequencia,
    dia: Optional[int],
    mes: Optional[int],
    competencia: date,
    ultimo_dia_util: bool = False,
    offset_meses: int = 1,
    n_dia_util: Optional[int] = None,
) -> date:
    """
    Calcula data de vencimento a partir da competência.

    Casos:
      - ANUAL + dia + mes: vence no `dia/mes` do ano seguinte ao da competência.
      - ANUAL + ultimo_dia_util=True: último dia útil de `mes` no ano seguinte.
      - MENSAL + dia + offset_meses=N: vence no `dia` do N-ésimo mês após
        a competência (default N=1 = mês seguinte).
      - MENSAL + n_dia_util=K + offset_meses=N: vence no K-ésimo dia útil
        do N-ésimo mês após a competência (ex: EFD-Contribuições — 10º dia
        útil do 2º mês seguinte).
      - SEMESTRAL/TRIMESTRAL: pendentes (delegados pra etapa futura).

    Args:
        frequencia: ANUAL | MENSAL | TRIMESTRAL | SEMESTRAL
        dia: dia do vencimento (1-31), ou None se usar ultimo_dia_util / n_dia_util
        mes: mês do vencimento (1-12) — None pra MENSAL
        competencia: data-base da competência fiscal
        ultimo_dia_util: True quando "último dia útil de [mes]"
        offset_meses: deslocamento de meses (apenas MENSAL — default 1)
        n_dia_util: K-ésimo dia útil do mês alvo (apenas MENSAL — None desativa)

    Returns:
        data de vencimento.
    """
    if frequencia == "ANUAL":
        ano_alvo = competencia.year + 1
        if ultimo_dia_util:
            assert mes is not None, "ANUAL + ultimo_dia_util exige mes"
            return _ultimo_dia_util(ano_alvo, mes)
        assert dia is not None and mes is not None, "ANUAL exige dia + mes"
        return date(ano_alvo, mes, dia)

    if frequencia == "MENSAL":
        # Mês alvo é offset_meses depois da competência
        assert offset_meses >= 1, "offset_meses deve ser ≥ 1 (mês seguinte ou posterior)"
        d_alvo = _adicionar_meses(competencia.replace(day=1), offset_meses)
        ano_alvo, mes_alvo = d_alvo.year, d_alvo.month
        if n_dia_util is not None:
            return _n_esimo_dia_util(ano_alvo, mes_alvo, n_dia_util)
        if ultimo_dia_util:
            return _ultimo_dia_util(ano_alvo, mes_alvo)
        assert dia is not None, "MENSAL exige dia (ou n_dia_util / ultimo_dia_util)"
        # Quando dia > último-dia-do-mês-alvo, usa último dia disponível
        ultimo = calendar.monthrange(ano_alvo, mes_alvo)[1]
        return date(ano_alvo, mes_alvo, min(dia, ultimo))

    # TRIMESTRAL e SEMESTRAL ficam pra etapa futura quando obrigações
    # com essas frequências entrarem na matriz.
    raise NotImplementedError(
        f"Frequência {frequencia!r} ainda não implementada. Pendência WS7b."
    )


# ─────────────────────────────────────────────────────────────────────────────
# DERIVAR NÍVEL DE PORTE
# ─────────────────────────────────────────────────────────────────────────────

def derivar_nivel_porte(
    *,
    regime: str,
    enquadramento_simples: Optional[str],
    tipo_societario: Optional[str],  # noqa: ARG001 — futuro: COOPERATIVA tem regras próprias
) -> NivelPorte:
    """
    Mapeia (regime, enquadramento_simples) → NivelPorte.

      MEI/MEI_CAMINHONEIRO → MEI
      ME                   → ME
      EPP                  → EPP
      Demais (Presumido, Real, Imune, Simples sem enquadramento) → DEMAIS
    """
    if enquadramento_simples in ("MEI", "MEI_CAMINHONEIRO"):
        return "MEI"
    if regime == "MEI":
        return "MEI"
    if enquadramento_simples == "ME":
        return "ME"
    if enquadramento_simples == "EPP":
        return "EPP"
    return "DEMAIS"


# ─────────────────────────────────────────────────────────────────────────────
# CITAÇÕES CANÔNICAS (FROZEN — validadas Escrivão 2026-05-08)
# ─────────────────────────────────────────────────────────────────────────────

_AMPARO_DASN_SIMEI: str = (
    "LC 123/2006 Art. 38 § 6º (multa MEI por DASN-SIMEI: mín R$ 50). "
    "Prazo conforme Resolução CGSN 140/2018 (Art. 25 LC 123 delega ao CGSN — "
    "captura agendada em WS7b)"
)

_AMPARO_DEFIS: str = (
    "LC 123/2006 Art. 38 I + § 3º (multa DEFIS: 2% ao mês limitado a 20%; "
    "mín R$ 200; reduções de metade ou 75% conforme § 2º). "
    "Prazo conforme Resolução CGSN 140/2018 (Art. 25 LC 123 delega ao CGSN)"
)

_AMPARO_PGDAS_D: str = (
    "LC 123/2006 Art. 38-A (redação LC 214/2025 — multa por atraso na PGDAS-D: "
    "2% ao mês limitado a 20%; mín R$ 50 por mês-referência; § 2º + R$ 20 "
    "por grupo de 10 informações incorretas). "
    "Prazo conforme Resolução CGSN 140/2018 (Art. 18 § 15-A LC 123 delega ao CGSN)"
)

# WS7b — extensões com cache validado por Escrivão 2026-05-08
_AMPARO_ECF: str = (
    "Decreto-Lei 1.598/77 Art. 8º-A (incluído pela Lei 12.973/2014 Art. 2º — "
    "multa pela falta/atraso de apresentação do livro fiscal: 0,25% por mês "
    "ou fração sobre o lucro líquido antes do IRPJ/CSLL, limitada a 10%; "
    "II — 3% sobre valor omitido/inexato, mín R$ 100,00). "
    "Prazo conforme IN RFB 2.004/2021 (captura pendente WS7b)"
)

_AMPARO_DCTFWEB_DEMAIS: str = (
    "Lei 10.426/2002 Art. 7º (multa por atraso DCTFWeb: 2% ao mês limitado "
    "a 20%; § 3º — mín R$ 500,00 para regime regular não-Simples). "
    "Prazo conforme IN RFB 2.005/2021 (captura pendente WS7b)"
)

# Pendências WS7c (cache de IN RFB ainda não capturável):
# - ECD multa específica: Lei 8.218/91 Art. 11 (escrituração genérica) + Art. 12
#   (percentuais sobre receita; sem piso fixo em reais — pisos em IN RFB pendente)
# - EFD-Contribuições multa específica: idem Art. 12 + IN RFB 1.252/2012 pendente


# ─────────────────────────────────────────────────────────────────────────────
# OBRIGAÇÕES CADASTRADAS (Simples Nacional — apenas multas validadas)
# ─────────────────────────────────────────────────────────────────────────────

_DASN_SIMEI = Obrigacao(
    codigo="DASN_SIMEI",
    nome="DASN-SIMEI — Declaração Anual do Simples Nacional para o MEI",
    frequencia="ANUAL",
    prazo_descricao="31 de maio do ano seguinte (Res. CGSN 140/2018 — pendente cache)",
    multa_descricao="2% ao mês sobre tributos declarados, limitado a 20%; mín R$ 50,00",
    base_legal=_AMPARO_DASN_SIMEI,
    prazo_dia=31,
    prazo_mes=5,
    prazo_amparo_pendente=True,
)

_DEFIS = Obrigacao(
    codigo="DEFIS",
    nome="DEFIS — Declaração de Informações Socioeconômicas e Fiscais",
    frequencia="ANUAL",
    prazo_descricao="31 de março do ano seguinte (Res. CGSN 140/2018 — pendente cache)",
    multa_descricao="2% ao mês sobre tributos declarados, limitado a 20%; mín R$ 200,00",
    base_legal=_AMPARO_DEFIS,
    prazo_dia=31,
    prazo_mes=3,
    prazo_amparo_pendente=True,
)

_PGDAS_D = Obrigacao(
    codigo="PGDAS_D",
    nome="PGDAS-D — Apuração mensal do DAS do Simples Nacional",
    frequencia="MENSAL",
    prazo_descricao="dia 20 do mês seguinte (Res. CGSN 140/2018 — pendente cache)",
    multa_descricao="2% ao mês sobre tributos, limitado a 20%; mín R$ 50,00 por mês-referência",
    base_legal=_AMPARO_PGDAS_D,
    prazo_dia=20,
    prazo_mes=None,
    prazo_amparo_pendente=True,
)

# WS7b — Lucro Presumido / Real / Imune
_ECF = Obrigacao(
    codigo="ECF",
    nome="ECF — Escrituração Contábil Fiscal",
    frequencia="ANUAL",
    prazo_descricao="último dia útil de julho do ano seguinte (IN RFB 2.004/2021 — pendente cache)",
    multa_descricao=(
        "0,25% sobre lucro líquido antes do IRPJ/CSLL por mês ou fração, "
        "limitada a 10%; ou 3% sobre valor omitido/inexato, mín R$ 100,00"
    ),
    base_legal=_AMPARO_ECF,
    prazo_dia=None,
    prazo_mes=7,
    prazo_ultimo_dia_util=True,
    prazo_amparo_pendente=True,
)

_DCTFWEB_DEMAIS = Obrigacao(
    codigo="DCTFWEB",
    nome="DCTFWeb — Declaração de Débitos e Créditos Tributários Federais",
    frequencia="MENSAL",
    prazo_descricao="dia 15 do segundo mês seguinte (IN RFB 2.005/2021 — pendente cache)",
    multa_descricao="2% ao mês sobre os tributos declarados, limitado a 20%; mín R$ 500,00",
    base_legal=_AMPARO_DCTFWEB_DEMAIS,
    prazo_dia=15,
    prazo_mes=None,
    prazo_offset_meses=2,  # "segundo mês seguinte" — IN RFB 2.005/2021
    prazo_amparo_pendente=True,
)


# ─────────────────────────────────────────────────────────────────────────────
# MATRIZ porte × regime → obrigações
# ─────────────────────────────────────────────────────────────────────────────

_MATRIZ: dict[tuple[NivelPorte, Regime], tuple[Obrigacao, ...]] = {
    # MEI é sub-regime do Simples (LC 123/2006 Art. 18-A) — chave canônica
    # única é ("MEI", "SIMPLES"). Caller que passar regime="MEI" é
    # normalizado em obter_obrigacoes() abaixo (regime="MEI" → "SIMPLES").
    ("MEI", "SIMPLES"): (_DASN_SIMEI, _PGDAS_D),
    # ME e EPP no Simples
    ("ME", "SIMPLES"): (_DEFIS, _PGDAS_D),
    ("EPP", "SIMPLES"): (_DEFIS, _PGDAS_D),
    # WS7b — Lucro Presumido + Real (cache validado: ECF + DCTFWeb)
    # ECD/EFD-Contribuições pendentes (sem cache de IN RFB de prazo+multa específica)
    ("DEMAIS", "PRESUMIDO"): (_ECF, _DCTFWEB_DEMAIS),
    ("DEMAIS", "REAL"): (_ECF, _DCTFWEB_DEMAIS),
    # IMUNE: declaração de ECF é obrigação Lei 9.532/97 Art. 12 § 2º (escrituração
    # como requisito de imunidade). Sem cache de IN RFB pra prazo específico, mantém
    # mesma estrutura ECF.
    ("DEMAIS", "IMUNE"): (_ECF,),
}


def _normalizar_regime(regime: str) -> str:
    """
    MEI é sub-regime do Simples (LC 123/2006 Art. 18-A — "tratamento
    diferenciado dentro do Simples"), não regime tributário próprio.

    O schema do motor (`EmpresaFornecedora.regime`) mantém "MEI" como
    valor distinto pra ter MEIEngine isolado com Guard Clause (Camada 2).
    Aqui em obrigações, normalizamos pra evitar duplicação de chave da
    matriz. Combinações absurdas (porte=MEI + regime=PRESUMIDO/REAL/IMUNE)
    NÃO são normalizadas — caem em fallback `()` (Rail R2).
    """
    if regime == "MEI":
        return "SIMPLES"
    return regime


def obter_obrigacoes(*, porte: NivelPorte, regime: str) -> tuple[Obrigacao, ...]:
    """
    Retorna tupla imutável de obrigações aplicáveis ao par (porte, regime).

    Quando combinação não está mapeada, devolve tupla vazia (Rail R2 — sem
    extrapolação). Eventos de "obrigação faltante" são responsabilidade
    do caller, não desta camada.

    Normalização: regime="MEI" é tratado como regime="SIMPLES" (MEI é
    sub-regime do Simples — LC 123/2006 Art. 18-A). Validação de
    coerência porte×regime (ex: MEI×PRESUMIDO é absurdo) vive no
    orquestrador WS6 etapa 6 — não duplicada aqui.
    """
    regime_normalizado = _normalizar_regime(regime)
    return _MATRIZ.get((porte, regime_normalizado), ())


# ─────────────────────────────────────────────────────────────────────────────
# GERAR ALERTAS
# ─────────────────────────────────────────────────────────────────────────────

def _proxima_competencia_aplicavel(
    obrigacao: Obrigacao, hoje: date, competencia_atual: date,
) -> date:
    """
    Resolve qual COMPETÊNCIA está sendo declarada agora.

    Para ANUAL: competência = ano-calendário cujo prazo (ano seguinte +
    dia/mes) é o próximo após `hoje`. Para MENSAL: competência é o mês
    cujo vencimento (mês seguinte + dia) é o próximo após `hoje`.

    Caller pode passar uma `competencia_atual` específica como pista,
    mas a função decide qual competência efetivamente vai vencer próximo.
    """
    if obrigacao.frequencia == "ANUAL":
        # Tenta ano da competência atual; se já passou o vencimento, próximo
        candidato = calcular_data_vencimento(
            frequencia="ANUAL",
            dia=obrigacao.prazo_dia,
            mes=obrigacao.prazo_mes,
            competencia=competencia_atual,
            ultimo_dia_util=obrigacao.prazo_ultimo_dia_util,
        )
        if candidato < hoje:
            # Próxima competência (ano subsequente)
            return date(competencia_atual.year + 1, 12, 31)
        return competencia_atual

    if obrigacao.frequencia == "MENSAL":
        # Mês candidato é o anterior a `hoje` (vencimento é no mês seguinte)
        # Se hoje > vencimento do mês imediato anterior, pula pro próximo
        # competência = competencia_atual; vencimento = mês seguinte dia X
        return competencia_atual

    raise NotImplementedError(
        f"Frequência {obrigacao.frequencia!r} ainda não implementada."
    )


def _classificar_nivel(dias_restantes: int) -> NivelAlerta:
    """
    Heurística de gravidade pelo prazo (dias_restantes):
      ≤ 5  → CRITICO
      ≤ 15 → ALTO
      ≤ 30 → MEDIO
      > 30 → INFO
    """
    if dias_restantes <= 5:
        return "CRITICO"
    if dias_restantes <= 15:
        return "ALTO"
    if dias_restantes <= 30:
        return "MEDIO"
    return "INFO"


def gerar_alertas_obrigacoes(
    *,
    porte: NivelPorte,
    regime: str,
    hoje: date,
    competencia_atual: date,
    dias_antecedencia: int = 30,
) -> tuple[AlertaObrigacao, ...]:
    """
    Gera alertas pra cada obrigação cujo próximo vencimento esteja dentro
    da janela de antecedência (dias_restantes ≤ dias_antecedencia).

    Não dispara alerta pra vencimento já passado (dias_restantes < 0) —
    cabe à camada de UI tratar inadimplência separadamente.

    Args:
        porte: NivelPorte (MEI/ME/EPP/DEMAIS)
        regime: regime tributário
        hoje: data de referência (geralmente date.today())
        competencia_atual: competência fiscal (último dia do período declarado)
        dias_antecedencia: janela em dias pra disparar alerta (default 30)

    Returns:
        tupla imutável de AlertaObrigacao em ordem crescente de dias_restantes.
    """
    obrigacoes = obter_obrigacoes(porte=porte, regime=regime)
    alertas: list[AlertaObrigacao] = []

    for o in obrigacoes:
        try:
            comp_efetiva = _proxima_competencia_aplicavel(o, hoje, competencia_atual)
            data_venc = calcular_data_vencimento(
                frequencia=o.frequencia,
                dia=o.prazo_dia,
                mes=o.prazo_mes,
                competencia=comp_efetiva,
                ultimo_dia_util=o.prazo_ultimo_dia_util,
                offset_meses=o.prazo_offset_meses,
                n_dia_util=o.prazo_n_dia_util,
            )
        except (NotImplementedError, AssertionError):
            # Frequência não-implementada pula sem inventar alerta
            continue

        dias = (data_venc - hoje).days
        if dias < 0:
            # Vencimento passado — caller decide o que fazer
            continue
        if dias > dias_antecedencia:
            continue

        nivel = _classificar_nivel(dias)
        msg = (
            f"{o.nome} vence em {data_venc.isoformat()} ({dias} dias). "
            f"Multa: {o.multa_descricao}. {o.base_legal}"
        )
        alertas.append(AlertaObrigacao(
            obrigacao=o,
            data_vencimento=data_venc,
            dias_restantes=dias,
            nivel=nivel,
            mensagem=msg,
        ))

    alertas.sort(key=lambda a: a.dias_restantes)
    return tuple(alertas)
