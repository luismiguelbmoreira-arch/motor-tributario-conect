# -*- coding: utf-8 -*-
"""
mapa_categorias_cbs_ibs.py — Mapa-mestre de classificação de despesas para
fins de crédito CBS/IBS (LC 214/2025 Arts. 47 + 57).

SUBFASE 2.0 (arquitetura + categorias-piloto). Subfases 2.1-2.5 ampliam
o catálogo até cobrir as ~100 categorias mais comuns do plano de contas.

Base legal (validada por Escrivão em 30/04/2026):
- LC 214/2025 Art. 47, caput — direito ao crédito (regra geral).
- LC 214/2025 Art. 47, § 9º — crédito de fornecedor Simples = fração do DAS.
- LC 214/2025 Arts. 48-56 — apropriação e utilização do crédito.
- LC 214/2025 Art. 57, caput — bens/serviços de uso ou consumo pessoal
  (vedação ao crédito): joias, obras de arte, bebidas alcoólicas, derivados
  do tabaco, armas, recreação/esporte/estética, imóveis residenciais e
  veículos pra sócios/funcionários.
- LC 214/2025 Art. 57, § 3º, IV — exceções: uniformes, EPIs, alimentação,
  saúde, creche, planos, vales (originalmente exigia previsão em
  acordo/convenção coletiva).
- LC 214/2025 Arts. 108-109 — bens de capital (crédito integral e imediato).

Pendências documentadas pra próxima rodada Escrivão:
- LC 227/2026 dispensou requisito de acordo coletivo pra vale-refeição,
  vale-alimentação e vale-transporte. Texto literal da LC 227/2026 sobre
  isso não confirmado nesta rodada — categorias relacionadas ficam fora
  do mapa até validação.
- Arts. 353 e 356-360 (Planalto offline na rodada Escrivão) — não
  modelados como base de creditamento; usados apenas como cronograma de
  transição (compete a outros módulos).

Política R2 (proibição de extrapolação):
- Categorias com confiança ALTA do Escrivão entram com classificação firme.
- Categorias com confiança MÉDIA/BAIXA entram com tipo CASO_DUVIDA ou
  ficam fora do mapa até nova validação.
"""

from datetime import date
from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.versioned_rule import VersionedRule, lookup

# Tipos de classificação fiscal de uma categoria de despesa.
TipoClassificacao = Literal[
    # Gera crédito pleno (Art. 47 caput).
    "INSUMO_CREDITAVEL",
    # Bens de capital — crédito integral e imediato (Arts. 108-109).
    "BEM_DE_CAPITAL",
    # Vedado por uso/consumo pessoal (Art. 57 caput).
    "USO_CONSUMO_PESSOAL",
    # Não-creditável por natureza (folha, encargos, despesa sem documento fiscal).
    "NAO_TRIBUTADO",
    # Caso ambíguo — bloqueia cálculo automático até revisão manual (Rail R2).
    "CASO_DUVIDA",
]


class ClassificacaoCredito(BaseModel):
    """
    Classificação fiscal de uma categoria de despesa para fins de crédito CBS/IBS.

    `gera_credito` é derivado de `tipo` mas exposto explicitamente pra evitar
    que o caller dependa do detalhe semântico do enum.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    categoria: str = Field(..., min_length=2, description="Nome canônico da categoria")
    tipo: TipoClassificacao
    gera_credito: bool = Field(..., description="True = direito ao crédito CBS/IBS pleno")
    amparo_legal: str
    confianca: Literal["ALTA", "MEDIA", "BAIXA"] = Field(
        ...,
        description="Confiança da classificação por Escrivão. Apenas ALTA entra firme.",
    )
    observacao: Optional[str] = None


def _categoria(
    nome: str,
    tipo: TipoClassificacao,
    amparo_legal: str,
    confianca: Literal["ALTA", "MEDIA", "BAIXA"] = "ALTA",
    observacao: Optional[str] = None,
) -> ClassificacaoCredito:
    """Builder pra reduzir verbosidade da tabela."""
    gera = tipo in ("INSUMO_CREDITAVEL", "BEM_DE_CAPITAL")
    return ClassificacaoCredito(
        categoria=nome,
        tipo=tipo,
        gera_credito=gera,
        amparo_legal=amparo_legal,
        confianca=confianca,
        observacao=observacao,
    )


def _mapa_subfase_2_0() -> Dict[str, ClassificacaoCredito]:
    """
    9 categorias-piloto da subfase 2.0.

    Critério: SOMENTE categorias com confiança ALTA do Escrivão (30/04/2026).
    Categorias com confiança MÉDIA (vales, plano de saúde) aguardam validação
    da LC 227/2026; com confiança BAIXA (combustível pra frota, brindes)
    ficam fora até nova rodada Escrivão.
    """
    art_47_caput = "LC 214/2025, Art. 47, caput (direito ao crédito CBS/IBS)"
    art_57_caput = "LC 214/2025, Art. 57, caput (uso ou consumo pessoal — vedação)"

    return {
        "ENERGIA_ELETRICA": _categoria(
            "ENERGIA_ELETRICA",
            "INSUMO_CREDITAVEL",
            art_47_caput,
            "ALTA",
            "Energia elétrica empresarial — não consta no Art. 57.",
        ),
        "AGUA_SANEAMENTO": _categoria(
            "AGUA_SANEAMENTO",
            "INSUMO_CREDITAVEL",
            art_47_caput,
            "ALTA",
            "Água/saneamento empresarial — não consta no Art. 57.",
        ),
        "TELEFONE_INTERNET": _categoria(
            "TELEFONE_INTERNET",
            "INSUMO_CREDITAVEL",
            art_47_caput,
            "ALTA",
            "Telefonia/internet empresarial — não consta no Art. 57.",
        ),
        "ALUGUEL_COMERCIAL": _categoria(
            "ALUGUEL_COMERCIAL",
            "INSUMO_CREDITAVEL",
            art_47_caput,
            "ALTA",
            "Aluguel de imóvel não-residencial pra atividade da empresa.",
        ),
        "MATERIAL_ESCRITORIO": _categoria(
            "MATERIAL_ESCRITORIO",
            "INSUMO_CREDITAVEL",
            art_47_caput,
            "ALTA",
        ),
        "SOFTWARE_LICENCAS": _categoria(
            "SOFTWARE_LICENCAS",
            "INSUMO_CREDITAVEL",
            art_47_caput,
            "ALTA",
            "Software/licenças usados na atividade da empresa.",
        ),
        "MANUTENCAO_IMOVEL_COMERCIAL": _categoria(
            "MANUTENCAO_IMOVEL_COMERCIAL",
            "INSUMO_CREDITAVEL",
            art_47_caput,
            "ALTA",
        ),
        "ALUGUEL_RESIDENCIAL_FUNCIONARIO": _categoria(
            "ALUGUEL_RESIDENCIAL_FUNCIONARIO",
            "USO_CONSUMO_PESSOAL",
            art_57_caput,
            "ALTA",
            "Imóvel residencial fornecido a pessoa física — Art. 57 caput.",
        ),
        "SALARIOS": _categoria(
            "SALARIOS",
            "NAO_TRIBUTADO",
            "Folha de salários — fora do escopo CBS/IBS (não é operação tributada)",
            "ALTA",
            "Folha não é operação CBS/IBS; não há crédito por construção.",
        ),
    }


# Histórico versionado do mapa-mestre. Migrador acrescenta nova entrada
# quando há alteração legislativa (ex: LC 227/2026 sobre vales).
MAPA_CATEGORIAS_VERSIONADO: list[VersionedRule[Dict[str, ClassificacaoCredito]]] = [
    VersionedRule(
        valor=_mapa_subfase_2_0(),
        vigencia_inicio=date(2026, 1, 1),
        vigencia_fim=date(2026, 12, 31),
        lei="LC 214/2025 Arts. 47 + 57 + 108-109 (subfase 2.0 — 9 categorias)",
        url_planalto="https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm",
        observacao="Validado por Escrivão em 30/04/2026 — apenas confiança ALTA.",
    ),
    VersionedRule(
        valor=_mapa_subfase_2_0(),
        vigencia_inicio=date(2027, 1, 1),
        vigencia_fim=date(2027, 12, 31),
        lei="LC 214/2025 Arts. 47 + 57 + 108-109 (vigência plena CBS/IBS)",
        url_planalto="https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm",
        observacao="Mesmo conjunto da subfase 2.0; subfases 2.1-2.5 expandirão.",
    ),
]


# ── API pública ──────────────────────────────────────────────────────────────

def classificar(categoria: str, data_operacao: date) -> Optional[ClassificacaoCredito]:
    """
    Retorna a classificação fiscal da categoria na data, ou None se não consta no mapa.

    Categorias fora do mapa NÃO são "não-creditáveis por padrão" — são
    UNKNOWN. Caller deve marcar como CASO_DUVIDA pra revisão manual
    (Rail R2 — sem fonte primária, sem decisão automática).

    Raises:
        ValueError: data fora da janela coberta (2026-2027 hoje).
    """
    if not isinstance(categoria, str):
        return None
    nome = categoria.strip().upper()
    if not nome:
        return None
    mapa = lookup(MAPA_CATEGORIAS_VERSIONADO, data_operacao).valor
    return mapa.get(nome)


def gera_credito(categoria: str, data_operacao: date) -> bool:
    """
    Atalho boolean — True se a categoria gera crédito CBS/IBS na data.

    Categorias UNKNOWN (fora do mapa) retornam False — conservadorismo
    fiscal: na dúvida, não há crédito.
    """
    classificacao = classificar(categoria, data_operacao)
    return classificacao is not None and classificacao.gera_credito


def listar_categorias_creditaveis(data_operacao: date) -> list[str]:
    """Lista (ordenada) das categorias que geram crédito na data."""
    mapa = lookup(MAPA_CATEGORIAS_VERSIONADO, data_operacao).valor
    return sorted(nome for nome, c in mapa.items() if c.gera_credito)
