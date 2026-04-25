# -*- coding: utf-8 -*-
"""
validador_mei.py — Sub-validador específico do MEI

WS6 Etapa 3 do plano de refinamento. Valida os requisitos extras do MEI
(LC 123/2006 Art. 18-A + LC 188/2021) que não cabem na matriz societária
pura da Etapa 2:

  1. tipo_societario deve ser EI (MEI é status do Simples para EI)
  2. faturamento_12m dentro do teto vigente na data
       - MEI tradicional: R$ 81.000 (LC 123/2006 Art. 18-A § 1º)
       - MEI Caminhoneiro: R$ 251.600 (LC 188/2021)
  3. CNAE no Anexo XI Resolução CGSN 140/2018 (lista parcial confirmada;
     CNAEs fora da lista retornam Indeterminado, não False)
  4. CNAE não vedado pelo Art. 17 LC 123 (delegado a WS12)
  5. MEI Caminhoneiro requer CNAE de transporte rodoviário de carga

DECISÕES ARQUITETURAIS:
  - Função pura: recebe payload, retorna ResultadoValidacaoMEI imutável
  - Não chama Banco de Dados, não levanta exceção em entrada inválida
    (caller decide se 422 ou warning)
  - Cita LC 123/2006 Art. 18-A + LC 188/2021 + Res. CGSN 140/2018 Anexo XI
  - Consome WS10 (TETO_MEI_VERSIONADO) — Rail R3 cobertura temporal

REFERÊNCIA LEGAL:
  - LC 123/2006 Art. 18-A (caput, §§ 1º a 7º)
  - LC 188/2021 (MEI Caminhoneiro)
  - Resolução CGSN 140/2018 Anexo XI
  - Lei 14.195/2021 Art. 11 (Empresário Individual)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.cnae_mei_anexo_xi import (
    cnae_eh_mei_caminhoneiro,
    cnae_no_anexo_xi_mei,
)
from core.versioned_rule import (
    TETO_MEI_CAMINHONEIRO_VERSIONADO,
    TETO_MEI_VERSIONADO,
    valor_em,
)


class ResultadoValidacaoMEI(BaseModel):
    """Resultado imutável da validação MEI."""

    model_config = ConfigDict(frozen=True)

    valido: Optional[bool] = Field(
        description=(
            "True quando todos os requisitos MEI batem, False quando algum "
            "requisito é violado, None quando há requisito indeterminado "
            "(ex: CNAE fora da lista parcial Anexo XI — caller deve consultar)."
        )
    )
    modalidade: Literal["MEI", "MEI_CAMINHONEIRO", "NAO_APLICAVEL"] = Field(
        description=(
            "Modalidade detectada. NAO_APLICAVEL quando enquadramento_simples "
            "não é MEI nem MEI_CAMINHONEIRO."
        )
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
# API pública
# ─────────────────────────────────────────────────────────────────────────────

def validar_mei(
    *,
    tipo_societario: Optional[str],
    enquadramento_simples: Optional[str],
    cnae_principal: str,
    faturamento_12m: Decimal,
    data_emissao: date,
) -> ResultadoValidacaoMEI:
    """
    Valida os requisitos específicos do MEI.

    Args:
        tipo_societario: forma jurídica (deve ser "EI" pra MEI)
        enquadramento_simples: status no Simples ("MEI" / "MEI_CAMINHONEIRO" / outro / None)
        cnae_principal: CNAE 7 dígitos sem pontuação
        faturamento_12m: RBT12 em Decimal
        data_emissao: data da operação (define teto vigente)

    Returns:
        ResultadoValidacaoMEI imutável.

    Não levanta exceção — caller decide tratamento (422 vs warning).
    """
    # 0. Não aplicável quando enquadramento não é MEI
    if enquadramento_simples not in ("MEI", "MEI_CAMINHONEIRO"):
        return ResultadoValidacaoMEI(
            valido=None,
            modalidade="NAO_APLICAVEL",
            base_legal_aplicavel=("LC 123/2006 Art. 18-A — validador só se aplica a enquadramento MEI",),
        )

    modalidade: Literal["MEI", "MEI_CAMINHONEIRO"] = (
        "MEI_CAMINHONEIRO" if enquadramento_simples == "MEI_CAMINHONEIRO" else "MEI"
    )
    motivos: list[str] = []
    pendencias: list[str] = []
    leis: list[str] = ["LC 123/2006 Art. 18-A"]

    # 1. tipo_societario deve ser EI (estrutura sem sócios — Lei 14.195/2021 Art. 11)
    if tipo_societario != "EI":
        motivos.append(
            f"MEI requer tipo_societario='EI' (Empresário Individual, sem sócios). "
            f"Recebido: {tipo_societario!r}. Base: LC 123/2006 Art. 18-A caput "
            f"+ Lei 14.195/2021 Art. 11."
        )

    # 2. Faturamento dentro do teto vigente na data
    if modalidade == "MEI_CAMINHONEIRO":
        leis.append("LC 188/2021")
        try:
            teto = valor_em(TETO_MEI_CAMINHONEIRO_VERSIONADO, data_emissao)
        except ValueError:
            pendencias.append(
                f"Teto MEI Caminhoneiro indisponível para data {data_emissao.isoformat()} "
                f"(LC 188/2021 vigência a partir de 2022)."
            )
            teto = None
    else:
        try:
            teto = valor_em(TETO_MEI_VERSIONADO, data_emissao)
        except ValueError:
            pendencias.append(
                f"Teto MEI indisponível para data {data_emissao.isoformat()} "
                f"(LC 123/2006 Art. 18-A § 1º redação LC 155/2016 vigência a partir de 2018)."
            )
            teto = None

    if teto is not None and faturamento_12m > teto:
        motivos.append(
            f"Faturamento R$ {faturamento_12m} excede teto MEI vigente "
            f"R$ {teto} em {data_emissao.isoformat()}. "
            f"Base: {'LC 188/2021' if modalidade == 'MEI_CAMINHONEIRO' else 'LC 123/2006 Art. 18-A § 1º'}."
        )

    # 3. CNAE no Anexo XI CGSN 140/2018
    leis.append("Resolução CGSN 140/2018 Anexo XI")
    cnae_check = cnae_no_anexo_xi_mei(cnae_principal)
    if cnae_check is None:
        pendencias.append(
            f"CNAE {cnae_principal} fora da lista parcial confirmada do "
            f"Anexo XI CGSN 140/2018. Contador deve consultar a Resolução "
            f"CGSN 140/2018 Anexo XI manualmente para confirmar."
        )
    elif cnae_check is False:  # reservado para futuro com lista completa
        motivos.append(
            f"CNAE {cnae_principal} não consta no Anexo XI CGSN 140/2018 (lista MEI)."
        )

    # 4. MEI Caminhoneiro requer CNAE específico de transporte de carga
    if modalidade == "MEI_CAMINHONEIRO" and not cnae_eh_mei_caminhoneiro(cnae_principal):
        motivos.append(
            f"MEI_CAMINHONEIRO exige CNAE de transporte rodoviário de carga "
            f"(LC 188/2021). Recebido: {cnae_principal}. CNAEs aceitos: "
            f"4930201/4930202/4930203/4930204."
        )

    # ── Decisão final ──────────────────────────────────────────────────────
    if motivos:
        valido: Optional[bool] = False
    elif pendencias:
        valido = None  # Indeterminado — caller pede confirmação manual
    else:
        valido = True

    return ResultadoValidacaoMEI(
        valido=valido,
        modalidade=modalidade,
        motivos_bloqueio=tuple(motivos),
        pendencias=tuple(pendencias),
        base_legal_aplicavel=tuple(leis),
    )
