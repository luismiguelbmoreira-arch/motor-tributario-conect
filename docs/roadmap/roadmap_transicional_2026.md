# 🗺️ ROADMAP TRANSICIONAL 2026-2033 — reFIN

**Estratégia de Implementação: Motor Tributário Conect**  
**Visão:** Redução da incerteza fiscal através de processamento determinístico.

---

## 📅 FASES DE IMPLANTAÇÃO

### FASE 1: Fundação e Protocolos (STATUS: INICIADA)
*   **Ação:** Modelagem `Pydantic V2` para `OperacaoFiscal` e `EmpresaFornecedora`.
*   **Meta:** Zero tolerância a `float`. Validação rigorosa de CNPJ e NCM.

### FASE 2: Núcleo Simples Nacional (STATUS: TESTE e-CAC)
*   **Ação:** Cálculo de RBT12, Fator R e Alíquota Efetiva.
*   **Meta:** Delta máximo aceitável vs. governo de R$ 5,00.

### FASE 3: Segregação IVA / Split Payment (STATUS: ARQUITETURA)
*   **Ação:** Implementação das tabelas de repartição de tributos (PIS/COFINS/ICMS/ISS).
*   **Meta:** Identificar a fração de crédito B2B integral.

### FASE 4: Simulação de Embate (Cenários Opt-out)
*   **Ação:** Algoritmo comparativo entre Simples Puro vs. IVA Monofásico segregado.
*   **Meta:** Decisão orientada ao caixa da empresa adquirente.

### FASE 5: Entrega e Diagnóstico (JSON Payload)
*   **Ação:** Agregação de resultados em objeto estruturado.
*   **Meta:** Purga automática de dados sensíveis (LGPD) pós-emissão.

### FASE 6: UI Analítica e Exportação PDF
*   **Ação:** Visualização comparativa e geração do Relatório de Auditoria.
*   **Meta:** Geração da "Bíblia da Reforma" para apresentação ao cliente.

---
*Escritório Moreira — A ciência das exatas protegendo o patrimônio.*
