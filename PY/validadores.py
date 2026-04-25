"""
validadores.py — Fundação de Dados (Fase 1)
Projeto: Motor Tributário Conect 2026-2033
Padrão: NUNCA lança exceção pura. Retorna ValidationResult estruturado.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, List, Optional

logger = logging.getLogger("motor_conect.validadores")


@dataclass
class ValidationResult:
    """Resultado de validação estruturado. ok=False lista todos os erros."""
    ok: bool
    errors: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok

    def adicionar_erro(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)


# ─────────────────────────────────────────────────────────────────────────────
# UFs válidas do Brasil (26 estados + DF)
# ─────────────────────────────────────────────────────────────────────────────
UFS_VALIDAS = frozenset({
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
    "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
    "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
})


def validar_uf(uf: str) -> ValidationResult:
    """
    Valida se a UF existe.
    Aceita lowercase (normaliza para maiúsculo).
    """
    resultado = ValidationResult(ok=True)
    if not uf or not isinstance(uf, str):
        resultado.adicionar_erro("UF não pode ser vazia.")
        return resultado
    uf_upper = uf.strip().upper()
    if uf_upper not in UFS_VALIDAS:
        resultado.adicionar_erro(f"UF inválida: '{uf}'. Use sigla de 2 letras (ex: SP, RJ).")
    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# Validador NCM — Nomenclatura Comum do Mercosul
# Deve ter exatamente 8 dígitos numéricos (pontuação ignorada)
# ─────────────────────────────────────────────────────────────────────────────
def validar_ncm(ncm: str) -> ValidationResult:
    """
    NCM deve ter exatamente 8 dígitos.
    Aceita formatos com pontuação: 8409.91.90 → 84099190
    """
    resultado = ValidationResult(ok=True)
    if not ncm or not isinstance(ncm, str):
        resultado.adicionar_erro("NCM não pode ser vazio.")
        return resultado
    ncm_limpo = re.sub(r'[\s.\-]', '', ncm.strip())
    if not re.match(r'^\d{8}$', ncm_limpo):
        resultado.adicionar_erro(
            f"NCM inválido: '{ncm}'. Deve conter exatamente 8 dígitos (ex: 84099190)."
        )
    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# Validador CNPJ — Módulo 11 (RFC oficial Receita Federal)
# ─────────────────────────────────────────────────────────────────────────────
def _calcular_digito_cnpj(cnpj14: str, posicao: int) -> int:
    """
    Calcula o dígito verificador do CNPJ na posição indicada (12 ou 13).
    Pesos: posição 12 usa [5,4,3,2,9,8,7,6,5,4,3,2]
           posição 13 usa [6,5,4,3,2,9,8,7,6,5,4,3,2]
    Regra: resto < 2 → dígito = 0, senão → dígito = 11 - resto
    """
    pesos = list(range(posicao - 7, 1, -1)) + list(range(9, 1, -1))
    soma = sum(int(cnpj14[i]) * pesos[i] for i in range(posicao))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def validar_cnpj(cnpj: str) -> ValidationResult:
    """
    Validação completa de CNPJ conforme algoritmo Módulo 11 da Receita Federal.
    Aceita formatos: 12.345.678/0001-95, 12345678000195
    Rejeita: todos os dígitos iguais (00000000000000, etc.)
    """
    resultado = ValidationResult(ok=True)
    if not cnpj or not isinstance(cnpj, str):
        resultado.adicionar_erro("CNPJ não pode ser vazio.")
        return resultado

    # Remove pontuação
    cnpj_limpo = re.sub(r'[\s.\-/]', '', cnpj.strip())

    if len(cnpj_limpo) != 14:
        resultado.adicionar_erro(
            f"CNPJ inválido: deve ter 14 dígitos (recebido: {len(cnpj_limpo)} dígitos)."
        )
        return resultado

    if not cnpj_limpo.isdigit():
        resultado.adicionar_erro("CNPJ inválido: contém caracteres não numéricos.")
        return resultado

    # Rejeita CNPJs com todos os dígitos iguais (ex: 00000000000000)
    if len(set(cnpj_limpo)) == 1:
        resultado.adicionar_erro("CNPJ inválido: todos os dígitos são iguais.")
        return resultado

    # Valida 1º dígito verificador (posição 12)
    d1_esperado = _calcular_digito_cnpj(cnpj_limpo, 12)
    if int(cnpj_limpo[12]) != d1_esperado:
        resultado.adicionar_erro("CNPJ inválido: primeiro dígito verificador incorreto.")
        return resultado

    # Valida 2º dígito verificador (posição 13)
    d2_esperado = _calcular_digito_cnpj(cnpj_limpo, 13)
    if int(cnpj_limpo[13]) != d2_esperado:
        resultado.adicionar_erro("CNPJ inválido: segundo dígito verificador incorreto.")
        return resultado

    return resultado


def normalizar_cnpj(cnpj: str) -> str:
    """Retorna CNPJ apenas com 14 dígitos, sem pontuação."""
    return re.sub(r'[\s.\-/]', '', cnpj.strip())


# ─────────────────────────────────────────────────────────────────────────────
# Validador CNAE — 7 dígitos numéricos
# ─────────────────────────────────────────────────────────────────────────────
def validar_cnae(cnae: str) -> ValidationResult:
    """
    CNAE deve ter exatamente 7 dígitos.
    Aceita formato com hífen: 4711-3/02 → 4711302
    """
    resultado = ValidationResult(ok=True)
    if not cnae or not isinstance(cnae, str):
        resultado.adicionar_erro("CNAE não pode ser vazio.")
        return resultado
    cnae_limpo = re.sub(r'[\s.\-/]', '', cnae.strip())
    if not re.match(r'^\d{7}$', cnae_limpo):
        resultado.adicionar_erro(
            f"CNAE inválido: '{cnae}'. Deve conter exatamente 7 dígitos (ex: 4711302)."
        )
    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# DETECÇÃO DE ANOMALIAS E CROSSCHECK (Legado de validacoes.py)
# ─────────────────────────────────────────────────────────────────────────────

_RBT12_VS_RPA_LIMITE = Decimal("20")
_CONFIANCA_OCR_LIMIAR = 0.75
_FOLHA_VS_RBT12_LIMITE = Decimal("1")
_PIS_DIVERGENCIA_LIMITE = Decimal("0.05")

_TOL_VERDE = Decimal("0.005")   # 0.5%
_TOL_AMARELO = Decimal("0.05")  # 5%

def _ts() -> str:
    return datetime.now().isoformat()

def rbt12_vs_rpa(rbt12: Decimal, rpa_mensal: Decimal) -> Optional[dict[str, Any]]:
    """Dispara se RBT12 > 20× RPA (receita mensal média)."""
    if rpa_mensal <= 0 or rbt12 <= 0:
        return None
    razao = rbt12 / rpa_mensal
    if razao <= _RBT12_VS_RPA_LIMITE:
        return None
    return {
        "tipo": "ALERTA_ANOMALIA_RBT12_DESPROPORCIONAL",
        "id": "ANOMALIA_RBT12_VS_RPA",
        "titulo": "RBT12 desproporcional ao RPA mensal",
        "memoria": {
            "rbt12": str(rbt12), "rpa_mensal": str(rpa_mensal),
            "razao": str(razao.quantize(Decimal("0.01"))),
        },
        "interpretacao": (
            f"RBT12 R$ {rbt12:,.2f} eh {razao:.1f}x o RPA mensal R$ {rpa_mensal:,.2f}. "
            "Ou queda brutal ou erro de extracao. Revisar."
        ),
        "amparo_legal": "LC 123/2006, Art. 3 §2 — base RBT12 mensal",
        "timestamp": _ts(),
    }

def folha_inconsistente(folha_12m: Decimal, rbt12: Decimal) -> Optional[dict[str, Any]]:
    """Dispara se folha_12m > 100% do RBT12."""
    if folha_12m <= 0 or rbt12 <= 0:
        return None
    if folha_12m <= rbt12 * _FOLHA_VS_RBT12_LIMITE:
        return None
    razao = folha_12m / rbt12
    return {
        "tipo": "ALERTA_ANOMALIA_FOLHA_IMPOSSIVEL",
        "id": "ANOMALIA_FOLHA_VS_RBT12",
        "titulo": "Folha maior que faturamento — provavel erro de separador decimal",
        "memoria": {"folha_12m": str(folha_12m), "rbt12": str(rbt12), "razao": str(razao.quantize(Decimal("0.01")))},
        "interpretacao": (
            f"Folha R$ {folha_12m:,.2f} eh {razao:.1f}x o RBT12. "
            "Verificar separador decimal do CSV (virgula vs ponto)."
        ),
        "amparo_legal": "LC 123/2006, Art. 18 §24 — Fator R exige folha real",
        "timestamp": _ts(),
    }

def avaliar_das(das_calculado: Decimal, das_pago: Decimal) -> dict[str, Any]:
    """Crosscheck DAS calculado pelo motor vs DAS efetivamente pago."""
    das_calc = Decimal(das_calculado).quantize(Decimal("0.01"), ROUND_HALF_UP)
    das_pg = Decimal(das_pago).quantize(Decimal("0.01"), ROUND_HALF_UP)
    delta_abs = (das_pg - das_calc).copy_abs()

    _INTERPRETACAO_DAS = {
        "verde": "Divergencia <=0.5% — arredondamento aceitavel.",
        "amarelo": "Divergencia 0.5-5% — verificar periodo ou exclusao ICMS-ST.",
        "vermelho": "Divergencia >5% — possivel erro de apuracao. Revisar PGDAS-D.",
    }

    if das_calc == 0:
        semaforo = "verde" if das_pg == 0 else "vermelho"
        delta_pct = Decimal("0") if das_pg == 0 else Decimal("100")
    else:
        delta_pct_raw = delta_abs / das_calc
        delta_pct = (delta_pct_raw * 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if delta_pct_raw <= _TOL_VERDE:
            semaforo = "verde"
        elif delta_pct_raw <= _TOL_AMARELO:
            semaforo = "amarelo"
        else:
            semaforo = "vermelho"

    return {
        "tipo": "SEMAFORO_DAS",
        "id": "SEMAFORO_DAS_CROSSCHECK",
        "titulo": f"Crosscheck DAS calculado vs pago — {semaforo.upper()}",
        "semaforo": semaforo,
        "memoria": {
            "das_calculado": str(das_calc),
            "das_pago": str(das_pg),
            "delta_abs": str(delta_abs),
            "delta_pct": str(delta_pct),
        },
        "interpretacao": _INTERPRETACAO_DAS[semaforo],
        "amparo_legal": "LC 123/2006, Art. 21 — apuracao mensal do DAS unificado",
    }
