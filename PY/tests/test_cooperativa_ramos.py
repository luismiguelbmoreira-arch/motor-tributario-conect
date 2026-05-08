# -*- coding: utf-8 -*-
"""
tests/test_cooperativa_ramos.py — WS6 etapa 5b
Sincronia entre Literal (schema) e frozenset (validador) na fonte única
core/cooperativa_ramos.py.

OBJETIVO: garantir que nenhum drift entre as duas representações passe
batido. Se um ramo entrar no Literal mas ficar fora do frozenset (ou
vice-versa), o teste vermelho aponta antes do bug fiscal aparecer em
produção.
"""
from __future__ import annotations

import os
import sys
from typing import get_args

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.cooperativa_ramos import (  # noqa: E402
    RAMOS_5A,
    RAMOS_5B,
    RAMOS_TODOS,
    RamoCooperativo,
    RamoCooperativo5a,
    RamoCooperativo5b,
)


class TestCooperativaRamosSincronia:
    """Literal e frozenset não podem sair de sincronia."""

    def test_literal_5a_bate_com_frozenset_5a(self):
        assert set(get_args(RamoCooperativo5a)) == set(RAMOS_5A)

    def test_literal_5b_bate_com_frozenset_5b(self):
        assert set(get_args(RamoCooperativo5b)) == set(RAMOS_5B)

    def test_literal_total_bate_com_uniao_dos_frozensets(self):
        assert set(get_args(RamoCooperativo)) == set(RAMOS_TODOS)

    def test_5a_e_5b_disjuntos(self):
        # Nenhum ramo está em 5a E em 5b ao mesmo tempo
        assert RAMOS_5A.isdisjoint(RAMOS_5B)

    def test_5a_contem_5_ramos(self):
        assert len(RAMOS_5A) == 5

    def test_5b_contem_2_ramos(self):
        assert len(RAMOS_5B) == 2

    def test_total_contem_7_ramos(self):
        assert len(RAMOS_TODOS) == 7
