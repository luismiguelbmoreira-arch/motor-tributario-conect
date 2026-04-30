# -*- coding: utf-8 -*-
"""
calendario_legal.py — Janelas legais de opt-out e renúncia.

Cobre as duas janelas operacionais que o contador precisa monitorar:

1. RENÚNCIA AO SIMPLES NACIONAL (janela de janeiro)
   - Comunicação até o último dia útil de janeiro de cada ano.
   - Efeitos a partir de 1º de janeiro do mesmo ano-calendário.
   - Amparo: LC 123/2006, Art. 30, caput I + § 1º I; efeitos Art. 31, II.
   - Fonte primária: https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp123.htm

2. OPT-IN REGIME REGULAR CBS/IBS — 1º SEMESTRE/2027 (janela de setembro/2026)
   - Janela firme única regulamentada até a data deste módulo.
   - Período: 01 a 30/09/2026.
   - Efeitos: 01/01/2027 a 30/06/2027 (apenas 1º semestre/2027).
   - Cancelamento irrevogável da opção: até 30/11/2026.
   - Amparo: LC 214/2025, Art. 348 §§ 3º-4º (incluídos por LC 227/2026);
            Resolução CGSN nº 186/2026, art. 2º.
   - Fontes primárias:
     - https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm
     - https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp227.htm
     - Resolução CGSN 186/2026 (DOU 17/04/2026, ato 09/04/2026)

JANELAS POSTERIORES (2º sem/2027, 2028+):
NÃO modeladas neste módulo enquanto Resolução CGSN específica não for publicada.
Qualquer data inventada violaria Rail R2 (proibição de extrapolação). Quando
nova Resolução CGSN sair, Migrador adiciona a constante correspondente — o
schema `JanelaLegal.pendente_regulamentacao` segue disponível mas sem instância
ativa no momento.

Heurísticas internas (não-normativas) marcadas explicitamente.
"""

import calendar
from datetime import date, timedelta
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

TipoJanela = Literal["RENUNCIA_SIMPLES", "OPT_IN_REGULAR_CBS_IBS"]


class JanelaLegal(BaseModel):
    """
    Janela legal de renúncia ao Simples ou opt-in CBS/IBS.

    Quando `pendente_regulamentacao=True`, datas firmes podem ser None e
    `janela_aproximada` traz texto descritivo (ex: "Esperada 2º sem/2027").
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    nome: str = Field(..., description="Nome humano da janela")
    tipo: TipoJanela = Field(..., description="Tipo da janela")
    pendente_regulamentacao: bool = Field(
        ...,
        description="True quando lei prevê a janela mas regulamentação ainda não saiu",
    )
    data_inicio: Optional[date] = Field(default=None, description="Início do período de comunicação/opção")
    data_fim: Optional[date] = Field(default=None, description="Fim do período de comunicação/opção")
    data_efeitos_inicio: Optional[date] = Field(default=None, description="Quando o efeito da opção começa")
    data_efeitos_fim: Optional[date] = Field(default=None, description="Quando o efeito da opção termina (None = indefinido)")
    cancelamento_irrevogavel_ate: Optional[date] = Field(
        default=None,
        description="Última data pra cancelar a opção. None = não aplicável.",
    )
    janela_aproximada: Optional[str] = Field(
        default=None,
        description="Texto descritivo quando pendente_regulamentacao=True",
    )
    amparo_legal: str = Field(..., description="Citação legal completa (lei + artigo + §)")

    @model_validator(mode="after")
    def _validar_consistencia(self) -> "JanelaLegal":
        if not self.pendente_regulamentacao:
            if self.data_inicio is None or self.data_fim is None:
                raise ValueError(
                    "Janela firme requer data_inicio e data_fim. "
                    "Se a regulamentação ainda não saiu, use pendente_regulamentacao=True."
                )
            if self.data_inicio > self.data_fim:
                raise ValueError(
                    f"data_inicio ({self.data_inicio}) deve ser ≤ data_fim ({self.data_fim})."
                )
        return self


class AlertaJanelaLegal(BaseModel):
    """Alerta de janela legal próxima ou aberta."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    janela: JanelaLegal
    dias_restantes: int = Field(..., description="Dias até a janela abrir. 0 = aberta hoje, negativo = última oportunidade hoje")
    mensagem: str
    amparo_legal: str


# ── Helpers internos ─────────────────────────────────────────────────────────

def _ultimo_dia_util_mes(ano: int, mes: int) -> date:
    """
    Último dia útil do mês — desconsidera apenas sábados e domingos.

    LIMITAÇÃO CONHECIDA: não considera feriados nacionais (CLT Art. 70 §1º
    e Lei 662/1949). Heurística interna conservadora — em janeiro o único
    feriado nacional é 1º (Confraternização Universal), que nunca é o último
    dia útil. Para outros meses, Migrador deve atualizar com tabela de
    feriados se precisar precisão dia-a-dia.
    """
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    d = date(ano, mes, ultimo_dia)
    while d.weekday() >= 5:  # 5=sábado, 6=domingo
        d -= timedelta(days=1)
    return d


def _janela_renuncia_simples(ano: int) -> JanelaLegal:
    """
    Constrói a janela de janeiro pra renúncia ao Simples Nacional.

    LC 123/2006, Art. 30, caput I + § 1º I; efeitos Art. 31, II.
    """
    return JanelaLegal(
        nome=f"Renúncia ao Simples Nacional — efeitos {ano}",
        tipo="RENUNCIA_SIMPLES",
        pendente_regulamentacao=False,
        data_inicio=date(ano, 1, 1),
        data_fim=_ultimo_dia_util_mes(ano, 1),
        data_efeitos_inicio=date(ano, 1, 1),
        data_efeitos_fim=None,
        cancelamento_irrevogavel_ate=None,
        amparo_legal="LC 123/2006, Art. 30, caput I + § 1º I; efeitos Art. 31, II",
    )


# ── Constantes firmes (fonte primária validada por Escrivão em 29/04/2026) ──

JANELA_OPT_IN_CBS_IBS_SET_2026 = JanelaLegal(
    nome="Opt-in Regime Regular CBS/IBS — 1º semestre/2027",
    tipo="OPT_IN_REGULAR_CBS_IBS",
    pendente_regulamentacao=False,
    data_inicio=date(2026, 9, 1),
    data_fim=date(2026, 9, 30),
    data_efeitos_inicio=date(2027, 1, 1),
    data_efeitos_fim=date(2027, 6, 30),
    cancelamento_irrevogavel_ate=date(2026, 11, 30),
    amparo_legal=(
        "LC 214/2025, Art. 348 §§ 3º-4º (incluídos por LC 227/2026); "
        "Resolução CGSN nº 186/2026, art. 2º"
    ),
)


# Lista vazia até Migrador acrescentar nova Resolução CGSN regulamentando
# janelas posteriores (2º sem/2027, 2028+). Rail R2 — sem fonte primária,
# sem instância. O schema `JanelaLegal.pendente_regulamentacao` segue
# disponível pra quando precisar.
JANELAS_PENDENTES_REGULAMENTACAO: List[JanelaLegal] = []


# ── API pública ──────────────────────────────────────────────────────────────

def listar_janelas_firmes(hoje: date, anos_futuro: int = 2) -> List[JanelaLegal]:
    """
    Retorna todas as janelas firmes (não-pendentes) relevantes a partir de hoje.

    Inclui janelas cujo data_fim >= hoje. Lista é ordenada cronologicamente.
    `anos_futuro` controla até quando gerar janelas anuais de Renúncia Simples.
    """
    if anos_futuro < 0:
        raise ValueError(f"anos_futuro deve ser >= 0, recebido {anos_futuro}.")

    janelas: List[JanelaLegal] = []

    if JANELA_OPT_IN_CBS_IBS_SET_2026.data_fim is not None and JANELA_OPT_IN_CBS_IBS_SET_2026.data_fim >= hoje:
        janelas.append(JANELA_OPT_IN_CBS_IBS_SET_2026)

    for ano in range(hoje.year, hoje.year + anos_futuro + 1):
        renuncia = _janela_renuncia_simples(ano)
        if renuncia.data_fim is not None and renuncia.data_fim >= hoje:
            janelas.append(renuncia)

    return sorted(janelas, key=lambda j: j.data_inicio or date.max)


def janela_aberta_hoje(hoje: date, janela: JanelaLegal) -> bool:
    """True se hoje ∈ [data_inicio, data_fim]. Pendentes retornam False."""
    if janela.pendente_regulamentacao:
        return False
    if janela.data_inicio is None or janela.data_fim is None:
        return False
    return janela.data_inicio <= hoje <= janela.data_fim


def dias_restantes_para_janela(hoje: date, janela: JanelaLegal) -> Optional[int]:
    """
    Dias até a janela abrir.

    - Retorna 0 se a janela está aberta hoje (hoje ∈ [inicio, fim]).
    - Retorna inteiro positivo se a janela ainda vai abrir (futuro).
    - Retorna None se a janela já fechou (passou) OU é pendente.
    """
    if janela.pendente_regulamentacao:
        return None
    if janela.data_inicio is None or janela.data_fim is None:
        return None
    if hoje > janela.data_fim:
        return None
    if hoje >= janela.data_inicio:
        return 0
    return (janela.data_inicio - hoje).days


def proxima_janela_optout(
    hoje: date,
    tipo_filtro: Optional[TipoJanela] = None,
    anos_futuro: int = 2,
) -> Optional[JanelaLegal]:
    """
    Retorna a próxima janela firme cuja `data_fim >= hoje`.

    Se `tipo_filtro` é fornecido, restringe ao tipo (RENUNCIA_SIMPLES ou
    OPT_IN_REGULAR_CBS_IBS). Janelas pendentes são ignoradas.

    Retorna None se nenhuma janela firme está disponível.
    """
    janelas = listar_janelas_firmes(hoje, anos_futuro=anos_futuro)
    if tipo_filtro is not None:
        janelas = [j for j in janelas if j.tipo == tipo_filtro]
    return janelas[0] if janelas else None


def alertar_janelas_proximas(
    hoje: date,
    n_dias_aviso: int = 30,
    anos_futuro: int = 2,
) -> List[AlertaJanelaLegal]:
    """
    Gera alertas pra cada janela firme que está aberta hoje OU abre em ≤ n_dias_aviso dias.

    HEURÍSTICA INTERNA — limiar de 30 dias é convenção operacional, não valor
    normativo. Justificativa: prazos de comunicação fiscal típicos giram em
    torno de 1 mês para o cliente reunir documentação e decidir.
    """
    if n_dias_aviso < 0:
        raise ValueError(f"n_dias_aviso deve ser >= 0, recebido {n_dias_aviso}.")

    alertas: List[AlertaJanelaLegal] = []
    for janela in listar_janelas_firmes(hoje, anos_futuro=anos_futuro):
        dias = dias_restantes_para_janela(hoje, janela)
        if dias is None:
            continue
        if dias > n_dias_aviso:
            continue

        if dias == 0:
            ate = janela.data_fim
            assert ate is not None  # garantido por listar_janelas_firmes
            mensagem = (
                f"Janela ABERTA HOJE ({janela.nome}). "
                f"Encerra em {ate.isoformat()} ({(ate - hoje).days} dias restantes pra comunicar)."
            )
        else:
            mensagem = (
                f"Janela ABRE em {dias} dia(s) ({janela.nome}). "
                f"Período: {janela.data_inicio} a {janela.data_fim}."
            )

        alertas.append(AlertaJanelaLegal(
            janela=janela,
            dias_restantes=dias,
            mensagem=mensagem,
            amparo_legal=janela.amparo_legal,
        ))
    return alertas
