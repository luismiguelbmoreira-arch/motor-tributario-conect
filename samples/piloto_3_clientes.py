#!/usr/bin/env python3
"""
piloto_3_clientes.py — Teste headless do upload PDF e-CAC via API.

Autentica como admin, faz upload dos PDFs de cada cliente e valida o
diagnostico retornado.

Uso: python samples/piloto_3_clientes.py
"""
import json
import sys
from pathlib import Path

import requests

BASE = "http://localhost:8000"
USER = "admin"
PASS_PADRAO = "131189Luis"
ROOT = Path(__file__).resolve().parent / "doc_calculo"

CLIENTES = {
    "CONFI_AR": [
        "CNPJ_CONFI_AR.pdf",
        "DAS_01_26.pdf",
        "Empresa 428 - CONFI- AR.pdf",
        "PGDASD-DECLARACAO-08172834202601001 (1).pdf",
        "PGDASD-EXTRATO-07202603752184288.pdf",
        "RECIBO.pdf",
    ],
    "CANAVEZI": [
        "CANAVEZI.pdf",
        "CNPJ_CANAVEZI.pdf",
        "DAS_01_2026.pdf",
        "Empresa 46 - CANAVEZZI.pdf",
        "ESTRATO SIMPLES NACIONAL_CANAVEZI.pdf",
        "RECIBO_01_2026.pdf",
    ],
    "ITANGUA": [
        "CNPJ_ITANGUA.pdf",
        "DECLARACAO_ITANGUA_01_2026.pdf",
        "Empresa 88 - ITANGUA.pdf",
        "PGDASD-EXTRATO-07202604979852429.pdf",
        "RECIBO_ITANGUA.pdf",
    ],
}


def login() -> str:
    """Faz login admin e retorna o JWT."""
    r = requests.post(
        f"{BASE}/auth/login",
        json={"username": USER, "password": PASS_PADRAO},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("must_change_password"):
        print("[WARN] Senha precisa ser trocada. Continuando com token atual...")
    return data["access_token"]


def upload_pdfs(token: str, cliente: str, arquivos: list[str]) -> dict:
    """Envia os PDFs do cliente para /analise/pdf e retorna o diagnostico."""
    pasta = ROOT / cliente
    files = []
    for nome in arquivos:
        caminho = pasta / nome
        if not caminho.exists():
            print(f"[{cliente}] FALTA: {nome}")
            continue
        files.append(("files", (nome, open(caminho, "rb"), "application/pdf")))

    print(f"[{cliente}] Enviando {len(files)} PDFs...")
    r = requests.post(
        f"{BASE}/analise/pdf",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
        timeout=180,  # extracao via Claude Vision pode demorar
    )

    # Fechar handles
    for _, (_, fh, _) in files:
        fh.close()

    if r.status_code != 200:
        print(f"[{cliente}] ERRO HTTP {r.status_code}: {r.text[:500]}")
        return {"erro": r.text, "status": r.status_code}

    return r.json()


def resumir(cliente: str, diag: dict) -> None:
    """Imprime resumo do diagnostico."""
    if "erro" in diag:
        print(f"\n=== {cliente}: FALHOU ===")
        print(diag.get("erro", "")[:500])
        return

    empresa = diag.get("empresa", {})
    aliquotas = diag.get("aliquotas", {})
    alertas = diag.get("alertas", [])
    difal = diag.get("difal", {})
    trilha = diag.get("trilha_auditoria", [])

    print(f"\n=== {cliente}: SUCESSO ===")
    print(f"  CNPJ            : {empresa.get('cnpj', 'N/A')}")
    print(f"  Razao social    : {empresa.get('razao_social', 'N/A')}")
    print(f"  Regime          : {empresa.get('regime', 'N/A')}")
    print(f"  CNAE            : {empresa.get('cnae', 'N/A')}")
    print(f"  UF              : {empresa.get('uf', 'N/A')}")
    print(f"  RBT12           : R$ {empresa.get('rbt12', 'N/A')}")
    print(f"  Anexo Simples   : {empresa.get('anexo_simples', 'N/A')}")
    print(f"  Aliquota efetiva: {aliquotas.get('efetiva_percentual', 'N/A')}")
    print(f"  Total mensal    : R$ {aliquotas.get('total_mensal', 'N/A')}")
    print(f"  Alertas         : {len(alertas)}")
    print(f"  Trilha (passos) : {len(trilha)}")
    print(f"  DIFAL aplicavel : {difal.get('aplicavel', 'N/A')}")
    if difal.get("aplicavel"):
        print(f"  DIFAL valor     : R$ {difal.get('difal_valor', 'N/A')}")

    if alertas:
        print(f"  --- Alertas ---")
        for a in alertas[:3]:
            print(f"    [{a.get('nivel', '?')}] {a.get('codigo', '?')}: {a.get('mensagem', '')[:80]}")


def main():
    print("=" * 60)
    print("PILOTO 3 CLIENTES — Motor Tributario Conect")
    print("=" * 60)

    # Health check
    try:
        r = requests.get(f"{BASE}/health", timeout=5)
        print(f"Health: {r.json()}")
    except Exception as e:
        print(f"[FATAL] API nao esta no ar em {BASE}: {e}")
        sys.exit(1)

    # Login
    try:
        token = login()
        print(f"Login OK (token {len(token)} chars)")
    except Exception as e:
        print(f"[FATAL] Login falhou: {e}")
        sys.exit(1)

    # Pilotos sequenciais
    resultados = {}
    for cliente, arquivos in CLIENTES.items():
        try:
            diag = upload_pdfs(token, cliente, arquivos)
            resultados[cliente] = diag
            resumir(cliente, diag)

            # Salvar JSON completo
            out = ROOT.parent / f"piloto_{cliente.lower()}.json"
            with open(out, "w", encoding="utf-8") as f:
                json.dump(diag, f, indent=2, ensure_ascii=False, default=str)
            print(f"  Diagnostico salvo: {out}")
        except Exception as e:
            print(f"\n[{cliente}] EXCECAO: {type(e).__name__}: {e}")
            resultados[cliente] = {"erro": str(e)}

    # Relatorio final
    print("\n" + "=" * 60)
    print("RELATORIO FINAL")
    print("=" * 60)
    for cliente, diag in resultados.items():
        status = "FALHOU" if "erro" in diag else "OK"
        print(f"  {cliente:12} : {status}")


if __name__ == "__main__":
    main()
