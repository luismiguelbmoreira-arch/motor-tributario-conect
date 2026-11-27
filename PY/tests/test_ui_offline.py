# -*- coding: utf-8 -*-
"""
tests/test_ui_offline.py — UI precisa abrir sem internet (.exe desktop).

Garante que nenhuma página/CSS/JS da UI carrega recurso remoto (CDN, Google
Fonts), que todo arquivo local referenciado existe e que config.js entra antes
de components.js (mcFetch usa MC_CONFIG.API_BASE).
"""

import re
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parent.parent.parent / "UI"
PAGINAS = sorted(UI.glob("*.html"))
FONTES = PAGINAS + sorted(UI.glob("*.css")) + sorted(UI.glob("*.js"))

# src=/href= de <script>/<link>
_TAG = re.compile(r"""<(?:script|link)\b[^>]*?\b(?:src|href)=["']([^"']+)["']""", re.IGNORECASE)
# url()/@import de CSS (minúsculo e fora de identificador: não pega createObjectURL(blob) nem mcApiUrl(x))
_CSS_URL = re.compile(r"""(?<![\w.])url\(\s*["']([^"']+)["']|(?<![\w.])url\(\s*([^"')\s]+)\)""")


def _refs(path: Path) -> list[str]:
    texto = path.read_text(encoding="utf-8")
    refs = [m.group(1) for m in _TAG.finditer(texto)]
    if path.suffix != ".js":
        refs += [m.group(1) or m.group(2) for m in _CSS_URL.finditer(texto)]
    return refs


def test_js_sem_cdn():
    for arquivo in sorted(UI.glob("*.js")):
        texto = arquivo.read_text(encoding="utf-8")
        assert not re.search(r"https?://(unpkg|cdn\.|fonts\.g)", texto), arquivo.name


def test_ha_paginas():
    assert len(PAGINAS) >= 9


@pytest.mark.parametrize("arquivo", FONTES, ids=lambda p: p.name)
def test_sem_recurso_remoto(arquivo):
    remotos = [r for r in _refs(arquivo) if re.match(r"(https?:)?//", r)]
    assert remotos == [], f"{arquivo.name} carrega da internet: {remotos}"


@pytest.mark.parametrize("arquivo", FONTES, ids=lambda p: p.name)
def test_referencias_locais_existem(arquivo):
    faltando = []
    for ref in _refs(arquivo):
        if ref.startswith(("data:", "#", "/", "http:", "https:")) or "${" in ref:
            continue
        alvo = (arquivo.parent / ref.split("?")[0]).resolve()
        if not alvo.is_file():
            faltando.append(ref)
    assert faltando == [], f"{arquivo.name} referencia arquivo inexistente: {faltando}"


def test_inter_css_aponta_para_woff2_existentes():
    css = UI / "vendor" / "inter" / "inter.css"
    arquivos = re.findall(r"url\('([^']+\.woff2)'\)", css.read_text(encoding="utf-8"))
    assert len(arquivos) == 10  # 5 pesos × (latin + latin-ext)
    for rel in arquivos:
        assert (css.parent / rel).is_file(), rel


@pytest.mark.parametrize("pagina", [p for p in PAGINAS if "components.js" in p.read_text(encoding="utf-8")], ids=lambda p: p.name)
def test_config_js_antes_de_components_js(pagina):
    texto = pagina.read_text(encoding="utf-8")
    assert 0 <= texto.find('src="config.js"') < texto.find('src="components.js"')


def test_api_base_centralizada():
    """window.location.origin só aparece em config.js."""
    for arquivo in FONTES:
        if arquivo.name == "config.js":
            continue
        assert "location.origin" not in arquivo.read_text(encoding="utf-8"), arquivo.name
