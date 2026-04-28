# -*- coding: utf-8 -*-
"""
historico_seis_meses.py — Schema da janela fiscal consolidada de 6 meses.

Fase 0a do Plano de Reforma Tributária. Implementa o blueprint
``~/.claude/plans/blueprint-historico-seis-meses-corrigido.md`` (28/04/2026)
após auditoria que aplicou 6 correções ao desenho original do Luiz Moreira.

Amparo legal:
    - LC 123/2006 Art. 3º §1º (RBT12 — definição)
    - LC 123/2006 Art. 12 §1º (apuração mensal Simples)
    - LC 123/2006 Art. 18 §24 (Fator R)
    - LC 214/2025 Art. 47 (apuração mensal CBS/IBS)
    - CLAUDE.md MAX_03 (data base declarada antes do cálculo)
    - Rail R3 (versão normativa) + Rail R5 (separação rígida de regimes)

Decisões arquiteturais herdadas do blueprint:
    - Pydantic V2 + ``frozen=True`` em todos os schemas (imutabilidade)
    - ``Decimal`` em qualquer campo monetário (CLAUDE.md)
    - ``valor_em(TETO_SIMPLES_NACIONAL_VERSIONADO, data)`` em vez do
      inexistente ``resolve_teto_simples`` (correção 2 do blueprint)
    - CNAE 7 dígitos sem hífen, padrão do projeto (correção 4)
    - ``OperacaoMensal`` ganha ``forma_recebimento`` + tipos extras
      ``COMPRA_ATIVO_IMOBILIZADO``, ``DEVOLUCAO_VENDA``, ``AJUSTE``
      (correção 5 — Tesoureiro precisa pra fluxo de caixa)
    - ``_fator_r_consistente`` consulta ``regras_cnae.resolve_anexo``
      antes de bloquear, evitando falso positivo em CNAEs categoria
      ``E_VEDADO`` ou ``D_ESPECIAL`` (correção 6)
    - Oscilação RBT12 > 50% vira **warning na trilha**, não erro de
      construção (correção 7 — empresa em recuperação real pode oscilar)
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import List, Literal, Optional

from dateutil.relativedelta import relativedelta
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.regras_cnae import resolve_anexo
from core.versioned_rule import TETO_SIMPLES_NACIONAL_VERSIONADO, valor_em
from validadores import validar_cnpj


# ─────────────────────────────────────────────────────────────────────────────
# Tipos enumerados (Literal — Pydantic V2 valida na entrada)
# ─────────────────────────────────────────────────────────────────────────────

TipoOperacao = Literal[
    "VENDA_B2B",
    "VENDA_B2C",
    "COMPRA_INSUMO",
    "COMPRA_USO_CONSUMO",
    "COMPRA_ATIVO_IMOBILIZADO",   # LC 214/2025 Art. 28 §III (crédito de ativo)
    "DEVOLUCAO_VENDA",            # realidade contábil — devoluções afetam RBT12
    "AJUSTE",                     # ajustes pós-fechamento
]

FormaRecebimento = Literal[
    "PIX_DIRETO",
    "PIX_VIA_PSP",
    "BOLETO",
    "CARTAO_DEBITO",
    "CARTAO_CREDITO",
    "DINHEIRO",
    "TRANSFERENCIA",
]


# ─────────────────────────────────────────────────────────────────────────────
# OperacaoMensal — granularidade mínima dentro do mês
# ─────────────────────────────────────────────────────────────────────────────


class OperacaoMensal(BaseModel):
    """Operação agregada por tipo dentro de um mês.

    Não é uma nota fiscal individual — é a soma de todas as notas do mesmo
    tipo no mês (ex: "soma de todas VENDA_B2B em PIX em nov/2025"). Mantém
    rastreabilidade pra Tesoureiro reconstruir fluxo de caixa.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    tipo: TipoOperacao
    valor_total: Decimal = Field(..., gt=0, max_digits=15, decimal_places=2)
    quantidade_notas: int = Field(..., ge=1)

    # CNAE 7 dígitos sem hífen (padrão do projeto — ver tabelas_simples.py:55)
    cnae_predominante: str = Field(..., pattern=r"^\d{7}$")

    # DIFAL: UF destino só faz sentido pra venda interestadual; opcional.
    uf_destino: Optional[str] = Field(None, pattern=r"^[A-Z]{2}$")

    # Tesoureiro precisa pra fluxo de caixa. Obrigatório em VENDA_*,
    # opcional nos outros tipos (compras saem por contas a pagar — outro fluxo).
    forma_recebimento: Optional[FormaRecebimento] = Field(
        None,
        description="Obrigatório em VENDA_B2B / VENDA_B2C; opcional nos demais tipos.",
    )

    @model_validator(mode="after")
    def _venda_exige_forma_recebimento(self) -> "OperacaoMensal":
        if self.tipo.startswith("VENDA_") and self.forma_recebimento is None:
            raise ValueError(
                f"Operação {self.tipo} exige forma_recebimento "
                "(Tesoureiro precisa pra reconstruir fluxo de caixa)."
            )
        return self


# ─────────────────────────────────────────────────────────────────────────────
# MesFiscal — 1 mês fiscal (granularidade mínima do diagnóstico consolidado)
# ─────────────────────────────────────────────────────────────────────────────


class MesFiscal(BaseModel):
    """1 mês fiscal — bloco de construção de ``HistoricoSeisMeses``.

    Amparo: LC 214/2025 Art. 47 (apuração mensal CBS/IBS) +
    LC 123/2006 Art. 12 §1º (RBT12 móvel — receita dos 12 meses anteriores).
    """

    model_config = ConfigDict(frozen=True)

    competencia: str = Field(
        ...,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description='ISO YYYY-MM — formato canônico do projeto (ver CLAUDE.md).',
    )
    rbt12_declarado: Decimal = Field(
        ...,
        ge=0,
        max_digits=15,
        decimal_places=2,
        description="RBT12 vigente NO mês — LC 123/2006 Art. 12 §1º.",
    )
    faturamento_mes: Decimal = Field(..., ge=0, max_digits=15, decimal_places=2)
    folha_pagamento_mes: Decimal = Field(
        ...,
        ge=0,
        max_digits=15,
        decimal_places=2,
        description="Pró-labore + salários + encargos — Fator R LC 123/2006 Art. 18 §24.",
    )
    folha_12m: Decimal = Field(
        ...,
        ge=0,
        max_digits=15,
        decimal_places=2,
        description="Soma da folha nos últimos 12 meses — denominador do Fator R.",
    )
    operacoes: List[OperacaoMensal] = Field(default_factory=list)
    anexo_aplicado: Literal["I", "II", "III", "IV", "V"]
    fator_r_calculado: Decimal = Field(
        ...,
        ge=0,
        le=1,
        max_digits=5,
        decimal_places=4,
        description="folha_12m / rbt12_declarado — limiar 28% (LC 123 Art. 18 §24).",
    )

    @field_validator("competencia")
    @classmethod
    def _competencia_dentro_da_janela(cls, v: str) -> str:
        """Rail R3 — VersionedRule cobre janela 2024-2033."""
        ano, _ = v.split("-")
        if int(ano) < 2024 or int(ano) > 2033:
            raise ValueError(
                f"Competência {v} fora da janela normativa 2024-2033 "
                "(Rail R3 — versão normativa)."
            )
        return v

    @model_validator(mode="after")
    def _coerencia_faturamento_operacoes(self) -> "MesFiscal":
        """Soma das operações ≈ faturamento_mes (tolerância 1%).

        Opera apenas quando há operações registradas e faturamento > 0;
        meses sem detalhamento de operações ficam isentos.
        """
        if not self.operacoes or self.faturamento_mes == 0:
            return self
        soma_ops = sum((o.valor_total for o in self.operacoes), Decimal("0"))
        if soma_ops <= 0:
            return self
        delta = abs(soma_ops - self.faturamento_mes) / self.faturamento_mes
        if delta > Decimal("0.01"):
            raise ValueError(
                f"Soma das operações (R$ {soma_ops}) diverge de "
                f"faturamento_mes (R$ {self.faturamento_mes}) em mais de 1%."
            )
        return self

    @model_validator(mode="after")
    def _fator_r_consistente(self) -> "MesFiscal":
        """Verifica anexo_aplicado contra o motor de regras de CNAE (WS12).

        Correção 6 do blueprint: NÃO levanta erro. CNAEs em categoria
        ``D_ESPECIAL`` ou ``E_VEDADO`` resolvem para fallback que pode
        divergir do anexo declarado sem ser erro do declarante. Quando
        houver divergência, registra um marcador interno via
        ``object.__setattr__`` (driblando ``frozen=True``) pra orquestrador
        externo decidir se promove a warning na trilha de auditoria.
        """
        if self.faturamento_mes == 0 or not self.operacoes:
            return self

        cnae_principal = self.operacoes[0].cnae_predominante
        try:
            anexo_esperado, fonte_categoria = resolve_anexo(
                cnae_principal,
                self.fator_r_calculado,
            )
        except (ValueError, KeyError):
            # CNAE fora do catálogo — pula validação cruzada (Rail R2).
            return self

        if anexo_esperado != self.anexo_aplicado:
            # frozen=True impede atribuição normal; object.__setattr__ contorna
            # apenas pra carimbar metadado de divergência. Não vaza pra trilha
            # diretamente — quem promove é o orquestrador.
            object.__setattr__(
                self,
                "_anexo_divergencia",
                {
                    "cnae": cnae_principal,
                    "anexo_esperado": anexo_esperado,
                    "anexo_declarado": self.anexo_aplicado,
                    "fonte_categoria": fonte_categoria,
                },
            )
        return self


# ─────────────────────────────────────────────────────────────────────────────
# HistoricoSeisMeses — janela consolidada
# ─────────────────────────────────────────────────────────────────────────────


# Alias semântico — entrada da trilha de auditoria (warning não-bloqueante).
WarningTrilha = dict


class HistoricoSeisMeses(BaseModel):
    """Janela fiscal consolidada com 6 meses sequenciais.

    Amparo: LC 123/2006 Art. 3º §1º + Art. 12 §1º; LC 214/2025 Art. 47;
    CLAUDE.md MAX_03 (data base declarada).

    Granularidade: 6 meses é o piso pra detectar sazonalidade (>= 1 ciclo
    trimestral) e oscilações relevantes de RBT12 sem inflar input do cliente.
    """

    model_config = ConfigDict(frozen=True)

    cnpj: str = Field(
        ...,
        pattern=r"^\d{14}$",
        description="CNPJ raiz + filial (14 dígitos, sem pontuação).",
    )
    razao_social: str = Field(..., min_length=3, max_length=200)
    regime_atual: Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI"]
    tipo_societario: Literal[
        "MEI",
        "MEI_CAMINHONEIRO",
        "ME",
        "EPP",
        "LTDA",
        "SLU",
        "SA",
        "COOPERATIVA",
        "ASSOCIACAO",
        "FUNDACAO",
        "ORG_RELIGIOSA",
        "SCP",
        "ESC",
        "CONSORCIO",
        "PRODUTOR_RURAL_PF",
    ]
    competencia_referencia: date = Field(
        ...,
        description=(
            "Data base do diagnóstico (MAX_03 — declarar antes do cálculo). "
            "Tipicamente último dia do último mês da janela."
        ),
    )
    meses: List[MesFiscal] = Field(..., min_length=6, max_length=6)

    # Warnings não-bloqueantes coletados durante a validação (correção 7).
    # ``exclude=True`` mantém o campo fora da serialização padrão pra não
    # poluir o contrato externo — orquestrador acessa via atributo direto.
    warnings: List[WarningTrilha] = Field(default_factory=list, exclude=True)

    @field_validator("cnpj")
    @classmethod
    def _cnpj_modulo_11(cls, v: str) -> str:
        """Validação de CNPJ via Mod-11 oficial Receita Federal."""
        if not validar_cnpj(v).ok:
            raise ValueError(f"CNPJ {v} falha validação Módulo 11 da Receita Federal.")
        return v

    @model_validator(mode="after")
    def _meses_sequenciais_sem_buraco(self) -> "HistoricoSeisMeses":
        """Bloqueia janela com mês faltante (ex: nov/dez/fev/mar/abr/mai)."""
        comps = [m.competencia for m in self.meses]
        for i in range(1, len(comps)):
            ano_ant, mes_ant = map(int, comps[i - 1].split("-"))
            ano_atu, mes_atu = map(int, comps[i].split("-"))
            esperado_mes = mes_ant + 1 if mes_ant < 12 else 1
            esperado_ano = ano_ant if mes_ant < 12 else ano_ant + 1
            if (ano_atu, mes_atu) != (esperado_ano, esperado_mes):
                raise ValueError(
                    f"Buraco temporal na janela: após {comps[i - 1]} esperado "
                    f"{esperado_ano:04d}-{esperado_mes:02d}, recebido {comps[i]}."
                )
        return self

    @model_validator(mode="after")
    def _sem_duplicatas(self) -> "HistoricoSeisMeses":
        comps = [m.competencia for m in self.meses]
        if len(set(comps)) != len(comps):
            raise ValueError(f"Competências duplicadas na janela: {comps}.")
        return self

    @model_validator(mode="after")
    def _janela_18_meses_max(self) -> "HistoricoSeisMeses":
        """Mês mais antigo da janela não pode ultrapassar 18 meses antes
        de ``competencia_referencia`` (LC 123 Art. 12 §1º — RBT12 móvel só
        olha 12 meses pra trás; 18 meses é folga conservadora pra fechamento)."""
        mes_antigo = self.meses[0].competencia
        ano, mes = map(int, mes_antigo.split("-"))
        data_mes_antigo = date(ano, mes, 1)
        limite = self.competencia_referencia - relativedelta(months=18)
        if data_mes_antigo < limite:
            raise ValueError(
                f"Mês mais antigo {mes_antigo} ultrapassa janela de 18 meses "
                f"em relação a competencia_referencia "
                f"({self.competencia_referencia.isoformat()}, "
                f"limite {limite.isoformat()}) — LC 123 Art. 12 §1º."
            )
        return self

    @model_validator(mode="after")
    def _rbt12_oscilacao_alerta(self) -> "HistoricoSeisMeses":
        """Oscilação > 50% mês-a-mês vira warning, não erro (correção 7).

        Empresa em crise/recuperação pode oscilar mais. Conservadorismo
        bloqueador atrapalha cliente legítimo. Quem quiser bloquear pode
        promover o warning a erro fora do schema.
        """
        for i in range(1, 6):
            anterior = self.meses[i - 1].rbt12_declarado
            atual = self.meses[i].rbt12_declarado
            if anterior > 0:
                delta = abs(atual - anterior) / anterior
                if delta > Decimal("0.5"):
                    self.warnings.append(
                        {
                            "tipo": "RBT12_OSCILACAO_ALTA",
                            "competencia_anterior": self.meses[i - 1].competencia,
                            "competencia_atual": self.meses[i].competencia,
                            "delta_pct": str((delta * 100).quantize(Decimal("0.01"))),
                            "valor_anterior": str(anterior),
                            "valor_atual": str(atual),
                            "amparo_legal": (
                                "LC 123/2006 Art. 12 §1º — RBT12 móvel; "
                                "oscilação >50% sugere revisão de lançamentos."
                            ),
                            "severidade": "MEDIO",
                        }
                    )
        return self

    @model_validator(mode="after")
    def _folha_12m_sanity(self) -> "HistoricoSeisMeses":
        """folha_12m sempre ≥ folha_pagamento_mes (impossibilidade matemática)."""
        for m in self.meses:
            if m.folha_12m < m.folha_pagamento_mes:
                raise ValueError(
                    f"{m.competencia}: folha_12m (R$ {m.folha_12m}) < "
                    f"folha_pagamento_mes (R$ {m.folha_pagamento_mes}) — impossível."
                )
        return self

    @model_validator(mode="after")
    def _teto_simples_continuo(self) -> "HistoricoSeisMeses":
        """SIMPLES não pode estourar teto vigente em nenhum mês da janela.

        Correção 2: usa ``valor_em(TETO_SIMPLES_NACIONAL_VERSIONADO, data)``
        em vez do inexistente ``resolve_teto_simples``. Cumpre Rail R5
        (separação rígida de regimes).
        """
        if self.regime_atual != "SIMPLES":
            return self
        for m in self.meses:
            ano, _ = map(int, m.competencia.split("-"))
            teto = valor_em(TETO_SIMPLES_NACIONAL_VERSIONADO, date(ano, 1, 1))
            if m.rbt12_declarado > teto:
                raise ValueError(
                    f"{m.competencia}: RBT12 R$ {m.rbt12_declarado} excede "
                    f"teto Simples Nacional R$ {teto} — empresa deveria ter "
                    "migrado de regime (LC 123/2006 Art. 3º §9)."
                )
        return self
