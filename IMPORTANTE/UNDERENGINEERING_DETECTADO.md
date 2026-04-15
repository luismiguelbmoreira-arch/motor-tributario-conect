# 🔴 Underengineering Detectado — Motor Tributário Conect

**Data da Análise:** 14 de Abril de 2026

---

## 1. Frontend (`UI/`) — Zero Compartilhamento de Componentes

- **Onde:** 13 arquivos HTML soltos, `resultado.html` com **91 KB** de HTML/CSS/JS inline.
- **Por quê:** Não existe sistema de templates, nem includes, nem Web Components. Cada página replica sidebar, header, footer, e lógica de autenticação JWT manualmente. Mudar um item de menu = editar 10+ arquivos.
- **Sugestão:** Implementar ao menos um `components.js` que injeta sidebar/header via DOM, ou adotar Jinja2 server-side (já nativo no ecossistema FastAPI).
- **Prioridade:** 🔴 CRÍTICA — primeiro ponto que vai travar a evolução.

---

## 2. Testes de Integração da API — Ausentes

- **Onde:** `PY/tests/` tem testes unitários de módulos isolados, mas **zero teste de endpoint HTTP** (nenhum `TestClient` do FastAPI/Starlette).
- **Por quê:** Os endpoints são o contrato público do sistema. Sem testes de integração, qualquer refatoração (como a que acabamos de fazer) pode quebrar rotas silenciosamente.
- **Sugestão:** Criar `tests/api/test_health.py`, `test_auth.py`, `test_analise_manual.py` usando `from fastapi.testclient import TestClient`.
- **Prioridade:** 🟠 ALTA — qualquer deploy sem isso é roleta russa.

---

## 3. Migrations (Alembic) — Configuradas mas Sem Histórico

- **Onde:** `PY/alembic/` e `alembic.ini` existem, mas não há migrations históricas versionadas.
- **Por quê:** O `database.py` usa `SQLModel.metadata.create_all()` (auto-create). Em produção com dados reais, isso **não migra colunas novas** — só cria tabelas inexistentes. Adicionar um campo novo em `EmpresaDB` = dados perdidos ou crash silencioso.
- **Sugestão:** Gerar a migration inicial (`alembic revision --autogenerate -m "baseline"`) e parar de usar `create_all()` em produção.
- **Prioridade:** 🟠 ALTA — bomba-relógio para o primeiro schema change em prod.

---

## 4. Dashboard Endpoint — Dados Hardcoded

- **Onde:** `GET /dashboard/summary` retorna JSON literal com números fixos (42 empresas, R$ 184.290,00).
- **Por quê:** O frontend consome isso como se fosse real. Em demo funciona, mas em produção o cliente verá dados estáticos eternamente.
- **Sugestão:** Conectar ao `database.py` com queries reais (`COUNT(*)` em `empresas`, `SUM(delta)` em `diagnosticos`), com fallback ao hardcoded se o banco estiver vazio.
- **Prioridade:** 🟡 MÉDIA — funciona para demo, mas engana em produção.

---

## 5. Validação de CNPJ — Apenas Contagem de Dígitos

- **Onde:** Todas as funções de validação (`database.py`, `sieg_service.py`, `main.py`) checam apenas `len(cnpj) == 14`.
- **Por quê:** CNPJ tem **dígito verificador** (módulo 11). Aceitar `00000000000000` como válido é risco fiscal real.
- **Sugestão:** O `validadores.py` (7 KB) já existe no projeto — verificar se implementa o check de dígito verificador e integrá-lo nos guard clauses dos endpoints.
- **Prioridade:** 🟡 MÉDIA — risco fiscal, mas baixa probabilidade de input acidental.

---

## Ordem de Ataque Sugerida

1. **Frontend `components.js`** — destravar evolução de UI
2. **Migration baseline Alembic** — blindar dados de produção
3. **Testes de integração HTTP** — blindar refatorações futuras
4. **Dashboard dinâmico** — credibilidade em demo/produção
5. **CNPJ com dígito verificador** — compliance fiscal completa
