#!/bin/bash
# Fail-closed live ISO serial boot gate for CI.
# Boots the ISO in QEMU and requires GRUB / live menu markers in the serial log.
# Unlike a bare timeout observation, missing markers fail the job.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ISO_PATH="${1:-${ROOT_DIR}/out/devos-26.04-amd64.iso}"
MODE="${2:-bios}"
TIMEOUT_SEC="${DEVOS_LIVE_BOOT_TIMEOUT:-45}"
LOG_DIR="${ROOT_DIR}/out"
LOG="${LOG_DIR}/qemu-live-${MODE}.log"

case "$MODE" in bios|uefi) ;; *) echo "Usage: $0 [iso] [bios|uefi]" >&2; exit 2 ;; esac

if [ ! -f "${ISO_PATH}" ]; then
    echo "ERROR: ISO not found at ${ISO_PATH}" >&2
    exit 1
fi
if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
    echo "ERROR: qemu-system-x86_64 is not installed." >&2
    exit 1
fi

mkdir -p "${LOG_DIR}"
QEMU_ARGS=(
    -m "${QEMU_RAM:-2048}"
    -smp "${QEMU_CPUS:-2}"
    -cdrom "${ISO_PATH}"
    -display none
    -vga virtio
    -serial stdio
    -no-reboot
)

if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    QEMU_ARGS+=(-enable-kvm -cpu host)
else
    QEMU_ARGS+=(-cpu max)
fi

if [ "$MODE" = "uefi" ]; then
    # shellcheck source=firmware.sh
    source "${SCRIPT_DIR}/firmware.sh"
    devos_find_ovmf
    VARS="${LOG_DIR}/ovmf_vars_${MODE}.fd"
    cp -f "${OVMF_VARS_TEMPLATE}" "${VARS}"
    QEMU_ARGS+=(-drive "if=pflash,format=raw,readonly=on,file=${OVMF_CODE}")
    QEMU_ARGS+=(-drive "if=pflash,format=raw,file=${VARS}")
fi

echo "==> Live serial boot assert (${MODE}, timeout ${TIMEOUT_SEC}s)..."
rm -f "${LOG}"
rc=0
timeout "${TIMEOUT_SEC}" qemu-system-x86_64 "${QEMU_ARGS[@]}" < /dev/null > "${LOG}" 2>&1 || rc=$?

echo "==> Last 50 lines of ${LOG}:"
tail -n 50 "${LOG}" || true

# QEMU process crash (not timeout) is always a failure.
if [ "$rc" -ne 0 ] && [ "$rc" -ne 124 ]; then
    echo "::error::QEMU exited with code $rc before boot markers were checked" >&2
    exit "$rc"
fi

if grep -qE "Try or Install DevOS|DevOS \\(Safe Graphics\\)|GNU GRUB|boot:|casper" "${LOG}"; then
    echo "==> Live ${MODE} serial boot assert PASSED"
    exit 0
fi

echo "::error::Live ${MODE} boot markers not found in serial log" >&2
echo "    Full log: ${LOG}" >&2
exit 1
