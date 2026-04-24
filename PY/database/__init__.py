"""
database.py — Fachada (Facade) para o novo sistema modular de banco de dados.
Refatorado em 14/04/2026 para decompor o monólito de 48KB.
"""

# 1. Configuração e Conexão
from .connection import (
    engine,
    get_session,
    criar_tabelas,
    DATABASE_URL
)

# 2. Enums
from .enums import (
    RegimeTributario,
    NivelAlerta,
    StatusAlerta,
    StatusAuditoria
)

# 3. Modelos (SQLModel)
from .models import (
    EmpresaDB,
    AtividadeDB,
    DiagnosticoDB,
    EmpresaHistoricoDB,
    AuditoriaDocumentoDB,
    AuditoriaAcessoDB,
    AlertaDB,
    AuditoriaTentativaAcessoDB
)

# 4. Repositórios (CRUD)
from .repositories.empresa_repo import (
    salvar_empresa,
    buscar_empresa_por_cnpj,
    listar_empresas,
    registrar_historico_empresa,
    buscar_historico_empresa,
    purge_empresa
)

from .repositories.diagnostico_repo import (
    salvar_diagnostico,
    buscar_diagnosticos_por_empresa,
    listar_por_user as listar_diagnosticos_por_user,
    validar_competencia,
    tem_acesso_cnpj,
)

from .repositories.alerta_repo import (
    salvar_alertas,
    buscar_alertas_por_nivel,
    buscar_alertas_por_empresa,
    resolver_alerta
)

from .repositories.auditoria_repo import (
    registrar_documento_auditoria,
    buscar_documentos_por_cnpj,
    buscar_documento_por_hash,
    aceitar_documento,
    marcar_documento_purgado,
    registrar_acesso_documento,
    buscar_documentos_por_diagnostico,
    listar_documentos_purgaveis
)

# 5. Serviços (Agregações)
from .services.dashboard_service import get_dashboard_metrics

# Garantir que __all__ esteja definido para facilitar limpezas futuras
__all__ = [
    "engine", "get_session", "criar_tabelas", "DATABASE_URL",
    "RegimeTributario", "NivelAlerta", "StatusAlerta", "StatusAuditoria",
    "EmpresaDB", "AtividadeDB", "DiagnosticoDB", "EmpresaHistoricoDB",
    "AuditoriaDocumentoDB", "AuditoriaAcessoDB", "AlertaDB",
    "AuditoriaTentativaAcessoDB",
    "salvar_empresa", "buscar_empresa_por_cnpj", "listar_empresas",
    "registrar_historico_empresa", "buscar_historico_empresa", "purge_empresa",
    "salvar_diagnostico", "buscar_diagnosticos_por_empresa",
    "listar_diagnosticos_por_user", "validar_competencia", "tem_acesso_cnpj",
    "salvar_alertas", "buscar_alertas_por_nivel", "buscar_alertas_por_empresa", "resolver_alerta",
    "registrar_documento_auditoria", "buscar_documentos_por_cnpj",
    "buscar_documento_por_hash", "aceitar_documento", "marcar_documento_purgado",
    "registrar_acesso_documento", "buscar_documentos_por_diagnostico", "listar_documentos_purgaveis",
    "get_dashboard_metrics"
]
