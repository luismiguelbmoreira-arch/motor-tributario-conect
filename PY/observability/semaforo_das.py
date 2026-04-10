"""
semaforo_das.py — Crosscheck DAS calculado pelo motor vs DAS efetivamente pago.

Classifica a divergência em três níveis:
    - VERDE:    |Δ| ≤ 0.5%   — arredondamento aceitável
    - AMARELO:  0.5% < |Δ| ≤ 5%  — divergência pequena, verificar período
    - VERMELHO: |Δ| > 5%     — divergência grave, erro de contador OU de motor

Amparo: LC 123/2006 Art. 21 — DAS deve refletir apuração mensal correta.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import Any


class SemaforoDAS(str, Enum):
    VERDE = "verde"
    AMARELO = "amarelo"
    VERMELHO = "vermelho"


_TOL_VERDE = Decimal("0.005")    # 0.5%
_TOL_AMARELO = Decimal("0.05")   # 5%

_INTERPRETACAO = {
    SemaforoDAS.VERDE: (
        "Divergencia dentro da tolerancia (<=0.5%) — "
        "arredondamento ou diferenca centavos, aceitavel."
    ),
    SemaforoDAS.AMARELO: (
        "Divergencia pequena (0.5% a 5%) — verificar se o PDF e-CAC eh do mesmo "
        "periodo ou se ha exclusao de ICMS-ST nao contabilizada."
    ),
    SemaforoDAS.VERMELHO: (
        "Divergencia grave (>5%) — possivel erro de apuracao do contador ou "
        "receita omitida. Revisar PGDAS-D e cruzar com XML NFe do mes."
    ),
}


def avaliar(das_calculado: Decimal, das_pago: Decimal) -> dict[str, Any]:
    """
    Compara DAS calculado pelo motor com o DAS efetivamente pago.

    Args:
        das_calculado: saída do motor (MotorReformaTributaria)
        das_pago: valor extraído do PDF e-CAC ou informado pelo cliente

    Returns:
        dict com:
            - tipo: "SEMAFORO_DAS"
            - id: "SEMAFORO_DAS_CROSSCHECK"
            - semaforo: "verde" | "amarelo" | "vermelho"
            - das_calculado / das_pago (str)
            - delta_abs: diferença absoluta (str)
            - delta_pct: diferença percentual (str)
            - interpretacao: texto humano
            - amparo_legal: LC 123/2006 Art. 21
    """
    das_calc = Decimal(das_calculado).quantize(Decimal("0.01"), ROUND_HALF_UP)
    das_pg = Decimal(das_pago).quantize(Decimal("0.01"), ROUND_HALF_UP)

    delta_abs = (das_pg - das_calc).copy_abs()

    # Casos extremos: DAS calculado zero
    if das_calc == 0:
        if das_pg == 0:
            semaforo = SemaforoDAS.VERDE
            delta_pct = Decimal("0")
        else:
            semaforo = SemaforoDAS.VERMELHO
            delta_pct = Decimal("100")
    else:
        delta_pct_raw = delta_abs / das_calc
        delta_pct = (delta_pct_raw * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)

        if delta_pct_raw <= _TOL_VERDE:
            semaforo = SemaforoDAS.VERDE
        elif delta_pct_raw <= _TOL_AMARELO:
            semaforo = SemaforoDAS.AMARELO
        else:
            semaforo = SemaforoDAS.VERMELHO

    return {
        "tipo": "SEMAFORO_DAS",
        "id": "SEMAFORO_DAS_CROSSCHECK",
        "titulo": f"Crosscheck DAS calculado vs pago — {semaforo.value.upper()}",
        "semaforo": semaforo.value,
        "memoria": {
            "das_calculado": str(das_calc),
            "das_pago": str(das_pg),
            "delta_abs": str(delta_abs),
            "delta_pct": str(delta_pct),
        },
        "interpretacao": _INTERPRETACAO[semaforo],
        "amparo_legal": "LC 123/2006, Art. 21 — apuracao mensal do DAS unificado",
    }
