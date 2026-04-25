"""
schema_registry.py — Registro de versão e checksum dos parsers de documentos fiscais.

Quando um parser for alterado:
  1. Bump de VERSION no dicionário correspondente
  2. Atualizar CHECKSUM com o SHA-256 do conteúdo NORMALIZADO (CRLF→LF):
     python -c "import hashlib; b=open('parsers/nome.py','rb').read().replace(b'\\r\\n', b'\\n').replace(b'\\r', b'\\n'); print(hashlib.sha256(b).hexdigest())"

O hash é calculado sobre o conteúdo com line endings normalizados (LF) para
manter o gate estável cross-platform — Windows com core.autocrlf=true reescreve
LF→CRLF no checkout sem mudar o conteúdo fonte, o que invalidaria o hash bruto.

O CI (schema-registry.yml) bloqueia merge se qualquer parser mudar sem
atualização do checksum aqui. Isso garante rastreabilidade de mudanças de
contrato de schema (ERR-052 / Gate Akita).
"""

PARSER_REGISTRY: dict[str, dict[str, str]] = {
    "csv_folha.py": {
        "version": "1.0.0",
        "sha256": "d83d5c2eda9ec644ffaccb76dac6af87b59772b121053633d87a239a3b02f903",
        "description": "Parser CSV folha de pagamento",
    },
    "sped_ecd.py": {
        "version": "1.0.0",
        "sha256": "51d73d8b0dd1572a9d9ff64cced67d56d3a1acfc7885d1398d279cbe72a2bed2",
        "description": "Parser SPED ECD (Escrituração Contábil Digital)",
    },
    "sped_efd_contrib.py": {
        "version": "1.0.0",
        "sha256": "f421a8331c6ce553f5885d008bb1c144169d1cee4768ae274cccd59105cea468",
        "description": "Parser SPED EFD-Contribuições (PIS/COFINS)",
    },
    "xml_nfce.py": {
        "version": "1.0.0",
        "sha256": "4b88b4fc25cf09c4c17f325503d9baf3a459db95a94018ae2626ffc8b852f433",
        "description": "Parser XML NFC-e 4.0",
    },
    "xml_nfe.py": {
        "version": "1.0.0",
        "sha256": "32840e2b860e1b046725eaea91f4fe109cb7b7df47af0ac5ccd42f4bd63af610",
        "description": "Parser XML NF-e 4.0",
    },
}
