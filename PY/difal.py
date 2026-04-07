# -*- coding: utf-8 -*-
"""
difal.py — DIFAL Interestadual (Diferencial de Alíquota ICMS)
Motor Tributário Conect 2026-2033

BASE LEGAL:
  - EC 87/2015 — instituiu DIFAL para consumidor final não contribuinte
  - LC 190/2022 — regulamentou cobrança (STF ADI 5469 / RE 1287019)
  - LC 87/1996, Art. 13 — base de cálculo ICMS "por dentro"
  - Res. SF 22/1989 — alíquotas interestaduais 7% e 12%
  - Res. SF 13/2012 — 4% para produtos importados
  - CF/1988, Art. 155, §2º, VII e VIII — competência
  - ADCT Art. 99, V (EC 87/2015) — partilha 100% destino desde 01/01/2019

REGRAS:
  - B2C (consumidor final não contribuinte): base única — remetente recolhe
    DIFAL = Valor × (Alíq.Interna_Destino − Alíq.Interestadual)
  - B2B (contribuinte, uso/consumo/ativo): base dupla "por dentro" — destinatário recolhe
    ICMS_Inter = Valor × Alíq.Inter
    Base_Interna = (Valor − ICMS_Inter) / (1 − Alíq.Interna)
    ICMS_Interno = Base_Interna × Alíq.Interna
    DIFAL = ICMS_Interno − ICMS_Inter
  - Operação interna (mesma UF): sem DIFAL
  - Partilha: 100% destino desde 01/01/2019 (Art. 99, V, ADCT)
  - Transição 2029-2032: DIFAL reduz junto com ICMS. Extinto em 2033.

NOTA ES: Espírito Santo é Sudeste geograficamente mas EXCLUÍDO do bloco
  remetente Sul/Sudeste da Res. SF 22/1989. Quando ES remete, aplica 12%
  (não 7%). Quando ES recebe de SP/RJ/MG/PR/SC/RS, recebe com 7% como
  se fosse N/NE/CO.
"""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# ALÍQUOTAS ICMS INTERNAS POR UF (2026) — inclui FECP quando aplicável
# Fonte: legislações estaduais vigentes + consolidação de mercado
# Atualizar anualmente com publicações estaduais (DOE).
# ─────────────────────────────────────────────────────────────────────────────

ALIQUOTA_ICMS_INTERNA: Dict[str, Decimal] = {
    "AC": Decimal("0.19"),    # Acre
    "AL": Decimal("0.20"),    # Alagoas (19% + 1% FECP)
    "AM": Decimal("0.20"),    # Amazonas
    "AP": Decimal("0.18"),    # Amapá
    "BA": Decimal("0.205"),   # Bahia
    "CE": Decimal("0.20"),    # Ceará
    "DF": Decimal("0.20"),    # Distrito Federal
    "ES": Decimal("0.17"),    # Espírito Santo
    "GO": Decimal("0.19"),    # Goiás
    "MA": Decimal("0.23"),    # Maranhão
    "MG": Decimal("0.18"),    # Minas Gerais
    "MS": Decimal("0.19"),    # Mato Grosso do Sul
    "MT": Decimal("0.17"),    # Mato Grosso
    "PA": Decimal("0.19"),    # Pará
    "PB": Decimal("0.20"),    # Paraíba
    "PE": Decimal("0.205"),   # Pernambuco
    "PI": Decimal("0.225"),   # Piauí
    "PR": Decimal("0.195"),   # Paraná (17,5% + 2% FECP)
    "RJ": Decimal("0.22"),    # Rio de Janeiro (20% + 2% FECP)
    "RN": Decimal("0.20"),    # Rio Grande do Norte
    "RO": Decimal("0.195"),   # Rondônia
    "RR": Decimal("0.20"),    # Roraima
    "RS": Decimal("0.17"),    # Rio Grande do Sul
    "SC": Decimal("0.17"),    # Santa Catarina
    "SE": Decimal("0.20"),    # Sergipe (19% + 1% FECP)
    "SP": Decimal("0.18"),    # São Paulo
    "TO": Decimal("0.20"),    # Tocantins
}


# ─────────────────────────────────────────────────────────────────────────────
# ALÍQUOTAS INTERESTADUAIS — Res. SF 22/1989 + Res. SF 13/2012
# ─────────────────────────────────────────────────────────────────────────────

# UFs remetentes Sul/Sudeste que aplicam 7% para N/NE/CO/ES
# NOTA CRÍTICA: ES é Sudeste mas EXCLUÍDO deste grupo (aplica 12% como remetente)
UFS_SUL_SUDESTE_REMETENTE = frozenset({"SP", "RJ", "MG", "PR", "SC", "RS"})

# UFs destino que recebem com 7% de remetente Sul/Sudeste
UFS_DESTINO_7PCT = frozenset({
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
    "MT", "MS", "PA", "PB", "PE", "PI", "RN", "RO", "RR", "SE", "TO",
})

ALIQUOTA_IMPORTADO = Decimal("0.04")    # Res. SF 13/2012
ALIQUOTA_INTER_7   = Decimal("0.07")    # Res. SF 22/1989 (Sul/Sudeste → N/NE/CO/ES)
ALIQUOTA_INTER_12  = Decimal("0.12")    # Res. SF 22/1989 (demais)


# ─────────────────────────────────────────────────────────────────────────────
# FUNÇÕES DE CONSULTA
# ─────────────────────────────────────────────────────────────────────────────

def obter_aliquota_interestadual(
    uf_origem: str,
    uf_destino: str,
    produto_importado: bool = False,
) -> Decimal:
    """
    Determina alíquota interestadual ICMS.
    Res. SF 13/2012 (4% importado) | Res. SF 22/1989 (7% ou 12%).
    """
    if produto_importado:
        return ALIQUOTA_IMPORTADO
    if uf_origem in UFS_SUL_SUDESTE_REMETENTE and uf_destino in UFS_DESTINO_7PCT:
        return ALIQUOTA_INTER_7
    return ALIQUOTA_INTER_12


def obter_aliquota_interna(uf: str) -> Decimal:
    """Retorna alíquota interna ICMS de uma UF. Levanta ValueError se UF inválida."""
    aliq = ALIQUOTA_ICMS_INTERNA.get(uf.upper())
    if aliq is None:
        raise ValueError(f"UF '{uf}' não encontrada em ALIQUOTA_ICMS_INTERNA.")
    return aliq


# ─────────────────────────────────────────────────────────────────────────────
# CÁLCULO PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def calcular_difal(
    valor_operacao: Decimal,
    uf_origem: str,
    uf_destino: str,
    tipo_destinatario: str,
    produto_importado: bool = False,
    trilha: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Calcula DIFAL interestadual.

    Args:
        valor_operacao: Valor R$ da operação
        uf_origem: UF do remetente ("SP")
        uf_destino: UF do destinatário ("BA")
        tipo_destinatario: "B2B_CONTRIBUINTE" | "B2C_CONSUMIDOR_FINAL" | "MISTO"
        produto_importado: True se conteúdo de importação > 40% (Res. SF 13/2012)
        trilha: lista opcional para registro de auditoria

    Returns:
        Dict com 10 campos compatíveis com resultado.html::renderDifal()

    Base Legal: EC 87/2015 | LC 190/2022 | LC 87/1996, Art. 13
    """
    uf_origem = uf_origem.upper().strip()
    uf_destino = uf_destino.upper().strip()

    # ── Operação interna: sem DIFAL ───────────────────────────────────
    if uf_origem == uf_destino:
        resultado = {
            "aplicavel": False,
            "uf_origem": uf_origem,
            "uf_destino": uf_destino,
            "metodo": "N/A",
            "responsavel": None,
            "produto_importado": produto_importado,
            "aliquota_interestadual": Decimal("0"),
            "aliquota_interna_destino": Decimal("0"),
            "difal_valor": Decimal("0.00"),
            "base_legal": "Operação interna — sem DIFAL (CF Art. 155, §2º, VII)",
        }
        if trilha is not None:
            trilha.append({
                "tipo": "INFO_DIFAL",
                "id": "DIFAL_OPERACAO_INTERNA",
                "titulo": "DIFAL — Operação interna",
                "formula": f"UF origem ({uf_origem}) = UF destino ({uf_destino}) → DIFAL = R$ 0,00",
                "amparo_legal": "CF/1988, Art. 155, §2º, VII — DIFAL apenas em operações interestaduais",
                "detalhe": "Operação intra-estadual. Nenhum diferencial de alíquota aplicável.",
                "timestamp": str(datetime.now()),
            })
        return resultado

    # ── Alíquotas aplicáveis ──────────────────────────────────────────
    aliq_inter = obter_aliquota_interestadual(uf_origem, uf_destino, produto_importado)
    aliq_interna = obter_aliquota_interna(uf_destino)

    # ── Caso degenerado: alíquota interna ≤ interestadual ─────────────
    if aliq_interna <= aliq_inter:
        return {
            "aplicavel": False,
            "uf_origem": uf_origem,
            "uf_destino": uf_destino,
            "metodo": "N/A",
            "responsavel": None,
            "produto_importado": produto_importado,
            "aliquota_interestadual": aliq_inter,
            "aliquota_interna_destino": aliq_interna,
            "difal_valor": Decimal("0.00"),
            "base_legal": (
                f"Alíq.Interna {uf_destino} ({aliq_interna*100:.2f}%) ≤ "
                f"Alíq.Inter ({aliq_inter*100:.2f}%) — sem diferencial"
            ),
        }

    # ── Determinar método de cálculo ──────────────────────────────────
    is_b2c = tipo_destinatario in ("B2C_CONSUMIDOR_FINAL", "MISTO")

    if is_b2c:
        # ── BASE ÚNICA (B2C) ──────────────────────────────────────────
        # DIFAL = Valor × (Alíq.Interna − Alíq.Inter)
        # Responsável: REMETENTE (CF Art. 155, §2º, VII, 'b')
        diferencial = aliq_interna - aliq_inter
        difal_valor = (valor_operacao * diferencial).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        metodo = "BASE_UNICA"
        responsavel = "REMETENTE"
        base_legal = (
            "EC 87/2015 | LC 190/2022 | CF Art. 155, §2º, VII, 'b' | "
            + ("Res. SF 13/2012 (importado)" if produto_importado else "Res. SF 22/1989")
        )
    else:
        # ── BASE DUPLA "POR DENTRO" (B2B uso/consumo/ativo) ───────────
        # ICMS_Inter = Valor × Alíq_Inter
        # Base_Interna = (Valor − ICMS_Inter) / (1 − Alíq_Interna)
        # ICMS_Interno = Base_Interna × Alíq_Interna
        # DIFAL = ICMS_Interno − ICMS_Inter
        # Responsável: DESTINATÁRIO (CF Art. 155, §2º, VII, 'a')
        icms_inter = (valor_operacao * aliq_inter).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        base_liquida = valor_operacao - icms_inter
        base_interna = (base_liquida / (Decimal("1") - aliq_interna)).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        icms_interno = (base_interna * aliq_interna).quantize(
            Decimal("0.01"), ROUND_HALF_UP
        )
        difal_valor = max(
            Decimal("0.00"),
            (icms_interno - icms_inter).quantize(Decimal("0.01"), ROUND_HALF_UP),
        )
        metodo = "BASE_DUPLA"
        responsavel = "DESTINATARIO"
        base_legal = (
            "LC 87/1996, Art. 13 | EC 87/2015 | LC 190/2022 | "
            "CF Art. 155, §2º, VII, 'a' | "
            + ("Res. SF 13/2012 (importado)" if produto_importado else "Res. SF 22/1989")
        )

    # ── Registrar na trilha de auditoria ──────────────────────────────
    if trilha is not None:
        trilha.append({
            "tipo": "CALCULO",
            "id": f"DIFAL_{metodo}",
            "titulo": f"DIFAL {uf_origem}→{uf_destino} ({metodo.replace('_', ' ')})",
            "formula": (
                f"Base [{valor_operacao:,.2f}] × "
                f"(Alíq.Interna [{aliq_interna*100:.2f}%] − "
                f"Alíq.Inter [{aliq_inter*100:.2f}%]) = R$ {difal_valor:,.2f}"
            ),
            "memoria": {
                "base": str(valor_operacao),
                "aliquota_interestadual": str(aliq_inter),
                "aliquota_interna_destino": str(aliq_interna),
                "difal_valor": str(difal_valor),
            },
            "amparo_legal": base_legal,
            "detalhe": f"Responsável: {responsavel}. Partilha: 100% destino ({uf_destino}) — ADCT Art. 99, V.",
            "timestamp": str(datetime.now()),
        })

    return {
        "aplicavel": True,
        "uf_origem": uf_origem,
        "uf_destino": uf_destino,
        "metodo": metodo,
        "responsavel": responsavel,
        "produto_importado": produto_importado,
        "aliquota_interestadual": aliq_inter,
        "aliquota_interna_destino": aliq_interna,
        "difal_valor": difal_valor,
        "base_legal": base_legal,
    }
