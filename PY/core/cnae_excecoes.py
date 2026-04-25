# -*- coding: utf-8 -*-
"""
cnae_excecoes.py — Overrides Cirurgicos do Mapa CNAE -> Anexo Simples Nacional
Projeto: Motor Tributario Conect 2026-2033

CONTEXTO (WS12 / ERR-005 reaberto):
  Resolucao CGSN 140/2018 Anexo VI mapeia ~1330 CNAEs, mas o mapa nao
  comporta a logica do Fator R (Art. 18 §5º-D LC 123/2006). Alem disso,
  ~14 casos cirurgicos NAO seguem o padrao da divisao CNAE — e precisam
  override explicito com base legal.

  Ex: 6920601 (Contabilidade) cai na divisao 69 que SERIA C_FATOR_R, mas
  LC 123 §5º-B XIV diz "Anexo III SEMPRE". Sem este override, motor calcula
  errado quando empresa nao tem folha (Fator R = 0 -> caia em Anexo V).

REFERENCIA:
  docs/especificacoes/WS12_schema_cnae_luiz_moreira.md (Luiz Moreira)
  LC 123/2006, Art. 18 §5º-A a §5º-J + Art. 17 (vedacoes)
  Resolucao CGSN 140/2018 Anexo VI
"""
from __future__ import annotations

from typing import Literal, Optional, TypedDict


class ExcecaoCNAE(TypedDict, total=False):
    """Estrutura plana de override. Schema completo em regras_cnae.py."""
    categoria: Literal["A_FIXO", "B_ANEXO_III", "C_FATOR_R", "D_ESPECIAL", "E_VEDADO"]
    anexo_padrao: Optional[Literal["I", "II", "III", "IV", "V"]]
    depende_fator_r: bool
    base_legal: str
    observacao: Optional[str]


# ─────────────────────────────────────────────────────────────────────────────
# CASOS CIRURGICOS — CNAEs que NAO seguem o padrao da divisao
# Cada entrada cita Art. e paragrafo da LC 123/2006 explicitamente.
# ─────────────────────────────────────────────────────────────────────────────

CNAE_EXCECOES: dict[str, ExcecaoCNAE] = {
    # ─── DIVISAO 69 (Atividades juridicas, contabeis, consultoria) ─────────
    # Contabilidade e auditoria: §5º-B XIV diz "Anexo III SEMPRE"
    "6920601": {
        "categoria": "B_ANEXO_III",
        "anexo_padrao": "III",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §5º-B XIV",
        "observacao": "Atividades de contabilidade — Anexo III sempre, independente de Fator R. Caso MOREIRA confirma.",
    },
    "6920602": {
        "categoria": "B_ANEXO_III",
        "anexo_padrao": "III",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §5º-B XIV",
        "observacao": "Auditoria/pericia contabil — Anexo III sempre.",
    },
    # Advocacia: §5º-C V diz "Anexo IV SEMPRE" (ATENCAO: nao e III nem V)
    "6911701": {
        "categoria": "D_ESPECIAL",
        "anexo_padrao": "IV",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §5º-C V",
        "observacao": "Advocacia — Anexo IV sempre. CPP recolhida separadamente. NAO confundir com contabilidade (que e III).",
    },

    # ─── COMERCIO VAREJISTA (CASOS REAIS DO PROJETO) ───────────────────────
    "4757100": {
        "categoria": "A_FIXO",
        "anexo_padrao": "I",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §4º I",
        "observacao": "Comercio varejista de eletroeletronicos — Anexo I (Comercio). Caso CANAVEZI.",
    },

    # ─── INDUSTRIA (CASOS REAIS DO PROJETO) ────────────────────────────────
    "2539001": {
        "categoria": "A_FIXO",
        "anexo_padrao": "II",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §4º II",
        "observacao": "Tempera/cementacao de metais — Anexo II (Industria). Caso CONFI_AR.",
    },

    # ─── DIVISAO 56 (Alimentacao) — C_FATOR_R explicito ────────────────────
    "5611201": {
        "categoria": "C_FATOR_R",
        "anexo_padrao": None,
        "depende_fator_r": True,
        "base_legal": "LC 123/2006 Art. 18 §5º-D I",
        "observacao": "Restaurante — Fator R: III se folha alta (>=28%), V se baixa.",
    },
    "5611203": {
        "categoria": "C_FATOR_R",
        "anexo_padrao": None,
        "depende_fator_r": True,
        "base_legal": "LC 123/2006 Art. 18 §5º-D I",
        "observacao": "Lanchonete/casa de cha — Fator R.",
    },

    # ─── DIVISAO 62 (TI) — C_FATOR_R explicito ─────────────────────────────
    "6201501": {
        "categoria": "C_FATOR_R",
        "anexo_padrao": None,
        "depende_fator_r": True,
        "base_legal": "LC 123/2006 Art. 18 §5º-D I",
        "observacao": "Desenvolvimento sob encomenda — Fator R.",
    },
    "6202300": {
        "categoria": "C_FATOR_R",
        "anexo_padrao": None,
        "depende_fator_r": True,
        "base_legal": "LC 123/2006 Art. 18 §5º-D I",
        "observacao": "Desenvolvimento customizavel — Fator R.",
    },

    # ─── ACADEMIAS (LC 155/2016 incluiu em §5º-B IX) ───────────────────────
    "9311500": {
        "categoria": "B_ANEXO_III",
        "anexo_padrao": "III",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §5º-B IX (incluido pela LC 155/2016)",
        "observacao": "Academia de ginastica — Anexo III sempre, sem Fator R.",
    },

    # ─── CONSTRUCAO SUBCONTRATADA ──────────────────────────────────────────
    "4399103": {
        "categoria": "D_ESPECIAL",
        "anexo_padrao": "IV",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §5º-C I",
        "observacao": "Construcao de obras subcontratada — Anexo IV.",
    },

    # ─── SAUDE (medico ambulatorial — C_FATOR_R) ───────────────────────────
    "8630501": {
        "categoria": "C_FATOR_R",
        "anexo_padrao": None,
        "depende_fator_r": True,
        "base_legal": "LC 123/2006 Art. 18 §5º-D III + §5º-J (LC 155/2016)",
        "observacao": "Atividade medica ambulatorial — Fator R.",
    },

    # ─── VEDADOS AO SIMPLES (Art. 17) ──────────────────────────────────────
    "6491300": {
        "categoria": "E_VEDADO",
        "anexo_padrao": None,
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 17 I",
        "observacao": "Bancos — vedados ao Simples Nacional.",
    },
    "6422100": {
        "categoria": "E_VEDADO",
        "anexo_padrao": None,
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 17 I",
        "observacao": "Caixa economica federal — vedada ao Simples.",
    },
    "6435201": {
        "categoria": "E_VEDADO",
        "anexo_padrao": None,
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 17 VI",
        "observacao": "Factoring — vedado ao Simples.",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# REGRAS POR DIVISAO CNAE (2 primeiros digitos)
# Aplicadas quando o CNAE 7-digitos NAO esta em CNAE_EXCECOES.
# Fonte: LC 123/2006 Art. 18 §4º (A_FIXO), §5º-B/C/D + Resolucao CGSN 140/2018.
# ─────────────────────────────────────────────────────────────────────────────

DIVISAO_PARA_CATEGORIA: dict[str, ExcecaoCNAE] = {
    # ─── A_FIXO: Industria de transformacao (Anexo II) ─────────────────────
    **{str(i).zfill(2): {
        "categoria": "A_FIXO",
        "anexo_padrao": "II",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §4º II",
        "observacao": f"Divisao {str(i).zfill(2)} — Industria de transformacao.",
    } for i in range(10, 34)},

    # Agropecuaria/Pesca (industrial — Anexo II)
    **{str(i).zfill(2): {
        "categoria": "A_FIXO",
        "anexo_padrao": "II",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §4º II",
        "observacao": f"Divisao {str(i).zfill(2)} — Agropecuaria/Pesca.",
    } for i in (1, 2, 3)},

    # ─── A_FIXO: Comercio (Anexo I) ────────────────────────────────────────
    "45": {  # Comercio veiculos
        "categoria": "A_FIXO",
        "anexo_padrao": "I",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §4º I",
        "observacao": "Comercio veiculos automotores.",
    },
    "46": {  # Comercio atacadista
        "categoria": "A_FIXO",
        "anexo_padrao": "I",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §4º I",
        "observacao": "Comercio atacadista.",
    },
    "47": {  # Comercio varejista
        "categoria": "A_FIXO",
        "anexo_padrao": "I",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §4º I",
        "observacao": "Comercio varejista.",
    },

    # ─── D_ESPECIAL: Construcao (Anexo IV) ─────────────────────────────────
    **{str(i): {
        "categoria": "D_ESPECIAL",
        "anexo_padrao": "IV",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §5º-C I",
        "observacao": f"Divisao {i} — Construcao civil (Anexo IV).",
    } for i in (41, 42, 43)},

    # ─── B_ANEXO_III: Servicos do §5º-B ────────────────────────────────────
    "49": {  # Transporte terrestre
        "categoria": "B_ANEXO_III",
        "anexo_padrao": "III",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §5º-B I",
        "observacao": "Transporte terrestre (carga e passageiros — anexo III sempre).",
    },
    "85": {  # Educacao
        "categoria": "B_ANEXO_III",
        "anexo_padrao": "III",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §5º-B VIII",
        "observacao": "Educacao — Anexo III sempre.",
    },
    "87": {
        "categoria": "B_ANEXO_III",
        "anexo_padrao": "III",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §5º-B XII",
        "observacao": "Atividades de assistencia social com alojamento.",
    },
    "88": {
        "categoria": "B_ANEXO_III",
        "anexo_padrao": "III",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §5º-B XII",
        "observacao": "Atividades de assistencia social sem alojamento.",
    },
    "96": {  # Cabeleireiros, esteticistas
        "categoria": "B_ANEXO_III",
        "anexo_padrao": "III",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §5º-B XIII",
        "observacao": "Cabeleireiros/esteticistas (Salao-Parceiro LC 155/2016).",
    },

    # ─── C_FATOR_R: Servicos do §5º-D ──────────────────────────────────────
    "55": {  # Hospedagem
        "categoria": "C_FATOR_R",
        "anexo_padrao": None,
        "depende_fator_r": True,
        "base_legal": "LC 123/2006 Art. 18 §5º-D I",
        "observacao": "Hospedagem — Fator R.",
    },
    "56": {  # Alimentacao (restaurantes, bares)
        "categoria": "C_FATOR_R",
        "anexo_padrao": None,
        "depende_fator_r": True,
        "base_legal": "LC 123/2006 Art. 18 §5º-D I",
        "observacao": "Alimentacao — Fator R. Restaurantes, bares, lanchonetes.",
    },
    "62": {  # TI
        "categoria": "C_FATOR_R",
        "anexo_padrao": None,
        "depende_fator_r": True,
        "base_legal": "LC 123/2006 Art. 18 §5º-D I",
        "observacao": "Tecnologia da informacao — Fator R.",
    },
    "63": {  # Tratamento de dados
        "categoria": "C_FATOR_R",
        "anexo_padrao": None,
        "depende_fator_r": True,
        "base_legal": "LC 123/2006 Art. 18 §5º-D I",
        "observacao": "Tratamento de dados, hospedagem, portais — Fator R.",
    },
    "71": {  # Engenharia/Arquitetura
        "categoria": "C_FATOR_R",
        "anexo_padrao": None,
        "depende_fator_r": True,
        "base_legal": "LC 123/2006 Art. 18 §5º-D II",
        "observacao": "Engenharia/Arquitetura — Fator R.",
    },
    "73": {  # Publicidade
        "categoria": "C_FATOR_R",
        "anexo_padrao": None,
        "depende_fator_r": True,
        "base_legal": "LC 123/2006 Art. 18 §5º-D VI",
        "observacao": "Publicidade — Fator R.",
    },
    "74": {  # Design/Fotografia
        "categoria": "C_FATOR_R",
        "anexo_padrao": None,
        "depende_fator_r": True,
        "base_legal": "LC 123/2006 Art. 18 §5º-D VII",
        "observacao": "Design e fotografia — Fator R.",
    },
    "86": {  # Saude
        "categoria": "C_FATOR_R",
        "anexo_padrao": None,
        "depende_fator_r": True,
        "base_legal": "LC 123/2006 Art. 18 §5º-D III + §5º-J",
        "observacao": "Saude humana — Fator R (medicina, odontologia, fisioterapia).",
    },

    # ─── D_ESPECIAL (Anexo IV — vigilancia, limpeza) ────────────────────────
    "80": {  # Vigilancia/Seguranca
        "categoria": "D_ESPECIAL",
        "anexo_padrao": "IV",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §5º-C VI",
        "observacao": "Vigilancia/seguranca — Anexo IV.",
    },
    "81": {  # Servicos para edificios (limpeza)
        "categoria": "D_ESPECIAL",
        "anexo_padrao": "IV",
        "depende_fator_r": False,
        "base_legal": "LC 123/2006 Art. 18 §5º-C II",
        "observacao": "Servicos a edificios e atividades de paisagismo (limpeza, conservacao).",
    },
}
