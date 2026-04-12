# -*- coding: utf-8 -*-
"""
regimes/simples_multi.py — Motor Simples Nacional Multi-Atividade
Projeto: Motor Tributário Conect 2026-2033

BASE LEGAL:
  - LC 123/2006, Art. 18, § 3º — cada atividade tributada no Anexo correto
  - LC 123/2006, Art. 13, § 1º, VII — ICMS-ST zerado no DAS
  - LC 123/2006, Art. 18, §§ 1º e 24 — fórmula AE por Anexo

ESCOPO ("Funcionar" primeiro):
  - Recebe EmpresaFornecedora com atividades[] preenchido
  - Cada Atividade: receita, anexo, icms_st, iss_retido
  - DAS por atividade com abatimento proporcional de ST/ISS
  - Alíquota efetiva total = total_das / receita_total

GUARD CLAUSE (Camada 2):
  1. regime != "SIMPLES"  → RegimeMismatchError (via BaseRegimeEngine)
  2. atividades ausentes  → ValueError com instrução clara
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List

from core.regimes.base import BaseRegimeEngine
from core.tabelas_simples import (
    DISTRIBUICAO_DAS,
    TABELAS_ANEXOS,
    TETO_SIMPLES_NACIONAL,
    obter_faixa_numero,
)

# ─────────────────────────────────────────────────────────────────────────────
# ENGINE — SIMPLES NACIONAL MULTI-ATIVIDADE
# ─────────────────────────────────────────────────────────────────────────────

class SimplesMultiAtividadeEngine(BaseRegimeEngine):
    """
    Motor de cálculo para empresas Simples Nacional com múltiplas atividades.
    Guard Clause: aceita SOMENTE regime='SIMPLES' COM atividades preenchidas.

    Ancoragem: LC 123/2006, Art. 18, § 3º.
    """
    REGIME_ACEITO = "SIMPLES"

    def __init__(self, fornecedora: Any, trilha: List[Dict[str, Any]]) -> None:
        super().__init__(fornecedora, trilha)  # Ativa Camada 2 — Guard Clause regime

        # Guard adicional: atividades obrigatórias
        if not fornecedora.atividades:
            raise ValueError(
                "SimplesMultiAtividadeEngine requer 'atividades' preenchido. "
                "Preencha EmpresaFornecedora.atividades=[Atividade(receita, anexo)]. "
                "Ancoragem: LC 123/2006, Art. 18, §3º."
            )

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNOS — TABELAS
    # ─────────────────────────────────────────────────────────────────────────

    def _buscar_faixa(self, rbt12: Decimal, anexo: str):
        """
        Retorna (aliquota_nominal, parcela_deduzir) para o RBT12 e Anexo.
        LC 123/2006, Art. 18, § 1º — tabelas Anexos I a V.
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

    def _calcular_ae_por_anexo(self, rbt12: Decimal, anexo: str) -> Decimal:
        """
        Alíquota Efetiva para o Anexo informado dado o RBT12.
        Fórmula: ((RBT12 × Aliq_Nominal) - Parcela_Deduzir) / RBT12
        LC 123/2006, Art. 18, § 1º.
        """
        aliq_nominal, parcela_deduzir = self._buscar_faixa(rbt12, anexo)
        ae = (rbt12 * aliq_nominal - parcela_deduzir) / rbt12
        return ae.quantize(Decimal("0.000001"), ROUND_HALF_UP)

    # ─────────────────────────────────────────────────────────────────────────
    # CÁLCULO PRINCIPAL
    # ─────────────────────────────────────────────────────────────────────────

    def calcular_das_multi_atividade(self) -> Dict[str, Any]:
        """
        DAS mensal por atividade com abatimento de ST/ISS retido.
        LC 123/2006, Art. 18, §§ 1º e 3º | Art. 13, § 1º, VII.

        Retorna breakdown por atividade + total + alíquota efetiva.
        """
        rbt12 = self.fornecedora.faturamento_12m
        itens: List[Dict[str, Any]] = []
        total_das    = Decimal("0.00")
        receita_total = Decimal("0.00")

        for atividade in self.fornecedora.atividades:
            ae_bruta  = self._calcular_ae_por_anexo(rbt12, atividade.anexo)
            faixa_num = obter_faixa_numero(rbt12, atividade.anexo)
            dist      = DISTRIBUICAO_DAS.get(atividade.anexo, {}).get(faixa_num, {})

            # Abatimento por ST/ISS retido (LC 123/2006, Art. 13, § 1º, VII)
            pct_abatimento = Decimal("0")
            if atividade.icms_st:
                pct_abatimento += dist.get("ICMS", Decimal("0"))
            if atividade.iss_retido:
                pct_abatimento += dist.get("ISS", Decimal("0"))

            ae_liquida = (ae_bruta * (Decimal("1") - pct_abatimento)).quantize(
                Decimal("0.000001"), ROUND_HALF_UP
            )
            das_item = (atividade.receita * ae_liquida).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )

            itens.append({
                "anexo":      atividade.anexo,
                "receita":    atividade.receita,
                "ae_bruta":   ae_bruta,
                "ae_liquida": ae_liquida,
                "icms_st":    atividade.icms_st,
                "iss_retido": atividade.iss_retido,
                "das":        das_item,
            })
            total_das     += das_item
            receita_total += atividade.receita

        total_das     = total_das.quantize(Decimal("0.01"), ROUND_HALF_UP)
        receita_total = receita_total.quantize(Decimal("0.01"), ROUND_HALF_UP)

        aliquota_efetiva = (
            (total_das / receita_total).quantize(Decimal("0.000001"), ROUND_HALF_UP)
            if receita_total > Decimal("0")
            else Decimal("0.000000")
        )

        self._registrar_passo(
            id="DAS_MULTI_ATIVIDADE",
            titulo="DAS Simples Nacional — Multi-Atividade",
            base=f"Receita Total R$ {receita_total:,.2f} | RBT12 R$ {rbt12:,.2f}",
            deducoes=f"Abatimentos ST/ISS retido por atividade ({len(itens)} atividade(s))",
            aliquota=f"AE efetiva {aliquota_efetiva*100:.4f}%",
            valor=f"R$ {total_das:,.2f}",
            lei="LC 123/2006, Art. 18, §§ 1º e 3º | Art. 13, § 1º, VII",
        )

        return {
            "itens":            itens,
            "total_das":        total_das,
            "receita_total":    receita_total,
            "aliquota_efetiva": aliquota_efetiva,
            "rbt12":            rbt12,
        }

    def calcular_carga_total_mensal(self) -> Dict[str, Any]:
        """
        Carga tributária total mensal — Simples Nacional Multi-Atividade.
        Retorna breakdown por atividade + total + trilha de auditoria.
        LC 123/2006, Art. 18, §§ 1º e 3º.
        """
        das = self.calcular_das_multi_atividade()

        self._registrar_passo(
            id="CARGA_TOTAL_SIMPLES_MULTI",
            titulo="Carga Total Mensal — Simples Multi-Atividade",
            base=f"Receita Total R$ {das['receita_total']:,.2f}",
            deducoes=f"DAS unificado por atividade — {len(das['itens'])} atividade(s)",
            aliquota=f"AE efetiva {das['aliquota_efetiva']*100:.4f}%",
            valor=f"R$ {das['total_das']:,.2f}",
            lei="LC 123/2006, Art. 18, §§ 1º e 3º | LC 214/2025 (transição IVA)",
        )

        return {
            "regime":           "SIMPLES",
            "atividades":       das["itens"],
            "receita_total":    das["receita_total"],
            "total_mensal":     das["total_das"],
            "aliquota_efetiva": das["aliquota_efetiva"],
            "nota": (
                "Simples Nacional Multi-Atividade — DAS calculado por Anexo por atividade. "
                "LC 123/2006, Art. 18, §3º."
            ),
            "trilha_auditoria": self.trilha,
        }
