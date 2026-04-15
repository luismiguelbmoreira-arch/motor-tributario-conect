"""
sieg_ingestor.py — Shim de compatibilidade.
Redireciona para database/sieg_service.py pós-faxina arquitetural.
"""
from .sieg_service import (
    SincronizacaoResult,
    SiegService as SiegIngestor  # Alias para compatibilidade
)

NOME_ORIGINAL_PREFIX = "sieg::"
