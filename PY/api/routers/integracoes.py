import logging
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from api.dependencies import extrair_user_id, get_current_user
from database import tem_acesso_cnpj
from database.repositories.auditoria_tentativa_repo import registrar_tentativa_acesso

# ─────────────────────────────────────────────────────────────────────────────
# Constantes de motivo público (mensagens neutras, sem vazar caminho/senha)
# ─────────────────────────────────────────────────────────────────────────────
_MOTIVO_INATIVA = "Integração inativa — configure credenciais."
_MOTIVO_INDISPONIVEL = "Integração indisponível neste ambiente."
_MOTIVO_OK = None  # Status OK → motivo_erro_publico = null

logger = logging.getLogger("motor_conect.api")


def _verificar_ownership_cnpj(
    cnpj: str,
    current_user: dict,
    request: Optional[Request],
    endpoint: str,
) -> None:
    """
    Guard de ownership horizontal (ERR-018.b).

    Admin bypassa a verificação. Usuários comuns precisam de ao menos um
    diagnóstico ou documento vinculado ao CNPJ. Bloqueia com 403 e registra
    tentativa de acesso cruzado (LGPD Art. 46 §1º + Art. 6º VII).

    Amparo: LGPD Art. 46 §1º + Art. 6º VII (segurança no tratamento).
            CTN Art. 198 (sigilo fiscal, fundamento subsidiário).
    """
    # Admin tem acesso a qualquer CNPJ — registra para rastreabilidade (LGPD Art. 37)
    if current_user.get("role") == "admin":
        logger.info(
            "ADMIN_CNPJ_ACCESS | user_id=%s | endpoint=%s",
            extrair_user_id(current_user),
            endpoint,
        )
        return

    user_id = extrair_user_id(current_user)
    if user_id is None:
        raise HTTPException(status_code=403, detail="Acesso negado.")

    apenas_digitos = re.sub(r"\D", "", cnpj or "")
    if not tem_acesso_cnpj(user_id, apenas_digitos):
        ip = "unknown"
        if request is not None:
            try:
                ip = request.client.host if request.client else "unknown"
            except Exception:
                pass
        # Prefixo do CNPJ como id de recurso (não vaza o CNPJ completo)
        registrar_tentativa_acesso(
            analise_id_prefix=apenas_digitos[:8],
            user_id_tentando=user_id,
            user_id_dono=None,
            ip=ip,
            endpoint=endpoint,
        )
        raise HTTPException(
            status_code=403,
            detail="Acesso negado. Você não tem diagnóstico ou documento vinculado a este CNPJ.",
        )

# Auth aplicada no router inteiro — todo endpoint herda get_current_user.
# Adicionar novo endpoint aqui fica AUTOMATICAMENTE protegido.
# Para expor algo público, criar outro APIRouter sem essa dependency.
#
# Endpoints que precisam do dict do usuário (sieg/integra pra user_id) declaram
# `current_user: dict = Depends(get_current_user)` no próprio handler — FastAPI
# cacheia a dependência por request (use_cache=True default), então
# get_current_user roda UMA vez mesmo com duplicação. Zero overhead.
router = APIRouter(
    tags=["Integrações"],
    dependencies=[Depends(get_current_user)],
)

# --- SIEG ---

class SiegSincronizarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cnpj: str = Field(..., description="CNPJ (14 dígitos, com ou sem pontuação)")
    data_inicio: Optional[str] = Field(None, description="ISO YYYY-MM-DD")
    data_fim: Optional[str] = Field(None, description="ISO YYYY-MM-DD")
    ano_base: Optional[int] = Field(None, ge=2020, le=2033)
    xml_type: int = Field(1, description="1=NFe (default), 2=CTe, 3=NFSe, 4=NFCe")

@router.post("/sieg/sincronizar")
async def sieg_sincronizar(
    payload: SiegSincronizarRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
) -> JSONResponse:
    _verificar_ownership_cnpj(payload.cnpj, current_user, request, "/sieg/sincronizar")
    from datetime import date as _date
    if payload.ano_base:
        if payload.data_inicio or payload.data_fim:
            raise HTTPException(status_code=422, detail="ano_base é mutuamente exclusivo com data_inicio/data_fim")
        data_inicio = _date(payload.ano_base, 1, 1)
        data_fim = _date(payload.ano_base, 12, 31)
    else:
        if not payload.data_inicio or not payload.data_fim:
            raise HTTPException(status_code=422, detail="Forneça ano_base OU (data_inicio E data_fim)")
        try:
            data_inicio = _date.fromisoformat(payload.data_inicio)
            data_fim = _date.fromisoformat(payload.data_fim)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Data inválida: {exc}") from exc

    from integrations.sieg_service import XML_TYPES_VALIDOS, SiegCredentialError, SiegError, SiegService

    if payload.xml_type not in XML_TYPES_VALIDOS:
        raise HTTPException(status_code=422, detail=f"xml_type inválido — esperado {list(XML_TYPES_VALIDOS)}")

    try:
        svc = SiegService()
    except SiegCredentialError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        resultado = svc.sincronizar(
            cnpj=payload.cnpj,
            data_inicio=data_inicio,
            data_fim=data_fim,
            xml_type=payload.xml_type,
            # ERR-049 (Fase 5): extrair_user_id lê "sub" (JWT real) OU "id"
            # (fixture). current_user.get("id") sempre devolvia None em prod.
            uploaded_by_user_id=extrair_user_id(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SiegError as exc:
        raise HTTPException(status_code=502, detail=f"Sieg: {exc}") from exc

    return JSONResponse(content=resultado.to_dict(), status_code=200)

# --- INTEGRA CONTADOR ---

class IntegraSincronizarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cnpj: str = Field(..., description="CNPJ do cliente")
    ano_base: Optional[int] = Field(None, ge=2020, le=2033)
    periodos: Optional[list[str]] = Field(None)
    tipos: list[Literal["pgdasd", "das"]] = Field(default_factory=lambda: ["pgdasd", "das"])

    def resolver_periodos(self) -> list[str]:
        if self.ano_base is not None and self.periodos:
            raise ValueError("Forneça 'ano_base' OU 'periodos', não ambos.")
        if self.ano_base is None and not self.periodos:
            raise ValueError("Forneça 'ano_base' ou 'periodos'.")
        if self.ano_base is not None:
            return [f"{self.ano_base}-{m:02d}" for m in range(1, 13)]
        return list(self.periodos or [])

@router.post("/integra/sincronizar")
async def integra_sincronizar(
    payload: IntegraSincronizarRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    _verificar_ownership_cnpj(payload.cnpj, current_user, request, "/integra/sincronizar")
    try:
        periodos = payload.resolver_periodos()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        from integrations.integra_adapter import IntegraAdapter, IntegraAuthError, IntegraCertError, IntegraError
        from integrations.integra_credentials import IntegraCredentialError, get_integra_credenciais
        from integrations.integra_ingestor import IntegraIngestor
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"Integra Contador indisponível (imports): {exc}")

    try:
        credenciais = get_integra_credenciais()
    except IntegraCredentialError as exc:
        raise HTTPException(status_code=503, detail=f"Integra Contador não configurado: {exc}")

    adapter = IntegraAdapter(credenciais)
    try:
        ingestor = IntegraIngestor(adapter)
        resultado = ingestor.sincronizar(
            cnpj=payload.cnpj,
            periodos=periodos,
            tipos=tuple(payload.tipos),
            # ERR-049 (Fase 5): idem sieg_sincronizar.
            uploaded_by_user_id=extrair_user_id(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except (IntegraCertError, IntegraAuthError, IntegraError) as exc:
        raise HTTPException(status_code=502, detail=f"Integra Contador: {exc}")
    finally:
        adapter.close()
    return {"ok": True, "resumo": resultado.to_dict()}

# --- E-CAC ---
try:
    from integrations.ecac_scraper import EcacScraper, load_pfx_to_pem
    _ECAC_AVAILABLE = True
except ImportError:
    _ECAC_AVAILABLE = False

@router.post("/integracoes/ecac/sync")
async def ecac_sync_a1(
    request: Request,
    cnpj: str = Form(...),
    senha_cert: str = Form(...),
    certificado_pfx: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    # ERR-018.b (Fase 5): guard de ownership — CTN Art. 198 + LGPD Art. 48.
    # Admin bypass implícito em _verificar_ownership_cnpj.
    _verificar_ownership_cnpj(cnpj, current_user, request, "/integracoes/ecac/sync")
    if not _ECAC_AVAILABLE:
        raise HTTPException(status_code=501, detail="Integração e-CAC indisponível neste ambiente.")
    try:
        pfx_bytes = await certificado_pfx.read()
        cert_data = load_pfx_to_pem(pfx_bytes, senha_cert)
        scraper = EcacScraper(cert_data)
        pdf_bytes = await scraper.get_pgdas_pdf(cnpj, "2026-01")
        return {
            "status": "success",
            "message": "Extração A1 do Gov.br concluída.",
            "diagnostics": {"pdf_bytes_length": len(pdf_bytes) if pdf_bytes else 0},
        }
    except (ValueError, OSError) as exc:
        # ValueError: senha do .pfx inválida, pfx corrompido, parâmetros.
        # OSError: falha de rede/arquivo.
        # Log com contexto técnico mas SEM PII (sem CNPJ completo, sem str(exc) bruto).
        logger.exception(
            "Falha previsível na extração e-CAC | tipo=%s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Não foi possível concluir a extração e-CAC. Verifique certificado e tente novamente.",
        )
    except Exception as exc:
        # Erro inesperado: loga completo internamente, devolve mensagem neutra.
        # str(exc) NUNCA vai pro cliente — pode conter path do .pfx, stack da lib, etc.
        logger.exception(
            "Erro não previsto em e-CAC | tipo=%s",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Integração Governamental indisponível. Contate o suporte.",
        )


# ─────────────────────────────────────────────────────────────────────────────
# GET /integracoes/status (Fase 5)
#
# Reporta estado das 3 integrações (SIEG, Integra Contador, e-CAC).
# SEM vazamento de credenciais/paths:
#   - ok: bool
#   - ultimo_sync: ISO timestamp OU null
#   - motivo_erro_publico: mensagem neutra OU null
#
# Ownership: status é GLOBAL — qualquer autenticado vê o mesmo retorno.
# Não vazamos telemetria por usuário aqui (fase futura).
#
# Detecção de estado:
#   - SIEG: chama get_api_key(). Se levanta SiegCredentialError → offline.
#   - Integra: chama get_integra_credenciais(). Idem.
#   - e-CAC: verifica se módulo ecac_scraper importa (dependências opcionais).
#
# NUNCA captura str(exc) no motivo público — exc pode carregar path do arquivo
# de chave / conteúdo de env var / etc. Usamos constantes neutras.
# ─────────────────────────────────────────────────────────────────────────────


class StatusIntegracao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    ultimo_sync: Optional[str] = Field(None, description="ISO 8601 ou null")
    motivo_erro_publico: Optional[str] = Field(
        None,
        description="Mensagem neutra sem vazar credencial/path",
    )


class IntegracoesStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sieg: StatusIntegracao
    integra: StatusIntegracao
    ecac: StatusIntegracao


def _check_sieg() -> StatusIntegracao:
    """
    Sonda SIEG — apenas presença de credencial. Não faz ping real (fora
    do escopo da Fase 5 — endpoint seria lento e cobrar custo externo).
    """
    try:
        from integrations.sieg_service import get_api_key
        _ = get_api_key()
        return StatusIntegracao(ok=True, ultimo_sync=None, motivo_erro_publico=_MOTIVO_OK)
    except Exception as exc:
        # Qualquer exceção → offline. Nunca vazamos str(exc) no retorno.
        logger.debug("SIEG status offline | tipo=%s", type(exc).__name__)
        return StatusIntegracao(
            ok=False,
            ultimo_sync=None,
            motivo_erro_publico=_MOTIVO_INATIVA,
        )


def _check_integra() -> StatusIntegracao:
    """Sonda Integra Contador — presença de certificado/credencial."""
    try:
        from integrations.integra_credentials import get_integra_credenciais
        _ = get_integra_credenciais()
        return StatusIntegracao(ok=True, ultimo_sync=None, motivo_erro_publico=_MOTIVO_OK)
    except Exception as exc:
        logger.debug("Integra status offline | tipo=%s", type(exc).__name__)
        return StatusIntegracao(
            ok=False,
            ultimo_sync=None,
            motivo_erro_publico=_MOTIVO_INATIVA,
        )


def _check_ecac() -> StatusIntegracao:
    """
    Sonda e-CAC — verifica se o módulo nativo (cryptography/cert) importou.
    O import é feito no topo do arquivo via try/except — se falhou,
    `_ECAC_AVAILABLE` fica False.
    """
    if _ECAC_AVAILABLE:
        return StatusIntegracao(ok=True, ultimo_sync=None, motivo_erro_publico=_MOTIVO_OK)
    return StatusIntegracao(
        ok=False,
        ultimo_sync=None,
        motivo_erro_publico=_MOTIVO_INDISPONIVEL,
    )


@router.get(
    "/integracoes/status",
    response_model=IntegracoesStatusResponse,
    summary="Status das integrações externas (SIEG / Integra / e-CAC)",
)
def integracoes_status() -> IntegracoesStatusResponse:
    """
    Retorna snapshot do estado das integrações.

    Contrato de segurança:
      - Nenhum campo devolve path de arquivo, env var, conteúdo de secret
        ou stack trace. Usamos constantes neutras pré-definidas.
      - `ultimo_sync` é null na Fase 5 — telemetria por integração
        ficou fora do escopo (fase posterior plugará).
    """
    return IntegracoesStatusResponse(
        sieg=_check_sieg(),
        integra=_check_integra(),
        ecac=_check_ecac(),
    )
