"""
Parser SPED ECD (Escrituração Contábil Digital) — Motor Tributário Conect.

Formato exportado pelo Domínio Contábil (Thomson Reuters) em TXT
pipe-delimitado posicional. Layout oficial Receita Federal.

Blocos lidos:
    |0000|  — abertura (CNPJ, período, razão social)
    |I050|  — plano de contas
    |I200|  — cabeçalho de lançamento (data, valor, histórico)
    |I250|  — partidas do lançamento (conta, valor, D/C)

Blocos ignorados neste parser (podem existir mas não impactam cálculo):
    |0001|–|0010|  — identificação complementar
    |I150|         — saldos periódicos
    |I300|+        — outras demonstrações
    |9900|+        — controle

Amparo legal:
- Instrução Normativa RFB nº 2.003/2021 — ECD obrigatória
- Lei 6.404/76 Art. 177 — escrituração contábil
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from pydantic import BaseModel, Field


class SPEDEcdParserError(ValueError):
    """Erro ao parsear SPED ECD — arquivo corrompido, vazio ou sem bloco 0000."""


class LancamentoContabil(BaseModel):
    """Lançamento contábil com suas partidas (I200 + I250)."""

    numero: str
    data: date
    valor_total: Decimal
    historico: str = ""
    partidas: list[dict] = Field(default_factory=list)
    # Cada partida: {"conta": "1.1.01.001", "valor": Decimal, "dc": "D"|"C"}


class SPEDEcdParsedData(BaseModel):
    """Dados extraídos de arquivo SPED ECD do Domínio Contábil."""

    cnpj_empresa: str = Field(..., description="CNPJ (14 dígitos) do bloco |0000|")
    razao_social: str = ""
    periodo_inicio: date
    periodo_fim: date
    plano_contas: list[dict] = Field(default_factory=list)
    # Cada conta: {"codigo": "1.1.01.001", "nome": "Caixa", "tipo": "A"|"S"}
    lancamentos: list[LancamentoContabil] = Field(default_factory=list)
    total_debitos: Decimal = Decimal("0")
    total_creditos: Decimal = Decimal("0")
    avisos: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _decodificar(conteudo: bytes) -> str:
    """
    SPED ECD padrão é latin-1 (cp1252). Algumas exportações Domínio vêm
    em UTF-8 — tentamos ambos com fallback.
    """
    for encoding in ("latin-1", "cp1252", "utf-8"):
        try:
            return conteudo.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    raise SPEDEcdParserError(
        "Nao foi possivel decodificar o arquivo SPED ECD. "
        "Tente salvar em latin-1 ou UTF-8."
    )


def _parse_decimal(valor: str) -> Decimal:
    """
    SPED usa vírgula como separador decimal e sem separador de milhar.
    Exemplo: '1234,56' → Decimal('1234.56')
    """
    valor = (valor or "").strip().replace(",", ".")
    if not valor:
        return Decimal("0")
    try:
        return Decimal(valor)
    except InvalidOperation as exc:
        raise SPEDEcdParserError(f"Valor decimal invalido: '{valor}'") from exc


def _parse_data_sped(valor: str) -> date:
    """SPED formata datas como DDMMAAAA."""
    valor = (valor or "").strip()
    if len(valor) != 8:
        raise SPEDEcdParserError(
            f"Data SPED deve ter 8 digitos (DDMMAAAA), recebido: '{valor}'"
        )
    try:
        return datetime.strptime(valor, "%d%m%Y").date()
    except ValueError as exc:
        raise SPEDEcdParserError(f"Data SPED invalida: '{valor}'") from exc


def _split_registro(linha: str) -> list[str]:
    """
    Split por | e remove os campos vazios de extremidade.
    Linhas SPED sempre começam e terminam com |.
    Exemplo: '|0000|LECD|01012026|31122026|EMP|...|'
             → ['', '0000', 'LECD', '01012026', '31122026', 'EMP', ..., '']
    """
    campos = linha.split("|")
    # Remove extremos vazios (primeiro e último)
    if campos and campos[0] == "":
        campos = campos[1:]
    if campos and campos[-1] == "":
        campos = campos[:-1]
    return campos


# ─────────────────────────────────────────────────────────────────────────────
# PARSER PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────

def parsear_sped_ecd(conteudo: bytes) -> SPEDEcdParsedData:
    """
    Parseia arquivo SPED ECD em bytes e retorna SPEDEcdParsedData.

    Exigências mínimas:
    - Deve ter bloco |0000| com CNPJ + datas de período
    - Lançamentos são opcionais (arquivo vazio de movimento é válido)

    Raises:
        SPEDEcdParserError: arquivo vazio, sem 0000, ou campos inválidos
    """
    if not conteudo:
        raise SPEDEcdParserError("Arquivo SPED ECD vazio.")

    texto = _decodificar(conteudo)
    linhas = [ln for ln in texto.splitlines() if ln.strip()]

    # Estado do parser
    cnpj: Optional[str] = None
    razao_social = ""
    periodo_inicio: Optional[date] = None
    periodo_fim: Optional[date] = None
    plano_contas: list[dict] = []
    lancamentos: list[LancamentoContabil] = []
    avisos: list[str] = []

    lancamento_atual: Optional[LancamentoContabil] = None
    total_debitos = Decimal("0")
    total_creditos = Decimal("0")

    for linha in linhas:
        campos = _split_registro(linha)
        if not campos:
            continue
        registro = campos[0]

        # ── Bloco 0000: abertura ────────────────────────────────────────────
        if registro == "0000":
            # Layout: |0000|LECD|DT_INI|DT_FIN|NOME|CNPJ|UF|IE|COD_MUN|IM|IND_SIT_ESP|IND_SIT_INI_PER|IND_NIRE|IND_FIN_ESC|COD_SCP|IDENT_MF|IND_ESC_CONS|COD_SCP_CONS|DT_EX_SOCIAL
            # Alguns exportadores Domínio omitem LECD na posição 1 — lidamos.
            idx_offset = 0
            if len(campos) > 1 and campos[1] == "LECD":
                idx_offset = 1

            if len(campos) < 6 + idx_offset:
                raise SPEDEcdParserError(
                    f"Bloco 0000 incompleto: {len(campos)} campos. "
                    "Esperado: 0000|[LECD]|DT_INI|DT_FIN|NOME|CNPJ|..."
                )

            try:
                periodo_inicio = _parse_data_sped(campos[1 + idx_offset])
                periodo_fim = _parse_data_sped(campos[2 + idx_offset])
                razao_social = campos[3 + idx_offset].strip()
                cnpj_raw = campos[4 + idx_offset].strip()
                cnpj = "".join(c for c in cnpj_raw if c.isdigit())
                if len(cnpj) != 14:
                    raise SPEDEcdParserError(
                        f"CNPJ no bloco 0000 tem {len(cnpj)} digitos, esperado 14: '{cnpj_raw}'"
                    )
            except IndexError as exc:
                raise SPEDEcdParserError(
                    "Bloco 0000 nao tem todos os campos obrigatorios."
                ) from exc

        # ── Bloco I050: plano de contas ─────────────────────────────────────
        elif registro == "I050":
            # Layout: |I050|DT_ALT|COD_NAT|IND_CTA|NIVEL|COD_CTA|COD_CTA_SUP|CTA
            if len(campos) >= 8:
                plano_contas.append({
                    "codigo": campos[5].strip(),
                    "nome": campos[7].strip(),
                    "tipo": campos[3].strip(),  # A=analitica, S=sintetica
                })

        # ── Bloco I200: cabeçalho de lançamento ─────────────────────────────
        elif registro == "I200":
            # Layout: |I200|NUM_LCTO|DT_LCTO|VL_LCTO|IND_LCTO
            if len(campos) < 5:
                avisos.append(f"I200 incompleto ignorado: {linha[:60]}")
                continue
            try:
                lancamento_atual = LancamentoContabil(
                    numero=campos[1].strip(),
                    data=_parse_data_sped(campos[2]),
                    valor_total=_parse_decimal(campos[3]),
                    historico="",
                    partidas=[],
                )
                lancamentos.append(lancamento_atual)
            except SPEDEcdParserError as exc:
                avisos.append(f"I200 invalido ignorado: {exc}")
                lancamento_atual = None

        # ── Bloco I250: partidas do lançamento ──────────────────────────────
        elif registro == "I250":
            # Layout: |I250|COD_CTA|COD_CCUS|VL_DC|IND_DC|NUM_ARQ|COD_HIST_PAD|HIST
            if lancamento_atual is None:
                avisos.append(f"I250 sem I200 anterior ignorado: {linha[:60]}")
                continue
            if len(campos) < 5:
                continue
            try:
                partida_valor = _parse_decimal(campos[3])
                partida_dc = campos[4].strip().upper()
                if partida_dc not in ("D", "C"):
                    avisos.append(f"I250 IND_DC invalido ('{partida_dc}'), ignorado")
                    continue
                lancamento_atual.partidas.append({
                    "conta": campos[1].strip(),
                    "valor": partida_valor,
                    "dc": partida_dc,
                })
                if partida_dc == "D":
                    total_debitos += partida_valor
                else:
                    total_creditos += partida_valor

                # Histórico vem depois
                if len(campos) >= 8 and not lancamento_atual.historico:
                    lancamento_atual.historico = campos[7].strip()
            except SPEDEcdParserError as exc:
                avisos.append(f"I250 invalido: {exc}")

    # ── Validação final ────────────────────────────────────────────────────
    if cnpj is None or periodo_inicio is None or periodo_fim is None:
        raise SPEDEcdParserError(
            "Arquivo SPED ECD nao tem bloco |0000| valido (CNPJ ou periodo ausente)."
        )

    # Partida dobrada: débitos devem bater com créditos
    if total_debitos != total_creditos:
        delta = abs(total_debitos - total_creditos)
        avisos.append(
            f"Partida dobrada quebrada: debitos R$ {total_debitos:,.2f} != "
            f"creditos R$ {total_creditos:,.2f} (delta R$ {delta:,.2f})"
        )



    return SPEDEcdParsedData(
        cnpj_empresa=cnpj,
        razao_social=razao_social,
        periodo_inicio=periodo_inicio,
        periodo_fim=periodo_fim,
        plano_contas=plano_contas,
        lancamentos=lancamentos,
        total_debitos=total_debitos,
        total_creditos=total_creditos,
        avisos=avisos,
    )
