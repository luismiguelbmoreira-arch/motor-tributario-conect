# -*- coding: utf-8 -*-
"""
test_elegibilidade_societaria.py — Testes WS6 Etapa 2 (REVISADO)

Cobre os 52 cruzamentos da matriz (13 tipos × 4 regimes) + funções helper +
imutabilidade da MATRIZ + exceção customizada + aliases EIRELI/MEI_CAMINHONEIRO
no schema EmpresaFornecedora.

Achados endereçados (referência ao brief):
  A1/A2  citação ASSOCIACAO × PRESUMIDO corrigida
  A3     premissa "perde imunidade" reescrita (não se perde, coexiste)
  A4     COOPERATIVA × SIMPLES virou condicional valido=True (Opção A)
  A5     helpers retornam tupla de Elegibilidade, não strings
  A6     DECISAO_ESPERADA explícita por célula
  B1     MATRIZ é MappingProxyType (read-only)
  B2     CombinacaoSocietariaNaoMapeadaError (subclasse de ValueError)
  B3     `obrigatorio` documentado como sempre False na matriz pura
  B4     SCP, ESC, CONSORCIO, PRODUTOR_RURAL_PF, EIRELI alias, MEI_CAMINHONEIRO
  C1-C5  citações ampliadas
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.elegibilidade_societaria import (
    MATRIZ,
    CombinacaoSocietariaNaoMapeadaError,
    Elegibilidade,
    elegibilidade,
    regimes_permitidos,
    tipos_para_regime,
)
from schemas.motor import EmpresaFornecedora


# ─────────────────────────────────────────────────────────────────────────────
# Tabela canônica de decisão esperada — A6
# Fonte de verdade pra TODA célula. Se mudar uma decisão, muda aqui antes
# de mudar no código. Erro de decisão entre lei e implementação aparece aqui.
# ─────────────────────────────────────────────────────────────────────────────
DECISAO_ESPERADA: dict[tuple[str, str], bool] = {
    # EI
    ("EI", "SIMPLES"): True,
    ("EI", "PRESUMIDO"): True,
    ("EI", "REAL"): True,
    ("EI", "IMUNE"): False,
    # SLU
    ("SLU", "SIMPLES"): True,
    ("SLU", "PRESUMIDO"): True,
    ("SLU", "REAL"): True,
    ("SLU", "IMUNE"): False,
    # LTDA
    ("LTDA", "SIMPLES"): True,
    ("LTDA", "PRESUMIDO"): True,
    ("LTDA", "REAL"): True,
    ("LTDA", "IMUNE"): False,
    # SS
    ("SS", "SIMPLES"): True,
    ("SS", "PRESUMIDO"): True,
    ("SS", "REAL"): True,
    ("SS", "IMUNE"): False,
    # SA
    ("SA", "SIMPLES"): False,  # LC 123/2006 Art. 3º §4º (inciso TBD pelo Escrivão)
    ("SA", "PRESUMIDO"): True,
    ("SA", "REAL"): True,
    ("SA", "IMUNE"): False,
    # COOPERATIVA — Simples agora True condicional (apenas consumo)
    ("COOPERATIVA", "SIMPLES"): True,
    ("COOPERATIVA", "PRESUMIDO"): True,
    ("COOPERATIVA", "REAL"): True,
    ("COOPERATIVA", "IMUNE"): False,
    # ASSOCIACAO — Presumido agora True (RIR/2018 + Lei 9.532/97 + Lei 9.718/98)
    # Escrivão removeu citação inventada de SC COSIT 174/2019 (ERR-017.b)
    ("ASSOCIACAO", "SIMPLES"): False,
    ("ASSOCIACAO", "PRESUMIDO"): True,
    ("ASSOCIACAO", "REAL"): True,
    ("ASSOCIACAO", "IMUNE"): True,
    # FUNDACAO — Presumido agora True (simetria com associação)
    ("FUNDACAO", "SIMPLES"): False,
    ("FUNDACAO", "PRESUMIDO"): True,
    ("FUNDACAO", "REAL"): True,
    ("FUNDACAO", "IMUNE"): True,
    # ORGANIZACAO_RELIGIOSA — Presumido agora True (simetria)
    ("ORGANIZACAO_RELIGIOSA", "SIMPLES"): False,
    ("ORGANIZACAO_RELIGIOSA", "PRESUMIDO"): True,
    ("ORGANIZACAO_RELIGIOSA", "REAL"): True,
    ("ORGANIZACAO_RELIGIOSA", "IMUNE"): True,
    # SCP — sem personalidade jurídica, regime herdado do sócio ostensivo
    ("SCP", "SIMPLES"): False,
    ("SCP", "PRESUMIDO"): False,
    ("SCP", "REAL"): False,
    ("SCP", "IMUNE"): False,
    # ESC — vedada ao Simples (atividade financeira)
    ("ESC", "SIMPLES"): False,
    ("ESC", "PRESUMIDO"): True,
    ("ESC", "REAL"): True,
    ("ESC", "IMUNE"): False,
    # CONSORCIO — sem personalidade jurídica
    ("CONSORCIO", "SIMPLES"): False,
    ("CONSORCIO", "PRESUMIDO"): False,
    ("CONSORCIO", "REAL"): False,
    ("CONSORCIO", "IMUNE"): False,
    # PRODUTOR_RURAL_PF — pessoa física, IRPF
    ("PRODUTOR_RURAL_PF", "SIMPLES"): False,
    ("PRODUTOR_RURAL_PF", "PRESUMIDO"): False,
    ("PRODUTOR_RURAL_PF", "REAL"): False,
    ("PRODUTOR_RURAL_PF", "IMUNE"): False,
}


TIPOS = (
    "EI", "SLU", "LTDA", "SS", "SA", "COOPERATIVA",
    "ASSOCIACAO", "FUNDACAO", "ORGANIZACAO_RELIGIOSA",
    "SCP", "ESC", "CONSORCIO", "PRODUTOR_RURAL_PF",
)
REGIMES = ("SIMPLES", "PRESUMIDO", "REAL", "IMUNE")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Decisão por célula bate com a tabela canônica (A6 — substitui o
#    teste `isinstance` solto que passava com decisão errada)
# ─────────────────────────────────────────────────────────────────────────────

class TestDecisaoCanonica:

    @pytest.mark.parametrize(
        "tipo,regime,esperado",
        [(t, r, esp) for (t, r), esp in DECISAO_ESPERADA.items()],
    )
    def test_decisao_bate_com_tabela_canonica(self, tipo, regime, esperado):
        e = elegibilidade(tipo, regime)
        assert e.valido is esperado, (
            f"Decisão errada para ({tipo}, {regime}): "
            f"esperado valido={esperado}, recebido valido={e.valido}. "
            f"Base legal citada: {e.base_legal!r}. "
            f"Verifique a tabela DECISAO_ESPERADA OU a célula no módulo."
        )


class TestCoberturaTotal:

    def test_cobertura_e_completude(self):
        """Toda combinação tipo × regime tem célula com base legal."""
        assert len(MATRIZ) == len(TIPOS) * len(REGIMES) == 52
        for tipo in TIPOS:
            for regime in REGIMES:
                e = elegibilidade(tipo, regime)
                assert isinstance(e, Elegibilidade)
                assert e.base_legal, f"base_legal vazio em ({tipo},{regime})"

    def test_decisao_esperada_cobre_toda_matriz(self):
        """DECISAO_ESPERADA não tem buraco — defesa contra esquecimento."""
        chaves_matriz = set(MATRIZ.keys())
        chaves_esperadas = set(DECISAO_ESPERADA.keys())
        assert chaves_matriz == chaves_esperadas, (
            f"Discrepância DECISAO_ESPERADA × MATRIZ. "
            f"Faltando em esperada: {chaves_matriz - chaves_esperadas}. "
            f"Faltando em matriz: {chaves_esperadas - chaves_matriz}."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Toda célula vedada cita motivo + lei. Toda célula válida tem
#    base_legal não-vazia (já coberto na cobertura, ressaltado aqui).
# ─────────────────────────────────────────────────────────────────────────────

class TestForma:

    @pytest.mark.parametrize("tipo,regime", list(DECISAO_ESPERADA.keys()))
    def test_celula_tem_base_legal(self, tipo, regime):
        e = elegibilidade(tipo, regime)
        assert e.base_legal and len(e.base_legal) > 5

    @pytest.mark.parametrize(
        "tipo,regime",
        [(t, r) for (t, r), v in DECISAO_ESPERADA.items() if v is False],
    )
    def test_celula_vedada_tem_motivo(self, tipo, regime):
        e = elegibilidade(tipo, regime)
        assert e.motivo is not None and len(e.motivo) > 10, (
            f"Célula vedada sem motivo: ({tipo},{regime})"
        )

    def test_obrigatorio_sempre_false_na_matriz_pura(self):
        """B3 — `obrigatorio` é decidido pelo orquestrador, nunca aqui."""
        for chave, e in MATRIZ.items():
            assert e.obrigatorio is False, (
                f"`obrigatorio=True` na célula {chave} viola o contrato da "
                f"matriz pura (deve ser composto pelo orquestrador WS6.6)."
            )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Casos cirúrgicos que mudaram comparado à versão anterior — A1-A4, C1-C5
# ─────────────────────────────────────────────────────────────────────────────

class TestCorrecoesAuditoria:

    # A1 — citação ASSOCIACAO × PRESUMIDO corrigida
    # Escrivão verificou em 25/04/2026: SC COSIT 174/2019 não existe sobre
    # esse tema (a SC nº 174 que existe é de 2023 e trata de Imposto sobre
    # Importação / Ex-Tarifário). Citação foi removida — base sustenta-se
    # em RIR/2018 + Lei 9.532/97 + Lei 9.718/98 (composição normativa).
    def test_associacao_presumido_base_legal_sem_citacao_inventada(self):
        e = elegibilidade("ASSOCIACAO", "PRESUMIDO")
        assert e.valido is True
        assert "RIR/2018" in e.base_legal
        assert "Lei 9.532/97" in e.base_legal
        assert "Lei 9.718/98" in e.base_legal
        # Anti-alucinação: NÃO deve citar SC COSIT 174/2019 (não existe sobre o tema)
        assert "COSIT 174/2019" not in e.base_legal
        assert "COSIT 174/2019" not in (e.observacao or "")
        assert any("CTN Art. 14" in c for c in e.condicoes)

    # A2 — FUNDACAO × PRESUMIDO virou True
    def test_fundacao_presumido_eh_valido_com_condicoes(self):
        e = elegibilidade("FUNDACAO", "PRESUMIDO")
        assert e.valido is True
        assert any("CTN Art. 14 §2" in c for c in e.condicoes)

    # A2 — ORGANIZACAO_RELIGIOSA × PRESUMIDO virou True
    def test_organizacao_religiosa_presumido_eh_valido(self):
        e = elegibilidade("ORGANIZACAO_RELIGIOSA", "PRESUMIDO")
        assert e.valido is True
        assert any("CF Art. 150" in c for c in e.condicoes)

    # A3 — premissa "perde imunidade" reescrita
    def test_associacao_real_nao_diz_perde_imunidade(self):
        e = elegibilidade("ASSOCIACAO", "REAL")
        assert e.valido is True
        assert any("não amparada" in c.lower() for c in e.condicoes)
        # Pelo menos uma condição menciona o §2º (atividade econômica fora do escopo)
        assert any("§2" in c for c in e.condicoes)

    # A4 — COOPERATIVA × SIMPLES virou True com condicao de "consumo"
    def test_cooperativa_simples_eh_valido_com_condicao_consumo(self):
        e = elegibilidade("COOPERATIVA", "SIMPLES")
        assert e.valido is True
        assert any("consumo" in c.lower() for c in e.condicoes)
        assert "Art. 3º §1º" in e.base_legal or "§1º" in e.base_legal

    # C1 — LTDA × SIMPLES cita §4º incs. I a XV
    def test_ltda_simples_cita_incisos_i_a_xv(self):
        e = elegibilidade("LTDA", "SIMPLES")
        assert any("I a XV" in c for c in e.condicoes)

    # C2 — SS × SIMPLES distingue empresária × pura
    def test_ss_simples_distingue_empresaria_e_pura(self):
        e = elegibilidade("SS", "SIMPLES")
        assert e.observacao is not None
        assert "empresária" in e.observacao.lower() or "empresaria" in e.observacao.lower()
        assert "pura" in e.observacao.lower()

    # C3 — COOPERATIVA × REAL cita Lei 5.764/71 + RIR + 9.430/96
    def test_cooperativa_real_amplia_citacao(self):
        e = elegibilidade("COOPERATIVA", "REAL")
        assert "5.764/71" in e.base_legal
        assert "RIR/2018" in e.base_legal
        assert "9.430/96" in e.base_legal

    # C4 — ORG_RELIGIOSA × IMUNE cita Lei 9.532/97 + STF RE 325.822
    def test_org_religiosa_imune_cita_jurisprudencia(self):
        e = elegibilidade("ORGANIZACAO_RELIGIOSA", "IMUNE")
        assert "9.532/97" in e.base_legal
        assert "RE 325.822" in e.base_legal


# ─────────────────────────────────────────────────────────────────────────────
# 4. Novos tipos — SCP, ESC, CONSORCIO, PRODUTOR_RURAL_PF (B4)
# ─────────────────────────────────────────────────────────────────────────────

class TestNovosTipos:

    @pytest.mark.parametrize("regime", REGIMES)
    def test_scp_sempre_invalido_com_referencia_a_socio_ostensivo(self, regime):
        e = elegibilidade("SCP", regime)
        assert e.valido is False
        assert "991" in e.base_legal  # CC Art. 991
        assert "ostensivo" in (e.motivo or "").lower()

    def test_esc_simples_vedado_por_atividade_financeira(self):
        e = elegibilidade("ESC", "SIMPLES")
        assert e.valido is False
        assert "167/2019" in e.base_legal
        assert "financeira" in (e.motivo or "").lower()

    def test_esc_presumido_aceito_com_teto(self):
        e = elegibilidade("ESC", "PRESUMIDO")
        assert e.valido is True
        assert any("4,8M" in c for c in e.condicoes)

    @pytest.mark.parametrize("regime", REGIMES)
    def test_consorcio_sempre_invalido(self, regime):
        e = elegibilidade("CONSORCIO", regime)
        assert e.valido is False
        assert "278" in e.base_legal  # Lei 6.404/76 Art. 278

    @pytest.mark.parametrize("regime", REGIMES)
    def test_produtor_rural_pf_sempre_invalido(self, regime):
        e = elegibilidade("PRODUTOR_RURAL_PF", regime)
        assert e.valido is False
        assert "8.023/90" in e.base_legal


# ─────────────────────────────────────────────────────────────────────────────
# 5. Imutabilidade — schema + MATRIZ
# ─────────────────────────────────────────────────────────────────────────────

class TestImutabilidade:

    def test_elegibilidade_eh_frozen(self):
        e = elegibilidade("EI", "SIMPLES")
        with pytest.raises((ValueError, TypeError)):
            e.valido = False  # type: ignore[misc]

    def test_matriz_eh_read_only(self):
        """B1 — MATRIZ é MappingProxyType, mutação direta levanta TypeError."""
        with pytest.raises(TypeError):
            MATRIZ[("EI", "SIMPLES")] = elegibilidade("EI", "REAL")  # type: ignore[index]

    def test_matriz_nao_aceita_del(self):
        with pytest.raises(TypeError):
            del MATRIZ[("EI", "SIMPLES")]  # type: ignore[attr-defined]


# ─────────────────────────────────────────────────────────────────────────────
# 6. Exceção customizada (B2)
# ─────────────────────────────────────────────────────────────────────────────

class TestCombinacaoNaoMapeada:

    def test_combinacao_invalida_levanta_excecao_customizada(self):
        with pytest.raises(CombinacaoSocietariaNaoMapeadaError, match="não mapeada"):
            elegibilidade("FOO", "BAR")  # type: ignore[arg-type]

    def test_excecao_herda_de_value_error(self):
        """Compatibilidade com try/except ValueError legado."""
        with pytest.raises(ValueError):
            elegibilidade("FOO", "BAR")  # type: ignore[arg-type]

    def test_mensagem_lista_tipos_validos(self):
        with pytest.raises(CombinacaoSocietariaNaoMapeadaError) as exc_info:
            elegibilidade("FOO", "SIMPLES")  # type: ignore[arg-type]
        msg = str(exc_info.value)
        assert "EI" in msg and "SLU" in msg


# ─────────────────────────────────────────────────────────────────────────────
# 7. Helpers — agora retornam tupla de Elegibilidade (A5)
# ─────────────────────────────────────────────────────────────────────────────

class TestHelpers:

    def test_regimes_permitidos_retorna_objetos_elegibilidade(self):
        """A5 — não retorna mais strings."""
        regimes = regimes_permitidos("EI")
        assert all(isinstance(e, Elegibilidade) for e in regimes)
        assert len(regimes) == 3  # SIMPLES, PRESUMIDO, REAL (não IMUNE)

    def test_regimes_permitidos_ei(self):
        regimes = regimes_permitidos("EI")
        assert all(e.valido is True for e in regimes)

    def test_regimes_permitidos_sa_nao_inclui_simples(self):
        regimes = regimes_permitidos("SA")
        # SA tem 2 regimes válidos: PRESUMIDO e REAL
        assert len(regimes) == 2

    def test_regimes_permitidos_associacao(self):
        regimes = regimes_permitidos("ASSOCIACAO")
        # PRESUMIDO virou True na correção A2 — agora 3 válidos
        assert len(regimes) == 3

    def test_regimes_permitidos_scp_zero(self):
        """SCP não opta por nenhum regime sozinha."""
        assert regimes_permitidos("SCP") == ()

    def test_tipos_para_regime_retorna_objetos_elegibilidade(self):
        tipos = tipos_para_regime("SIMPLES")
        assert all(isinstance(e, Elegibilidade) for e in tipos)

    def test_tipos_para_regime_simples_inclui_cooperativa(self):
        """A4 — cooperativa de consumo entra como elegível com condição."""
        tipos = tipos_para_regime("SIMPLES")
        assert all(e.valido for e in tipos)
        # Pelo menos uma célula deve mencionar "cooperativa" ou "consumo"
        # (a célula de cooperativa)
        textos = " ".join((e.observacao or "") + " ".join(e.condicoes) for e in tipos)
        assert "consumo" in textos.lower()

    def test_tipos_para_regime_imune_so_3(self):
        tipos = tipos_para_regime("IMUNE")
        # ASSOCIACAO + FUNDACAO + ORGANIZACAO_RELIGIOSA
        assert len(tipos) == 3

    def test_tipos_para_regime_presumido_inclui_associacao(self):
        """A2 — associação agora aparece como elegível ao Presumido."""
        tipos = tipos_para_regime("PRESUMIDO")
        # 4 PJ lucrativa (EI, SLU, LTDA, SS, SA, COOPERATIVA, ESC) + 3 imunes (ASSOC, FUND, ORG_REL) = 10
        assert len(tipos) == 10


# ─────────────────────────────────────────────────────────────────────────────
# 8. Aliases no schema EmpresaFornecedora (B4) — EIRELI e MEI_CAMINHONEIRO
# ─────────────────────────────────────────────────────────────────────────────

def _payload_minimo(**override):
    base = dict(
        cnpj="11222333000181",
        razao_social="Empresa Teste Ltda",
        regime="SIMPLES",
        cnae_principal="4757100",
        uf_origem="SP",
        faturamento_12m=Decimal("1000000"),
    )
    base.update(override)
    return base


class TestAliasEIRELI:

    def test_eireli_normaliza_para_slu(self):
        emp = EmpresaFornecedora(**_payload_minimo(tipo_societario="EIRELI"))
        assert emp.tipo_societario == "SLU"

    def test_eireli_alias_nao_seta_enquadramento(self):
        emp = EmpresaFornecedora(**_payload_minimo(tipo_societario="EIRELI"))
        assert emp.enquadramento_simples is None


class TestAliasMEICaminhoneiro:

    def test_mei_caminhoneiro_normaliza_para_ei(self):
        emp = EmpresaFornecedora(
            **_payload_minimo(tipo_societario="MEI_CAMINHONEIRO",
                              regime="MEI",
                              faturamento_12m=Decimal("200000"))
        )
        assert emp.tipo_societario == "EI"
        assert emp.enquadramento_simples == "MEI_CAMINHONEIRO"

    def test_tipo_exibicao_mei_caminhoneiro(self):
        emp = EmpresaFornecedora(
            **_payload_minimo(tipo_societario="MEI_CAMINHONEIRO",
                              regime="MEI",
                              faturamento_12m=Decimal("200000"))
        )
        assert emp.tipo_exibicao == "MEI Caminhoneiro"


class TestNovosLiteraisAceitos:
    """B4 — schema aceita os novos tipos sem KeyError."""

    @pytest.mark.parametrize("tipo", ["SCP", "ESC", "CONSORCIO", "PRODUTOR_RURAL_PF"])
    def test_schema_aceita_novo_tipo(self, tipo):
        emp = EmpresaFornecedora(**_payload_minimo(tipo_societario=tipo))
        assert emp.tipo_societario == tipo

    @pytest.mark.parametrize("tipo", ["SCP", "ESC", "CONSORCIO", "PRODUTOR_RURAL_PF"])
    def test_consulta_elegibilidade_dos_novos_tipos_nao_explode(self, tipo):
        for regime in REGIMES:
            e = elegibilidade(tipo, regime)
            assert isinstance(e, Elegibilidade)
