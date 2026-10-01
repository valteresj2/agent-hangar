# Memória dos agentes: Graphiti (grafo de conhecimento temporal) sobre Neo4j ou FalkorDB (MEMORY_BACKEND).
# Embeddings locais (fastembed/ONNX): o modelo é baixado no build, então nada sai da rede para gerar vetores.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 FASTEMBED_CACHE_PATH=/srv/models HF_HUB_OFFLINE=0
WORKDIR /srv
COPY requirements.txt .
RUN PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=8 pip install -r requirements.txt
ARG EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('${EMBEDDING_MODEL}')"
COPY app ./app
RUN useradd -r -u 10001 memory && chown -R memory /srv
USER memory
ENV PYTHONPATH=/srv HF_HUB_OFFLINE=1 EMBEDDING_DIM=384 GRAPHITI_TELEMETRY_ENABLED=false
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["python", "-m", "app.server"]
