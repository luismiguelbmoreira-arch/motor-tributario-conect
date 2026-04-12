# -*- coding: utf-8 -*-
"""
guardrails.py — Guardrails de Validação Pré-Cálculo
Projeto: Motor Tributário Conect 2026-2033

G-01: validar_campos_regime() — verifica campos obrigatórios por regime ANTES do motor.
G-05: assert_legal_anchor() — verifica amparo legal em cada passo da trilha.

REGRA: Chamar validar_campos_regime() antes de qualquer cálculo.
FROZEN: Não alterar sem justificativa legal + aprovação de Luiz.
"""

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger("motor_conect.guardrails")


# ─────────────────────────────────────────────────────────────────────────────
# G-01: VALIDAÇÃO DE CAMPOS OBRIGATÓRIOS POR REGIME
# Roda ANTES de instanciar o motor — rejeita entrada incompleta.
# ─────────────────────────────────────────────────────────────────────────────

# Campos obrigatórios universais (todos os regimes)
_CAMPOS_UNIVERSAIS = [
    "cnpj", "razao_social", "regime", "cnae_principal",
    "uf_origem", "faturamento_12m",
]

# Campos obrigatórios adicionais por regime
_CAMPOS_POR_REGIME: Dict[str, List[str]] = {
    "SIMPLES": [],  # folha_salarios_12m é condicional (Fator R, não obrigatório)
    "PRESUMIDO": [],
    "REAL": [],  # lucro_real_mensal recomendado mas usa proxy se ausente
    "MEI": ["categoria_mei"],
}

# Campos condicionais com regras específicas
_CAMPOS_CONDICIONAIS: Dict[str, Dict[str, str]] = {
    "SIMPLES": {
        "folha_salarios_12m": (
            "Recomendado para Fator R (Anexo V→III). "
            "Sem este campo, CNAEs Anexo V permanecerão no Anexo V mesmo com folha alta."
        ),
    },
    "REAL": {
        "lucro_real_mensal": (
            "Recomendado para cálculo preciso de IRPJ/CSLL. "
            "Sem este campo, será usada receita mensal como proxy conservador."
        ),
    },
}

# Campos da operação obrigatórios
_CAMPOS_OPERACAO = ["data_emissao", "valor_operacao"]


class ValidacaoRegimeResult:
    """Resultado da validação de campos por regime."""

    def __init__(self) -> None:
        self.ok: bool = True
        self.erros: List[str] = []
        self.avisos: List[str] = []

    def __bool__(self) -> bool:
        return self.ok

    def adicionar_erro(self, msg: str) -> None:
        self.ok = False
        self.erros.append(msg)

    def adicionar_aviso(self, msg: str) -> None:
        self.avisos.append(msg)


def validar_campos_regime(
    empresa: Any,
    operacao: Optional[Any] = None,
) -> ValidacaoRegimeResult:
    """
    G-01: Valida se todos os campos obrigatórios para o regime da empresa
    estão preenchidos ANTES de instanciar o motor de cálculo.

    Args:
        empresa: Instância de EmpresaFornecedora (ou dict com mesmos campos)
        operacao: Instância de OperacaoFiscal (ou dict), se disponível

    Returns:
        ValidacaoRegimeResult com erros e avisos

    Exemplo:
        resultado = validar_campos_regime(fornecedora, operacao)
        if not resultado:
            raise ValueError(f"Campos inválidos: {resultado.erros}")
    """
    resultado = ValidacaoRegimeResult()

    # Identifica regime
    regime = _get_campo(empresa, "regime")
    if not regime:
        resultado.adicionar_erro(
            "Campo 'regime' ausente. Valores aceitos: SIMPLES, PRESUMIDO, REAL, MEI."
        )
        return resultado

    regime = regime.upper()
    if regime not in _CAMPOS_POR_REGIME:
        resultado.adicionar_erro(
            f"Regime '{regime}' desconhecido. "
            f"Valores aceitos: {list(_CAMPOS_POR_REGIME.keys())}."
        )
        return resultado

    # Verifica campos universais
    for campo in _CAMPOS_UNIVERSAIS:
        valor = _get_campo(empresa, campo)
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            resultado.adicionar_erro(
                f"Campo obrigatório '{campo}' ausente ou vazio (regime={regime})."
            )

    # Verifica campos específicos do regime
    for campo in _CAMPOS_POR_REGIME[regime]:
        valor = _get_campo(empresa, campo)
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            resultado.adicionar_erro(
                f"Campo '{campo}' é obrigatório para regime {regime}."
            )

    # Verifica campos condicionais (avisos, não erros)
    condicionais = _CAMPOS_CONDICIONAIS.get(regime, {})
    for campo, msg in condicionais.items():
        valor = _get_campo(empresa, campo)
        if valor is None:
            resultado.adicionar_aviso(f"Campo condicional '{campo}' ausente: {msg}")

    # Verifica campos da operação (se fornecida)
    if operacao is not None:
        for campo in _CAMPOS_OPERACAO:
            valor = _get_campo(operacao, campo)
            if valor is None:
                resultado.adicionar_erro(
                    f"Campo '{campo}' ausente em OperacaoFiscal."
                )

    # Validações específicas de regime
    if regime == "SIMPLES":
        faturamento = _get_campo(empresa, "faturamento_12m")
        if faturamento is not None:
            try:
                fat_dec = Decimal(str(faturamento))
                if fat_dec > Decimal("4800000.00"):
                    resultado.adicionar_erro(
                        f"RBT12 R$ {fat_dec:,.2f} excede teto do Simples Nacional "
                        f"(R$ 4.800.000,00). LC 123/2006, Art. 3º, II."
                    )
            except Exception:
                pass

    if regime == "MEI":
        faturamento = _get_campo(empresa, "faturamento_12m")
        if faturamento is not None:
            try:
                fat_dec = Decimal(str(faturamento))
                if fat_dec > Decimal("81000.00"):
                    resultado.adicionar_erro(
                        f"RBT12 R$ {fat_dec:,.2f} excede teto do MEI "
                        f"(R$ 81.000,00). LC 123/2006, Art. 18-A, §1º."
                    )
            except Exception:
                pass

    if resultado.avisos:
        for aviso in resultado.avisos:
            logger.warning("GUARDRAIL_AVISO | %s", aviso)

    if not resultado.ok:
        for erro in resultado.erros:
            logger.error("GUARDRAIL_ERRO | %s", erro)

    return resultado


def _get_campo(obj: Any, campo: str) -> Any:
    """Extrai campo de objeto Pydantic ou dict."""
    if isinstance(obj, dict):
        return obj.get(campo)
    return getattr(obj, campo, None)


# ─────────────────────────────────────────────────────────────────────────────
# G-05: ASSERT LEGAL ANCHOR — Verifica amparo legal em trilha de auditoria
# ─────────────────────────────────────────────────────────────────────────────

def assert_legal_anchor(trilha: List[Dict[str, Any]]) -> List[str]:
    """
    G-05: Verifica que todo passo na trilha de auditoria tem amparo_legal
    não vazio. Retorna lista de IDs de passos sem amparo.

    Regra MAX_FISCAL_02: "Todo valor calculado deve ter citação de artigo de lei".

    Args:
        trilha: lista de dicts (passos da trilha_auditoria)

    Returns:
        Lista de IDs de passos sem amparo_legal (vazia = tudo OK)
    """
    sem_amparo = []
    for passo in trilha:
        amparo = passo.get("amparo_legal", "")
        if not amparo or not str(amparo).strip():
            passo_id = passo.get("id", "DESCONHECIDO")
            sem_amparo.append(passo_id)
            logger.warning(
                "GUARDRAIL_G05 | Passo '%s' sem amparo_legal — viola MAX_FISCAL_02",
                passo_id,
            )
    return sem_amparo
