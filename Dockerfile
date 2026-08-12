# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check do CONTÊINER: "este processo ainda serve HTTP?"
#
# Aponta para /health (sem banco), e não para /api/v1/health (com banco), de
# propósito. O que este comando decide é se o contêiner deve ser reiniciado, e
# banco fora não se conserta reiniciando a API — o único efeito seria derrubar
# a resposta "API no ar, banco fora" justamente durante o incidente em que ela
# é a informação útil. A saúde das dependências é monitorada de fora, por
# /api/v1/health; ver DEPLOY.md.
#
# raise_for_status() não é detalhe: sem ele, requests.get() considera sucesso
# qualquer resposta HTTP, inclusive 500 e 503, e o healthcheck só falharia com
# a porta fechada. Era o caso até aqui.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=5).raise_for_status()" || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
