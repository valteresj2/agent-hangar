# Imagens de harness: 1 container efêmero por job (nunca fica em pé; ver deploy.run_job_container).
# Multi-stage: cada harness vira uma imagem própria (agent-hangar/harness-<id>) em vez de um monolito de 7 GB.
# O entrypoint é o mesmo em todas e escolhe o runner por HARNESS_ID; `base` só roda o modo mock.
#
#   docker build --target claude-code -t agent-hangar/harness-claude-code harness/
#
# Versões fixadas para builds reproduzíveis — atualize conscientemente (ver docs/harnesses.md).
ARG CLAUDE_CODE_VERSION=2.1.283
ARG CODEX_VERSION=0.157.1
ARG DSH_VERSION=0.1.5-rc.3
ARG HERMES_COMMIT=8c9fe9640

FROM node:22-slim AS base
# python3 + pytest: projetos Python nos jobs e nas avaliações de código (eval_runner.js)
RUN apt-get update && apt-get upgrade -y --no-install-recommends && apt-get install -y --no-install-recommends git ca-certificates python3 python3-pytest \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 harness \
    && mkdir -p /workspace /srv && chown -R harness:harness /workspace /srv
COPY entrypoint.js /srv/entrypoint.js
COPY eval_runner.js /srv/eval_runner.js
# HOME fora do workspace: caches e config dos CLIs não poluem o diff do job
ENV HOME=/home/harness
WORKDIR /workspace
USER harness
CMD ["node", "/srv/entrypoint.js"]

FROM base AS claude-code
ARG CLAUDE_CODE_VERSION
USER root
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} && npm cache clean --force
USER harness

FROM base AS codex
ARG CODEX_VERSION
USER root
RUN npm install -g @openai/codex@${CODEX_VERSION} && npm cache clean --force
USER harness

FROM base AS deepseek-harness
ARG DSH_VERSION
USER root
RUN npm install -g @deepseek-ai/dsh@${DSH_VERSION} && npm cache clean --force
ENV DSH_TELEMETRY_MODE=DISABLED
USER harness

# Hermes Agent (Nous Research): instalador próprio (clona o repo, baixa Python/uv, compila a CLI).
# HERMES_HOME fica em /opt (não /root, que é 700 e invisível para o usuário sem privilégios que roda o
# container); o launcher que o instalador grava em ~/.local/bin é copiado para /usr/local/bin.
FROM base AS hermes
ARG HERMES_COMMIT
USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl build-essential pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*
ENV HERMES_HOME=/opt/hermes
# o instalador grava o launcher em $HOME/.local/bin — roda com o HOME do root e depois restaura
RUN export HOME=/root \
    && curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --non-interactive --commit ${HERMES_COMMIT} \
    && cp /root/.local/bin/hermes /usr/local/bin/hermes && chmod 755 /usr/local/bin/hermes \
    && chmod -R a+rwX "$HERMES_HOME"
USER harness
