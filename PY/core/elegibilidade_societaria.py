# -*- coding: utf-8 -*-
"""
elegibilidade_societaria.py — Matriz Tipo Societário × Regime Tributário
Projeto: Motor Tributário Conect 2026-2033

WS6 Etapa 2 do plano de refinamento. Função pura, sem efeitos colaterais.

═══════════════════════════════════════════════════════════════════════════════
ESCOPO
═══════════════════════════════════════════════════════════════════════════════
Responde APENAS à pergunta "tipo societário X pode optar por regime Y?".
Não trata limites de faturamento (WS10 — VersionedRule), não trata vedações
por CNAE (WS12 — categoria E_VEDADO), não trata requisitos específicos de
MEI/Imune (WS6 etapas 3 e 4).

═══════════════════════════════════════════════════════════════════════════════
PRECEDÊNCIA NA COMPOSIÇÃO (WS6 Etapa 6 — orquestrador)
═══════════════════════════════════════════════════════════════════════════════
A elegibilidade final de uma empresa é o AND lógico de:

    elegibilidade_societaria  ∧  vedacao_cnae  ∧  limite_faturamento  ∧  ...

Regras que o orquestrador DEVE respeitar quando compor:

  1. CONCATENAR mensagens de TODAS as falhas — nunca retornar só a primeira.
     O contador precisa ver todos os bloqueios para tomar decisão informada.

  2. Se WS6 diz `valido=True` mas WS12 (CNAE) diz `vedado`, prevalece a
     vedação por CNAE — com menção EXPLÍCITA na mensagem ("permitido pela
     forma jurídica, mas vedado pelo CNAE X.YYYY-Z").

  3. Se WS6 retorna `condicoes`, o orquestrador deve VERIFICAR cada condição
     contra dados reais (CNAE, faturamento, atividade). Condições não
     verificadas = falha fechada.

  4. Obrigatoriedade de regime (ex: Real obrigatório > R$ 78M ou financeiras
     do Lei 9.718/98 Art. 14) NÃO é decidida nesta matriz — é composta no
     orquestrador cruzando com WS10 (faturamento) + WS12 (CNAE/atividade).

═══════════════════════════════════════════════════════════════════════════════
REFERÊNCIA LEGAL
═══════════════════════════════════════════════════════════════════════════════
  - LC 123/2006 Art. 3º §4º (vedações ao Simples por forma jurídica)
  - Lei 9.718/98 Art. 13 (Lucro Presumido — limite R$ 78M, Lei 12.814/2013)
  - Lei 9.718/98 Art. 14 (Lucro Real obrigatório — financeiras, factoring)
  - Lei 9.430/96 Art. 1º (Lucro Real geral)
  - RIR/2018 Arts. 184, 257, 587 (entidades sem fins lucrativos no Real/Presumido)
  - RIR/2018 Art. 184 (entidades isentas — tributação das receitas não compreendidas na isenção)
  - RIR/2018 Art. 587 (forma de apuração do Presumido)
  - Lei 9.532/97 Art. 12 §2º (limites da isenção das entidades sem fins lucrativos)
  - CC Art. 53 (associações), Art. 62-69 (fundações), Art. 991-996 (SCP)
  - CF Art. 150 VI b (templos), VI c (associações sem fins lucrativos), §4º
  - CTN Art. 14 (requisitos da imunidade)
  - Lei 5.764/71 (cooperativas), Art. 87 (segregação atos cooperativos)
  - Lei 9.532/97 Art. 12 §2º (imunidade — desdobramentos)
  - Lei 10.825/2003 (organizações religiosas — adicionadas ao CC Art. 44)
  - LC 167/2019 (Empresa Simples de Crédito)
  - LC 188/2021 (MEI Caminhoneiro — sublimite específico)
  - Lei 14.195/2021 (extinção da EIRELI — convertida em SLU)
  - Lei 6.404/76 Art. 278 (consórcios)
  - Lei 8.023/90 (Produtor Rural PF — opção pelo livro caixa)
  - STF RE 325.822 (imunidade religiosa — extensão das atividades essenciais)
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

# ─────────────────────────────────────────────────────────────────────────────
# Tipos
# ─────────────────────────────────────────────────────────────────────────────
# IMPORTANTE: a inclusão de um tipo aqui IMPLICA atualização espelhada em
# `schemas/motor.py::EmpresaFornecedora.tipo_societario` (Literal). Manter
# os dois Literals sincronizados é regra de manutenção do WS6.
TipoSocietario = Literal[
    "EI", "SLU", "LTDA", "SS", "SA", "COOPERATIVA",
    "ASSOCIACAO", "FUNDACAO", "ORGANIZACAO_RELIGIOSA",
    # Adicionados WS6 Etapa 2 — defesa contra KeyError em CNPJs reais
    "SCP",                  # Sociedade em Conta de Participação (CC Art. 991-996)
    "ESC",                  # Empresa Simples de Crédito (LC 167/2019)
    "CONSORCIO",            # Consórcio (Lei 6.404/76 Art. 278)
    "PRODUTOR_RURAL_PF",    # Produtor rural pessoa física (Lei 8.023/90)
]

RegimeBase = Literal["SIMPLES", "PRESUMIDO", "REAL", "IMUNE"]

_TODOS_TIPOS: tuple[TipoSocietario, ...] = (
    "EI", "SLU", "LTDA", "SS", "SA", "COOPERATIVA",
    "ASSOCIACAO", "FUNDACAO", "ORGANIZACAO_RELIGIOSA",
    "SCP", "ESC", "CONSORCIO", "PRODUTOR_RURAL_PF",
)
_TODOS_REGIMES: tuple[RegimeBase, ...] = ("SIMPLES", "PRESUMIDO", "REAL", "IMUNE")


# ─────────────────────────────────────────────────────────────────────────────
# Exceção customizada
# ─────────────────────────────────────────────────────────────────────────────
class CombinacaoSocietariaNaoMapeadaError(ValueError):
    """
    Levantada quando `elegibilidade(tipo, regime)` recebe combinação fora da
    matriz. Herda de ValueError para não quebrar try/except legado.
    """


# ─────────────────────────────────────────────────────────────────────────────
# Schema Pydantic — frozen (imutável)
# ─────────────────────────────────────────────────────────────────────────────
class Elegibilidade(BaseModel):
    """
    Resultado da consulta (tipo_societario, regime) -> elegibilidade fiscal.

    Notas de campo:
      - `obrigatorio`: SEMPRE False nesta matriz pura. A obrigatoriedade de
        regime depende de inputs externos (faturamento, atividade) e é
        composta no orquestrador WS6 Etapa 6 (cruzando com WS10/WS12).
        Mantido no schema para documentar a intenção explícita: matriz
        societária NÃO decide obrigatoriedade.
    """

    model_config = ConfigDict(frozen=True)

    valido: bool = Field(description="Combinação é permitida em lei?")
    base_legal: str = Field(description="Lei/artigo que sustenta a decisão")
    motivo: Optional[str] = Field(
        default=None,
        description="Quando valido=False, descreve por que a combinação é vedada",
    )
    condicoes: tuple[str, ...] = Field(
        default=(),
        description="Quando valido=True mas requer condições adicionais (verificadas no orquestrador)",
    )
    obrigatorio: bool = Field(
        default=False,
        description=(
            "SEMPRE False nesta matriz. Obrigatoriedade depende de "
            "faturamento/atividade — composta pelo orquestrador WS6.6 "
            "cruzando com WS10 (faturamento) e WS12 (CNAE)."
        ),
    )
    observacao: Optional[str] = Field(
        default=None,
        description="Nota informativa (não bloqueante) para o auditor/contador",
    )


# ─────────────────────────────────────────────────────────────────────────────
# MATRIZ — uma célula por combinação (tipo, regime). Cada célula traz base
# legal explícita (MAX_FISCAL_02). Construída como dict mutável e exposta
# como MappingProxyType (read-only) ao final do módulo.
# ─────────────────────────────────────────────────────────────────────────────
_MATRIZ_BUILDER: dict[tuple[TipoSocietario, RegimeBase], Elegibilidade] = {

    # ═════════════════════════════════════════════════════════════════════════
    # EI — Empresário Individual (CC Art. 966)
    # ═════════════════════════════════════════════════════════════════════════
    ("EI", "SIMPLES"): Elegibilidade(
        valido=True,
        base_legal="LC 123/2006 Art. 3º caput (ME/EPP) + Art. 18-A (MEI)",
        condicoes=(
            "Faturamento dentro do limite ME/EPP (R$ 4,8M) ou MEI (R$ 81k)",
            "Atividade não vedada (LC 123/2006 Art. 17)",
        ),
    ),
    ("EI", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.718/98 Art. 13 + Lei 12.814/2013",
        condicoes=("Faturamento ≤ R$ 78M (Lei 9.718/98 Art. 13)",),
    ),
    ("EI", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º + RIR/2018 Art. 257",
    ),
    ("EI", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CF Art. 150 VI c + CC Art. 966",
        motivo=(
            "EI tem finalidade lucrativa por natureza (CC Art. 966 — exerce "
            "profissionalmente atividade econômica organizada). Imunidade "
            "alcança apenas associações/fundações sem fins lucrativos."
        ),
    ),

    # ═════════════════════════════════════════════════════════════════════════
    # SLU — Sociedade Limitada Unipessoal (Lei 13.874/19)
    # ═════════════════════════════════════════════════════════════════════════
    ("SLU", "SIMPLES"): Elegibilidade(
        valido=True,
        base_legal="LC 123/2006 Art. 3º caput (incluiu SLU desde Lei 13.874/2019)",
        condicoes=(
            "Faturamento dentro do limite ME/EPP",
            "Atender demais incisos do Art. 3º §4º (sem participação em outra PJ, sócio PF, etc.)",
            "Atividade não vedada (LC 123/2006 Art. 17)",
        ),
    ),
    ("SLU", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.718/98 Art. 13 + Lei 12.814/2013",
        condicoes=("Faturamento ≤ R$ 78M",),
    ),
    ("SLU", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º + Lei 9.718/98 Art. 14",
        observacao=(
            "Real é obrigatório se faturamento > R$ 78M ou atividade do "
            "Art. 14 (financeira, factoring, etc.) — verificar no orquestrador WS10+WS12"
        ),
    ),
    ("SLU", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CF Art. 150 VI c",
        motivo="SLU tem finalidade lucrativa por natureza societária",
    ),

    # ═════════════════════════════════════════════════════════════════════════
    # LTDA — Sociedade Empresária Limitada (CC Art. 1.052)
    # ═════════════════════════════════════════════════════════════════════════
    ("LTDA", "SIMPLES"): Elegibilidade(
        valido=True,
        base_legal="LC 123/2006 Art. 3º caput",
        condicoes=(
            "Faturamento dentro do limite ME/EPP",
            "Atender Art. 3º §4º incs. I a XV "
            "(sócios PF, sem participação em outra PJ, sem débito INSS, "
            "não constituída há menos de 5 anos por dissolução de PJ, etc.)",
            "Atividade não vedada (LC 123/2006 Art. 17)",
        ),
    ),
    ("LTDA", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.718/98 Art. 13 + Lei 12.814/2013",
        condicoes=("Faturamento ≤ R$ 78M",),
    ),
    ("LTDA", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º + Lei 9.718/98 Art. 14",
        observacao=(
            "Real obrigatório quando faturamento > R$ 78M (Lei 9.718/98 Art. 14 III) "
            "ou atividade financeira/factoring (Art. 14 II). Composição feita "
            "pelo orquestrador WS6.6 com WS10/WS12."
        ),
    ),
    ("LTDA", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CF Art. 150 VI c",
        motivo="LTDA empresarial tem finalidade lucrativa (CC Art. 982)",
    ),

    # ═════════════════════════════════════════════════════════════════════════
    # SS — Sociedade Simples (CC Art. 997)
    # ═════════════════════════════════════════════════════════════════════════
    ("SS", "SIMPLES"): Elegibilidade(
        valido=True,
        base_legal="LC 123/2006 Art. 3º caput + Art. 17 + Art. 18 §5º-B/C/D",
        condicoes=(
            "Faturamento dentro do limite ME/EPP",
            "Profissão regulamentada listada no Art. 18 §5º-B/C/D (quando SS pura)",
            "Atender Art. 3º §4º incs. I a XV",
        ),
        observacao=(
            "SS empresária (registrada na Junta Comercial) segue regra da LTDA; "
            "SS pura (registrada no RCPJ) exige profissão listada no §5º-B/C/D — "
            "validar via WS12 (CNAE)"
        ),
    ),
    ("SS", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.718/98 Art. 13",
        condicoes=("Faturamento ≤ R$ 78M",),
    ),
    ("SS", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º",
    ),
    ("SS", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CF Art. 150 VI c + CC Art. 997",
        motivo="SS tem finalidade lucrativa (CC Art. 981)",
    ),

    # ═════════════════════════════════════════════════════════════════════════
    # SA — Sociedade Anônima (Lei 6.404/76)
    # ═════════════════════════════════════════════════════════════════════════
    # Inciso X confirmado pelo Escrivão em 25/04/2026 contra texto consolidado
    # da LC 123/2006 (alterações até abril/2026 — LC 155/2016, LC 167/2019,
    # LC 188/2021 não tocaram este dispositivo; redação original mantida).
    ("SA", "SIMPLES"): Elegibilidade(
        valido=False,
        base_legal="LC 123/2006 Art. 3º §4º X",
        motivo=(
            "Sociedade por ações é vedada ao Simples Nacional "
            "(LC 123/2006 Art. 3º §4º, inciso X — 'constituída sob a forma de "
            "sociedade por ações')."
        ),
    ),
    ("SA", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.718/98 Art. 13",
        condicoes=("Faturamento ≤ R$ 78M",),
        observacao=(
            "SA de capital aberto, instituições financeiras, seguradoras e "
            "demais do Lei 9.718/98 Art. 14 são obrigadas ao Real — "
            "validar atividade via WS12"
        ),
    ),
    ("SA", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º + Lei 9.718/98 Art. 14",
        observacao=(
            "Obrigatório para SA de capital aberto, financeiras, seguradoras, "
            "factoring e securitização (Lei 9.718/98 Art. 14 incs. I-VII). "
            "Composição feita pelo orquestrador WS6.6."
        ),
    ),
    ("SA", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CF Art. 150 VI c + Lei 6.404/76",
        motivo="SA tem finalidade lucrativa por essência societária",
    ),

    # ═════════════════════════════════════════════════════════════════════════
    # COOPERATIVA — Lei 5.764/71
    # ═════════════════════════════════════════════════════════════════════════
    ("COOPERATIVA", "SIMPLES"): Elegibilidade(
        valido=True,
        base_legal="LC 123/2006 Art. 3º §4º VI (vedação geral) + Art. 3º §1º (exceção)",
        condicoes=(
            "Apenas cooperativa de consumo (LC 123/2006 Art. 3º §1º) — "
            "demais cooperativas são vedadas pelo Art. 3º §4º VI",
            "Faturamento dentro do limite ME/EPP",
            "Validar via WS12 (CNAE de cooperativa de consumo)",
        ),
        observacao=(
            "Cooperativa de TRABALHO é explicitamente vedada (Art. 3º §4º VI). "
            "Cooperativa de CONSUMO é a exceção que permite Simples. "
            "Caller deve verificar a `condicoes` antes de exibir como elegível."
        ),
    ),
    ("COOPERATIVA", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.718/98 Art. 13 + Lei 5.764/71 Art. 87",
        condicoes=(
            "Faturamento ≤ R$ 78M",
            "Atos cooperativos segregados de atos não-cooperativos (Lei 5.764/71 Art. 87)",
        ),
    ),
    ("COOPERATIVA", "REAL"): Elegibilidade(
        valido=True,
        base_legal=(
            "Lei 5.764/71 Arts. 87 e 111 + RIR/2018 Arts. 193-195 + Lei 9.430/96 Art. 1º"
        ),
        observacao=(
            "Cooperativa de CRÉDITO é obrigada ao Real (Lei 9.718/98 Art. 14 II — "
            "instituição financeira). Composição feita pelo orquestrador."
        ),
    ),
    ("COOPERATIVA", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CF Art. 150 VI + Lei 5.764/71 Art. 79",
        motivo=(
            "Cooperativa não é entidade imune. Possui regime tributário próprio: "
            "ato cooperativo não é tributado (Lei 5.764/71 Art. 79), "
            "ato não-cooperativo é tributado normalmente."
        ),
    ),

    # ═════════════════════════════════════════════════════════════════════════
    # ASSOCIACAO — CC Art. 53
    # ═════════════════════════════════════════════════════════════════════════
    ("ASSOCIACAO", "SIMPLES"): Elegibilidade(
        valido=False,
        base_legal="LC 123/2006 Art. 3º caput + CC Art. 53",
        motivo=(
            "Associação não é ME/EPP — Simples é regime para empresas com "
            "fins lucrativos. Associação tem finalidade não-econômica (CC Art. 53)."
        ),
    ),
    ("ASSOCIACAO", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal=(
            "CC Art. 53 + RIR/2018 Arts. 184 e 587 + "
            "Lei 9.532/97 Art. 12 §2º + Lei 9.718/98 Art. 13"
        ),
        condicoes=(
            "Apenas para receitas de atividade econômica não amparada pela "
            "imunidade/isenção (CTN Art. 14 §2º + Lei 9.532/97 Art. 12 §2º)",
            "Faturamento ≤ R$ 78M (Lei 9.718/98 Art. 13)",
            "Manutenção da isenção sobre a parcela amparada (CTN Art. 14)",
        ),
        observacao=(
            "Caminho fiscal padrão é IMUNE/ISENTA para a parcela amparada. "
            "Para receitas não amparadas, a opção pelo Presumido decorre da "
            "combinação RIR/2018 Art. 184 (tributação das receitas fora da "
            "isenção) + Art. 587 (forma de apuração) + Lei 9.718/98 Art. 13 "
            "(opção). Não há SC COSIT vinculante específica — contador deve "
            "avaliar caso a caso (ERR-017.b: evitar citação de precedente "
            "que não trate diretamente do regime/entidade)."
        ),
    ),
    ("ASSOCIACAO", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º + RIR/2018 Art. 184",
        condicoes=(
            "Tributação incide sobre atividades econômicas não amparadas pela "
            "imunidade (CTN Art. 14 §2º)",
            "OU descumprimento dos requisitos da imunidade (CTN Art. 14)",
        ),
        observacao=(
            "Caminho padrão é IMUNE. Real aplica-se sobre receitas fora do "
            "escopo da imunidade ou em caso de descumprimento dos requisitos."
        ),
    ),
    ("ASSOCIACAO", "IMUNE"): Elegibilidade(
        valido=True,
        base_legal="CF Art. 150 VI c + CTN Art. 14 + Lei 9.532/97 Art. 12",
        condicoes=(
            "Sem distribuição de patrimônio ou rendas (CTN Art. 14 I)",
            "Não remeter recursos ao exterior (CTN Art. 14 II)",
            "Manter escrituração regular das receitas/despesas (CTN Art. 14 III)",
            "Aplicar integralmente os recursos na manutenção dos objetivos institucionais",
        ),
    ),

    # ═════════════════════════════════════════════════════════════════════════
    # FUNDACAO — CC Art. 62-69
    # ═════════════════════════════════════════════════════════════════════════
    ("FUNDACAO", "SIMPLES"): Elegibilidade(
        valido=False,
        base_legal="LC 123/2006 Art. 3º caput + CC Art. 62",
        motivo=(
            "Fundação não é ME/EPP. Constituída por dotação patrimonial para "
            "fim não-lucrativo (CC Art. 62) — incompatível com Simples."
        ),
    ),
    ("FUNDACAO", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal=(
            "CC Arts. 62-69 + RIR/2018 Arts. 184 e 587 + "
            "Lei 9.532/97 Art. 12 §2º + Lei 9.718/98 Art. 13"
        ),
        condicoes=(
            "Apenas para receitas de atividade econômica não amparada pela "
            "imunidade (CTN Art. 14 §2º + Lei 9.532/97 Art. 12 §2º)",
            "Faturamento ≤ R$ 78M (Lei 9.718/98 Art. 13)",
            "Manutenção da imunidade sobre a parcela amparada (CTN Art. 14)",
        ),
        observacao=(
            "Caminho padrão é IMUNE. Para receitas não amparadas, a opção pelo "
            "Presumido decorre de RIR/2018 Arts. 184/587 + Lei 9.718/98 Art. 13. "
            "Não há ato COSIT vinculante específico para fundações — aplicação "
            "por composição normativa (ERR-017.b: contador deve avaliar caso "
            "a caso, sem alegar precedente RFB direto que não exista)."
        ),
    ),
    ("FUNDACAO", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º + RIR/2018 Art. 184 + CC Art. 62",
        condicoes=(
            "Tributação incide sobre atividades econômicas não amparadas pela imunidade (CTN Art. 14 §2º)",
            "OU descumprimento dos requisitos da imunidade (CTN Art. 14)",
        ),
    ),
    ("FUNDACAO", "IMUNE"): Elegibilidade(
        valido=True,
        base_legal="CF Art. 150 VI c + CTN Art. 14 + CC Art. 62 + Lei 9.532/97 Art. 12",
        condicoes=(
            "Sem distribuição de patrimônio aos instituidores (CTN Art. 14 I)",
            "Não remeter recursos ao exterior (CTN Art. 14 II)",
            "Manter escrituração regular (CTN Art. 14 III)",
            "Atendimento à finalidade estatutária (CC Art. 62)",
        ),
    ),

    # ═════════════════════════════════════════════════════════════════════════
    # ORGANIZACAO_RELIGIOSA — CC Art. 44 V (Lei 10.825/2003)
    # ═════════════════════════════════════════════════════════════════════════
    ("ORGANIZACAO_RELIGIOSA", "SIMPLES"): Elegibilidade(
        valido=False,
        base_legal="LC 123/2006 Art. 3º caput + CC Art. 44 V",
        motivo="Organização religiosa não é ME/EPP — não exerce atividade com finalidade lucrativa",
    ),
    ("ORGANIZACAO_RELIGIOSA", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal=(
            "CC Art. 44 V + CF Art. 150 §4º + RIR/2018 Arts. 184 e 587 + "
            "Lei 9.532/97 Art. 12 §2º + Lei 9.718/98 Art. 13"
        ),
        condicoes=(
            "Apenas para receitas de atividade econômica não amparada pela "
            "imunidade religiosa (CF Art. 150 §4º + STF RE 325.822)",
            "Faturamento ≤ R$ 78M (Lei 9.718/98 Art. 13)",
            "Manutenção da imunidade sobre culto e atividades essenciais",
        ),
        observacao=(
            "Caminho padrão é IMUNE para culto e essenciais. Comércio paralelo "
            "(livraria, café, estacionamento) sem amparo de essencialidade pode "
            "optar Presumido por composição RIR/2018 Arts. 184/587 + Lei 9.718. "
            "Não há ato COSIT vinculante específico para organizações religiosas "
            "no Presumido — aplicação por composição normativa (ERR-017.b)."
        ),
    ),
    ("ORGANIZACAO_RELIGIOSA", "REAL"): Elegibilidade(
        valido=True,
        base_legal="Lei 9.430/96 Art. 1º + RIR/2018 Art. 184",
        condicoes=(
            "Tributação incide sobre atividade econômica não amparada pela imunidade (CF Art. 150 §4º)",
            "OU descumprimento dos requisitos do Art. 14 CTN",
        ),
        observacao=(
            "Imunidade alcança culto e atividades essenciais (STF RE 325.822) — "
            "comércio paralelo sem amparo cai em Real."
        ),
    ),
    ("ORGANIZACAO_RELIGIOSA", "IMUNE"): Elegibilidade(
        valido=True,
        base_legal=(
            "CF Art. 150 VI b §4º + Lei 9.532/97 Art. 12 §2º + STF RE 325.822"
        ),
        condicoes=(
            "Atividade limitada a culto e fins essenciais (CF Art. 150 §4º)",
            "Sem distribuição de patrimônio (CTN Art. 14 I)",
            "Não remeter recursos ao exterior (CTN Art. 14 II)",
            "Manter escrituração regular (CTN Art. 14 III)",
        ),
    ),

    # ═════════════════════════════════════════════════════════════════════════
    # SCP — Sociedade em Conta de Participação (CC Art. 991-996)
    # SCP não tem personalidade jurídica própria. Sócio ostensivo aparece
    # perante terceiros e responde pelos tributos. Regime tributário do
    # sócio ostensivo é que vale — esta entidade não opta sozinha.
    # ═════════════════════════════════════════════════════════════════════════
    ("SCP", "SIMPLES"): Elegibilidade(
        valido=False,
        base_legal="CC Art. 991 + LC 123/2006 Art. 3º",
        motivo="SCP não possui personalidade jurídica — regime herdado do sócio ostensivo (CC Art. 991)",
        observacao="Verificar regime do sócio ostensivo via CNPJ próprio",
    ),
    ("SCP", "PRESUMIDO"): Elegibilidade(
        valido=False,
        base_legal="CC Art. 991 + Lei 9.718/98 Art. 13",
        motivo="SCP não possui personalidade jurídica — regime herdado do sócio ostensivo (CC Art. 991)",
        observacao="Verificar regime do sócio ostensivo via CNPJ próprio",
    ),
    ("SCP", "REAL"): Elegibilidade(
        valido=False,
        base_legal="CC Art. 991 + Lei 9.430/96 Art. 1º",
        motivo="SCP não possui personalidade jurídica — regime herdado do sócio ostensivo (CC Art. 991)",
        observacao="Verificar regime do sócio ostensivo via CNPJ próprio",
    ),
    ("SCP", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CC Art. 991 + CF Art. 150 VI",
        motivo="SCP não possui personalidade jurídica — regime herdado do sócio ostensivo (CC Art. 991)",
    ),

    # ═════════════════════════════════════════════════════════════════════════
    # ESC — Empresa Simples de Crédito (LC 167/2019)
    # ═════════════════════════════════════════════════════════════════════════
    ("ESC", "SIMPLES"): Elegibilidade(
        valido=False,
        base_legal="LC 167/2019 Art. 1º + LC 123/2006 Art. 17 VIII",
        motivo=(
            "ESC realiza atividade financeira (empréstimos, descontos, "
            "financiamentos com recursos próprios) — vedação ao Simples "
            "para atividades financeiras (LC 123/2006 Art. 17)."
        ),
    ),
    ("ESC", "PRESUMIDO"): Elegibilidade(
        valido=True,
        base_legal="LC 167/2019 Art. 1º §1º + Lei 9.718/98 Art. 13",
        condicoes=(
            "Receita bruta anual ≤ R$ 4,8M (LC 167/2019 Art. 1º §1º)",
            "Constituída como EI, EIRELI/SLU ou Sociedade Limitada (LC 167/2019 Art. 1º)",
        ),
        observacao=(
            "ESC tem teto de R$ 4,8M (LC 167/2019). Acima disso descaracteriza "
            "a forma e exige reenquadramento como financeira (Real obrigatório)."
        ),
    ),
    ("ESC", "REAL"): Elegibilidade(
        valido=True,
        base_legal="LC 167/2019 Art. 1º + Lei 9.430/96 Art. 1º + Lei 9.718/98 Art. 14 II",
        observacao=(
            "Real obrigatório se exceder R$ 4,8M e for reenquadrada como "
            "instituição financeira (Lei 9.718/98 Art. 14 II)."
        ),
    ),
    ("ESC", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="CF Art. 150 VI + LC 167/2019",
        motivo="ESC tem finalidade lucrativa (atividade financeira com recursos próprios)",
    ),

    # ═════════════════════════════════════════════════════════════════════════
    # CONSORCIO — Lei 6.404/76 Art. 278-279
    # Consórcio não tem personalidade jurídica — cada consorciada tributa
    # sua parcela proporcional no seu próprio regime (IN RFB 1.199/2011).
    # ═════════════════════════════════════════════════════════════════════════
    ("CONSORCIO", "SIMPLES"): Elegibilidade(
        valido=False,
        base_legal="Lei 6.404/76 Art. 278 §1º + IN RFB 1.199/2011 + LC 123/2006 Art. 3º",
        motivo=(
            "Consórcio não tem personalidade jurídica (Lei 6.404/76 Art. 278 §1º). "
            "Tributação ocorre na consorciada, no regime dela."
        ),
        observacao="Cada consorciada tributa sua parcela proporcional",
    ),
    ("CONSORCIO", "PRESUMIDO"): Elegibilidade(
        valido=False,
        base_legal="Lei 6.404/76 Art. 278 §1º + IN RFB 1.199/2011",
        motivo="Consórcio não tem personalidade jurídica — não opta por regime próprio",
        observacao="Cada consorciada tributa sua parcela proporcional no próprio regime",
    ),
    ("CONSORCIO", "REAL"): Elegibilidade(
        valido=False,
        base_legal="Lei 6.404/76 Art. 278 §1º + IN RFB 1.199/2011",
        motivo="Consórcio não tem personalidade jurídica — não opta por regime próprio",
        observacao="Cada consorciada tributa sua parcela proporcional no próprio regime",
    ),
    ("CONSORCIO", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="Lei 6.404/76 Art. 278 §1º + CF Art. 150 VI",
        motivo="Consórcio não tem personalidade jurídica — não pode ser sujeito de imunidade",
    ),

    # ═════════════════════════════════════════════════════════════════════════
    # PRODUTOR_RURAL_PF — Pessoa física com inscrição no CAEPF (Lei 8.023/90)
    # Tributação no IRPF (livro caixa); CNPJ só se constituir PJ.
    # ═════════════════════════════════════════════════════════════════════════
    ("PRODUTOR_RURAL_PF", "SIMPLES"): Elegibilidade(
        valido=False,
        base_legal="LC 123/2006 Art. 3º caput + Lei 8.023/90",
        motivo=(
            "Produtor rural PF é tributado pelo IRPF (livro caixa, Lei 8.023/90). "
            "Simples é regime de PJ — produtor rural PF não opta sem antes "
            "constituir PJ (EI ou SLU)."
        ),
    ),
    ("PRODUTOR_RURAL_PF", "PRESUMIDO"): Elegibilidade(
        valido=False,
        base_legal="Lei 8.023/90 + Lei 9.718/98 Art. 13",
        motivo=(
            "Produtor rural PF é tributado pelo IRPF (livro caixa). Presumido "
            "é regime de PJ. Para optar, precisa constituir EI/SLU/LTDA."
        ),
    ),
    ("PRODUTOR_RURAL_PF", "REAL"): Elegibilidade(
        valido=False,
        base_legal="Lei 8.023/90 + Lei 9.430/96 Art. 1º",
        motivo=(
            "Produtor rural PF é tributado pelo IRPF (livro caixa). Real "
            "é regime de PJ. Para optar, precisa constituir EI/SLU/LTDA."
        ),
    ),
    ("PRODUTOR_RURAL_PF", "IMUNE"): Elegibilidade(
        valido=False,
        base_legal="Lei 8.023/90 + CF Art. 150 VI",
        motivo="Produtor rural PF tem finalidade lucrativa (atividade rural com fim econômico)",
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# Cobertura — sanity check de construção. Garante que TODA combinação
# (tipo × regime) tem célula. Falha em import-time se faltar alguma.
# ─────────────────────────────────────────────────────────────────────────────
_combinacoes_esperadas = {
    (tipo, regime) for tipo in _TODOS_TIPOS for regime in _TODOS_REGIMES
}
_combinacoes_construidas = set(_MATRIZ_BUILDER.keys())
_faltando = _combinacoes_esperadas - _combinacoes_construidas
if _faltando:
    raise RuntimeError(
        f"Matriz societária incompleta — combinações faltando: {sorted(_faltando)}"
    )


# Exposta como read-only. Mutação direta levanta TypeError.
MATRIZ: Mapping[tuple[TipoSocietario, RegimeBase], Elegibilidade] = MappingProxyType(
    _MATRIZ_BUILDER
)


# ─────────────────────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────────────────────

def elegibilidade(
    tipo_societario: TipoSocietario,
    regime: RegimeBase,
) -> Elegibilidade:
    """
    Consulta a matriz e retorna a elegibilidade da combinação.

    Função pura: mesma entrada -> mesma saída, sem efeitos colaterais.

    Raises:
        CombinacaoSocietariaNaoMapeadaError: se a combinação não estiver
            mapeada — defesa em profundidade contra Literal mal validado
            pelo caller. Herda de ValueError para compatibilidade.
    """
    chave = (tipo_societario, regime)
    if chave not in MATRIZ:
        raise CombinacaoSocietariaNaoMapeadaError(
            f"Combinação não mapeada: {tipo_societario} × {regime}. "
            f"Tipos válidos: {_TODOS_TIPOS}. Regimes válidos: {_TODOS_REGIMES}."
        )
    return MATRIZ[chave]


def regimes_permitidos(
    tipo_societario: TipoSocietario,
) -> tuple[Elegibilidade, ...]:
    """
    Retorna a tupla de `Elegibilidade` (objeto completo) de cada regime em
    que `tipo_societario` é elegível (`valido=True`).

    NOTA: a partir de WS6 Etapa 2 retorna `tuple[Elegibilidade, ...]`
    (não mais `tuple[str, ...]`). UI/caller deve inspecionar `.condicoes`
    e `.observacao` antes de exibir como elegível ao usuário — ex:
    cooperativa × Simples só é válida pra cooperativa de consumo.
    """
    return tuple(
        MATRIZ[(tipo_societario, regime)]
        for regime in _TODOS_REGIMES
        if MATRIZ[(tipo_societario, regime)].valido
    )


def tipos_para_regime(
    regime: RegimeBase,
) -> tuple[Elegibilidade, ...]:
    """
    Retorna a tupla de `Elegibilidade` (objeto completo) de cada tipo
    societário que pode optar por `regime`. Inverso de `regimes_permitidos`.

    NOTA: a partir de WS6 Etapa 2 retorna `tuple[Elegibilidade, ...]`
    (não mais `tuple[str, ...]`). Caller deve inspecionar condicoes
    antes de filtrar/exibir.
    """
    return tuple(
        MATRIZ[(tipo, regime)]
        for tipo in _TODOS_TIPOS
        if MATRIZ[(tipo, regime)].valido
    )
