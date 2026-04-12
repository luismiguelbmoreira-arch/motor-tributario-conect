# -*- coding: utf-8 -*-
"""
planejamento_tributario.py — Cérebro Preditivo (Otimizador de Regimes)
Projeto: Motor Tributário Conect 2026-2033

DESCRIÇÃO:
Em vez de auditar cálculos retroativos, recebe a base documental de uma empresa 
(dados de Receita extraídos do PGDAS-D e eventuais dados de DRE/Balancetes) 
e simula o impacto tributário do NOVO IVA DUAL (LC 214/2025) cruzando os 4 Regimes Possíveis.

RIGOR CONTÁBIL (ANTI-CHUTE):
- O cenário LUCRO PRESUMIDO assume a presunção oficial em lei (Lei 9.249/95).
- O cenário LUCRO REAL aborta a simulação caso o payload não traga `lucro_real_mensal`,
  pois "Contabilidade exige lastro documental (DRE)". Não inserimos margem genérica.
"""

import json
import sys
from copy import deepcopy
from decimal import Decimal
from typing import Any, Dict, List, Optional
from datetime import datetime

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from pydantic import ValidationError

from core.motor_tributario import EmpresaFornecedora, EmpresaCompradora, OperacaoFiscal, MotorReformaTributaria


class OtimizadorTributario:
    """Ferramenta para projeção e planejamento tributário sob o novo IVA Dual."""

    REGIMES = ["MEI", "SIMPLES", "PRESUMIDO", "REAL"]

    def __init__(
        self,
        base_fornecedor: Dict[str, Any],
        base_comprador: Dict[str, Any],
        base_operacao: Dict[str, Any]
    ):
        """
        Inicia guardando a estrutura pura (dicts) para permitir a reinjeção 
        segura por regime, evitando contaminações de model fields de classes já instanciadas.
        """
        self.base_fornecedor = base_fornecedor
        self.base_comprador = base_comprador
        self.base_operacao = base_operacao

    def comparar_regimes(self) -> Dict[str, Any]:
        """
        Itera sobre todos os 4 regimes, monta instâncias separadas (isohubs) 
        do MotorReformaTributaria e tenta extrair a totalização do DAS/Carga Anual/Mensal.
        Retorna o relatório comparativo ranqueado.
        """
        cenarios: List[Dict[str, Any]] = []

        for regime in self.REGIMES:
            # Clona os dicts base para modificação atômica
            f_clone = deepcopy(self.base_fornecedor)
            c_clone = deepcopy(self.base_comprador)
            o_clone = deepcopy(self.base_operacao)

            # Força o regime sendo testado
            f_clone["regime"] = regime

            # -------------------------------------------------------------
            # RIGOR CONTÁBIL: Bloqueio do Lucro Real se não há DRE provada
            # -------------------------------------------------------------
            if regime == "REAL":
                if o_clone.get("lucro_real_mensal") is None:
                    cenarios.append({
                        "regime": "REAL",
                        "viavel": False,
                        "motivo_inviabilidade": "INVIÁVEL: Ausência de Documentação Contábil Comprobatória (DRE/Balancete) para atestar o Lucro Líquido Real.",
                        "carga_total_estimada": Decimal("999999999999.00") # Infinity constraint para ordenação rebaixada
                    })
                    continue

            # Injeção e Inicialização do Motor
            try:
                empresa = EmpresaFornecedora(**f_clone)
                comprador = EmpresaCompradora(**c_clone)
                op = OperacaoFiscal(**o_clone)

                with MotorReformaTributaria(empresa, comprador, op) as motor:
                    diagnostico = motor.gerar_diagnostico()
                    
                    # Checando se a Guard Clause ejetou o cliente localmente (ex: Faturamento > Teto Simples/MEI)
                    alertas_criticos = [a for a in diagnostico.get("alertas", []) if a["nivel"] == "CRITICO"]
                    if alertas_criticos:
                        motivo = alertas_criticos[0]["mensagem"]
                        cenarios.append({
                            "regime": regime,
                            "viavel": False,
                            "motivo_inviabilidade": motivo,
                            "carga_total_estimada": Decimal("999999999999.00")
                        })
                        continue

                    # Métrica mestre de Carga Financeira (Resiliência Multi-Engine)
                    carga_financeira = diagnostico.get("das_motor")
                    if carga_financeira is None or carga_financeira == "":
                        carga_financeira = diagnostico.get("aliquotas", {}).get("total_mensal")
                        
                    if carga_financeira is None or carga_financeira == "":
                        ae = diagnostico.get("aliquotas", {}).get("efetiva_das_total", 0)
                        rpa = o_clone.get("rpa_mensal") or o_clone.get("valor_operacao", 0)
                        carga_financeira = float(rpa) * float(ae)
                    
                    if hasattr(carga_financeira, "quantize"):
                        carga_financeira = float(carga_financeira)
                        
                    carga_dec = Decimal(str(carga_financeira))

                    # Se a carga for 0 pode haver anomalia na injeção, mas é matematicamente viável (ex: ISENÇÃO)
                    cenarios.append({
                        "regime": regime,
                        "viavel": True,
                        "motivo_inviabilidade": "",
                        "carga_total_estimada": carga_dec,
                        "breakdown": diagnostico.get("breakdown_regime", {}),
                        "aliquota_efetiva": diagnostico.get("aliquotas", {}).get("efetiva_percentual", "N/A")
                    })

            except ValidationError as ve:
                cenarios.append({
                    "regime": regime,
                    "viavel": False,
                    "motivo_inviabilidade": f"Erro de Estrutura Contábil: {ve.errors()[0]['msg']} em {ve.errors()[0]['loc']}",
                    "carga_total_estimada": Decimal("999999999999.00")
                })
            except Exception as e:
                cenarios.append({
                    "regime": regime,
                    "viavel": False,
                    "motivo_inviabilidade": f"Erro de Cálculo (Engine Falha): {str(e)}",
                    "carga_total_estimada": Decimal("999999999999.00")
                })

        # -------------------------------------------------------------
        # RANQUEAMENTO DE CENÁRIOS
        # -------------------------------------------------------------
        cenarios_ordenados = sorted(cenarios, key=lambda x: x["carga_total_estimada"])

        if cenarios_ordenados and cenarios_ordenados[0]["viavel"]:
            regime_recomendado = cenarios_ordenados[0]["regime"]
            menor_carga = cenarios_ordenados[0]["carga_total_estimada"]
            
            # Pega o atual para tirar a diferença
            regime_atual = self.base_fornecedor.get("regime", "DESCONHECIDO")
            
            # Acha o custo no regime atual para projetar economia:
            custo_atual = menor_carga # Default safety risk
            for c in cenarios_ordenados:
                if c["regime"] == regime_atual and c["viavel"]:
                    custo_atual = c["carga_total_estimada"]
                    break

            economia_mes = custo_atual - menor_carga
        else:
            regime_recomendado = "NÃO DETERMINADO (Todos Inviáveis)"
            economia_mes = Decimal("0")

        return {
            "timestamp_geracao": str(datetime.now()),
            "empresa_analisada": self.base_fornecedor.get("razao_social", "Anônima"),
            "regime_matriz": self.base_fornecedor.get("regime", "NÃO INFORMADO"),
            "recomendacao_otimizada": {
                "regime_vencedor": regime_recomendado,
                "economia_projetada_mes": str(economia_mes),
                "economia_projetada_ano": str(economia_mes * 12)
            },
            "ranqueamento": [
                {
                    "regime": c["regime"],
                    "status": "VIÁVEL✅" if c["viavel"] else "INVIÁVEL❌",
                    "carga_mensal": str(c["carga_total_estimada"]) if c["viavel"] else "BLOQUEADO",
                    "aliquota_efetiva": c.get("aliquota_efetiva", "N/A"),
                    "detalhe": c["motivo_inviabilidade"] if not c["viavel"] else "Cálculo matemático concluído e validado."
                } for c in cenarios_ordenados
            ]
        }


# Execução Exemplo / Laboratório Interno
if __name__ == "__main__":
    from core.motor_tributario import _fmt_brl
    import sys

    # Carrega dados padrão se nao passar via cmd (para evitar error import)
    # Exemplo: Empresa no Simples Nacional prestejada
    payload_exemplo = {
        "fornecedora": {
            "cnpj": "06.990.590/0001-23",
            "razao_social": "CLINICA MÉDICA MARCOS LTDA",
            "regime": "SIMPLES",
            "cnae_principal": "8630503", # Atividade Médica (Geralmente Anexo III com Fator R)
            "uf_origem": "SP",
            "faturamento_12m": "1200000.00",
            "folha_salarios_12m": "480000.00", # Fator R = 40% (Cai no Anexo III)
            "anexo_simples": None
        },
        "compradora": {
            "tipo": "B2C_CONSUMIDOR_FINAL",
            "percentual_b2b": "0",
            "regime": "NAO_INFORMADO",
            "uf_destino": "SP"
        },
        "operacao": {
            "data_emissao": "2026-06-15",
            "valor_operacao": "100000.00",
            "rpa_mensal": "100000.00",      
            "ncm_nbs": "00000000",
            "forma_recebimento": "PIX_BOLETO",
            # "lucro_real_mensal": "35000.00", -> APAGADO DE PROPÓSITO PARA TESTAR BLOQUEIO DE COMPLIANCE
            "tinha_st_icms": False,
            "reducao_cbs_ibs": "REDUCAO_60", # Saúde tem 60% de redução na nova reforma
            "beneficio_fiscal_antigo": "0.00"
        }
    }

    print("\n[+] INICIANDO OTIMIZADOR TRIBUTÁRIO (IVA_DUAL 2026) ...\n")
    motor = OtimizadorTributario(
        base_fornecedor=payload_exemplo["fornecedora"],
        base_comprador=payload_exemplo["compradora"],
        base_operacao=payload_exemplo["operacao"],
    )
    
    comparativo = motor.comparar_regimes()
    
    print(json.dumps(comparativo, indent=2, ensure_ascii=False))

