# -*- coding: utf-8 -*-
"""
core/comparador_cenarios.py — Comparador de Cenários Fiscais 2026-2033

PEÇA FINAL DO REDESIGN (visão SaaS): o motor NÃO recalcula o imposto do
cliente — EXTRAI da guia (carga real), PARAMETRIZA o perfil (anexo, tipo
societário, faturamento) e PROJETA cenários alternativos pra apontar o
melhor cenário fiscal por ano-alvo da Reforma Tributária.

FLUXO:
  DocumentoFiscalExtraido (guia — carga REAL, nunca recalculada)
    + PerfilEmpresa (CNAE, tipo societário, RBT12, folha, DRE opcional)
    → cenário MANTER (guia projetada via projetor_reforma)
    → cenários MIGRAR (engines existentes — MAX_08: inputs hipotéticos
      que o MOTOR calcula; zero cálculo mental)
    → viabilidade societária via orquestrador (matriz 13×4 + tetos R3/R7)
    → ranking no PERÍMETRO COMPARÁVEL + guarda anti-falso-vencedor

PERÍMETRO COMPARÁVEL (parecer Luiz Moreira 12/07/2026):
  IRPJ + CSLL + PIS/COFINS residuais + CBS + IBS — o mesmo recorte dos
  dois lados da comparação.
  FORA do ranking (exibidos, nunca somados):
    - ICMS/ISS: no Simples valor conhecido (partilha do DAS); em
      Presumido/Real NÃO QUANTIFICADO (sem fonte unificada por UF/município
      — Rail R2).
    - CPP: excluída DOS DOIS LADOS (no Simples embutida na partilha
      Anexos I/II/III/V; fora dele, 20% da folha — quantificação BLOQUEADA
      até a Lei 8.212/91 entrar no cache de fontes, Rail R1/MAX_07).
    - IPI e Imposto Seletivo: exibidos quando presentes.

GUARDA ANTI-FALSO-VENCEDOR:
  Quando a comparação cruza Simples ↔ regime normal, o piso conhecido do
  custo não comparado = fração ICMS+ISS do DAS. Se |Δ| < piso, o resultado
  sai INCONCLUSIVO — proibido declarar vencedor (a decisão estaria
  exatamente na parte não comparável).

BASE LEGAL:
  - LC 123/2006, Art. 18, § 1º (alíquota efetiva) + § 24 (Fator R)
    + Art. 18, § 5º-C (Anexo IV: CPP por fora) + Art. 3º (teto)
    + Arts. 13-A e 19, § 4º (sublimite ICMS/ISS)
  - LC 214/2025, Art. 41, §§ 1º e 2º (optante permanece no regime unificado)
    + Art. 47 (não-cumulatividade — débito bruto ≠ carga líquida)
    + Arts. 344, 347, 348 (transição) + Art. 519 (Anexos XVIII-XXII)
  - Lei 9.249/1995, Arts. 15 e 20; Lei 9.718/1998, Arts. 2º e 13;
    Lei 9.430/1996, Arts. 25 e 29
  - EC 132/2023 + ADCT Art. 126
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.projetor_reforma import (
    AnoTransicao,
    DocumentoFiscalExtraido,
    projetar_delta_reforma,
)
from core.orquestrador_societario import validar_combinacao
from core.sublimites_uf import sublimite_para_uf
from core.tabelas_simples import (
    DISTRIBUICAO_DAS,
    SUBLIMITE_ICMS_ISS,
    calcular_partilha_iss_cap,
    obter_faixa_numero,
)

_Q2 = Decimal("0.01")

NAO_QUANTIFICADO = "NAO_QUANTIFICADO"

# Rótulo obrigatório (parecer 12/07/2026): CBS/IBS projetado é débito
# BRUTO — regime regular é não-cumulativo pleno e o motor ainda não
# apropria créditos de insumos (campo reservado em PerfilEmpresa).
AVISO_DEBITO_BRUTO = (
    "DEBITO_BRUTO_SEM_CREDITOS: CBS/IBS projetados como débito bruto "
    "(receita × alíquota), SEM apropriação de créditos de insumos "
    "(LC 214/2025, Art. 47 — regime regular é não-cumulativo). "
    "A carga líquida real tende a ser menor conforme o volume de insumos "
    "creditáveis."
)

AVISO_RANKING_PARCIAL = (
    "RANKING_PARCIAL: comparação restrita ao perímetro federal + CBS/IBS. "
    "A decisão de migração exige análise complementar de folha (CPP) e "
    "estadual/municipal (ICMS/ISS), fora deste ranking."
)

AVISO_CSLL_BASE_IRPJ = (
    "LIMITACAO_WS6B1: CSLL do cenário Lucro Real calculada sobre a mesma "
    "base do IRPJ (LucroRealEngine não distingue base CSLL até WS6.b1)."
)


class PerfilEmpresa(BaseModel):
    """
    Parâmetros da empresa que a guia sozinha não carrega.

    Origem canônica: DadosExtraidosPDF (Claude Vision) — o extrator já
    devolve CNAE, UF, RBT12 e folha. Overrides manuais são permitidos
    (ex.: contador corrige o CNAE), sempre auditáveis.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cnae_principal: str
    uf_origem: str
    faturamento_12m: Decimal = Field(gt=Decimal("0"), description="RBT12 em R$.")
    razao_social: str = Field(default="EMPRESA ANALISADA", min_length=2)
    tipo_societario: Optional[str] = Field(
        default=None,
        description="Forma jurídica RFB (EI, SLU, LTDA, SS, SA, COOPERATIVA...).",
    )
    folha_salarios_12m: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description="Folha 12 meses — necessária pro Fator R (LC 123 Art. 18 § 24).",
    )
    lucro_real_mensal: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description="Lucro real MENSAL comprovado por DRE/balancete. Sem ele, "
                    "cenário Lucro Real sai NAO_AVALIADO (anti-chute, Rail R2).",
    )
    creditos_pis_cofins: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    insumos_creditaveis_mensal: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description="RESERVADO (v2): insumos creditáveis de CBS/IBS extraídos "
                    "de balancete (LC 214/2025 Art. 47). NÃO usado no cálculo v1.",
    )

    @classmethod
    def from_dados_extraidos_pdf(cls, dados: object, **overrides: Any) -> "PerfilEmpresa":
        """Monta o perfil a partir do payload do extrator (duck-typed)."""
        from core.projetor_reforma import _to_decimal

        folha_raw = getattr(dados, "folha_salarios_12m", None)
        base: Dict[str, Any] = {
            "cnae_principal": str(getattr(dados, "cnae_principal", "") or ""),
            "uf_origem": str(getattr(dados, "uf_origem", "") or ""),
            "faturamento_12m": _to_decimal(getattr(dados, "faturamento_12m", "0")),
            "razao_social": str(getattr(dados, "razao_social", "") or "EMPRESA ANALISADA"),
            "folha_salarios_12m": _to_decimal(folha_raw) if folha_raw not in (None, "") else None,
        }
        base.update(overrides)
        return cls(**base)


class CenarioFiscal(BaseModel):
    """Um cenário (manter ou migrar) com perímetro comparável e disclosure."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    regime: str
    origem_carga: Literal["GUIA_EXTRAIDA", "MOTOR_PROJETADO"]
    status: Literal["AVALIADO", "BLOQUEADO", "NAO_AVALIADO"]
    motivo: str = ""
    perimetro_comparavel_mensal: Optional[Decimal] = None
    breakdown_perimetro: Dict[str, Decimal] = Field(default_factory=dict)
    fora_do_perimetro: Dict[str, str] = Field(
        default_factory=dict,
        description="Tributo → valor conhecido (str Decimal) ou NAO_QUANTIFICADO.",
    )
    anexo_simples: Optional[str] = None
    fator_r: Optional[str] = None
    avisos: tuple[str, ...] = ()
    base_legal: tuple[str, ...] = ()


class ComparativoCenarios(BaseModel):
    """Resultado do comparador — ranking parcial auditável."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cnpj: str
    competencia: date
    ano_alvo: int
    regime_atual: str
    cenarios: tuple[CenarioFiscal, ...] = Field(
        description="AVALIADOS por perímetro crescente, depois NAO_AVALIADO/BLOQUEADO."
    )
    resultado: Literal["VENCEDOR_DEFINIDO", "INCONCLUSIVO", "SEM_COMPARACAO"]
    melhor_cenario_id: Optional[str] = None
    economia_mensal_vs_manter: Optional[Decimal] = None
    economia_anual_vs_manter: Optional[Decimal] = None
    piso_nao_comparado_mensal: Decimal = Decimal("0.00")
    alertas: tuple[Dict[str, str], ...] = ()
    trilha_auditoria: tuple[Dict[str, Any], ...] = ()
    base_legal: tuple[str, ...] = (
        "LC 123/2006, Art. 18, § 1º (alíquota efetiva do Simples)",
        "LC 214/2025, Arts. 344, 347, 348 (transição CBS/IBS)",
        "LC 214/2025, Art. 47 (não-cumulatividade — débito bruto)",
        "EC 132/2023 (Reforma Tributária)",
    )


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS INTERNOS
# ─────────────────────────────────────────────────────────────────────────────

def _passo_trilha(
    trilha: List[Dict[str, Any]],
    *,
    id: str,
    titulo: str,
    formula: str,
    memoria: Dict[str, str],
    amparo_legal: str,
) -> None:
    trilha.append({
        "tipo": "CALCULO",
        "id": id,
        "titulo": titulo,
        "formula": formula,
        "memoria": memoria,
        "amparo_legal": amparo_legal,
        "timestamp": datetime.now().isoformat(),
    })


def _fornecedora(perfil: PerfilEmpresa, cnpj: str, regime: str):
    """EmpresaFornecedora pro regime candidato (import tardio — evita ciclo)."""
    from core.motor_tributario import EmpresaFornecedora

    return EmpresaFornecedora(
        cnpj=cnpj,
        razao_social=perfil.razao_social,
        regime=regime,  # type: ignore[arg-type]
        cnae_principal=perfil.cnae_principal,
        uf_origem=perfil.uf_origem,
        faturamento_12m=perfil.faturamento_12m,
        folha_salarios_12m=perfil.folha_salarios_12m,
        tipo_societario=perfil.tipo_societario,  # type: ignore[arg-type]
    )


def _fator_r_calculado(perfil: PerfilEmpresa) -> Optional[Decimal]:
    if perfil.folha_salarios_12m is None or perfil.faturamento_12m <= 0:
        return None
    return (perfil.folha_salarios_12m / perfil.faturamento_12m).quantize(
        Decimal("0.0001"), ROUND_HALF_UP
    )


def _viabilidade(perfil: PerfilEmpresa, cnpj: str, regime: str, competencia: date):
    """Roda o orquestrador societário. Retorna (resultado|None, erro_validacao|None)."""
    try:
        fornecedora = _fornecedora(perfil, cnpj, regime)
    except ValidationError as e:
        return None, "; ".join(err["msg"] for err in e.errors()[:3])
    resultado = validar_combinacao(
        fornecedora=fornecedora,
        data_emissao=competencia,
        fator_r_calculado=_fator_r_calculado(perfil),
    )
    return resultado, None


def _cenario_bloqueado(id_: str, regime: str, validacao) -> CenarioFiscal:
    motivos = " | ".join(b.mensagem for b in validacao.bloqueios)
    base = tuple(b.base_legal for b in validacao.bloqueios if b.base_legal)
    return CenarioFiscal(
        id=id_,
        regime=regime,
        origem_carga="MOTOR_PROJETADO",
        status="BLOQUEADO",
        motivo=motivos or "Combinação societária inválida.",
        base_legal=base,
    )


def _perimetro_regime_normal(delta) -> tuple[Decimal, Dict[str, Decimal]]:
    """Perímetro comparável de PRESUMIDO/REAL a partir do DeltaReformaTributaria."""
    bk = delta.breakdown_projetado
    breakdown = {
        "IRPJ": bk["irpj_inalterado"],
        "CSLL": bk["csll_inalterada"],
        "PIS_RESIDUAL": bk["pis_residual"],
        "COFINS_RESIDUAL": bk["cofins_residual"],
        "CBS": bk["cbs"],
        "IBS": bk["ibs"],
    }
    total = sum(breakdown.values(), Decimal("0")).quantize(_Q2, ROUND_HALF_UP)
    return total, breakdown


# ─────────────────────────────────────────────────────────────────────────────
# CENÁRIOS
# ─────────────────────────────────────────────────────────────────────────────

def _cenario_manter(
    documento: DocumentoFiscalExtraido,
    ano_alvo: AnoTransicao,
    trilha: List[Dict[str, Any]],
) -> CenarioFiscal:
    """Baseline: carga extraída da guia (nunca recalculada), projetada no ano-alvo."""
    delta = projetar_delta_reforma(documento=documento, ano_alvo=ano_alvo)
    id_ = f"MANTER_{documento.regime_atual}"

    if documento.regime_atual in ("SIMPLES", "MEI"):
        # Parcelas federais da guia = partilha REAL paga (não estimada).
        # CPP excluída do perímetro (simetria — ver docstring do módulo).
        breakdown = {
            "IRPJ": documento.irpj_pago,
            "CSLL": documento.csll_paga,
            "PIS": documento.pis_pago,
            "COFINS": documento.cofins_paga,
        }
        perimetro = sum(breakdown.values(), Decimal("0")).quantize(_Q2, ROUND_HALF_UP)
        fora = {
            "ICMS": str(documento.icms_pago),
            "ISS": str(documento.iss_pago),
            "CPP_EXCLUIDA_DO_RANKING": str(documento.cpp_pago),
            "IPI": str(documento.ipi_pago),
        }
        avisos = tuple(delta.avisos)
        base_legal = delta.base_legal
        _passo_trilha(
            trilha,
            id=f"COMPARADOR_PERIMETRO_{id_}",
            titulo=f"Perímetro comparável — {id_} (guia extraída)",
            formula="IRPJ [{}] + CSLL [{}] + PIS [{}] + COFINS [{}] = {}".format(
                breakdown["IRPJ"], breakdown["CSLL"],
                breakdown["PIS"], breakdown["COFINS"], perimetro,
            ),
            memoria={k: str(v) for k, v in breakdown.items()},
            amparo_legal="LC 214/2025, Art. 41, §§ 1º e 2º + Art. 519 | LC 123/2006, Art. 13",
        )
    else:
        perimetro, breakdown = _perimetro_regime_normal(delta)
        bk = delta.breakdown_projetado
        fora = {
            "ICMS_RESIDUAL": str(bk["icms_residual"]),
            "ISS_RESIDUAL": str(bk["iss_residual"]),
            "CPP_EXCLUIDA_DO_RANKING": str(bk["cpp_inalterada"]),
            "IPI": str(bk["ipi_inalterado"]),
        }
        avisos = (AVISO_DEBITO_BRUTO,) if (bk["cbs"] + bk["ibs"]) > 0 else ()
        base_legal = delta.base_legal
        _passo_trilha(
            trilha,
            id=f"COMPARADOR_PERIMETRO_{id_}",
            titulo=f"Perímetro comparável — {id_} (guia extraída + projeção)",
            formula=(
                "IRPJ [{IRPJ}] + CSLL [{CSLL}] + PIS_res [{PIS_RESIDUAL}] + "
                "COFINS_res [{COFINS_RESIDUAL}] + CBS [{CBS}] + IBS [{IBS}] = {t}"
            ).format(**{k: str(v) for k, v in breakdown.items()}, t=perimetro),
            memoria={k: str(v) for k, v in breakdown.items()},
            amparo_legal="LC 214/2025, Arts. 344, 347, 348 | EC 132/2023, ADCT Art. 126, II",
        )

    return CenarioFiscal(
        id=id_,
        regime=documento.regime_atual,
        origem_carga="GUIA_EXTRAIDA",
        status="AVALIADO",
        perimetro_comparavel_mensal=perimetro,
        breakdown_perimetro=breakdown,
        fora_do_perimetro=fora,
        avisos=avisos,
        base_legal=base_legal,
    )


def _cenario_migrar_simples(
    documento: DocumentoFiscalExtraido,
    perfil: PerfilEmpresa,
    ano_alvo: AnoTransicao,
    trilha: List[Dict[str, Any]],
) -> CenarioFiscal:
    """Cenário Simples Nacional calculado pelo MOTOR (AE × RPA + partilha oficial)."""
    id_ = "MIGRAR_SIMPLES"
    validacao, erro = _viabilidade(perfil, documento.cnpj, "SIMPLES", documento.competencia)
    if erro is not None:
        return CenarioFiscal(
            id=id_, regime="SIMPLES", origem_carga="MOTOR_PROJETADO",
            status="NAO_AVALIADO", motivo=f"Dados insuficientes/ inválidos: {erro}",
        )
    if not validacao.valido:
        return _cenario_bloqueado(id_, "SIMPLES", validacao)

    # MAX_08: alíquota efetiva vem do MOTOR (LC 123 Art. 18 § 1º),
    # nunca de conta manual.
    from core.motor_tributario import (
        EmpresaCompradora,
        MotorReformaTributaria,
        OperacaoFiscal,
    )

    receita_mensal = documento.receita_bruta_mensal
    motor = MotorReformaTributaria(
        _fornecedora(perfil, documento.cnpj, "SIMPLES"),
        EmpresaCompradora(tipo="B2B_CONTRIBUINTE", uf_destino=perfil.uf_origem),
        OperacaoFiscal(
            data_emissao=documento.competencia,
            valor_operacao=receita_mensal if receita_mensal > 0 else Decimal("1"),
            ncm_nbs="00000000",
            rpa_mensal=receita_mensal,
        ),
    )
    ae = motor.aliquota_efetiva
    anexo = motor.anexo_principal
    fator_r = motor.fator_r
    faixa = obter_faixa_numero(perfil.faturamento_12m, anexo)
    if faixa == 0:
        return CenarioFiscal(
            id=id_, regime="SIMPLES", origem_carga="MOTOR_PROJETADO",
            status="BLOQUEADO",
            motivo=f"RBT12 R$ {perfil.faturamento_12m} acima do teto do Simples.",
            base_legal=("LC 123/2006, Art. 3º",),
        )

    das = (receita_mensal * ae).quantize(_Q2, ROUND_HALF_UP)
    # Partilha oficial com cap de 5% do ISS aplicado quando necessário
    # (LC 123/2006, Art. 18, § 5º-F — Anexos III/IV faixas altas).
    # NOTA: cada anexo só traz as chaves dos SEUS tributos (Anexo II não
    # tem ISS; III/IV/V não têm ICMS) — sempre .get() com default 0.
    partilha: Dict[str, Decimal] = calcular_partilha_iss_cap(anexo, faixa, ae)
    if not partilha:
        partilha = DISTRIBUICAO_DAS[anexo][faixa]

    def _parcela(tributo: str) -> Decimal:
        return (das * partilha.get(tributo, Decimal("0"))).quantize(
            _Q2, ROUND_HALF_UP,
        )

    fracao_perimetro = sum(
        (partilha.get(t, Decimal("0"))
         for t in ("IRPJ", "CSLL", "PIS", "COFINS", "IBS", "CBS")),
        Decimal("0"),
    )
    perimetro = (das * fracao_perimetro).quantize(_Q2, ROUND_HALF_UP)
    breakdown = {
        trib: _parcela(trib) for trib in ("IRPJ", "CSLL", "PIS", "COFINS")
    }
    icms_das = _parcela("ICMS")
    iss_das = _parcela("ISS")
    cpp_das = _parcela("CPP")
    ipi_das = _parcela("IPI")

    fora = {
        "ICMS": str(icms_das),
        "ISS": str(iss_das),
        "CPP_EXCLUIDA_DO_RANKING": str(cpp_das),
        "IPI": str(ipi_das),
    }
    # Sublimite ICMS/ISS: fonte versionada POR UF (Portarias CGSN —
    # core/sublimites_uf.py). Fallback documentado pra competência fora
    # das vigências firmadas: constante padrão LC 123 Art. 13-A.
    avisos: List[str] = []
    try:
        sublimite_uf = sublimite_para_uf(perfil.uf_origem, documento.competencia)
    except (KeyError, ValueError):
        sublimite_uf = SUBLIMITE_ICMS_ISS
        avisos.append(
            "SUBLIMITE_FALLBACK: sem vigência firmada de sublimite pra "
            "competência — usado padrão R$ 3,6M (LC 123/2006, Art. 13-A)."
        )
    # Acima do sublimite (faixa 6) ICMS/ISS saem do DAS — a partilha
    # oficial já traz ICMS/ISS = 0; o custo vira NÃO QUANTIFICADO
    # (mesma simetria dos regimes normais).
    if perfil.faturamento_12m > sublimite_uf:
        fora["ICMS"] = NAO_QUANTIFICADO
        fora["ISS"] = NAO_QUANTIFICADO
        avisos.append(
            "SUBLIMITE_ICMS_ISS: RBT12 acima de R$ 3,6M — ICMS/ISS recolhidos "
            "POR FORA do DAS (LC 123/2006, Arts. 13-A, 19, § 4º e 20, § 1º), "
            "não quantificados neste ranking."
        )
    if ano_alvo >= 2027:
        # ID distinto do AVISO_SIMPLES_APROXIMACAO do projetor (lá: total
        # do DAS mantido; aqui: partilha usada) — mensagens intencionais.
        avisos.append(
            "APROXIMACAO_PARTILHA_LC155: partilha LC 155/2016 usada como "
            "aproximação — Anexos XVIII-XXII da LC 214/2025 (Art. 519, "
            "CBS/IBS na partilha 2027+) pendentes de versionamento."
        )
    if fator_r is not None and Decimal("0.27") <= fator_r < Decimal("0.29"):
        avisos.append(
            "FATOR_R_ZONA_LIMITE: Fator R em zona de fronteira (0,27-0,29) — "
            "monitorar mensalmente o enquadramento de anexo "
            "(LC 123/2006, Art. 18, §§ 5º-J e 24)."
        )
    if perfil.folha_salarios_12m is None:
        avisos.append(
            "ANEXO_NAO_CONFIRMADO: folha_salarios_12m ausente — sem Fator R, "
            "anexo resolvido de forma conservadora. Informe a folha pra "
            "confirmar o enquadramento (LC 123/2006, Art. 18, §§ 5º-J e 24)."
        )

    _passo_trilha(
        trilha,
        id=f"COMPARADOR_PERIMETRO_{id_}",
        titulo="Perímetro comparável — MIGRAR_SIMPLES (motor)",
        formula=(
            f"DAS = RPA [{receita_mensal}] × AE [{ae}] = {das}; "
            f"Perímetro = DAS × fração federal+IVA da partilha "
            f"[{fracao_perimetro}] = {perimetro}"
        ),
        memoria={
            "anexo": anexo, "faixa": str(faixa), "aliquota_efetiva": str(ae),
            "das_mensal": str(das), "fator_r": str(fator_r),
            **{k: str(v) for k, v in breakdown.items()},
        },
        amparo_legal="LC 123/2006, Art. 18, § 1º | LC 155/2016 (partilha)",
    )

    return CenarioFiscal(
        id=id_,
        regime="SIMPLES",
        origem_carga="MOTOR_PROJETADO",
        status="AVALIADO",
        perimetro_comparavel_mensal=perimetro,
        breakdown_perimetro=breakdown,
        fora_do_perimetro=fora,
        anexo_simples=anexo,
        fator_r=str(fator_r) if fator_r is not None else None,
        avisos=tuple(avisos),
        base_legal=(
            "LC 123/2006, Art. 18, § 1º (alíquota efetiva)",
            "LC 214/2025, Art. 41, §§ 1º e 2º (regime unificado mantido)",
        ),
    )


def _cenario_migrar_normal(
    documento: DocumentoFiscalExtraido,
    perfil: PerfilEmpresa,
    ano_alvo: AnoTransicao,
    regime: Literal["PRESUMIDO", "REAL"],
    trilha: List[Dict[str, Any]],
) -> CenarioFiscal:
    """Cenário Presumido/Real: engine → documento sintético → projetor."""
    id_ = f"MIGRAR_{regime}"

    if regime == "REAL" and perfil.lucro_real_mensal is None:
        return CenarioFiscal(
            id=id_, regime=regime, origem_carga="MOTOR_PROJETADO",
            status="NAO_AVALIADO",
            motivo=(
                "Ausência de documentação contábil comprobatória (DRE/"
                "balancete) para atestar o lucro real. Cenário não estimado "
                "— rigor anti-chute (Rail R2)."
            ),
        )

    validacao, erro = _viabilidade(perfil, documento.cnpj, regime, documento.competencia)
    if erro is not None:
        return CenarioFiscal(
            id=id_, regime=regime, origem_carga="MOTOR_PROJETADO",
            status="NAO_AVALIADO", motivo=f"Dados insuficientes/ inválidos: {erro}",
        )
    if not validacao.valido:
        return _cenario_bloqueado(id_, regime, validacao)

    receita_mensal = documento.receita_bruta_mensal
    trilha_engine: List[Dict[str, Any]] = []
    avisos: List[str] = [AVISO_DEBITO_BRUTO]

    if regime == "PRESUMIDO":
        from core.regimes.lucro_presumido import LucroPresumidoEngine

        engine = LucroPresumidoEngine(
            _fornecedora(perfil, documento.cnpj, "PRESUMIDO"), trilha_engine
        )
        resultado = engine.calcular_carga_total_mensal(receita_mensal)
        irpj = resultado["breakdown"]["IRPJ"]
        base_legal = (
            "Lei 9.249/1995, Arts. 15 e 20 (presunção IRPJ/CSLL)",
            "Lei 9.718/1998, Art. 2º (PIS/COFINS cumulativo)",
        )
    else:
        from core.regimes.lucro_real import LucroRealEngine

        engine = LucroRealEngine(
            _fornecedora(perfil, documento.cnpj, "REAL"), trilha_engine
        )
        resultado = engine.calcular_carga_total_mensal(
            receita_mensal=receita_mensal,
            lucro_real_mensal=perfil.lucro_real_mensal,
            creditos_pis_cofins=perfil.creditos_pis_cofins,
        )
        irpj = (
            resultado["breakdown"]["IRPJ"] + resultado["breakdown"]["IRPJ_ADICIONAL"]
        ).quantize(_Q2, ROUND_HALF_UP)
        avisos.append(AVISO_CSLL_BASE_IRPJ)
        base_legal = (
            "Lei 9.430/1996, Arts. 25 e 29 (IRPJ/CSLL apuração)",
            "Lei 10.637/2002 e Lei 10.833/2003 (PIS/COFINS não-cumulativo)",
        )

    trilha.extend(trilha_engine)

    # Documento SINTÉTICO — inputs hipotéticos que o motor calculou (MAX_08),
    # rotulados como tal (fonte ≠ guia) e projetados pelo MESMO projetor.
    doc_sintetico = DocumentoFiscalExtraido(
        cnpj=documento.cnpj,
        competencia=documento.competencia,
        regime_atual=regime,
        receita_bruta_mensal=receita_mensal,
        irpj_pago=irpj,
        csll_paga=resultado["breakdown"]["CSLL"],
        pis_pago=resultado["breakdown"]["PIS"],
        cofins_paga=resultado["breakdown"]["COFINS"],
        documento_origem_hash=documento.documento_origem_hash,
        fonte_extracao="motor_projetado",
    )
    delta = projetar_delta_reforma(documento=doc_sintetico, ano_alvo=ano_alvo)
    perimetro, breakdown = _perimetro_regime_normal(delta)

    fora = {
        "ICMS": NAO_QUANTIFICADO,
        "ISS": NAO_QUANTIFICADO,
        "CPP_EXCLUIDA_DO_RANKING": (
            NAO_QUANTIFICADO
            if perfil.folha_salarios_12m is None
            else f"{NAO_QUANTIFICADO} (folha 12m de referência: "
                 f"R$ {perfil.folha_salarios_12m})"
        ),
        "IPI": NAO_QUANTIFICADO,
    }

    _passo_trilha(
        trilha,
        id=f"COMPARADOR_PERIMETRO_{id_}",
        titulo=f"Perímetro comparável — {id_} (engine + projetor)",
        formula=(
            "IRPJ [{IRPJ}] + CSLL [{CSLL}] + PIS_res [{PIS_RESIDUAL}] + "
            "COFINS_res [{COFINS_RESIDUAL}] + CBS [{CBS}] + IBS [{IBS}] = {t}"
        ).format(**{k: str(v) for k, v in breakdown.items()}, t=perimetro),
        memoria={k: str(v) for k, v in breakdown.items()},
        amparo_legal=" | ".join(base_legal)
        + " | LC 214/2025, Arts. 344, 347, 348",
    )

    return CenarioFiscal(
        id=id_,
        regime=regime,
        origem_carga="MOTOR_PROJETADO",
        status="AVALIADO",
        perimetro_comparavel_mensal=perimetro,
        breakdown_perimetro=breakdown,
        fora_do_perimetro=fora,
        avisos=tuple(avisos),
        base_legal=base_legal + ("LC 214/2025, Arts. 344, 347, 348",),
    )


# ─────────────────────────────────────────────────────────────────────────────
# GUARDA ANTI-FALSO-VENCEDOR + RANKING
# ─────────────────────────────────────────────────────────────────────────────

def _piso_nao_comparado(a: CenarioFiscal, b: CenarioFiscal) -> Decimal:
    """
    Piso conhecido do custo não comparado quando a comparação cruza
    Simples/MEI ↔ regime normal: fração ICMS+ISS do DAS do lado Simples.
    Comparações inteiramente dentro da família normal (Presumido × Real)
    têm o buraco simétrico dos dois lados → piso 0.
    """
    piso = Decimal("0")
    for cen in (a, b):
        if cen.regime in ("SIMPLES", "MEI"):
            for chave in ("ICMS", "ISS", "ICMS_RESIDUAL", "ISS_RESIDUAL"):
                valor = cen.fora_do_perimetro.get(chave)
                if valor is not None and valor != NAO_QUANTIFICADO:
                    piso += Decimal(valor)
    return piso.quantize(_Q2, ROUND_HALF_UP)


def comparar_cenarios(
    *,
    documento: DocumentoFiscalExtraido,
    perfil: PerfilEmpresa,
    ano_alvo: AnoTransicao,
) -> ComparativoCenarios:
    """
    Compara cenários fiscais e ranqueia no perímetro comparável.

    Args:
        documento: guia extraída (carga REAL — nunca recalculada).
        perfil: parâmetros da empresa (CNAE, tipo societário, RBT12, folha,
            DRE opcional).
        ano_alvo: ano da transição (2026-2033).

    Returns:
        ComparativoCenarios frozen — ranking parcial auditável, com guarda
        INCONCLUSIVO e alertas não supressíveis.
    """
    trilha: List[Dict[str, Any]] = []
    alertas: List[Dict[str, str]] = []

    manter = _cenario_manter(documento, ano_alvo, trilha)
    cenarios: List[CenarioFiscal] = [manter]

    if documento.regime_atual != "SIMPLES":
        cenarios.append(_cenario_migrar_simples(documento, perfil, ano_alvo, trilha))
    if documento.regime_atual != "PRESUMIDO":
        cenarios.append(
            _cenario_migrar_normal(documento, perfil, ano_alvo, "PRESUMIDO", trilha)
        )
    if documento.regime_atual != "REAL":
        cenarios.append(
            _cenario_migrar_normal(documento, perfil, ano_alvo, "REAL", trilha)
        )

    avaliados = sorted(
        (c for c in cenarios if c.status == "AVALIADO"),
        key=lambda c: c.perimetro_comparavel_mensal,
    )
    demais = [c for c in cenarios if c.status != "AVALIADO"]
    ordenados = tuple(avaliados + demais)

    # ── Alertas não supressíveis (parecer 12/07/2026) ────────────────────
    # RANKING_PARCIAL é incondicional: CPP/ICMS/ISS ficam fora do ranking
    # em TODA comparação, não só quando há cenário Simples.
    alertas.append({
        "id": "ALERTA_RANKING_PARCIAL",
        "titulo": "Ranking parcial — perímetro federal + CBS/IBS",
        "detalhe": AVISO_RANKING_PARCIAL,
        "amparo_legal": "LC 123/2006, Art. 18, § 5º-C | Rail R2",
    })
    if any(AVISO_DEBITO_BRUTO in c.avisos for c in cenarios):
        alertas.append({
            "id": "ALERTA_DEBITO_BRUTO_SEM_CREDITOS",
            "titulo": "CBS/IBS projetados como débito bruto",
            "detalhe": AVISO_DEBITO_BRUTO,
            "amparo_legal": "LC 214/2025, Art. 47",
        })
    if documento.ipi_pago > 0 and ano_alvo >= 2027:
        alertas.append({
            "id": "ALERTA_IPI_POS_2027",
            "titulo": "IPI mantido integral (modelagem conservadora)",
            "detalhe": (
                "A partir de 2027 o IPI tem alíquotas reduzidas a zero, "
                "exceto produtos com industrialização incentivada na Zona "
                "Franca de Manaus. O comparador mantém o IPI integral "
                "(conservador) até a parametrização ZFM."
            ),
            "amparo_legal": "ADCT, Art. 126, III, 'a' (EC 132/2023)",
        })

    # ── Ranking + guarda ─────────────────────────────────────────────────
    piso = Decimal("0.00")
    if len(avaliados) < 2:
        resultado = "SEM_COMPARACAO"
        melhor_id = avaliados[0].id if avaliados else None
        economia_mensal = None
    else:
        melhor = avaliados[0]
        delta_vs_manter = (
            manter.perimetro_comparavel_mensal - melhor.perimetro_comparavel_mensal
        ).quantize(_Q2, ROUND_HALF_UP)
        # Piso só faz sentido quando há troca de regime na comparação —
        # manter vencedor = sem migração, guarda inaplicável.
        piso = (
            _piso_nao_comparado(manter, melhor)
            if melhor.id != manter.id
            else Decimal("0.00")
        )

        if melhor.id != manter.id and abs(delta_vs_manter) < piso:
            resultado = "INCONCLUSIVO"
            melhor_id = None
            economia_mensal = None
            alertas.append({
                "id": "ALERTA_RANKING_INCONCLUSIVO",
                "titulo": "Ranking inconclusivo — diferença menor que o custo não comparado",
                "detalhe": (
                    f"Diferença no perímetro comparável (R$ {abs(delta_vs_manter)}/mês) "
                    f"é MENOR que o piso conhecido do custo fora do ranking "
                    f"(ICMS+ISS do DAS: R$ {piso}/mês). Proibido declarar "
                    f"vencedor — a decisão está exatamente na parte não "
                    f"comparável (folha, ICMS/ISS estadual/municipal)."
                ),
                "amparo_legal": "Rail R2 (proibição de extrapolação) | parecer 12/07/2026",
            })
        else:
            resultado = "VENCEDOR_DEFINIDO"
            melhor_id = melhor.id
            economia_mensal = max(delta_vs_manter, Decimal("0.00"))

    _passo_trilha(
        trilha,
        id="COMPARADOR_RANKING",
        titulo="Ranking de cenários no perímetro comparável",
        formula=(
            "ordenar(avaliados, perímetro asc); "
            "INCONCLUSIVO se |Δ vs manter| < piso ICMS+ISS do DAS"
        ),
        memoria={
            "resultado": resultado,
            "melhor_cenario": str(melhor_id),
            "piso_nao_comparado": str(piso),
            "avaliados": ", ".join(
                f"{c.id}={c.perimetro_comparavel_mensal}" for c in avaliados
            ),
        },
        amparo_legal="LC 123/2006, Art. 18, § 1º | LC 214/2025, Arts. 344-348",
    )

    return ComparativoCenarios(
        cnpj=documento.cnpj,
        competencia=documento.competencia,
        ano_alvo=ano_alvo,
        regime_atual=documento.regime_atual,
        cenarios=ordenados,
        resultado=resultado,
        melhor_cenario_id=melhor_id,
        economia_mensal_vs_manter=economia_mensal,
        economia_anual_vs_manter=(
            (economia_mensal * 12).quantize(_Q2, ROUND_HALF_UP)
            if economia_mensal is not None
            else None
        ),
        piso_nao_comparado_mensal=piso,
        alertas=tuple(alertas),
        trilha_auditoria=tuple(trilha),
    )
