# -*- coding: utf-8 -*-
"""
services/projecao_pipeline.py — Pipeline canônico do redesign

Conecta os 3 componentes alinhados com a visão SaaS
(project_visao_saas.md):

  1. EXTRAÇÃO   — services/extrator_pdfs.py (Claude Vision)
  2. ADAPTAÇÃO  — core/projetor_reforma.DocumentoFiscalExtraido
  3. PROJEÇÃO   — core/projetor_reforma.projetar_delta_reforma

API pública:

  gerar_projecao_pipeline(pdfs_bytes, *, ano_alvo, regime_atual,
                          extrator=None) → DeltaReformaTributaria
  gerar_comparativo_pipeline(pdfs_bytes, *, ano_alvo, regime_atual,
                             extrator=None, perfil_overrides=None)
                             → ComparativoCenarios

Função pura. Aceita extrator INJETÁVEL — em produção usa o real
(Claude Vision); em testes injeta mock pra evitar chamada à API.

Caller esperado: endpoint `/analise/projecao-reforma/{ano_alvo}`
(criação posterior — endpoint só envelopa esta função com
auth/JWT/buffer/auditoria).
"""
from __future__ import annotations

from typing import Callable, Optional, Sequence

from core.projetor_reforma import (
    AnoTransicao,
    DeltaReformaTributaria,
    DocumentoFiscalExtraido,
    RegimeAtual,
    projetar_delta_reforma,
)


def gerar_projecao_pipeline(
    pdfs_bytes: Sequence[bytes],
    *,
    ano_alvo: AnoTransicao,
    regime_atual: RegimeAtual,
    extrator: Optional[Callable[[Sequence[bytes]], object]] = None,
    documento_origem_hash: Optional[str] = None,
) -> DeltaReformaTributaria:
    """
    Pipeline ponta-a-ponta: PDFs do contador → projeção Δ Reforma.

    Args:
        pdfs_bytes: lista de PDFs já lidos em memória (bytes).
        ano_alvo: ano da transição (2026-2033) para projetar.
        regime_atual: regime tributário declarado da empresa.
        extrator: função que recebe `Sequence[bytes]` e retorna
            `DadosExtraidosPDF`. Default: usa
            `services.extrator_pdfs.extrair_dados_pdfs_bytes` (real, Claude
            Vision). Em testes, injetar mock pra evitar chamada à API.
        documento_origem_hash: SHA-256 do PDF cifrado (rastreabilidade
            LGPD — auditoria_documentos.hash). Opcional.

    Returns:
        DeltaReformaTributaria frozen com carga atual, projetada, breakdown
        e base legal.

    Raises:
        ValueError: pdfs_bytes vazio, ou erro na extração/conversão.

    NOTA SOBRE LGPD:
        Esta função NÃO persiste nada. O caller (endpoint) é quem aplica
        cifragem + persiste em `auditoria_documentos` antes de chamar
        este pipeline. Aqui só processa em memória.
    """
    if not pdfs_bytes:
        raise ValueError(
            "pdfs_bytes vazio — pipeline exige pelo menos 1 PDF do contador."
        )

    # Resolve extrator: injetado pelo caller OU import lazy do real
    if extrator is None:
        # Import lazy pra evitar carregar Claude Vision em testes que mockam
        from services.extrator_pdfs import extrair_dados_pdfs_bytes
        extrator = extrair_dados_pdfs_bytes

    # 1. EXTRAÇÃO
    dados_extraidos = extrator(pdfs_bytes)

    # 2. ADAPTAÇÃO
    documento = DocumentoFiscalExtraido.from_dados_extraidos_pdf(
        dados_extraidos,
        regime_atual=regime_atual,
        documento_origem_hash=documento_origem_hash,
    )

    # 3. PROJEÇÃO
    return projetar_delta_reforma(documento=documento, ano_alvo=ano_alvo)


def gerar_comparativo_pipeline(
    pdfs_bytes: Sequence[bytes],
    *,
    ano_alvo: AnoTransicao,
    regime_atual: RegimeAtual,
    extrator: Optional[Callable[[Sequence[bytes]], object]] = None,
    documento_origem_hash: Optional[str] = None,
    perfil_overrides: Optional[dict] = None,
):
    """
    Pipeline ponta-a-ponta do COMPARADOR: PDFs do contador → melhor cenário.

    Extrai a guia (carga REAL — nunca recalculada), monta o PerfilEmpresa
    a partir do próprio payload do extrator (CNAE, UF, RBT12, folha) e
    ranqueia os cenários fiscais no ano-alvo (core/comparador_cenarios.py).

    Args:
        pdfs_bytes: PDFs já lidos em memória.
        ano_alvo: ano da transição (2026-2033).
        regime_atual: regime tributário declarado da empresa.
        extrator: injetável (default: Claude Vision real).
        documento_origem_hash: SHA-256 do PDF cifrado (rastreabilidade LGPD).
        perfil_overrides: overrides do PerfilEmpresa (ex.:
            {"lucro_real_mensal": Decimal("30000"), "tipo_societario": "LTDA"}).
            Necessário pro cenário Lucro Real (DRE não vem da guia).

    Returns:
        ComparativoCenarios frozen — ranking parcial auditável.

    Raises:
        ValueError: pdfs_bytes vazio, extração inválida ou perfil incompleto.
    """
    # Import local: comparador puxa motor+engines — mantém o caminho da
    # projeção simples leve.
    from core.comparador_cenarios import PerfilEmpresa, comparar_cenarios

    if not pdfs_bytes:
        raise ValueError(
            "pdfs_bytes vazio — pipeline exige pelo menos 1 PDF do contador."
        )

    if extrator is None:
        from services.extrator_pdfs import extrair_dados_pdfs_bytes
        extrator = extrair_dados_pdfs_bytes

    dados_extraidos = extrator(pdfs_bytes)

    documento = DocumentoFiscalExtraido.from_dados_extraidos_pdf(
        dados_extraidos,
        regime_atual=regime_atual,
        documento_origem_hash=documento_origem_hash,
    )
    perfil = PerfilEmpresa.from_dados_extraidos_pdf(
        dados_extraidos, **(perfil_overrides or {}),
    )

    return comparar_cenarios(documento=documento, perfil=perfil, ano_alvo=ano_alvo)
