#!/usr/bin/env python3
# Copyright 2026 radish40
# SPDX-License-Identifier: AGPL-3.0-only

"""Install the TLS virtual hosts and Matrix discovery after issuing the certificate."""

from pathlib import Path
import shutil
import subprocess

configuration = Path("/etc/nginx/conf.d")
root = configuration / "547626.xyz.conf"
chat = configuration / "radish-chat.conf"
temporary = configuration / "radish-chat-http.conf"
root_original = root.read_bytes()
chat_original = chat.read_bytes() if chat.exists() else None
temporary_original = temporary.read_bytes() if temporary.exists() else None
backup = configuration / "547626.xyz.conf.before-radish-chat"
if not backup.exists():
    shutil.copy2(root, backup)

discovery = '''
    location = /.well-known/matrix/client {
        default_type application/json;
        add_header Access-Control-Allow-Origin "*" always;
        return 200 '{"m.homeserver":{"base_url":"https://matrix.547626.xyz"}}';
    }
    location = /.well-known/matrix/server {
        default_type application/json;
        return 200 '{"m.server":"matrix.547626.xyz:443"}';
    }
'''
content = root_original.decode()
if "/.well-known/matrix/client" not in content:
    marker = "    ssl_protocols TLSv1.2 TLSv1.3;\n"
    if content.count(marker) != 1:
        raise ValueError("Unexpected root virtual host configuration")
    content = content.replace(marker, marker + discovery)

try:
    root.write_text(content)
    chat.write_bytes(Path(__file__).with_name("nginx.conf").read_bytes())
    temporary.unlink(missing_ok=True)
    subprocess.run(["restorecon", "-F", str(root), str(chat)], check=True)
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
except Exception:
    root.write_bytes(root_original)
    if chat_original is None:
        chat.unlink(missing_ok=True)
    else:
        chat.write_bytes(chat_original)
    if temporary_original is not None:
        temporary.write_bytes(temporary_original)
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    raise
