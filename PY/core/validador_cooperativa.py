# -*- coding: utf-8 -*-
"""
validador_cooperativa.py — Sub-validador específico de cooperativas

WS6 Etapa 5a do plano de refinamento. Função pura que valida combinação
de tipo_societario × ramo cooperativo × regime × Art. 271. Irmão de
core.validador_mei (mesma forma).

ESCOPO 5a: CONSUMO / TRABALHO / PRODUCAO / AGROPECUARIA / TRANSPORTE.
ESCOPO 5b (não implementado): CREDITO / SAUDE.

DECISÕES ARQUITETURAIS:
  - Função pura: recebe payload, retorna ResultadoValidacaoCooperativa imutável
  - Não chama Banco de Dados, não levanta exceção em entrada inválida
    (caller decide se 422 ou warning)
  - Cita LC 214/2025 + LC 123/2006 + Lei 5.764/71 com base ESCRIVÃO 2026-05-08

REFERÊNCIA LEGAL (validada por Escrivão 2026-05-08 contra cache local):
  - LC 214/2025 Art. 271 caput + § 3º (opção alíquota zero IBS/CBS — § 3º
    exige opção declarada no ano-calendário anterior, Rail R8)
  - LC 123/2006 Art. 3º § 4º VI (vedação Simples salvo cooperativa de consumo)
  - LC 123/2006 Art. 3º § 1º (exceção que permite cooperativa de consumo
    no Simples)
  - Lei 5.764/71 Art. 4º — sociedades de pessoas constituídas para prestar
    serviços aos associados (características I-XI; "não objetiva lucro" é
    dedução doutrinária, não literal)
  - Lei 5.764/71 Art. 5º caput — "qualquer gênero de serviço, operação ou
    atividade" (objeto da cooperativa)
  - Lei 5.764/71 Art. 10 caput + § 1º — classificação por objeto/natureza,
    modalidades caracterizadas pelo órgão controlador (OCB/CGSN); ramos
    NÃO são enumeração legal taxativa
  - Lei 5.764/71 Art. 79 — definição canônica de ato cooperativo
  - Lei 5.764/71 Art. 87 (caput, texto único) — segregação contábil:
    "contabilizados em separado, de molde a permitir cálculo para
    incidência de tributos" — NÃO citar como "§ único" (parágrafo
    único INEXISTENTE; bloqueio MAX_07 prévio)
  - Lei 5.764/71 Art. 111 — regra de incidência sobre ato não-cooperativo
    (resultados das operações dos Arts. 85, 86 e 88 são renda tributável);
    NÃO é cláusula sancionadora

ANTI-ALUCINAÇÃO MAX_07:
  Citações cobertas em testes regressivos:
    - Art. 87 § único NÃO aparece em base_legal_aplicavel (parágrafo inexistente)
    - Art. 10 caput + § 1º (classificação correta — não Art. 6º + Art. 7º)
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# WS6 etapa 5b — fonte única de ramos cooperativos (PMD #1: unificar
# Literal × frozenset). Aliases preservados pra compat com chamadas legadas.
from core.cooperativa_ramos import RAMOS_5A, RAMOS_5B

RamosCooperativos5a = RAMOS_5A
RamosCooperativos5b = RAMOS_5B


# ─────────────────────────────────────────────────────────────────────────────
# RESULTADO IMUTÁVEL
# ─────────────────────────────────────────────────────────────────────────────

class ResultadoValidacaoCooperativa(BaseModel):
    """Resultado imutável da validação societária de cooperativa."""

    model_config = ConfigDict(frozen=True)

    aplicavel: bool = Field(
        description=(
            "True quando tipo_societario='COOPERATIVA' (validação se aplica). "
            "False quando tipo é outro — caller deve ignorar este resultado."
        )
    )
    valido: Optional[bool] = Field(
        description=(
            "True quando todos os requisitos batem. False quando algum é "
            "violado. None quando há requisito indeterminado pendente. "
            "None também quando aplicavel=False (não se aplica)."
        )
    )
    ramo: Optional[str] = Field(
        default=None,
        description="Ramo cooperativo declarado (espelho de subtipo_cooperativa).",
    )
    motivos_bloqueio: tuple[str, ...] = Field(
        default=(),
        description="Razões pelas quais valido=False (vazio quando válido).",
    )
    pendencias: tuple[str, ...] = Field(
        default=(),
        description="Itens indeterminados que exigem confirmação manual.",
    )
    base_legal_aplicavel: tuple[str, ...] = Field(
        default=(),
        description="Leis/artigos que sustentam a decisão.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# API PÚBLICA
# ─────────────────────────────────────────────────────────────────────────────

def validar_cooperativa(
    *,
    tipo_societario: Optional[str],
    subtipo_cooperativa: Optional[str],
    regime: str,
    cnae_principal: str,
    optante_art271: bool,
    data_emissao: date,
    data_opcao_art271: Optional[date],
) -> ResultadoValidacaoCooperativa:
    """
    Valida requisitos societários de cooperativa.

    Args:
        tipo_societario: forma jurídica (deve ser "COOPERATIVA" pra aplicação)
        subtipo_cooperativa: ramo cooperativo (CONSUMO/TRABALHO/PRODUCAO/
            AGROPECUARIA/TRANSPORTE em 5a; CREDITO/SAUDE em 5b)
        regime: regime tributário (SIMPLES/PRESUMIDO/REAL/MEI/IMUNE)
        cnae_principal: CNAE 7 dígitos (informativo nesta etapa — validação
            CNAE × ramo é responsabilidade de WS12)
        optante_art271: opção pela alíquota zero IBS/CBS (LC 214 Art. 271)
        data_emissao: data da operação fiscal
        data_opcao_art271: quando declarou a opção (Rail R8 — § 3º exige
            ano anterior ao da operação)

    Returns:
        ResultadoValidacaoCooperativa imutável.

    Não levanta exceção — caller decide tratamento (422 vs warning vs alerta).
    """
    # 0. NÃO APLICÁVEL — tipo_societario != COOPERATIVA
    if tipo_societario != "COOPERATIVA":
        return ResultadoValidacaoCooperativa(
            aplicavel=False,
            valido=None,
            base_legal_aplicavel=(
                "Lei 5.764/71 Art. 4º — validador só se aplica a sociedades cooperativas",
            ),
        )

    motivos: list[str] = []
    pendencias: list[str] = []
    leis: list[str] = [
        "Lei 5.764/71 Art. 4º (sociedades de pessoas constituídas para prestar serviços aos associados)",
        "Lei 5.764/71 Art. 10 caput + § 1º (classificação por objeto/natureza; modalidades via OCB/CGSN)",
    ]

    # 1a. CREDITO — Real obrigatório + alertas regime serviços financeiros
    if subtipo_cooperativa == "CREDITO":
        leis.append(
            "Lei 9.718/98 Art. 14 II (cooperativas de crédito obrigadas ao Lucro Real)"
        )
        leis.append(
            "LC 214/2025 Art. 181 caput (regime específico de serviços financeiros)"
        )
        leis.append(
            "LC 214/2025 Art. 183 § 1º III "
            "(cooperativas de crédito como entidade supervisionada do SFN)"
        )
        leis.append(
            "LC 214/2025 Art. 192 § 8º "
            "(operações coop-associado fora da base — independe do Art. 271)"
        )
        leis.append(
            "LC 214/2025 Art. 188 (cooperativa financeira optante reverte deduções "
            "proporcionais)"
        )
        leis.append(
            "LC 214/2025 Art. 197 I, redação dada pela LC 227/2026 "
            "(associado tomador NÃO apropria créditos)"
        )
        if regime != "REAL":
            motivos.append(
                f"Cooperativa de CRÉDITO obrigada ao Lucro Real — recebido "
                f"regime='{regime}'. Lei 9.718/98 Art. 14 II lista cooperativas "
                f"de crédito entre as instituições obrigadas ao Real."
            )

    # 1b. SAUDE — regime específico Cap III Tít V (Arts. 234-238)
    elif subtipo_cooperativa == "SAUDE":
        leis.append(
            "LC 214/2025 Art. 234, caput + inciso III "
            "(cooperativas operadoras de planos de saúde no regime específico)"
        )
        leis.append(
            "LC 214/2025 Art. 235 (base de cálculo: prêmios/contraprestações "
            "menos indenizações, cancelamentos, intermediação e taxa de adm.)"
        )
        leis.append(
            "LC 214/2025 Art. 237 "
            "(alíquota IBS/CBS = alíquota de referência reduzida em 60%)"
        )
        leis.append(
            "LC 214/2025 Art. 238 (vedado crédito ao adquirente de planos de saúde)"
        )
        if optante_art271:
            # Schema também bloqueia, mas validador é defensivo (caller pode
            # construir entrada bypassando o schema em testes/admin tools).
            motivos.append(
                "Cooperativa de SAÚDE não pode optar pelo Art. 271. Cap III "
                "Tít V (Arts. 234-238) define regime próprio com alíquota de "
                "referência reduzida em 60% (Art. 237) — Art. 271 é restrito "
                "ao Tít VII (Cooperativas) e não cobre planos de saúde."
            )

    # 2. SUBTIPO ausente — não validamos nada além disso
    elif subtipo_cooperativa is None:
        pendencias.append(
            "Ramo cooperativo não declarado (campo subtipo_cooperativa). "
            "Lei 5.764/71 Art. 10 caput exige classificação por objeto."
        )

    # 3. RAMO 5a — validações específicas
    elif subtipo_cooperativa in RamosCooperativos5a:
        # 3.1 Vedação Simples salvo CONSUMO
        if regime == "SIMPLES" and subtipo_cooperativa != "CONSUMO":
            motivos.append(
                f"Cooperativa de {subtipo_cooperativa} não pode optar pelo "
                f"Simples Nacional. Vedação: LC 123/2006 Art. 3º § 4º VI. "
                f"Exceção (cooperativa de CONSUMO) está em LC 123/2006 Art. 3º § 1º."
            )
            leis.append("LC 123/2006 Art. 3º § 4º VI (vedação)")
            leis.append("LC 123/2006 Art. 3º § 1º (exceção CONSUMO)")
        elif regime == "SIMPLES" and subtipo_cooperativa == "CONSUMO":
            leis.append("LC 123/2006 Art. 3º § 1º (exceção que permite Simples)")

        # 3.2 Opt-in Art. 271 — janela § 3º (Rail R8)
        if optante_art271:
            leis.append("LC 214/2025 Art. 271 caput + § 3º (opção alíquota zero)")
            if data_opcao_art271 is None:
                # Schema deveria barrar, mas validador é defensivo
                motivos.append(
                    "Optante do Art. 271 sem data_opcao_art271 declarada. "
                    "LC 214/2025 Art. 271 § 3º exige opção em ano-calendário "
                    "anterior ao da operação."
                )
            elif data_opcao_art271.year >= data_emissao.year:
                motivos.append(
                    f"Opção pelo Art. 271 declarada em "
                    f"{data_opcao_art271.isoformat()} produz efeitos só a partir "
                    f"de {data_opcao_art271.year + 1}. Operação em "
                    f"{data_emissao.isoformat()} fora da janela. "
                    f"LC 214/2025 Art. 271 § 3º."
                )

    else:
        # Defensivo — Literal já cobre, mas se enum crescer sem atualizar:
        motivos.append(
            f"Ramo cooperativo desconhecido: {subtipo_cooperativa!r}. "
            "Atualize core.validador_cooperativa.RamosCooperativos5a/5b."
        )

    # ── Decisão final ──────────────────────────────────────────────────────
    if motivos:
        valido: Optional[bool] = False
    elif pendencias:
        valido = None
    else:
        valido = True

    return ResultadoValidacaoCooperativa(
        aplicavel=True,
        valido=valido,
        ramo=subtipo_cooperativa,
        motivos_bloqueio=tuple(motivos),
        pendencias=tuple(pendencias),
        base_legal_aplicavel=tuple(leis),
    )
