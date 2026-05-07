# -*- coding: utf-8 -*-
"""
mapa_categorias_cbs_ibs.py — Mapa-mestre de classificação de despesas para
fins de crédito CBS/IBS (LC 214/2025 Arts. 47 + 57 + 108).

Catálogo atual em `_mapa_subfase_2_2()` (subfases 2.3-2.5 expandirão).
Contagem oficial: ver assert no teste `test_mapa_subfase_2_2_tem_N_categorias`.

Base legal (validada por Escrivão em 30/04/2026, 07/05/2026 e 07/05/2026 rodada 2):
- LC 214/2025 Art. 47, caput — direito ao crédito (regra geral).
- LC 214/2025 Art. 47, § 9º — crédito de fornecedor Simples = fração do DAS.
- LC 214/2025 Arts. 48-56 — apropriação e utilização do crédito.
- LC 214/2025 Art. 57, caput — bens/serviços de uso ou consumo pessoal
  (vedação ao crédito): joias, obras de arte, bebidas alcoólicas, derivados
  do tabaco, armas, recreação/esporte/estética, imóveis residenciais e
  veículos pra sócios/funcionários.
- LC 214/2025 Art. 57, § 3º (com redação da LC 227/2026) — vale-refeição,
  vale-alimentação, vale-transporte: crédito sem exigência de acordo coletivo.
  Plano de saúde MANTÉM exigência (LC 227/2026 alterou só os 3 vales).
- LC 214/2025 Art. 108 — bens de capital: crédito integral e imediato.
  Art. 109 estabelece rota alternativa (suspensão na entrada via ato CGIBS),
  não condicionante do crédito ordinário do Art. 108.
- CF Art. 149 — contribuições parafiscais (anuidade de conselho profissional
  está fora do escopo CBS/IBS por construção).

Pendências documentadas (subfase 2.3 ou tickets separados):
- PLANO_SAUDE_FUNCIONARIO — Escrivão validou que LC 227/2026 manteve a
  exigência de acordo coletivo. Schema atual não tem flag `existe_acordo_coletivo`
  no input — categoria entra como CASO_DUVIDA quando schema for estendido.
- BRINDES_MARKETING — depende de flag `destinatario_brinde`
  (CLIENTE | EMPREGADO_OU_VINCULADO). Schema atual não tem o flag — fica
  como CASO_DUVIDA quando estendido.

Nota arquitetônica (07/05/2026): COMBUSTIVEL_FROTA_EMPRESARIAL entra na
subfase 2.2 como categoria de DESPESA. NÃO confundir com bloqueio de NCM
2710 em `schemas/motor.py:54` (`NCMS_MONOFASICAS_BLOQUEADAS`) — aquele
protege o motor de calcular ERRADO uma operação de VENDA de combustível
(regime monofásico exige fórmula própria). Despesa de frota nunca passa
por aquele schema. Bloqueio mantido inalterado.

Recomendação Escrivão (operacional, fora desta subfase):
- Planalto offline em 3 rodadas consecutivas. Implementar cache local de
  leis em `data/fontes_legais/planalto/lcp214_v2026-05.txt` com SHA-256 +
  URL canônica. Sem isso o protocolo Escrivão fica frágil em fiscalização
  real (Rail R1 exige fonte primária citada literalmente). Ticket separado.

Política R2 (proibição de extrapolação):
- Categorias com confiança ALTA entram firme. Validação cruzada de fontes
  secundárias (≥3 batendo) é aceita quando Planalto offline E o ponto
  load-bearing converge entre Mayer Brown / Tauil & Chequer / Mattos Filho /
  Conjur / etc.
- Categorias com flag faltando no schema viram CASO_DUVIDA preditivo
  (caller decide ao integrar) ou ficam fora até schema ser estendido.
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


def _mapa_subfase_2_2() -> Dict[str, ClassificacaoCredito]:
    """
    Categorias da subfase 2.2 = subfase 2.1 + 9 novas validadas em 07/05/2026 (rodada 2).
    Contagem exata e invariantes verificados nos testes (Rail R6 — fonte única).

    Novas na subfase 2.2 (9):
    - 4 BEM_DE_CAPITAL (Art. 108) — COMPUTADOR_NOTEBOOK_ATIVO,
      IMPRESSORA_EQUIPAMENTO_ESCRITORIO, MOBILIARIO_ESCRITORIO,
      MAQUINARIO_INDUSTRIAL
    - 3 INSUMO_CREDITAVEL vales (Art. 57 § 3º + LC 227/2026) — VALE_REFEICAO,
      VALE_ALIMENTACAO, VALE_TRANSPORTE
    - 1 NAO_TRIBUTADO — ANUIDADE_CONSELHO_PJ (CF Art. 149 — parafiscal)
    - 1 INSUMO_CREDITAVEL — COMBUSTIVEL_FROTA_EMPRESARIAL (Art. 180 a contrario
      sensu; vedação só pra revenda/distribuição). Categoria de DESPESA, não
      colide com bloqueio de venda em NCMS_MONOFASICAS_BLOQUEADAS.

    Pendências documentadas (FORA desta subfase, não inferir):
    - PLANO_SAUDE_FUNCIONARIO — Escrivão validou MEDIA com flag dependente
      de `existe_acordo_coletivo`. Schema atual não tem o flag.
    - BRINDES_MARKETING — Escrivão validou MEDIA com flag `destinatario_brinde`
      (CLIENTE → INSUMO; EMPREGADO_OU_VINCULADO → USO_PESSOAL). Schema sem flag.
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

    # ── Subfase 2.2: 8 novas (validadas em 07/05/2026 rodada 2) ─────────────

    # Bens de capital — Art. 108 (crédito integral e imediato).
    art_108 = (
        "LC 214/2025, Art. 108 (crédito integral e imediato em aquisição "
        "de bens de capital, na forma dos Arts. 47 a 56)"
    )
    novas_bem_capital: Dict[str, ClassificacaoCredito] = {
        "COMPUTADOR_NOTEBOOK_ATIVO": _categoria(
            "COMPUTADOR_NOTEBOOK_ATIVO", "BEM_DE_CAPITAL", art_108, "ALTA",
            "Equipamento de informática destinado ao ativo imobilizado da PJ.",
        ),
        "IMPRESSORA_EQUIPAMENTO_ESCRITORIO": _categoria(
            "IMPRESSORA_EQUIPAMENTO_ESCRITORIO", "BEM_DE_CAPITAL", art_108, "ALTA",
            "Impressora/scanner/copiadora — ativo imobilizado operacional.",
        ),
        "MOBILIARIO_ESCRITORIO": _categoria(
            "MOBILIARIO_ESCRITORIO", "BEM_DE_CAPITAL", art_108, "ALTA",
            "Mobiliário registrado no ativo imobilizado (equiparado a CIAP no regime atual).",
        ),
        "MAQUINARIO_INDUSTRIAL": _categoria(
            "MAQUINARIO_INDUSTRIAL", "BEM_DE_CAPITAL", art_108, "ALTA",
            "Máquina destinada ao processo produtivo — caso paradigmático de bem de capital.",
        ),
    }

    # Vales (Art. 57 § 3º com redação da LC 227/2026 — dispensa de acordo coletivo).
    art_57_par3_lc227 = (
        "LC 214/2025, Art. 57, § 3º (com redação dada pela LC 227/2026 — "
        "dispensada exigência de previsão em acordo/convenção coletiva "
        "para vale-refeição, vale-alimentação e vale-transporte)"
    )
    novas_vales: Dict[str, ClassificacaoCredito] = {
        "VALE_REFEICAO": _categoria(
            "VALE_REFEICAO", "INSUMO_CREDITAVEL", art_57_par3_lc227, "ALTA",
            "Crédito assegurado independente de acordo/convenção coletiva (LC 227/2026).",
        ),
        "VALE_ALIMENTACAO": _categoria(
            "VALE_ALIMENTACAO", "INSUMO_CREDITAVEL", art_57_par3_lc227, "ALTA",
            "Crédito assegurado independente de acordo/convenção coletiva (LC 227/2026).",
        ),
        "VALE_TRANSPORTE": _categoria(
            "VALE_TRANSPORTE", "INSUMO_CREDITAVEL", art_57_par3_lc227, "ALTA",
            "Crédito assegurado independente de acordo/convenção coletiva (LC 227/2026).",
        ),
    }

    # Anuidade de conselho profissional — contribuição parafiscal, fora do escopo.
    parafiscal_fora_escopo = (
        "CF Art. 149 (contribuições parafiscais de interesse de categoria "
        "profissional, Lei 12.514/2011, STF RE 838.284) + LC 214/2025, Art. 1º "
        "a contrario sensu — anuidade de conselho não é operação com bens ou "
        "serviços; conselho não emite débito CBS/IBS, logo PJ adquirente "
        "não tem crédito a apropriar"
    )
    novas_anuidade: Dict[str, ClassificacaoCredito] = {
        "ANUIDADE_CONSELHO_PJ": _categoria(
            "ANUIDADE_CONSELHO_PJ", "NAO_TRIBUTADO", parafiscal_fora_escopo, "ALTA",
            "Estrutural (não interpretativa): inexistência de débito na origem.",
        ),
    }

    # Combustível pra frota própria empresarial — Art. 180 a contrario sensu.
    # Vedação só pra revenda/distribuição/comercialização; uso operacional
    # próprio mantém direito ao crédito (Conjur, ConfEB, Dickel, Cenários
    # Consultoria — convergência ≥4 fontes secundárias autoritativas).
    art_180_a_contrario_sensu = (
        "LC 214/2025, Art. 180 a contrario sensu (vedação aplicável apenas "
        "a revenda/distribuição/comercialização — combustível para frota "
        "própria operacional mantém direito ao crédito) + LC 214/2025 Art. 47 caput"
    )
    novas_combustivel: Dict[str, ClassificacaoCredito] = {
        "COMBUSTIVEL_FROTA_EMPRESARIAL": _categoria(
            "COMBUSTIVEL_FROTA_EMPRESARIAL", "INSUMO_CREDITAVEL",
            art_180_a_contrario_sensu, "ALTA",
            (
                "Categoria de DESPESA (compra). Não confundir com OperacaoFiscal "
                "de venda — bloqueio NCMS_MONOFASICAS_BLOQUEADAS em schemas/motor.py "
                "vale pra venda, não pra despesa. Quando integrar com motor de "
                "cálculo, regime monofásico exige fórmula própria; usar mapa só "
                "como classificação fiscal, não como base de cálculo direta."
            ),
        ),
    }

    return {
        **base_2_0,
        **novas_insumo,
        **novas_uso_pessoal,
        **novas_nao_tributado,
        **novas_bem_capital,
        **novas_vales,
        **novas_anuidade,
        **novas_combustivel,
    }


# Histórico versionado do mapa-mestre. Migrador acrescenta nova entrada
# quando há alteração legislativa (ex: LC 227/2026 sobre vales).
MAPA_CATEGORIAS_VERSIONADO: list[VersionedRule[Dict[str, ClassificacaoCredito]]] = [
    VersionedRule(
        valor=_mapa_subfase_2_2(),
        vigencia_inicio=date(2026, 1, 1),
        vigencia_fim=date(2026, 12, 31),
        lei="LC 214/2025 Arts. 47 + 57 + 108 + LC 227/2026 (subfase 2.2 — confiança ALTA)",
        url_planalto="https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm",
        observacao="Validado por Escrivão em 30/04/2026 + 07/05/2026 (2 rodadas).",
    ),
    VersionedRule(
        valor=_mapa_subfase_2_2(),
        vigencia_inicio=date(2027, 1, 1),
        vigencia_fim=date(2027, 12, 31),
        lei="LC 214/2025 Arts. 47 + 57 + 108 + LC 227/2026 (vigência plena CBS/IBS)",
        url_planalto="https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp214.htm",
        observacao="Mesmo conjunto da subfase 2.2; subfases 2.3-2.5 expandirão.",
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
