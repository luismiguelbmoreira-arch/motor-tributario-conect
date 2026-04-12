# -*- coding: utf-8 -*-
"""
regimes/lucro_presumido.py — Motor Lucro Presumido
Projeto: Motor Tributário Conect 2026-2033

BASE LEGAL:
  - RIR/2018 (Decreto 9.580/2018), Art. 214 — Lucro Presumido
  - Lei 9.249/1995, Art. 15 — Percentuais de Presunção por Atividade
  - Lei 9.718/1998, Art. 2º — PIS/COFINS Cumulativo
  - Lei 7.689/1988 + Lei 9.430/1996 — CSLL

GUARD CLAUSE (Camada 2):
  Qualquer tentativa de usar este engine com empresa regime != "PRESUMIDO"
  resulta em RegimeMismatchError com log na trilha de auditoria.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List

from core.regimes.base import BaseRegimeEngine

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES LEGAIS — FROZEN (aprovadas por Luiz Moreira)
# ─────────────────────────────────────────────────────────────────────────────

# PIS/COFINS Cumulativo (Lei 9.718/1998 — regime Presumido/MEI)
ALIQUOTA_PIS_CUMULATIVO   = Decimal("0.0065")   # 0,65%
ALIQUOTA_COFINS_CUMULATIVO = Decimal("0.03")    # 3,00%

# IRPJ — Lei 9.430/1996, Art. 25
ALIQUOTA_IRPJ           = Decimal("0.15")       # 15%
ALIQUOTA_IRPJ_ADICIONAL = Decimal("0.10")       # 10% sobre lucro acima de R$60k/trimestre
TETO_IRPJ_SEM_ADICIONAL_TRIMESTRAL = Decimal("60000.00")  # R$ 60.000/trimestre

# CSLL — Lei 7.689/1988, Art. 3º; CSLL Lei 9.430/1996, Art. 29
ALIQUOTA_CSLL_COMERCIO  = Decimal("0.09")       # 9% (comércio/indústria)
ALIQUOTA_CSLL_SERVICOS  = Decimal("0.09")       # 9% (serviços — igual)

# Percentuais de Presunção por Atividade (Lei 9.249/1995, Art. 15 — IRPJ; Art. 20 — CSLL)
# Formato: CNAE prefixo → (presunção_IRPJ, presunção_CSLL)
# Âncora: RIR/2018 (Decreto 9.580/2018), Art. 591-604 — consolida Art. 15 da Lei 9.249/1995.
PRESUNCAO_IRPJ_CSLL: Dict[str, tuple] = {
    # Comércio atacadista/varejista (Seção G — CNAE 45xx, 46xx, 47xx)
    # Lei 9.249/1995, Art. 15, I: presunção IRPJ = 8%; CSLL = 12% (RIR/2018, Art. 592, I)
    "45": (Decimal("0.08"), Decimal("0.12")),  # Comércio e reparação de veículos
    "46": (Decimal("0.08"), Decimal("0.12")),  # Comércio atacadista
    "47": (Decimal("0.08"), Decimal("0.12")),  # Comércio varejista
    # Serviços hospitalares, laboratoriais e clínicas (Seção Q — CNAE 86xx)
    # Lei 9.249/1995, Art. 15, III: presunção IRPJ = 8% para serviços hospitalares
    # (tratamento igual ao comércio; exceção ao 32% geral para serviços de saúde)
    "86": (Decimal("0.08"), Decimal("0.12")),  # Atividades de atenção à saúde humana
    # Transporte de PASSAGEIROS — presunção 16% (Lei 9.249/1995, Art. 15, §1º, III, "a")
    # RIR/2018, Art. 592, III — serviços de transporte que NÃO sejam de carga
    "4921": (Decimal("0.16"), Decimal("0.12")),  # Transporte municipal passageiros
    "4922": (Decimal("0.16"), Decimal("0.12")),  # Transporte intermunicipal passageiros
    "4929": (Decimal("0.16"), Decimal("0.12")),  # Transporte outros passageiros
    "4930": (Decimal("0.16"), Decimal("0.12")),  # Transporte rodoviário passageiros
    # Transporte de CARGAS — presunção 8% (Lei 9.249/1995, Art. 15, §1º, III)
    "49": (Decimal("0.08"), Decimal("0.12")),    # Transporte terrestre (carga — fallback)
    # Demais serviços — regra geral residual
    # Lei 9.249/1995, Art. 15, caput + §1º: presunção IRPJ = 32%; CSLL = 32%
    # Inclui: consultoria, TI, serviços profissionais, publicidade, educação privada, etc.
    "_default_servicos": (Decimal("0.32"), Decimal("0.32")),
    # Indústria e equiparados (Seção C — CNAE 10xx a 33xx)
    # Lei 9.249/1995, Art. 15, I: presunção IRPJ = 8%; CSLL = 12%
    "_default_industria": (Decimal("0.08"), Decimal("0.12")),
}

# ─────────────────────────────────────────────────────────────────────────────
# ENGINE — LUCRO PRESUMIDO
# ─────────────────────────────────────────────────────────────────────────────

class LucroPresumidoEngine(BaseRegimeEngine):
    """
    Motor de cálculo para empresas no Lucro Presumido.
    Guard Clause: aceita SOMENTE empresas com regime='PRESUMIDO'.
    Ancoragem: RIR/2018 Art. 214 | Lei 9.249/1995 Art. 15.
    """
    REGIME_ACEITO = "PRESUMIDO"

    def __init__(self, fornecedora: Any, trilha: List[Dict[str, Any]]) -> None:
        super().__init__(fornecedora, trilha)  # Ativa Camada 2 automaticamente

    def _obter_percentual_presuncao(self) -> tuple:
        """
        Retorna (perc_IRPJ, perc_CSLL) conforme CNAE.
        Lei 9.249/1995, Art. 15.
        """
        cnae = getattr(self.fornecedora, "cnae_principal", "") or ""
        prefixo4 = cnae[:4]  # Busca 4 dígitos primeiro (ex: 4921 = passageiros 16%)
        prefixo = cnae[:2]

        if prefixo4 in PRESUNCAO_IRPJ_CSLL:
            return PRESUNCAO_IRPJ_CSLL[prefixo4]
        if prefixo in PRESUNCAO_IRPJ_CSLL:
            return PRESUNCAO_IRPJ_CSLL[prefixo]

        # Fallback: verifica se é indústria (seções B e C — prefixos 05 a 33)
        try:
            num = int(prefixo)
            if 5 <= num <= 33:
                return PRESUNCAO_IRPJ_CSLL["_default_industria"]
        except ValueError:
            pass

        return PRESUNCAO_IRPJ_CSLL["_default_servicos"]

    def calcular_pis_cofins(self, receita_bruta: Decimal) -> Dict[str, Decimal]:
        """
        PIS/COFINS Cumulativo (Lucro Presumido — regime padrão).
        Lei 9.718/1998, Art. 2º — alíquotas 0,65% e 3%.
        """
        pis    = (receita_bruta * ALIQUOTA_PIS_CUMULATIVO).quantize(Decimal("0.01"), ROUND_HALF_UP)
        cofins = (receita_bruta * ALIQUOTA_COFINS_CUMULATIVO).quantize(Decimal("0.01"), ROUND_HALF_UP)

        self._registrar_passo(
            id="PIS_COFINS_CUMULATIVO",
            titulo="PIS/COFINS Cumulativo (Lucro Presumido)",
            base=f"Receita Bruta R$ {receita_bruta:,.2f}",
            deducoes="R$ 0,00 (sem deduções no cumulativo)",
            aliquota=f"PIS {ALIQUOTA_PIS_CUMULATIVO*100:.2f}% | COFINS {ALIQUOTA_COFINS_CUMULATIVO*100:.2f}%",
            valor=f"PIS R$ {pis:,.2f} | COFINS R$ {cofins:,.2f}",
            lei="Lei 9.718/1998, Art. 2º",
        )
        return {"PIS": pis, "COFINS": cofins}

    def calcular_csll(self, receita_bruta: Decimal) -> Decimal:
        """
        CSLL sobre base presumida.
        Lei 7.689/1988 | Lei 9.430/1996 Art. 29.
        CSLL: 9% sobre (receita × % presunção CSLL).
        """
        _, perc_csll = self._obter_percentual_presuncao()
        base_csll = (receita_bruta * perc_csll).quantize(Decimal("0.01"), ROUND_HALF_UP)
        csll = (base_csll * ALIQUOTA_CSLL_COMERCIO).quantize(Decimal("0.01"), ROUND_HALF_UP)

        self._registrar_passo(
            id="CSLL_PRESUMIDO",
            titulo="CSLL — Base Presumida",
            base=f"Receita Bruta R$ {receita_bruta:,.2f}",
            deducoes=f"% Presunção CSLL {perc_csll*100:.0f}%",
            aliquota=f"CSLL {ALIQUOTA_CSLL_COMERCIO*100:.0f}%",
            valor=f"Base R$ {base_csll:,.2f} → CSLL R$ {csll:,.2f}",
            lei="Lei 7.689/1988 | Lei 9.430/1996, Art. 29",
        )
        return csll

    def calcular_irpj(self, receita_bruta: Decimal, meses: int = 3) -> Dict[str, Decimal]:
        """
        IRPJ sobre base presumida (apuração trimestral).
        Lei 9.430/1996, Art. 25 | RIR/2018, Art. 214.
        Adicional 10% sobre lucro > R$60k/trimestre.
        """
        perc_irpj, _ = self._obter_percentual_presuncao()

        receita_trimestral = receita_bruta * meses
        base_irpj = (receita_trimestral * perc_irpj).quantize(Decimal("0.01"), ROUND_HALF_UP)

        irpj_principal = (base_irpj * ALIQUOTA_IRPJ).quantize(Decimal("0.01"), ROUND_HALF_UP)

        # Adicional de 10% sobre excedente de R$60k/trimestre
        excedente = max(Decimal("0"), base_irpj - TETO_IRPJ_SEM_ADICIONAL_TRIMESTRAL)
        irpj_adicional = (excedente * ALIQUOTA_IRPJ_ADICIONAL).quantize(Decimal("0.01"), ROUND_HALF_UP)
        irpj_total = irpj_principal + irpj_adicional

        # Converte para mensal para comparabilidade com outros regimes
        irpj_mensal = (irpj_total / meses).quantize(Decimal("0.01"), ROUND_HALF_UP)

        self._registrar_passo(
            id="IRPJ_PRESUMIDO",
            titulo="IRPJ — Base Presumida (Trimestral)",
            base=f"Receita Trimestral R$ {receita_trimestral:,.2f}",
            deducoes=f"% Presunção IRPJ {perc_irpj*100:.0f}%",
            aliquota=f"IRPJ 15% + Adicional 10% (excedente R$ {excedente:,.2f})",
            valor=f"IRPJ R$ {irpj_principal:,.2f} + Adicional R$ {irpj_adicional:,.2f} = R$ {irpj_total:,.2f} (≈ R$ {irpj_mensal:,.2f}/mês)",
            lei="Lei 9.430/1996, Art. 25 | RIR/2018, Art. 214",
        )
        return {
            "IRPJ_PRINCIPAL": irpj_principal,
            "IRPJ_ADICIONAL": irpj_adicional,
            "IRPJ_TOTAL_TRIMESTRAL": irpj_total,
            "IRPJ_MENSAL_ESTIMADO": irpj_mensal,
        }

    def calcular_carga_total_mensal(self, receita_mensal: Decimal) -> Dict[str, Any]:
        """
        Carga tributária total mensal estimada (Lucro Presumido).
        Retorna breakdown por tributo + total + memória de cálculo.
        """
        pis_cofins = self.calcular_pis_cofins(receita_mensal)
        csll       = self.calcular_csll(receita_mensal)
        irpj_dict  = self.calcular_irpj(receita_mensal, meses=3)

        total = (
            pis_cofins["PIS"]
            + pis_cofins["COFINS"]
            + csll
            + irpj_dict["IRPJ_MENSAL_ESTIMADO"]
        ).quantize(Decimal("0.01"), ROUND_HALF_UP)

        aliquota_efetiva = (total / receita_mensal).quantize(Decimal("0.000001"), ROUND_HALF_UP)

        self._registrar_passo(
            id="CARGA_TOTAL_PRESUMIDO",
            titulo="Carga Total Mensal — Lucro Presumido",
            base=f"Receita Mensal R$ {receita_mensal:,.2f}",
            deducoes="PIS+COFINS+CSLL+IRPJ (sem CPP — recolhido separado via GPS)",
            aliquota=f"AE efetiva {aliquota_efetiva*100:.4f}%",
            valor=f"R$ {total:,.2f}",
            lei="RIR/2018 Art. 214 | Lei 9.249/1995 Art. 15 | Lei 9.718/1998 Art. 2º",
        )

        return {
            "regime": "PRESUMIDO",
            "receita_mensal": receita_mensal,
            "breakdown": {
                "PIS":   pis_cofins["PIS"],
                "COFINS":pis_cofins["COFINS"],
                "CSLL":  csll,
                "IRPJ":  irpj_dict["IRPJ_MENSAL_ESTIMADO"],
            },
            "total_mensal": total,
            "aliquota_efetiva": aliquota_efetiva,
            "nota": "CPP (INSS Patronal) não incluso — recolhido via GPS separado.",
            "trilha_auditoria": self.trilha,
        }
