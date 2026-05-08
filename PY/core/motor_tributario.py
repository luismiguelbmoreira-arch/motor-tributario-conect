"""
motor_tributario.py — Motor de Regras Tributárias Transicionais (2026-2033)
LC 123/2006 | LC 214/2025 | EC 132/2023

Decimal obrigatório (float=PROIBIDO). ROUND_HALF_UP em todos os quantize().
Nenhum log com CNPJ, razão social ou dado pessoal.
"""

import gc
import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import cached_property
from typing import Any, Dict, List, Optional

from core.difal import calcular_difal
from core.formatadores import _fmt_brl
from core.regimes.base import BaseRegimeEngine
from core.regimes.imune import ImuneEngine
from core.regimes.lucro_presumido import LucroPresumidoEngine
from core.regimes.lucro_real import LucroRealEngine
from core.regimes.mei import MEIEngine
from core.regimes.simples_multi import SimplesMultiAtividadeEngine
from core.tabelas_simples import (
    ANO_INICIO_SPLIT_PAYMENT,
    CRONOGRAMA_IVA,
    DISTRIBUICAO_DAS,
    TABELAS_ANEXOS,
    TETO_SIMPLES_NACIONAL,
    determinar_anexo_por_cnae_com_fonte,
    obter_faixa_numero,
)
from schemas.motor import (
    FORMAS_PAGAMENTO_COM_PSP,
    Atividade,  # noqa: F401 — re-exported: tests + extrator_pdfs import from here
    EmpresaCompradora,
    EmpresaFornecedora,
    OperacaoFiscal,
)

logger = logging.getLogger("motor_conect.motor")


# Versão do motor — bump a cada mudança de regra fiscal (V-04: rastreabilidade
# retroativa de diagnósticos persistidos). Formato SemVer. Incrementar MINOR
# para mudança de cálculo, PATCH para ajustes de citação/formatação.
MOTOR_VERSAO = "1.3.0"  # 1.2.0 → 1.3.0: Fase 0a — gerar_diagnostico_consolidado (histórico 6 meses)


# Fator R: limiar para migração Anexo V → Anexo III (LC 123/2006, Art. 18, § 24)
FATOR_R_LIMIAR = Decimal("0.28")
FATOR_R_ZONA_RISCO_MIN = Decimal("0.27")
FATOR_R_ZONA_RISCO_MAX = Decimal("0.29")

# CNAEs elegíveis ao Fator R (Serviços Anexo III/V)
CNAES_FATOR_R = frozenset({
    "6201501", "6202300", "6209100",  # TI
    "6911701", "6920601",              # Advocacia, Contabilidade
    "7111100", "7112000",              # Arquitetura, Engenharia
    "7210000", "8599603",              # P&D, Treinamento
})


# ─────────────────────────────────────────────────────────────────────────────
# MOTOR PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

class MotorReformaTributaria:
    """
    Motor Transicional de Regras Tributárias (2026-2033).
    Embate técnico entre a Legislação Antiga e o Novo IVA Dual (LC 214/2025).
    """

    fornecedora: EmpresaFornecedora
    compradora: EmpresaCompradora
    operacao: OperacaoFiscal
    trilha_auditoria: List[Dict[str, Any]]
    _engine_regime: Optional[BaseRegimeEngine]
    _diagnostico_gerado: bool
    _cnae_fonte: Optional[str]

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
        self.trilha_auditoria: List[Dict[str, Any]] = []
        # V-06 fix: inicializa _cnae_fonte explicitamente. Antes só era set lazy
        # em anexo_principal/_diagnostico_lucro_real, gerando risco de AttributeError
        # caso _gerar_alertas fosse chamado em path alternativo. getattr(...) defensivo
        # removido em troca de contrato claro.
        self._cnae_fonte = None

        logger.info(
            "Motor iniciado | regime=%s | tipo_comprador=%s | ano=%s",
            self.fornecedora.regime,
            self.compradora.tipo,
            self.operacao.data_emissao.year,
        )

        self._validar_timeline()
        # ERR-037: regime do comprador capturado na trilha (crédito cruzado LC 214/2025 Art. 47 §2º na Fase 4+)
        self._registrar_regime_comprador()
        self._engine_regime: Optional[BaseRegimeEngine] = self._instanciar_engine()

    def _instanciar_engine(self) -> Optional[BaseRegimeEngine]:
        """Instancia o engine de regime correto, passando a trilha unificada."""
        regime = self.fornecedora.regime
        if regime == "PRESUMIDO":
            return LucroPresumidoEngine(self.fornecedora, self.trilha_auditoria)
        if regime == "MEI":
            return MEIEngine(self.fornecedora, self.trilha_auditoria)
        if regime == "REAL":
            return LucroRealEngine(self.fornecedora, self.trilha_auditoria)
        if regime == "IMUNE":
            return ImuneEngine(self.fornecedora, self.trilha_auditoria)
        if regime == "SIMPLES" and self.fornecedora.atividades:
            return SimplesMultiAtividadeEngine(self.fornecedora, self.trilha_auditoria)
        # Simples Nacional mono-atividade usa os métodos nativos do MotorReformaTributaria
        return None

    def obter_engine_regime(self) -> Optional[BaseRegimeEngine]:
        """Retorna o engine de regime instanciado."""
        return self._engine_regime

    def __enter__(self):  # pragma: no cover
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):  # pragma: no cover
        self.purge()

    def _validar_timeline(self) -> None:
        """Validação da data base da operação (MAX_FISCAL_03). LC 214/2025, Art. 360."""
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

    def _registrar_regime_comprador(self) -> None:
        """Registra regime do comprador na trilha (ERR-037). Crédito cruzado em Fase 4+."""
        regime_c = self.compradora.regime
        conhecido = regime_c != "NAO_INFORMADO"
        detalhe = (
            f"Regime do comprador capturado: '{regime_c}'. "
            "Aplicação em crédito cruzado (LC 214/2025 Art. 47 §2º) "
            "prevista para fase posterior — motor usa PIOR CASO (sem crédito) "
            "até lá."
        ) if conhecido else (
            "Regime do comprador NÃO INFORMADO — motor assume PIOR CASO "
            "(sem crédito cruzado, LC 214/2025 Art. 47 §2º). Informe o "
            "regime para habilitar a recomendação de crédito B2B na "
            "Fase 4."
        )
        self._registrar_passo(
            id="REGIME_COMPRADOR_CAPTURADO",
            titulo="Regime do Comprador (captura informativa)",
            base=f"Tipo: {self.compradora.tipo}",
            deducoes="N/A",
            aliquota="N/A",
            valor=regime_c,
            lei="LC 214/2025, Art. 47 §2º",
            detalhe=detalhe,
        )

        # MEI não é contribuinte de IBS/CBS (LC 123/2006 Art. 18-A §4º V) —
        # combinação B2B_CONTRIBUINTE + MEI é semanticamente incoerente.
        if self.compradora.tipo == "B2B_CONTRIBUINTE" and regime_c == "MEI":
            self.trilha_auditoria.append({
                "tipo": "ALERTA_MEI_NAO_CONTRIBUINTE",
                "id": "MEI_INCOMPATIVEL_B2B_CONTRIBUINTE",
                "titulo": "Comprador MEI marcado como B2B contribuinte — inconsistente",
                "amparo_legal": "LC 123/2006 Art. 18-A §4º V + LC 214/2025 Art. 47 §2º",
                "detalhe": (
                    "MEI não é contribuinte de IBS/CBS — não apropria crédito "
                    "nem emite crédito na cadeia. A combinação "
                    "tipo=B2B_CONTRIBUINTE + regime=MEI é incoerente. "
                    "Revise o cadastro do comprador — provavelmente B2C ou "
                    "regime diferente."
                ),
                "timestamp": str(datetime.now()),
            })

    def _registrar_passo(
        self, id: str, titulo: str, base: Any, deducoes: Any,
        aliquota: Any, valor: Any, lei: str, detalhe: str = "",
        vigente_desde: str = "",
    ) -> None:
        """Registro de Memória de Cálculo (MAX_FISCAL_01/02)."""
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

    @cached_property
    def rbt12(self) -> Decimal:
        """Receita Bruta Acumulada 12 meses. Proporcionaliza para < 12 meses. LC 123/2006, Art. 3º, §2º."""
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
                        f"RBT12 informada {_fmt_brl(rbt12)} ÷ {meses_atividade} meses × 12 = "
                        f"{_fmt_brl(rbt12_proporcional)} (proporcionalizada)."
                    ),
                )
                return rbt12_proporcional

        return rbt12

    @cached_property
    def fator_r(self) -> Optional[Decimal]:
        """Fator R = Folha 12m / RBT12. LC 123/2006, Art. 18, § 24. None se folha ausente ou CNAE inelegível."""
        if self.fornecedora.folha_salarios_12m is None:
            return None
        if self.fornecedora.cnae_principal not in CNAES_FATOR_R:
            return None
        rbt12_val = self.rbt12
        if rbt12_val == Decimal("0"):
            return Decimal("0")
        fator = self.fornecedora.folha_salarios_12m / rbt12_val
        return fator.quantize(Decimal("0.0001"), ROUND_HALF_UP)

    @cached_property
    def anexo_principal(self) -> str:
        """Determina Anexo Simples Nacional. Precedência: explícito > Fator R ≥ 0,28 > CNAE > fallback III. LC 123/2006, Art. 18."""
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

        f_r = self.fator_r
        if f_r is not None and f_r >= FATOR_R_LIMIAR:
            motivo = (
                f"Fator R = {f_r:.4f} ≥ {FATOR_R_LIMIAR} → migra Anexo V → Anexo III. "
                f"Folha {_fmt_brl(self.fornecedora.folha_salarios_12m)} / RBT12 {_fmt_brl(self.rbt12)}."
            )
            self._registrar_passo(
                id="DECISAO_ANEXO",
                titulo="Anexo Simples Nacional: III (Fator R ≥ 0,28)",
                base=_fmt_brl(self.fornecedora.folha_salarios_12m),
                deducoes="N/A",
                aliquota=f"Fator R {f_r:.4f}",
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
        """Alíquota nominal e parcela deduzir para RBT12 e Anexo. Raises ValueError se > teto."""
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

    def _obter_distribuicao_tributos(self, anexo: str) -> Dict[str, Decimal]:
        """Partilha de tributos para o Anexo/faixa atuais."""
        faixa_num = obter_faixa_numero(self.rbt12, anexo)
        return DISTRIBUICAO_DAS.get(anexo, {}).get(faixa_num, {})

    @property
    def perfil_b2b_ajustado(self) -> Decimal:
        """Percentual B2B normalizado: 100 se B2B_CONTRIBUINTE, 0 se B2C, ou percentual_b2b."""
        if self.compradora.tipo == "B2B_CONTRIBUINTE":
            return Decimal("100")
        if self.compradora.tipo == "B2C_CONSUMIDOR_FINAL":
            return Decimal("0")
        return self.compradora.percentual_b2b or Decimal("0")

    def calcular_ae_por_anexo(self, anexo: str) -> Decimal:
        """Alíquota efetiva para Anexo específico com base no RBT12 total. LC 123/2006, Art. 18, § 1º."""
        rbt12_val = self.rbt12
        if rbt12_val == Decimal("0"):
            return Decimal("0.00")

        aliq_nominal, parcela_deduzir = self._buscar_faixa(rbt12_val, anexo)

        # Fórmula SRF: ((RBT12 × Aliq_nominal) - Parcela_Deduzir) / RBT12
        aliquota_efetiva = ((rbt12_val * aliq_nominal) - parcela_deduzir) / rbt12_val
        return aliquota_efetiva.quantize(Decimal("0.000001"), ROUND_HALF_UP)

    @cached_property
    def aliquota_efetiva(self) -> Decimal:
        """Alíquota efetiva do DAS total. LC 123/2006, Art. 18, § 1º. 6 casas decimais."""
        rbt12_val = self.rbt12
        if rbt12_val == Decimal("0"):
            return Decimal("0.000000")

        anexo = self.anexo_principal
        aliq_nominal, parcela_deduzir = self._buscar_faixa(rbt12_val, anexo)

        # Fórmula SRF: ((RBT12 × Aliq_nominal) - Parcela_Deduzir) / RBT12
        ae = ((rbt12_val * aliq_nominal) - parcela_deduzir) / rbt12_val
        ae_final = ae.quantize(Decimal("0.000001"), ROUND_HALF_UP)

        self._registrar_passo(
            id="AE_SIMPLES",
            titulo=f"Alíquota Efetiva (Anexo {anexo})",
            base=_fmt_brl(rbt12_val),
            deducoes=f"PD {_fmt_brl(parcela_deduzir)}",
            aliquota=f"Nominal {(aliq_nominal*100):.2f}%",
            valor=f"{(ae_final*100):.4f}%",
            lei="LC 123/2006, Art. 18, § 1º",
            detalhe="Fórmula: ((RBT12 * Aliq_Nominal) - PD) / RBT12"
        )
        return ae_final

    @cached_property
    def das_mensal(self) -> Decimal:
        """DAS mensal sobre o RPA (ou RBT12/12). Suporta multi-atividade (ERR-008)."""
        rbt12_val = self.rbt12

        # CASO A: Multi-atividade (ERR-008)
        if self.fornecedora.atividades:
            das_total = Decimal("0")
            for item in self.fornecedora.atividades:
                ae = self.calcular_ae_por_anexo(item.anexo)
                dist = self._obter_distribuicao_tributos(item.anexo)

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

        # CASO B: Legado (única atividade ou RPA global)
        if self.operacao.rpa_mensal is not None:
            base = self.operacao.rpa_mensal
            base_motivo = f"RPA mensal real {_fmt_brl(base)} (informado pelo operador)"
            base_lei = "LC 123/2006, Art. 18, § 1º — base de cálculo mensal real"
        else:
            base = rbt12_val / Decimal("12")
            base_motivo = f"RBT12/12 = {_fmt_brl(base)} (RPA não informado — aproximação mensal)"
            base_lei = "LC 123/2006, Art. 18, § 1º — estimativa por RBT12 médio (ERR-007: delta aceito < 0,3%)"

        self._registrar_passo(
            id="BASE_CALCULO_DAS",
            titulo="Base de Cálculo do DAS Mensal",
            base=f"RBT12 {_fmt_brl(rbt12_val)}",
            deducoes="N/A",
            aliquota="N/A",
            valor=_fmt_brl(base),
            lei=base_lei,
            detalhe=base_motivo,
            vigente_desde="01/07/2007 (LC 123/2006)",
        )
        aliquota = self.aliquota_efetiva

        if self.fornecedora.receita_com_st_icms is None:
            return (base * aliquota).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # ERR-006: Segregação ICMS-ST parcial (legado)
        anexo = self.anexo_principal
        dist = self._obter_distribuicao_tributos(anexo)
        icms_pct = dist.get("ICMS", Decimal("0"))

        receita_sem_st = base - self.fornecedora.receita_com_st_icms
        das_sem_st = (receita_sem_st * aliquota).quantize(Decimal("0.01"), ROUND_HALF_UP)

        ae_sem_icms = (aliquota - aliquota * icms_pct).quantize(Decimal("0.000001"), ROUND_HALF_UP)
        das_com_st = (self.fornecedora.receita_com_st_icms * ae_sem_icms).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        total_das = (das_sem_st + das_com_st).quantize(Decimal("0.01"), ROUND_HALF_UP)

        self._registrar_passo(
            id="DAS_ST_SEGREGAÇÃO",
            titulo="Segregação de ICMS-ST no DAS",
            base=f"ST {_fmt_brl(self.fornecedora.receita_com_st_icms)} | s/ST {_fmt_brl(receita_sem_st)}",
            deducoes=f"ICMS {icms_pct*100:.2f}% na faixa",
            aliquota=f"AE s/ICMS {ae_sem_icms*100:.4f}%",
            valor=_fmt_brl(total_das),
            lei="LC 123/2006, Art. 13, § 1º, VII",
            detalhe="Parcela com ST reduz a alíquota efetiva pela fração correspondente ao ICMS."
        )

        return total_das

    def calcular_das_detalhado(self, rpa: Optional[Decimal] = None) -> Decimal:
        """DAS com arredondamento per-tributo. Suporta multi-atividade (ERR-008)."""
        # CASO A: Multi-atividade
        if self.fornecedora.atividades:
            total_detalhado = Decimal("0")
            for item in self.fornecedora.atividades:
                ae = self.calcular_ae_por_anexo(item.anexo)
                dist = self._obter_distribuicao_tributos(item.anexo)

                if not dist:
                    total_detalhado += (item.receita * ae).quantize(Decimal("0.01"), ROUND_HALF_UP)
                    continue

                for tributo, p_dist in dist.items():
                    if p_dist == Decimal("0"):
                        continue
                    if tributo == "ICMS" and item.icms_st:
                        continue
                    if tributo == "ISS" and item.iss_retido:
                        continue
                    componente = (item.receita * ae * p_dist).quantize(Decimal("0.01"), ROUND_HALF_UP)
                    total_detalhado += componente
            return total_detalhado

        # CASO B: Legado
        base = rpa if rpa is not None else (
            self.operacao.rpa_mensal if self.operacao.rpa_mensal is not None
            else (self.rbt12 / Decimal("12"))
        )
        aliquota = self.aliquota_efetiva
        anexo = self.anexo_principal
        dist = self._obter_distribuicao_tributos(anexo)

        if not dist:
            return (base * aliquota).quantize(Decimal("0.01"), ROUND_HALF_UP)

        das_total = Decimal("0")
        for tributo, percentual_dist in dist.items():
            if percentual_dist == Decimal("0"):
                continue
            # ERR-006: ST ICMS global (legado)
            if tributo == "ICMS" and self.fornecedora.receita_com_st_icms is not None:
                r_sem_st = base - self.fornecedora.receita_com_st_icms
                comp = (r_sem_st * aliquota * percentual_dist).quantize(Decimal("0.01"), ROUND_HALF_UP)
            else:
                comp = (base * aliquota * percentual_dist).quantize(Decimal("0.01"), ROUND_HALF_UP)
            das_total += comp

        return das_total

    def _distancia_proxima_faixa(self) -> Optional[Decimal]:
        """Quanto falta (R$) para a próxima faixa de RBT12."""
        rbt12_val = self.rbt12
        anexo = self.anexo_principal
        tabela = TABELAS_ANEXOS.get(anexo, [])
        for limite, _, _ in tabela:
            if rbt12_val <= limite:
                return (limite - rbt12_val).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return None

    def alertar_fator_r(self) -> Optional[str]:
        """Alerta zona de risco Fator R (0,27-0,29): pequena variação na folha muda o Anexo."""
        fator_r_val = self.fator_r
        if fator_r_val is not None and FATOR_R_ZONA_RISCO_MIN <= fator_r_val < FATOR_R_ZONA_RISCO_MAX:
            return (
                f"FATOR R = {fator_r_val:.4f} — ZONA DE RISCO (0,27-0,29). "
                f"Monitorar mensalmente. Pequena variação na folha pode mudar de "
                f"Anexo V ({fator_r_val:.0%} DAS) para Anexo III."
            )
        return None

    # ── FASE 3: IBS/CBS ───────────────────────────────────────────────────────

    def _fator_reducao_cbs_ibs(self) -> Decimal:
        """Fator de redução CBS/IBS: INTEGRAL=1.00, REDUCAO_30=0.70, REDUCAO_60=0.40, ISENTO=0.00. LC 214/2025, Arts. 258-264."""
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
        """Alíquotas CBS/IBS vigentes no ano da operação. LC 214/2025, Art. 360."""
        ano = self.operacao.data_emissao.year
        if ano in CRONOGRAMA_IVA:
            return CRONOGRAMA_IVA[ano]
        from core.tabelas_simples import ALIQUOTA_IVA_PLENA_ESTIMADA
        return {
            "CBS": ALIQUOTA_IVA_PLENA_ESTIMADA,
            "IBS": Decimal("0.177"),
        }

    def _calcular_fracao_componente(self, componente: str) -> Decimal:
        """Valor mensal (R$) do componente no DAS (ex: 'CBS', 'IBS', 'ICMS')."""
        anexo = self.anexo_principal
        rbt12_val = self.rbt12
        faixa_num = obter_faixa_numero(rbt12_val, anexo)
        if faixa_num == 0:
            return Decimal("0")
        distribuicao = DISTRIBUICAO_DAS.get(anexo, {}).get(faixa_num, {})
        percentual = distribuicao.get(componente, Decimal("0"))
        das_mensal = self.das_mensal
        return (das_mensal * percentual).quantize(Decimal("0.01"), ROUND_HALF_UP)

    @cached_property
    def fracao_ibs(self) -> Decimal:
        """IBS mensal dentro do DAS (período transitório)."""
        return self._calcular_fracao_componente("IBS")

    @cached_property
    def fracao_cbs(self) -> Decimal:
        """CBS mensal dentro do DAS (período transitório)."""
        return self._calcular_fracao_componente("CBS")

    def _fracao_iva_no_das(self, anexo: str, faixa: int, ano: int) -> Decimal:
        """
        Fração CBS+IBS embutida no DAS por ano. LC 214/2025, Art. 47 § 9º
        (crédito em valor equivalente ao DAS recolhido pelo fornecedor Simples).
        2026: 0 (dispensado — Art. 348 III "c").
        2027-2028: PIS+COFINS → CBS (cronograma de transição).
        2029-2032: CBS + IBS phase-in 10%/ano.
        2033+: CBS + IBS pleno.

        Nota ERR-057 (30/04/2026): citação anterior `Art. 47 §II + Arts. 344,
        353, 356-360` pra creditamento Simples era ERRADA — Escrivão validou
        que §II trata de "valor do crédito em geral" e que Arts. 344-360 são
        cronograma, não creditamento. Corrigido pra § 9º.
        """
        if ano <= 2026:
            return Decimal("0.0000")

        partilha = DISTRIBUICAO_DAS.get(anexo, {}).get(faixa, {})
        if not partilha:
            return Decimal("0.0000")

        fracao_pis = partilha.get("PIS", Decimal("0"))
        fracao_cofins = partilha.get("COFINS", Decimal("0"))
        fracao_cbs = fracao_pis + fracao_cofins

        fracao_icms = partilha.get("ICMS", Decimal("0"))
        fracao_iss = partilha.get("ISS", Decimal("0"))
        fracao_icms_iss_total = fracao_icms + fracao_iss

        if ano <= 2028:
            fracao_ibs = Decimal("0")
        elif ano >= 2033:
            fracao_ibs = fracao_icms_iss_total
        else:
            # Fase-in 2029-2032: 10%, 20%, 30%, 40%
            fator_fase_in = Decimal(ano - 2028) * Decimal("0.10")
            fracao_ibs = fracao_icms_iss_total * fator_fase_in

        total = fracao_cbs + fracao_ibs
        return total.quantize(Decimal("0.0001"), ROUND_HALF_UP)

    @cached_property
    def credito_b2b_simples(self) -> Decimal:
        """
        Crédito IBS+CBS apropriável pelo comprador B2B de fornecedor Simples Nacional.
        LC 214/2025, Art. 47 § 9º: credito = DAS_mensal × fração_CBS_IBS_no_DAS(anexo, faixa, ano).
        2026: R$0 (Art. 348 III "c"). 2027+: fração real do DAS por Anexo/Faixa.
        ERR-016: fator_reducao_cbs_ibs (Arts. 258, 262, 264).
        """
        ano = self.operacao.data_emissao.year

        # 2026: dispensa de destaque — crédito = 0 (Art. 348, III, "c")
        if ano <= 2026:
            return Decimal("0.00")

        # 2027+: fração real CBS+IBS no DAS por anexo × faixa
        anexo = self.anexo_principal
        rbt12_val = self.rbt12
        faixa = obter_faixa_numero(rbt12_val, anexo)
        if faixa == 0:
            return Decimal("0.00")

        das_mensal_val = self.das_mensal
        fracao = self._fracao_iva_no_das(anexo, faixa, ano)
        fator_reducao = self._fator_reducao_cbs_ibs()

        credito = (das_mensal_val * fracao * fator_reducao).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        self._registrar_passo(
            id="CREDITO_B2B_ART_47",
            titulo=f"Crédito B2B cliente ({ano}) — LC 214/2025 Art. 47 § 9º",
            base=f"DAS mensal {_fmt_brl(das_mensal_val)}",
            deducoes=(
                f"Fração CBS+IBS no DAS Anexo {anexo} Faixa {faixa}: "
                f"{(fracao*100):.2f}%"
            ),
            aliquota=f"Fator redução CBS/IBS: {fator_reducao}",
            valor=_fmt_brl(credito),
            lei=(
                "LC 214/2025 Art. 47 § 9º (crédito em valor equivalente ao DAS recolhido) | "
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

    # ── FASE 4: OPT-OUT ───────────────────────────────────────────────────────

    def cenario_simples_puro(self) -> Dict[str, Any]:
        """Cenário A: Empresa mantém Simples Nacional sem alteração."""
        ae_efetiva = self.aliquota_efetiva
        custo_total = (self.operacao.valor_operacao * ae_efetiva).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        credito_b2b = self.credito_b2b_simples
        percentual_credito = (credito_b2b / self.operacao.valor_operacao * 100).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        return {
            "cenario": "SIMPLES_PURO",
            "descricao": "Empresa mantém regime Simples Nacional sem alteração",
            "custo_das_por_operacao": str(custo_total),
            "aliquota_efetiva": str(ae_efetiva),
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
        """Cenário B: Empresa recolhe IBS/CBS separadamente (Opt-Out).

        ERR-046 fix (ATA Fase 1, commit pós-4caf82c):
        Fórmula antiga subtraía R$ do DAS mensal de um custo sobre valor_operacao
        (bases incompatíveis, viola MAX_FISCAL_01). Pior: DISTRIBUICAO_DAS tem
        IBS/CBS zerados em todas as faixas (motor usa _fracao_iva_no_das para
        calcular a fração real), então o motor não expurgava NADA do DAS no
        opt-out — resultava em dupla tributação silenciosa.

        Fórmula nova (base única = valor_operacao, simetria de fator_reducao):
            custo_das_sem_iva = valor_operacao × AE × (1 − fração_IVA_% × fator_reducao)

        Simetria: se IVA por fora sofre REDUCAO_60 (40% da alíquota), a fração
        do DAS expurgada também é 40% — caso contrário há viés pró-opt-out.
        """
        aliquotas_iva = self.get_aliquotas_iva_por_ano()
        ae_efetiva = self.aliquota_efetiva
        fator_reducao = self._fator_reducao_cbs_ibs()

        iva_por_fora = (
            self.operacao.valor_operacao
            * (aliquotas_iva["CBS"] + aliquotas_iva["IBS"])
            * fator_reducao
        ).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # Fração IVA (CBS+IBS) percentual no DAS, por anexo/faixa/ano.
        # Reutiliza _fracao_iva_no_das (mesma fonte usada em credito_b2b_simples).
        anexo = self.anexo_principal
        faixa = obter_faixa_numero(self.rbt12, anexo)
        ano = self.operacao.data_emissao.year
        fracao_iva_pct = self._fracao_iva_no_das(anexo, faixa, ano)

        # AE líquida do DAS: expurga a fração IVA simetricamente ao fator de redução.
        ae_sem_iva = (
            ae_efetiva * (Decimal("1") - fracao_iva_pct * fator_reducao)
        ).quantize(Decimal("0.000001"), ROUND_HALF_UP)

        custo_das_sem_iva = (
            self.operacao.valor_operacao * ae_sem_iva
        ).quantize(Decimal("0.01"), ROUND_HALF_UP)

        custo_das_completo_ref = (
            self.operacao.valor_operacao * ae_efetiva
        ).quantize(Decimal("0.01"), ROUND_HALF_UP)

        custo_total = (custo_das_sem_iva + iva_por_fora).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        self._registrar_passo(
            id="OPT_OUT_CALCULO",
            titulo="Cenário Opt-Out — DAS líquido + IVA por fora (base única)",
            base=f"Valor operação {_fmt_brl(self.operacao.valor_operacao)}",
            deducoes=(
                f"Fração IBS+CBS no DAS Anexo {anexo} Faixa {faixa} em {ano}: "
                f"{(fracao_iva_pct*100):.2f}% × fator redução {fator_reducao}"
            ),
            aliquota=(
                f"AE líquida {(ae_sem_iva*100):.4f}% + IVA por fora "
                f"{((aliquotas_iva['CBS']+aliquotas_iva['IBS'])*fator_reducao*100):.2f}%"
            ),
            valor=_fmt_brl(custo_total),
            lei=(
                "LC 214/2025 Arts. 41-44 (dispositivo de opt-out) | "
                "Art. 47 § 9º (crédito equivalente ao DAS recolhido) | "
                "Arts. 258-264 (fator redução CBS/IBS — aplicação simétrica) | "
                "Arts. 344 e 353 (CBS substitui PIS/COFINS 2027) | "
                "Arts. 356-360 (fase-in IBS 2029-2032) | "
                "Art. 348 III 'c' (dispensa 2026)"
            ),
            detalhe=(
                f"DAS completo seria {_fmt_brl(custo_das_completo_ref)}. "
                f"AE líquida = AE × (1 − fração_IVA_% × fator_redução) = "
                f"{_fmt_brl(custo_das_sem_iva)}. IVA por fora {_fmt_brl(iva_por_fora)}. "
                f"Total {_fmt_brl(custo_total)}. Base única (valor_operacao), "
                f"simetria de fator_reducao nas duas pontas (ERR-046 fix)."
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
                "Empresa mantém competitividade no polo industrial. "
                "Fração IVA do DAS expurgada proporcionalmente à operação — "
                "sem dupla tributação e sem viés direcional (ERR-046)."
            ),
        }

    @cached_property
    def split_payment_impacto(self) -> Dict[str, Any]:
        """
        Split Payment: IBS/CBS retido na fonte pelo PSP a partir de jan/2027. LC 214/2025, Art. 344 + Art. 353 §1º.
        ERR-038: gating por FORMAS_PAGAMENTO_COM_PSP — PIX_VIA_PSP/BOLETO/CARTAO disparam; PIX_DIRETO/DINHEIRO escapam.
        """
        ano = self.operacao.data_emissao.year
        forma = self.operacao.forma_recebimento
        tem_psp = forma in FORMAS_PAGAMENTO_COM_PSP  # V-07: import agora no toplevel

        if ano >= ANO_INICIO_SPLIT_PAYMENT and tem_psp:
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
                base=f"Valor NF {_fmt_brl(self.operacao.valor_operacao)}",
                deducoes="R$ 0,00",
                aliquota=f"{(taxa_retencao*100):.2f}%",
                valor=_fmt_brl(retencao),
                lei="LC 214/2025, Art. 344 + Art. 353 §1º",
                detalhe=(
                    f"Forma de recebimento '{forma}' intermediada por PSP "
                    "— LC 214/2025 Art. 353 §1º impõe retenção automática."
                ),
            )

            return {
                "ativo": True,
                "ano_ativacao": ANO_INICIO_SPLIT_PAYMENT,
                "forma_recebimento": forma,
                "intermediado_por_psp": True,
                "retencao_imediata": str(retencao),
                "percentual_retencao": f"{taxa_retencao * 100:.2f}%",
                "impacto_liquidez": "ALTO — IBS/CBS retido antes de cair na conta.",
                "reducao_mensal_estimada": str(
                    (retencao * 12).quantize(Decimal("0.01"), ROUND_HALF_UP)
                ) + " (anual)",
            }

        if ano < ANO_INICIO_SPLIT_PAYMENT:
            motivo = (
                f"Ano {ano} < {ANO_INICIO_SPLIT_PAYMENT} "
                "(Split Payment ainda não ativo, LC 214/2025 Art. 344)."
            )
        elif forma == "DINHEIRO":
            motivo = (
                "Pagamento em DINHEIRO não passa por PSP — "
                "fora do escopo de Split Payment (LC 214/2025 Art. 353 §1º)."
            )
        elif forma == "PIX_DIRETO":
            motivo = (
                "PIX direto banco-a-banco não tem PSP intermediário — "
                "não dispara retenção automática (LC 214/2025 Art. 353 §1º). "
                "Split Payment atinge apenas PIX via PSP."
            )
        else:
            motivo = f"Forma '{forma}' fora do conjunto com PSP."

        return {
            "ativo": False,
            "forma_recebimento": forma,
            "intermediado_por_psp": tem_psp,
            "motivo": motivo,
            "retencao_imediata": "0.00",
            "impacto_liquidez": "ZERO",
        }

    @cached_property
    def disparidade_anual(self) -> Decimal:
        """Delta anual (Opt-Out - Simples Puro). Positivo = Opt-Out mais caro; negativo = Opt-Out economiza."""
        custo_a = Decimal(self.cenario_simples_puro().get("custo_das_por_operacao", "0"))
        custo_b_total = Decimal(self.cenario_opt_out().get("custo_total", "0"))
        disparidade_por_operacao = custo_b_total - custo_a
        return (disparidade_por_operacao * 12).quantize(Decimal("0.01"), ROUND_HALF_UP)

    def _gerar_recomendacao_opt_out(self) -> Dict[str, str]:
        """Recomendação inteligente de Opt-Out. LC 214/2025 Arts. 41-44 | Res. CGSN 183/2025."""
        from core.recomendacoes_optout import gerar_recomendacao_opt_out
        return gerar_recomendacao_opt_out(
            self.perfil_b2b_ajustado,
            self.disparidade_anual,
            self.rbt12,
        )

    def _montar_cenarios_com_recomendacao(self) -> Dict[str, Any]:
        """Monta o bloco 'cenarios' do diagnóstico com recomendação inteligente."""
        rec = self._gerar_recomendacao_opt_out()
        pct_b2b = self.perfil_b2b_ajustado

        return {
            "simples_puro": self.cenario_simples_puro(),
            "opt_out": self.cenario_opt_out(),
            "disparidade_anual_estimada": str(self.disparidade_anual),
            "percentual_b2b": str(pct_b2b),
            "recomendacao": (
                "OPT_OUT recomendado para reter cliente B2B."
                if rec["codigo"] in ("OPT_OUT_FORTE", "OPT_OUT_VANTAJOSO")
                else (
                    "SIMPLES_PURO adequado — perfil majoritariamente B2C."
                    if rec["codigo"] == "MANTER_SIMPLES"
                    else "Análise individual recomendada — zona cinza."
                )
            ),
            "recomendacao_inteligente": rec,
        }

    # ── FASE 5: DIAGNÓSTICO + ALERTAS + LGPD ─────────────────────────────────

    def _calcular_difal_diagnostico(self) -> Dict[str, Any]:
        """Calcula DIFAL interestadual quando UF origem != UF destino. EC 87/2015 | LC 190/2022."""
        resultado = calcular_difal(
            valor_operacao=self.operacao.valor_operacao,
            uf_origem=self.fornecedora.uf_origem,
            uf_destino=self.compradora.uf_destino,
            tipo_destinatario=self.compradora.tipo,
            produto_importado=self.operacao.produto_importado,
            trilha=self.trilha_auditoria,
        )
        return {
            k: (str(v) if isinstance(v, Decimal) else v)
            for k, v in resultado.items()
        }

    def _gerar_alertas(self) -> List[Dict[str, str]]:
        """Alertas fiscais baseados em gatilhos matemáticos."""
        from core.alertas_motor import gerar_alertas
        return gerar_alertas(
            rbt12=self.rbt12,
            alerta_fator_r=self.alertar_fator_r(),
            split_payment=self.split_payment_impacto,
            tipo_compradora=self.compradora.tipo,
            regime_fornecedora=self.fornecedora.regime,
            data_emissao=self.operacao.data_emissao,
            data_liquidacao=self.operacao.data_liquidacao,
            valor_operacao=self.operacao.valor_operacao,
            qtd_itens=self.operacao.qtd_itens,
            estorno_realizado=self.operacao.estorno_realizado,
            tinha_st_icms=self.operacao.tinha_st_icms,
            cnae_principal=self.fornecedora.cnae_principal,
            cnae_fonte=self._cnae_fonte,  # V-06: inicializado no __init__
        )

    def _diagnostico_lucro_real(self) -> Dict[str, Any]:
        """Diagnóstico para regime Lucro Real via LucroRealEngine."""
        if self._engine_regime is None:  # pragma: no cover
            raise RuntimeError(
                "LucroRealEngine não instanciado. Verifique se regime='REAL' "
                "foi configurado corretamente em EmpresaFornecedora."
            )
        engine = self._engine_regime

        receita_mensal = self.operacao.rpa_mensal or (self.fornecedora.faturamento_12m / 12)
        if receita_mensal <= Decimal("0"):  # pragma: no cover
            raise ValueError(
                "Lucro Real: receita mensal é zero. Informe faturamento_12m > 0 "
                "ou rpa_mensal > 0 para calcular."
            )
        lucro = self.operacao.lucro_real_mensal or receita_mensal
        creditos = self.operacao.creditos_pis_cofins

        _, cnae_fonte = determinar_anexo_por_cnae_com_fonte(self.fornecedora.cnae_principal)
        self._cnae_fonte = cnae_fonte

        resultado = engine.calcular_carga_total_mensal(
            receita_mensal=receita_mensal,
            lucro_real_mensal=lucro,
            creditos_pis_cofins=creditos,
        )

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
            "versao_motor": MOTOR_VERSAO,  # V-04: rastreabilidade retroativa
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
            "split_payment": self.split_payment_impacto,
            "cronograma_iva": cronograma_iva_lista,
            "alertas": self._gerar_alertas(),
            "trilha_auditoria": self.trilha_auditoria,
            "meta": {
                "elaborado_por": f"Escritório Conect — Motor Tributário v{MOTOR_VERSAO}",
                "legislacao_base": ["RIR/2018", "Lei 7.689/1988", "Lei 10.637/2002", "Lei 10.833/2003", "LC 214/2025"],
                "validar_com_profissional": True,
                "aviso": (
                    "Este diagnóstico é de natureza informativa. "
                    "Decisões tributárias devem ser validadas por contador responsável (CRC-SP). "
                    f"Motor v{MOTOR_VERSAO}: diagnósticos gerados em versões anteriores "
                    "podem conter erros fiscais corrigidos em versões posteriores "
                    "(ver campo `versao_motor` e CHANGELOG). Verifique antes de usar "
                    "como prova em defesa jurídica."
                ),
            },
        }

    def gerar_diagnostico(self) -> Dict[str, Any]:
        """Diagnóstico completo em JSON estruturado. Fases 2-5. LGPD: purge() automático após geração."""
        if self.fornecedora.regime == "REAL":
            diagnostico = self._diagnostico_lucro_real()
            self._diagnostico_gerado = True
            return diagnostico

        rbt12_val = self.rbt12
        anexo = self.anexo_principal
        ae_efetiva = self.aliquota_efetiva
        f_r = self.fator_r
        aliquotas_iva = self.get_aliquotas_iva_por_ano()

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
            "versao_motor": MOTOR_VERSAO,  # V-04: rastreabilidade retroativa
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
                "rbt12": str(rbt12_val),
                "fator_r": str(f_r) if f_r is not None else None,
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
                "efetiva_das_total": str(ae_efetiva),
                "efetiva_percentual": f"{ae_efetiva * 100:.4f}%",
                "cbs_vigente_ano": str(aliquotas_iva["CBS"]),
                "ibs_vigente_ano": str(aliquotas_iva["IBS"]),
                "fracao_cbs_no_das": str(self.fracao_cbs),
                "fracao_ibs_no_das": str(self.fracao_ibs),
            },

            "cenarios": self._montar_cenarios_com_recomendacao(),

            "difal": self._calcular_difal_diagnostico(),

            "split_payment": self.split_payment_impacto,

            "cronograma_iva": cronograma_iva_lista,

            "alertas": self._gerar_alertas(),

            "trilha_auditoria": self.trilha_auditoria,

            "meta": {
                "elaborado_por": f"Escritório Conect — Motor Tributário v{MOTOR_VERSAO}",
                "legislacao_base": ["LC 123/2006", "LC 214/2025"],
                "validar_com_profissional": True,
                "aviso": (
                    "Este diagnóstico é de natureza informativa. "
                    "Decisões tributárias devem ser validadas por contador responsável (CRC-SP). "
                    f"Motor v{MOTOR_VERSAO}: diagnósticos gerados em versões anteriores "
                    "podem conter erros fiscais corrigidos em versões posteriores "
                    "(ver campo `versao_motor` e CHANGELOG). Verifique antes de usar "
                    "como prova em defesa jurídica."
                ),
            },
        }

        self._diagnostico_gerado = True
        return diagnostico

    # ── LGPD ──────────────────────────────────────────────────────────────────

    def purge(self) -> None:
        """LGPD Art. 16 — Elimina fornecedora, compradora, operação E trilha_auditoria
        (contém RBT12, CNAE, valor_operacao, UF). Chamar APÓS serializar/persistir o
        diagnóstico — o chamador que guardar referência direta de `motor.trilha_auditoria`
        após `__exit__` receberá lista vazia.

        V-09 fix (auditoria Luiz pós-fissura): trilha_auditoria é dado econômico
        identificável e estava sobrevivendo ao purge anterior. Em FastAPI keep-alive,
        vazava para a próxima análise do mesmo worker.
        """
        setattr(self, "fornecedora", None)
        setattr(self, "compradora", None)
        setattr(self, "operacao", None)
        self.trilha_auditoria.clear()
        gc.collect()
        logger.info("purge() concluído. Dados da análise eliminados da memória.")

    def __del__(self) -> None:
        """Garante purge() no garbage collection caso não tenha sido chamado."""
        if getattr(self, "fornecedora", None) is not None or getattr(self, "compradora", None) is not None:
            self.purge()

    @staticmethod
    def gerar_diagnostico_consolidado(historico: "Any") -> "Any":
        """
        Consolida 6 meses de histórico em DiagnosticoConsolidado.
        Delega para core.historico_consolidado (import local evita circularidade).
        Todo número no output vem do motor rodando — MAX_08.
        LC 123/2006 | LC 214/2025.
        """
        from core.historico_consolidado import gerar_diagnostico_consolidado
        return gerar_diagnostico_consolidado(historico)
