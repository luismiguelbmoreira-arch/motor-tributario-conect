# -*- coding: utf-8 -*-
"""
elegibilidade_societaria.py — Matriz Tipo Societário × Regime Tributário
Projeto: Motor Tributário Conect 2026-2033

WS6 Etapa 2 do plano de refinamento. Função pura, sem efeitos colaterais.

ESCOPO:
  Responde APENAS à pergunta "tipo societário X pode optar por regime Y?".
  Não trata limites de faturamento (WS10 — VersionedRule), não trata
  vedações por CNAE (WS12 — categoria E_VEDADO), não trata requisitos
  específicos de MEI/Imune (WS6 etapas 3 e 4).

  O orquestrador da etapa 6 compõe esta matriz com WS10 + WS12 + sub-
  validadores via AND lógico. Cliente do motor não vê a divisão.

REFERÊNCIA:
  - LC 123/2006 Art. 3º §4º (vedações ao Simples por forma jurídica)
  - Lei 9.718/98 Art. 13-14 (Lucro Presumido e obrigatoriedade do Real)
  - CC Art. 53 (associações), Art. 62-69 (fundações)
  - CF Art. 150 VI b (templos), VI c (associações sem fins lucrativos)
  - Lei 5.764/71 (cooperativas)
  - Plano: docs/especificacoes/WS12_schema_cnae_luiz_moreira.md (referência)
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

TipoSocietario = Literal[
    "EI", "SLU", "LTDA", "SS", "SA", "COOPERATIVA",
    "ASSOCIACAO", "FUNDACAO", "ORGANIZACAO_RELIGIOSA",
]

RegimeBase = Literal["SIMPLES", "PRESUMIDO", "REAL", "IMUNE"]


class Elegibilidade(BaseModel):
    """
    Resultado da consulta (tipo_societario, regime) -> elegibilidade fiscal.
    """

    model_config = ConfigDict(frozen=True)

    valido: bool = Field(description="Combinação é permitida em lei?")
    base_legal: str = Field(description="Lei ou artigo que sustenta a decisão")
    motivo: Optional[str] = Field(
        default=None,
        description="Quando valido=False, descreve por que a combinação é vedada",
    )
    condicoes: tuple[str, ...] = Field(
        default=(),
        description="Quando valido=True mas requer condições adicionais",
    )
    obrigatorio: bool = Field(
        default=False,
        description="Quando valido=True E o regime é obrigatório (não opcional)",
    )
    observacao: Optional[str] = Field(default=None)


# ─────────────────────────────────────────────────────────────────────────────
# MATRIZ 9×4 — uma célula por combinação (tipo, regime).
# Ordenada por tipo. Cada célula traz base legal explícita.
# ─────────────────────────────────────────────────────────────────────────────

_MATRIZ: dict[tuple[TipoSocietario, RegimeBase], Elegibilidade] = {

    # ─── EI (Empresário Individual) ────────────────────────────────────────
    ("EI", "SIMPLES"): Elegibilidade(
        valido=True,
        base_legal="LC 123/2006 Art. 3º caput (ME/EPP) + Art. 18-A (MEI)",
        condicoes=(
            "Faturamento dentro do limite ME/EPP (R$ 4,8M) ou MEI (R$ 81k)",
            "Atividade não vedada (Art. 17)",
        ),
    ),
    ("EI", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.718/98 Art. 13",
        condicoes=("Faturamento ≤ R$ 78M (Lei 12.814/2013)",),
    ),
    ("EI", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º + RIR/2018 Art. 257",
    ),
    ("EI", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CF Art. 150 VI c",
        motivo="EI tem finalidade lucrativa por natureza; imunidade alcança "
               "associações/fundações sem fins lucrativos",
    ),

    # ─── SLU (Sociedade Limitada Unipessoal) ───────────────────────────────
    ("SLU", "SIMPLES"): Elegibilidade(
        valido=True,
        base_legal="LC 123/2006 Art. 3º caput (incluiu SLU desde Lei 13.874/19)",
        condicoes=(
            "Faturamento dentro do limite ME/EPP",
            "Atividade não vedada",
        ),
    ),
    ("SLU", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.718/98 Art. 13",
        condicoes=("Faturamento ≤ R$ 78M",),
    ),
    ("SLU", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º",
    ),
    ("SLU", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CF Art. 150 VI c",
        motivo="SLU tem finalidade lucrativa",
    ),

    # ─── LTDA (Sociedade Empresária Limitada) ──────────────────────────────
    ("LTDA", "SIMPLES"): Elegibilidade(
        valido=True,
        base_legal="LC 123/2006 Art. 3º caput",
        condicoes=(
            "Faturamento dentro do limite ME/EPP",
            "Sócios pessoas físicas (Art. 3º §4º I e II)",
            "Atividade não vedada",
        ),
    ),
    ("LTDA", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.718/98 Art. 13",
        condicoes=("Faturamento ≤ R$ 78M (Lei 12.814/2013)",),
    ),
    ("LTDA", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º + Lei 9.718/98 Art. 14",
        observacao="Real é obrigatório se faturamento > R$ 78M ou atividade "
                   "do Art. 14 (financeira, factoring, etc.) — validar via WS12+WS10",
    ),
    ("LTDA", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CF Art. 150 VI c",
        motivo="LTDA empresarial tem finalidade lucrativa",
    ),

    # ─── SS (Sociedade Simples) ────────────────────────────────────────────
    ("SS", "SIMPLES"): Elegibilidade(
        valido=True,
        base_legal="LC 123/2006 Art. 3º caput + Art. 17",
        condicoes=(
            "Profissão regulamentada listada no Art. 18 §5º-B/C/D",
            "Faturamento dentro do limite ME/EPP",
        ),
        observacao="SS de profissão NÃO listada nos parágrafos do Art. 18 "
                   "fica vedada — validar via WS12 (CNAE)",
    ),
    ("SS", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.718/98 Art. 13",
        condicoes=("Faturamento ≤ R$ 78M",),
    ),
    ("SS", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º",
    ),
    ("SS", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CF Art. 150 VI c",
        motivo="SS tem finalidade lucrativa",
    ),

    # ─── SA (Sociedade Anônima) ────────────────────────────────────────────
    ("SA", "SIMPLES"): Elegibilidade(
        valido=False,
        base_legal="LC 123/2006 Art. 3º §4º X",
        motivo="Sociedade por ações é vedada ao Simples Nacional",
    ),
    ("SA", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.718/98 Art. 13",
        condicoes=("Faturamento ≤ R$ 78M",),
        observacao="SA de capital aberto e instituições financeiras geralmente "
                   "obrigadas ao Real (Lei 9.718/98 Art. 14)",
    ),
    ("SA", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º + Lei 9.718/98 Art. 14",
        observacao="Obrigatório para SA de capital aberto, financeiras, "
                   "seguradoras — validar atividade via WS12",
    ),
    ("SA", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CF Art. 150 VI c",
        motivo="SA tem finalidade lucrativa",
    ),

    # ─── COOPERATIVA (Lei 5.764/71) ────────────────────────────────────────
    ("COOPERATIVA", "SIMPLES"): Elegibilidade(
        valido=False,
        base_legal="LC 123/2006 Art. 3º §1º + §4º",
        motivo="Cooperativas em geral não optam pelo Simples — cooperativa "
               "de trabalho é explicitamente vedada",
        observacao="EXCEÇÃO: cooperativa de consumo pode optar (Art. 3º §1º). "
                   "Validar caso a caso via WS12 (CNAE) antes de bloquear.",
    ),
    ("COOPERATIVA", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.718/98 Art. 13 + Lei 5.764/71 Art. 87",
        condicoes=(
            "Faturamento ≤ R$ 78M",
            "Atos cooperativos segregados de atos não-cooperativos",
        ),
    ),
    ("COOPERATIVA", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 5.764/71 Art. 87 + Lei 9.430/96 Art. 1º",
        observacao="Cooperativas de crédito obrigadas ao Real (Lei 9.718/98 Art. 14)",
    ),
    ("COOPERATIVA", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CF Art. 150 VI + Lei 5.764/71",
        motivo="Cooperativa não é entidade imune; tem regime tributário "
               "próprio (ato cooperativo não tributado, Art. 79 Lei 5.764/71)",
    ),

    # ─── ASSOCIACAO (CC Art. 53) ───────────────────────────────────────────
    ("ASSOCIACAO", "SIMPLES"): Elegibilidade(
        valido=False,
        base_legal="LC 123/2006 Art. 3º caput",
        motivo="Associação não é ME/EPP — Simples é regime para empresas "
               "com fins lucrativos",
    ),
    ("ASSOCIACAO", "PRESUMIDO"): Elegibilidade(
        valido=False,
        base_legal="Lei 9.718/98 Art. 13",
        motivo="Presumido pressupõe lucro — associação sem fins lucrativos "
               "não se enquadra. Quando perde imunidade, vai para Real",
    ),
    ("ASSOCIACAO", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º + RIR/2018 Art. 184",
        condicoes=(
            "Quando perde imunidade ou isenção por descumprir Art. 14 CTN",
        ),
        observacao="Caminho fiscal padrão é IMUNE; cai em Real apenas em "
                   "infrações ou atividades não amparadas pela imunidade",
    ),
    ("ASSOCIACAO", "IMUNE"): Elegibilidade(
        valido=True,
        base_legal="CF Art. 150 VI c + CTN Art. 14",
        condicoes=(
            "Sem distribuição de lucro (CTN Art. 14 I)",
            "Não remeter recursos ao exterior (CTN Art. 14 II)",
            "Manter escrituração regular (CTN Art. 14 III)",
        ),
    ),

    # ─── FUNDACAO (CC Art. 62-69) ──────────────────────────────────────────
    ("FUNDACAO", "SIMPLES"): Elegibilidade(
        valido=False,
        base_legal="LC 123/2006 Art. 3º caput",
        motivo="Fundação não é ME/EPP",
    ),
    ("FUNDACAO", "PRESUMIDO"): Elegibilidade(
        valido=False,
        base_legal="Lei 9.718/98 Art. 13",
        motivo="Presumido pressupõe lucro — fundação sem fins lucrativos não se enquadra",
    ),
    ("FUNDACAO", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º",
        condicoes=("Quando perde imunidade ou exerce atividade não amparada",),
    ),
    ("FUNDACAO", "IMUNE"): Elegibilidade(
        valido=True,
        base_legal="CF Art. 150 VI c + CTN Art. 14",
        condicoes=(
            "Sem distribuição de patrimônio aos instituidores (CTN Art. 14 I)",
            "Não remeter recursos ao exterior (CTN Art. 14 II)",
            "Manter escrituração regular (CTN Art. 14 III)",
            "Atendimento à finalidade estatutária (CC Art. 62)",
        ),
    ),

    # ─── ORGANIZACAO_RELIGIOSA (Lei 10.825/2003) ───────────────────────────
    ("ORGANIZACAO_RELIGIOSA", "SIMPLES"): Elegibilidade(
        valido=False,
        base_legal="LC 123/2006 Art. 3º",
        motivo="Templos não são ME/EPP",
    ),
    ("ORGANIZACAO_RELIGIOSA", "PRESUMIDO"): Elegibilidade(
        valido=False,
        base_legal="Lei 9.718/98 Art. 13",
        motivo="Templos não exercem atividade com finalidade lucrativa",
    ),
    ("ORGANIZACAO_RELIGIOSA", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º",
        condicoes=("Quando exerce atividade econômica não amparada pela imunidade",),
        observacao="Imunidade alcança apenas culto e atividades essenciais — "
                   "comércio paralelo (livraria, café) cai em Real",
    ),
    ("ORGANIZACAO_RELIGIOSA", "IMUNE"): Elegibilidade(
        valido=True,
        base_legal="CF Art. 150 VI b (templos de qualquer culto)",
        condicoes=(
            "Atividade limitada a culto e fins essenciais (CF Art. 150 §4º)",
            "Sem distribuição de patrimônio (CTN Art. 14 I aplicado por analogia)",
        ),
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────────────────────

def elegibilidade(
    tipo_societario: TipoSocietario,
    regime: RegimeBase,
) -> Elegibilidade:
    """
    Consulta a matriz e retorna a elegibilidade da combinação.

    Função pura: mesma entrada -> mesma saída, sem efeitos colaterais.

    Raises:
        KeyError: se a combinação não estiver mapeada — defesa em profundidade
                  contra Literal mal validado pelo caller.
    """
    chave = (tipo_societario, regime)
    if chave not in _MATRIZ:
        raise KeyError(
            f"Combinação não mapeada: {tipo_societario} × {regime}. "
            f"Verifique se o tipo e o regime estão nos Literals válidos."
        )
    return _MATRIZ[chave]


def regimes_permitidos(tipo_societario: TipoSocietario) -> tuple[RegimeBase, ...]:
    """
    Lista os regimes em que `tipo_societario` é elegível (valido=True).
    Útil para UI que precisa pré-filtrar opções no formulário.
    """
    return tuple(
        regime for regime in ("SIMPLES", "PRESUMIDO", "REAL", "IMUNE")
        if _MATRIZ[(tipo_societario, regime)].valido
    )


def tipos_para_regime(regime: RegimeBase) -> tuple[TipoSocietario, ...]:
    """
    Lista os tipos societários que podem optar por `regime`.
    Inverso de regimes_permitidos. Útil para validação reversa.
    """
    todos: tuple[TipoSocietario, ...] = (
        "EI", "SLU", "LTDA", "SS", "SA", "COOPERATIVA",
        "ASSOCIACAO", "FUNDACAO", "ORGANIZACAO_RELIGIOSA",
    )
    return tuple(t for t in todos if _MATRIZ[(t, regime)].valido)
