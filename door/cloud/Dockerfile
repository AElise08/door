# Door as a Plow cloud agent (one-click install from the agent index).
# Build from the repository root:  docker build -f cloud/Dockerfile -t door-cloud:0.3 .
# Stage "panel-tests" compiles the panel on Linux and runs its checks:  docker build -f cloud/Dockerfile --target panel-tests .

FROM swift:6.2 AS panel
WORKDIR /src/panel
COPY panel/Package.swift ./
COPY panel/Sources ./Sources
RUN swift build -c release --product door-panel --static-swift-stdlib

FROM panel AS panel-tests
RUN swift build --product panel-tests && swift run panel-tests

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* && useradd -u 10001 -m -d /home/door door \
    && install -d -o door -g door /var/lib/door
WORKDIR /opt/door
COPY pyproject.toml README.md ./
COPY door ./door
RUN pip install --no-cache-dir .
COPY --from=panel /src/panel/.build/release/door-panel /usr/local/bin/door-panel
COPY cloud/entrypoint.sh /opt/door/entrypoint.sh
USER door
ENV DOOR_STATE=/var/lib/door PYTHONUNBUFFERED=1
VOLUME /var/lib/door
HEALTHCHECK --interval=30s --timeout=5s CMD python3 -c "import socket; socket.create_connection(('127.0.0.1', 9630), 3).close()"
# Plow's VMs boot the image's CMD, so the ENTRYPOINT is cleared (same as MyPlow's cloud image).
ENTRYPOINT []
CMD ["/opt/door/entrypoint.sh"]
