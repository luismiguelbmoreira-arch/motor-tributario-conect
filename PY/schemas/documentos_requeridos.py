"""
documentos_requeridos.py — Contrato de saída do endpoint GET /documentos-requeridos.

Dado (ano_alvo, perfil, regime, mes_corte), a API devolve a lista de cards
que a UI deve renderizar, com período pontual derivado via utils.periodo_base.

Sem lógica de cálculo aqui — só modelo de dados (Pydantic V2).

Amparo legal dos IDs canônicos:
    LC 123/2006 Art. 18 (PGDAS-D / DAS)
    LC 123/2006 Art. 26 (notas fiscais eletrônicas)
    IN RFB 2.003/2021 (SPED ECD)
    IN RFB 1.252/2012 (SPED EFD-Contribuições)
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NivelCard = Literal["base", "b2b", "b2c", "sped"]


class DocumentoRequerido(BaseModel):
    """
    Card de documento que a UI de upload renderiza.

    O `periodo_label` é texto humano ("01/2025 a 12/2025"); `periodo_iso`
    é formato de máquina ("2025-01..2025-12" ou "2025-12") pra parser/filtro
    na UI e cross-check futuro com `dhEmi` do XML.
    """

    id: str = Field(..., description="ID canônico alinhado com _detectar_tipo_documento()")
    label: str = Field(..., description="Título humano do card")
    descricao: str = Field("", description="Texto curto explicando o documento")
    periodo_label: str = Field(..., description="Período em formato humano")
    periodo_iso: str = Field(..., description="Período em formato ISO máquina")
    extensao: str = Field(..., description="Extensão esperada do arquivo (.pdf, .xml, .csv)")
    obrigatorio: bool = Field(..., description="Se False, card é 'recomendado' mas não bloqueia")
    amparo_legal: str = Field(..., description="Citação legal — LC/IN/Art §")
    nivel: NivelCard = Field(..., description="Categoria do card: base | b2b | b2c | sped")
    automacao_disponivel: str | None = Field(
        None,
        description="Se preenchido, a UI mostra legenda 'Automação: <fase>'",
    )


class CardsResponse(BaseModel):
    """Response do endpoint GET /documentos-requeridos."""

    ano_alvo: int
    periodo_base: dict  # serialização de PeriodoBase.to_dict()
    perfil: str
    regime: str
    cards: list[DocumentoRequerido]
