#!/bin/bash
# DevOS Automated Build & Test Runner for WSL / Linux
set -euo pipefail

DEVOS_SRC="/mnt/host/c/docker/DevOS"
WORK_DIR="/mnt/docker-desktop-disk/devos_work"
ISO_DIR="/mnt/docker-desktop-disk/devos_iso"
OUT_DIR="${DEVOS_SRC}/out"
OUTPUT_ISO="${OUT_DIR}/devos-24.04-amd64.iso"

echo "=========================================================="
echo "          DevOS Production ISO Builder                    "
echo "=========================================================="
echo "Source: ${DEVOS_SRC}"
echo "Rootfs: ${WORK_DIR}"
echo "Target: ${OUTPUT_ISO}"
echo "=========================================================="

mkdir -p "${ISO_DIR}/casper" "${ISO_DIR}/boot/grub" "${OUT_DIR}"

# 1. Setup DNS and APT in Chroot
echo "nameserver 1.1.1.1" > "${WORK_DIR}/etc/resolv.conf"
cat << 'EOF' > "${WORK_DIR}/etc/apt/sources.list"
deb http://archive.ubuntu.com/ubuntu/ noble main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu/ noble-updates main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu/ noble-security main restricted universe multiverse
EOF

# 2. Bind virtual filesystems
cleanup() {
    echo "==> Cleaning up mount points..."
    for m in "${WORK_DIR}/dev/pts" "${WORK_DIR}/dev" "${WORK_DIR}/proc" "${WORK_DIR}/sys"; do
        if mountpoint -q "$m" 2>/dev/null; then
            umount -lf "$m" || true
        fi
    done
}
trap cleanup EXIT

mount --bind /dev "${WORK_DIR}/dev"
mount --bind /dev/pts "${WORK_DIR}/dev/pts"
mount -t proc proc "${WORK_DIR}/proc"
mount -t sysfs sysfs "${WORK_DIR}/sys"

# 3. Ensure essential packages are present
echo "==> Verifying core packages in chroot..."
chroot "${WORK_DIR}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    zram-tools \
    earlyoom \
    calamares \
    kpmcore \
    squashfs-tools \
    rsync || true

# 4. Copy custom configurations and hooks
echo "==> Applying DevOS includes and configs..."
cp -r "${DEVOS_SRC}/build/includes.chroot/." "${WORK_DIR}/" || true

# Set Hostname
echo "devos" > "${WORK_DIR}/etc/hostname"
cat << 'EOF' > "${WORK_DIR}/etc/hosts"
127.0.0.1   localhost devos
::1         localhost ip6-localhost ip6-loopback
EOF

# 5. Execute optimization hooks
echo "==> Running optimization hooks..."
for hook in "${DEVOS_SRC}/build/hooks/"*.hook.chroot; do
    if [ -f "$hook" ]; then
        echo "  Running: $(basename "$hook")"
        cp "$hook" "${WORK_DIR}/tmp/run_hook.sh"
        chmod +x "${WORK_DIR}/tmp/run_hook.sh"
        chroot "${WORK_DIR}" /tmp/run_hook.sh || true
        rm -f "${WORK_DIR}/tmp/run_hook.sh"
    fi
done

# 6. Extract Kernel & Initramfs
echo "==> Extracting live boot kernel and initrd..."
VMLINUZ=$(ls -1 "${WORK_DIR}/boot/vmlinuz-"* 2>/dev/null | sort -V | tail -n 1)
INITRD=$(ls -1 "${WORK_DIR}/boot/initrd.img-"* 2>/dev/null | sort -V | tail -n 1)

if [ -z "$VMLINUZ" ] || [ -z "$INITRD" ]; then
    echo "ERROR: Kernel or initrd not found in ${WORK_DIR}/boot"
    exit 1
fi

cp "$VMLINUZ" "${ISO_DIR}/casper/vmlinuz"
cp "$INITRD" "${ISO_DIR}/casper/initrd"

# 7. Unmount chroot before building SquashFS
cleanup

# 8. Build SquashFS on host
echo "==> Creating filesystem.squashfs with zstd compression..."
rm -f "${ISO_DIR}/casper/filesystem.squashfs"
mksquashfs "${WORK_DIR}" "${ISO_DIR}/casper/filesystem.squashfs" \
    -comp zstd -Xcompression-level 15 \
    -noappend -e boot -e dev -e proc -e sys -e tmp -e "ubuntu-base-*"

# Record filesystem size
du -sk "${WORK_DIR}" | awk '{print $1 * 1024}' > "${ISO_DIR}/casper/filesystem.size"

# 9. Configure GRUB
echo "==> Configuring GRUB bootloader..."
cat << 'EOF' > "${ISO_DIR}/boot/grub/grub.cfg"
set default="0"
set timeout=5

menuentry "Try or Install DevOS (24.04 LTS)" {
    set gfxpayload=keep
    linux /casper/vmlinuz boot=casper quiet splash fsck.mode=skip ---
    initrd /casper/initrd
}

menuentry "DevOS (Safe Graphics Mode)" {
    set gfxpayload=keep
    linux /casper/vmlinuz boot=casper nomodeset quiet splash ---
    initrd /casper/initrd
}
EOF

# 10. Generate EFI boot image
echo "==> Generating EFI boot image..."
mkdir -p /tmp/devos_efi/EFI/BOOT
grub-mkstandalone \
    --format=x86_64-efi \
    --output=/tmp/devos_efi/EFI/BOOT/BOOTX64.EFI \
    --locales="" \
    --fonts="" \
    "boot/grub/grub.cfg=${ISO_DIR}/boot/grub/grub.cfg" || true

# If grub-mkstandalone failed, copy from Ubuntu chroot
if [ ! -f /tmp/devos_efi/EFI/BOOT/BOOTX64.EFI ]; then
    if [ -f "${WORK_DIR}/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed" ]; then
        cp "${WORK_DIR}/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed" /tmp/devos_efi/EFI/BOOT/BOOTX64.EFI
    fi
fi

rm -f "${ISO_DIR}/boot/grub/efi.img"
dd if=/dev/zero of="${ISO_DIR}/boot/grub/efi.img" bs=1M count=10
mkfs.vfat "${ISO_DIR}/boot/grub/efi.img"
mcopy -s -i "${ISO_DIR}/boot/grub/efi.img" /tmp/devos_efi/EFI :: || true

# 11. Assemble Hybrid ISO with xorriso
echo "==> Assembling final hybrid BIOS+UEFI ISO..."
xorriso -as mkisofs \
    -r -V "DEVOS_2404" \
    -J -joliet-long \
    -append_partition 2 0xef "${ISO_DIR}/boot/grub/efi.img" \
    -appended_part_as_gpt \
    -output "${OUTPUT_ISO}" \
    "${ISO_DIR}"

# 12. Size Report
echo "=========================================================="
echo "             DevOS Build Completed Successfully           "
echo "=========================================================="
ISO_SIZE=$(du -h "${OUTPUT_ISO}" | cut -f1)
ISO_BYTES=$(stat -c%s "${OUTPUT_ISO}")
echo "ISO Location: ${OUTPUT_ISO}"
echo "Final ISO Size: ${ISO_SIZE} (${ISO_BYTES} bytes)"
sha256sum "${OUTPUT_ISO}" > "${OUTPUT_ISO}.sha256"
echo "SHA256: $(cat "${OUTPUT_ISO}.sha256")"
echo "=========================================================="
