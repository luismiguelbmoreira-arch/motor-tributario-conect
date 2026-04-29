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


def arquetipo_1_b2c_puro():
    """
    Arquétipo 1 — B2C puro alto volume com PICO SAZONAL (Boutique Encanto Natal).

    Perfil do PDF (página 2):
        Comércio varejista, restaurante, clínica de estética. Faturamento
        ~R$ 3M/ano. 100% pessoa física como cliente.

    Características modeladas (parâmetros cravados por Luiz Moreira em 28/04/2026):
        - CNAE 4781400 "Comércio varejista de artigos do vestuário e acessórios"
        - Anexo I (comércio) — Fator R não aplica (LC 123/2006 Art. 18 §5º-J)
        - 100% VENDA_B2C, predominância CARTAO_CREDITO (varejo Natal/Black Friday)
        - 6 meses: nov/2025 a abr/2026
        - Sazonalidade DEZEMBRO = 5× média dos outros 5 meses (R$ 375k vs R$ 75k)
        - Folha estável ~R$ 8.500/mês + 1 sazonal em dezembro
        - RBT12 cresce ao incorporar dezembro/2025 (~R$ 1M → R$ 1.33M)

    Por que esse arquétipo é crítico:
        Cobre o cenário 5 do blueprint do DiagnosticoConsolidado — sazonalidade
        detectada com mes_pico contendo "12". Razão pico/média = 5.0× (acima de
        qualquer threshold razoável: CoV > 0.25 + ratio_max/mediana > 1.5).
    """
    from schemas.historico_seis_meses import (
        HistoricoSeisMeses,
        MesFiscal,
        OperacaoMensal,
    )

    cnae_varejo_vestuario = "4781400"

    def _mes(competencia, rbt12, faturamento, folha_mes, folha_12m, fator_r, qtd_notas):
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
                    valor_total=Decimal(faturamento),
                    quantidade_notas=qtd_notas,
                    cnae_predominante=cnae_varejo_vestuario,
                    uf_destino="SP",
                    forma_recebimento="CARTAO_CREDITO",  # Varejo natalino
                ),
            ],
        )

    return HistoricoSeisMeses(
        cnpj="11222333000181",  # Mod-11 validado
        razao_social="Boutique Encanto Natal LTDA",
        regime_atual="SIMPLES",
        tipo_societario="EPP",
        competencia_referencia=date(2026, 4, 30),
        meses=[
            # nov/2025 — pré-Natal (vendas começam a subir)
            _mes("2025-11", "980000.00", "75000.00", "8500.00", "102000.00", "0.1041", 1500),
            # dez/2025 — PICO (Black Friday + Natal): 5× a média mensal
            _mes("2025-12", "1030000.00", "375000.00", "12000.00", "105500.00", "0.1024", 6800),
            # jan/2026 — ressaca pós-festas
            _mes("2026-01", "1330000.00", "70000.00", "8500.00", "105500.00", "0.0793", 1400),
            # fev/2026 — mês curto + carnaval
            _mes("2026-02", "1325000.00", "72000.00", "8500.00", "105500.00", "0.0796", 1450),
            # mar/2026 — outono começa, vendas estáveis
            _mes("2026-03", "1322000.00", "78000.00", "8500.00", "105500.00", "0.0798", 1550),
            # abr/2026 — leve crescimento (Dia das Mães em maio cria expectativa)
            _mes("2026-04", "1325000.00", "80000.00", "8500.00", "105500.00", "0.0796", 1600),
        ],
    )


def arquetipo_2_b2b_anexo_iii_fator_r():
    """
    Arquétipo 2 — B2B Anexo III com Fator R OSCILANTE (Vértice Consultoria & TI).

    Perfil do PDF (página 3):
        Consultoria, escritório de TI, agência. Faturamento ~R$ 3M/ano.
        100% PJ como cliente. Folha relevante (>28% da receita).

    Características modeladas (parâmetros cravados por Luiz Moreira):
        - CNAE 6201500 "Desenvolvimento de programas de computador sob encomenda"
        - LC 123/2006 Art. 18 §5º-M, I — vai pra Anexo III SE Fator R ≥ 0.28,
          ELSE Anexo V (oscilação cara — economia de ~9pp na alíquota nominal)
        - 100% VENDA_B2B, predominância BOLETO (contratos PJ-PJ, prazo 30d)
        - 6 meses: nov/2025 a abr/2026
        - Folha 12m oscila R$ 786k a R$ 810k (mistura CLT + freelancers PJ)
        - 5 atravessamentos da fronteira 0.28 (alterna III ↔ V mensalmente)

    Por que esse arquétipo é crítico:
        Cobre o cenário 3 do blueprint — ≥2 alertas FATOR_R_ATRAVESSOU_028.
        Aqui produzimos 5 alertas (todos os meses 2..6 cruzaram a fronteira).
    """
    from schemas.historico_seis_meses import (
        HistoricoSeisMeses,
        MesFiscal,
        OperacaoMensal,
    )

    cnae_dev_software = "6201500"

    def _mes(competencia, rbt12, faturamento, folha_mes, folha_12m, anexo, fator_r):
        return MesFiscal(
            competencia=competencia,
            rbt12_declarado=Decimal(rbt12),
            faturamento_mes=Decimal(faturamento),
            folha_pagamento_mes=Decimal(folha_mes),
            folha_12m=Decimal(folha_12m),
            anexo_aplicado=anexo,
            fator_r_calculado=Decimal(fator_r),
            operacoes=[
                OperacaoMensal(
                    tipo="VENDA_B2B",
                    valor_total=Decimal(faturamento),
                    quantidade_notas=8,  # ~8 contratos B2B/mês
                    cnae_predominante=cnae_dev_software,
                    uf_destino="SP",
                    forma_recebimento="BOLETO",
                ),
            ],
        )

    return HistoricoSeisMeses(
        cnpj="22333444000181",  # Mod-11 validado
        razao_social="Vértice Consultoria & TI LTDA",
        regime_atual="SIMPLES",
        tipo_societario="EPP",
        competencia_referencia=date(2026, 4, 30),
        meses=[
            # nov/2025 — Fator R 0.2850 (≥0.28 → Anexo III)
            _mes("2025-11", "2800000.00", "235000.00", "68000.00", "798000.00", "III", "0.2850"),
            # dez/2025 — Fator R cai pra 0.2787 (<0.28 → Anexo V) — atravessamento 1
            _mes("2025-12", "2820000.00", "240000.00", "60000.00", "786000.00", "V", "0.2787"),
            # jan/2026 — Fator R volta pra 0.2845 (≥0.28 → Anexo III) — atravessamento 2
            _mes("2026-01", "2830000.00", "245000.00", "75000.00", "805000.00", "III", "0.2845"),
            # fev/2026 — Fator R cai pra 0.2785 (<0.28 → Anexo V) — atravessamento 3
            _mes("2026-02", "2840000.00", "248000.00", "62000.00", "791000.00", "V", "0.2785"),
            # mar/2026 — Fator R sobe pra 0.2842 (≥0.28 → Anexo III) — atravessamento 4
            _mes("2026-03", "2850000.00", "250000.00", "76000.00", "810000.00", "III", "0.2842"),
            # abr/2026 — Fator R cai pra 0.2790 (<0.28 → Anexo V) — atravessamento 5
            _mes("2026-04", "2860000.00", "252000.00", "65000.00", "798000.00", "V", "0.2790"),
        ],
    )


def arquetipo_4_b2b_anexo_v():
    """
    Arquétipo 4 — B2B Anexo V faixa alta com mix 60/40 (Aço Forte Engenharia).

    Perfil do PDF (página 5):
        Engenharia, advocacia complexa, arquitetura, auditoria. Faturamento
        ~R$ 4M+. Folha baixa relativa à receita. Margem alta.

    Características modeladas (parâmetros cravados por Luiz Moreira):
        - CNAE 7112000 "Serviços de engenharia"
        - LC 123/2006 Art. 18 §5º-I, XII — engenharia listada na LC 155/2016
        - Anexo V em todos os meses (Fator R ~0.097 << 0.28)
        - Mix 60% VENDA_B2B (incorporadoras/construtoras) + 40% VENDA_B2C
          (autônomos pessoa física construindo galpão particular)
        - B2B → BOLETO (contratos prazo); B2C → PIX_DIRETO (pessoa física)
        - 6 meses: nov/2025 a abr/2026
        - RBT12 já acima de R$ 3.6M (paga ICMS/ISS por fora — Art. 13-A)

    Por que esse arquétipo é crítico:
        Cobre o cenário 4 do blueprint — adapter calcula percentual_b2b ~60.
        Confirma que adapter consome operações reais (não chumba 100/0).
    """
    from schemas.historico_seis_meses import (
        HistoricoSeisMeses,
        MesFiscal,
        OperacaoMensal,
    )

    cnae_engenharia = "7112000"

    def _mes(competencia, rbt12, faturamento, folha_mes, folha_12m, fator_r):
        valor_b2b = Decimal(faturamento) * Decimal("0.6")
        valor_b2c = Decimal(faturamento) * Decimal("0.4")
        return MesFiscal(
            competencia=competencia,
            rbt12_declarado=Decimal(rbt12),
            faturamento_mes=Decimal(faturamento),
            folha_pagamento_mes=Decimal(folha_mes),
            folha_12m=Decimal(folha_12m),
            anexo_aplicado="V",
            fator_r_calculado=Decimal(fator_r),
            operacoes=[
                OperacaoMensal(
                    tipo="VENDA_B2B",
                    valor_total=valor_b2b,
                    quantidade_notas=4,  # ~4 incorporadoras/mês
                    cnae_predominante=cnae_engenharia,
                    uf_destino="SP",
                    forma_recebimento="BOLETO",
                ),
                OperacaoMensal(
                    tipo="VENDA_B2C",
                    valor_total=valor_b2c,
                    quantidade_notas=6,  # ~6 PFs/mês (galpões particulares)
                    cnae_predominante=cnae_engenharia,
                    uf_destino="SP",
                    forma_recebimento="PIX_DIRETO",
                ),
            ],
        )

    return HistoricoSeisMeses(
        cnpj="33444555000181",  # Mod-11 validado
        razao_social="Aço Forte Engenharia Estrutural LTDA",
        regime_atual="SIMPLES",
        tipo_societario="EPP",
        competencia_referencia=date(2026, 4, 30),
        meses=[
            _mes("2025-11", "3900000.00", "330000.00", "32000.00", "380000.00", "0.0974"),
            _mes("2025-12", "3950000.00", "340000.00", "33000.00", "385000.00", "0.0975"),
            _mes("2026-01", "3990000.00", "345000.00", "32500.00", "387000.00", "0.0970"),
            _mes("2026-02", "4020000.00", "350000.00", "33000.00", "388500.00", "0.0967"),
            _mes("2026-03", "4050000.00", "355000.00", "32500.00", "389000.00", "0.0961"),
            _mes("2026-04", "4080000.00", "360000.00", "33000.00", "390000.00", "0.0956"),
        ],
    )


def arquetipo_5_proximo_sublimite():
    """
    Arquétipo 5 — Próximo ao sublimite, cruza 90% no mês 5 (Distribuidora Trovão).

    Perfil do PDF (página 6):
        Empresa entre R$ 3M e R$ 4,5M de faturamento, B2B forte. Anda perto
        da fronteira do Simples — risco de exclusão.

    Características modeladas (parâmetros cravados por Luiz Moreira):
        - CNAE 4639701 "Comércio atacadista de produtos alimentícios em geral"
        - Anexo I (comércio puro)
        - 100% VENDA_B2B (pequenos mercados, padarias, restaurantes)
        - Predominância BOLETO (atacadista, prazo 30d)
        - 6 meses: nov/2025 a abr/2026 — RBT12 sobe progressivamente
        - Crescimento +R$ 170k/mês (entrou em rede nova de cliente em fev/2026)
        - Cruza 90% do teto Simples (R$ 4.32M = 0.90 × R$ 4.8M) NO MÊS 5

    Por que esse arquétipo é crítico:
        Cobre o cenário 2 do blueprint — RecomendacaoConsolidada.REVISAR_MANUALMENTE
        + NivelConfianca.BAIXA + alerta RBT12_90PCT_TETO. Rail R7 do plano
        (Opt-Out automático ≥ 90% do teto) é acionado nesta fixture.

        Empate evitado: mês 4 RBT12 = R$ 4.180k (96.7% de R$ 4.32M, NÃO dispara);
        mês 5 RBT12 = R$ 4.350k (≥ R$ 4.32M, DISPARA alerta).
    """
    from schemas.historico_seis_meses import (
        HistoricoSeisMeses,
        MesFiscal,
        OperacaoMensal,
    )

    cnae_atacadista_alimentos = "4639701"

    def _mes(competencia, rbt12, faturamento, folha_mes, folha_12m, fator_r):
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
                    tipo="VENDA_B2B",
                    valor_total=Decimal(faturamento),
                    quantidade_notas=45,  # atacado: várias pequenas operações
                    cnae_predominante=cnae_atacadista_alimentos,
                    uf_destino="SP",
                    forma_recebimento="BOLETO",
                ),
            ],
        )

    return HistoricoSeisMeses(
        cnpj="44555666000181",  # Mod-11 validado
        razao_social="Distribuidora Trovão Atacadista LTDA",
        regime_atual="SIMPLES",
        tipo_societario="EPP",
        competencia_referencia=date(2026, 4, 30),
        meses=[
            # nov/2025 — RBT12 R$ 3.85M (abaixo do gate 4.32M)
            _mes("2025-11", "3850000.00", "320000.00", "25000.00", "295000.00", "0.0766"),
            # dez/2025 — RBT12 R$ 3.92M (ainda abaixo)
            _mes("2025-12", "3920000.00", "340000.00", "26000.00", "298000.00", "0.0760"),
            # jan/2026 — RBT12 R$ 4.05M (ainda abaixo)
            _mes("2026-01", "4050000.00", "380000.00", "26000.00", "299000.00", "0.0738"),
            # fev/2026 — RBT12 R$ 4.18M (ainda abaixo do gate, 96.7% dele)
            _mes("2026-02", "4180000.00", "410000.00", "27000.00", "301000.00", "0.0720"),
            # MAR/2026 — RBT12 R$ 4.35M ⚠️ CRUZA o gate 4.32M (90% × 4.8M)
            _mes("2026-03", "4350000.00", "440000.00", "28000.00", "304000.00", "0.0699"),
            # abr/2026 — RBT12 R$ 4.52M (acima do gate, alerta persiste)
            _mes("2026-04", "4520000.00", "460000.00", "28000.00", "305000.00", "0.0675"),
        ],
    )
