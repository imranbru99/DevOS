#!/bin/bash
# Test the ISO as if it were written to a real USB stick with dd.
# This catches the hybrid-MBR/GPT bugs that a virtual CD-ROM test misses.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ISO_PATH="${ROOT_DIR}/out/devos-24.04-amd64.iso"

MODE="${1:-bios}"
TMP_DIR="${ROOT_DIR}/tests/qemu/usb-test-tmp"
USB_IMG="${TMP_DIR}/usb.img"
LOG="${TMP_DIR}/usb-${MODE}.log"
RAM_MB="${QEMU_RAM:-4096}"
CPUS="${QEMU_CPUS:-2}"

if [ ! -f "${ISO_PATH}" ]; then
    echo "ERROR: ISO image not found at ${ISO_PATH}. Run 'make iso' first." >&2
    exit 1
fi

if ! command -v qemu-system-x86_64 >/dev/null 2>&1; then
    echo "ERROR: qemu-system-x86_64 is not installed." >&2
    exit 1
fi

mkdir -p "${TMP_DIR}"
ISO_BYTES="$(stat -c%s "${ISO_PATH}")"
IMG_BYTES=$((ISO_BYTES + 2 * 1024 * 1024))

# Build a fake USB stick: sparse file slightly larger than the ISO, dd the ISO
# into the first bytes so the MBR/GPT layout is preserved exactly like a real
# dd-written stick.
echo "==> Creating dd-written USB image (${IMG_BYTES} bytes)..."
rm -f "${USB_IMG}"
truncate -s "${IMG_BYTES}" "${USB_IMG}"
dd if="${ISO_PATH}" of="${USB_IMG}" bs=1M conv=notrunc status=progress

QEMU_ARGS=(
    -m "${RAM_MB}"
    -smp "${CPUS}"
    -drive "file=${USB_IMG},format=raw,if=none,id=usbstick"
    -device "usb-storage,drive=usbstick"
    -net nic,model=virtio
    -net user
    -nographic
    -serial mon:stdio
)

if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    QEMU_ARGS+=(-enable-kvm -cpu host)
else
    QEMU_ARGS+=(-cpu max)
fi

if [ "$MODE" = "uefi" ]; then
    OVMF_CODE=""
    OVMF_VARS_TEMPLATE=""
    for cand in \
        /usr/share/OVMF/OVMF_CODE.fd \
        /usr/share/qemu/OVMF.fd \
        /usr/share/edk2/ovmf/OVMF_CODE.fd \
        /usr/share/edk2-ovmf/x64/OVMF_CODE.fd; do
        [ -f "$cand" ] && OVMF_CODE="$cand" && break
    done
    for cand in \
        /usr/share/OVMF/OVMF_VARS.fd \
        /usr/share/edk2/ovmf/OVMF_VARS.fd \
        /usr/share/edk2-ovmf/x64/OVMF_VARS.fd; do
        [ -f "$cand" ] && OVMF_VARS_TEMPLATE="$cand" && break
    done
    if [ -z "$OVMF_CODE" ]; then
        echo "ERROR: OVMF firmware not found." >&2
        exit 1
    fi
    cp -f "${OVMF_VARS_TEMPLATE:-${OVMF_CODE}}" "${TMP_DIR}/ovmf_vars.fd" 2>/dev/null || true
    QEMU_ARGS+=(-drive "if=pflash,format=raw,readonly=on,file=${OVMF_CODE}")
    QEMU_ARGS+=(-drive "if=pflash,format=raw,file=${TMP_DIR}/ovmf_vars.fd")
fi

echo "==> Booting USB image in QEMU (${MODE})..."
rm -f "${LOG}"
timeout 30 qemu-system-x86_64 "${QEMU_ARGS[@]}" > "${LOG}" 2>&1 || true

echo "==> Captured boot log (last 40 lines):"
tail -n 40 "${LOG}" || true

if grep -qE "Try or Install DevOS|DevOS \(Safe Graphics\)|GNU GRUB" "${LOG}"; then
    echo "==> USB ${MODE} boot test PASSED: GRUB menu reached on a dd-written USB stick"
    exit 0
else
    echo "==> USB ${MODE} boot test FAILED: GRUB menu was not observed" >&2
    echo "    Full log: ${LOG}" >&2
    exit 1
fi
