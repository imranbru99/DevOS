#!/bin/bash
# Bootstrap the published updater on an existing DevOS installation.
set -euo pipefail
command -v python3 >/dev/null || { echo 'Python 3 is required.' >&2; exit 1; }
command -v curl >/dev/null || { echo 'Install curl first.' >&2; exit 1; }
script=$(mktemp /tmp/devos-updater.XXXXXXXX.py)
trap 'rm -f "$script"' EXIT
curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 \
    https://raw.githubusercontent.com/imranbru99/DevOS/main/components/updater/updater.py -o "$script"
python3 "$script" "$@"
