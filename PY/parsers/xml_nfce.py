"""
Parser XML NFCe 4.0 — Motor Tributário Conect
Extrai dados de Nota Fiscal de Consumidor Eletrônica (modelo 65 — B2C).

Diferenças em relação à NFe (modelo 55):
- ide/mod = "65"
- Sem dest/CNPJ (consumidor final anônimo)
- indPres em ide: 1=presencial, 4=entrega domiciliar

Amparo legal:
- LC 123/2006 Art. 3º §2º — RBT12 real, base de cálculo mensal
- Ajuste SINIEF 7/2013 — modelo 65 NFCe
"""

from __future__ import annotations

from decimal import Decimal

from .xml_nfe import (
    NFeParsedData,
    NFeParserError,
    MODELO_NFCE,
    _get_lxml,
    _strip_ns,
    _get_raiz_nfe,
    _text,
    _decimal,
)


def parsear_xml_nfce(conteudo: bytes) -> NFeParsedData:
    """
    Parseia um único XML NFCe 4.0 e retorna NFeParsedData.

    Args:
        conteudo: bytes do arquivo XML NFCe

    Returns:
        NFeParsedData com modelo="65", pct_clientes_b2b=0 (consumidor final)

    Raises:
        NFeParserError: se o XML for inválido, faltar campos, ou mod != 65
    """
    etree = _get_lxml()
    try:
        root = etree.fromstring(conteudo)
    except etree.XMLSyntaxError as e:
        raise NFeParserError(f"XML NFCe inválido: {e}") from e

    tag = _strip_ns(root.tag)
    if tag not in ("nfeProc", "NFe", "infNFe"):
        raise NFeParserError(
            f"Namespace/root inesperado: <{tag}>. "
            "O arquivo não parece ser um XML NFCe 4.0 SEFAZ."
        )

    inf = _get_raiz_nfe(root)

    # Validar modelo 65
    mod = _text(inf, "ide", "mod") or ""
    if mod and mod != MODELO_NFCE:
        raise NFeParserError(
            f"ide/mod={mod!r} — esperado '65' para NFCe. "
            "Use parsear_xml_nfe() para NFe modelo 55."
        )

    # CNPJ emitente
    import re
    cnpj_emit = _text(inf, "emit", "CNPJ") or ""
    if not cnpj_emit:
        raise NFeParserError("XML NFCe sem emit/CNPJ — documento incompleto")
    cnpj_emit = re.sub(r"\D", "", cnpj_emit)

    # Competência
    import re as _re
    dh_emi = _text(inf, "ide", "dhEmi") or _text(inf, "ide", "dEmi") or ""
    if not dh_emi:
        raise NFeParserError("XML NFCe sem ide/dhEmi — documento incompleto")
    competencia = dh_emi[:7]
    if not _re.match(r"^\d{4}-\d{2}$", competencia):
        raise NFeParserError(f"ide/dhEmi em formato inesperado: {dh_emi!r}")

    # Valores — NFCe não tem dest/CNPJ nem indIEDest (sempre consumidor final)
    v_nf = _decimal(inf, "total", "ICMSTot", "vNF")
    v_icms_st = _decimal(inf, "total", "ICMSTot", "vICMSST")

    chave = inf.get("Id", "").replace("NFe", "")

    return NFeParsedData(
        cnpj_emitente=cnpj_emit,
        competencia=competencia,
        valor_total_mes=v_nf,
        receita_st_icms=v_icms_st,
        pct_clientes_b2b=Decimal("0"),  # NFCe = sempre consumidor final
        notas_processadas=1,
        chaves_nfe=[chave] if chave else [],
        modelo=MODELO_NFCE,
    )


def parsear_lote_nfce(conteudos: list[bytes]) -> NFeParsedData:
    """
    Consolida múltiplos XMLs NFCe do mesmo mês em um único NFeParsedData.

    Args:
        conteudos: lista de bytes de arquivos XML NFCe

    Returns:
        NFeParsedData consolidado com modelo="65"
    """
    if not conteudos:
        raise NFeParserError("Lote vazio — nenhum XML NFCe fornecido")

    notas = [parsear_xml_nfce(c) for c in conteudos]

    import re
    cnpjs = {n.cnpj_emitente for n in notas}
    if len(cnpjs) > 1:
        raise NFeParserError(
            f"XMLs NFCe de CNPJs diferentes no mesmo lote: {cnpjs}"
        )
    competencias = {n.competencia for n in notas}
    if len(competencias) > 1:
        raise NFeParserError(
            f"XMLs NFCe de meses diferentes no mesmo lote: {competencias}"
        )

    from decimal import ROUND_HALF_UP
    valor_total = sum(n.valor_total_mes for n in notas)
    receita_st = sum(n.receita_st_icms for n in notas)
    chaves = [c for n in notas for c in n.chaves_nfe]

    return NFeParsedData(
        cnpj_emitente=notas[0].cnpj_emitente,
        competencia=notas[0].competencia,
        valor_total_mes=valor_total,
        receita_st_icms=receita_st,
        pct_clientes_b2b=Decimal("0"),
        notas_processadas=len(notas),
        chaves_nfe=chaves,
        modelo=MODELO_NFCE,
    )
