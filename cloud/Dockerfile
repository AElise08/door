# MyPlow as a Plow cloud agent: 1-click from aiworthusing.com/agent-index/myplow.
#
# The released MyPlow image plus the three things a Plow VM needs and a Mac does not:
#   - a model bridge: Claude Code speaks Anthropic's API, Plow serves OpenAI chat completions
#     (billed to the owner's Plow credits, so nobody logs into Claude inside the VM). Agents ask
#     for Plow's default model by name, so the Index is told the model that actually answered;
#   - the plow-chat plugin switched on, which reads the VM's line from PLOW_API_BASE;
#   - the Agent Index reporter, fed by agentsview, which is the only way it sees Claude Code.
# Nothing tenant-specific is baked in: the token comes from Plow's proxy at run time.
#
#   docker buildx build --platform linux/amd64 -f cloud/Dockerfile -t ghcr.io/delattre1/myplow:v1 .
ARG BASE=ghcr.io/delattre1/mypeople:5.18.0
FROM ${BASE}

USER root
ARG LITELLM_VERSION=1.102.1
RUN pip install --no-cache-dir "litellm[proxy]==${LITELLM_VERSION}"

ARG AGENTSVIEW_VERSION=0.44.0
ARG AGENTSVIEW_SHA256=037ea7a46d52e06b20363b4aa7cd7f28e32f31d8215803d6e9a0c96bac5818e3
RUN set -eux; \
    curl -fsSL "https://github.com/wesm/agentsview/releases/download/v${AGENTSVIEW_VERSION}/agentsview_${AGENTSVIEW_VERSION}_linux_amd64.tar.gz" -o /tmp/av.tgz; \
    echo "${AGENTSVIEW_SHA256}  /tmp/av.tgz" | sha256sum -c -; \
    tar -xzf /tmp/av.tgz -C /usr/local/bin agentsview; rm /tmp/av.tgz; \
    chmod 0755 /usr/local/bin/agentsview

ARG CLIENT_REV=edf196031803e204cdbcd81ce574e1f54fd75f65
ARG CLIENT_SHA256=970caf7534cd7d3b71ffee8f1a576f9da4dc494a508e8ab1998ee2ce6f4a2ac4
RUN set -eux; mkdir -p /opt/myplow; \
    curl -fsSL "https://raw.githubusercontent.com/plow-pbc/agent-index-client/${CLIENT_REV}/standalone/agent_index_client.py" \
      -o /opt/myplow/agent_index_client.py; \
    echo "${CLIENT_SHA256}  /opt/myplow/agent_index_client.py" | sha256sum -c -

COPY cloud/entrypoint.sh cloud/agent-index.sh cloud/litellm.yaml /opt/myplow/
RUN chmod 0755 /opt/myplow/*.sh

ENV PLOW_CHAT=1 \
    ANTHROPIC_BASE_URL=http://127.0.0.1:4000 \
    ANTHROPIC_AUTH_TOKEN=myplow-bridge \
    DEFAULT_CLAUDE_MODEL=claude-sonnet-5 \
    DEFAULT_ENG_MODEL=claude-sonnet-5 \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

USER mypeople
ENTRYPOINT ["/opt/myplow/entrypoint.sh"]
