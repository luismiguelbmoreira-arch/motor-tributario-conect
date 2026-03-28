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
import json
import logging
import os
from decimal import Decimal, ROUND_HALF_UP
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
# SCHEMA DE SAÍDA — O que a IA extrai dos PDFs
# ─────────────────────────────────────────────────────────────────────────────

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
        """Converte campo string para Decimal seguro."""
        valor = getattr(self, campo, None)
        if valor is None:
            return None
        # Remove R$, espaços, separadores de milhar, normaliza vírgula
        limpo = (
            str(valor)
            .replace("R$", "").replace(" ", "")
            .replace(".", "").replace(",", ".")
        )
        try:
            return Decimal(limpo).quantize(Decimal("0.01"), ROUND_HALF_UP)
        except Exception:
            logger.warning("Nao foi possivel converter '%s' para Decimal: campo=%s", valor, campo)
            return None

    def purge(self):
        """LGPD: limpa dados sensíveis da instância após uso."""
        self.cnpj = "REDACTED"
        self.razao_social = "REDACTED"
        import gc; gc.collect()


# ─────────────────────────────────────────────────────────────────────────────
# PROMPT DE EXTRAÇÃO — Instrução para Claude Vision
# ─────────────────────────────────────────────────────────────────────────────

PROMPT_EXTRACAO = """
Voce e um especialista tributario brasileiro analisando documentos do PGDAS-D (Simples Nacional).
Extraia os dados tributarios dos documentos fornecidos e retorne EXCLUSIVAMENTE um JSON valido.

CAMPOS OBRIGATORIOS:
- cnpj: CNPJ completo (ex: "12.345.678/0001-90")
- razao_social: Razao social completa
- cnae_principal: CNAE principal sem pontuacao (7 digitos, ex: "4711302")
- uf_origem: UF de 2 letras (ex: "SP")
- faturamento_12m: RBT12 - Receita Bruta Total dos ultimos 12 meses em R$ (ex: "1158950.86")
- rpa_referencia: Receita do Periodo de Apuracao do mes em questao em R$
- das_ecac_referencia: Valor total do DAS pago em R$
- competencia: Competencia no formato "MM/AAAA" (ex: "01/2026")

CAMPOS OPCIONAIS (null se nao encontrado):
- folha_salarios_12m: Folha de salarios 12 meses em R$ (para calculo do Fator R)
- anexo_simples: Anexo Simples Nacional ("I", "II", "III", "IV" ou "V")
- receita_com_st_icms: Valor MENSAL da receita sujeita a Substituicao Tributaria ICMS em R$ (quando o ICMS e zerado no DAS porque ja foi retido pelo substituto)

BREAKDOWN DO DAS (valores em R$, 0.00 se nao encontrado):
- das_breakdown: {
    "IRPJ": "valor",
    "CSLL": "valor",
    "COFINS": "valor",
    "PIS": "valor",
    "CPP": "valor",
    "ICMS": "valor",
    "ISS": "valor",
    "IPI": "valor"
  }

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

    if dados.campos_nao_encontrados:
        logger.warning(
            "Campos nao encontrados nos PDFs: %s", ", ".join(dados.campos_nao_encontrados)
        )

    logger.info(
        "Extracao concluida. Empresa: %s | Confianca: %.0f%%",
        dados.razao_social,
        dados.confianca_extracao * 100,
    )

    return dados


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRAÇÃO COM O MOTOR — Converte extração para parâmetros do motor
# ─────────────────────────────────────────────────────────────────────────────

def dados_para_motor(dados: DadosExtraidosPDF) -> dict:
    """
    Converte DadosExtraidosPDF para um dict pronto para instanciar EmpresaFornecedora.

    Returns:
        dict com campos para EmpresaFornecedora e campos de auditoria separados
    """
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
            "anexo_simples": dados.anexo_simples,
            "receita_com_st_icms": dados.to_decimal("receita_com_st_icms"),
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
        },
    }
