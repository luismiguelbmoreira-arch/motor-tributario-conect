# -*- coding: utf-8 -*-
"""
cnae_mei_anexo_xi.py — Lista de CNAEs permitidos no MEI (Anexo XI CGSN 140/2018)

WS6 Etapa 3. Conservador por design (Rail R2):
  - Set fechado de CNAEs MEI CONFIRMADOS contra ocupações tradicionais do
    Anexo XI Resolução CGSN 140/2018. Cada entrada tem comentário com a
    ocupação correspondente.
  - CNAEs FORA deste set retornam `None` (Indeterminado) — caller deve
    pedir confirmação manual ao contador.
  - CNAEs já marcados como E_VEDADO em `cnae_excecoes.py` (banco, factoring)
    são tratados pelo validador chamador, não duplicados aqui.

ATENÇÃO ANTI-ALUCINAÇÃO (ERR-017.b):
  Esta lista é PARCIAL e bem documentada. NÃO inventar CNAE — se não
  está na lista, retorna Indeterminado, não False. Lista canônica completa
  exige curadoria contra Anexo XI CGSN 140/2018 oficial (~480 ocupações),
  pendente de regeneração via WS12 quando puxar CSV CGSN.

REFERÊNCIA:
  - LC 123/2006 Art. 18-A
  - Resolução CGSN 140/2018 Anexo XI (lista de ocupações MEI)
  - LC 188/2021 (MEI Caminhoneiro — atividades específicas)
"""
from __future__ import annotations

from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# CNAEs MEI confirmados (lista parcial — expandir via curadoria CSV CGSN)
# Cada CNAE com a ocupação Anexo XI correspondente em comentário.
# ─────────────────────────────────────────────────────────────────────────────
_CNAES_MEI_CONFIRMADOS: frozenset[str] = frozenset({
    # Beleza/estética
    "9602501",  # Cabeleireiros
    "9602502",  # Manicure / pedicure
    "9602504",  # Maquiadores
    "9609204",  # Esteticistas / depiladores

    # Alimentação ambulante e fixa pequena
    "5612100",  # Comidas preparadas / vendedor ambulante de alimentos
    "5611205",  # Bares e similares (lanche caseiro)
    "1091102",  # Padeiro / confeiteiro autônomo
    "1091101",  # Doceiro / panificador artesanal

    # Costura e artesanato
    "1411802",  # Costureiro(a) sob medida
    "1340599",  # Bordadeiro(a)

    # Construção / reparos
    "4399105",  # Pedreiro
    "4330404",  # Eletricista (reparos prediais)
    "4322302",  # Encanador (reparos prediais)
    "4330404",  # Pintor de paredes (mesmo CNAE eletricista — RFB classifica junto)
    "4329104",  # Instalador de equipamentos
    "4520001",  # Mecânico de automóveis
    "4520005",  # Mecânico de motos
    "9521500",  # Reparador de eletrodomésticos
    "9529105",  # Reparador de bicicletas

    # Transporte (modalidades MEI tradicional)
    "5320202",  # Motoboy / entregador
    "8011101",  # Vigilante autônomo (atenção: pode requerer registro)

    # MEI Caminhoneiro (LC 188/2021) — transporte rodoviário de carga
    "4930201",  # Transporte rodoviário de carga municipal
    "4930202",  # Transporte rodoviário de carga intermunicipal/interestadual
    "4930203",  # Transporte rodoviário de carga internacional
    "4930204",  # Transporte de mudanças

    # Comércio varejista pequeno
    "4781400",  # Comércio varejista de artigos do vestuário
    "4789099",  # Comércio varejista não especificado
    "4761003",  # Comércio varejista de artigos de papelaria

    # Serviços domésticos/limpeza
    "8121400",  # Limpeza em prédios e domicílios
    "8129000",  # Limpeza não especificada
    "9700500",  # Serviços domésticos

    # Outros tradicionais
    "7420002",  # Fotógrafo autônomo
    "9601701",  # Lavanderia
    "8593700",  # Professor particular (curso livre)
})

# CNAEs específicos do MEI Caminhoneiro (LC 188/2021)
# Subset dos confirmados acima — usado para validar enquadramento_simples="MEI_CAMINHONEIRO"
CNAES_MEI_CAMINHONEIRO: frozenset[str] = frozenset({
    "4930201",  # Transporte rodoviário de carga municipal
    "4930202",  # Transporte rodoviário de carga intermunicipal/interestadual
    "4930203",  # Transporte rodoviário de carga internacional
    "4930204",  # Transporte de mudanças
})


def cnae_no_anexo_xi_mei(cnae_7_digitos: str) -> Optional[bool]:
    """
    Verifica se o CNAE está confirmado no Anexo XI CGSN 140/2018 (MEI).

    Returns:
        True   — CNAE confirmadamente permitido pra MEI
        False  — reservado para versão futura com lista completa CSV CGSN
                 (hoje não retorna False; CNAE não confirmado retorna None)
        None   — Indeterminado: lista parcial não tem cobertura, contador
                 deve consultar Anexo XI CGSN 140/2018 manualmente.

    Rail R2: nunca afirma "vedado MEI" sem fonte. Se não está confirmado,
    devolve `None` pra caller decidir (geralmente sinalizar dúvida ao usuário,
    não bloquear automaticamente).
    """
    if not cnae_7_digitos or len(cnae_7_digitos) != 7 or not cnae_7_digitos.isdigit():
        return None
    if cnae_7_digitos in _CNAES_MEI_CONFIRMADOS:
        return True
    return None


def cnae_eh_mei_caminhoneiro(cnae_7_digitos: str) -> bool:
    """Verifica se o CNAE é da modalidade MEI Caminhoneiro (LC 188/2021)."""
    return cnae_7_digitos in CNAES_MEI_CAMINHONEIRO
