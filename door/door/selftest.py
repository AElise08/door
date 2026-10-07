"""Real sandbox self-test (spec 17.1). Fails closed: any item that does not pass returns 1."""
import os
import tempfile
from pathlib import Path


def _sh(rt, pol, script, env_key="door-selftest", timeout=60):
    d = Path(tempfile.mkdtemp(prefix="door-st-"))
    (d / "work").mkdir()
    (d / "out").mkdir(mode=0o777)
    os.chmod(d / "out", 0o777)
    spec = {"name": "door-run-selftest", "export_dir": str(d / "work"), "outbox_dir": str(d / "out"),
            "placeholder_key": env_key, "prompt": "", "model": "", "cpus": pol["sandbox"]["cpus"],
            "memory_mb": pol["sandbox"]["memory_mb"], "command": ["sh", "-c", script]}
    try:
        r = rt.run(spec, timeout)
        return r.exit_code, (d / "out" / "r.txt").read_text() if (d / "out" / "r.txt").exists() else ""
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def run(pol, rt, credential) -> int:
    if not rt.available():
        print("FAIL: container runtime unavailable")
        return 1
    rt.ensure_internal_network()
    tests = {
        "no ~/.ssh, ~/.aws, ~/.config, .env": 'for p in /home/agent/.ssh /home/agent/.aws /home/agent/.config /root/.ssh /work/.env /Users /host_mnt; do [ -e "$p" ] && echo "VISIBLE $p" >> /outbox/r.txt; done; true',
        "read-only root filesystem": 'touch /etc/door-x 2>/dev/null && echo "WROTE" >> /outbox/r.txt; touch /work/x 2>/dev/null && echo "WROTE /work" >> /outbox/r.txt; true',
        "no direct network": 'for h in 1.1.1.1 8.8.8.8 api.anthropic.com; do timeout 5 bash -c "echo > /dev/tcp/$h/443" 2>/dev/null && echo "REACHED $h" >> /outbox/r.txt; done; true',
        "no real credential in the environment": 'env | grep -F -- "$REAL" >> /outbox/r.txt; true',
    }
    bad = 0
    for name, script in tests.items():
        s = script.replace("$REAL", credential or "NOT-SET-xyz")
        code, out = _sh(rt, pol, s)
        ok = code == 0 and not out.strip()
        print(("ok     " if ok else "FAIL   ") + name + ("" if ok else " -> %s %s" % (code, out.strip()[:200])))
        bad += not ok
    return 1 if bad else 0
