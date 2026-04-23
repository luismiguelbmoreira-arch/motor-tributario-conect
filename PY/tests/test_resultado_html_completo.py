# -*- coding: utf-8 -*-
"""
test_resultado_html_completo.py — Garante que `UI/resultado.html` tem as
mesmas seções do PDF gerado pelo `relatorio_pdf.py`.

Testa estaticamente (sem JS runtime) a presença dos elementos obrigatórios:
  - Seção Validação e-CAC com semáforo
  - Seção Decisão Estratégica Opt-Out com 6 sub-blocos
  - Seção Glossário com 12 termos
  - Botão "Baixar Dossiê de Prova"
  - Filtro de trilha aplicado (função filtrarTrilhaCliente)
  - Lógica de renderização paralela ao Python
"""
from __future__ import annotations

from pathlib import Path

import pytest

HTML_PATH = Path(__file__).resolve().parent.parent.parent / "UI" / "resultado.html"


@pytest.fixture(scope="module")
def html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


# ── Seção Validação e-CAC ──────────────────────────────────────────────────


class TestSecaoValidacaoEcac:
    def test_section_existe(self, html):
        assert 'id="sec-validacao-ecac"' in html

    def test_iniciada_oculta(self, html):
        """Por padrão inicia hidden (só aparece quando há _extracao com validação)."""
        assert 'id="sec-validacao-ecac"' in html
        # hidden deve estar na class inicial
        assert 'id="sec-validacao-ecac" class="fade-in hidden"' in html

    def test_titulo(self, html):
        assert "Validação contra o e-CAC" in html

    def test_elementos_do_card(self, html):
        assert 'id="validacao-ecac-card"' in html
        assert 'id="validacao-ecac-icone"' in html
        assert 'id="validacao-ecac-titulo"' in html
        assert 'id="validacao-ecac-calculado"' in html
        assert 'id="validacao-ecac-pago"' in html
        assert 'id="validacao-ecac-delta"' in html
        assert 'id="validacao-ecac-explicacao"' in html

    def test_amparo_legal_citado(self, html):
        assert "LC 123/2006, Art. 18" in html

    def test_renderer_js_existe(self, html):
        assert "function renderValidacaoEcac" in html

    def test_renderer_js_ligado_no_render_principal(self, html):
        assert "renderValidacaoEcac(d._extracao" in html

    def test_semáforo_tres_faixas(self, html):
        """O renderer deve ter lógica para verde/amarelo/vermelho."""
        # Delta < 0.5 = verde
        assert "emerald" in html and "Aprovado" in html
        # 0.5 < delta < 5 = amarelo
        assert "amber" in html and "Diferença pequena" in html
        # delta >= 5 = vermelho
        assert ("red-50" in html or "red-500" in html) and "Diferença significativa" in html


# ── Seção Decisão Estratégica Opt-Out ──────────────────────────────────────


class TestSecaoDecisaoOptOut:
    def test_section_existe(self, html):
        assert 'id="sec-decisao-optout"' in html

    def test_titulo(self, html):
        assert "Decisão Estratégica: Opt-Out IVA" in html

    def test_sub_bloco_1_o_que_eh(self, html):
        assert "sair do recolhimento unificado" in html
        assert "100% de crédito de CBS/IBS" in html

    def test_sub_bloco_2_tabela(self, html):
        assert 'id="optout-tabela-situacao"' in html
        assert "Sua situação específica" in html

    def test_sub_bloco_3_diagnostico_personalizado(self, html):
        assert 'id="optout-diagnostico-card"' in html
        assert 'id="optout-diagnostico-titulo"' in html
        assert 'id="optout-diagnostico-justificativa"' in html

    def test_sub_bloco_4_datas_chave(self, html):
        assert "30/04/2026" in html
        assert "30/09/2026" in html
        assert "irretratável por 5 anos-calendário" in html
        assert "LC 214/2025, Art. 43" in html

    def test_sub_bloco_5_como_fazer(self, html):
        assert "PGDAS-D" in html
        assert "Recolhimento de CBS/IBS fora do DAS" in html

    def test_sub_bloco_6_riscos_com_multa_correta(self, html):
        """Multa de 75% (não 20%) — correção crítica do PR #9."""
        assert "Multa de <strong>75%</strong>" in html
        assert "Lei 9.430/1996, Art. 44" in html
        assert "Lei 14.689/2023" in html

    def test_renderer_js_existe(self, html):
        assert "function renderDecisaoOptOut" in html

    def test_consome_recomendacao_inteligente(self, html):
        assert "cenarios.recomendacao_inteligente" in html

    def test_4_cores_semaforo_da_recomendacao(self, html):
        """OPT_OUT_FORTE, OPT_OUT_VANTAJOSO, MANTER_SIMPLES, ZONA_CINZA."""
        assert "OPT_OUT_FORTE" in html
        assert "OPT_OUT_VANTAJOSO" in html
        assert "MANTER_SIMPLES" in html
        assert "ZONA_CINZA" in html


# ── Seção Glossário ─────────────────────────────────────────────────────────


TERMOS_OBRIGATORIOS = [
    "DAS",
    "RBT12",
    "Anexo I a V",
    "Fator R",
    "Sublimite",
    "CBS",
    "IBS",
    "IVA Dual",
    "Opt-Out",
    "B2B / B2C",
    "Crédito IVA",
    "DIFAL",
]


class TestSecaoGlossario:
    def test_section_existe(self, html):
        assert 'id="sec-glossario"' in html

    def test_titulo(self, html):
        assert ">Glossário<" in html

    def test_todos_os_12_termos_presentes(self, html):
        for termo in TERMOS_OBRIGATORIOS:
            assert f"'{termo}'" in html or f'"{termo}"' in html, f"Termo '{termo}' ausente"

    def test_renderer_js_existe(self, html):
        assert "function renderGlossario" in html
        assert "TERMOS_GLOSSARIO" in html

    def test_lista_constante_tem_12(self, html):
        """Conta entradas no TERMOS_GLOSSARIO pela contagem de [' entries."""
        # Abordagem simples: achar o bloco TERMOS_GLOSSARIO e contar '[' dentro
        inicio = html.find("const TERMOS_GLOSSARIO")
        fim = html.find("];", inicio)
        bloco = html[inicio:fim]
        # Cada termo é uma linha ["termo", "def"]
        assert bloco.count("['") == 12


# ── Botão Dossiê de Prova ───────────────────────────────────────────────────


class TestBotaoDossie:
    def test_botao_existe(self, html):
        assert 'id="btn-baixar-dossie"' in html

    def test_botao_inicia_oculto(self, html):
        """Só aparece quando há documentos_auditoria no _extracao."""
        assert 'class="hidden focus-ring inline-flex' in html
        assert 'id="btn-baixar-dossie"' in html

    def test_handler_js_existe(self, html):
        assert "async function baixarDossieProva" in html

    def test_exige_motivo_minimo_10_chars(self, html):
        assert "pelo menos 10 caracteres" in html
        assert "length < 10" in html

    def test_chama_endpoint_correto(self, html):
        assert "/auditoria/prova/cnpj/" in html

    def test_passa_motivo_como_query_param(self, html):
        assert "motivo=" in html
        assert "encodeURIComponent(motivo" in html

    def test_tratamento_404_mensagem_clara(self, html):
        assert "status === 404" in html or "status == 404" in html
        assert "Nenhum documento de auditoria" in html

    def test_tratamento_401_limpa_sessao(self, html):
        # Fase 2 — Contratos Blindados: 401 é tratado GLOBALMENTE em mcFetch
        # (UI/components.js). A função só precisa usar mcFetch — a limpeza
        # de sessionStorage + redirect pro login ficam no helper.
        idx = html.find("async function baixarDossieProva")
        bloco = html[idx:idx + 3000]
        assert "mcFetch(" in bloco, (
            "Função deve chamar mcFetch (helper que trata 401 globalmente), não fetch() direto."
        )
        # components.js é a fonte única de limpeza de sessão em 401
        assert 'src="components.js"' in html

    def test_funcao_mostrar_botao_dossie(self, html):
        assert "function mostrarBotaoDossie" in html
        # Só mostra quando há documentos
        assert "documentos_auditoria" in html


# ── Filtro da trilha (paridade com Python) ──────────────────────────────────


class TestFiltroTrilhaJs:
    def test_funcao_existe(self, html):
        assert "function filtrarTrilhaCliente" in html

    def test_exclui_max_fiscal(self, html):
        assert "MAX_FISCAL_" in html

    def test_exclui_violacao(self, html):
        assert "VIOLACAO_" in html

    def test_exclui_difal_operacao_interna(self, html):
        assert "DIFAL_OPERACAO_INTERNA" in html

    def test_dedup_por_id(self, html):
        # A lógica usa Map para dedup — "const vistos = new Map()"
        idx = html.find("function filtrarTrilhaCliente")
        bloco = html[idx:idx + 2000]
        assert "new Map" in bloco

    def test_ordenacao_prioridade(self, html):
        """DECISAO_ANEXO, AE_SIMPLES, FATOR_R, OPT_OUT_CALCULO, DIFAL_*."""
        idx = html.find("function filtrarTrilhaCliente")
        bloco = html[idx:idx + 3000]
        assert "DECISAO_ANEXO" in bloco
        assert "AE_SIMPLES" in bloco
        assert "OPT_OUT_CALCULO" in bloco
        assert "DIFAL_BASE_UNICA" in bloco

    def test_trilha_render_usa_filtro(self, html):
        """renderTrilhaAuditoria deve chamar filtrarTrilhaCliente."""
        idx = html.find("function renderTrilhaAuditoria")
        bloco = html[idx:idx + 500]
        assert "filtrarTrilhaCliente" in bloco

    def test_titulo_trilha_reflete_filtro(self, html):
        """Título 'Cálculos usados neste caso' em vez de 'Como foi calculado?'."""
        assert "Cálculos usados neste caso" in html
        # Subtítulo também
        assert "Apenas os passos aplicáveis" in html


# ── Integração no renderDiagnostico ─────────────────────────────────────────


class TestIntegracaoRenderPrincipal:
    def _bloco_render(self, html: str) -> str:
        """Extrai o corpo da função renderDiagnostico (do início até a próxima função)."""
        idx = html.find("function renderDiagnostico")
        # Vai até a próxima 'function ' no nível do script — limite generoso
        return html[idx:idx + 5000]

    def test_render_principal_chama_todos_novos(self, html):
        bloco = self._bloco_render(html)
        assert "renderValidacaoEcac" in bloco
        assert "renderDecisaoOptOut" in bloco
        assert "renderGlossario" in bloco
        assert "renderTrilhaAuditoria" in bloco
        assert "mostrarBotaoDossie" in bloco

    def test_ordem_das_secoes_no_render(self, html):
        """Ordem esperada: validação > alertas > ... > cenários > optout > ... > glossário > trilha."""
        bloco = self._bloco_render(html)
        pos_validacao = bloco.find("renderValidacaoEcac")
        pos_alertas = bloco.find("renderAlertas")
        pos_cenarios = bloco.find("renderCenarios")
        pos_optout = bloco.find("renderDecisaoOptOut")
        pos_glossario = bloco.find("renderGlossario")
        pos_trilha = bloco.find("renderTrilhaAuditoria")

        assert all(p > 0 for p in [pos_validacao, pos_alertas, pos_cenarios, pos_optout, pos_glossario, pos_trilha])
        assert pos_validacao < pos_alertas
        assert pos_cenarios < pos_optout
        assert pos_optout < pos_glossario
        assert pos_glossario < pos_trilha


class TestInvarianteDasUnico:
    """
    REGRA À PROVA DE ERRO (rails fiscal): o card 'DAS MENSAL ESTIMADO' do
    header NÃO pode calcular fiscal por conta própria. Tem que usar o
    valor JÁ calculado pelo motor (cenarios.simples_puro.custo_das_por_operacao).

    Antes desta regra, o JS calculava `aliq × rbt12 / 12` que dava valores
    DIFERENTES da tabela Opt-Out (que usa RPA real do e-CAC), gerando
    inconsistência visual gritante para o contador.
    """

    def test_card_das_usa_simples_puro_custo(self, html):
        # No bloco JS de renderDiagnostico, o cálculo do dasMensal deve
        # usar cenarios.simples_puro.custo_das_por_operacao como fonte primária
        idx = html.find("function renderDiagnostico")
        fim = html.find("function ", idx + 100)  # próxima função
        bloco_render = html[idx:fim]
        assert "simples_puro" in bloco_render, "renderDiagnostico não usa cenarios.simples_puro"
        assert "custo_das_por_operacao" in bloco_render
        assert "card-das" in bloco_render

    def test_fallback_documentado(self, html):
        """Se não houver cenário, o fallback aliq × rbt12 / 12 é permitido mas tem comentário."""
        idx = html.find("FONTE ÚNICA")
        assert idx > 0, "Fix do DAS único deve ter comentário 'FONTE ÚNICA'"

    def test_nenhum_outro_lugar_calcula_das_mensal(self, html):
        """
        Não pode haver outro 'aliqEf * rbt12 / 12' na página fora do fallback
        do card-das.
        """
        # Conta ocorrências do padrão de cálculo manual de DAS
        count = html.count("aliqEf * rbt12Val")
        assert count <= 1, f"DAS calculado manualmente em {count} lugares — deve ser só no fallback do card-das"
