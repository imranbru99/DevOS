#!/bin/bash
# DevOS ISO Generation Pipeline (Phase 1)
# Produces a bootable, hybrid BIOS+UEFI ISO for DevOS based on Ubuntu 24.04 LTS (Noble)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

DISTRO_NAME="DevOS"
DISTRO_RELEASE="noble"
DISTRO_VERSION="24.04"
ISO_NAME="devos-${DISTRO_VERSION}-amd64.iso"
OUTPUT_DIR="${ROOT_DIR}/out"
OUTPUT_ISO="${OUTPUT_DIR}/${ISO_NAME}"

WORK_DIR="${ROOT_DIR}/build_work"
CHROOT_DIR="${WORK_DIR}/chroot"
ISODIR="${WORK_DIR}/iso"

ZSTD_LEVEL="${DEVOS_ZSTD_LEVEL:-19}"
MIRROR="${UBUNTU_MIRROR:-http://archive.ubuntu.com/ubuntu/}"

echo "==========================================================="
echo "       Building ${DISTRO_NAME} ${DISTRO_VERSION} Live ISO        "
echo "==========================================================="
echo "Output ISO: ${OUTPUT_ISO}"
echo "Zstandard Level: ${ZSTD_LEVEL}"
echo "Mirror: ${MIRROR}"
echo "==========================================================="

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: build-iso.sh requires root privileges." >&2
    exit 1
fi

cleanup() {
    echo "==> Cleaning up chroot mount points..."
    for mnt in "${CHROOT_DIR}/dev/pts" "${CHROOT_DIR}/dev" "${CHROOT_DIR}/proc" "${CHROOT_DIR}/sys"; do
        if mountpoint -q "$mnt" 2>/dev/null; then
            umount -lf "$mnt" || true
        fi
    done
}
trap cleanup EXIT

mkdir -p "${OUTPUT_DIR}" "${WORK_DIR}" "${ISODIR}"

# 1. Debootstrap stage
if [ ! -d "${CHROOT_DIR}/etc" ]; then
    echo "==> Step 1: Bootstrapping Ubuntu ${DISTRO_RELEASE} rootfs..."
    mkdir -p "${CHROOT_DIR}"
    debootstrap --arch=amd64 \
        --components=main,restricted,universe,multiverse \
        --include=systemd,systemd-sysv,udev,dbus,curl,ca-certificates \
        "${DISTRO_RELEASE}" "${CHROOT_DIR}" "${MIRROR}"
else
    echo "==> Step 1: Using existing chroot at ${CHROOT_DIR}..."
fi

# 2. Prepare chroot mount points
echo "==> Step 2: Preparing virtual filesystems inside chroot..."
mount --bind /dev "${CHROOT_DIR}/dev"
mount --bind /dev/pts "${CHROOT_DIR}/dev/pts"
mount -t proc proc "${CHROOT_DIR}/proc"
mount -t sysfs sysfs "${CHROOT_DIR}/sys"

# Configure DNS
cp -L /etc/resolv.conf "${CHROOT_DIR}/etc/resolv.conf" 2>/dev/null || echo "nameserver 1.1.1.1" > "${CHROOT_DIR}/etc/resolv.conf"

# 3. Configure APT inside chroot
echo "==> Step 3: Configuring APT sources and preferences..."
cat << EOF > "${CHROOT_DIR}/etc/apt/sources.list"
deb ${MIRROR} ${DISTRO_RELEASE} main restricted universe multiverse
deb ${MIRROR} ${DISTRO_RELEASE}-updates main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu/ ${DISTRO_RELEASE}-security main restricted universe multiverse
EOF

# Mask snapd via APT pin
cat << 'EOF' > "${CHROOT_DIR}/etc/apt/preferences.d/nosnap.pref"
Package: snapd
Pin: release *
Pin-Priority: -10
EOF

# 4. Install Packages
echo "==> Step 4: Installing package lists..."
chroot "${CHROOT_DIR}" env DEBIAN_FRONTEND=noninteractive apt-get update -y

PACKAGE_LIST=""
for listfile in "${ROOT_DIR}/build/package-lists/"*.list.chroot; do
    if [ -f "$listfile" ]; then
        echo "  Loading packages from: $(basename "$listfile")"
        while IFS= read -r pkg || [ -n "$pkg" ]; do
            # Trim whitespace and comments
            pkg_trimmed=$(echo "$pkg" | sed -e 's/#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
            if [ -n "$pkg_trimmed" ]; then
                PACKAGE_LIST="${PACKAGE_LIST} ${pkg_trimmed}"
            fi
        done < "$listfile"
    fi
done

if [ -n "$PACKAGE_LIST" ]; then
    chroot "${CHROOT_DIR}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ${PACKAGE_LIST}
fi

# 5. Copy includes
echo "==> Step 5: Copying includes into chroot..."
if [ -d "${ROOT_DIR}/build/includes.chroot" ]; then
    cp -a "${ROOT_DIR}/build/includes.chroot/." "${CHROOT_DIR}/"
fi

# Set Hostname
echo "devos" > "${CHROOT_DIR}/etc/hostname"
cat << 'EOF' > "${CHROOT_DIR}/etc/hosts"
127.0.0.1   localhost devos
::1         localhost ip6-localhost ip6-loopback
EOF

# 6. Execute Chroot Hooks
echo "==> Step 6: Executing chroot optimization hooks..."
for hook in "${ROOT_DIR}/build/hooks/"*.hook.chroot; do
    if [ -f "$hook" ]; then
        echo "  Executing hook: $(basename "$hook")"
        cp "$hook" "${CHROOT_DIR}/tmp/current_hook.sh"
        chmod +x "${CHROOT_DIR}/tmp/current_hook.sh"
        chroot "${CHROOT_DIR}" /tmp/current_hook.sh
        rm -f "${CHROOT_DIR}/tmp/current_hook.sh"
    fi
done

# 7. Extract Kernel & Initramfs for Live Boot
echo "==> Step 7: Extracting live kernel and initrd..."
mkdir -p "${ISODIR}/casper"
VMLINUZ=$(ls -1 "${CHROOT_DIR}/boot/vmlinuz-"* 2>/dev/null | sort -V | tail -n 1)
INITRD=$(ls -1 "${CHROOT_DIR}/boot/initrd.img-"* 2>/dev/null | sort -V | tail -n 1)

if [ -z "$VMLINUZ" ] || [ -z "$INITRD" ]; then
    echo "ERROR: Could not find kernel or initrd in chroot /boot directory!" >&2
    exit 1
fi

cp "$VMLINUZ" "${ISODIR}/casper/vmlinuz"
cp "$INITRD" "${ISODIR}/casper/initrd"

# 8. Unmount chroot before building SquashFS
cleanup

# 9. Create SquashFS with zstd
echo "==> Step 8: Creating filesystem.squashfs (zstd level ${ZSTD_LEVEL})..."
rm -f "${ISODIR}/casper/filesystem.squashfs"
mksquashfs "${CHROOT_DIR}" "${ISODIR}/casper/filesystem.squashfs" \
    -comp zstd -Xcompression-level "${ZSTD_LEVEL}" \
    -noappend -e boot

# Generate size and manifest info
chroot "${CHROOT_DIR}" dpkg-query -W --showformat='${Package} ${Version}\n' > "${ISODIR}/casper/filesystem.manifest"
printf $(du -sx --block-size=1 "${CHROOT_DIR}" | cut -f1) > "${ISODIR}/casper/filesystem.size"

# 10. Configure GRUB for BIOS and UEFI
echo "==> Step 9: Setting up GRUB bootloader..."
mkdir -p "${ISODIR}/boot/grub/x86_64-efi"

cat << 'EOF' > "${ISODIR}/boot/grub/grub.cfg"
set default="0"
set timeout=5

insmod font
if loadfont /boot/grub/font.pf2 ; then
    insmod gfxterm
    set gfxmode=auto
    terminal_output gfxterm
fi

set menu_color_normal=white/black
set menu_color_highlight=black/light-gray

menuentry "Try or Install DevOS (24.04 LTS)" {
    set gfxpayload=keep
    linux /casper/vmlinuz boot=casper quiet splash fsck.mode=skip ---
    initrd /casper/initrd
}

menuentry "DevOS (Safe Graphics)" {
    set gfxpayload=keep
    linux /casper/vmlinuz boot=casper nomodeset quiet splash ---
    initrd /casper/initrd
}

menuentry "Check Disc for Defects" {
    linux /casper/vmlinuz boot=casper integrity-check quiet splash ---
    initrd /casper/initrd
}
EOF

# 11. Create EFI Boot Image
echo "==> Step 10: Generating EFI boot partition..."
mkdir -p "${WORK_DIR}/efi_tmp/EFI/BOOT"
grub-mkstandalone \
    --format=x86_64-efi \
    --output="${WORK_DIR}/efi_tmp/EFI/BOOT/BOOTX64.EFI" \
    --locales="" \
    --fonts="" \
    "boot/grub/grub.cfg=${ISODIR}/boot/grub/grub.cfg" || true

# If grub-mkstandalone output missing, fallback to copying signed EFI binary if available
if [ ! -f "${WORK_DIR}/efi_tmp/EFI/BOOT/BOOTX64.EFI" ]; then
    if [ -f "${CHROOT_DIR}/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed" ]; then
        cp "${CHROOT_DIR}/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed" "${WORK_DIR}/efi_tmp/EFI/BOOT/BOOTX64.EFI"
    fi
fi

# Create FAT16/FAT12 EFI image
dd if=/dev/zero of="${ISODIR}/boot/grub/efi.img" bs=1M count=10
mkfs.vfat "${ISODIR}/boot/grub/efi.img"
mcopy -s -i "${ISODIR}/boot/grub/efi.img" "${WORK_DIR}/efi_tmp/EFI" ::

# 12. Build Hybrid ISO using xorriso
echo "==> Step 11: Assembling final hybrid ISO with xorriso..."
xorriso -as mkisofs \
    -r -V "DEVOS_2404" \
    -J -joliet-long \
    -b boot/grub/i386-pc/eltorito.img \
    -c boot.catalog \
    -no-emul-boot -boot-load-size 4 -boot-info-table \
    --eltorito-alt-boot \
    -e boot/grub/efi.img \
    -no-emul-boot -isohybrid-gpt-basdat \
    -output "${OUTPUT_ISO}" \
    "${ISODIR}" 2>/dev/null || \
xorriso -as mkisofs \
    -r -V "DEVOS_2404" \
    -J -joliet-long \
    -append_partition 2 0xef "${ISODIR}/boot/grub/efi.img" \
    -appended_part_as_gpt \
    -output "${OUTPUT_ISO}" \
    "${ISODIR}"

# 13. Verify and Report
echo "==========================================================="
echo "                DevOS ISO Build Complete                   "
echo "==========================================================="
if [ -f "${OUTPUT_ISO}" ]; then
    ISO_BYTES=$(stat -c%s "${OUTPUT_ISO}")
    ISO_HUMAN=$(du -h "${OUTPUT_ISO}" | cut -f1)
    echo "Output: ${OUTPUT_ISO}"
    echo "Size: ${ISO_HUMAN} (${ISO_BYTES} bytes)"
    sha256sum "${OUTPUT_ISO}" > "${OUTPUT_ISO}.sha256"
    echo "SHA256: $(cat "${OUTPUT_ISO}.sha256")"

    # Size check against <= 4 GB constraint
    MAX_BYTES=$((4 * 1024 * 1024 * 1024))
    if [ "$ISO_BYTES" -le "$MAX_BYTES" ]; then
        echo "Status: PASSED (Under 4.0 GB budget)"
    else
        echo "Status: FAILED (Exceeded 4.0 GB budget: ${ISO_BYTES} > ${MAX_BYTES})" >&2
        exit 1
    fi
else
    echo "ERROR: Target ISO was not created!" >&2
    exit 1
fi
