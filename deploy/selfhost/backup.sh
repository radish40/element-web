#!/usr/bin/env bash
# Copyright 2026 radish40
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail
umask 077

root=/opt/radish-chat
exec 9>"$root/backup.lock"
flock -n 9 || exit 0
stamp=$(date -u +%Y%m%dT%H%M%SZ)
staging=$(mktemp -d "$root/backups/.backup-XXXXXX")
trap 'rm -rf -- "$staging"' EXIT
podman exec radish-chat-postgres pg_dump -U synapse -Fc synapse > "$staging/synapse.dump"
podman exec -i radish-chat-postgres pg_restore --list < "$staging/synapse.dump" > /dev/null
tar -C "$root" -czf "$staging/server-data.tar.gz" private data/synapse
readlink -f "$root/current" > "$staging/client-release.txt"
mv "$staging" "$root/backups/$stamp"
trap - EXIT
find "$root/backups" -mindepth 1 -maxdepth 1 -type d -name '20??????T??????Z' -mtime +6 -exec rm -rf -- {} +
echo "Backup completed at $root/backups/$stamp"
