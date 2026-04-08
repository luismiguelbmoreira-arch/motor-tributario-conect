# -*- coding: utf-8 -*-
"""
Testes do parser CSV Folha de Pagamento — PY/parsers/csv_folha.py
"""
import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parsers.csv_folha import (
    FolhaParsedData,
    FolhaParserError,
    parsear_csv_folha,
)


def _csv(*linhas: str, sep: str = ";") -> bytes:
    return "\n".join(linhas).encode("utf-8")


# ── CSV Domínio — formato típico ──────────────────────────────────────────────

CSV_DOMINIO_12M = _csv(
    "Competência;CNPJ;Funcionário;Total Bruto;INSS Patronal",
    "01/2026;12.345.678/0001-90;JOÃO SILVA;5000.00;450.00",
    "02/2026;12.345.678/0001-90;JOÃO SILVA;5000.00;450.00",
    "03/2026;12.345.678/0001-90;JOÃO SILVA;5000.00;450.00",
    "04/2026;12.345.678/0001-90;JOÃO SILVA;5000.00;450.00",
    "05/2026;12.345.678/0001-90;JOÃO SILVA;5000.00;450.00",
    "06/2026;12.345.678/0001-90;JOÃO SILVA;5000.00;450.00",
    "07/2026;12.345.678/0001-90;JOÃO SILVA;5000.00;450.00",
    "08/2026;12.345.678/0001-90;JOÃO SILVA;5000.00;450.00",
    "09/2026;12.345.678/0001-90;JOÃO SILVA;5000.00;450.00",
    "10/2026;12.345.678/0001-90;JOÃO SILVA;5000.00;450.00",
    "11/2026;12.345.678/0001-90;JOÃO SILVA;5000.00;450.00",
    "12/2026;12.345.678/0001-90;JOÃO SILVA;5000.00;450.00",
)

CSV_1_MES = _csv(
    "Competência;Total Bruto;FGTS",
    "01/2026;41750.00;3340.00",
)

CSV_MOREIRA_6M = _csv(
    "Competência;Total Bruto;INSS Patronal",
    "07/2025;41750.00;3340.00",
    "08/2025;41750.00;3340.00",
    "09/2025;41750.00;3340.00",
    "10/2025;41750.00;3340.00",
    "11/2025;41750.00;3340.00",
    "12/2025;41750.00;3340.00",
)


# ── Testes básicos ────────────────────────────────────────────────────────────

class TestParsearCsvFolha:
    def test_retorna_folha_parsed_data(self):
        resultado = parsear_csv_folha(CSV_DOMINIO_12M)
        assert isinstance(resultado, FolhaParsedData)

    def test_12_meses_encontrados(self):
        resultado = parsear_csv_folha(CSV_DOMINIO_12M)
        assert resultado.meses_encontrados == 12

    def test_folha_12m_calculada(self):
        # 12 meses × (5000 + 450) = 65400
        resultado = parsear_csv_folha(CSV_DOMINIO_12M)
        assert resultado.folha_12m == Decimal("65400.00")

    def test_sem_fonte_estimativa_12_meses(self):
        resultado = parsear_csv_folha(CSV_DOMINIO_12M)
        assert resultado.fonte_estimativa is False

    def test_cnpj_extraido(self):
        resultado = parsear_csv_folha(CSV_DOMINIO_12M)
        assert resultado.cnpj_empresa == "12345678000190"

    def test_competencias_processadas_ordenadas(self):
        resultado = parsear_csv_folha(CSV_DOMINIO_12M)
        assert resultado.competencias_processadas[0] == "2026-01"
        assert resultado.competencias_processadas[-1] == "2026-12"


class TestEstimativa1Mes:
    def test_fonte_estimativa_true(self):
        resultado = parsear_csv_folha(CSV_1_MES)
        assert resultado.fonte_estimativa is True

    def test_extrapola_12x(self):
        # (41750 + 3340) × 12 = 541080
        resultado = parsear_csv_folha(CSV_1_MES)
        assert resultado.folha_12m == Decimal("541080.00")

    def test_aviso_estimativa_presente(self):
        resultado = parsear_csv_folha(CSV_1_MES)
        assert any("ESTIMATIVA" in a for a in resultado.avisos)

    def test_1_mes_encontrado(self):
        resultado = parsear_csv_folha(CSV_1_MES)
        assert resultado.meses_encontrados == 1


class TestEstimativa6Meses:
    def test_extrapola_por_media(self):
        # (41750 + 3340) × 6 meses × 2 (extrapola para 12) = 541080
        resultado = parsear_csv_folha(CSV_MOREIRA_6M)
        assert resultado.folha_12m == Decimal("541080.00")

    def test_fonte_estimativa_true(self):
        resultado = parsear_csv_folha(CSV_MOREIRA_6M)
        assert resultado.fonte_estimativa is True

    def test_6_meses_encontrados(self):
        resultado = parsear_csv_folha(CSV_MOREIRA_6M)
        assert resultado.meses_encontrados == 6


class TestFatorRMoreira:
    """
    Caso Moreira: RBT12 = R$ 1.793.000 / folha_12m = R$ 501.000
    Fator R = 501.000 / 1.793.000 = 0.2795... → Anexo V (< 28%)
    LC 123/2006 Art. 18 §24
    """

    def test_folha_moreira_501k(self):
        # 12 meses × R$ 41.750/mês = R$ 501.000
        csv = _csv(
            "Competência;Total Bruto",
            *[f"{str(i).zfill(2)}/2025;41750.00" for i in range(1, 13)]
        )
        resultado = parsear_csv_folha(csv)
        assert resultado.folha_12m == Decimal("501000.00")
        # Fator R = 501000 / 1793000 ≈ 0.2795 < 0.28 → Anexo V
        fator_r = resultado.folha_12m / Decimal("1793000.00")
        assert fator_r < Decimal("0.28")


class TestCodificacao:
    def test_aceita_latin1(self):
        csv_latin1 = "Competência;Total Bruto\n01/2026;5000.00\n".encode("latin-1")
        resultado = parsear_csv_folha(csv_latin1)
        assert resultado.folha_12m > 0

    def test_aceita_utf8_bom(self):
        csv_bom = "\ufeffCompetência;Total Bruto\n01/2026;5000.00\n".encode("utf-8-sig")
        resultado = parsear_csv_folha(csv_bom)
        assert resultado.folha_12m > 0

    def test_separador_virgula(self):
        csv_virgula = b"Competencia,Total Bruto\n01/2026,5000.00\n"
        resultado = parsear_csv_folha(csv_virgula)
        assert resultado.folha_12m > 0


class TestErros:
    def test_sem_coluna_reconhecivel_levanta_erro(self):
        csv = b"Codigo;Descricao;Valor\n001;Item A;100.00\n"
        with pytest.raises(FolhaParserError, match="coluna de total"):
            parsear_csv_folha(csv)

    def test_csv_vazio_levanta_erro(self):
        with pytest.raises(FolhaParserError):
            parsear_csv_folha(b"")
