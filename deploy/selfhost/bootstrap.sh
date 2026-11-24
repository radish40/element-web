#!/usr/bin/env bash
# Copyright 2026 radish40
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
test "$(id -u)" -eq 0
root=/opt/radish-chat
files=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
synapse=ghcr.io/element-hq/synapse@sha256:673b4223c81a7634fd07d832b939a58f97081cfdaae7cdd2d1664cdcf7611b62
postgres=docker.io/library/postgres@sha256:e5f8ac607c7d44a0da3a42712a3e978b75fb1757e9f3e1488cd0cca4dbec76e9

install -d -m 0755 "$root" "$root/releases" "$root/data" /usr/local/libexec/radish-chat
install -d -m 0700 "$root/private" "$root/backups"
install -d -o 991 -g 991 -m 0750 "$root/data/synapse"
install -d -m 0700 "$root/data/postgres"
install -m 0755 "$files/publish.py" /usr/local/libexec/radish-chat/publish.py
install -m 0755 "$files/receive.sh" /usr/local/libexec/radish-chat/receive.sh
install -m 0755 "$files/backup.sh" /usr/local/libexec/radish-chat/backup.sh
podman pull "$synapse"
podman pull "$postgres"

if ! test -f "$root/data/synapse/547626.xyz.signing.key"; then
    podman run --rm -e SYNAPSE_SERVER_NAME=547626.xyz -e SYNAPSE_REPORT_STATS=no \
        -v "$root/data/synapse:/data:Z" "$synapse" generate
fi
python3 - <<'PYTHON'
import json
from pathlib import Path
import secrets
import os
import shutil
import tempfile

os.umask(0o077)
root = Path('/opt/radish-chat')
private = root / 'private'
secrets_file = private / 'server-secrets.json'
if not secrets_file.exists():
    secrets_file.write_text(json.dumps({
        'database_password': secrets.token_urlsafe(36),
        'registration_secret': secrets.token_urlsafe(48),
        'macaroon_secret': secrets.token_urlsafe(48),
        'form_secret': secrets.token_urlsafe(48),
    }, indent=4) + '\n')
values = json.loads(secrets_file.read_text())
(private / 'postgres.env').write_text(
    'POSTGRES_USER=synapse\nPOSTGRES_DB=synapse\n'
    'POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale=C\n'
    'POSTGRES_PASSWORD=' + values['database_password'] + '\n'
)
config = {
    'server_name': '547626.xyz',
    'public_baseurl': 'https://matrix.547626.xyz/',
    'pid_file': '/data/homeserver.pid',
    'listeners': [{
        'port': 8008, 'tls': False, 'type': 'http', 'x_forwarded': True,
        'bind_addresses': ['0.0.0.0'],
        'resources': [{'names': ['client', 'federation'], 'compress': False}],
    }],
    'database': {'name': 'psycopg2', 'args': {
        'user': 'synapse', 'password': values['database_password'],
        'database': 'synapse', 'host': 'radish-chat-postgres', 'port': 5432,
        'cp_min': 5, 'cp_max': 10,
    }},
    'log_config': '/data/log.config',
    'media_store_path': '/data/media_store',
    'signing_key_path': '/data/547626.xyz.signing.key',
    'registration_shared_secret': values['registration_secret'],
    'macaroon_secret_key': values['macaroon_secret'],
    'form_secret': values['form_secret'],
    'enable_registration': False,
    'enable_registration_without_verification': False,
    'allow_guest_access': False,
    'max_upload_size': '100M',
    'report_stats': False,
    'trusted_key_servers': [{'server_name': 'matrix.org'}],
    'suppress_key_server_warning': True,
}
synapse = root / 'data' / 'synapse'
log = {
    'version': 1,
    'formatters': {'standard': {'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'standard'}},
    'root': {'level': 'INFO', 'handlers': ['console']},
}
for name, content in [('homeserver.yaml', config), ('log.config', log)]:
    target = synapse / name
    if target.exists():
        shutil.copy2(target, target.with_name(name + '.before-bootstrap'))
    with tempfile.NamedTemporaryFile(mode='w', dir=synapse, delete=False) as staged:
        staged.write(json.dumps(content, indent=4) + '\n')
        staged.flush()
        os.fsync(staged.fileno())
        os.fchown(staged.fileno(), 991, 991)
        os.fchmod(staged.fileno(), 0o600)
    os.replace(staged.name, target)
PYTHON

install -d -m 0755 /etc/containers/systemd
cat > /etc/containers/systemd/radish-chat.network <<'NETWORK'
[Network]
NetworkName=radish-chat
NETWORK
cat > /etc/containers/systemd/radish-chat-postgres.container <<POSTGRES
[Unit]
Description=Radish Chat PostgreSQL
[Container]
Image=$postgres
ContainerName=radish-chat-postgres
Network=radish-chat.network
EnvironmentFile=$root/private/postgres.env
Volume=$root/data/postgres:/var/lib/postgresql/data:Z
[Service]
Restart=always
TimeoutStartSec=180
[Install]
WantedBy=multi-user.target
POSTGRES
cat > /etc/containers/systemd/radish-chat-synapse.container <<SYNAPSE
[Unit]
Description=Radish Chat Synapse
Requires=radish-chat-postgres.service
After=radish-chat-postgres.service
[Container]
Image=$synapse
ContainerName=radish-chat-synapse
Network=radish-chat.network
Volume=$root/data/synapse:/data:Z
PublishPort=127.0.0.1:8008:8008
[Service]
Restart=always
RestartSec=5
TimeoutStartSec=180
[Install]
WantedBy=multi-user.target
SYNAPSE
systemctl daemon-reload
systemctl start radish-chat-postgres.service
for attempt in $(seq 1 40); do
    if podman exec radish-chat-postgres pg_isready -U synapse -d synapse > /dev/null; then break; fi
    sleep 2
done
podman exec radish-chat-postgres pg_isready -U synapse -d synapse
systemctl start radish-chat-synapse.service

if ! id chat-deploy > /dev/null 2>&1; then useradd --create-home --shell /bin/bash chat-deploy; fi
passwd -l chat-deploy > /dev/null
install -d -o chat-deploy -g chat-deploy -m 0700 /home/chat-deploy/.ssh
if ! test -f "$root/private/actions-deploy"; then
    ssh-keygen -q -t ed25519 -N '' -C radish-chat-actions -f "$root/private/actions-deploy"
fi
printf 'restrict,command="/usr/local/libexec/radish-chat/receive.sh" %s\n' \
    "$(cat "$root/private/actions-deploy.pub")" > /home/chat-deploy/.ssh/authorized_keys
chown chat-deploy:chat-deploy /home/chat-deploy/.ssh/authorized_keys
chmod 0600 /home/chat-deploy/.ssh/authorized_keys
printf '%s\n' 'chat-deploy ALL=(root) NOPASSWD: /usr/local/libexec/radish-chat/publish.py *' \
    > /etc/sudoers.d/radish-chat-deploy
chmod 0440 /etc/sudoers.d/radish-chat-deploy
visudo -cf /etc/sudoers.d/radish-chat-deploy

if ! semanage fcontext -l | grep -F '/opt/radish-chat/releases(/.*)?' > /dev/null; then
    semanage fcontext -a -t httpd_sys_content_t '/opt/radish-chat/releases(/.*)?'
fi
restorecon -RF "$root/releases"
setsebool -P httpd_can_network_connect 1

cat > /etc/systemd/system/radish-chat-backup.service <<'BACKUP'
[Unit]
Description=Back up Radish Chat database, configuration and media
After=radish-chat-postgres.service
[Service]
Type=oneshot
ExecStart=/usr/local/libexec/radish-chat/backup.sh
BACKUP
cat > /etc/systemd/system/radish-chat-backup.timer <<'TIMER'
[Unit]
Description=Daily Radish Chat backup
[Timer]
OnCalendar=*-*-* 19:00:00 UTC
RandomizedDelaySec=900
Persistent=true
[Install]
WantedBy=timers.target
TIMER
systemctl daemon-reload
systemctl enable --now radish-chat-backup.timer
for attempt in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:8008/_matrix/client/versions > /dev/null; then
        echo 'Synapse is ready'
        exit 0
    fi
    sleep 2
done
journalctl -u radish-chat-synapse.service -n 40 --no-pager
exit 1
