"""
relatorio_pdf.py — Geração de relatório PDF via weasyprint
Motor Tributário Conect 2026-2033 · FASE 5
Âncora Legal: LC 123/2006 | LC 214/2025 | EC 132/2023
"""
from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

# Silencia warnings GLib/GIO das libs nativas C do WeasyPrint ANTES de qualquer import
os.environ.setdefault("GIO_USE_VFS", "local")
os.environ.setdefault("G_MESSAGES_DEBUG", "")
os.environ.setdefault("NO_AT_BRIDGE", "1")
os.environ.setdefault("GIO_MODULE_DIR", "")

# ── LAZY IMPORT de weasyprint ─────────────────────────────────────────────
# Import adiado para dentro de gerar_pdf() — evita carregar libs GTK/GIO no
# startup da API (que disparam GLib-GIO-WARNING no Windows mesmo sem usar PDF).
_WeasyprintHTML = None
_WEASYPRINT_DISPONIVEL = None  # None = ainda nao tentou importar

def _tentar_importar_weasyprint():
    """Importa weasyprint sob demanda. Idempotente."""
    global _WeasyprintHTML, _WEASYPRINT_DISPONIVEL
    if _WEASYPRINT_DISPONIVEL is not None:
        return _WEASYPRINT_DISPONIVEL
    try:
        # Redirecionar stderr durante o import para suprimir warnings GLib nativos
        import sys
        _stderr_fd = os.dup(2)
        _devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(_devnull, 2)
        try:
            from weasyprint import HTML as WeasyprintHTML  # type: ignore
            _WeasyprintHTML = WeasyprintHTML
            _WEASYPRINT_DISPONIVEL = True
        finally:
            os.dup2(_stderr_fd, 2)
            os.close(_devnull)
            os.close(_stderr_fd)
    except Exception:
        _WEASYPRINT_DISPONIVEL = False
        _WeasyprintHTML = None
    return _WEASYPRINT_DISPONIVEL


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


def _gerar_html(diagnostico: dict, pii: dict | None = None) -> str:
    """
    Gera string HTML completo do relatório — CSS inline, sem CDN.

    Args:
        diagnostico: dict despersonalizado retornado por gerar_diagnostico() (LGPD).
        pii: dict opcional com {cnpj, razao_social} entregues separadamente
             apenas no momento de gerar o PDF para o cliente.
             Se None, header mostra "—".
    """
    pii = pii or {}
    empresa   = diagnostico.get("empresa", {})
    aliquotas = diagnostico.get("aliquotas", {})
    # PII vem do parâmetro separado (LGPD: nunca do diagnostico)
    razao   = _esc(pii.get("razao_social") or empresa.get("razao_social") or "—")
    cnpj    = _esc(pii.get("cnpj") or empresa.get("cnpj") or "—")
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
            cor = "#fef2f2"
            borda = "#ef4444"
            titulo_cor = "#991b1b"
        elif "ALTO" in nivel:
            cor = "#fffbeb"
            borda = "#f59e0b"
            titulo_cor = "#92400e"
        else:
            cor = "#fefce8"
            borda = "#eab308"
            titulo_cor = "#713f12"
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

{_secao_validacao_ecac(diagnostico)}

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

{_secao_decisao_opt_out(diagnostico)}

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

{_secao_glossario()}

<!-- Rodapé -->
<div class="footer">
  Calculado em {data_c} · LC 123/2006 + LC 214/2025 (vigente 01/01/2026) ·
  Auditado por Luiz Moreira 26/03/2026 · Motor Tributário Conect v2.1 ·
  Este relatório tem fins informativos e não substitui assessoria jurídica/tributária.
</div>

</body>
</html>"""


def _secao_decisao_opt_out(diagnostico: dict) -> str:
    """
    Gera a seção 'Decisão Estratégica: Opt-Out IVA' do PDF cliente.

    Frente 3.3 (Bloco B): converte os números crus de cenarios em uma narrativa
    educativa estruturada em 6 sub-blocos:
      1. O que é (definição em linguagem de empresário)
      2. Sua situação (tabela 2 colunas Simples × Opt-Out)
      3. Diagnóstico personalizado (recomendacao_inteligente do Bloco A)
      4. Datas-chave 2026 (janelas semestrais + irretratabilidade)
      5. Como fazer (checklist 3 passos)
      6. Riscos (cards vermelhos)

    Base legal: LC 214/2025 Arts. 41-44 + Resolução CGSN 183/2025.
    """
    cenarios = diagnostico.get("cenarios", {})
    simples_puro = cenarios.get("simples_puro", {})
    opt_out = cenarios.get("opt_out", {})
    rec = cenarios.get("recomendacao_inteligente") or {}

    # Fallback se Bloco A não rodou (compatibilidade)
    codigo = rec.get("codigo", "ZONA_CINZA")
    titulo_rec = _esc(rec.get("titulo", "Análise individual recomendada"))
    justificativa = _esc(rec.get("justificativa", ""))
    amparo_rec = _esc(rec.get("amparo_legal", ""))

    # Cores da recomendação por código (semâforo)
    cor_map = {
        "OPT_OUT_FORTE":     ("#065f46", "#d1fae5", "#10b981"),  # verde forte
        "OPT_OUT_VANTAJOSO": ("#0c4a6e", "#dbeafe", "#3b82f6"),  # azul
        "MANTER_SIMPLES":    ("#1f2937", "#f3f4f6", "#6b7280"),  # cinza neutro
        "ZONA_CINZA":        ("#92400e", "#fef3c7", "#f59e0b"),  # amarelo
    }
    cor_texto, cor_bg, cor_borda = cor_map.get(codigo, cor_map["ZONA_CINZA"])

    # Tabela Sua Situação
    custo_simples = _fmt_moeda(simples_puro.get("custo_das_por_operacao", 0))
    custo_opt_das = _fmt_moeda(opt_out.get("custo_das_por_operacao", 0))
    iva_por_fora = _fmt_moeda(opt_out.get("iva_recolhido_por_fora", 0))
    custo_opt_total = _fmt_moeda(opt_out.get("custo_total", 0))
    credito_simples = _fmt_moeda(simples_puro.get("credito_gerado_para_comprador", 0))
    credito_opt = _fmt_moeda(opt_out.get("credito_gerado_para_comprador", 0))
    pct_credito_simples = _esc(simples_puro.get("percentual_credito_nf", "1%"))
    pct_credito_opt = _esc(opt_out.get("percentual_credito_nf", "100%"))

    return f"""
<!-- Decisão Estratégica: Opt-Out IVA -->
<h2>Decisão Estratégica: Opt-Out IVA</h2>

<!-- Sub-bloco 1: O que é -->
<div style="background:#f8fafc;border-left:4px solid #1e40af;padding:10px 14px;margin-bottom:12px;border-radius:0 4px 4px 0;">
  <div style="font-weight:700;font-size:11px;color:#1e3a5f;margin-bottom:4px;text-transform:uppercase;letter-spacing:.04em;">O que é</div>
  <div style="font-size:11px;color:#374151;line-height:1.5;">
    Opt-Out é a opção do Simples Nacional de <strong>sair do recolhimento unificado</strong>
    de CBS/IBS, recolhendo esses dois tributos separadamente. O resto continua no DAS
    (IRPJ, CSLL, CPP, ICMS, ISS). A grande diferença é que, com Opt-Out, seu cliente B2B
    recebe <strong>100% de crédito de CBS/IBS</strong> em vez de 1% — o que pode ser
    decisivo para reter clientes corporativos depois de 2027.
  </div>
</div>

<!-- Sub-bloco 2: Sua situação (tabela comparativa) -->
<h3 style="margin-top:14px;">Sua Situação Específica</h3>
<table style="margin-bottom:12px;">
  <thead>
    <tr><th>Item</th><th>Simples Puro</th><th>Opt-Out IVA</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>DAS por operação</strong></td>
      <td>{custo_simples}</td>
      <td>{custo_opt_das}</td>
    </tr>
    <tr>
      <td><strong>IVA recolhido por fora</strong></td>
      <td style="color:#9ca3af;">—</td>
      <td>{iva_por_fora}</td>
    </tr>
    <tr style="background:#eff6ff;">
      <td><strong>Custo total por operação</strong></td>
      <td><strong>{custo_simples}</strong></td>
      <td><strong>{custo_opt_total}</strong></td>
    </tr>
    <tr>
      <td><strong>Crédito gerado para comprador B2B</strong></td>
      <td>{credito_simples} <span style="color:#9ca3af;">({pct_credito_simples})</span></td>
      <td><strong style="color:#065f46;">{credito_opt} ({pct_credito_opt})</strong></td>
    </tr>
  </tbody>
</table>

<!-- Sub-bloco 3: Diagnóstico personalizado -->
<div style="background:{cor_bg};border:2px solid {cor_borda};padding:14px 16px;border-radius:6px;margin-bottom:14px;">
  <div style="font-weight:800;font-size:13px;color:{cor_texto};margin-bottom:6px;text-transform:uppercase;letter-spacing:.03em;">
    📋 Diagnóstico Personalizado: {titulo_rec}
  </div>
  <div style="font-size:11px;color:#1f2937;line-height:1.6;">
    {justificativa}
  </div>
</div>

<!-- Sub-bloco 4: Datas-chave 2026 -->
<h3 style="margin-top:14px;">Datas-Chave 2026 — Janelas de Decisão</h3>
<table style="margin-bottom:8px;">
  <thead>
    <tr><th style="width:110px;">Data Limite</th><th>Decisão</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>30/04/2026</strong></td>
      <td>Janela do <strong>1º semestre</strong> — opção válida de Jul/2026 em diante</td>
    </tr>
    <tr>
      <td><strong>30/09/2026</strong></td>
      <td>Janela do <strong>2º semestre</strong> — opção válida de Jan/2027 em diante (CBS sobe para 8,8%)</td>
    </tr>
  </tbody>
</table>
<div style="background:#fef2f2;border-left:4px solid #dc2626;padding:10px 14px;margin-bottom:14px;border-radius:0 4px 4px 0;">
  <div style="font-weight:700;font-size:11px;color:#991b1b;margin-bottom:3px;">⚠ ATENÇÃO — IRRETRATABILIDADE</div>
  <div style="font-size:10px;color:#7f1d1d;">
    A decisão pelo Opt-Out é <strong>irretratável por 5 anos-calendário</strong>
    (LC 214/2025, Art. 43). Avalie com seu contador antes de optar.
  </div>
</div>

<!-- Sub-bloco 5: Como fazer (checklist) -->
<h3 style="margin-top:14px;">Como Fazer o Opt-Out na Prática</h3>
<table style="margin-bottom:14px;">
  <thead>
    <tr><th style="width:40px;">Passo</th><th>Ação</th></tr>
  </thead>
  <tbody>
    <tr>
      <td style="text-align:center;font-weight:700;color:#1e40af;">1</td>
      <td>Acessar o <strong>portal do Simples Nacional</strong> (gov.br/receitafederal) com certificado digital ou código de acesso</td>
    </tr>
    <tr>
      <td style="text-align:center;font-weight:700;color:#1e40af;">2</td>
      <td>No menu PGDAS-D, marcar a opção <strong>"Recolhimento de CBS/IBS fora do DAS"</strong> dentro da janela semestral aberta</td>
    </tr>
    <tr>
      <td style="text-align:center;font-weight:700;color:#1e40af;">3</td>
      <td>Confirmar e <strong>imprimir o protocolo</strong>. A partir do semestre seguinte, recolher CBS/IBS via DARF (códigos a serem definidos por ato da RFB)</td>
    </tr>
  </tbody>
</table>

<!-- Sub-bloco 6: Riscos -->
<h3 style="margin-top:14px;">Riscos do Opt-Out</h3>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:14px;">
  <div style="background:#fef2f2;border-left:3px solid #dc2626;padding:8px 10px;border-radius:0 4px 4px 0;">
    <div style="font-weight:700;font-size:10px;color:#991b1b;margin-bottom:2px;">5 ANOS SEM VOLTA</div>
    <div style="font-size:9px;color:#7f1d1d;line-height:1.4;">
      Decisão irretratável por 5 anos-calendário. LC 214/2025, Art. 43.
    </div>
  </div>
  <div style="background:#fffbeb;border-left:3px solid #f59e0b;padding:8px 10px;border-radius:0 4px 4px 0;">
    <div style="font-weight:700;font-size:10px;color:#92400e;margin-bottom:2px;">OBRIGAÇÕES EXTRAS</div>
    <div style="font-size:9px;color:#78350f;line-height:1.4;">
      EFD-Reinf e EFD-Contribuições passam a ser obrigatórias mensalmente.
    </div>
  </div>
  <div style="background:#fef2f2;border-left:3px solid #dc2626;padding:8px 10px;border-radius:0 4px 4px 0;">
    <div style="font-weight:700;font-size:10px;color:#991b1b;margin-bottom:2px;">MULTA DE OFÍCIO</div>
    <div style="font-size:9px;color:#7f1d1d;line-height:1.4;">
      Multa de <strong>75%</strong> sobre o tributo não recolhido (Lei 9.430/1996,
      Art. 44, I). Majorada para 100% em sonegação e 150% em reincidência
      (Lei 14.689/2023).
    </div>
  </div>
</div>

<p style="font-size:9px;color:#6b7280;font-style:italic;margin-top:4px;">
  ⚖ {amparo_rec or 'LC 214/2025, Arts. 41-44 | CF Art. 146, III, "d" | Resolução CGSN 183/2025'}
</p>
"""


def _secao_glossario() -> str:
    """
    Gera o glossário micro de termos tributários no fim do PDF.

    Frente 3.4 / Bloco C: empresário não conhece "Anexo III", "Sublimite",
    "Fator R", "DIFAL". 11 termos curtos antes do rodapé resolvem.

    Termos estáveis (não dependem do diagnóstico) — função sem argumentos,
    fácil de cachear se necessário.
    """
    termos = [
        ("DAS",
         "Documento de Arrecadação do Simples Nacional. Guia única mensal que "
         "unifica 8 tributos (IRPJ, CSLL, PIS, COFINS, CPP, ICMS, ISS, IPI)."),
        ("RBT12",
         "Receita Bruta dos últimos 12 meses. É o que define em qual faixa e "
         "anexo do Simples sua empresa paga (LC 123/2006, Art. 18)."),
        ("Anexo I a V",
         "Tabelas do Simples Nacional por tipo de atividade. I=Comércio, "
         "II=Indústria, III/V=Serviços (Fator R decide), IV=Serviços s/ CPP."),
        ("Fator R",
         "Folha de pagamento ÷ RBT12. Se ≥ 28%, serviços vão no Anexo III "
         "(menor carga); se &lt; 28%, vão no Anexo V (maior carga)."),
        ("Sublimite",
         "Teto de R$ 3.600.000/ano. Acima disso, ICMS e ISS saem do DAS e "
         "passam a ser recolhidos fora do Simples (LC 123/2006, Art. 13 §1º)."),
        ("CBS",
         "Contribuição sobre Bens e Serviços. Tributo federal que substitui "
         "PIS e COFINS a partir de 2027 (LC 214/2025, EC 132/2023)."),
        ("IBS",
         "Imposto sobre Bens e Serviços. Tributo estadual+municipal que "
         "substitui ICMS e ISS gradualmente entre 2029 e 2033."),
        ("IVA Dual",
         "Nome informal do sistema CBS+IBS. \"Dual\" porque são dois tributos "
         "sobre a mesma base (um federal, outro subnacional)."),
        ("Opt-Out",
         "Opção do Simples Nacional de sair do recolhimento unificado de "
         "CBS/IBS, passando a recolher esses dois separadamente. Libera "
         "crédito 100% para clientes B2B (LC 214/2025, Arts. 41-44)."),
        ("B2B / B2C",
         "B2B (Business-to-Business) = venda para outra empresa contribuinte. "
         "B2C (Business-to-Consumer) = venda para consumidor final."),
        ("Crédito IVA",
         "Valor de CBS/IBS que o comprador pode abater dos tributos que ele "
         "próprio vai recolher. Empresas no Simples geram crédito de apenas "
         "1%; com Opt-Out, geram 100%."),
        ("DIFAL",
         "Diferencial de Alíquota do ICMS. Devido quando se vende para outro "
         "estado — compensa a diferença entre alíquotas interna e "
         "interestadual (EC 87/2015, LC 190/2022)."),
    ]

    linhas = ""
    for termo, definicao in termos:
        linhas += (
            f"<tr>"
            f"<td style='font-weight:700;color:#1e3a5f;width:110px;vertical-align:top;'>{termo}</td>"
            f"<td style='color:#374151;line-height:1.5;'>{definicao}</td>"
            f"</tr>"
        )

    return f"""
<!-- Glossário (Frente 3.4 / Bloco C) -->
<h2>Glossário</h2>
<p style="font-size:10px;color:#6b7280;margin-bottom:8px;">
  Termos técnicos citados neste relatório em linguagem de empresário.
</p>
<table style="font-size:10px;margin-bottom:10px;">
  <tbody>
    {linhas}
  </tbody>
</table>
"""


def _secao_validacao_ecac(diagnostico: dict) -> str:
    """
    Gera a seção 'Validação contra e-CAC' do PDF.

    Frente 3.5 (Bloco D): expõe a validação cruzada DAS calculado × DAS pago no
    e-CAC que hoje fica escondida em `_extracao.validacao_cruzada`. Só aparece
    em PDFs gerados a partir de extração (upload de PDFs do e-CAC); em análise
    manual o bloco fica oculto.

    Semáforo:
      🟢 delta < 0,5%   → verde  "Aprovado — confere com o e-CAC"
      🟡 0,5% ≤ Δ < 5% → amarelo "Diferença pequena — revisar antes de pagar"
      🔴 delta ≥ 5%     → vermelho "Diferença significativa — investigar"

    Base legal: LC 123/2006, Art. 18 (DAS = alíquota efetiva × receita do PA).
    """
    extracao = diagnostico.get("_extracao") or {}
    validacoes = extracao.get("validacao_cruzada") or []

    # Encontra o item DAS_CALCULADO_VS_ECAC (pode haver outros tipos como BREAKDOWN)
    item = next(
        (v for v in validacoes if v.get("tipo") == "DAS_CALCULADO_VS_ECAC"),
        None,
    )
    if not item:
        return ""  # PDF de análise manual — sem validação cruzada

    try:
        das_calc = Decimal(str(item.get("das_calculado", "0")))
        das_ecac = Decimal(str(item.get("das_ecac", "0")))
        delta = Decimal(str(item.get("delta", "0")))
        delta_pct = Decimal(str(item.get("delta_pct", "0")))
    except Exception:
        return ""

    # Semáforo de cor por delta percentual
    if delta_pct < Decimal("0.5"):
        cor_bg, cor_borda, cor_texto = "#f0fdf4", "#10b981", "#065f46"
        icone = "✓"
        titulo = "Aprovado — confere com o e-CAC"
        explicacao = (
            "O DAS calculado pelo motor está alinhado com o valor pago no e-CAC. "
            "Diferença dentro da margem aceitável (< 0,5%)."
        )
    elif delta_pct < Decimal("5"):
        cor_bg, cor_borda, cor_texto = "#fffbeb", "#f59e0b", "#92400e"
        icone = "⚠"
        titulo = "Diferença pequena — revisar antes de pagar"
        explicacao = (
            "O DAS calculado difere do pago no e-CAC em menos de 5%. "
            "Geralmente é arredondamento, RPA aproximado ou pequeno descasamento "
            "de competência. Confira antes de usar como referência."
        )
    else:
        cor_bg, cor_borda, cor_texto = "#fef2f2", "#ef4444", "#991b1b"
        icone = "✗"
        titulo = "Diferença significativa — investigue antes de usar"
        explicacao = (
            "O DAS calculado difere do pago no e-CAC em mais de 5%. "
            "Possíveis causas: ICMS-ST não segregado, multi-atividade não declarada, "
            "RPA real diferente do extraído, CNAE/Anexo divergente, ou Fator R com "
            "folha desatualizada. Não use este diagnóstico como referência sem revisão."
        )

    delta_str = _fmt_moeda(delta)
    delta_pct_str = f"{delta_pct:.2f}%".replace(".", ",")
    das_calc_str = _fmt_moeda(das_calc)
    das_ecac_str = _fmt_moeda(das_ecac)

    return f"""
<!-- Validação contra e-CAC (Frente 3.5 / Bloco D) -->
<h2>Validação contra o e-CAC</h2>
<div style="background:{cor_bg};border:2px solid {cor_borda};border-radius:6px;padding:12px 14px;margin-bottom:12px;">
  <div style="font-weight:800;font-size:13px;color:{cor_texto};margin-bottom:8px;">
    {icone} {titulo}
  </div>
  <table style="margin-bottom:8px;">
    <thead>
      <tr><th>Origem</th><th style="text-align:right;">Valor</th></tr>
    </thead>
    <tbody>
      <tr><td><strong>DAS calculado pelo motor</strong></td><td style="text-align:right;font-family:monospace;">{das_calc_str}</td></tr>
      <tr><td><strong>DAS pago no e-CAC</strong></td><td style="text-align:right;font-family:monospace;">{das_ecac_str}</td></tr>
      <tr style="background:{cor_bg};">
        <td><strong>Diferença</strong></td>
        <td style="text-align:right;font-family:monospace;font-weight:700;color:{cor_texto};">
          {delta_str} ({delta_pct_str})
        </td>
      </tr>
    </tbody>
  </table>
  <div style="font-size:10px;color:#374151;line-height:1.5;">
    {explicacao}
  </div>
  <div style="font-size:9px;color:#6b7280;margin-top:6px;font-style:italic;">
    ⚖ LC 123/2006, Art. 18 — DAS = alíquota efetiva × receita do período de apuração
  </div>
</div>
"""


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


def gerar_pdf(diagnostico: dict, pii: dict | None = None) -> bytes:
    """
    Gera bytes do PDF do diagnóstico fiscal.

    Args:
        diagnostico: dict retornado por MotorReformaTributaria.gerar_diagnostico()
                     (despersonalizado por LGPD — sem cnpj/razao_social)
        pii: dict opcional {cnpj, razao_social} entregue separadamente
             apenas no momento de gerar PDF para o cliente. Não persistido.

    Returns:
        bytes do PDF gerado

    Raises:
        RuntimeError: se weasyprint não estiver instalado ou falhar
    """
    # Lazy import: só carrega weasyprint na primeira chamada
    if not _tentar_importar_weasyprint() or _WeasyprintHTML is None:
        raise RuntimeError(
            "weasyprint não instalado ou GTK ausente. "
            "Execute: pip install weasyprint>=61.0 (Windows: precisa GTK3 Runtime)"
        )

    html_str = _gerar_html(diagnostico, pii=pii)
    try:
        pdf_bytes: bytes = _WeasyprintHTML(string=html_str).write_pdf()
        logger.info(
            "PDF gerado com sucesso — %d bytes",  # sem PII no log
            len(pdf_bytes),
        )
        return pdf_bytes
    except Exception as exc:
        logger.error("Erro ao gerar PDF via weasyprint: %s", exc)
        raise RuntimeError(f"Falha na geração do PDF: {exc}") from exc
