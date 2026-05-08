# -*- coding: utf-8 -*-
"""
regimes/imune.py — Motor de regime IMUNE (CF Art. 150 VI b/c + LC 214/2025 Art. 9º)
Projeto: Motor Tributário Conect 2026-2033

BASE LEGAL (validada por Escrivão 2026-05-07 contra cache local):
  - LC 214/2025 Art. 9º caput      → "São imunes também ao IBS e à CBS os fornecimentos:"
  - LC 214/2025 Art. 9º § 3º       → CTN 14 vincula APENAS o inciso III
  - LC 214/2025 Art. 9º § 4º       → imunidade NÃO alcança aquisições
  - LC 214/2025 Art. 49 caput      → adquirente B2B NÃO credita
  - LC 214/2025 Art. 51 caput +§1º → anulação proporcional de crédito
  - CF/88 Art. 150 VI b (red. EC 132/2023) — "entidades religiosas e templos
    de qualquer culto, inclusive suas organizações assistenciais e beneficentes"
  - CF/88 Art. 150 VI c — "patrimônio, renda ou serviços de partidos políticos,
    suas fundações, entidades sindicais dos trabalhadores, instituições de
    educação e de assistência social, sem fins lucrativos"
  - CF/88 Art. 150 § 4º — vedações compreendem patrimônio, renda e serviços
    relacionados com as finalidades essenciais
  - CTN Art. 14 incs. I-III + §§ 1º e 2º — requisitos cumulativos
  - STF RE 325.822/SP, Rel. Min. Ilmar Galvão, Red. p/ acórdão Min. Gilmar Mendes,
    j. 18/12/2002 — imunidade religiosa abrange patrimônio/renda/serviços
    vinculados às finalidades essenciais
  - STF Súmula Vinculante 52 — alínea c (educação/assistência/sindicatos/partidos);
    aplicável por analogia jurisprudencial a IBS/CBS via LC 214 Art. 9º §3º

GUARD CLAUSE (Camada 2):
  Qualquer tentativa de usar este engine com regime != "IMUNE" resulta em
  RegimeMismatchError com log na trilha de auditoria.

CARACTERÍSTICAS:
  - IBS+CBS = R$ 0,00 sobre receita amparada (Art. 9º caput)
  - Receita não amparada NÃO é tocada pelo engine — Rail R5 (operador
    escolhe regime externo via orquestrador)
  - 3 ALERTAS sempre presentes na trilha:
      ALERTA_IMUNE_AQUISICAO_NAO_IMUNE      (Art. 9º §4º)
      ALERTA_IMUNE_ANULACAO_CREDITO_PROPORCIONAL (Art. 51 §1º — quando há não-amparada)
      ALERTA_IMUNE_B2B_NAO_CREDITA          (Art. 49)
  - Inciso II (templo + assistencial vinculada): dispensa CTN 14
  - Inciso III (demais): exige requisitos_ctn14_atendidos cumulativos —
    falha fechada via ImunidadeNaoConfiguradaError
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

from core.regimes.base import BaseRegimeEngine, RegimeMismatchError

logger = logging.getLogger("motor_conect.regimes.imune")


# ─────────────────────────────────────────────────────────────────────────────
# CITAÇÕES CANÔNICAS (FROZEN — validadas Escrivão 2026-05-07)
# ─────────────────────────────────────────────────────────────────────────────

AMPARO_BASE_TEMPLO: str = (
    "CF/88 Art. 150 VI b (red. EC 132/2023) | CF/88 Art. 150 §4º | "
    "LC 214/2025 Art. 9º caput, II | "
    "STF RE 325.822/SP, Rel. Min. Ilmar Galvão, "
    "Red. p/ acórdão Min. Gilmar Mendes, j. 18/12/2002"
)

AMPARO_BASE_INCISO_III: str = (
    "CF/88 Art. 150 VI c | CF/88 Art. 150 §4º | "
    "LC 214/2025 Art. 9º caput, III + §3º | "
    "CTN Art. 14 incs. I-III + §§ 1º e 2º | "
    "STF SV 52 (aplicável por analogia jurisprudencial — "
    "IPTU → IBS/CBS via LC 214 Art. 9º §3º)"
)

AMPARO_AQUISICAO: str = "LC 214/2025 Art. 9º § 4º"
AMPARO_ANULACAO_CREDITO: str = "LC 214/2025 Art. 51 caput + § 1º"
AMPARO_B2B_NAO_CREDITA: str = "LC 214/2025 Art. 49 caput"
AMPARO_NAO_AMPARADA: str = (
    "CF/88 Art. 150 §4º — atividades essenciais | "
    "LC 214/2025 Art. 9º caput (escopo da imunidade)"
)
AMPARO_CTN14_VIOLADO: str = (
    "LC 214/2025 Art. 9º § 3º (vincula CTN 14 ao inciso III) | "
    "CTN Art. 14 incs. I-III (requisitos cumulativos)"
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — timestamp ISO (isolado para facilitar mock em testes)
# ─────────────────────────────────────────────────────────────────────────────

def agora_str() -> str:
    """Wrapper pra timestamp ISO; isolado para facilitar mock em testes."""
    return str(datetime.now())


# ─────────────────────────────────────────────────────────────────────────────
# EXCEÇÃO ESPECÍFICA — falha de configuração da imunidade (CTN 14 não cumprido)
# ─────────────────────────────────────────────────────────────────────────────

class ImunidadeNaoConfiguradaError(RegimeMismatchError):
    """
    Levantada quando entidade do inciso III (LC 214 Art. 9º §3º) declara
    requisitos do CTN Art. 14 não cumpridos cumulativamente.

    Herda de RegimeMismatchError pra que callers que esperam falha de regime
    capturem esta também (compatibilidade com handlers existentes).
    """


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — mapeia subtipo → inciso aplicável da LC 214 Art. 9º
# ─────────────────────────────────────────────────────────────────────────────

def _inciso_aplicavel(subtipo: str, vinculada_religiosa: bool) -> str:
    """
    Decide se o subtipo recai no inciso II ou III da LC 214 Art. 9º.

    Inciso II (LC 214 Art. 9º caput, II) — não exige CTN 14:
      - TEMPLO_RELIGIOSO sempre
      - ENTIDADE_ASSISTENCIAL vinculada a entidade religiosa
        (organização assistencial/beneficente do templo — EC 132/2023)

    Inciso III (LC 214 Art. 9º caput, III + §3º) — exige CTN 14 cumulativo:
      - PARTIDO_POLITICO, SINDICATO_TRABALHADOR,
        ENTIDADE_EDUCACIONAL_SEM_FINS_LUCRATIVOS,
        ENTIDADE_ASSISTENCIAL autônoma (não vinculada a templo)
    """
    if subtipo == "TEMPLO_RELIGIOSO":
        return "II"
    if subtipo == "ENTIDADE_ASSISTENCIAL" and vinculada_religiosa:
        return "II"
    return "III"


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE — IMUNE
# ─────────────────────────────────────────────────────────────────────────────

class ImuneEngine(BaseRegimeEngine):
    """
    Motor de cálculo para entidades imunes ao IBS+CBS (LC 214/2025 Art. 9º).
    Guard Clause: aceita SOMENTE empresas com regime='IMUNE'.

    Ancoragem principal: LC 214/2025 Art. 9º caput.
    Subtipos II/III determinam citação constitucional e exigência CTN 14.
    """

    REGIME_ACEITO = "IMUNE"

    def __init__(self, fornecedora: Any, trilha: List[Dict[str, Any]]) -> None:
        super().__init__(fornecedora, trilha)  # ativa Camada 2 (Guard)

    def _amparo_base(self) -> str:
        """Citação canônica do subtipo da empresa (TEMPLO ou inciso III)."""
        inciso = _inciso_aplicavel(
            self.fornecedora.subtipo_imune,
            self.fornecedora.vinculada_a_entidade_religiosa,
        )
        return AMPARO_BASE_TEMPLO if inciso == "II" else AMPARO_BASE_INCISO_III

    def _exigir_ctn14(self) -> None:
        """
        Inciso III da LC 214 Art. 9º + §3º: requisitos do CTN 14 cumulativos.
        Falha fechada via ImunidadeNaoConfiguradaError quando algum False/None.

        Templo (inciso II) e assistencial vinculada não passam por aqui.
        """
        inciso = _inciso_aplicavel(
            self.fornecedora.subtipo_imune,
            self.fornecedora.vinculada_a_entidade_religiosa,
        )
        if inciso != "III":
            return

        requisitos = self.fornecedora.requisitos_ctn14_atendidos
        if requisitos is None or not all(requisitos):
            motivo = (
                f"Subtipo '{self.fornecedora.subtipo_imune}' recai no inciso III "
                "da LC 214/2025 Art. 9º — exige cumprimento cumulativo dos requisitos "
                "do CTN Art. 14 (I não-distribuição, II aplicação no País, III "
                f"escrituração regular). Recebido: requisitos_ctn14_atendidos={requisitos}."
            )
            # Registramos o evento manualmente (não usamos registrar_violacao
            # da base porque ela levanta RegimeMismatchError direto, e queremos
            # ImunidadeNaoConfiguradaError especializada).
            self.trilha.append({
                "tipo": "VIOLACAO_SEGURANCA",
                "id": "VIOLACAO_ImuneEngine_CTN14_NAO_ATENDIDO",
                "titulo": "Imunidade não configurada — CTN Art. 14 não cumprido",
                "formula": (
                    f"Inciso III LC 214/2025 Art. 9º × CTN Art. 14 cumulativo "
                    f"[recebido: {requisitos}]"
                ),
                "memoria": {
                    "regime_empresa": "IMUNE",
                    "modulo_chamado": "ImuneEngine",
                    "subtipo": str(self.fornecedora.subtipo_imune),
                    "requisitos_ctn14_atendidos": str(requisitos),
                    "motivo": motivo,
                },
                "amparo_legal": AMPARO_CTN14_VIOLADO,
                "detalhe": motivo,
                "timestamp": agora_str(),
            })
            logger.error(
                "IMUNIDADE_NAO_CONFIGURADA | subtipo=%s | requisitos=%s",
                self.fornecedora.subtipo_imune,
                requisitos,
            )
            raise ImunidadeNaoConfiguradaError(
                mensagem=motivo,
                regime_empresa="IMUNE",
                modulo_chamado="ImuneEngine",
                lei=AMPARO_CTN14_VIOLADO,
            )

    def _registrar_alertas_obrigatorios(self) -> None:
        """
        3 ALERTAS sempre presentes em toda análise IMUNE — refletem
        consequências de caixa que o cliente comum desconhece:
          - aquisição NÃO é imune (cliente paga IBS+CBS na compra)
          - operação anterior tem crédito anulado proporcionalmente
          - adquirente B2B não credita (risco competitivo)
        """
        agora = agora_str()

        self.trilha.append({
            "tipo": "ALERTA_IMUNE_AQUISICAO",
            "id": "ALERTA_IMUNE_AQUISICAO_NAO_IMUNE",
            "titulo": "Aquisições de bens e serviços NÃO são imunes",
            "detalhe": (
                "A imunidade alcança apenas o fornecimento (saída) — entidade "
                "imune paga IBS+CBS quando ADQUIRE bens, direitos e serviços. "
                "Risco real de subestimar caixa de despesas."
            ),
            "amparo_legal": AMPARO_AQUISICAO,
            "timestamp": agora,
        })

        self.trilha.append({
            "tipo": "ALERTA_IMUNE_B2B",
            "id": "ALERTA_IMUNE_B2B_NAO_CREDITA",
            "titulo": "Adquirente B2B contribuinte NÃO credita",
            "detalhe": (
                "Cliente B2B contribuinte que adquire de entidade imune NÃO se "
                "apropria de crédito de IBS/CBS. Pode tornar a entidade imune "
                "competitivamente pior que fornecedor regime comum em cadeia B2B."
            ),
            "amparo_legal": AMPARO_B2B_NAO_CREDITA,
            "timestamp": agora,
        })

        # Anulação proporcional só faz sentido se há receita não-amparada
        # (proporção 100% imune = anulação 100%, mas operacionalmente irrelevante
        # se não houver insumos compartilhados; alerta é mais informativo nesse caso).
        if (
            self.fornecedora.receita_nao_amparada is not None
            and self.fornecedora.receita_nao_amparada > Decimal("0")
        ):
            r_amp = self.fornecedora.receita_amparada or Decimal("0")
            r_nao = self.fornecedora.receita_nao_amparada
            total = r_amp + r_nao
            proporcao = r_amp / total if total > 0 else Decimal("0")
            self.trilha.append({
                "tipo": "ALERTA_IMUNE_CREDITO",
                "id": "ALERTA_IMUNE_ANULACAO_CREDITO_PROPORCIONAL",
                "titulo": "Crédito de operações anteriores anulado proporcionalmente",
                "detalhe": (
                    "LC 214 Art. 51 §1º: anulação dos créditos de operações "
                    f"anteriores é proporcional ao valor das operações imunes. "
                    f"Proporção imune: {proporcao} ({r_amp}/{total}). "
                    "Operador deve aplicar essa proporção sobre os créditos de "
                    "insumos do período (não calculado automaticamente — depende "
                    "de input externo)."
                ),
                "amparo_legal": AMPARO_ANULACAO_CREDITO,
                "memoria": {
                    "receita_amparada": str(r_amp),
                    "receita_nao_amparada": str(r_nao),
                    "proporcao_imunidade": str(proporcao),
                },
                "timestamp": agora,
            })

    def _registrar_alerta_nao_amparada(self) -> None:
        """
        Receita não amparada NÃO é tocada pelo engine (Rail R5).
        Alerta o operador que precisa rodar engine externo (Presumido/Real)
        sobre essa parcela.
        """
        if (
            self.fornecedora.receita_nao_amparada is None
            or self.fornecedora.receita_nao_amparada <= Decimal("0")
        ):
            return

        r_nao = self.fornecedora.receita_nao_amparada
        self.trilha.append({
            "tipo": "ALERTA_IMUNE_NAO_AMPARADA",
            "id": "ALERTA_IMUNE_NAO_AMPARADA_REQUER_ANALISE",
            "titulo": "Receita não amparada requer análise externa",
            "detalhe": (
                f"Receita de atividade-meio R$ {r_nao} fora do escopo da imunidade. "
                "Engine IMUNE NÃO calcula essa parcela (Rail R5 — separação "
                "fonte ≠ motor). CF Art. 150 §4º exige análise humana sobre "
                "reversão à finalidade essencial. Operador deve escolher regime "
                "externo (Presumido/Real) e rodar engine apropriado."
            ),
            "amparo_legal": AMPARO_NAO_AMPARADA,
            "memoria": {
                "receita_nao_amparada": str(r_nao),
                "subtipo": str(self.fornecedora.subtipo_imune),
            },
            "timestamp": agora_str(),
        })

    def calcular_carga_total_mensal(self) -> Dict[str, Any]:
        """
        Carga IBS+CBS sobre receita amparada — sempre R$ 0,00.

        Sequência:
          1. Valida CTN 14 (só inciso III) — falha fechada se não atendido
          2. Calcula IBS amparada = R$ 0 (LC 214 Art. 9º caput)
          3. Calcula CBS amparada = R$ 0 (mesma base)
          4. Registra os 3 ALERTAS críticos
          5. Registra ALERTA de não-amparada (se aplicável)
          6. Devolve breakdown
        """
        # 1) Validação CTN 14
        self._exigir_ctn14()

        # 2-3) Cálculo zerado (Art. 9º caput)
        receita_amparada = self.fornecedora.receita_amparada or Decimal("0.00")
        ibs_amparada = receita_amparada * Decimal("0.00")
        cbs_amparada = receita_amparada * Decimal("0.00")
        total_mensal = (ibs_amparada + cbs_amparada).quantize(Decimal("0.01"))

        amparo_base = self._amparo_base()
        self._registrar_passo(
            id="IMUNE_CARGA_AMPARADA",
            titulo="Carga IBS+CBS sobre receita amparada — Imunidade",
            base=f"Receita amparada R$ {receita_amparada}",
            deducoes="Imunidade integral (LC 214 Art. 9º caput)",
            aliquota="0,0% IBS + 0,0% CBS (imune)",
            valor=f"IBS R$ {ibs_amparada} + CBS R$ {cbs_amparada} = R$ {total_mensal}",
            lei=amparo_base,
        )

        # 4-5) Alertas
        self._registrar_alertas_obrigatorios()
        self._registrar_alerta_nao_amparada()

        return {
            "regime": "IMUNE",
            "subtipo_imune": self.fornecedora.subtipo_imune,
            "inciso_aplicavel": _inciso_aplicavel(
                self.fornecedora.subtipo_imune,
                self.fornecedora.vinculada_a_entidade_religiosa,
            ),
            "receita_amparada": receita_amparada,
            "receita_nao_amparada": self.fornecedora.receita_nao_amparada or Decimal("0.00"),
            "ibs_amparada": ibs_amparada.quantize(Decimal("0.01")),
            "cbs_amparada": cbs_amparada.quantize(Decimal("0.01")),
            "total_mensal": total_mensal,
            "credito_iva_b2b_cliente": Decimal("0.00"),  # Art. 49
            "nota": (
                "Imunidade IBS+CBS sobre receita amparada (LC 214/2025 Art. 9º). "
                "Aquisições NÃO são imunes (§4º). Adquirente B2B não credita (Art. 49). "
                "Crédito anterior anulado proporcionalmente (Art. 51 §1º)."
            ),
            "trilha_auditoria": self.trilha,
        }
