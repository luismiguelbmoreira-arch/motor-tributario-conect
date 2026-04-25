# -*- coding: utf-8 -*-
"""
test_empresa_fornecedora_societario.py — Testes WS6 Etapa 1

Cobre:
  - Campos novos (tipo_societario, qualificacoes_especiais, enquadramento_simples)
  - Alias MEI: tipo_societario="MEI" -> EI + enquadramento_simples=MEI
  - Computed property tipo_exibicao
  - Compatibilidade: chamadas legadas sem os campos novos continuam válidas
  - Combinações reais: ASSOCIACAO + [OSCIP, CEBAS]
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas.motor import EmpresaFornecedora


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


# ─────────────────────────────────────────────────────────────────────────────
# 1. Compatibilidade — chamadas legadas continuam válidas
# ─────────────────────────────────────────────────────────────────────────────

class TestCompatibilidadeLegada:

    def test_payload_minimo_sem_campos_novos_continua_valido(self):
        emp = EmpresaFornecedora(**_payload_minimo())
        assert emp.tipo_societario is None
        assert emp.qualificacoes_especiais == []
        assert emp.enquadramento_simples is None

    def test_tipo_exibicao_none_quando_sem_dados_societarios(self):
        emp = EmpresaFornecedora(**_payload_minimo())
        assert emp.tipo_exibicao is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Tipos societários — armazenamento direto
# ─────────────────────────────────────────────────────────────────────────────

class TestTipoSocietarioDireto:

    def test_ltda_armazenado(self):
        emp = EmpresaFornecedora(**_payload_minimo(tipo_societario="LTDA"))
        assert emp.tipo_societario == "LTDA"
        assert emp.enquadramento_simples is None
        assert emp.tipo_exibicao == "LTDA"

    def test_sa_armazenado(self):
        emp = EmpresaFornecedora(**_payload_minimo(tipo_societario="SA"))
        assert emp.tipo_societario == "SA"

    def test_associacao_armazenada(self):
        emp = EmpresaFornecedora(**_payload_minimo(tipo_societario="ASSOCIACAO"))
        assert emp.tipo_societario == "ASSOCIACAO"

    def test_organizacao_religiosa(self):
        emp = EmpresaFornecedora(**_payload_minimo(tipo_societario="ORGANIZACAO_RELIGIOSA"))
        assert emp.tipo_societario == "ORGANIZACAO_RELIGIOSA"

    def test_tipo_invalido_rejeitado(self):
        with pytest.raises((ValueError,)):
            EmpresaFornecedora(**_payload_minimo(tipo_societario="ONG"))  # ONG não é categoria

    def test_tipo_invalido_oscip_rejeitado(self):
        """OSCIP não é tipo societário, é qualificação."""
        with pytest.raises((ValueError,)):
            EmpresaFornecedora(**_payload_minimo(tipo_societario="OSCIP"))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Alias MEI — UX-friendly, storage correto
# ─────────────────────────────────────────────────────────────────────────────

class TestAliasMEI:

    def test_alias_mei_normaliza_para_ei_mais_enquadramento(self):
        emp = EmpresaFornecedora(
            **_payload_minimo(tipo_societario="MEI", regime="MEI",
                              faturamento_12m=Decimal("60000"))
        )
        assert emp.tipo_societario == "EI"
        assert emp.enquadramento_simples == "MEI"

    def test_tipo_exibicao_volta_mei_quando_enquadramento_eh_mei(self):
        emp = EmpresaFornecedora(
            **_payload_minimo(tipo_societario="MEI", regime="MEI",
                              faturamento_12m=Decimal("60000"))
        )
        assert emp.tipo_exibicao == "MEI"

    def test_alias_mei_nao_sobrescreve_enquadramento_explicito(self):
        """Se caller passar enquadramento_simples explícito, respeitar."""
        emp = EmpresaFornecedora(
            **_payload_minimo(tipo_societario="MEI",
                              enquadramento_simples="MEI",
                              regime="MEI",
                              faturamento_12m=Decimal("60000"))
        )
        assert emp.enquadramento_simples == "MEI"

    def test_ei_sem_alias_nao_seta_enquadramento(self):
        """EI direto não dispara o alias — caller controla enquadramento."""
        emp = EmpresaFornecedora(**_payload_minimo(tipo_societario="EI"))
        assert emp.tipo_societario == "EI"
        assert emp.enquadramento_simples is None
        assert emp.tipo_exibicao == "EI"

    def test_ei_com_enquadramento_me(self):
        emp = EmpresaFornecedora(
            **_payload_minimo(tipo_societario="EI", enquadramento_simples="ME")
        )
        assert emp.tipo_societario == "EI"
        assert emp.enquadramento_simples == "ME"
        assert emp.tipo_exibicao == "EI"  # ME não muda display, só MEI


# ─────────────────────────────────────────────────────────────────────────────
# 4. Qualificações especiais — combinações reais
# ─────────────────────────────────────────────────────────────────────────────

class TestQualificacoesEspeciais:

    def test_associacao_com_oscip(self):
        emp = EmpresaFornecedora(
            **_payload_minimo(tipo_societario="ASSOCIACAO",
                              qualificacoes_especiais=["OSCIP"])
        )
        assert emp.qualificacoes_especiais == ["OSCIP"]

    def test_associacao_com_oscip_e_cebas(self):
        """Caso real: Pastoral da Criança = ASSOCIACAO + OSCIP + CEBAS."""
        emp = EmpresaFornecedora(
            **_payload_minimo(tipo_societario="ASSOCIACAO",
                              qualificacoes_especiais=["OSCIP", "CEBAS"])
        )
        assert "OSCIP" in emp.qualificacoes_especiais
        assert "CEBAS" in emp.qualificacoes_especiais

    def test_qualificacao_invalida_rejeitada(self):
        with pytest.raises((ValueError,)):
            EmpresaFornecedora(
                **_payload_minimo(tipo_societario="ASSOCIACAO",
                                  qualificacoes_especiais=["FOO"])
            )

    def test_qualificacoes_default_lista_vazia(self):
        emp = EmpresaFornecedora(**_payload_minimo(tipo_societario="LTDA"))
        assert emp.qualificacoes_especiais == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. Enquadramento Simples — porte/MEI explícito
# ─────────────────────────────────────────────────────────────────────────────

class TestEnquadramentoSimples:

    def test_me_aceito(self):
        emp = EmpresaFornecedora(
            **_payload_minimo(tipo_societario="LTDA", enquadramento_simples="ME",
                              faturamento_12m=Decimal("300000"))
        )
        assert emp.enquadramento_simples == "ME"

    def test_epp_aceito(self):
        emp = EmpresaFornecedora(
            **_payload_minimo(tipo_societario="LTDA", enquadramento_simples="EPP",
                              faturamento_12m=Decimal("4000000"))
        )
        assert emp.enquadramento_simples == "EPP"

    def test_enquadramento_invalido_rejeitado(self):
        with pytest.raises((ValueError,)):
            EmpresaFornecedora(
                **_payload_minimo(tipo_societario="LTDA",
                                  enquadramento_simples="GIGANTE")
            )
