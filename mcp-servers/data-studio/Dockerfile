# Data Studio: MCP server de análise de dados e geração de entregáveis (PPTX, slides/dashboards HTML, DOCX).
# Modo "process" (padrão): o servidor roda como root DENTRO do container só para trocar de uid — cada sessão
# (conversa) executa Python com um uid próprio e workspace 700 (app/kernels.py). Modo "container": cada sessão ganha
# o seu próprio container sandbox desta mesma imagem (app/sandbox.py).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 MPLBACKEND=Agg
# LibreOffice (headless) renderiza PPTX/DOCX/XLSX em imagens para preview_file; Carlito/Liberation têm as métricas
# de Calibri/Arial, então o slide renderizado fica fiel ao que o PowerPoint mostra.
RUN apt-get update && apt-get upgrade -y --no-install-recommends && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-por tesseract-ocr-eng util-linux fonts-dejavu-core \
        libreoffice-impress libreoffice-writer libreoffice-calc fonts-crosextra-carlito fonts-liberation2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY requirements.txt .
RUN PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=8 pip install -r requirements.txt
# Cópias locais das libs JS (mesmas versões de app/builders/common.py) para HTML com offline=true
COPY fetch_js_libs.py .
RUN python fetch_js_libs.py /srv/static_libs
COPY app ./app
ENV PYTHONPATH=/srv DATA_DIR=/data JS_LIB_DIR=/srv/static_libs
EXPOSE 8000 8001
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')"
CMD ["python", "-m", "app.server"]
