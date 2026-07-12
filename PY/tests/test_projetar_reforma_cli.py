# -*- coding: utf-8 -*-
"""
tests/test_projetar_reforma_cli.py — CLI do redesign.

Testa o argparse + IO + roteamento mock/real chamando main() direto
com argv passado (sem subprocess — mais rápido + sem flakiness).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Import lazy do CLI (depende de path setup acima)
from scripts.projetar_reforma_cli import _build_parser, _fmt_brl, main  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def pdf_temp(tmp_path):
    """Cria um arquivo PDF fake em tmp_path (bytes arbitrários)."""
    p = tmp_path / "competencia_06_2026.pdf"
    p.write_bytes(b"%PDF-fake-content-pra-testar-cli")
    return p


@pytest.fixture
def pdf2_temp(tmp_path):
    p = tmp_path / "competencia_07_2026.pdf"
    p.write_bytes(b"%PDF-segundo-arquivo")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# HELPER fmt_brl
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatadorBRL:
    @pytest.mark.parametrize("valor,esperado", [
        ("0", "R$ 0,00"),
        ("100.50", "R$ 100,50"),
        ("1234.56", "R$ 1.234,56"),
        ("1000000.00", "R$ 1.000.000,00"),
    ])
    def test_formato_brasileiro(self, valor, esperado):
        from decimal import Decimal
        assert _fmt_brl(Decimal(valor)) == esperado


# ─────────────────────────────────────────────────────────────────────────────
# ARGPARSE
# ─────────────────────────────────────────────────────────────────────────────

class TestParser:
    def test_argumentos_obrigatorios_exigidos(self):
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_ano_alvo_fora_do_intervalo_rejeita(self):
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "--pdf", "a.pdf",
                "--ano-alvo", "2025",
                "--regime-atual", "SIMPLES",
            ])

    def test_regime_atual_invalido_rejeita(self):
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "--pdf", "a.pdf",
                "--ano-alvo", "2026",
                "--regime-atual", "ARBITRADO",  # não existe
            ])

    def test_multiplos_pdfs_aceitos(self):
        parser = _build_parser()
        args = parser.parse_args([
            "--pdf", "a.pdf", "--pdf", "b.pdf",
            "--ano-alvo", "2026",
            "--regime-atual", "SIMPLES",
        ])
        assert len(args.pdf) == 2


# ─────────────────────────────────────────────────────────────────────────────
# EXECUÇÃO — main() com mock
# ─────────────────────────────────────────────────────────────────────────────

class TestExecucaoMock:
    def test_main_com_mock_retorna_zero(self, pdf_temp, capsys):
        ret = main([
            "--pdf", str(pdf_temp),
            "--ano-alvo", "2027",
            "--regime-atual", "SIMPLES",
            "--mock",
        ])
        assert ret == 0
        captured = capsys.readouterr()
        # Output humano deve conter as palavras-chave
        assert "PROJECAO" in captured.out
        assert "CBS" in captured.out
        assert "DELTA REFORMA" in captured.out

    def test_main_com_mock_json_output(self, pdf_temp, capsys):
        ret = main([
            "--pdf", str(pdf_temp),
            "--ano-alvo", "2026",
            "--regime-atual", "SIMPLES",
            "--mock",
            "--json",
        ])
        assert ret == 0
        captured = capsys.readouterr()
        # JSON deve parsear
        payload = json.loads(captured.out)
        assert payload["ano_alvo"] == 2026
        assert payload["cnpj"] == "12345678000195"
        assert "carga_atual" in payload
        assert "delta_absoluto" in payload
        assert "base_legal" in payload

    def test_main_com_multiplos_pdfs(self, pdf_temp, pdf2_temp, capsys):
        ret = main([
            "--pdf", str(pdf_temp),
            "--pdf", str(pdf2_temp),
            "--ano-alvo", "2030",
            "--regime-atual", "PRESUMIDO",
            "--mock",
        ])
        assert ret == 0


# ─────────────────────────────────────────────────────────────────────────────
# FALHA FECHADA
# ─────────────────────────────────────────────────────────────────────────────

class TestFalhaFechada:
    def test_pdf_inexistente_retorna_1(self, capsys, tmp_path):
        ret = main([
            "--pdf", str(tmp_path / "nao_existe.pdf"),
            "--ano-alvo", "2026",
            "--regime-atual", "SIMPLES",
            "--mock",
        ])
        assert ret == 1
        captured = capsys.readouterr()
        assert "ERRO" in captured.err
        assert "nao_existe.pdf" in captured.err

    def test_caminho_eh_diretorio_retorna_1(self, capsys, tmp_path):
        ret = main([
            "--pdf", str(tmp_path),  # diretório, não arquivo
            "--ano-alvo", "2026",
            "--regime-atual", "SIMPLES",
            "--mock",
        ])
        assert ret == 1


# ─────────────────────────────────────────────────────────────────────────────
# CONTEÚDO DO OUTPUT
# ─────────────────────────────────────────────────────────────────────────────

class TestOutputCompleto:
    def test_output_humano_mostra_aliquotas_corretas(self, pdf_temp, capsys):
        # 2026 = ano-teste: CBS 0,9% + IBS 0,1%
        main([
            "--pdf", str(pdf_temp),
            "--ano-alvo", "2026",
            "--regime-atual", "SIMPLES",
            "--mock",
        ])
        out = capsys.readouterr().out
        assert "Aliquota CBS" in out
        assert "Aliquota IBS" in out

    def test_output_json_tem_breakdown(self, pdf_temp, capsys):
        # Regime NORMAL (Presumido) → breakdown do caminho de extinção
        # gradual. SIMPLES tem branch próprio (guard LC 214 Art. 41) com
        # chaves das_* — coberto em test_projetor_reforma.TestGuardSimplesMei.
        main([
            "--pdf", str(pdf_temp),
            "--ano-alvo", "2027",
            "--regime-atual", "PRESUMIDO",
            "--mock",
            "--json",
        ])
        out = capsys.readouterr().out
        payload = json.loads(out)
        bk = payload["breakdown_projetado"]
        assert "cbs" in bk
        assert "ibs" in bk
        assert "irpj_inalterado" in bk

    def test_output_json_simples_mantem_das(self, pdf_temp, capsys):
        # Guard SIMPLES/MEI: DAS mantém total, sem CBS/IBS por fora.
        main([
            "--pdf", str(pdf_temp),
            "--ano-alvo", "2027",
            "--regime-atual", "SIMPLES",
            "--mock",
            "--json",
        ])
        payload = json.loads(capsys.readouterr().out)
        assert payload["carga_projetada"] == payload["carga_atual"]
        assert "das_pis" in payload["breakdown_projetado"]

    def test_comparar_output_humano(self, pdf_temp, capsys):
        ret = main([
            "--pdf", str(pdf_temp),
            "--ano-alvo", "2027",
            "--regime-atual", "SIMPLES",
            "--mock",
            "--comparar",
        ])
        assert ret == 0
        out = capsys.readouterr().out
        assert "COMPARADOR DE CENARIOS" in out
        assert "MANTER_SIMPLES" in out
        assert "MIGRAR_PRESUMIDO" in out
        assert "Alertas" in out

    def test_comparar_output_json_estruturado(self, pdf_temp, capsys):
        ret = main([
            "--pdf", str(pdf_temp),
            "--ano-alvo", "2027",
            "--regime-atual", "SIMPLES",
            "--mock",
            "--comparar",
            "--json",
        ])
        assert ret == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["resultado"] in (
            "VENCEDOR_DEFINIDO", "INCONCLUSIVO", "SEM_COMPARACAO",
        )
        ids = {c["id"] for c in payload["cenarios"]}
        assert "MANTER_SIMPLES" in ids
        assert "MIGRAR_REAL" in ids

    def test_lucro_real_mensal_invalido_erro_amigavel(self, pdf_temp, capsys):
        # Decimal inválido não pode virar traceback cru (achado BAIXO PMD)
        with pytest.raises(SystemExit) as exc:
            main([
                "--pdf", str(pdf_temp),
                "--ano-alvo", "2027",
                "--regime-atual", "SIMPLES",
                "--mock",
                "--comparar",
                "--lucro-real-mensal", "abc",
            ])
        assert exc.value.code == 2
        assert "valor monetario invalido" in capsys.readouterr().err

    def test_comparar_lucro_real_mensal_habilita_cenario_real(self, pdf_temp, capsys):
        main([
            "--pdf", str(pdf_temp),
            "--ano-alvo", "2027",
            "--regime-atual", "SIMPLES",
            "--mock",
            "--comparar",
            "--json",
            "--lucro-real-mensal", "20000.00",
        ])
        payload = json.loads(capsys.readouterr().out)
        real = next(c for c in payload["cenarios"] if c["id"] == "MIGRAR_REAL")
        assert real["status"] == "AVALIADO"

    def test_output_humano_mostra_base_legal(self, pdf_temp, capsys):
        main([
            "--pdf", str(pdf_temp),
            "--ano-alvo", "2026",
            "--regime-atual", "SIMPLES",
            "--mock",
        ])
        out = capsys.readouterr().out
        assert "LC 214/2025" in out
        assert "EC 132/2023" in out
