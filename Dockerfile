FROM python:3.12-slim AS package-builder

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY mypeople ./mypeople
RUN pip wheel --no-deps --wheel-dir /dist .

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        tmux curl git bash procps ca-certificates asciinema \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /bin/bash mypeople \
    && mkdir -p /var/lib/mypeople \
    && chown -R mypeople:mypeople /var/lib/mypeople /home/mypeople

ARG TARGETARCH
ARG TTYD_VERSION=1.7.7
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) asset=x86_64; sha256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55 ;; \
      arm64) asset=aarch64; sha256=b38acadd89d1d396a0f5649aa52c539edbad07f4bc7348b27b4f4b7219dd4165 ;; \
      *) echo "unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.${asset}" \
      -o /usr/local/bin/ttyd; \
    echo "${sha256}  /usr/local/bin/ttyd" | sha256sum -c -; \
    chmod 0755 /usr/local/bin/ttyd

# Claude is installed in the image, but its credential is never baked into an image layer.
ARG CLAUDE_VERSION=2.1.205
USER mypeople
RUN curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_VERSION}"
USER root
RUN cp /home/mypeople/.local/bin/claude /usr/local/bin/claude

COPY --from=package-builder /dist/mypeople-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/mypeople-*.whl \
    && rm /tmp/mypeople-*.whl

ENV MYPEOPLE_HOME=/var/lib/mypeople \
    MYPEOPLE_CONFIG_PATH=/var/lib/mypeople/config/queue.env \
    MYPEOPLE_CONTAINER=1 \
    HOME=/home/mypeople \
    BIND_ADDR=0.0.0.0 \
    HUD_PORT=9900 \
    TODO_PORT=9933 \
    TTYD_PORT=7681 \
    TTYD_BROWSER_PORT=7681 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

VOLUME ["/var/lib/mypeople", "/home/mypeople"]
EXPOSE 9900 9933 7681
HEALTHCHECK --interval=10s --timeout=4s --start-period=45s --retries=6 \
  CMD curl -fsS http://127.0.0.1:9933/health >/dev/null || exit 1

USER mypeople
ENTRYPOINT ["mypeople", "up", "--both"]
