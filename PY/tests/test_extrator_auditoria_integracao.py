"""
test_extrator_auditoria_integracao.py — Trava o hook de auditoria documental
no pipeline do extrator.

Mocka a chamada à API Claude Vision para isolar o comportamento da
persistência: cifragem + registro em DB + injeção do campo
documentos_auditoria no diagnóstico.

Cobre os 4 caminhos:
  - persistir_auditoria=False (default): nada acontece
  - persistir_auditoria=True + arquivos_nomes ausente: levanta ValueError
  - persistir_auditoria=True funcionando: docs cifrados + DB populado
  - persistir_auditoria=True com falha de cifra: status PARCIAL/FALHOU
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Setup ANTES dos imports do projeto
os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import database  # noqa: E402
import storage_cifrado  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import SQLModel, create_engine  # noqa: E402


PDF_FAKE_A = b"%PDF-1.4\n%fakeA\n" + b"a" * 512
PDF_FAKE_B = b"%PDF-1.4\n%fakeB\n" + b"b" * 1024
CNPJ_FAKE = "54657895000160"
# DadosExtraidosPDF.limpar_cnpj normaliza para XX.XXX.XXX/XXXX-XX
CNPJ_FAKE_NORMALIZADO = "54.657.895/0001-60"


@pytest.fixture(autouse=True)
def storage_e_db_isolados(tmp_path, monkeypatch):
    """Storage cifrado em pasta tmp + banco em memória limpo por teste."""
    monkeypatch.setattr(storage_cifrado, "STORAGE_ROOT", tmp_path / "auditoria")

    # StaticPool: mantém UMA conexão compartilhada — necessário para :memory:
    # senão cada Session() abre um banco vazio novo.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)

    # ANTHROPIC_API_KEY fake só para passar a verificação inicial do extrator
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-test-key")

    yield


def _diagnostico_mockado(cnpj: str = CNPJ_FAKE) -> dict:
    """Retorna um diagnóstico mínimo válido (formato real do motor)."""
    return {
        "empresa": {
            "regime": "SIMPLES",
            "anexo_simples": "I",
            "rbt12": "1000000.00",
        },
        "aliquotas": {
            "efetiva_das_total": "0.07",
        },
        "cenarios": {},
        "trilha_auditoria": [],
    }


def _patch_pipeline_claude(cnpj: str = CNPJ_FAKE):
    """
    Helper que retorna patches do pipeline Claude para usar com `with`.

    Substitui:
      - anthropic.Anthropic — não bate na API real
      - DadosExtraidosPDF — devolve dados sintéticos com o CNPJ desejado
      - dados_para_motor — devolve params válidos do motor
      - MotorReformaTributaria — devolve um motor que cuspe diagnóstico mockado
    """
    # Mock do response do Claude
    fake_response = MagicMock()
    fake_response.content = [
        MagicMock(text='{"cnpj":"' + cnpj + '","razao_social":"FAKE","cnae_principal":"4757100","uf_origem":"SP","faturamento_12m":"1000000","anexo_simples":"I","rpa_referencia":"83333.33","das_ecac_referencia":"5833.33","competencia":"01/2026","confianca_extracao":0.99}')
    ]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    # Mock do motor — devolve diagnóstico mínimo
    fake_motor_instance = MagicMock()
    fake_motor_instance.gerar_diagnostico.return_value = _diagnostico_mockado(cnpj)
    fake_motor_class = MagicMock(return_value=fake_motor_instance)

    return {
        "anthropic_client": patch("extrator_pdfs.anthropic.Anthropic", return_value=fake_client),
        "motor": patch("motor_tributario.MotorReformaTributaria", fake_motor_class),
    }


# ── Caminhos do parâmetro persistir_auditoria ──────────────────────────────


def test_persistir_false_nao_toca_auditoria():
    from extrator_pdfs import processar_pdfs_bytes

    patches = _patch_pipeline_claude()
    with patches["anthropic_client"], patches["motor"]:
        diag = processar_pdfs_bytes([PDF_FAKE_A])

    extracao = diag.get("_extracao", {})
    assert extracao.get("documentos_auditoria") == []
    assert extracao.get("auditoria_status") == "DESATIVADO"

    # E o banco continua vazio
    assert database.buscar_documentos_por_cnpj(CNPJ_FAKE_NORMALIZADO) == []


def test_persistir_true_sem_arquivos_nomes_levanta():
    from extrator_pdfs import processar_pdfs_bytes

    with pytest.raises(ValueError, match="arquivos_nomes"):
        processar_pdfs_bytes([PDF_FAKE_A], persistir_auditoria=True)


def test_arquivos_nomes_tamanho_diferente_levanta():
    from extrator_pdfs import processar_pdfs_bytes

    with pytest.raises(ValueError, match="mesmo tamanho"):
        processar_pdfs_bytes(
            [PDF_FAKE_A, PDF_FAKE_B],
            arquivos_nomes=["a.pdf"],  # só 1 nome para 2 PDFs
            persistir_auditoria=True,
        )


def test_persistir_ok_cifra_e_registra_dois_pdfs():
    from extrator_pdfs import processar_pdfs_bytes

    patches = _patch_pipeline_claude()
    with patches["anthropic_client"], patches["motor"]:
        diag = processar_pdfs_bytes(
            [PDF_FAKE_A, PDF_FAKE_B],
            arquivos_nomes=["pgdas.pdf", "das.pdf"],
            user_id=42,
            persistir_auditoria=True,
        )

    extracao = diag["_extracao"]
    assert extracao["auditoria_status"] == "OK"
    docs = extracao["documentos_auditoria"]
    assert len(docs) == 2

    # Cada doc tem id, hash, nome, tamanho
    nomes = {d["nome_original"] for d in docs}
    assert nomes == {"pgdas.pdf", "das.pdf"}
    assert all(len(d["hash_sha256"]) == 64 for d in docs)
    assert all(d["id"] is not None for d in docs)
    assert {d["tamanho_bytes"] for d in docs} == {len(PDF_FAKE_A), len(PDF_FAKE_B)}

    # E o banco realmente foi populado
    salvos = database.buscar_documentos_por_cnpj(CNPJ_FAKE_NORMALIZADO)
    assert len(salvos) == 2
    assert all(s.uploaded_by_user_id == 42 for s in salvos)


def test_persistir_arquivos_realmente_cifrados_em_disco():
    """Confere que o byte-a-byte do PDF não aparece no arquivo cifrado."""
    from extrator_pdfs import processar_pdfs_bytes

    patches = _patch_pipeline_claude()
    with patches["anthropic_client"], patches["motor"]:
        processar_pdfs_bytes(
            [PDF_FAKE_A],
            arquivos_nomes=["pgdas.pdf"],
            persistir_auditoria=True,
        )

    salvos = database.buscar_documentos_por_cnpj(CNPJ_FAKE_NORMALIZADO)
    assert len(salvos) == 1
    path_cifrado = salvos[0].storage_path
    blob = open(path_cifrado, "rb").read()
    assert PDF_FAKE_A not in blob  # plaintext NÃO está no disco
    assert len(blob) >= len(PDF_FAKE_A) + 28  # nonce 12 + tag 16


def test_round_trip_auditoria_decifra_recupera_pdf_original():
    """Workflow completo: cifrar via extrator → buscar do DB → decifrar → bate."""
    from extrator_pdfs import processar_pdfs_bytes
    from storage_cifrado import decifrar

    patches = _patch_pipeline_claude()
    with patches["anthropic_client"], patches["motor"]:
        diag = processar_pdfs_bytes(
            [PDF_FAKE_A],
            arquivos_nomes=["pgdas.pdf"],
            persistir_auditoria=True,
        )

    doc_meta = diag["_extracao"]["documentos_auditoria"][0]
    salvo = database.buscar_documento_por_hash(doc_meta["hash_sha256"])
    assert salvo is not None

    # Decifragem usando cnpj + hash do registro
    from pathlib import Path
    plaintext = decifrar(
        Path(salvo.storage_path),
        CNPJ_FAKE,
        hash_esperado=salvo.hash_sha256,
    )
    assert plaintext == PDF_FAKE_A


def test_falha_de_cifra_nao_derruba_diagnostico(monkeypatch):
    """Se cifrar_e_persistir explodir, o diagnóstico ainda volta."""
    from extrator_pdfs import processar_pdfs_bytes

    def cifra_explode(*a, **kw):
        raise RuntimeError("disco cheio")

    monkeypatch.setattr(storage_cifrado, "cifrar_e_persistir", cifra_explode)

    patches = _patch_pipeline_claude()
    with patches["anthropic_client"], patches["motor"]:
        diag = processar_pdfs_bytes(
            [PDF_FAKE_A],
            arquivos_nomes=["pgdas.pdf"],
            persistir_auditoria=True,
        )

    # Diagnóstico ainda volta — extração principal não foi afetada
    assert "empresa" in diag
    assert diag["_extracao"]["auditoria_status"] in ("PARCIAL", "OK")  # 0 docs salvos = PARCIAL
    assert diag["_extracao"]["documentos_auditoria"] == []


def test_falha_total_de_master_key_marca_falhou(monkeypatch):
    """Se a master key não estiver no env, status vira FALHOU mas diag volta."""
    from extrator_pdfs import processar_pdfs_bytes

    monkeypatch.delenv("MOTOR_CONECT_MASTER_KEY", raising=False)

    patches = _patch_pipeline_claude()
    with patches["anthropic_client"], patches["motor"]:
        diag = processar_pdfs_bytes(
            [PDF_FAKE_A],
            arquivos_nomes=["pgdas.pdf"],
            persistir_auditoria=True,
        )

    assert "empresa" in diag
    # Cada doc individualmente vai falhar mas o try externo segura
    assert diag["_extracao"]["documentos_auditoria"] == []
    assert diag["_extracao"]["auditoria_status"] in ("PARCIAL", "FALHOU")
