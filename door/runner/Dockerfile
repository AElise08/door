# Imagem fixada do sandbox: só o CLI do agente e o relay (socat). Nada do Mac entra aqui.
FROM node:22-slim
ARG CLAUDE_VERSION=2.1.118
RUN apt-get update && apt-get install -y --no-install-recommends socat ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/claude-code@${CLAUDE_VERSION} \
    && useradd -u 10001 -m -d /home/agent agent
# More engines, each pinned. They run the same way: read-only copy in /work, no network except the proxy, one answer file.
ARG OPENCODE_VERSION=1.18.34
ARG CODEX_VERSION=0.160.1
USER root
RUN npm install -g opencode-ai@${OPENCODE_VERSION} @openai/codex@${CODEX_VERSION}
USER 10001:10001
WORKDIR /work
