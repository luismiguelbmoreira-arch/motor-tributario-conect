"""
Parser SPED EFD-Contribuicoes (PIS/COFINS) — Motor Tributario Conect.

Formato exportado pelo Dominio Escrita Fiscal (Thomson Reuters) em TXT
pipe-delimitado posicional. Layout oficial Receita Federal.

Blocos lidos:
    |0000|  — abertura (CNPJ, periodo, indicador de natureza)
    |0110|  — regime de apuracao (cumulativo, nao cumulativo)
    |M200|  — consolidacao PIS/PASEP do periodo
    |M600|  — consolidacao COFINS do periodo

Usado para:
    - Crosscheck PIS/COFINS declarado vs somatorio das NFes (anomalia)
    - Validacao de regime (Simples Nacional nao deve ter EFD-Contrib)

Amparo legal:
- Lei 10.637/2002 (PIS nao cumulativo)
- Lei 10.833/2003 (COFINS nao cumulativo)
- Lei 9.718/1998 (cumulativo)
- IN RFB 1.252/2012 (EFD-Contribuicoes)
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, Optional

from pydantic import BaseModel, Field

from observability.schema_registry import validar_campos


class SPEDEfdContribParserError(ValueError):
    """Erro ao parsear SPED EFD-Contribuicoes."""


RegimeApuracao = Literal["cumulativo", "nao_cumulativo", "misto", "desconhecido"]


class SPEDEfdContribParsedData(BaseModel):
    """Dados extraidos de arquivo SPED EFD-Contribuicoes."""

    cnpj_empresa: str = Field(..., description="CNPJ (14 digitos) do bloco |0000|")
    periodo: str = Field(..., description="Competencia YYYY-MM")
    periodo_inicio: date
    periodo_fim: date
    regime: RegimeApuracao = "desconhecido"

    # PIS (bloco M200)
    pis_total_contribuicao: Decimal = Decimal("0")
    pis_total_credito: Decimal = Decimal("0")
    pis_valor_devido: Decimal = Decimal("0")

    # COFINS (bloco M600)
    cofins_total_contribuicao: Decimal = Decimal("0")
    cofins_total_credito: Decimal = Decimal("0")
    cofins_valor_devido: Decimal = Decimal("0")

    avisos: list[str] = Field(default_factory=list)

    @property
    def tributo_total(self) -> Decimal:
        return self.pis_valor_devido + self.cofins_valor_devido


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS (reusam lógica do sped_ecd mas duplicamos para isolamento)
# ─────────────────────────────────────────────────────────────────────────────

def _decodificar(conteudo: bytes) -> str:
    for encoding in ("latin-1", "cp1252", "utf-8"):
        try:
            return conteudo.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    raise SPEDEfdContribParserError(
        "Nao foi possivel decodificar o arquivo SPED EFD-Contribuicoes."
    )


def _parse_decimal(valor: str) -> Decimal:
    valor = (valor or "").strip().replace(",", ".")
    if not valor:
        return Decimal("0")
    try:
        return Decimal(valor)
    except InvalidOperation as exc:
        raise SPEDEfdContribParserError(f"Valor decimal invalido: '{valor}'") from exc


def _parse_data_sped(valor: str) -> date:
    valor = (valor or "").strip()
    if len(valor) != 8:
        raise SPEDEfdContribParserError(
            f"Data SPED deve ter 8 digitos (DDMMAAAA), recebido: '{valor}'"
        )
    try:
        return datetime.strptime(valor, "%d%m%Y").date()
    except ValueError as exc:
        raise SPEDEfdContribParserError(f"Data invalida: '{valor}'") from exc


def _split_registro(linha: str) -> list[str]:
    campos = linha.split("|")
    if campos and campos[0] == "":
        campos = campos[1:]
    if campos and campos[-1] == "":
        campos = campos[:-1]
    return campos


def _mapear_regime(ind_apro_cred: str) -> RegimeApuracao:
    """
    Bloco 0110 campo IND_APRO_CRED:
        1 = Metodo de Apropriacao Direta (nao cumulativo)
        2 = Metodo de Rateio Proporcional (nao cumulativo misto)
        3 = Cumulativo
    """
    cod = (ind_apro_cred or "").strip()
    if cod == "1":
        return "nao_cumulativo"
    if cod == "2":
        return "misto"
    if cod == "3":
        return "cumulativo"
    return "desconhecido"


# ─────────────────────────────────────────────────────────────────────────────
# PARSER PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def parsear_sped_efd_contrib(conteudo: bytes) -> SPEDEfdContribParsedData:
    """
    Parseia arquivo SPED EFD-Contribuicoes.

    Retorna SPEDEfdContribParsedData com PIS e COFINS consolidados.
    Se nao houver bloco M200 (sem movimento PIS), retorna valores zerados.

    Raises:
        SPEDEfdContribParserError: arquivo vazio, sem 0000, ou campos invalidos
    """
    if not conteudo:
        raise SPEDEfdContribParserError("Arquivo SPED EFD-Contribuicoes vazio.")

    texto = _decodificar(conteudo)
    linhas = [ln for ln in texto.splitlines() if ln.strip()]

    cnpj: Optional[str] = None
    periodo_inicio: Optional[date] = None
    periodo_fim: Optional[date] = None
    regime: RegimeApuracao = "desconhecido"

    pis_total = Decimal("0")
    pis_credito = Decimal("0")
    pis_devido = Decimal("0")

    cofins_total = Decimal("0")
    cofins_credito = Decimal("0")
    cofins_devido = Decimal("0")

    avisos: list[str] = []

    for linha in linhas:
        campos = _split_registro(linha)
        if not campos:
            continue
        registro = campos[0]

        # ── Bloco 0000: abertura ────────────────────────────────────────────
        if registro == "0000":
            # Layout: |0000|COD_VER|TIPO_ESCRIT|IND_SIT_ESP|NUM_REC_ANTERIOR|DT_INI|DT_FIN|NOME|CNPJ|UF|COD_MUN|SUFRAMA|IND_NAT_PJ|IND_ATIV
            if len(campos) < 9:
                raise SPEDEfdContribParserError(
                    f"Bloco 0000 EFD-Contrib incompleto: {len(campos)} campos."
                )
            try:
                periodo_inicio = _parse_data_sped(campos[5])
                periodo_fim = _parse_data_sped(campos[6])
                cnpj_raw = campos[8].strip()
                cnpj = "".join(c for c in cnpj_raw if c.isdigit())
                if len(cnpj) != 14:
                    raise SPEDEfdContribParserError(
                        f"CNPJ invalido no bloco 0000: '{cnpj_raw}'"
                    )
            except IndexError as exc:
                raise SPEDEfdContribParserError(
                    "Bloco 0000 EFD-Contrib sem campos obrigatorios."
                ) from exc

        # ── Bloco 0110: regime ──────────────────────────────────────────────
        elif registro == "0110":
            # Layout: |0110|COD_INC_TRIB|IND_APRO_CRED|COD_TIPO_CONT|IND_REG_CUM
            if len(campos) >= 3:
                regime = _mapear_regime(campos[2])

        # ── Bloco M200: consolidacao PIS ───────────────────────────────────
        elif registro == "M200":
            # Layout simplificado:
            # |M200|VL_TOT_CONT_NC_PER|VL_TOT_CRED_DESC|VL_TOT_CRED_DESC_ANT|
            #       VL_TOT_CONT_NC_DEV|VL_RET_NC|VL_OUT_DED_NC|VL_CONT_NC_REC|
            #       VL_TOT_CONT_CUM_PER|VL_RET_CUM|VL_OUT_DED_CUM|VL_CONT_CUM_REC|
            #       VL_TOT_CONT_REC
            try:
                # Nao cumulativo
                pis_total_nc = _parse_decimal(campos[1]) if len(campos) > 1 else Decimal("0")
                pis_credito_nc = _parse_decimal(campos[2]) if len(campos) > 2 else Decimal("0")
                pis_devido_nc = _parse_decimal(campos[4]) if len(campos) > 4 else Decimal("0")
                # Cumulativo
                pis_total_cum = _parse_decimal(campos[8]) if len(campos) > 8 else Decimal("0")
                pis_devido_cum = _parse_decimal(campos[11]) if len(campos) > 11 else Decimal("0")

                pis_total = pis_total_nc + pis_total_cum
                pis_credito = pis_credito_nc
                pis_devido = pis_devido_nc + pis_devido_cum
            except SPEDEfdContribParserError as exc:
                avisos.append(f"M200 (PIS) campos invalidos: {exc}")

        # ── Bloco M600: consolidacao COFINS ────────────────────────────────
        elif registro == "M600":
            # Mesmo layout do M200 mas para COFINS
            try:
                cofins_total_nc = _parse_decimal(campos[1]) if len(campos) > 1 else Decimal("0")
                cofins_credito_nc = _parse_decimal(campos[2]) if len(campos) > 2 else Decimal("0")
                cofins_devido_nc = _parse_decimal(campos[4]) if len(campos) > 4 else Decimal("0")
                cofins_total_cum = _parse_decimal(campos[8]) if len(campos) > 8 else Decimal("0")
                cofins_devido_cum = _parse_decimal(campos[11]) if len(campos) > 11 else Decimal("0")

                cofins_total = cofins_total_nc + cofins_total_cum
                cofins_credito = cofins_credito_nc
                cofins_devido = cofins_devido_nc + cofins_devido_cum
            except SPEDEfdContribParserError as exc:
                avisos.append(f"M600 (COFINS) campos invalidos: {exc}")

    # ── Validacao final ────────────────────────────────────────────────────
    if cnpj is None or periodo_inicio is None or periodo_fim is None:
        raise SPEDEfdContribParserError(
            "Arquivo SPED EFD-Contribuicoes sem bloco |0000| valido."
        )

    if regime == "desconhecido":
        avisos.append(
            "Regime de apuracao nao identificado (bloco 0110 ausente ou invalido)."
        )

    periodo_str = periodo_inicio.strftime("%Y-%m")

    # Gate do schema registry
    validar_campos(
        "sped_efd_contrib",
        [
            "0000/CNPJ",
            "0000/DT_INI",
            "0000/DT_FIN",
            "0110/IND_APRO_CRED",
            "M200/VL_TOT_CONT_NC_PER",
            "M200/VL_TOT_CRED_DESC",
            "M600/VL_TOT_CONT_NC_PER",
            "M600/VL_TOT_CRED_DESC",
        ],
    )

    return SPEDEfdContribParsedData(
        cnpj_empresa=cnpj,
        periodo=periodo_str,
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
        regime=regime,
        pis_total_contribuicao=pis_total,
        pis_total_credito=pis_credito,
        pis_valor_devido=pis_devido,
        cofins_total_contribuicao=cofins_total,
        cofins_total_credito=cofins_credito,
        cofins_valor_devido=cofins_devido,
        avisos=avisos,
    )
