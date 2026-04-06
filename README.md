# Motor Tributario Conect 2026-2033

Motor de auditoria tributaria transicional para a Reforma Tributaria brasileira (EC 132/2023 | LC 123/2006 | LC 214/2025).

Extrai PDFs do e-CAC via Claude Vision, calcula tributos por regime (Simples Nacional, Lucro Presumido, MEI, Lucro Real) e compara DAS calculado vs DAS pago.

## Requisitos

- Python 3.11+
- Dependencias do sistema para weasyprint (libpango, libpangocairo, etc.)

## Setup

```bash
# 1. Instalar dependencias
cd PY
pip install -r requirements.txt

# 2. Configurar variaveis de ambiente (criar PY/.env)
#    ANTHROPIC_API_KEY=sk-ant-api03-...
#    DATABASE_URL=sqlite:///motor_tributario.db

# 3. Inicializar banco de dados
python -c "from database import criar_tabelas; criar_tabelas()"

# 4. Rodar migracoes
alembic upgrade head
```

## Uso

### Demo (API + UI)

```bash
python run_demo.py
# Acesse http://localhost:8000/ui/login.html
# Credenciais: admin / Conect@2026!
```

### API direta

```bash
cd PY && uvicorn api_motor:app --reload --port 8000
# Docs: http://localhost:8000/docs
```

### Docker

```bash
docker compose up --build
```

## Testes

```bash
cd PY

# Todos os testes
python -m pytest tests/ -v

# Arquivo especifico
python -m pytest tests/test_fase2_simples.py -v

# Com cobertura
python -m pytest tests/ -v --cov=. --cov-report=term-missing
```

## Lint

```bash
cd PY && ruff check .
```

## Estrutura do Projeto

```
motor-tributario-conect/
├── PY/                    # Backend Python (FastAPI + Motor Tributario)
│   ├── api_motor.py       # API FastAPI — endpoints HTTP
│   ├── motor_tributario.py# Orquestrador principal + Dispatcher de regime
│   ├── database.py        # SQLModel + SQLite, Enums, LGPD
│   ├── auth.py            # Autenticacao JWT + bcrypt
│   ├── validadores.py     # CNPJ, CNAE, NCM, UF
│   ├── tabelas_simples.py # Anexos I-V, CNAE->Anexo, cronograma IVA (FROZEN)
│   ├── extrator_pdfs.py   # Claude Vision API — extracao de PDFs
│   ├── relatorio_pdf.py   # Geracao de PDF via weasyprint
│   ├── audit_universal.py # Pipeline de auditoria
│   ├── regimes/           # Engines por regime tributario
│   │   ├── base.py        # BaseRegimeEngine + Guard Clauses
│   │   ├── lucro_presumido.py
│   │   ├── lucro_real.py
│   │   ├── mei.py
│   │   └── simples_multi.py
│   ├── tests/             # Suite de testes (188+ testes)
│   └── alembic/           # Migracoes de banco de dados
├── UI/                    # Frontend HTML (login, dashboard, analise)
├── docs/                  # Documentacao do projeto
│   ├── arquitetura/       # Docs tecnicas do motor
│   ├── roadmap/           # Planejamento e log de erros
│   ├── certificados/      # Certificados de validacao
│   ├── split_payment/     # Estrategia Split Payment
│   ├── templates/         # Templates de comunicacao
│   └── referencia/        # Documentos de referencia legal
├── samples/               # Exemplos de documentos de clientes (para testes)
│   └── doc_calculo/       # PDFs extraidos do e-CAC
├── data/                  # Dados de runtime (SQLite)
├── Dockerfile
├── docker-compose.yml
└── run_demo.py            # Launcher da demo
```

## Regimes Suportados

| Regime | Status |
|--------|--------|
| Simples Nacional (Anexo I) | Certificado |
| Lucro Presumido | Certificado |
| MEI | Implementado |
| Lucro Real | Proxima fase |

## Protecao de Regime (3 Camadas)

1. **Pydantic V2** — entrada invalida rejeitada antes de entrar no motor
2. **Guard Clause** — engine errado = `RegimeMismatchError` + log na trilha
3. **pytest** — se Guard removida = CI quebra, deploy bloqueado

## Licenca

Projeto proprietario — Escritorio Contabil Conect, Sorocaba, SP.
