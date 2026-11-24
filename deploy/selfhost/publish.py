#!/usr/bin/env python3
# Copyright 2026 radish40
# SPDX-License-Identifier: AGPL-3.0-only

"""Publish an immutable client release, or atomically restore an existing one."""

import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path("/opt/radish-chat")
RELEASES = ROOT / "releases"
CURRENT = ROOT / "current"


def extract_release(archive, destination):
    """Extract only regular files and directories inside a new release directory."""
    with tarfile.open(fileobj=archive, mode="r:gz") as bundle:
        members = bundle.getmembers()
        if len(members) > 50000 or sum(member.size for member in members) > 3 * 1024**3:
            raise ValueError("Release archive exceeds the size limit")
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or "\\" in member.name:
                raise ValueError("Unsafe archive path")
            if not (member.isdir() or member.isfile()):
                raise ValueError("Archive links and special files are forbidden")
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(member) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o644)


def validate_release(release, commit):
    if not (release / "index.html").is_file() or not (release / "bundles").is_dir():
        raise ValueError("Release is missing the client application")
    revision = json.loads((release / "revision.json").read_text())
    config = json.loads((release / "config.json").read_text())
    if revision["commit"] != commit:
        raise ValueError("Release commit does not match the requested commit")
    if config["default_server_config"]["m.homeserver"]["base_url"] != "https://matrix.547626.xyz":
        raise ValueError("Release points to an unexpected homeserver")


def activate_release(release):
    previous = CURRENT.resolve() if CURRENT.is_symlink() else None
    pending = ROOT / "current.next"
    pending.unlink(missing_ok=True)
    pending.symlink_to(release)
    os.replace(pending, CURRENT)
    try:
        subprocess.run(["restorecon", "-RF", str(release)], check=True)
        subprocess.run(["nginx", "-t", "-q"], check=True)
        subprocess.run(
            ["curl", "-fsS", "--max-time", "15", "--resolve", "chat.547626.xyz:443:127.0.0.1",
             "https://chat.547626.xyz/revision.json", "-o", "/dev/null"],
            check=True,
        )
    except Exception:
        if previous:
            pending.symlink_to(previous)
            os.replace(pending, CURRENT)
        else:
            CURRENT.unlink(missing_ok=True)
        raise


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("deploy", "rollback"):
        raise ValueError("Usage: publish.py deploy|rollback COMMIT")
    action, commit = sys.argv[1:]
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A complete commit SHA is required")
    RELEASES.mkdir(parents=True, exist_ok=True)
    with (ROOT / "publish.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        release = RELEASES / commit
        if action == "deploy" and not release.exists():
            with tempfile.NamedTemporaryFile(dir=ROOT) as archive:
                received = 0
                while chunk := sys.stdin.buffer.read(1024 * 1024):
                    received += len(chunk)
                    if received > 1024**3:
                        raise ValueError("Compressed release exceeds 1 GiB")
                    archive.write(chunk)
                archive.flush()
                staging = Path(tempfile.mkdtemp(prefix=".release-", dir=RELEASES))
                try:
                    staging.chmod(0o755)
                    archive.seek(0)
                    extract_release(archive, staging)
                    validate_release(staging, commit)
                    staging.rename(release)
                finally:
                    if staging.exists():
                        shutil.rmtree(staging)
        validate_release(release, commit)
        activate_release(release)
        print(json.dumps({"action": action, "commit": commit, "url": "https://chat.547626.xyz"}))


if __name__ == "__main__":
    main()
