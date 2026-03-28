# 📧 TEMPLATE — Coleta de Documentos para Análise de Reforma Tributária

**Uso:** Enviar para cada empresa cliente antes da parametrização no motor.  
**Versão:** 1.0 | **Data:** 27/03/2026  

---

## MODELO DE EMAIL

**Assunto:** Reforma Tributária — Documentos Necessários para Análise de Impacto

---

Prezado(a) [Nome do Responsável],

Estamos desenvolvendo uma análise personalizada de impacto da **Reforma Tributária (IBS/CBS)**
para sua empresa, com projeções para o período 2026–2033.

Para concluir a parametrização do sistema e garantir que os cálculos reflitam **exatamente a
sua realidade fiscal**, precisamos dos seguintes documentos referentes a **[mês/ano de referência]:**

---

### 📋 DOCUMENTOS PARA TODOS OS ENQUADRAMENTOS

1. **Cartão CNPJ atualizado** (confirmar CNAE principal e secundários)
2. **Regime tributário atual** (Simples Nacional / Lucro Presumido / Lucro Real)
3. **Faturamento mensal dos últimos 12 meses** (planilha ou extrato do sistema)

---

### 📋 SE SIMPLES NACIONAL — ADICIONALMENTE

4. **PGDAS-D dos últimos 12 meses** (exportado do e-CAC ou portal Simples Nacional)
5. **Comprovante de pagamento do DAS** do mês de referência
6. **Informação sobre ICMS-ST:** sua empresa vende produtos com ICMS retido pelo
   fornecedor? Se sim, qual percentual aproximado do faturamento mensal?
7. **Se houver mais de uma atividade** (ex: comércio + serviços): faturamento separado
   por atividade e respectivo CNAE

> **Nota para o escritório:** Para certificação completa do motor, precisamos de **um cliente
> representativo por Anexo**: Anexo II (indústria), Anexo III (serviços, Fator R ≥ 0,28),
> Anexo IV (construção/limpeza/vigilância) e Anexo V (TI, advocacia, engenharia).
> Para o Anexo III e V, incluir também a **folha de salários dos últimos 12 meses**
> (necessária para o cálculo do Fator R — LC 123/2006, Art. 18, § 24).

---

### 📋 SE LUCRO PRESUMIDO — ADICIONALMENTE

4. **DCTF do último trimestre** (declaração de débitos e créditos)
5. **DARFs pagos** de IRPJ, CSLL, PIS e COFINS do período de referência
6. **Faturamento tributável** do trimestre (por atividade, se houver mais de uma)

> **Nota para o escritório:** Um cliente de Lucro Presumido com DCTF + DARFs de qualquer
> trimestre de 2026 é suficiente para certificar este módulo no motor.

---

### 📋 SE LUCRO REAL *(módulo em implementação)*

- LALUR / LACS do período
- EFD-Contribuições (regime não cumulativo de PIS/COFINS)
- Balanço + DRE do período

> **Status:** Motor de Lucro Real em desenvolvimento (Fase 3 do roadmap).

---

Com esses documentos, entregamos:

- ✅ Simulação do impacto do **Split Payment** no seu fluxo de caixa (2026–2033)
- ✅ Comparativo de carga tributária **antes e depois da transição**
- ✅ Recomendação de regime (Simples Puro × Opt-Out para B2B) a partir de 2027
- ✅ Relatório com **memória de cálculo completa**, pronto para apresentar ao contador ou fiscal

Prazo sugerido para envio: **[DATA]**

Em caso de dúvidas, estou à disposição.

Atenciosamente,

**Luiz Moreira**  
Escritório Contábil Conect — Sorocaba, SP  
[telefone] | [e-mail]

---

## 📌 CHECKLIST INTERNO (uso do escritório — não enviar ao cliente)

Antes de parametrizar, confirmar que recebeu:

- [ ] Cartão CNPJ
- [ ] Regime declarado
- [ ] Faturamento 12 meses
- [ ] **Simples:** PGDAS-D + DAS pago + info ICMS-ST + atividades segregadas
- [ ] **Presumido:** DCTF + DARFs + faturamento trimestral
- [ ] **Anexo III/V:** Folha de salários 12 meses (Fator R)

Arquivo recebido → salvar em `docs/doc calculo/[NOME_EMPRESA]/`  
Pipeline de extração → `python PY/audit_universal.py "docs/doc calculo/[NOME_EMPRESA]"`
