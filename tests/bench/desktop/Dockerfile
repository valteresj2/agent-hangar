# Runner do Cua Bench para os casos do desktop governado. Roda na rede do desktop (hangar_desktop, sem internet):
# fala com o cua-spacesd do desktop (preparar e conferir o estado) e com a central (o Digital employee faz a tarefa).
FROM python:3.12-slim

RUN pip install --no-cache-dir "cua-bench==0.4.4" "httpx>=0.27"

WORKDIR /bench
COPY . /bench
ENV PYTHONPATH=/bench CUA_ENV_TYPE=linux CUA_OUTPUT_DIR=/out HF_HUB_OFFLINE=1 CUA_TELEMETRY_ENABLED=false
ENTRYPOINT ["python", "-m", "cua_bench.batch.solver"]
