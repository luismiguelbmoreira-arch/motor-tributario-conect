"""
catalogo_documentos.py — Catálogo declarativo de documentos requeridos.

Dado (perfil, regime, período-base), devolve a lista de cards que a UI
deve renderizar. Centraliza IDs, labels, amparo legal e período derivado
numa única fonte de verdade. Usado pelo endpoint GET /documentos-requeridos.

IDs alinhados com `_detectar_tipo_documento()` em api_motor.py:1040 para
garantir round-trip entre "o que o card pede" e "o que o validador aceita".

Amparo legal:
    LC 123/2006 Art. 18        — PGDAS-D + DAS (Simples Nacional)
    LC 123/2006 Art. 13 §1º V  — NFe obrigatória B2B (ICMS-ST + receita real)
    LC 123/2006 Art. 18 §24    — Folha p/ Fator R
    LC 123/2006 Art. 3º §2º    — NFCe / PDV B2C
    IN RFB 2.003/2021          — SPED ECD
    IN RFB 1.252/2012          — SPED EFD-Contribuições
    LC 123/2006 Art. 18-A      — MEI (DAS fixo)
"""
from __future__ import annotations

from typing import Literal

from schemas.documentos_requeridos import DocumentoRequerido
from utils.periodo_base import PeriodoBase

Perfil = Literal["B2B_CONTRIBUINTE", "B2C_CONSUMIDOR_FINAL", "MISTO"]
Regime = Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI"]

PERFIS_VALIDOS: tuple[str, ...] = ("B2B_CONTRIBUINTE", "B2C_CONSUMIDOR_FINAL", "MISTO")
REGIMES_VALIDOS: tuple[str, ...] = ("SIMPLES", "PRESUMIDO", "REAL", "MEI")


# ─── Helpers de formatação de período ─────────────────────────────────────


def _periodo_mensal_label(periodo: PeriodoBase) -> str:
    """'01/2025 a 12/2025' (padrão) ou '04/2025 a 03/2026' (janela móvel)."""
    ini_ano, ini_mes = periodo.rbt12_inicio.split("-")
    fim_ano, fim_mes = periodo.rbt12_fim.split("-")
    return f"{ini_mes}/{ini_ano} a {fim_mes}/{fim_ano}"


def _periodo_mensal_iso(periodo: PeriodoBase) -> str:
    return f"{periodo.rbt12_inicio}..{periodo.rbt12_fim}"


def _das_label(periodo: PeriodoBase) -> str:
    """'Dezembro/2025' — último mês fechado."""
    ano, mes = periodo.das_referencia.split("-")
    meses = [
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
    ]
    return f"{meses[int(mes) - 1]}/{ano}"


def _exercicio_label(periodo: PeriodoBase) -> str:
    return f"Exercício {periodo.exercicio_sped}"


# ─── Montagem declarativa ─────────────────────────────────────────────────


def _card_pgdas_d(periodo: PeriodoBase) -> DocumentoRequerido:
    return DocumentoRequerido(
        id="pgdas_d",
        label="PGDAS-D — Extrato Simples Nacional",
        descricao="Extrato mensal do Portal do Simples (e-CAC). Mínimo: mês de referência do DAS.",
        periodo_label=f"Mensal — {_periodo_mensal_label(periodo)}",
        periodo_iso=_periodo_mensal_iso(periodo),
        extensao=".pdf",
        obrigatorio=True,
        amparo_legal="LC 123/2006 Art. 18",
        nivel="base",
        automacao_disponivel="Fase 2B (Integra Contador/Serpro)",
    )


def _card_das(periodo: PeriodoBase) -> DocumentoRequerido:
    return DocumentoRequerido(
        id="das",
        label="DAS — Comprovante de pagamento",
        descricao="Guia paga do DAS do mês de referência (semáforo anual).",
        periodo_label=_das_label(periodo),
        periodo_iso=periodo.das_referencia,
        extensao=".pdf",
        obrigatorio=False,
        amparo_legal="LC 123/2006 Art. 21",
        nivel="base",
        automacao_disponivel="Fase 2B (Integra Contador/Serpro)",
    )


def _card_nfe_saida(periodo: PeriodoBase) -> DocumentoRequerido:
    return DocumentoRequerido(
        id="nfe_saida",
        label="XML NFe modelo 55 (saída)",
        descricao="Notas fiscais eletrônicas emitidas — receita real B2B + ICMS-ST.",
        periodo_label=_periodo_mensal_label(periodo),
        periodo_iso=_periodo_mensal_iso(periodo),
        extensao=".xml",
        obrigatorio=True,
        amparo_legal="LC 123/2006 Art. 13 §1º V",
        nivel="b2b",
        automacao_disponivel="Fase 2A (Sieg API)",
    )


def _card_nfce(periodo: PeriodoBase) -> DocumentoRequerido:
    return DocumentoRequerido(
        id="nfce",
        label="XML NFCe modelo 65",
        descricao="Notas fiscais de consumidor final — receita real B2C.",
        periodo_label=_periodo_mensal_label(periodo),
        periodo_iso=_periodo_mensal_iso(periodo),
        extensao=".xml",
        obrigatorio=True,
        amparo_legal="LC 123/2006 Art. 3º §2º",
        nivel="b2c",
        automacao_disponivel="Fase 2A (Sieg API)",
    )


def _card_folha(periodo: PeriodoBase) -> DocumentoRequerido:
    return DocumentoRequerido(
        id="folha_csv",
        label="CSV Folha de Pagamento (12 meses)",
        descricao="Exportação da folha (Domínio ou similar) para cálculo do Fator R.",
        periodo_label=_periodo_mensal_label(periodo),
        periodo_iso=_periodo_mensal_iso(periodo),
        extensao=".csv",
        obrigatorio=True,
        amparo_legal="LC 123/2006 Art. 18 §24",
        nivel="base",
        automacao_disponivel="Fase 2C (file watcher Domínio)",
    )


def _card_sped_ecd(periodo: PeriodoBase) -> DocumentoRequerido:
    return DocumentoRequerido(
        id="sped_ecd",
        label="SPED ECD — Escrituração Contábil Digital",
        descricao="Arquivo TXT do SPED ECD do exercício fechado.",
        periodo_label=_exercicio_label(periodo),
        periodo_iso=str(periodo.exercicio_sped),
        extensao=".txt",
        obrigatorio=False,
        amparo_legal="IN RFB 2.003/2021",
        nivel="sped",
        automacao_disponivel="Fase 2C (file watcher Domínio)",
    )


def _card_sped_efd_contrib(periodo: PeriodoBase) -> DocumentoRequerido:
    return DocumentoRequerido(
        id="sped_efd_contrib",
        label="SPED EFD-Contribuições",
        descricao="Arquivo TXT do SPED EFD-Contribuições (PIS/COFINS) do exercício fechado.",
        periodo_label=_exercicio_label(periodo),
        periodo_iso=str(periodo.exercicio_sped),
        extensao=".txt",
        obrigatorio=False,
        amparo_legal="IN RFB 1.252/2012",
        nivel="sped",
        automacao_disponivel="Fase 2C (file watcher Domínio)",
    )


# ─── Função pública ───────────────────────────────────────────────────────


def montar_cards(
    perfil: str,
    regime: str,
    periodo: PeriodoBase,
) -> list[DocumentoRequerido]:
    """
    Monta a lista de cards para (perfil, regime, periodo).

    Regras:
        - PGDAS-D + DAS são base para Simples Nacional
        - B2B_CONTRIBUINTE / MISTO → exige NFe saída + Folha (Fator R)
        - B2C_CONSUMIDOR_FINAL / MISTO → exige NFCe
        - Simples → SPED ECD e EFD-Contrib são recomendados (não bloqueantes)
        - MEI → apenas DAS-SIMEI (sem folha, sem fator R, sem SPED)
        - PRESUMIDO / REAL → obriga SPED ECD + EFD-Contrib

    Raises:
        ValueError: perfil ou regime inválido.
    """
    if perfil not in PERFIS_VALIDOS:
        raise ValueError(
            f"perfil inválido: {perfil!r}. Esperado um de {PERFIS_VALIDOS}"
        )
    if regime not in REGIMES_VALIDOS:
        raise ValueError(
            f"regime inválido: {regime!r}. Esperado um de {REGIMES_VALIDOS}"
        )

    cards: list[DocumentoRequerido] = []

    # ─── MEI: regra simplificada ────────────────────────────────────────
    if regime == "MEI":
        cards.append(
            DocumentoRequerido(
                id="das",
                label="DAS-SIMEI — Comprovante mensal",
                descricao="Guia mensal do MEI (valor fixo por categoria).",
                periodo_label=_das_label(periodo),
                periodo_iso=periodo.das_referencia,
                extensao=".pdf",
                obrigatorio=True,
                amparo_legal="LC 123/2006 Art. 18-A",
                nivel="base",
            )
        )
        return cards

    # ─── SIMPLES NACIONAL ───────────────────────────────────────────────
    if regime == "SIMPLES":
        cards.append(_card_pgdas_d(periodo))
        cards.append(_card_das(periodo))

        if perfil in ("B2B_CONTRIBUINTE", "MISTO"):
            cards.append(_card_nfe_saida(periodo))
            cards.append(_card_folha(periodo))

        if perfil in ("B2C_CONSUMIDOR_FINAL", "MISTO"):
            cards.append(_card_nfce(periodo))

        # SPED recomendado (não bloqueante) para Simples
        cards.append(_card_sped_ecd(periodo))
        return cards

    # ─── PRESUMIDO / REAL ───────────────────────────────────────────────
    if regime in ("PRESUMIDO", "REAL"):
        if perfil in ("B2B_CONTRIBUINTE", "MISTO"):
            cards.append(_card_nfe_saida(periodo))
        if perfil in ("B2C_CONSUMIDOR_FINAL", "MISTO"):
            cards.append(_card_nfce(periodo))

        # SPED obrigatório fora do Simples
        ecd = _card_sped_ecd(periodo)
        efd = _card_sped_efd_contrib(periodo)
        cards.append(ecd.model_copy(update={"obrigatorio": True}))
        cards.append(efd.model_copy(update={"obrigatorio": True}))

        # Folha recomendada
        folha = _card_folha(periodo)
        cards.append(folha.model_copy(update={"obrigatorio": False}))
        return cards

    # Unreachable — regime já validado acima
    return cards  # pragma: no cover
