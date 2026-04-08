"""
database.py — Camada de Persistência do Motor Tributário Conect 2026-2033

ARQUITETURA (parecer O Viciado 28/03/2026):
  - Models de DOMÍNIO (BaseModel) ficam em motor_tributario.py — NÃO MUDAM.
  - Models de PERSISTÊNCIA (SQLModel) ficam AQUI — com id, timestamps, FK.
  - Conversão explícita entre os dois via métodos to_domain() / from_domain().
  - Decimal armazenado como TEXT no SQLite (sem float, sem surpresa).
  - PRAGMA strict=ON ativado na conexão.

LGPD (Lei 13.709/2018, Art. 15):
  - purge_empresa() apaga dados de empresa específica.
  - Logs de diagnóstico NÃO contêm CNPJ ou razão social — só IDs internos.
  - Retenção: 5 anos (prazo fiscal), depois purge obrigatório.

Fase 1: SQLite local (arquivo .db, zero config)
Fase 2: PostgreSQL (mudar DATABASE_URL, Alembic migra schema)
"""

import json
import logging
import os
import re
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import TEXT, Column, Field, Session, SQLModel, create_engine

logger = logging.getLogger("motor_conect.database")


# ─────────────────────────────────────────────────────────────────────────────
# ENUMS — Contratos de domínio para persistência
# ─────────────────────────────────────────────────────────────────────────────

class RegimeTributario(str, Enum):
    """
    Regimes tributários suportados pelo motor.
    LC 123/2006 (Simples/MEI) | RIR/2018 (Presumido/Real).
    ATENÇÃO: adicionar novo valor aqui exige aprovação de Luiz Moreira.
    """
    SIMPLES = "SIMPLES"
    PRESUMIDO = "PRESUMIDO"
    REAL = "REAL"
    MEI = "MEI"


class NivelAlerta(str, Enum):
    """Níveis de severidade para alertas do motor."""
    INFO = "INFO"
    MEDIO = "MEDIO"
    ATENCAO = "ATENCAO"
    ALTO = "ALTO"
    CRITICO = "CRITICO"


class StatusAlerta(str, Enum):
    """Ciclo de vida do alerta."""
    ABERTO = "ABERTO"
    RESOLVIDO = "RESOLVIDO"
    IGNORADO = "IGNORADO"


class StatusAuditoria(str, Enum):
    """Status de auditoria do diagnóstico vs e-CAC."""
    APROVADO = "APROVADO"
    PENDENTE = "PENDENTE"
    REJEITADO = "REJEITADO"


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURAÇÃO DO BANCO
# ─────────────────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite:///" + str(Path(__file__).resolve().parent.parent / "data" / "motor_tributario.db"),
)


def validar_competencia(competencia: str) -> str:
    """
    Valida e retorna competência no formato ISO 8601 'YYYY-MM'.
    Rejeita formato BR 'MM/YYYY'. Rejeita qualquer outro formato.

    Raises:
        ValueError: se formato inválido ou fora do range 2020-2040.
    """
    if re.match(r"^\d{2}/\d{4}$", competencia):
        raise ValueError(
            f"Competencia '{competencia}' esta no formato BR (MM/YYYY). "
            f"Use formato ISO 8601: 'YYYY-MM'. Exemplo: '2026-01'."
        )
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", competencia):
        raise ValueError(
            f"Competencia '{competencia}' invalida. "
            f"Formato obrigatorio: 'YYYY-MM' (ex: '2026-01')."
        )
    ano = int(competencia[:4])
    if ano < 2020 or ano > 2040:
        raise ValueError(
            f"Competencia '{competencia}' fora do range fiscal 2020-2040."
        )
    return competencia

# SQLite: ativar PRAGMA strict e WAL mode na conexão
# Parecer Viciado: "Sem PRAGMA strict=ON, a proposta está VETADA."
@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_conn: Any, connection_record: Any) -> None:
    """Ativa strict mode e WAL no SQLite. Ignorado em PostgreSQL."""
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")       # Write-Ahead Logging
        cursor.execute("PRAGMA foreign_keys=ON;")         # FK enforcement
        cursor.execute("PRAGMA busy_timeout=5000;")       # 5s antes de lock error
    except Exception as e:
        logger.warning("[database] PRAGMA setup ignorado (provavelmente PostgreSQL): %s", e)
    finally:
        cursor.close()


engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},  # SQLite thread safety
)


def criar_tabelas() -> None:
    """Cria todas as tabelas se não existirem."""
    SQLModel.metadata.create_all(engine)
    logger.info("Tabelas criadas/verificadas com sucesso.")


def get_session() -> Session:
    """Retorna uma sessão do banco."""
    return Session(engine)


# ─────────────────────────────────────────────────────────────────────────────
# MODELS DE PERSISTÊNCIA
# Regra Viciado: "Separar model de domínio do model de persistência."
# ─────────────────────────────────────────────────────────────────────────────

class EmpresaDB(SQLModel, table=True):
    """
    Persistência de empresa. Espelha EmpresaFornecedora mas com:
    - id (PK auto-increment)
    - created_at / updated_at (auditoria temporal)
    - Decimal como TEXT (SQLite não tem NUMERIC real)

    Conversão: EmpresaDB.from_domain(empresa) / empresa_db.to_domain()
    """
    __tablename__ = "empresas"

    id: Optional[int] = Field(default=None, primary_key=True)
    cnpj: str = Field(index=True, unique=True, max_length=18)
    razao_social: str = Field(max_length=200)
    regime: str = Field(max_length=20)  # SIMPLES, PRESUMIDO, REAL
    cnae_principal: str = Field(max_length=10)
    uf_origem: str = Field(max_length=2)

    # Decimal como TEXT — Parecer Viciado: "float no banco = LOG_ERROS.md"
    faturamento_12m: str = Field(sa_column=Column(TEXT, nullable=False))
    folha_salarios_12m: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))

    anexo_simples: Optional[str] = Field(default=None, max_length=3)

    # Auditoria temporal
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    @classmethod
    def from_domain(cls, empresa: Any) -> "EmpresaDB":
        """Converte EmpresaFornecedora (domínio) → EmpresaDB (persistência)."""
        return cls(
            cnpj=empresa.cnpj,
            razao_social=empresa.razao_social,
            regime=empresa.regime,
            cnae_principal=empresa.cnae_principal,
            uf_origem=empresa.uf_origem,
            faturamento_12m=str(empresa.faturamento_12m),
            folha_salarios_12m=str(empresa.folha_salarios_12m) if empresa.folha_salarios_12m is not None else None,
            anexo_simples=empresa.anexo_simples,
        )

    def to_domain_dict(self) -> Dict[str, Any]:
        """Converte EmpresaDB → dict compatível com EmpresaFornecedora()."""
        return {
            "cnpj": self.cnpj,
            "razao_social": self.razao_social,
            "regime": self.regime,
            "cnae_principal": self.cnae_principal,
            "uf_origem": self.uf_origem,
            "faturamento_12m": Decimal(self.faturamento_12m),
            "folha_salarios_12m": Decimal(self.folha_salarios_12m) if self.folha_salarios_12m else None,
            "anexo_simples": self.anexo_simples,
        }


class AtividadeDB(SQLModel, table=True):
    """
    Persistência de atividade individual (multi-atividade PGDAS-D).
    FK → empresas.id
    LC 123/2006, Art. 18, §3º
    """
    __tablename__ = "atividades"

    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresas.id", index=True)
    competencia: str = Field(max_length=7)  # "2026-01" ISO 8601

    receita: str = Field(sa_column=Column(TEXT, nullable=False))  # Decimal como TEXT
    anexo: str = Field(max_length=3)  # I, II, III, IV, V
    icms_st: bool = Field(default=False)
    iss_retido: bool = Field(default=False)

    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def to_domain_dict(self) -> Dict[str, Any]:
        """Converte AtividadeDB → dict compatível com Atividade()."""
        return {
            "receita": Decimal(self.receita),
            "anexo": self.anexo,
            "icms_st": self.icms_st,
            "iss_retido": self.iss_retido,
        }


class DiagnosticoDB(SQLModel, table=True):
    """
    Persistência de diagnóstico gerado pelo motor.
    FK → empresas.id
    LGPD: diagnóstico NÃO contém CNPJ — referencia por empresa_id.
    """
    __tablename__ = "diagnosticos"

    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresas.id", index=True)
    competencia: str = Field(max_length=7)  # "2026-01" ISO 8601

    # Resultado do motor — JSON completo
    resultado_json: str = Field(sa_column=Column(TEXT, nullable=False))

    # Campos-chave extraídos pra query rápida (Decimal como TEXT)
    das_mensal: str = Field(sa_column=Column(TEXT, nullable=False))
    aliquota_efetiva: str = Field(sa_column=Column(TEXT, nullable=False))
    rbt12_usado: str = Field(sa_column=Column(TEXT, nullable=False))

    # ERR-010: regime usado no cálculo (rastreabilidade MAX_01)
    regime_no_calculo: str = Field(max_length=20)  # Validado por RegimeTributario

    # Auditoria
    das_ecac_referencia: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))
    delta: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))
    status_auditoria: Optional[str] = Field(default=None, max_length=20)  # APROVADO, PENDENTE, REJEITADO

    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    def get_resultado(self) -> Dict[str, Any]:
        """Deserializa o JSON do diagnóstico."""
        return json.loads(self.resultado_json)

    def get_das_mensal(self) -> Decimal:
        """Retorna DAS mensal como Decimal."""
        return Decimal(self.das_mensal)

    def get_delta(self) -> Optional[Decimal]:
        """Retorna delta como Decimal."""
        return Decimal(self.delta) if self.delta else None


class EmpresaHistoricoDB(SQLModel, table=True):
    """
    Rastreabilidade de alterações em dados da empresa.

    CTN Art. 180: A imunidade tributária não extingue a obrigação de
    comprovar os fatos que a justificam. Alterações em dados fiscais
    (faturamento, regime, CNAE) devem ser rastreáveis.

    LGPD: Registra o CAMPO alterado (não o CNPJ) para minimizar PII.
    O empresa_id serve de referência sem expor dados sensíveis nos logs.

    Uso:
        registrar_historico_empresa(empresa_id=5, campo="faturamento_12m",
            valor_anterior="500000.00", valor_novo="620000.00",
            alterado_por="joao.silva")
    """
    __tablename__ = "empresa_historico"

    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresas.id", index=True)

    # O que mudou
    campo_alterado: str = Field(max_length=50)   # ex: "faturamento_12m", "regime", "cnae_principal"
    valor_anterior: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))
    valor_novo: str = Field(sa_column=Column(TEXT, nullable=False))

    # Quem e quando — rastreabilidade CTN Art. 180
    alterado_por: str = Field(max_length=100)    # username do operador
    alterado_em: str = Field(default_factory=lambda: datetime.now().isoformat())

    # Contexto opcional (ex: "Atualização via PGDAS-D jan/2026")
    motivo: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))


class AuditoriaDocumentoDB(SQLModel, table=True):
    """
    Persistência do registro de cada documento (PDF) submetido pelo cliente
    para análise. Armazena APENAS os metadados — o conteúdo cifrado vive
    em disco via storage_cifrado.py.

    Bloqueia o vetor "dado errado culpa do contador":
      - hash_sha256 = ID canônico do plaintext (imutável, irrefutável)
      - storage_path = ponteiro para o arquivo cifrado AES-256-GCM
      - aceito_em + aceito_por = termo de aceite digital do operador
      - empresa_cnpj armazenado em claro AQUI (precisa pra busca por
        cliente), mas o conteúdo do PDF jamais aparece em texto plano
        em DB ou logs.

    LGPD Art. 16 + CTN Art. 173:
      - purge_after = uploaded_at + 5 anos (decadência fiscal)
      - purged_at preenchido quando storage_cifrado.purge() é chamado
      - listar_documentos_purgaveis() permite cron de limpeza

    Vínculo com diagnóstico:
      - diagnostico_id (FK opcional): em qual análise este doc foi usado
      - Um doc pode ser referenciado por múltiplos diagnósticos (re-análise),
        mas só é cifrado uma vez (hash_sha256 unique).
    """
    __tablename__ = "auditoria_documentos"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Identificação imutável do conteúdo
    hash_sha256: str = Field(unique=True, index=True, max_length=64)

    # Ligação com cliente — empresa_cnpj precisa estar em claro para busca,
    # mas storage_path usa hash anônimo da pasta (LGPD)
    empresa_cnpj: str = Field(index=True, max_length=18)

    # Metadados do upload
    nome_original: str = Field(max_length=255)
    mime_type: str = Field(default="application/pdf", max_length=64)
    tamanho_bytes: int
    paginas: Optional[int] = Field(default=None)

    # Onde o arquivo cifrado vive em disco (relativo a STORAGE_ROOT)
    storage_path: str = Field(max_length=500)

    # Auditoria temporal — user_id e soft (UserDB tem engine proprio em auth.py)
    uploaded_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    uploaded_by_user_id: Optional[int] = Field(default=None, index=True)

    # Termo de aceite digital — registra quem confirmou que aquele é o
    # documento oficial a ser analisado. Sem aceite, o doc não pode ser
    # usado em diagnóstico (proteção do escritório).
    aceito_em: Optional[str] = Field(default=None)
    aceito_por_user_id: Optional[int] = Field(default=None, index=True)
    aceito_ip: Optional[str] = Field(default=None, max_length=64)

    # Vínculo com a análise que usou este doc — soft FK para permitir
    # registro do doc ANTES do diagnóstico ser persistido (cifragem
    # acontece no upload, motor roda depois)
    diagnostico_id: Optional[int] = Field(default=None, index=True)

    # LGPD Art. 16 — política de retenção
    purge_after: str = Field(
        default_factory=lambda: (
            datetime.now().replace(year=datetime.now().year + 5).isoformat()
        ),
        description="ISO datetime — quando este doc deve ser purgado (uploaded_at + 5 anos)",
    )
    purged_at: Optional[str] = Field(default=None)


class AuditoriaAcessoDB(SQLModel, table=True):
    """
    Log estruturado de cada acesso a documento original cifrado.
    LGPD Art. 37 — registro de operações de tratamento.

    Toda chamada a decifrar() em produção DEVE primeiro registrar aqui
    quem está acessando, qual documento, e por quê (motivo livre).
    """
    __tablename__ = "auditoria_acessos"

    id: Optional[int] = Field(default=None, primary_key=True)
    documento_id: int = Field(foreign_key="auditoria_documentos.id", index=True)
    acessado_em: str = Field(default_factory=lambda: datetime.now().isoformat())
    acessado_por_user_id: Optional[int] = Field(default=None, index=True)
    motivo: str = Field(max_length=500)
    ip: Optional[str] = Field(default=None, max_length=64)


class AlertaDB(SQLModel, table=True):
    """
    Histórico de alertas gerados pelo motor.
    FK → empresas.id
    Permite: "mostre todos os alertas CRITICO dos últimos 30 dias"
    """
    __tablename__ = "alertas"

    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresas.id", index=True)
    competencia: str = Field(max_length=7)  # "2026-01" ISO 8601

    nivel: str = Field(max_length=10)   # CRITICO, ALTO, MEDIO, INFO
    codigo: str = Field(max_length=50)  # RBT12_PROXIMO_TETO, FATOR_R_ZONA_RISCO, etc.
    mensagem: str = Field(sa_column=Column(TEXT, nullable=False))

    # ERR-011: ciclo de vida do alerta (auditoria fiscal)
    status: str = Field(default="ABERTO", max_length=10)  # StatusAlerta
    resolvido_em: Optional[str] = Field(default=None)      # ISO 8601 datetime
    resolvido_por: Optional[str] = Field(default=None, max_length=100)
    acao_tomada: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))

    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# ─────────────────────────────────────────────────────────────────────────────
# CRUD — Operações de banco
# ─────────────────────────────────────────────────────────────────────────────

def salvar_empresa(empresa_domain: Any) -> EmpresaDB:
    """
    Salva ou atualiza empresa no banco.
    Se CNPJ já existe, atualiza dados. Se não, insere.
    """
    with get_session() as session:
        existente = session.query(EmpresaDB).filter(
            EmpresaDB.cnpj == empresa_domain.cnpj
        ).first()

        try:
            if existente:
                existente.razao_social = empresa_domain.razao_social
                existente.regime = empresa_domain.regime
                existente.cnae_principal = empresa_domain.cnae_principal
                existente.uf_origem = empresa_domain.uf_origem
                existente.faturamento_12m = str(empresa_domain.faturamento_12m)
                existente.folha_salarios_12m = (
                    str(empresa_domain.folha_salarios_12m)
                    if empresa_domain.folha_salarios_12m is not None else None
                )
                existente.anexo_simples = empresa_domain.anexo_simples
                existente.updated_at = datetime.now().isoformat()
                session.add(existente)
                session.commit()
                session.refresh(existente)
                logger.info("Empresa atualizada | id=%s", existente.id)
                return existente
            else:
                nova = EmpresaDB.from_domain(empresa_domain)
                session.add(nova)
                session.commit()
                session.refresh(nova)
                logger.info("Empresa criada | id=%s", nova.id)
                return nova
        except IntegrityError as exc:
            session.rollback()
            logger.error("IntegrityError em salvar_empresa | cnpj=%s | %s", empresa_domain.cnpj, exc)
            raise RuntimeError(
                f"Conflito ao salvar empresa (CNPJ duplicado ou constraint violada): {exc.orig}"
            ) from exc
        except OperationalError as exc:
            session.rollback()
            logger.error("OperationalError em salvar_empresa | %s", exc)
            raise RuntimeError("Banco de dados indisponível — tente novamente.") from exc


def registrar_historico_empresa(
    empresa_id: int,
    campo_alterado: str,
    valor_novo: str,
    alterado_por: str,
    valor_anterior: Optional[str] = None,
    motivo: Optional[str] = None,
) -> EmpresaHistoricoDB:
    """
    Registra uma alteração em dado da empresa na tabela de histórico.
    Exigência: CTN Art. 180 — rastreabilidade de alterações contábeis.

    Deve ser chamado ANTES de cada salvar_empresa() que altere campos fiscais,
    passando o valor anterior (se conhecido) e o novo valor.

    Args:
        empresa_id: ID da empresa no banco
        campo_alterado: Nome do campo alterado (ex: "faturamento_12m", "regime")
        valor_novo: Novo valor como string
        alterado_por: Username do operador responsável
        valor_anterior: Valor anterior como string (None se campo era inexistente)
        motivo: Contexto da alteração (ex: "Atualização via PGDAS-D 01/2026")

    Returns:
        EmpresaHistoricoDB persistido
    """
    registro = EmpresaHistoricoDB(
        empresa_id=empresa_id,
        campo_alterado=campo_alterado,
        valor_anterior=valor_anterior,
        valor_novo=valor_novo,
        alterado_por=alterado_por,
        motivo=motivo,
    )
    with get_session() as session:
        try:
            session.add(registro)
            session.commit()
            session.refresh(registro)
            logger.info(
                "Histórico registrado | empresa_id=%s | campo=%s | por=%s",
                empresa_id, campo_alterado, alterado_por,
            )
            return registro
        except (IntegrityError, OperationalError) as exc:
            session.rollback()
            logger.error(
                "Erro ao registrar histórico | empresa_id=%s | campo=%s | %s",
                empresa_id, campo_alterado, exc,
            )
            raise RuntimeError(
                f"Falha ao registrar histórico de alteração (empresa_id={empresa_id}, campo={campo_alterado})."
            ) from exc


def buscar_historico_empresa(empresa_id: int) -> List[EmpresaHistoricoDB]:
    """
    Lista todo o histórico de alterações de uma empresa, ordem cronológica inversa.
    CTN Art. 180 — permite auditoria de mudanças fiscais.
    """
    with get_session() as session:
        return list(
            session.query(EmpresaHistoricoDB)
            .filter(EmpresaHistoricoDB.empresa_id == empresa_id)
            .order_by(EmpresaHistoricoDB.alterado_em.desc())
            .all()
        )


def buscar_empresa_por_cnpj(cnpj: str) -> Optional[EmpresaDB]:
    """Busca empresa por CNPJ. Retorna None se não encontrar."""
    with get_session() as session:
        return session.query(EmpresaDB).filter(EmpresaDB.cnpj == cnpj).first()


def listar_empresas() -> List[EmpresaDB]:
    """Lista todas as empresas cadastradas."""
    with get_session() as session:
        return list(session.query(EmpresaDB).all())


def salvar_diagnostico(
    empresa_id: int,
    competencia: str,
    resultado: Dict[str, Any],
    das_mensal: Decimal,
    aliquota_efetiva: Decimal,
    rbt12: Decimal,
    regime: str,
    das_ecac: Optional[Decimal] = None,
) -> DiagnosticoDB:
    """Salva diagnóstico do motor no banco."""
    competencia = validar_competencia(competencia)

    try:
        RegimeTributario(regime)
    except ValueError:
        raise ValueError(
            f"Regime '{regime}' invalido. "
            f"Valores aceitos: {[e.value for e in RegimeTributario]}"
        )

    delta = None
    status = None
    if das_ecac is not None:
        delta = abs(das_ecac - das_mensal)
        # Aprovado se delta ≤ 1% do DAS e-CAC
        status = "APROVADO" if delta <= das_ecac * Decimal("0.01") else "PENDENTE"
        StatusAuditoria(status)  # Valida — levanta ValueError se inválido

    diag = DiagnosticoDB(
        empresa_id=empresa_id,
        competencia=competencia,
        resultado_json=json.dumps(resultado, default=str),
        das_mensal=str(das_mensal),
        aliquota_efetiva=str(aliquota_efetiva),
        rbt12_usado=str(rbt12),
        regime_no_calculo=regime,
        das_ecac_referencia=str(das_ecac) if das_ecac else None,
        delta=str(delta) if delta else None,
        status_auditoria=status,
    )

    with get_session() as session:
        try:
            session.add(diag)
            session.commit()
            session.refresh(diag)
            logger.info("Diagnóstico salvo | empresa_id=%s | competencia=%s", empresa_id, competencia)
            return diag
        except IntegrityError as exc:
            session.rollback()
            logger.error(
                "IntegrityError em salvar_diagnostico | empresa_id=%s | competencia=%s | %s",
                empresa_id, competencia, exc,
            )
            raise RuntimeError(
                f"Diagnóstico duplicado para empresa_id={empresa_id} competencia={competencia}. "
                "Use a competência correta ou atualize o diagnóstico existente."
            ) from exc
        except OperationalError as exc:
            session.rollback()
            logger.error("OperationalError em salvar_diagnostico | %s", exc)
            raise RuntimeError("Banco de dados indisponível — tente novamente.") from exc


def salvar_alertas(empresa_id: int, competencia: str, alertas: List[Dict[str, str]]) -> None:
    """Salva lista de alertas no banco. Valida nivel contra NivelAlerta."""
    competencia = validar_competencia(competencia)
    with get_session() as session:
        for alerta in alertas:
            nivel_str = alerta.get("nivel", "INFO")
            try:
                NivelAlerta(nivel_str)
            except ValueError:
                raise ValueError(
                    f"Nivel de alerta invalido: '{nivel_str}'. "
                    f"Valores aceitos: {[e.value for e in NivelAlerta]}"
                )
            db_alerta = AlertaDB(
                empresa_id=empresa_id,
                competencia=competencia,
                nivel=nivel_str,
                codigo=alerta.get("codigo", "DESCONHECIDO"),
                mensagem=alerta.get("mensagem", ""),
                status="ABERTO",
            )
            session.add(db_alerta)
        try:
            session.commit()
            logger.info("Alertas salvos | empresa_id=%s | qtd=%d", empresa_id, len(alertas))
        except IntegrityError as exc:
            session.rollback()
            logger.error("IntegrityError em salvar_alertas | empresa_id=%s | %s", empresa_id, exc)
            raise RuntimeError(
                f"Conflito ao salvar alertas para empresa_id={empresa_id}: {exc.orig}"
            ) from exc
        except OperationalError as exc:
            session.rollback()
            logger.error("OperationalError em salvar_alertas | %s", exc)
            raise RuntimeError("Banco de dados indisponível — tente novamente.") from exc


def buscar_diagnosticos_por_empresa(empresa_id: int) -> List[DiagnosticoDB]:
    """Lista diagnósticos de uma empresa, ordenados por data."""
    with get_session() as session:
        return list(
            session.query(DiagnosticoDB)
            .filter(DiagnosticoDB.empresa_id == empresa_id)
            .order_by(DiagnosticoDB.created_at.desc())
            .all()
        )


def buscar_alertas_por_nivel(nivel: str) -> List[AlertaDB]:
    """Busca alertas por nível (CRITICO, ALTO, MEDIO, INFO)."""
    with get_session() as session:
        return list(
            session.query(AlertaDB)
            .filter(AlertaDB.nivel == nivel)
            .order_by(AlertaDB.created_at.desc())
            .all()
        )


def resolver_alerta(
    alerta_id: int,
    resolvido_por: str,
    acao_tomada: str,
    status: str = "RESOLVIDO",
) -> Optional["AlertaDB"]:
    """
    Resolve um alerta com rastreabilidade completa.
    Registra: quem resolveu, quando, e qual ação foi tomada.
    Exigência fiscal: alerta sem resolução documentada = passivo.

    Args:
        alerta_id: ID do alerta a resolver
        resolvido_por: Nome de quem resolveu (ex: "Luiz Moreira")
        acao_tomada: Descrição da ação (ex: "Ajustado RBT12 no PGDAS-D")
        status: RESOLVIDO ou IGNORADO (validado contra StatusAlerta)

    Returns:
        AlertaDB atualizado ou None se não encontrado.
    """
    try:
        StatusAlerta(status)
    except ValueError:
        raise ValueError(
            f"Status '{status}' invalido. "
            f"Valores aceitos: {[e.value for e in StatusAlerta]}"
        )

    if not resolvido_por or not resolvido_por.strip():
        raise ValueError("resolvido_por e obrigatorio (quem resolveu o alerta).")
    if not acao_tomada or not acao_tomada.strip():
        raise ValueError("acao_tomada e obrigatoria (o que foi feito para resolver).")

    with get_session() as session:
        alerta = session.query(AlertaDB).filter(AlertaDB.id == alerta_id).first()
        if not alerta:
            return None

        alerta.status = status
        alerta.resolvido_em = datetime.now().isoformat()
        alerta.resolvido_por = resolvido_por.strip()
        alerta.acao_tomada = acao_tomada.strip()
        try:
            session.add(alerta)
            session.commit()
            session.refresh(alerta)
            logger.info(
                "Alerta resolvido | id=%s | por=%s | status=%s",
                alerta_id, resolvido_por, status,
            )
            return alerta
        except (IntegrityError, OperationalError) as exc:
            session.rollback()
            logger.error("Erro ao resolver alerta | id=%s | %s", alerta_id, exc)
            raise RuntimeError(f"Falha ao persistir resolução do alerta id={alerta_id}.") from exc


# ─────────────────────────────────────────────────────────────────────────────
# AUDITORIA DOCUMENTAL — Tabela auditoria_documentos
# Bloqueia o vetor "dado errado culpa do contador" + LGPD Art. 16/37/46
# ─────────────────────────────────────────────────────────────────────────────

def registrar_documento_auditoria(
    hash_sha256: str,
    empresa_cnpj: str,
    nome_original: str,
    tamanho_bytes: int,
    storage_path: str,
    mime_type: str = "application/pdf",
    paginas: Optional[int] = None,
    uploaded_by_user_id: Optional[int] = None,
    diagnostico_id: Optional[int] = None,
) -> AuditoriaDocumentoDB:
    """
    Persiste o registro de um documento submetido pelo cliente.

    O conteúdo cifrado já deve estar em disco — esta função só grava os
    metadados que apontam pra ele. Se o hash já existe (mesmo arquivo
    re-enviado), retorna o registro existente atualizando opcionalmente
    o diagnostico_id (vinculando a uma nova análise).

    Args:
        hash_sha256: SHA-256 hex do plaintext (vem de storage_cifrado.hash_documento)
        empresa_cnpj: CNPJ do cliente (já normalizado/validado upstream)
        nome_original: nome do arquivo enviado (sem path)
        tamanho_bytes: tamanho do plaintext
        storage_path: caminho relativo retornado por cifrar_e_persistir
        mime_type: default "application/pdf"
        paginas: opcional, n° de páginas (extraído via PyPDF2 se disponível)
        uploaded_by_user_id: id do operador autenticado
        diagnostico_id: análise que vai usar este doc (pode vincular depois)

    Returns:
        AuditoriaDocumentoDB persistido (novo ou existente atualizado).
    """
    if not hash_sha256 or len(hash_sha256) != 64:
        raise ValueError(f"hash_sha256 invalido: '{hash_sha256}' (esperado 64 chars hex)")
    if not empresa_cnpj or not nome_original:
        raise ValueError("empresa_cnpj e nome_original sao obrigatorios")
    if tamanho_bytes <= 0:
        raise ValueError(f"tamanho_bytes invalido: {tamanho_bytes}")

    with get_session() as session:
        existente = session.query(AuditoriaDocumentoDB).filter(
            AuditoriaDocumentoDB.hash_sha256 == hash_sha256
        ).first()

        if existente:
            # Re-upload do mesmo arquivo: vincula novo diagnóstico se fornecido
            if diagnostico_id and existente.diagnostico_id != diagnostico_id:
                existente.diagnostico_id = diagnostico_id
                session.add(existente)
                session.commit()
                session.refresh(existente)
            logger.info(
                "Documento ja registrado | id=%s | hash=%s...",
                existente.id, hash_sha256[:16],
            )
            return existente

        novo = AuditoriaDocumentoDB(
            hash_sha256=hash_sha256,
            empresa_cnpj=empresa_cnpj,
            nome_original=nome_original,
            mime_type=mime_type,
            tamanho_bytes=tamanho_bytes,
            paginas=paginas,
            storage_path=storage_path,
            uploaded_by_user_id=uploaded_by_user_id,
            diagnostico_id=diagnostico_id,
        )
        try:
            session.add(novo)
            session.commit()
            session.refresh(novo)
            logger.info(
                "Documento auditoria registrado | id=%s | hash=%s... | bytes=%d",
                novo.id, hash_sha256[:16], tamanho_bytes,
            )
            return novo
        except IntegrityError as exc:
            session.rollback()
            logger.error("IntegrityError em registrar_documento_auditoria | %s", exc)
            raise RuntimeError(f"Falha ao registrar documento de auditoria: {exc.orig}") from exc


def aceitar_documento(
    documento_id: int,
    aceito_por_user_id: int,
    aceito_ip: Optional[str] = None,
) -> Optional[AuditoriaDocumentoDB]:
    """
    Marca o termo de aceite digital — operador confirma que aquele é o
    documento oficial a ser analisado. Sem aceite, o doc não deve ser
    usado em diagnóstico (verificação fica a cargo do caller).

    Args:
        documento_id: ID retornado por registrar_documento_auditoria
        aceito_por_user_id: id do operador que clicou "aceito"
        aceito_ip: IP de origem (auditoria forense)

    Returns:
        Registro atualizado, ou None se não encontrado.
    """
    with get_session() as session:
        doc = session.query(AuditoriaDocumentoDB).filter(
            AuditoriaDocumentoDB.id == documento_id
        ).first()
        if not doc:
            return None
        doc.aceito_em = datetime.now().isoformat()
        doc.aceito_por_user_id = aceito_por_user_id
        doc.aceito_ip = aceito_ip
        session.add(doc)
        session.commit()
        session.refresh(doc)
        logger.info(
            "Termo de aceite registrado | doc_id=%s | user_id=%s",
            documento_id, aceito_por_user_id,
        )
        return doc


def buscar_documentos_por_cnpj(empresa_cnpj: str) -> List[AuditoriaDocumentoDB]:
    """Lista todos os docs de auditoria de um cliente, mais recentes primeiro."""
    with get_session() as session:
        return list(
            session.query(AuditoriaDocumentoDB)
            .filter(AuditoriaDocumentoDB.empresa_cnpj == empresa_cnpj)
            .filter(AuditoriaDocumentoDB.purged_at.is_(None))  # type: ignore[union-attr]
            .order_by(AuditoriaDocumentoDB.uploaded_at.desc())
            .all()
        )


def buscar_documentos_por_diagnostico(diagnostico_id: int) -> List[AuditoriaDocumentoDB]:
    """Lista os docs vinculados a uma análise específica."""
    with get_session() as session:
        return list(
            session.query(AuditoriaDocumentoDB)
            .filter(AuditoriaDocumentoDB.diagnostico_id == diagnostico_id)
            .filter(AuditoriaDocumentoDB.purged_at.is_(None))  # type: ignore[union-attr]
            .order_by(AuditoriaDocumentoDB.uploaded_at.asc())
            .all()
        )


def buscar_documento_por_hash(hash_sha256: str) -> Optional[AuditoriaDocumentoDB]:
    """Busca documento por hash SHA-256 (ID canônico)."""
    with get_session() as session:
        return session.query(AuditoriaDocumentoDB).filter(
            AuditoriaDocumentoDB.hash_sha256 == hash_sha256
        ).first()


def registrar_acesso_documento(
    documento_id: int,
    motivo: str,
    acessado_por_user_id: Optional[int] = None,
    ip: Optional[str] = None,
) -> AuditoriaAcessoDB:
    """
    LGPD Art. 37 — registra cada acesso a documento original cifrado.

    Deve ser chamado ANTES de toda decifragem em produção. Em testes
    pode ser omitido. O log fica permanentemente no banco — não há
    deleção mesmo após purge do documento.
    """
    if not motivo or not motivo.strip():
        raise ValueError("motivo do acesso e obrigatorio (LGPD Art. 37)")

    log = AuditoriaAcessoDB(
        documento_id=documento_id,
        acessado_por_user_id=acessado_por_user_id,
        motivo=motivo.strip()[:500],
        ip=ip,
    )
    with get_session() as session:
        session.add(log)
        session.commit()
        session.refresh(log)
        logger.info(
            "Acesso a documento registrado | doc_id=%s | user_id=%s",
            documento_id, acessado_por_user_id,
        )
        return log


def listar_documentos_purgaveis(referencia: Optional[datetime] = None) -> List[AuditoriaDocumentoDB]:
    """
    Lista documentos cujo purge_after já passou e ainda não foram purgados.
    Útil para cron diário de limpeza LGPD.
    """
    ref = (referencia or datetime.now()).isoformat()
    with get_session() as session:
        return list(
            session.query(AuditoriaDocumentoDB)
            .filter(AuditoriaDocumentoDB.purge_after <= ref)
            .filter(AuditoriaDocumentoDB.purged_at.is_(None))  # type: ignore[union-attr]
            .all()
        )


def marcar_documento_purgado(documento_id: int) -> Optional[AuditoriaDocumentoDB]:
    """
    Marca o registro como purgado APÓS storage_cifrado.purge() ter sido
    chamado com sucesso. Mantém o registro no banco (fato histórico) mas
    indica que o conteúdo cifrado em disco já não existe.
    """
    with get_session() as session:
        doc = session.query(AuditoriaDocumentoDB).filter(
            AuditoriaDocumentoDB.id == documento_id
        ).first()
        if not doc:
            return None
        doc.purged_at = datetime.now().isoformat()
        session.add(doc)
        session.commit()
        session.refresh(doc)
        logger.info("Documento marcado como purgado | id=%s", documento_id)
        return doc


# ─────────────────────────────────────────────────────────────────────────────
# LGPD — Purge de dados (Lei 13.709/2018, Art. 15)
# ─────────────────────────────────────────────────────────────────────────────

def _purge_empresa_legado(cnpj: str) -> bool:
    """
    DEPRECATED — Mantido para referência. NÃO USAR EM PRODUÇÃO.
    Viola CTN Art. 173 (retenção 5 anos). Ver ERR-012.
    Substituído por anonimizar_empresa().
    """
    with get_session() as session:
        empresa = session.query(EmpresaDB).filter(EmpresaDB.cnpj == cnpj).first()
        if not empresa:
            return False

        # Cascata manual (SQLite não garante CASCADE em todas as versões)
        session.query(AlertaDB).filter(AlertaDB.empresa_id == empresa.id).delete()
        session.query(DiagnosticoDB).filter(DiagnosticoDB.empresa_id == empresa.id).delete()
        session.query(AtividadeDB).filter(AtividadeDB.empresa_id == empresa.id).delete()
        session.delete(empresa)
        session.commit()

        logger.info("LGPD purge legado concluído | empresa_id=%s", empresa.id)
        return True


def anonimizar_empresa(cnpj: str) -> bool:
    """
    LGPD Art. 15 + CTN Art. 173 — Anonimização de PII com retenção fiscal.

    Preserva: valores fiscais (DAS, alíquotas, RBT12, diagnósticos).
    Anonimiza: CNPJ, razão social, dados identificáveis.
    Bloqueia: se prazo fiscal de 5 anos não expirou.

    STUB: lógica de prazo pendente da definição de Luiz Moreira (ERR-012).

    Returns:
        True se anonimizou, False se não encontrou.

    Raises:
        NotImplementedError: se prazo fiscal não puder ser verificado ainda.
    """
    raise NotImplementedError(
        "ERR-012: anonimizar_empresa() aguarda definição de Luiz Moreira "
        "sobre marco temporal do CTN Art. 173 (fato gerador vs criação do dado). "
        "NÃO deletar dados fiscais dentro do prazo de 5 anos."
    )


def purge_empresa(cnpj: str) -> bool:
    """
    Wrapper que direciona para _purge_empresa_legado() enquanto ERR-012 não é resolvido.

    AVISO: em produção, substituir por anonimizar_empresa() após Luiz Moreira
    definir o marco temporal do CTN Art. 173.
    """
    return _purge_empresa_legado(cnpj)


# ─────────────────────────────────────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    criar_tabelas()
    print("Banco criado com sucesso: motor_tributario.db")
    print("Tabelas: empresas, atividades, diagnosticos, alertas")
