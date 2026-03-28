# -*- coding: utf-8 -*-
"""
regimes/base.py — Infraestrutura de Segurança (3 Camadas + Trilha Unificada)
Projeto: Motor Tributário Conect 2026-2033

ARQUITETURA DE PROTEÇÃO:
  Camada 1 (Pydantic)     → valida dados na entrada (ver motor_tributario.py)
  Camada 2 (Guard Clause) → bloqueia chamada de módulo errado em tempo de execução
  Camada 3 (pytest)       → bloqueia deploy se as travas forem removidas

TRILHA UNIFICADA: todas as violações convergem para _registrar_violacao(),
que grava na mesma trilha de auditoria — conforme MAX_FISCAL_01/02.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal

logger = logging.getLogger("motor_conect.regimes")

# ─────────────────────────────────────────────────────────────────────────────
# EXCEÇÃO DE VIOLAÇÃO DE REGIME (MAX_FISCAL_02 — Ancoragem Legal)
# ─────────────────────────────────────────────────────────────────────────────

class RegimeMismatchError(Exception):
    """
    Chamada de módulo tributário incompatível com o regime da empresa.
    Ancoragem: MAX_FISCAL_02 — toda falha de regime tem endereço legal.
    """
    def __init__(self, mensagem: str, regime_empresa: str, modulo_chamado: str, lei: str):
        self.regime_empresa = regime_empresa
        self.modulo_chamado = modulo_chamado
        self.lei = lei
        super().__init__(
            f"[VIOLAÇÃO REGIME] Módulo '{modulo_chamado}' chamado para empresa regime='{regime_empresa}'. "
            f"Ancoragem: {lei}. Detalhe: {mensagem}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# TRILHA UNIFICADA — ponto único de log para todas as camadas
# ─────────────────────────────────────────────────────────────────────────────

def registrar_violacao(
    trilha: List[Dict[str, Any]],
    motivo: str,
    regime_empresa: str,
    modulo_chamado: str,
    lei: str,
) -> None:
    """
    Grava a violação na trilha de auditoria E lança a exceção.
    Chamado pelas Camadas 1, 2 e 3 — trilha sempre unificada.
    Ancoragem: MAX_FISCAL_01 (memória de cálculo) + MAX_FISCAL_02 (lei).
    """
    evento = {
        "tipo": "VIOLACAO_SEGURANCA",
        "id": f"VIOLACAO_{modulo_chamado}_{regime_empresa}",
        "titulo": "Guard Clause — Regime Incompatível",
        "formula": f"Módulo [{modulo_chamado}] ≠ Regime [{regime_empresa}]",
        "memoria": {
            "regime_empresa": regime_empresa,
            "modulo_chamado": modulo_chamado,
            "motivo": motivo,
        },
        "amparo_legal": lei,
        "detalhe": motivo,
        "timestamp": str(datetime.now()),
    }
    trilha.append(evento)

    logger.error(
        "VIOLACAO_REGIME | modulo=%s | regime=%s | lei=%s",
        modulo_chamado,
        regime_empresa,
        lei,
    )

    raise RegimeMismatchError(
        mensagem=motivo,
        regime_empresa=regime_empresa,
        modulo_chamado=modulo_chamado,
        lei=lei,
    )


# ─────────────────────────────────────────────────────────────────────────────
# BASE ENGINE — Camada 2 (Guard Clause obrigatório em todo engine filho)
# ─────────────────────────────────────────────────────────────────────────────

class BaseRegimeEngine:
    """
    Classe base para todos os motores de regime tributário.
    Implementa a Guard Clause (Camada 2) antes de qualquer cálculo.

    Todo engine filho DEVE declarar `REGIME_ACEITO` e chamar
    super().__init__() para ativar a proteção automaticamente.

    Exemplo:
        class LucroPresumidoEngine(BaseRegimeEngine):
            REGIME_ACEITO = "PRESUMIDO"
    """
    REGIME_ACEITO: Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI"] = NotImplemented  # type: ignore

    def __init__(self, fornecedora: Any, trilha: List[Dict[str, Any]]) -> None:
        self.fornecedora = fornecedora
        self.trilha = trilha

        # ── CAMADA 2: Guard Clause ────────────────────────────────────────────
        if self.REGIME_ACEITO is NotImplemented:
            raise NotImplementedError(
                f"{self.__class__.__name__} não declarou REGIME_ACEITO."
            )

        if fornecedora.regime != self.REGIME_ACEITO:
            registrar_violacao(
                trilha=self.trilha,
                motivo=(
                    f"O engine '{self.__class__.__name__}' aceita apenas '{self.REGIME_ACEITO}', "
                    f"mas a empresa está enquadrada como '{fornecedora.regime}'."
                ),
                regime_empresa=fornecedora.regime,
                modulo_chamado=self.__class__.__name__,
                lei="LC 123/2006 Art. 13 (Simples) | RIR/2018 Art. 214 (Presumido) | RIR/2018 Art. 247 (Real)",
            )

        logger.info(
            "Engine iniciado | modulo=%s | regime=%s",
            self.__class__.__name__,
            self.REGIME_ACEITO,
        )

    def _registrar_passo(
        self,
        id: str,
        titulo: str,
        base: Any,
        deducoes: Any,
        aliquota: Any,
        valor: Any,
        lei: str,
        detalhe: str = "",
    ) -> None:
        """Registro de Memória de Cálculo (MAX_FISCAL_01/02) — herdado por todos os engines."""
        passo = {
            "tipo": "CALCULO",
            "id": id,
            "titulo": titulo,
            "formula": f"Base [{base}] - Deduções [{deducoes}] * Alíquota [{aliquota}] = {valor}",
            "memoria": {
                "base": str(base),
                "deducoes": str(deducoes),
                "aliquota": str(aliquota),
                "valor_final": str(valor),
            },
            "amparo_legal": lei,
            "detalhe": detalhe,
            "timestamp": str(datetime.now()),
        }
        self.trilha.append(passo)
