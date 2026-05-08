# -*- coding: utf-8 -*-
"""
core/cooperativa_ramos.py — Fonte única de RAMOS COOPERATIVOS

WS6 etapa 5b: PMD pediu unificar `RamosCooperativos5a/5b` (frozenset em
core.validador_cooperativa) com o `Literal` declarado no schema
EmpresaFornecedora. Esta é a fonte única — schema, validador, overlay e
orquestrador importam daqui.

ESCOPO:
  - 5a: CONSUMO, TRABALHO, PRODUCAO, AGROPECUARIA, TRANSPORTE
  - 5b: CREDITO, SAUDE

BASE LEGAL (validada por Escrivão 2026-05-08):
  Lei 5.764/71 Art. 10 caput + § 1º — classificação por objeto/natureza,
  modalidades caracterizadas pelo órgão controlador (OCB/CGSN). Os ramos
  NÃO são enumeração legal taxativa — são modalidades CONSAGRADAS pela
  OCB. Sempre citar como classificação administrativa, nunca como
  enumeração legal (anti-alucinação MAX_07).
"""
from __future__ import annotations

from typing import Literal

# ─────────────────────────────────────────────────────────────────────────────
# LITERAL CANÔNICO — usado em schemas/motor.py::EmpresaFornecedora
# ─────────────────────────────────────────────────────────────────────────────

RamoCooperativo5a = Literal[
    "CONSUMO",
    "TRABALHO",
    "PRODUCAO",
    "AGROPECUARIA",
    "TRANSPORTE",
]

RamoCooperativo5b = Literal[
    "CREDITO",
    "SAUDE",
]

RamoCooperativo = Literal[
    "CONSUMO",
    "TRABALHO",
    "PRODUCAO",
    "AGROPECUARIA",
    "TRANSPORTE",
    "CREDITO",
    "SAUDE",
]


# ─────────────────────────────────────────────────────────────────────────────
# FROZEN SETS — usados em validador/overlay para checagem rápida
# Sincronizados manualmente com os Literals acima. Teste regressivo
# em test_cooperativa_ramos.py garante que não saem de sincronia.
# ─────────────────────────────────────────────────────────────────────────────

RAMOS_5A: frozenset[str] = frozenset({
    "CONSUMO",
    "TRABALHO",
    "PRODUCAO",
    "AGROPECUARIA",
    "TRANSPORTE",
})

RAMOS_5B: frozenset[str] = frozenset({
    "CREDITO",
    "SAUDE",
})

RAMOS_TODOS: frozenset[str] = RAMOS_5A | RAMOS_5B
