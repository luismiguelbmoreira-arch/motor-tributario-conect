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
import re
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
from fastapi.responses import JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator  # noqa: E402
from pydantic import ValidationError as PydanticValidationError  # noqa: E402
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

# Adiciona PY/ ao path para imports relativos
sys.path.insert(0, str(Path(__file__).parent))

import database  # noqa: E402
from auth import (  # noqa: E402
    criar_admin_default,
    criar_tabela_users,
)
from core.motor_tributario import (  # noqa: E402
    EmpresaCompradora,
    EmpresaFornecedora,
    MotorReformaTributaria,
    OperacaoFiscal,
)
from schemas.catalogo_documentos import montar_cards  # noqa: E402
from schemas.documentos_requeridos import CardsResponse  # noqa: E402
from schemas.responses import DiagnosticoResponse  # noqa: E402
from utils.periodo_base import ANO_MAX, ANO_MIN  # noqa: E402
from utils.periodo_base import derivar as derivar_periodo  # noqa: E402
from validadores import validar_cnae, validar_cnpj, validar_uf  # noqa: E402

# relatorio_pdf importado lazy no endpoint — evita crash de startup se GTK ausente (Windows)
try:
    from services.relatorio_pdf import gerar_pdf as _gerar_pdf
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

TOTAL_TESTES = 984  # Atualizado 24/04/2026: 57 arquivos, 984 funções de teste (inclui suite HTTP Fase 5)


# ─────────────────────────────────────────────────────────────────────────────
# SECURITY — Importados de api.dependencies
# ─────────────────────────────────────────────────────────────────────────────
from api.dependencies import get_current_user, limiter  # noqa: E402

# ─────────────────────────────────────────────────────────────────────────────
# MODELOS DE REQUEST — Auditoria (existentes)
# ─────────────────────────────────────────────────────────────────────────────

class AuditarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pasta_empresa: str = Field(
        ...,
        description="Caminho para pasta com PDFs da empresa",
        examples=["../samples/doc_calculo/CANAVEZI"],
    )


class AuditarBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pasta_base: str = Field(
        ...,
        description="Pasta base contendo subpastas de empresas",
        examples=["../samples/doc_calculo"],
    )




# ─────────────────────────────────────────────────────────────────────────────
# MODELOS DE REQUEST — Análise manual (sem PDF)
# ─────────────────────────────────────────────────────────────────────────────

class AnaliseManualRequest(BaseModel):
    """
    Payload para cálculo tributário direto — sem extração de PDF.
    Todos os campos espelham EmpresaFornecedora + EmpresaCompradora + OperacaoFiscal.
    Decimal serializado como string para zero perda de precisão.
    """
    model_config = ConfigDict(extra="forbid", json_encoders={Decimal: str})

    # ── EmpresaFornecedora ────────────────────────────────────────────────────
    cnpj: str = Field(..., description="CNPJ com ou sem pontuação")

    @field_validator("cnpj")
    @classmethod
    def validar_cnpj_manual(cls, v: str) -> str:
        """Valida CNPJ na entrada manual."""
        res = validar_cnpj(v)
        if not res.ok:
            raise ValueError(f"CNPJ Invalido: {', '.join(res.errors)}")
        return re.sub(r'[\s.\-/]', '', v.strip())
    razao_social: str = Field(..., min_length=2, description="Razão social completa")
    regime: Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI"] = Field(
        ..., description="Regime tributário"
    )
    cnae_principal: str = Field(..., description="CNAE principal (7 dígitos)")
    uf_origem: str = Field(..., description="UF de origem (2 letras)")

    @field_validator("uf_origem")
    @classmethod
    def validar_uf_manual(cls, v: str) -> str:
        """Valida UF na entrada manual."""
        res = validar_uf(v)
        if not res.ok:
            raise ValueError(f"UF Invalida: {', '.join(res.errors)}")
        return v.strip().upper()

    @field_validator("cnae_principal")
    @classmethod
    def validar_cnae_manual(cls, v: str) -> str:
        """Valida CNAE na entrada manual."""
        res = validar_cnae(v)
        if not res.ok:
            raise ValueError(f"CNAE Invalido: {', '.join(res.errors)}")
        return re.sub(r'[\s.\-/]', '', v.strip())
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
    # ERR-037 — Literal fechado. Evita string livre ("NAO_INFORMADO" fixo
    # enviado pelo frontend não é mais aceito como único valor). O motor
    # registra o regime na trilha mesmo quando NAO_INFORMADO.
    regime_comprador: Literal[
        "SIMPLES", "PRESUMIDO", "REAL", "MEI", "NAO_INFORMADO"
    ] = Field(
        default="NAO_INFORMADO",
        description=(
            "Regime tributário do comprador "
            "(LC 214/2025 Art. 47 §2º). NAO_INFORMADO = pior caso."
        ),
    )
    uf_destino: str = Field(default="SP", description="UF de destino (2 letras; padrão: SP)")

    # ── OperacaoFiscal ────────────────────────────────────────────────────────
    data_emissao: str = Field(
        ..., description="Data de emissão ISO (YYYY-MM-DD) — deve estar em 2026-2033"
    )
    valor_operacao: Decimal = Field(..., gt=Decimal("0"), description="Valor da operação em R$")
    ncm_nbs: str = Field(default="00000000", description="NCM/NBS (8 dígitos; padrão: 00000000)")
    # ERR-038 — Literal granular; Split Payment só dispara em formas com PSP
    # (LC 214/2025 Art. 353 §1º). PIX_DIRETO (banco-a-banco) e DINHEIRO ficam fora.
    forma_recebimento: Literal[
        "DINHEIRO", "PIX_DIRETO", "PIX_VIA_PSP", "BOLETO", "CARTAO",
    ] = Field(
        default="PIX_VIA_PSP",
        description=(
            "Forma de recebimento — impacta Split Payment "
            "(LC 214/2025 Art. 353 §1º). PIX_DIRETO/DINHEIRO não disparam."
        ),
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
    # ERR-036 — Campo `beneficio_fiscal_antigo` removido na Fase 3.2.
    # Era DECORATIVO: o valor nunca entrava na base de cálculo. O phase-out
    # do ADCT Art. 92-A §3º (redução 20%/ano a partir de 2029) exige tabela
    # FROZEN por ano + fonte específica da categoria — entregue na fase que
    # modelar benefícios ICMS herdados (Fase 4+). Pydantic extra="forbid"
    # rejeita o campo com 422.

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

    # ── Guards de consistência fiscal (ERR-024) ────────────────────────────────
    @model_validator(mode="after")
    def validar_consistencia_fiscal(self):
        """
        Guards de entrada — MAX_FISCAL_02 (toda regra tem amparo).

        Bloqueia cenários em que o cálculo downstream daria resultado
        semanticamente errado sem que o operador perceba. Cada bloqueio
        tem citação legal obrigatória — nada de `or`-fallback silencioso.

        Cenários bloqueados:
          1. MEI com faturamento_12m > teto anual (LC 123/2006 Art. 18-A §1º).
             §§5º-7º obrigam desenquadramento automático — rodar cálculo MEI
             com receita acima do teto é erro conceitual, a empresa já é Simples.
          2. MEI sem categoria_mei explícita (LC 123/2006 Art. 18-A §§3º I-III).
             Categoria define DAS fixo distinto (COMERCIO/INDUSTRIA/SERVICOS/
             COMERCIO_SERVICOS). Fallback silencioso viola MAX_FISCAL_02.
          3. percentual_b2b != 100 com tipo_comprador ≠ MISTO
             (LC 214/2025 Art. 47 II + Art. 48). Crédito IBS/CBS só em B2B
             contribuinte — misto exige tipo=MISTO explícito para não
             contaminar a recomendação Opt-Out.
        """
        # Import local para evitar ciclo e aproveitar a constante FROZEN do motor.
        # Fonte única: core.regimes.mei.TETO_ANUAL_MEI (LC 123/2006 Art. 18-A §1º).
        from core.regimes.mei import TETO_ANUAL_MEI

        # 1. MEI acima do teto
        if self.regime == "MEI" and self.faturamento_12m > TETO_ANUAL_MEI:
            raise ValueError(
                f"MEI com faturamento_12m={self.faturamento_12m} > teto "
                f"R$ {TETO_ANUAL_MEI} (LC 123/2006 Art. 18-A §1º). "
                "Empresa desenquadrada para Simples Nacional (§§5º-7º). "
                "Use regime='SIMPLES'."
            )

        # 2. MEI sem categoria — bloqueia fallback silencioso
        if self.regime == "MEI" and self.categoria_mei is None:
            raise ValueError(
                "MEI exige categoria_mei explícita "
                "(COMERCIO|INDUSTRIA|SERVICOS|COMERCIO_SERVICOS). "
                "LC 123/2006 Art. 18-A §§3º I a III — cada categoria tem "
                "DAS fixo distinto (INSS 5% SM + ICMS R$1 ou ISS R$5)."
            )

        # 3. percentual_b2b fora de MISTO — incoerência semântica
        if self.tipo_comprador != "MISTO" and self.percentual_b2b != Decimal("100"):
            raise ValueError(
                f"percentual_b2b={self.percentual_b2b} só é válido com "
                f"tipo_comprador='MISTO'. Para tipo='{self.tipo_comprador}' "
                "use percentual_b2b=100 (LC 214/2025 Art. 47 II + Art. 48 — "
                "crédito IBS/CBS só existe em operação B2B contribuinte)."
            )

        return self


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


# _extrair_user_id: helper universal movido para api/dependencies.extrair_user_id
# como parte do fix ERR-049 (ownership latentemente quebrado). Mantém alias local
# por compatibilidade com referências internas deste módulo.
from api.dependencies import extrair_user_id as _extrair_user_id  # noqa: E402


def _registrar_erro_parser(origem: str, exc: Exception, diagnostico: dict) -> None:
    """
    Registra falha não-fatal de parser em logger + diagnostico._erros.

    Padrão unificado ERR-021/025 — o rastro da falha chega ao dossiê jurídico
    e ao response do frontend. Substitui o antigo `except Exception: logger.warning(...)`
    silencioso que descartava exceptions sem deixar prova de que o parser falhou.

    Amparo legal:
      - CTN Art. 142 (motivação do lançamento — rastro deve refletir falhas)
      - LGPD Art. 37 (registro de operações de tratamento)
      - LC 214/2025 Art. 45 §3º (integridade da trilha de apuração IBS/CBS)
      - Lei 8.137/1990 Art. 1º II (evita dolo eventual por omissão de rastro)

    Args:
        origem: rótulo curto do parser (ex.: "parser_xml_nfe", "parser_csv_folha").
        exc: exception capturada no try/except do chamador.
        diagnostico: dict mutável — recebe append em `_erros` (cria a lista se ausente).
    """
    logger.warning(
        "Falha parser %s: %s — %s", origem, type(exc).__name__, exc, exc_info=True,
    )
    diagnostico.setdefault("_erros", []).append({
        "origem": origem,
        "tipo": type(exc).__name__,
        "mensagem": str(exc),
    })


def _persistir_diagnostico_best_effort(
    fornecedora: Any,
    diagnostico: dict,
    user_id: Optional[int],
    periodo: Optional[str] = None,
) -> None:
    """
    Persiste EmpresaDB + DiagnosticoDB após análise bem-sucedida.

    ERR-051 (Fase 5): salvar_diagnostico nunca era chamado nos handlers
    de análise → DB ficava permanentemente vazio, /auditorias sempre []
    em produção. Fix: chamar aqui em bloco best-effort.

    CONTRATO:
      - Falha NÃO quebra a análise — só loga warning.
      - user_id None → não persiste (não dá pra popular ownership).
      - Qualquer exception é absorvida (Zero-Trust: DB offline,
        FK inválida, race no create_all de teste, etc).

    Amparo:
      - MAX_FISCAL_05 — rastreabilidade documental.
      - LGPD Art. 37 — registro operacional.
      - CTN Art. 173 — retenção 5 anos começa aqui.
    """
    if user_id is None:
        # Sem dono identificável: não adianta persistir — a listagem do
        # histórico filtra por user_id e registros órfãos viram lixo.
        return

    try:
        from database import salvar_diagnostico as _sd
        from database import salvar_empresa

        empresa_db = salvar_empresa(fornecedora)

        # Extrai valores do diagnóstico. Todos vêm como str (serializados)
        # ou Decimal dependendo de qual lugar do fluxo chama. Convertemos
        # pra Decimal defensivamente — zero float.
        das_raw = diagnostico.get("das_mensal") or diagnostico.get("valor_das") or "0"
        aliq_raw = diagnostico.get("aliquota_efetiva") or "0"
        rbt12_raw = (
            diagnostico.get("rbt12")
            or (diagnostico.get("_extracao") or {}).get("rbt12")
            or "0"
        )
        regime = diagnostico.get("regime") or getattr(fornecedora, "regime", "SIMPLES")

        # Período: prioriza override (do handler), depois campo do diagnóstico,
        # depois extração de data_emissao se houver.
        competencia = periodo or diagnostico.get("competencia")
        if not competencia:
            data_emissao = diagnostico.get("data_emissao")
            if isinstance(data_emissao, str) and len(data_emissao) >= 7:
                competencia = data_emissao[:7]
        if not competencia:
            # Fallback: primeiro mês do ano base do diagnóstico; se tudo
            # falhar, usa ano corrente. Nunca deve explodir por isso.
            from datetime import date as _date
            competencia = _date.today().strftime("%Y-%m")

        _sd(
            empresa_id=empresa_db.id,
            competencia=competencia,
            resultado=diagnostico,
            das_mensal=Decimal(str(das_raw)),
            aliquota_efetiva=Decimal(str(aliq_raw)),
            rbt12=Decimal(str(rbt12_raw)),
            regime=str(regime),
            uploaded_by_user_id=user_id,
        )
    except Exception as exc:
        # Persistência é best-effort — falha NÃO derruba o endpoint.
        # Logamos o tipo sem exc_info=True pra não poluir em dev com
        # tracebacks de DB em memória durante testes.
        logger.warning(
            "Persistencia de diagnostico falhou | tipo=%s | motivo=%s",
            type(exc).__name__,
            str(exc)[:200],
        )


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

app = FastAPI(
    title="Motor Tributário Conect 2026-2033",
    description=(
        "API de Auditoria Tributária Transicional (EC 132/2023 | LC 123/2006 | LC 214/2025). "
        "Extrai PDFs do e-CAC via Claude Vision e compara DAS calculado vs DAS pago."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

from api.routers import auth, usuarios  # noqa: E402

app.include_router(auth.router)
app.include_router(usuarios.router)
from api.routers import auditoria, integracoes  # noqa: E402

app.include_router(integracoes.router)
app.include_router(auditoria.router)
# Fase 5 — páginas fantasmas vivas: histórico + configurações
from api.routers import configuracoes, historico  # noqa: E402

app.include_router(historico.router)
app.include_router(configuracoes.router)

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
    from core.tabelas_simples import determinar_anexo_por_cnae_com_fonte, estimar_perfil_b2b
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
# ENDPOINTS — Dashboard Summary (preparação para o novo frontend)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/dashboard/summary", tags=["dashboard"])
def dashboard_summary(_current_user: dict = Depends(get_current_user)):
    """
    Retorna um resumo consolidado das atividades para o Dashboard Premium.
    Gera dados dinâmicos com base nas auditorias já realizadas no sistema.
    """
    try:
        metrics = database.get_dashboard_metrics()
    except Exception as exc:
        logger.error("Erro ao carregar métricas do dashboard: %s", exc)
        # Fallback para não quebrar a UI
        return {
            "stats": {"empresas_ativas": 0, "economia_apurada": "0,00", "alertas_risco": 0, "precisao": 0.0},
            "recent_audits": []
        }

    # TODO: nibo_sync — aguarda parceria Nibo
    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS — Análise manual (autenticado)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/analise/manual", response_model=DiagnosticoResponse, tags=["analise"])
def analise_manual(
    req: AnaliseManualRequest,
    current_user: dict = Depends(get_current_user),
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
            # ERR-024: fallback silencioso removido — o @model_validator acima
            # garante que categoria_mei nunca é None quando regime=MEI.
            # Para os demais regimes o próprio EmpresaFornecedora ignora o campo.
            categoria_mei=req.categoria_mei,
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
        # ERR-036 — `beneficio_fiscal_antigo` removido do schema.
        operacao = OperacaoFiscal(
            data_emissao=data_emissao_parsed,
            valor_operacao=req.valor_operacao,
            ncm_nbs=req.ncm_nbs,
            forma_recebimento=req.forma_recebimento,
            rpa_mensal=req.rpa_mensal,
            tinha_st_icms=req.tinha_st_icms,
            reducao_cbs_ibs=req.reducao_cbs_ibs,
            lucro_real_mensal=req.lucro_real_mensal,
            creditos_pis_cofins=req.creditos_pis_cofins,
            produto_importado=req.produto_importado,
        )

    except PydanticValidationError as exc:
        # Pydantic detalha cada campo inválido — repassar ao cliente.
        # Pydantic V2 pode incluir em `ctx.error` a exception original (ValueError,
        # date, Decimal) que não são JSON-serializáveis pelo json.dumps do Starlette.
        # Sanitizamos para primitivos antes de mandar.
        from fastapi.encoders import jsonable_encoder
        erros = exc.errors(include_url=False, include_input=False)
        raise HTTPException(status_code=422, detail=jsonable_encoder(erros))
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

        # Fase 4 Segurança/LGPD: guarda envelope em buffer in-memory e devolve
        # analise_id opaco. Frontend guarda só o id em sessionStorage (não-PII)
        # e hidrata PII em memória via GET /analise/sessao/{id}.
        # LGPD Art. 6º V (minimização) — PII fora do storage do browser.
        user_id = _extrair_user_id(current_user)
        try:
            from services.analise_buffer import get_buffer
            if user_id is not None:
                analise_id = get_buffer().armazenar(
                    envelope=_serializar_decimal(payload),
                    user_id=user_id,
                )
                payload["analise_id"] = analise_id
        except Exception as exc_buf:
            # Buffer é best-effort — falha nele NÃO quebra o /analise/manual.
            # Frontend detecta ausência de analise_id e cai em modo legado.
            logger.warning(
                "Falha ao armazenar analise em buffer | tipo=%s",
                type(exc_buf).__name__,
            )

        # ERR-051 (Fase 5): wire de persistência pro histórico do user.
        # Best-effort — falha não derruba o endpoint.
        competencia_req = (
            req.data_emissao[:7] if isinstance(req.data_emissao, str)
            and len(req.data_emissao) >= 7 else None
        )
        _persistir_diagnostico_best_effort(
            fornecedora=fornecedora,
            diagnostico=diagnostico,
            user_id=user_id,
            periodo=competencia_req,
        )

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
# GET /analise/sessao/{analise_id} — Hidratação do resultado em memória
#
# Fase 4 Segurança/LGPD: frontend guarda só um id opaco em sessionStorage.
# Aqui ele troca o id pelo envelope {diagnostico, pii}. PII nunca passa no
# storage do browser — vive apenas em memória (window.__MC_SESSION__).
#
# Ownership obrigatório (ERR-018 IDOR):
#   Buffer valida que user_id do JWT == dono do envelope. Caso contrário,
#   devolve 404 — mesma resposta que "id inexistente", para não vazar a
#   existência do registro a terceiros.
#
# TTL curto (10 min padrão): cobre navegação + geração de PDF/dossiê.
# Após expirar, frontend faz redirect para /analise_unificada.html (nova análise).
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/analise/sessao/{analise_id}", tags=["analise"])
def obter_analise_sessao(
    analise_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Devolve envelope {diagnostico, pii} de uma sessão de análise ativa.

    Códigos:
      200 — sessão válida, dono correto, envelope devolvido
      401 — sem JWT / token inválido (tratado por get_current_user)
      404 — sessão inexistente, expirada OU pertence a outro user
            (mesma resposta de propósito — ownership IDOR-safe)
    """
    # Sanitização leve: o id gerado é hex 32 chars, não deve conter nada além.
    # Rejeita cedo para evitar dores com ids longos vindos de atacantes.
    if not analise_id or len(analise_id) > 64 or not analise_id.isalnum():
        raise HTTPException(status_code=404, detail="Sessão de análise não encontrada.")

    user_id = _extrair_user_id(current_user)
    if user_id is None:
        # Sem user_id válido, ownership não faz sentido — responde 404.
        raise HTTPException(status_code=404, detail="Sessão de análise não encontrada.")

    # ── IP da requisição — sem PII, usado só para correlação em log/auditoria.
    # Amparo: LGPD Art. 7º VI (legítimo interesse — segurança) + Art. 37
    # (registro de operações de tratamento). NUNCA logar CNPJ ou razão social.
    ip_origem = request.client.host if request and request.client else None

    from services.analise_buffer import get_buffer
    buffer = get_buffer()
    envelope = buffer.recuperar(analise_id, user_id)

    if envelope is None:
        # Detecta se é IDOR (dono existe, é outro) ou 404 legítimo
        # (id inexistente / expirado). Só registra tentativa em auditoria
        # no caso IDOR — 404 legítimo não é incidente.
        dono = buffer.get_dono(analise_id)
        if dono is not None and dono != user_id:
            # Tentativa de acesso cruzado — LGPD Art. 46 §1º + 48 (evidência 72h ANPD)
            try:
                from database.repositories.auditoria_tentativa_repo import (
                    registrar_tentativa_acesso,
                )
                registrar_tentativa_acesso(
                    analise_id_prefix=analise_id[:8],
                    user_id_tentando=user_id,
                    user_id_dono=dono,
                    ip=ip_origem or "unknown",
                    endpoint="/analise/sessao",
                )
            except Exception:
                # Falha ao persistir a tentativa não pode quebrar o 404.
                # O warning em analise_buffer.recuperar() já deixou rastro.
                logger.exception(
                    "Falha ao registrar tentativa de acesso | analise_id=%s... | user_id=%s",
                    analise_id[:8], user_id,
                )
        raise HTTPException(status_code=404, detail="Sessão de análise não encontrada.")

    # ── Log estruturado de hidratação bem-sucedida (ressalva Luiz Fase 4.1 #2).
    # LGPD Art. 5º X + Art. 37 — acesso/reprodução de PII é operação de
    # tratamento registrável. Campos: prefixo do id (não-reversível), user_id,
    # ip, evento. SEM CNPJ, SEM razão social — o envelope foi acessado, mas
    # o log não repassa PII.
    logger.info(
        "HIDRATACAO_SESSAO | analise_id=%s | user_id=%s | ip=%s | evento=%s",
        analise_id[:8],
        user_id,
        ip_origem,
        "HIDRATACAO_SESSAO",
    )
    return JSONResponse(content=envelope)


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




@app.get(
    "/documentos-requeridos",
    summary="Lista cards de documentos com período-base pontual",
    tags=["Análise"],
    response_model=CardsResponse,
)
async def documentos_requeridos(
    ano_alvo: int = Query(
        ...,
        ge=ANO_MIN,
        le=ANO_MAX,
        description=f"Ano-alvo da análise ({ANO_MIN}..{ANO_MAX} — cronograma IVA EC 132/2023)",
    ),
    perfil: Literal["B2B_CONTRIBUINTE", "B2C_CONSUMIDOR_FINAL", "MISTO"] = Query(
        ...,
        description="Perfil do comprador",
    ),
    regime: Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI"] = Query(
        ...,
        description="Regime tributário da empresa analisada",
    ),
    mes_corte: int = Query(
        12,
        ge=1,
        le=12,
        description="Mês de fechamento (default 12 = corte anual em 31/dez)",
    ),
) -> CardsResponse:
    """
    Retorna a lista de documentos requeridos para a análise com período-base
    derivado automaticamente do ano-alvo + mês-corte.

    Exemplo: `GET /documentos-requeridos?ano_alvo=2026&perfil=B2B_CONTRIBUINTE&regime=SIMPLES`
    → cards pedem XMLs de `2025-01..2025-12`, DAS de `Dezembro/2025`, etc.

    Amparo: MAX_FISCAL_03 (declarar data base ANTES do cálculo) +
    LC 123/2006 Art. 3º §1º (RBT12 = 12 meses imediatamente anteriores).

    Endpoint público (sem JWT) — não vaza dados, só configuração.
    """
    try:
        periodo = derivar_periodo(ano_alvo, mes_corte=mes_corte)
        cards = montar_cards(perfil, regime, periodo)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    return CardsResponse(
        ano_alvo=ano_alvo,
        periodo_base=periodo.to_dict(),
        perfil=perfil,
        regime=regime,
        cards=cards,
    )


@app.post(
    "/analise/pdf",
    response_model=DiagnosticoResponse,
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

    # Operador autenticado — ERR-049: extrair_user_id aceita "sub" (JWT real)
    # e "id" (fixture de teste). Antes só aceitava "id", user_id sempre None
    # em produção, quebrando auditoria documental.
    user_id = _extrair_user_id(current_user)

    # Pipeline de extração + auditoria documental
    try:
        from services.extrator_pdfs import processar_pdfs_bytes

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
                _registrar_erro_parser("parser_xml_nfe", exc_nfe, diagnostico)

        if conteudos_xml_nfce:
            try:
                from parsers.xml_nfce import parsear_lote_nfce
                nfce_data = parsear_lote_nfce(conteudos_xml_nfce)
            except Exception as exc_nfce:
                _registrar_erro_parser("parser_xml_nfce", exc_nfce, diagnostico)

        if conteudos_csv:
            try:
                from parsers.csv_folha import parsear_csv_folha
                # Concatenar múltiplos CSVs (raro, mas possível)
                csv_bytes = b"\n".join(conteudos_csv)
                folha_data = parsear_csv_folha(csv_bytes)
            except Exception as exc_csv:
                _registrar_erro_parser("parser_csv_folha", exc_csv, diagnostico)

        # SPED Domínio Contábil — ECD (lançamentos) e EFD-Contribuições (PIS/COFINS)
        ecd_data = None
        efd_contrib_data = None

        if conteudos_sped_ecd:
            try:
                from parsers.sped_ecd import parsear_sped_ecd
                # Parse só o primeiro — múltiplos ECDs em um request é improvável
                ecd_data = parsear_sped_ecd(conteudos_sped_ecd[0])
            except Exception as exc_ecd:
                _registrar_erro_parser("parser_sped_ecd", exc_ecd, diagnostico)

        if conteudos_sped_efd_contrib:
            try:
                from parsers.sped_efd_contrib import parsear_sped_efd_contrib
                efd_contrib_data = parsear_sped_efd_contrib(conteudos_sped_efd_contrib[0])
            except Exception as exc_efd:
                _registrar_erro_parser("parser_sped_efd_contrib", exc_efd, diagnostico)

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
                from services.storage_cifrado import cifrar_e_persistir, hash_documento
                cnpj_empresa = (payload.get("pii") or {}).get("cnpj", "")
                if cnpj_empresa:
                    hash_doc = hash_documento(conteudo_extra)
                    path_cifrado = cifrar_e_persistir(conteudo_extra, cnpj_empresa)
                    doc_id = registrar_documento_auditoria(
                        hash_sha256=hash_doc,
                        empresa_cnpj=cnpj_empresa,
                        nome_original=nome_extra,
                        mime_type=mime_extra,
                        tamanho_bytes=len(conteudo_extra),
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
                # Passa o nome do arquivo como parte da origem para rastreabilidade.
                _registrar_erro_parser(
                    f"auditoria_doc_extra:{nome_extra}", exc_audit, diagnostico,
                )

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
                _registrar_erro_parser("termo_aceite_lgpd", exc_aceite, diagnostico)

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

        # ─── Validações e crosschecks (módulo unificado) ────────────────────
        try:
            from decimal import Decimal as _D

            from validacoes import avaliar_das, detectar_anomalias

            trilha = diagnostico.get("trilha_auditoria") or []

            # 1. Detecção de anomalias
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

            alertas = detectar_anomalias(
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
            trilha.extend(alertas)

            # 2. Semáforo DAS (quando calc e pago presentes)
            das_calc_raw = diagnostico.get("das_calculado") or diagnostico.get("valor_das")
            das_pago_raw = (diagnostico.get("_extracao", {}) or {}).get("das_pago_e_cac")
            if das_calc_raw and das_pago_raw:
                try:
                    semaforo = avaliar_das(_D(str(das_calc_raw)), _D(str(das_pago_raw)))
                    diagnostico["_semaforo_das"] = semaforo
                    trilha.append(semaforo)
                except Exception as exc_sem:
                    logger.warning("Falha ao avaliar semáforo DAS: %s", exc_sem)

            # HMAC removido daqui — assinatura apenas na persistência definitiva
            diagnostico["trilha_auditoria"] = trilha
        except Exception as exc_obs:
            # Antes: swallow silencioso. Agora: loga com stack + expõe _erros
            # ao frontend para diagnóstico transparente (filosofia Zero Trust).
            logger.warning(
                "Falha nas validacoes/anomalias em /analise/pdf: %s — %s",
                type(exc_obs).__name__, exc_obs, exc_info=True,
            )
            diagnostico.setdefault("_erros", []).append({
                "origem": "validacoes_anomalias",
                "tipo": type(exc_obs).__name__,
                "mensagem": str(exc_obs),
            })

        # Fase 4 Segurança/LGPD: analise_id opaco no envelope.
        # Mesmo padrão de /analise/manual — PII vive só em memória do backend
        # e na memória (window.__MC_SESSION__) do frontend depois da hidratação.
        try:
            from services.analise_buffer import get_buffer
            if user_id is not None:
                analise_id = get_buffer().armazenar(
                    envelope=_serializar_decimal(payload),
                    user_id=user_id,
                )
                payload["analise_id"] = analise_id
        except Exception as exc_buf:
            logger.warning(
                "Falha ao armazenar analise PDF em buffer | tipo=%s",
                type(exc_buf).__name__,
            )

        # ERR-051 (Fase 5): persistência do histórico no /analise/pdf.
        # Diferente do /manual, aqui a "fornecedora" sai da extração. Tentamos
        # reconstruí-la com os campos mínimos; se faltar algo crítico (CNPJ
        # inválido, CNAE ausente), o helper absorve a exception. Best-effort.
        #
        # ACHADO-L1 (Fase 5.1 — Luiz Moreira): guard CNAE REAL obrigatório.
        # Antes, a ausência de CNAE caía em default "4711301" (Comércio
        # varejista com predominância de produtos alimentícios), mas a empresa
        # poderia ser prestadora de serviços (Anexo V) ou construção (Anexo IV).
        # CNAE fictício em histórico persistido = passivo de auditoria e
        # viola MAX_FISCAL_02 ("toda regra cita base legal"). Sem CNAE da
        # fonte, não escrevemos no histórico — histórico é PROVA, não suposição.
        # Amparo: LC 123/2006 Art. 18 §1º-§24 (Anexo depende do CNAE).
        try:
            pii_block = payload.get("pii") or {}
            cnpj_ext = pii_block.get("cnpj") or diagnostico.get("cnpj")
            cnae_real = (
                diagnostico.get("cnae_principal")
                or (diagnostico.get("_extracao") or {}).get("cnae")
            )
            uf_real = (
                diagnostico.get("uf_origem")
                or (diagnostico.get("_extracao") or {}).get("uf")
            )
            if not cnae_real:
                # Sem CNAE confiável, não persistimos. Não inventamos.
                logger.info(
                    "Persistencia /analise/pdf pulada | motivo=cnae_ausente | user_id=%s",
                    user_id,
                )
            elif cnpj_ext and user_id is not None:
                from core.motor_tributario import EmpresaFornecedora as _EF
                fornecedora_pdf = _EF(
                    cnpj=cnpj_ext,
                    razao_social=(pii_block.get("razao_social") or "Cliente e-CAC"),
                    regime=diagnostico.get("regime", "SIMPLES"),
                    cnae_principal=cnae_real,
                    uf_origem=(uf_real or "SP"),
                    faturamento_12m=Decimal(str(
                        diagnostico.get("rbt12")
                        or (diagnostico.get("_extracao") or {}).get("rbt12")
                        or "0"
                    )),
                    anexo_simples=diagnostico.get("anexo_simples"),
                )
                _persistir_diagnostico_best_effort(
                    fornecedora=fornecedora_pdf,
                    diagnostico=diagnostico,
                    user_id=user_id,
                )
        except Exception as exc_persist:
            logger.warning(
                "Persistencia /analise/pdf falhou | tipo=%s",
                type(exc_persist).__name__,
            )

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
# STATIC FILES — UI servida em /ui/ para não colidir com rotas da API
# Montagem no final garante que todos os routes têm prioridade.
# Acesse: http://localhost:8000/ui/login.html
# ─────────────────────────────────────────────────────────────────────────────
if _UI_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")
else:
    logger.warning("Pasta UI não encontrada em %s — interface web indisponível.", _UI_DIR)

