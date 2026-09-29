#!/usr/bin/env bash
set -euo pipefail
if [[ $(id -u) != 0 ]]; then
    echo 'Run with sudo bash install.sh (or bash install.sh as root).' >&2
    exit 1
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if ! command -v python3 >/dev/null || ! command -v ip >/dev/null; then
    apt-get update
    apt-get install -y python3 iproute2
fi
exec python3 deploy/install.py "$@"
