# -*- coding: utf-8 -*-
"""
profissoes_regulamentadas.py — LC 214/2025 Art. 127.

Redução de 30% sobre as alíquotas de IBS e CBS para 18 profissões
intelectuais regulamentadas, sujeitas a fiscalização por conselho profissional.
Lista TAXATIVA — quem está fora dos incisos I-XVIII NÃO recebe a redução,
mesmo que exerça profissão regulamentada por conselho próprio.

Atenção:
- Plano original do projeto citava "Art. 138" — citação ERRADA. Art. 138
  trata de insumos agropecuários (60% redução). Validação Escrivão em
  30/04/2026 confirmou Art. 127 como base correta.
- Médico humano (CRM) NÃO está nesta lista — médicos humanos seguem regime
  de saúde (Art. 128+). Apenas veterinários e zootecnistas (inciso XIII).
- Requisitos pra PJ receber a redução estão em §§ do Art. 127 (não
  modelados aqui — pendente re-consulta Escrivão pra texto literal).

Fonte primária:
- https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm
- LC 214/2025 publicada em 16/01/2025.
"""

from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Códigos canônicos das 18 profissões do Art. 127, em ordem de inciso.
CodigoProfissao = Literal[
    "ADMINISTRADOR",
    "ADVOGADO",
    "ARQUITETO_URBANISTA",
    "ASSISTENTE_SOCIAL",
    "BIBLIOTECARIO",
    "BIOLOGO",
    "CONTABILISTA",
    "ECONOMISTA",
    "ECONOMISTA_DOMESTICO",
    "EDUCADOR_FISICO",
    "ENGENHEIRO_AGRONOMO",
    "ESTATISTICO",
    "MEDICO_VETERINARIO_ZOOTECNISTA",
    "MUSEOLOGO",
    "QUIMICO",
    "RELACOES_PUBLICAS",
    "TECNICO_INDUSTRIAL",
    "TECNICO_AGRICOLA",
]


class ProfissaoRegulamentada(BaseModel):
    """Profissão do Art. 127 da LC 214/2025."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    codigo: CodigoProfissao
    nome: str = Field(..., description="Nome usado no inciso")
    inciso: str = Field(..., description="Numeral romano do inciso (I a XVIII)")
    lei_conselho: str = Field(..., description="Lei reguladora do conselho profissional")


# Tabela TAXATIVA — Art. 127, incisos I a XVIII.
# Validada por Escrivão em 30/04/2026.
PROFISSOES_ART_127: Dict[str, ProfissaoRegulamentada] = {
    "ADMINISTRADOR": ProfissaoRegulamentada(
        codigo="ADMINISTRADOR",
        nome="Administrador",
        inciso="I",
        lei_conselho="Lei 4.769/1965 (CFA/CRA)",
    ),
    "ADVOGADO": ProfissaoRegulamentada(
        codigo="ADVOGADO",
        nome="Advogado",
        inciso="II",
        lei_conselho="Lei 8.906/1994 (OAB)",
    ),
    "ARQUITETO_URBANISTA": ProfissaoRegulamentada(
        codigo="ARQUITETO_URBANISTA",
        nome="Arquiteto e urbanista",
        inciso="III",
        lei_conselho="Lei 12.378/2010 (CAU)",
    ),
    "ASSISTENTE_SOCIAL": ProfissaoRegulamentada(
        codigo="ASSISTENTE_SOCIAL",
        nome="Assistente social",
        inciso="IV",
        lei_conselho="Lei 8.662/1993 (CFESS/CRESS)",
    ),
    "BIBLIOTECARIO": ProfissaoRegulamentada(
        codigo="BIBLIOTECARIO",
        nome="Bibliotecário",
        inciso="V",
        lei_conselho="Lei 4.084/1962 (CFB/CRB)",
    ),
    "BIOLOGO": ProfissaoRegulamentada(
        codigo="BIOLOGO",
        nome="Biólogo",
        inciso="VI",
        lei_conselho="Lei 6.684/1979 (CFBio/CRBio)",
    ),
    "CONTABILISTA": ProfissaoRegulamentada(
        codigo="CONTABILISTA",
        nome="Contabilista",
        inciso="VII",
        lei_conselho="DL 9.295/1946 (CFC/CRC)",
    ),
    "ECONOMISTA": ProfissaoRegulamentada(
        codigo="ECONOMISTA",
        nome="Economista",
        inciso="VIII",
        lei_conselho="Lei 1.411/1951 (COFECON/CORECON)",
    ),
    "ECONOMISTA_DOMESTICO": ProfissaoRegulamentada(
        codigo="ECONOMISTA_DOMESTICO",
        nome="Economista doméstico",
        inciso="IX",
        lei_conselho="Lei 7.387/1985 (CFED/CRED)",
    ),
    "EDUCADOR_FISICO": ProfissaoRegulamentada(
        codigo="EDUCADOR_FISICO",
        nome="Profissional de educação física",
        inciso="X",
        lei_conselho="Lei 9.696/1998 (CONFEF/CREF)",
    ),
    "ENGENHEIRO_AGRONOMO": ProfissaoRegulamentada(
        codigo="ENGENHEIRO_AGRONOMO",
        nome="Engenheiro e agrônomo",
        inciso="XI",
        lei_conselho="Lei 5.194/1966 (CONFEA/CREA)",
    ),
    "ESTATISTICO": ProfissaoRegulamentada(
        codigo="ESTATISTICO",
        nome="Estatístico",
        inciso="XII",
        lei_conselho="Lei 4.739/1965 (CONFE/CONRE)",
    ),
    "MEDICO_VETERINARIO_ZOOTECNISTA": ProfissaoRegulamentada(
        codigo="MEDICO_VETERINARIO_ZOOTECNISTA",
        nome="Médico veterinário e zootecnista",
        inciso="XIII",
        lei_conselho="Lei 5.517/1968 + Lei 5.550/1968 (CFMV/CRMV)",
    ),
    "MUSEOLOGO": ProfissaoRegulamentada(
        codigo="MUSEOLOGO",
        nome="Museólogo",
        inciso="XIV",
        lei_conselho="Lei 7.287/1984 (COFEM/COREM)",
    ),
    "QUIMICO": ProfissaoRegulamentada(
        codigo="QUIMICO",
        nome="Químico",
        inciso="XV",
        lei_conselho="Lei 2.800/1956 (CFQ/CRQ)",
    ),
    "RELACOES_PUBLICAS": ProfissaoRegulamentada(
        codigo="RELACOES_PUBLICAS",
        nome="Profissional de relações públicas",
        inciso="XVI",
        lei_conselho="Lei 5.377/1967 (CONFERP/CONRERP)",
    ),
    "TECNICO_INDUSTRIAL": ProfissaoRegulamentada(
        codigo="TECNICO_INDUSTRIAL",
        nome="Técnico industrial",
        inciso="XVII",
        lei_conselho="Lei 13.639/2018 (CFT/CRT)",
    ),
    "TECNICO_AGRICOLA": ProfissaoRegulamentada(
        codigo="TECNICO_AGRICOLA",
        nome="Técnico agrícola",
        inciso="XVIII",
        lei_conselho="Lei 13.639/2018 (CFTA/CRTA)",
    ),
}


def aplica_reducao_30(profissao: Optional[str]) -> bool:
    """True se a profissão consta dos 18 incisos do Art. 127."""
    return profissao is not None and profissao in PROFISSOES_ART_127


def amparo_legal_profissao(codigo: str) -> str:
    """Citação completa: Art. 127 inciso N + Lei do conselho profissional."""
    if codigo not in PROFISSOES_ART_127:
        raise ValueError(
            f"Profissão '{codigo}' não consta no Art. 127 da LC 214/2025. "
            f"Lista taxativa: {sorted(PROFISSOES_ART_127.keys())}."
        )
    p = PROFISSOES_ART_127[codigo]
    return f"LC 214/2025, Art. 127, inciso {p.inciso}; {p.lei_conselho}"
