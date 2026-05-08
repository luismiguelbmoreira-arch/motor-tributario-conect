# -*- coding: utf-8 -*-
"""
tests/test_refazer_calculo.py — WS5 (Rail R6 — logs refazíveis)

`refazer_calculo.verificar_diagnostico()` é função pura que recebe o dict
resultado (com trilha_auditoria) e devolve RelatorioVerificacao frozen
verificando:

  1. Estrutura mínima: todo evento tem tipo, id, timestamp (MAX_01)
  2. Citação legal: todo evento (exceto certos) tem amparo_legal não-vazio (MAX_02)
  3. Aritmética: eventos CALCULO com memoria parseable como Decimal são
     recalculados ((base - deducoes) * aliquota) e comparados com
     valor_final dentro de tolerância de centavos
  4. Sem violações de segurança: trilha não pode conter VIOLACAO_SEGURANCA
     (Camada 2 — Guard Clause acionada = diagnóstico inválido)

Rail R6: "Cada cálculo gera log auto-suficiente. refazer_calculo.py
reconstroi o número apenas do log."

Rode com: pytest PY/tests/test_refazer_calculo.py -v
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.refazer import (  # noqa: E402
    DivergenciaCalculo,
    RelatorioVerificacao,
    StatusVerificacao,
    verificar_diagnostico,
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — fábrica de eventos canônicos
# ─────────────────────────────────────────────────────────────────────────────

def _calculo(
    *,
    id: str = "PASSO_X",
    base: str = "100000.00",
    deducoes: str = "0",
    aliquota: str = "0.10",
    valor_final: str = "10000.00",
    amparo: str = "LC 123/2006 Art. 18",
) -> dict:
    return {
        "tipo": "CALCULO",
        "id": id,
        "titulo": id,
        "formula": f"Base [{base}] - Deduções [{deducoes}] * Alíquota [{aliquota}] = {valor_final}",
        "memoria": {
            "base": base,
            "deducoes": deducoes,
            "aliquota": aliquota,
            "valor_final": valor_final,
        },
        "amparo_legal": amparo,
        "detalhe": "",
        "timestamp": "2027-06-15T10:00:00",
    }


def _alerta(
    *,
    id: str = "ALERTA_TESTE",
    amparo: str = "LC 214/2025 Art. X",
) -> dict:
    return {
        "tipo": "ALERTA_GENERICO",
        "id": id,
        "titulo": id,
        "detalhe": "alerta de teste",
        "amparo_legal": amparo,
        "timestamp": "2027-06-15T10:00:01",
    }


def _resultado(trilha: list) -> dict:
    return {
        "regime": "PRESUMIDO",
        "trilha_auditoria": trilha,
        "motor_versao": "1.3.0",
    }


# ─────────────────────────────────────────────────────────────────────────────
# CASO FELIZ
# ─────────────────────────────────────────────────────────────────────────────

class TestRefazerCalculoCasoFeliz:
    """Diagnóstico consistente — tudo bate."""

    def test_diagnostico_consistente_retorna_consistente_true(self):
        trilha = [
            _calculo(id="PASSO_1", base="100000", deducoes="0", aliquota="0.10", valor_final="10000.00"),
            _calculo(id="PASSO_2", base="50000", deducoes="5000", aliquota="0.20", valor_final="9000.00"),
        ]
        r = verificar_diagnostico(_resultado(trilha))
        assert isinstance(r, RelatorioVerificacao)
        assert r.consistente is True
        assert r.divergencias == ()
        assert r.violacoes_seguranca == ()

    def test_total_eventos_bate(self):
        trilha = [_calculo(id=f"P{i}") for i in range(5)] + [_alerta(id="A1")]
        r = verificar_diagnostico(_resultado(trilha))
        assert r.total_eventos == 6
        assert r.por_tipo.get("CALCULO") == 5
        assert r.por_tipo.get("ALERTA_GENERICO") == 1


# ─────────────────────────────────────────────────────────────────────────────
# DIVERGÊNCIA ARITMÉTICA
# ─────────────────────────────────────────────────────────────────────────────

class TestRefazerCalculoDivergencia:
    """Quando valor_final declarado ≠ recalculado."""

    def test_divergencia_acima_da_tolerancia_eh_reportada(self):
        # (100000 - 0) * 0.10 = 10000.00, mas trilha declara 12000.00
        trilha = [_calculo(base="100000", deducoes="0", aliquota="0.10", valor_final="12000.00")]
        r = verificar_diagnostico(_resultado(trilha))
        assert r.consistente is False
        assert len(r.divergencias) == 1
        d = r.divergencias[0]
        assert isinstance(d, DivergenciaCalculo)
        assert d.esperado_recalculado == Decimal("10000.00")
        assert d.declarado == Decimal("12000.00")

    def test_divergencia_dentro_da_tolerancia_passa(self):
        # Tolerância default: R$ 0,02. Diferença de R$ 0,01 = MATCH.
        trilha = [_calculo(base="100000", deducoes="0", aliquota="0.10", valor_final="10000.01")]
        r = verificar_diagnostico(_resultado(trilha))
        assert r.consistente is True
        assert r.divergencias == ()


# ─────────────────────────────────────────────────────────────────────────────
# NÃO-VERIFICÁVEL AUTOMATICAMENTE — fórmula composta
# ─────────────────────────────────────────────────────────────────────────────

class TestRefazerCalculoNaoVerificavel:
    """Quando memoria não tem Decimals limpos (alíquota textual etc.)."""

    def test_aliquota_textual_marca_nao_verificavel(self):
        # IMUNE registra "aliquota": "0,0% IBS + 0,0% CBS (imune)"
        evento = _calculo()
        evento["memoria"]["aliquota"] = "0,0% IBS + 0,0% CBS (imune)"
        r = verificar_diagnostico(_resultado([evento]))
        assert r.consistente is True  # não bloqueia
        # Aparece em "nao_verificaveis", não em "divergencias"
        assert len(r.nao_verificaveis) == 1
        assert r.nao_verificaveis[0].id == evento["id"]

    def test_base_puramente_textual_marca_nao_verificavel(self):
        # Texto sem número final extraível: parser BR não consegue
        evento = _calculo()
        evento["memoria"]["base"] = "Imunidade integral (LC 214 Art. 9º caput)"
        r = verificar_diagnostico(_resultado([evento]))
        assert r.consistente is True
        assert len(r.nao_verificaveis) == 1


# ─────────────────────────────────────────────────────────────────────────────
# AMPARO LEGAL OBRIGATÓRIO (MAX_02)
# ─────────────────────────────────────────────────────────────────────────────

class TestRefazerCalculoAmparoLegal:
    """Todo evento (exceto VIOLACAO) deve citar amparo_legal."""

    def test_evento_sem_amparo_legal_eh_reportado(self):
        evento = _calculo(amparo="")
        r = verificar_diagnostico(_resultado([evento]))
        assert r.consistente is False
        assert len(r.eventos_sem_amparo) == 1
        assert r.eventos_sem_amparo[0] == evento["id"]

    def test_violacao_sem_amparo_nao_bloqueia_amparo(self):
        # VIOLACAO_SEGURANCA já indica falha — não exige amparo extra
        evento = {
            "tipo": "VIOLACAO_SEGURANCA",
            "id": "VIOLACAO_X",
            "titulo": "Guard Clause",
            "amparo_legal": "",
            "timestamp": "...",
        }
        r = verificar_diagnostico(_resultado([evento]))
        # Mas a presença da violação faz consistente=False
        assert r.consistente is False
        assert len(r.violacoes_seguranca) == 1


# ─────────────────────────────────────────────────────────────────────────────
# VIOLAÇÃO DE SEGURANÇA
# ─────────────────────────────────────────────────────────────────────────────

class TestRefazerCalculoViolacao:
    """VIOLACAO_SEGURANCA invalida o diagnóstico."""

    def test_violacao_seguranca_marca_inconsistente(self):
        evento = {
            "tipo": "VIOLACAO_SEGURANCA",
            "id": "VIOLACAO_LucroPresumidoEngine_SIMPLES",
            "titulo": "Guard Clause",
            "amparo_legal": "LC 123 Art. 13",
            "memoria": {"regime_empresa": "SIMPLES"},
            "timestamp": "...",
        }
        r = verificar_diagnostico(_resultado([evento]))
        assert r.consistente is False
        assert len(r.violacoes_seguranca) == 1


# ─────────────────────────────────────────────────────────────────────────────
# ESTRUTURA MÍNIMA (MAX_01)
# ─────────────────────────────────────────────────────────────────────────────

class TestRefazerCalculoEstrutura:
    """Eventos mal-formados são reportados sem quebrar."""

    def test_evento_sem_id_eh_reportado(self):
        evento = _calculo()
        del evento["id"]
        r = verificar_diagnostico(_resultado([evento]))
        assert r.consistente is False
        assert len(r.eventos_malformados) == 1

    def test_trilha_vazia_consistente(self):
        # Engine não chamado, trilha vazia: tecnicamente consistente
        # (sem cálculo pra verificar). Caller decide se trilha vazia
        # é negócio aceitável.
        r = verificar_diagnostico(_resultado([]))
        assert r.total_eventos == 0
        # Sem CALCULO, sem divergência, sem violação → consistente
        assert r.consistente is True

    def test_resultado_sem_trilha_auditoria_levanta_erro(self):
        with pytest.raises(KeyError, match="trilha_auditoria"):
            verificar_diagnostico({"regime": "SIMPLES"})


# ─────────────────────────────────────────────────────────────────────────────
# IMUTABILIDADE
# ─────────────────────────────────────────────────────────────────────────────

class TestRefazerCalculoImutabilidade:
    """RelatorioVerificacao é frozen."""

    def test_relatorio_e_frozen(self):
        r = verificar_diagnostico(_resultado([_calculo()]))
        with pytest.raises(Exception):
            r.consistente = False  # type: ignore[misc]

    def test_divergencias_e_tuple(self):
        r = verificar_diagnostico(_resultado([]))
        assert isinstance(r.divergencias, tuple)
        assert isinstance(r.violacoes_seguranca, tuple)
        assert isinstance(r.nao_verificaveis, tuple)
        assert isinstance(r.eventos_sem_amparo, tuple)
        assert isinstance(r.eventos_malformados, tuple)


# ─────────────────────────────────────────────────────────────────────────────
# STATUS POR EVENTO (renderização)
# ─────────────────────────────────────────────────────────────────────────────

class TestRefazerCalculoStatusPorEvento:
    """Cada evento ganha status_verificacao individual."""

    def test_status_match_quando_aritmetica_bate(self):
        trilha = [_calculo(base="100", deducoes="0", aliquota="0.5", valor_final="50.00")]
        r = verificar_diagnostico(_resultado(trilha))
        s = r.status_por_evento[0]
        assert isinstance(s, StatusVerificacao)
        assert s.status == "MATCH"

    def test_status_divergencia_quando_aritmetica_nao_bate(self):
        trilha = [_calculo(base="100", deducoes="0", aliquota="0.5", valor_final="80.00")]
        r = verificar_diagnostico(_resultado(trilha))
        s = r.status_por_evento[0]
        assert s.status == "DIVERGENCIA"

    def test_status_nao_verificavel_quando_textual(self):
        e = _calculo()
        e["memoria"]["aliquota"] = "0,0% (imune)"
        trilha = [e]
        r = verificar_diagnostico(_resultado(trilha))
        s = r.status_por_evento[0]
        assert s.status == "NAO_VERIFICAVEL_AUTOMATICO"

    def test_status_violacao_quando_seguranca(self):
        e = {
            "tipo": "VIOLACAO_SEGURANCA",
            "id": "V",
            "titulo": "X",
            "amparo_legal": "lei",
            "timestamp": "t",
        }
        r = verificar_diagnostico(_resultado([e]))
        s = r.status_por_evento[0]
        assert s.status == "VIOLACAO"


# ─────────────────────────────────────────────────────────────────────────────
# PARSER BR — R$ / % / vírgula decimal / ponto milhar
# Achado PMD: motor real grava memoria narrativa ("R$ 100.000,00", "8.90%")
# Sem parser BR, 100% dos CALCULOs reais ficavam NAO_VERIFICAVEL.
# ─────────────────────────────────────────────────────────────────────────────

class TestRefazerCalculoParserBR:
    """Parser deve reconhecer formatos do motor: R$, %, vírgula BR, milhar."""

    def test_split_payment_real_recalcula_correto(self):
        # Caso real do motor (PMD output): SPLIT_PAYMENT
        # base="Valor NF R$ 100.000,00" aliq="8.90%" valor="R$ 8.900,00"
        evento = {
            "tipo": "CALCULO",
            "id": "SPLIT_PAYMENT",
            "titulo": "Split Payment",
            "formula": "...",
            "memoria": {
                "base": "Valor NF R$ 100.000,00",
                "deducoes": "0",
                "aliquota": "8.90%",
                "valor_final": "R$ 8.900,00",
            },
            "amparo_legal": "LC 214/2025 Art. 353",
            "timestamp": "2027-06-15T10:00:00",
        }
        r = verificar_diagnostico(_resultado([evento]))
        # Aritmética bate: 100000 * 0.089 = 8900
        assert r.consistente is True
        s = r.status_por_evento[0]
        assert s.status == "MATCH"

    def test_valores_brasileiros_simples_recalculam(self):
        # Motor às vezes usa formato BR puro: "R$ 1.000.000,00"
        evento = _calculo(
            base="R$ 1.000.000,00",
            deducoes="R$ 0,00",
            aliquota="0,10",
            valor_final="R$ 100.000,00",
        )
        r = verificar_diagnostico(_resultado([evento]))
        assert r.consistente is True

    def test_aliquota_percentual_dividida_por_cem(self):
        # "8.90%" deve virar Decimal("0.089"), não Decimal("8.90")
        evento = _calculo(
            base="100",
            deducoes="0",
            aliquota="8.90%",
            valor_final="8.90",  # 100 * 0.089 = 8.9
        )
        r = verificar_diagnostico(_resultado([evento]))
        assert r.consistente is True

    def test_n_a_marca_nao_verificavel(self):
        # aliquota="N/A" é sentinela do motor pra eventos não-aritméticos
        # (ex: DECISAO_ANEXO). Não pode virar DIVERGENCIA.
        evento = _calculo(aliquota="N/A", valor_final="Anexo III")
        r = verificar_diagnostico(_resultado([evento]))
        # Não verificável → consistente
        assert r.consistente is True
        assert len(r.nao_verificaveis) == 1

    def test_anexo_como_valor_marca_nao_verificavel(self):
        evento = _calculo()
        evento["memoria"]["valor_final"] = "Anexo III"
        evento["memoria"]["aliquota"] = "N/A"
        r = verificar_diagnostico(_resultado([evento]))
        assert r.consistente is True
        assert len(r.nao_verificaveis) == 1

    def test_status_textual_marca_nao_verificavel(self):
        # MAX_FISCAL_03: aliquota="Configurada por Data" valor="Status: TESTE"
        evento = _calculo(
            base="Ano 2027",
            deducoes="N/A",
            aliquota="Configurada por Data",
            valor_final="Status: TESTE",
        )
        r = verificar_diagnostico(_resultado([evento]))
        assert r.consistente is True
        assert len(r.nao_verificaveis) == 1

    def test_milhar_brasileiro_com_vargem_decimal(self):
        # 1.234,56 → Decimal("1234.56")
        evento = _calculo(
            base="R$ 1.234,56",
            deducoes="0",
            aliquota="0,5",
            valor_final="R$ 617,28",  # 1234.56 * 0.5
        )
        r = verificar_diagnostico(_resultado([evento]))
        assert r.consistente is True


# ─────────────────────────────────────────────────────────────────────────────
# CLI WRAPPER (scripts/refazer_calculo.py) com --input-file (bypass DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestRefazerCalculoCLI:
    """CLI wrapper aceita --input-file pra auditoria offline."""

    def _import_cli(self):
        # Import lazy do módulo do script — evita SQLAlchemy nos demais testes
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "scripts.refazer_calculo",
            os.path.join(os.path.dirname(__file__), "..", "scripts", "refazer_calculo.py"),
        )
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        return modulo

    def test_cli_input_file_diagnostico_consistente_exit_code_0(self, tmp_path):
        cli = self._import_cli()
        import json

        diag_path = tmp_path / "diag.json"
        diag_path.write_text(
            json.dumps(_resultado([_calculo()])),
            encoding="utf-8",
        )

        rc = cli.main([
            "--diagnostico-id", "1",
            "--input-file", str(diag_path),
        ])
        assert rc == 0

    def test_cli_input_file_divergencia_exit_code_1(self, tmp_path):
        cli = self._import_cli()
        import json

        diag_path = tmp_path / "diag.json"
        diag_path.write_text(
            json.dumps(_resultado([_calculo(
                base="100", deducoes="0", aliquota="0.5", valor_final="80.00",
            )])),
            encoding="utf-8",
        )
        rc = cli.main([
            "--diagnostico-id", "1",
            "--input-file", str(diag_path),
        ])
        assert rc == 1

    def test_cli_input_file_inexistente_exit_code_2(self, tmp_path):
        cli = self._import_cli()
        rc = cli.main([
            "--diagnostico-id", "1",
            "--input-file", str(tmp_path / "nao_existe.json"),
        ])
        assert rc == 2

    def test_cli_strict_com_nao_verificavel_exit_code_1(self, tmp_path):
        cli = self._import_cli()
        import json

        evento = _calculo()
        evento["memoria"]["aliquota"] = "0,0% (imune)"
        diag_path = tmp_path / "diag.json"
        diag_path.write_text(
            json.dumps(_resultado([evento])),
            encoding="utf-8",
        )
        rc = cli.main([
            "--diagnostico-id", "1",
            "--input-file", str(diag_path),
            "--strict",
        ])
        assert rc == 1

    def test_cli_output_arquivo_gera_json(self, tmp_path):
        cli = self._import_cli()
        import json

        diag_path = tmp_path / "diag.json"
        diag_path.write_text(
            json.dumps(_resultado([_calculo()])),
            encoding="utf-8",
        )
        out_path = tmp_path / "rel.json"
        cli.main([
            "--diagnostico-id", "1",
            "--input-file", str(diag_path),
            "--output", str(out_path),
        ])
        assert out_path.exists()
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["relatorio"]["consistente"] is True
        assert payload["diagnostico_id"] == 1
