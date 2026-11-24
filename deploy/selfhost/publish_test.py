# Copyright 2026 radish40
# SPDX-License-Identifier: AGPL-3.0-only

import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
