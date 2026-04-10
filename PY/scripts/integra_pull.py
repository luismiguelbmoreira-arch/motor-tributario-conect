"""
integra_pull.py — CLI on-demand para puxar PGDAS-D + DAS do Integra Contador.

Uso:
    python PY/scripts/integra_pull.py \\
        --cnpj 12345678000190 \\
        --ano-base 2025 \\
        --tipos pgdasd,das \\
        --user-id 1

    # Atalho: um único período
    python PY/scripts/integra_pull.py --cnpj ... --periodo 2025-12 --tipos pgdasd

    # Dry-run: só lista o que seria chamado
    python PY/scripts/integra_pull.py --cnpj ... --ano-base 2025 --dry-run

Requer variáveis de ambiente do cofre Integra (INTEGRA_CERT_PATH,
INTEGRA_CERT_PASSWORD, INTEGRA_CONTRATANTE_CNPJ,
INTEGRA_AUTOR_PEDIDO_DADOS_CNPJ) ou arquivo INI protegido.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Permite rodar como script solto: python PY/scripts/integra_pull.py
_HERE = os.path.dirname(os.path.abspath(__file__))
_PY_ROOT = os.path.dirname(_HERE)
if _PY_ROOT not in sys.path:
    sys.path.insert(0, _PY_ROOT)

from integrations.integra_adapter import (  # noqa: E402
    IntegraAdapter,
    IntegraAuthError,
    IntegraCertError,
    IntegraError,
)
from integrations.integra_credentials import (  # noqa: E402
    IntegraCredentialError,
    get_integra_credenciais,
)
from integrations.integra_ingestor import IntegraIngestor  # noqa: E402


TIPOS_VALIDOS = ("pgdasd", "das")


def _periodos_do_ano(ano: int) -> list[str]:
    return [f"{ano}-{m:02d}" for m in range(1, 13)]


def _parse_tipos(raw: str) -> list[str]:
    tipos = [t.strip().lower() for t in raw.split(",") if t.strip()]
    invalidos = [t for t in tipos if t not in TIPOS_VALIDOS]
    if invalidos:
        raise SystemExit(
            f"tipos inválidos: {invalidos}. Use subconjunto de {TIPOS_VALIDOS}"
        )
    return tipos


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Puxa PGDAS-D + DAS do Integra Contador (Serpro/RFB).",
    )
    parser.add_argument("--cnpj", required=True, help="CNPJ do cliente (14 dígitos, aceita pontuação)")

    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--ano-base", type=int, help="Ano completo (ex: 2025 → 12 períodos)")
    g.add_argument("--periodo", help="Período único YYYY-MM (ex: 2025-12)")

    parser.add_argument(
        "--tipos",
        default="pgdasd,das",
        help="Lista separada por vírgula (default: pgdasd,das)",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="id do operador no banco (uploaded_by_user_id)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Só imprime o plano sem chamar Serpro",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Log DEBUG",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    tipos = _parse_tipos(args.tipos)
    if args.ano_base is not None:
        if not (2020 <= args.ano_base <= 2033):
            raise SystemExit("--ano-base fora do range 2020-2033")
        periodos = _periodos_do_ano(args.ano_base)
    else:
        periodos = [args.periodo]

    print(f"CNPJ:        {args.cnpj}")
    print(f"Períodos:    {periodos[0]} .. {periodos[-1]} ({len(periodos)})")
    print(f"Tipos:       {','.join(tipos)}")
    print(f"User ID:     {args.user_id}")
    total_chamadas = len(periodos) * len(tipos)
    print(f"Chamadas:    {total_chamadas}")

    if args.dry_run:
        print("\n[DRY-RUN] Nenhuma chamada Serpro executada.")
        return 0

    try:
        credenciais = get_integra_credenciais()
    except IntegraCredentialError as exc:
        print(f"\n[ERRO] Credenciais Integra Contador: {exc}", file=sys.stderr)
        return 2

    adapter = IntegraAdapter(credenciais)
    try:
        ingestor = IntegraIngestor(adapter)
        resultado = ingestor.sincronizar(
            cnpj=args.cnpj,
            periodos=periodos,
            tipos=tuple(tipos),
            uploaded_by_user_id=args.user_id,
        )
    except IntegraCertError as exc:
        print(f"\n[ERRO] Certificado: {exc}", file=sys.stderr)
        return 3
    except IntegraAuthError as exc:
        print(f"\n[ERRO] Autenticação Serpro: {exc}", file=sys.stderr)
        return 4
    except IntegraError as exc:
        print(f"\n[ERRO] Integra Contador: {exc}", file=sys.stderr)
        return 5
    finally:
        adapter.close()

    print("\n── Resultado ──")
    print(f"Baixados:    {resultado.total_baixados}")
    print(f"Novos:       {resultado.total_novos}")
    print(f"Duplicados:  {resultado.total_duplicados}")
    print(f"Erros:       {len(resultado.erros)}")
    if resultado.erros:
        print("\nDetalhes de erros:")
        for msg in resultado.erros:
            print(f"  - {msg}")

    return 0 if not resultado.erros else 1


if __name__ == "__main__":
    raise SystemExit(main())
