# -*- coding: utf-8 -*-
"""
motor.py — Schemas do Motor Tributário (Pydantic V2)
Separados da lógica de cálculo para evitar monólitos e facilitar testes unitários.
"""

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from validadores import validar_cnae, validar_cnpj, validar_ncm, validar_uf

logger = logging.getLogger("motor_conect.schemas")


# ─────────────────────────────────────────────────────────────────────────────
# ERR-039 — Bloqueio preventivo de NCMs monofásicas (FROZEN)
#
# LC 214/2025 Arts. 172-174 institui regime monofásico específico para
# combustíveis, cigarros e bebidas alcoólicas — cálculo da CBS/IBS ocorre
# numa única etapa da cadeia (importador/produtor/distribuidor) e este motor
# NÃO modela essa dinâmica. Aceitar NCM monofásica no formulário padrão
# produziria cálculo cumulativo semanticamente errado em cadeia que deveria
# ser monofásica — MAX_FISCAL_01 + Lei 8.137/1990 Art. 1º II.
#
# Comparação é feita por PREFIXO de 4 dígitos (capítulo NCM), pois o regime
# monofásico abrange a posição inteira e não suas subposições específicas.
# CF/88 Art. 149 §2º III + LC 214/2025 Art. 172-174.
# ─────────────────────────────────────────────────────────────────────────────
NCMS_MONOFASICAS_BLOQUEADAS: frozenset[str] = frozenset({
    # Combustíveis e derivados de petróleo — LC 214/2025 Art. 172 I
    "2710",
    # Cigarros e produtos do tabaco — LC 214/2025 Art. 172 II
    "2402", "2403",
    # Bebidas alcoólicas — LC 214/2025 Art. 172 III
    "2203",  # cerveja
    "2204",  # vinho de uva
    "2205",  # vermute
    "2206",  # outras bebidas fermentadas
    "2207",  # álcool etílico não desnaturado ≥ 80% vol. (para bebidas)
    "2208",  # aguardentes, licores, destilados
})


# ─────────────────────────────────────────────────────────────────────────────
# ERR-038 — Granularidade de forma de recebimento (FROZEN)
#
# Split Payment (LC 214/2025 Art. 353 §1º) só se aplica a pagamentos
# intermediados por PSP — Prestador de Serviço de Pagamento. PIX direto
# banco-a-banco NÃO tem PSP e portanto não dispara retenção automática.
# Agrupar PIX_DIRETO e PIX_VIA_PSP sob o mesmo rótulo ("PIX_BOLETO")
# superestima a retenção em pagamentos domésticos reais.
# ─────────────────────────────────────────────────────────────────────────────
FORMAS_PAGAMENTO_COM_PSP: frozenset[str] = frozenset({
    # Formas que passam por PSP e disparam Split Payment a partir de 2027
    # LC 214/2025 Art. 353 §1º
    "PIX_VIA_PSP",  # Mercado Pago, PagSeguro, Stone, Nubank PJ, etc.
    "BOLETO",       # Registrado/emitido via PSP do banco
    "CARTAO",       # Credenciadoras/adquirentes (PSP por natureza)
})

class Atividade(BaseModel):
    """
    Atividade individual do PGDAS-D para empresas multi-atividade.
    LC 123/2006, Art. 18, §§ 1º e 3º — cada atividade tributada no Anexo correto.
    """
    model_config = ConfigDict(extra="forbid")

    receita: Decimal = Field(..., gt=Decimal("0"), description="Receita desta atividade no mês (RPA parcial)")
    anexo: Literal["I", "II", "III", "IV", "V"] = Field(..., description="Anexo Simples desta atividade")
    icms_st: bool = Field(default=False, description="ICMS retido por ST — zerado no DAS desta parcela")
    iss_retido: bool = Field(default=False, description="ISS retido pelo tomador — zerado no DAS desta parcela")

    @field_validator("receita", mode="before")
    @classmethod
    def converter_para_decimal(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            return Decimal(str(v))
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class EmpresaFornecedora(BaseModel):
    """
    Dados do emitente (cliente do escritório — fornecedor na cadeia B2B).
    """
    model_config = ConfigDict(extra="forbid")

    cnpj: str = Field(..., description="CNPJ com ou sem pontuação")
    razao_social: str = Field(..., min_length=2, description="Razão social completa")
    regime: Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI"] = Field(..., description="Regime tributário")
    cnae_principal: str = Field(..., description="CNAE principal (7 dígitos)")
    uf_origem: str = Field(..., description="UF de origem (2 letras)")
    faturamento_12m: Decimal = Field(..., ge=Decimal("0"), description="RBT12 em R$")
    folha_salarios_12m: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description="Folha de salários 12 meses (necessário para Fator R)"
    )
    anexo_simples: Optional[Literal["I", "II", "III", "IV", "V"]] = Field(
        default=None, description="Anexo Simples (auto-detectado se None)"
    )
    atividades: Optional[List[Atividade]] = Field(
        default=None,
        description="Atividades individuais para empresas multi-atividade (ERR-008)."
    )
    receita_com_st_icms: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description="Parcela mensal da receita com ICMS-ST."
    )
    categoria_mei: Optional[Literal["COMERCIO", "INDUSTRIA", "SERVICOS", "COMERCIO_SERVICOS"]] = Field(
        default=None, description="Categoria MEI."
    )
    data_inicio_atividade: Optional[date] = Field(
        default=None, description="Data de início de atividade."
    )

    # ── WS6 — Eixo societário (separado do regime tributário) ──────────────
    # Tipo societário = forma jurídica (CC + Tabela RFB Naturezas Jurídicas).
    # Distinto de `regime` (tributário) e `enquadramento_simples` (porte/MEI).
    # Default None preserva compatibilidade com chamadas legadas.
    tipo_societario: Optional[
        Literal["EI", "SLU", "LTDA", "SS", "SA", "COOPERATIVA",
                "ASSOCIACAO", "FUNDACAO", "ORGANIZACAO_RELIGIOSA"]
    ] = Field(
        default=None,
        description="Forma jurídica RFB. MEI é alias aceito (normalizado para EI + enquadramento_simples=MEI).",
    )

    # Qualificações especiais ortogonais ao tipo societário.
    # Uma associação pode ter OSCIP (Lei 9.790/99) + CEBAS (Lei 12.101/2009).
    qualificacoes_especiais: List[
        Literal["OSCIP", "OS", "CEBAS", "UTILIDADE_PUBLICA_FEDERAL"]
    ] = Field(
        default_factory=list,
        description="Qualificações que podem coexistir (OSCIP+CEBAS é real).",
    )

    # Porte/enquadramento dentro do Simples — derivado de RBT12, mas pode
    # ser declarado pra MEI (Art. 18-A LC 123/2006) onde é status, não porte.
    enquadramento_simples: Optional[Literal["MEI", "ME", "EPP"]] = Field(
        default=None,
        description="MEI/ME/EPP — status no Simples Nacional. MEI é Art. 18-A.",
    )

    @model_validator(mode="before")
    @classmethod
    def _expandir_alias_mei(cls, data: Any) -> Any:
        """
        Aceita tipo_societario="MEI" como alias UX-friendly e normaliza para
        a representação fiscalmente correta: tipo_societario="EI" +
        enquadramento_simples="MEI" (Art. 18-A LC 123/2006 — MEI é status
        do Simples para Empresário Individual com faturamento ≤ R$ 81k).
        """
        if not isinstance(data, dict):
            return data
        if data.get("tipo_societario") == "MEI":
            data["tipo_societario"] = "EI"
            data.setdefault("enquadramento_simples", "MEI")
        return data

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tipo_exibicao(self) -> Optional[str]:
        """
        Rótulo amigável pra UI/PDF: 'MEI' quando enquadramento_simples='MEI',
        senão o tipo societário cru. Mantém storage fiel à RFB e display
        fiel à linguagem do contador.
        """
        if self.enquadramento_simples == "MEI":
            return "MEI"
        return self.tipo_societario

    @field_validator("cnpj")
    @classmethod
    def validar_campo_cnpj(cls, v: str) -> str:
        res = validar_cnpj(v)
        if not res.ok:
            raise ValueError(f"CNPJ Invalido: {', '.join(res.errors)}")
        return re.sub(r'[\s.\-/]', '', v.strip())

    @field_validator("cnae_principal")
    @classmethod
    def validar_campo_cnae(cls, v: str) -> str:
        res = validar_cnae(v)
        if not res.ok:
            raise ValueError(f"CNAE Invalido: {', '.join(res.errors)}")
        return re.sub(r'[\s.\-/]', '', v.strip())

    @field_validator("uf_origem")
    @classmethod
    def validar_campo_uf(cls, v: str) -> str:
        res = validar_uf(v)
        if not res.ok:
            raise ValueError(f"UF Invalida: {', '.join(res.errors)}")
        return v.strip().upper()

    @field_validator("faturamento_12m", "folha_salarios_12m", mode="before")
    @classmethod
    def converter_para_decimal(cls, v: Any) -> Optional[Decimal]:
        if v is None:
            return None
        if isinstance(v, float):
            return Decimal(str(v))
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class EmpresaCompradora(BaseModel):
    """
    Dados do destinatário (comprador).
    """
    model_config = ConfigDict(extra="forbid")

    tipo: Literal["B2B_CONTRIBUINTE", "B2C_CONSUMIDOR_FINAL", "MISTO"] = Field(
        ..., description="Tipo do comprador"
    )
    percentual_b2b: Decimal = Field(
        default=Decimal("100"), ge=Decimal("0"), le=Decimal("100")
    )
    # ERR-037 — regime do comprador sai de `str` livre para Literal fechado.
    # Valor captado vira dado auditável na trilha (crédito cruzado LC 214/2025
    # Art. 47 §2º fica previsto para Fase 4). "NAO_INFORMADO" é o default
    # explícito — assume PIOR CASO (sem crédito).
    regime: Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI", "NAO_INFORMADO"] = Field(
        default="NAO_INFORMADO",
        description=(
            "Regime tributário do comprador — LC 214/2025 Art. 47 §2º. "
            "NAO_INFORMADO = pior caso (sem crédito cruzado)."
        ),
    )
    uf_destino: str = Field(..., description="UF de destino (2 letras)")

    @field_validator("uf_destino")
    @classmethod
    def validar_campo_uf(cls, v: str) -> str:
        res = validar_uf(v)
        if not res.ok:
            raise ValueError(f"UF Invalida: {', '.join(res.errors)}")
        return v.strip().upper()


class OperacaoFiscal(BaseModel):
    """
    Dados da operação tributária transicional.
    """
    model_config = ConfigDict(extra="forbid")

    data_emissao: date = Field(...)
    valor_operacao: Decimal = Field(..., gt=Decimal("0"))
    ncm_nbs: str = Field(..., description="NCM/NBS (8 dígitos)")
    c_class_trib: Optional[str] = Field(default=None)
    tinha_st_icms: bool = Field(default=False)
    reducao_cbs_ibs: Literal["INTEGRAL", "REDUCAO_30", "REDUCAO_60", "ISENTO"] = Field(default="INTEGRAL")
    # ERR-038 — Literal granular separa PIX banco-a-banco de PIX via PSP.
    # Split Payment só dispara para formas em FORMAS_PAGAMENTO_COM_PSP
    # (LC 214/2025 Art. 353 §1º). Ver motor_tributario.split_payment_impacto.
    forma_recebimento: Literal[
        "DINHEIRO",
        "PIX_DIRETO",    # banco-a-banco, sem PSP → NÃO dispara Split
        "PIX_VIA_PSP",   # Mercado Pago/PagSeguro/etc → dispara Split
        "BOLETO",        # registrado via PSP do banco → dispara Split
        "CARTAO",        # credenciadora/adquirente → dispara Split
    ] = Field(default="PIX_VIA_PSP")
    rpa_mensal: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    lucro_real_mensal: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    produto_importado: bool = Field(default=False)
    creditos_pis_cofins: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    qtd_itens: int = Field(default=1, ge=1, description="Quantidade de itens na NF-e")
    estorno_realizado: bool = Field(default=False, description="Flag de estorno após Split Payment")
    data_liquidacao: Optional[date] = Field(
        default=None,
        description="Data de liquidação financeira (Split Payment). Deve ser >= data_emissao."
    )

    @model_validator(mode="after")
    def validar_transicao(self):
        # Período transicional obrigatório — LC 214/2025, Art. 348
        if not (2026 <= self.data_emissao.year <= 2033):
            raise ValueError(
                f"Data {self.data_emissao} fora do período transicional válido (2026-2033). "
                "LC 214/2025 vigora apenas nesse intervalo."
            )
        # Liquidação não pode ser anterior à emissão
        if self.data_liquidacao is not None and self.data_liquidacao < self.data_emissao:
            raise ValueError(
                f"data_liquidacao ({self.data_liquidacao}) não pode ser anterior à emissão "
                f"({self.data_emissao}). Verifique a data de liquidação."
            )
        return self

    @field_validator("ncm_nbs")
    @classmethod
    def validar_campo_ncm(cls, v: str) -> str:
        res = validar_ncm(v)
        if not res.ok:
            raise ValueError(f"NCM Invalido: {', '.join(res.errors)}")
        limpo = re.sub(r'[\s.\-]', '', v.strip())

        # ERR-039 — Bloqueio de NCM de regime monofásico.
        # LC 214/2025 Arts. 172-174 (regime específico de combustíveis,
        # tabacos e bebidas alcoólicas) + CF/88 Art. 149 §2º III.
        # Este motor NÃO modela monofásico — aceitar gera cálculo
        # semanticamente errado (MAX_FISCAL_01). Falha fechada é
        # preferível a silenciar o erro no diagnóstico.
        prefixo_cap = limpo[:4]
        if prefixo_cap in NCMS_MONOFASICAS_BLOQUEADAS:
            raise ValueError(
                f"NCM {limpo} é de regime monofásico "
                "(LC 214/2025 Arts. 172-174). "
                "Este motor não modela cálculo monofásico. "
                "Consulte regra específica para o setor "
                "(combustíveis 2710, tabacos 2402/2403, "
                "bebidas alcoólicas 2203-2208)."
            )
        return limpo

    @field_validator("valor_operacao", mode="before")
    @classmethod
    def converter_para_decimal(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            return Decimal(str(v))
        return Decimal(str(v)) if not isinstance(v, Decimal) else v
