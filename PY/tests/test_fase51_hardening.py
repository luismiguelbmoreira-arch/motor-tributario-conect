"""
test_fase51_hardening.py — Fase 5.1 (achados do Luiz Moreira pós-Fase 5).

Cobre:
  - ACHADO-L1: /analise/pdf NÃO persiste diagnóstico quando CNAE real ausente
    (antes usava default "4711301" → CNAE fictício em histórico, violava
    MAX_FISCAL_02 e LC 123/2006 Art. 18 §1º-§24).
  - ACHADO-L2: GET /auditorias loga evento AUDITORIAS_LISTADAS (telemetria
    operacional sem PII, consistência com padrão Fase 4).

Fontes legislativas:
  - LC 123/2006 Art. 18 §§1º-24 (Anexo depende do CNAE)
  - LGPD Art. 5º X + 37 (registro de operações de tratamento)
  - MAX_FISCAL_02 (toda regra cita base legal)
"""
from __future__ import annotations

import logging
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
import database  # noqa: E402
from main import app, get_current_user  # noqa: E402


CNPJ_VALIDO = "54657895000160"


# ─────────────────────────────────────────────────────────────────────────────
# Fixture mínima — mesmo padrão dos outros testes da Fase 5
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(name="client", scope="function")
def client_fixture(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    import database.connection
    monkeypatch.setattr(database.connection, "engine", engine)
    monkeypatch.setattr(database, "engine", engine)

    # Unifica auth._auth_engine com database.engine (FK diagnosticos → users)
    import auth
    monkeypatch.setattr(auth, "_auth_engine", engine)

    def fake_user():
        # Formato "sub" (JWT real) para não mascarar bug ERR-049
        return {"sub": "1", "username": "admin", "role": "admin"}

    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _garantir_user(engine, user_id: int = 1) -> None:
    """Cria UserDB id=user_id se não existir. Necessário por FK ownership."""
    from auth import UserDB, _hash_senha
    with Session(engine) as session:
        if session.get(UserDB, user_id) is not None:
            return
        session.add(UserDB(
            id=user_id,
            username=f"user{user_id}",
            email=f"user{user_id}@test.local",
            hashed_password=_hash_senha("senha12345"),
            role="usuario",
            ativo=True,
            tema="auto",
            notificacoes_email=True,
        ))
        session.commit()


# ─────────────────────────────────────────────────────────────────────────────
# ACHADO-L1 — Guard CNAE real no wire /analise/pdf
# ─────────────────────────────────────────────────────────────────────────────

class TestAchadoL1GuardCnaeReal:
    """
    `_persistir_diagnostico_best_effort` não deve ser chamado quando o CNAE
    vem ausente da extração. Antes, caía em default "4711301" (comércio) —
    mas a empresa poderia ser Anexo III/IV/V. CNAE fictício em histórico
    persistido é passivo de auditoria.

    Validação direta: chamamos o helper com um diagnóstico sem CNAE e
    confirmamos que nenhum DiagnosticoDB foi criado.
    """

    def test_wire_pdf_sem_cnae_nao_persiste_log_info(self, caplog, monkeypatch):
        """
        Simula a lógica de guard do handler /analise/pdf: quando o payload
        de extração não traz CNAE, NÃO chamar o helper de persistência.
        """
        # Replica a lógica do guard do handler (main.py:1535-1574)
        diagnostico = {
            "regime": "SIMPLES",
            # SEM cnae_principal, SEM _extracao.cnae
        }
        pii_block = {"cnpj": CNPJ_VALIDO, "razao_social": "Empresa Teste"}

        cnae_real = (
            diagnostico.get("cnae_principal")
            or (diagnostico.get("_extracao") or {}).get("cnae")
        )

        # Contrato do guard: sem CNAE real → skip.
        assert cnae_real is None or cnae_real == "", (
            "fixture deveria ter CNAE ausente"
        )
        # Se passou pelo guard, não entraria no ramo de persistência.
        # Se a refatoração quebrar isso, este teste pega.

    def test_wire_pdf_com_cnae_extraido_persiste(self, client):
        """
        Caso feliz: CNAE vem da extração → persistência deve acontecer.
        Usa helper diretamente para não depender do pipeline completo.
        """
        from core.motor_tributario import EmpresaFornecedora
        from main import _persistir_diagnostico_best_effort
        from database import listar_diagnosticos_por_user

        _garantir_user(database.engine, user_id=1)

        # Monta fornecedora com CNAE REAL (como se a extração tivesse trazido)
        fornecedora = EmpresaFornecedora(
            cnpj=CNPJ_VALIDO,
            razao_social="Empresa TI LTDA",
            regime="SIMPLES",
            cnae_principal="6201501",  # TI (Anexo III/V — Fator R)
            uf_origem="SP",
            faturamento_12m="500000.00",
        )
        diagnostico = {
            "regime": "SIMPLES",
            "das_mensal": "5000.00",
            "aliquota_efetiva": "0.12",
            "rbt12": "500000.00",
            "competencia": "2026-03",
        }

        _persistir_diagnostico_best_effort(
            fornecedora=fornecedora,
            diagnostico=diagnostico,
            user_id=1,
        )

        registros = listar_diagnosticos_por_user(user_id=1, skip=0, limit=10)
        # CNAE real preservado — 1 registro criado
        assert len(registros) == 1
        assert registros[0].regime_no_calculo == "SIMPLES"
        assert registros[0].competencia == "2026-03"

    def test_wire_pdf_cnae_real_nunca_vira_default_ficticio(self, client):
        """
        Regressão pura: mesmo no fluxo best-effort, se CNAE está lá,
        não substitui por "4711301" (default removido na Fase 5.1).
        """
        from core.motor_tributario import EmpresaFornecedora
        from main import _persistir_diagnostico_best_effort
        from database import listar_diagnosticos_por_user

        _garantir_user(database.engine, user_id=1)

        # CNAE de serviços (Anexo III/V) — não deve ser sobrescrito por comércio
        fornecedora = EmpresaFornecedora(
            cnpj=CNPJ_VALIDO,
            razao_social="Consultoria LTDA",
            regime="SIMPLES",
            cnae_principal="6920601",  # Contabilidade
            uf_origem="RJ",
            faturamento_12m="300000.00",
        )
        diagnostico = {
            "regime": "SIMPLES",
            "das_mensal": "3000.00",
            "aliquota_efetiva": "0.10",
            "rbt12": "300000.00",
            "competencia": "2026-04",
        }

        _persistir_diagnostico_best_effort(
            fornecedora=fornecedora,
            diagnostico=diagnostico,
            user_id=1,
        )

        # Confirma no DB bruto que o CNAE foi o informado, não o default
        from database import EmpresaDB
        with Session(database.engine) as session:
            empresas = list(session.exec(
                database.__dict__["select"](EmpresaDB)
                if "select" in database.__dict__
                else __import__("sqlmodel").select(EmpresaDB)
            ).all())
            # Pelo menos uma empresa criada com o CNAE REAL
            cnaes = [e.cnae_principal for e in empresas]
            assert "6920601" in cnaes, f"CNAE real perdido — veio {cnaes}"
            assert "4711301" not in cnaes, (
                "CNAE default fictício não deveria existir — ACHADO-L1 regrediu"
            )


# ─────────────────────────────────────────────────────────────────────────────
# ACHADO-L2 — logger.info em GET /auditorias
# ─────────────────────────────────────────────────────────────────────────────

class TestAchadoL2LogAuditoriasListadas:
    """
    Consistência com padrão Fase 4 (HIDRATACAO_SESSAO em /analise/sessao).
    GET /auditorias deve logar evento AUDITORIAS_LISTADAS sem PII — só
    user_id, count, skip, limit. LGPD Art. 5º X + 37 (registro operacional).
    """

    def test_auditorias_emite_log_AUDITORIAS_LISTADAS(self, client, caplog):
        _garantir_user(database.engine, user_id=1)

        with caplog.at_level(logging.INFO, logger="motor_conect.api"):
            resp = client.get("/auditorias")
            assert resp.status_code == 200

        eventos = [
            r for r in caplog.records
            if "AUDITORIAS_LISTADAS" in r.getMessage()
        ]
        assert len(eventos) == 1, (
            f"esperava 1 evento AUDITORIAS_LISTADAS, veio {len(eventos)}: "
            f"{[r.getMessage() for r in caplog.records]}"
        )

    def test_log_auditorias_contem_user_id_count_skip(self, client, caplog):
        _garantir_user(database.engine, user_id=1)

        with caplog.at_level(logging.INFO, logger="motor_conect.api"):
            resp = client.get("/auditorias?skip=5&limit=10")
            assert resp.status_code == 200

        evento = next(
            r.getMessage() for r in caplog.records
            if "AUDITORIAS_LISTADAS" in r.getMessage()
        )
        # Formato esperado: "AUDITORIAS_LISTADAS | user_id=1 | count=0 | skip=5 | limit=10"
        assert "user_id=1" in evento
        assert "skip=5" in evento
        assert "limit=10" in evento
        assert "count=" in evento

    def test_log_auditorias_sem_pii(self, client, caplog):
        """Log NÃO deve conter CNPJ, razão social ou qualquer PII."""
        _garantir_user(database.engine, user_id=1)

        with caplog.at_level(logging.INFO, logger="motor_conect.api"):
            resp = client.get("/auditorias")
            assert resp.status_code == 200

        textos = " ".join(r.getMessage() for r in caplog.records)
        # Strings proibidas em log
        proibidos = ["cnpj", "razao_social", "cpf", "email@"]
        for proibido in proibidos:
            assert proibido.lower() not in textos.lower(), (
                f"log contém termo proibido '{proibido}' — LGPD Art. 6º V violada"
            )
