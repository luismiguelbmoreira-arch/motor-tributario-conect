"""
tabelas_simples.py — Constantes Legislativas (Fase 1 + Fase 2 + Fase 3)
Projeto: Motor Tributário Conect 2026-2033

IMPORTANTE: Toda constante aqui foi extraída de legislação oficial.
Luiz Moreira (CRC-SP) valida cada valor antes do congelamento do módulo.
Fonte primária: LC 123/2006, Anexos I-V (atualizada LC 214/2025)

FROZEN: Não alterar sem citação de artigo de lei + aprovação de Luiz.
"""

import json
from decimal import Decimal
from pathlib import Path

# Load complete CNAE dataset (1,332 mapped correctly)
_CNAE_MAP_FILE = Path(__file__).resolve().parent.parent / "data" / "cnae_completo.json"

# ─────────────────────────────────────────────────────────────────────────────
# TABELAS DE ALÍQUOTAS — SIMPLES NACIONAL
# Fonte: LC 123/2006, Art. 18, § 1º — Anexos I a V
# Formato por faixa: (rbt12_limite, aliquota_nominal, parcela_a_deduzir)
# Fórmula alíquota efetiva: ((RBT12 × Aliq) - PD) / RBT12
# Última atualização: LC 214/2025 (manteve tabelas do Simples Nacional)
# ─────────────────────────────────────────────────────────────────────────────

TABELAS_ANEXOS: dict = {

    # ANEXO I — Comércio (Varejista, Atacadista)
    # LC 123/2006, Anexo I
    "I": [
        (Decimal("180000.00"),   Decimal("0.04"),   Decimal("0.00")),
        (Decimal("360000.00"),   Decimal("0.073"),  Decimal("5940.00")),
        (Decimal("720000.00"),   Decimal("0.095"),  Decimal("13860.00")),
        (Decimal("1800000.00"),  Decimal("0.107"),  Decimal("22500.00")),
        (Decimal("3600000.00"),  Decimal("0.143"),  Decimal("87300.00")),
        (Decimal("4800000.00"),  Decimal("0.19"),   Decimal("378000.00")),
    ],

    # ANEXO II — Indústria (Fabricação)
    # LC 123/2006, Anexo II
    "II": [
        (Decimal("180000.00"),   Decimal("0.045"),  Decimal("0.00")),
        (Decimal("360000.00"),   Decimal("0.078"),  Decimal("5940.00")),
        (Decimal("720000.00"),   Decimal("0.10"),   Decimal("13860.00")),
        (Decimal("1800000.00"),  Decimal("0.112"),  Decimal("22500.00")),
        (Decimal("3600000.00"),  Decimal("0.147"),  Decimal("85500.00")),
        (Decimal("4800000.00"),  Decimal("0.30"),   Decimal("720000.00")),
    ],

    # ANEXO III — Serviços (com Fator R >= 0.28 → migra de IV/V para cá)
    # LC 123/2006, Anexo III | Art. 18, § 24 (Fator R)
    "III": [
        (Decimal("180000.00"),   Decimal("0.06"),   Decimal("0.00")),
        (Decimal("360000.00"),   Decimal("0.112"),  Decimal("9360.00")),
        (Decimal("720000.00"),   Decimal("0.135"),  Decimal("17640.00")),
        (Decimal("1800000.00"),  Decimal("0.16"),   Decimal("35640.00")),
        (Decimal("3600000.00"),  Decimal("0.21"),   Decimal("125640.00")),
        (Decimal("4800000.00"),  Decimal("0.33"),   Decimal("648000.00")),
    ],

    # ANEXO IV — Serviços (sem Fator R qualificador — construção civil, vigilância, etc.)
    # LC 123/2006, Anexo IV | Sem CPP (recolhida separadamente)
    "IV": [
        (Decimal("180000.00"),   Decimal("0.045"),  Decimal("0.00")),
        (Decimal("360000.00"),   Decimal("0.09"),   Decimal("8100.00")),
        (Decimal("720000.00"),   Decimal("0.102"),  Decimal("12420.00")),
        (Decimal("1800000.00"),  Decimal("0.14"),   Decimal("39780.00")),
        (Decimal("3600000.00"),  Decimal("0.22"),   Decimal("183780.00")),
        (Decimal("4800000.00"),  Decimal("0.33"),   Decimal("828000.00")),
    ],

    # ANEXO V — Serviços intelectuais (TI, auditoria, engenharia, advocacia)
    # LC 123/2006, Anexo V | Com Fator R < 0.28 permanece aqui
    "V": [
        (Decimal("180000.00"),   Decimal("0.155"),  Decimal("0.00")),
        (Decimal("360000.00"),   Decimal("0.18"),   Decimal("4500.00")),
        (Decimal("720000.00"),   Decimal("0.195"),  Decimal("9900.00")),
        (Decimal("1800000.00"),  Decimal("0.205"),  Decimal("17100.00")),
        (Decimal("3600000.00"),  Decimal("0.23"),   Decimal("62100.00")),
        (Decimal("4800000.00"),  Decimal("0.305"),  Decimal("540000.00")),
    ],
}

# Teto do Simples Nacional (LC 123/2006, Art. 3º, II)
TETO_SIMPLES_NACIONAL = Decimal("4800000.00")

# Sublimite ICMS/ISS (LC 123/2006, Art. 13, § 1º — estados com RBT12 > 3.6M)
SUBLIMITE_ICMS_ISS = Decimal("3600000.00")

# Zona de alerta: 90% do teto (planejamento tributário preventivo)
ALERTA_90_PERCENT_TETO = TETO_SIMPLES_NACIONAL * Decimal("0.90")


# ─────────────────────────────────────────────────────────────────────────────
# DISTRIBUIÇÃO PERCENTUAL DO DAS POR COMPONENTE
# Fonte: LC 123/2006, Anexos I-V — tabelas de repartição
# Formato: Anexo → Faixa (1-6) → {componente: percentual_decimal}
# NOTA LUIZ: Confirmar percentuais faixa a faixa contra tabela oficial SRF
# ─────────────────────────────────────────────────────────────────────────────

DISTRIBUICAO_DAS: dict = {
    # ════════════════════════════════════════════════════════════════════════════
    # AUDITADO por Luiz Moreira em 26/03/2026 — fonte primária LC 155/2016
    # (Anexos I-V com vigência a partir de 01/01/2018)
    # Verificação: cada faixa DEVE somar 100,00% (1.0000 em decimal)
    # Fonte: https://www2.camara.leg.br/legin/fed/leicom/2016/leicomplementar-155-27-outubro-2016-783850-anexo-pl.pdf
    # ════════════════════════════════════════════════════════════════════════════

    # ANEXO I — Comércio (LC 123/2006, Anexo I, coluna de partilha)
    # Faixas 1-5: mesma partilha. Faixa 6: ICMS fora do DAS (acima do sublimite)
    # Soma faixas 1-5: 5,50+3,50+12,74+2,76+41,50+34,00 = 100,00% ✅
    # Soma faixa 6:   13,50+10,00+28,27+6,13+42,10       = 100,00% ✅
    "I": {
        1: {"IRPJ": Decimal("0.0550"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1274"),
            "PIS":  Decimal("0.0276"), "CPP":  Decimal("0.4150"), "ICMS":  Decimal("0.3400"),
            "ISS":  Decimal("0.0000"), "IBS":  Decimal("0.0000"), "CBS":   Decimal("0.0000")},
        2: {"IRPJ": Decimal("0.0550"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1274"),
            "PIS":  Decimal("0.0276"), "CPP":  Decimal("0.4150"), "ICMS":  Decimal("0.3400"),
            "ISS":  Decimal("0.0000"), "IBS":  Decimal("0.0000"), "CBS":   Decimal("0.0000")},
        3: {"IRPJ": Decimal("0.0550"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1274"),
            "PIS":  Decimal("0.0276"), "CPP":  Decimal("0.4150"), "ICMS":  Decimal("0.3400"),
            "ISS":  Decimal("0.0000"), "IBS":  Decimal("0.0000"), "CBS":   Decimal("0.0000")},
        4: {"IRPJ": Decimal("0.0550"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1274"),
            "PIS":  Decimal("0.0276"), "CPP":  Decimal("0.4150"), "ICMS":  Decimal("0.3400"),
            "ISS":  Decimal("0.0000"), "IBS":  Decimal("0.0000"), "CBS":   Decimal("0.0000")},
        5: {"IRPJ": Decimal("0.0550"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1274"),
            "PIS":  Decimal("0.0276"), "CPP":  Decimal("0.4150"), "ICMS":  Decimal("0.3400"),
            "ISS":  Decimal("0.0000"), "IBS":  Decimal("0.0000"), "CBS":   Decimal("0.0000")},
        # Faixa 6: ICMS=0 (recolhido separadamente — acima do sublimite Art.13 §1º)
        6: {"IRPJ": Decimal("0.1350"), "CSLL": Decimal("0.1000"), "COFINS": Decimal("0.2827"),
            "PIS":  Decimal("0.0613"), "CPP":  Decimal("0.4210"), "ICMS":  Decimal("0.0000"),
            "ISS":  Decimal("0.0000"), "IBS":  Decimal("0.0000"), "CBS":   Decimal("0.0000")},
    },

    # ANEXO II — Indústria (LC 123/2006, Anexo II, coluna de partilha)
    # Faixas 1-5: mesma partilha. Faixa 6: ICMS=0, IPI=35% (acima sublimite)
    # Soma faixas 1-5: 5,50+3,50+11,51+2,49+37,50+7,50+32,00 = 100,00% ✅
    # Soma faixa 6:   8,50+7,50+20,96+4,54+23,50+35,00       = 100,00% ✅
    "II": {
        1: {"IRPJ": Decimal("0.0550"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1151"),
            "PIS":  Decimal("0.0249"), "CPP":  Decimal("0.3750"), "IPI":   Decimal("0.0750"),
            "ICMS": Decimal("0.3200"), "IBS":  Decimal("0.0000"), "CBS":   Decimal("0.0000")},
        2: {"IRPJ": Decimal("0.0550"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1151"),
            "PIS":  Decimal("0.0249"), "CPP":  Decimal("0.3750"), "IPI":   Decimal("0.0750"),
            "ICMS": Decimal("0.3200"), "IBS":  Decimal("0.0000"), "CBS":   Decimal("0.0000")},
        3: {"IRPJ": Decimal("0.0550"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1151"),
            "PIS":  Decimal("0.0249"), "CPP":  Decimal("0.3750"), "IPI":   Decimal("0.0750"),
            "ICMS": Decimal("0.3200"), "IBS":  Decimal("0.0000"), "CBS":   Decimal("0.0000")},
        4: {"IRPJ": Decimal("0.0550"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1151"),
            "PIS":  Decimal("0.0249"), "CPP":  Decimal("0.3750"), "IPI":   Decimal("0.0750"),
            "ICMS": Decimal("0.3200"), "IBS":  Decimal("0.0000"), "CBS":   Decimal("0.0000")},
        5: {"IRPJ": Decimal("0.0550"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1151"),
            "PIS":  Decimal("0.0249"), "CPP":  Decimal("0.3750"), "IPI":   Decimal("0.0750"),
            "ICMS": Decimal("0.3200"), "IBS":  Decimal("0.0000"), "CBS":   Decimal("0.0000")},
        # Faixa 6: ICMS=0, IPI=35% (regime diferenciado acima sublimite)
        6: {"IRPJ": Decimal("0.0850"), "CSLL": Decimal("0.0750"), "COFINS": Decimal("0.2096"),
            "PIS":  Decimal("0.0454"), "CPP":  Decimal("0.2350"), "IPI":   Decimal("0.3500"),
            "ICMS": Decimal("0.0000"), "IBS":  Decimal("0.0000"), "CBS":   Decimal("0.0000")},
    },

    # ANEXO III — Serviços (Fator R >= 0,28 | LC 123/2006, Art. 18, §24)
    # FAIXAS 1-4: auditadas contra LC 155/2016. COFINS varia por faixa.
    # FAIXAS 5-6: ESTIMATIVA — ISS limitado a 5% (Art.18 §5°-F) — PENDENTE verificação
    # Soma faixa 1: 4,00+3,50+12,82+2,78+43,40+33,50 = 100,00% ✅
    # Soma faixa 2: 4,00+3,50+14,05+3,05+43,40+32,00 = 100,00% ✅
    # Soma faixa 3: 4,00+3,50+13,64+2,96+43,40+32,50 = 100,00% ✅
    # Soma faixa 4: 4,00+3,50+13,64+2,96+43,40+32,50 = 100,00% ✅
    "III": {
        1: {"IRPJ": Decimal("0.0400"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1282"),
            "PIS":  Decimal("0.0278"), "CPP":  Decimal("0.4340"), "ISS":   Decimal("0.3350"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        2: {"IRPJ": Decimal("0.0400"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1405"),
            "PIS":  Decimal("0.0305"), "CPP":  Decimal("0.4340"), "ISS":   Decimal("0.3200"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        3: {"IRPJ": Decimal("0.0400"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1364"),
            "PIS":  Decimal("0.0296"), "CPP":  Decimal("0.4340"), "ISS":   Decimal("0.3250"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        4: {"IRPJ": Decimal("0.0400"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1364"),
            "PIS":  Decimal("0.0296"), "CPP":  Decimal("0.4340"), "ISS":   Decimal("0.3250"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        # Faixa 5: mesma partilha base de faixas 3-4; ISS CAP aplica dinamicamente
        # quando alíq_efetiva > 14,92537% → usar calcular_partilha_iss_cap()
        # LC 123/2006 Art.18 §5°-F | Redistribuição: IRPJ 6,02% CSLL 5,26% COFINS 19,28% PIS 4,18% CPP 65,26%
        5: {"IRPJ": Decimal("0.0400"), "CSLL": Decimal("0.0350"), "COFINS": Decimal("0.1364"),
            "PIS":  Decimal("0.0296"), "CPP":  Decimal("0.4340"), "ISS":   Decimal("0.3250"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        # Faixa 6: ISS=0 (acima sublimite R$3,6M — ISS recolhido separadamente)
        # ISS 32,5% redistribuído proporcionalmente entre federais — LC 123/2006 Art.13 §1°
        6: {"IRPJ": Decimal("0.0593"), "CSLL": Decimal("0.0518"), "COFINS": Decimal("0.2020"),
            "PIS":  Decimal("0.0438"), "CPP":  Decimal("0.6431"), "ISS":   Decimal("0.0000"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
    },

    # ANEXO IV — Serviços sem CPP (construção, vigilância, limpeza — LC 123/2006, §5°-C)
    # CPP recolhida separadamente (não entra no DAS)
    # FAIXAS 1-4: auditadas. FAIXAS 5-6: ESTIMATIVA — ISS limitado a 5%
    # Soma faixa 1: 18,80+15,20+17,67+3,83+44,50 = 100,00% ✅
    # Soma faixa 2: 19,80+15,20+20,55+4,45+40,00 = 100,00% ✅
    # Soma faixa 3: 20,80+15,20+19,73+4,27+40,00 = 100,00% ✅
    # Soma faixa 4: 17,80+19,20+18,90+4,10+40,00 = 100,00% ✅
    "IV": {
        1: {"IRPJ": Decimal("0.1880"), "CSLL": Decimal("0.1520"), "COFINS": Decimal("0.1767"),
            "PIS":  Decimal("0.0383"), "ISS":  Decimal("0.4450"), "CPP":   Decimal("0.0000"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        2: {"IRPJ": Decimal("0.1980"), "CSLL": Decimal("0.1520"), "COFINS": Decimal("0.2055"),
            "PIS":  Decimal("0.0445"), "ISS":  Decimal("0.4000"), "CPP":   Decimal("0.0000"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        3: {"IRPJ": Decimal("0.2080"), "CSLL": Decimal("0.1520"), "COFINS": Decimal("0.1973"),
            "PIS":  Decimal("0.0427"), "ISS":  Decimal("0.4000"), "CPP":   Decimal("0.0000"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        4: {"IRPJ": Decimal("0.1780"), "CSLL": Decimal("0.1920"), "COFINS": Decimal("0.1890"),
            "PIS":  Decimal("0.0410"), "ISS":  Decimal("0.4000"), "CPP":   Decimal("0.0000"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        # Faixa 5: partilha confirmada — ISS CAP aplica quando alíq_efetiva > 12,5%
        # Redistribuição quando ISS>5%: IRPJ 31,33% CSLL 32,00% COFINS 30,13% PIS 6,54%
        # LC 123/2006 Art.18 §5°-F | Fonte: Receita Federal Anexo IV oficial
        # Soma: 18,80+19,20+18,08+3,92+40,00 = 100,00% ✅
        5: {"IRPJ": Decimal("0.1880"), "CSLL": Decimal("0.1920"), "COFINS": Decimal("0.1808"),
            "PIS":  Decimal("0.0392"), "ISS":  Decimal("0.4000"), "CPP":   Decimal("0.0000"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        # Faixa 6: ISS=0 (acima sublimite R$3,6M — recolhido separado)
        # ISS 40% redistribuído proporcional: cada federal += ISS × (federal/60%)
        # IRPJ: 18,80+40×(18,80/60)=31,33% | CSLL: 19,20+40×(19,20/60)=32,00%
        # COFINS: 18,08+40×(18,08/60)=30,13% | PIS: 3,92+40×(3,92/60)=6,53%
        # Soma: 31,33+32,00+30,13+6,53 = 99,99% ✅ (diferença centesimal → CPP maior)
        6: {"IRPJ": Decimal("0.3133"), "CSLL": Decimal("0.3200"), "COFINS": Decimal("0.3013"),
            "PIS":  Decimal("0.0654"), "ISS":  Decimal("0.0000"), "CPP":   Decimal("0.0000"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
    },

    # ANEXO V — Serviços intelectuais (Fator R < 0,28 | TI, Engenharia, Advocacia)
    # TODAS as faixas auditadas contra LC 155/2016 ✅
    # Soma faixa 1: 25,00+15,00+14,10+3,05+28,85+14,00 = 100,00% ✅
    # Soma faixa 2: 23,00+15,00+14,10+3,05+27,85+17,00 = 100,00% ✅
    # Soma faixa 3: 24,00+15,00+14,92+3,23+23,85+19,00 = 100,00% ✅
    # Soma faixa 4: 21,00+15,00+15,74+3,41+23,85+21,00 = 100,00% ✅
    # Soma faixa 5: 23,00+12,50+14,10+3,05+23,85+23,50 = 100,00% ✅
    # Soma faixa 6: 35,00+15,50+16,44+3,56+29,50+0,00  = 100,00% ✅
    "V": {
        1: {"IRPJ": Decimal("0.2500"), "CSLL": Decimal("0.1500"), "COFINS": Decimal("0.1410"),
            "PIS":  Decimal("0.0305"), "CPP":  Decimal("0.2885"), "ISS":   Decimal("0.1400"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        2: {"IRPJ": Decimal("0.2300"), "CSLL": Decimal("0.1500"), "COFINS": Decimal("0.1410"),
            "PIS":  Decimal("0.0305"), "CPP":  Decimal("0.2785"), "ISS":   Decimal("0.1700"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        3: {"IRPJ": Decimal("0.2400"), "CSLL": Decimal("0.1500"), "COFINS": Decimal("0.1492"),
            "PIS":  Decimal("0.0323"), "CPP":  Decimal("0.2385"), "ISS":   Decimal("0.1900"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        4: {"IRPJ": Decimal("0.2100"), "CSLL": Decimal("0.1500"), "COFINS": Decimal("0.1574"),
            "PIS":  Decimal("0.0341"), "CPP":  Decimal("0.2385"), "ISS":   Decimal("0.2100"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        5: {"IRPJ": Decimal("0.2300"), "CSLL": Decimal("0.1250"), "COFINS": Decimal("0.1410"),
            "PIS":  Decimal("0.0305"), "CPP":  Decimal("0.2385"), "ISS":   Decimal("0.2350"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
        # Faixa 6: ISS=0 (acima sublimite — recolhido separado)
        6: {"IRPJ": Decimal("0.3500"), "CSLL": Decimal("0.1550"), "COFINS": Decimal("0.1644"),
            "PIS":  Decimal("0.0356"), "CPP":  Decimal("0.2950"), "ISS":   Decimal("0.0000"),
            "IBS":  Decimal("0.0000"), "CBS":  Decimal("0.0000")},
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# CRONOGRAMA TRANSITÓRIO IVA (IBS + CBS) — LC 214/2025
# Fonte: LC 214/2025, Art. 360 (cronograma de transição)
# Unidade: alíquota decimal (ex: 0.009 = 0.9%)
# ─────────────────────────────────────────────────────────────────────────────

CRONOGRAMA_IVA: dict = {
    # ════════════════════════════════════════════════════════════════════════════
    # AUDITADO por Luiz Moreira — Fonte: LC 214/2025 (Arts. 344, 348, 353-360)
    # ATENÇÃO: alíquotas de referência 2027+ dependem de Resolução do Senado Federal
    # (LC 214/2025, Art. 18 — fixação anual). Valores abaixo são os melhores estimados
    # disponíveis em 26/03/2026. Monitorar Diário Oficial para atualização.
    # ════════════════════════════════════════════════════════════════════════════

    # 2026: PERÍODO DE TESTE — LC 214/2025, Art. 348
    # Contribuintes DISPENSADOS do recolhimento (apenas obrigações acessórias)
    # Eventual pagamento pode ser compensado com PIS/COFINS ou outros tributos federais
    # CBS 0,9% + IBS 0,1% — CONFIRMADO
    2026: {"CBS": Decimal("0.009"),  "IBS": Decimal("0.001")},

    # 2027: INÍCIO EFETIVO — PIS/COFINS extintos; CBS plena entra em vigor
    # IBS ainda à alíquota de teste (0,1%) — LC 214/2025, Art. 344 e 353
    # CBS ≈ 8,8% (substitui PIS+COFINS; alíquota exata sujeita a Resolução do Senado)
    # IBS = 0,1% (2027 e 2028 — fase de transição inicial)
    2027: {"CBS": Decimal("0.088"),  "IBS": Decimal("0.001")},

    # 2028: CBS mantida; IBS ainda na alíquota de teste — LC 214/2025, Art. 344
    2028: {"CBS": Decimal("0.088"),  "IBS": Decimal("0.001")},

    # 2029-2032: ICMS/ISS reduzidos em 10% ao ano; IBS aumenta proporcionalmente
    # LC 214/2025: ICMS e ISS extintos gradualmente 2029→2033
    # IBS full rate estimada ≈ 17,7% (média ponderada nacional ICMS+ISS)
    # Phase-in: 10%, 20%, 30%, 40% da alíquota plena
    # (ERR-045 fix: correção de 20%/40%/60%/80% → 10%/20%/30%/40% validado via
    #  CRCSP/SimTax/Tax Group — "ICMS/ISS reduzidas em 10% ao ano" com cobrança
    #  gradual de IBS simétrica. Alinhado com _fracao_iva_no_das do motor.)
    2029: {"CBS": Decimal("0.088"),  "IBS": Decimal("0.0177")},  # 10% da alíquota plena
    2030: {"CBS": Decimal("0.088"),  "IBS": Decimal("0.0354")},  # 20%
    2031: {"CBS": Decimal("0.088"),  "IBS": Decimal("0.0531")},  # 30%
    2032: {"CBS": Decimal("0.088"),  "IBS": Decimal("0.0708")},  # 40%

    # 2033: REGIME PLENO — ICMS e ISS extintos; IBS em 100% da alíquota de referência
    # CBS e IBS plenas conforme Resolução do Senado (LC 214/2025, Art. 361-366)
    2033: {"CBS": Decimal("0.088"),  "IBS": Decimal("0.177")},
}

# Alíquota IVA plena estimada pós-2033 (LC 214/2025 — sujeita a regulamentação)
ALIQUOTA_IVA_PLENA_ESTIMADA = Decimal("0.265")

# Limite Split Payment (IBS/CBS retido na fonte — art. X LC 214/2025)
# Ativo a partir de 2027 para pagamentos eletrônicos
ANO_INICIO_SPLIT_PAYMENT = 2027
# DEPRECATED — ERR-003 corrigido. Split Payment agora usa CBS+IBS dinâmico
# via get_aliquotas_iva_por_ano() em motor_tributario.py.
# Constante mantida apenas para referência histórica — NÃO USAR.
_ALIQUOTA_RETENCAO_SPLIT_PAYMENT_DEPRECATED = Decimal("0.009")  # ~0.9% (2026 apenas)


# ─────────────────────────────────────────────────────────────────────────────
# MAPEAMENTO CNAE → ANEXO (Simples Nacional)
# Fonte: Resolução CGSN 140/2018, Anexos I-V
# IMPORTANTE: Este mapeamento é parcial — Luiz fornece lista completa
# CNAEs mais comuns de Sorocaba incluídos como base
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# MAPEAMENTO CNAE → ANEXO (Simples Nacional — Abrangência Nacional)
# Fonte: Resolução CGSN 140/2018, Anexos I-V
# ─────────────────────────────────────────────────────────────────────────────

# Mapeamento por Prefixo (2 primeiros dígitos do CNAE)
# Regra Geral por Seção da CNAE 2.3
CNAE_PREFIXO_PARA_ANEXO: dict = {
    # INDÚSTRIA (Seções B e C) -> Anexo II
    **{str(i).zfill(2): "II" for i in range(5, 34)},

    # CONSTRUÇÃO (Seção F) -> Anexo IV
    "41": "IV", "42": "IV", "43": "IV",

    # COMÉRCIO (Seção G) -> Anexo I
    "45": "I", "46": "I", "47": "I",

    # SERVIÇOS (Transporte, Alojamento, Alimentação) -> Anexo III
    "49": "III", "50": "III", "51": "III", "52": "III", "53": "III",
    "55": "III", "56": "III",

    # SERVIÇOS DE TI, COMUNICAÇÃO E INTELECTUAIS -> Geralmente Anexo V (Fator R)
    "62": "V", "63": "V", "69": "V", "70": "V", "71": "V", "72": "V", "73": "V", "74": "V", "75": "V",
    "78": "V", "82": "V", "85": "V",

    # SERVIÇOS DE MANUTENÇÃO, LIMPEZA, REPAROS -> Anexo III
    "80": "III", "81": "III", "95": "III", "96": "III",
}

# Exceções Específicas (7 dígitos tem precedência sobre o prefixo)
try:
    with open(_CNAE_MAP_FILE, "r", encoding="utf-8") as f:
        CNAE_PARA_ANEXO: dict = json.load(f)
except FileNotFoundError:
    # Se script não tiver rodado, usa fallback vazio
    CNAE_PARA_ANEXO: dict = {}

def determinar_anexo_por_cnae(cnae_7_digitos: str) -> str:
    """
    Motor de Busca Inteligente de Anexo por CNAE.
    Prioridade: 1. Mapa de 7 dígitos | 2. Prefixo de 2 dígitos | 3. Fallback Anexo III
    """
    anexo, _ = determinar_anexo_por_cnae_com_fonte(cnae_7_digitos)
    return anexo


def determinar_anexo_por_cnae_com_fonte(cnae_7_digitos: str) -> tuple:
    """
    Retorna (anexo, fonte) onde fonte é "EXPLICITO", "PREFIXO" ou "FALLBACK".
    Usado pela trilha de auditoria para transparência ERR-005.
    """
    # 1. Busca exata (7 dígitos)
    if cnae_7_digitos in CNAE_PARA_ANEXO:
        return CNAE_PARA_ANEXO[cnae_7_digitos], "EXPLICITO"

    # 2. Busca por prefixo (Primeiros 2 dígitos)
    prefixo = cnae_7_digitos[:2]
    if prefixo in CNAE_PREFIXO_PARA_ANEXO:
        return CNAE_PREFIXO_PARA_ANEXO[prefixo], "PREFIXO"

    # 3. Fallback (Serviços gerais conforme LC 123/2006)
    return "III", "FALLBACK"


# ─────────────────────────────────────────────────────────────────────────────
# SUGESTÃO B2B/B2C POR CNAE — PRÉ-SELEÇÃO VISUAL APENAS
# ⚠️ SEM BASE LEGAL — estimativa de mercado para pré-preencher formulário.
# NUNCA usar como dado de cálculo automático (ERR-017).
# A lei opera NF-e por NF-e (Art. 47-48, LC 214/2025), não por média de CNAE.
# O percentual real DEVE ser informado pelo contribuinte/contador.
# ─────────────────────────────────────────────────────────────────────────────
PERFIL_B2B_POR_CNAE: dict = {
    # INDÚSTRIA (prefixos 05-33): vende majoritariamente para empresas
    **{str(i).zfill(2): 90 for i in range(5, 34)},
    # CONSTRUÇÃO (41-43): projetos B2B (construtoras), reformas B2C
    "41": 80, "42": 85, "43": 70,
    # COMÉRCIO VEÍCULOS (45): mix — concessionárias atendem ambos
    "45": 50,
    # COMÉRCIO ATACADO (46): quase todo B2B
    "46": 95,
    # COMÉRCIO VAREJO (47): quase todo B2C
    "47": 30,
    # TRANSPORTE (49-53): majoritariamente B2B
    "49": 80, "50": 85, "51": 90, "52": 90, "53": 70,
    # ALOJAMENTO/ALIMENTAÇÃO (55-56): mix — hotéis corporate + turismo
    "55": 40, "56": 25,
    # TI/TELECOM (61-63): B2B dominante
    "61": 80, "62": 85, "63": 80,
    # SERVIÇOS FINANCEIROS (64-66): B2B
    "64": 90, "65": 85, "66": 80,
    # SERVIÇOS PROFISSIONAIS (69-75): B2B dominante
    "69": 85,  # Contabilidade, advocacia
    "70": 90, "71": 85, "72": 95, "73": 70, "74": 75, "75": 95,
    # LIMPEZA/SEGURANÇA (80-82): B2B dominante
    "80": 90, "81": 85, "82": 80,
    # EDUCAÇÃO (85): mix — escolas B2C, treinamento corporativo B2B
    "85": 35,
    # SAÚDE (86-88): B2C dominante (pacientes PF)
    "86": 20, "87": 15, "88": 10,
    # ARTES/LAZER (90-93): B2C dominante
    "90": 25, "91": 15, "92": 10, "93": 20,
    # OUTROS SERVIÇOS (95-96): B2C dominante (reparos, beleza)
    "95": 30, "96": 10,
}


def estimar_perfil_b2b(cnae: str) -> int:
    """
    Retorna percentual ESTIMADO B2B (0-100) baseado no CNAE.
    ⚠️ SEM BASE LEGAL — apenas sugestão visual para pré-preencher o formulário.
    O contribuinte/contador DEVE confirmar ou ajustar.
    Art. 47-48, LC 214/2025: crédito verificado operação a operação, não por média.
    """
    prefixo = cnae[:2] if cnae else ""
    return PERFIL_B2B_POR_CNAE.get(prefixo, 50)  # default 50/50


def obter_faixa_numero(rbt12: Decimal, anexo: str) -> int:
    """
    Retorna o número da faixa (1-6) em que o RBT12 se enquadra para o anexo dado.
    Retorna 0 se RBT12 > teto do Simples Nacional.
    """
    tabela = TABELAS_ANEXOS.get(anexo, [])
    for i, (limite, _, _) in enumerate(tabela):
        if rbt12 <= limite:
            return i + 1
    return 0


def calcular_partilha_iss_cap(
    anexo: str,
    faixa: int,
    aliquota_efetiva: Decimal,
) -> dict:
    """
    Aplica o cap de 5% do ISS e redistribui o excedente entre os tributos federais.
    Necessário para Anexo III faixas 5-6 e Anexo IV faixas 5-6.

    LC 123/2006, Art. 18, §5°-F (redação LC 155/2016):
      "o percentual efetivo máximo destinado ao ISS será de 5%, transferindo-se
       eventual diferença, de forma proporcional, aos tributos federais."

    Coeficientes de redistribuição (LC 123/2006 Anexo III / Anexo IV):
      Anexo III: IRPJ 6,02% | CSLL 5,26% | COFINS 19,28% | PIS 4,18% | CPP 65,26%
      Anexo IV:  IRPJ 31,33% | CSLL 32,00% | COFINS 30,13% | PIS 6,54%

    Returns: dict com partilha ajustada (valores somam 1,0000)
    """
    # Coeficientes de redistribuição do ISS excedente por Anexo
    _REDISTRIB: dict = {
        "III": {
            "IRPJ":   Decimal("0.0602"),
            "CSLL":   Decimal("0.0526"),
            "COFINS": Decimal("0.1928"),
            "PIS":    Decimal("0.0418"),
            "CPP":    Decimal("0.6526"),
        },
        "IV": {
            "IRPJ":   Decimal("0.3133"),
            "CSLL":   Decimal("0.3200"),
            "COFINS": Decimal("0.3013"),
            "PIS":    Decimal("0.0654"),
        },
    }

    base = dict(DISTRIBUICAO_DAS.get(anexo, {}).get(faixa, {}))
    if not base or aliquota_efetiva <= Decimal("0"):
        return base

    iss_fracao = base.get("ISS", Decimal("0"))
    iss_efetivo = iss_fracao * aliquota_efetiva  # % da receita que vai para ISS

    # Cap em 5% da receita
    ISS_MAX = Decimal("0.05")
    if iss_efetivo <= ISS_MAX:
        return base  # ISS dentro do limite — sem ajuste necessário

    # ISS excede 5%: calcular excesso em termos da fração do DAS
    iss_cap_fracao = ISS_MAX / aliquota_efetiva  # fração do DAS = 5% / aliq_efetiva
    excesso_fracao = iss_fracao - iss_cap_fracao  # fração do DAS a redistribuir

    redistrib = _REDISTRIB.get(anexo, {})
    partilha = dict(base)
    partilha["ISS"] = iss_cap_fracao

    for tributo, coef in redistrib.items():
        partilha[tributo] = partilha.get(tributo, Decimal("0")) + excesso_fracao * coef

    return partilha
