# -*- coding: utf-8 -*-
"""
test_akita_end_to_end.py — Pipeline Akita Rails + SPED Dominio Contabil.

Simula o fluxo do endpoint /analise/pdf sem subir FastAPI:
    1. Parsea SPED ECD + SPED EFD-Contribuicoes (Dominio Contabil)
    2. Roda anomalias.detectar() com dados realistas
    3. Avalia semaforo_das para DAS calculado vs pago
    4. Assina trilha com hmac_trilha e verifica integridade
    5. Confirma que mutacao em qualquer passo invalida o HMAC
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Garante master key para HMAC (32 bytes hex)
os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "a" * 64)

from observability import anomalias, hmac_trilha, semaforo_das  # noqa: E402
from parsers.sped_ecd import parsear_sped_ecd  # noqa: E402
from parsers.sped_efd_contrib import parsear_sped_efd_contrib  # noqa: E402


CNPJ_MOREIRA = "54657895000160"


def _sped_ecd_minimo() -> bytes:
    linhas = [
        f"|0000|LECD|01012026|31012026|MOREIRA COMERCIO LTDA|{CNPJ_MOREIRA}|SP|12345678|3550308|||||",
        "|0001|0|",
        "|I050|01012026||A|1|1.1.01.001|1.1.01|Caixa|",
        "|I050|01012026||A|1|3.1.01.001|3.1.01|Receita de Vendas|",
        "|I200|1|15012026|5000,00|N|",
        "|I250|1.1.01.001||5000,00|D|0001||Venda|",
        "|I250|3.1.01.001||5000,00|C|0001||Venda|",
        "|9999|",
    ]
    return "\n".join(linhas).encode("latin-1")


def _sped_efd_contrib_minimo() -> bytes:
    pis = ["0"] * 7 + ["500,00", "0", "0", "500,00", "500,00"]
    cofins = ["0"] * 7 + ["2300,00", "0", "0", "2300,00", "2300,00"]
    linhas = [
        f"|0000|010|0|0||01012026|31012026|MOREIRA|{CNPJ_MOREIRA}|SP|3550308||02|0|",
        "|0110|1|3|1|1|",
        "|M200|" + "|".join(pis) + "|",
        "|M600|" + "|".join(cofins) + "|",
        "|9999|",
    ]
    return "\n".join(linhas).encode("latin-1")


def test_pipeline_completo_sem_anomalia():
    """Caso verde: SPED parseia, DAS bate, trilha integra."""
    ecd = parsear_sped_ecd(_sped_ecd_minimo())
    efd = parsear_sped_efd_contrib(_sped_efd_contrib_minimo())

    assert ecd.cnpj_empresa == CNPJ_MOREIRA
    assert ecd.total_debitos == ecd.total_creditos == Decimal("5000.00")
    assert efd.regime == "cumulativo"
    assert efd.pis_valor_devido == Decimal("500.00")
    assert efd.tributo_total == Decimal("2800.00")

    # Caso Moreira real: RBT12 1.793M / folha 501k (28%)
    rbt12 = Decimal("1793000")
    folha = Decimal("501000")
    alertas = anomalias.detectar(
        rbt12=rbt12,
        rpa_mensal=rbt12 / Decimal("12"),
        confianca_extracao=0.92,
        folha_12m=folha,
        pis_sped=efd.pis_valor_devido,
        pis_nfe=Decimal("495.00"),  # 1% delta
        cofins_sped=efd.cofins_valor_devido,
        cofins_nfe=Decimal("2290.00"),  # <1% delta
    )
    assert alertas == [], f"Esperava sem alertas, veio: {alertas}"

    semaforo = semaforo_das.avaliar(Decimal("1500.00"), Decimal("1500.50"))
    assert semaforo["semaforo"] == "verde"

    trilha = [
        {
            "tipo": "CALCULO",
            "id": "FASE2_RBT12",
            "titulo": "Receita Bruta 12 meses",
            "amparo_legal": "LC 123/2006 Art. 12",
            "memoria": {"valor": str(rbt12)},
        },
        semaforo,
    ]
    trilha_assinada = hmac_trilha.assinar_trilha(trilha)
    indices_invalidos = hmac_trilha.verificar_trilha(trilha_assinada)
    assert indices_invalidos == []


def test_pipeline_detecta_anomalia_ocr_baixa():
    """Confianca Claude Vision baixa dispara alerta."""
    alertas = anomalias.detectar(confianca_extracao=0.60)
    assert len(alertas) == 1
    assert "OCR" in alertas[0]["tipo"] or "OCR" in alertas[0].get("id", "")


def test_pipeline_detecta_rbt12_desproporcional():
    """RBT12 25x maior que RPA — alerta."""
    alertas = anomalias.detectar(
        rbt12=Decimal("2500000"),
        rpa_mensal=Decimal("100000"),  # 25x ratio
    )
    assert any("RBT12" in (a.get("tipo") or "") or "RBT12" in (a.get("id") or "") for a in alertas)


def test_pipeline_semaforo_vermelho_dispara_em_delta_maior_5pct():
    """DAS calculado muito diferente do pago — vermelho."""
    sem = semaforo_das.avaliar(Decimal("1000.00"), Decimal("1500.00"))
    assert sem["semaforo"] == "vermelho"


def test_pipeline_hmac_detecta_mutacao_em_passo():
    """Alterar memoria de um passo deve invalidar o HMAC."""
    trilha = [
        {
            "tipo": "CALCULO",
            "id": "FASE2_ALIQUOTA",
            "titulo": "Aliquota Efetiva",
            "amparo_legal": "LC 123/2006 Art. 18",
            "memoria": {"aliquota": "6.54"},
        }
    ]
    assinada = hmac_trilha.assinar_trilha(trilha)
    assert hmac_trilha.verificar_trilha(assinada) == []

    # Mutacao maliciosa no valor
    assinada[0]["memoria"]["aliquota"] = "3.00"
    invalidos = hmac_trilha.verificar_trilha(assinada)
    assert invalidos == [0]


def test_pipeline_crosscheck_pis_sped_vs_nfe_dentro_tolerancia():
    """PIS SPED vs NFe com delta < 5% nao dispara alerta."""
    alertas = anomalias.detectar(
        pis_sped=Decimal("500"),
        pis_nfe=Decimal("510"),  # 2% delta
    )
    assert not any("PIS" in (a.get("tipo") or "") for a in alertas)


def test_pipeline_crosscheck_pis_sped_vs_nfe_acima_tolerancia():
    """PIS SPED vs NFe com delta > 5% dispara."""
    alertas = anomalias.detectar(
        pis_sped=Decimal("500"),
        pis_nfe=Decimal("600"),  # 20% delta
    )
    assert any("PIS" in (a.get("tipo") or "") or "PIS" in (a.get("id") or "") for a in alertas)
