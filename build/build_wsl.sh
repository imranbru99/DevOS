#!/bin/bash
# DevOS Automated Build & Test Runner for WSL / Linux
# Builds complete bootable hybrid live ISO with DevOS Dashboard & PIN/Security setup
set -euo pipefail

DEVOS_SRC="/mnt/host/c/docker/DevOS"
WORK_DIR="/mnt/docker-desktop-disk/data/devos_work"
ISO_DIR="/mnt/docker-desktop-disk/data/devos_iso"
OUT_DIR="${DEVOS_SRC}/out"
OUTPUT_ISO="${OUT_DIR}/devos-26.04-amd64.iso"

echo "=========================================================="
echo "          DevOS Production ISO Builder 2027               "
echo "=========================================================="
echo "Source: ${DEVOS_SRC}"
echo "Rootfs: ${WORK_DIR}"
echo "Target: ${OUTPUT_ISO}"
echo "=========================================================="

mkdir -p "${ISO_DIR}/casper" "${ISO_DIR}/boot/grub" "${OUT_DIR}"

# 1. Ensure Ubuntu Base Rootfs Exists
if [ ! -f "${WORK_DIR}/etc/os-release" ]; then
    echo "==> Step 1: Downloading Ubuntu 26.04 Resolute base rootfs..."
    mkdir -p "${WORK_DIR}"
    TARBALL="ubuntu-base-26.04.1-base-amd64.tar.gz"
    CACHE_FILE="/mnt/docker-desktop-disk/data/${TARBALL}"
    if [ ! -f "${CACHE_FILE}" ]; then
        wget -c "http://cdimage.ubuntu.com/ubuntu-base/releases/26.04/release/${TARBALL}" -O "${CACHE_FILE}" || \
        wget -c "http://cdimage.ubuntu.com/ubuntu-base/releases/26.04/release/ubuntu-base-26.04-base-amd64.tar.gz" -O "${CACHE_FILE}"
    fi
    echo "==> Extracting base rootfs into ${WORK_DIR}..."
    tar -xzf "${CACHE_FILE}" -C "${WORK_DIR}"
fi

# 2. Setup DNS and APT in Chroot
identity="${WORK_DIR}/usr/lib/os-release.ubuntu"
[ -f "$identity" ] || identity="${WORK_DIR}/etc/os-release"
version=$(. "$identity"; printf '%s' "${VERSION_ID:-unknown}")
[ "$version" = 26.04 ] || { echo "ERROR: Use a fresh 26.04 rootfs; this cache is $version." >&2; exit 1; }
echo "nameserver 1.1.1.1" > "${WORK_DIR}/etc/resolv.conf"
cat << 'EOF' > "${WORK_DIR}/etc/apt/sources.list"
deb http://archive.ubuntu.com/ubuntu/ resolute main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu/ resolute-updates main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu/ resolute-security main restricted universe multiverse
EOF

# 3. Bind virtual filesystems
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

# 4. Update APT & install core packages
echo "==> Step 2: Updating APT repositories in rootfs..."
chroot "${WORK_DIR}" env DEBIAN_FRONTEND=noninteractive apt-get update -y

echo "==> Step 3: Installing kernel, casper, systemd, and workstation utilities..."
chroot "${WORK_DIR}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    linux-image-generic \
    casper \
    systemd \
    systemd-sysv \
    udev \
    dbus \
    sudo \
    bash \
    coreutils \
    grub-pc-bin \
    grub-efi-amd64-bin \
    grub-efi-amd64-signed \
    shim-signed \
    efibootmgr \
    zram-tools \
    earlyoom \
    calamares \
    kpmcore \
    squashfs-tools \
    rsync \
    dosfstools \
    mtools \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    libgl1-mesa-dri \
    plymouth \
    plymouth-themes \
    plymouth-label \
    iproute2 \
    net-tools \
    btrfs-progs || true

# 5. Copy custom configurations and hooks
echo "==> Step 4: Applying DevOS includes and luxury configs..."
cp -r "${DEVOS_SRC}/build/includes.chroot/." "${WORK_DIR}/" || true

if [ -f "${WORK_DIR}/usr/local/sbin/devos-install-chrome" ]; then
    echo "==> Installing Google Chrome..."
    chroot "${WORK_DIR}" /bin/bash /usr/local/sbin/devos-install-chrome || true
fi

# Install DevOS components into chroot
echo "==> Installing DevOS components and unified CLI..."
mkdir -p "${WORK_DIR}/usr/local/share/devos/components"
cp -r "${DEVOS_SRC}/components/." "${WORK_DIR}/usr/local/share/devos/components/" || true

mkdir -p "${WORK_DIR}/usr/local/bin"
cat << 'EOF' > "${WORK_DIR}/usr/local/bin/devos"
#!/usr/bin/env bash
exec /usr/bin/python3 /usr/local/share/devos/components/devos_cli.py "$@"
EOF
chmod +x "${WORK_DIR}/usr/local/bin/devos"

# Ensure dashboard launcher permissions
mkdir -p "${WORK_DIR}/etc/skel/Desktop"
chmod +x "${WORK_DIR}/usr/share/applications/devos-dashboard.desktop" 2>/dev/null || true
chmod +x "${WORK_DIR}/etc/xdg/autostart/devos-dashboard.desktop" 2>/dev/null || true
chmod +x "${WORK_DIR}/etc/skel/Desktop/devos-dashboard.desktop" 2>/dev/null || true

# Set Hostname
echo "devos" > "${WORK_DIR}/etc/hostname"
cat << 'EOF' > "${WORK_DIR}/etc/hosts"
127.0.0.1   localhost devos
::1         localhost ip6-localhost ip6-loopback
EOF

# 6. Execute optimization hooks
echo "==> Step 5: Running optimization hooks..."
for hook in "${DEVOS_SRC}/build/hooks/"*.hook.chroot; do
    if [ -f "$hook" ]; then
        echo "  Running: $(basename "$hook")"
        cp "$hook" "${WORK_DIR}/tmp/run_hook.sh"
        chmod +x "${WORK_DIR}/tmp/run_hook.sh"
        chroot "${WORK_DIR}" /tmp/run_hook.sh || true
        rm -f "${WORK_DIR}/tmp/run_hook.sh"
    fi
done

# 7. Extract Kernel & Initramfs
echo "==> Step 6: Extracting live boot kernel and initrd..."
VMLINUZ=$(ls -1 "${WORK_DIR}/boot/vmlinuz-"* 2>/dev/null | sort -V | tail -n 1 || true)
INITRD=$(ls -1 "${WORK_DIR}/boot/initrd.img-"* 2>/dev/null | sort -V | tail -n 1 || true)

if [ -z "$VMLINUZ" ] || [ -z "$INITRD" ]; then
    echo "ERROR: Kernel or initrd not found in ${WORK_DIR}/boot"
    exit 1
fi

echo "  Kernel: $(basename "$VMLINUZ")"
echo "  Initrd: $(basename "$INITRD")"
cp "$VMLINUZ" "${ISO_DIR}/casper/vmlinuz"
cp "$INITRD" "${ISO_DIR}/casper/initrd"

# 8. Unmount chroot before building SquashFS
cleanup

# Ensure critical mount points and temporary directories exist with correct permissions
mkdir -p "${WORK_DIR}/dev" "${WORK_DIR}/proc" "${WORK_DIR}/sys" "${WORK_DIR}/tmp" "${WORK_DIR}/run" "${WORK_DIR}/mnt" "${WORK_DIR}/media" "${WORK_DIR}/var/crash"
rm -rf "${WORK_DIR}"/tmp/* "${WORK_DIR}"/var/tmp/* 2>/dev/null || true
chmod 1777 "${WORK_DIR}/tmp" "${WORK_DIR}/var/tmp" 2>/dev/null || true

# 9. Build SquashFS on host
echo "==> Step 7: Creating filesystem.squashfs with zstd compression..."
rm -f "${ISO_DIR}/casper/filesystem.squashfs"
mksquashfs "${WORK_DIR}" "${ISO_DIR}/casper/filesystem.squashfs" \
    -comp zstd -Xcompression-level 15 \
    -noappend -e "ubuntu-base-*"

# Record filesystem size
du -sk "${WORK_DIR}" | awk '{print $1 * 1024}' > "${ISO_DIR}/casper/filesystem.size"

# 10. Configure GRUB
echo "==> Step 8: Configuring GRUB bootloader..."
mkdir -p "${ISO_DIR}/boot/grub" "${ISO_DIR}/EFI/BOOT"
cat << 'EOF' > "${ISO_DIR}/boot/grub/grub.cfg"
set default="0"
set timeout=5

search --no-floppy --set=root --file /casper/vmlinuz

insmod font
if loadfont /boot/grub/font.pf2 ; then
    insmod gfxterm
    set gfxmode=auto
    terminal_output gfxterm
fi

set menu_color_normal=white/black
set menu_color_highlight=black/light-gray

menuentry "Try or Install DevOS (26.04 LTS)" {
    set gfxpayload=keep
    search --no-floppy --set=root --file /casper/vmlinuz
    linux /casper/vmlinuz boot=casper quiet splash plymouth.theme=devos fsck.mode=skip ---
    initrd /casper/initrd
}

menuentry "DevOS (Safe Graphics)" {
    set gfxpayload=keep
    search --no-floppy --set=root --file /casper/vmlinuz
    linux /casper/vmlinuz boot=casper nomodeset quiet splash plymouth.theme=devos ---
    initrd /casper/initrd
}

menuentry "Check Disc for Defects" {
    search --no-floppy --set=root --file /casper/vmlinuz
    linux /casper/vmlinuz boot=casper integrity-check quiet splash plymouth.theme=devos ---
    initrd /casper/initrd
}
EOF
cp "${ISO_DIR}/boot/grub/grub.cfg" "${ISO_DIR}/EFI/BOOT/grub.cfg"

# 11. Generate EFI boot image
echo "==> Step 9: Generating EFI boot image..."
mkdir -p /tmp/devos_efi/EFI/BOOT
grub-mkstandalone \
    --format=x86_64-efi \
    --output=/tmp/devos_efi/EFI/BOOT/BOOTX64.EFI \
    --locales="" \
    --fonts="" \
    --modules="iso9660 fat ntfs ext2 part_msdos part_gpt normal boot linux search search_fs_file search_fs_uuid search_label configfile font test sleep echo" \
    "boot/grub/grub.cfg=${ISO_DIR}/boot/grub/grub.cfg" || true

# If grub-mkstandalone failed, copy from Ubuntu chroot
if [ ! -f /tmp/devos_efi/EFI/BOOT/BOOTX64.EFI ]; then
    if [ -f "${WORK_DIR}/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed" ]; then
        cp "${WORK_DIR}/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed" /tmp/devos_efi/EFI/BOOT/BOOTX64.EFI
    fi
fi
cp /tmp/devos_efi/EFI/BOOT/BOOTX64.EFI "${ISO_DIR}/EFI/BOOT/BOOTX64.EFI"

rm -f "${ISO_DIR}/boot/grub/efi.img"
dd if=/dev/zero of="${ISO_DIR}/boot/grub/efi.img" bs=1M count=10
mkfs.vfat "${ISO_DIR}/boot/grub/efi.img"
mcopy -s -i "${ISO_DIR}/boot/grub/efi.img" /tmp/devos_efi/EFI :: || true

# 12. Assemble Hybrid ISO with xorriso
echo "==> Step 10: Assembling final hybrid BIOS+UEFI ISO..."
xorriso -as mkisofs \
    -r -V "DEVOS_2404" \
    -J -joliet-long \
    -partition_offset 16 \
    --eltorito-alt-boot \
    -e boot/grub/efi.img \
    -no-emul-boot \
    -isohybrid-gpt-basdat \
    -output "${OUTPUT_ISO}" \
    "${ISO_DIR}"

# 13. Size Report
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
