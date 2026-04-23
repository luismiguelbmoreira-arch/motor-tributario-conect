# -*- coding: utf-8 -*-
"""
analise_buffer.py — Buffer in-memory de envelopes de análise (Fase 4 Segurança/LGPD)

CONTEXTO:
  O frontend de /analise/manual e /analise/pdf redireciona pra resultado.html
  por meio de window.location.href, o que mata qualquer variável em window.
  Antes da Fase 4, o envelope (diagnostico + PII) era persistido em
  sessionStorage — vazamento de PII (cnpj, razao_social) no armazenamento do
  browser, disponível a qualquer script da mesma origem (LGPD Art. 6º V —
  minimização).

  Este módulo provê um buffer em processo, com TTL curto, chaveado por UUID
  opaco. O frontend guarda só o analise_id (não-PII) em sessionStorage e, no
  resultado.html, faz GET /analise/sessao/{id} com JWT para hidratar a PII em
  memória (window.__MC_SESSION__).

PRINCÍPIOS:
  - In-memory: não toca disco. Morre no restart da API (OK para TTL curto).
  - TTL default 600 s (10 min): suficiente pra navegação + gerar PDF/dossiê.
  - Ownership por user_id (ERR-018 IDOR): só o dono do JWT recupera a sessão.
  - Purge oportunístico a cada operação — sem thread/loop em background.
  - Thread-safe via lock único (GIL + lock resolve para dict dentro de FastAPI).

LGPD:
  - LGPD Art. 6º V (minimização): PII vive apenas na memória do processo.
  - LGPD Art. 37 (registro): operações de armazenar/recuperar podem ser logadas
    pelo chamador (sem vazar cnpj nos logs — só analise_id + user_id).
  - LGPD Art. 46 (segurança): ownership obrigatório + expiração curta.

NÃO É:
  - Cache distribuído (process-local — se escalar horizontal, virar Redis).
  - Storage persistente (para prova jurídica, AuditoriaDocumentoDB é o caminho).
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("motor_conect.analise_buffer")

# TTL padrão. Override por chamada em armazenar(ttl_segundos=...).
TTL_DEFAULT_S: int = 600


@dataclass
class _EntradaBuffer:
    """Envelope persistido em memória, atrelado ao user_id dono."""
    envelope: dict[str, Any]
    user_id: int
    criado_em: float
    expira_em: float


class AnaliseBuffer:
    """
    Buffer in-memory de envelopes de análise, chaveado por UUID opaco,
    com ownership obrigatório e expiração.

    Métodos:
      armazenar(envelope, user_id, ttl) → analise_id (str)
      recuperar(analise_id, user_id)    → envelope (dict) ou None
      remover(analise_id, user_id)      → bool
      purge_expirados()                 → int (quantos removidos)
      tamanho()                         → int (para testes/observabilidade)
    """

    def __init__(self) -> None:
        self._data: dict[str, _EntradaBuffer] = {}
        self._lock = threading.Lock()

    # ───── Operações públicas ─────────────────────────────────────────────────

    def armazenar(
        self,
        envelope: dict[str, Any],
        user_id: int,
        ttl_segundos: int = TTL_DEFAULT_S,
    ) -> str:
        """
        Persiste envelope em memória e retorna analise_id (UUID opaco).

        Args:
            envelope: dict contendo pelo menos {"diagnostico": ..., "pii": ...}.
            user_id: ID do usuário dono (claim "sub" do JWT).
            ttl_segundos: tempo de vida do buffer.

        Returns:
            analise_id: string hex de 32 chars (secrets.token_hex) — opaca,
                        não reversível, sem PII.

        Raises:
            ValueError: envelope vazio ou user_id inválido.
        """
        if not isinstance(envelope, dict) or not envelope:
            raise ValueError("envelope deve ser dict não-vazio.")
        if not isinstance(user_id, int) or user_id <= 0:
            raise ValueError("user_id deve ser inteiro positivo.")
        if ttl_segundos <= 0:
            raise ValueError("ttl_segundos deve ser > 0.")

        analise_id = secrets.token_hex(16)  # 128 bits — espaço impossível de adivinhar
        agora = time.monotonic()
        entrada = _EntradaBuffer(
            envelope=envelope,
            user_id=user_id,
            criado_em=agora,
            expira_em=agora + ttl_segundos,
        )
        with self._lock:
            # Purge oportunístico — mantém a memória enxuta sem thread dedicada
            self._purge_expirados_locked(agora)
            self._data[analise_id] = entrada

        logger.info(
            "Analise armazenada | analise_id=%s... | user_id=%s | ttl=%ss",
            analise_id[:8], user_id, ttl_segundos,
        )
        return analise_id

    def recuperar(self, analise_id: str, user_id: int) -> Optional[dict[str, Any]]:
        """
        Retorna envelope se existir, não expirou e pertence ao user_id.

        Falhas silenciosas (retorna None): id inexistente, expirado ou
        user_id diferente do dono. Em qualquer caso, o chamador deve
        devolver 404 ao cliente para não vazar se o id existe ou não
        (ownership IDOR-safe).

        Args:
            analise_id: UUID opaco retornado por armazenar().
            user_id: ID do usuário autenticado (JWT claim "sub").

        Returns:
            envelope (dict) se válido e dono, None caso contrário.
        """
        if not analise_id or not isinstance(analise_id, str):
            return None
        if not isinstance(user_id, int) or user_id <= 0:
            return None

        agora = time.monotonic()
        with self._lock:
            entrada = self._data.get(analise_id)
            if entrada is None:
                return None
            if entrada.expira_em <= agora:
                # Expirou — remove oportunisticamente
                del self._data[analise_id]
                logger.info(
                    "Analise expirada removida | analise_id=%s...",
                    analise_id[:8],
                )
                return None
            if entrada.user_id != user_id:
                # Ownership falhou — não vaza nem o fato da existência
                logger.warning(
                    "Tentativa de acesso cruzado | analise_id=%s... | user_id_tentando=%s",
                    analise_id[:8], user_id,
                )
                return None
            return entrada.envelope

    def remover(self, analise_id: str, user_id: int) -> bool:
        """
        Remove explicitamente (logout, nova análise, direito LGPD de eliminação).

        Returns:
            True se removeu, False se id ausente ou ownership inválido.
        """
        if not analise_id or not isinstance(analise_id, str):
            return False
        with self._lock:
            entrada = self._data.get(analise_id)
            if entrada is None:
                return False
            if entrada.user_id != user_id:
                return False
            del self._data[analise_id]
            return True

    def purge_expirados(self) -> int:
        """
        Limpeza explícita de todas as entradas expiradas.
        Útil em testes e em endpoint admin opcional.

        Returns:
            Número de entradas removidas.
        """
        agora = time.monotonic()
        with self._lock:
            return self._purge_expirados_locked(agora)

    def tamanho(self) -> int:
        """Número de entradas atualmente no buffer (para testes/métricas)."""
        with self._lock:
            return len(self._data)

    # ───── Internos ───────────────────────────────────────────────────────────

    def _purge_expirados_locked(self, agora: float) -> int:
        """Remove expirados. DEVE ser chamado com self._lock adquirido."""
        expirados = [aid for aid, e in self._data.items() if e.expira_em <= agora]
        for aid in expirados:
            del self._data[aid]
        return len(expirados)


# ───── Singleton do processo ────────────────────────────────────────────────
# A API toda compartilha uma instância — escopo = vida do worker uvicorn.
_BUFFER_SINGLETON = AnaliseBuffer()


def get_buffer() -> AnaliseBuffer:
    """Retorna o singleton global. Substituível em testes via monkeypatch."""
    return _BUFFER_SINGLETON
