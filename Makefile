# Read from the package so a release bump cannot leave this behind (it shipped 0.3.1
# images from 0.3.2 source).
VERSION := $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' mypeople/__init__.py)

.PHONY: wheel image verify clean live

wheel:
	uv build --wheel --out-dir dist

image:
	docker build -t mypeople:$(VERSION) .

verify:
	mypeople verify

clean:
	rm -rf build .hatch dist/*.whl

# The one way a release reaches this Mac's live install. `mypeople up` from this checkout copies
# the runtime into INSTALL_DIR and only then stamps VERSION, restarts every daemon and plugin still
# serving older code, and stamps run/serving.version -- so the version shown is the code running.
# Never write those two files by hand: on 10-03 three fixes were stamped live that were not running.
# env -i because daemons inherit this environment and an agent's shell carries its own AGENT_ID,
# TMUX and session; PATH is the one the desktop app gives them (desktop/src-tauri/src/main.rs).
APP_RT := /Applications/MyPlow.app/Contents/Resources/runtime
live:
	env -i HOME="$$HOME" USER="$$USER" LOGNAME="$$LOGNAME" SHELL="$$SHELL" TMPDIR="$$TMPDIR" \
	  LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 SSH_AUTH_SOCK="$$SSH_AUTH_SOCK" \
	  PATH="$(APP_RT)/bin:$(APP_RT)/python/bin:$$HOME/.local/bin:$$HOME/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" \
	  python3 -m mypeople.cli up --detach
