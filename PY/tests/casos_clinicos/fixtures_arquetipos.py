"""
fixtures_arquetipos.py — 5 arquétipos do checklist (PDF 28/04/2026).

Cada arquétipo é uma factory function que constrói uma instância de
HistoricoSeisMeses representativa do perfil. Factory em vez de instância
estática pra (a) suportar variações (sazonalidade ON/OFF, faturamento ±20%)
e (b) lazy import — não quebra import se o schema ainda não existe.

Curador: Caso-Clínico (.claude/agents/caso-clinico.md)
Blueprint: ~/.claude/plans/blueprint-historico-seis-meses-corrigido.md

ATENÇÃO — todos os CNPJs e razões sociais são FICTÍCIOS.
Sem dado real de cliente. Tudo plausível mas inventado.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal


def arquetipo_3_misto_5050():
    """
    Arquétipo 3 — Misto 50/50 (Padaria com B2B + B2C).

    Perfil do PDF (página 4):
        Padaria que vende balcão (B2C) e atende restaurantes (B2B).
        Distribuidora pequena. Faturamento ~R$ 2M/ano.

    Hipótese inicial do PDF:
        Caso limítrofe. Conta precisa ser feita com rigor — depende do
        peso real de cada lado e da composição de despesa.

    Características modeladas:
        - 6 meses: novembro/2025 a abril/2026
        - Anexo I (comércio — CNAE 4721102 "Padaria e confeitaria com
          predominância de revenda", balcão B2C + entrega B2B restaurantes)
        - Sazonalidade dezembro +33% (panetones, ceia)
        - Mix 50/50 B2B (restaurantes) + B2C (balcão)
        - Folha 12m ~R$ 348k (4 funcionários CLT + pró-labore)
        - Fator R ~0.17 (não aplica em Anexo I, mas campo é obrigatório)

    Por que esse arquétipo é crítico:
        Misto 50/50 é onde motor erra mais — explicitado no PDF e no
        CLAUDE.md. Se este arquétipo virar verde no diagnóstico, os outros
        4 (que são casos de borda em vez de centro) ficam mais fáceis.
    """
    # Lazy import — só carrega quando função é chamada (TDD friendly)
    from schemas.historico_seis_meses import (
        HistoricoSeisMeses,
        MesFiscal,
        OperacaoMensal,
    )

    # CNAE 4721102 — "Padaria e confeitaria com predominância de revenda".
    # Resolve pra Anexo I em regras_cnae.py (comércio varejista). É o CNAE
    # típico da padaria de bairro com balcão B2C + entrega B2B pra restaurantes.
    # Diferencia de 1091102 ("Fabricação produtos panificação industrial",
    # Anexo II) usado por padarias industriais grandes — não é nosso caso.
    cnae_padaria = "4721102"

    def _mes(
        competencia: str,
        rbt12: str,
        faturamento: str,
        folha_mes: str,
        folha_12m: str,
        fator_r: str,
    ) -> "MesFiscal":
        """Helper pra reduzir verbosidade — gera mês com mix 50/50 padrão."""
        meio_faturamento = Decimal(faturamento) / 2
        return MesFiscal(
            competencia=competencia,
            rbt12_declarado=Decimal(rbt12),
            faturamento_mes=Decimal(faturamento),
            folha_pagamento_mes=Decimal(folha_mes),
            folha_12m=Decimal(folha_12m),
            anexo_aplicado="I",
            fator_r_calculado=Decimal(fator_r),
            operacoes=[
                OperacaoMensal(
                    tipo="VENDA_B2C",
                    valor_total=meio_faturamento,
                    quantidade_notas=int(meio_faturamento / Decimal("45")),  # ticket médio R$ 45 balcão
                    cnae_predominante=cnae_padaria,
                    uf_destino="SP",
                    forma_recebimento="PIX_DIRETO",
                ),
                OperacaoMensal(
                    tipo="VENDA_B2B",
                    valor_total=meio_faturamento,
                    quantidade_notas=12,  # ~12 restaurantes clientes/mês
                    cnae_predominante=cnae_padaria,
                    uf_destino="SP",
                    forma_recebimento="BOLETO",
                ),
            ],
        )

    return HistoricoSeisMeses(
        cnpj="54657895000160",
        razao_social="Padaria Doce Manhã LTDA",
        regime_atual="SIMPLES",
        tipo_societario="ME",
        competencia_referencia=date(2026, 4, 30),
        meses=[
            # nov/2025 — pré-natal, vendas estáveis
            _mes(
                competencia="2025-11",
                rbt12="1980000.00",
                faturamento="165000.00",
                folha_mes="28000.00",
                folha_12m="336000.00",
                fator_r="0.1697",
            ),
            # dez/2025 — pico (panetones, ceia, presentes corporativos)
            _mes(
                competencia="2025-12",
                rbt12="2035000.00",  # +55k vs nov (entrou nov/25 165k, saiu nov/24 ~110k)
                faturamento="220000.00",  # +33% sazonal
                folha_mes="30000.00",  # 13º proporcional
                folha_12m="348000.00",
                fator_r="0.1710",
            ),
            # jan/2026 — ressaca pós-festas
            _mes(
                competencia="2026-01",
                rbt12="2040000.00",  # +5k vs dez (entrou dez/25 220k, saiu dez/24 ~215k)
                faturamento="150000.00",  # -32% vs dez
                folha_mes="28000.00",
                folha_12m="348000.00",
                fator_r="0.1706",
            ),
            # fev/2026 — mês curto + carnaval
            _mes(
                competencia="2026-02",
                rbt12="2025000.00",  # -15k (saiu jan/25 estimado 165k > entrou jan/26 150k)
                faturamento="145000.00",
                folha_mes="28000.00",
                folha_12m="348000.00",
                fator_r="0.1719",
            ),
            # mar/2026 — volta ao normal
            _mes(
                competencia="2026-03",
                rbt12="2025000.00",  # estável
                faturamento="165000.00",
                folha_mes="28000.00",
                folha_12m="348000.00",
                fator_r="0.1719",
            ),
            # abr/2026 — leve crescimento
            _mes(
                competencia="2026-04",
                rbt12="2030000.00",  # +5k
                faturamento="170000.00",
                folha_mes="28000.00",
                folha_12m="348000.00",
                fator_r="0.1714",
            ),
        ],
    )


# Stub das outras 4 fixtures — implementadas após Misto 50/50 virar verde
def arquetipo_1_b2c_puro():
    raise NotImplementedError("Pendente após Arquétipo 3 (Misto 50/50) virar verde")


def arquetipo_2_b2b_anexo_iii_fator_r():
    raise NotImplementedError("Pendente após Arquétipo 3 (Misto 50/50) virar verde")


def arquetipo_4_b2b_anexo_v():
    raise NotImplementedError("Pendente após Arquétipo 3 (Misto 50/50) virar verde")


def arquetipo_5_proximo_sublimite():
    raise NotImplementedError("Pendente após Arquétipo 3 (Misto 50/50) virar verde")
