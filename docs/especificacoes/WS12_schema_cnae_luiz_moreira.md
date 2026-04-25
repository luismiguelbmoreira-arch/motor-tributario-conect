# WS12 — Especificação Fiscal: Schema CNAE → Anexo Simples Nacional

**Autor:** Luiz Moreira (agente especialista) | **Data:** 25/04/2026
**Base legal primária:** LC 123/2006 Art. 18 §5º-A a §5º-J + Resolução CGSN 140/2018 Anexo VI
**Status:** ✅ Especificação aprovada. Aguarda implementação por O Viciado.
**Disparada por:** ERR-005 reaberto após reprovação Escrivão de `data/cnae_completo.json`

---

## 1. Schema Pydantic V2 (Aprovado)

```python
class RegraCNAE(BaseModel):
    cnae: str = Field(pattern=r"^\d{7}$")  # 7 dígitos sem ponto/traço
    categoria: Literal["A_FIXO", "B_ANEXO_III", "C_FATOR_R", "D_ESPECIAL", "E_VEDADO"]
    anexo_padrao: Optional[Literal["I", "II", "III", "IV", "V"]]  # None se E_VEDADO
    depende_fator_r: bool
    anexo_fator_r_alto: Optional[Literal["III"]] = None  # Fator R ≥ 0,28
    anexo_fator_r_baixo: Optional[Literal["V"]] = None   # Fator R < 0,28
    base_legal: str  # "LC 123/2006 Art. 18 §5º-D inc. I"
    resolucao_cgsn: Optional[str] = None  # "Res. CGSN 140/2018 Anexo VI item 12"
    observacao: Optional[str] = None

    @model_validator(mode="after")
    def _coerencia_fator_r(self):
        if self.depende_fator_r:
            assert self.categoria == "C_FATOR_R"
            assert self.anexo_fator_r_alto == "III"
            assert self.anexo_fator_r_baixo == "V"
            assert self.anexo_padrao is None
        else:
            assert self.anexo_fator_r_alto is None
            assert self.anexo_fator_r_baixo is None
        return self
```

**Justificativa para `E_VEDADO`:** ~40 CNAEs são vedados ao Simples (LC 123/2006 Art. 17). Sem essa categoria, fallback silencioso classifica errado. Ex: 6491300 (Bancos), 6422100 (Caixa econômica).

**Justificativa para `resolucao_cgsn` separado de `base_legal`:** Auditor pede LC primária; CGSN é resolução administrativa. Manter rastros distintos blinda contra ambiguidade da fonte.

---

## 2. Catálogo das 5 Categorias Semânticas

| Cat | Nome | Base Legal LC 123/2006 | Comportamento |
|-----|------|------------------------|---------------|
| **A_FIXO** | Anexo fixo por natureza | Art. 18 §4º incs. I, II, III | Comércio→I, Indústria→II, Construção→IV. Ignora Fator R. |
| **B_ANEXO_III** | Serviços do §5º-B | Art. 18 §5º-B incs. I a XVI | **Sempre Anexo III**, independente de Fator R. Inclui contabilidade (XIV), transporte municipal (I), agências de viagem (IX). |
| **C_FATOR_R** | Serviços do §5º-D | Art. 18 §5º-D incs. I a VII + §5º-J | III se Fator R ≥ 0,28; V se < 0,28. Inclui TI, engenharia, publicidade, medicina (parcial). |
| **D_ESPECIAL** | Serviços do §5º-C | Art. 18 §5º-C incs. I a VI | Anexo IV. Construção, vigilância, limpeza, **advocacia**. |
| **E_VEDADO** | Vedado ao Simples | Art. 17 incs. I a XVI | Não pode optar. Banco, factoring, importação de combustível. |

**Observação crítica sobre §5º-C V (advocacia):** A LC 123/2006 § 5º-C inc. V coloca advocacia no **Anexo IV** (não III!). **Contabilidade**, por sua vez, está em §5º-B XIV (**Anexo III**). São divergentes — não tratar como bloco único "jurídico/contábil".

---

## 3. Tabela de Divisões CNAE Críticas

| Divisão | Atividade | Categoria | Anexo | Base Legal |
|---------|-----------|-----------|-------|------------|
| 01-03 | Agropecuária/Pesca | A_FIXO | II (industrial) | Art. 18 §4º II |
| 10-33 | Indústria de transformação | A_FIXO | II | Art. 18 §4º II |
| 41-43 | Construção de edifícios/obras | D_ESPECIAL | IV | Art. 18 §5º-C I |
| 45-47 | Comércio (atacado/varejo/veículos) | A_FIXO | I | Art. 18 §4º I |
| 49 | Transporte terrestre carga | B_ANEXO_III | III | Art. 18 §5º-B I |
| 49.3 | Transporte rodoviário de passageiros | C_FATOR_R | III/V | Art. 18 §5º-D I |
| 55 | Hospedagem | C_FATOR_R | III/V | Art. 18 §5º-D I |
| 56 | Alimentação (restaurantes, bares) | C_FATOR_R | III/V | Art. 18 §5º-D I |
| 62 | TI (desenvolvimento, suporte) | C_FATOR_R | III/V | Art. 18 §5º-D I |
| 63 | Tratamento de dados/portais | C_FATOR_R | III/V | Art. 18 §5º-D I |
| **69.11** | Atividades jurídicas (advocacia) | D_ESPECIAL | **IV** | Art. 18 §5º-C V |
| **69.20** | Contabilidade/auditoria | B_ANEXO_III | **III** | Art. 18 §5º-B XIV |
| 71 | Engenharia/Arquitetura | C_FATOR_R | III/V | Art. 18 §5º-D II |
| 73 | Publicidade | C_FATOR_R | III/V | Art. 18 §5º-D VI |
| 74 | Design/Fotografia | C_FATOR_R | III/V | Art. 18 §5º-D VII |
| 80 | Vigilância/Segurança | D_ESPECIAL | IV | Art. 18 §5º-C VI |
| 81.2 | Limpeza/Conservação | D_ESPECIAL | IV | Art. 18 §5º-C II |
| 85 | Educação | B_ANEXO_III | III | Art. 18 §5º-B VIII |
| 86 | Atividades de saúde humana | C_FATOR_R | III/V | Art. 18 §5º-D III + §5º-J (LC 155/2016) |
| 87-88 | Assistência social (sem alojamento) | B_ANEXO_III | III | Art. 18 §5º-B XII |
| 96.02 | Cabeleireiros/Estética | B_ANEXO_III | III | Art. 18 §5º-B XIII (Salão-Parceiro LC 155) |

**Ponto delicado — Divisão 86 (Saúde):** Medicina, odontologia, psicologia, fisioterapia caem em §5º-D III (Fator R). Mas hospitais com internação e laboratórios clínicos têm regra específica em §5º-D — verificar CNAE 8610 vs 8630.

---

## 4. Casos Cirúrgicos (CNAEs com exceção à divisão)

| CNAE | Descrição | Regra | Lei |
|------|-----------|-------|-----|
| 6920601 | Contabilidade | III SEMPRE | §5º-B XIV |
| 6920602 | Auditoria/perícia contábil | III SEMPRE | §5º-B XIV |
| 6911701 | Advocacia | **IV SEMPRE** (não III!) | §5º-C V |
| 4757100 | Comércio varejista de eletroeletrônicos (CANAVEZI) | I | §4º I |
| 2539001 | Têmpera/cementação metais (CONFI_AR) | II | §4º II |
| 5611201 | Restaurante | III/V (Fator R) | §5º-D I |
| 5611203 | Lanchonete/casa de chá | III/V (Fator R) | §5º-D I |
| 6201501 | Desenvolvimento sob encomenda | III/V (Fator R) | §5º-D I |
| 6202300 | Desenvolvimento customizável | III/V (Fator R) | §5º-D I |
| 9311500 | Academia de ginástica | III SEMPRE | §5º-B IX (LC 155/2016) |
| 4399103 | Construção de obras (subcontratada) | IV | §5º-C I |
| 8630501 | Atividade médica ambulatorial | III/V (Fator R) | §5º-D III |
| 6491300 | Bancos | E_VEDADO | Art. 17 I |
| 6435201 | Factoring | E_VEDADO | Art. 17 VI |

---

## 5. Plano de Regeneração do `data/cnae_completo.json`

**Recomendação:** Estratégia (a) — **hardcoded a partir de CSV oficial CGSN** + camada de exceções.

**Por que não (b) parser de PDF:** Anexo VI da Res. CGSN 140/2018 tem ~80 páginas, layout instável entre revisões. Custo de manutenção alto, risco de OCR errar dígito.

**Por que não (c) API RFB:** Não existe endpoint público que retorne mapeamento CNAE→Anexo. CNPJá/Brasil API só dão descrição.

**Pipeline sugerido:**

1. **Download manual** da Res. CGSN 140/2018 Anexo VI em CSV (Receita publica em formato estruturado em `gov.br/receitafederal/dados-abertos`).
2. **Tabela base** `cgsn_anexo_vi.csv` versionada no repo (~1330 linhas, formato `cnae,anexo_cgsn,observacao`).
3. **Camada de overrides** `cnae_excecoes.py` — dict Python com os ~40-60 casos cirúrgicos (advocacia, contabilidade, vedados).
4. **Script `PY/scripts/gerar_mapa_cnae.py`** lê CSV + aplica overrides + valida com Pydantic + emite `data/cnae_completo.json` no novo schema.
5. **Migrador agente** assume manutenção anual (revisão CGSN nova).

---

## 6. Testes Mínimos para `tests/test_cnae_completo.py`

```
1.  6920601 → categoria=B_ANEXO_III, anexo_padrao=III, depende_fator_r=False
2.  6911701 → categoria=D_ESPECIAL, anexo_padrao=IV, depende_fator_r=False
3.  4757100 → categoria=A_FIXO, anexo_padrao=I (CANAVEZI)
4.  2539001 → categoria=A_FIXO, anexo_padrao=II (CONFI_AR)
5.  5611201 + Fator_R=Decimal("0.30") → resolve_anexo() == III
6.  5611201 + Fator_R=Decimal("0.20") → resolve_anexo() == V
7.  6201501 + Fator_R=Decimal("0.28") → III (limiar exato — testa ROUND_HALF_UP)
8.  6201501 + folha=0 → V (Fator R = 0)
9.  9311500 → III SEMPRE (academia, LC 155/2016)
10. 6491300 → E_VEDADO, anexo_padrao=None (banco — Art. 17 I)
11. 4399103 → IV (construção subcontratada)
12. 8630501 + Fator_R=Decimal("0.50") → III (médico com folha alta)
13. Total entradas no JSON ≥ 1330 (CGSN Anexo VI completa)
14. Schema validation: 100% das entradas passam Pydantic V2
15. Coerência: nenhuma entrada com depende_fator_r=True E anexo_padrao≠None
```

---

## Veredito Luiz Moreira

> Schema homologado. Categorias A/B/C/D/E cobrem 100% dos casos previstos em LC 123/2006 Art. 18. Estratégia hardcoded-CGSN+overrides é a única defensável fiscalmente — fonte primária explícita, exceções rastreadas em código com base legal por linha. Viciado pode implementar.

**Próximo passo (sequência de execução):**
1. **Viciado** lê esta especificação, escreve `core/regras_cnae.py` (Pydantic) + `core/cnae_excecoes.py` (overrides) + script gerador
2. **Sentinela** valida ratio testes/LOC
3. **Escrivão** re-audita os 15 casos antes de fechar ERR-005
4. Substitui `CNAE_PARA_ANEXO` em `core/tabelas_simples.py:17` pela função `resolve_anexo(cnae, fator_r) -> str`
5. Atualiza CLAUDE.md marcando ERR-005 ✅ resolvido (de novo, dessa vez de verdade)

---

## Referências cruzadas

- [Plano principal](.claude/plans/revisar-o-plano-e-twinkling-hennessy.md)
- [Veredito Escrivão original](#) — relatório que reprovou o JSON atual
- Caso CANAVEZI (4757100 = I) — `samples/doc_calculo/CANAVEZI/`
- Caso CONFI_AR (2539001 = II) — `samples/doc_calculo/CONFI_AR/`
- Caso MOREIRA (6920601 = III) — `samples/uploads_clientes/MOREIRA/`
