# -*- coding: utf-8 -*-
"""
regras_cnae.py — Schema Pydantic V2 + resolve_anexo() para mapeamento CNAE -> Anexo
Projeto: Motor Tributario Conect 2026-2033

CONTEXTO:
  WS12 (ERR-005 reaberto) — schema novo aprovado por Luiz Moreira em 25/04/2026.
  Substitui o `Dict[str, str]` antigo do `tabelas_simples.py` que nao comportava
  Fator R (LC 123/2006 Art. 18 §5º-D).

DECISAO ARQUITETURAL:
  - 5 categorias semanticas (A_FIXO, B_ANEXO_III, C_FATOR_R, D_ESPECIAL, E_VEDADO)
  - Override por CNAE 7-digitos (cnae_excecoes.CNAE_EXCECOES) tem precedencia
    sobre regra por divisao (cnae_excecoes.DIVISAO_PARA_CATEGORIA)
  - resolve_anexo(cnae, fator_r) retorna o anexo correto considerando Fator R

REFERENCIA:
  docs/especificacoes/WS12_schema_cnae_luiz_moreira.md
  LC 123/2006 Art. 18 §5º-A a §5º-J + Art. 17 (vedacoes)
  Resolucao CGSN 140/2018 Anexo VI
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from core.cnae_excecoes import CNAE_EXCECOES, DIVISAO_PARA_CATEGORIA

# Limiar do Fator R (LC 123/2006 Art. 18 §5º-J)
FATOR_R_LIMIAR = Decimal("0.28")


class RegraCNAE(BaseModel):
    """Regra fiscal de classificacao CNAE -> Anexo do Simples Nacional."""

    cnae: str = Field(pattern=r"^\d{7}$", description="CNAE 7 digitos sem pontuacao")
    categoria: Literal["A_FIXO", "B_ANEXO_III", "C_FATOR_R", "D_ESPECIAL", "E_VEDADO"]
    anexo_padrao: Optional[Literal["I", "II", "III", "IV", "V"]]
    depende_fator_r: bool
    anexo_fator_r_alto: Optional[Literal["III"]] = None
    anexo_fator_r_baixo: Optional[Literal["V"]] = None
    base_legal: str
    resolucao_cgsn: Optional[str] = None
    observacao: Optional[str] = None

    @model_validator(mode="after")
    def _coerencia_fator_r(self):
        """
        Garante que C_FATOR_R sempre tem anexo_fator_r_alto/baixo,
        e que outras categorias nao tem (Rail R5 — separacao rigida).
        """
        if self.depende_fator_r:
            assert self.categoria == "C_FATOR_R", (
                f"depende_fator_r=True so vale para C_FATOR_R, recebido {self.categoria}"
            )
            assert self.anexo_fator_r_alto == "III", "C_FATOR_R requer anexo_fator_r_alto=III"
            assert self.anexo_fator_r_baixo == "V", "C_FATOR_R requer anexo_fator_r_baixo=V"
            assert self.anexo_padrao is None, (
                "C_FATOR_R nao tem anexo_padrao (resolucao depende de Fator R)"
            )
        else:
            assert self.anexo_fator_r_alto is None
            assert self.anexo_fator_r_baixo is None
            if self.categoria != "E_VEDADO":
                assert self.anexo_padrao is not None, (
                    f"Categoria {self.categoria} requer anexo_padrao"
                )
            else:
                assert self.anexo_padrao is None, "E_VEDADO nao tem anexo_padrao"
        return self


def _construir_regra(cnae: str, dados: dict) -> RegraCNAE:
    """Constroi RegraCNAE a partir do dict de excecao/divisao."""
    base = {
        "cnae": cnae,
        "categoria": dados["categoria"],
        "anexo_padrao": dados.get("anexo_padrao"),
        "depende_fator_r": dados.get("depende_fator_r", False),
        "base_legal": dados["base_legal"],
        "observacao": dados.get("observacao"),
    }
    if base["depende_fator_r"]:
        base["anexo_fator_r_alto"] = "III"
        base["anexo_fator_r_baixo"] = "V"
    return RegraCNAE(**base)


def obter_regra(cnae_7_digitos: str) -> Optional[RegraCNAE]:
    """
    Retorna a RegraCNAE para o CNAE informado.

    Prioridade (ordem):
      1. Override cirurgico (CNAE_EXCECOES) — ~14 casos com lei especifica
      2. Regra por divisao (DIVISAO_PARA_CATEGORIA) — primeiros 2 digitos
      3. None se nao mapeado (caller decide fallback)

    NUNCA retorna anexo errado em silencio: se nao encontrar, devolve None
    para o caller aplicar fallback explicito (Rail R2 — sem extrapolacao).
    """
    if not cnae_7_digitos or len(cnae_7_digitos) != 7 or not cnae_7_digitos.isdigit():
        return None

    # 1. Override cirurgico (precedencia maxima)
    if cnae_7_digitos in CNAE_EXCECOES:
        return _construir_regra(cnae_7_digitos, CNAE_EXCECOES[cnae_7_digitos])

    # 2. Regra por divisao (2 primeiros digitos)
    divisao = cnae_7_digitos[:2]
    if divisao in DIVISAO_PARA_CATEGORIA:
        return _construir_regra(cnae_7_digitos, DIVISAO_PARA_CATEGORIA[divisao])

    # 3. Nao mapeado — caller decide (geralmente fallback Anexo III conservador)
    return None


def resolve_anexo(
    cnae_7_digitos: str,
    fator_r: Optional[Decimal] = None,
) -> tuple[str, str]:
    """
    Resolve o Anexo do Simples Nacional para um CNAE.

    Args:
        cnae_7_digitos: CNAE 7 digitos sem pontuacao
        fator_r: Fator R (folha 12m / RBT12) — Decimal, opcional

    Returns:
        (anexo, fonte_categoria)
        - anexo: "I" | "II" | "III" | "IV" | "V"
        - fonte_categoria: "A_FIXO" | "B_ANEXO_III" | "C_FATOR_R_ALTO" |
          "C_FATOR_R_BAIXO" | "C_FATOR_R_CONSERVADOR" | "D_ESPECIAL" |
          "E_VEDADO_FALLBACK_III" | "FALLBACK_NAO_MAPEADO"

    Comportamento conservador (Rail R2 + Constraint 6 do Luiz):
        - C_FATOR_R sem fator_r informado -> retorna V (mais oneroso = mais seguro)
        - CNAE nao mapeado -> retorna III (servicos gerais, conservador)
        - E_VEDADO -> levanta nao, retorna fallback III com fonte explicita
          (motor decide se rejeita; manter API simples)

    Raises:
        ValueError: se cnae for E_VEDADO e fator_r for informado
                    (sinaliza erro de uso pra caller).
    """
    regra = obter_regra(cnae_7_digitos)

    if regra is None:
        # CNAE fora de qualquer mapeamento — fallback conservador (servicos III)
        return "III", "FALLBACK_NAO_MAPEADO"

    if regra.categoria == "E_VEDADO":
        # Empresa nao pode estar no Simples — caller deveria saber.
        # Retorna III com fonte explicita pra trilha auditar a anomalia.
        return "III", "E_VEDADO_FALLBACK_III"

    if regra.categoria == "A_FIXO":
        return regra.anexo_padrao, "A_FIXO"

    if regra.categoria == "B_ANEXO_III":
        return regra.anexo_padrao, "B_ANEXO_III"

    if regra.categoria == "D_ESPECIAL":
        return regra.anexo_padrao, "D_ESPECIAL"

    if regra.categoria == "C_FATOR_R":
        if fator_r is None:
            # Conservador: sem informar Fator R, usa V (mais oneroso)
            return "V", "C_FATOR_R_CONSERVADOR"
        if fator_r >= FATOR_R_LIMIAR:
            return "III", "C_FATOR_R_ALTO"
        return "V", "C_FATOR_R_BAIXO"

    # Inalcancavel pelo schema — defesa em profundidade
    return "III", "FALLBACK_NAO_MAPEADO"


def is_vedado(cnae_7_digitos: str) -> bool:
    """Helper: retorna True se o CNAE for vedado ao Simples (Art. 17 LC 123)."""
    regra = obter_regra(cnae_7_digitos)
    return regra is not None and regra.categoria == "E_VEDADO"
