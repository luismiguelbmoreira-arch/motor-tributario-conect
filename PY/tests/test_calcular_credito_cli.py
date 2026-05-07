# -*- coding: utf-8 -*-
"""
test_calcular_credito_cli — Cobertura do CLI consumidor do mapa-mestre.

`tools.calcular_credito.main()` chamada direto com argv. Exit codes:
    0 — cálculo OK
    1 — erro de validação (alíquota negativa, data malformada)
    2 — erro de I/O / JSON malformado / estrutura inválida
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.calcular_credito import main  # noqa: E402

# Fixture canônica versionada no repo — executa o mesmo cenário do
# test_caso_real_lanchonete em test_calculo_credito_cbs_ibs.py.
_FIXTURE_LANCHONETE = (
    Path(__file__).resolve().parent.parent.parent
    / "data" / "exemplos" / "despesas_lanchonete_2027.json"
)


def _escrever_json(tmp_path: Path, payload, nome: str = "in.json") -> Path:
    p = tmp_path / nome
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


# ── Caminho feliz ────────────────────────────────────────────────────────────

def test_fixture_lanchonete_executa_e_imprime_total(capsys):
    """Roda a fixture canônica e confirma total esperado no stdout."""
    assert _FIXTURE_LANCHONETE.exists(), (
        f"Fixture {_FIXTURE_LANCHONETE} ausente — repo desincronizado."
    )
    rc = main([
        "--despesas", str(_FIXTURE_LANCHONETE),
        "--data", "2027-03-15",
        "--aliquota", "0.265",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    # Crédito esperado bate com test_caso_real_lanchonete
    assert "2843.45" in out
    # 3 ignoradas (SALARIOS, INSS_PATRONAL_FGTS = NAO_TRIBUTADO; CARTORIO = UNKNOWN)
    assert "Ignoradas:        3" in out
    assert "NAO_TRIBUTADO" in out
    assert "UNKNOWN" in out


def test_lista_direta_no_topo_aceita(tmp_path, capsys):
    """JSON pode ser lista direta (sem envelope `despesas`)."""
    arq = _escrever_json(tmp_path, [
        {"categoria": "ENERGIA_ELETRICA", "valor": "1000.00"},
    ])
    rc = main([
        "--despesas", str(arq),
        "--data", "2027-01-01",
        "--aliquota", "0.265",
    ])
    assert rc == 0
    assert "265.00" in capsys.readouterr().out


def test_quiet_suprime_stdout(tmp_path, capsys):
    """--quiet zera stdout, mantém exit 0."""
    arq = _escrever_json(tmp_path, [
        {"categoria": "ENERGIA_ELETRICA", "valor": "100"},
    ])
    rc = main([
        "--despesas", str(arq),
        "--data", "2026-06-01",
        "--aliquota", "0.265",
        "--quiet",
    ])
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_lista_vazia_retorna_zero(tmp_path, capsys):
    """Sem despesas: cálculo válido com total 0.00 (exit 0)."""
    arq = _escrever_json(tmp_path, {"despesas": []})
    rc = main([
        "--despesas", str(arq),
        "--data", "2027-01-01",
        "--aliquota", "0.265",
    ])
    assert rc == 0
    assert "0.00" in capsys.readouterr().out


# ── Erros de validação (exit 1) ──────────────────────────────────────────────

def test_aliquota_negativa_exit_1(tmp_path, capsys):
    arq = _escrever_json(tmp_path, [
        {"categoria": "ENERGIA_ELETRICA", "valor": "100"},
    ])
    rc = main([
        "--despesas", str(arq),
        "--data", "2027-01-01",
        "--aliquota", "-0.1",
    ])
    assert rc == 1
    assert "ERRO de validação" in capsys.readouterr().err


def test_data_malformada_exit_1(tmp_path, capsys):
    arq = _escrever_json(tmp_path, [])
    rc = main([
        "--despesas", str(arq),
        "--data", "31/12/2027",  # formato BR — não ISO
        "--aliquota", "0.265",
    ])
    assert rc == 1
    err = capsys.readouterr().err
    assert "ERRO" in err and "data" in err.lower()


def test_aliquota_nao_decimal_exit_1(tmp_path, capsys):
    arq = _escrever_json(tmp_path, [])
    rc = main([
        "--despesas", str(arq),
        "--data", "2027-01-01",
        "--aliquota", "vinte_e_seis",
    ])
    assert rc == 1
    assert "ERRO" in capsys.readouterr().err


# ── Erros de I/O / formato (exit 2) ──────────────────────────────────────────

def test_arquivo_inexistente_exit_2(tmp_path, capsys):
    rc = main([
        "--despesas", str(tmp_path / "nao_existe.json"),
        "--data", "2027-01-01",
        "--aliquota", "0.265",
    ])
    assert rc == 2
    assert "ERRO" in capsys.readouterr().err


def test_json_malformado_exit_2(tmp_path, capsys):
    arq = tmp_path / "broken.json"
    arq.write_text("{ isso nao é json valido", encoding="utf-8")
    rc = main([
        "--despesas", str(arq),
        "--data", "2027-01-01",
        "--aliquota", "0.265",
    ])
    assert rc == 2


def test_dict_sem_campo_despesas_exit_2(tmp_path, capsys):
    """Dict no topo precisa ter 'despesas' — caso contrário, formato inválido."""
    arq = _escrever_json(tmp_path, {"outras_coisas": []})
    rc = main([
        "--despesas", str(arq),
        "--data", "2027-01-01",
        "--aliquota", "0.265",
    ])
    assert rc == 2
    assert "despesas" in capsys.readouterr().err.lower()


def test_item_sem_categoria_exit_2(tmp_path, capsys):
    arq = _escrever_json(tmp_path, [{"valor": "100"}])
    rc = main([
        "--despesas", str(arq),
        "--data", "2027-01-01",
        "--aliquota", "0.265",
    ])
    assert rc == 2


def test_item_sem_valor_exit_2(tmp_path, capsys):
    arq = _escrever_json(tmp_path, [{"categoria": "ENERGIA_ELETRICA"}])
    rc = main([
        "--despesas", str(arq),
        "--data", "2027-01-01",
        "--aliquota", "0.265",
    ])
    assert rc == 2


def test_valor_nao_numerico_exit_2(tmp_path, capsys):
    arq = _escrever_json(tmp_path, [
        {"categoria": "ENERGIA_ELETRICA", "valor": "vinte_reais"},
    ])
    rc = main([
        "--despesas", str(arq),
        "--data", "2027-01-01",
        "--aliquota", "0.265",
    ])
    assert rc == 2


# ── Erros propagados do caller (estrutura OK, mas regra falha) ───────────────

def test_valor_negativo_exit_1(tmp_path, capsys):
    """Valor negativo é detectado pelo caller (ValueError) → exit 1."""
    arq = _escrever_json(tmp_path, [
        {"categoria": "ENERGIA_ELETRICA", "valor": "-100"},
    ])
    rc = main([
        "--despesas", str(arq),
        "--data", "2027-01-01",
        "--aliquota", "0.265",
    ])
    assert rc == 1
    assert "Valor negativo" in capsys.readouterr().err


def test_data_fora_da_janela_exit_1(tmp_path, capsys):
    """Mapa cobre 2026-2027. Ano fora levanta ValueError do lookup → exit 1."""
    arq = _escrever_json(tmp_path, [
        {"categoria": "ENERGIA_ELETRICA", "valor": "100"},
    ])
    rc = main([
        "--despesas", str(arq),
        "--data", "2099-01-01",
        "--aliquota", "0.265",
    ])
    assert rc == 1


# ── Smoke test do parser CLI nativo ──────────────────────────────────────────

def test_arg_obrigatorio_ausente_levanta_systemexit(tmp_path):
    """argparse aborta com SystemExit(2) se faltar --aliquota."""
    arq = _escrever_json(tmp_path, [])
    with pytest.raises(SystemExit):
        main([
            "--despesas", str(arq),
            "--data", "2027-01-01",
        ])
