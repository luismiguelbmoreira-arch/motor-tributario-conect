import io
import logging
import zipfile
from datetime import datetime as _dt
from pathlib import Path as _Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from api.dependencies import extrair_user_id, get_current_user
from database import (
    buscar_documentos_por_cnpj,
    registrar_acesso_documento,
)
from services.storage_cifrado import anonimizar_cnpj, decifrar

logger = logging.getLogger("motor_conect.api")

router = APIRouter(tags=["Auditoria"])

@router.get(
    "/auditoria/prova/cnpj/{cnpj_digitos}",
    summary="Gera dossiê de prova ZIP com PDFs decifrados de um cliente",
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
    Cada PDF é decifrado on-the-fly e o acesso é registrado (LGPD Art. 37).
    """
    # Normaliza CNPJ: remove qualquer não-dígito, exige 14 dígitos
    apenas_digitos = "".join(c for c in (cnpj_digitos or "") if c.isdigit())
    if len(apenas_digitos) != 14:
        raise HTTPException(
            status_code=422,
            detail=f"CNPJ deve ter 14 digitos. Recebido: {len(apenas_digitos)}.",
        )

    # Formata para o formato canônico XX.XXX.XXX/XXXX-XX
    cnpj_formatado = (
        f"{apenas_digitos[:2]}.{apenas_digitos[2:5]}.{apenas_digitos[5:8]}"
        f"/{apenas_digitos[8:12]}-{apenas_digitos[12:]}"
    )
    cnpj = cnpj_formatado

    # Extrai user_id + IP para auditoria
    # ERR-049 (Fase 5): JWT real usa claim "sub". current_user.get("id")
    # sempre devolvia None em produção — dossiê ficava sem rastro do solicitante.
    user_id = extrair_user_id(current_user)

    ip = None
    if request is not None:
        try:
            ip = request.client.host if request.client else None
        except Exception:
            ip = None

    # Busca documentos do cliente
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
                nome_seguro = doc.nome_original.replace("/", "_").replace("\\", "_")
                zf.writestr(f"originais/{nome_seguro}", plaintext)
                hashes_txt.append(f"{doc.hash_sha256}  originais/{nome_seguro}")

                registrar_acesso_documento(
                    documento_id=doc.id,
                    motivo=motivo,
                    acessado_por_user_id=user_id,
                    ip=ip,
                )
            except Exception as exc:
                logger.error("Falha ao decifrar doc_id=%s no dossie: %s", doc.id, exc)
                erros.append(f"{doc.nome_original}: {type(exc).__name__}")

        zf.writestr("HASHES.txt", "\n".join(hashes_txt).encode("utf-8"))

        readme = [
            "DOSSIE DE PROVA — Motor Tributario Conect",
            "=" * 50,
            f"Cliente (CNPJ anonimizado): {cnpj_anon}",
            f"Gerado em: {_dt.now().isoformat()}",
            f"Solicitante: user_id={user_id} | ip={ip or 'N/A'}",
            f"Motivo: {motivo}",
            "",
            "Base legal:",
            "  - LGPD Art. 37: registro de operacoes de tratamento",
            "  - CTN Art. 173: prazo decadencial de 5 anos",
            "  - CTN Art. 142: constituicao do credito exige prova documental",
            "",
            "Verificacao de integridade:",
            "  sha256sum originais/*.pdf  # deve bater com as linhas em HASHES.txt",
        ]
        zf.writestr("README.txt", "\n".join(readme).encode("utf-8"))

    buffer.seek(0)
    filename = f"dossie_{cnpj_anon}_{timestamp}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
