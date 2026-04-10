"""
anomalias.py — Regras Akita de detecção de padrões suspeitos.

Cada regra é uma função pura que recebe dados e retorna:
    - None  → nada a reportar
    - dict  → evento tipo ALERTA_ANOMALIA_* para anexar à trilha

A funcao `detectar()` roda todas as regras e devolve a lista de alertas.
Caller tipico: `mesclar_fontes_documentais()` em extrator_pdfs.py.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional


# Limiares (ajustaveis apos observacao de producao)
_RBT12_VS_RPA_LIMITE = Decimal("20")   # RBT12 > 20x RPA medio
_CONFIANCA_OCR_LIMIAR = 0.75           # Claude Vision abaixo disso
_FOLHA_VS_RBT12_LIMITE = Decimal("1")  # folha 12m > 100% do RBT12
_PIS_DIVERGENCIA_LIMITE = Decimal("0.05")  # 5% entre SPED EFD e NFe


def _timestamp() -> str:
    return datetime.now().isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# REGRAS
# ─────────────────────────────────────────────────────────────────────────────

def rbt12_vs_rpa(rbt12: Decimal, rpa_mensal: Decimal) -> Optional[dict[str, Any]]:
    """
    Dispara se RBT12 > 20 × RPA (receita mensal média).

    Interpretacao: ou a empresa teve queda brutal recente, ou RBT12 foi
    extraido errado do PGDAS-D. Exige revisao humana.
    """
    if rpa_mensal <= 0:
        return None
    if rbt12 <= 0:
        return None

    razao = rbt12 / rpa_mensal
    if razao <= _RBT12_VS_RPA_LIMITE:
        return None

    return {
        "tipo": "ALERTA_ANOMALIA_RBT12_DESPROPORCIONAL",
        "id": "ANOMALIA_RBT12_VS_RPA",
        "titulo": "RBT12 despropor cional ao RPA mensal",
        "memoria": {
            "rbt12": str(rbt12),
            "rpa_mensal": str(rpa_mensal),
            "razao": str(razao.quantize(Decimal("0.01"))),
            "limite": str(_RBT12_VS_RPA_LIMITE),
        },
        "interpretacao": (
            f"RBT12 R$ {rbt12:,.2f} eh {razao:.1f}x o RPA mensal R$ {rpa_mensal:,.2f}. "
            "Ou a empresa teve queda brutal, ou ha erro de extracao. Revisar."
        ),
        "amparo_legal": "LC 123/2006, Art. 3 §2 — base RBT12 mensal",
        "timestamp": _timestamp(),
    }


def confianca_extracao_baixa(
    confianca: float, limiar: float = _CONFIANCA_OCR_LIMIAR
) -> Optional[dict[str, Any]]:
    """
    Dispara se confianca do Claude Vision < limiar (default 0.75).

    Interpretacao: PDF com scan ruim, carimbo cobrindo valor, ou layout
    atipico. Extracao pode ter campo errado. Exige revisao humana.
    """
    if confianca >= limiar:
        return None

    return {
        "tipo": "ALERTA_ANOMALIA_OCR_BAIXA_CONFIANCA",
        "id": "ANOMALIA_CONFIANCA_EXTRACAO",
        "titulo": "Claude Vision com confianca baixa na extracao",
        "memoria": {
            "confianca": f"{confianca:.2f}",
            "limiar": f"{limiar:.2f}",
        },
        "interpretacao": (
            f"Confianca da extracao ({confianca:.0%}) abaixo do limiar ({limiar:.0%}). "
            "PDF pode ter scan ruim ou layout atipico. Recomenda revisao manual dos campos."
        ),
        "amparo_legal": "LGPD Art. 20 — direito a revisao de decisoes automatizadas",
        "timestamp": _timestamp(),
    }


def folha_inconsistente(
    folha_12m: Decimal, rbt12: Decimal
) -> Optional[dict[str, Any]]:
    """
    Dispara se folha_12m > 100% do RBT12.

    Interpretacao: quase sempre erro de separador decimal (virgula vs ponto)
    ou o CSV tem valores em centavos. Impossivel matematicamente para
    empresa ativa pagar mais em folha do que fatura.
    """
    if folha_12m <= 0 or rbt12 <= 0:
        return None

    if folha_12m <= rbt12 * _FOLHA_VS_RBT12_LIMITE:
        return None

    razao = folha_12m / rbt12
    return {
        "tipo": "ALERTA_ANOMALIA_FOLHA_IMPOSSIVEL",
        "id": "ANOMALIA_FOLHA_VS_RBT12",
        "titulo": "Folha maior que faturamento — provavel erro de separador decimal",
        "memoria": {
            "folha_12m": str(folha_12m),
            "rbt12": str(rbt12),
            "razao": str(razao.quantize(Decimal("0.01"))),
        },
        "interpretacao": (
            f"Folha R$ {folha_12m:,.2f} eh {razao:.1f}x o RBT12 R$ {rbt12:,.2f}. "
            "Impossivel — verificar separador decimal do CSV de folha (virgula vs ponto) "
            "ou se os valores nao estao em centavos."
        ),
        "amparo_legal": "LC 123/2006, Art. 18 §24 — Fator R exige folha real",
        "timestamp": _timestamp(),
    }


def crosscheck_pis_cofins_sped_vs_nfe(
    pis_sped: Decimal, pis_nfe: Decimal, tributo: str = "PIS"
) -> Optional[dict[str, Any]]:
    """
    Dispara se |PIS SPED - PIS NFe| / PIS NFe > 5%.

    Detecta subdeclaracao de PIS/COFINS: SPED EFD-Contribuicoes do Dominio
    tem valor diferente do que as NFes somariam. Pode indicar omissao de
    receita ou erro de escrituracao.
    """
    if pis_nfe <= 0:
        return None

    delta = (pis_sped - pis_nfe).copy_abs()
    razao = delta / pis_nfe

    if razao <= _PIS_DIVERGENCIA_LIMITE:
        return None

    return {
        "tipo": f"ALERTA_ANOMALIA_{tributo}_DIVERGENTE_SPED_NFE",
        "id": f"ANOMALIA_CROSSCHECK_{tributo}",
        "titulo": f"{tributo} do SPED EFD diverge do XML NFe",
        "memoria": {
            f"{tributo.lower()}_sped": str(pis_sped),
            f"{tributo.lower()}_nfe": str(pis_nfe),
            "delta_pct": str((razao * 100).quantize(Decimal("0.01"))),
        },
        "interpretacao": (
            f"{tributo} declarado no SPED EFD R$ {pis_sped:,.2f} diverge do somado "
            f"nas NFes R$ {pis_nfe:,.2f} em {razao:.1%}. "
            "Possivel subdeclaracao ou erro de escrituracao."
        ),
        "amparo_legal": "Lei 10.637/2002 (PIS) + Lei 10.833/2003 (COFINS)",
        "timestamp": _timestamp(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────

def detectar(
    rbt12: Optional[Decimal] = None,
    rpa_mensal: Optional[Decimal] = None,
    folha_12m: Optional[Decimal] = None,
    confianca_extracao: Optional[float] = None,
    pis_sped: Optional[Decimal] = None,
    pis_nfe: Optional[Decimal] = None,
    cofins_sped: Optional[Decimal] = None,
    cofins_nfe: Optional[Decimal] = None,
) -> list[dict[str, Any]]:
    """
    Roda todas as regras aplicaveis e retorna lista de alertas.

    Cada parametro eh opcional — regra cujo input eh None simplesmente
    nao roda. Chamador passa so os dados que tem.
    """
    alertas: list[dict[str, Any]] = []

    if rbt12 is not None and rpa_mensal is not None:
        alerta = rbt12_vs_rpa(rbt12, rpa_mensal)
        if alerta:
            alertas.append(alerta)

    if folha_12m is not None and rbt12 is not None:
        alerta = folha_inconsistente(folha_12m, rbt12)
        if alerta:
            alertas.append(alerta)

    if confianca_extracao is not None:
        alerta = confianca_extracao_baixa(confianca_extracao)
        if alerta:
            alertas.append(alerta)

    if pis_sped is not None and pis_nfe is not None:
        alerta = crosscheck_pis_cofins_sped_vs_nfe(pis_sped, pis_nfe, "PIS")
        if alerta:
            alertas.append(alerta)

    if cofins_sped is not None and cofins_nfe is not None:
        alerta = crosscheck_pis_cofins_sped_vs_nfe(cofins_sped, cofins_nfe, "COFINS")
        if alerta:
            alertas.append(alerta)

    return alertas
