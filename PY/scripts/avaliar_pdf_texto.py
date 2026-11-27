# -*- coding: utf-8 -*-
"""
scripts/avaliar_pdf_texto.py — Avalia se PDFs têm texto legível sem internet.

Pergunta que responde: dá para ler localmente (pdfplumber, sem Claude Vision)
os campos que o extrator usa? Só mostra PRESENÇA de rótulos e números de
página/caracteres. NUNCA imprime valores, CNPJ ou nome: os PDFs são de cliente.

Uso (a partir de PY/; pdfplumber NÃO está em requirements — instalar à parte):
    uv pip install pdfplumber        # num venv de avaliação
    python scripts/avaliar_pdf_texto.py ../samples/uploads_clientes
    python scripts/avaliar_pdf_texto.py ../samples/uploads_clientes --json

Resultado da avaliação com samples/: docs/deploy/avaliacao_pdf_offline.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

# Rótulos do extrato/declaração PGDAS-D e do Cartão CNPJ, por campo de
# `DadosExtraidosPDF` (services/extrator_pdfs.py). Só presença: não extrai valor.
ROTULOS: dict[str, str] = {
    "cnpj": r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}",
    "razao_social": r"(?i)nome empresarial|raz[aã]o social",
    "cnae_principal": r"\d{2}\.\d{2}-\d-\d{2}",
    "uf_origem": r"\bUF:\s*[A-Z]{2}\b",
    "faturamento_12m": r"\(RBT12\)",
    "rpa_referencia": r"\(RPA\)",
    "competencia": r"(?i)per[ií]odo de apura[cç][aã]o \(PA\)",
    "das_ecac_referencia": r"(?i)informa[cç][oõ]es sobre DAS gerado",
    "das_breakdown": r"IRPJ\s+CSLL\s+COFINS",
    "folha_salarios_12m": r"(?i)folha de sal[aá]rios",
}

MIN_CHARS_PAGINA = 20  # abaixo disso a página é tratada como imagem (escaneada)


def rotulos_presentes(texto: str) -> dict[str, bool]:
    """Campo → rótulo encontrado no texto. Função pura (testável sem pdfplumber)."""
    return {campo: bool(re.search(padrao, texto)) for campo, padrao in ROTULOS.items()}


def avaliar_textos(textos_por_pagina: list[str]) -> dict:
    texto = "\n".join(textos_por_pagina)
    return {
        "paginas": len(textos_por_pagina),
        "paginas_sem_texto": sum(1 for t in textos_por_pagina if len(t.strip()) < MIN_CHARS_PAGINA),
        "caracteres": len(texto),
        "rotulos": rotulos_presentes(texto),
    }


def avaliar_pdf(caminho: Path) -> dict:
    import pdfplumber

    inicio = time.perf_counter()
    with pdfplumber.open(caminho) as doc:
        textos = [pagina.extract_text() or "" for pagina in doc.pages]
        tabelas = sum(len(pagina.extract_tables()) for pagina in doc.pages)
    resultado = avaliar_textos(textos)
    resultado.update(arquivo=caminho.name, tabelas=tabelas, segundos=round(time.perf_counter() - inicio, 2))
    return resultado


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("pasta", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        import pdfplumber  # noqa: F401
    except ImportError:
        print("pdfplumber não instalado (fora do requirements de propósito). "
              "Instale num venv de avaliação: uv pip install pdfplumber", file=sys.stderr)
        return 2

    pdfs = sorted(args.pasta.rglob("*.pdf"))
    if not pdfs:
        print(f"Nenhum PDF em {args.pasta}", file=sys.stderr)
        return 1
    resultados = [avaliar_pdf(p) for p in pdfs]

    if args.json:
        print(json.dumps(resultados, ensure_ascii=False, indent=1))
        return 0
    for r in resultados:
        achados = [c for c, ok in r["rotulos"].items() if ok]
        print(f"{r['arquivo']}: {r['paginas']} pág, {r['paginas_sem_texto']} sem texto, "
              f"{r['caracteres']} chars, {r['tabelas']} tabelas, {r['segundos']} s")
        print(f"  rótulos: {', '.join(achados) or 'nenhum'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
