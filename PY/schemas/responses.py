# -*- coding: utf-8 -*-
"""
responses.py — Contratos de Response da API (Pydantic V2).

Missão: frontend e backend falando a mesma língua. Resposta dos endpoints
/analise/pdf e /analise/manual padronizada em DiagnosticoResponse.

Filosofia:
  - Envelope estável: { diagnostico, pii }.
  - O miolo de `diagnostico` é Dict[str, Any] porque o motor evolui e o
    front tolera campos novos sem quebrar (forward-compat). Contrato forte
    é o envelope; o diagnóstico interno é opaco ao schema.
  - _extracao, _anomalias, _erros, trilha_auditoria vivem DENTRO de
    `diagnostico` (é onde o frontend já lê — ver UI/resultado.html).
  - Decimal nunca aparece aqui — backend serializa como str antes de
    montar a resposta (ver _serializar_decimal em main.py).
"""

from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field


class PIIResponse(BaseModel):
    """
    Bloco PII separado do diagnóstico (LGPD Art. 6º V — minimização).

    Zero-Trust na saída: string vazia passa despercebida pelo frontend como
    header "--" e mascara falhas silenciosas de extração. min_length força
    o motor a falhar cedo (500 explícito) quando CNPJ/razão social vierem
    vazios — sinal claro de que o PDF foi ruim, não de bug visual.
    """
    model_config = ConfigDict(extra="forbid")

    cnpj: str = Field(
        ...,
        min_length=14,
        max_length=14,
        description="CNPJ sem pontuação (14 dígitos)",
    )
    razao_social: str = Field(
        ...,
        min_length=2,
        description="Razão social da empresa",
    )


class DiagnosticoResponse(BaseModel):
    """
    Resposta canônica de /analise/pdf e /analise/manual.

    Chaves opcionais que o motor popula dentro de `diagnostico` em runtime:
      - _extracao      : metadados da extração de PDF (confiança, docs auditoria).
      - _anomalias     : alertas SPED×NFe, confiança baixa, etc.
      - _erros         : erros não-fatais do pipeline (parsers, validações opcionais).
      - trilha_auditoria: passos fiscais (MAX_01/MAX_02 — base → dedução → alíquota → valor).
    """
    # extra="ignore" (default): resposta permissiva — front tolera campos novos.
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "diagnostico": {
                    "regime": "SIMPLES",
                    "das_calculado": "1234.56",
                    "_extracao": {"confianca": 0.94, "documentos_auditoria": []},
                    "_anomalias": [],
                    "trilha_auditoria": [],
                },
                "pii": {"cnpj": "12345678000190", "razao_social": "Empresa X LTDA"},
            }
        }
    )

    diagnostico: Dict[str, Any] = Field(
        ...,
        description=(
            "Diagnóstico tributário gerado pelo motor. Contém chaves internas "
            "_extracao, _anomalias, _erros e trilha_auditoria quando aplicável."
        ),
    )
    pii: PIIResponse = Field(
        ...,
        description="Dados identificáveis (CNPJ + razão social) — separados do diagnóstico",
    )
