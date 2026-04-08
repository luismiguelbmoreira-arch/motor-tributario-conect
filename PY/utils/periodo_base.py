"""
periodo_base.py — Calculadora pura de período-base para análise fiscal.

Dado um ano-alvo (ex: 2026) e opcionalmente um mês-corte (default 12),
deriva a janela de 12 meses imediatamente anteriores que alimenta o RBT12,
o DAS de referência e o exercício SPED.

Regra:
    - Padrão dezembro/anual: ano_alvo=2026, mes_corte=12
        → RBT12 = 2025-01..2025-12
        → DAS ref = 2025-12
        → exercício SPED = 2025
    - Intra-ano: ano_alvo=2026, mes_corte=3
        → RBT12 = 2025-04..2026-03 (12 meses retroativos)
        → DAS ref = 2026-02 (último mês fechado antes do corte)
        → exercício SPED = 2025 (último exercício fechado)

Amparo legal:
    LC 123/2006 Art. 3º, §1º — definição de RBT12 (12 meses imediatamente anteriores)
    LC 123/2006 Art. 18, §1º — Alíquota Efetiva calculada sobre RBT12
    MAX_FISCAL_03 (CLAUDE.md) — declarar a data base ANTES do cálculo

Sem I/O. Sem Decimal. Função pura.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

ANO_MIN = 2026
ANO_MAX = 2033


@dataclass(frozen=True)
class PeriodoBase:
    """
    Janela de período-base derivada de (ano_alvo, mes_corte).

    Campos imutáveis (frozen). Datas em formato ISO `YYYY-MM` para round-trip
    com `database.validar_competencia()`.
    """

    ano_alvo: int
    mes_corte: int
    rbt12_inicio: str       # ex: "2025-01"
    rbt12_fim: str          # ex: "2025-12"
    das_referencia: str     # ex: "2025-12"
    exercicio_sped: int     # ex: 2025
    label_humano: str       # ex: "Ano-base 2025 (corte 31/12/2025)"

    def to_dict(self) -> dict:
        """Serialização JSON-friendly (usada pelo endpoint REST)."""
        return asdict(self)


def derivar(ano_alvo: int, mes_corte: int = 12) -> PeriodoBase:
    """
    Deriva o período-base a partir do ano-alvo da análise.

    Args:
        ano_alvo: ano calendário da análise (2026..2033, faixa do cronograma IVA).
        mes_corte: mês do "fechamento" da análise (1..12). Default 12 = corte anual.

    Returns:
        PeriodoBase com janela RBT12, DAS de referência, exercício SPED e label humano.

    Raises:
        ValueError: ano_alvo fora da faixa [2026, 2033] ou mes_corte fora de [1, 12].
    """
    if not (ANO_MIN <= ano_alvo <= ANO_MAX):
        raise ValueError(
            f"ano_alvo deve estar entre {ANO_MIN} e {ANO_MAX} "
            f"(cronograma IVA EC 132/2023). Recebido: {ano_alvo}"
        )
    if not (1 <= mes_corte <= 12):
        raise ValueError(f"mes_corte deve estar entre 1 e 12. Recebido: {mes_corte}")

    if mes_corte == 12:
        # Caso padrão: corte anual em 31/dez do ano anterior
        ano_base = ano_alvo - 1
        rbt12_inicio = f"{ano_base}-01"
        rbt12_fim = f"{ano_base}-12"
        das_referencia = f"{ano_base}-12"
        exercicio_sped = ano_base
        label = f"Ano-base {ano_base} (corte 31/12/{ano_base})"
    else:
        # Caso intra-ano: janela móvel de 12 meses retroativa ao mes_corte
        # Ex: ano_alvo=2026, mes_corte=3 → 2025-04..2026-03
        fim_mes = mes_corte
        fim_ano = ano_alvo
        # Início = 12 meses antes do fim (inclusive). fim - 11 meses.
        inicio_mes = fim_mes + 1
        inicio_ano = fim_ano - 1
        if inicio_mes > 12:
            inicio_mes -= 12
            inicio_ano += 1
        rbt12_inicio = f"{inicio_ano}-{inicio_mes:02d}"
        rbt12_fim = f"{fim_ano}-{fim_mes:02d}"

        # DAS de referência: último mês fechado antes do corte
        # Ex: corte em mes_corte=3 → DAS de fevereiro (mes_corte - 1)
        das_mes = mes_corte - 1
        das_ano = ano_alvo
        if das_mes == 0:
            das_mes = 12
            das_ano -= 1
        das_referencia = f"{das_ano}-{das_mes:02d}"

        # Exercício SPED = último exercício fechado (ano anterior ao corte)
        exercicio_sped = ano_alvo - 1
        label = (
            f"Janela móvel {rbt12_inicio} a {rbt12_fim} "
            f"(corte {mes_corte:02d}/{ano_alvo})"
        )

    return PeriodoBase(
        ano_alvo=ano_alvo,
        mes_corte=mes_corte,
        rbt12_inicio=rbt12_inicio,
        rbt12_fim=rbt12_fim,
        das_referencia=das_referencia,
        exercicio_sped=exercicio_sped,
        label_humano=label,
    )
