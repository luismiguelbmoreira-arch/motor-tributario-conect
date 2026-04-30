# -*- coding: utf-8 -*-
"""
imposto_seletivo.py — Imposto Seletivo (LC 214/2025 Arts. 409-434).

Base legal:
- CF/88 Art. 153 VIII (competência) + EC 132/2023 Art. 153 § 6º
- LC 214/2025 Art. 409 caput + § 1º (incidência sobre 8 categorias taxativas)
- LC 214/2025 Art. 410 (incidência única, sem creditamento)
- LC 214/2025 Art. 412 (alíquotas — DELEGADAS à lei ordinária / PLP 42/2026)
- LC 214/2025 Art. 544 (vigência: 1º/01/2027)

Validação Escrivão (30/04/2026) com 5+ fontes secundárias autoritativas:
Fazenda RJ, Câmara, Jusbrasil, IBET, Mayer Brown, Modelo Inicial.

ESCOPO RESTRITO (Rail R2):
- Identifica EXPOSIÇÃO ao IS por categoria semântica + prefixo NCM 4 dígitos.
- NÃO calcula valor — alíquotas estão delegadas a lei ordinária (PLP 42/2026
  em tramitação 04/2026); Rail R2 proíbe extrapolação.
- Antes de 1º/01/2027 NÃO se aplica (Rail R8 — consistência temporal).
- Combustíveis (NCM 2710) seguem regime monofásico de IBS/CBS (Art. 172),
  tributo DIFERENTE do Seletivo — não modelados aqui.
- NCMs com critério ambiental (veículos 8703), embarcações (8901-8906),
  aeronaves (8801-8802), bens minerais e açúcar/sal puro: FORA enquanto
  PLP 42/2026 não publicar critérios firmes (Rail R2).

Quando PLP 42/2026 for sancionada, Migrador atualiza:
- Mapa de NCMs (incluindo capítulos novos)
- Tabela de alíquotas
- Categorias com critério ambiental / cota
"""

from datetime import date
from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# 8 categorias taxativas do Art. 409 § 1º.
# (Bens minerais / aeronaves / embarcações / veículos / apostas: previstas na lei
# mas sem mapeamento NCM firme até PLP 42/2026 — listadas no Literal pra não
# inflar o type quando a regulamentação chegar.)
CategoriaSeletivo = Literal[
    "PRODUTOS_FUMIGENOS",
    "BEBIDAS_ALCOOLICAS",
    "BEBIDAS_ACUCARADAS",
    "VEICULOS",
    "EMBARCACOES",
    "AERONAVES",
    "BENS_MINERAIS",
    "APOSTAS_PROGNOSTICOS",
]

# Vigência (Art. 544 LC 214/2025).
DATA_INICIO_VIGENCIA: date = date(2027, 1, 1)


class ExposicaoSeletivo(BaseModel):
    """Sinaliza que uma operação está exposta ao Imposto Seletivo."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    ncm: str = Field(..., min_length=8, max_length=8)
    categoria: CategoriaSeletivo
    vigente_na_data: bool = Field(
        ...,
        description="True se data_emissao >= 2027-01-01 (Art. 544)",
    )
    aliquota_disponivel: bool = Field(
        default=False,
        description="True quando PLP 42/2026 publicar a alíquota da categoria",
    )
    amparo_legal: str


# Mapa de prefixo NCM 4-dígitos → categoria. Entrada cobre apenas itens
# CONFIRMADOS pelo Escrivão em fonte secundária autoritativa.
# Migrador estende quando PLP 42/2026 firmar critérios para veículos/etc.
NCMS_SUJEITOS: Dict[str, CategoriaSeletivo] = {
    # Produtos fumígenos — Art. 409 § 1º
    "2402": "PRODUTOS_FUMIGENOS",  # cigarros, cigarrilhas, charutos
    "2403": "PRODUTOS_FUMIGENOS",  # outros tabacos
    # Bebidas alcoólicas — Art. 409 § 1º
    "2203": "BEBIDAS_ALCOOLICAS",  # cerveja
    "2204": "BEBIDAS_ALCOOLICAS",  # vinho de uva
    "2205": "BEBIDAS_ALCOOLICAS",  # vermute
    "2206": "BEBIDAS_ALCOOLICAS",  # outras bebidas fermentadas
    "2207": "BEBIDAS_ALCOOLICAS",  # álcool etílico ≥ 80%
    "2208": "BEBIDAS_ALCOOLICAS",  # destilados (cachaça, gin, vodka)
    # Bebidas açucaradas — Art. 409 § 1º
    # Critério "açucarada" delegado à lei ordinária; capítulo 2202 cobre
    # refrigerantes, sucos não fermentados, energéticos.
    "2202": "BEBIDAS_ACUCARADAS",
}


def is_aplicavel_em(data_operacao: date) -> bool:
    """True se a operação ocorre em data de vigência do IS (≥ 2027-01-01)."""
    return data_operacao >= DATA_INICIO_VIGENCIA


def categoria_seletivo(ncm: str) -> Optional[CategoriaSeletivo]:
    """
    Retorna a categoria do IS aplicável ao NCM (por prefixo de 4 dígitos),
    ou None se não consta no mapa.
    """
    if not isinstance(ncm, str) or len(ncm) < 4:
        return None
    return NCMS_SUJEITOS.get(ncm[:4])


def eh_sujeito_ao_seletivo(ncm: str) -> bool:
    """Atalho booleano — True se o NCM está em alguma categoria do IS."""
    return categoria_seletivo(ncm) is not None


def detectar_exposicao(ncm: str, data_operacao: date) -> Optional[ExposicaoSeletivo]:
    """
    Detecta se a operação está exposta ao Imposto Seletivo.

    Retorna None se o NCM não consta no mapa. Caso contrário retorna
    ExposicaoSeletivo com flag de vigência temporal.

    Não calcula valor — alíquotas estão delegadas a lei ordinária
    (PLP 42/2026). O caller decide o que fazer com a exposição.
    """
    categoria = categoria_seletivo(ncm)
    if categoria is None:
        return None
    return ExposicaoSeletivo(
        ncm=ncm,
        categoria=categoria,
        vigente_na_data=is_aplicavel_em(data_operacao),
        aliquota_disponivel=False,  # PLP 42/2026 ainda não sancionada (30/04/2026)
        amparo_legal=(
            "LC 214/2025, Art. 409 § 1º (incidência) + Art. 410 (não-cumulatividade) + "
            "Art. 412 (alíquotas — lei ordinária) + Art. 544 (vigência 2027)"
        ),
    )
