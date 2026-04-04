# Motor Tributário Conect — Dockerfile
# Build:  docker build -t motor-tributario .
# Run:    docker run -p 8000:8000 --env-file PY/.env motor-tributario

FROM python:3.12-slim

# Metadados
LABEL maintainer="Escritório Contábil Conect <contato@conect.local>"
LABEL description="Motor Tributário Conect 2026-2033 — API + UI"

# Dependências do sistema para weasyprint (renderização HTML→PDF)
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Criar usuário não-root para segurança
RUN groupadd -r motorapp && useradd -r -g motorapp motorapp

# Diretório de trabalho
WORKDIR /app

# Instalar dependências Python primeiro (cache de layer)
COPY PY/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copiar código da aplicação
COPY PY/ ./PY/
COPY UI/ ./UI/

# Permissões para o usuário da app
RUN chown -R motorapp:motorapp /app
USER motorapp

# Criar banco de dados inicial (idempotente)
WORKDIR /app/PY
RUN python -c "from database import criar_tabelas; criar_tabelas()" 2>/dev/null || true

# Porta exposta
EXPOSE 8000

# Health check — verifica se a API responde
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Comando padrão: uvicorn em modo produção
CMD ["python", "-m", "uvicorn", "api_motor:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--log-level", "info"]
