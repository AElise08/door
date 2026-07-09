# MyPeople

Self-hosted Claude Code teams: a priorities board, live HUD, browser terminal, persistent Boss,
engineers, and board backups. This repository contains the implemented runtime; installing it does
not hydrate or generate code from the SEED.

Each machine must authenticate Claude independently. Never copy, mount, or reuse another node's
credential store.

## Docker (recommended)

Requirements: Docker Desktop/Engine with Compose.

```bash
docker compose pull
docker compose run --rm --entrypoint claude mypeople auth login
docker compose up -d
docker compose ps
```

Open <http://localhost:9933>. The HUD is at <http://localhost:9933/dashboard> and terminal links
open port 7681. State and this node's Claude login persist in named volumes.

To update without losing state:

```bash
docker compose pull
docker compose up -d
```

To build the same image from the public source instead, run `make image`.

## Python / uv

On a machine that already has Claude Code, tmux, ttyd, and asciinema:

```bash
uv tool install git+https://github.com/delattre1/mypeople.git
claude auth login
mypeople up --detach
```

This installs the Python package directly from the canonical public source. Use the native installer
below when the host dependencies are not installed yet.

## Native installer

The installer builds and installs the wheel from this checkout, installs missing host packages when
the supported package manager is available, preserves existing MyPeople data, and starts the stack.

```bash
claude auth login
./install.sh
```

Then use:

```bash
mypeople status
mypeople verify
mypeople logs
mypeople down
```

Default state is `~/.local/share/mypeople`; config is `~/.config/mypeople/queue.env`. For another
isolated instance, set both `MYPEOPLE_HOME` and ports before installing/running.

## Worker/client mode

```bash
UPSTREAM_QUEUE_URL=http://server-host:9900 \
UPSTREAM_QUEUE_SECRET='<server queue secret>' \
mypeople up --client
```

For cross-host terminal links, set `TTYD_PUBLIC_URL` to a browser-reachable URL for that worker,
such as `http://worker.lan:7681`. A same-host board derives the terminal host from the browser origin.
