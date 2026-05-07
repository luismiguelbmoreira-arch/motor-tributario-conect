# -*- coding: utf-8 -*-
"""
test_err057_anti_alucinacao_max06.py — Regressão MAX_07.

ERR-057: MAX_06 do CLAUDE.md citava "Art. 47 §II + Arts. 344, 353, 356-360"
como base do crédito B2B de fornecedor Simples Nacional. Validação Escrivão
em 30/04/2026 (5+ fontes secundárias autoritativas: LegisWeb, ModeloInicial,
Jusbrasil, ConJur, Reformatributaria.com, Nuvant) confirmou:

- Art. 47 §II NÃO trata especificamente de fornecedor Simples — é regra
  geral de "valor do crédito" (= valor destacado no documento).
- Art. 47 § 9º É a base correta — quando IBS/CBS pagos via Simples,
  optantes não se apropriam de crédito; adquirente do regime regular
  se credita em valor equivalente ao recolhido no DAS.
- Arts. 344/353/356-360 são CRONOGRAMA de transição CBS/IBS, NÃO regra
  de creditamento. Citação cumulativa errada.

Mesma classe de erro de:
- ERR-017.b (citação inventada SC COSIT 174/2019)
- ERR-056 (Art. 172 II/III pra cigarro/bebida — eram Art. 409)

Este teste BLOQUEIA o redo. Quem editar MAX_06 voltando à citação errada
quebra o teste.

Rail R5: o motor consome a citação no `lei` da trilha de auditoria
(motor_tributario.py:_fracao_iva_no_das + credito_b2b_simples). Se a
citação volta a ser §II, fiscalização real vai pedir base e ela não
sustenta — risco material direto.
"""

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

CLAUDE_MD = Path(__file__).resolve().parents[2] / "CLAUDE.md"
MOTOR_PY = Path(__file__).resolve().parents[1] / "core" / "motor_tributario.py"
RELATORIO_PY = Path(__file__).resolve().parents[1] / "services" / "relatorio_pdf.py"


def _texto(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ── CLAUDE.md MAX_06 ──────────────────────────────────────────────────────────

def test_claude_md_existe():
    assert CLAUDE_MD.exists(), f"CLAUDE.md não encontrado em {CLAUDE_MD}"


def test_max06_cita_paragrafo_9_correto():
    """MAX_06 deve citar 'Art. 47 § 9º' (citação correta validada por Escrivão)."""
    texto = _texto(CLAUDE_MD)
    # Localiza a linha do MAX_06 (única no documento)
    linhas_max06 = [linha for linha in texto.splitlines() if "**MAX_06**" in linha]
    assert len(linhas_max06) == 1, f"Esperava 1 linha MAX_06, encontrei {len(linhas_max06)}"
    linha = linhas_max06[0]
    assert "Art. 47 § 9º" in linha, (
        f"MAX_06 deveria citar 'Art. 47 § 9º' (validado por Escrivão 30/04/2026). "
        f"Linha: {linha[:200]}"
    )


def test_max06_nao_cita_paragrafo_ii_errado():
    """REGRESSÃO ERR-057: 'Art. 47 §II' como base de creditamento Simples não pode voltar."""
    texto = _texto(CLAUDE_MD)
    linhas_max06 = [linha for linha in texto.splitlines() if "**MAX_06**" in linha]
    linha = linhas_max06[0]
    # A regra é: se MAX_06 ainda mencionar §II, deve ser explicitamente como ERRO histórico.
    if "Art. 47 §II" in linha:
        assert "ERR-057" in linha or "ERRADA" in linha, (
            "Se MAX_06 ainda cita 'Art. 47 §II', deve ser apenas como nota histórica "
            "marcando ERR-057. Caso contrário é regressão."
        )


def test_max06_nao_cita_arts_344_353_356_como_creditamento():
    """REGRESSÃO ERR-057: Arts. 344/353/356-360 são cronograma, NÃO creditamento."""
    texto = _texto(CLAUDE_MD)
    linhas_max06 = [linha for linha in texto.splitlines() if "**MAX_06**" in linha]
    linha = linhas_max06[0]
    if re.search(r"Arts?\.\s*344.*353.*356", linha):
        assert "ERR-057" in linha or "ERRADA" in linha, (
            "Se MAX_06 ainda cita Arts. 344/353/356-360, deve ser apenas como nota "
            "histórica marcando ERR-057. Esses artigos são CRONOGRAMA, não creditamento."
        )


# ── core/motor_tributario.py — uso real do crédito B2B ───────────────────────

def test_motor_credito_b2b_simples_cita_paragrafo_9():
    """A docstring de credito_b2b_simples deve referir Art. 47 § 9º."""
    texto = _texto(MOTOR_PY)
    # Busca a docstring após `def credito_b2b_simples`
    match = re.search(
        r"def credito_b2b_simples[^\"']+\"\"\"(.+?)\"\"\"",
        texto,
        flags=re.DOTALL,
    )
    assert match, "Não localizei a docstring de credito_b2b_simples"
    docstring = match.group(1)
    assert "Art. 47 § 9º" in docstring, (
        f"credito_b2b_simples deveria citar 'Art. 47 § 9º'. Docstring atual: "
        f"{docstring[:300]}"
    )


def test_motor_passo_credito_b2b_cita_paragrafo_9():
    """O passo CREDITO_B2B_ART_47 da trilha deve citar § 9º no campo titulo."""
    texto = _texto(MOTOR_PY)
    # Localiza o titulo do passo
    match = re.search(
        r'titulo=f"Crédito B2B cliente \(\{ano\}\) — LC 214/2025 Art\. 47[^"]+"',
        texto,
    )
    assert match, "Não localizei o titulo do passo CREDITO_B2B_ART_47"
    titulo = match.group(0)
    assert "§ 9º" in titulo, f"Titulo do passo deveria citar § 9º, veio: {titulo}"
    assert "§II" not in titulo, f"Titulo NÃO pode citar §II (ERR-057). Veio: {titulo}"


# ── services/relatorio_pdf.py — citação visível ao cliente ───────────────────

def test_relatorio_pdf_cita_paragrafo_9_no_credito_b2b():
    """Linha que tem 'Crédito aproveitado por clientes B2B' deve citar § 9º."""
    texto = _texto(RELATORIO_PY)
    linhas_b2b = [
        linha for linha in texto.splitlines()
        if "Crédito aproveitado por clientes B2B" in linha
    ]
    assert linhas_b2b, "Não localizei linha 'Crédito aproveitado por clientes B2B'"
    for linha in linhas_b2b:
        assert "§ 9º" in linha, (
            f"Linha do crédito B2B no PDF deveria citar § 9º. Linha: {linha[:300]}"
        )
        assert "§II" not in linha, (
            f"REGRESSÃO ERR-057: linha cita §II (errado). Linha: {linha[:300]}"
        )


# ── Sanity check: § 9º existe nos 3 arquivos críticos ────────────────────────

@pytest.mark.parametrize("path,nome", [
    (CLAUDE_MD, "CLAUDE.md"),
    (MOTOR_PY, "core/motor_tributario.py"),
    (RELATORIO_PY, "services/relatorio_pdf.py"),
])
def test_paragrafo_9_aparece_no_arquivo(path: Path, nome: str):
    """Citação corrigida deve estar presente em todos os arquivos do escopo ERR-057."""
    texto = _texto(path)
    assert "Art. 47 § 9º" in texto, (
        f"{nome} deveria conter 'Art. 47 § 9º' (citação validada Escrivão 30/04/2026)."
    )
