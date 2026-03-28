"""
motor_tributario.py — Motor de Regras Tributárias Transicionais (2026-2033)
Projeto: Motor Tributário Conect 2026-2033
Escritório Contábil Conect — Sorocaba, SP

PADRÕES OBRIGATÓRIOS (Chefe veta qualquer desvio):
  - Decimal em TODOS os valores monetários. Float = PROIBIDO.
  - ROUND_HALF_UP em todos os quantize().
  - purge() chamado após gerar_diagnostico() — LGPD compliance.
  - Nenhum log com CNPJ, razão social ou dado pessoal.
  - Toda constante tem citação do artigo de lei.

Fases implementadas:
  Fase 1: EmpresaFornecedora, EmpresaCompradora, OperacaoFiscal (Pydantic V2)
  Fase 2: calcular_rbt12, calcular_fator_r, determinar_anexo, calcular_aliquota_efetiva
  Fase 3: calcular_fracao_ibs, calcular_fracao_cbs, get_aliquotas_iva_por_ano
  Fase 4: cenario_simples_puro, cenario_opt_out, calcular_split_payment_impacto
  Fase 5: gerar_diagnostico, _gerar_alertas, purge
"""

import gc
import logging
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Literal, Optional, Any

from pydantic import BaseModel, Field, field_validator, model_validator

from validadores import validar_cnpj, validar_ncm, validar_uf, validar_cnae, ValidationResult
from tabelas_simples import (
    TABELAS_ANEXOS,
    DISTRIBUICAO_DAS,
    CRONOGRAMA_IVA,
    CNAE_PARA_ANEXO,
    CNAE_PREFIXO_PARA_ANEXO,
    determinar_anexo_por_cnae,
    TETO_SIMPLES_NACIONAL,
    SUBLIMITE_ICMS_ISS,
    ALERTA_90_PERCENT_TETO,
    ANO_INICIO_SPLIT_PAYMENT,
    ALIQUOTA_RETENCAO_SPLIT_PAYMENT,
    obter_faixa_numero,
)
from regimes.base import BaseRegimeEngine, registrar_violacao, RegimeMismatchError
from regimes.lucro_presumido import LucroPresumidoEngine

logger = logging.getLogger("motor_conect.motor")

# Fator R: limiar para migração Anexo V → Anexo III (LC 123/2006, Art. 18, § 24)
FATOR_R_LIMIAR = Decimal("0.28")
FATOR_R_ZONA_RISCO_MIN = Decimal("0.27")
FATOR_R_ZONA_RISCO_MAX = Decimal("0.29")

# CNAEs que aplicam o Fator R (Serviços Anexo III/V)
CNAES_FATOR_R = frozenset({
    "6201501", "6202300", "6209100",  # TI
    "6911701", "6920601",              # Advocacia, Contabilidade
    "7111100", "7112000",              # Arquitetura, Engenharia
    "7210000", "8599603",              # P&D, Treinamento
})


# ─────────────────────────────────────────────────────────────────────────────
# FASE 1 — CLASSES DE DADOS (Pydantic V2)
# ─────────────────────────────────────────────────────────────────────────────

class Atividade(BaseModel):
    """
    Atividade individual do PGDAS-D para empresas multi-atividade.
    LC 123/2006, Art. 18, §§ 1º e 3º — cada atividade tributada no Anexo correto.

    Uso (ERR-008 — implementação futura):
        EmpresaFornecedora(atividades=[
            Atividade(receita=Decimal("95594.08"), anexo="III"),
            Atividade(receita=Decimal("4929.43"),  anexo="I"),
            Atividade(receita=Decimal("32970.57"), anexo="I",  icms_st=True),
            Atividade(receita=Decimal("5650.00"),  anexo="III", iss_retido=True),
        ])
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
    Fase 1: Validação rigorosa de todos os campos.
    """
    cnpj: str = Field(..., description="CNPJ com ou sem pontuação")
    razao_social: str = Field(..., min_length=2, description="Razão social completa")
    regime: Literal["SIMPLES", "PRESUMIDO", "REAL"] = Field(..., description="Regime tributário")
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
    atividades: Optional[List["Atividade"]] = Field(
        default=None,
        description=(
            "Atividades individuais para empresas multi-atividade (ERR-008). "
            "Quando preenchido, calcular_das_mensal() aplicará o Anexo correto por atividade. "
            "LC 123/2006, Art. 18, §3º. Implementação pendente de aprovação arquitetural."
        )
    )
    receita_com_st_icms: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description=(
            "Parcela mensal da receita com ICMS-ST (Substituição Tributária). "
            "Quando informado, o ICMS desta parcela é zerado no DAS (já retido pelo substituto). "
            "LC 123/2006, Art. 13, § 1º, VII."
        )
    )

    @field_validator("cnpj")
    @classmethod
    def validar_campo_cnpj(cls, v: str) -> str:
        resultado = validar_cnpj(v)
        if not resultado:
            raise ValueError(f"CNPJ inválido: {'; '.join(resultado.errors)}")
        return v

    @field_validator("cnae_principal")
    @classmethod
    def validar_campo_cnae(cls, v: str) -> str:
        resultado = validar_cnae(v)
        if not resultado:
            raise ValueError(f"CNAE inválido: {'; '.join(resultado.errors)}")
        import re
        return re.sub(r'[\s.\-/]', '', v.strip())

    @field_validator("uf_origem")
    @classmethod
    def validar_campo_uf(cls, v: str) -> str:
        resultado = validar_uf(v)
        if not resultado:
            raise ValueError(f"UF inválida: {'; '.join(resultado.errors)}")
        return v.strip().upper()

    @field_validator("faturamento_12m", "folha_salarios_12m", mode="before")
    @classmethod
    def converter_para_decimal(cls, v: Any) -> Optional[Decimal]:
        if v is None:
            return None
        if isinstance(v, float):
            logger.warning("AVISO: Float detectado em campo monetário. Convertendo para Decimal.")
            return Decimal(str(v))
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class EmpresaCompradora(BaseModel):
    """
    Dados do destinatário (comprador — pode ser B2B ou B2C).
    Fase 1: Define se crédito IBS/CBS é exigido.
    """
    tipo: Literal["B2B_CONTRIBUINTE", "B2C_CONSUMIDOR_FINAL"] = Field(
        ..., description="Tipo do comprador"
    )
    regime: str = Field(default="NAO_INFORMADO", description="Regime tributário do comprador")
    uf_destino: str = Field(..., description="UF de destino (2 letras)")

    @field_validator("uf_destino")
    @classmethod
    def validar_campo_uf(cls, v: str) -> str:
        resultado = validar_uf(v)
        if not resultado:
            raise ValueError(f"UF inválida: {'; '.join(resultado.errors)}")
        return v.strip().upper()


class OperacaoFiscal(BaseModel):
    """
    Dados da operação (NF-e, pedido, contrato).
    Fase 1: Validação temporal e de NCM.
    """
    data_emissao: date = Field(..., description="Data de emissão do documento fiscal")
    valor_operacao: Decimal = Field(..., gt=Decimal("0"), description="Valor da operação em R$")
    ncm_nbs: str = Field(..., description="NCM/NBS (8 dígitos)")
    c_class_trib: Optional[str] = Field(
        default=None, description="Código de classificação tributária LC 214/2025"
    )
    tinha_st_icms: bool = Field(
        default=False, description="Empresa possuía Substituição Tributária de ICMS"
    )
    possui_reducao_cbs_ibs: bool = Field(
        default=False,
        description="Produto com redução de alíquota CBS/IBS (medicamentos, agro, educação)"
    )
    beneficio_fiscal_antigo: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"),
        description="Isenção/benefício ICMS que será eliminado até 2032"
    )
    forma_recebimento: Literal["DINHEIRO", "PIX_BOLETO", "CARTAO"] = Field(
        default="PIX_BOLETO", description="Forma de recebimento (impacta Split Payment)"
    )
    rpa_mensal: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description=(
            "Receita do Período de Apuração (RPA) do mês corrente. "
            "Quando informado, usado como base do DAS em vez de RBT12/12. "
            "Obrigatório para auditoria e-CAC com precisão ≤ R$5,00. "
            "LC 123/2006, Art. 18, §1º — DAS calculado sobre RPA do mês."
        )
    )

    @field_validator("ncm_nbs")
    @classmethod
    def validar_campo_ncm(cls, v: str) -> str:
        resultado = validar_ncm(v)
        if not resultado:
            raise ValueError(f"NCM inválido: {'; '.join(resultado.errors)}")
        import re
        return re.sub(r'[\s.\-]', '', v.strip())

    @field_validator("data_emissao")
    @classmethod
    def validar_data_transicional(cls, v: date) -> date:
        if not (2026 <= v.year <= 2033):
            raise ValueError(
                f"Data {v} fora do período transicional LC 214/2025 (2026-2033). "
                f"Para períodos fora da transição, usar motor legado."
            )
        return v

    @field_validator("valor_operacao", "beneficio_fiscal_antigo", mode="before")
    @classmethod
    def converter_para_decimal(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            logger.warning("AVISO: Float detectado em valor_operacao. Convertendo para Decimal.")
            return Decimal(str(v))
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


# ─────────────────────────────────────────────────────────────────────────────
# MOTOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class MotorReformaTributaria:
    """
    Motor Transicional de Regras Tributárias (2026-2033).
    Realiza o embate técnico entre a Legislação Antiga e o Novo IVA Dual (LC 214/2025).

    Uso:
        motor = MotorReformaTributaria(fornecedora, compradora, operacao)
        diagnostico = motor.gerar_diagnostico()
        # motor.purge() é chamado automaticamente

    LGPD: Nenhum dado persiste após purge().
    """

    def __init__(
        self,
        fornecedora: EmpresaFornecedora,
        compradora: EmpresaCompradora,
        operacao: OperacaoFiscal,
    ) -> None:
        self.fornecedora = fornecedora
        self.compradora = compradora
        self.operacao = operacao
        self._diagnostico_gerado = False

        # ── TRILHA UNIFICADA (MAX_FISCAL_04) ─────────────────────────────────
        # Lista compartilhada: motor principal + todos os engines de regime
        # escrevem aqui. Um único ponto de verdade para o auditor.
        self.trilha_auditoria: List[Dict[str, Any]] = []

        # Log SEM PII (regime e tipo apenas — sem CNPJ, razão social)
        logger.info(
            "Motor iniciado | regime=%s | tipo_comprador=%s | ano=%s",
            self.fornecedora.regime,
            self.compradora.tipo,
            self.operacao.data_emissao.year,
        )

        # [MAX_FISCAL_03] Validação de Cronograma de Transição (Timeline Awareness)
        self._validar_timeline()

        # ── DISPATCHER DE REGIME ────────────────────────────────────────────
        # Instancia o engine correto e vincula à trilha unificada.
        # Guard Clause (Camada 2) ocorre dentro do engine — exceção gravada na trilha.
        self._engine_regime: Optional[BaseRegimeEngine] = self._instanciar_engine()

    def _instanciar_engine(self) -> Optional[BaseRegimeEngine]:
        """Despacha para o engine de regime correto, passando a trilha unificada."""
        regime = self.fornecedora.regime
        if regime == "PRESUMIDO":
            return LucroPresumidoEngine(self.fornecedora, self.trilha_auditoria)
        # REAL e MEI: a implementar nas próximas fases (ROADMAP itens 3 e 6)
        # Simples Nacional usa os métodos nativos do MotorReformaTributaria
        return None

    def obter_engine_regime(self) -> Optional[BaseRegimeEngine]:
        """Retorna o engine de regime instanciado (para uso externo nos audits)."""
        return self._engine_regime

    def _validar_timeline(self):
        """Validação obrigatória da data base da operação (MAX_FISCAL_03)."""
        ano = self.operacao.data_emissao.year
        status = "TESTE" if ano == 2026 else "EFETIVO" if ano <= 2028 else "TRANSICAO"
        self._registrar_passo(
            id="MAX_FISCAL_03",
            titulo="Validação de Cronograma de Transição",
            base=f"Ano {ano}",
            deducoes="N/A",
            aliquota="Configurada por Data",
            valor=f"Status: {status}",
            lei="LC 214/2025, Art. 360",
            detalhe=f"Ano de operação {ano} validado para motor transicional."
        )

    def _registrar_passo(
        self, id: str, titulo: str, base: Any, deducoes: Any, 
        aliquota: Any, valor: Any, lei: str, detalhe: str = ""
    ) -> None:
        """Registro obrigatório de Memória de Cálculo (MAX_FISCAL_01/02)."""
        passo = {
            "id": id,
            "titulo": titulo,
            "formula": f"Base [{base}] - Deduções [{deducoes}] * Alíquota [{aliquota}] = {valor}",
            "memoria": {
                "base": str(base),
                "deducoes": str(deducoes),
                "aliquota": str(aliquota),
                "valor_final": str(valor)
            },
            "amparo_legal": lei,
            "detalhe": detalhe,
            "timestamp": str(datetime.now())
        }
        self.trilha_auditoria.append(passo)

    # ── FASE 2: NÚCLEO SIMPLES NACIONAL ──────────────────────────────────────

    def calcular_rbt12(self) -> Decimal:
        """
        Receita Bruta Acumulada 12 meses.
        LC 123/2006, Art. 12, § 1º.
        """
        return self.fornecedora.faturamento_12m.quantize(Decimal("0.01"), ROUND_HALF_UP)

    def calcular_fator_r(self) -> Optional[Decimal]:
        """
        Fator R = Folha de Salários 12m / RBT12.
        LC 123/2006, Art. 18, § 24.
        Aplicável apenas para CNAEs de serviço com tributação nos Anexos III/V.
        Retorna None se folha não informada ou CNAE não elegível.
        """
        if self.fornecedora.folha_salarios_12m is None:
            return None
        if self.fornecedora.cnae_principal not in CNAES_FATOR_R:
            return None
        rbt12 = self.calcular_rbt12()
        if rbt12 == Decimal("0"):
            return Decimal("0")
        fator = self.fornecedora.folha_salarios_12m / rbt12
        return fator.quantize(Decimal("0.0001"), ROUND_HALF_UP)

    def determinar_anexo(self) -> str:
        """
        Determina o Anexo Simples Nacional correto.
        Precedência:
          1. Anexo informado explicitamente (self.fornecedora.anexo_simples)
          2. Fator R: se elegível e >= 0.28 → Anexo III (mesmo que CNAE indique V)
          3. Mapeamento CNAE → Anexo (tabelas_simples.CNAE_PARA_ANEXO)
          4. Fallback: Anexo III (serviço genérico)
        LC 123/2006, Art. 18, §§ 1º e 24.
        """
        if self.fornecedora.anexo_simples:
            return self.fornecedora.anexo_simples

        fator_r = self.calcular_fator_r()
        if fator_r is not None and fator_r >= FATOR_R_LIMIAR:
            # Fator R >= 0.28: migra de Anexo V para Anexo III
            # LC 123/2006, Art. 18, § 24
            return "III"

        cnae = self.fornecedora.cnae_principal
        return determinar_anexo_por_cnae(cnae)

    def _buscar_faixa(self, rbt12: Decimal, anexo: str):
        """
        Retorna (aliquota_nominal, parcela_deduzir) para o RBT12 e Anexo informados.
        Raises ValueError se RBT12 > teto do Simples Nacional.
        """
        tabela = TABELAS_ANEXOS.get(anexo)
        if not tabela:
            raise ValueError(f"Anexo '{anexo}' inválido. Use I, II, III, IV ou V.")

        for limite, aliquota, parcela in tabela:
            if rbt12 <= limite:
                return aliquota, parcela

        raise ValueError(
            f"RBT12 R$ {rbt12:,.2f} excede o teto do Simples Nacional "
            f"(R$ {TETO_SIMPLES_NACIONAL:,.2f}). Empresa deve migrar de regime."
        )

    def calcular_ae_por_anexo(self, anexo: str) -> Decimal:
        """
        Calcula a alíquota efetiva para um Anexo específico, baseando-se no RBT12 total.
        LC 123/2006, Art. 18, § 1º.
        """
        rbt12 = self.calcular_rbt12()
        aliq_nominal, parcela_deduzir = self._buscar_faixa(rbt12, anexo)
        
        # Fórmula SRF: ((RBT12 × Aliq_nominal) - Parcela_Deduzir) / RBT12
        aliquota_efetiva = ((rbt12 * aliq_nominal) - parcela_deduzir) / rbt12
        return aliquota_efetiva.quantize(Decimal("0.000001"), ROUND_HALF_UP)

    def calcular_aliquota_efetiva(self) -> Decimal:
        """
        Alíquota efetiva do DAS total (baseada no Anexo principal).
        LC 123/2006, Art. 18, § 1º.
        Precisão: 6 casas decimais, ROUND_HALF_UP.
        """
        anexo = self.determinar_anexo()
        rbt12 = self.calcular_rbt12()
        aliq_nominal, parcela_deduzir = self._buscar_faixa(rbt12, anexo)
        
        # Fórmula SRF: ((RBT12 × Aliq_nominal) - Parcela_Deduzir) / RBT12
        ae = ((rbt12 * aliq_nominal) - parcela_deduzir) / rbt12
        ae_final = ae.quantize(Decimal("0.000001"), ROUND_HALF_UP)
        
        self._registrar_passo(
            id="AE_SIMPLES",
            titulo=f"Alíquota Efetiva (Anexo {anexo})",
            base=f"RBT12 R$ {rbt12:,.2f}",
            deducoes=f"PD R$ {parcela_deduzir:,.2f}",
            aliquota=f"Nominal {(aliq_nominal*100):.2f}%",
            valor=f"{(ae_final*100):.4f}%",
            lei="LC 123/2006, Art. 18, § 1º",
            detalhe=f"Fórmula: ((RBT12 * Aliq_Nominal) - PD) / RBT12"
        )
        return ae_final

    def calcular_das_mensal(self) -> Decimal:
        """
        DAS mensal.
        Suporta multi-atividade (ERR-008) quando self.fornecedora.atividades está presente.
        
        LC 123/2006, Art. 18, § 3º:
        "No caso de a ME ou a EPP exercer mais de uma atividade [...] a alíquota 
        nominal [...] será a correspondente à respectiva atividade [...] aplicada 
        sobre a base de cálculo da mesma."
        """
        rbt12 = self.calcular_rbt12()

        # CASO A: Multi-atividade (ERR-008)
        if self.fornecedora.atividades:
            das_total = Decimal("0")
            for item in self.fornecedora.atividades:
                ae = self.calcular_ae_por_anexo(item.anexo)
                faixa_num = obter_faixa_numero(rbt12, item.anexo)
                
                # Ajuste de segregação (ST/ISS Retido)
                dist = DISTRIBUICAO_DAS.get(item.anexo, {}).get(faixa_num, {})
                pct_abatimento = Decimal("0")
                if item.icms_st:
                    pct_abatimento += dist.get("ICMS", Decimal("0"))
                if item.iss_retido:
                    pct_abatimento += dist.get("ISS", Decimal("0"))
                
                ae_liquida = (ae * (Decimal("1") - pct_abatimento)).quantize(
                    Decimal("0.000001"), ROUND_HALF_UP
                )
                
                das_item = (item.receita * ae_liquida).quantize(Decimal("0.01"), ROUND_HALF_UP)
                das_total += das_item
            return das_total

        # CASO B: Comportamento Legado (Única Atividade ou RPA Global)
        # ERR-007: RPA real tem precedência sobre estimativa RBT12/12
        base = self.operacao.rpa_mensal if self.operacao.rpa_mensal is not None \
            else (rbt12 / Decimal("12"))
        aliquota = self.calcular_aliquota_efetiva()

        if self.fornecedora.receita_com_st_icms is None:
            return (base * aliquota).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # ERR-006: Segregação ICMS-ST parcial (legado)
        anexo = self.determinar_anexo()
        faixa = obter_faixa_numero(rbt12, anexo)
        dist = DISTRIBUICAO_DAS.get(anexo, {}).get(faixa, {})
        icms_pct = dist.get("ICMS", Decimal("0"))

        receita_sem_st = base - self.fornecedora.receita_com_st_icms
        das_sem_st = (receita_sem_st * aliquota).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # Para a parcela com ST: retira a fração ICMS da alíquota efetiva
        ae_sem_icms = (aliquota - aliquota * icms_pct).quantize(Decimal("0.000001"), ROUND_HALF_UP)
        das_com_st = (self.fornecedora.receita_com_st_icms * ae_sem_icms).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        total_das = (das_sem_st + das_com_st).quantize(Decimal("0.01"), ROUND_HALF_UP)

        self._registrar_passo(
            id="DAS_ST_SEGREGAÇÃO",
            titulo="Segregação de ICMS-ST no DAS",
            base=f"ST R$ {self.fornecedora.receita_com_st_icms:,.2f} | s/ST R$ {receita_sem_st:,.2f}",
            deducoes=f"ICMS {icms_pct*100:.2f}% na faixa",
            aliquota=f"AE s/ICMS {ae_sem_icms*100:.4f}%",
            valor=f"R$ {total_das:,.2f}",
            lei="LC 123/2006, Art. 13, § 1º, VII",
            detalhe="Parcela com ST reduz a alíquota efetiva pela fração correspondente ao ICMS."
        )

        return total_das

    def calcular_das_detalhado(self, rpa: Optional[Decimal] = None) -> Decimal:
        """
        DAS com arredondamento per-tributo — estrutura de componentes individuais.
        Suporta multi-atividade (ERR-008).
        """
        rbt12 = self.calcular_rbt12()

        # CASO A: Multi-atividade
        if self.fornecedora.atividades:
            total_detalhado = Decimal("0")
            for item in self.fornecedora.atividades:
                ae = self.calcular_ae_por_anexo(item.anexo)
                faixa_num = obter_faixa_numero(rbt12, item.anexo)
                dist = DISTRIBUICAO_DAS.get(item.anexo, {}).get(faixa_num, {})
                
                if not dist:
                    total_detalhado += (item.receita * ae).quantize(Decimal("0.01"), ROUND_HALF_UP)
                    continue

                for tributo, p_dist in dist.items():
                    if p_dist == Decimal("0"):
                        continue
                        
                    # Zerar se for ST de ICMS ou Retenção de ISS
                    if tributo == "ICMS" and item.icms_st:
                        continue
                    if tributo == "ISS" and item.iss_retido:
                        continue
                        
                    # Arredondamento individual per-tributo per-item
                    componente = (item.receita * ae * p_dist).quantize(Decimal("0.01"), ROUND_HALF_UP)
                    total_detalhado += componente
            return total_detalhado

        # CASO B: Legado
        base = rpa if rpa is not None else (
            self.operacao.rpa_mensal if self.operacao.rpa_mensal is not None
            else (rbt12 / Decimal("12"))
        )
        aliquota = self.calcular_aliquota_efetiva()
        anexo = self.determinar_anexo()
        faixa = obter_faixa_numero(rbt12, anexo)
        dist = DISTRIBUICAO_DAS.get(anexo, {}).get(faixa, {})

        if not dist:
            return (base * aliquota).quantize(Decimal("0.01"), ROUND_HALF_UP)

        das_total = Decimal("0")
        for tributo, percentual_dist in dist.items():
            if percentual_dist == Decimal("0"):
                continue

            # Especial para legado ERR-006 (ST ICMS global)
            if tributo == "ICMS" and self.fornecedora.receita_com_st_icms is not None:
                r_sem_st = base - self.fornecedora.receita_com_st_icms
                comp = (r_sem_st * aliquota * percentual_dist).quantize(Decimal("0.01"), ROUND_HALF_UP)
            else:
                comp = (base * aliquota * percentual_dist).quantize(Decimal("0.01"), ROUND_HALF_UP)
            
            das_total += comp

        return das_total

    def _distancia_proxima_faixa(self) -> Optional[Decimal]:
        """
        Quanto falta para entrar na próxima faixa de RBT12 (em R$).
        Útil para alertas de planejamento.
        """
        rbt12 = self.calcular_rbt12()
        anexo = self.determinar_anexo()
        tabela = TABELAS_ANEXOS.get(anexo, [])
        for limite, _, _ in tabela:
            if rbt12 <= limite:
                return (limite - rbt12).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return None  # Já no teto

    def alertar_fator_r(self) -> Optional[str]:
        """
        Alerta zona de risco do Fator R (0.27-0.29).
        Nesta faixa, pequena variação na folha muda drasticamente a alíquota.
        """
        fator_r = self.calcular_fator_r()
        if fator_r is not None and FATOR_R_ZONA_RISCO_MIN <= fator_r < FATOR_R_ZONA_RISCO_MAX:
            return (
                f"FATOR R = {fator_r:.4f} — ZONA DE RISCO (0,27-0,29). "
                f"Monitorar mensalmente. Pequena variação na folha pode mudar de "
                f"Anexo V ({fator_r:.0%} DAS) para Anexo III."
            )
        return None

    # ── FASE 3: DISSECAÇÃO IBS/CBS ────────────────────────────────────────────

    def get_aliquotas_iva_por_ano(self) -> Dict[str, Decimal]:
        """
        Alíquotas CBS e IBS vigentes no ano da operação.
        LC 214/2025, Art. 360 (cronograma de transição).
        """
        ano = self.operacao.data_emissao.year
        if ano in CRONOGRAMA_IVA:
            return CRONOGRAMA_IVA[ano]
        # Ano fora do cronograma: usa pleno
        from tabelas_simples import ALIQUOTA_IVA_PLENA_ESTIMADA
        return {
            "CBS": ALIQUOTA_IVA_PLENA_ESTIMADA,
            "IBS": Decimal("0.177"),
        }

    def _calcular_fracao_componente(self, componente: str) -> Decimal:
        """
        Calcula quanto do DAS total corresponde ao componente informado (ex: "CBS", "IBS", "ICMS").
        Retorna valor em R$ por mês.
        """
        anexo = self.determinar_anexo()
        rbt12 = self.calcular_rbt12()
        faixa_num = obter_faixa_numero(rbt12, anexo)
        if faixa_num == 0:
            return Decimal("0")

        distribuicao = DISTRIBUICAO_DAS.get(anexo, {}).get(faixa_num, {})
        percentual = distribuicao.get(componente, Decimal("0"))
        das_mensal = self.calcular_das_mensal()
        return (das_mensal * percentual).quantize(Decimal("0.01"), ROUND_HALF_UP)

    def calcular_fracao_ibs(self) -> Decimal:
        """IBS mensal dentro do DAS (durante período transitório)."""
        return self._calcular_fracao_componente("IBS")

    def calcular_fracao_cbs(self) -> Decimal:
        """CBS mensal dentro do DAS (durante período transitório)."""
        return self._calcular_fracao_componente("CBS")

    def calcular_credito_simples_para_b2b(self) -> Decimal:
        """
        Crédito IBS+CBS que o comprador B2B pode apropriar quando fornecedor está no Simples.
        No Simples puro: crédito limitado ao cobrado na guia (fração mínima do DAS).
        LC 214/2025, Art. X (regra de creditamento para Simples Nacional).
        """
        aliquotas_iva = self.get_aliquotas_iva_por_ano()
        # Crédito = valor_operacao × (CBS + IBS vigentes no ano)
        credito = self.operacao.valor_operacao * (
            aliquotas_iva["CBS"] + aliquotas_iva["IBS"]
        )
        return credito.quantize(Decimal("0.01"), ROUND_HALF_UP)

    # ── FASE 4: SIMULAÇÃO OPT-OUT ─────────────────────────────────────────────

    def cenario_simples_puro(self) -> Dict[str, Any]:
        """
        Cenário A: Empresa mantém tudo no Simples Nacional.
        IBS/CBS dentro do DAS — crédito para B2B é mínimo.
        Risco: perda de contrato com indústria/grande empresa.
        """
        aliquota_efetiva = self.calcular_aliquota_efetiva()
        custo_total = (self.operacao.valor_operacao * aliquota_efetiva).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        credito_b2b = self.calcular_credito_simples_para_b2b()
        percentual_credito = (credito_b2b / self.operacao.valor_operacao * 100).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        return {
            "cenario": "SIMPLES_PURO",
            "descricao": "Empresa mantém regime Simples Nacional sem alteração",
            "custo_das_por_operacao": str(custo_total),
            "aliquota_efetiva": str(aliquota_efetiva),
            "credito_gerado_para_comprador": str(credito_b2b),
            "percentual_credito_nf": f"{percentual_credito}%",
            "risco_b2b": self.compradora.tipo == "B2B_CONTRIBUINTE",
            "observacao": (
                "Crédito gerado é mínimo (fração do DAS). "
                "Comprador B2B pode exigir migração ou trocar fornecedor."
                if self.compradora.tipo == "B2B_CONTRIBUINTE"
                else "Comprador B2C: crédito irrelevante."
            ),
        }

    def cenario_opt_out(self) -> Dict[str, Any]:
        """
        Cenário B: Empresa opta por recolher IBS/CBS separadamente (Opt-Out).
        Mantém Simples para IRPJ/CSLL/CPP. Recolhe IVA por fora.
        Resultado: 100% de crédito para comprador B2B.
        Impacto caixa: geralmente neutro (IVA repassado no preço).
        LC 214/2025, Art. X (dispositivo de opt-out — aguardar regulamentação).
        """
        aliquotas_iva = self.get_aliquotas_iva_por_ano()
        aliquota_efetiva = self.calcular_aliquota_efetiva()

        # Custo Simples sem as frações IBS/CBS (mantém IRPJ/CSLL/CPP/ICMS/ISS)
        ibs_no_das = self._calcular_fracao_componente("IBS")
        cbs_no_das = self._calcular_fracao_componente("CBS")
        das_mensal = self.calcular_das_mensal()
        das_sem_iva = das_mensal - ibs_no_das - cbs_no_das

        # IVA recolhido separadamente (por operação)
        iva_por_fora = (
            self.operacao.valor_operacao * (aliquotas_iva["CBS"] + aliquotas_iva["IBS"])
        ).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # Custo total = DAS (sem IVA) + IVA por fora
        custo_das_por_operacao = (self.operacao.valor_operacao * aliquota_efetiva).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        custo_total = custo_das_por_operacao + iva_por_fora

        return {
            "cenario": "OPT_OUT",
            "descricao": "Empresa recolhe IBS/CBS separadamente, mantém Simples para demais tributos",
            "custo_das_por_operacao": str(custo_das_por_operacao),
            "iva_recolhido_por_fora": str(iva_por_fora),
            "custo_total": str(custo_total),
            "credito_gerado_para_comprador": str(iva_por_fora),
            "percentual_credito_nf": "100%",
            "risco_b2b": False,
            "impacto_caixa": "NEUTRO se IVA repassado no preço de venda",
            "observacao": (
                "100% do IBS/CBS é creditável pelo comprador B2B. "
                "Empresa mantém competitividade no polo industrial."
            ),
        }

    def calcular_split_payment_impacto(self) -> Dict[str, Any]:
        """
        Split Payment: IBS/CBS retido na fonte pelo intermediador financeiro.
        Ativo a partir de Jan/2027 para pagamentos eletrônicos (PIX, Boleto, Cartão).
        DINHEIRO escapa da retenção (até regulamentação posterior).
        LC 214/2025, Art. X (Split Payment).
        """
        ano = self.operacao.data_emissao.year
        forma = self.operacao.forma_recebimento

        if ano >= ANO_INICIO_SPLIT_PAYMENT and forma != "DINHEIRO":
            # Split Payment dinâmico: usa CBS+IBS do ano da operação (LC 214/2025, Art. 344)
            aliquotas_ano = self.get_aliquotas_iva_por_ano()
            taxa_retencao = aliquotas_ano["CBS"] + aliquotas_ano["IBS"]
            retencao = (
                self.operacao.valor_operacao * taxa_retencao
            ).quantize(Decimal("0.01"), ROUND_HALF_UP)
            
            self._registrar_passo(
                id="SPLIT_PAYMENT",
                titulo="Retenção Split Payment (IBS/CBS)",
                base=f"Valor NF R$ {self.operacao.valor_operacao:,.2f}",
                deducoes="R$ 0,00",
                aliquota=f"{(taxa_retencao*100):.2f}%",
                valor=f"R$ {retencao:,.2f}",
                lei="LC 214/2025, Art. 344 e Art. X",
                detalhe=f"Forma de recebimento {forma} identificada como elegível."
            )
            
            return {
                "ativo": True,
                "ano_ativacao": ANO_INICIO_SPLIT_PAYMENT,
                "forma_recebimento": forma,
                "retencao_imediata": str(retencao),
                "percentual_retencao": f"{taxa_retencao * 100:.2f}%",
                "impacto_liquidez": "ALTO — IBS/CBS retido antes de cair na conta.",
                "reducao_mensal_estimada": str(
                    (retencao * 12).quantize(Decimal("0.01"), ROUND_HALF_UP)
                ) + " (anual)",
            }

        return {
            "ativo": False,
            "motivo": (
                f"Ano {ano} < {ANO_INICIO_SPLIT_PAYMENT} (Split Payment ainda não ativo)."
                if ano < ANO_INICIO_SPLIT_PAYMENT
                else "Pagamento em DINHEIRO: não sujeito ao Split Payment em 2027."
            ),
            "retencao_imediata": "0.00",
            "impacto_liquidez": "ZERO",
        }

    def calcular_disparidade_anual(self) -> Decimal:
        """
        Diferença financeira anualizada entre Cenário B (Opt-Out) e Cenário A (Simples Puro).
        Positivo = Opt-Out custa mais; Negativo = Opt-Out economiza.
        Na prática deve ser próximo de zero (IVA repassado no preço).
        """
        custo_a = Decimal(self.cenario_simples_puro().get("custo_das_por_operacao", "0"))
        custo_b_total = Decimal(self.cenario_opt_out().get("custo_total", "0"))
        disparidade_por_operacao = custo_b_total - custo_a
        # Multiplica por 12 para projeção anual (simplificação: 1 operação/mês)
        return (disparidade_por_operacao * 12).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # ── FASE 5: DIAGNÓSTICO + ALERTAS + LGPD ─────────────────────────────────

    def _gerar_alertas(self) -> List[Dict[str, str]]:
        """
        Sistema de alertas baseado em gatilhos matemáticos.
        Cada alerta tem nível: CRITICO, ALTO, MEDIO, INFO.
        """
        alertas = []
        rbt12 = self.calcular_rbt12()
        ano = self.operacao.data_emissao.year
        fator_r = self.calcular_fator_r()

        # CRÍTICO: RBT12 > 90% do teto
        if rbt12 > ALERTA_90_PERCENT_TETO:
            alertas.append({
                "nivel": "CRITICO",
                "codigo": "RBT12_PROXIMO_TETO",
                "mensagem": (
                    f"RBT12 R$ {rbt12:,.2f} = {(rbt12/TETO_SIMPLES_NACIONAL*100):.1f}% do teto. "
                    f"Planejar migração para Lucro Presumido IMEDIATAMENTE."
                ),
            })

        # ALTO: Fator R zona de risco
        alerta_fr = self.alertar_fator_r()
        if alerta_fr:
            alertas.append({
                "nivel": "ALTO",
                "codigo": "FATOR_R_ZONA_RISCO",
                "mensagem": alerta_fr,
            })

        # ALTO: Split Payment ativo
        split = self.calcular_split_payment_impacto()
        if split["ativo"]:
            alertas.append({
                "nivel": "ALTO",
                "codigo": "SPLIT_PAYMENT_ATIVO",
                "mensagem": (
                    f"Split Payment ativo desde Jan/2027. "
                    f"Retenção na fonte: R$ {split['retencao_imediata']} por operação."
                ),
            })

        # ALTO: B2B com Simples puro — risco de perda de contrato
        if (
            self.compradora.tipo == "B2B_CONTRIBUINTE"
            and self.fornecedora.regime == "SIMPLES"
        ):
            alertas.append({
                "nivel": "ALTO",
                "codigo": "RISCO_B2B_CREDITO_INSUFICIENTE",
                "mensagem": (
                    "Fornecedor no Simples gera crédito mínimo para comprador B2B. "
                    "Avaliar Opt-Out para reter contrato com indústria/grande empresa."
                ),
            })

        # MÉDIO: Sublimite ICMS/ISS ultrapassado
        if rbt12 > SUBLIMITE_ICMS_ISS:
            alertas.append({
                "nivel": "MEDIO",
                "codigo": "SUBLIMITE_ICMS_ISS",
                "mensagem": (
                    f"RBT12 R$ {rbt12:,.2f} > sublimite R$ {SUBLIMITE_ICMS_ISS:,.2f}. "
                    f"ICMS e ISS devem ser apurados em guias separadas (fora do DAS)."
                ),
            })

        # MÉDIO: Benefício fiscal antigo a ser extinto
        if self.operacao.beneficio_fiscal_antigo > Decimal("0"):
            alertas.append({
                "nivel": "MEDIO",
                "codigo": "BENEFICIO_FISCAL_EXTINCAO",
                "mensagem": (
                    f"Benefício fiscal de R$ {self.operacao.beneficio_fiscal_antigo:,.2f} "
                    f"será eliminado gradualmente até 2032 (LC 214/2025, Art. X). "
                    f"Revisar precificação."
                ),
            })

        # INFO: Substituição Tributária ICMS extinta
        if self.operacao.tinha_st_icms:
            alertas.append({
                "nivel": "INFO",
                "codigo": "ST_ICMS_EXTINTA",
                "mensagem": (
                    "Substituição Tributária de ICMS será extinta com o IBS. "
                    "Capital de giro travado na ST será liberado progressivamente até 2032."
                ),
            })

        return alertas

    def gerar_diagnostico(self) -> Dict[str, Any]:
        """
        Diagnóstico completo em JSON estruturado.
        Integra Fases 2, 3, 4 e 5 num único payload tipificado.
        LGPD: purge() é chamado automaticamente após geração.
        """
        rbt12 = self.calcular_rbt12()
        anexo = self.determinar_anexo()
        aliquota_efetiva = self.calcular_aliquota_efetiva()
        fator_r = self.calcular_fator_r()
        aliquotas_iva = self.get_aliquotas_iva_por_ano()

        diagnostico = {
            "versao_schema": "1.0",
            "versao_lei": "LC123_2006_LC214_2025",
            "data_analise": str(date.today()),
            "ano_operacao": self.operacao.data_emissao.year,

            "empresa": {
                "regime": self.fornecedora.regime,
                "cnae": self.fornecedora.cnae_principal,
                "uf": self.fornecedora.uf_origem,
                "anexo_simples": anexo,
                "rbt12": str(rbt12),
                "fator_r": str(fator_r) if fator_r is not None else None,
                "proxima_faixa_em": str(self._distancia_proxima_faixa()),
            },

            "comprador": {
                "tipo": self.compradora.tipo,
                "uf_destino": self.compradora.uf_destino,
                "exige_credito_iva": self.compradora.tipo == "B2B_CONTRIBUINTE",
            },

            "operacao": {
                "valor": str(self.operacao.valor_operacao),
                "ncm": self.operacao.ncm_nbs,
                "forma_recebimento": self.operacao.forma_recebimento,
            },

            "aliquotas": {
                "efetiva_das_total": str(aliquota_efetiva),
                "efetiva_percentual": f"{aliquota_efetiva * 100:.4f}%",
                "cbs_vigente_ano": str(aliquotas_iva["CBS"]),
                "ibs_vigente_ano": str(aliquotas_iva["IBS"]),
                "fracao_cbs_no_das": str(self.calcular_fracao_cbs()),
                "fracao_ibs_no_das": str(self.calcular_fracao_ibs()),
            },

            "cenarios": {
                "simples_puro": self.cenario_simples_puro(),
                "opt_out": self.cenario_opt_out(),
                "disparidade_anual_estimada": str(self.calcular_disparidade_anual()),
                "recomendacao": (
                    "OPT_OUT recomendado para reter cliente B2B."
                    if self.compradora.tipo == "B2B_CONTRIBUINTE"
                    else "SIMPLES_PURO adequado para B2C. Sem impacto de crédito."
                ),
            },

            "split_payment": self.calcular_split_payment_impacto(),

            "alertas": self._gerar_alertas(),

            "trilha_auditoria": self.trilha_auditoria, # [MAX_FISCAL_01]

            "meta": {
                "elaborado_por": "Escritório Conect — Motor Tributário v1.0",
                "legislacao_base": ["LC 123/2006", "LC 214/2025"],
                "validar_com_profissional": True,
                "aviso": (
                    "Este diagnóstico é de natureza informativa. "
                    "Decisões tributárias devem ser validadas por contador responsável (CRC-SP)."
                ),
            },
        }

        self._diagnostico_gerado = True
        self.purge()
        return diagnostico

    # ── LGPD — PURGE OBRIGATÓRIO ──────────────────────────────────────────────

    def purge(self) -> None:
        """
        LGPD Art. 15 — Eliminação de dados após finalidade cumprida.
        Chamado automaticamente após gerar_diagnostico().
        Pode ser chamado manualmente a qualquer momento.
        Após purge(), o objeto não deve ser reutilizado.
        """
        self.fornecedora = None  # type: ignore[assignment]
        self.compradora = None   # type: ignore[assignment]
        self.operacao = None     # type: ignore[assignment]
        gc.collect()
        logger.info("purge() concluído. Dados da análise eliminados da memória.")

    def __del__(self) -> None:
        """Garante purge() no garbage collection caso não tenha sido chamado."""
        if self.fornecedora is not None or self.compradora is not None:
            self.purge()
