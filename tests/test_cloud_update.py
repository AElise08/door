"""cloud/update.py pulls ONE layer of the pinned image -- the release dir -- and nothing it can't verify.

A fake registry in-process: it demands an anonymous bearer token first (the public ECR dance),
serves an index -> amd64 manifest -> config with the myplow.release label -> gzip layer.
"""
import gzip
import hashlib
import importlib.util
import io
import json
import os
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def sha(b):
    return "sha256:" + hashlib.sha256(b).hexdigest()


def layer_with(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            t.addfile(info, io.BytesIO(data))
    return gzip.compress(buf.getvalue())


def registry(blobs, manifests):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/token"):
                return self.reply(200, json.dumps({"token": "anon"}).encode())
            if self.headers.get("Authorization") != "Bearer anon":
                self.send_response(401)
                self.send_header("WWW-Authenticate",
                                 f'Bearer realm="http://127.0.0.1:{self.server.server_port}/token",'
                                 'service="test",scope="repository:myplow:pull"')
                return self.end_headers()
            ref = self.path.rsplit("/", 1)[1]
            body = manifests.get(ref) or blobs.get(ref)
            self.reply(200 if body else 404, body or b"")

        def reply(self, code, body):
            self.send_response(code)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class CloudUpdatePull(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        (root / "releases").mkdir()
        with mock.patch.dict(os.environ, {"MYPLOW_ROOT": str(root), "MYPLOW_REGISTRY_SCHEME": "http"}):
            spec = importlib.util.spec_from_file_location("update", ROOT / "cloud" / "update.py")
            self.u = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.u)
        self.root = root
        self.layer = layer_with({"opt/myplow/current": b"", "opt/myplow/releases/9.9.9/run.sh": b"#!/bin/sh\n",
                                 "opt/myplow/releases/9.9.9/RELEASE": b"9.9.9\n", "etc/passwd": b"no"})
        config = json.dumps({"config": {"Labels": {"myplow.release": "9.9.9"}}}).encode()
        base = gzip.compress(b"base layer")
        man = json.dumps({"config": {"digest": sha(config)},
                          "layers": [{"digest": sha(base)}, {"digest": sha(self.layer),
                                     "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip"}]}).encode()
        index = json.dumps({"manifests": [
            {"digest": "sha256:arm", "platform": {"os": "linux", "architecture": "arm64"}},
            {"digest": sha(man), "platform": {"os": "linux", "architecture": "amd64"}}]}).encode()
        self.blobs = {sha(config): config, sha(base): base, sha(self.layer): self.layer}
        self.srv = registry(self.blobs, {"sha256:idx": index, sha(man): man})
        self.image = f"127.0.0.1:{self.srv.server_port}/myplow@sha256:idx"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.td.cleanup()

    def test_stages_only_the_release_dir_of_the_last_layer(self):
        release, layer, reg = self.u.release_of(self.image)
        self.assertEqual("9.9.9", release)
        self.u.stage(release, layer, reg)
        self.assertEqual("9.9.9\n", (self.root / "releases/9.9.9/RELEASE").read_text())
        self.assertFalse((self.root / "etc").exists(), "only opt/myplow/releases/<release>/ may land")
        self.assertEqual(["9.9.9"], [p.name for p in (self.root / "releases").iterdir()])

    def test_a_layer_that_does_not_match_its_digest_is_refused(self):
        release, layer, reg = self.u.release_of(self.image)
        self.blobs[layer["digest"]] = layer_with({"opt/myplow/releases/9.9.9/run.sh": b"evil"})
        with self.assertRaises(ValueError):
            self.u.stage(release, layer, reg)
        self.assertFalse((self.root / "releases/9.9.9").exists())


if __name__ == "__main__":
    unittest.main()
