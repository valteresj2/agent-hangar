FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd -m -u 10001 agent
WORKDIR /srv
COPY requirements.txt .
RUN PIP_DEFAULT_TIMEOUT=120 PIP_RETRIES=8 pip install -r requirements.txt
COPY app.py .
RUN mkdir /data && chown agent /data
USER agent
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
