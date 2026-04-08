# -*- coding: utf-8 -*-
"""
test_verify_trilha.py — CLI de verificação HMAC da trilha de auditoria.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Garante master key para HMAC antes de importar hmac_trilha
os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "a" * 64)

from observability import hmac_trilha  # noqa: E402
from tools.verify_trilha import main  # noqa: E402


def _trilha_fixture() -> list[dict]:
    return [
        {
            "tipo": "CALCULO",
            "id": "FASE2_RBT12",
            "titulo": "Receita Bruta 12 meses",
            "amparo_legal": "LC 123/2006 Art. 12",
            "memoria": {"valor": "1793000.00"},
        },
        {
            "tipo": "CALCULO",
            "id": "FASE2_ALIQUOTA",
            "titulo": "Alíquota Efetiva",
            "amparo_legal": "LC 123/2006 Art. 18",
            "memoria": {"aliquota": "6.54"},
        },
    ]


def test_trilha_integra_exit_0(tmp_path: Path, capsys):
    trilha = hmac_trilha.assinar_trilha(_trilha_fixture())
    path = tmp_path / "trilha.json"
    path.write_text(json.dumps(trilha), encoding="utf-8")

    rc = main(["--trilha", str(path)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "ÍNTEGRA" in out
    assert "Adulterados:     0" in out


def test_trilha_adulterada_exit_1(tmp_path: Path, capsys):
    trilha = hmac_trilha.assinar_trilha(_trilha_fixture())
    # Mutação maliciosa no passo 1
    trilha[1]["memoria"]["aliquota"] = "3.00"

    path = tmp_path / "trilha.json"
    path.write_text(json.dumps(trilha), encoding="utf-8")

    rc = main(["--trilha", str(path)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "ADULTERADA" in out
    assert "[1]" in out
    assert "FASE2_ALIQUOTA" in out


def test_diagnostico_com_trilha_embutida(tmp_path: Path, capsys):
    trilha = hmac_trilha.assinar_trilha(_trilha_fixture())
    diagnostico = {
        "empresa": {"razao_social": "MOREIRA LTDA"},
        "trilha_auditoria": trilha,
    }
    path = tmp_path / "diagnostico.json"
    path.write_text(json.dumps(diagnostico), encoding="utf-8")

    rc = main(["--diagnostico", str(path)])
    assert rc == 0
    assert "ÍNTEGRA" in capsys.readouterr().out


def test_arquivo_inexistente_exit_2(tmp_path: Path, capsys):
    rc = main(["--trilha", str(tmp_path / "nao_existe.json")])
    assert rc == 2
    assert "ERRO" in capsys.readouterr().err


def test_json_malformado_exit_2(tmp_path: Path, capsys):
    path = tmp_path / "lixo.json"
    path.write_text("{not json", encoding="utf-8")

    rc = main(["--trilha", str(path)])
    assert rc == 2
    assert "ERRO" in capsys.readouterr().err


def test_trilha_dict_wrapper_extrai_campo(tmp_path: Path):
    """Aceita {trilha_auditoria: [...]} como wrapper."""
    trilha = hmac_trilha.assinar_trilha(_trilha_fixture())
    path = tmp_path / "wrap.json"
    path.write_text(json.dumps({"trilha_auditoria": trilha}), encoding="utf-8")

    rc = main(["--trilha", str(path), "--quiet"])
    assert rc == 0


def test_quiet_sem_output(tmp_path: Path, capsys):
    trilha = hmac_trilha.assinar_trilha(_trilha_fixture())
    path = tmp_path / "trilha.json"
    path.write_text(json.dumps(trilha), encoding="utf-8")

    rc = main(["--trilha", str(path), "--quiet"])
    captured = capsys.readouterr()

    assert rc == 0
    assert captured.out == ""
    assert captured.err == ""


def test_sem_argumentos_obrigatorios():
    with pytest.raises(SystemExit):
        main([])
