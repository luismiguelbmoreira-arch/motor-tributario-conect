"""
formatadores.py — Utilitários de formatação compartilhados pelo motor.
Fonte única de verdade para _fmt_brl (consolidação pós-V-08/V-02).
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def _fmt_brl(valor: Any) -> str:
    """
    Formata valor monetário no padrão BR: R$ X.XXX,YY.

    V-02 fix: evita o idiom tóxico `valor or 0` — `Decimal("0.00") or 0`
    retorna `int(0)` (falsy) e perde casas decimais antes do quantize.
    Usa `valor if valor is not None else Decimal("0")`.
    """
    try:
        base = valor if valor is not None else Decimal("0")
        d = Decimal(str(base)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except Exception:
        return "R$ 0,00"
    return f"R$ {d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
