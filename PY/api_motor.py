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
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

# ── Fodase warnings: suprime TODO warning nao-fatal no terminal ────────────
warnings.filterwarnings("ignore")
os.environ.setdefault("PYTHONWARNINGS", "ignore")
# Silencia GLib/GIO warnings do WeasyPrint (libs nativas C no Windows)
os.environ.setdefault("GIO_USE_VFS", "local")
os.environ.setdefault("G_MESSAGES_DEBUG", "")
os.environ.setdefault("NO_AT_BRIDGE", "1")

# ── Carrega .env (ANTHROPIC_API_KEY, JWT_SECRET_KEY, LOG_LEVEL, etc) ──────
try:
    from dotenv import load_dotenv
    _here = Path(__file__).resolve().parent
    for _candidato in (_here / ".env", _here.parent / ".env", Path.cwd() / ".env"):
        if _candidato.exists():
            load_dotenv(_candidato, override=True)  # override=True: forca re-leitura mesmo se env ja existe (vazia)
            break
except ImportError:
    pass  # dotenv opcional

# NOTA: imports abaixo ficam após o bloco de warnings/dotenv de propósito
# (precisam que PYTHONWARNINGS e ANTHROPIC_API_KEY estejam seteados primeiro).
# O ruff E402 é silenciado via noqa por motivo documentado.
from decimal import Decimal  # noqa: E402
from typing import Any, Literal, Optional  # noqa: E402

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, Response, StreamingResponse  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field  # noqa: E402
from pydantic import ValidationError as PydanticValidationError  # noqa: E402
from slowapi import Limiter, _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402
from slowapi.util import get_remote_address  # noqa: E402

# Adiciona PY/ ao path para imports relativos
sys.path.insert(0, str(Path(__file__).parent))

from audit_universal import auditar_empresa  # noqa: E402
from auth import (  # noqa: E402
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
from motor_tributario import (  # noqa: E402
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
    log_level = os.environ.get("LOG_LEVEL", "ERROR").upper()
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

    # Silencia loggers chatos de libs externas
    for noisy in (
        "uvicorn", "uvicorn.access", "uvicorn.error",
        "weasyprint", "fontTools", "fontTools.subset",
        "PIL", "httpx", "httpcore", "passlib",
        "anthropic", "multipart", "sqlalchemy",
    ):
        logging.getLogger(noisy).setLevel(logging.ERROR)


_setup_logging()
logger = logging.getLogger("motor_conect.api")

TOTAL_TESTES = 327  # Atualizado 08/04/2026: + 7 testes LGPD PII separation (fix bug latente Lucro Real)


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
    produto_importado: bool = Field(
        default=False,
        description=(
            "True se conteúdo de importação > 40% (Res. SF 13/2012). "
            "Afeta alíquota interestadual ICMS (4%) no cálculo do DIFAL."
        )
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
            produto_importado=req.produto_importado,
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

        # Envelope com PII separada do diagnóstico despersonalizado (LGPD).
        # cnpj e razao_social vieram do formulário — devolvemos ao cliente
        # num campo separado para popular o header do resultado.html.
        payload = {
            "diagnostico": diagnostico,
            "pii": {
                "cnpj": fornecedora.cnpj,
                "razao_social": fornecedora.razao_social,
            },
        }
        return JSONResponse(content=_serializar_decimal(payload))

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
    payload: dict,
    current_user: dict = Depends(get_current_user),  # noqa: ARG001 — autenticação obrigatória
) -> Response:
    """
    Recebe payload {diagnostico, pii?} no body JSON e retorna PDF.

    Schema esperado:
    {
        "diagnostico": {...},     # dict despersonalizado (LGPD)
        "pii": {                   # opcional — PII só para o PDF
            "cnpj": "...",
            "razao_social": "..."
        }
    }

    Para retrocompatibilidade, ainda aceita o diagnostico direto no body
    (caso pii esteja embutida em diagnostico.empresa, embora isso fira LGPD).

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

    # Suporte a 2 formatos: novo (com pii separado) e legado (diagnostico direto)
    if isinstance(payload, dict) and "diagnostico" in payload:
        diagnostico = payload["diagnostico"]
        pii = payload.get("pii") or None
    else:
        # Legado: payload É o diagnóstico
        diagnostico = payload
        pii = None

    try:
        pdf_bytes = _gerar_pdf(diagnostico, pii=pii)
    except RuntimeError as exc:
        if "não instalado" in str(exc):
            raise HTTPException(
                status_code=503,
                detail="Geração de PDF indisponível — weasyprint não instalado no servidor.",
            )
        logger.error("Erro ao gerar PDF: %s", exc)
        raise HTTPException(status_code=500, detail="Falha na geração do PDF.")

    razao = (
        (pii or {}).get("razao_social")
        or diagnostico.get("empresa", {}).get("razao_social")
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
# POST /analise/pdf — Upload multi-documento → extração → diagnóstico (FASE 3)
# Aceita: PDF e-CAC (PGDAS-D), XML NFe/NFCe, CSV/TXT Folha de Pagamento
# Bloqueia com HTTP 422 se documentos mínimos por regime estiverem ausentes.
# Amparo: LC 123/2006 Art. 18 §24 (Fator R) + Art. 13 §1º V (ICMS-ST)
# ─────────────────────────────────────────────────────────────────────────────

_MIME_ACEITOS: dict[str, str] = {
    "application/pdf": "pdf",
    "text/xml": "xml",
    "application/xml": "xml",
    "text/csv": "csv",
    "text/plain": "csv",   # .txt Domínio/SPED
}

_EXT_ACEITAS: set[str] = {".pdf", ".xml", ".csv", ".txt"}


def _sniff_xml_mod(conteudo: bytes) -> str:
    """
    Lê os primeiros 2 KB do XML para detectar ide/mod sem parse completo.
    Retorna "55" (NFe), "65" (NFCe) ou "" (desconhecido).
    """
    trecho = conteudo[:2048].decode("utf-8", errors="replace")
    import re as _re
    m = _re.search(r"<mod>\s*(\d+)\s*</mod>", trecho)
    return m.group(1) if m else ""


def _sniff_sped_tipo(conteudo: bytes) -> str:
    """
    Detecta qual SPED o arquivo é, olhando os primeiros ~2 KB:
      - "sped_ecd"          → contém '|0000|LECD|' (ECD Domínio Contábil)
      - "sped_efd_contrib"  → contém '|0110|' e cabeçalho 14 campos estilo EFD-Contribuições
      - ""                  → não é SPED (folha CSV/TXT comum)
    """
    trecho = conteudo[:4096].decode("latin-1", errors="replace")
    if "|0000|LECD|" in trecho:
        return "sped_ecd"
    # EFD-Contribuições: bloco 0000 com 13+ campos separados por | e presença de 0110
    if "|0000|" in trecho and "|0110|" in trecho:
        return "sped_efd_contrib"
    return ""


def _detectar_tipo_documento(filename: str, conteudo: bytes) -> str:
    """
    Classifica um arquivo em:
      "pgdas_d" | "nfe_saida" | "nfce" | "folha_csv" |
      "sped_ecd" | "sped_efd_contrib" | "desconhecido"

    Usado para validar documentos mínimos por regime (bloqueio 422) e para
    rotear para o parser correto. SPED é identificado por sniff do conteúdo
    (header |0000|) porque compartilha extensão .txt com folha Domínio.
    """
    nome = (filename or "").lower()
    if nome.endswith(".pdf"):
        return "pgdas_d"
    if nome.endswith((".xml",)):
        mod = _sniff_xml_mod(conteudo)
        if mod == "55":
            return "nfe_saida"
        if mod == "65":
            return "nfce"
        return "xml_desconhecido"
    if nome.endswith((".csv", ".txt")):
        # SPED tem precedência se o header bater — senão cai como folha CSV
        tipo_sped = _sniff_sped_tipo(conteudo)
        if tipo_sped:
            return tipo_sped
        return "folha_csv"
    return "desconhecido"


def _validar_docs_por_regime(
    tipo_comprador: str,
    tipos_presentes: set[str],
) -> list[str]:
    """
    Retorna lista de documentos obrigatórios ainda faltantes para o regime.
    Lista vazia = todos os documentos presentes.

    Amparo legal:
    - LC 123/2006 Art. 18 §24 — folha obrigatória para Fator R B2B
    - LC 123/2006 Art. 13 §1º V — NFe obrigatória para segregar ICMS-ST B2B
    """
    faltando: list[str] = []
    if "pgdas_d" not in tipos_presentes:
        faltando.append("PGDAS-D PDF (e-CAC) — Extrato Simples Nacional")
    if tipo_comprador in ("B2B_CONTRIBUINTE", "MISTO"):
        if "nfe_saida" not in tipos_presentes:
            faltando.append(
                "XML NFe de saída — mês analisado "
                "(LC 123/2006 Art. 13 §1º V — ICMS-ST + receita real B2B)"
            )
        if "folha_csv" not in tipos_presentes:
            faltando.append(
                "CSV Folha de Pagamento — 12 meses (Domínio ou similar) "
                "(LC 123/2006 Art. 18 §24 — Fator R correto)"
            )
    if tipo_comprador in ("B2C_CONSUMIDOR_FINAL", "MISTO"):
        if "nfce" not in tipos_presentes and "folha_csv" not in tipos_presentes:
            faltando.append(
                "XML NFCe ou CSV de vendas PDV — mês analisado "
                "(LC 123/2006 Art. 3º §2º — receita real B2C)"
            )
    return faltando


# ─────────────────────────────────────────────────────────────────────────────
# SIEG — Sincronização direta de XMLs (PARTE 2 do pareamento)
# ─────────────────────────────────────────────────────────────────────────────


class SiegSincronizarRequest(BaseModel):
    """
    Request do endpoint POST /sieg/sincronizar.

    Janela recomendada: 12 meses retroativos ao mês-corte (alinhada com
    o período-base do diagnóstico). Use ano_base para baixar o ano inteiro
    (atalho 01/01..31/12).
    """

    model_config = ConfigDict(extra="forbid")

    cnpj: str = Field(..., description="CNPJ (14 dígitos, com ou sem pontuação)")
    data_inicio: Optional[str] = Field(None, description="ISO YYYY-MM-DD")
    data_fim: Optional[str] = Field(None, description="ISO YYYY-MM-DD")
    ano_base: Optional[int] = Field(
        None,
        ge=2020,
        le=2033,
        description="Atalho: baixa 01/01..31/12 do ano informado",
    )
    xml_type: int = Field(
        1,
        description="1=NFe (default), 2=CTe, 3=NFSe, 4=NFCe",
    )


@app.post(
    "/sieg/sincronizar",
    summary="Baixa XMLs da Sieg e persiste cifrados em auditoria_documentos",
    tags=["Integrações"],
)
async def sieg_sincronizar(
    payload: SiegSincronizarRequest,
    current_user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Sincronização Sieg → storage_cifrado → DB.

    Idempotente: re-executar a mesma janela não duplica registros. XMLs
    já conhecidos (mesmo hash SHA-256) são pulados sem refazer I/O.

    A API key da Sieg NÃO trafega no request — ela vem das 3 fontes
    canônicas (env, arquivo protegido, AWS Secrets Manager).

    Amparo: MAX_FISCAL_05 (auditoria documental obrigatória) +
    LGPD Art. 37 (registro das operações de tratamento).
    """
    from datetime import date as _date

    # ─ resolver janela ─
    if payload.ano_base:
        if payload.data_inicio or payload.data_fim:
            raise HTTPException(
                status_code=422,
                detail="ano_base é mutuamente exclusivo com data_inicio/data_fim",
            )
        data_inicio = _date(payload.ano_base, 1, 1)
        data_fim = _date(payload.ano_base, 12, 31)
    else:
        if not payload.data_inicio or not payload.data_fim:
            raise HTTPException(
                status_code=422,
                detail="Forneça ano_base OU (data_inicio E data_fim)",
            )
        try:
            data_inicio = _date.fromisoformat(payload.data_inicio)
            data_fim = _date.fromisoformat(payload.data_fim)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Data inválida: {exc}"
            ) from exc

    # Lazy imports — evita pagar o custo se o endpoint nunca for chamado
    from integrations.sieg_adapter import (
        XML_TYPES_VALIDOS,
        SiegAdapter,
        SiegError,
    )
    from integrations.sieg_credentials import (
        SiegCredentialError,
        get_sieg_api_key,
    )
    from integrations.sieg_ingestor import SiegIngestor

    if payload.xml_type not in XML_TYPES_VALIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"xml_type inválido — esperado um de {list(XML_TYPES_VALIDOS)}",
        )

    try:
        api_key = get_sieg_api_key()
    except SiegCredentialError as exc:
        logger.error("SIEG_API_KEY ausente — endpoint não pode operar")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    adapter = SiegAdapter(api_key=api_key)
    ingestor = SiegIngestor(adapter)

    try:
        resultado = ingestor.sincronizar(
            cnpj=payload.cnpj,
            data_inicio=data_inicio,
            data_fim=data_fim,
            xml_type=payload.xml_type,
            uploaded_by_user_id=current_user.get("id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SiegError as exc:
        logger.error("Sieg sincronizar falhou: %s", exc)
        raise HTTPException(status_code=502, detail=f"Sieg: {exc}") from exc

    return JSONResponse(content=resultado.to_dict(), status_code=200)


@app.post(
    "/analise/pdf",
    summary="Extrai dados de documentos fiscais e gera diagnóstico",
    tags=["Análise"],
)
async def analise_pdf(
    request: Request,
    files: list[UploadFile] = File(
        ...,
        description="PDFs e-CAC, XMLs NFe/NFCe, CSV/TXT Folha de Pagamento (máx. 20 arquivos)"
    ),
    termo_aceite: bool = Form(
        False,
        description="Termo de aceite digital obrigatório (CTN Art. 142 + LGPD Art. 37)",
    ),
    tipo_comprador: str = Form(
        "B2B_CONTRIBUINTE",
        description="Perfil do comprador: B2B_CONTRIBUINTE | B2C_CONSUMIDOR_FINAL | MISTO",
    ),
    current_user: dict = Depends(get_current_user),
) -> JSONResponse:
    """
    Aceita múltiplos documentos fiscais:
    - PDF e-CAC: PGDAS-D (obrigatório), DAS, SIMEI, comprovantes
    - XML NFe 4.0 (modelo 55): receita real B2B + ICMS-ST
    - XML NFCe 4.0 (modelo 65): receita real B2C
    - CSV/TXT Folha de Pagamento: Fator R correto (LC 123/2006 Art. 18 §24)

    Bloqueio 422: se documentos mínimos para o tipo_comprador estiverem ausentes.
    Auditoria: PDFs cifrados AES-256-GCM + registrados em auditoria_documentos.
    Merge: mesclar_fontes_documentais() combina PDF + XML + CSV antes do motor.
    """
    _TIPOS_COMPRADOR_VALIDOS = {"B2B_CONTRIBUINTE", "B2C_CONSUMIDOR_FINAL", "MISTO"}
    if tipo_comprador not in _TIPOS_COMPRADOR_VALIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"tipo_comprador inválido: {tipo_comprador!r}. "
                   f"Válidos: {sorted(_TIPOS_COMPRADOR_VALIDOS)}",
        )
    if not termo_aceite:
        raise HTTPException(
            status_code=400,
            detail=(
                "Termo de aceite digital obrigatório. "
                "Marque a caixa 'Confirmo que estes são os documentos oficiais' "
                "antes de enviar (CTN Art. 142 + LGPD Art. 37)."
            ),
        )
    if not files:
        raise HTTPException(status_code=422, detail="Nenhum arquivo enviado.")
    if len(files) > 20:
        raise HTTPException(status_code=422, detail="Máximo de 20 arquivos por requisição.")

    MAX_BYTES = 50 * 1024 * 1024  # 50 MB por arquivo
    conteudos_pdf: list[bytes] = []
    nomes_pdf: list[str] = []
    conteudos_xml_nfe: list[bytes] = []
    conteudos_xml_nfce: list[bytes] = []
    conteudos_csv: list[bytes] = []
    conteudos_sped_ecd: list[bytes] = []
    conteudos_sped_efd_contrib: list[bytes] = []
    tipos_presentes: set[str] = set()

    for f in files:
        nome = (f.filename or "arquivo").lower()
        ext = "." + nome.rsplit(".", 1)[-1] if "." in nome else ""
        if ext not in _EXT_ACEITAS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Arquivo '{f.filename}' com extensão não suportada. "
                    f"Aceitos: .pdf, .xml, .csv, .txt"
                ),
            )
        conteudo = await f.read()
        if len(conteudo) > MAX_BYTES:
            raise HTTPException(
                status_code=422,
                detail=f"Arquivo '{f.filename}' excede o limite de 50 MB.",
            )

        tipo = _detectar_tipo_documento(f.filename or "", conteudo)
        tipos_presentes.add(tipo)

        if tipo == "pgdas_d":
            conteudos_pdf.append(conteudo)
            nomes_pdf.append(f.filename or "documento.pdf")
        elif tipo == "nfe_saida":
            conteudos_xml_nfe.append(conteudo)
        elif tipo == "nfce":
            conteudos_xml_nfce.append(conteudo)
        elif tipo == "folha_csv":
            conteudos_csv.append(conteudo)
        elif tipo == "sped_ecd":
            conteudos_sped_ecd.append(conteudo)
        elif tipo == "sped_efd_contrib":
            conteudos_sped_efd_contrib.append(conteudo)
        else:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Arquivo '{f.filename}' não reconhecido. "
                    "XMLs devem ser NFe (mod=55) ou NFCe (mod=65). "
                    "CSVs devem ser folhas de pagamento."
                ),
            )

    # Bloqueio 422 — documentos mínimos por regime
    faltando = _validar_docs_por_regime(tipo_comprador, tipos_presentes)
    if faltando:
        raise HTTPException(
            status_code=422,
            detail={
                "codigo": "DOCUMENTOS_INSUFICIENTES",
                "tipo_comprador": tipo_comprador,
                "faltando": faltando,
                "amparo_legal": "LC 123/2006 Art. 18 §24 (Fator R) + Art. 13 §1º V (ICMS-ST)",
            },
        )

    # Operador autenticado
    user_id = None
    try:
        user_id = int(current_user.get("id")) if current_user else None
    except (TypeError, ValueError):
        user_id = None

    # Pipeline de extração + auditoria documental
    try:
        from extrator_pdfs import processar_pdfs_bytes

        payload = processar_pdfs_bytes(
            conteudos_pdf,
            arquivos_nomes=nomes_pdf,
            user_id=user_id,
            persistir_auditoria=True,
            envelope=True,
        )
        diagnostico = payload["diagnostico"]

        # Parsear XMLs e CSV — enriquecer dados extraídos do PDF
        nfe_data = None
        nfce_data = None
        folha_data = None

        if conteudos_xml_nfe:
            try:
                from parsers.xml_nfe import parsear_lote_nfe
                nfe_data = parsear_lote_nfe(conteudos_xml_nfe)
            except Exception as exc_nfe:
                logger.warning("Falha ao parsear XML NFe: %s", exc_nfe)

        if conteudos_xml_nfce:
            try:
                from parsers.xml_nfce import parsear_lote_nfce
                nfce_data = parsear_lote_nfce(conteudos_xml_nfce)
            except Exception as exc_nfce:
                logger.warning("Falha ao parsear XML NFCe: %s", exc_nfce)

        if conteudos_csv:
            try:
                from parsers.csv_folha import parsear_csv_folha
                # Concatenar múltiplos CSVs (raro, mas possível)
                csv_bytes = b"\n".join(conteudos_csv)
                folha_data = parsear_csv_folha(csv_bytes)
            except Exception as exc_csv:
                logger.warning("Falha ao parsear CSV folha: %s", exc_csv)

        # SPED Domínio Contábil — ECD (lançamentos) e EFD-Contribuições (PIS/COFINS)
        ecd_data = None
        efd_contrib_data = None

        if conteudos_sped_ecd:
            try:
                from parsers.sped_ecd import parsear_sped_ecd
                # Parse só o primeiro — múltiplos ECDs em um request é improvável
                ecd_data = parsear_sped_ecd(conteudos_sped_ecd[0])
            except Exception as exc_ecd:
                logger.warning("Falha ao parsear SPED ECD: %s", exc_ecd)

        if conteudos_sped_efd_contrib:
            try:
                from parsers.sped_efd_contrib import parsear_sped_efd_contrib
                efd_contrib_data = parsear_sped_efd_contrib(conteudos_sped_efd_contrib[0])
            except Exception as exc_efd:
                logger.warning("Falha ao parsear SPED EFD-Contrib: %s", exc_efd)

        # Auditoria: persistir XMLs, CSVs e SPEDs também (cifrar + registrar)
        for conteudo_extra, nome_extra, mime_extra in (
            [(c, f"nfe_{i}.xml", "text/xml") for i, c in enumerate(conteudos_xml_nfe)]
            + [(c, f"nfce_{i}.xml", "text/xml") for i, c in enumerate(conteudos_xml_nfce)]
            + [(c, f"folha_{i}.csv", "text/csv") for i, c in enumerate(conteudos_csv)]
            + [(c, f"sped_ecd_{i}.txt", "text/plain") for i, c in enumerate(conteudos_sped_ecd)]
            + [(c, f"sped_efd_contrib_{i}.txt", "text/plain") for i, c in enumerate(conteudos_sped_efd_contrib)]
        ):
            try:
                from database import aceitar_documento, registrar_documento_auditoria
                from storage_cifrado import cifrar_e_persistir, hash_documento
                cnpj_empresa = (payload.get("pii") or {}).get("cnpj", "")
                if cnpj_empresa:
                    hash_doc = hash_documento(conteudo_extra)
                    path_cifrado = cifrar_e_persistir(conteudo_extra, cnpj_empresa)
                    doc_id = registrar_documento_auditoria(
                        hash_sha256=hash_doc,
                        empresa_cnpj=cnpj_empresa,
                        nome_original=nome_extra,
                        mime=mime_extra,
                        tamanho=len(conteudo_extra),
                        storage_path=str(path_cifrado),
                        uploaded_by_user_id=user_id,
                    )
                    if doc_id and user_id:
                        ip_origem = request.client.host if request.client else None
                        aceitar_documento(
                            documento_id=doc_id,
                            aceito_por_user_id=user_id,
                            aceito_ip=ip_origem,
                        )
            except Exception as exc_audit:
                logger.warning("Falha ao auditar arquivo extra %s: %s", nome_extra, exc_audit)

        # Registra termo de aceite para PDFs persistidos (LGPD Art. 37)
        ip_origem = request.client.host if request.client else None
        docs_auditoria = (
            diagnostico.get("_extracao", {}).get("documentos_auditoria", []) or []
        )
        if docs_auditoria and user_id is not None:
            try:
                from database import aceitar_documento
                for doc in docs_auditoria:
                    doc_id = doc.get("id")
                    if doc_id is not None:
                        aceitar_documento(
                            documento_id=doc_id,
                            aceito_por_user_id=user_id,
                            aceito_ip=ip_origem,
                        )
            except Exception as exc_aceite:
                logger.warning("Falha ao registrar termo de aceite: %s", exc_aceite)

        # Adicionar metadados de fontes extra ao diagnóstico
        diagnostico.setdefault("_extracao", {})["fontes_extra"] = {
            "nfe_notas": nfe_data.notas_processadas if nfe_data else 0,
            "nfce_notas": nfce_data.notas_processadas if nfce_data else 0,
            "folha_meses": folha_data.meses_encontrados if folha_data else 0,
            "folha_estimativa": folha_data.fonte_estimativa if folha_data else None,
            "tipo_comprador": tipo_comprador,
            "sped_ecd_lancamentos": len(ecd_data.lancamentos) if ecd_data else 0,
            "sped_efd_contrib_regime": efd_contrib_data.regime if efd_contrib_data else None,
            "sped_efd_pis_devido": str(efd_contrib_data.pis_valor_devido) if efd_contrib_data else None,
            "sped_efd_cofins_devido": str(efd_contrib_data.cofins_valor_devido) if efd_contrib_data else None,
        }

        # ─── Observability layer (Akita Rails) ──────────────────────────────
        try:
            from decimal import Decimal as _D

            from observability import anomalias, hmac_trilha, semaforo_das

            trilha = diagnostico.get("trilha_auditoria") or []

            # 1. Anomaly detection
            rbt12_raw = diagnostico.get("rbt12") or diagnostico.get("_extracao", {}).get("rbt12")
            confianca_raw = (diagnostico.get("_extracao", {}) or {}).get("confianca")
            folha_raw = (diagnostico.get("_extracao", {}) or {}).get("folha_12m")

            rbt12_dec = _D(str(rbt12_raw)) if rbt12_raw not in (None, "") else None
            folha_dec = _D(str(folha_raw)) if folha_raw not in (None, "") else None
            rpa_dec = (rbt12_dec / _D("12")) if rbt12_dec else None
            conf_float = float(confianca_raw) if confianca_raw is not None else None

            pis_nfe = None
            cofins_nfe = None
            if nfe_data is not None:
                pis_nfe = getattr(nfe_data, "pis_total", None) or getattr(nfe_data, "total_pis", None)
                cofins_nfe = getattr(nfe_data, "cofins_total", None) or getattr(nfe_data, "total_cofins", None)

            alertas = anomalias.detectar(
                rbt12=rbt12_dec,
                rpa_mensal=rpa_dec,
                confianca_extracao=conf_float,
                folha_12m=folha_dec,
                pis_sped=efd_contrib_data.pis_valor_devido if efd_contrib_data else None,
                pis_nfe=pis_nfe,
                cofins_sped=efd_contrib_data.cofins_valor_devido if efd_contrib_data else None,
                cofins_nfe=cofins_nfe,
            )
            diagnostico["_anomalias"] = alertas
            for alerta in alertas:
                trilha.append(alerta)

            # 2. Semáforo DAS (quando calc e pago presentes)
            das_calc_raw = diagnostico.get("das_calculado") or diagnostico.get("valor_das")
            das_pago_raw = (diagnostico.get("_extracao", {}) or {}).get("das_pago_e_cac")
            if das_calc_raw and das_pago_raw:
                try:
                    semaforo = semaforo_das.avaliar(
                        _D(str(das_calc_raw)),
                        _D(str(das_pago_raw)),
                    )
                    diagnostico["_semaforo_das"] = semaforo
                    trilha.append(semaforo)
                except Exception as exc_sem:
                    logger.warning("Falha ao avaliar semáforo DAS: %s", exc_sem)

            # 3. HMAC trilha signing (integridade de prova fiscal)
            if trilha:
                diagnostico["trilha_auditoria"] = hmac_trilha.assinar_trilha(trilha)
        except Exception as exc_obs:
            logger.warning("Falha na camada de observability: %s", exc_obs)

        return JSONResponse(content=_serializar_decimal(payload))

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
            detail="Falha na extração dos documentos. Verifique os arquivos enviados.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# GET /auditoria/prova/cnpj/{cnpj} — Dossiê de prova ZIP (Gap P0 / Etapa 5)
#
# Decifra todos os PDFs cifrados de um cliente e devolve um ZIP com:
#   - originais/<nome>.pdf         (decifrados on-the-fly)
#   - HASHES.txt                   (hash SHA-256 esperado de cada arquivo)
#   - README.txt                   (metadados: quando, quem, LGPD Art. 37)
#
# Cada decifragem é registrada em AuditoriaAcessoDB (LGPD Art. 37).
# Exige motivo explícito via query param.
# ─────────────────────────────────────────────────────────────────────────────

@app.get(
    "/auditoria/prova/cnpj/{cnpj_digitos}",
    summary="Gera dossiê de prova ZIP com PDFs decifrados de um cliente",
    tags=["Auditoria"],
)
async def gerar_dossie_prova(
    cnpj_digitos: str,
    motivo: str = Query(
        ...,
        min_length=10,
        max_length=500,
        description="Motivo do acesso (LGPD Art. 37). Ex: 'Fiscalizacao RFB processo 123/2026'",
    ),
    current_user: dict = Depends(get_current_user),
    request: Request = None,  # type: ignore[assignment]
) -> StreamingResponse:
    """
    Monta o dossiê de prova de um cliente como ZIP binário:

      dossie_<cnpj_anon>_<timestamp>.zip
      ├── originais/
      │   ├── pgdasd-extrato.pdf
      │   ├── das_01_2026.pdf
      │   └── ...
      ├── HASHES.txt
      └── README.txt

    Cada PDF é decifrado on-the-fly via storage_cifrado.decifrar usando
    a chave derivada do CNPJ. O registro de acesso é gravado em
    AuditoriaAcessoDB com o motivo, user_id e IP (LGPD Art. 37).

    Exige Bearer token JWT válido e motivo explícito. Retorna 404 se o
    cliente não tem documentos, 500 se alguma decifragem falhar.
    """
    import io
    import zipfile
    from datetime import datetime as _dt
    from pathlib import Path as _Path

    from database import (
        buscar_documentos_por_cnpj,
        registrar_acesso_documento,
    )
    from storage_cifrado import anonimizar_cnpj, decifrar

    # Normaliza CNPJ: remove qualquer não-dígito, exige 14 dígitos
    apenas_digitos = "".join(c for c in (cnpj_digitos or "") if c.isdigit())
    if len(apenas_digitos) != 14:
        raise HTTPException(
            status_code=422,
            detail=f"CNPJ deve ter 14 digitos. Recebido: {len(apenas_digitos)}.",
        )
    # Formata para o formato canônico usado pelo extrator (XX.XXX.XXX/XXXX-XX)
    cnpj_formatado = (
        f"{apenas_digitos[:2]}.{apenas_digitos[2:5]}.{apenas_digitos[5:8]}"
        f"/{apenas_digitos[8:12]}-{apenas_digitos[12:]}"
    )
    # Usamos o formato formatado para buscar (é o que está no DB),
    # mas passamos os dígitos puros para storage_cifrado.decifrar
    # (que normaliza internamente via HKDF sobre dígitos).
    cnpj = cnpj_formatado

    # Extrai user_id + IP para auditoria
    try:
        user_id = int(current_user.get("id")) if current_user else None
    except (TypeError, ValueError):
        user_id = None
    ip = None
    if request is not None:
        try:
            ip = request.client.host if request.client else None  # type: ignore[attr-defined]
        except Exception:
            ip = None

    # Busca documentos do cliente (não purgados) — tenta primeiro o formato
    # canônico, depois os dígitos puros (compat com entradas antigas)
    docs = buscar_documentos_por_cnpj(cnpj_formatado)
    if not docs:
        docs = buscar_documentos_por_cnpj(apenas_digitos)
    if not docs:
        raise HTTPException(
            status_code=404,
            detail=f"Nenhum documento de auditoria encontrado para o CNPJ {cnpj_formatado}.",
        )

    # Monta ZIP em memória
    buffer = io.BytesIO()
    cnpj_anon = anonimizar_cnpj(cnpj)
    timestamp = _dt.now().strftime("%Y%m%d-%H%M%S")
    hashes_txt = [
        "# DOSSIE DE PROVA — Motor Tributario Conect",
        f"# CNPJ anonimizado: {cnpj_anon}",
        f"# Gerado em: {_dt.now().isoformat()}",
        f"# Solicitante: user_id={user_id}",
        f"# Motivo: {motivo}",
        "#",
        "# Verificacao: sha256sum originais/*.pdf deve bater com as linhas abaixo.",
        "#",
    ]
    erros: list[str] = []

    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for doc in docs:
            try:
                plaintext = decifrar(
                    _Path(doc.storage_path),
                    cnpj,
                    hash_esperado=doc.hash_sha256,
                )
                # Sanitiza nome (evita path traversal no ZIP)
                nome_seguro = doc.nome_original.replace("/", "_").replace("\\", "_")
                zf.writestr(f"originais/{nome_seguro}", plaintext)
                hashes_txt.append(f"{doc.hash_sha256}  originais/{nome_seguro}")

                # LGPD Art. 37: registra o acesso
                registrar_acesso_documento(
                    documento_id=doc.id,
                    motivo=motivo,
                    acessado_por_user_id=user_id,
                    ip=ip,
                )
            except Exception as exc:
                logger.error(
                    "Falha ao decifrar doc_id=%s no dossie de %s: %s",
                    doc.id, cnpj_anon, exc,
                )
                erros.append(f"{doc.nome_original}: {type(exc).__name__}")

        # HASHES.txt
        zf.writestr("HASHES.txt", "\n".join(hashes_txt).encode("utf-8"))

        # README.txt
        readme = [
            "DOSSIE DE PROVA — Motor Tributario Conect",
            "=" * 50,
            "",
            f"Cliente (CNPJ anonimizado): {cnpj_anon}",
            f"Gerado em: {_dt.now().isoformat()}",
            f"Documentos incluidos: {len(docs) - len(erros)}",
            f"Falhas de decifragem: {len(erros)}",
            "",
            "Solicitante:",
            f"  user_id: {user_id}",
            f"  ip: {ip or 'N/A'}",
            f"  motivo: {motivo}",
            "",
            "Conteudo do ZIP:",
            "  originais/         PDFs decifrados, idênticos ao upload original",
            "  HASHES.txt         SHA-256 esperado de cada arquivo",
            "  README.txt         este arquivo",
            "",
            "Como verificar integridade:",
            "  1. Extraia o ZIP",
            "  2. Rode: sha256sum originais/*.pdf",
            "  3. Compare com HASHES.txt — devem bater byte a byte",
            "",
            "Base legal:",
            "  - LGPD Art. 37 (Lei 13.709/2018): registro de operacoes de tratamento",
            "  - CTN Art. 173: prazo decadencial de 5 anos",
            "  - CTN Art. 142: constituicao do credito exige prova documental",
            "",
            "Este dossie eh prova de que os dados analisados vieram EXATAMENTE",
            "destes arquivos, no momento registrado. Qualquer divergencia entre",
            "os PDFs aqui e os calculos do diagnostico eh responsabilidade de",
            "quem enviou o arquivo, nao do contador que processou.",
        ]
        if erros:
            readme.extend(["", "FALHAS DE DECIFRAGEM:", *[f"  - {e}" for e in erros]])
        zf.writestr("README.txt", "\n".join(readme).encode("utf-8"))

    buffer.seek(0)
    filename = f"dossie_{cnpj_anon}_{timestamp}.zip"
    logger.info(
        "Dossie gerado | cnpj_anon=%s | docs=%d | erros=%d | user_id=%s",
        cnpj_anon, len(docs), len(erros), user_id,
    )
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRA CONTADOR (Serpro/RFB) — PGDAS-D + DAS automatizados
# ─────────────────────────────────────────────────────────────────────────────


class IntegraSincronizarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cnpj: str = Field(..., description="CNPJ do cliente (14 dígitos, aceita pontuação)")
    ano_base: Optional[int] = Field(
        None, ge=2020, le=2033,
        description="Ano completo (expande em 12 períodos). XOR com 'periodos'.",
    )
    periodos: Optional[list[str]] = Field(
        None, description="Lista explícita YYYY-MM. XOR com 'ano_base'."
    )
    tipos: list[Literal["pgdasd", "das"]] = Field(
        default_factory=lambda: ["pgdasd", "das"],
        description="Subconjunto de serviços a puxar.",
    )

    def resolver_periodos(self) -> list[str]:
        if self.ano_base is not None and self.periodos:
            raise ValueError("Forneça 'ano_base' OU 'periodos', não ambos.")
        if self.ano_base is None and not self.periodos:
            raise ValueError("Forneça 'ano_base' ou 'periodos'.")
        if self.ano_base is not None:
            return [f"{self.ano_base}-{m:02d}" for m in range(1, 13)]
        return list(self.periodos or [])


@app.post("/integra/sincronizar", tags=["Integrações"])
async def integra_sincronizar(
    payload: IntegraSincronizarRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Puxa PGDAS-D e/ou DAS do Integra Contador (Serpro/RFB) para o CNPJ.

    Requer credenciais configuradas no servidor via env vars
    (INTEGRA_CERT_PATH, INTEGRA_CERT_PASSWORD, INTEGRA_CONTRATANTE_CNPJ,
    INTEGRA_AUTOR_PEDIDO_DADOS_CNPJ) ou arquivo INI protegido.
    """
    try:
        periodos = payload.resolver_periodos()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Lazy imports — mantém api_motor carregável sem cryptography/cert
    try:
        from integrations.integra_adapter import (
            IntegraAdapter,
            IntegraAuthError,
            IntegraCertError,
            IntegraError,
        )
        from integrations.integra_credentials import (
            IntegraCredentialError,
            get_integra_credenciais,
        )
        from integrations.integra_ingestor import IntegraIngestor
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Integra Contador indisponível (imports): {exc}",
        )

    try:
        credenciais = get_integra_credenciais()
    except IntegraCredentialError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Integra Contador não configurado: {exc}",
        )

    adapter = IntegraAdapter(credenciais)
    try:
        ingestor = IntegraIngestor(adapter)
        resultado = ingestor.sincronizar(
            cnpj=payload.cnpj,
            periodos=periodos,
            tipos=tuple(payload.tipos),
            uploaded_by_user_id=current_user.get("id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except IntegraCertError as exc:
        raise HTTPException(status_code=503, detail=f"Certificado: {exc}")
    except IntegraAuthError as exc:
        raise HTTPException(status_code=502, detail=f"Autenticação Serpro: {exc}")
    except IntegraError as exc:
        raise HTTPException(status_code=502, detail=f"Integra Contador: {exc}")
    finally:
        adapter.close()

    return {"ok": True, "resumo": resultado.to_dict()}


# ─────────────────────────────────────────────────────────────────────────────
# STATIC FILES — UI servida em /ui/ para não colidir com rotas da API
# Montagem no final garante que todos os routes têm prioridade.
# Acesse: http://localhost:8000/ui/login.html
# ─────────────────────────────────────────────────────────────────────────────
if _UI_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")
else:
    logger.warning("Pasta UI não encontrada em %s — interface web indisponível.", _UI_DIR)
