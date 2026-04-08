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
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from difal import calcular_difal
from regimes.base import BaseRegimeEngine
from regimes.lucro_presumido import LucroPresumidoEngine
from regimes.lucro_real import LucroRealEngine
from regimes.mei import MEIEngine
from regimes.simples_multi import SimplesMultiAtividadeEngine
from tabelas_simples import (
    ALERTA_90_PERCENT_TETO,
    ANO_INICIO_SPLIT_PAYMENT,
    CRONOGRAMA_IVA,
    DISTRIBUICAO_DAS,
    SUBLIMITE_ICMS_ISS,
    TABELAS_ANEXOS,
    TETO_SIMPLES_NACIONAL,
    determinar_anexo_por_cnae_com_fonte,
    obter_faixa_numero,
)
from validadores import validar_cnae, validar_cnpj, validar_ncm, validar_uf

logger = logging.getLogger("motor_conect.motor")


def _fmt_brl(valor: Any) -> str:
    """
    Formata valor monetário no padrão BR: R$ X.XXX,YY (ponto milhar, vírgula decimal).

    Substitui o uso de f-strings com :,.2f que produzem formato US (R$ X,XXX.YY).
    Usar SEMPRE este helper em mensagens, justificativas e trilhas de auditoria
    que vão para humanos (UI, PDF). NÃO usar para serialização — para isso
    use Decimal/str(Decimal) que mantém o ponto decimal nativo do Python.

    REGRA À PROVA DE ERRO: nenhuma f-string {valor:,.2f} no projeto. Sempre _fmt_brl.
    """
    try:
        d = Decimal(str(valor or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except Exception:
        return "R$ 0,00"
    # Truque: formata em US, depois troca separadores
    return f"R$ {d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

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
    categoria_mei: Optional[Literal["COMERCIO", "INDUSTRIA", "SERVICOS", "COMERCIO_SERVICOS"]] = Field(
        default=None,
        description=(
            "Categoria MEI — determina DAS fixo. "
            "Obrigatório quando regime='MEI'. Default: SERVICOS. "
            "LC 123/2006, Art. 18-A."
        )
    )
    data_inicio_atividade: Optional[date] = Field(
        default=None,
        description=(
            "Data de início de atividade da empresa. "
            "Se empresa tem menos de 12 meses, RBT12 deve ser proporcionalizada. "
            "LC 123/2006, Art. 3º, §2º."
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
    Dados do destinatário (comprador — pode ser B2B, B2C ou mix dos dois).
    Fase 1: Define se crédito IBS/CBS é exigido.
    Empresas que vendem para ambos (ex: loja de materiais, escritório contábil)
    usam percentual_b2b para ponderar cenários.
    """
    tipo: Literal["B2B_CONTRIBUINTE", "B2C_CONSUMIDOR_FINAL", "MISTO"] = Field(
        ..., description="Tipo do comprador (MISTO = atende B2B e B2C)"
    )
    percentual_b2b: Decimal = Field(
        default=Decimal("100"),
        ge=Decimal("0"), le=Decimal("100"),
        description=(
            "Percentual da receita que vem de clientes B2B (0-100). "
            "Usado quando tipo='MISTO'. Ex: 70 = 70% B2B, 30% B2C."
        )
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
    reducao_cbs_ibs: Literal["INTEGRAL", "REDUCAO_30", "REDUCAO_60", "ISENTO"] = Field(
        default="INTEGRAL",
        description=(
            "Nível de redução CBS/IBS conforme LC 214/2025: "
            "INTEGRAL (sem redução), REDUCAO_30 (Art. 262 — profissionais liberais), "
            "REDUCAO_60 (Art. 258 — saúde, educação, cesta básica ampliada), "
            "ISENTO (Art. 264 — cesta básica nacional). "
        )
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
    lucro_real_mensal: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description=(
            "Lucro Real apurado no mês (R$). Usado pelo LucroRealEngine. "
            "Se None, usa receita mensal como proxy conservador. "
            "RIR/2018, Art. 228."
        )
    )
    creditos_pis_cofins: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"),
        description=(
            "Créditos PIS/COFINS não-cumulativo (R$). "
            "Lei 10.637/2002 (PIS) + Lei 10.833/2003 (COFINS)."
        )
    )
    # ─────────────────────────────────────────────────────────────────────────────
    # Fase 5 (Stress Test) — Campos Adicionais para testes R14 a R17
    # ─────────────────────────────────────────────────────────────────────────────
    data_liquidacao: Optional[date] = Field(
        default=None,
        description="Data real do recebimento/liquidação. O Split Payment atua aqui, não na emissão."
    )
    qtd_itens: int = Field(
        default=1, ge=1,
        description="Quantidade de NCMs distintos na nota (impacta timeout no CGIBS)."
    )
    estorno_realizado: bool = Field(
        default=False,
        description="Sinaliza se a operação sofreu devolução de mercadoria após liquidação."
    )
    produto_importado: bool = Field(
        default=False,
        description=(
            "True se conteúdo de importação > 40% (Res. SF 13/2012). "
            "Afeta alíquota interestadual ICMS (4%) e cálculo do DIFAL."
        )
    )

    @model_validator(mode="after")
    def validar_liquidacao(self):
        if self.data_liquidacao and self.data_liquidacao < self.data_emissao:
            raise ValueError(f"Data de liquidação {self.data_liquidacao} não pode ser anterior à emissão {self.data_emissao}")
        return self

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
        if regime == "MEI":
            return MEIEngine(self.fornecedora, self.trilha_auditoria)
        if regime == "REAL":
            return LucroRealEngine(self.fornecedora, self.trilha_auditoria)
        if regime == "SIMPLES" and self.fornecedora.atividades:
            return SimplesMultiAtividadeEngine(self.fornecedora, self.trilha_auditoria)
        # Simples Nacional mono-atividade usa os métodos nativos do MotorReformaTributaria
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
        aliquota: Any, valor: Any, lei: str, detalhe: str = "",
        vigente_desde: str = "",
    ) -> None:
        """Registro obrigatório de Memória de Cálculo (MAX_FISCAL_01/02)."""
        passo = {
            "tipo": "CALCULO",
            "id": id,
            "titulo": titulo,
            "formula": f"Base [{base}] - Deduções [{deducoes}] * Alíquota [{aliquota}] = {valor}",
            "memoria": {
                "base": str(base),
                "deducoes": str(deducoes),
                "aliquota": str(aliquota),
                "valor_final": str(valor),
            },
            "amparo_legal": lei,
            "vigente_desde": vigente_desde,
            "detalhe": detalhe,
            "timestamp": str(datetime.now()),
        }
        self.trilha_auditoria.append(passo)

    # ── FASE 2: NÚCLEO SIMPLES NACIONAL ──────────────────────────────────────

    def calcular_rbt12(self) -> Decimal:
        """
        Receita Bruta Acumulada 12 meses.
        Se empresa tem menos de 12 meses, proporcionaliza automaticamente.
        LC 123/2006, Art. 3º, §2º — limites proporcionais ao nº de meses.
        """
        rbt12 = self.fornecedora.faturamento_12m.quantize(Decimal("0.01"), ROUND_HALF_UP)

        if self.fornecedora.data_inicio_atividade is not None:
            hoje = self.operacao.data_emissao
            delta = (hoje.year - self.fornecedora.data_inicio_atividade.year) * 12 + \
                    (hoje.month - self.fornecedora.data_inicio_atividade.month)
            meses_atividade = max(1, min(delta, 12))

            if meses_atividade < 12:
                rbt12_proporcional = (rbt12 / meses_atividade * 12).quantize(
                    Decimal("0.01"), ROUND_HALF_UP
                )
                self._registrar_passo(
                    id="RBT12_PROPORCIONAL",
                    titulo=f"RBT12 proporcionalizada ({meses_atividade} meses de atividade)",
                    base=str(rbt12),
                    deducoes="N/A",
                    aliquota=f"{meses_atividade}/12",
                    valor=str(rbt12_proporcional),
                    lei="LC 123/2006, Art. 3º, §2º",
                    detalhe=(
                        f"Empresa iniciou em {self.fornecedora.data_inicio_atividade}. "
                        f"RBT12 informada R$ {rbt12:,.2f} ÷ {meses_atividade} meses × 12 = "
                        f"R$ {rbt12_proporcional:,.2f} (proporcionalizada)."
                    ),
                )
                return rbt12_proporcional

        return rbt12

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
            anexo = self.fornecedora.anexo_simples
            motivo = f"Anexo {anexo} informado explicitamente pelo operador."
            self._registrar_passo(
                id="DECISAO_ANEXO",
                titulo=f"Anexo Simples Nacional: {anexo} (explícito)",
                base=f"CNAE {self.fornecedora.cnae_principal}",
                deducoes="N/A",
                aliquota="N/A",
                valor=anexo,
                lei="LC 123/2006, Art. 18, §§ 1º e 24",
                detalhe=motivo,
                vigente_desde="01/07/2007 (LC 123/2006)",
            )
            return anexo

        fator_r = self.calcular_fator_r()
        if fator_r is not None and fator_r >= FATOR_R_LIMIAR:
            motivo = (
                f"Fator R = {fator_r:.4f} ≥ {FATOR_R_LIMIAR} → migra Anexo V → Anexo III. "
                f"Folha R$ {self.fornecedora.folha_salarios_12m:,.2f} / RBT12 R$ {self.calcular_rbt12():,.2f}."
            )
            self._registrar_passo(
                id="DECISAO_ANEXO",
                titulo="Anexo Simples Nacional: III (Fator R ≥ 0,28)",
                base=f"Folha R$ {self.fornecedora.folha_salarios_12m:,.2f}",
                deducoes="N/A",
                aliquota=f"Fator R {fator_r:.4f}",
                valor="Anexo III",
                lei="LC 123/2006, Art. 18, § 24",
                detalhe=motivo,
                vigente_desde="01/01/2018 (LC 155/2016, alterou LC 123/2006)",
            )
            return "III"

        cnae = self.fornecedora.cnae_principal
        anexo, fonte_cnae = determinar_anexo_por_cnae_com_fonte(cnae)
        detalhe_fonte = {
            "EXPLICITO": f"CNAE {cnae} mapeado para Anexo {anexo} (correspondência exata na tabela CGSN).",
            "PREFIXO": f"CNAE {cnae} mapeado por prefixo '{cnae[:2]}' para Anexo {anexo}. Verifique se a atividade confere.",
            "FALLBACK": (
                f"CNAE {cnae} não encontrado na tabela — Anexo III assumido como fallback seguro. "
                f"ERR-005: mapeamento CNAE incompleto. Confirme o Anexo correto com o contador."
            ),
        }
        self._registrar_passo(
            id="DECISAO_ANEXO",
            titulo=f"Anexo Simples Nacional: {anexo} (por CNAE {cnae} — fonte: {fonte_cnae})",
            base=f"CNAE {cnae}",
            deducoes="N/A",
            aliquota="N/A",
            valor=anexo,
            lei="LC 123/2006, Art. 18, §§ 1º e 24 | Res. CGSN 140/2018",
            detalhe=detalhe_fonte[fonte_cnae],
            vigente_desde="01/01/2018 (Res. CGSN 140/2018)",
        )
        # Guardar fonte para uso em alertas
        self._cnae_fonte = fonte_cnae
        return anexo

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
            detalhe="Fórmula: ((RBT12 * Aliq_Nominal) - PD) / RBT12"
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
        if self.operacao.rpa_mensal is not None:
            base = self.operacao.rpa_mensal
            base_motivo = f"RPA mensal real R$ {base:,.2f} (informado pelo operador)"
            base_lei = "LC 123/2006, Art. 18, § 1º — base de cálculo mensal real"
        else:
            base = rbt12 / Decimal("12")
            base_motivo = f"RBT12/12 = R$ {base:,.2f} (RPA não informado — aproximação mensal)"
            base_lei = "LC 123/2006, Art. 18, § 1º — estimativa por RBT12 médio (ERR-007: delta aceito < 0,3%)"

        self._registrar_passo(
            id="BASE_CALCULO_DAS",
            titulo="Base de Cálculo do DAS Mensal",
            base=f"RBT12 R$ {rbt12:,.2f}",
            deducoes="N/A",
            aliquota="N/A",
            valor=f"R$ {base:,.2f}",
            lei=base_lei,
            detalhe=base_motivo,
            vigente_desde="01/07/2007 (LC 123/2006)",
        )
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

    def _fator_reducao_cbs_ibs(self) -> Decimal:
        """
        ERR-016: Fator multiplicador conforme nível de redução CBS/IBS.
        LC 214/2025:
          - INTEGRAL   → 1.00 (sem redução)
          - REDUCAO_30 → 0.70 (Art. 262 — profissionais liberais)
          - REDUCAO_60 → 0.40 (Art. 258 — saúde, educação, cesta básica ampliada)
          - ISENTO     → 0.00 (Art. 264 — cesta básica nacional)
        """
        _FATORES: Dict[str, Decimal] = {
            "INTEGRAL":    Decimal("1.00"),
            "REDUCAO_30":  Decimal("0.70"),
            "REDUCAO_60":  Decimal("0.40"),
            "ISENTO":      Decimal("0.00"),
        }
        nivel = self.operacao.reducao_cbs_ibs
        fator = _FATORES[nivel]
        if nivel != "INTEGRAL":
            self._registrar_passo(
                id="REDUCAO_CBS_IBS",
                titulo=f"Redução CBS/IBS — {nivel}",
                base="Alíquotas CBS/IBS do período",
                deducoes="N/A",
                aliquota=f"Fator {fator}",
                valor=f"Alíquotas multiplicadas por {fator}",
                lei="LC 214/2025, Arts. 258, 262, 264",
            )
        return fator

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

    def _fracao_iva_no_das(self, anexo: str, faixa: int, ano: int) -> Decimal:
        """
        Retorna a fração (0-1) de CBS+IBS que estará embutida no DAS do Simples
        Nacional no ano informado, conforme LC 214/2025 Art. 47 §II.

        LÓGICA DA TRANSIÇÃO — por ano:

          2026: 0 (Art. 348, III, "c" — optantes do Simples estão DISPENSADOS
                de destacar CBS/IBS no período-teste; logo, cliente B2B não
                recebe crédito).

          2027-2028: fração(PIS + COFINS) do DAS — a CBS substitui INTEGRALMENTE
                PIS e COFINS a partir de 2027 (Art. 344 + 353). ICMS e ISS
                continuam ativos no DAS do Simples, mas não viram IBS ainda.

          2029-2032: fração(PIS + COFINS) + fração(ICMS + ISS) × fase_in, onde
                fase_in = 10% em 2029, 20% em 2030, 30% em 2031, 40% em 2032.
                Arts. 356-360 — redução escalonada de ICMS/ISS com IBS crescendo
                proporcionalmente.

          2033+: fração(PIS + COFINS) + fração(ICMS + ISS) integral — IBS
                substituiu completamente ICMS e ISS. Sistema IVA dual pleno.

        EXEMPLO — Anexo III Faixa 5 (R$ 1,8M < RBT12 ≤ R$ 3,6M):
          PIS = 2,96% do DAS
          COFINS = 13,64% do DAS
          CBS 2027 = 16,60% do DAS
          ISS = 32,50% do DAS
          IBS 2033 = 32,50% do DAS
          Total 2033 (CBS + IBS) = 49,10% do DAS

        NOTA: esta é a interpretação técnica do Art. 47 §II pré-regulamentação
        definitiva do CGSN. Caso o Comitê Gestor publique resolução que altere
        a metodologia de cálculo (ex: fator fixo ao invés de proporcional), esta
        função deve ser revisitada. Acompanhar DOU + Receita Federal.

        Returns:
            Decimal entre 0 e ~0.60, arredondado a 4 casas.
        """
        if ano <= 2026:
            return Decimal("0.0000")

        partilha = DISTRIBUICAO_DAS.get(anexo, {}).get(faixa, {})
        if not partilha:
            return Decimal("0.0000")

        # CBS substitui PIS + COFINS integralmente a partir de 2027
        fracao_pis = partilha.get("PIS", Decimal("0"))
        fracao_cofins = partilha.get("COFINS", Decimal("0"))
        fracao_cbs = fracao_pis + fracao_cofins

        # IBS substitui ICMS + ISS gradualmente (2029-2032), pleno em 2033
        fracao_icms = partilha.get("ICMS", Decimal("0"))
        fracao_iss = partilha.get("ISS", Decimal("0"))
        fracao_icms_iss_total = fracao_icms + fracao_iss

        if ano <= 2028:
            fracao_ibs = Decimal("0")
        elif ano >= 2033:
            fracao_ibs = fracao_icms_iss_total
        else:
            # Fase-in 2029-2032: 10%, 20%, 30%, 40%
            # 2029 → (2029-2028)×10% = 10%
            # 2032 → (2032-2028)×10% = 40%
            fator_fase_in = Decimal(ano - 2028) * Decimal("0.10")
            fracao_ibs = fracao_icms_iss_total * fator_fase_in

        total = fracao_cbs + fracao_ibs
        return total.quantize(Decimal("0.0001"), ROUND_HALF_UP)

    def calcular_credito_simples_para_b2b(self) -> Decimal:
        """
        Crédito IBS+CBS que o comprador B2B pode apropriar quando fornecedor
        está no Simples Nacional (SEM exercício da opção pelo regime regular).

        BASE LEGAL — LC 214/2025, Art. 47, §§ I e II:
          (I)  "Não é permitida a apropriação de créditos de IBS e CBS pelo
               optante do Simples Nacional"
          (II) "É permitida ao contribuinte sujeito ao regime regular de IBS
               e CBS a apropriação de créditos de IBS e CBS correspondentes
               aos valores destes tributos pagos nas aquisições de optantes
               pelo Simples Nacional, EM MONTANTE EQUIVALENTE AO DEVIDO POR
               MEIO DESTE REGIME"

        REGRA DE 2026 — LC 214/2025, Art. 348, III, "c":
          Em 2026, os optantes do Simples Nacional NÃO aplicam as alíquotas
          de transição — não destacam CBS/IBS nas operações, logo NÃO geram
          crédito para clientes B2B neste ano. Retorna R$ 0.

        REGRA DE 2027+ (CORREÇÃO ART. 47 §II):
          O crédito é CALCULADO como:
            credito = DAS_mensal × fração_CBS_IBS_no_DAS(anexo, faixa, ano) × fator_reducao

          A fração vem de `_fracao_iva_no_das()` que consulta a tabela
          DISTRIBUICAO_DAS real do Simples Nacional. NÃO é `valor_operacao ×
          alíquota cheia` — essa era a aproximação errada anterior que
          super-estimava o crédito em 3-5×.

        EXEMPLO — Moreira (Anexo III Faixa 5, RPA R$ 251.303,53, DAS R$ 43.913,87):
          2026: R$ 0,00 (dispensado)
          2027: R$ 43.913,87 × 16,60% (PIS+COFINS) = R$ 7.289,70
          2029: R$ 43.913,87 × (16,60% + 32,50%×10%) = R$ 8.717,00
          2033: R$ 43.913,87 × 49,10% (CBS+IBS pleno) = R$ 21.561,71

        ERR-016: Aplica fator de redução conforme reducao_cbs_ibs
        (LC 214/2025, Arts. 258, 262, 264 — setores reduzidos/isentos).
        """
        ano = self.operacao.data_emissao.year

        # 2026: dispensa de destaque — crédito = 0 (Art. 348, III, "c")
        if ano <= 2026:
            return Decimal("0.00")

        # 2027+: fração real CBS+IBS no DAS por anexo × faixa
        anexo = self.determinar_anexo()
        rbt12 = self.calcular_rbt12()
        faixa = obter_faixa_numero(rbt12, anexo)
        if faixa == 0:
            return Decimal("0.00")

        das_mensal = self.calcular_das_mensal()
        fracao = self._fracao_iva_no_das(anexo, faixa, ano)
        fator_reducao = self._fator_reducao_cbs_ibs()

        credito = (das_mensal * fracao * fator_reducao).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        # Trilha de auditoria — MAX_FISCAL_02 exige citação legal em cada passo
        self._registrar_passo(
            id="CREDITO_B2B_ART_47",
            titulo=f"Crédito B2B cliente ({ano}) — LC 214/2025 Art. 47 §II",
            base=f"DAS mensal R$ {das_mensal:,.2f}",
            deducoes=(
                f"Fração CBS+IBS no DAS Anexo {anexo} Faixa {faixa}: "
                f"{float(fracao)*100:.2f}%"
            ),
            aliquota=f"Fator redução CBS/IBS: {fator_reducao}",
            valor=f"R$ {credito:,.2f}",
            lei=(
                "LC 214/2025 Art. 47 §II (creditamento proporcional ao devido) | "
                "Arts. 344 e 353 (CBS substitui PIS/COFINS em 2027) | "
                "Arts. 356-360 (fase-in IBS 2029-2032)"
            ),
            detalhe=(
                f"Anexo {anexo} Faixa {faixa}: PIS + COFINS = CBS em 2027+. "
                f"ICMS + ISS → IBS gradualmente 2029-2032 (10%/ano), pleno em 2033. "
                f"Interpretação pré-regulamentação do CGSN."
            ),
        )
        return credito

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

        # Frações IBS/CBS que já estão dentro do DAS (serão subtraídas no Opt-Out)
        ibs_no_das = self._calcular_fracao_componente("IBS")
        cbs_no_das = self._calcular_fracao_componente("CBS")

        # IVA recolhido separadamente (por operação)
        # ERR-016: aplica fator de redução CBS/IBS (Arts. 258-264 LC 214/2025)
        fator_reducao = self._fator_reducao_cbs_ibs()
        iva_por_fora = (
            self.operacao.valor_operacao
            * (aliquotas_iva["CBS"] + aliquotas_iva["IBS"])
            * fator_reducao
        ).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # Custo DAS completo (proporcional à operação) antes de tirar o IVA
        custo_das_por_operacao_completo = (self.operacao.valor_operacao * aliquota_efetiva).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        # Subtrai a fração IBS/CBS que já estava dentro do DAS (evita dupla contagem)
        fracao_iva_no_das = (ibs_no_das + cbs_no_das)
        custo_das_sem_iva = (custo_das_por_operacao_completo - fracao_iva_no_das).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        # Custo total = DAS (sem IVA) + IVA por fora — sem dupla contagem
        custo_total = (custo_das_sem_iva + iva_por_fora).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        self._registrar_passo(
            id="OPT_OUT_CALCULO",
            titulo="Cenário Opt-Out — DAS sem IVA + IVA por fora",
            base=f"DAS completo R$ {custo_das_por_operacao_completo:,.2f}",
            deducoes=f"IBS/CBS no DAS R$ {fracao_iva_no_das:,.2f}",
            aliquota=f"IVA por fora {(aliquotas_iva['CBS']+aliquotas_iva['IBS'])*100:.2f}%",
            valor=f"R$ {custo_total:,.2f}",
            lei="LC 214/2025 (dispositivo de opt-out — aguardar regulamentação)",
            detalhe=(
                f"DAS sem IVA R$ {custo_das_sem_iva:,.2f} + IVA por fora R$ {iva_por_fora:,.2f} = "
                f"Total R$ {custo_total:,.2f}. Sem dupla contagem de IBS/CBS."
            ),
        )

        return {
            "cenario": "OPT_OUT",
            "descricao": "Empresa recolhe IBS/CBS separadamente, mantém Simples para demais tributos",
            "custo_das_por_operacao": str(custo_das_sem_iva),
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
            # ERR-016: aplica fator de redução CBS/IBS (Arts. 258-264)
            fator_reducao = self._fator_reducao_cbs_ibs()
            taxa_retencao = (aliquotas_ano["CBS"] + aliquotas_ano["IBS"]) * fator_reducao
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

    def _gerar_recomendacao_opt_out(self) -> Dict[str, str]:
        """
        Gera recomendação inteligente de Opt-Out cruzando:
          - percentual_b2b (peso comercial: quantos clientes perderiam crédito)
          - disparidade_anual / RBT12 (peso financeiro: custo relativo de sair)
          - tipo do comprador (gate: B2C puro nunca recomenda Opt-Out)

        Retorna dict com 4 chaves:
          - codigo: identificador da matriz de decisão (ex: "OPT_OUT_FORTE")
          - titulo: frase curta para header (ex: "OPT-OUT FORTEMENTE RECOMENDADO")
          - justificativa: parágrafo explicando o porquê em linguagem de empresário
          - amparo_legal: LC 214/2025 Arts. 41-44 + CF Art. 146, III, "d"

        MATRIZ DE DECISÃO (LC 214/2025, Arts. 41-44 + Resolução CGSN 183/2025):
          B2B ≥ 70% E disparidade/RBT12 ≤ 5%  → OPT_OUT_FORTE
          B2B ≥ 50% E disparidade/RBT12 ≤ 10% → OPT_OUT_VANTAJOSO
          B2B < 30%                            → MANTER_SIMPLES
          Demais casos                         → ZONA_CINZA (análise individual)

        NOTA: a disparidade real deve ser próxima de zero quando IVA é repassado
        no preço de venda. Quando positiva, indica que o Opt-Out custa mais caixa
        para a empresa — só vale a pena se o ganho de retenção B2B compensa.
        """
        percentual_b2b = self.compradora.percentual_b2b or Decimal("0")
        # Normaliza percentual_b2b quando tipo é B2B_CONTRIBUINTE puro (100%)
        # ou B2C puro (0%) — independente do default do Pydantic
        if self.compradora.tipo == "B2B_CONTRIBUINTE":
            percentual_b2b = Decimal("100")
        elif self.compradora.tipo == "B2C_CONSUMIDOR_FINAL":
            percentual_b2b = Decimal("0")

        disparidade = self.calcular_disparidade_anual()
        rbt12 = self.calcular_rbt12() or Decimal("1")  # evita divisão por zero
        # Razão disparidade/RBT12 em percentual (absoluto — ganhos e perdas)
        razao_disparidade = (abs(disparidade) / rbt12 * Decimal("100")).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        # Threshold absoluto: custo extra acima disso exige aviso explícito
        # de "só compensa se houver repasse ou risco real de perda de cliente"
        # Default: R$ 6.000/ano = R$ 500/mês (impacto sensível em fluxo de caixa)
        THRESHOLD_CUSTO_ABSOLUTO_ANUAL = Decimal("6000.00")
        custo_alto_absoluto = abs(disparidade) > THRESHOLD_CUSTO_ABSOLUTO_ANUAL

        razao_pct_str = f"{razao_disparidade:.2f}".replace(".", ",")
        b2b_str = f"{percentual_b2b:.0f}"

        # ── Matriz de decisão ────────────────────────────────────────────────
        # Lógica refinada: além de % B2B e razão disparidade/RBT12, também
        # considera o VALOR ABSOLUTO do custo extra (que sai do caixa) vs
        # benefício (crédito vai pro CLIENTE B2B, não pra empresa).
        if percentual_b2b >= Decimal("70") and razao_disparidade <= Decimal("5"):
            if custo_alto_absoluto:
                codigo = "OPT_OUT_CONDICIONAL"
                titulo = "OPT-OUT CONDICIONAL — só com repasse de preço"
                justificativa = (
                    f"Você tem {b2b_str}% de clientes B2B (empresas que precisam de "
                    f"crédito de CBS/IBS para abater dos próprios impostos). O Opt-Out "
                    f"traria competitividade comercial, MAS o custo extra é "
                    f"{_fmt_brl(disparidade)}/ano ({razao_pct_str}% da receita) — "
                    f"esse valor sai DIRETO do seu caixa enquanto o crédito vai para o "
                    f"CLIENTE, não para você. Só compensa se: (1) seus clientes B2B "
                    f"aceitarem pagar mais para ter o crédito cheio, OU (2) houver risco "
                    f"real de perderem para concorrentes do regime normal. Avalie com "
                    f"seu contador antes da janela semestral."
                )
            else:
                codigo = "OPT_OUT_FORTE"
                titulo = "OPT-OUT FORTEMENTE RECOMENDADO"
                justificativa = (
                    f"Você tem {b2b_str}% de clientes B2B (empresas que precisam de "
                    f"crédito de CBS/IBS para abater dos próprios impostos). No Simples "
                    f"Puro, eles recebem apenas 1% de crédito — risco real de migrarem "
                    f"para concorrentes no regime normal. O custo anual extra do Opt-Out "
                    f"é {_fmt_brl(disparidade)} ({razao_pct_str}% da receita), valor baixo "
                    f"e normalmente neutralizado pelo repasse no preço. O ganho de "
                    f"competitividade e retenção de clientes compensa."
                )
        elif percentual_b2b >= Decimal("50") and razao_disparidade <= Decimal("10"):
            codigo = "OPT_OUT_VANTAJOSO"
            titulo = "OPT-OUT VANTAJOSO — avaliar caixa"
            ressalva = (
                " IMPORTANTE: o crédito gerado vai para os clientes B2B, não para você. "
                "Só compensa se houver poder de repasse no preço ou risco de perda de cliente."
                if custo_alto_absoluto else ""
            )
            justificativa = (
                f"Você tem {b2b_str}% de clientes B2B. Metade ou mais do seu faturamento "
                f"vem de empresas que podem exigir crédito IVA. O custo anual extra do "
                f"Opt-Out é {_fmt_brl(disparidade)} ({razao_pct_str}% da receita). Avalie "
                f"se o repasse no preço é viável no seu mercado e se há fluxo de caixa "
                f"para absorver o aumento durante a transição.{ressalva}"
            )
        elif percentual_b2b < Decimal("30"):
            codigo = "MANTER_SIMPLES"
            titulo = "MANTENHA SIMPLES PURO"
            justificativa = (
                f"Você tem apenas {b2b_str}% de clientes B2B — a maioria da sua receita "
                f"vem de consumidores finais (pessoa física), que NÃO usam crédito de "
                f"CBS/IBS. Sair do Simples Puro para o Opt-Out aumentaria a complexidade "
                f"operacional (EFD-Reinf, EFD-Contribuições) e o custo anual em "
                f"{_fmt_brl(disparidade)} sem trazer benefício comercial. Mantenha o "
                f"regime atual e reavalie apenas se o perfil de clientes mudar."
            )
        else:
            codigo = "ZONA_CINZA"
            titulo = "ZONA CINZA — análise individual necessária"
            justificativa = (
                f"Seu caso está numa faixa intermediária: {b2b_str}% de clientes B2B com "
                f"custo anual de Opt-Out de {_fmt_brl(disparidade)} ({razao_pct_str}% da "
                f"receita). A decisão depende de fatores qualitativos (concentração de "
                f"clientes, poder de repasse de preço, capacidade de absorver obrigações "
                f"acessórias adicionais). Recomendamos análise individual com seu contador "
                f"antes das janelas semestrais (abril e setembro)."
            )

        return {
            "codigo": codigo,
            "titulo": titulo,
            "justificativa": justificativa,
            "amparo_legal": (
                "LC 214/2025, Arts. 41-44 (dispositivo de Opt-Out) | "
                "CF Art. 146, III, 'd' (regime diferenciado Simples Nacional) | "
                "Resolução CGSN 183/2025 (janelas semestrais abr/set)"
            ),
        }

    def _montar_cenarios_com_recomendacao(self) -> Dict[str, Any]:
        """
        Monta o bloco 'cenarios' do diagnóstico com recomendação inteligente.

        Retorna dict com:
          - simples_puro: cenário A
          - opt_out: cenário B
          - disparidade_anual_estimada: diferença financeira anual (str)
          - percentual_b2b: float 0-100 — perfil real de clientes (usado para
            ponderar o crédito B2B na tabela de exibição)
          - recomendacao: frase curta (compat retrô — usada por testes antigos)
          - recomendacao_inteligente: dict {codigo, titulo, justificativa, amparo_legal}
        """
        rec = self._gerar_recomendacao_opt_out()

        # Percentual real de clientes B2B (mesmo cálculo do _gerar_recomendacao)
        pct_b2b = self.compradora.percentual_b2b or Decimal("0")
        if self.compradora.tipo == "B2B_CONTRIBUINTE":
            pct_b2b = Decimal("100")
        elif self.compradora.tipo == "B2C_CONSUMIDOR_FINAL":
            pct_b2b = Decimal("0")

        return {
            "simples_puro": self.cenario_simples_puro(),
            "opt_out": self.cenario_opt_out(),
            "disparidade_anual_estimada": str(self.calcular_disparidade_anual()),
            "percentual_b2b": str(pct_b2b),
            # Compatibilidade com testes antigos (string curta)
            "recomendacao": (
                "OPT_OUT recomendado para reter cliente B2B."
                if rec["codigo"] in ("OPT_OUT_FORTE", "OPT_OUT_VANTAJOSO")
                else (
                    "SIMPLES_PURO adequado — perfil majoritariamente B2C."
                    if rec["codigo"] == "MANTER_SIMPLES"
                    else "Análise individual recomendada — zona cinza."
                )
            ),
            # Recomendação inteligente (novo contrato — Bloco A Frente 3.2)
            "recomendacao_inteligente": rec,
        }

    # ── FASE 5: DIAGNÓSTICO + ALERTAS + LGPD ─────────────────────────────────

    def _calcular_difal_diagnostico(self) -> Dict[str, Any]:
        """
        Calcula DIFAL interestadual se UF origem != UF destino.
        EC 87/2015 | LC 190/2022 | LC 87/1996, Art. 13.

        Retorna dict com Decimals convertidos para str (JSON-safe).
        Se operação interna, retorna dict com aplicavel=False.
        """
        resultado = calcular_difal(
            valor_operacao=self.operacao.valor_operacao,
            uf_origem=self.fornecedora.uf_origem,
            uf_destino=self.compradora.uf_destino,
            tipo_destinatario=self.compradora.tipo,
            produto_importado=self.operacao.produto_importado,
            trilha=self.trilha_auditoria,
        )
        # Decimal → str para serialização JSON
        return {
            k: (str(v) if isinstance(v, Decimal) else v)
            for k, v in resultado.items()
        }

    def _gerar_alertas(self) -> List[Dict[str, str]]:
        """
        Sistema de alertas baseado em gatilhos matemáticos.
        Cada alerta tem nível: CRITICO, ALTO, MEDIO, INFO.
        """
        alertas = []
        rbt12 = self.calcular_rbt12()

        # CRÍTICO: Desenquadramento imediato (RBT12 > 120% do teto = R$ 5.760.000)
        # LC 123/2006, Art. 3º, §§ 9º e 10 — exclusão retroativa ao mês do excesso
        teto_excesso_imediato = TETO_SIMPLES_NACIONAL * Decimal("1.20")  # R$ 5.760.000
        if rbt12 > teto_excesso_imediato:
            alertas.append({
                "nivel": "CRITICO",
                "codigo": "DESENQUADRAMENTO_IMEDIATO",
                "mensagem": (
                    f"RBT12 R$ {rbt12:,.2f} ultrapassou R$ {teto_excesso_imediato:,.2f} (120% do teto). "
                    f"DESENQUADRAMENTO IMEDIATO do Simples Nacional — efeitos RETROATIVOS ao mês do excesso. "
                    f"LC 123/2006, Art. 3º, §§ 9º e 10."
                ),
            })
        # CRÍTICO: Desenquadramento no exercício seguinte (RBT12 > R$ 4.800.000)
        # LC 123/2006, Art. 3º, II — exclusão a partir de janeiro do ano seguinte
        elif rbt12 > TETO_SIMPLES_NACIONAL:
            alertas.append({
                "nivel": "CRITICO",
                "codigo": "DESENQUADRAMENTO_PROXIMO_ANO",
                "mensagem": (
                    f"RBT12 R$ {rbt12:,.2f} excedeu o teto de R$ {TETO_SIMPLES_NACIONAL:,.2f}. "
                    f"Empresa será excluída do Simples Nacional a partir de janeiro/{self.operacao.data_emissao.year + 1}. "
                    f"LC 123/2006, Art. 3º, II."
                ),
            })
        # ALTO: RBT12 > 90% do teto (alerta preventivo)
        elif rbt12 > ALERTA_90_PERCENT_TETO:
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

        # ─────────────────────────────────────────────────────────────────────────────
        # ALERTAS FASE 5 (STRESS TEST) — R14 a R17
        # ─────────────────────────────────────────────────────────────────────────────

        # C1 (R14) Fantasma do Ano Novo: Emissão X Liquidação em mudança de regime
        if self.operacao.data_liquidacao and self.operacao.data_liquidacao.year > self.operacao.data_emissao.year:
            # Regra: só dispara se cruzar a virada (ex: emissão 2026, pagto 2027 que inicia split payment dinâmico)
            if self.operacao.data_emissao.year < ANO_INICIO_SPLIT_PAYMENT and self.operacao.data_liquidacao.year >= ANO_INICIO_SPLIT_PAYMENT:
                alertas.append({
                    "nivel": "ALTO",
                    "codigo": "CONCILIACAO_RISCO",
                    "mensagem": (
                        f"Fantasma do Ano Novo: Emissão em {self.operacao.data_emissao.year} "
                        f"e liquidação em {self.operacao.data_liquidacao.year}. "
                        "Cuidado: contabilidade gera imposto na emissão, mas retenção do Split Payment atua na liquidação."
                    ),
                })

        # C2 (R15) Explosão do Sublimite
        # Se RBT12 estava seguro, mas o delta dessa operação específica estourou o sublimite
        if rbt12 <= SUBLIMITE_ICMS_ISS and (rbt12 + self.operacao.valor_operacao) > SUBLIMITE_ICMS_ISS:
            alertas.append({
                "nivel": "ALTO",
                "codigo": "SUBLIMITE_CRITICO",
                "mensagem": (
                    f"A operação atual (R$ {self.operacao.valor_operacao:,.2f}) "
                    f"cruzou o Sublimite Estadual (R$ {SUBLIMITE_ICMS_ISS:,.2f}). "
                    "ICMS e ISS serão ejetados do DAS no próximo mês!"
                ),
            })

        # C3 (R16) Salada de Frutas (Timeouts)
        if self.operacao.qtd_itens > 50:
            alertas.append({
                "nivel": "MEDIO",
                "codigo": "RISCO_TIMEOUT_API",
                "mensagem": (
                    f"Carga extrema: NF com {self.operacao.qtd_itens} itens. "
                    "Risco de instabilidade no CGIBS. Se ocorrer timeout de API, "
                    "o Split Payment pode aplicar retenção punitiva máxima."
                ),
            })

        # C4 (R17) Estorno do Medo
        if self.operacao.estorno_realizado:
            alertas.append({
                "nivel": "ALTO",
                "codigo": "CAPITAL_GIRO_COMPROMETIDO",
                "mensagem": (
                    "Estorno após Split Payment: O imposto já foi retido no PIX/Cartão. "
                    "Com a devolução, esse saldo virará crédito tributário de difícil "
                    "recuperação, e não dinheiro em conta."
                ),
            })

        # MEDIO: CNAE mapeado por fallback (ERR-005)
        cnae_fonte = getattr(self, "_cnae_fonte", None)
        if cnae_fonte == "FALLBACK":
            alertas.append({
                "nivel": "MEDIO",
                "codigo": "CNAE_FALLBACK_ERR005",
                "mensagem": (
                    f"CNAE {self.fornecedora.cnae_principal} não encontrado na tabela de mapeamento. "
                    f"Anexo III foi assumido como fallback seguro. "
                    f"Confirme o Anexo correto com o contador responsável antes de tomar decisões."
                ),
            })
        elif cnae_fonte == "PREFIXO":
            alertas.append({
                "nivel": "INFO",
                "codigo": "CNAE_PREFIXO",
                "mensagem": (
                    f"CNAE {self.fornecedora.cnae_principal} mapeado por prefixo (grupo '{self.fornecedora.cnae_principal[:2]}'). "
                    f"Verifique se o Anexo corresponde à atividade principal da empresa."
                ),
            })

        return alertas

    def _diagnostico_lucro_real(self) -> Dict[str, Any]:
        """Diagnóstico para regime Lucro Real via LucroRealEngine."""
        if self._engine_regime is None:
            raise RuntimeError(
                "LucroRealEngine não instanciado. Verifique se regime='REAL' "
                "foi configurado corretamente em EmpresaFornecedora."
            )
        engine = self._engine_regime

        receita_mensal = self.operacao.rpa_mensal or (self.fornecedora.faturamento_12m / 12)
        if receita_mensal <= Decimal("0"):
            raise ValueError(
                "Lucro Real: receita mensal é zero. Informe faturamento_12m > 0 "
                "ou rpa_mensal > 0 para calcular."
            )
        lucro = self.operacao.lucro_real_mensal or receita_mensal
        creditos = self.operacao.creditos_pis_cofins

        # CNAE fonte para alertas (Lucro Real também pode ter CNAE em fallback)
        _, cnae_fonte = determinar_anexo_por_cnae_com_fonte(self.fornecedora.cnae_principal)
        self._cnae_fonte = cnae_fonte

        resultado = engine.calcular_carga_total_mensal(
            receita_mensal=receita_mensal,
            lucro_real_mensal=lucro,
            creditos_pis_cofins=creditos,
        )

        # Registrar na trilha se usou proxy
        if self.operacao.lucro_real_mensal is None:
            self.trilha_auditoria.append({
                "tipo": "ALERTA_PROXY",
                "id": "PROXY_LUCRO_REAL",
                "titulo": "Lucro Real não informado — usando receita mensal como proxy",
                "amparo_legal": "RIR/2018, Art. 228",
                "detalhe": f"lucro_real_mensal=None → proxy={receita_mensal}. Resultado conservador.",
                "timestamp": str(datetime.now()),
            })

        aliquotas_iva = self.get_aliquotas_iva_por_ano()
        cronograma_iva_lista = [
            {"ano": ano, "cbs": str(vals["CBS"]), "ibs": str(vals["IBS"]),
             "total": str(vals["CBS"] + vals["IBS"])}
            for ano, vals in sorted(CRONOGRAMA_IVA.items())
        ]

        return {
            "versao_schema": "1.0",
            "versao_lei": "RIR_2018_LC214_2025",
            "data_analise": str(date.today()),
            "ano_operacao": self.operacao.data_emissao.year,
            "empresa": {
                # LGPD: cnpj/razao_social NUNCA aparecem no diagnostico
                # (separados via gerar_pdf(diagnostico, pii={...}))
                "regime": "REAL",
                "cnae": self.fornecedora.cnae_principal,
                "uf": self.fornecedora.uf_origem,
                "anexo_simples": None,
                "rbt12": str(self.fornecedora.faturamento_12m),
                "fator_r": None,
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
                "efetiva_das_total": str(resultado["aliquota_efetiva"]),
                "efetiva_percentual": f"{resultado['aliquota_efetiva'] * 100:.4f}%",
                "total_mensal": str(resultado["total_mensal"]),
                "cbs_vigente_ano": str(aliquotas_iva["CBS"]),
                "ibs_vigente_ano": str(aliquotas_iva["IBS"]),
            },
            "breakdown_regime": {k: str(v) for k, v in resultado["breakdown"].items()},
            "cenarios": {},
            "difal": self._calcular_difal_diagnostico(),
            "split_payment": self.calcular_split_payment_impacto(),
            "cronograma_iva": cronograma_iva_lista,
            "alertas": self._gerar_alertas(),
            "trilha_auditoria": self.trilha_auditoria,
            "meta": {
                "elaborado_por": "Escritório Conect — Motor Tributário v1.0",
                "legislacao_base": ["RIR/2018", "Lei 7.689/1988", "Lei 10.637/2002", "Lei 10.833/2003", "LC 214/2025"],
                "validar_com_profissional": True,
                "aviso": (
                    "Este diagnóstico é de natureza informativa. "
                    "Decisões tributárias devem ser validadas por contador responsável (CRC-SP)."
                ),
            },
        }

    def gerar_diagnostico(self) -> Dict[str, Any]:
        """
        Diagnóstico completo em JSON estruturado.
        Integra Fases 2, 3, 4 e 5 num único payload tipificado.
        Condiciona output por regime: Simples usa cálculos internos, Lucro Real usa engine.
        LGPD: purge() é chamado automaticamente após geração.
        """
        # Lucro Real: delega ao engine dedicado
        if self.fornecedora.regime == "REAL":
            diagnostico = self._diagnostico_lucro_real()
            self._diagnostico_gerado = True
            self.purge()
            return diagnostico

        rbt12 = self.calcular_rbt12()
        anexo = self.determinar_anexo()
        aliquota_efetiva = self.calcular_aliquota_efetiva()
        fator_r = self.calcular_fator_r()
        aliquotas_iva = self.get_aliquotas_iva_por_ano()

        # Serializa cronograma IVA 2026-2033 como lista ordenada
        cronograma_iva_lista = [
            {
                "ano": ano,
                "cbs": str(vals["CBS"]),
                "ibs": str(vals["IBS"]),
                "total": str(vals["CBS"] + vals["IBS"]),
            }
            for ano, vals in sorted(CRONOGRAMA_IVA.items())
        ]

        diagnostico = {
            "versao_schema": "1.0",
            "versao_lei": "LC123_2006_LC214_2025",
            "data_analise": str(date.today()),
            "ano_operacao": self.operacao.data_emissao.year,

            "empresa": {
                # LGPD: cnpj/razao_social NUNCA aparecem no diagnostico
                # (separados via gerar_pdf(diagnostico, pii={...}))
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

            "cenarios": self._montar_cenarios_com_recomendacao(),

            # DIFAL Interestadual (EC 87/2015 | LC 190/2022)
            "difal": self._calcular_difal_diagnostico(),

            "split_payment": self.calcular_split_payment_impacto(),

            # Cronograma de transição IVA 2026-2033 — LC 214/2025, Art. 348
            "cronograma_iva": cronograma_iva_lista,

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
