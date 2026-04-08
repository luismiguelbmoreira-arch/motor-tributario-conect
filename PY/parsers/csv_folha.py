"""
Parser CSV/TXT Folha de Pagamento — Motor Tributário Conect
Extrai folha_salarios_12m para cálculo correto do Fator R.

Suporta: Domínio Folha (Thomson Reuters), genérico por detecção de header.
Codificações: UTF-8, Latin-1 (cp1252) — tenta ambas.
Separadores: ponto-e-vírgula (;) ou vírgula (,) — detectado automaticamente.

Amparo legal:
- LC 123/2006 Art. 18 §24 — Fator R = folha_12m / RBT12
  Fator R ≥ 28% → Anexo III; < 28% → Anexo V (serviços)
"""

from __future__ import annotations

import csv
import io
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from pydantic import BaseModel, Field

# ── Sinônimos de colunas por categoria ───────────────────────────────────────

ALIASES_FOLHA_TOTAL: list[str] = [
    "total folha",
    "folha liquida",
    "folha bruta",
    "vencimentos",
    "total vencimentos",
    "salario bruto",
    "total bruto",
    "pro_labore",
    "pro-labore",
    "prolabore",
    "remuneracao",
    "total remuneracao",
]

ALIASES_ENCARGOS: list[str] = [
    "inss patronal",
    "fgts",
    "encargos patronais",
    "total encargos",
    "contribuicao patronal",
    "encargos",
    "previdencia patronal",
    "total patronal",
]

ALIASES_COMPETENCIA: list[str] = [
    "competencia",
    "competência",
    "periodo",
    "período",
    "mes",
    "mês",
    "referencia",
    "referência",
    "data",
]

ALIASES_CNPJ: list[str] = [
    "cnpj",
    "empresa",
    "cnpj empresa",
]


class FolhaParsedData(BaseModel):
    """Dados de folha de pagamento extraídos de CSV/TXT."""

    cnpj_empresa: Optional[str] = Field(
        default=None, description="CNPJ da empresa (14 dígitos, se presente no CSV)"
    )
    folha_12m: Decimal = Field(..., description="Folha consolidada 12 meses (LC 123/2006 Art. 18 §24)")
    meses_encontrados: int = Field(..., description="Quantidade de meses distintos encontrados (1-12)")
    fonte_estimativa: bool = Field(
        default=False,
        description="True se < 12 meses no CSV — valor extrapolado ×12 com aviso ESTIMATIVA_FOLHA_1_MES"
    )
    competencias_processadas: list[str] = Field(
        default_factory=list, description="Lista de competências encontradas (YYYY-MM)"
    )
    avisos: list[str] = Field(
        default_factory=list, description="Avisos sobre qualidade/estimativa dos dados"
    )


class FolhaParserError(ValueError):
    """Erro de parsing de CSV de folha de pagamento."""


def _normalizar_header(col: str) -> str:
    """Remove acentos, pontuação e normaliza para comparação."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", col.lower().strip())
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", sem_acento).strip()


def _encontrar_coluna(headers: list[str], aliases: list[str]) -> Optional[int]:
    """Retorna o índice da primeira coluna que bate com um dos aliases."""
    norm_headers = [_normalizar_header(h) for h in headers]
    for alias in aliases:
        alias_norm = _normalizar_header(alias)
        for i, h in enumerate(norm_headers):
            if alias_norm in h or h in alias_norm:
                return i
    return None


def _to_decimal(valor: str) -> Optional[Decimal]:
    """Converte string de valor monetário brasileiro para Decimal."""
    if not valor or not valor.strip():
        return None
    # Remove espaços, R$, e normaliza separadores
    v = valor.strip().lstrip("R$").strip()
    # Formato BR: "1.234,56" → "1234.56"
    if "," in v and "." in v:
        v = v.replace(".", "").replace(",", ".")
    elif "," in v:
        v = v.replace(",", ".")
    # Remove caracteres não numéricos exceto ponto e sinal
    v = re.sub(r"[^\d.\-]", "", v)
    if not v:
        return None
    try:
        return Decimal(v).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except Exception:
        return None


def _parse_competencia(valor: str) -> Optional[str]:
    """
    Converte competência para YYYY-MM.
    Aceita: "01/2026", "2026-01", "Jan/2026", "01-2026".
    """
    if not valor or not valor.strip():
        return None
    v = valor.strip()

    # ISO: YYYY-MM ou YYYY-MM-DD
    m = re.match(r"^(\d{4})-(\d{2})", v)
    if m:
        return f"{m.group(1)}-{m.group(2)}"

    # BR: MM/AAAA ou MM-AAAA
    m = re.match(r"^(\d{1,2})[/\-](\d{4})$", v)
    if m:
        return f"{m.group(2)}-{m.group(1).zfill(2)}"

    # Nome do mês: "Janeiro/2026", "Jan/2026"
    MESES = {
        "jan": "01", "fev": "02", "mar": "03", "abr": "04",
        "mai": "05", "jun": "06", "jul": "07", "ago": "08",
        "set": "09", "out": "10", "nov": "11", "dez": "12",
    }
    m = re.match(r"^([a-zA-ZçÇ]{3,})[/\-\s](\d{4})$", v)
    if m:
        mes_abrev = m.group(1).lower()[:3]
        ano = m.group(2)
        mes_num = MESES.get(mes_abrev)
        if mes_num:
            return f"{ano}-{mes_num}"

    return None


def _decodificar(conteudo: bytes) -> str:
    """Tenta decodificar bytes com UTF-8, depois Latin-1 (cp1252)."""
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return conteudo.decode(enc)
        except UnicodeDecodeError:
            continue
    raise FolhaParserError(
        "Não foi possível decodificar o CSV de folha. "
        "Salve o arquivo como UTF-8 ou Latin-1."
    )


def _detectar_separador(texto: str) -> str:
    """Detecta separador predominante na primeira linha."""
    primeira = texto.split("\n")[0] if "\n" in texto else texto[:500]
    if primeira.count(";") >= primeira.count(","):
        return ";"
    return ","


def parsear_csv_folha(conteudo: bytes) -> FolhaParsedData:
    """
    Parseia CSV/TXT de folha de pagamento e extrai folha_salarios_12m.

    Estratégia:
    1. Detecta codificação (UTF-8 / Latin-1)
    2. Detecta separador (; ou ,)
    3. Detecta colunas por aliases (ALIASES_FOLHA_TOTAL, etc.)
    4. Agrupa por competência (YYYY-MM)
    5. Se < 12 meses: extrapola ×12 com aviso ESTIMATIVA_FOLHA_1_MES

    Args:
        conteudo: bytes do arquivo CSV/TXT

    Returns:
        FolhaParsedData com folha_12m calculada

    Raises:
        FolhaParserError: se o CSV não tiver coluna de total reconhecível
    """
    texto = _decodificar(conteudo)
    sep = _detectar_separador(texto)

    reader = csv.reader(io.StringIO(texto), delimiter=sep)
    rows = list(reader)

    # Encontrar linha de header — a primeira que tem mais de 2 colunas não vazias
    header_idx = None
    headers: list[str] = []
    for i, row in enumerate(rows):
        cols_nao_vazias = [c for c in row if c.strip()]
        if len(cols_nao_vazias) >= 2:
            header_idx = i
            headers = row
            break

    if header_idx is None:
        raise FolhaParserError("CSV de folha sem linha de cabeçalho reconhecível")

    # Mapear colunas
    idx_total = _encontrar_coluna(headers, ALIASES_FOLHA_TOTAL)
    idx_encargos = _encontrar_coluna(headers, ALIASES_ENCARGOS)
    idx_competencia = _encontrar_coluna(headers, ALIASES_COMPETENCIA)
    idx_cnpj = _encontrar_coluna(headers, ALIASES_CNPJ)

    if idx_total is None:
        raise FolhaParserError(
            f"CSV de folha sem coluna de total reconhecível. "
            f"Colunas encontradas: {headers}. "
            f"Esperado um dos: {ALIASES_FOLHA_TOTAL}"
        )

    # Processar linhas de dados
    por_competencia: dict[str, Decimal] = {}
    cnpj_empresa: Optional[str] = None
    avisos: list[str] = []

    for row in rows[header_idx + 1:]:
        # Pular linhas vazias ou de subtotal/rodapé (sem competência)
        if not any(c.strip() for c in row):
            continue
        if len(row) <= max(filter(None, [idx_total, idx_encargos, idx_competencia, 0])):
            continue

        # Competência
        competencia = None
        if idx_competencia is not None and idx_competencia < len(row):
            competencia = _parse_competencia(row[idx_competencia])

        # Valor total da linha
        if idx_total >= len(row):
            continue
        val_total = _to_decimal(row[idx_total])
        if val_total is None or val_total <= 0:
            continue

        # Encargos patronais (INSS + FGTS) — somados ao total se coluna separada
        val_encargos = Decimal("0")
        if idx_encargos is not None and idx_encargos < len(row):
            enc = _to_decimal(row[idx_encargos])
            if enc is not None and enc > 0:
                val_encargos = enc

        linha_total = val_total + val_encargos

        # Agrupa por competência
        chave = competencia or "_sem_competencia"
        if chave not in por_competencia:
            por_competencia[chave] = Decimal("0")
        por_competencia[chave] += linha_total

        # CNPJ
        if cnpj_empresa is None and idx_cnpj is not None and idx_cnpj < len(row):
            raw_cnpj = re.sub(r"\D", "", row[idx_cnpj])
            if len(raw_cnpj) == 14:
                cnpj_empresa = raw_cnpj

    if not por_competencia:
        raise FolhaParserError(
            "CSV de folha sem linhas de dados reconhecíveis. "
            "Verifique se a coluna de total está correta."
        )

    # Remover bucket sem competência se existirem outros com competência
    competencias_identificadas = [k for k in por_competencia if k != "_sem_competencia"]
    if competencias_identificadas:
        por_competencia.pop("_sem_competencia", None)
    else:
        # Sem competências identificadas — tratar tudo como um único mês
        total_sem_comp = por_competencia.get("_sem_competencia", Decimal("0"))
        por_competencia = {"_sem_competencia": total_sem_comp}

    # Calcular folha_12m
    meses = len(por_competencia)
    soma_meses = sum(por_competencia.values())
    fonte_estimativa = False

    if meses >= 12:
        # Usar os 12 maiores valores (protege contra mês parcial no início)
        folha_12m = sum(sorted(por_competencia.values(), reverse=True)[:12])
    elif meses == 1:
        folha_12m = soma_meses * 12
        fonte_estimativa = True
        avisos.append(
            "ESTIMATIVA_FOLHA_1_MES: apenas 1 mês encontrado no CSV. "
            "Folha extrapolada ×12. Para Fator R preciso, forneça 12 meses "
            "(LC 123/2006 Art. 18 §24)."
        )
    else:
        # 2-11 meses: extrapola proporcionalmente
        media_mensal = soma_meses / meses
        folha_12m = (media_mensal * 12).quantize(Decimal("0.01"), ROUND_HALF_UP)
        fonte_estimativa = True
        avisos.append(
            f"ESTIMATIVA_FOLHA_{meses}_MESES: {meses} meses encontrados. "
            f"Folha extrapolada pela média mensal ×12. "
            "Para Fator R preciso, forneça os 12 meses completos "
            "(LC 123/2006 Art. 18 §24)."
        )

    # Competências processadas em ordem cronológica
    comps_processadas = sorted(
        k for k in por_competencia.keys() if k != "_sem_competencia"
    )

    return FolhaParsedData(
        cnpj_empresa=cnpj_empresa,
        folha_12m=folha_12m.quantize(Decimal("0.01"), ROUND_HALF_UP),
        meses_encontrados=meses,
        fonte_estimativa=fonte_estimativa,
        competencias_processadas=comps_processadas,
        avisos=avisos,
    )
