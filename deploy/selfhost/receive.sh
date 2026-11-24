#!/usr/bin/env bash
# Copyright 2026 radish40
# SPDX-License-Identifier: AGPL-3.0-only
set -euo pipefail

if [[ ! ${SSH_ORIGINAL_COMMAND:-} =~ ^(deploy|rollback)\ ([0-9a-f]{40})$ ]]; then
    echo 'Expected deploy or rollback followed by a complete commit SHA' >&2
    exit 1
fi
exec sudo -n /usr/local/libexec/radish-chat/publish.py "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
