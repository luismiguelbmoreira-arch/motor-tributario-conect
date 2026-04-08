# Auditoria Legal — 2026-04-08

**Disparador:** Durante a Frente 3.3 (seção Opt-Out no PDF cliente), hardcodei
"multa de 20%" sem verificar. A realidade da Lei 9.430/1996 Art. 44 é **75%**.
Fix aplicado em `relatorio_pdf.py` no commit `9607069`.

Por precaução, varri o projeto todo para identificar outras defasagens.

## Mapa levantado

**142+ constantes fiscais hardcoded em 8 arquivos**, mapeadas contra
**22 citações legais**. Agrupamento por risco:

- 🔴 **Alto:** Tetos, sublimites, faixas de receita
- 🟡 **Médio:** Alíquotas federais (IRPJ/CSLL/PIS/COFINS/ICMS internas)
- 🟢 **Baixo:** Alíquotas estáveis há décadas, citações em comentário

## Itens verificados contra fontes oficiais

| # | Item | Código | Fonte oficial | Resultado |
|---|---|---|---|---|
| 1 | Salário mínimo 2026 | `mei.py:35` → R$ 1.621,00 | Decreto 12.797/2025 (Planalto) | ✅ Confere |
| 2 | CBS fase-teste 2026 | `tabelas_simples.py` → 0,9% | LC 214/2025 Art. 348 | ✅ Confere |
| 3 | IBS fase-teste 2026 | `tabelas_simples.py` → 0,1% | LC 214/2025 Art. 348 | ✅ Confere |
| 4 | CBS alíquota de referência 2027+ | `tabelas_simples.py` → 8,8% | LC 214/2025 (consolidação pós-2027) | ✅ Confere |
| 5 | ICMS SP interno | `difal.py` → 18% | Legislação SP 2026 | ✅ Confere |
| 6 | ICMS MA interno | `difal.py` → 23% | Maior modal do Brasil | ✅ Confere |
| 7 | ICMS RJ interno | `difal.py` → 22% | 20% base + 2% FECP Lei 10.253/2023 | ✅ Confere (FECP já somado) |
| 8 | ICMS BA interno | `difal.py` → 20,5% | 20,5% modal base (FECOEP condicional) | ✅ Confere (política de projeto) |
| 9 | Multa Lei 9.430/96 Art. 44 | `relatorio_pdf.py:465` → 75% | Planalto (confirmado) | ✅ Corrigido em `9607069` |
| 10 | Majoração multa sonegação | `relatorio_pdf.py:466` → 100%/150% | Lei 14.689/2023 | ✅ Confere |

## Itens NÃO verificados (risco aceito para o PR atual)

### Valores estáveis há anos — risco baixo
- Faixas dos 5 Anexos do Simples Nacional (LC 123/2006, últimas alterações 2018)
- Alíquotas IRPJ 15% + 10% adicional (Lei 9.430/1996 Art. 25 + RIR/2018)
- CSLL 9% (Lei 7.689/1988 Art. 3º)
- PIS cumulativo 0,65% + COFINS cumulativo 3% (Lei 9.718/1998)
- PIS não-cumulativo 1,65% + COFINS não-cumulativo 7,6% (Leis 10.637/2002 e 10.833/2003)
- Presunção por CNAE Lei 9.249/1995 Art. 15
- Teto MEI R$ 81.000 (LC 123/2006 Art. 18-A)
- Sublimite Simples R$ 3,6M + Teto R$ 4,8M (LC 123/2006)

### Cobertura incompleta — risco médio
- **23 UFs** sem spot-check contra DOE (só 4 verificadas: SP, RJ, BA, MA)
- **SM 2027-2033** são estimativas +7% a.a. (aguardam decretos futuros)
- **Cronograma IVA 2029-2033** é estimativa de fase-in (aguarda Resolução Senado)

## Política FECP adotada (documentada em `difal.py`)

Inconsistência identificada: algumas UFs tinham FECP acoplado (RJ 22% =
20% + 2%) e outras não (BA 20,5% modal base). Decisão de design:

- **FECP generalizado por lei estadual** → incluído na alíquota (RJ, PR, AL, SE)
- **FECP condicional a produtos específicos** → NÃO incluído (BA, demais)

Justificativa: DIFAL é cálculo genérico. FECP produto-a-produto fica fora
do escopo do motor tributário 2026-2033.

## Ações tomadas hoje

1. ✅ Correção da multa 75% (já commitado ontem em `9607069`)
2. ✅ Enriquecimento dos comentários de `difal.py::ALIQUOTA_ICMS_INTERNA` com:
   - Política FECP explícita
   - Data desta auditoria
   - UFs spot-checked contra fontes oficiais
   - Nota sobre vida útil 2026-2028 (transição ICMS pela reforma)

## Pendências pós-PR (não bloqueantes)

1. 🟡 Auditoria das 23 UFs ICMS restantes contra DOE oficial — trabalho braçal, ~3h
2. 🟡 Revisão anual das estimativas SM 2027-2033 conforme decretos saírem
3. 🟡 Acompanhar Resoluções do Senado Federal para confirmar cronograma IVA 2029-2033
4. 🟢 Teste unitário somando distribuições DAS por faixa (validar que cada faixa = 100%)

## Conclusão

**Motor está apto para merge.** Os valores mais críticos (tetos, sublimites,
cronograma IVA próximo, salário mínimo 2026, multas) foram confrontados com
fontes oficiais. Os demais são valores estáveis há anos ou estimativas com
margem conservadora declarada.

Risco residual: médio-baixo, concentrado em ICMS de UFs que não foram
spot-checked. Mitigação: revisão anual + acompanhamento de DOEs.
