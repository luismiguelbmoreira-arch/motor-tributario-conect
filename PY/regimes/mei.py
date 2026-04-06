# -*- coding: utf-8 -*-
"""
regimes/mei.py — Motor MEI (Microempreendedor Individual)
Projeto: Motor Tributário Conect 2026-2033

BASE LEGAL:
  - LC 123/2006, Art. 18-A (MEI — DAS fixo mensal)
  - Resolução CGSN nº 140/2018 (regulamenta DAS-MEI)
  - LC 214/2025, Art. 4º (MEI sem crédito CBS/IBS para tomadores)

GUARD CLAUSE (Camada 2):
  Qualquer tentativa de usar este engine com empresa regime != "MEI"
  resulta em RegimeMismatchError com log na trilha de auditoria.

CARACTERÍSTICAS MEI:
  - DAS fixo mensal por categoria (COMERCIO / INDUSTRIA / SERVICOS / COMERCIO_SERVICOS)
  - Teto de receita: R$ 81.000/ano — alerta na trilha se excedido (não bloqueia)
  - Sem crédito CBS/IBS para tomadores (credito_iva = R$ 0,00)
  - Sem PIS/COFINS, CSLL, IRPJ — substituídos pelo DAS unificado
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List

from regimes.base import BaseRegimeEngine

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTES LEGAIS — FROZEN 2026 (LC 123/2006, Art. 18-A + Resolução CGSN)
# ─────────────────────────────────────────────────────────────────────────────

# Salário mínimo por ano — base de cálculo do INSS MEI (LC 123/2006, Art. 18-A, §3º, I)
# 2026: Decreto confirmado. 2027-2033: estimativas conservadoras (~7% a.a.)
# ATUALIZAR anualmente com decreto presidencial.
SM_POR_ANO: Dict[int, Decimal] = {
    2026: Decimal("1621.00"),   # Confirmado — R$ 1.621,00 (SM 2026)
    2027: Decimal("1734.00"),   # Estimativa (+7%)
    2028: Decimal("1855.00"),   # Estimativa (+7%)
    2029: Decimal("1985.00"),   # Estimativa (+7%)
    2030: Decimal("2124.00"),   # Estimativa (+7%)
    2031: Decimal("2273.00"),   # Estimativa (+7%)
    2032: Decimal("2432.00"),   # Estimativa (+7%)
    2033: Decimal("2602.00"),   # Estimativa (+7%)
}
SALARIO_MINIMO_2026 = SM_POR_ANO[2026]  # Compatibilidade

# INSS MEI: 5% do salário mínimo (LC 123/2006, Art. 18-A, § 3º, I)
ALIQUOTA_INSS_MEI = Decimal("0.05")

# Parcelas fixas (LC 123/2006, Art. 18-A, § 3º, II e III)
ICMS_FIXO = Decimal("5.00")   # comércio e indústria
ISS_FIXO  = Decimal("5.00")   # serviços

# Teto anual de receita bruta MEI (LC 123/2006, Art. 18-A, caput)
TETO_ANUAL_MEI = Decimal("81000.00")

# ─────────────────────────────────────────────────────────────────────────────
# CATEGORIAS VÁLIDAS
# ─────────────────────────────────────────────────────────────────────────────

CATEGORIAS_MEI = {"COMERCIO", "INDUSTRIA", "SERVICOS", "COMERCIO_SERVICOS"}

# ─────────────────────────────────────────────────────────────────────────────
# ENGINE — MEI
# ─────────────────────────────────────────────────────────────────────────────

class MEIEngine(BaseRegimeEngine):
    """
    Motor de cálculo para Microempreendedor Individual (MEI).
    Guard Clause: aceita SOMENTE empresas com regime='MEI'.
    Ancoragem: LC 123/2006, Art. 18-A.
    """
    REGIME_ACEITO = "MEI"

    def __init__(self, fornecedora: Any, trilha: List[Dict[str, Any]]) -> None:
        super().__init__(fornecedora, trilha)  # Ativa Camada 2 automaticamente

    def calcular_das_mensal(self, categoria: str) -> Dict[str, Decimal]:
        """
        Calcula o DAS MEI mensal por categoria de atividade.
        LC 123/2006, Art. 18-A, § 3º | Resolução CGSN nº 140/2018.

        Categorias aceitas:
          - COMERCIO          → INSS + ICMS
          - INDUSTRIA         → INSS + ICMS
          - SERVICOS          → INSS + ISS
          - COMERCIO_SERVICOS → INSS + ICMS + ISS
        """
        if categoria not in CATEGORIAS_MEI:
            raise ValueError(
                f"Categoria MEI inválida: '{categoria}'. "
                f"Categorias aceitas: {sorted(CATEGORIAS_MEI)}"
            )

        inss = (SALARIO_MINIMO_2026 * ALIQUOTA_INSS_MEI).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )

        icms = ICMS_FIXO if categoria in ("COMERCIO", "INDUSTRIA", "COMERCIO_SERVICOS") else Decimal("0.00")
        iss  = ISS_FIXO  if categoria in ("SERVICOS", "COMERCIO_SERVICOS") else Decimal("0.00")

        das_total = (inss + icms + iss).quantize(Decimal("0.01"), ROUND_HALF_UP)

        self._registrar_passo(
            id="DAS_MEI",
            titulo=f"DAS MEI — Categoria {categoria}",
            base=f"Salário Mínimo 2026 R$ {SALARIO_MINIMO_2026:,.2f}",
            deducoes="Regime Unificado (sem PIS/COFINS/CSLL/IRPJ separados)",
            aliquota=(
                f"INSS {ALIQUOTA_INSS_MEI*100:.0f}% s/ SM"
                + (f" | ICMS R$ {ICMS_FIXO}" if icms else "")
                + (f" | ISS R$ {ISS_FIXO}" if iss else "")
            ),
            valor=f"INSS R$ {inss} + ICMS R$ {icms} + ISS R$ {iss} = R$ {das_total}",
            lei="LC 123/2006, Art. 18-A, § 3º | Resolução CGSN nº 140/2018",
        )

        return {
            "INSS":      inss,
            "ICMS":      icms,
            "ISS":       iss,
            "DAS_TOTAL": das_total,
        }

    def _verificar_teto(self, receita_acumulada_ano: Decimal) -> None:
        """
        Verifica se a receita acumulada no ano excede o teto MEI.
        Alerta na trilha se excedido — NÃO bloqueia o cálculo.
        LC 123/2006, Art. 18-A, caput — teto R$ 81.000/ano.
        """
        if receita_acumulada_ano > TETO_ANUAL_MEI:
            excesso = (receita_acumulada_ano - TETO_ANUAL_MEI).quantize(
                Decimal("0.01"), ROUND_HALF_UP
            )
            evento = {
                "tipo": "ALERTA_MEI_TETO",
                "id": "ALERTA_TETO_MEI",
                "titulo": "Teto Anual MEI Excedido",
                "detalhe": (
                    f"Receita acumulada R$ {receita_acumulada_ano:,.2f} "
                    f"excede o teto de R$ 81.000,00 em R$ {excesso:,.2f}. "
                    f"Empresa deve migrar de regime (LC 123/2006, Art. 18-A, caput)."
                ),
                "amparo_legal": "LC 123/2006, Art. 18-A, caput",
                "receita_acumulada": str(receita_acumulada_ano),
                "teto": str(TETO_ANUAL_MEI),
                "excesso": str(excesso),
            }
            self.trilha.append(evento)

    def calcular_carga_total_mensal(
        self,
        receita_mensal: Decimal,
        categoria: str,
        receita_acumulada_ano: Decimal = Decimal("0.00"),
    ) -> Dict[str, Any]:
        """
        Carga tributária total mensal MEI.
        Retorna DAS breakdown + alíquota efetiva + credito_iva = R$ 0,00.

        Parâmetros:
          receita_mensal       — receita do mês para cálculo de alíquota efetiva
          categoria            — COMERCIO | INDUSTRIA | SERVICOS | COMERCIO_SERVICOS
          receita_acumulada_ano — acumulado para verificação de teto (default 0)
        """
        # Verificar teto antes do cálculo (alerta não-bloqueante)
        self._verificar_teto(receita_acumulada_ano)

        # Calcular DAS
        das = self.calcular_das_mensal(categoria)

        # Alíquota efetiva = DAS / receita mensal
        aliquota_efetiva = (
            (das["DAS_TOTAL"] / receita_mensal).quantize(Decimal("0.000001"), ROUND_HALF_UP)
            if receita_mensal > Decimal("0")
            else Decimal("0.000000")
        )

        self._registrar_passo(
            id="CARGA_TOTAL_MEI",
            titulo="Carga Total Mensal — MEI",
            base=f"Receita Mensal R$ {receita_mensal:,.2f}",
            deducoes="DAS Unificado (INSS + ICMS/ISS) — sem crédito IVA para tomadores",
            aliquota=f"AE efetiva {aliquota_efetiva*100:.4f}%",
            valor=f"R$ {das['DAS_TOTAL']:,.2f}",
            lei="LC 123/2006, Art. 18-A | LC 214/2025, Art. 4º",
        )

        return {
            "regime": "MEI",
            "categoria": categoria,
            "receita_mensal": receita_mensal,
            "breakdown": {
                "INSS": das["INSS"],
                "ICMS": das["ICMS"],
                "ISS":  das["ISS"],
            },
            "total_mensal":      das["DAS_TOTAL"],
            "aliquota_efetiva":  aliquota_efetiva,
            "credito_iva":       Decimal("0.00"),  # LC 214/2025, Art. 4º
            "nota": "MEI não gera crédito CBS/IBS para tomadores (LC 214/2025, Art. 4º).",
            "trilha_auditoria":  self.trilha,
        }
