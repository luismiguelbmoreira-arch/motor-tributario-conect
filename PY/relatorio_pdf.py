"""
relatorio_pdf.py — Geração de relatório PDF via weasyprint
Motor Tributário Conect 2026-2033 · FASE 5
Âncora Legal: LC 123/2006 | LC 214/2025 | EC 132/2023
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

# ── Importação defensiva de weasyprint ─────────────────────────────────────
try:
    from weasyprint import HTML as WeasyprintHTML  # type: ignore
    _WEASYPRINT_DISPONIVEL = True
except ImportError:
    _WEASYPRINT_DISPONIVEL = False
    logger.warning(
        "weasyprint não instalado — geração de PDF indisponível. "
        "Execute: pip install weasyprint>=61.0"
    )


def _fmt_moeda(valor: Any) -> str:
    """Formata valor como moeda brasileira a partir de str, Decimal ou float."""
    try:
        return f"R$ {Decimal(str(valor)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(valor)


def _fmt_pct(valor: Any, casas: int = 2) -> str:
    """Formata alíquota/percentual (0.065 → '6,50%')."""
    try:
        return f"{Decimal(str(valor)) * 100:.{casas}f}%".replace(".", ",")
    except Exception:
        return str(valor)


def _esc(s: Any) -> str:
    """Escape HTML mínimo para valores inseridos no template."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _gerar_html(diagnostico: dict) -> str:
    """Gera string HTML completo do relatório — CSS inline, sem CDN."""

    empresa   = diagnostico.get("empresa", {})
    aliquotas = diagnostico.get("aliquotas", {})
    razao   = _esc(empresa.get("razao_social") or "—")
    cnpj    = _esc(empresa.get("cnpj") or "—")
    regime  = _esc(empresa.get("regime") or "—")
    anexo   = _esc(empresa.get("anexo_simples") or "—")
    rbt12   = _fmt_moeda(empresa.get("rbt12", 0))
    aliq_ef = _fmt_pct(aliquotas.get("efetiva_das_total", 0))
    # DAS mensal estimado: alíquota efetiva × RBT12 / 12
    try:
        das_m = _fmt_moeda(Decimal(str(aliquotas.get("efetiva_das_total", 0))) * Decimal(str(empresa.get("rbt12", 0))) / 12)
    except Exception:
        das_m = "—"
    fator_r = _esc(empresa.get("fator_r") or "—")
    data_c  = _esc(diagnostico.get("data_analise") or "—")

    # Alertas
    alertas_html = ""
    for alerta in diagnostico.get("alertas", []):
        nivel  = str(alerta.get("nivel", "")).upper()
        codigo = str(alerta.get("codigo", nivel))
        detalhe = _esc(alerta.get("mensagem") or "")
        lei    = ""
        if "CRITICO" in nivel:
            cor = "#fef2f2"; borda = "#ef4444"; titulo_cor = "#991b1b"
        elif "ALTO" in nivel:
            cor = "#fffbeb"; borda = "#f59e0b"; titulo_cor = "#92400e"
        else:
            cor = "#fefce8"; borda = "#eab308"; titulo_cor = "#713f12"
        alertas_html += f"""
        <div style="background:{cor};border-left:4px solid {borda};padding:10px 14px;border-radius:4px;margin-bottom:8px;">
          <div style="font-weight:700;color:{titulo_cor};font-size:10px;text-transform:uppercase;margin-bottom:4px;">{_esc(codigo)}</div>
          <div style="font-size:11px;color:#374151;">{detalhe}</div>
          {f'<div style="font-size:10px;color:#6b7280;margin-top:4px;">⚖ {lei}</div>' if lei else ''}
        </div>"""

    if not alertas_html:
        alertas_html = '<p style="color:#6b7280;font-size:11px;">Nenhum alerta identificado.</p>'

    # Cronograma IVA
    iva_rows = ""
    for item in diagnostico.get("cronograma_iva", []):
        ano  = _esc(item.get("ano", ""))
        cbs  = _fmt_pct(item.get("cbs", 0), 3)
        ibs  = _fmt_pct(item.get("ibs", 0), 3)
        tot  = _fmt_pct(item.get("total", 0), 3)
        iva_rows += f"<tr><td>{ano}</td><td>{cbs}</td><td>{ibs}</td><td style='font-weight:600'>{tot}</td></tr>"

    if not iva_rows:
        iva_rows = "<tr><td colspan='4' style='text-align:center;color:#9ca3af;'>Dados indisponíveis</td></tr>"

    # Cenários
    cenarios      = diagnostico.get("cenarios", {})
    simples_puro  = cenarios.get("simples_puro", {})
    opt_out       = cenarios.get("opt_out", {})
    carga_simples = _fmt_moeda(simples_puro.get("custo_das_por_operacao", 0))
    carga_opt     = _fmt_moeda(opt_out.get("custo_total", 0))
    disparidade   = cenarios.get("disparidade_anual_estimada")
    economia_str  = _fmt_moeda(disparidade) if disparidade else "—"

    # Trilha de auditoria
    trilha_html = ""
    for passo in diagnostico.get("trilha_auditoria", []):
        titulo  = _esc(passo.get("titulo") or passo.get("id") or "")
        formula = _esc(passo.get("formula") or "")
        lei     = _esc(passo.get("amparo_legal") or "")
        vigente = _esc(passo.get("vigente_desde") or "")
        detalhe = _esc(passo.get("detalhe") or "")
        trilha_html += f"""
        <div style="border-left:3px solid #dbeafe;padding:8px 12px;margin-bottom:8px;background:#f8fafc;border-radius:0 4px 4px 0;">
          <div style="font-weight:600;font-size:11px;color:#1e3a5f;margin-bottom:3px;">{titulo}</div>
          {f'<div style="font-size:10px;color:#374151;font-family:monospace;background:#f1f5f9;padding:3px 6px;border-radius:2px;margin:3px 0;">{formula}</div>' if formula else ''}
          {f'<div style="font-size:10px;color:#1e40af;margin-top:3px;">⚖ {lei}</div>' if lei else ''}
          {f'<div style="font-size:10px;color:#6b7280;">Vigente desde: {vigente}</div>' if vigente else ''}
          {f'<div style="font-size:10px;color:#4b5563;margin-top:2px;">{detalhe}</div>' if detalhe else ''}
        </div>"""

    if not trilha_html:
        trilha_html = '<p style="color:#9ca3af;font-size:11px;">Trilha de auditoria indisponível.</p>'

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
      font-size: 12px; color: #1c1c1c; background: #fff;
      padding: 32px 40px;
    }}
    h1 {{ font-size: 20px; color: #1e3a5f; margin-bottom: 4px; }}
    h2 {{ font-size: 13px; color: #1e3a5f; font-weight: 700;
          margin: 20px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #e2e8f0; }}
    h3 {{ font-size: 11px; font-weight: 600; color: #374151; margin-bottom: 6px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
    th {{ background: #1e40af; color: #fff; padding: 6px 10px; text-align: left; font-size: 10px; }}
    td {{ padding: 6px 10px; border-bottom: 1px solid #f1f5f9; }}
    tr:nth-child(even) td {{ background: #f8fafc; }}
    .kpi-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 4px; }}
    .kpi {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px 12px; }}
    .kpi-label {{ font-size: 9px; text-transform: uppercase; color: #64748b; letter-spacing: .04em; margin-bottom: 2px; }}
    .kpi-value {{ font-size: 15px; font-weight: 700; color: #1e3a5f; }}
    .cenarios-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .cenario {{ border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; }}
    .cenario-opt {{ border-color: #059669; background: #f0fdf4; }}
    .footer {{ margin-top: 32px; padding-top: 12px; border-top: 1px solid #e2e8f0;
                font-size: 9px; color: #94a3b8; text-align: center; }}
    @page {{ margin: 20mm 15mm; size: A4; }}
  </style>
</head>
<body>

<!-- Cabeçalho -->
<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px;padding-bottom:12px;border-bottom:2px solid #1e40af;">
  <div>
    <div style="font-size:10px;color:#6b7280;font-weight:600;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;">Motor Tributário Conect · Diagnóstico Fiscal</div>
    <h1>{razao}</h1>
    <div style="font-size:11px;color:#475569;margin-top:2px;">CNPJ: {cnpj} · Regime: {regime}{' · Anexo ' + anexo if anexo != '—' else ''}</div>
  </div>
  <div style="text-align:right;font-size:10px;color:#64748b;">
    <div>Calculado em:</div>
    <div style="font-weight:600;color:#1e3a5f;">{data_c}</div>
  </div>
</div>

<!-- KPIs -->
<h2>Situação Atual</h2>
<div class="kpi-grid">
  <div class="kpi">
    <div class="kpi-label">Receita Bruta 12m</div>
    <div class="kpi-value">{rbt12}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Alíquota Efetiva</div>
    <div class="kpi-value">{aliq_ef}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">DAS Mensal</div>
    <div class="kpi-value">{das_m}</div>
  </div>
  <div class="kpi">
    <div class="kpi-label">Fator R</div>
    <div class="kpi-value">{fator_r if fator_r != '—' else 'N/A'}</div>
  </div>
</div>

<!-- Alertas -->
<h2>Alertas de Risco</h2>
{alertas_html}

<!-- Cronograma IVA -->
<h2>Cronograma de Transição IVA 2026–2033</h2>
<p style="font-size:10px;color:#6b7280;margin-bottom:8px;">Conforme LC 214/2025, Art. 348 — CBS (Federal) + IBS (Subnacional)</p>
<table>
  <thead>
    <tr><th>Ano</th><th>CBS</th><th>IBS</th><th>Total IVA</th></tr>
  </thead>
  <tbody>
    {iva_rows}
  </tbody>
</table>

<!-- Cenários comparativos -->
<h2>Cenários Comparativos</h2>
<div class="cenarios-grid">
  <div class="cenario">
    <h3>Simples Nacional Puro</h3>
    <div style="font-size:18px;font-weight:700;color:#1e3a5f;margin-top:4px;">{carga_simples}</div>
    <div style="font-size:10px;color:#64748b;margin-top:2px;">Carga tributária anual estimada</div>
  </div>
  <div class="cenario cenario-opt">
    <h3 style="color:#065f46;">Opt-Out IVA</h3>
    <div style="font-size:18px;font-weight:700;color:#065f46;margin-top:4px;">{carga_opt}</div>
    <div style="font-size:10px;color:#047857;margin-top:2px;">Carga tributária anual estimada</div>
    {f'<div style="margin-top:6px;background:#d1fae5;border-radius:4px;padding:4px 8px;font-size:10px;font-weight:700;color:#065f46;display:inline-block;">Disparidade anual: {economia_str}</div>' if disparidade and str(disparidade) not in ('0', '0.00', 'None') else ''}
  </div>
</div>

<!-- Serviços recomendados -->
<h2>Serviços Recomendados</h2>
<table>
  <thead><tr><th>Serviço</th><th>Contexto</th></tr></thead>
  <tbody>
    <tr><td style="font-weight:600;">Relatório de Conformidade Fiscal 2026</td><td>Documentação completa da situação tributária — sempre indicado</td></tr>
    {_servicos_recomendados(diagnostico)}
  </tbody>
</table>
<p style="font-size:10px;color:#9ca3af;margin-top:6px;font-style:italic;">* Valores e condições a combinar com o escritório. Esta lista não constitui proposta comercial.</p>

<!-- Trilha de auditoria -->
<h2>Trilha de Auditoria</h2>
<p style="font-size:10px;color:#6b7280;margin-bottom:10px;">Todos os cálculos abaixo citam base legal explícita — MAX_02 Motor Tributário Conect.</p>
{trilha_html}

<!-- Rodapé -->
<div class="footer">
  Calculado em {data_c} · LC 123/2006 + LC 214/2025 (vigente 01/01/2026) ·
  Auditado por Luiz Moreira 26/03/2026 · Motor Tributário Conect v2.1 ·
  Este relatório tem fins informativos e não substitui assessoria jurídica/tributária.
</div>

</body>
</html>"""


def _servicos_recomendados(diagnostico: dict) -> str:
    """Gera linhas de serviços recomendados baseado nos alertas do diagnóstico."""
    alertas   = diagnostico.get("alertas", [])
    codigos_alerta = {str(a.get("codigo", a.get("nivel", ""))) for a in alertas}
    cenarios   = diagnostico.get("cenarios", {})
    disparidade = cenarios.get("disparidade_anual_estimada")

    rows = ""
    if any("FATOR_R" in t for t in codigos_alerta):
        rows += "<tr><td style='font-weight:600;'>Adequação de Folha de Pagamento</td><td>Fator R em zona de risco — rebalancear pró-labore/folha pode reduzir carga</td></tr>"

    if any("B2B" in t or "IVA" in t or "CBS" in t or "IBS" in t for t in codigos_alerta):
        rows += "<tr><td style='font-weight:600;'>Diagnóstico de Impacto Tributário 2026</td><td>Operações B2B com fornecedores expostos ao IVA a partir de 2026</td></tr>"

    if disparidade:
        try:
            if Decimal(str(disparidade)) != Decimal("0"):
                rows += "<tr><td style='font-weight:600;'>Análise de Viabilidade Opt-Out</td><td>Disparidade entre cenários identificada — avaliação completa de viabilidade</td></tr>"
        except Exception:
            pass

    if any("TETO" in t or "MEI" in t for t in codigos_alerta):
        rows += "<tr><td style='font-weight:600;'>Planejamento de Transição MEI→ME</td><td>Receita próxima do teto MEI — planejamento preventivo de reenquadramento</td></tr>"

    return rows


def gerar_pdf(diagnostico: dict) -> bytes:
    """
    Gera bytes do PDF do diagnóstico fiscal.

    Args:
        diagnostico: dict retornado por MotorReformaTributaria.gerar_diagnostico()

    Returns:
        bytes do PDF gerado

    Raises:
        RuntimeError: se weasyprint não estiver instalado ou falhar
    """
    if not _WEASYPRINT_DISPONIVEL:
        raise RuntimeError(
            "weasyprint não instalado. Execute: pip install weasyprint>=61.0"
        )

    html_str = _gerar_html(diagnostico)
    try:
        pdf_bytes: bytes = WeasyprintHTML(string=html_str).write_pdf()
        logger.info(
            "PDF gerado com sucesso — %d bytes · empresa: %s",
            len(pdf_bytes),
            diagnostico.get("empresa", {}).get("razao_social") or "desconhecida",
        )
        return pdf_bytes
    except Exception as exc:
        logger.error("Erro ao gerar PDF via weasyprint: %s", exc)
        raise RuntimeError(f"Falha na geração do PDF: {exc}") from exc
