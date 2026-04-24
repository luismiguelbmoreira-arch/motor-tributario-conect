"""
recomendacoes_optout.py — Lógica de recomendação Opt-Out extraída do MotorReformaTributaria.
LC 214/2025 Arts. 41-44 | Res. CGSN 183/2025
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict


def _fmt_brl(valor: Any) -> str:
    try:
        d = Decimal(str(valor or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except Exception:
        return "R$ 0,00"
    return f"R$ {d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar_recomendacao_opt_out(
    percentual_b2b: Decimal,
    disparidade_anual: Decimal,
    rbt12: Decimal,
) -> Dict[str, str]:
    """
    Recomendação inteligente de Opt-Out cruzando:
      - percentual_b2b: peso comercial (clientes que perderiam crédito)
      - disparidade_anual / rbt12: custo relativo de sair do Simples Puro
      - threshold absoluto: R$ 6.000/ano separa impacto alto de baixo
    """
    rbt12_val = rbt12 or Decimal("1")

    razao_disparidade = (abs(disparidade_anual) / rbt12_val * Decimal("100")).quantize(
        Decimal("0.01"), ROUND_HALF_UP
    )

    THRESHOLD_CUSTO_ABSOLUTO_ANUAL = Decimal("6000.00")
    custo_alto_absoluto = abs(disparidade_anual) > THRESHOLD_CUSTO_ABSOLUTO_ANUAL

    razao_pct_str = f"{razao_disparidade:.2f}".replace(".", ",")
    b2b_str = f"{percentual_b2b:.0f}"

    if percentual_b2b >= Decimal("70") and razao_disparidade <= Decimal("5"):
        if custo_alto_absoluto:
            codigo = "OPT_OUT_CONDICIONAL"
            titulo = "OPT-OUT CONDICIONAL — só com repasse de preço"
            justificativa = (
                f"Você tem {b2b_str}% de clientes B2B (empresas que precisam de "
                f"crédito de CBS/IBS para abater dos próprios impostos). O Opt-Out "
                f"traria competitividade comercial, MAS o custo extra é "
                f"{_fmt_brl(disparidade_anual)}/ano ({razao_pct_str}% da receita) — "
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
                f"é {_fmt_brl(disparidade_anual)} ({razao_pct_str}% da receita), valor baixo "
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
            f"Opt-Out é {_fmt_brl(disparidade_anual)} ({razao_pct_str}% da receita). Avalie "
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
            f"{_fmt_brl(disparidade_anual)} sem trazer benefício comercial. Mantenha o "
            f"regime atual e reavalie apenas se o perfil de clientes mudar."
        )
    else:
        codigo = "ZONA_CINZA"
        titulo = "ZONA CINZA — análise individual necessária"
        justificativa = (
            f"Seu caso está numa faixa intermediária: {b2b_str}% de clientes B2B com "
            f"custo anual de Opt-Out de {_fmt_brl(disparidade_anual)} ({razao_pct_str}% da "
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
