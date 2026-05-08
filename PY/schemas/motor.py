# -*- coding: utf-8 -*-
"""
motor.py — Schemas do Motor Tributário (Pydantic V2)
Separados da lógica de cálculo para evitar monólitos e facilitar testes unitários.
"""

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from core.cooperativa_ramos import RamoCooperativo
from validadores import validar_cnae, validar_cnpj, validar_ncm, validar_uf

logger = logging.getLogger("motor_conect.schemas")


# ─────────────────────────────────────────────────────────────────────────────
# ERR-039/ERR-056 — Bloqueio preventivo de NCMs em regimes especiais (FROZEN)
#
# Este motor NÃO modela duas dinâmicas distintas que incidem uma única vez
# na cadeia, sem creditamento subsequente:
#
#   (a) Regime MONOFÁSICO de IBS/CBS (LC 214/2025 Art. 172) — APENAS combustíveis.
#   (b) IMPOSTO SELETIVO (LC 214/2025 Arts. 409 § 1º + 410) — produtos
#       fumígenos e bebidas alcoólicas (capítulos NCM com convergência total
#       em fonte primária).
#
# Aceitar NCMs desses regimes no formulário padrão B2B produziria cálculo
# cumulativo semanticamente errado em cadeia que deveria ser de incidência
# única — MAX_FISCAL_01 + Lei 8.137/1990 Art. 1º II.
#
# Demais categorias do Imposto Seletivo (bebidas açucaradas 2202, veículos,
# embarcações, aeronaves, bens minerais, apostas) NÃO são bloqueadas no
# formulário pra preservar casos B2B legítimos (ex: distribuidor vendendo
# refrigerante pra lanchonete). DETECÇÃO de exposição vai por camada
# superior em core/imposto_seletivo.py — Rail R2: critério "açucarada" e
# critério ambiental de veículos delegados a PLP 42/2026, sem fonte firme
# pra hardcode no gate.
#
# Comparação é feita por PREFIXO de 4 dígitos (capítulo NCM), pois ambos
# os regimes abrangem a posição inteira e não suas subposições específicas.
#
# Validação Escrivão (30/04/2026): citação anterior atribuía cigarros e
# bebidas ao Art. 172 (regime monofásico) — INVENTADO. Art. 172 lista
# APENAS combustíveis. Cigarros e bebidas alcoólicas vão pro Imposto
# Seletivo Art. 409 § 1º, tributo diferente do regime monofásico.
#
# CF/88 Art. 149 §2º III (monofásico) + Art. 153 VIII (Seletivo) +
# LC 214/2025 Art. 172 (monofásico) + Arts. 409-434 (Imposto Seletivo).
# ─────────────────────────────────────────────────────────────────────────────
NCMS_MONOFASICAS_BLOQUEADAS: frozenset[str] = frozenset({
    # Combustíveis e derivados de petróleo — LC 214/2025 Art. 172 (regime monofásico IBS/CBS)
    "2710",
    # Cigarros e produtos do tabaco — LC 214/2025 Art. 409 § 1º + Art. 410 (Imposto Seletivo)
    "2402", "2403",
    # Bebidas alcoólicas — LC 214/2025 Art. 409 § 1º + Art. 410 (Imposto Seletivo)
    "2203",  # cerveja
    "2204",  # vinho de uva
    "2205",  # vermute
    "2206",  # outras bebidas fermentadas
    "2207",  # álcool etílico não desnaturado ≥ 80% vol. (para bebidas)
    "2208",  # aguardentes, licores, destilados
})


# ─────────────────────────────────────────────────────────────────────────────
# ERR-038 — Granularidade de forma de recebimento (FROZEN)
#
# Split Payment (LC 214/2025 Art. 353 §1º) só se aplica a pagamentos
# intermediados por PSP — Prestador de Serviço de Pagamento. PIX direto
# banco-a-banco NÃO tem PSP e portanto não dispara retenção automática.
# Agrupar PIX_DIRETO e PIX_VIA_PSP sob o mesmo rótulo ("PIX_BOLETO")
# superestima a retenção em pagamentos domésticos reais.
# ─────────────────────────────────────────────────────────────────────────────
FORMAS_PAGAMENTO_COM_PSP: frozenset[str] = frozenset({
    # Formas que passam por PSP e disparam Split Payment a partir de 2027
    # LC 214/2025 Art. 353 §1º
    "PIX_VIA_PSP",  # Mercado Pago, PagSeguro, Stone, Nubank PJ, etc.
    "BOLETO",       # Registrado/emitido via PSP do banco
    "CARTAO",       # Credenciadoras/adquirentes (PSP por natureza)
})

class Atividade(BaseModel):
    """
    Atividade individual do PGDAS-D para empresas multi-atividade.
    LC 123/2006, Art. 18, §§ 1º e 3º — cada atividade tributada no Anexo correto.
    """
    model_config = ConfigDict(extra="forbid")

    receita: Decimal = Field(..., gt=Decimal("0"), description="Receita desta atividade no mês (RPA parcial)")
    anexo: Literal["I", "II", "III", "IV", "V"] = Field(..., description="Anexo Simples desta atividade")
    icms_st: bool = Field(default=False, description="ICMS retido por ST — zerado no DAS desta parcela")
    iss_retido: bool = Field(default=False, description="ISS retido pelo tomador — zerado no DAS desta parcela")

    @field_validator("receita", mode="before")
    @classmethod
    def converter_para_decimal(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            return Decimal(str(v))
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class EmpresaFornecedora(BaseModel):
    """
    Dados do emitente (cliente do escritório — fornecedor na cadeia B2B).
    """
    model_config = ConfigDict(extra="forbid")

    cnpj: str = Field(..., description="CNPJ com ou sem pontuação")
    razao_social: str = Field(..., min_length=2, description="Razão social completa")
    regime: Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI", "IMUNE"] = Field(..., description="Regime tributário")
    cnae_principal: str = Field(..., description="CNAE principal (7 dígitos)")
    uf_origem: str = Field(..., description="UF de origem (2 letras)")
    faturamento_12m: Decimal = Field(..., ge=Decimal("0"), description="RBT12 em R$")
    folha_salarios_12m: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description="Folha de salários 12 meses (necessário para Fator R)"
    )
    anexo_simples: Optional[Literal["I", "II", "III", "IV", "V"]] = Field(
        default=None, description="Anexo Simples (auto-detectado se None)"
    )
    atividades: Optional[List[Atividade]] = Field(
        default=None,
        description="Atividades individuais para empresas multi-atividade (ERR-008)."
    )
    receita_com_st_icms: Optional[Decimal] = Field(
        default=None, ge=Decimal("0"),
        description="Parcela mensal da receita com ICMS-ST."
    )
    categoria_mei: Optional[Literal["COMERCIO", "INDUSTRIA", "SERVICOS", "COMERCIO_SERVICOS"]] = Field(
        default=None, description="Categoria MEI."
    )
    data_inicio_atividade: Optional[date] = Field(
        default=None, description="Data de início de atividade."
    )

    # ── WS6 — Eixo societário (separado do regime tributário) ──────────────
    # Tipo societário = forma jurídica (CC + Tabela RFB Naturezas Jurídicas).
    # Distinto de `regime` (tributário) e `enquadramento_simples` (porte/MEI).
    # Default None preserva compatibilidade com chamadas legadas.
    #
    # Aliases tratados em `_expandir_alias_mei`:
    #   - "MEI"     → "EI" + enquadramento_simples="MEI" (LC 123/2006 Art. 18-A)
    #   - "EIRELI"  → "SLU"  (Lei 14.195/2021 — extinção da EIRELI)
    #
    # Manter sincronizado com `core.elegibilidade_societaria.TipoSocietario`.
    tipo_societario: Optional[
        Literal["EI", "SLU", "LTDA", "SS", "SA", "COOPERATIVA",
                "ASSOCIACAO", "FUNDACAO", "ORGANIZACAO_RELIGIOSA",
                # WS6 Etapa 2 — adicionados para evitar KeyError em CNPJs reais
                "SCP", "ESC", "CONSORCIO", "PRODUTOR_RURAL_PF"]
    ] = Field(
        default=None,
        description=(
            "Forma jurídica RFB. Aliases aceitos: 'MEI' (→ EI + MEI), "
            "'EIRELI' (→ SLU, Lei 14.195/2021)."
        ),
    )

    # Qualificações especiais ortogonais ao tipo societário.
    # Uma associação pode ter OSCIP (Lei 9.790/99) + CEBAS (Lei 12.101/2009).
    qualificacoes_especiais: List[
        Literal["OSCIP", "OS", "CEBAS", "UTILIDADE_PUBLICA_FEDERAL"]
    ] = Field(
        default_factory=list,
        description="Qualificações que podem coexistir (OSCIP+CEBAS é real).",
    )

    # Porte/enquadramento dentro do Simples — derivado de RBT12, mas pode
    # ser declarado pra MEI (Art. 18-A LC 123/2006) onde é status, não porte.
    enquadramento_simples: Optional[Literal["MEI", "MEI_CAMINHONEIRO", "ME", "EPP"]] = Field(
        default=None,
        description=(
            "Status no Simples Nacional. "
            "MEI = Art. 18-A LC 123/2006 (teto R$ 81k). "
            "MEI_CAMINHONEIRO = LC 188/2021 (sublimite específico). "
            "ME/EPP = porte conforme RBT12."
        ),
    )

    # Profissão regulamentada do Art. 127 LC 214/2025 (redução 30% IBS/CBS).
    # Lista taxativa de 18 incisos (validada Escrivão 30/04/2026). Default None
    # = sem redução aplicada (conservador). Códigos canônicos definidos em
    # core.profissoes_regulamentadas.CodigoProfissao.
    profissao_regulamentada: Optional[
        Literal[
            "ADMINISTRADOR", "ADVOGADO", "ARQUITETO_URBANISTA",
            "ASSISTENTE_SOCIAL", "BIBLIOTECARIO", "BIOLOGO",
            "CONTABILISTA", "ECONOMISTA", "ECONOMISTA_DOMESTICO",
            "EDUCADOR_FISICO", "ENGENHEIRO_AGRONOMO", "ESTATISTICO",
            "MEDICO_VETERINARIO_ZOOTECNISTA", "MUSEOLOGO", "QUIMICO",
            "RELACOES_PUBLICAS", "TECNICO_INDUSTRIAL", "TECNICO_AGRICOLA",
        ]
    ] = Field(
        default=None,
        description=(
            "Profissão do Art. 127 LC 214/2025 (redução 30% IBS/CBS). "
            "Lista taxativa — médico humano NÃO entra (regime de saúde, Art. 128+). "
            "None = sem redução por profissão regulamentada."
        ),
    )

    # ── WS6 Etapa 4 — Eixo IMUNIDADE (LC 214/2025 Art. 9º + CF Art. 150 VI b/c) ──
    # Campos só fazem sentido quando regime="IMUNE". model_validator cruzado abaixo
    # garante consistência (subtipo obrigatório, tipo societário compatível, CTN 14).
    subtipo_imune: Optional[
        Literal[
            "TEMPLO_RELIGIOSO",                          # LC 214 Art. 9º caput, II
            "PARTIDO_POLITICO",                          # LC 214 Art. 9º caput, III
            "SINDICATO_TRABALHADOR",                     # LC 214 Art. 9º caput, III
            "ENTIDADE_EDUCACIONAL_SEM_FINS_LUCRATIVOS",  # LC 214 Art. 9º caput, III
            "ENTIDADE_ASSISTENCIAL",                     # II ou III conforme flag
        ]
    ] = Field(
        default=None,
        description=(
            "Subtipo de imunidade. Obrigatório quando regime='IMUNE'. "
            "TEMPLO_RELIGIOSO cai no inciso II (LC 214 Art. 9º — não exige CTN 14). "
            "Demais caem no inciso III (LC 214 Art. 9º §3º — exige CTN 14 cumulativo)."
        ),
    )
    vinculada_a_entidade_religiosa: bool = Field(
        default=False,
        description=(
            "ENTIDADE_ASSISTENCIAL vinculada a templo cai no inciso II "
            "(dispensa CTN 14). Autônoma cai no inciso III (exige CTN 14)."
        ),
    )
    requisitos_ctn14_atendidos: Optional[tuple[bool, bool, bool]] = Field(
        default=None,
        description=(
            "(I, II, III) do CTN Art. 14: I=sem distribuição patrimônio/rendas; "
            "II=aplicação integral no País; III=escrituração regular. "
            "Obrigatório se subtipo cair no inciso III. Qualquer False ou None "
            "= ImunidadeNaoConfiguradaError."
        ),
    )
    receita_amparada: Optional[Decimal] = Field(
        default=None,
        ge=Decimal("0"),
        description="Receita de atividade-fim (amparada pela imunidade). IBS+CBS = 0.",
    )
    receita_nao_amparada: Optional[Decimal] = Field(
        default=None,
        ge=Decimal("0"),
        description=(
            "Receita de atividade-meio (não amparada pela imunidade). Engine "
            "IMUNE não calcula — Rail R5: operador escolhe regime externo."
        ),
    )

    # ── WS6 Etapa 5a — Eixo COOPERATIVA (LC 214/2025 Art. 271 + Lei 5.764/71) ──
    # Cooperativa NÃO é regime tributário — é tipo societário com regime próprio
    # de ato cooperativo que SOBREPÕE (overlay) o regime regular SIMPLES/PRESUMIDO/REAL.
    # Por isso aqui estão CAMPOS de cooperativa, não regime "COOPERATIVA".
    #
    # CLASSIFICAÇÃO POR RAMO (validado Escrivão 2026-05-08):
    # Lei 5.764/71 Art. 10 caput + § 1º — "as cooperativas se classificam também
    # de acordo com o objeto ou pela natureza das atividades... caberá ao
    # respectivo órgão controlador apreciar e caracterizar outras modalidades".
    # Os 5 ramos NÃO estão enumerados literalmente na Lei 5.764/71 — são
    # modalidades CONSAGRADAS via OCB/CGSN (órgão controlador). Não citar como
    # se fosse enumeração legal (anti-alucinação MAX_07).
    #
    # 5a cobre: CONSUMO, TRABALHO, PRODUCAO, AGROPECUARIA, TRANSPORTE.
    # 5b (futuro) cobre: CREDITO (regime de serviços financeiros LC 214 Art. 181+
    # + Lei 9.718/98 Art. 14 II → Real obrigatório) e SAUDE (regime específico de
    # operadora de plano de saúde LC 214). Schema captura o Literal completo pra
    # dar mensagem de erro CLARA quando 5b ainda não estiver implementado.
    # Fonte única em core.cooperativa_ramos.RamoCooperativo (PMD #1 — etapa 5b).
    # Comentário fiscal por ramo:
    #   CONSUMO       — exceção do Simples (LC 123/2006 Art. 3º § 1º)
    #   TRABALHO      — vedada no Simples (LC 123/2006 Art. 3º § 4º VI)
    #   PRODUCAO      — vedada no Simples (idem)
    #   AGROPECUARIA  — vedada no Simples + Art. 271 § 1º II (anulação crédito)
    #   TRANSPORTE    — vedada no Simples + crédito presumido LC 214 Art. 169 § 8º
    #   CREDITO       — Real obrigatório (Lei 9.718/98 Art. 14 II); regime LC 214 Art. 181+ (5b)
    #   SAUDE         — operadora de plano de saúde com regime específico LC 214 (5b)
    subtipo_cooperativa: Optional[RamoCooperativo] = Field(
        default=None,
        description=(
            "Ramo cooperativo. Obrigatório quando tipo_societario='COOPERATIVA'. "
            "Base normativa: Lei 5.764/71 Art. 10 caput + § 1º (classificação por "
            "objeto, modalidades caracterizadas pelo órgão controlador OCB/CGSN — "
            "NÃO é enumeração legal taxativa). 5a: CONSUMO/TRABALHO/PRODUCAO/"
            "AGROPECUARIA/TRANSPORTE. 5b (não implementado): CREDITO/SAUDE."
        ),
    )
    optante_art271_cbs_ibs: bool = Field(
        default=False,
        description=(
            "Opção pela alíquota zero do Art. 271 LC 214/2025 sobre receita de "
            "ato cooperativo. § 3º exige opção declarada no ano-calendário "
            "anterior. Default conservador: False (motor não zera sem opção)."
        ),
    )
    data_opcao_art271: Optional[date] = Field(
        default=None,
        description=(
            "Data da opção pelo Art. 271. Quando optante_art271_cbs_ibs=True, "
            "este campo é obrigatório (LC 214/2025 Art. 271 § 3º — ano anterior)."
        ),
    )
    receita_ato_cooperativo: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        description=(
            "Receita de ato cooperativo (Lei 5.764/71 — operações entre "
            "cooperativa e seus associados ou entre cooperativas). Quando "
            "tipo_societario='COOPERATIVA', soma com receita_ato_nao_cooperativo "
            "deve ser > 0."
        ),
    )
    receita_ato_nao_cooperativo: Decimal = Field(
        default=Decimal("0"),
        ge=Decimal("0"),
        description=(
            "Receita de ato não-cooperativo (operações com terceiros não "
            "associados — Lei 5.764/71). Tributada normalmente pelo regime regular."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _expandir_alias_mei(cls, data: Any) -> Any:
        """
        Normaliza aliases UX-friendly para a representação fiscalmente correta:

          - tipo_societario="MEI"   → "EI" + enquadramento_simples="MEI"
            (LC 123/2006 Art. 18-A — MEI é status do Simples para EI ≤ R$ 81k)

          - tipo_societario="MEI_CAMINHONEIRO" → "EI" + enquadramento_simples="MEI_CAMINHONEIRO"
            (LC 188/2021 — sublimite específico do MEI Caminhoneiro)

          - tipo_societario="EIRELI" → "SLU"
            (Lei 14.195/2021 — convertou EIRELI em Sociedade Limitada Unipessoal)
        """
        if not isinstance(data, dict):
            return data
        tipo = data.get("tipo_societario")
        if tipo == "MEI":
            data["tipo_societario"] = "EI"
            data.setdefault("enquadramento_simples", "MEI")
        elif tipo == "MEI_CAMINHONEIRO":
            data["tipo_societario"] = "EI"
            data.setdefault("enquadramento_simples", "MEI_CAMINHONEIRO")
        elif tipo == "EIRELI":
            data["tipo_societario"] = "SLU"
        return data

    @model_validator(mode="after")
    def _validar_consistencia_imune(self) -> "EmpresaFornecedora":
        """
        Consistência cruzada quando regime='IMUNE' (WS6 Etapa 4).

        Regras:
          1. regime='IMUNE' exige subtipo_imune declarado.
          2. regime='IMUNE' exige tipo_societario que a MATRIZ canônica de
             elegibilidade_societaria reconheça como `valido=True` para IMUNE.
             Hoje: {ASSOCIACAO, FUNDACAO, ORGANIZACAO_RELIGIOSA}.
             Lei nova entrar (ex: alguma cooperativa social ganhar imunidade
             parcial) → MATRIZ é a fonte única; este validator herda automático.
          3. Campos de imunidade só fazem sentido com regime='IMUNE' — caso
             contrário, motor aceita mas não usa (engine ignora).

        Não valida CTN 14 aqui (responsabilidade do engine — só na execução).

        Amparo: LC 214/2025 Art. 9º caput + §3º; CF/88 Art. 150 VI b/c.
        Rail R1 (fonte normativa única): MATRIZ é a verdade — não duplicar.
        """
        # Import local evita ciclo no carregamento (elegibilidade_societaria
        # é puro, schemas/motor.py é importado por muita gente).
        from core.elegibilidade_societaria import MATRIZ as _MATRIZ_ELEG

        if self.regime == "IMUNE":
            if self.subtipo_imune is None:
                raise ValueError(
                    "regime='IMUNE' exige campo 'subtipo_imune' declarado "
                    "(TEMPLO_RELIGIOSO, PARTIDO_POLITICO, SINDICATO_TRABALHADOR, "
                    "ENTIDADE_EDUCACIONAL_SEM_FINS_LUCRATIVOS ou ENTIDADE_ASSISTENCIAL). "
                    "LC 214/2025 Art. 9º caput, II/III."
                )
            tipos_compativeis = frozenset(
                tipo for (tipo, regime), eleg in _MATRIZ_ELEG.items()
                if regime == "IMUNE" and eleg.valido
            )
            if self.tipo_societario is not None and self.tipo_societario not in tipos_compativeis:
                raise ValueError(
                    f"tipo_societario='{self.tipo_societario}' incompatível com "
                    f"regime='IMUNE'. Tipos aceitos (MATRIZ canônica): "
                    f"{sorted(tipos_compativeis)}. Empresarial (LTDA, SA, SLU, EI "
                    "etc.) tem finalidade lucrativa — fora do escopo da imunidade "
                    "(CF Art. 150 VI c)."
                )
        return self

    @model_validator(mode="after")
    def _validar_consistencia_cooperativa(self) -> "EmpresaFornecedora":
        """
        Consistência cruzada quando tipo_societario='COOPERATIVA' (WS6 Etapa 5a).

        Regras:
          1. tipo_societario='COOPERATIVA' exige subtipo_cooperativa declarado.
          2. tipo_societario='COOPERATIVA' exige
             receita_ato_cooperativo + receita_ato_nao_cooperativo > 0.
          3. subtipo_cooperativa só faz sentido com tipo_societario='COOPERATIVA'.
          4. Subtipos CREDITO e SAUDE são tratados em WS6 etapa 5b — bloquear em 5a
             com mensagem específica que cita a próxima etapa.
          5. Vedação Simples salvo CONSUMO — LC 123/2006 Art. 3º § 4º VI + § 1º.
          6. Optante do Art. 271 exige data_opcao_art271 declarada (§ 3º).

        Amparo:
          - LC 214/2025 Art. 271 caput + I, II + § 3º (opção alíquota zero IBS/CBS)
          - LC 123/2006 Art. 3º § 4º VI (vedação Simples)
          - LC 123/2006 Art. 3º § 1º (exceção cooperativa de consumo)
          - Lei 9.718/98 Art. 14 II (cooperativa de crédito = Real obrigatório — 5b)
        """
        # 4a. CREDITO — Real obrigatório (Lei 9.718/98 Art. 14 II)
        # Cooperativas de crédito estão entre as instituições obrigadas ao
        # Lucro Real. Schema bloqueia outro regime antes do diagnóstico.
        if self.subtipo_cooperativa == "CREDITO" and self.regime != "REAL":
            raise ValueError(
                f"Cooperativa de CRÉDITO obrigada ao Lucro Real — "
                f"recebido regime='{self.regime}'. Lei 9.718/98 Art. 14 II "
                f"lista cooperativas de crédito entre as instituições obrigadas "
                f"ao Lucro Real. Regime tributário deve ser 'REAL'."
            )

        # 4b. SAUDE — opt-in Art. 271 INAPLICÁVEL
        # Cooperativas operadoras de plano de saúde caem no regime específico
        # de planos de assistência à saúde (LC 214/2025 Art. 234 III + Arts.
        # 235-238 — alíquota de referência reduzida em 60% pelo Art. 237). O
        # Art. 271 (alíquota zero IBS/CBS sobre ato cooperativo) não cobre o
        # Cap III Tít V — bloqueio explícito.
        if self.subtipo_cooperativa == "SAUDE" and self.optante_art271_cbs_ibs:
            raise ValueError(
                "Cooperativa de SAÚDE (operadora de plano) cai no regime "
                "específico LC 214/2025 Art. 234, caput + inciso III, c/c "
                "Arts. 235-238 (alíquota de referência reduzida em 60% pelo "
                "Art. 237; vedado crédito ao adquirente — Art. 238). "
                "Art. 271 (alíquota zero IBS/CBS) NÃO se aplica — opt-in "
                "deve ser False."
            )

        # 3. subtipo_cooperativa em tipo_societario != COOPERATIVA → erro
        if self.subtipo_cooperativa is not None and self.tipo_societario != "COOPERATIVA":
            raise ValueError(
                f"subtipo_cooperativa='{self.subtipo_cooperativa}' só faz sentido "
                f"com tipo_societario='COOPERATIVA'. Recebido: "
                f"tipo_societario='{self.tipo_societario}'."
            )

        if self.tipo_societario == "COOPERATIVA":
            # 1. exige subtipo
            if self.subtipo_cooperativa is None:
                raise ValueError(
                    "tipo_societario='COOPERATIVA' exige campo 'subtipo_cooperativa' "
                    "declarado (CONSUMO, TRABALHO, PRODUCAO, AGROPECUARIA ou TRANSPORTE)."
                )
            # 2. exige soma de receitas > 0
            soma = self.receita_ato_cooperativo + self.receita_ato_nao_cooperativo
            if soma <= Decimal("0"):
                raise ValueError(
                    "tipo_societario='COOPERATIVA' exige receita declarada — "
                    "soma de receita_ato_cooperativo + receita_ato_nao_cooperativo "
                    "deve ser > 0."
                )
            # 5. vedação Simples salvo CONSUMO
            if self.regime == "SIMPLES" and self.subtipo_cooperativa != "CONSUMO":
                raise ValueError(
                    f"Cooperativa de '{self.subtipo_cooperativa}' não pode optar "
                    f"pelo Simples Nacional. Vedação: LC 123/2006 Art. 3º § 4º VI. "
                    f"Exceção (cooperativa de consumo) está em LC 123/2006 Art. 3º § 1º."
                )

        # 6. Optante do Art. 271 exige data declarada
        if self.optante_art271_cbs_ibs and self.data_opcao_art271 is None:
            raise ValueError(
                "optante_art271_cbs_ibs=True exige 'data_opcao_art271' declarada. "
                "LC 214/2025 Art. 271 § 3º — opção produz efeitos no ano-calendário "
                "subsequente, exigindo data certa de manifestação."
            )

        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tipo_exibicao(self) -> Optional[str]:
        """
        Rótulo amigável pra UI/PDF: 'MEI' quando enquadramento_simples='MEI',
        senão o tipo societário cru. Mantém storage fiel à RFB e display
        fiel à linguagem do contador.
        """
        if self.enquadramento_simples == "MEI":
            return "MEI"
        if self.enquadramento_simples == "MEI_CAMINHONEIRO":
            return "MEI Caminhoneiro"
        return self.tipo_societario

    @field_validator("cnpj")
    @classmethod
    def validar_campo_cnpj(cls, v: str) -> str:
        res = validar_cnpj(v)
        if not res.ok:
            raise ValueError(f"CNPJ Invalido: {', '.join(res.errors)}")
        return re.sub(r'[\s.\-/]', '', v.strip())

    @field_validator("cnae_principal")
    @classmethod
    def validar_campo_cnae(cls, v: str) -> str:
        res = validar_cnae(v)
        if not res.ok:
            raise ValueError(f"CNAE Invalido: {', '.join(res.errors)}")
        return re.sub(r'[\s.\-/]', '', v.strip())

    @field_validator("uf_origem")
    @classmethod
    def validar_campo_uf(cls, v: str) -> str:
        res = validar_uf(v)
        if not res.ok:
            raise ValueError(f"UF Invalida: {', '.join(res.errors)}")
        return v.strip().upper()

    @field_validator(
        "faturamento_12m",
        "folha_salarios_12m",
        "receita_ato_cooperativo",
        "receita_ato_nao_cooperativo",
        mode="before",
    )
    @classmethod
    def converter_para_decimal(cls, v: Any) -> Optional[Decimal]:
        if v is None:
            return None
        if isinstance(v, float):
            return Decimal(str(v))
        return Decimal(str(v)) if not isinstance(v, Decimal) else v


class EmpresaCompradora(BaseModel):
    """
    Dados do destinatário (comprador).
    """
    model_config = ConfigDict(extra="forbid")

    tipo: Literal["B2B_CONTRIBUINTE", "B2C_CONSUMIDOR_FINAL", "MISTO"] = Field(
        ..., description="Tipo do comprador"
    )
    percentual_b2b: Decimal = Field(
        default=Decimal("100"), ge=Decimal("0"), le=Decimal("100")
    )
    # ERR-037 — regime do comprador sai de `str` livre para Literal fechado.
    # Valor captado vira dado auditável na trilha (crédito cruzado LC 214/2025
    # Art. 47 §2º fica previsto para Fase 4). "NAO_INFORMADO" é o default
    # explícito — assume PIOR CASO (sem crédito).
    regime: Literal["SIMPLES", "PRESUMIDO", "REAL", "MEI", "NAO_INFORMADO"] = Field(
        default="NAO_INFORMADO",
        description=(
            "Regime tributário do comprador — LC 214/2025 Art. 47 §2º. "
            "NAO_INFORMADO = pior caso (sem crédito cruzado)."
        ),
    )
    uf_destino: str = Field(..., description="UF de destino (2 letras)")

    @field_validator("uf_destino")
    @classmethod
    def validar_campo_uf(cls, v: str) -> str:
        res = validar_uf(v)
        if not res.ok:
            raise ValueError(f"UF Invalida: {', '.join(res.errors)}")
        return v.strip().upper()


class OperacaoFiscal(BaseModel):
    """
    Dados da operação tributária transicional.
    """
    model_config = ConfigDict(extra="forbid")

    data_emissao: date = Field(...)
    valor_operacao: Decimal = Field(..., gt=Decimal("0"))
    ncm_nbs: str = Field(..., description="NCM/NBS (8 dígitos)")
    c_class_trib: Optional[str] = Field(default=None)
    tinha_st_icms: bool = Field(default=False)
    reducao_cbs_ibs: Literal["INTEGRAL", "REDUCAO_30", "REDUCAO_60", "ISENTO"] = Field(default="INTEGRAL")
    # ERR-038 — Literal granular separa PIX banco-a-banco de PIX via PSP.
    # Split Payment só dispara para formas em FORMAS_PAGAMENTO_COM_PSP
    # (LC 214/2025 Art. 353 §1º). Ver motor_tributario.split_payment_impacto.
    forma_recebimento: Literal[
        "DINHEIRO",
        "PIX_DIRETO",    # banco-a-banco, sem PSP → NÃO dispara Split
        "PIX_VIA_PSP",   # Mercado Pago/PagSeguro/etc → dispara Split
        "BOLETO",        # registrado via PSP do banco → dispara Split
        "CARTAO",        # credenciadora/adquirente → dispara Split
    ] = Field(default="PIX_VIA_PSP")
    rpa_mensal: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    lucro_real_mensal: Optional[Decimal] = Field(default=None, ge=Decimal("0"))
    produto_importado: bool = Field(default=False)
    creditos_pis_cofins: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    qtd_itens: int = Field(default=1, ge=1, description="Quantidade de itens na NF-e")
    estorno_realizado: bool = Field(default=False, description="Flag de estorno após Split Payment")
    data_liquidacao: Optional[date] = Field(
        default=None,
        description="Data de liquidação financeira (Split Payment). Deve ser >= data_emissao."
    )

    @model_validator(mode="after")
    def validar_transicao(self):
        # Período transicional obrigatório — LC 214/2025, Art. 348
        if not (2026 <= self.data_emissao.year <= 2033):
            raise ValueError(
                f"Data {self.data_emissao} fora do período transicional válido (2026-2033). "
                "LC 214/2025 vigora apenas nesse intervalo."
            )
        # Liquidação não pode ser anterior à emissão
        if self.data_liquidacao is not None and self.data_liquidacao < self.data_emissao:
            raise ValueError(
                f"data_liquidacao ({self.data_liquidacao}) não pode ser anterior à emissão "
                f"({self.data_emissao}). Verifique a data de liquidação."
            )
        return self

    @field_validator("ncm_nbs")
    @classmethod
    def validar_campo_ncm(cls, v: str) -> str:
        res = validar_ncm(v)
        if not res.ok:
            raise ValueError(f"NCM Invalido: {', '.join(res.errors)}")
        limpo = re.sub(r'[\s.\-]', '', v.strip())

        # ERR-039/ERR-056 — Bloqueio de NCM de regime de incidência única.
        # Combustíveis (NCM 2710): regime monofásico IBS/CBS — LC 214/2025 Art. 172.
        # Cigarros (2402-2403) e bebidas alcoólicas (2203-2208): Imposto Seletivo
        # — LC 214/2025 Arts. 409 § 1º + 410. Tributos diferentes, mesmo gate.
        # Motor não modela nenhum dos dois — falha fechada é preferível a
        # silenciar o erro no diagnóstico (MAX_FISCAL_01).
        prefixo_cap = limpo[:4]
        if prefixo_cap in NCMS_MONOFASICAS_BLOQUEADAS:
            if prefixo_cap == "2710":
                regime = "regime monofásico de IBS/CBS (LC 214/2025 Art. 172)"
            else:
                regime = "Imposto Seletivo (LC 214/2025 Arts. 409 § 1º + 410)"
            raise ValueError(
                f"NCM {limpo} sujeito a {regime}. "
                "Este motor não modela esse regime. Consulte regra específica do setor "
                "(combustíveis 2710 — monofásico; tabacos 2402-2403 e bebidas "
                "alcoólicas 2203-2208 — Imposto Seletivo)."
            )
        return limpo

    @field_validator("valor_operacao", mode="before")
    @classmethod
    def converter_para_decimal(cls, v: Any) -> Decimal:
        if isinstance(v, float):
            return Decimal(str(v))
        return Decimal(str(v)) if not isinstance(v, Decimal) else v
