# Shared DevOS Python app launcher helpers.
# Source from /usr/local/bin wrappers:
#   . /usr/local/lib/devos/python-app.sh
#   devos_exec_python desktop_id /path/to/script.py "$@"
#
# Forces argv0 / process title so Plasma never shows "python3" or a blank icon.

devos_components_dir() {
  local dir="/usr/local/share/devos/components"
  if [ -d "/home/imran/project/dev-os/components" ]; then
    dir="/home/imran/project/dev-os/components"
  fi
  printf '%s' "$dir"
}

devos_exec_python() {
  local desktop_id="${1:-}"
  local script="${2:-}"
  shift 2 || true
  if [ -z "$desktop_id" ] || [ -z "$script" ]; then
    echo "devos_exec_python: desktop_id and script required" >&2
    exit 2
  fi
  desktop_id="${desktop_id%.desktop}"
  export DEVOS_DESKTOP_FILE="$desktop_id"
  export RESOURCE_NAME="$desktop_id"
  # Prefer the dedicated runner when present (sets app_identity before Qt starts).
  if [ -x /usr/local/bin/devos-run ]; then
    exec /usr/local/bin/devos-run --desktop="$desktop_id" "$script" "$@"
  fi
  exec -a "$desktop_id" /usr/bin/python3 "$script" "$@"
}
