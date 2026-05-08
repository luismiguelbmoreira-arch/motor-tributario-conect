# -*- coding: utf-8 -*-
"""
core/refazer.py — WS5 (Rail R6 — logs refazíveis)

Função pura `verificar_diagnostico(resultado)` que recebe o dict resultado
persistido (`DiagnosticoDB.resultado_json` desserializado) e devolve um
relatório frozen verificando:

  1. Estrutura mínima (MAX_01) — todo evento tem tipo, id, timestamp
  2. Citação legal (MAX_02) — todo evento (exceto VIOLACAO) tem amparo_legal
  3. Aritmética dos eventos CALCULO — quando memoria é parseable como Decimal
     ((base - deducoes) * aliquota = valor_final), recalcula e compara
  4. Sem violações de segurança — VIOLACAO_SEGURANCA invalida o diagnóstico

CONTRATO Rail R6: "Cada cálculo gera log auto-suficiente. refazer_calculo
reconstroi o número apenas do log."

Quando o evento NÃO é verificável automaticamente (alíquota textual tipo
"0,0% IBS + 0,0% CBS (imune)", base com texto), marca status
NAO_VERIFICAVEL_AUTOMATICO sem bloquear consistência. Operador deve
auditar manualmente esses casos.

Uso típico:
    from core.refazer import verificar_diagnostico
    relatorio = verificar_diagnostico(diagnostico_db.get_resultado())
    if not relatorio.consistente:
        sys.exit(1)
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Tolerância de centavos para comparação Decimal
TOLERANCIA_CENTAVOS = Decimal("0.02")

# Tipos de status por evento na ordem da trilha
StatusEventoLiteral = Literal[
    "MATCH",                       # aritmética bate
    "DIVERGENCIA",                 # aritmética não bate (acima da tolerância)
    "NAO_VERIFICAVEL_AUTOMATICO",  # memoria sem Decimals limpos (ex: alíquota textual)
    "VIOLACAO",                    # VIOLACAO_SEGURANCA — Camada 2 acionada
    "INFORMATIVO",                 # ALERTA_*, CALCULO sem aritmética parseável (timestamp puro)
    "MALFORMADO",                  # estrutura mínima quebrada (sem id, etc.)
]


# ─────────────────────────────────────────────────────────────────────────────
# DATA CLASSES IMUTÁVEIS
# ─────────────────────────────────────────────────────────────────────────────

class DivergenciaCalculo(BaseModel):
    """Cálculo CALCULO cujo recálculo difere do declarado além da tolerância."""

    model_config = ConfigDict(frozen=True)

    id: str
    base: Decimal
    deducoes: Decimal
    aliquota: Decimal
    declarado: Decimal
    esperado_recalculado: Decimal
    delta: Decimal


class StatusVerificacao(BaseModel):
    """Status de cada evento da trilha, na ordem original."""

    model_config = ConfigDict(frozen=True)

    indice: int = Field(description="Posição na trilha original (0-based).")
    id: str = Field(description="ID do evento (ou '<sem_id>' se ausente).")
    tipo: str
    status: StatusEventoLiteral
    detalhe: str = ""


class RelatorioVerificacao(BaseModel):
    """Relatório consolidado da verificação Rail R6."""

    model_config = ConfigDict(frozen=True)

    consistente: bool = Field(
        description=(
            "True se: zero divergências aritméticas, zero VIOLACAO_SEGURANCA, "
            "zero eventos malformados, zero eventos sem amparo legal."
        )
    )
    total_eventos: int
    por_tipo: dict[str, int] = Field(default_factory=dict)
    divergencias: tuple[DivergenciaCalculo, ...] = ()
    nao_verificaveis: tuple[StatusVerificacao, ...] = ()
    eventos_sem_amparo: tuple[str, ...] = ()
    eventos_malformados: tuple[str, ...] = ()
    violacoes_seguranca: tuple[str, ...] = ()
    status_por_evento: tuple[StatusVerificacao, ...] = ()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_SENTINELAS_NAO_NUMERICOS = frozenset({
    "N/A", "NA", "-", "--", "S/I", "SEM INFORMACAO",
})


def _to_decimal(valor: Any) -> Optional[Decimal]:
    """
    Tenta converter valor pra Decimal. Devolve None se for textual/inválido.

    Reconhece formatos do motor:
      - "R$ 1.000.000,00" (BR) → Decimal("1000000.00")
      - "R$ 1.234,56"           → Decimal("1234.56")
      - "8.90%"                 → Decimal("0.089")  (americano + %)
      - "8,90%"                 → Decimal("0.089")  (BR + %)
      - "0.10"                  → Decimal("0.10")
      - "0,10"                  → Decimal("0.10")

    Devolve None pra:
      - "N/A", "NA", "-" (sentinelas explícitos)
      - "Anexo III", "Status: TESTE" (sentinelas com letra fora de prefixo)
      - "Nominal 20.50%" (texto + número misturado — preferir NAO_VERIFICAVEL
        ao chute aritmético com a fórmula genérica errada)
    """
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return valor
    if isinstance(valor, (int, float)):
        return Decimal(str(valor))
    if not isinstance(valor, str):
        return None

    s = valor.strip()
    if not s:
        return None
    if s.upper() in _SENTINELAS_NAO_NUMERICOS:
        return None

    # Remove prefixo monetário "R$" e "$" (com ou sem espaço)
    s_limpo = s.replace("R$", "").replace("$", "").strip()

    # Detecta sufixo "%" — aliquota percentual (vai dividir por 100 no fim)
    eh_percentual = False
    if s_limpo.endswith("%"):
        eh_percentual = True
        s_limpo = s_limpo[:-1].strip()

    # Após esses limpadores, qualquer letra remanescente é texto livre
    # (ex: "Nominal 20.50", "Valor NF 100.000,00", "Anexo III"). Tratar
    # como texto: o número pode estar embebido, mas não é seguro extrair
    # automaticamente — preferir NAO_VERIFICAVEL.
    if any(c.isalpha() for c in s_limpo):
        # Última tentativa: se for "<texto> <número>" com 1 número claro
        # no final, extrai. Ex: "Valor NF R$ 100.000,00" → após remover R$,
        # vira "Valor NF 100.000,00".
        partes = s_limpo.split()
        if len(partes) >= 2 and not any(c.isalpha() for c in partes[-1]):
            s_limpo = partes[-1]
        else:
            return None

    # Sem espaços internos
    s_limpo = s_limpo.replace(" ", "")
    if not s_limpo:
        return None

    # Heurística BR/Americano:
    # - Tem ponto E vírgula → BR (ponto = milhar, vírgula = decimal)
    # - Só vírgula → BR (vírgula = decimal)
    # - Só ponto ou só dígitos → mantém (americano ou puro)
    if "." in s_limpo and "," in s_limpo:
        s_limpo = s_limpo.replace(".", "").replace(",", ".")
    elif "," in s_limpo:
        s_limpo = s_limpo.replace(",", ".")

    try:
        d = Decimal(s_limpo)
    except (InvalidOperation, ValueError):
        return None

    if eh_percentual:
        d = d / Decimal("100")
    return d


def _evento_eh_violacao(evento: dict) -> bool:
    return evento.get("tipo") == "VIOLACAO_SEGURANCA"


def _evento_eh_calculo(evento: dict) -> bool:
    return evento.get("tipo") == "CALCULO"


def _malformado(evento: dict) -> bool:
    """Estrutura mínima (MAX_01): tipo, id, timestamp."""
    return (
        "tipo" not in evento
        or "id" not in evento
        or "timestamp" not in evento
    )


def _sem_amparo(evento: dict) -> bool:
    """Citação legal obrigatória (MAX_02), exceto pra VIOLACAO_SEGURANCA."""
    if _evento_eh_violacao(evento):
        return False  # violacao em si é a falha — amparo é opcional
    amparo = (evento.get("amparo_legal") or "").strip()
    return amparo == ""


# ─────────────────────────────────────────────────────────────────────────────
# RECALCULO ARITMÉTICO
# ─────────────────────────────────────────────────────────────────────────────

def _tentar_recalcular(
    evento: dict,
) -> tuple[StatusEventoLiteral, Optional[DivergenciaCalculo]]:
    """
    Tenta recalcular um evento CALCULO via fórmula canônica:
        esperado = (base - deducoes) * aliquota

    Retorna:
      ("MATCH", None) — recálculo dentro da tolerância
      ("DIVERGENCIA", DivergenciaCalculo) — fora da tolerância
      ("NAO_VERIFICAVEL_AUTOMATICO", None) — memoria não parseable
      ("INFORMATIVO", None) — evento sem campos de cálculo (timestamp puro)
    """
    memoria = evento.get("memoria") or {}
    if not memoria:
        return "INFORMATIVO", None

    base = _to_decimal(memoria.get("base"))
    deducoes = _to_decimal(memoria.get("deducoes"))
    aliquota = _to_decimal(memoria.get("aliquota"))
    declarado = _to_decimal(memoria.get("valor_final"))

    if any(v is None for v in (base, deducoes, aliquota, declarado)):
        return "NAO_VERIFICAVEL_AUTOMATICO", None

    esperado = (base - deducoes) * aliquota  # type: ignore[operator]
    delta = abs(esperado - declarado)  # type: ignore[operator]

    if delta <= TOLERANCIA_CENTAVOS:
        return "MATCH", None

    return "DIVERGENCIA", DivergenciaCalculo(
        id=str(evento.get("id", "<sem_id>")),
        base=base,  # type: ignore[arg-type]
        deducoes=deducoes,  # type: ignore[arg-type]
        aliquota=aliquota,  # type: ignore[arg-type]
        declarado=declarado,  # type: ignore[arg-type]
        esperado_recalculado=esperado,
        delta=delta,
    )


# ─────────────────────────────────────────────────────────────────────────────
# API PÚBLICA
# ─────────────────────────────────────────────────────────────────────────────

def verificar_diagnostico(resultado: dict) -> RelatorioVerificacao:
    """
    Verifica integridade Rail R6 do dict resultado de um diagnóstico.

    Args:
        resultado: dict com chave "trilha_auditoria" contendo lista de eventos.

    Returns:
        RelatorioVerificacao frozen com diagnóstico completo (consistente,
        divergências, eventos malformados, violações, status por evento).

    Raises:
        KeyError: se "trilha_auditoria" não existir no resultado.
    """
    if "trilha_auditoria" not in resultado:
        raise KeyError(
            "resultado não tem campo 'trilha_auditoria' — não é diagnóstico "
            "do motor (ou está corrompido)."
        )

    trilha: list[dict] = resultado["trilha_auditoria"] or []

    divergencias: list[DivergenciaCalculo] = []
    nao_verificaveis: list[StatusVerificacao] = []
    eventos_sem_amparo: list[str] = []
    eventos_malformados: list[str] = []
    violacoes: list[str] = []
    status_lista: list[StatusVerificacao] = []
    contador_tipo: Counter = Counter()

    for idx, evento in enumerate(trilha):
        evento_id = str(evento.get("id", "<sem_id>"))
        tipo = evento.get("tipo", "<sem_tipo>")
        contador_tipo[tipo] += 1

        # Estrutura mínima
        if _malformado(evento):
            eventos_malformados.append(evento_id)
            status_lista.append(StatusVerificacao(
                indice=idx, id=evento_id, tipo=tipo, status="MALFORMADO",
                detalhe="Falta tipo, id ou timestamp.",
            ))
            continue

        # Violação de segurança
        if _evento_eh_violacao(evento):
            violacoes.append(evento_id)
            status_lista.append(StatusVerificacao(
                indice=idx, id=evento_id, tipo=tipo, status="VIOLACAO",
                detalhe="VIOLACAO_SEGURANCA — Camada 2 (Guard Clause) acionada.",
            ))
            continue

        # Citação legal (MAX_02)
        if _sem_amparo(evento):
            eventos_sem_amparo.append(evento_id)

        # Aritmética (CALCULO)
        if _evento_eh_calculo(evento):
            status, divergencia = _tentar_recalcular(evento)
            sv = StatusVerificacao(
                indice=idx, id=evento_id, tipo=tipo, status=status,
                detalhe=(
                    f"esperado={divergencia.esperado_recalculado} "
                    f"declarado={divergencia.declarado} "
                    f"delta={divergencia.delta}"
                ) if divergencia else "",
            )
            status_lista.append(sv)
            if divergencia is not None:
                divergencias.append(divergencia)
            elif status == "NAO_VERIFICAVEL_AUTOMATICO":
                nao_verificaveis.append(sv)
        else:
            # Eventos não-CALCULO (ALERTA_*, AJUSTE_*, etc.) viram INFORMATIVO
            status_lista.append(StatusVerificacao(
                indice=idx, id=evento_id, tipo=tipo, status="INFORMATIVO",
            ))

    consistente = (
        len(divergencias) == 0
        and len(violacoes) == 0
        and len(eventos_malformados) == 0
        and len(eventos_sem_amparo) == 0
    )

    return RelatorioVerificacao(
        consistente=consistente,
        total_eventos=len(trilha),
        por_tipo=dict(contador_tipo),
        divergencias=tuple(divergencias),
        nao_verificaveis=tuple(nao_verificaveis),
        eventos_sem_amparo=tuple(eventos_sem_amparo),
        eventos_malformados=tuple(eventos_malformados),
        violacoes_seguranca=tuple(violacoes),
        status_por_evento=tuple(status_lista),
    )
