# -*- coding: utf-8 -*-
"""
test_guardrails.py — Testes Sentinela de Guardrails
Projeto: Motor Tributário Conect 2026-2033

G-02: Verifica que todos os passos da trilha têm "tipo"
G-03: Verifica que DISTRIBUICAO_DAS por faixa soma 1.0000
G-04: Verifica que CBS é estável e IBS cresce 2029-2033
G-01: Testa validar_campos_regime()
G-05: Testa assert_legal_anchor()
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from guardrails import assert_legal_anchor, validar_campos_regime
from motor_tributario import (
    EmpresaCompradora,
    EmpresaFornecedora,
    MotorReformaTributaria,
    OperacaoFiscal,
)
from tabelas_simples import CRONOGRAMA_IVA, DISTRIBUICAO_DAS


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURE: Empresa e operação padrão para testes de trilha
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def motor_simples():
    """Motor Simples Nacional padrão para testes de trilha."""
    fornecedora = EmpresaFornecedora(
        cnpj="11.222.333/0001-81",
        razao_social="Empresa Teste Guardrails LTDA",
        regime="SIMPLES",
        cnae_principal="4711302",
        uf_origem="SP",
        faturamento_12m=Decimal("500000.00"),
        folha_salarios_12m=Decimal("100000.00"),
        anexo_simples="I",
    )
    compradora = EmpresaCompradora(
        tipo="B2B_CONTRIBUINTE",
        uf_destino="SP",
    )
    operacao = OperacaoFiscal(
        data_emissao=date(2026, 6, 15),
        valor_operacao=Decimal("50000.00"),
        ncm_nbs="84099190",
        forma_recebimento="PIX_BOLETO",
    )
    motor = MotorReformaTributaria(fornecedora, compradora, operacao)
    # Dispara cálculos para popular a trilha
    motor.gerar_diagnostico()
    return motor


# ═════════════════════════════════════════════════════════════════════════════
# G-02: TODOS OS PASSOS DA TRILHA DEVEM TER "tipo"
# ═════════════════════════════════════════════════════════════════════════════

class TestG02TrilhaTipoCalculo:
    """
    G-02: Cada passo na trilha_auditoria deve ter o campo 'tipo' definido.
    Previne inconsistência entre _registrar_passo() do motor principal
    e dos engines de regime (BUG-01).
    """

    def test_todos_passos_tem_tipo(self, motor_simples):
        """Nenhum passo da trilha pode ter 'tipo' ausente ou vazio."""
        trilha = motor_simples.trilha_auditoria
        assert len(trilha) > 0, "Trilha de auditoria vazia — motor não registrou passos"

        passos_sem_tipo = []
        for i, passo in enumerate(trilha):
            tipo = passo.get("tipo")
            if not tipo or not str(tipo).strip():
                passos_sem_tipo.append(f"Passo #{i} (id={passo.get('id', '?')})")

        assert len(passos_sem_tipo) == 0, (
            f"Passos da trilha sem 'tipo': {passos_sem_tipo}. "
            f"Violação MAX_FISCAL_02 — todo passo deve ter tipo definido."
        )

    def test_tipo_calculo_presente(self, motor_simples):
        """Pelo menos um passo deve ter tipo='CALCULO'."""
        trilha = motor_simples.trilha_auditoria
        tipos = {passo.get("tipo") for passo in trilha}
        assert "CALCULO" in tipos, (
            f"Nenhum passo com tipo='CALCULO'. Tipos encontrados: {tipos}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# G-03: DISTRIBUICAO_DAS SOMA 100% POR FAIXA
# ═════════════════════════════════════════════════════════════════════════════

class TestG03DistribuicaoSoma100:
    """
    G-03: Cada faixa (1-6) de cada Anexo (I-V) na DISTRIBUICAO_DAS
    deve somar exatamente 1.0000 (100%).
    LC 123/2006, Anexos I-V — tabelas de repartição.
    """

    @pytest.mark.parametrize("anexo", ["I", "II", "III", "IV", "V"])
    def test_soma_por_faixa(self, anexo):
        """Verifica que cada faixa do Anexo soma 1.0000."""
        faixas = DISTRIBUICAO_DAS.get(anexo, {})
        assert faixas, f"Anexo {anexo} ausente em DISTRIBUICAO_DAS"

        for num_faixa, componentes in faixas.items():
            soma = sum(componentes.values())
            assert soma == Decimal("1.0000") or abs(soma - Decimal("1.0000")) <= Decimal("0.0001"), (
                f"Anexo {anexo} Faixa {num_faixa}: soma = {soma} "
                f"(esperado: 1.0000). Componentes: {componentes}"
            )

    @pytest.mark.parametrize("anexo", ["I", "II", "III", "IV", "V"])
    def test_todas_faixas_presentes(self, anexo):
        """Cada Anexo deve ter faixas 1-6."""
        faixas = DISTRIBUICAO_DAS.get(anexo, {})
        for num in range(1, 7):
            assert num in faixas, (
                f"Anexo {anexo}: faixa {num} ausente em DISTRIBUICAO_DAS"
            )


# ═════════════════════════════════════════════════════════════════════════════
# G-04: CRONOGRAMA IVA — CBS ESTÁVEL, IBS CRESCENTE
# ═════════════════════════════════════════════════════════════════════════════

class TestG04CronogramaIVA:
    """
    G-04: Verifica invariantes do CRONOGRAMA_IVA:
    - CBS estável em 0.088 de 2027 a 2033
    - IBS crescente de 2029 a 2033
    LC 214/2025, Arts. 344, 348, 353-360.
    """

    def test_cbs_estavel_2027_2033(self):
        """CBS deve ser 0.088 de 2027 a 2033 (substituindo PIS/COFINS)."""
        for ano in range(2027, 2034):
            aliquotas = CRONOGRAMA_IVA.get(ano)
            assert aliquotas is not None, f"Ano {ano} ausente no CRONOGRAMA_IVA"
            assert aliquotas["CBS"] == Decimal("0.088"), (
                f"CBS {ano} = {aliquotas['CBS']} (esperado: 0.088)"
            )

    def test_ibs_crescente_2029_2033(self):
        """IBS deve crescer monotonicamente de 2029 a 2033."""
        anos = list(range(2029, 2034))
        for i in range(len(anos) - 1):
            ibs_atual = CRONOGRAMA_IVA[anos[i]]["IBS"]
            ibs_proximo = CRONOGRAMA_IVA[anos[i + 1]]["IBS"]
            assert ibs_proximo > ibs_atual, (
                f"IBS não crescente: {anos[i]}={ibs_atual} → {anos[i+1]}={ibs_proximo}"
            )

    def test_2026_periodo_teste(self):
        """2026 deve ter CBS=0.009 e IBS=0.001 (período de teste)."""
        aliq = CRONOGRAMA_IVA[2026]
        assert aliq["CBS"] == Decimal("0.009"), f"CBS 2026 = {aliq['CBS']}"
        assert aliq["IBS"] == Decimal("0.001"), f"IBS 2026 = {aliq['IBS']}"

    def test_todos_anos_transicao_presentes(self):
        """Cronograma deve cobrir 2026-2033 sem lacunas."""
        for ano in range(2026, 2034):
            assert ano in CRONOGRAMA_IVA, f"Ano {ano} ausente no CRONOGRAMA_IVA"


# ═════════════════════════════════════════════════════════════════════════════
# G-01: VALIDAÇÃO DE CAMPOS POR REGIME
# ═════════════════════════════════════════════════════════════════════════════

class TestG01ValidarCamposRegime:
    """G-01: validar_campos_regime() deve rejeitar entradas incompletas."""

    def test_simples_valido(self):
        """Empresa Simples com todos os campos passa."""
        empresa = {
            "cnpj": "11.222.333/0001-81",
            "razao_social": "Teste LTDA",
            "regime": "SIMPLES",
            "cnae_principal": "4711302",
            "uf_origem": "SP",
            "faturamento_12m": Decimal("500000.00"),
        }
        resultado = validar_campos_regime(empresa)
        assert resultado.ok, f"Erros inesperados: {resultado.erros}"

    def test_mei_sem_categoria_falha(self):
        """MEI sem categoria_mei deve falhar."""
        empresa = {
            "cnpj": "11.222.333/0001-81",
            "razao_social": "MEI Teste",
            "regime": "MEI",
            "cnae_principal": "4711302",
            "uf_origem": "SP",
            "faturamento_12m": Decimal("50000.00"),
            "categoria_mei": None,
        }
        resultado = validar_campos_regime(empresa)
        assert not resultado.ok
        assert any("categoria_mei" in e for e in resultado.erros)

    def test_mei_acima_teto_falha(self):
        """MEI com faturamento acima de R$ 81.000 deve falhar."""
        empresa = {
            "cnpj": "11.222.333/0001-81",
            "razao_social": "MEI Rico",
            "regime": "MEI",
            "cnae_principal": "4711302",
            "uf_origem": "SP",
            "faturamento_12m": Decimal("100000.00"),
            "categoria_mei": "SERVICOS",
        }
        resultado = validar_campos_regime(empresa)
        assert not resultado.ok
        assert any("teto do MEI" in e for e in resultado.erros)

    def test_simples_acima_teto_falha(self):
        """Simples com RBT12 acima de R$ 4.800.000 deve falhar."""
        empresa = {
            "cnpj": "11.222.333/0001-81",
            "razao_social": "Grande Comércio",
            "regime": "SIMPLES",
            "cnae_principal": "4711302",
            "uf_origem": "SP",
            "faturamento_12m": Decimal("5000000.00"),
        }
        resultado = validar_campos_regime(empresa)
        assert not resultado.ok
        assert any("teto do Simples" in e for e in resultado.erros)

    def test_regime_invalido_falha(self):
        """Regime desconhecido deve falhar."""
        empresa = {"regime": "LUCRO_ARBITRADO"}
        resultado = validar_campos_regime(empresa)
        assert not resultado.ok
        assert any("desconhecido" in e for e in resultado.erros)

    def test_cnpj_ausente_falha(self):
        """CNPJ ausente deve gerar erro."""
        empresa = {
            "razao_social": "Sem CNPJ",
            "regime": "SIMPLES",
            "cnae_principal": "4711302",
            "uf_origem": "SP",
            "faturamento_12m": Decimal("100000.00"),
        }
        resultado = validar_campos_regime(empresa)
        assert not resultado.ok
        assert any("cnpj" in e for e in resultado.erros)

    def test_aviso_folha_salarios_simples(self):
        """Simples sem folha_salarios_12m deve gerar aviso (não erro)."""
        empresa = {
            "cnpj": "11.222.333/0001-81",
            "razao_social": "Sem Folha",
            "regime": "SIMPLES",
            "cnae_principal": "4711302",
            "uf_origem": "SP",
            "faturamento_12m": Decimal("300000.00"),
        }
        resultado = validar_campos_regime(empresa)
        assert resultado.ok  # Sem erro
        assert len(resultado.avisos) > 0  # Mas com aviso
        assert any("folha_salarios_12m" in a for a in resultado.avisos)

    def test_operacao_valor_ausente_falha(self):
        """OperacaoFiscal sem valor_operacao deve falhar."""
        empresa = {
            "cnpj": "11.222.333/0001-81",
            "razao_social": "Teste",
            "regime": "PRESUMIDO",
            "cnae_principal": "4711302",
            "uf_origem": "SP",
            "faturamento_12m": Decimal("1000000.00"),
        }
        operacao = {"data_emissao": date(2026, 1, 1)}
        resultado = validar_campos_regime(empresa, operacao)
        assert not resultado.ok
        assert any("valor_operacao" in e for e in resultado.erros)

    def test_pydantic_model_funciona(self):
        """Deve aceitar instância Pydantic (EmpresaFornecedora) diretamente."""
        fornecedora = EmpresaFornecedora(
            cnpj="11.222.333/0001-81",
            razao_social="Pydantic Teste",
            regime="SIMPLES",
            cnae_principal="4711302",
            uf_origem="SP",
            faturamento_12m=Decimal("400000.00"),
            folha_salarios_12m=Decimal("80000.00"),
        )
        resultado = validar_campos_regime(fornecedora)
        assert resultado.ok, f"Erros: {resultado.erros}"


# ═════════════════════════════════════════════════════════════════════════════
# G-05: ASSERT LEGAL ANCHOR — TRILHA COM AMPARO LEGAL
# ═════════════════════════════════════════════════════════════════════════════

class TestG05AssertLegalAnchor:
    """G-05: Todo passo da trilha deve ter amparo_legal não vazio."""

    def test_trilha_completa_tem_amparo(self, motor_simples):
        """Trilha de diagnóstico completo deve ter amparo legal em todos os passos."""
        trilha = motor_simples.trilha_auditoria
        sem_amparo = assert_legal_anchor(trilha)
        assert len(sem_amparo) == 0, (
            f"Passos sem amparo_legal: {sem_amparo}. "
            f"Viola MAX_FISCAL_02 — todo valor calculado deve citar artigo de lei."
        )

    def test_trilha_vazia_ok(self):
        """Trilha vazia não gera erros (não há passos para validar)."""
        sem_amparo = assert_legal_anchor([])
        assert len(sem_amparo) == 0

    def test_detecta_passo_sem_amparo(self):
        """Deve detectar passo com amparo_legal vazio."""
        trilha = [
            {"id": "PASSO_OK", "tipo": "CALCULO", "amparo_legal": "LC 123/2006"},
            {"id": "PASSO_RUIM", "tipo": "CALCULO", "amparo_legal": ""},
            {"id": "PASSO_NULL", "tipo": "CALCULO"},
        ]
        sem_amparo = assert_legal_anchor(trilha)
        assert "PASSO_RUIM" in sem_amparo
        assert "PASSO_NULL" in sem_amparo
        assert "PASSO_OK" not in sem_amparo
