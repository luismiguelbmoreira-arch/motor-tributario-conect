"""
Parser XML NFe 4.0 — Motor Tributário Conect
Extrai dados fiscais de XMLs de Nota Fiscal Eletrônica (modelo 55).

Amparo legal:
- LC 123/2006 Art. 3º §2º — RBT12 como base de cálculo mensal real
- LC 123/2006 Art. 13 §1º V — ICMS-ST sai do DAS
- SEFAZ: leiaute NFe 4.00 (NT 2019.001)
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from pydantic import BaseModel, Field

# Namespace oficial SEFAZ NFe 4.0
_NS = "http://www.portalfiscal.inf.br/nfe"
_NS_MAP = {"nfe": _NS}

# modelo 55 = NFe, 65 = NFCe
MODELO_NFE = "55"
MODELO_NFCE = "65"


class NFeParsedData(BaseModel):
    """Dados consolidados extraídos de um lote de XMLs NFe do mesmo mês."""

    cnpj_emitente: str = Field(..., description="CNPJ do emitente (14 dígitos)")
    competencia: str = Field(..., description="Competência no formato YYYY-MM")
    valor_total_mes: Decimal = Field(..., description="Soma de vNF de todas as NFe do mês")
    receita_st_icms: Decimal = Field(
        default=Decimal("0"), description="Soma de vICMSST — segregação ST (sai do DAS)"
    )
    pct_clientes_b2b: Decimal = Field(
        default=Decimal("0"),
        description="Percentual da receita para contribuintes (indIEDest=1)"
    )
    notas_processadas: int = Field(default=0, description="Quantidade de notas processadas")
    chaves_nfe: list[str] = Field(default_factory=list, description="Chaves de acesso para rastreabilidade")
    modelo: str = Field(default=MODELO_NFE, description="Modelo fiscal: 55=NFe, 65=NFCe")


class NFeParserError(ValueError):
    """Erro de parsing de XML NFe — documento inválido ou incompleto."""


def _get_lxml():
    """Importa lxml.etree com mensagem de erro clara se não instalado."""
    try:
        from lxml import etree  # type: ignore[import]
        return etree
    except ImportError:
        raise ImportError(
            "lxml não instalado. Execute: pip install lxml>=5.0\n"
            "Necessário para parse de XML NFe (LC 123/2006 Art. 13 §1º V)"
        )


def _strip_ns(tag: str) -> str:
    """Remove namespace de uma tag: '{ns}tag' → 'tag'."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _find(element, *path_parts):
    """Busca elemento por partes do path (ignora namespace)."""
    _get_lxml()
    current = element
    for part in path_parts:
        found = None
        for child in current:
            if _strip_ns(child.tag) == part:
                found = child
                break
        if found is None:
            return None
        current = found
    return current


def _text(element, *path_parts) -> Optional[str]:
    """Retorna o texto de um nó encontrado pelo path, ou None."""
    node = _find(element, *path_parts)
    if node is not None and node.text:
        return node.text.strip()
    return None


def _decimal(element, *path_parts) -> Decimal:
    """Retorna valor Decimal de um nó, ou Decimal('0') se ausente."""
    val = _text(element, *path_parts)
    if val:
        try:
            return Decimal(val).quantize(Decimal("0.01"), ROUND_HALF_UP)
        except Exception:
            return Decimal("0")
    return Decimal("0")


def _get_raiz_nfe(root) -> object:
    """
    Normaliza root para o elemento <infNFe>.
    Aceita root = nfeProc, NFe, ou infNFe diretamente.
    """
    tag = _strip_ns(root.tag)
    if tag == "nfeProc":
        nfe = _find(root, "NFe")
        if nfe is None:
            raise NFeParserError("nfeProc sem elemento NFe filho")
        inf = _find(nfe, "infNFe")
        return inf if inf is not None else nfe
    if tag == "NFe":
        inf = _find(root, "infNFe")
        return inf if inf is not None else root
    if tag == "infNFe":
        return root
    raise NFeParserError(
        f"Root inesperado: <{tag}>. Esperado: nfeProc, NFe ou infNFe. "
        "Verifique se o arquivo é um XML NFe 4.0 válido."
    )


def _extrair_uma_nota(root_element) -> dict:
    """
    Extrai campos relevantes de um único XML NFe (<nfeProc> ou <NFe>).
    Retorna dict com: cnpj_emit, competencia, vNF, vICMSST, indIEDest, mod, chave.
    """
    _get_lxml()
    inf = _get_raiz_nfe(root_element)

    # Modelo (55=NFe, 65=NFCe)
    mod = _text(inf, "ide", "mod") or ""

    # CNPJ emitente
    cnpj_emit = _text(inf, "emit", "CNPJ") or ""
    if not cnpj_emit:
        raise NFeParserError("XML NFe sem emit/CNPJ — documento incompleto")

    # Competência — dhEmi: "2026-01-15T10:00:00-03:00"
    dh_emi = _text(inf, "ide", "dhEmi") or _text(inf, "ide", "dEmi") or ""
    if not dh_emi:
        raise NFeParserError("XML NFe sem ide/dhEmi — documento incompleto")
    competencia = dh_emi[:7]  # "YYYY-MM"
    if not re.match(r"^\d{4}-\d{2}$", competencia):
        raise NFeParserError(f"ide/dhEmi em formato inesperado: {dh_emi!r}")

    # Valores totais
    v_nf = _decimal(inf, "total", "ICMSTot", "vNF")
    v_icms_st = _decimal(inf, "total", "ICMSTot", "vICMSST")

    # Perfil do destinatário (1=contribuinte, 2=isento, 9=não contribuinte)
    ind_ie_dest = _text(inf, "dest", "indIEDest") or "9"

    # Chave de acesso (Id do infNFe, sem "NFe")
    chave = inf.get("Id", "").replace("NFe", "")

    return {
        "cnpj_emit": re.sub(r"\D", "", cnpj_emit),
        "competencia": competencia,
        "v_nf": v_nf,
        "v_icms_st": v_icms_st,
        "ind_ie_dest": ind_ie_dest,
        "mod": mod,
        "chave": chave,
    }


def parsear_xml_nfe(conteudo: bytes) -> NFeParsedData:
    """
    Parseia um único XML NFe 4.0 e retorna NFeParsedData.
    Para múltiplos XMLs do mesmo mês, use parsear_lote_nfe().

    Args:
        conteudo: bytes do arquivo XML NFe

    Returns:
        NFeParsedData com dados consolidados

    Raises:
        NFeParserError: se o XML for inválido ou faltar campos obrigatórios
    """
    etree = _get_lxml()
    try:
        root = etree.fromstring(conteudo)
    except etree.XMLSyntaxError as e:
        raise NFeParserError(f"XML inválido: {e}") from e

    tag = _strip_ns(root.tag)
    if tag not in ("nfeProc", "NFe", "infNFe"):
        raise NFeParserError(
            f"Namespace/root inesperado: <{tag}>. "
            "O arquivo não parece ser um XML NFe 4.0 SEFAZ."
        )

    nota = _extrair_uma_nota(root)

    return NFeParsedData(
        cnpj_emitente=nota["cnpj_emit"],
        competencia=nota["competencia"],
        valor_total_mes=nota["v_nf"],
        receita_st_icms=nota["v_icms_st"],
        pct_clientes_b2b=Decimal("1") if nota["ind_ie_dest"] == "1" else Decimal("0"),
        notas_processadas=1,
        chaves_nfe=[nota["chave"]] if nota["chave"] else [],
        modelo=nota["mod"],
    )


def parsear_lote_nfe(conteudos: list[bytes]) -> NFeParsedData:
    """
    Parseia múltiplos XMLs NFe do mesmo mês e consolida em um único NFeParsedData.
    Valida que todos os XMLs são do mesmo CNPJ emitente e mesmo período.

    Args:
        conteudos: lista de bytes de arquivos XML NFe

    Returns:
        NFeParsedData consolidado

    Raises:
        NFeParserError: se XMLs forem de CNPJs/meses diferentes
    """
    if not conteudos:
        raise NFeParserError("Lote vazio — nenhum XML NFe fornecido")

    notas = [parsear_xml_nfe(c) for c in conteudos]

    # Validar consistência
    cnpjs = {n.cnpj_emitente for n in notas}
    if len(cnpjs) > 1:
        raise NFeParserError(
            f"XMLs de CNPJs diferentes no mesmo lote: {cnpjs}. "
            "Cada análise deve conter XMLs de um único emitente."
        )
    competencias = {n.competencia for n in notas}
    if len(competencias) > 1:
        raise NFeParserError(
            f"XMLs de meses diferentes no mesmo lote: {competencias}. "
            "Cada análise deve conter XMLs de um único período."
        )

    # Consolidar
    valor_total = sum(n.valor_total_mes for n in notas)
    receita_st = sum(n.receita_st_icms for n in notas)
    chaves = [c for n in notas for c in n.chaves_nfe]

    # pct_clientes_b2b ponderado por valor
    valor_b2b = sum(
        n.valor_total_mes for n in notas if n.pct_clientes_b2b == Decimal("1")
    )
    pct_b2b = (
        (valor_b2b / valor_total).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        if valor_total > 0 else Decimal("0")
    )

    return NFeParsedData(
        cnpj_emitente=notas[0].cnpj_emitente,
        competencia=notas[0].competencia,
        valor_total_mes=valor_total,
        receita_st_icms=receita_st,
        pct_clientes_b2b=pct_b2b,
        notas_processadas=len(notas),
        chaves_nfe=chaves,
        modelo=notas[0].modelo,
    )
