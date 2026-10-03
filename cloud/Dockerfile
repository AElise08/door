# MyPlow as a Plow cloud agent: 1-click from aiworthusing.com/agent-index/myplow.
#
# The FULL MyPlow image (every browser and coding CLI it ships) plus the three things a Plow VM needs
# and a Mac does not. ~4 GB; cloud/Dockerfile.slim is the same MyPlow at ~0.9 GB without the Playwright
# browsers and the codex/grok CLIs (Claude agents only, no in-container browsing):
#   - its OWNER's Claude subscription login, fetched at boot from the owner's login server
#     (claude-login.sh). PROTOTYPE: every copy runs on that one person's Claude plan, and the server
#     hands the login only to agents on the owner's Plow account -- anyone else's install boots
#     without one and texts its installer that it only works for its owner. No login is in the image;
#   - the plow-chat plugin switched on, which reads the VM's line from PLOW_API_BASE;
#   - the Agent Index reporter, fed by agentsview, which is the only way it sees Claude Code.
# Nothing tenant-specific is baked in: the token comes from Plow's proxy at run time.
#
# Published by .github/workflows/publish-container.yml as ghcr.io/delattre1/mypeople:cloud-<version>,
# with BASE set to that same release. By hand:
#   docker buildx build --platform linux/amd64 -f cloud/Dockerfile --build-arg BASE=... .
ARG BASE=ghcr.io/delattre1/mypeople:latest
FROM ${BASE}

USER root
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

# The owner's model choice. The Boss is spawned without --model, so on a Mac it follows the
# owner's own ~/.claude/settings.json; that file never travels into this image, and without it
# Claude Code fell back to its default (Sonnet). firstrun merges its hooks into this file and
# keeps these keys.
RUN install -d -o mypeople -g mypeople /home/mypeople/.claude \
 && printf '{\n  "model": "claude-opus-5-5",\n  "effortLevel": "xhigh"\n}\n' > /home/mypeople/.claude/settings.json \
 && chown mypeople:mypeople /home/mypeople/.claude/settings.json

ENV PLOW_CHAT=1 \
    DEFAULT_CLAUDE_MODEL=claude-opus-5-5 \
    DEFAULT_ENG_MODEL=claude-opus-5-5 \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

# Plow's VMs (exe.dev) boot the image's CMD, not its ENTRYPOINT, and may boot it as root: the
# base image's ENTRYPOINT is cleared so `docker run` boots the same CMD, and entrypoint.sh drops
# to the mypeople user itself.
USER mypeople
ENTRYPOINT []
CMD ["/opt/myplow/entrypoint.sh"]
