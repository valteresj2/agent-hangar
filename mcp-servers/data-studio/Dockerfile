# Data Studio: MCP server de análise de dados e geração de entregáveis (PPTX, slides/dashboards HTML, DOCX).
# O servidor roda como root DENTRO do container só para trocar de uid: cada sessão (conversa) executa Python com
# um uid próprio e workspace 700 — ver app/kernels.py. O container em si não tem capabilities além das listadas
# no compose (SETUID/SETGID/CHOWN/FOWNER/KILL/DAC_OVERRIDE).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MPLBACKEND=Agg
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-por tesseract-ocr-eng util-linux fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
ENV PYTHONPATH=/srv DATA_DIR=/data
VOLUME /data
EXPOSE 8000 8001
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')"
CMD ["python", "-m", "app.server"]
