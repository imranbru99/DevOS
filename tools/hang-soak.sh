#!/bin/bash
# Sample PSI and kernel journal during a long interactive workload soak.
# Exits non-zero on hung-task reports or sustained high memory pressure.
set -euo pipefail

MINUTES=60
INTERVAL_SEC=10
# Fail when memory pressure "some" avg10 stays at or above this level for
# DEVOS_SOAK_MEM_CONSEC consecutive samples (default 3 ~= 30s at 10s interval).
MEM_AVG10_FAIL="${DEVOS_SOAK_MEM_AVG10_FAIL:-80.0}"
MEM_CONSEC_FAIL="${DEVOS_SOAK_MEM_CONSEC:-3}"

usage() {
  cat <<EOF
Usage: $0 [--minutes N] [--interval SEC] [--dry-run]

Watch /proc/pressure, journal hung-task warnings, and optional devos smooth status.
Environment:
  DEVOS_SOAK_MEM_AVG10_FAIL   memory some avg10 threshold (default ${MEM_AVG10_FAIL})
  DEVOS_SOAK_MEM_CONSEC       consecutive high samples before fail (default ${MEM_CONSEC_FAIL})
EOF
}

DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --minutes) MINUTES="${2:?}"; shift 2 ;;
    --interval) INTERVAL_SEC="${2:?}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

read_avg10() {
  local file="$1"
  [ -r "$file" ] || { echo ""; return 0; }
  awk '/^some / {
    for (i = 1; i <= NF; i++) {
      if ($i ~ /^avg10=/) { sub(/^avg10=/, "", $i); print $i; exit }
    }
  }' "$file"
}

START_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
END_EPOCH=$(( $(date +%s) + MINUTES * 60 ))
if [ "${DRY_RUN}" -eq 1 ]; then
  END_EPOCH=$(( $(date +%s) + INTERVAL_SEC ))
fi

high_mem_streak=0
hung_seen=0

echo "==> Hang soak: ${MINUTES} min, sample every ${INTERVAL_SEC}s (since ${START_ISO})"
echo "    memory fail: some avg10 >= ${MEM_AVG10_FAIL} for ${MEM_CONSEC_FAIL} consecutive samples"

while [ "$(date +%s)" -lt "${END_EPOCH}" ]; do
  stamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  for res in cpu memory io; do
    p="/proc/pressure/${res}"
    if [ -r "$p" ]; then
      avg10="$(read_avg10 "$p")"
      printf '[%s] pressure %s some avg10=%s\n' "$stamp" "$res" "${avg10:-n/a}"
      if [ "$res" = memory ] && [ -n "${avg10:-}" ]; then
        if awk -v v="$avg10" -v lim="$MEM_AVG10_FAIL" 'BEGIN { exit !(v+0 >= lim+0) }'; then
          high_mem_streak=$((high_mem_streak + 1))
        else
          high_mem_streak=0
        fi
      fi
    else
      printf '[%s] pressure %s unavailable\n' "$stamp" "$res"
    fi
  done

  if command -v journalctl >/dev/null 2>&1; then
    if journalctl -k -b --no-pager --grep='hung task|Blocked for more than' \
        --since="$START_ISO" 2>/dev/null | grep -qE 'hung task|Blocked for more than'; then
      hung_seen=1
      echo "[${stamp}] FAIL: kernel hung-task/blocking message in this boot"
    fi
  fi

  if command -v devos >/dev/null 2>&1; then
    devos smooth status 2>/dev/null | head -n 20 || true
  elif [ -x "./components/optimizer/responsiveness.py" ] || [ -f "./components/optimizer/responsiveness.py" ]; then
    python3 components/optimizer/responsiveness.py status 2>/dev/null | head -n 20 || true
  fi

  if [ "${high_mem_streak}" -ge "${MEM_CONSEC_FAIL}" ]; then
    echo "[${stamp}] FAIL: memory some avg10 >= ${MEM_AVG10_FAIL} for ${MEM_CONSEC_FAIL} samples"
    exit 1
  fi
  if [ "${hung_seen}" -eq 1 ]; then
    exit 1
  fi

  sleep "${INTERVAL_SEC}"
done

echo "==> Hang soak finished without hung-task or sustained memory pressure failures"
