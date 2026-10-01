# MyPlow as a Plow cloud agent: 1-click from aiworthusing.com/agent-index/myplow.
#
# Built on its own, not on the full MyPlow image: a cloud MyPlow runs Claude Code only, so the
# Playwright browsers (2 GB), the Codex CLI (1.2 GB) and grok are left out -- well under 1 GB instead
# of 4 GB, so a fresh Plow host starts it fast instead of only a warm one. On top of mypeople it adds:
#   - its OWNER's Claude subscription login, fetched at boot from the owner's login server
#     (claude-login.sh). PROTOTYPE: every copy runs on that one person's Claude plan, and the server
#     hands the login only to agents on the owner's Plow account -- anyone else's install boots
#     without one and texts its installer that it only works for its owner. No login is in the image;
#   - the plow-chat plugin switched on, which reads the VM's line from PLOW_API_BASE;
#   - the Agent Index reporter, fed by agentsview, which is the only way it sees Claude Code.
# Nothing tenant-specific is baked in: the token comes from Plow's proxy at run time.
#
# Published by .github/workflows/publish-container.yml as ghcr.io/delattre1/mypeople:cloud-<version>.
# By hand:  docker buildx build --platform linux/amd64 -f cloud/Dockerfile .
FROM python:3.12-slim AS wheel
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY mypeople ./mypeople
RUN pip wheel --no-deps --wheel-dir /dist .

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends tmux curl git procps ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 --shell /bin/bash mypeople \
    && mkdir -p /var/lib/mypeople && chown -R mypeople:mypeople /var/lib/mypeople /home/mypeople

# ttyd: supervise.sh keeps it running for the board's terminal views; tiny, and without it the
# supervisor would log a failed start every 10 seconds.
ARG TTYD_VERSION=1.7.7
ARG TTYD_SHA256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55
RUN set -eux; \
    curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64" -o /usr/local/bin/ttyd; \
    echo "${TTYD_SHA256}  /usr/local/bin/ttyd" | sha256sum -c -; chmod 0755 /usr/local/bin/ttyd

# Claude Code: installed as the user, then the one binary copied out and the installer's own copy
# removed, so the image does not carry it twice.
ARG CLAUDE_VERSION=2.1.205
USER mypeople
RUN curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_VERSION}"
USER root
RUN cp -L /home/mypeople/.local/bin/claude /usr/local/bin/claude \
    && rm -rf /home/mypeople/.local/bin/claude /home/mypeople/.local/share/claude

COPY --from=wheel /dist/mypeople-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/mypeople-*.whl && rm /tmp/mypeople-*.whl

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

COPY cloud/entrypoint.sh cloud/agent-index.sh cloud/claude-login.sh /opt/myplow/
RUN chmod 0755 /opt/myplow/*.sh

# The same runtime contract as the full image (mypeople reads these), plus the cloud switches.
ENV MYPEOPLE_HOME=/var/lib/mypeople \
    MYPEOPLE_CONFIG_PATH=/var/lib/mypeople/config/queue.env \
    MYPEOPLE_CONTAINER=1 \
    HOME=/home/mypeople \
    BIND_ADDR=0.0.0.0 \
    HUD_PORT=9900 \
    TODO_PORT=9933 \
    TTYD_PORT=7681 \
    TTYD_BROWSER_PORT=7681 \
    DEFAULT_BACKEND=claude \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PLOW_CHAT=1 \
    DEFAULT_CLAUDE_MODEL=claude-opus-5-5 \
    DEFAULT_ENG_MODEL=claude-opus-5-5 \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

VOLUME ["/var/lib/mypeople", "/home/mypeople"]

# Plow's VMs (exe.dev) boot the image's CMD, not its ENTRYPOINT, and may boot it as root:
# entrypoint.sh drops to the mypeople user itself.
USER mypeople
CMD ["/opt/myplow/entrypoint.sh"]
