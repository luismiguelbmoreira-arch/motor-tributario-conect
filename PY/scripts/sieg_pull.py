"""
sieg_pull.py — CLI para sincronizar XMLs Sieg → storage cifrado.

Uso:
    python PY/scripts/sieg_pull.py --cnpj 12345678000190 \
        --data-inicio 2025-01-01 --data-fim 2025-12-31

    python PY/scripts/sieg_pull.py --cnpj 12345678000190 \
        --ano-base 2025 --xml-type 1

Flags:
    --cnpj          CNPJ (14 dígitos, com ou sem pontuação)
    --data-inicio   ISO YYYY-MM-DD
    --data-fim      ISO YYYY-MM-DD
    --ano-base      Atalho: baixa ano inteiro (01/01..31/12)
    --xml-type      1=NFe (default), 2=CTe, 3=NFSe, 4=NFCe
    --dry-run       Não persiste — só mostra o que seria baixado
    --verbose       Logging DEBUG

Exige SIEG_API_KEY em env, arquivo ou AWS Secrets Manager.
Ver CLAUDE.md → seção "Fontes alternativas da master key".
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

# PY/ no sys.path — permite rodar de qualquer lugar
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from integrations.sieg_adapter import (  # noqa: E402
    SiegAdapter,
    SiegError,
    XML_TYPES_VALIDOS,
)
from integrations.sieg_credentials import (  # noqa: E402
    SiegCredentialError,
    get_sieg_api_key,
)
from integrations.sieg_ingestor import SiegIngestor  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Sincroniza XMLs da Sieg para o storage cifrado.",
    )
    p.add_argument("--cnpj", required=True, help="CNPJ (14 dígitos)")
    p.add_argument("--data-inicio", help="ISO YYYY-MM-DD")
    p.add_argument("--data-fim", help="ISO YYYY-MM-DD")
    p.add_argument(
        "--ano-base",
        type=int,
        help="Atalho: --ano-base 2025 baixa 2025-01-01..2025-12-31",
    )
    p.add_argument(
        "--xml-type",
        type=int,
        default=1,
        choices=XML_TYPES_VALIDOS,
        help="1=NFe, 2=CTe, 3=NFSe, 4=NFCe",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Só lista — não grava em disco nem DB",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def _resolver_janela(args: argparse.Namespace) -> tuple[date, date]:
    if args.ano_base:
        if args.data_inicio or args.data_fim:
            raise SystemExit("--ano-base é mutuamente exclusivo com --data-*")
        return (date(args.ano_base, 1, 1), date(args.ano_base, 12, 31))
    if not args.data_inicio or not args.data_fim:
        raise SystemExit("Forneça --ano-base OU (--data-inicio E --data-fim)")
    try:
        return (date.fromisoformat(args.data_inicio), date.fromisoformat(args.data_fim))
    except ValueError as exc:
        raise SystemExit(f"Data inválida: {exc}") from exc


def _dry_run_lista(adapter: SiegAdapter, *, cnpj: str, ini: date, fim: date, xml_type: int) -> int:
    """Itera sem persistir, só conta."""
    contador = 0
    try:
        for item in adapter.baixar_xmls(
            cnpj=cnpj,
            data_inicio=ini,
            data_fim=fim,
            xml_type=xml_type,
        ):
            contador += 1
            print(f"  [{contador:4d}] chave={item.chave}  bytes={len(item.xml_bytes)}")
    except SiegError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    print(f"\nDry-run: {contador} XMLs seriam baixados.")
    return 0


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    data_inicio, data_fim = _resolver_janela(args)

    # Lazy imports para evitar side-effects em dry-run
    try:
        api_key = get_sieg_api_key()
    except SiegCredentialError as exc:
        print(f"ERRO DE CREDENCIAL: {exc}", file=sys.stderr)
        return 1

    adapter = SiegAdapter(api_key=api_key)

    if args.dry_run:
        return _dry_run_lista(
            adapter,
            cnpj=args.cnpj,
            ini=data_inicio,
            fim=data_fim,
            xml_type=args.xml_type,
        )

    # Real: exige MOTOR_CONECT_MASTER_KEY para cifragem
    if not os.environ.get("MOTOR_CONECT_MASTER_KEY"):
        print(
            "ERRO: MOTOR_CONECT_MASTER_KEY não definida — obrigatória para cifragem.",
            file=sys.stderr,
        )
        return 1

    ingestor = SiegIngestor(adapter)
    try:
        resultado = ingestor.sincronizar(
            cnpj=args.cnpj,
            data_inicio=data_inicio,
            data_fim=data_fim,
            xml_type=args.xml_type,
        )
    except SiegError as exc:
        print(f"ERRO SIEG: {exc}", file=sys.stderr)
        return 2

    print("Sincronização concluída:")
    print(f"  CNPJ:          {resultado.cnpj}")
    print(f"  Janela:        {resultado.data_inicio} .. {resultado.data_fim}")
    print(f"  Baixados:      {resultado.total_baixados}")
    print(f"  Novos:         {resultado.total_novos}")
    print(f"  Duplicados:    {resultado.total_duplicados}")
    print(f"  Erros parciais:{len(resultado.erros)}")
    for erro in resultado.erros[:10]:
        print(f"    ! {erro}")
    return 0 if not resultado.erros else 3


if __name__ == "__main__":
    sys.exit(main())
