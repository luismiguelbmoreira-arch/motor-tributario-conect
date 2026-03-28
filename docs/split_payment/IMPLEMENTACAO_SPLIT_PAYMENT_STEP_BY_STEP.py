"""
O VICIADO: Guia de Implementação Step-by-Step
Strategy Pattern + Decimal + Enum para Split Payment (2026-2033)

Arquivo: IMPLEMENTACAO_SPLIT_PAYMENT_STEP_BY_STEP.py
Status: Pronto para refactorização em motor_tributario.py
"""

from enum import Enum
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Protocol, List, Optional
from dataclasses import dataclass
from datetime import date


# ═════════════════════════════════════════════════════════════════════════════
# PASSO 1: ENUM de Anos com Rastreabilidade Legal
# ═════════════════════════════════════════════════════════════════════════════

class AnoTransicaoIVA(Enum):
    """Cada ano da transição (2026-2033) vinculado à sua lei e fase."""

    ANO_2026 = (2026, "LC 214/2025, Art. 348", "TESTE")
    ANO_2027 = (2027, "LC 214/2025, Art. 344-353", "EFETIVO")
    ANO_2028 = (2028, "LC 214/2025, Art. 344-353", "EFETIVO")
    ANO_2029 = (2029, "LC 214/2025, Art. 360-362", "TRANSICAO_ICMS_ISS")
    ANO_2030 = (2030, "LC 214/2025, Art. 360-362", "TRANSICAO_ICMS_ISS")
    ANO_2031 = (2031, "LC 214/2025, Art. 360-362", "TRANSICAO_ICMS_ISS")
    ANO_2032 = (2032, "LC 214/2025, Art. 360-362", "TRANSICAO_ICMS_ISS")
    ANO_2033 = (2033, "LC 214/2025, Art. 361-366", "REGIME_PLENO")

    @property
    def ano_num(self) -> int:
        return self.value[0]

    @property
    def lei_vigente(self) -> str:
        return self.value[1]

    @property
    def fase(self) -> str:
        return self.value[2]

    @classmethod
    def from_ano(cls, ano: int) -> "AnoTransicaoIVA":
        for membro in cls:
            if membro.ano_num == ano:
                return membro
        raise ValueError(f"Ano {ano} fora do período transicional (2026-2033)")


# ═════════════════════════════════════════════════════════════════════════════
# PASSO 2: ENUM de Formas de Recebimento com Elegibilidade
# ═════════════════════════════════════════════════════════════════════════════

class FormaRecebimento(Enum):
    """
    LC 214/2025, Art. X: Split Payment obrigatório APENAS para transferências
    eletrônicas (com intermediador: PIX, Boleto, Cartão).

    DINHEIRO e CHEQUE: isentos (sem rede eletrônica).
    """

    PIX = "PIX"
    BOLETO = "BOLETO"
    CARTAO_CREDITO = "CARTAO_CREDITO"
    CARTAO_DEBITO = "CARTAO_DEBITO"
    TED = "TED"
    DINHEIRO = "DINHEIRO"
    CHEQUE = "CHEQUE"

    def eh_eletronico(self) -> bool:
        """Indica se forma passa por intermediador financeiro."""
        return self not in (FormaRecebimento.DINHEIRO, FormaRecebimento.CHEQUE)


# ═════════════════════════════════════════════════════════════════════════════
# PASSO 3: DATACLASS para Alíquotas com Rastreabilidade
# ═════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class AliquotasIVA:
    """
    Capsulação de CBS e IBS com fonte legal.
    Frozen=True garante imutabilidade (segurança auditoria).

    Formato: Decimal com 4+ casas decimais (ex: 0.0089 = 0,89%)
    """

    cbs: Decimal       # Contribuição sobre Bens e Serviços
    ibs: Decimal       # Imposto sobre Bens e Serviços
    ano: int
    lei_vigente: str   # Ex: "LC 214/2025, Art. 348"

    def total(self) -> Decimal:
        """Retorna CBS + IBS com precisão decimal."""
        return (self.cbs + self.ibs).quantize(Decimal("0.000001"), ROUND_HALF_UP)

    def __repr__(self) -> str:
        return (
            f"AliquotasIVA(ano={self.ano}, CBS={self.cbs*100:.2f}%, "
            f"IBS={self.ibs*100:.2f}%, Total={self.total()*100:.2f}%)"
        )


# ═════════════════════════════════════════════════════════════════════════════
# PASSO 4: REGISTRY de Alíquotas (Cronograma Oficial)
# ═════════════════════════════════════════════════════════════════════════════

class CronogramaIVA:
    """
    Registry centralizado de alíquotas IVA 2026-2033.
    Fonte: LC 214/2025, Art. 344, 348, 353-366.

    CRITICAMENTE: permite atualização por Resolução Senado Federal
    sem quebrar código existente (padrão Registry).
    """

    _aliquotas: Dict[int, AliquotasIVA] = {
        2026: AliquotasIVA(
            cbs=Decimal("0.009"),
            ibs=Decimal("0.001"),
            ano=2026,
            lei_vigente="LC 214/2025, Art. 348 (período de TESTE)"
        ),
        2027: AliquotasIVA(
            cbs=Decimal("0.088"),   # 8,8% (substitui PIS+COFINS)
            ibs=Decimal("0.001"),   # 0,1% (teste final)
            ano=2027,
            lei_vigente="LC 214/2025, Art. 344-353 (efetivo)"
        ),
        2028: AliquotasIVA(
            cbs=Decimal("0.088"),
            ibs=Decimal("0.001"),
            ano=2028,
            lei_vigente="LC 214/2025, Art. 344-353 (efetivo)"
        ),
        2029: AliquotasIVA(
            cbs=Decimal("0.088"),
            ibs=Decimal("0.035"),   # ~20% da alíquota plena
            ano=2029,
            lei_vigente="LC 214/2025, Art. 360-362 (transição ICMS/ISS)"
        ),
        2030: AliquotasIVA(
            cbs=Decimal("0.088"),
            ibs=Decimal("0.071"),   # ~40%
            ano=2030,
            lei_vigente="LC 214/2025, Art. 360-362"
        ),
        2031: AliquotasIVA(
            cbs=Decimal("0.088"),
            ibs=Decimal("0.106"),   # ~60%
            ano=2031,
            lei_vigente="LC 214/2025, Art. 360-362"
        ),
        2032: AliquotasIVA(
            cbs=Decimal("0.088"),
            ibs=Decimal("0.142"),   # ~80%
            ano=2032,
            lei_vigente="LC 214/2025, Art. 360-362"
        ),
        2033: AliquotasIVA(
            cbs=Decimal("0.088"),
            ibs=Decimal("0.177"),   # 100% (regime pleno)
            ano=2033,
            lei_vigente="LC 214/2025, Art. 361-366 (regime PLENO)"
        ),
    }

    @classmethod
    def obter_aliquotas(cls, ano: int) -> AliquotasIVA:
        """Busca alíquotas de um ano (fail-fast se fora do período)."""
        if ano not in cls._aliquotas:
            raise ValueError(f"Ano {ano} não consta no cronograma IVA (2026-2033)")
        return cls._aliquotas[ano]

    @classmethod
    def adicionar_aliquotas(cls, ano: int, aliquotas: AliquotasIVA) -> None:
        """
        Atualiza cronograma via Resolução Senado Federal.
        Exemplo: CBS aumentado para 9,2% por decisão do Senado em 2027.

        Operação: 3 linhas de código, zero alterações em lógica existente.
        """
        if not (2026 <= ano <= 2033):
            raise ValueError(f"Fora do período transicional: {ano}")
        cls._aliquotas[ano] = aliquotas
        # Log para auditoria: print(f"[CRONOGRAMA] Alíquotas {ano} atualizadas")

    @classmethod
    def listar_cronograma(cls) -> Dict[int, AliquotasIVA]:
        """Retorna cópia do cronograma (visualização)."""
        return dict(cls._aliquotas)


# ═════════════════════════════════════════════════════════════════════════════
# PASSO 5: PROTOCOL (Interface) para Estratégias de Retenção
# ═════════════════════════════════════════════════════════════════════════════

class EstrategiaRetencaoSplit(Protocol):
    """
    Define contrato que toda estratégia deve cumprir.

    Benefício: novas estratégias implementam exatamente estes 3 métodos,
    sem dependência cíclica ou acoplamento.
    """

    def calcular_retencao(
        self,
        valor_nf: Decimal,
        aliquotas: AliquotasIVA,
        forma: FormaRecebimento
    ) -> Decimal:
        """Retorna valor retido na fonte (em reais)."""
        ...

    def eh_elegivel(self, ano: int, forma: FormaRecebimento) -> bool:
        """Retorna True se Split Payment se aplica neste cenário."""
        ...

    def obter_mensagem_impacto(self) -> str:
        """Explicação amigável do impacto financeiro."""
        ...


# ═════════════════════════════════════════════════════════════════════════════
# PASSO 6: ESTRATÉGIAS CONCRETAS (Implementações)
# ═════════════════════════════════════════════════════════════════════════════

class RetencaoSplitPaymentIsenta2026:
    """
    2026: Período de teste.
    LC 214/2025, Art. 348: recolhimento DISPENSADO.
    Contribuintes isentos de retenção obrigatória (apenas obrigações acessórias).
    """

    def calcular_retencao(
        self,
        valor_nf: Decimal,
        aliquotas: AliquotasIVA,
        forma: FormaRecebimento
    ) -> Decimal:
        return Decimal("0.00")

    def eh_elegivel(self, ano: int, forma: FormaRecebimento) -> bool:
        """Nunca elegível: 2026 é isento."""
        return False

    def obter_mensagem_impacto(self) -> str:
        return (
            "2026: Período de TESTE (LC 214/2025, Art. 348). "
            "Recolhimento dispensado, apenas obrigações acessórias."
        )


class RetencaoSplitPaymentPadrao:
    """
    Estratégia padrão (2027+): retenção integral de CBS+IBS na fonte
    para pagamentos eletrônicos.

    Exemplo 2027: R$ 10.000 × (8,8% + 0,1%) = R$ 890 retido.
    """

    def calcular_retencao(
        self,
        valor_nf: Decimal,
        aliquotas: AliquotasIVA,
        forma: FormaRecebimento
    ) -> Decimal:
        taxa_total = aliquotas.total()
        retencao = valor_nf * taxa_total
        return retencao.quantize(Decimal("0.01"), ROUND_HALF_UP)

    def eh_elegivel(self, ano: int, forma: FormaRecebimento) -> bool:
        """Elegível: 2027+ E forma eletrônica."""
        return ano >= 2027 and forma.eh_eletronico()

    def obter_mensagem_impacto(self) -> str:
        return (
            "Split Payment padrão (LC 214/2025): retenção integral na fonte. "
            "ALTO impacto de liquidez — IBS/CBS retido antes de cair na conta."
        )


class RetencaoSplitPaymentReservaDinheiro:
    """
    Estratégia de isenção: DINHEIRO e CHEQUE não têm intermediador.
    LC 214/2025, Art. X: isento em operações sem rede eletrônica.
    """

    def calcular_retencao(
        self,
        valor_nf: Decimal,
        aliquotas: AliquotasIVA,
        forma: FormaRecebimento
    ) -> Decimal:
        return Decimal("0.00")

    def eh_elegivel(self, ano: int, forma: FormaRecebimento) -> bool:
        """Nunca elegível: dinheiro não passa por intermediador."""
        return False

    def obter_mensagem_impacto(self) -> str:
        return (
            "Pagamento em DINHEIRO/CHEQUE: isento de Split Payment "
            "(sem intermediador financeiro)."
        )


class RetencaoSplitPaymentComDesconto:
    """
    Estratégia extensível: retenção reduzida por política pública.

    Exemplo: Senado Federal publica Resolução com desconto para PME,
    indústria 4.0, setores estratégicos, etc.
    """

    def __init__(self, percentual_reducao: Decimal = Decimal("0.0")):
        """
        percentual_reducao: Ex. Decimal("0.50") = 50% de desconto.
        """
        self.percentual_reducao = percentual_reducao

    def calcular_retencao(
        self,
        valor_nf: Decimal,
        aliquotas: AliquotasIVA,
        forma: FormaRecebimento
    ) -> Decimal:
        taxa_base = aliquotas.total()
        taxa_efetiva = taxa_base * (Decimal("1.0") - self.percentual_reducao)
        retencao = valor_nf * taxa_efetiva
        return retencao.quantize(Decimal("0.01"), ROUND_HALF_UP)

    def eh_elegivel(self, ano: int, forma: FormaRecebimento) -> bool:
        """Elegível se eletrônico e desconto aplicável."""
        return ano >= 2027 and forma.eh_eletronico()

    def obter_mensagem_impacto(self) -> str:
        perc_desc = (self.percentual_reducao * 100).quantize(Decimal("0.0"), ROUND_HALF_UP)
        return (
            f"Split Payment com retenção reduzida ({perc_desc}% de desconto). "
            f"Política de fomento PME ou setor estratégico."
        )


# ═════════════════════════════════════════════════════════════════════════════
# PASSO 7: FACTORY (Seletor Automático de Estratégia)
# ═════════════════════════════════════════════════════════════════════════════

class FabricaEstrategiaRetencao:
    """
    Factory Pattern: seleciona automaticamente a estratégia certa
    baseada em: ano, forma de recebimento, políticas ativas.

    Benefício: decisão centralizada, fácil de estender.
    """

    _cache_estrategias: Dict[tuple, EstrategiaRetencaoSplit] = {}

    @classmethod
    def obter_estrategia(
        cls,
        ano: int,
        forma: FormaRecebimento,
        politica_reducao: Decimal = Decimal("0.0")
    ) -> EstrategiaRetencaoSplit:
        """
        Lógica de seleção:
        1. 2026 → isento
        2. Não-eletrônico (DINHEIRO/CHEQUE) → isento
        3. Eletrônico com desconto → RetencaoComDesconto
        4. Eletrônico sem desconto → Padrão

        Cache para performance (memoization).
        """

        chave_cache = (ano, forma, politica_reducao)

        if chave_cache in cls._cache_estrategias:
            return cls._cache_estrategias[chave_cache]

        # Decisão de estratégia
        if ano == 2026:
            estrategia = RetencaoSplitPaymentIsenta2026()
        elif not forma.eh_eletronico():
            estrategia = RetencaoSplitPaymentReservaDinheiro()
        elif politica_reducao > Decimal("0.0"):
            estrategia = RetencaoSplitPaymentComDesconto(politica_reducao)
        else:
            estrategia = RetencaoSplitPaymentPadrao()

        cls._cache_estrategias[chave_cache] = estrategia
        return estrategia

    @classmethod
    def limpar_cache(cls) -> None:
        """Limpa cache (útil em testes)."""
        cls._cache_estrategias.clear()


# ═════════════════════════════════════════════════════════════════════════════
# PASSO 8: DATACLASSES para Entrada e Saída
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ParametrosSplitPayment:
    """Entrada para cálculo."""
    valor_nf: Decimal
    ano_emissao: int
    forma_recebimento: FormaRecebimento
    cnae: Optional[str] = None
    regime_contribuinte: Optional[str] = None


@dataclass
class ResultadoSplitPayment:
    """Saída estruturada."""
    ativo: bool
    valor_retido: Decimal
    percentual_taxa: Decimal
    aliquotas: AliquotasIVA
    estrategia_classe: str
    lei_vigente: str
    fase_transicao: str
    mensagem_impacto: str
    avisos: Optional[List[str]] = None


# ═════════════════════════════════════════════════════════════════════════════
# PASSO 9: CALCULADORA (Orquestrador)
# ═════════════════════════════════════════════════════════════════════════════

class CalculadoraSplitPayment:
    """
    Orquestrador que integra:
    - AnoTransicaoIVA (Enum)
    - CronogramaIVA (Registry)
    - Estratégias (Factory)
    - Resultado (Dataclass)

    Interface única e simples para motor_tributario.py.
    """

    def __init__(self, politica_reducao: Decimal = Decimal("0.0")):
        self.politica_reducao = politica_reducao

    def calcular(self, parametros: ParametrosSplitPayment) -> ResultadoSplitPayment:
        """
        Fluxo completo:
        1. Validação (Enum)
        2. Busca alíquotas (Registry)
        3. Seleção estratégia (Factory)
        4. Cálculo (Strategy)
        5. Estruturação (Dataclass)
        """

        # 1. Mapeamento de ano
        ano_enum = AnoTransicaoIVA.from_ano(parametros.ano_emissao)

        # 2. Busca alíquotas
        aliquotas = CronogramaIVA.obter_aliquotas(parametros.ano_emissao)

        # 3. Seleção de estratégia
        estrategia = FabricaEstrategiaRetencao.obter_estrategia(
            parametros.ano_emissao,
            parametros.forma_recebimento,
            self.politica_reducao
        )

        # 4. Cálculo
        valor_retido = estrategia.calcular_retencao(
            parametros.valor_nf,
            aliquotas,
            parametros.forma_recebimento
        )

        # 5. Avisos automáticos
        avisos = []
        if parametros.ano_emissao == 2026:
            avisos.append(
                "2026 é período de teste: alíquotas sujeitas a ajuste por "
                "Resolução do Senado Federal."
            )
        if valor_retido > Decimal("0.00"):
            avisos.append(
                f"IMPACTO DE LIQUIDEZ: R$ {valor_retido:,.2f} retido "
                f"a cada operação."
            )

        return ResultadoSplitPayment(
            ativo=estrategia.eh_elegivel(parametros.ano_emissao, parametros.forma_recebimento),
            valor_retido=valor_retido,
            percentual_taxa=aliquotas.total(),
            aliquotas=aliquotas,
            estrategia_classe=estrategia.__class__.__name__,
            lei_vigente=aliquotas.lei_vigente,
            fase_transicao=ano_enum.fase,
            mensagem_impacto=estrategia.obter_mensagem_impacto(),
            avisos=avisos if avisos else None
        )


# ═════════════════════════════════════════════════════════════════════════════
# PASSO 10: TESTES UNITÁRIOS
# ═════════════════════════════════════════════════════════════════════════════

def run_tests():
    """Suite de testes completa."""
    print("\n" + "="*80)
    print("TESTES: Split Payment Strategy Pattern")
    print("="*80 + "\n")

    calc = CalculadoraSplitPayment()

    # Test 1: Enum de anos
    print("Test 1: Enum de anos (validação)")
    try:
        ano_enum = AnoTransicaoIVA.from_ano(2027)
        assert ano_enum.lei_vigente == "LC 214/2025, Art. 344-353"
        assert ano_enum.fase == "EFETIVO"
        print(f"  ✓ 2027: {ano_enum}")
    except Exception as e:
        print(f"  ✗ FALHOU: {e}")
        return

    # Test 2: Cronograma (acesso simples)
    print("\nTest 2: Cronograma IVA (acesso)")
    aliq_2027 = CronogramaIVA.obter_aliquotas(2027)
    print(f"  ✓ 2027: CBS={aliq_2027.cbs}, IBS={aliq_2027.ibs}, Total={aliq_2027.total()}")
    assert aliq_2027.total() == Decimal("0.089"), "Erro no cálculo de total"

    # Test 3: Formas de recebimento
    print("\nTest 3: Formas de recebimento")
    assert FormaRecebimento.PIX.eh_eletronico() == True
    assert FormaRecebimento.DINHEIRO.eh_eletronico() == False
    print(f"  ✓ PIX eletrônico: {FormaRecebimento.PIX.eh_eletronico()}")
    print(f"  ✓ DINHEIRO eletrônico: {FormaRecebimento.DINHEIRO.eh_eletronico()}")

    # Test 4: 2026 (isento)
    print("\nTest 4: 2026 (período de teste, isento)")
    r = calc.calcular(ParametrosSplitPayment(
        valor_nf=Decimal("10000.00"),
        ano_emissao=2026,
        forma_recebimento=FormaRecebimento.PIX
    ))
    assert r.ativo == False
    assert r.valor_retido == Decimal("0.00")
    print(f"  ✓ 2026 PIX: ativo={r.ativo}, retido={r.valor_retido}")
    print(f"    Estratégia: {r.estrategia_classe}")
    print(f"    Lei: {r.lei_vigente}")

    # Test 5: 2027 PIX (8,9%)
    print("\nTest 5: 2027 PIX (Split obrigatório 8,9%)")
    r = calc.calcular(ParametrosSplitPayment(
        valor_nf=Decimal("10000.00"),
        ano_emissao=2027,
        forma_recebimento=FormaRecebimento.PIX
    ))
    assert r.ativo == True
    assert r.valor_retido == Decimal("890.00")
    print(f"  ✓ 2027 PIX: ativo={r.ativo}, retido={r.valor_retido}")
    print(f"    Percentual: {r.percentual_taxa * 100:.2f}%")
    print(f"    Estratégia: {r.estrategia_classe}")

    # Test 6: 2027 DINHEIRO (isento)
    print("\nTest 6: 2027 DINHEIRO (isento de Split)")
    r = calc.calcular(ParametrosSplitPayment(
        valor_nf=Decimal("10000.00"),
        ano_emissao=2027,
        forma_recebimento=FormaRecebimento.DINHEIRO
    ))
    assert r.ativo == False
    assert r.valor_retido == Decimal("0.00")
    print(f"  ✓ 2027 DINHEIRO: ativo={r.ativo}, retido={r.valor_retido}")
    print(f"    Estratégia: {r.estrategia_classe}")

    # Test 7: 2033 (regime pleno, 26,5%)
    print("\nTest 7: 2033 CARTAO_CREDITO (regime pleno 26,5%)")
    r = calc.calcular(ParametrosSplitPayment(
        valor_nf=Decimal("10000.00"),
        ano_emissao=2033,
        forma_recebimento=FormaRecebimento.CARTAO_CREDITO
    ))
    assert r.ativo == True
    assert r.valor_retido == Decimal("2650.00")
    print(f"  ✓ 2033 CARTAO: ativo={r.ativo}, retido={r.valor_retido}")
    print(f"    Percentual: {r.percentual_taxa * 100:.2f}%")
    print(f"    CBS={r.aliquotas.cbs*100:.1f}% + IBS={r.aliquotas.ibs*100:.1f}%")

    # Test 8: Precisão Decimal
    print("\nTest 8: Precisão Decimal (sem erros de float)")
    r = calc.calcular(ParametrosSplitPayment(
        valor_nf=Decimal("99.99"),
        ano_emissao=2027,
        forma_recebimento=FormaRecebimento.BOLETO
    ))
    esperado = (Decimal("99.99") * Decimal("0.089")).quantize(Decimal("0.01"), ROUND_HALF_UP)
    assert r.valor_retido == esperado
    print(f"  ✓ 99.99 × 8.9% = {r.valor_retido} (precisão Decimal)")

    # Test 9: Atualização de cronograma (sem quebra)
    print("\nTest 9: Atualização de cronograma (Resolução Senado Federal)")
    aliq_original = CronogramaIVA.obter_aliquotas(2027)
    print(f"  Original 2027: CBS={aliq_original.cbs}")

    # Simula Resolução Senado: CBS aumenta de 8,8% para 9,2%
    CronogramaIVA.adicionar_aliquotas(
        2027,
        AliquotasIVA(
            cbs=Decimal("0.092"),
            ibs=Decimal("0.001"),
            ano=2027,
            lei_vigente="LC 214/2025 + Res. Senado (Jul/2027)"
        )
    )

    r_novo = calc.calcular(ParametrosSplitPayment(
        valor_nf=Decimal("10000.00"),
        ano_emissao=2027,
        forma_recebimento=FormaRecebimento.PIX
    ))
    print(f"  Novo 2027: CBS={r_novo.aliquotas.cbs}")
    assert r_novo.valor_retido == Decimal("930.00")  # 10000 × 0.093
    print(f"  ✓ Novo cálculo 2027 PIX: retido={r_novo.valor_retido}")

    # Restaura valor original
    CronogramaIVA.adicionar_aliquotas(
        2027,
        aliq_original
    )

    # Test 10: Desconto PME
    print("\nTest 10: Desconto PME (50% de redução na taxa)")
    calc_pme = CalculadoraSplitPayment(politica_reducao=Decimal("0.50"))
    r = calc_pme.calcular(ParametrosSplitPayment(
        valor_nf=Decimal("10000.00"),
        ano_emissao=2027,
        forma_recebimento=FormaRecebimento.PIX
    ))
    assert r.ativo == True
    assert r.valor_retido == Decimal("445.00")  # 10000 × 0.089 × 0.5
    print(f"  ✓ 2027 PIX com 50% desconto PME: retido={r.valor_retido}")
    print(f"    Estratégia: {r.estrategia_classe}")

    print("\n" + "="*80)
    print("✅ TODOS OS TESTES PASSARAM!")
    print("="*80 + "\n")


# ═════════════════════════════════════════════════════════════════════════════
# PASSO 11: MIGRAÇÃO PARA MOTOR_TRIBUTARIO.PY
# ═════════════════════════════════════════════════════════════════════════════

def exemplo_migracao():
    """
    Demonstra como substituir método antigo em motor_tributario.py.

    ANTES (14 linhas com if/else aninhados):
    ```python
    def calcular_split_payment_impacto(self) -> Dict:
        ano = self.operacao.data_emissao.year
        forma = self.operacao.forma_recebimento

        if ano >= ANO_INICIO_SPLIT_PAYMENT and forma != "DINHEIRO":
            aliquotas_ano = self.get_aliquotas_iva_por_ano()
            taxa_retencao = aliquotas_ano["CBS"] + aliquotas_ano["IBS"]
            retencao = (self.operacao.valor_operacao * taxa_retencao).quantize(...)
            return {
                "ativo": True,
                "retencao_imediata": str(retencao),
                ...
            }
        return {
            "ativo": False,
            "motivo": "...",
            ...
        }
    ```

    DEPOIS (3 linhas claras):
    ```python
    def calcular_split_payment_impacto(self) -> Dict:
        calculadora = CalculadoraSplitPayment()
        resultado = calculadora.calcular(
            ParametrosSplitPayment(
                valor_nf=self.operacao.valor_operacao,
                ano_emissao=self.operacao.data_emissao.year,
                forma_recebimento=FormaRecebimento[self.operacao.forma_recebimento]
            )
        )

        return {
            "ativo": resultado.ativo,
            "retencao_imediata": str(resultado.valor_retido),
            "percentual_retencao": f"{resultado.percentual_taxa * 100:.2f}%",
            "lei_vigente": resultado.lei_vigente,
            "estrategia": resultado.estrategia_classe,
            "impacto_liquidez": resultado.mensagem_impacto,
            "avisos": resultado.avisos or [],
        }
    ```
    """
    print("\n" + "="*80)
    print("EXEMPLO: Integração com motor_tributario.py")
    print("="*80 + "\n")

    # Simula objeto de operação
    from dataclasses import dataclass as dc

    @dc
    class MockOperacao:
        valor_operacao: Decimal
        data_emissao: date
        forma_recebimento: str

    operacao = MockOperacao(
        valor_operacao=Decimal("5000.00"),
        data_emissao=date(2027, 3, 15),
        forma_recebimento="PIX"
    )

    # Novo método (refatorado)
    def calcular_split_payment_impacto(operacao) -> Dict:
        calculadora = CalculadoraSplitPayment()
        resultado = calculadora.calcular(
            ParametrosSplitPayment(
                valor_nf=operacao.valor_operacao,
                ano_emissao=operacao.data_emissao.year,
                forma_recebimento=FormaRecebimento[operacao.forma_recebimento]
            )
        )

        return {
            "ativo": resultado.ativo,
            "ano_ativacao": resultado.aliquotas.ano,
            "forma_recebimento": operacao.forma_recebimento,
            "retencao_imediata": str(resultado.valor_retido),
            "percentual_retencao": f"{resultado.percentual_taxa * 100:.2f}%",
            "lei_vigente": resultado.lei_vigente,
            "fase_transicao": resultado.fase_transicao,
            "estrategia": resultado.estrategia_classe,
            "impacto_liquidez": resultado.mensagem_impacto,
            "avisos": resultado.avisos or [],
        }

    # Teste
    resultado = calcular_split_payment_impacto(operacao)
    print("Resultado da operação (27/03/2027, PIX, R$ 5.000):")
    for chave, valor in resultado.items():
        print(f"  {chave}: {valor}")

    print("\n" + "="*80)


# ═════════════════════════════════════════════════════════════════════════════
# MAIN: Executa exemplos e testes
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    run_tests()
    exemplo_migracao()
