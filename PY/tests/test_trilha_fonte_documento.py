"""
test_trilha_fonte_documento.py — Trava o enriquecimento da trilha de auditoria
com referências aos documentos-fonte.

Objetivo: provar que cada passo da trilha retornada por
processar_pdfs_bytes(persistir_auditoria=True) tem o campo `fonte` apontando
para os documentos cifrados. Sem isso, a trilha seria inútil em fiscalização
(prova a fórmula mas não a origem dos dados).
"""
from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import database  # noqa: E402
import storage_cifrado  # noqa: E402
from extrator_pdfs import _inferir_campo_origem  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import SQLModel, create_engine  # noqa: E402


PDF_FAKE = b"%PDF-1.4\n%fake\n" + b"a" * 512
CNPJ_FAKE = "54657895000160"
CNPJ_FAKE_NORMALIZADO = "54.657.895/0001-60"


@pytest.fixture(autouse=True)
def iso(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_cifrado, "STORAGE_ROOT", tmp_path / "auditoria")
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    yield


def _patch_pipeline(trilha_fake=None):
    """Mock do pipeline Claude + motor com trilha customizada."""
    fake_response = MagicMock()
    fake_response.content = [
        MagicMock(text=(
            '{"cnpj":"' + CNPJ_FAKE + '",'
            '"razao_social":"FAKE","cnae_principal":"4757100","uf_origem":"SP",'
            '"faturamento_12m":"1000000","anexo_simples":"I",'
            '"rpa_referencia":"83333.33","das_ecac_referencia":"5833.33",'
            '"competencia":"01/2026","confianca_extracao":0.99}'
        ))
    ]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    diag_base = {
        "empresa": {"regime": "SIMPLES", "anexo_simples": "I"},
        "aliquotas": {"efetiva_das_total": "0.07"},
        "cenarios": {},
        "trilha_auditoria": trilha_fake if trilha_fake is not None else [
            {"tipo": "CALCULO", "id": "FASE2_RBT12", "titulo": "Receita Bruta 12m",
             "formula": "x", "amparo_legal": "LC 123/2006, Art. 12"},
            {"tipo": "CALCULO", "id": "FATOR_R", "titulo": "Fator R",
             "formula": "y", "amparo_legal": "LC 123/2006, Art. 18"},
            {"tipo": "CALCULO", "id": "FASE2_ANEXO", "titulo": "Anexo",
             "formula": "z", "amparo_legal": "LC 123/2006, Anexo III"},
            {"tipo": "CALCULO", "id": "FASE2_ALIQUOTA_EFETIVA", "titulo": "Aliquota",
             "formula": "w", "amparo_legal": "LC 123/2006, Art. 18"},
            {"tipo": "CALCULO", "id": "DIFAL_BASE_UNICA", "titulo": "DIFAL",
             "formula": "v", "amparo_legal": "EC 87/2015"},
            {"tipo": "ALERTA_INFO", "id": "CRONOGRAMA_IVA_2026", "titulo": "Cronograma",
             "amparo_legal": "LC 214/2025, Art. 348"},
            {"tipo": "ALERTA_STRESS", "id": "STRESS_R14_FANTASMA", "titulo": "Stress",
             "amparo_legal": "LC 123/2006"},
        ],
    }

    fake_motor_instance = MagicMock()
    fake_motor_instance.gerar_diagnostico.return_value = diag_base
    fake_motor_class = MagicMock(return_value=fake_motor_instance)

    return (
        patch("extrator_pdfs.anthropic.Anthropic", return_value=fake_client),
        patch("motor_tributario.MotorReformaTributaria", fake_motor_class),
    )


# ── _inferir_campo_origem ──────────────────────────────────────────────────


class TestInferirCampoOrigem:
    def test_rbt12(self):
        assert "RBT12" in _inferir_campo_origem("FASE2_RBT12")

    def test_fator_r(self):
        assert "Folha" in _inferir_campo_origem("FATOR_R_BORDA")

    def test_folha(self):
        assert "Folha" in _inferir_campo_origem("FOLHA_12M_CALCULADA")

    def test_anexo(self):
        assert "Anexo" in _inferir_campo_origem("FASE2_ANEXO_III")

    def test_cnae(self):
        assert "CNAE" in _inferir_campo_origem("CNAE_VALIDACAO")

    def test_difal(self):
        assert "UF" in _inferir_campo_origem("DIFAL_BASE_DUPLA")

    def test_cronograma(self):
        assert "LC 214/2025" in _inferir_campo_origem("CRONOGRAMA_IVA_2026")

    def test_aliquota_derivado(self):
        assert "derivado" in _inferir_campo_origem("FASE2_ALIQUOTA_EFETIVA")

    def test_stress_derivado(self):
        assert "derivado" in _inferir_campo_origem("STRESS_R14_FANTASMA")

    def test_default_fallback(self):
        assert "PGDAS-D" in _inferir_campo_origem("INEXISTENTE_XYZ")

    def test_case_insensitive(self):
        assert _inferir_campo_origem("fase2_rbt12") == _inferir_campo_origem("FASE2_RBT12")

    def test_id_vazio(self):
        assert "PGDAS-D" in _inferir_campo_origem("")


# ── Enriquecimento da trilha via processar_pdfs_bytes ──────────────────────


class TestTrilhaEnriquecida:
    def test_trilha_recebe_fonte_em_cada_passo(self):
        from extrator_pdfs import processar_pdfs_bytes

        p1, p2 = _patch_pipeline()
        with p1, p2:
            diag = processar_pdfs_bytes(
                [PDF_FAKE],
                arquivos_nomes=["pgdas.pdf"],
                persistir_auditoria=True,
            )

        trilha = diag["trilha_auditoria"]
        assert len(trilha) == 7
        for passo in trilha:
            assert "fonte" in passo, f"passo {passo['id']} sem fonte"
            fonte = passo["fonte"]
            assert fonte["tipo"] == "extracao_pdf"
            assert len(fonte["documentos_ids"]) == 1
            assert len(fonte["documentos_hashes"]) == 1
            assert len(fonte["documentos_hashes"][0]) == 64  # sha256

    def test_todos_os_passos_apontam_para_mesma_lista_de_docs(self):
        from extrator_pdfs import processar_pdfs_bytes

        p1, p2 = _patch_pipeline()
        with p1, p2:
            diag = processar_pdfs_bytes(
                [PDF_FAKE, b"%PDF-1.4\n%other\n" + b"b" * 200],
                arquivos_nomes=["a.pdf", "b.pdf"],
                persistir_auditoria=True,
            )

        trilha = diag["trilha_auditoria"]
        refs = [tuple(p["fonte"]["documentos_ids"]) for p in trilha]
        # Todos os passos compartilham a mesma lista (2 docs)
        assert all(len(r) == 2 for r in refs)
        assert len(set(refs)) == 1  # todas iguais

    def test_campo_origem_cada_passo_reflete_sua_semantica(self):
        from extrator_pdfs import processar_pdfs_bytes

        p1, p2 = _patch_pipeline()
        with p1, p2:
            diag = processar_pdfs_bytes(
                [PDF_FAKE],
                arquivos_nomes=["pgdas.pdf"],
                persistir_auditoria=True,
            )

        por_id = {p["id"]: p["fonte"]["campo_origem"] for p in diag["trilha_auditoria"]}
        assert "RBT12" in por_id["FASE2_RBT12"]
        assert "Folha" in por_id["FATOR_R"]
        assert "Anexo" in por_id["FASE2_ANEXO"]
        assert "derivado" in por_id["FASE2_ALIQUOTA_EFETIVA"]
        assert "UF" in por_id["DIFAL_BASE_UNICA"]
        assert "LC 214/2025" in por_id["CRONOGRAMA_IVA_2026"]
        assert "derivado" in por_id["STRESS_R14_FANTASMA"]

    def test_persistir_desativado_trilha_nao_tem_fonte(self):
        """Backward compat: sem persistir_auditoria, trilha continua sem fonte."""
        from extrator_pdfs import processar_pdfs_bytes

        p1, p2 = _patch_pipeline()
        with p1, p2:
            diag = processar_pdfs_bytes([PDF_FAKE])

        for passo in diag["trilha_auditoria"]:
            assert "fonte" not in passo

    def test_falha_de_cifra_trilha_nao_e_enriquecida(self, monkeypatch):
        """Se nenhum doc foi salvo, não adiciona fonte vazia."""
        from extrator_pdfs import processar_pdfs_bytes

        def explode(*a, **kw):
            raise RuntimeError("disco cheio")

        monkeypatch.setattr(storage_cifrado, "cifrar_e_persistir", explode)

        p1, p2 = _patch_pipeline()
        with p1, p2:
            diag = processar_pdfs_bytes(
                [PDF_FAKE],
                arquivos_nomes=["x.pdf"],
                persistir_auditoria=True,
            )

        # Nenhum doc foi salvo → trilha não recebe fonte (evita link quebrado)
        for passo in diag["trilha_auditoria"]:
            assert "fonte" not in passo

    def test_trilha_vazia_nao_quebra(self):
        """Edge case: diagnóstico sem trilha."""
        from extrator_pdfs import processar_pdfs_bytes

        p1, p2 = _patch_pipeline(trilha_fake=[])
        with p1, p2:
            diag = processar_pdfs_bytes(
                [PDF_FAKE],
                arquivos_nomes=["x.pdf"],
                persistir_auditoria=True,
            )

        assert diag["trilha_auditoria"] == []

    def test_passo_malformado_e_ignorado(self):
        """Se um passo for string ou None em vez de dict, não quebra."""
        from extrator_pdfs import processar_pdfs_bytes

        trilha_com_lixo = [
            {"id": "FASE2_RBT12", "tipo": "CALCULO"},
            "string malformada",  # não é dict
            None,
            {"id": "FATOR_R", "tipo": "CALCULO"},
        ]
        p1, p2 = _patch_pipeline(trilha_fake=trilha_com_lixo)
        with p1, p2:
            diag = processar_pdfs_bytes(
                [PDF_FAKE],
                arquivos_nomes=["x.pdf"],
                persistir_auditoria=True,
            )

        # Os 2 dicts viraram com fonte; os 2 lixos ficaram como estavam
        trilha = diag["trilha_auditoria"]
        assert len(trilha) == 4
        assert "fonte" in trilha[0]
        assert trilha[1] == "string malformada"
        assert trilha[2] is None
        assert "fonte" in trilha[3]
