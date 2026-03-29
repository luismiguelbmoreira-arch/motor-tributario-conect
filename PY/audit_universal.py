# -*- coding: utf-8 -*-
"""
audit_universal.py — Pipeline Completo de Auditoria Tributária com IA
Projeto: Motor Tributário Conect 2026-2033
Escritório Contábil Conect — Sorocaba, SP

USO:
  python audit_universal.py "docs/doc calculo/CANAVEZI"
  python audit_universal.py "docs/doc calculo/CONFI_AR"
  python audit_universal.py "docs/doc calculo/ITANGUA"

PIPELINE:
  1. Lê todos os PDFs da pasta da empresa
  2. Claude Vision extrai dados estruturados
  3. Motor calcula DAS
  4. Compara com DAS do e-CAC
  5. Exibe relatório com delta e análise

CONFIGURAÇÃO:
  set ANTHROPIC_API_KEY=sk-ant-...
"""

import logging
import sys
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

# Adiciona PY/ ao path para imports relativos
sys.path.insert(0, str(Path(__file__).parent))

from extrator_pdfs import extrair_dados_pdfs, dados_para_motor
from motor_tributario import (
    EmpresaFornecedora,
    EmpresaCompradora,
    OperacaoFiscal,
    MotorReformaTributaria,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("audit_universal")

LIMITE_DELTA_ACEITAVEL = Decimal("1.00")  # Delta máximo aceitável para aprovação


def auditar_empresa(pasta_empresa: str | Path) -> dict:
    """
    Executa auditoria completa de uma empresa a partir da pasta com PDFs.

    Args:
        pasta_empresa: Caminho para pasta contendo os PDFs (PGDAS-D, CNPJ, etc.)

    Returns:
        dict com resultado da auditoria (motor vs e-CAC, delta, status)
    """
    pasta = Path(pasta_empresa)
    if not pasta.exists():
        raise FileNotFoundError(f"Pasta nao encontrada: {pasta}")

    # Coleta todos os PDFs da pasta
    pdfs = sorted(pasta.glob("*.pdf"))
    if not pdfs:
        raise RuntimeError(f"Nenhum PDF encontrado em: {pasta}")

    print(f"\n{'='*60}")
    print(f"AUDITORIA: {pasta.name}")
    print(f"PDFs encontrados: {len(pdfs)}")
    for pdf in pdfs:
        print(f"  - {pdf.name}")
    print(f"{'='*60}")

    # ETAPA 1: Extração com IA
    print("\n[1/4] Extraindo dados com Claude Vision...")
    dados = extrair_dados_pdfs([str(p) for p in pdfs])
    parametros = dados_para_motor(dados)

    empresa_params = parametros["empresa"]
    auditoria_params = parametros["auditoria"]
    meta = parametros["meta"]

    print(f"      Empresa: {dados.razao_social}")
    print(f"      CNPJ: {dados.cnpj}")
    print(f"      CNAE: {dados.cnae_principal}")
    print(f"      RBT12: R$ {empresa_params['faturamento_12m']:,.2f}")
    print(f"      Confianca extracao: {meta['confianca']:.0%}")

    if meta["campos_ausentes"]:
        print(f"      AVISO: Campos nao encontrados: {', '.join(meta['campos_ausentes'])}")

    # ETAPA 2: Instanciar motor
    print("\n[2/4] Instanciando motor de calculo...")
    fornecedora = EmpresaFornecedora(**empresa_params)

    compradora = EmpresaCompradora(
        tipo="B2B_CONTRIBUINTE",
        regime="PRESUMIDO",
        uf_destino=empresa_params["uf_origem"],
    )

    operacao = OperacaoFiscal(
        data_emissao=date(2026, 1, 1),  # competencia 01/2026
        valor_operacao=auditoria_params["rpa"],
        rpa_mensal=auditoria_params["rpa"],  # base real do DAS — sem isso cai em RBT12/12
        ncm_nbs="84099190",  # NCM generico para fins de auditoria
        forma_recebimento="PIX_BOLETO",
    )

    motor = MotorReformaTributaria(fornecedora, compradora, operacao)
    anexo: str = "MULTI"  # default para multi-atividade; sobrescrito no path mono abaixo

    # ETAPA 3: Calcular DAS
    print("\n[3/4] Calculando DAS pelo motor...")
    rbt12 = motor.calcular_rbt12()

    engine = motor.obter_engine_regime()
    if engine is not None and hasattr(engine, "calcular_das_multi_atividade"):
        # Multi-atividade: usa SimplesMultiAtividadeEngine
        resultado_multi = engine.calcular_carga_total_mensal()
        das_motor = resultado_multi["total_mensal"]
        ae = resultado_multi["aliquota_efetiva"]
        n_atividades = len(resultado_multi["atividades"])
        print(f"      RBT12: R$ {rbt12:,.2f}")
        print(f"      Modo: MULTI-ATIVIDADE ({n_atividades} atividades)")
        for item in resultado_multi["atividades"]:
            flag_st  = " [ST]"  if item["icms_st"]    else ""
            flag_iss = " [ISS-ret]" if item["iss_retido"] else ""
            print(f"        Anexo {item['anexo']}{flag_st}{flag_iss}: "
                  f"R$ {item['receita']:,.2f} × {item['ae_liquida']*100:.4f}% = R$ {item['das']:,.2f}")
        print(f"      Aliquota Efetiva: {ae:.4%}")
        print(f"      DAS Motor: R$ {das_motor:,.2f}")
    else:
        # Mono-atividade: caminho original
        anexo = motor.determinar_anexo()
        ae = motor.calcular_aliquota_efetiva()
        das_motor = motor.calcular_das_mensal()
        print(f"      RBT12: R$ {rbt12:,.2f}")
        print(f"      Anexo: {anexo}")
        print(f"      Aliquota Efetiva: {ae:.4%}")
        print(f"      DAS Motor: R$ {das_motor:,.2f}")

    # ETAPA 4: Comparar com e-CAC
    print("\n[4/4] Comparando com e-CAC...")
    das_ecac = auditoria_params["das_ecac"]
    delta = abs(das_motor - das_ecac)
    delta_pct = (delta / das_ecac * 100) if das_ecac else Decimal("0")

    status = "APROVADO" if delta <= LIMITE_DELTA_ACEITAVEL else "REVISAR"
    icone = "OK" if status == "APROVADO" else "ATENCAO"

    print(f"\n{'='*60}")
    print(f"RESULTADO — {pasta.name}")
    print(f"{'='*60}")
    print(f"  DAS Motor:   R$ {das_motor:>12,.2f}")
    print(f"  DAS e-CAC:   R$ {das_ecac:>12,.2f}")
    print(f"  Delta:       R$ {delta:>12,.2f} ({delta_pct:.2f}%)")
    print(f"  Status:      [{icone}] {status}")

    if auditoria_params.get("breakdown"):
        print(f"\nComposicao do DAS (e-CAC):")
        for tributo, valor in auditoria_params["breakdown"].items():
            if valor and float(str(valor).replace(",", ".")) > 0:
                print(f"  {tributo:<8}: R$ {float(str(valor).replace(',', '.')):>10,.2f}")

    if meta["observacoes"]:
        print(f"\nObservacoes da IA: {meta['observacoes']}")

    print(f"{'='*60}\n")

    # Limpa dados sensíveis da memória
    dados.purge()

    return {
        "empresa": pasta.name,
        "das_motor": das_motor,
        "das_ecac": das_ecac,
        "delta": delta,
        "delta_pct": delta_pct,
        "status": status,
        "anexo": anexo,
        "rbt12": rbt12,
        "ae": ae,
        "confianca_extracao": meta["confianca"],
        "campos_ausentes": meta["campos_ausentes"],
    }


def main():
    if len(sys.argv) < 2:
        print("USO: python audit_universal.py <pasta_empresa>")
        print("     python audit_universal.py docs/doc\\ calculo/CANAVEZI")
        print("     python audit_universal.py docs/doc\\ calculo/CONFI_AR")
        print("     python audit_universal.py docs/doc\\ calculo/ITANGUA")
        sys.exit(1)

    pasta = sys.argv[1]

    try:
        resultado = auditar_empresa(pasta)

        if resultado["status"] == "APROVADO":
            print(f"Auditoria concluida: APROVADO (delta R$ {resultado['delta']:.2f})")
            sys.exit(0)
        else:
            print(
                f"Auditoria concluida: REVISAR (delta R$ {resultado['delta']:.2f} "
                f"— acima do limite de R$ {LIMITE_DELTA_ACEITAVEL})"
            )
            sys.exit(1)

    except FileNotFoundError as e:
        print(f"ERRO: {e}")
        sys.exit(2)
    except ValueError as e:
        print(f"ERRO de configuracao: {e}")
        sys.exit(3)
    except Exception as e:
        print(f"ERRO inesperado: {e}")
        logger.exception("Erro durante auditoria")
        sys.exit(4)


if __name__ == "__main__":
    main()
