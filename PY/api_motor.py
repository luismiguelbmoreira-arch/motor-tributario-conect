# -*- coding: utf-8 -*-
"""
api_motor.py — FastAPI HTTP Wrapper do Motor Tributário Conect 2026-2033
Projeto: Motor Tributário Conect — Escritório Contábil Conect, Sorocaba, SP

ENDPOINTS:
  GET  /health                          → status + contagem de testes
  POST /auditar                         → audita uma empresa (pasta com PDFs)
  POST /auditar/batch                   → audita todas as empresas de uma pasta base
  POST /auth/login                      → autentica e retorna JWT
  GET  /auth/me                         → dados do usuário logado
  POST /admin/usuarios                  → criar usuário (admin)
  GET  /admin/usuarios                  → listar usuários (admin)
  POST /admin/usuarios/{id}/desativar   → desativar usuário (admin)
  POST /analise/manual                  → cálculo direto sem PDF (autenticado)
  POST /analise/pdf                     → upload PDFs e-CAC → extração → diagnóstico (autenticado)
  POST /relatorio/pdf                   → gera PDF do diagnóstico via weasyprint (autenticado)

USO:
  cd PY && uvicorn api_motor:app --reload --port 8000

LGPD:
  Nenhum dado persiste. purge() já chamado dentro de auditar_empresa().
  Logs sem CNPJ ou razão social.
  /analise/manual NÃO chama purge — dados permanecem para leitura do resultado.

DÉCIMAL:
  Todos os campos monetários são Decimal internamente.
  Serializados como strings no JSON (json_encoders) — sem perda de precisão.
"""

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# Adiciona PY/ ao path para imports relativos
sys.path.insert(0, str(Path(__file__).parent))

from audit_universal import auditar_empresa
from auth import (
    autenticar_usuario,
    criar_admin_default,
    criar_tabela_users,
    criar_usuario,
    desativar_usuario,
    gerar_token_jwt,
    listar_usuarios,
    renovar_token_jwt,
    resetar_senha,
    trocar_senha_proprio,
    verificar_token,
)
from motor_tributario import (
    EmpresaCompradora,
    EmpresaFornecedora,
    MotorReformaTributaria,
    OperacaoFiscal,
)

# relatorio_pdf importado lazy no endpoint — evita crash de startup se GTK ausente (Windows)
try:
    from relatorio_pdf import gerar_pdf as _gerar_pdf
    _RELATORIO_DISPONIVEL = True
except Exception:
    _gerar_pdf = None  # type: ignore
    _RELATORIO_DISPONIVEL = False


# ─────────────────────────────────────────────────────────────────────────────
# LOGGING ESTRUTURADO — JSON em produção, texto em dev
# ─────────────────────────────────────────────────────────────────────────────

class _JSONFormatter(logging.Formatter):
    """Formatter que emite cada log como uma linha JSON — adequado para ingestão por Datadog, Loki, etc."""
    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(log_obj, ensure_ascii=False)


def _setup_logging() -> None:
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_format = os.environ.get("LOG_FORMAT", "text")
    handler = logging.StreamHandler(sys.stdout)
    if log_format == "json":
        handler.setFormatter(_JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()
    root.addHandler(handler)


_setup_logging()
logger = logging.getLogger("motor_conect.api")

TOTAL_TESTES = 245  # atualizar após cada fase de testes


# ─────────────────────────────────────────────────────────────────────────────
# SECURITY — HTTPBearer + helpers de dependency injection
# ─────────────────────────────────────────────────────────────────────────────

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Dependency FastAPI: extrai e valida o Bearer token JWT.
    Lança HTTPException 401 se token inválido ou expirado.
    """
    return verificar_token(credentials.credentials)


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency FastAPI: exige role == "admin".
    Lança HTTPException 403 se usuário não for administrador.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Acesso restrito a administradores.",
        )
    return current_user


# ─────────────────────────────────────────────────────────────────────────────
# MODELOS DE REQUEST — Auditoria (existentes)
# ─────────────────────────────────────────────────────────────────────────────

class AuditarRequest(BaseModel):
    pasta_empresa: str = Field(
        ...,
        description="Caminho para pasta com PDFs da empresa",
        examples=["../samples/doc_calculo/CANAVEZI"],
    )


class AuditarBatchRequest(BaseModel):
    pasta_base: str = Field(
        ...,
        description="Pasta base contendo subpastas de empresas",
        examples=["../samples/doc_calculo"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# MODELOS DE REQUEST — Autenticação e administração
# ─────────────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Credenciais para autenticação via username + senha."""
    username: str
    password: str


class CriarUsuarioRequest(BaseModel):
    """Dados necessários para criar novo usuário no sistema."""
    username: str
    email: str
    password: str
    role: Literal["admin", "usuario"] = "usuario"


# ─────────────────────────────────────────────────────────────────────────────
# MODELOS DE REQUEST — Análise manual (sem PDF)
# ─────────────────────────────────────────────────────────────────────────────

class AnaliseManualRequest(BaseModel):
    """
    Payload para cálculo tributário direto — sem extração de PDF.
    Todos os campos espelham EmpresaFornecedora + EmpresaCompradora + OperacaoFiscal.
    Decimal serializado como string para zero perda de precisão.
    """
    model_config = ConfigDict(json_encoders={Decimal: str})

    # ── EmpresaFornecedora ────────────────────────────────────────────────────
    cnpj: str = Field(..., description="CNPJ com ou sem pontuação")
    razao_social: str = Field(..., min_length=2, description="Razão social completa")
    regime: Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI"] = Field(
        ..., description="Regime tributário"
    )
    cnae_principal: str = Field(..., description="CNAE principal (7 dígitos)")
    uf_origem: str = Field(..., description="UF de origem (2 letras)")
    faturamento_12m: Decimal = Field(..., ge=Decimal("0"), description="RBT12 em R$")
    folha_salarios_12m: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description="Folha de salários 12 meses (Fator R)"
    )
    anexo_simples: Optional[Literal["I", "II", "III", "IV", "V"]] = Field(
        default=None, description="Anexo Simples (auto-detectado se None)"
    )

    # ── EmpresaCompradora ─────────────────────────────────────────────────────
    tipo_comprador: Literal["B2B_CONTRIBUINTE", "B2C_CONSUMIDOR_FINAL", "MISTO"] = Field(
        ..., description="Tipo do comprador (MISTO = atende B2B e B2C)"
    )
    percentual_b2b: Decimal = Field(
        default=Decimal("100"), ge=Decimal("0"), le=Decimal("100"),
        description="% da receita B2B (0-100). Usado quando tipo=MISTO."
    )
    regime_comprador: str = Field(
        default="NAO_INFORMADO", description="Regime tributário do comprador"
    )
    uf_destino: str = Field(default="SP", description="UF de destino (2 letras; padrão: SP)")

    # ── OperacaoFiscal ────────────────────────────────────────────────────────
    data_emissao: str = Field(
        ..., description="Data de emissão ISO (YYYY-MM-DD) — deve estar em 2026-2033"
    )
    valor_operacao: Decimal = Field(..., gt=Decimal("0"), description="Valor da operação em R$")
    ncm_nbs: str = Field(default="00000000", description="NCM/NBS (8 dígitos; padrão: 00000000)")
    forma_recebimento: Literal["DINHEIRO", "PIX_BOLETO", "CARTAO"] = Field(
        default="PIX_BOLETO", description="Forma de recebimento (impacta Split Payment)"
    )
    rpa_mensal: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description=(
            "Receita do Período de Apuração do mês corrente. "
            "LC 123/2006, Art. 18, §1º."
        )
    )
    tinha_st_icms: bool = Field(
        default=False, description="Empresa possuía Substituição Tributária de ICMS"
    )
    reducao_cbs_ibs: Literal["INTEGRAL", "REDUCAO_30", "REDUCAO_60", "ISENTO"] = Field(
        default="INTEGRAL",
        description="Nível de redução CBS/IBS (LC 214/2025, Arts. 258-270)"
    )
    beneficio_fiscal_antigo: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"),
        description="Isenção/benefício ICMS eliminado até 2032"
    )

    # ── Empresa nova (< 12 meses) ──────────────────────────────────────────
    data_inicio_atividade: Optional[str] = Field(
        default=None,
        description="Data de início de atividade (YYYY-MM-DD). Se < 12 meses, RBT12 proporcionalizada."
    )

    # ── MEI (visível apenas quando regime == "MEI") ──────────────────────────
    categoria_mei: Optional[Literal["COMERCIO", "INDUSTRIA", "SERVICOS", "COMERCIO_SERVICOS"]] = Field(
        default=None,
        description="Categoria MEI (obrigatório se regime=MEI). Default backend: SERVICOS"
    )

    # ── Lucro Real (visível apenas quando regime == "REAL") ──────────────────
    lucro_real_mensal: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description="Lucro Real apurado no mês (R$). Se None, usa receita mensal como proxy."
    )
    creditos_pis_cofins: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"),
        description="Créditos PIS/COFINS não-cumulativo (R$). Padrão: 0"
    )


# ─────────────────────────────────────────────────────────────────────────────
# MODELOS DE RESPONSE — Auditoria (existentes)
# ─────────────────────────────────────────────────────────────────────────────

class AuditResult(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: str})

    empresa: str
    das_motor: Decimal
    das_ecac: Decimal
    delta: Decimal
    delta_pct: Decimal           # Decimal end-to-end — nunca float
    status: Literal["APROVADO", "REVISAR"]
    anexo: str                   # "I"–"V" ou "MULTI" para multi-atividade
    rbt12: Decimal
    ae: Decimal
    confianca_extracao: float    # 0.0–1.0 — metadado, não valor monetário
    campos_ausentes: list[str]


class HealthResponse(BaseModel):
    status: str
    testes: int
    versao: str


class BatchResult(BaseModel):
    model_config = ConfigDict(json_encoders={Decimal: str})

    total: int
    aprovados: int
    revisao: int
    erros_extracao: int
    resultados: list[AuditResult]
    erros: list[dict]            # {"empresa": str, "erro": str} — falhas individuais


# ─────────────────────────────────────────────────────────────────────────────
# MODELOS DE RESPONSE — Autenticação e administração
# ─────────────────────────────────────────────────────────────────────────────

class LoginResponse(BaseModel):
    """Resposta do login com token JWT e dados básicos do usuário."""
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str
    must_change_password: bool = False  # True = redirecionar para troca de senha


class UsuarioResponse(BaseModel):
    """Dados públicos de um usuário — sem hashed_password."""
    id: int
    username: str
    email: str
    role: str
    ativo: bool
    created_at: str
    ultimo_acesso: Optional[str]


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────────────────────────────────────

def _serializar_decimal(obj: Any) -> Any:
    """
    Serializa recursivamente Decimal para str em dicts/listas.
    Garante zero perda de precisão ao converter diagnóstico para JSON.
    Nunca usa float — HARD CONSTRAINT.
    """
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _serializar_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serializar_decimal(i) for i in obj]
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# APLICAÇÃO
# ─────────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializa tabelas de autenticação e admin padrão na startup
    criar_tabela_users()
    criar_admin_default()
    logger.info("Motor Tributário API iniciada | testes=%d", TOTAL_TESTES)
    yield
    logger.info("Motor Tributário API encerrada")


# ─────────────────────────────────────────────────────────────────────────────
# RATE LIMITING — protege login contra brute force e API contra abuso
# ─────────────────────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Motor Tributário Conect 2026-2033",
    description=(
        "API de Auditoria Tributária Transicional (EC 132/2023 | LC 123/2006 | LC 214/2025). "
        "Extrai PDFs do e-CAC via Claude Vision e compara DAS calculado vs DAS pago."
    ),
    version="2.0.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — origens permitidas via CORS_ORIGINS (separadas por vírgula).
# Padrão: apenas localhost. NUNCA usar "*" com autenticação JWT em produção.
_cors_origins = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000,http://localhost:5500,http://127.0.0.1:5500"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# Servir UI como arquivos estáticos — montado APÓS todos os routes no final do módulo
# Calculado aqui para suportar execução a partir de qualquer diretório
_UI_DIR = Path(__file__).parent.parent / "UI"


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS — Infra (público)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse, tags=["infra"])
def health():
    """Status da API e contagem de testes certificados. Público — sem autenticação."""
    return HealthResponse(
        status="ok",
        testes=TOTAL_TESTES,
        versao=app.version,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS — Inferência CNAE (autenticado)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/cnae/{cnae}/perfil", tags=["infra"])
def perfil_cnae(
    cnae: str,
    _current_user: dict = Depends(get_current_user),
):
    """
    Retorna sugestão de perfil B2B/B2C e Anexo para o CNAE informado.
    Usado pelo frontend para pré-preencher campos automaticamente.
    """
    from tabelas_simples import determinar_anexo_por_cnae_com_fonte, estimar_perfil_b2b
    anexo, fonte = determinar_anexo_por_cnae_com_fonte(cnae)
    pct_b2b = estimar_perfil_b2b(cnae)
    return {
        "cnae": cnae,
        "anexo_sugerido": anexo,
        "anexo_fonte": fonte,
        "percentual_b2b_estimado": pct_b2b,
        "perfil_sugerido": "B2B_CONTRIBUINTE" if pct_b2b >= 80 else "B2C_CONSUMIDOR_FINAL" if pct_b2b <= 20 else "MISTO",
        "disclaimer": (
            "Estimativa sem base legal — baseada em perfil tipico do segmento. "
            "O percentual real deve ser informado pelo contribuinte. "
            "Art. 47-48 LC 214/2025: credito verificado NF-e a NF-e."
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS — Auditoria PDF (existentes — sem auth por ora)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/auditar", response_model=AuditResult, tags=["auditoria"])
def auditar(req: AuditarRequest):
    """
    Audita uma empresa a partir da pasta com PDFs do e-CAC.

    Pipeline:
      1. Claude Vision extrai dados dos PDFs
      2. Motor calcula DAS (Simples Nacional, multi-atividade se detectado)
      3. Compara com DAS pago no e-CAC
      4. Retorna delta + status APROVADO/REVISAR

    Erros HTTP:
      404 — pasta não encontrada
      422 — erro de configuração (RBT12 inválido, sem PDFs, etc.)
      500 — erro interno (contate o suporte)
    """
    try:
        resultado = auditar_empresa(req.pasta_empresa)
        return AuditResult(**resultado)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("Erro inesperado em POST /auditar: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Erro interno — contate o suporte.")


@app.post("/auditar/batch", response_model=BatchResult, tags=["auditoria"])
def auditar_batch(req: AuditarBatchRequest):
    """
    Audita todas as empresas (subpastas) dentro de pasta_base.

    Falhas individuais não abortam o batch — retornadas em `erros[]`.
    Útil para processar todos os clientes do escritório de uma vez.
    """
    pasta_base = Path(req.pasta_base)
    if not pasta_base.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Pasta base não encontrada: {pasta_base}",
        )

    subpastas = sorted(p for p in pasta_base.iterdir() if p.is_dir())
    if not subpastas:
        raise HTTPException(
            status_code=422,
            detail=f"Nenhuma subpasta encontrada em: {pasta_base}",
        )

    resultados: list[AuditResult] = []
    erros: list[dict] = []

    for pasta in subpastas:
        try:
            resultado = auditar_empresa(str(pasta))
            resultados.append(AuditResult(**resultado))
        except Exception as exc:
            erros.append({"empresa": pasta.name, "erro": str(exc)})
            logger.warning("Batch: falha em %s — %s", pasta.name, type(exc).__name__)

    aprovados = sum(1 for r in resultados if r.status == "APROVADO")

    return BatchResult(
        total=len(resultados) + len(erros),
        aprovados=aprovados,
        revisao=len(resultados) - aprovados,
        erros_extracao=len(erros),
        resultados=resultados,
        erros=erros,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS — Autenticação (público: /auth/login)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/auth/login", response_model=LoginResponse, tags=["auth"])
@limiter.limit("5/minute")
def login(request: Request, req: LoginRequest):
    """
    Autentica usuário e retorna JWT Bearer token (exp 8h).
    Rate limit: 5 tentativas por minuto por IP.

    Erros HTTP:
      401 — credenciais inválidas ou usuário inativo
      429 — muitas tentativas (rate limit)
    """
    user = autenticar_usuario(req.username, req.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Credenciais inválidas.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = gerar_token_jwt(
        user_id=user.id,
        username=user.username,
        role=user.role,
    )
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        username=user.username,
        role=user.role,
        must_change_password=user.must_change_password,
    )


@app.get("/auth/me", tags=["auth"])
def me(current_user: dict = Depends(get_current_user)):
    """
    Retorna dados básicos do usuário autenticado (extraídos do JWT).
    Não consulta banco — usa apenas claims do token.
    """
    return {
        "user_id": current_user.get("sub"),
        "username": current_user.get("username"),
        "role": current_user.get("role"),
    }


@app.post("/auth/refresh", tags=["auth"])
def refresh_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """
    Renova JWT se restam menos de 2h para expirar.
    Retorna novo token ou 304 se ainda não precisa renovar.
    O frontend chama periodicamente (ex: a cada 30min).
    """
    novo = renovar_token_jwt(credentials.credentials)
    if novo is None:
        return JSONResponse(
            status_code=304,
            content={"detail": "Token ainda válido, renovação não necessária."},
        )
    return {"access_token": novo, "token_type": "bearer"}


class TrocarSenhaRequest(BaseModel):
    senha_atual: str = Field(..., min_length=1)
    nova_senha: str = Field(..., min_length=8)


@app.post("/auth/change-password", tags=["auth"])
def change_password(
    req: TrocarSenhaRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Permite que o usuário autenticado altere sua própria senha.
    Verifica a senha atual antes de aceitar a nova.
    Limpa o flag must_change_password após sucesso.

    Erros HTTP:
      400 — senha atual incorreta ou nova senha muito curta
      404 — usuário não encontrado (inconsistência de banco)
    """
    user_id = int(current_user["sub"])
    try:
        sucesso = trocar_senha_proprio(user_id, req.senha_atual, req.nova_senha)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not sucesso:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    logger.info("Troca de senha confirmada | user_id=%s", user_id)
    return {"detail": "Senha alterada com sucesso."}


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS — Administração (requer role == "admin")
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/admin/usuarios", response_model=UsuarioResponse, tags=["admin"])
@limiter.limit("10/minute")
def criar_usuario_endpoint(
    request: Request,
    req: CriarUsuarioRequest,
    _admin: dict = Depends(require_admin),
):
    """
    Cria novo usuário no sistema. Requer role admin.

    Erros HTTP:
      400 — username ou e-mail já cadastrado
      403 — usuário não é admin
    """
    try:
        novo = criar_usuario(
            username=req.username,
            email=req.email,
            senha_plain=req.password,
            role=req.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return UsuarioResponse(
        id=novo.id,
        username=novo.username,
        email=novo.email,
        role=novo.role,
        ativo=novo.ativo,
        created_at=novo.created_at,
        ultimo_acesso=novo.ultimo_acesso,
    )


@app.get("/admin/usuarios", response_model=list[UsuarioResponse], tags=["admin"])
def listar_usuarios_endpoint(_admin: dict = Depends(require_admin)):
    """
    Lista todos os usuários cadastrados, ordenados por ID. Requer role admin.
    """
    usuarios = listar_usuarios()
    return [
        UsuarioResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            role=u.role,
            ativo=u.ativo,
            created_at=u.created_at,
            ultimo_acesso=u.ultimo_acesso,
        )
        for u in usuarios
    ]


@app.post("/admin/usuarios/{user_id}/desativar", tags=["admin"])
def desativar_usuario_endpoint(
    user_id: int,
    admin: dict = Depends(require_admin),
):
    """
    Desativa usuário por ID (soft delete — não apaga do banco). Requer role admin.

    Erros HTTP:
      404 — usuário não encontrado
      403 — usuário não é admin
      409 — bloqueado: último admin ativo não pode ser desativado
    """
    # Proteção: impede que o último admin ativo seja desativado
    todos = listar_usuarios()
    admins_ativos = [u for u in todos if u.role == "admin" and u.ativo]
    alvo = next((u for u in todos if u.id == user_id), None)
    if alvo and alvo.role == "admin" and alvo.ativo and len(admins_ativos) <= 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "Operação bloqueada: você é o único administrador ativo. "
                "Promova outro usuário a admin antes de se desativar."
            ),
        )
    sucesso = desativar_usuario(user_id)
    if not sucesso:
        raise HTTPException(
            status_code=404,
            detail=f"Usuário id={user_id} não encontrado.",
        )
    return {"detail": f"Usuário id={user_id} desativado com sucesso."}


class ResetSenhaRequest(BaseModel):
    nova_senha: str = Field(..., min_length=8, description="Nova senha (mínimo 8 caracteres)")


@app.post("/admin/usuarios/{user_id}/reset-senha", tags=["admin"])
def reset_senha_endpoint(
    user_id: int,
    req: ResetSenhaRequest,
    _admin: dict = Depends(require_admin),
):
    """
    Redefine a senha de um usuário. Apenas admins.
    A nova senha deve ter no mínimo 8 caracteres.

    Erros HTTP:
      400 — senha muito curta
      404 — usuário não encontrado
      403 — usuário não é admin
    """
    try:
        sucesso = resetar_senha(user_id, req.nova_senha)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not sucesso:
        raise HTTPException(status_code=404, detail=f"Usuário id={user_id} não encontrado.")
    return {"detail": f"Senha do usuário id={user_id} redefinida com sucesso."}


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS — Análise manual (autenticado)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/analise/manual", tags=["analise"])
def analise_manual(
    req: AnaliseManualRequest,
    _current_user: dict = Depends(get_current_user),
):
    """
    Executa cálculo tributário completo sem extração de PDF.
    Útil para simulações manuais, testes e homologação.

    Pipeline:
      1. Monta EmpresaFornecedora + EmpresaCompradora + OperacaoFiscal
      2. Instancia MotorReformaTributaria
      3. Chama gerar_diagnostico()
      4. Retorna diagnóstico completo com trilha de auditoria

    LGPD: NÃO chama purge() — o resultado precisa ser lido pelo solicitante.
    Dados não persistem em banco neste endpoint (stateless por design).

    Erros HTTP:
      422 — dados de entrada inválidos (CNPJ, CNAE, UF, data fora de 2026-2033, etc.)
      500 — erro interno — contate o suporte
    """
    from datetime import date as date_type

    try:
        # Monta EmpresaFornecedora — Pydantic V2 valida CNPJ, CNAE, UF
        fornecedora = EmpresaFornecedora(
            cnpj=req.cnpj,
            razao_social=req.razao_social,
            regime=req.regime,
            cnae_principal=req.cnae_principal,
            uf_origem=req.uf_origem,
            faturamento_12m=req.faturamento_12m,
            folha_salarios_12m=req.folha_salarios_12m,
            anexo_simples=req.anexo_simples,
            categoria_mei=req.categoria_mei or ("SERVICOS" if req.regime == "MEI" else None),
            data_inicio_atividade=(
                date_type.fromisoformat(req.data_inicio_atividade)
                if req.data_inicio_atividade else None
            ),
        )

        # Monta EmpresaCompradora
        compradora = EmpresaCompradora(
            tipo=req.tipo_comprador,
            percentual_b2b=req.percentual_b2b,
            regime=req.regime_comprador,
            uf_destino=req.uf_destino,
        )

        # Converte data_emissao str → date (Pydantic V2 valida range 2026-2033)
        try:
            data_emissao_parsed = date_type.fromisoformat(req.data_emissao)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"data_emissao inválida: {exc}. Formato esperado: YYYY-MM-DD",
            )

        # Monta OperacaoFiscal
        operacao = OperacaoFiscal(
            data_emissao=data_emissao_parsed,
            valor_operacao=req.valor_operacao,
            ncm_nbs=req.ncm_nbs,
            forma_recebimento=req.forma_recebimento,
            rpa_mensal=req.rpa_mensal,
            tinha_st_icms=req.tinha_st_icms,
            reducao_cbs_ibs=req.reducao_cbs_ibs,
            beneficio_fiscal_antigo=req.beneficio_fiscal_antigo,
            lucro_real_mensal=req.lucro_real_mensal,
            creditos_pis_cofins=req.creditos_pis_cofins,
        )

    except PydanticValidationError as exc:
        # Pydantic detalha cada campo inválido — repassar ao cliente
        raise HTTPException(status_code=422, detail=exc.errors())
    except HTTPException:
        raise  # já tratada acima (data_emissao)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Executa o motor — erros de cálculo retornam 500 (não vazar stack trace)
    try:
        motor = MotorReformaTributaria(
            fornecedora=fornecedora,
            compradora=compradora,
            operacao=operacao,
        )
        diagnostico = motor.gerar_diagnostico()
        # Serializa Decimal como str — nunca float
        return JSONResponse(content=_serializar_decimal(diagnostico))

    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error(
            "Erro inesperado em POST /analise/manual: %s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="Erro interno no motor de cálculo — contate o suporte.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# POST /relatorio/pdf — Geração de PDF via weasyprint (FASE 5)
# ─────────────────────────────────────────────────────────────────────────────

@app.post(
    "/relatorio/pdf",
    summary="Gera PDF do diagnóstico fiscal",
    tags=["Relatório"],
    responses={
        200: {"content": {"application/pdf": {}}, "description": "PDF gerado com sucesso"},
        422: {"description": "Diagnóstico inválido"},
        503: {"description": "weasyprint não disponível"},
    },
)
async def gerar_relatorio_pdf(
    diagnostico: dict,
    current_user: dict = Depends(get_current_user),  # noqa: ARG001 — autenticação obrigatória
) -> Response:
    """
    Recebe o objeto diagnóstico no body JSON e retorna um PDF gerado via weasyprint.

    O diagnóstico é o mesmo objeto retornado por POST /analise/manual ou POST /analise/pdf.
    Dados sensíveis trafegam no body (POST), nunca na query string (GET).
    Exige Bearer token JWT válido.
    """
    if not _RELATORIO_DISPONIVEL or _gerar_pdf is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Geração de PDF indisponível — weasyprint/GTK não instalado. "
                "No Windows: instale GTK3 Runtime em https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer"
            ),
        )
    try:
        pdf_bytes = _gerar_pdf(diagnostico)
    except RuntimeError as exc:
        if "não instalado" in str(exc):
            raise HTTPException(
                status_code=503,
                detail="Geração de PDF indisponível — weasyprint não instalado no servidor.",
            )
        logger.error("Erro ao gerar PDF: %s", exc)
        raise HTTPException(status_code=500, detail="Falha na geração do PDF.")

    razao = (
        diagnostico.get("empresa", {}).get("razao_social")
        or diagnostico.get("razao_social")
        or "relatorio"
    )
    filename = "".join(c if c.isalnum() or c in " _-" else "_" for c in str(razao))[:50]
    filename = filename.strip("_").replace(" ", "_") or "relatorio"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}_diagnostico.pdf"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /analise/pdf — Upload PDFs e-CAC → extração → diagnóstico (FASE 3)
# ─────────────────────────────────────────────────────────────────────────────

@app.post(
    "/analise/pdf",
    summary="Extrai dados de PDFs e-CAC e gera diagnóstico",
    tags=["Análise"],
)
async def analise_pdf(
    files: list[UploadFile] = File(..., description="PDFs do e-CAC (máx. 10 arquivos)"),
    current_user: dict = Depends(get_current_user),  # noqa: ARG001
) -> JSONResponse:
    """
    Aceita múltiplos PDFs do e-CAC (PGDAS-D, DAS, SIMEI, comprovantes).
    Extrai dados via pipeline extrator_pdfs.py + Claude Vision API.
    Retorna diagnóstico fiscal completo.
    Exige Bearer token JWT válido.
    """
    if not files:
        raise HTTPException(status_code=422, detail="Nenhum arquivo enviado.")
    if len(files) > 10:
        raise HTTPException(status_code=422, detail="Máximo de 10 arquivos por requisição.")

    # Validar tipo e tamanho
    MAX_BYTES = 50 * 1024 * 1024  # 50 MB por arquivo
    conteudos: list[bytes] = []
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            raise HTTPException(
                status_code=422,
                detail=f"Arquivo '{f.filename}' não é um PDF.",
            )
        conteudo = await f.read()
        if len(conteudo) > MAX_BYTES:
            raise HTTPException(
                status_code=422,
                detail=f"Arquivo '{f.filename}' excede o limite de 50 MB.",
            )
        conteudos.append(conteudo)

    # Pipeline de extração
    try:
        from extrator_pdfs import (
            processar_pdfs_bytes,  # importação lazy — evita falha no startup se ANTHROPIC_API_KEY ausente
        )

        diagnostico = processar_pdfs_bytes(conteudos)
        return JSONResponse(content=_serializar_decimal(diagnostico))

    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="Pipeline de extração de PDFs não disponível — verifique a instalação.",
        )
    except ValueError as exc:
        msg = str(exc)
        logger.error("Erro em POST /analise/pdf: %s", msg)
        if "ANTHROPIC_API_KEY" in msg:
            raise HTTPException(
                status_code=503,
                detail="ANTHROPIC_API_KEY não configurada. Defina a variável no arquivo PY/.env para usar o upload de PDFs.",
            )
        raise HTTPException(status_code=422, detail=msg)
    except Exception as exc:
        logger.error("Erro em POST /analise/pdf: %s — %s", type(exc).__name__, exc)
        raise HTTPException(
            status_code=500,
            detail="Falha na extração dos documentos. Verifique se os PDFs são do e-CAC.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# STATIC FILES — UI servida em /ui/ para não colidir com rotas da API
# Montagem no final garante que todos os routes têm prioridade.
# Acesse: http://localhost:8000/ui/login.html
# ─────────────────────────────────────────────────────────────────────────────
if _UI_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")
else:
    logger.warning("Pasta UI não encontrada em %s — interface web indisponível.", _UI_DIR)
