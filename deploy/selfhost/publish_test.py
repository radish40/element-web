# Copyright 2026 radish40
# SPDX-License-Identifier: AGPL-3.0-only

import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("publish", Path(__file__).with_name("publish.py"))
publish = importlib.util.module_from_spec(spec)
# fcntl is native to Linux. Run these deployment tests on the Linux runner/server.
spec.loader.exec_module(publish)


class ExtractReleaseTests(unittest.TestCase):
    def make_archive(self, name, kind=tarfile.REGTYPE):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.size = 2 if kind == tarfile.REGTYPE else 0
            member.linkname = "/etc/passwd" if kind == tarfile.SYMTYPE else ""
            bundle.addfile(member, io.BytesIO(b"ok") if member.size else None)
        archive.seek(0)
        return archive

    def test_extract_regular_file(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = self.make_archive("./bundles/app.js")
            publish.extract_release(archive, Path(folder))
            self.assertEqual((Path(folder) / "bundles/app.js").read_text(), "ok")

    def test_reject_path_traversal_before_writing(self):
        for name in ("../escape", "/etc/passwd", "bundles/../../escape", "..\\escape"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    publish.extract_release(self.make_archive(name), Path(folder))
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_reject_symbolic_link(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                publish.extract_release(self.make_archive("link", tarfile.SYMTYPE), Path(folder))


class PublishReleaseTests(unittest.TestCase):
    def test_validate_matching_client_and_homeserver(self):
        with tempfile.TemporaryDirectory() as folder:
            release = Path(folder)
            (release / "index.html").write_text("client")
            (release / "bundles").mkdir()
            (release / "revision.json").write_text(json.dumps({"commit": "a" * 40}))
            (release / "config.json").write_text(json.dumps({
                "default_server_config": {"m.homeserver": {"base_url": "https://matrix.547626.xyz"}},
            }))
            publish.validate_release(release, "a" * 40)
            with self.assertRaises(ValueError):
                publish.validate_release(release, "b" * 40)

    def test_activate_release(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            release = root / "new-release"
            release.mkdir()
            with patch.multiple(publish, ROOT=root, CURRENT=root / "current"), patch.object(
                publish.subprocess, "run"
            ):
                publish.activate_release(release)
            self.assertEqual((root / "current").resolve(), release)

    def test_failed_health_check_restores_previous_release(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            previous = root / "previous"
            previous.mkdir()
            release = root / "new-release"
            release.mkdir()
            (root / "current").symlink_to(previous)
            with patch.multiple(publish, ROOT=root, CURRENT=root / "current"), patch.object(
                publish.subprocess, "run",
                side_effect=[None, None, subprocess.CalledProcessError(1, "curl")],
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    publish.activate_release(release)
            self.assertEqual((root / "current").resolve(), previous)

    def test_failed_first_release_removes_broken_link(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            release = root / "new-release"
            release.mkdir()
            with patch.multiple(publish, ROOT=root, CURRENT=root / "current"), patch.object(
                publish.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "nginx")
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    publish.activate_release(release)
            self.assertFalse((root / "current").is_symlink())


if __name__ == "__main__":
    unittest.main()
