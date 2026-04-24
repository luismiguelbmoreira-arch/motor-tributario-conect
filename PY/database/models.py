import json
import re
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import field_validator
from sqlmodel import TEXT, Column, Field, SQLModel

from validadores import validar_cnae, validar_cnpj, validar_uf


class EmpresaDB(SQLModel, table=True):
    __tablename__ = "empresas"

    id: Optional[int] = Field(default=None, primary_key=True)
    cnpj: str = Field(index=True, unique=True, max_length=18)
    razao_social: str = Field(max_length=200)
    regime: str = Field(max_length=20)
    cnae_principal: str = Field(max_length=10)
    uf_origem: str = Field(max_length=2)

    faturamento_12m: str = Field(sa_column=Column(TEXT, nullable=False))
    folha_salarios_12m: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))
    anexo_simples: Optional[str] = Field(default=None, max_length=3)

    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    @field_validator("cnpj")
    @classmethod
    def validar_cnpj_rigido(cls, v: str) -> str:
        res = validar_cnpj(v)
        if not res.ok:
            raise ValueError(f"CNPJ Invalido: {', '.join(res.errors)}")
        return re.sub(r'[\s.\-/]', '', v.strip())

    @field_validator("uf_origem")
    @classmethod
    def validar_uf_rigido(cls, v: str) -> str:
        res = validar_uf(v)
        if not res.ok:
            raise ValueError(f"UF Invalida: {', '.join(res.errors)}")
        return v.strip().upper()

    @field_validator("cnae_principal")
    @classmethod
    def validar_cnae_rigido(cls, v: str) -> str:
        res = validar_cnae(v)
        if not res.ok:
            raise ValueError(f"CNAE Invalido: {', '.join(res.errors)}")
        return v.strip().replace('.', '').replace('-', '')

    @classmethod
    def from_domain(cls, domain: Any) -> "EmpresaDB":
        return cls(
            cnpj=domain.cnpj,
            razao_social=domain.razao_social,
            regime=domain.regime,
            cnae_principal=domain.cnae_principal,
            uf_origem=domain.uf_origem,
            faturamento_12m=str(domain.faturamento_12m),
            folha_salarios_12m=str(domain.folha_salarios_12m) if domain.folha_salarios_12m is not None else None,
            anexo_simples=domain.anexo_simples
        )

class AtividadeDB(SQLModel, table=True):
    __tablename__ = "atividades"
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresas.id", index=True)
    cnae: str = Field(max_length=10)
    descricao: str = Field(max_length=200)
    principal: bool = Field(default=False)

class DiagnosticoDB(SQLModel, table=True):
    __tablename__ = "diagnosticos"

    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresas.id", index=True)
    competencia: str = Field(max_length=7)  # YYYY-MM

    resultado_json: str = Field(sa_column=Column(TEXT, nullable=False))

    das_mensal: str = Field(sa_column=Column(TEXT, nullable=False))
    aliquota_efetiva: str = Field(sa_column=Column(TEXT, nullable=False))
    rbt12_usado: str = Field(sa_column=Column(TEXT, nullable=False))

    regime_no_calculo: str = Field(max_length=20)
    das_ecac_referencia: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))
    delta: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))
    status_auditoria: Optional[str] = Field(default=None, max_length=20)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    # ERR-050 (Fase 5): ownership para o endpoint GET /auditorias do histórico.
    # Nullable — registros pré-Fase 5 não têm dono conhecido e ficarão fora
    # da listagem filtrada por user_id. Novos inserts sempre populam.
    # LGPD Art. 6º V (minimização) + Art. 46 (segurança) — user A jamais vê
    # diagnósticos de user B pelo endpoint público.
    uploaded_by_user_id: Optional[int] = Field(
        default=None,
        foreign_key="users.id",
        index=True,
    )

    def get_resultado(self) -> Dict[str, Any]:
        return json.loads(self.resultado_json)

class EmpresaHistoricoDB(SQLModel, table=True):
    __tablename__ = "empresa_historico"
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresas.id", index=True)
    campo_alterado: str = Field(max_length=50)
    valor_anterior: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))
    valor_novo: str = Field(sa_column=Column(TEXT, nullable=False))
    alterado_por: str = Field(max_length=100)
    alterado_em: str = Field(default_factory=lambda: datetime.now().isoformat())
    motivo: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))

class AuditoriaDocumentoDB(SQLModel, table=True):
    __tablename__ = "auditoria_documentos"
    id: Optional[int] = Field(default=None, primary_key=True)
    hash_sha256: str = Field(unique=True, index=True, max_length=64)
    empresa_cnpj: str = Field(index=True, max_length=18)
    nome_original: str = Field(max_length=255)
    mime_type: str = Field(default="application/pdf", max_length=64)
    tamanho_bytes: int
    paginas: Optional[int] = Field(default=None)
    storage_path: str = Field(max_length=500)
    uploaded_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    uploaded_by_user_id: Optional[int] = Field(default=None, index=True)
    aceito_em: Optional[str] = Field(default=None)
    aceito_por_user_id: Optional[int] = Field(default=None, index=True)
    aceito_ip: Optional[str] = Field(default=None, max_length=64)
    diagnostico_id: Optional[int] = Field(default=None, index=True)
    purge_after: str = Field(
        default_factory=lambda: (
            datetime.now().replace(year=datetime.now().year + 5).isoformat()
        )
    )
    purged_at: Optional[str] = Field(default=None)

class AuditoriaAcessoDB(SQLModel, table=True):
    __tablename__ = "auditoria_acessos"
    id: Optional[int] = Field(default=None, primary_key=True)
    documento_id: int = Field(foreign_key="auditoria_documentos.id", index=True)
    acessado_em: str = Field(default_factory=lambda: datetime.now().isoformat())
    acessado_por_user_id: Optional[int] = Field(default=None, index=True)
    motivo: str = Field(max_length=500)
    ip: Optional[str] = Field(default=None, max_length=64)

class AlertaDB(SQLModel, table=True):
    __tablename__ = "alertas"
    id: Optional[int] = Field(default=None, primary_key=True)
    empresa_id: int = Field(foreign_key="empresas.id", index=True)
    competencia: str = Field(max_length=7)
    nivel: str = Field(max_length=10)
    codigo: str = Field(max_length=50)
    mensagem: str = Field(sa_column=Column(TEXT, nullable=False))
    status: str = Field(default="ABERTO", max_length=10)
    resolvido_em: Optional[str] = Field(default=None)
    resolvido_por: Optional[str] = Field(default=None, max_length=100)
    acao_tomada: Optional[str] = Field(default=None, sa_column=Column(TEXT, nullable=True))
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class AuditoriaTentativaAcessoDB(SQLModel, table=True):
    """
    Tabela de auditoria de tentativas de acesso cruzado (IDOR horizontal).

    Registra toda vez que um `user_id_tentando` foi bloqueado ao tentar
    acessar um recurso (sessão de análise, integração externa, etc.)
    cujo dono é outro usuário. Diferente de `AuditoriaAcessoDB`, que
    registra ACESSOS LEGÍTIMOS a documentos cifrados, esta tabela
    registra INCIDENTES DE SEGURANÇA (tentativas bloqueadas).

    Amparo:
      - LGPD Art. 7º VI — IP armazenado em cleartext (legítimo interesse,
        segurança da informação — não é dado pessoal sensível por si só).
      - LGPD Art. 37 — registro de operações de tratamento.
      - LGPD Art. 46 §1º — obrigação de medidas de segurança.
      - LGPD Art. 48 — evidência em caso de incidente reportável à ANPD
        (72h); a tabela é a base de prova.
      - CTN Art. 195 — retenção mínima de 5 anos alinhada à obrigação
        fiscal de conservação de documentos (consistente com
        `auditoria_documentos`).

    Consumidores previstos:
      - Fase 4.1 — `/analise/sessao/{id}` (ERR-018.a já corrigido; aqui
        apenas persiste o registro da tentativa para prova).
      - Fase 5 — `/integracoes/ecac/sync`, `sieg_sincronizar`,
        `integra_sincronizar`, dossiê de prova (ERR-018.b pendente).
    """

    __tablename__ = "auditoria_tentativas_acesso"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Prefixo de 8 chars do id do recurso tentado (analise_id hex, etc.).
    # Não armazenamos o id completo para não recriar o vetor de IDOR via
    # dump da tabela — o prefixo é suficiente para correlação em incidente.
    analise_id_prefix: str = Field(max_length=8, index=True)

    # User que tentou o acesso (sempre existe — o endpoint é autenticado).
    user_id_tentando: int = Field(foreign_key="users.id", index=True)

    # User dono do recurso. Pode ser None apenas em endpoints futuros onde
    # o id existe mas está desvinculado de um dono identificável. No uso
    # atual (/analise/sessao), um mismatch sempre tem dono != tentando.
    user_id_dono: Optional[int] = Field(default=None, foreign_key="users.id")

    # IP de origem em cleartext (LGPD Art. 7º VI — legítimo interesse).
    # IPv6 tem no máximo 39 chars (ex: ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff);
    # 45 cobre IPv6-mapped-IPv4 (::ffff:192.168.0.1 = 45).
    ip: str = Field(max_length=45)

    tentado_em: datetime = Field(default_factory=datetime.utcnow, index=True)

    # Endpoint que disparou a tentativa (ex: "/analise/sessao",
    # "/integracoes/ecac/sync"). Usado para correlação e relatório.
    endpoint: str = Field(max_length=255, index=True)
