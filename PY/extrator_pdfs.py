# -*- coding: utf-8 -*-
"""
extrator_pdfs.py — Pipeline de Extração IA para Documentos Tributários
Projeto: Motor Tributário Conect 2026-2033
Escritório Contábil Conect — Sorocaba, SP

ARQUITETURA:
  PDFs do e-CAC (PGDAS-D, CNPJ, Declaração, Extrato)
       ↓
  Claude Vision API (lê texto E imagem — sem OCR manual)
       ↓
  JSON estruturado (validado por Pydantic V2)
       ↓
  EmpresaFornecedora + parâmetros de auditoria
       ↓
  MotorReformaTributaria

VARIÁVEIS DE AMBIENTE:
  ANTHROPIC_API_KEY — obrigatório. Nunca commitado.

LGPD:
  Dados processados em RAM. Nenhuma persistência de CNPJ ou PII.
  purge() chamado automaticamente após uso.
"""

import base64
import gc
import json
import logging
import os
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Literal, Optional

import anthropic
from pydantic import BaseModel, Field, field_validator

# Carrega .env automaticamente (busca na raiz do projeto ou no diretório pai)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parent.parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path, override=True)
except ImportError:
    pass  # python-dotenv opcional — variável pode vir do ambiente do SO

logger = logging.getLogger("motor_conect.extrator")

# ─────────────────────────────────────────────────────────────────────────────
# VERSIONAMENTO DO PROMPT — rastreia qual versão extraiu os dados
# Se o layout do e-CAC mudar, incrementar PROMPT_VERSION e registrar na trilha.
# ─────────────────────────────────────────────────────────────────────────────
PROMPT_VERSION: str = "v2.2-2026-04-02"
"""
Histórico:
  v1.0-2026-03-20: extração mono-atividade (CANAVEZI)
  v2.0-2026-03-26: multi-atividade + ST + ISS retido (CONFI-AR, ITANGUA)
  v2.1-2026-03-26: RPA mensal + formato US/BR auto-detect (to_decimal)
  v2.2-2026-04-02: confiança mínima 0.8 + versionamento layout e-CAC + processar_pdfs_bytes
"""

# Layout do e-CAC por ano — incrementar quando Receita Federal mudar os campos
# Se a extração degradar após mudança de ano fiscal, verificar aqui primeiro.
VERSAO_LAYOUT_ECAC: str = "2026"
"""
Histórico de layouts:
  2024: Campo "Receita Bruta Acumulada nos 12 meses anteriores ao período de apuração"
  2025: Sem mudança de layout conhecida
  2026: Campo RBT12 pode aparecer abreviado como "RBT12" em novos layouts do PGDAS-D
  → Se a extração falhar sistematicamente após virada do ano, incrementar aqui e no PROMPT_EXTRACAO.
"""

# Limiar mínimo de confiança — abaixo disso, recusa processar para evitar cálculos sobre dados
# incorretos. Configurável via variável de ambiente para ajuste sem redeploy.
_CONFIANCA_MINIMA: float = float(os.environ.get("EXTRATOR_CONFIANCA_MINIMA", "0.8"))

# Campos obrigatórios — motor para se ausentes
_CAMPOS_OBRIGATORIOS: tuple[str, ...] = ("cnpj", "razao_social", "faturamento_12m", "cnae_principal")
# Campos opcionais — fallback documentado se ausentes
_CAMPOS_OPCIONAIS: dict[str, str] = {
    "folha_salarios_12m": "Fator R indisponível — Anexo calculado apenas por CNAE",
    "rpa_mensal":         "RPA ausente — usando RBT12/12 como aproximação (ERR-007, delta < 0,3%)",
    "receita_com_st_icms": "ST não declarado — DAS calculado sem segregação ICMS-ST",
    "das_ecac":           "DAS do e-CAC ausente — comparação delta indisponível",
}


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA DE SAÍDA — O que a IA extrai dos PDFs
# ─────────────────────────────────────────────────────────────────────────────

class AtividadeExtraida(BaseModel):
    """
    Atividade individual extraída do PGDAS-D para empresa multi-atividade.
    LC 123/2006, Art. 18, §3º — cada atividade tem Anexo próprio.
    """
    receita: str = Field(..., description="Receita da atividade no mês em R$ (apenas números e ponto decimal)")
    anexo: Literal["I", "II", "III", "IV", "V"] = Field(..., description="Anexo Simples desta atividade")
    icms_st: bool = Field(default=False, description="True quando ICMS foi retido por ST — zerado no DAS")
    iss_retido: bool = Field(default=False, description="True quando ISS foi retido pelo tomador — zerado no DAS")


class DadosExtraidosPDF(BaseModel):
    """
    Dados tributários extraídos dos PDFs do e-CAC por Claude Vision.
    Mapeia diretamente para EmpresaFornecedora + parâmetros de auditoria.
    """

    # ── Para EmpresaFornecedora (motor de cálculo) ───────────────────────────
    cnpj: str = Field(..., description="CNPJ completo com pontuação XX.XXX.XXX/XXXX-XX")
    razao_social: str = Field(..., description="Razão social completa")
    cnae_principal: str = Field(..., description="CNAE principal (7 dígitos, sem pontuação)")
    uf_origem: str = Field(..., description="UF de 2 letras")
    faturamento_12m: str = Field(..., description="RBT12 em R$ (string para Decimal)")
    folha_salarios_12m: Optional[str] = Field(
        default=None, description="Folha de salários 12 meses em R$ (se disponível)"
    )
    anexo_simples: Optional[Literal["I", "II", "III", "IV", "V"]] = Field(
        default=None, description="Anexo Simples Nacional detectado no documento"
    )
    receita_com_st_icms: Optional[str] = Field(
        default=None,
        description=(
            "Receita mensal com ICMS-ST (substituicao tributaria) em R$. "
            "Presente quando empresa tem atividade com ST — ICMS nao compoe DAS. "
            "LC 123/2006, Art. 13, par. 1, VII."
        )
    )
    atividades_detalhadas: Optional[list] = Field(
        default=None,
        description=(
            "Lista de atividades individuais quando empresa tem mais de um segmento de receita "
            "com Anexos diferentes. Cada item: {receita, anexo, icms_st, iss_retido}. "
            "LC 123/2006, Art. 18, §3º."
        )
    )

    # ── Para referência de auditoria (comparar com e-CAC) ────────────────────
    rpa_referencia: str = Field(
        ..., description="Receita do Periodo de Apuracao (RPA) em R$"
    )
    das_ecac_referencia: str = Field(
        ..., description="Valor total do DAS pago no e-CAC em R$"
    )
    competencia: str = Field(
        ..., description="Competencia de apuracao no formato MM/AAAA"
    )
    das_breakdown: dict = Field(
        default_factory=dict,
        description="Composicao do DAS por tributo: IRPJ, CSLL, COFINS, PIS, CPP, ICMS, ISS, IPI"
    )

    # ── Metadados de extração ─────────────────────────────────────────────────
    campos_nao_encontrados: list = Field(
        default_factory=list,
        description="Campos que a IA nao conseguiu extrair dos documentos"
    )
    confianca_extracao: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Confianca da extracao: 1.0 = total, 0.0 = nenhuma"
    )
    observacoes: str = Field(
        default="", description="Notas da IA sobre limitacoes ou ambiguidades encontradas"
    )

    @field_validator("cnpj")
    @classmethod
    def limpar_cnpj(cls, v: str) -> str:
        # Normaliza para formato XX.XXX.XXX/XXXX-XX
        digitos = "".join(c for c in v if c.isdigit())
        if len(digitos) == 14:
            return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"
        return v

    @field_validator("cnae_principal")
    @classmethod
    def limpar_cnae(cls, v: str) -> str:
        import re
        return re.sub(r"[\s.\-/]", "", v.strip())

    @field_validator("uf_origem")
    @classmethod
    def normalizar_uf(cls, v: str) -> str:
        return v.strip().upper()[:2]

    def to_decimal(self, campo: str) -> Optional[Decimal]:
        """
        Converte campo string para Decimal seguro.

        Detecta automaticamente o formato:
          - Decimal US/API   "2014303.11"  → ponto é decimal, sem vírgula
          - Brasileiro       "2.014.303,11" → pontos são milhares, vírgula é decimal
          - Só vírgula       "2014303,11"  → vírgula é decimal
        """
        valor = getattr(self, campo, None)
        if valor is None:
            return None

        limpo = str(valor).replace("R$", "").replace(" ", "").strip()
        tem_ponto  = "." in limpo
        tem_virgula = "," in limpo

        if tem_ponto and tem_virgula:
            # Formato brasileiro: 2.014.303,11 — pontos = milhares, vírgula = decimal
            limpo = limpo.replace(".", "").replace(",", ".")
        elif tem_virgula and not tem_ponto:
            # Só vírgula: 2014303,11 — vírgula é decimal
            limpo = limpo.replace(",", ".")
        # else: formato decimal US/API "2014303.11" ou inteiro — mantém como está

        try:
            return Decimal(limpo).quantize(Decimal("0.01"), ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            logger.warning("Nao foi possivel converter '%s' para Decimal: campo=%s", valor, campo)
            return None

    def purge(self):
        """LGPD: limpa dados sensíveis da instância após uso."""
        self.cnpj = "REDACTED"
        self.razao_social = "REDACTED"
        gc.collect()


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT DE EXTRAÇÃO — Instrução para Claude Vision
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_EXTRACAO = f"""
Voce e um especialista tributario brasileiro analisando documentos do PGDAS-D (Simples Nacional).
Extraia os dados tributarios dos documentos fornecidos e retorne EXCLUSIVAMENTE um JSON valido.

VERSAO DO LAYOUT e-CAC ESPERADO: {VERSAO_LAYOUT_ECAC}
- Layout 2024-2025: campo RBT12 aparece como "Receita Bruta Acumulada nos 12 meses anteriores ao periodo de apuracao"
- Layout 2026+: campo pode aparecer como "RBT12" diretamente no cabecalho do PGDAS-D
- Se o layout do documento nao corresponder ao esperado, informe em "observacoes" e reduza confianca_extracao

CAMPOS OBRIGATORIOS:
- cnpj: CNPJ completo (ex: "12.345.678/0001-90")
- razao_social: Razao social completa
- cnae_principal: CNAE principal sem pontuacao (7 digitos, ex: "4711302")
- uf_origem: UF de 2 letras (ex: "SP")
- faturamento_12m: RBT12 — campo especifico chamado "Receita Bruta Acumulada nos 12 meses anteriores ao periodo de apuracao" ou "RBT12" no Extrato PGDAS-D. ATENÇÃO: este valor e tipicamente entre R$ 50.000 e R$ 4.800.000 para empresas Simples Nacional. Informe apenas o numero sem formatacao (ex: "856430.21"). NAO confunda com receita acumulada de varios anos, CNPJ ou outros numeros do documento.
- rpa_referencia: Receita do Periodo de Apuracao (RPA) do mes em questao — campo "Receita Bruta do Periodo de Apuracao" no Extrato PGDAS-D, em R$
- das_ecac_referencia: Valor total do DAS pago, encontrado no Recibo de Pagamento ou no campo "Total" da Declaracao, em R$
- competencia: Competencia no formato "MM/AAAA" (ex: "01/2026")

CAMPOS OPCIONAIS (null se nao encontrado):
- folha_salarios_12m: Folha de salarios 12 meses em R$ (para calculo do Fator R)
- anexo_simples: Anexo Simples Nacional ("I", "II", "III", "IV" ou "V") — apenas quando a empresa tem UMA atividade
- receita_com_st_icms: Valor MENSAL da receita sujeita a Substituicao Tributaria ICMS em R$ (quando o ICMS e zerado no DAS porque ja foi retido pelo substituto)
- atividades_detalhadas: Lista de atividades quando a empresa tem MAIS DE UM segmento de receita com Anexos DIFERENTES. OBRIGATORIO quando houver mix de comercio (Anexo I/II) + servicos (Anexo III/IV). Formato:
  [
    {{"receita": "95594.08", "anexo": "III", "icms_st": false, "iss_retido": false}},
    {{"receita": "4929.43",  "anexo": "I",   "icms_st": false, "iss_retido": false}},
    {{"receita": "32970.57", "anexo": "I",   "icms_st": true,  "iss_retido": false}},
    {{"receita": "5650.00",  "anexo": "III", "icms_st": false, "iss_retido": true}}
  ]
  Regras: (1) Receita em formato numerico sem R$ (ex: "32970.57"). (2) icms_st=true quando ICMS zerado por ST. (3) iss_retido=true quando ISS retido pelo tomador. (4) Se empresa so tem um Anexo, deixe null.

BREAKDOWN DO DAS (valores em R$, 0.00 se nao encontrado):
- das_breakdown: {{
    "IRPJ": "valor",
    "CSLL": "valor",
    "COFINS": "valor",
    "PIS": "valor",
    "CPP": "valor",
    "ICMS": "valor",
    "ISS": "valor",
    "IPI": "valor"
  }}

METADADOS:
- campos_nao_encontrados: lista de campos que voce nao encontrou nos documentos
- confianca_extracao: numero entre 0.0 e 1.0 indicando sua confianca
- observacoes: notas sobre limitacoes, ambiguidades ou pontos de atencao

REGRAS CRITICAS:
1. Valores monetarios: apenas numeros e ponto decimal (ex: "16428.83", NAO "R$ 16.428,83")
2. ICMS-ST: campo receita_com_st_icms e o valor da receita COM substituicao tributaria — quando ha duas atividades (revenda sem ST e revenda com ST), informe o valor da parcela COM ST
3. Se documento for imagem ilegivel, liste o campo em campos_nao_encontrados
4. NAO invente dados. Se nao encontrar, coloque null

Retorne APENAS o JSON, sem texto adicional.
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# FUNÇÃO PRINCIPAL — Extração via Claude Vision
# ─────────────────────────────────────────────────────────────────────────────

def extrair_dados_pdfs(caminhos_pdf: list[str | Path]) -> DadosExtraidosPDF:
    """
    Usa Claude Vision para extrair dados tributários dos PDFs do e-CAC.

    Args:
        caminhos_pdf: Lista de caminhos para os PDFs da empresa
                      (PGDAS-D extrato, CNPJ, Declaração, Empresa, Recibo)

    Returns:
        DadosExtraidosPDF validado pelo Pydantic V2

    Raises:
        ValueError: Se ANTHROPIC_API_KEY não estiver configurada
        RuntimeError: Se a IA não conseguir extrair os campos obrigatórios

    Exemplo:
        dados = extrair_dados_pdfs([
            "docs/doc calculo/CANAVEZI/PGDAS-D extrato.pdf",
            "docs/doc calculo/CANAVEZI/CNPJ_CANAVEZI.pdf",
        ])
        print(dados.das_ecac_referencia)  # "16428.83"
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY nao configurada. "
            "Defina a variavel de ambiente antes de usar o extrator. "
            "Exemplo: set ANTHROPIC_API_KEY=sk-ant-..."
        )

    cliente = anthropic.Anthropic(api_key=api_key)

    # Monta conteúdo da mensagem com todos os PDFs
    conteudo: list[dict[str, Any]] = []

    for caminho in caminhos_pdf:
        caminho = Path(caminho)
        if not caminho.exists():
            logger.warning("PDF nao encontrado, ignorando: %s", caminho)
            continue

        pdf_bytes = caminho.read_bytes()
        pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

        conteudo.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_b64,
            },
        })
        logger.info("PDF carregado: %s (%d KB)", caminho.name, len(pdf_bytes) // 1024)

    if not conteudo:
        raise RuntimeError("Nenhum PDF valido fornecido para extração.")

    # Adiciona o prompt de instrução
    conteudo.append({"type": "text", "text": PROMPT_EXTRACAO})

    logger.info("Enviando %d PDF(s) para Claude Vision...", len(conteudo) - 1)

    resposta = cliente.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": conteudo}],
    )

    texto_resposta = resposta.content[0].text.strip()

    # Remove blocos de código markdown se presentes
    if texto_resposta.startswith("```"):
        linhas = texto_resposta.split("\n")
        texto_resposta = "\n".join(linhas[1:-1])

    try:
        dados_brutos = json.loads(texto_resposta)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"IA retornou resposta invalida (nao e JSON): {e}\n"
            f"Resposta recebida: {texto_resposta[:500]}"
        ) from e

    # Valida com Pydantic V2
    dados = DadosExtraidosPDF(**dados_brutos)

    # Log estruturado de campos ausentes — com motivo e fallback documentado
    if dados.campos_nao_encontrados:
        for campo in dados.campos_nao_encontrados:
            if campo in _CAMPOS_OBRIGATORIOS:
                logger.error(
                    "CAMPO_OBRIGATORIO_AUSENTE | campo=%s | prompt_version=%s | "
                    "motivo=ausente_no_pdf | impacto=motor_bloqueado",
                    campo, PROMPT_VERSION,
                )
            else:
                fallback_msg = _CAMPOS_OPCIONAIS.get(campo, "sem fallback documentado")
                logger.warning(
                    "CAMPO_OPCIONAL_AUSENTE | campo=%s | prompt_version=%s | fallback=%s",
                    campo, PROMPT_VERSION, fallback_msg,
                )

    logger.info(
        "Extracao concluida | empresa=%s | confianca=%.0f%% | prompt=%s | campos_ausentes=%d",
        dados.razao_social,
        dados.confianca_extracao * 100,
        PROMPT_VERSION,
        len(dados.campos_nao_encontrados),
    )

    # Rejeitar extração com confiança abaixo do limiar — evita cálculos sobre dados incorretos.
    # Limiar configurável via EXTRATOR_CONFIANCA_MINIMA (padrão: 0.8).
    if dados.confianca_extracao < _CONFIANCA_MINIMA:
        campos_ausentes_str = ", ".join(dados.campos_nao_encontrados) if dados.campos_nao_encontrados else "nenhum informado"
        obs = dados.observacoes or "sem detalhes"
        raise RuntimeError(
            f"Confiança de extração insuficiente: {dados.confianca_extracao:.0%} "
            f"(mínimo exigido: {_CONFIANCA_MINIMA:.0%}). "
            f"Campos ausentes ou ambíguos: {campos_ausentes_str}. "
            f"Observações da IA: {obs}. "
            f"Ação recomendada: forneça PDFs com melhor qualidade ou informe os dados manualmente "
            f"via formulário de análise. "
            f"[PROMPT_VERSION={PROMPT_VERSION} | LAYOUT_ECAC={VERSAO_LAYOUT_ECAC}]"
        )

    return dados


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRAÇÃO COM O MOTOR — Converte extração para parâmetros do motor
# ─────────────────────────────────────────────────────────────────────────────

_TETO_SIMPLES = Decimal("4800000.00")  # LC 123/2006, Art. 3º, II


def dados_para_motor(dados: DadosExtraidosPDF) -> dict:
    """
    Converte DadosExtraidosPDF para um dict pronto para instanciar EmpresaFornecedora.

    Returns:
        dict com campos para EmpresaFornecedora e campos de auditoria separados

    Raises:
        ValueError: Se RBT12 excede o teto do Simples Nacional — indica erro de extração.
    """
    rbt12 = dados.to_decimal("faturamento_12m")
    if rbt12 is None:
        raise ValueError(
            "RBT12 nao pôde ser extraído dos PDFs (campo 'faturamento_12m' retornou None). "
            "Verifique se o Extrato PGDAS-D está legível e contém o campo "
            "'Receita Bruta Acumulada nos 12 meses anteriores ao período de apuração'. "
            "Valor bruto retornado pela IA: '%s'" % dados.faturamento_12m
        )
    if rbt12 > _TETO_SIMPLES:
        raise ValueError(
            f"RBT12 extraido R$ {rbt12:,.2f} excede o teto do Simples Nacional "
            f"(R$ {_TETO_SIMPLES:,.2f}). "
            f"Provavel erro de extracao: verifique o campo 'Receita Bruta Acumulada nos "
            f"12 meses anteriores ao periodo de apuracao' no Extrato PGDAS-D. "
            f"Valor bruto retornado pela IA: '{dados.faturamento_12m}'"
        )

    # Converte atividades_detalhadas em lista de Atividade (multi-atividade)
    atividades = None
    if dados.atividades_detalhadas:
        from motor_tributario import Atividade
        atividades = []
        for item in dados.atividades_detalhadas:
            receita_str = str(item.get("receita", "0"))
            receita_limpa = receita_str.replace("R$", "").replace(" ", "")
            tem_ponto  = "." in receita_limpa
            tem_virgula = "," in receita_limpa
            if tem_ponto and tem_virgula:
                receita_limpa = receita_limpa.replace(".", "").replace(",", ".")
            elif tem_virgula:
                receita_limpa = receita_limpa.replace(",", ".")
            try:
                receita_dec = Decimal(receita_limpa).quantize(Decimal("0.01"), ROUND_HALF_UP)
            except (InvalidOperation, ValueError):
                logger.warning("Receita invalida em atividade, ignorando: %s", item)
                continue
            atividades.append(Atividade(
                receita=receita_dec,
                anexo=item.get("anexo", "I"),
                icms_st=bool(item.get("icms_st", False)),
                iss_retido=bool(item.get("iss_retido", False)),
            ))
        if not atividades:
            atividades = None

    return {
        # Campos para EmpresaFornecedora
        "empresa": {
            "cnpj": dados.cnpj,
            "razao_social": dados.razao_social,
            "regime": "SIMPLES",
            "cnae_principal": dados.cnae_principal,
            "uf_origem": dados.uf_origem,
            "faturamento_12m": dados.to_decimal("faturamento_12m"),
            "folha_salarios_12m": dados.to_decimal("folha_salarios_12m"),
            "anexo_simples": dados.anexo_simples if not atividades else None,
            "receita_com_st_icms": dados.to_decimal("receita_com_st_icms") if not atividades else None,
            "atividades": atividades,
        },
        # Referências para auditoria (comparar com e-CAC)
        "auditoria": {
            "rpa": dados.to_decimal("rpa_referencia"),
            "das_ecac": dados.to_decimal("das_ecac_referencia"),
            "competencia": dados.competencia,
            "breakdown": dados.das_breakdown,
        },
        # Metadados
        "meta": {
            "confianca": dados.confianca_extracao,
            "campos_ausentes": dados.campos_nao_encontrados,
            "observacoes": dados.observacoes,
            "prompt_version": PROMPT_VERSION,
            "layout_ecac": VERSAO_LAYOUT_ECAC,
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT PARA API — Recebe bytes em memória (sem disco)
# ─────────────────────────────────────────────────────────────────────────────

def processar_pdfs_bytes(conteudos: list[bytes]) -> dict:
    """
    Extrai dados tributários a partir de bytes de PDFs em memória.
    Usado pelo endpoint POST /analise/pdf — PDFs chegam via HTTP upload, sem gravar em disco.

    Args:
        conteudos: Lista de bytes de cada PDF (já lidos pelo FastAPI UploadFile)

    Returns:
        dict diagnóstico fiscal — mesmo formato de MotorReformaTributaria.gerar_diagnostico()

    Raises:
        ValueError: ANTHROPIC_API_KEY ausente
        RuntimeError: Confiança insuficiente, campos obrigatórios ausentes, ou falha de API
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "ANTHROPIC_API_KEY nao configurada. "
            "Defina a variavel de ambiente antes de usar o extrator."
        )

    if not conteudos:
        raise RuntimeError("Nenhum conteúdo de PDF fornecido.")

    cliente = anthropic.Anthropic(api_key=api_key)

    # Monta conteúdo da mensagem com todos os PDFs (em memória — sem disco)
    conteudo_msg: list[dict[str, Any]] = []
    for i, pdf_bytes in enumerate(conteudos):
        pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
        conteudo_msg.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": pdf_b64,
            },
        })
        logger.info("PDF[%d] carregado em memória: %d KB", i + 1, len(pdf_bytes) // 1024)

    conteudo_msg.append({"type": "text", "text": PROMPT_EXTRACAO})

    logger.info("Enviando %d PDF(s) bytes para Claude Vision...", len(conteudos))

    resposta = cliente.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": conteudo_msg}],
    )

    texto_resposta = resposta.content[0].text.strip()
    if texto_resposta.startswith("```"):
        linhas = texto_resposta.split("\n")
        texto_resposta = "\n".join(linhas[1:-1])

    try:
        dados_brutos = json.loads(texto_resposta)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"IA retornou resposta inválida (não é JSON): {exc}\n"
            f"Resposta recebida: {texto_resposta[:500]}"
        ) from exc

    dados = DadosExtraidosPDF(**dados_brutos)

    # Log de campos ausentes
    if dados.campos_nao_encontrados:
        for campo in dados.campos_nao_encontrados:
            if campo in _CAMPOS_OBRIGATORIOS:
                logger.error(
                    "CAMPO_OBRIGATORIO_AUSENTE | campo=%s | prompt_version=%s",
                    campo, PROMPT_VERSION,
                )
            else:
                fallback_msg = _CAMPOS_OPCIONAIS.get(campo, "sem fallback documentado")
                logger.warning(
                    "CAMPO_OPCIONAL_AUSENTE | campo=%s | fallback=%s",
                    campo, fallback_msg,
                )

    # Rejeitar confiança baixa
    if dados.confianca_extracao < _CONFIANCA_MINIMA:
        campos_ausentes_str = ", ".join(dados.campos_nao_encontrados) or "nenhum informado"
        raise RuntimeError(
            f"Confiança de extração insuficiente: {dados.confianca_extracao:.0%} "
            f"(mínimo: {_CONFIANCA_MINIMA:.0%}). "
            f"Campos problemáticos: {campos_ausentes_str}. "
            f"Tente PDFs com melhor qualidade ou use o formulário manual."
        )

    # Converte para parâmetros do motor e executa diagnóstico
    params = dados_para_motor(dados)
    empresa_params = params["empresa"]
    auditoria_params = params["auditoria"]

    from motor_tributario import (
        EmpresaCompradora,
        EmpresaFornecedora,
        MotorReformaTributaria,
        OperacaoFiscal,
    )
    from datetime import date

    fornecedora = EmpresaFornecedora(
        cnpj=empresa_params["cnpj"],
        razao_social=empresa_params["razao_social"],
        regime=empresa_params["regime"],
        cnae_principal=empresa_params["cnae_principal"],
        uf_origem=empresa_params["uf_origem"],
        faturamento_12m=empresa_params["faturamento_12m"],
        folha_salarios_12m=empresa_params.get("folha_salarios_12m"),
        anexo_simples=empresa_params.get("anexo_simples"),
        receita_com_st_icms=empresa_params.get("receita_com_st_icms"),
        atividades=empresa_params.get("atividades"),
    )
    compradora = EmpresaCompradora(tipo="B2C_CONSUMIDOR_FINAL")

    # Usar competência extraída para definir data_emissao
    competencia = auditoria_params.get("competencia", "")
    try:
        mes_str, ano_str = competencia.split("/")
        data_emissao = date(int(ano_str), int(mes_str), 1)
    except (ValueError, AttributeError):
        data_emissao = date.today()

    operacao = OperacaoFiscal(
        data_emissao=data_emissao,
        valor_operacao=auditoria_params.get("rpa") or fornecedora.faturamento_12m / 12,
        rpa_mensal=auditoria_params.get("rpa"),
    )

    motor = MotorReformaTributaria(
        fornecedora=fornecedora,
        compradora=compradora,
        operacao=operacao,
    )
    diagnostico = motor.gerar_diagnostico()

    # Injeta metadados da extração no diagnóstico
    diagnostico["_extracao"] = {
        "confianca": dados.confianca_extracao,
        "campos_ausentes": dados.campos_nao_encontrados,
        "observacoes": dados.observacoes,
        "prompt_version": PROMPT_VERSION,
        "layout_ecac": VERSAO_LAYOUT_ECAC,
        "das_ecac_referencia": str(auditoria_params.get("das_ecac") or ""),
        "competencia": competencia,
    }

    # LGPD: purge após uso
    dados.purge()

    return diagnostico
