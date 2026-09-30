# Contexto de build: raiz do repositório (para levar os templates junto).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY central/requirements.txt .
RUN pip install -r requirements.txt && useradd -u 10001 -m hangar \
    && mkdir -p /mcp-gateway && chown hangar /mcp-gateway   # volume compartilhado com o gateway Docker MCP
COPY central/alembic.ini ./alembic.ini
COPY central/migrations ./migrations
COPY central/app ./app
COPY templates ./templates
USER hangar
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
