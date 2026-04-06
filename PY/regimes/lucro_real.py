# -*- coding: utf-8 -*-
"""
regimes/lucro_real.py — Motor Lucro Real
Projeto: Motor Tributário Conect 2026-2033

BASE LEGAL:
  - RIR/2018 (Decreto 9.580/2018), Art. 228 — IRPJ 15% + adicional 10%
  - Lei 7.689/1988, Art. 3º + Lei 9.430/1996, Art. 29 — CSLL 9%
  - Lei 10.637/2002, Art. 2º — PIS não-cumulativo 1,65%
  - Lei 10.833/2003, Art. 2º — COFINS não-cumulativo 7,60%
  - Lei 10.637/2002, Art. 3º + Lei 10.833/2003, Art. 3º — Créditos PIS/COFINS

ESCOPO ("Funcionar" primeiro):
  - Aceita `lucro_real_mensal` como parâmetro externo (apurado pelo contador)
  - Créditos PIS/COFINS: parâmetro opcional (default R$ 0,00)
  - Apuração IRPJ/CSLL: base mensal estimada (não trimestral)

GUARD CLAUSE (Camada 2):
  Qualquer tentativa de usar este engine com regime != "REAL"
  resulta em RegimeMismatchError com log na trilha de auditoria.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List

from regimes.base import BaseRegimeEngine

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES LEGAIS — FROZEN (RIR/2018 + Leis 10.637 e 10.833)
# ─────────────────────────────────────────────────────────────────────────────

# IRPJ — RIR/2018, Art. 228
ALIQUOTA_IRPJ           = Decimal("0.15")       # 15% sobre lucro real
ALIQUOTA_IRPJ_ADICIONAL = Decimal("0.10")       # 10% sobre excedente mensal
TETO_IRPJ_SEM_ADICIONAL_MENSAL = Decimal("20000.00")  # R$ 20.000/mês

# CSLL — Lei 7.689/1988, Art. 3º
ALIQUOTA_CSLL = Decimal("0.09")                 # 9% sobre lucro real

# PIS — Lei 10.637/2002, Art. 2º (não-cumulativo)
ALIQUOTA_PIS = Decimal("0.0165")                # 1,65%

# COFINS — Lei 10.833/2003, Art. 2º (não-cumulativo)
ALIQUOTA_COFINS = Decimal("0.076")              # 7,60%


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE — LUCRO REAL
# ─────────────────────────────────────────────────────────────────────────────

class LucroRealEngine(BaseRegimeEngine):
    """
    Motor de cálculo para empresas no Lucro Real.
    Guard Clause: aceita SOMENTE empresas com regime='REAL'.
    Ancoragem: RIR/2018, Art. 228 | Lei 10.637/2002 | Lei 10.833/2003.
    """
    REGIME_ACEITO = "REAL"

    def __init__(self, fornecedora: Any, trilha: List[Dict[str, Any]]) -> None:
        super().__init__(fornecedora, trilha)  # Ativa Camada 2 automaticamente

    def calcular_irpj(self, lucro_real_mensal: Decimal) -> Dict[str, Decimal]:
        """
        IRPJ sobre lucro real mensal estimado.
        RIR/2018, Art. 228 — 15% + adicional 10% sobre excedente de R$ 20k/mês.
        """
        irpj_principal = (lucro_real_mensal * ALIQUOTA_IRPJ).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        excedente = max(Decimal("0"), lucro_real_mensal - TETO_IRPJ_SEM_ADICIONAL_MENSAL)
        irpj_adicional = (excedente * ALIQUOTA_IRPJ_ADICIONAL).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        irpj_total = irpj_principal + irpj_adicional

        self._registrar_passo(
            id="IRPJ_LUCRO_REAL",
            titulo="IRPJ — Lucro Real (apuração mensal estimada)",
            base=f"Lucro Real Mensal R$ {lucro_real_mensal:,.2f}",
            deducoes=f"Teto adicional R$ {TETO_IRPJ_SEM_ADICIONAL_MENSAL:,.2f}/mês",
            aliquota=(
                "IRPJ 15%"
                + (f" + Adicional 10% s/ excedente R$ {excedente:,.2f}" if excedente else "")
            ),
            valor=(
                f"Principal R$ {irpj_principal:,.2f}"
                + f" + Adicional R$ {irpj_adicional:,.2f}"
                + f" = R$ {irpj_total:,.2f}"
            ),
            lei="RIR/2018, Art. 228 | Lei 9.430/1996, Art. 2º",
        )

        return {
            "IRPJ_PRINCIPAL": irpj_principal,
            "IRPJ_ADICIONAL": irpj_adicional,
            "IRPJ_TOTAL":     irpj_total,
        }

    def calcular_csll(self, lucro_real_mensal: Decimal) -> Decimal:
        """
        CSLL sobre lucro real.
        Lei 7.689/1988, Art. 3º — 9% sobre lucro real.
        """
        csll = (lucro_real_mensal * ALIQUOTA_CSLL).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        self._registrar_passo(
            id="CSLL_LUCRO_REAL",
            titulo="CSLL — Lucro Real",
            base=f"Lucro Real Mensal R$ {lucro_real_mensal:,.2f}",
            deducoes="R$ 0,00 (base = lucro real integral)",
            aliquota=f"CSLL {ALIQUOTA_CSLL*100:.0f}%",
            valor=f"R$ {csll:,.2f}",
            lei="Lei 7.689/1988, Art. 3º | Lei 9.430/1996, Art. 29",
        )

        return csll

    def calcular_pis_cofins(
        self,
        receita_bruta: Decimal,
        creditos: Decimal = Decimal("0.00"),
    ) -> Dict[str, Decimal]:
        """
        PIS/COFINS não-cumulativo com abatimento de créditos.
        Lei 10.637/2002, Art. 2º (PIS 1,65%) | Lei 10.833/2003, Art. 2º (COFINS 7,60%).
        Créditos: Lei 10.637/2002, Art. 3º | Lei 10.833/2003, Art. 3º.
        """
        pis_bruto    = (receita_bruta * ALIQUOTA_PIS).quantize(Decimal("0.01"), ROUND_HALF_UP)
        cofins_bruto = (receita_bruta * ALIQUOTA_COFINS).quantize(Decimal("0.01"), ROUND_HALF_UP)
        total_bruto  = pis_bruto + cofins_bruto

        creditos = creditos.quantize(Decimal("0.01"), ROUND_HALF_UP)
        creditos_efetivos = min(creditos, total_bruto)

        # Distribui créditos proporcionalmente entre PIS e COFINS
        if total_bruto > Decimal("0"):
            prop_pis    = pis_bruto / total_bruto
            cred_pis    = (creditos_efetivos * prop_pis).quantize(Decimal("0.01"), ROUND_HALF_UP)
            cred_cofins = (creditos_efetivos - cred_pis).quantize(Decimal("0.01"), ROUND_HALF_UP)
        else:
            cred_pis = cred_cofins = Decimal("0.00")

        pis_liquido    = max(Decimal("0.00"), pis_bruto - cred_pis)
        cofins_liquido = max(Decimal("0.00"), cofins_bruto - cred_cofins)

        self._registrar_passo(
            id="PIS_COFINS_NAO_CUMULATIVO",
            titulo="PIS/COFINS Não-Cumulativo (Lucro Real)",
            base=f"Receita Bruta R$ {receita_bruta:,.2f}",
            deducoes=f"Créditos R$ {creditos_efetivos:,.2f}",
            aliquota=f"PIS {ALIQUOTA_PIS*100:.2f}% | COFINS {ALIQUOTA_COFINS*100:.2f}%",
            valor=(
                f"PIS líq. R$ {pis_liquido:,.2f} | COFINS líq. R$ {cofins_liquido:,.2f}"
                + f" (bruto R$ {total_bruto:,.2f} - créditos R$ {creditos_efetivos:,.2f})"
            ),
            lei="Lei 10.637/2002, Art. 2º e 3º | Lei 10.833/2003, Art. 2º e 3º",
        )

        return {
            "PIS_BRUTO":      pis_bruto,
            "COFINS_BRUTO":   cofins_bruto,
            "CREDITOS":       creditos_efetivos,
            "PIS_LIQUIDO":    pis_liquido,
            "COFINS_LIQUIDO": cofins_liquido,
        }

    def calcular_carga_total_mensal(
        self,
        receita_mensal: Decimal,
        lucro_real_mensal: Decimal,
        creditos_pis_cofins: Decimal = Decimal("0.00"),
    ) -> Dict[str, Any]:
        """
        Carga tributária total mensal — Lucro Real.
        Retorna breakdown por tributo + total + trilha de auditoria.
        """
        pis_cofins = self.calcular_pis_cofins(receita_mensal, creditos_pis_cofins)
        csll       = self.calcular_csll(lucro_real_mensal)
        irpj_dict  = self.calcular_irpj(lucro_real_mensal)

        total = (
            pis_cofins["PIS_LIQUIDO"]
            + pis_cofins["COFINS_LIQUIDO"]
            + csll
            + irpj_dict["IRPJ_TOTAL"]
        ).quantize(Decimal("0.01"), ROUND_HALF_UP)

        aliquota_efetiva = (
            (total / receita_mensal).quantize(Decimal("0.000001"), ROUND_HALF_UP)
            if receita_mensal > Decimal("0")
            else Decimal("0.000000")
        )

        self._registrar_passo(
            id="CARGA_TOTAL_REAL",
            titulo="Carga Total Mensal — Lucro Real",
            base=f"Receita R$ {receita_mensal:,.2f} | Lucro R$ {lucro_real_mensal:,.2f}",
            deducoes="PIS+COFINS não-cumulativo (líq.) + CSLL + IRPJ s/ lucro real",
            aliquota=f"AE efetiva {aliquota_efetiva*100:.4f}%",
            valor=f"R$ {total:,.2f}",
            lei="RIR/2018 Art. 228 | Lei 7.689/1988 | Lei 10.637/2002 | Lei 10.833/2003",
        )

        return {
            "regime":            "REAL",
            "receita_mensal":    receita_mensal,
            "lucro_real_mensal": lucro_real_mensal,
            "breakdown": {
                "PIS":            pis_cofins["PIS_LIQUIDO"],
                "COFINS":         pis_cofins["COFINS_LIQUIDO"],
                "CSLL":           csll,
                "IRPJ":           irpj_dict["IRPJ_PRINCIPAL"],
                "IRPJ_ADICIONAL": irpj_dict["IRPJ_ADICIONAL"],
            },
            "total_mensal":      total,
            "aliquota_efetiva":  aliquota_efetiva,
            "nota": (
                "Lucro Real — apuração mensal estimada. "
                "IRPJ/CSLL calculados sobre lucro real informado. "
                "PIS/COFINS não-cumulativos com créditos abatidos."
            ),
            "trilha_auditoria":  self.trilha,
        }
