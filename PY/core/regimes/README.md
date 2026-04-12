# Engines de Regimes Tributários — Bíblia do Motor

Aqui residem as regras de negócios duras (Hard Logic) responsáveis pelos cálculos de cada regime previsto.

## O Que é uma Guard Clause
Todo arquivo exporta uma Engine que extende `BaseRegimeEngine` (em `base.py`). 
A Engine DEVE estipular qual atributo ela processa (Ex: `REGIME_ACEITO = "REAL"`).
Isso protege o Motor Tributário de processar clientes com fórmulas cruzadas.

## Como as Engines Operam
- `motor_tributario.py` usa um orquestrador cego para instanciar a Engine correta validando as condições da Guard Clause.
- Nenhuma Engine deve editar a "Trilha de Auditoria Universal" diretamente manipulando arrays; ela deve invocar os métodos internos definidos em `BaseRegimeEngine` para despachar seus logs do cálculo com a **Fundamentação Legal**.

> [!CAUTION]
> **MAX_FISCAL VIGENTE:** Antes de aprovar um Pull Request modificado em qualquer Engine de regime, corra `pytest tests/test_regime_guard.py` e garanta validação 100% de segurança tributária.
