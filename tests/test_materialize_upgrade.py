"""Upgrading an install that has already been used -- the dogfooding path.

A fresh materialize() only ever writes into an empty dir, so nothing here was exercised until
0.4.0 was installed over the CEO's live install and died half-way with EACCES.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mypeople import firstrun  # noqa: E402


class MaterializeOverExistingInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.install = os.path.join(self.tmp.name, "install")

    def test_upgrades_over_a_published_role_store(self):
        """mprole chmods every published role file to 444 so an agent cannot rewrite its own
        personality. copytree's copy2 opens the destination for writing -> EACCES, and because
        ensure() calls materialize() before starting daemons, a failed upgrade leaves the fleet
        with no daemons at all."""
        firstrun.materialize(self.install)
        registry = os.path.join(self.install, "roles", "registry.json")
        self.assertTrue(os.path.exists(registry), "package must ship a role store")
        os.chmod(registry, 0o444)  # exactly what mprole.py does after publishing

        firstrun.materialize(self.install)  # must not raise

        self.assertTrue(os.path.exists(registry))
        mode = stat.S_IMODE(os.stat(registry).st_mode)
        self.assertFalse(mode & stat.S_IWUSR,
                         "the role store must stay read-only to the runtime agent after upgrade")

    def test_upgrade_refreshes_daemon_code(self):
        firstrun.materialize(self.install)
        mp = os.path.join(self.install, "bin", "mp")
        with open(mp, "w") as f:
            f.write("# stale\n")
        firstrun.materialize(self.install)
        self.assertNotEqual(open(mp).read(), "# stale\n", "upgrade must refresh daemon code")

    def test_upgrade_never_clobbers_live_state(self):
        firstrun.materialize(self.install)
        board = os.path.join(self.install, "todos", "board.v2.sqlite3")
        os.makedirs(os.path.dirname(board), exist_ok=True)
        with open(board, "w") as f:
            f.write("THE BOARD")
        firstrun.materialize(self.install)
        self.assertEqual(open(board).read(), "THE BOARD")

    def test_upgrade_keeps_roles_this_release_does_not_ship(self):
        """An install can hold roles the creator authored here. Replacing registry.json with the
        shipped one would leave them on disk but unspawnable -- silent loss of authored work."""
        firstrun.materialize(self.install)
        roles = Path(self.install) / "roles"
        reg = roles / "registry.json"
        profile = roles / "profiles" / "piada-pirata" / "1.0.0.json"
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text("{}")
        data = json.loads(reg.read_text())
        data["roles"]["piada-pirata"] = "profiles/piada-pirata/1.0.0.json"
        data["roles"]["ghost"] = "profiles/ghost/9.9.9.json"   # profile never existed
        os.chmod(reg, 0o644)
        reg.write_text(json.dumps(data))

        firstrun.materialize(self.install)

        after = json.loads(reg.read_text())["roles"]
        self.assertIn("piada-pirata", after, "upgrade unregistered an authored role")
        self.assertIn("boss", after, "upgrade dropped a shipped role")
        self.assertNotIn("ghost", after, "kept an entry whose profile does not exist")

    def test_scripts_stay_executable_after_upgrade(self):
        firstrun.materialize(self.install)
        firstrun.materialize(self.install)
        for name in ("mp", "supervise.sh", "boss-supervisor.sh"):
            p = os.path.join(self.install, "bin", name)
            self.assertTrue(os.access(p, os.X_OK), "%s must stay executable" % name)


class TmuxThemeTests(unittest.TestCase):
    def test_a_hung_theme_download_does_not_stop_up(self):
        """install_tmux_conf runs inside ensure(), before any daemon starts: a hung tpm clone on a
        fresh home raised TimeoutExpired there and `mypeople up` started nothing."""
        def run(cmd, **kw):
            if cmd[0] != "tmux":
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"HOME": home}), \
                mock.patch.object(firstrun, "CONFIG_DIR", os.path.join(home, "cfg")), \
                mock.patch.object(firstrun.shutil, "which", return_value="/usr/bin/x"), \
                mock.patch.object(firstrun.subprocess, "run", side_effect=run) as ran:
            install = os.path.join(home, "install")
            os.makedirs(os.path.join(install, "config"))
            Path(install, "config", "tmux.conf").write_text("set -g mouse on\n")
            firstrun.install_tmux_conf(install)  # must not raise
        self.assertEqual("git", ran.call_args_list[0][0][0][0])
        self.assertEqual("tmux", ran.call_args_list[-1][0][0][0], "the conf is still loaded")


if __name__ == "__main__":
    unittest.main()
