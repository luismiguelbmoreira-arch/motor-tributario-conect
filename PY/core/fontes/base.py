# -*- coding: utf-8 -*-
"""
fontes/base.py — Interface FonteCliente + exceções de domínio.

Rail R5 estendido (separação rígida): motor não conhece Nibo, e-CAC, sistema
próprio nem PDF — só consome o contrato `FonteCliente`. Quando uma fonte
nova entrar, ela implementa este Protocol e pluga sem refactor do motor.

Política de erro (regra global "erro berra"):
- Fonte indisponível (rede, auth, etc) → FonteIndisponivel com causa original.
- Dados extraídos não montam um HistoricoSeisMeses válido → DadosInsuficientesNaFonte.
- Validação de schema do motor falha → propaga ValidationError do Pydantic.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from schemas.historico_seis_meses import HistoricoSeisMeses


class FonteIndisponivel(Exception):
    """
    Fonte de dados não está acessível — rede, auth, rate-limit, etc.

    O caller deve tratar como falha temporária (retry com backoff) ou pedir
    intervenção manual. Não é falha de validação dos dados.
    """


class DadosInsuficientesNaFonte(Exception):
    """
    Fonte respondeu mas os dados retornados não montam um HistoricoSeisMeses
    válido — meses faltando, RBT12 zerado, CNPJ divergente, etc.

    O caller deve mostrar pendência ao usuário ("faltam 2 meses no Nibo do
    cliente XYZ") em vez de tratar como erro genérico.
    """

    def __init__(self, mensagem: str, *, faltantes: list[str] | None = None):
        super().__init__(mensagem)
        self.faltantes = faltantes or []


@runtime_checkable
class FonteCliente(Protocol):
    """
    Contrato de uma fonte de dados que entrega histórico fiscal pronto pro motor.

    Cada fonte concreta declara seu `nome` (identificador estável usado em
    trilha de auditoria e logs) e implementa `obter_historico_seis_meses`.

    Implementações esperadas:
    - FontePDFManual: PDFs PGDAS-D + Claude Vision.
    - FonteNibo: API Nibo (parqueada).
    - FonteSistemaProprio: sistema interno de notas.
    - FonteECAC: scraping/integração e-CAC Plus.

    Contratual:
    - `nome` é constante por fonte (não muda entre instâncias).
    - `obter_historico_seis_meses` levanta FonteIndisponivel ou
      DadosInsuficientesNaFonte em vez de retornar None / dict vazio.
    - Sucesso = HistoricoSeisMeses com 6 meses consecutivos validados.
    """

    nome: str

    def obter_historico_seis_meses(
        self,
        cnpj: str,
        mes_inicio: str,
    ) -> HistoricoSeisMeses:
        """
        Retorna 6 meses consecutivos de histórico fiscal a partir de `mes_inicio`.

        Args:
            cnpj: CNPJ da empresa (apenas dígitos, 14 chars).
            mes_inicio: primeiro mês do período no formato "YYYY-MM".

        Returns:
            HistoricoSeisMeses pronto pra `gerar_diagnostico_consolidado`.

        Raises:
            FonteIndisponivel: fonte não respondeu ou auth falhou.
            DadosInsuficientesNaFonte: dados não montam histórico válido.
            ValidationError: dados extraídos violam o schema do motor.
        """
        ...
