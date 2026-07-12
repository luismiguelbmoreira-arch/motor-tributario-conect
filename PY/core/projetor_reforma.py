# -*- coding: utf-8 -*-
"""
core/projetor_reforma.py — Projetor da Reforma Tributária 2026-2033

POSICIONAMENTO ARQUITETURAL (project_visao_saas.md):
  Motor Tributário Conect NÃO é calculadora de IRPJ/CSLL do zero.
  É EXTRATOR + PARAMETRIZADOR + PROJETOR:
    1. EXTRAI valores prontos dos PDFs do contador (Claude Vision —
       services/extrator_pdfs.py)
    2. PARAMETRIZA o cenário fiscal atual (regime, porte, ativid., CNAE)
    3. PROJETA o Δ Reforma Tributária 2026-2033 (CBS/IBS/IS/Split Payment)
       conforme CRONOGRAMA_IVA + LC 214/2025 Arts. 344, 348, 353-360

Este módulo é o caller canônico do CRONOGRAMA_IVA (já existente em
core/tabelas_simples.py, validado por Luiz Moreira em 2026-04-25).

PEÇAS REUSADAS:
  - DadosExtraidosPDF (services/extrator_pdfs.py) — origem dos números
  - CRONOGRAMA_IVA (core/tabelas_simples.py) — alíquotas CBS/IBS por ano
  - HistoricoSeisMeses (schemas/historico_seis_meses.py) — 6 meses validados
  - DiagnosticoConsolidado (core/historico_consolidado.py) — projeção mensal

ENGINES DE REGIME (LucroReal/Presumido/MEI/Imune/SimplesMulti) são usados
como VALIDADORES SECUNDÁRIOS do extrato — confirmam batimento entre número
declarado pelo contador e cálculo independente. Não são fonte primária do
diagnóstico (Rail R5: separação fonte ≠ motor).

BASE LEGAL:
  - LC 214/2025 Art. 344 (transição CBS/IBS)
  - LC 214/2025 Art. 348 (cronograma)
  - LC 214/2025 Arts. 353-360 (Split Payment + crédito B2B)
  - EC 132/2023 (Reforma Tributária)
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from core.tabelas_simples import CRONOGRAMA_IVA

# ─────────────────────────────────────────────────────────────────────────────
# CRONOGRAMA DE EXTINÇÃO PIS/COFINS/ICMS/ISS (modelagem v2)
#
# Espelha o cronograma fiscal validado pelo CRCSP/Luiz Moreira em
# tabelas_simples.py (fix ERR-045 — "ICMS/ISS reduzidas em 10% ao ano"):
#
#   - PIS/COFINS:
#       2026         → 100% devidos (CBS 0,9% é teste compensável)
#       2027-2033    → 0% (extintos — substituídos por CBS plena)
#
#   - ICMS/ISS:
#       2026-2028    → 100% devidos (IBS 0,1% é teste)
#       2029         → 90%  (reduzidos 10%)
#       2030         → 80%  (reduzidos 20%)
#       2031         → 70%  (reduzidos 30%)
#       2032         → 60%  (reduzidos 40%)
#       2033         → 0%   (extintos — IBS pleno)
#
# Amparo: LC 214/2025 Arts. 344, 347, 348 + EC 132/2023.
#
# IRPJ, CSLL, CPP e IPI NÃO entram aqui — não são tocados pela Reforma.
# ─────────────────────────────────────────────────────────────────────────────

_FATOR_RESIDUAL_PIS_COFINS: dict[int, Decimal] = {
    2026: Decimal("1.0"),
    2027: Decimal("0.0"), 2028: Decimal("0.0"), 2029: Decimal("0.0"),
    2030: Decimal("0.0"), 2031: Decimal("0.0"), 2032: Decimal("0.0"),
    2033: Decimal("0.0"),
}

_FATOR_RESIDUAL_ICMS_ISS: dict[int, Decimal] = {
    2026: Decimal("1.0"), 2027: Decimal("1.0"), 2028: Decimal("1.0"),
    2029: Decimal("0.9"),
    2030: Decimal("0.8"),
    2031: Decimal("0.7"),
    2032: Decimal("0.6"),
    2033: Decimal("0.0"),
}

# ─────────────────────────────────────────────────────────────────────────────
# TIPOS
# ─────────────────────────────────────────────────────────────────────────────

AnoTransicao = Literal[2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033]
RegimeAtual = Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI", "IMUNE"]


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA — Documento extraído (origem: PDFs do contador)
# ─────────────────────────────────────────────────────────────────────────────

class DocumentoFiscalExtraido(BaseModel):
    """
    Carga tributária consolidada extraída de documentos do contador.

    Origem canônica: services.extrator_pdfs.DadosExtraidosPDF + breakdown DAS.
    Schema mínimo necessário pra projetar Δ Reforma Tributária.

    Cada campo numérico é Decimal (Rail "nunca float em dinheiro" — CLAUDE.md).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cnpj: str = Field(description="CNPJ 14 dígitos sem pontuação.")
    competencia: date = Field(
        description="Mês de referência da apuração (data do 1º dia do mês)."
    )
    regime_atual: RegimeAtual
    receita_bruta_mensal: Decimal = Field(
        ge=Decimal("0"),
        description="Receita bruta da competência (extraída do PDF do contador).",
    )

    # Breakdown da carga ATUAL (extraída do DAS / DARF / ECF / balancete)
    irpj_pago: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    csll_paga: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    pis_pago: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    cofins_paga: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    icms_pago: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"),
        description="ICMS efetivamente recolhido (já líquido de créditos).",
    )
    iss_pago: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    ipi_pago: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"),
        description="IPI efetivamente recolhido (já líquido de créditos).",
    )
    cpp_pago: Decimal = Field(
        default=Decimal("0"), ge=Decimal("0"),
        description="Contribuição Previdenciária Patronal sobre folha.",
    )

    # Rastreabilidade (LGPD + auditoria)
    documento_origem_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 do PDF de origem (auditoria_documentos.hash).",
    )
    fonte_extracao: str = Field(
        default="extracao_pdf_claude_vision",
        description="Origem da extração (ex: extracao_pdf_claude_vision, fonte_nibo).",
    )

    @classmethod
    def from_dados_extraidos_pdf(
        cls,
        dados: object,  # services.extrator_pdfs.DadosExtraidosPDF — Any pra evitar ciclo
        *,
        regime_atual: RegimeAtual,
        competencia_override: Optional[date] = None,
        documento_origem_hash: Optional[str] = None,
    ) -> "DocumentoFiscalExtraido":
        """
        Adapter: DadosExtraidosPDF (Claude Vision) → DocumentoFiscalExtraido.

        Mapeamento:
          - cnpj: normaliza removendo pontuação
          - competencia: parseia "MM/AAAA" → date(AAAA, MM, 1)
          - receita_bruta_mensal: pega de `rpa_referencia` (receita do
            período de apuração mensal)
          - tributos: lê de `das_breakdown` (chaves IRPJ, CSLL, COFINS, PIS,
            CPP, ICMS, ISS, IPI) — valores podem vir como str/Decimal/float

        Args:
            dados: instância de services.extrator_pdfs.DadosExtraidosPDF
            regime_atual: regime declarado pela empresa (caller já validou)
            competencia_override: força competência (default: parsear `dados.competencia`)
            documento_origem_hash: SHA-256 do PDF cifrado (auditoria_documentos.hash)
        """
        # CNPJ normalizado (só dígitos)
        cnpj_str = str(getattr(dados, "cnpj", "")).strip()
        cnpj_digits = "".join(c for c in cnpj_str if c.isdigit())
        if len(cnpj_digits) != 14:
            raise ValueError(
                f"CNPJ inválido em DadosExtraidosPDF: {cnpj_str!r} "
                f"({len(cnpj_digits)} dígitos)"
            )

        # Competência
        if competencia_override is not None:
            competencia = competencia_override
        else:
            comp_str = str(getattr(dados, "competencia", "")).strip()
            try:
                mes, ano = comp_str.split("/")
                competencia = date(int(ano), int(mes), 1)
            except (ValueError, AttributeError) as e:
                raise ValueError(
                    f"competencia inválida em DadosExtraidosPDF: {comp_str!r}. "
                    "Formato esperado: MM/AAAA."
                ) from e

        # Receita bruta = RPA mensal (não RBT12 anual)
        rpa = str(getattr(dados, "rpa_referencia", "0"))
        receita_bruta_mensal = _to_decimal(rpa)

        # Breakdown DAS — dict[str, str|Decimal|float]
        breakdown = getattr(dados, "das_breakdown", {}) or {}

        return cls(
            cnpj=cnpj_digits,
            competencia=competencia,
            regime_atual=regime_atual,
            receita_bruta_mensal=receita_bruta_mensal,
            irpj_pago=_to_decimal(breakdown.get("IRPJ", 0)),
            csll_paga=_to_decimal(breakdown.get("CSLL", 0)),
            pis_pago=_to_decimal(breakdown.get("PIS", 0)),
            cofins_paga=_to_decimal(breakdown.get("COFINS", 0)),
            icms_pago=_to_decimal(breakdown.get("ICMS", 0)),
            iss_pago=_to_decimal(breakdown.get("ISS", 0)),
            ipi_pago=_to_decimal(breakdown.get("IPI", 0)),
            cpp_pago=_to_decimal(breakdown.get("CPP", 0)),
            documento_origem_hash=documento_origem_hash,
            fonte_extracao="extracao_pdf_claude_vision",
        )


def _to_decimal(v) -> Decimal:
    """Conversor robusto str/float/Decimal/None → Decimal não-negativo."""
    if v is None or v == "":
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    # String — pode vir como "1.234,56" (BR) ou "1234.56" (EN)
    s = str(v).strip().replace("R$", "").strip()
    # Remove separador de milhares BR (.) quando há vírgula decimal
    if "," in s and s.count(",") == 1:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except Exception as e:
        raise ValueError(f"Não consegui converter {v!r} para Decimal") from e


class DeltaReformaTributaria(BaseModel):
    """
    Resultado da projeção Δ Reforma Tributária.

    Compara carga ATUAL (extraída do PDF) vs carga PROJETADA no ano-alvo
    (aplicando CRONOGRAMA_IVA + extinção gradual PIS/COFINS/ICMS/ISS).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    competencia: date
    ano_alvo: int
    cnpj: str

    carga_atual: Decimal = Field(
        description="Soma dos tributos pagos hoje (IRPJ + CSLL + PIS + COFINS + ICMS + ISS + IPI + CPP)."
    )
    carga_projetada: Decimal = Field(
        description="Soma projetada no cenário CBS/IBS do ano-alvo."
    )
    delta_absoluto: Decimal = Field(
        description="carga_projetada - carga_atual (positivo = aumento)."
    )
    delta_percentual: Decimal = Field(
        description="delta_absoluto / carga_atual (Decimal, ex: 0.15 = +15%)."
    )

    breakdown_projetado: dict[str, Decimal] = Field(
        description=(
            "Componentes da projeção: cbs, ibs, pis_residual, cofins_residual, "
            "icms_residual, iss_residual, irpj_csll (não mudam pela Reforma), etc."
        )
    )

    aliquota_cbs: Decimal = Field(description="CBS vigente no ano-alvo (Cronograma).")
    aliquota_ibs: Decimal = Field(description="IBS vigente no ano-alvo (Cronograma).")
    base_legal: tuple[str, ...] = Field(
        default=(
            "LC 214/2025 Art. 344 (transição CBS/IBS)",
            "LC 214/2025 Art. 348 (cronograma)",
            "EC 132/2023 (Reforma Tributária)",
        )
    )
    avisos: tuple[str, ...] = Field(
        default=(),
        description="Avisos não supressíveis (aproximações e limitações da projeção).",
    )


# ─────────────────────────────────────────────────────────────────────────────
# API PÚBLICA
# ─────────────────────────────────────────────────────────────────────────────

def projetar_delta_reforma(
    *,
    documento: DocumentoFiscalExtraido,
    ano_alvo: AnoTransicao,
) -> DeltaReformaTributaria:
    """
    Projeta o Δ Reforma Tributária para o documento extraído.

    Aplica o CRONOGRAMA_IVA do ano-alvo (alíquotas CBS/IBS validadas por
    Luiz Moreira contra LC 214/2025) sobre a receita bruta do documento,
    mantendo IRPJ/CSLL/CPP inalterados (não são afetados pela Reforma) e
    reduzindo PIS/COFINS/ICMS/ISS conforme o cronograma de extinção.

    MODELAGEM v2 (09/05/2026): cronograma de extinção gradual conforme
    LC 214/2025 Arts. 344, 347, 348 (validado por CRCSP/Luiz Moreira em
    tabelas_simples.py — fix ERR-045):
      - PIS/COFINS: 100% em 2026; 0% de 2027 em diante (extintos)
      - ICMS/ISS: 100% em 2026-2028; 90/80/70/60% em 2029-2032; 0% em 2033
      - IRPJ/CSLL/CPP/IPI: permanecem (não tocados pela Reforma)
      - Sem cálculo de crédito B2B nem Split Payment (etapas futuras)

    Args:
        documento: DocumentoFiscalExtraido (origem: PDF do contador).
        ano_alvo: ano da transição (2026-2033) pra projetar.

    Returns:
        DeltaReformaTributaria frozen com carga atual, projetada, delta, breakdown.

    Raises:
        ValueError: ano_alvo fora do cronograma vigente.
    """
    if ano_alvo not in CRONOGRAMA_IVA:
        raise ValueError(
            f"Ano {ano_alvo} fora do cronograma vigente. "
            f"Anos disponíveis: {sorted(CRONOGRAMA_IVA.keys())}. "
            f"LC 214/2025 Art. 348."
        )

    aliquotas = CRONOGRAMA_IVA[ano_alvo]
    aliq_cbs = Decimal(str(aliquotas["CBS"]))
    aliq_ibs = Decimal(str(aliquotas["IBS"]))

    # ── Guard de regime (espírito Rail R5) ──────────────────────────────────
    # SIMPLES/MEI NÃO passam pelos fatores de extinção: dentro do Simples,
    # PIS/COFINS/ICMS/ISS não se extinguem — MIGRAM pra CBS/IBS NA PARTILHA
    # do DAS, mantendo o recolhimento unificado (LC 214/2025, Art. 41,
    # §§ 1º e 2º + Art. 519, que dá aos Anexos I-V da LC 123 a redação dos
    # Anexos XVIII-XXII). Aplicar extinção aqui zeraria parcelas do DAS em
    # 2027+ e somaria CBS/IBS "por fora" — dupla distorção.
    if documento.regime_atual in ("SIMPLES", "MEI"):
        return _projetar_simples_mei(
            documento=documento,
            ano_alvo=ano_alvo,
            aliq_cbs=aliq_cbs,
            aliq_ibs=aliq_ibs,
        )

    fator_pis_cofins = _FATOR_RESIDUAL_PIS_COFINS[ano_alvo]
    fator_icms_iss = _FATOR_RESIDUAL_ICMS_ISS[ano_alvo]

    # Carga atual = soma dos tributos pagos (já líquidos, extraídos do PDF)
    carga_atual = (
        documento.irpj_pago
        + documento.csll_paga
        + documento.pis_pago
        + documento.cofins_paga
        + documento.icms_pago
        + documento.iss_pago
        + documento.ipi_pago
        + documento.cpp_pago
    ).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # Projeção CBS/IBS sobre receita bruta (sem créditos — etapa futura)
    cbs_projetado = (documento.receita_bruta_mensal * aliq_cbs).quantize(
        Decimal("0.01"), ROUND_HALF_UP,
    )
    ibs_projetado = (documento.receita_bruta_mensal * aliq_ibs).quantize(
        Decimal("0.01"), ROUND_HALF_UP,
    )

    # Residuais PIS/COFINS/ICMS/ISS (modelagem v2 — cronograma legal)
    pis_residual = (documento.pis_pago * fator_pis_cofins).quantize(
        Decimal("0.01"), ROUND_HALF_UP,
    )
    cofins_residual = (documento.cofins_paga * fator_pis_cofins).quantize(
        Decimal("0.01"), ROUND_HALF_UP,
    )
    icms_residual = (documento.icms_pago * fator_icms_iss).quantize(
        Decimal("0.01"), ROUND_HALF_UP,
    )
    iss_residual = (documento.iss_pago * fator_icms_iss).quantize(
        Decimal("0.01"), ROUND_HALF_UP,
    )

    # IRPJ/CSLL/CPP/IPI permanecem (não mudam com Reforma)
    breakdown = {
        "cbs": cbs_projetado,
        "ibs": ibs_projetado,
        "irpj_inalterado": documento.irpj_pago,
        "csll_inalterada": documento.csll_paga,
        "ipi_inalterado": documento.ipi_pago,
        "cpp_inalterada": documento.cpp_pago,
        "pis_residual": pis_residual,
        "cofins_residual": cofins_residual,
        "icms_residual": icms_residual,
        "iss_residual": iss_residual,
    }

    carga_projetada = sum(breakdown.values())
    if not isinstance(carga_projetada, Decimal):
        carga_projetada = Decimal(str(carga_projetada))
    carga_projetada = carga_projetada.quantize(Decimal("0.01"), ROUND_HALF_UP)

    delta_absoluto = (carga_projetada - carga_atual).quantize(
        Decimal("0.01"), ROUND_HALF_UP,
    )
    delta_percentual = (
        (delta_absoluto / carga_atual).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        if carga_atual > 0
        else Decimal("0")
    )

    return DeltaReformaTributaria(
        competencia=documento.competencia,
        ano_alvo=ano_alvo,
        cnpj=documento.cnpj,
        carga_atual=carga_atual,
        carga_projetada=carga_projetada,
        delta_absoluto=delta_absoluto,
        delta_percentual=delta_percentual,
        breakdown_projetado=breakdown,
        aliquota_cbs=aliq_cbs,
        aliquota_ibs=aliq_ibs,
    )


AVISO_SIMPLES_APROXIMACAO = (
    "APROXIMACAO_ANEXOS_LC214: total do DAS mantido constante no ano-alvo. "
    "As tabelas dos Anexos XVIII-XXII da LC 214/2025 (Art. 519, vigências "
    "2027-2033, com CBS/IBS na partilha) ainda não estão versionadas no "
    "motor — as alíquotas nominais publicadas variam pontualmente por "
    "vigência (ex.: Anexo I faixa 6: 19,00% → 18,90% em 2027-2028)."
)


def _projetar_simples_mei(
    *,
    documento: DocumentoFiscalExtraido,
    ano_alvo: AnoTransicao,
    aliq_cbs: Decimal,
    aliq_ibs: Decimal,
) -> DeltaReformaTributaria:
    """
    Projeção pra optantes do Simples Nacional / MEI.

    O optante permanece sujeito ao regime unificado (LC 214/2025, Art. 41,
    §§ 1º e 2º): CBS/IBS entram DENTRO da partilha do DAS (Anexos XVIII-XXII,
    Art. 519) substituindo PIS/COFINS/ICMS/ISS sem alterar materialmente o
    total recolhido. Modelagem interina validada (parecer Luiz Moreira
    12/07/2026): carga projetada = carga atual, com aviso de aproximação
    não supressível até o versionamento das tabelas 2027+.
    """
    carga_atual = (
        documento.irpj_pago
        + documento.csll_paga
        + documento.pis_pago
        + documento.cofins_paga
        + documento.icms_pago
        + documento.iss_pago
        + documento.ipi_pago
        + documento.cpp_pago
    ).quantize(Decimal("0.01"), ROUND_HALF_UP)

    # Parcelas do DAS mantidas — em 2027+ PIS/COFINS/ICMS/ISS migram pra
    # CBS/IBS na partilha, com total preservado (aproximação interina).
    breakdown = {
        "das_irpj": documento.irpj_pago,
        "das_csll": documento.csll_paga,
        "das_pis": documento.pis_pago,
        "das_cofins": documento.cofins_paga,
        "das_icms": documento.icms_pago,
        "das_iss": documento.iss_pago,
        "das_ipi": documento.ipi_pago,
        "das_cpp": documento.cpp_pago,
    }

    return DeltaReformaTributaria(
        competencia=documento.competencia,
        ano_alvo=ano_alvo,
        cnpj=documento.cnpj,
        carga_atual=carga_atual,
        carga_projetada=carga_atual,
        delta_absoluto=Decimal("0.00"),
        delta_percentual=Decimal("0"),
        breakdown_projetado=breakdown,
        aliquota_cbs=aliq_cbs,
        aliquota_ibs=aliq_ibs,
        base_legal=(
            "LC 214/2025 Art. 41, §§ 1º e 2º (optante permanece no regime unificado)",
            "LC 214/2025 Art. 519 (Anexos XVIII-XXII — CBS/IBS na partilha do DAS)",
            "LC 123/2006 Art. 13 (recolhimento unificado)",
            "EC 132/2023 (Reforma Tributária)",
        ),
        # Em 2026 as tabelas vigentes SÃO as oficiais da LC 123 — não há
        # aproximação; o aviso só vale quando os Anexos XVIII-XXII (2027+)
        # passam a reger a partilha.
        avisos=(AVISO_SIMPLES_APROXIMACAO,) if ano_alvo >= 2027 else (),
    )
