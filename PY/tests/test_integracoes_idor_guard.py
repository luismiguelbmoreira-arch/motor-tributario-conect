# -*- coding: utf-8 -*-
"""
test_integracoes_idor_guard.py — ERR-018.b: IDOR Guard nos endpoints de integração.

Cobre _verificar_ownership_cnpj aplicado em:
  - POST /sieg/sincronizar
  - POST /integra/sincronizar
  - POST /integracoes/ecac/sync
  - GET  /auditoria/prova/cnpj/{cnpj_digitos}

Cenários:
  1.  Usuário sem ownership → 403
  2.  Bloqueio persiste em AuditoriaTentativaAcessoDB
  3.  Ownership via DiagnosticoDB → guard libera (status != 403)
  4.  Ownership via AuditoriaDocumentoDB (raw) → guard libera
  5.  CNPJ formatado no documento, raw na request → guard libera
  6.  CNPJ enviado formatado e raw → comportamento equivalente
  7.  Guard aplicado em /integra/sincronizar
  8.  Guard aplicado em /integracoes/ecac/sync (multipart)
  9.  Admin bypassa guard em qualquer CNPJ
 10.  Admin bypass não polui AuditoriaTentativaAcessoDB
 11.  JWT sem sub nem id → 403 sem linha de auditoria
 12.  Admin bypass gera log ADMIN_CNPJ_ACCESS sem PII (LGPD Art. 37)
 13.  Guard aplicado em /auditoria/prova/cnpj/ (dossiê ZIP)

Amparo:
  - LGPD Art. 46 §1º + Art. 6º VII (guard preventivo)
  - LGPD Art. 48 (prova de incidente reportável à ANPD — tabela de tentativas)
  - CTN Art. 198 (sigilo fiscal, fundamento subsidiário)
"""
from __future__ import annotations

import logging
import os
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MOTOR_CONECT_MASTER_KEY", "0" * 64)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("JWT_SECRET_KEY", "test-idor-guard-err018b")

import database  # noqa: E402
from database import AuditoriaTentativaAcessoDB  # noqa: E402

# CNPJ sem registros no DB — guard sempre bloqueia
CNPJ_ALHEIO = "12345678000100"

# CNPJ com EmpresaDB + DiagnosticoDB.uploaded_by_user_id=1
CNPJ_PROPRIO_DIAG = "54657895000160"

# CNPJ com AuditoriaDocumentoDB.uploaded_by_user_id=1 (formato raw)
CNPJ_PROPRIO_DOC_RAW = "11222333000144"

# CNPJ armazenado formatado em AuditoriaDocumentoDB, enviado raw na request
CNPJ_PROPRIO_DOC_FORMATADO = "11.333.666/0001-81"
CNPJ_PROPRIO_DOC_FORMATADO_RAW = "11333666000181"


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(name="db_engine")
def db_engine_fixture():
    """SQLite em memória semeado: users 1 (usuario) e 2 (admin) + dados de ownership."""
    import auth  # noqa: F401 — registra UserDB no metadata SQLModel

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    from auth import UserDB
    from database.models import AuditoriaDocumentoDB, DiagnosticoDB, EmpresaDB

    with Session(engine) as session:
        session.add(UserDB(
            id=1, username="user1", email="user1@test.local",
            hashed_password="x", role="usuario", ativo=True,
        ))
        session.add(UserDB(
            id=2, username="admin1", email="admin@test.local",
            hashed_password="x", role="admin", ativo=True,
        ))

        # EmpresaDB + DiagnosticoDB com ownership de user_id=1
        empresa = EmpresaDB(
            cnpj=CNPJ_PROPRIO_DIAG,
            razao_social="Empresa TI LTDA",
            regime="SIMPLES",
            cnae_principal="6201501",
            uf_origem="SP",
            faturamento_12m="500000.00",
        )
        session.add(empresa)
        session.flush()

        session.add(DiagnosticoDB(
            empresa_id=empresa.id,
            competencia="2026-03",
            resultado_json="{}",
            das_mensal="5000.00",
            aliquota_efetiva="0.10",
            rbt12_usado="500000.00",
            regime_no_calculo="SIMPLES",
            uploaded_by_user_id=1,
        ))

        # AuditoriaDocumentoDB com CNPJ raw — ownership user_id=1
        session.add(AuditoriaDocumentoDB(
            hash_sha256="a" * 64,
            empresa_cnpj=CNPJ_PROPRIO_DOC_RAW,
            nome_original="doc_raw.pdf",
            tamanho_bytes=1024,
            storage_path="/data/test/a.bin",
            uploaded_by_user_id=1,
        ))

        # AuditoriaDocumentoDB com CNPJ formatado — ownership user_id=1
        session.add(AuditoriaDocumentoDB(
            hash_sha256="b" * 64,
            empresa_cnpj=CNPJ_PROPRIO_DOC_FORMATADO,
            nome_original="doc_formatado.pdf",
            tamanho_bytes=2048,
            storage_path="/data/test/b.bin",
            uploaded_by_user_id=1,
        ))

        session.commit()

    return engine


def _patch_engines(monkeypatch, engine) -> None:
    import database.connection
    import auth as _auth_mod

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database.connection, "engine", engine)
    monkeypatch.setattr(_auth_mod, "_auth_engine", engine)


@pytest.fixture(name="client_user1")
def client_user1_fixture(db_engine, monkeypatch):
    """TestClient autenticado como user_id=1 (role=usuario)."""
    _patch_engines(monkeypatch, db_engine)

    from main import app, get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "1", "username": "user1", "role": "usuario",
    }
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(name="client_admin")
def client_admin_fixture(db_engine, monkeypatch):
    """TestClient autenticado como user_id=2 (role=admin)."""
    _patch_engines(monkeypatch, db_engine)

    from main import app, get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "2", "username": "admin1", "role": "admin",
    }
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def _contar_tentativas(db_engine) -> int:
    with Session(db_engine) as session:
        return session.query(AuditoriaTentativaAcessoDB).count()


def _ultima_tentativa(db_engine) -> AuditoriaTentativaAcessoDB | None:
    with Session(db_engine) as session:
        return (
            session.query(AuditoriaTentativaAcessoDB)
            .order_by(AuditoriaTentativaAcessoDB.id.desc())
            .first()
        )


# ─── Bloqueio e auditoria ────────────────────────────────────────────────────

class TestIDORGuardBloqueio:

    def test_sieg_cnpj_alheio_retorna_403(self, client_user1):
        resp = client_user1.post(
            "/sieg/sincronizar",
            json={"cnpj": CNPJ_ALHEIO, "ano_base": 2026},
        )
        assert resp.status_code == 403, f"Esperado 403, veio {resp.status_code}"

    def test_sieg_cnpj_alheio_persiste_tentativa_auditoria(self, client_user1, db_engine):
        antes = _contar_tentativas(db_engine)
        resp = client_user1.post(
            "/sieg/sincronizar",
            json={"cnpj": CNPJ_ALHEIO, "ano_base": 2026},
        )
        assert resp.status_code == 403
        assert _contar_tentativas(db_engine) == antes + 1

        linha = _ultima_tentativa(db_engine)
        assert linha is not None
        assert linha.analise_id_prefix == CNPJ_ALHEIO[:8]
        assert linha.user_id_tentando == 1
        assert linha.endpoint == "/sieg/sincronizar"

    def test_sieg_cnpj_proprio_via_diagnostico_passa_guard(self, client_user1):
        resp = client_user1.post(
            "/sieg/sincronizar",
            json={"cnpj": CNPJ_PROPRIO_DIAG, "ano_base": 2026},
        )
        assert resp.status_code != 403, (
            f"Guard bloqueou usuário com ownership via DiagnosticoDB: {resp.status_code}"
        )

    def test_sieg_cnpj_proprio_via_documento_passa_guard(self, client_user1):
        resp = client_user1.post(
            "/sieg/sincronizar",
            json={"cnpj": CNPJ_PROPRIO_DOC_RAW, "ano_base": 2026},
        )
        assert resp.status_code != 403, (
            f"Guard bloqueou usuário com ownership via AuditoriaDocumentoDB: {resp.status_code}"
        )

    def test_sieg_cnpj_formatado_no_documento_passa_guard(self, client_user1):
        """CNPJ armazenado formatado no doc, enviado raw na request → guard libera."""
        resp = client_user1.post(
            "/sieg/sincronizar",
            json={"cnpj": CNPJ_PROPRIO_DOC_FORMATADO_RAW, "ano_base": 2026},
        )
        assert resp.status_code != 403

    def test_sieg_cnpj_formatado_na_request_resolve_igual_raw(self, client_user1):
        """Mesmo CNPJ formatado e raw na request produzem o mesmo resultado de guard."""
        cnpj_raw = CNPJ_PROPRIO_DOC_RAW
        cnpj_fmt = (
            f"{cnpj_raw[:2]}.{cnpj_raw[2:5]}.{cnpj_raw[5:8]}"
            f"/{cnpj_raw[8:12]}-{cnpj_raw[12:]}"
        )
        resp_raw = client_user1.post(
            "/sieg/sincronizar", json={"cnpj": cnpj_raw, "ano_base": 2026},
        )
        resp_fmt = client_user1.post(
            "/sieg/sincronizar", json={"cnpj": cnpj_fmt, "ano_base": 2026},
        )
        # Ambos ou bloqueiam (403) ou passam — resultado idêntico
        assert (resp_raw.status_code == 403) == (resp_fmt.status_code == 403), (
            f"Formatos deveriam produzir mesmo resultado de guard: raw={resp_raw.status_code} fmt={resp_fmt.status_code}"
        )


# ─── Guard em outros endpoints ────────────────────────────────────────────────

class TestIDORGuardOutrosEndpoints:

    def test_integra_sincronizar_cnpj_alheio_retorna_403(self, client_user1):
        resp = client_user1.post(
            "/integra/sincronizar",
            json={"cnpj": CNPJ_ALHEIO, "ano_base": 2026},
        )
        assert resp.status_code == 403

    def test_ecac_sync_cnpj_alheio_retorna_403_form_data(self, client_user1):
        resp = client_user1.post(
            "/integracoes/ecac/sync",
            data={"cnpj": CNPJ_ALHEIO, "senha_cert": "senha_fake"},
            files={"certificado_pfx": ("cert.pfx", b"fake_pfx", "application/octet-stream")},
        )
        assert resp.status_code == 403, (
            f"Guard deveria bloquear antes de processar .pfx: {resp.status_code}"
        )

    def test_auditoria_prova_cnpj_alheio_retorna_403(self, client_user1):
        """Guard no endpoint de dossiê ZIP — qualquer CNPJ sem ownership → 403."""
        resp = client_user1.get(
            f"/auditoria/prova/cnpj/{CNPJ_ALHEIO}",
            params={"motivo": "Teste de bloqueio ERR-018.b"},
        )
        assert resp.status_code == 403, (
            f"Endpoint de dossiê deveria bloquear CNPJ sem ownership: {resp.status_code}"
        )


# ─── Admin bypass ─────────────────────────────────────────────────────────────

class TestAdminBypass:

    def test_admin_bypassa_guard_qualquer_cnpj(self, client_admin):
        """Admin nunca recebe 403 do guard de ownership."""
        resp = client_admin.post(
            "/sieg/sincronizar",
            json={"cnpj": CNPJ_ALHEIO, "ano_base": 2026},
        )
        assert resp.status_code != 403, (
            f"Admin não deveria ser bloqueado pelo guard: {resp.status_code}"
        )

    def test_admin_bypass_nao_polui_auditoria(self, client_admin, db_engine):
        """Admin bypass não gera linha em AuditoriaTentativaAcessoDB."""
        antes = _contar_tentativas(db_engine)
        client_admin.post(
            "/sieg/sincronizar",
            json={"cnpj": CNPJ_ALHEIO, "ano_base": 2026},
        )
        assert _contar_tentativas(db_engine) == antes

    def test_admin_bypass_gera_log_sem_pii(self, client_admin, caplog):
        """Admin bypass emite ADMIN_CNPJ_ACCESS sem CNPJ no log (LGPD Art. 37)."""
        with caplog.at_level(logging.INFO, logger="motor_conect.api"):
            client_admin.post(
                "/sieg/sincronizar",
                json={"cnpj": CNPJ_ALHEIO, "ano_base": 2026},
            )
        textos = " ".join(r.getMessage() for r in caplog.records)
        assert "ADMIN_CNPJ_ACCESS" in textos, (
            f"Log ADMIN_CNPJ_ACCESS não emitido. Logs: {textos[:300]}"
        )
        assert CNPJ_ALHEIO not in textos, "CNPJ completo não deve vazar no log"


# ─── JWT sem sub/id ──────────────────────────────────────────────────────────

class TestJwtSemSubOuId:

    def test_jwt_sem_sub_sem_id_retorna_403_sem_tentativa(self, db_engine, monkeypatch):
        """extrair_user_id retorna None → 403 imediato, sem linha de auditoria."""
        _patch_engines(monkeypatch, db_engine)

        from main import app, get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "ghost", "role": "usuario",
        }

        antes = _contar_tentativas(db_engine)
        with TestClient(app) as client:
            resp = client.post(
                "/sieg/sincronizar",
                json={"cnpj": CNPJ_ALHEIO, "ano_base": 2026},
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 403
        assert _contar_tentativas(db_engine) == antes, (
            "JWT sem user_id válido não deve gerar linha de tentativa"
        )
