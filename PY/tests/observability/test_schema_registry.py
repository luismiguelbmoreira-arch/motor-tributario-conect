"""
test_schema_registry.py — Gate Akita: valida que checksums dos parsers estão atualizados.

Falha de propósito se um parser for modificado sem atualizar
PARSER_REGISTRY em observability/schema_registry.py.

Rodar: python -m pytest tests/observability/test_schema_registry.py -v
"""
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from observability.schema_registry import PARSER_REGISTRY  # noqa: E402

PARSERS_DIR = Path(__file__).resolve().parent.parent.parent / "parsers"


def _sha256(path: Path) -> str:
    """
    SHA-256 com line endings normalizados (CRLF/CR → LF).

    Motivo: Windows com core.autocrlf=true reescreve LF→CRLF no checkout, o
    que muda o hash dos bytes em disco sem que o conteúdo fonte tenha mudado.
    Hashing pelos bytes brutos torna o gate dependente de plataforma. Hashing
    sobre o conteúdo normalizado mantém o registry estável cross-platform e
    ainda detecta toda mudança real de conteúdo.
    """
    raw = path.read_bytes()
    normalizado = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(normalizado).hexdigest()


def test_todos_parsers_registrados():
    """Todo arquivo .py em parsers/ (exceto __init__.py) deve estar no registro."""
    parser_files = {
        f.name for f in PARSERS_DIR.glob("*.py") if f.name != "__init__.py"
    }
    registered = set(PARSER_REGISTRY.keys())
    nao_registrados = parser_files - registered
    assert not nao_registrados, (
        f"Parsers sem registro em schema_registry.py: {sorted(nao_registrados)}\n"
        "Adicione a entrada com versão e SHA-256 atualizado."
    )


def test_checksums_correspondem_aos_arquivos():
    """Checksum registrado deve corresponder ao conteúdo atual do parser."""
    erros = []
    for nome, meta in PARSER_REGISTRY.items():
        path = PARSERS_DIR / nome
        if not path.exists():
            erros.append(f"{nome}: arquivo não encontrado em parsers/")
            continue
        atual = _sha256(path)
        esperado = meta["sha256"]
        if atual != esperado:
            erros.append(
                f"{nome} (v{meta['version']}): checksum diverge.\n"
                f"  Registrado: {esperado}\n"
                f"  Atual:      {atual}\n"
                "  → Faça bump de version e atualize sha256 em schema_registry.py"
            )
    assert not erros, "\n\n".join(erros)
