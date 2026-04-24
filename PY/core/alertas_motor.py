"""
alertas_motor.py — Geração de alertas fiscais extraída do MotorReformaTributaria.
LC 123/2006 | LC 214/2025 | EC 132/2023
"""

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from core.formatadores import _fmt_brl
from core.tabelas_simples import (
    ALERTA_90_PERCENT_TETO,
    ANO_INICIO_SPLIT_PAYMENT,
    SUBLIMITE_ICMS_ISS,
    TETO_SIMPLES_NACIONAL,
)


def gerar_alertas(
    rbt12: Decimal,
    alerta_fator_r: Optional[str],
    split_payment: Dict[str, Any],
    tipo_compradora: str,
    regime_fornecedora: str,
    data_emissao: date,
    data_liquidacao: Optional[date],
    valor_operacao: Decimal,
    qtd_itens: int,
    estorno_realizado: bool,
    tinha_st_icms: bool,
    cnae_principal: str,
    cnae_fonte: Optional[str],
) -> List[Dict[str, str]]:
    """Alertas fiscais baseados em gatilhos matemáticos."""
    alertas = []
    rbt12_val = rbt12

    # CRITICO: teto
    teto_excesso_imediato = TETO_SIMPLES_NACIONAL * Decimal("1.20")
    if rbt12_val > teto_excesso_imediato:
        alertas.append({
            "nivel": "CRITICO",
            "codigo": "DESENQUADRAMENTO_IMEDIATO",
            "mensagem": (
                f"RBT12 {_fmt_brl(rbt12_val)} ultrapassou {_fmt_brl(teto_excesso_imediato)} (120% do teto). "
                f"DESENQUADRAMENTO IMEDIATO do Simples Nacional — efeitos RETROATIVOS ao mês do excesso. "
                f"LC 123/2006, Art. 3º, §§ 9º e 10."
            ),
        })
    elif rbt12_val > TETO_SIMPLES_NACIONAL:
        alertas.append({
            "nivel": "CRITICO",
            "codigo": "DESENQUADRAMENTO_PROXIMO_ANO",
            "mensagem": (
                f"RBT12 {_fmt_brl(rbt12_val)} excedeu o teto de {_fmt_brl(TETO_SIMPLES_NACIONAL)}. "
                f"Empresa será excluída do Simples Nacional a partir de janeiro/{data_emissao.year + 1}. "
                f"LC 123/2006, Art. 3º, II."
            ),
        })
    elif rbt12_val > ALERTA_90_PERCENT_TETO:
        alertas.append({
            "nivel": "CRITICO",
            "codigo": "RBT12_PROXIMO_TETO",
            "mensagem": (
                f"RBT12 {_fmt_brl(rbt12_val)} = {(rbt12_val/TETO_SIMPLES_NACIONAL*100):.1f}% do teto. "
                f"Planejar migração para Lucro Presumido IMEDIATAMENTE."
            ),
        })

    # ALTO: Fator R zona de risco
    if alerta_fator_r:
        alertas.append({
            "nivel": "ALTO",
            "codigo": "FATOR_R_ZONA_RISCO",
            "mensagem": alerta_fator_r,
        })

    # ALTO: Split Payment ativo
    if split_payment["ativo"]:
        alertas.append({
            "nivel": "ALTO",
            "codigo": "SPLIT_PAYMENT_ATIVO",
            "mensagem": (
                f"Split Payment ativo desde Jan/2027. "
                f"Retenção na fonte: {_fmt_brl(Decimal(split_payment['retencao_imediata']))} por operação."
            ),
        })

    # ALTO: B2B com Simples puro — risco de perda de contrato
    if tipo_compradora == "B2B_CONTRIBUINTE" and regime_fornecedora == "SIMPLES":
        alertas.append({
            "nivel": "ALTO",
            "codigo": "RISCO_B2B_CREDITO_INSUFICIENTE",
            "mensagem": (
                "Fornecedor no Simples gera crédito mínimo para comprador B2B. "
                "Avaliar Opt-Out para reter contrato com indústria/grande empresa."
            ),
        })

    # MEDIO: Sublimite ICMS/ISS ultrapassado
    if rbt12_val > SUBLIMITE_ICMS_ISS:
        alertas.append({
            "nivel": "MEDIO",
            "codigo": "SUBLIMITE_ICMS_ISS",
            "mensagem": (
                f"RBT12 {_fmt_brl(rbt12_val)} > sublimite {_fmt_brl(SUBLIMITE_ICMS_ISS)}. "
                f"ICMS e ISS devem ser apurados em guias separadas (fora do DAS)."
            ),
        })

    # INFO: Substituição Tributária ICMS extinta
    if tinha_st_icms:
        alertas.append({
            "nivel": "INFO",
            "codigo": "ST_ICMS_EXTINTA",
            "mensagem": (
                "Substituição Tributária de ICMS será extinta com o IBS. "
                "Capital de giro travado na ST será liberado progressivamente até 2032."
            ),
        })

    # C1 (R14): Fantasma do Ano Novo — emissão X liquidação em mudança de regime
    if data_liquidacao and data_liquidacao.year > data_emissao.year:
        if data_emissao.year < ANO_INICIO_SPLIT_PAYMENT <= data_liquidacao.year:
            alertas.append({
                "nivel": "ALTO",
                "codigo": "CONCILIACAO_RISCO",
                "mensagem": (
                    f"Fantasma do Ano Novo: Emissão em {data_emissao.year} "
                    f"e liquidação em {data_liquidacao.year}. "
                    "Cuidado: contabilidade gera imposto na emissão, mas retenção do Split Payment atua na liquidação."
                ),
            })

    # C2 (R15): Explosão do Sublimite — esta operação cruza o limite
    if rbt12_val <= SUBLIMITE_ICMS_ISS < rbt12_val + valor_operacao:
        alertas.append({
            "nivel": "ALTO",
            "codigo": "SUBLIMITE_CRITICO",
            "mensagem": (
                f"A operação atual ({_fmt_brl(valor_operacao)}) "
                f"cruzou o Sublimite Estadual ({_fmt_brl(SUBLIMITE_ICMS_ISS)}). "
                "ICMS e ISS serão ejetados do DAS no próximo mês!"
            ),
        })

    # C3 (R16): Salada de Frutas — risco de timeout em NF com muitos itens
    if qtd_itens > 50:
        alertas.append({
            "nivel": "MEDIO",
            "codigo": "RISCO_TIMEOUT_API",
            "mensagem": (
                f"Carga extrema: NF com {qtd_itens} itens. "
                "Risco de instabilidade no CGIBS. Se ocorrer timeout de API, "
                "o Split Payment pode aplicar retenção punitiva máxima."
            ),
        })

    # C4 (R17): Estorno do Medo — imposto já retido não vira dinheiro
    if estorno_realizado:
        alertas.append({
            "nivel": "ALTO",
            "codigo": "CAPITAL_GIRO_COMPROMETIDO",
            "mensagem": (
                "Estorno após Split Payment: O imposto já foi retido no PIX/Cartão. "
                "Com a devolução, esse saldo virará crédito tributário de difícil "
                "recuperação, e não dinheiro em conta."
            ),
        })

    # CNAE: fallback ou prefixo (ERR-005)
    if cnae_fonte == "FALLBACK":
        alertas.append({
            "nivel": "MEDIO",
            "codigo": "CNAE_FALLBACK_ERR005",
            "mensagem": (
                f"CNAE {cnae_principal} não encontrado na tabela de mapeamento. "
                f"Anexo III foi assumido como fallback seguro. "
                f"Confirme o Anexo correto com o contador responsável antes de tomar decisões."
            ),
        })
    elif cnae_fonte == "PREFIXO":
        alertas.append({
            "nivel": "INFO",
            "codigo": "CNAE_PREFIXO",
            "mensagem": (
                f"CNAE {cnae_principal} mapeado por prefixo (grupo '{cnae_principal[:2]}'). "
                f"Verifique se o Anexo corresponde à atividade principal da empresa."
            ),
        })

    return alertas
