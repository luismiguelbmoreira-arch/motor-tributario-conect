# -*- coding: utf-8 -*-
"""
mapa_categorias_cbs_ibs.py — Mapa-mestre de classificação de despesas para
fins de crédito CBS/IBS (LC 214/2025 Arts. 47 + 57).

Catálogo atual em `_mapa_subfase_2_1()` (subfases 2.2-2.5 expandirão).
Contagem oficial: ver assert no teste `test_mapa_subfase_2_1_tem_N_categorias`.

Base legal (validada por Escrivão em 30/04/2026 e 07/05/2026):
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

Pendências documentadas pra próxima rodada Escrivão (Planalto offline em
07/05/2026 — refinamento, não erro):
- LC 227/2026 dispensou requisito de acordo coletivo pra vale-refeição,
  vale-alimentação e vale-transporte. Texto literal não confirmado.
- Numeração específica de inciso do Art. 57 caput (I joias, II obras de
  arte, V armas, VI recreação) — entraram com granularidade caput
  (idêntica ao piloto ALUGUEL_RESIDENCIAL_FUNCIONARIO da subfase 2.0).
- ANUIDADE_CONSELHO_PJ — split PJ/sócio + se anuidade é "operação tributada"
  exige leitura literal não confirmada. Fica fora.
- Bens de capital (computador, mobiliário, máquina industrial) — Arts. 108-109
  exigem leitura literal pra confirmar "crédito integral imediato sem
  condição de ato CGIBS". Ficam fora desta subfase.
- Arts. 353 e 356-360 — não modelados como base de creditamento; usados
  apenas como cronograma de transição.

Política R2 (proibição de extrapolação):
- Categorias com confiança ALTA do Escrivão entram firme.
- Categorias INCONCLUSIVAS por indisponibilidade de fonte ficam FORA até
  nova rodada — não viram CASO_DUVIDA preditivo.
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


def _mapa_subfase_2_1() -> Dict[str, ClassificacaoCredito]:
    """
    Categorias da subfase 2.1 = piloto da 2.0 + 16 novas validadas em 07/05/2026.
    Contagem exata e invariantes verificados nos testes (Rail R6 — fonte única).

    Critério estrito: SOMENTE categorias com confiança ALTA do Escrivão entram.
    Categorias INCONCLUSIVAS (Planalto offline em 07/05) ficam fora desta
    subfase — refinamento, não erro. Subfase 2.2 acrescenta quando fonte
    voltar:
    - ANUIDADE_CONSELHO_PJ
    - COMPUTADOR_NOTEBOOK_ATIVO, IMPRESSORA_EQUIPAMENTO_ESCRITORIO,
      MOBILIARIO_ESCRITORIO, MAQUINARIO_INDUSTRIAL (bens de capital — Arts. 108-109)
    - VALE_REFEICAO, VALE_TRANSPORTE, VALE_ALIMENTACAO, PLANO_SAUDE_FUNCIONARIO
      (LC 227/2026 dispensou acordo coletivo — texto literal não confirmado)
    - COMBUSTIVEL_FROTA, BRINDES_MARKETING (confiança BAIXA na rodada anterior)
    """
    art_47_caput = "LC 214/2025, Art. 47, caput (direito ao crédito CBS/IBS)"
    art_57_caput = "LC 214/2025, Art. 57, caput (uso ou consumo pessoal — vedação)"
    folha_fora_escopo = (
        "Folha de salários e encargos previdenciários — fora do escopo CBS/IBS "
        "(não é operação tributada por CBS/IBS; vínculo empregatício e INSS/FGTS "
        "estão sob CF Art. 195 + Lei 8.212/91, regime distinto)"
    )

    # ── Subfase 2.0: 9 piloto (ALTA confiança em 30/04/2026) ────────────────
    base_2_0: Dict[str, ClassificacaoCredito] = {
        "ENERGIA_ELETRICA": _categoria(
            "ENERGIA_ELETRICA", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Energia elétrica empresarial — não consta no Art. 57.",
        ),
        "AGUA_SANEAMENTO": _categoria(
            "AGUA_SANEAMENTO", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Água/saneamento empresarial — não consta no Art. 57.",
        ),
        "TELEFONE_INTERNET": _categoria(
            "TELEFONE_INTERNET", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Telefonia/internet empresarial — não consta no Art. 57.",
        ),
        "ALUGUEL_COMERCIAL": _categoria(
            "ALUGUEL_COMERCIAL", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Aluguel de imóvel não-residencial pra atividade da empresa.",
        ),
        "MATERIAL_ESCRITORIO": _categoria(
            "MATERIAL_ESCRITORIO", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
        ),
        "SOFTWARE_LICENCAS": _categoria(
            "SOFTWARE_LICENCAS", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Software/licenças usados na atividade da empresa.",
        ),
        "MANUTENCAO_IMOVEL_COMERCIAL": _categoria(
            "MANUTENCAO_IMOVEL_COMERCIAL", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
        ),
        "ALUGUEL_RESIDENCIAL_FUNCIONARIO": _categoria(
            "ALUGUEL_RESIDENCIAL_FUNCIONARIO", "USO_CONSUMO_PESSOAL", art_57_caput, "ALTA",
            "Imóvel residencial fornecido a pessoa física — Art. 57 caput.",
        ),
        "SALARIOS": _categoria(
            "SALARIOS", "NAO_TRIBUTADO", folha_fora_escopo, "ALTA",
            "Folha não é operação CBS/IBS; não há crédito por construção.",
        ),
    }

    # ── Subfase 2.1: 16 novas (ALTA em 07/05/2026) ──────────────────────────
    # Insumos creditáveis (12) — todos cobertos por Art. 47 caput.
    novas_insumo: Dict[str, ClassificacaoCredito] = {
        "LIMPEZA_TERCEIRIZADA": _categoria(
            "LIMPEZA_TERCEIRIZADA", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Serviço de limpeza contratado — não consta no Art. 57.",
        ),
        "SEGURANCA_VIGILANCIA": _categoria(
            "SEGURANCA_VIGILANCIA", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Segurança/vigilância terceirizadas pra estabelecimento.",
        ),
        "CORREIO_FRETE": _categoria(
            "CORREIO_FRETE", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Logística vinculada à atividade comercial (Correios + transportadoras).",
        ),
        "HOSPEDAGEM_CLOUD": _categoria(
            "HOSPEDAGEM_CLOUD", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "AWS/GCP/Azure/datacenter — análogo a SOFTWARE_LICENCAS.",
        ),
        "ASSESSORIA_JURIDICA": _categoria(
            "ASSESSORIA_JURIDICA", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Honorários advocatícios da PJ — não consta no Art. 57.",
        ),
        "ASSESSORIA_CONTABIL": _categoria(
            "ASSESSORIA_CONTABIL", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Honorários contábeis (escritório).",
        ),
        "AUDITORIA_EXTERNA": _categoria(
            "AUDITORIA_EXTERNA", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Auditoria contábil/fiscal independente.",
        ),
        "CARTORIO_REGISTRO_PUBLICO": _categoria(
            "CARTORIO_REGISTRO_PUBLICO", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Atos de registro vinculados à PJ — não consta no Art. 57.",
        ),
        "ASSINATURA_SOFTWARE_SAAS": _categoria(
            "ASSINATURA_SOFTWARE_SAAS", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Salesforce, Slack, Notion, etc — natureza idêntica a SOFTWARE_LICENCAS.",
        ),
        "MARKETING_DIGITAL": _categoria(
            "MARKETING_DIGITAL", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Google Ads, Meta Ads, mídia paga.",
        ),
        "TELEFONIA_MOVEL_CORPORATIVA": _categoria(
            "TELEFONIA_MOVEL_CORPORATIVA", "INSUMO_CREDITAVEL", art_47_caput, "ALTA",
            "Linha em titularidade da PJ. Linhas pessoais cedidas a sócios "
            "caem em Art. 57 caput — caller deve segregar.",
        ),
    }

    # Uso/consumo pessoal (4) — granularidade caput recomendada por Escrivão.
    # Numeração I/II/V/VI fica pra subfase 2.2 quando Planalto voltar.
    novas_uso_pessoal: Dict[str, ClassificacaoCredito] = {
        "JOIAS_METAIS_PRECIOSOS": _categoria(
            "JOIAS_METAIS_PRECIOSOS", "USO_CONSUMO_PESSOAL", art_57_caput, "ALTA",
            "Joias, pedras e metais preciosos — Art. 57 caput.",
        ),
        "OBRAS_ARTE_ANTIGUIDADES": _categoria(
            "OBRAS_ARTE_ANTIGUIDADES", "USO_CONSUMO_PESSOAL", art_57_caput, "ALTA",
            "Obras de arte e antiguidades de valor histórico — Art. 57 caput.",
        ),
        "ARMAS_MUNICOES": _categoria(
            "ARMAS_MUNICOES", "USO_CONSUMO_PESSOAL", art_57_caput, "ALTA",
            "Armas e munições — Art. 57 caput.",
        ),
        "RECREACAO_ESPORTE_ESTETICA": _categoria(
            "RECREACAO_ESPORTE_ESTETICA", "USO_CONSUMO_PESSOAL", art_57_caput, "ALTA",
            "Bens e serviços recreativos, esportivos e estéticos — Art. 57 caput.",
        ),
    }

    # Não tributado (1) — encargos sobre folha, fora do escopo CBS/IBS.
    novas_nao_tributado: Dict[str, ClassificacaoCredito] = {
        "INSS_PATRONAL_FGTS": _categoria(
            "INSS_PATRONAL_FGTS", "NAO_TRIBUTADO", folha_fora_escopo, "ALTA",
            "Encargos previdenciários sobre folha — não é operação CBS/IBS.",
        ),
    }

    return {**base_2_0, **novas_insumo, **novas_uso_pessoal, **novas_nao_tributado}


# Histórico versionado do mapa-mestre. Migrador acrescenta nova entrada
# quando há alteração legislativa (ex: LC 227/2026 sobre vales).
MAPA_CATEGORIAS_VERSIONADO: list[VersionedRule[Dict[str, ClassificacaoCredito]]] = [
    VersionedRule(
        valor=_mapa_subfase_2_1(),
        vigencia_inicio=date(2026, 1, 1),
        vigencia_fim=date(2026, 12, 31),
        lei="LC 214/2025 Arts. 47 + 57 (subfase 2.1 — confiança ALTA)",
        url_planalto="https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm",
        observacao="Validado por Escrivão em 30/04/2026 + 07/05/2026.",
    ),
    VersionedRule(
        valor=_mapa_subfase_2_1(),
        vigencia_inicio=date(2027, 1, 1),
        vigencia_fim=date(2027, 12, 31),
        lei="LC 214/2025 Arts. 47 + 57 (vigência plena CBS/IBS)",
        url_planalto="https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm",
        observacao="Mesmo conjunto da subfase 2.1; subfases 2.2-2.5 expandirão.",
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
