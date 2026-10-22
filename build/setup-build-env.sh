#!/bin/bash
# DevOS Build Environment Setup Script
# Installs required host dependencies on Ubuntu 26.04 LTS (Resolute) to build DevOS ISO
set -euo pipefail

echo "=========================================================="
echo "          DevOS Host Build Environment Setup              "
echo "=========================================================="

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root (or via sudo)." >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive

echo "==> Updating package indices..."
apt-get update -y

echo "==> Installing ISO creation tools, bootloaders, and utilities..."
apt-get install -y --no-install-recommends \
    debootstrap \
    squashfs-tools \
    xorriso \
    isolinux \
    syslinux-utils \
    mtools \
    dosfstools \
    grub-pc-bin \
    grub-efi-amd64-bin \
    grub-efi-ia32-bin \
    binutils \
    rsync \
    curl \
    ca-certificates \
    coreutils \
    file \
    gdisk \
    initramfs-tools-core \
    zstd \
    make

echo "==> Verifying core build binaries..."
for bin in debootstrap mksquashfs xorriso grub-mkrescue zstd; do
    if command -v "$bin" >/dev/null 2>&1; then
        echo "  [OK] $bin found: $(command -v "$bin")"
    else
        echo "  [WARN] Optional or path check: $bin"
    fi
done

echo "=========================================================="
echo " Build environment setup complete! You can now run:       "
echo "   make iso                                               "
echo "=========================================================="
