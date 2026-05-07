# -*- coding: utf-8 -*-
"""
calculo_credito_cbs_ibs.py — Caller real do mapa-mestre CBS/IBS.

Função pura que materializa o uso do `core/mapa_categorias_cbs_ibs.py`:
recebe lista de despesas categorizadas + alíquota CBS+IBS combinada e
devolve o crédito total acumulado, segregando despesas que não geram
crédito com motivo explícito.

Princípios (R9 Ampla Visão + Rail R5):
- Função pura, standalone — não acopla a EmpresaFornecedora, OperacaoFiscal
  nem ao motor de cálculo. Pode ser chamada por: script CLI, endpoint API
  novo ou (futuro) integração no `gerar_diagnostico`.
- Caller passa a alíquota explicitamente (CBS+IBS combinada). Quem decide
  qual alíquota vigente é o caller — esta função não consulta CRONOGRAMA_IVA.
- Falha fechada: valor negativo / alíquota negativa levantam ValueError.
- Despesas com categoria desconhecida vão pra `despesas_ignoradas` com
  motivo `UNKNOWN` (Rail R2 — sem decisão automática pra UNKNOWN).
- Decimal em todo número monetário; quantize a 2 casas decimais no total.

LC 214/2025 Arts. 47 caput + 57 caput + 108. Validado por Escrivão em
30/04/2026 e 07/05/2026.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Tuple

from pydantic import BaseModel, ConfigDict, Field

from core.mapa_categorias_cbs_ibs import classificar


class DespesaIgnorada(BaseModel):
    """Despesa que não entrou no cálculo de crédito (com motivo)."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    categoria: str
    valor: Decimal
    motivo: str = Field(
        ...,
        description=(
            "Motivo da exclusão: 'UNKNOWN' (categoria fora do mapa) ou "
            "tipo da classificação que NÃO gera crédito "
            "('USO_CONSUMO_PESSOAL', 'NAO_TRIBUTADO', 'CASO_DUVIDA')."
        ),
    )


class ResultadoCredito(BaseModel):
    """Saída do cálculo: total acumulado + ignoradas com motivo."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_credito: Decimal = Field(..., description="Crédito CBS+IBS total acumulado, R$")
    despesas_ignoradas: List[DespesaIgnorada]
    aliquota_aplicada: Decimal = Field(..., description="Alíquota CBS+IBS combinada usada no cálculo")
    data_referencia: date


def calcular_credito_total(
    despesas: List[Tuple[str, Decimal]],
    data_referencia: date,
    aliquota_cbs_ibs: Decimal,
) -> ResultadoCredito:
    """
    Soma crédito CBS+IBS de todas as despesas que geram crédito.

    Pra cada (categoria, valor) na lista:
    - Consulta `mapa_categorias_cbs_ibs.classificar(categoria, data_referencia)`
    - Se `gera_credito=True`, acumula `valor × aliquota_cbs_ibs`
    - Caso contrário, registra em `despesas_ignoradas` com motivo apropriado

    Args:
        despesas: lista de tuplas (categoria_canonica, valor_em_reais).
            Categoria é normalizada pra UPPER pelo `classificar`.
        data_referencia: data da operação (define versão vigente do mapa).
        aliquota_cbs_ibs: alíquota CBS+IBS combinada (decimal, ex: 0.265
            pra 26,5%). Caller obtém via CRONOGRAMA_IVA do ano.

    Returns:
        ResultadoCredito frozen com total + ignoradas + metadata.

    Raises:
        ValueError: se aliquota negativa, ou qualquer valor negativo.
    """
    if aliquota_cbs_ibs < Decimal("0"):
        raise ValueError(
            f"aliquota_cbs_ibs deve ser >= 0, recebido {aliquota_cbs_ibs}."
        )

    total = Decimal("0")
    ignoradas: List[DespesaIgnorada] = []

    for categoria, valor in despesas:
        if valor < Decimal("0"):
            raise ValueError(
                f"Valor negativo em '{categoria}': {valor}. "
                "Despesas devem ter valor >= 0."
            )

        classificacao = classificar(categoria, data_referencia)

        if classificacao is None:
            ignoradas.append(DespesaIgnorada(
                categoria=categoria,
                valor=valor,
                motivo="UNKNOWN",
            ))
            continue

        if classificacao.gera_credito:
            total += valor * aliquota_cbs_ibs
        else:
            ignoradas.append(DespesaIgnorada(
                categoria=categoria,
                valor=valor,
                motivo=classificacao.tipo,
            ))

    return ResultadoCredito(
        total_credito=total.quantize(Decimal("0.01"), ROUND_HALF_UP),
        despesas_ignoradas=ignoradas,
        aliquota_aplicada=aliquota_cbs_ibs,
        data_referencia=data_referencia,
    )
