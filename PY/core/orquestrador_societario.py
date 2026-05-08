# -*- coding: utf-8 -*-
"""
orquestrador_societario.py — WS6 Etapa 6
Orquestrador `validar_combinacao()` consolida WS6 + WS10 + WS12 num
único resultado.

OBJETIVO:
  AND lógico de:
    1. Matriz societária 13×4    — core.elegibilidade_societaria
    2. Sub-validador MEI         — core.validador_mei
    3. Sub-validador COOPERATIVA — core.validador_cooperativa
    4. Resolução CNAE × Anexo    — core.regras_cnae
    5. Limites versionados       — core.versioned_rule

  CONCATENA TODAS as falhas — não para na primeira. Operador vê tudo
  num único diagnóstico, em vez de iterar fix-rerun-fix-rerun.

  NÃO levanta exceção — caller decide tratamento (HTTP 422, warning UI,
  registro em trilha, ou bloqueio total). Schema Pydantic já valida
  estrutura; orquestrador valida COMBINAÇÃO semântica.

CONTRATO:
  validar_combinacao(*, fornecedora, data_emissao, fator_r_calculado=None)
      → ResultadoOrquestracaoSocietaria

POSICIONAMENTO ARQUITETURAL:
  Schema (Pydantic V2)   → estrutura: campos, tipos, ranges, conversões
  Orquestrador (este)    → combinação: tipo×regime×CNAE×limite versionado
  Engines / Overlay      → execução: cálculo IBS/CBS/IRPJ/CSLL etc.
  Guard Clause Camada 2  → defesa em profundidade: bloqueia engine errado

  Os 4 níveis coexistem. Orquestrador é o único com visão holística.

REFERÊNCIA:
  - LC 123/2006 (delegado a validador_mei + matriz)
  - LC 214/2025 (delegado a validador_cooperativa + cronograma)
  - Lei 5.764/71 (delegado a validador_cooperativa)
  - Lei 9.430/96 + Lei 9.718/98 (limites Real/Presumido)
  - Rails R1, R3, R5, R7, R8 (CLAUDE.md)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.elegibilidade_societaria import (
    CombinacaoSocietariaNaoMapeadaError,
    elegibilidade,
)
from core.regras_cnae import is_vedado, resolve_anexo
from core.validador_cooperativa import validar_cooperativa
from core.validador_mei import validar_mei
from core.versioned_rule import (
    LIMITE_LUCRO_PRESUMIDO_VERSIONADO,
    TETO_SIMPLES_NACIONAL_VERSIONADO,
    valor_em,
)

# TYPE_CHECKING evita ciclo runtime — schemas.motor não importa este módulo,
# então a forward reference resolve em type-check sem custo de import real.
if TYPE_CHECKING:
    from schemas.motor import EmpresaFornecedora

# ─────────────────────────────────────────────────────────────────────────────
# ORIGEM DOS BLOQUEIOS / ALERTAS — taxonomia para rastreabilidade
# ─────────────────────────────────────────────────────────────────────────────

OrigemBloqueio = Literal[
    "MATRIZ_SOCIETARIA",       # core.elegibilidade_societaria
    "VALIDADOR_MEI",           # core.validador_mei
    "VALIDADOR_COOPERATIVA",   # core.validador_cooperativa
    "REGRA_CNAE",              # core.regras_cnae
    "LIMITE_VERSIONADO",       # core.versioned_rule (RBT12 vs teto)
    "ORQUESTRADOR",            # falha estrutural detectada aqui
]


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES IMUTÁVEIS
# ─────────────────────────────────────────────────────────────────────────────

class Bloqueio(BaseModel):
    """Falha que torna a combinação inválida."""

    model_config = ConfigDict(frozen=True)

    origem: OrigemBloqueio = Field(description="Validador que detectou a falha.")
    mensagem: str = Field(description="Descrição humana.")
    base_legal: str = Field(default="", description="Lei/artigo invocado.")


class Alerta(BaseModel):
    """Aviso não-bloqueante (Rail R7, cronograma, recomendação)."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(description="Identificador snake_UPPER (ex: ALERTA_TETO_PROXIMO).")
    titulo: str = Field(description="Título humano curto.")
    detalhe: str = Field(description="Mensagem completa pro operador.")
    base_legal: str = Field(default="", description="Lei/artigo invocado.")


class ResultadoOrquestracaoSocietaria(BaseModel):
    """
    Resultado consolidado do orquestrador.

    Concatena bloqueios de todos os validadores (matriz + MEI + cooperativa
    + CNAE + limites versionados). Não para na primeira falha.
    """

    model_config = ConfigDict(frozen=True)

    valido: bool = Field(description="AND de todos os validadores (sem bloqueios).")
    bloqueios: tuple[Bloqueio, ...] = Field(default=(), description="Falhas concatenadas.")
    pendencias: tuple[str, ...] = Field(default=(), description="Itens indeterminados.")
    alertas: tuple[Alerta, ...] = Field(default=(), description="Avisos não-bloqueantes.")
    base_legal_aplicavel: tuple[str, ...] = Field(
        default=(), description="União das bases legais de todos os validadores."
    )
    engine_recomendado: str = Field(description="Engine que o motor deve instanciar.")
    overlay_aplicavel: Optional[Literal["COOPERATIVA"]] = Field(
        default=None,
        description="Overlay sobreposto ao engine regular (None se não aplicável).",
    )
    anexo_simples_resolvido: Optional[str] = Field(
        default=None,
        description="Anexo Simples I-V resolvido via core.regras_cnae (None se não aplicável).",
    )


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS DE CONVERSÃO
# ─────────────────────────────────────────────────────────────────────────────

def _regime_para_matriz(regime: str) -> Optional[str]:
    """
    A matriz societária só conhece SIMPLES/PRESUMIDO/REAL/IMUNE.
    Regime MEI no schema mapeia para SIMPLES na matriz (LC 123/2006 — MEI
    é status do Simples para EI ≤ R$ 81k).
    """
    if regime == "MEI":
        return "SIMPLES"
    if regime in ("SIMPLES", "PRESUMIDO", "REAL", "IMUNE"):
        return regime
    return None


def _consultar_matriz_societaria(
    fornecedora: "EmpresaFornecedora",
    bloqueios: list[Bloqueio],
    leis: list[str],
) -> None:
    """
    Consulta core.elegibilidade_societaria.elegibilidade(tipo, regime).
    Acumula bloqueios/leis. Tipos None ou ausência de matriz mapeada
    são tolerados — outras camadas detectam.
    """
    tipo = fornecedora.tipo_societario
    regime_matriz = _regime_para_matriz(fornecedora.regime)
    if tipo is None or regime_matriz is None:
        return  # Schema deveria garantir; orquestrador não inventa

    try:
        eleg = elegibilidade(tipo, regime_matriz)
    except CombinacaoSocietariaNaoMapeadaError as e:
        bloqueios.append(Bloqueio(
            origem="MATRIZ_SOCIETARIA",
            mensagem=f"Combinação não mapeada na matriz societária: {e}",
            base_legal="core.elegibilidade_societaria.MATRIZ",
        ))
        return

    leis.append(eleg.base_legal)
    if not eleg.valido:
        bloqueios.append(Bloqueio(
            origem="MATRIZ_SOCIETARIA",
            mensagem=(
                f"Combinação tipo_societario='{tipo}' × regime='{regime_matriz}' "
                f"é vedada. Motivo: {eleg.motivo or 'ver base legal'}."
            ),
            base_legal=eleg.base_legal,
        ))


def _consultar_validador_mei(
    fornecedora: "EmpresaFornecedora",
    data_emissao: date,
    bloqueios: list[Bloqueio],
    pendencias: list[str],
    leis: list[str],
) -> None:
    """Roda validar_mei quando enquadramento_simples in (MEI, MEI_CAMINHONEIRO)."""
    if fornecedora.enquadramento_simples not in ("MEI", "MEI_CAMINHONEIRO"):
        return

    r = validar_mei(
        tipo_societario=fornecedora.tipo_societario,
        enquadramento_simples=fornecedora.enquadramento_simples,
        cnae_principal=fornecedora.cnae_principal,
        faturamento_12m=fornecedora.faturamento_12m,
        data_emissao=data_emissao,
    )
    leis.extend(r.base_legal_aplicavel)
    for motivo in r.motivos_bloqueio:
        bloqueios.append(Bloqueio(
            origem="VALIDADOR_MEI",
            mensagem=motivo,
            base_legal="; ".join(r.base_legal_aplicavel),
        ))
    pendencias.extend(r.pendencias)


def _consultar_validador_cooperativa(
    fornecedora: "EmpresaFornecedora",
    data_emissao: date,
    bloqueios: list[Bloqueio],
    pendencias: list[str],
    leis: list[str],
) -> bool:
    """
    Roda validar_cooperativa quando tipo_societario=COOPERATIVA.
    Retorna True se overlay COOPERATIVA é aplicável.
    """
    if fornecedora.tipo_societario != "COOPERATIVA":
        return False

    r = validar_cooperativa(
        tipo_societario=fornecedora.tipo_societario,
        subtipo_cooperativa=fornecedora.subtipo_cooperativa,
        regime=fornecedora.regime,
        cnae_principal=fornecedora.cnae_principal,
        optante_art271=bool(fornecedora.optante_art271_cbs_ibs),
        data_emissao=data_emissao,
        data_opcao_art271=fornecedora.data_opcao_art271,
    )
    leis.extend(r.base_legal_aplicavel)
    for motivo in r.motivos_bloqueio:
        bloqueios.append(Bloqueio(
            origem="VALIDADOR_COOPERATIVA",
            mensagem=motivo,
            base_legal="; ".join(r.base_legal_aplicavel),
        ))
    pendencias.extend(r.pendencias)
    return r.aplicavel


def _consultar_regras_cnae(
    fornecedora: "EmpresaFornecedora",
    fator_r_calculado: Optional[Decimal],
    bloqueios: list[Bloqueio],
    leis: list[str],
) -> Optional[str]:
    """
    Resolve CNAE × Anexo (Rail R1/R5).
    Bloqueia se CNAE explicitamente vedado no Simples (E_VEDADO).
    Retorna anexo resolvido (string) quando aplicável.
    """
    cnae = fornecedora.cnae_principal

    if fornecedora.regime == "SIMPLES" and is_vedado(cnae):
        bloqueios.append(Bloqueio(
            origem="REGRA_CNAE",
            mensagem=(
                f"CNAE {cnae} é vedado no Simples Nacional (LC 123/2006 Art. 17). "
                "Empresa precisa migrar para Presumido ou Real."
            ),
            base_legal="LC 123/2006 Art. 17 + Resolução CGSN 140/2018",
        ))
        leis.append("LC 123/2006 Art. 17 (vedações Simples)")

    # Resolução de anexo só faz sentido para SIMPLES/MEI
    if fornecedora.regime in ("SIMPLES", "MEI"):
        try:
            anexo, fonte = resolve_anexo(cnae, fator_r_calculado)
            leis.append(f"core.regras_cnae fonte={fonte}")
            return anexo
        except Exception:
            return None
    return None


def _consultar_limites_versionados(
    fornecedora: "EmpresaFornecedora",
    data_emissao: date,
    bloqueios: list[Bloqueio],
    alertas: list[Alerta],
    leis: list[str],
) -> None:
    """
    Rail R3 (versão normativa) + R7 (≥ 90% do teto → migração obrigatória).
    Verifica limites de Simples e Lucro Presumido conforme regime.
    """
    rbt12 = fornecedora.faturamento_12m
    regime = fornecedora.regime

    if regime in ("SIMPLES", "MEI"):
        # Teto Simples Nacional R$ 4.800.000 (LC 155/2016 a partir de 2018)
        try:
            teto = valor_em(TETO_SIMPLES_NACIONAL_VERSIONADO, data_emissao)
        except ValueError:
            return  # Fora da janela; não inventa
        leis.append(f"Teto Simples vigente em {data_emissao}: R$ {teto}")
        if regime == "SIMPLES" and rbt12 > teto:
            bloqueios.append(Bloqueio(
                origem="LIMITE_VERSIONADO",
                mensagem=(
                    f"RBT12 R$ {rbt12} excede teto do Simples Nacional R$ {teto} "
                    f"vigente em {data_emissao.isoformat()}. Empresa precisa migrar."
                ),
                base_legal="LC 123/2006 Art. 3º caput + LC 155/2016",
            ))
        elif regime == "SIMPLES" and rbt12 >= (teto * Decimal("0.9")):
            alertas.append(Alerta(
                id="ALERTA_TETO_SIMPLES_PROXIMO",
                titulo="Faturamento próximo do teto do Simples (Rail R7)",
                detalhe=(
                    f"RBT12 R$ {rbt12} está em ≥ 90% do teto R$ {teto}. "
                    "Iniciar análise de migração obrigatória pra Presumido/Real."
                ),
                base_legal="Rail R7 (CLAUDE.md) + LC 123/2006 Art. 3º",
            ))

    if regime == "PRESUMIDO":
        # Limite Lucro Presumido R$ 78.000.000 (Lei 12.814/13)
        try:
            limite = valor_em(LIMITE_LUCRO_PRESUMIDO_VERSIONADO, data_emissao)
        except ValueError:
            return
        leis.append(f"Limite Lucro Presumido vigente em {data_emissao}: R$ {limite}")
        if rbt12 > limite:
            bloqueios.append(Bloqueio(
                origem="LIMITE_VERSIONADO",
                mensagem=(
                    f"RBT12 R$ {rbt12} excede teto do Lucro Presumido R$ {limite} "
                    f"vigente em {data_emissao.isoformat()}. Real obrigatório."
                ),
                base_legal="Lei 9.718/98 Art. 13 + Lei 12.814/13",
            ))


def _engine_recomendado(fornecedora: "EmpresaFornecedora") -> str:
    """Mapeia regime do schema para nome do engine."""
    r = fornecedora.regime
    if r in ("SIMPLES", "PRESUMIDO", "REAL", "MEI", "IMUNE"):
        return r
    return "DESCONHECIDO"


# ─────────────────────────────────────────────────────────────────────────────
# API PÚBLICA
# ─────────────────────────────────────────────────────────────────────────────

def validar_combinacao(
    *,
    fornecedora: "EmpresaFornecedora",
    data_emissao: date,
    fator_r_calculado: Optional[Decimal] = None,
) -> ResultadoOrquestracaoSocietaria:
    """
    Orquestra todos os validadores societários e devolve resultado consolidado.

    Args:
        fornecedora: instância de schemas.motor.EmpresaFornecedora.
        data_emissao: data da operação fiscal (define vigência das regras).
        fator_r_calculado: Fator R já calculado (opcional). Quando None,
            resolve_anexo aplica fallback conservador para CNAEs C_FATOR_R.

    Returns:
        ResultadoOrquestracaoSocietaria frozen com:
          - valido: AND de todos os validadores
          - bloqueios: TODAS as falhas concatenadas (com origem)
          - pendencias: itens indeterminados
          - alertas: avisos não-bloqueantes (Rail R7 etc.)
          - base_legal_aplicavel: união das bases legais
          - engine_recomendado: nome do engine
          - overlay_aplicavel: "COOPERATIVA" ou None
          - anexo_simples_resolvido: I-V ou None

    Não levanta exceção — caller decide tratamento.
    """
    bloqueios: list[Bloqueio] = []
    pendencias: list[str] = []
    alertas: list[Alerta] = []
    leis: list[str] = []

    # 1. Matriz societária 13×4
    _consultar_matriz_societaria(fornecedora, bloqueios, leis)

    # 2. Sub-validador MEI (quando aplicável)
    _consultar_validador_mei(fornecedora, data_emissao, bloqueios, pendencias, leis)

    # 3. Sub-validador COOPERATIVA (quando aplicável)
    overlay_coop_aplicavel = _consultar_validador_cooperativa(
        fornecedora, data_emissao, bloqueios, pendencias, leis,
    )

    # 4. Resolução CNAE × Anexo
    anexo = _consultar_regras_cnae(fornecedora, fator_r_calculado, bloqueios, leis)

    # 5. Limites versionados (Rail R3 + R7)
    _consultar_limites_versionados(fornecedora, data_emissao, bloqueios, alertas, leis)

    return ResultadoOrquestracaoSocietaria(
        valido=(len(bloqueios) == 0),
        bloqueios=tuple(bloqueios),
        pendencias=tuple(pendencias),
        alertas=tuple(alertas),
        base_legal_aplicavel=tuple(leis),
        engine_recomendado=_engine_recomendado(fornecedora),
        overlay_aplicavel="COOPERATIVA" if overlay_coop_aplicavel else None,
        anexo_simples_resolvido=anexo,
    )
