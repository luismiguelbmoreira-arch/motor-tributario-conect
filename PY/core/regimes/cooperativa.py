# -*- coding: utf-8 -*-
"""
regimes/cooperativa.py — Overlay COOPERATIVA (LC 214/2025 Art. 271 + Lei 5.764/71)
Projeto: Motor Tributário Conect 2026-2033 — WS6 Etapa 5a

ARQUITETURA:
  Cooperativa NÃO é regime tributário — é tipo societário com regime próprio
  de ato cooperativo que SOBREPÕE (overlay) o engine regular do regime
  tributário declarado (SIMPLES/PRESUMIDO/REAL). Por isso esta classe
  NÃO HERDA BaseRegimeEngine — é decorator/overlay que recebe o resultado
  do engine regular e modula.

  fornecedora.regime: SIMPLES|PRESUMIDO|REAL  (apuração regular)
  fornecedora.tipo_societario: "COOPERATIVA"   (dispara overlay)
  fornecedora.subtipo_cooperativa: ramo OCB    (CONSUMO/TRABALHO/...)

  Motor:
    1. roda engine regular (LucroPresumidoEngine, LucroRealEngine, etc.)
    2. se tipo_societario=="COOPERATIVA", instancia CooperativaOverlay
    3. overlay.aplicar(resultado_engine_regular, data_emissao=...) ⇒ resultado_ajustado

ESCOPO 5a — RAMOS COBERTOS:
  - CONSUMO       (LC 123/2006 Art. 3º § 1º — exceção do Simples)
  - TRABALHO      (vedação LC 123 Art. 3º § 4º VI no Simples)
  - PRODUCAO      (idem)
  - AGROPECUARIA  (idem + Art. 271 § 1º II — anulação proporcional crédito)
  - TRANSPORTE    (idem + Art. 169 § 8º — crédito presumido)

ESCOPO 5b (não implementado): CREDITO, SAUDE.

DUAS HIPÓTESES TRIBUTÁRIAS COEXISTEM (não confundir):
  - Art. 271 LC 214: opt-in, alíquota zero (TEM fato gerador, opta zerar)
  - Art. 6º VI/X/XI LC 214: fora de incidência SEMPRE (NÃO há fato gerador)

BASE LEGAL (validada por Escrivão 2026-05-08 contra cache local):
  - LC 214/2025 Art. 6º VI/X/XI         — fora de incidência
  - LC 214/2025 Art. 169 § 8º           — crédito presumido coop transporte
  - LC 214/2025 Art. 271 caput + I, II  — opção alíquota zero IBS/CBS
  - LC 214/2025 Art. 271 § 1º II + § 4º — anulação proporcional crédito coop
                                          agropecuária com associado não-contribuinte
                                          (§ 4º exceção: insumos com diferimento Art. 138 § 3º)
  - LC 214/2025 Art. 271 § 3º           — opção produz efeitos no ano subsequente (Rail R8)
  - LC 214/2025 Art. 272                — transferência créditos sem aplicar Art. 55
  - LC 123/2006 Art. 3º § 4º VI + § 1º  — vedação Simples salvo cooperativa de consumo
  - Lei 5.764/71 Art. 4º                — sociedades de pessoas, prestam serviços aos
                                          associados (características I-XI)
  - Lei 5.764/71 Art. 5º caput          — qualquer gênero de serviço/operação/atividade
  - Lei 5.764/71 Art. 10 caput + § 1º   — classificação por objeto, modalidades via
                                          órgão controlador (OCB/CGSN — não taxativo)
  - Lei 5.764/71 Art. 28                — Reserva 10% + FATES 5% das sobras líquidas
  - Lei 5.764/71 Art. 79                — definição canônica de ato cooperativo
  - Lei 5.764/71 Art. 87 (caput)        — segregação contábil (NÃO citar como
                                          "§ único" — parágrafo único INEXISTENTE)
  - Lei 5.764/71 Art. 111               — regra de incidência sobre ato não-cooperativo
                                          (resultados das operações dos Arts. 85/86/88)
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List

logger = logging.getLogger("motor_conect.regimes.cooperativa")


# ─────────────────────────────────────────────────────────────────────────────
# CITAÇÕES CANÔNICAS (FROZEN — validadas Escrivão 2026-05-08)
# ─────────────────────────────────────────────────────────────────────────────

AMPARO_ATO_COOPERATIVO: str = (
    "Lei 5.764/71 Art. 79 (definição canônica — ato cooperativo entre "
    "cooperativa e seus associados, ou entre cooperativas; § único: "
    "ato cooperativo não implica operação de mercado)"
)

AMPARO_FORA_INCIDENCIA_ART6: str = (
    "LC 214/2025 Art. 6º VI (juros e remuneração ao capital de cooperados) | "
    "Art. 6º X (destinação a fundos — remete a Lei 5.764/71 Art. 28) | "
    "Art. 6º XI (repasse a associados + sobras)"
)

AMPARO_ART271_ALIQUOTA_ZERO: str = (
    "LC 214/2025 Art. 271 caput + I + II (opção pela alíquota zero IBS/CBS "
    "sobre receita de ato cooperativo)"
)

AMPARO_ART271_JANELA: str = (
    "LC 214/2025 Art. 271 § 3º (opção produz efeitos no ano-calendário "
    "subsequente — Rail R8 consistência temporal)"
)

AMPARO_ART271_AGROPECUARIA_ANULACAO: str = (
    "LC 214/2025 Art. 271 § 1º II (cooperativa agropecuária com associado "
    "não-contribuinte — anulação proporcional do crédito do bem fornecido) "
    "+ § 4º (exceção: insumos agropecuários com diferimento Art. 138 § 3º "
    "— anulação NÃO se aplica)"
)

AMPARO_TRANSPORTE_CREDITO_PRESUMIDO: str = (
    "LC 214/2025 Art. 169 § 8º (crédito presumido para cooperativa de transporte)"
)

AMPARO_SEGREGACAO_CONTABIL: str = (
    "Lei 5.764/71 Art. 87 (caput, texto único — operações com não associados "
    "contabilizadas em separado, de molde a permitir cálculo para incidência "
    "de tributos)"
)

AMPARO_ATO_NAO_COOPERATIVO: str = (
    "Lei 5.764/71 Art. 111 (resultados positivos das operações dos Arts. 85, "
    "86 e 88 — renda tributável); Lei 5.764/71 Arts. 85, 86 e 88 (operações "
    "com não associados)"
)

AMPARO_CLASSIFICACAO_RAMO: str = (
    "Lei 5.764/71 Art. 10 caput + § 1º (classificação por objeto/natureza; "
    "modalidades caracterizadas pelo órgão controlador — OCB/CGSN; ramos "
    "NÃO são enumeração legal taxativa)"
)

AMPARO_VEDACAO_SIMPLES: str = (
    "LC 123/2006 Art. 3º § 4º VI (vedação geral) + Art. 3º § 1º (exceção "
    "cooperativa de consumo)"
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — timestamp ISO (isolado para facilitar mock em testes)
# ─────────────────────────────────────────────────────────────────────────────

def agora_str() -> str:
    """Wrapper pra timestamp ISO; isolado para facilitar mock em testes."""
    return str(datetime.now())


# ─────────────────────────────────────────────────────────────────────────────
# JANELA TEMPORAL — Rail R8 (consistência temporal)
# ─────────────────────────────────────────────────────────────────────────────

def _janela_art271_valida(data_opcao: date | None, data_emissao: date) -> bool:
    """
    LC 214/2025 Art. 271 § 3º — a opção produz efeitos no ano-calendário
    subsequente. Operação só é amparada quando data_opcao.year < data_emissao.year.
    """
    if data_opcao is None:
        return False
    return data_opcao.year < data_emissao.year


# ─────────────────────────────────────────────────────────────────────────────
# OVERLAY — não herda BaseRegimeEngine
# ─────────────────────────────────────────────────────────────────────────────

class CooperativaOverlay:
    """
    Overlay tributário de cooperativa. Sobrepõe o resultado do engine regular
    aplicando regras específicas da Lei 5.764/71 + LC 214/2025 Art. 271.

    Não substitui o engine regular — modula seu output.

    Uso esperado pelo orquestrador:
        engine = LucroPresumidoEngine(fornecedora, trilha)
        resultado = engine.calcular_carga_total_mensal()
        if fornecedora.tipo_societario == "COOPERATIVA":
            overlay = CooperativaOverlay(fornecedora, trilha)
            resultado = overlay.aplicar(resultado, data_emissao=operacao.data_emissao)
    """

    def __init__(self, fornecedora: Any, trilha: List[Dict[str, Any]]) -> None:
        if getattr(fornecedora, "tipo_societario", None) != "COOPERATIVA":
            raise ValueError(
                f"CooperativaOverlay aceita apenas tipo_societario='COOPERATIVA'. "
                f"Recebido: {getattr(fornecedora, 'tipo_societario', None)!r}."
            )
        self.fornecedora = fornecedora
        self.trilha = trilha

        logger.info(
            "CooperativaOverlay iniciado | ramo=%s | regime=%s | optante_271=%s",
            getattr(fornecedora, "subtipo_cooperativa", None),
            getattr(fornecedora, "regime", None),
            getattr(fornecedora, "optante_art271_cbs_ibs", False),
        )

    # ── Helpers de trilha ───────────────────────────────────────────────────

    def _registrar(
        self,
        *,
        tipo: str,
        id: str,
        titulo: str,
        amparo: str,
        memoria: Dict[str, Any] | None = None,
        detalhe: str = "",
        formula: str = "",
    ) -> None:
        self.trilha.append({
            "tipo": tipo,
            "id": id,
            "titulo": titulo,
            "formula": formula,
            "memoria": {k: str(v) for k, v in (memoria or {}).items()},
            "amparo_legal": amparo,
            "detalhe": detalhe,
            "timestamp": agora_str(),
        })

    # ── API pública ─────────────────────────────────────────────────────────

    def aplicar(
        self,
        resultado_engine_regular: Dict[str, Any],
        *,
        data_emissao: date,
    ) -> Dict[str, Any]:
        """
        Aplica overlay sobre o resultado do engine regular.

        Regras:
          1. Split de IBS/CBS proporcional entre ato cooperativo e ato
             não-cooperativo (segregação contábil — Lei 5.764/71 Art. 87 caput).
          2. Fora-de-incidência Art. 6º VI/X/XI — alerta SEMPRE registrado
             (independe de opt-in).
          3. Se optante_art271 + janela § 3º válida: zera IBS/CBS sobre
             ato cooperativo.
          4. AGROPECUARIA + opt-in: alerta de anulação proporcional do
             crédito (Art. 271 § 1º II); operador decide aplicar.
          5. TRANSPORTE: alerta de crédito presumido (Art. 169 § 8º);
             cálculo automático fica para etapa subsequente (sem fonte
             firme da alíquota presumida no caput do § 8º — Rail R2).

        Args:
            resultado_engine_regular: dict com pelo menos ibs_total, cbs_total,
                base_calculo (output típico dos LucroPresumidoEngine, etc.)
            data_emissao: data da operação fiscal (define janela § 3º).

        Returns:
            Dict com breakdown completo da cooperativa, agregando o resultado
            do engine regular como referência.
        """
        ramo = self.fornecedora.subtipo_cooperativa
        optante = bool(getattr(self.fornecedora, "optante_art271_cbs_ibs", False))
        data_opcao = getattr(self.fornecedora, "data_opcao_art271", None)
        janela_ok = _janela_art271_valida(data_opcao, data_emissao)

        receita_coop = Decimal(str(self.fornecedora.receita_ato_cooperativo))
        receita_nao_coop = Decimal(str(self.fornecedora.receita_ato_nao_cooperativo))
        receita_total = receita_coop + receita_nao_coop

        ibs_total_engine = Decimal(str(resultado_engine_regular.get("ibs_total", "0")))
        cbs_total_engine = Decimal(str(resultado_engine_regular.get("cbs_total", "0")))

        # 1. Split proporcional por receita (segregação Art. 87 caput)
        if receita_total > 0:
            proporcao_coop = receita_coop / receita_total
            proporcao_nao_coop = receita_nao_coop / receita_total
        else:
            # Pydantic já barra esse caso, mas defensivo
            proporcao_coop = Decimal("0")
            proporcao_nao_coop = Decimal("0")

        ibs_coop_inicial = (ibs_total_engine * proporcao_coop).quantize(Decimal("0.01"))
        cbs_coop_inicial = (cbs_total_engine * proporcao_coop).quantize(Decimal("0.01"))
        ibs_nao_coop = (ibs_total_engine * proporcao_nao_coop).quantize(Decimal("0.01"))
        cbs_nao_coop = (cbs_total_engine * proporcao_nao_coop).quantize(Decimal("0.01"))

        # 1.bis SEGREGAÇÃO contábil (Lei 5.764/71 Art. 87 caput + Art. 79) — SEMPRE
        self._registrar(
            tipo="CALCULO",
            id="COOPERATIVA_SEGREGACAO_RECEITAS",
            titulo="Segregação receita ato cooperativo × ato não-cooperativo",
            amparo=f"{AMPARO_SEGREGACAO_CONTABIL} | {AMPARO_ATO_COOPERATIVO} | {AMPARO_ATO_NAO_COOPERATIVO}",
            formula=(
                f"Receita coop [{receita_coop}] / Receita total [{receita_total}] "
                f"= proporção {proporcao_coop}"
            ),
            memoria={
                "ramo": ramo,
                "receita_ato_cooperativo": receita_coop,
                "receita_ato_nao_cooperativo": receita_nao_coop,
                "proporcao_ato_cooperativo": proporcao_coop,
                "ibs_engine_total": ibs_total_engine,
                "cbs_engine_total": cbs_total_engine,
                "ibs_split_coop": ibs_coop_inicial,
                "cbs_split_coop": cbs_coop_inicial,
                "ibs_split_nao_coop": ibs_nao_coop,
                "cbs_split_nao_coop": cbs_nao_coop,
            },
            detalhe=(
                "Lei 5.764/71 Art. 87 caput exige contabilização em separado das "
                "operações com não associados, de molde a permitir cálculo para "
                "incidência de tributos. Ato cooperativo definido em Art. 79; "
                "ato não-cooperativo regrado pelos Arts. 85/86/88 + 111."
            ),
        )

        # 2. ALERTA de fora-de-incidência (Art. 6º VI/X/XI) — SEMPRE
        self._registrar(
            tipo="ALERTA_COOPERATIVA",
            id="ALERTA_COOPERATIVA_FORA_INCIDENCIA_ART6",
            titulo="Cooperativa — operações fora da incidência IBS/CBS",
            amparo=AMPARO_FORA_INCIDENCIA_ART6,
            detalhe=(
                "Juros ao capital, destinação a fundos cooperativos (Lei 5.764/71 "
                "Art. 28 — Reserva 10% + FATES 5%), repasse aos associados e "
                "sobras NÃO compõem a base de cálculo IBS/CBS por estarem fora "
                "do campo de incidência (Art. 6º VI/X/XI LC 214/2025). Distinto "
                "da alíquota zero do Art. 271 — que pressupõe fato gerador."
            ),
            memoria={
                "ramo": ramo,
                "fonte_classificacao": AMPARO_CLASSIFICACAO_RAMO,
            },
        )

        # 3. Opt-in Art. 271
        if optante:
            if janela_ok:
                # Zera IBS/CBS sobre ato cooperativo
                ibs_coop_final = Decimal("0.00")
                cbs_coop_final = Decimal("0.00")
                self._registrar(
                    tipo="AJUSTE_COOPERATIVA",
                    id="AJUSTE_COOPERATIVA_ART271_ALIQUOTA_ZERO",
                    titulo="Ajuste — Alíquota zero IBS/CBS sobre ato cooperativo",
                    amparo=f"{AMPARO_ART271_ALIQUOTA_ZERO} + {AMPARO_ART271_JANELA} + {AMPARO_ATO_COOPERATIVO}",
                    formula=(
                        f"IBS [{ibs_coop_inicial}] + CBS [{cbs_coop_inicial}] "
                        f"× alíquota zero (Art. 271) = R$ 0,00"
                    ),
                    memoria={
                        "receita_ato_cooperativo": receita_coop,
                        "ibs_antes": ibs_coop_inicial,
                        "cbs_antes": cbs_coop_inicial,
                        "ibs_depois": Decimal("0.00"),
                        "cbs_depois": Decimal("0.00"),
                        "data_opcao": data_opcao,
                        "data_emissao": data_emissao,
                    },
                )
            else:
                # Fora da janela § 3º — opt-in não produz efeitos nesta operação
                ibs_coop_final = ibs_coop_inicial
                cbs_coop_final = cbs_coop_inicial
                self._registrar(
                    tipo="ALERTA_COOPERATIVA",
                    id="ALERTA_COOPERATIVA_ART271_FORA_DE_JANELA",
                    titulo="Opção pelo Art. 271 fora da janela § 3º",
                    amparo=AMPARO_ART271_JANELA,
                    detalhe=(
                        f"Opção declarada em {data_opcao} produz efeitos só no "
                        f"ano-calendário subsequente. Operação em {data_emissao} "
                        f"permanece tributada pelo regime regular sobre ato "
                        f"cooperativo. Para próximo ano-calendário, a opção "
                        f"vigente passa a zerar IBS/CBS."
                    ),
                    memoria={
                        "data_opcao": data_opcao,
                        "data_emissao": data_emissao,
                    },
                )
        else:
            # Não optante — ato cooperativo permanece tributado pelo regime regular.
            # Mesmo sem opt-in, a fração de ato cooperativo continua passível de
            # tributação pelo engine regular (Art. 6º trata de hipóteses de
            # fora-de-incidência distintas — fundos, sobras, juros — não a receita
            # toda do ato cooperativo).
            ibs_coop_final = ibs_coop_inicial
            cbs_coop_final = cbs_coop_inicial

        # 4. AGROPECUARIA + opt-in → alerta anulação Art. 271 § 1º II
        if ramo == "AGROPECUARIA" and optante and janela_ok:
            self._registrar(
                tipo="ALERTA_COOPERATIVA",
                id="ALERTA_COOPERATIVA_AGROPECUARIA_ANULACAO_CREDITO",
                titulo="Cooperativa agropecuária — anulação proporcional de crédito",
                amparo=AMPARO_ART271_AGROPECUARIA_ANULACAO,
                detalhe=(
                    "Quando associado não-contribuinte (produtor rural pessoa "
                    "física, p. ex.) fornece bem à cooperativa, o crédito do "
                    "bem deve ser anulado proporcionalmente (Art. 271 § 1º II). "
                    "Exceção (§ 4º): insumos agropecuários com diferimento do "
                    "Art. 138 § 3º — anulação NÃO se aplica. Operador deve "
                    "verificar a condição contábil do associado e a natureza "
                    "do insumo antes de aplicar o crédito."
                ),
                memoria={"ramo": ramo, "optante": True},
            )

        # 5. TRANSPORTE → alerta crédito presumido Art. 169 § 8º
        if ramo == "TRANSPORTE":
            self._registrar(
                tipo="ALERTA_COOPERATIVA",
                id="ALERTA_COOPERATIVA_TRANSPORTE_CREDITO_PRESUMIDO",
                titulo="Cooperativa de transporte — crédito presumido",
                amparo=AMPARO_TRANSPORTE_CREDITO_PRESUMIDO,
                detalhe=(
                    "Cooperativa de transporte tem direito a crédito presumido "
                    "do § 8º do Art. 169. Cálculo automático fica para etapa "
                    "posterior (a alíquota presumida depende de regulamento "
                    "específico — Rail R2: sem fonte firme não vira código)."
                ),
                memoria={"ramo": ramo},
            )

        # ── Breakdown final ────────────────────────────────────────────────
        total_iva_ajustado = (
            ibs_coop_final + cbs_coop_final + ibs_nao_coop + cbs_nao_coop
        ).quantize(Decimal("0.01"))

        return {
            # Identidade
            "tipo_societario": "COOPERATIVA",
            "subtipo_cooperativa": ramo,
            "regime": resultado_engine_regular.get("regime", self.fornecedora.regime),
            "optante_art271_cbs_ibs": optante,
            "art271_janela_valida": janela_ok,
            # Split de receita (Lei 5.764/71 Art. 87 caput)
            "receita_ato_cooperativo": receita_coop,
            "receita_ato_nao_cooperativo": receita_nao_coop,
            "proporcao_ato_cooperativo": proporcao_coop,
            # IBS/CBS por componente
            "ibs_ato_cooperativo": ibs_coop_final,
            "cbs_ato_cooperativo": cbs_coop_final,
            "ibs_ato_nao_cooperativo": ibs_nao_coop,
            "cbs_ato_nao_cooperativo": cbs_nao_coop,
            "total_iva_ajustado": total_iva_ajustado,
            # Engine regular preservado para auditoria comparativa
            "resultado_engine_regular": resultado_engine_regular,
            # Citações canônicas (Lei 5.764/71 + LC 214/2025)
            "base_legal_aplicavel": (
                AMPARO_CLASSIFICACAO_RAMO,
                AMPARO_ATO_COOPERATIVO,
                AMPARO_ATO_NAO_COOPERATIVO,
                AMPARO_SEGREGACAO_CONTABIL,
                AMPARO_FORA_INCIDENCIA_ART6,
                AMPARO_ART271_ALIQUOTA_ZERO,
                AMPARO_ART271_JANELA,
                AMPARO_VEDACAO_SIMPLES,
            ),
            # Trilha repassada por referência (não copiar — engine regular já gravou)
            "trilha_auditoria": self.trilha,
        }
