#!/bin/bash
# DevOS Automated QEMU Smoke Test Script
# Tests ISO boot under legacy BIOS and modern UEFI / OVMF
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

MODE="${1:-bios}"
ISO_PATH="${ROOT_DIR}/out/devos-26.04-amd64.iso"
DISK_IMAGE="${ROOT_DIR}/tests/qemu/test-disk.qcow2"
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

# Prepare temporary test virtual disk for Calamares target
if [ ! -f "${DISK_IMAGE}" ]; then
    echo "==> Creating 20GB test virtual disk (${DISK_IMAGE})..."
    qemu-img create -f qcow2 "${DISK_IMAGE}" 20G
fi

QEMU_ARGS=(
    -m "${RAM_MB}"
    -smp "${CPUS}"
    -cdrom "${ISO_PATH}"
    -drive "file=${DISK_IMAGE},format=qcow2,if=virtio"
    -net nic,model=virtio
    -net user
    -vga virtio
)

# Enable KVM hardware acceleration if available
if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    echo "==> Enabling KVM hardware acceleration..."
    QEMU_ARGS+=(-enable-kvm -cpu host)
else
    echo "==> KVM not available; using TCG emulation (cpu max)..."
    QEMU_ARGS+=(-cpu max)
fi

if [ "$MODE" = "uefi" ]; then
    echo "==> Configuring UEFI (OVMF) firmware..."
    OVMF_PATH=""
    for candidate in \
        /usr/share/OVMF/OVMF_CODE.fd \
        /usr/share/qemu/OVMF.fd \
        /usr/share/edk2/ovmf/OVMF_CODE.fd \
        /usr/share/edk2-ovmf/x64/OVMF_CODE.fd; do
        if [ -f "$candidate" ]; then
            OVMF_PATH="$candidate"
            break
        fi
    done

    if [ -z "$OVMF_PATH" ]; then
        echo "ERROR: OVMF UEFI firmware not found. Please install ovmf / qemu-efi." >&2
        exit 1
    fi
    echo "  Using OVMF firmware: ${OVMF_PATH}"
    QEMU_ARGS+=(-bios "${OVMF_PATH}")
    echo "==> Booting DevOS in UEFI mode..."
else
    echo "==> Booting DevOS in Legacy BIOS mode..."
fi

echo "==> Executing: qemu-system-x86_64 ${QEMU_ARGS[*]}"
qemu-system-x86_64 "${QEMU_ARGS[@]}"
