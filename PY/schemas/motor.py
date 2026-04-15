# -*- coding: utf-8 -*-
"""
motor.py — Schemas do Motor Tributário (Pydantic V2)
Separados da lógica de cálculo para evitar monólitos e facilitar testes unitários.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from validadores import validar_cnpj, validar_cnae, validar_ncm, validar_uf
import re

logger = logging.getLogger("motor_conect.schemas")

class Atividade(BaseModel):
    """
    Atividade individual do PGDAS-D para empresas multi-atividade.
    LC 123/2006, Art. 18, §§ 1º e 3º — cada atividade tributada no Anexo correto.
    """
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
        if v is None: return None
        if isinstance(v, float):
            return Decimal(str(v))
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class EmpresaCompradora(BaseModel):
    """
    Dados do destinatário (comprador).
    """
    tipo: Literal["B2B_CONTRIBUINTE", "B2C_CONSUMIDOR_FINAL", "MISTO"] = Field(
        ..., description="Tipo do comprador"
    )
    percentual_b2b: Decimal = Field(
        default=Decimal("100"), ge=Decimal("0"), le=Decimal("100")
    )
    regime: str = Field(default="NAO_INFORMADO")
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
    data_emissao: date = Field(...)
    valor_operacao: Decimal = Field(..., gt=Decimal("0"))
    ncm_nbs: str = Field(..., description="NCM/NBS (8 dígitos)")
    c_class_trib: Optional[str] = Field(default=None)
    tinha_st_icms: bool = Field(default=False)
    reducao_cbs_ibs: Literal["INTEGRAL", "REDUCAO_30", "REDUCAO_60", "ISENTO"] = Field(default="INTEGRAL")
    beneficio_fiscal_antigo: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    forma_recebimento: Literal["DINHEIRO", "PIX_BOLETO", "CARTAO"] = Field(default="PIX_BOLETO")
    rpa_mensal: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    lucro_real_mensal: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    creditos_pis_cofins: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))

    @model_validator(mode="after")
    def validar_transicao(self):
        # Validação temporal simples
        if not (2026 <= self.data_emissao.year <= 2033):
            logger.warning("Data %s fora do periodo transicional (2026-2033)", self.data_emissao)
        return self

    @field_validator("ncm_nbs")
    @classmethod
    def validar_campo_ncm(cls, v: str) -> str:
        res = validar_ncm(v)
        if not res.ok:
            raise ValueError(f"NCM Invalido: {', '.join(res.errors)}")
        return re.sub(r'[\s.\-]', '', v.strip())

    @field_validator("valor_operacao", "beneficio_fiscal_antigo", mode="before")
    @classmethod
    def converter_para_decimal(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            return Decimal(str(v))
        return Decimal(str(v)) if not isinstance(v, Decimal) else v
