"""
integrations — Adaptadores externos (Fase 2).

Módulos:
    onvio_adapter  — Thomson Reuters Onvio (SPED Domínio Contábil via OAuth2)
    sieg_adapter   — Sieg (exports XML NFe via API ou ZIP)

Contratos:
    - OAuth2 client credentials
    - Pagination + rate limit handling
    - Exponential backoff retries
    - Idempotent ingestion via checksum SHA-256
"""
