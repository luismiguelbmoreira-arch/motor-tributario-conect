"""
test_fase5_stress.py — Testes de Estresse Baseados na Matriz de Risco Operacional (R14-R17)
Cobre validações das guard clauses de operações críticas e limites operacionais.
"""
import pytest
from datetime import date
from decimal import Decimal

from motor_tributario import EmpresaFornecedora, EmpresaCompradora, OperacaoFiscal, MotorReformaTributaria


@pytest.fixture
def empresa_fornecedora_base():
    return EmpresaFornecedora(
        cnpj="06.990.590/0001-23",
        razao_social="CANAVEZI ELETRO COMERCIO LTDA",
        cnae_principal="4757100",  # Comércio, Anexo I
        regime="SIMPLES",
        faturamento_12m=Decimal("500000.00"),
        uf_origem="SP"
    )


@pytest.fixture
def empresa_compradora_base():
    # EmpresaCompradora schema: tipo, percentual_b2b (default), regime (default), uf_destino
    return EmpresaCompradora(
        tipo="B2B_CONTRIBUINTE",
        uf_destino="SP"
    )

# ─────────────────────────────────────────────────────────────────────────────
# C1 (R14) — Fantasma do Ano Novo
# ─────────────────────────────────────────────────────────────────────────────
class TestR14FantasmaDoAnoNovo:
    
    def test_liquidacao_impossivel(self):
        """Rail de segurança: liquidacao < emissao levanta erro no Pydantic"""
        with pytest.raises(ValueError, match="não pode ser anterior à emissão"):
            OperacaoFiscal(
                data_emissao=date(2026, 12, 10),
                data_liquidacao=date(2026, 11, 10),  # ERRO PROPOSITAL
                valor_operacao=Decimal("1000.00"),
                ncm_nbs="8517.12.31"
            )

    def test_alerta_conciliacao_ano_virada(self, empresa_fornecedora_base, empresa_compradora_base):
        """Emissão em Dez/2026 (sem split payment) liquidada em Jan/2027 (com split payment)"""
        op = OperacaoFiscal(
            data_emissao=date(2026, 12, 31),
            data_liquidacao=date(2027, 1, 5),
            valor_operacao=Decimal("15000.00"),
            ncm_nbs="8517.12.31"
        )
        motor = MotorReformaTributaria(empresa_fornecedora_base, empresa_compradora_base, op)
        alertas = motor._gerar_alertas()
        codigos = [a["codigo"] for a in alertas]
        assert "CONCILIACAO_RISCO" in codigos

    def test_sem_alerta_conciliacao_mesmo_ano(self, empresa_fornecedora_base, empresa_compradora_base):
        """Operação que não cruza ano/regime (mesmo que mude o mês) não deve gerar o alerta"""
        op = OperacaoFiscal(
            data_emissao=date(2027, 1, 20),
            data_liquidacao=date(2027, 2, 5),
            valor_operacao=Decimal("15000.00"),
            ncm_nbs="8517.12.31"
        )
        motor = MotorReformaTributaria(empresa_fornecedora_base, empresa_compradora_base, op)
        alertas = motor._gerar_alertas()
        codigos = [a["codigo"] for a in alertas]
        assert "CONCILIACAO_RISCO" not in codigos


# ─────────────────────────────────────────────────────────────────────────────
# C2 (R15) — Explosão do Sublimite
# ─────────────────────────────────────────────────────────────────────────────
class TestR15ExplosaoSublimite:

    def test_alerta_ultrapassa_sublimite_exato(self, empresa_fornecedora_base, empresa_compradora_base):
        """Empresa a R$ 3.590.000 emite nota de R$ 20.000 ultrapassando exatos R$ 3.6 Milhões"""
        empresa_fornecedora_base.faturamento_12m = Decimal("3590000.00")
        
        op = OperacaoFiscal(
            data_emissao=date(2026, 2, 10),
            valor_operacao=Decimal("20000.00"),
            ncm_nbs="8517.12.31"
        )
        motor = MotorReformaTributaria(empresa_fornecedora_base, empresa_compradora_base, op)
        alertas = motor._gerar_alertas()
        codigos = [a["codigo"] for a in alertas]
        assert "SUBLIMITE_CRITICO" in codigos
        
    def test_nao_dispara_se_ja_estava_acima(self, empresa_fornecedora_base, empresa_compradora_base):
        """Empresa que JÁ estava acima do sublimite não dispara o alerta crítico, mas o alerta MEDIO"""
        empresa_fornecedora_base.faturamento_12m = Decimal("3700000.00") # Já excedeu antes
        
        op = OperacaoFiscal(
            data_emissao=date(2026, 2, 10),
            valor_operacao=Decimal("5000.00"),
            ncm_nbs="8517.12.31"
        )
        motor = MotorReformaTributaria(empresa_fornecedora_base, empresa_compradora_base, op)
        alertas = motor._gerar_alertas()
        codigos = [a["codigo"] for a in alertas]
        assert "SUBLIMITE_CRITICO" not in codigos
        assert "SUBLIMITE_ICMS_ISS" in codigos # Alerta legado


# ─────────────────────────────────────────────────────────────────────────────
# C3 (R16) — Salada de Frutas (Timeouts CGIBS)
# ─────────────────────────────────────────────────────────────────────────────
class TestR16SaladaDeFrutas:

    @pytest.mark.parametrize("qtd,dispara", [
        (10, False),
        (30, False),
        (50, False),  # Limite exato
        (51, True),   # Estoura o limite
        (70, True),
    ])
    def test_carga_itens_escalonada(self, empresa_fornecedora_base, empresa_compradora_base, qtd, dispara):
        """Rail de segurança: testando fallback de overload nas NFs"""
        op = OperacaoFiscal(
            data_emissao=date(2026, 3, 1),
            valor_operacao=Decimal("50000.00"),
            ncm_nbs="8517.12.31",
            qtd_itens=qtd
        )
        motor = MotorReformaTributaria(empresa_fornecedora_base, empresa_compradora_base, op)
        alertas = motor._gerar_alertas()
        codigos = [a["codigo"] for a in alertas]
        
        if dispara:
            assert "RISCO_TIMEOUT_API" in codigos
        else:
            assert "RISCO_TIMEOUT_API" not in codigos


# ─────────────────────────────────────────────────────────────────────────────
# C4 (R17) — Estorno do Medo
# ─────────────────────────────────────────────────────────────────────────────
class TestR17EstornoDoMedo:

    def test_operacao_estornada(self, empresa_fornecedora_base, empresa_compradora_base):
        """Cross check entre flag de estorno com o aviso de liquidez comprometida"""
        op = OperacaoFiscal(
            data_emissao=date(2027, 4, 1), # Split payment ativo
            data_liquidacao=date(2027, 4, 2),
            valor_operacao=Decimal("1500.00"),
            ncm_nbs="8517.12.31",
            estorno_realizado=True
        )
        motor = MotorReformaTributaria(empresa_fornecedora_base, empresa_compradora_base, op)
        alertas = motor._gerar_alertas()
        codigos = [a["codigo"] for a in alertas]
        assert "CAPITAL_GIRO_COMPROMETIDO" in codigos
