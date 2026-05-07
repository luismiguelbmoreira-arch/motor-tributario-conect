# -*- coding: utf-8 -*-
"""
core.fontes — Fontes de dados que alimentam o motor.

Decisão arquitetônica (CLAUDE.md "🔌 DECISÃO ARQUITETÔNICA — DESACOPLAMENTO
DE FONTE DE DADOS", commit a556c6e):

Motor consome interface FonteCliente; fontes implementam.
- FontePDFManual (subfase 1) — Claude Vision + upload manual.
- FonteNibo (futuro, parqueado até contrato fechar).
- FonteSistemaProprio (futuro, sistema interno de notas).
- FonteECAC (futuro).

Esta subfase 0 entrega apenas a INTERFACE (Protocol) + exceções de domínio.
Implementações concretas vão pra subfases posteriores quando houver caller.
"""

from core.fontes.base import (
    DadosInsuficientesNaFonte,
    FonteCliente,
    FonteIndisponivel,
)

__all__ = [
    "DadosInsuficientesNaFonte",
    "FonteCliente",
    "FonteIndisponivel",
]
