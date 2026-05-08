# -*- coding: utf-8 -*-
"""
gerar_mapa_cnae.py — WS12: regenera data/cnae_completo.json no schema novo

REESCRITO em 2026-05-08 pra fechar ERR-005 oficialmente.

ANTES (legado):
  - get_anexo_base() interno duplicava regras por divisão
  - aplicar_excecoes_conhecidas() tinha 7 overrides hardcoded
  - Schema do JSON: {cnae: anexo_str}
  - DIVERGIA de core/cnae_excecoes.py em divisões com Fator R
    (ex: divisão 56 → "I" no gerador vs C_FATOR_R no schema novo)

AGORA:
  - Fonte única é core.regras_cnae.obter_regra() (consume CNAE_EXCECOES +
    DIVISAO_PARA_CATEGORIA do schema WS12 — Luiz Moreira aprovado em
    25/04/2026, commit f60aa61)
  - Schema enriquecido: {cnae: {categoria, anexo_padrao, depende_fator_r,
    base_legal, observacao}}
  - Metadados versionados: data_geracao, fonte_ibge_url, hash_sha256_ibge

USO:
  python PY/scripts/gerar_mapa_cnae.py

  Saída: PY/../data/cnae_completo.json (sobrescreve)

INPUT: API IBGE CONCLA https://servicodados.ibge.gov.br/api/v2/cnae/subclasses
OUTPUT: data/cnae_completo.json
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Permite rodar como script com `python PY/scripts/gerar_mapa_cnae.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.regras_cnae import obter_regra  # noqa: E402

API_IBGE_URL = "https://servicodados.ibge.gov.br/api/v2/cnae/subclasses"


def baixar_cnaes_ibge(url: str = API_IBGE_URL, timeout: int = 60) -> tuple[list[dict], str]:
    """
    Baixa a lista completa de subclasses CNAE 2.3 do IBGE CONCLA.

    Returns:
        (subclasses, sha256_hex) — lista de dicts brutos do IBGE +
        SHA-256 do payload bruto pra rastreabilidade.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "motor-tributario-conect/WS12"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — IBGE oficial
        raw = resp.read()
    sha = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw.decode("utf-8"))
    return data, sha


def montar_entrada(cnae: str) -> dict:
    """
    Para um CNAE 7 dígitos, consulta a fonte única (core.regras_cnae) e
    devolve a entrada enriquecida.

    Quando a regra é desconhecida (CNAE não mapeado em CNAE_EXCECOES nem em
    DIVISAO_PARA_CATEGORIA), entry indica `categoria=None` — caller decide
    fallback (Rail R2: motor aplica Anexo III conservador no resolve_anexo).
    """
    regra = obter_regra(cnae)
    if regra is None:
        return {
            "categoria": None,
            "anexo_padrao": None,
            "depende_fator_r": False,
            "base_legal": "FALLBACK_NAO_MAPEADO",
            "observacao": (
                "CNAE não consta em CNAE_EXCECOES nem em DIVISAO_PARA_CATEGORIA. "
                "Motor aplica Anexo III conservador (Rail R2 — sem extrapolação)."
            ),
        }
    return {
        "categoria": regra.categoria,
        "anexo_padrao": regra.anexo_padrao,
        "depende_fator_r": regra.depende_fator_r,
        "base_legal": regra.base_legal,
        "observacao": regra.observacao or "",
    }


def main() -> None:
    print("Baixando tabela de CNAEs do IBGE (API CONCLA)...")
    subclasses, sha_ibge = baixar_cnaes_ibge()
    print(f"  {len(subclasses)} subclasses recebidas (SHA-256 IBGE: {sha_ibge[:12]}...).")

    entradas: dict[str, dict] = {}
    for item in subclasses:
        cnae = item["id"].replace("-", "").replace("/", "")
        if len(cnae) != 7 or not cnae.isdigit():
            continue
        entradas[cnae] = montar_entrada(cnae)

    # Distribuição por categoria — para o operador conferir o resultado
    contagem: dict[str, int] = {}
    for entrada in entradas.values():
        cat = entrada["categoria"] or "FALLBACK_NAO_MAPEADO"
        contagem[cat] = contagem.get(cat, 0) + 1
    print("Distribuição por categoria:")
    for cat in sorted(contagem):
        print(f"  {cat:32s} {contagem[cat]:>5d}")

    payload = {
        "_metadata": {
            "schema_versao": "2.0",
            "data_geracao": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "fonte_ibge_url": API_IBGE_URL,
            "fonte_ibge_sha256": sha_ibge,
            "fonte_normativa": (
                "LC 123/2006 + Resolução CGSN 140/2018 Anexo VI; categorias "
                "semânticas A_FIXO/B_ANEXO_III/C_FATOR_R/D_ESPECIAL/E_VEDADO "
                "definidas em core/cnae_excecoes.py (Luiz Moreira 25/04/2026)"
            ),
            "consumidor_canonico": "core.regras_cnae.obter_regra",
        },
        "cnaes": entradas,
    }

    out_path = Path(__file__).resolve().parent.parent.parent / "data" / "cnae_completo.json"
    out_path.parent.mkdir(exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=False)
    tmp.replace(out_path)

    print(f"Sucesso! {len(entradas)} CNAEs gravados em {out_path}.")


if __name__ == "__main__":
    main()
