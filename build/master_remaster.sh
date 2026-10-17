#!/bin/bash
set -euo pipefail

DEVOS_OUT="${DEVOS_OUT:-/mnt/host/c/docker/DevOS/out}"
DEVOS_SRC="${DEVOS_SRC:-/mnt/host/c/docker/DevOS}"
STAGE_DIR="${DEVOS_OUT}/iso_stage"
OUTPUT_ISO="${DEVOS_OUT}/devos-24.04-amd64.iso"
TMP_DIR="${DEVOS_OUT}/tmp_build"
IMG="${DEVOS_IMG:-/mnt/host/c/docker/build_rootfs.img}"
MNT="${DEVOS_MNT:-/mnt/rootfs}"

echo "=========================================================="
echo "          DevOS Master Remaster & Full Builder 2027       "
echo "=========================================================="

mkdir -p "${TMP_DIR}" "${DEVOS_OUT}" "${DEVOS_SRC}/build/includes.chroot"
export TMPDIR="${TMP_DIR}"
# Earlier builds left the stage files read-only.
chmod -R u+w "${STAGE_DIR}" 2>/dev/null || true

# Detach /dev, /proc and /sys from the chroot. The rootfs itself stays mounted.
unmount_vfs() {
    echo "==> Unmounting chroot virtual filesystems..."
    for m in "${MNT}/dev/pts" "${MNT}/dev" "${MNT}/proc" "${MNT}/sys"; do
        if mountpoint -q "$m" 2>/dev/null; then
            umount -lf "$m" || true
        fi
    done
}

cleanup() {
    unmount_vfs
    if mountpoint -q "${MNT}" 2>/dev/null; then
        umount -lf "${MNT}" || true
    fi
}
trap cleanup EXIT

# DEVOS_RESUME=1 skips steps 1-4 and squashes the rootfs already prepared in
# ${IMG}. Use it when a run failed after the chroot work finished.
if [ "${DEVOS_RESUME:-0}" = "1" ]; then
    echo "==> Resuming from the prepared rootfs in ${IMG}"
    e2fsck -fp "${IMG}" || true
    mkdir -p "${MNT}"
    mount "${IMG}" "${MNT}"
    echo "==> Syncing updated includes.chroot and components into rootfs..."
    cp -r "${DEVOS_SRC}/build/includes.chroot/." "${MNT}/" || true
    mkdir -p "${MNT}/usr/local/share/devos/components"
    cp -r "${DEVOS_SRC}/components/." "${MNT}/usr/local/share/devos/components/" || true
    chmod 755 "${MNT}/usr/local/sbin/"* 2>/dev/null || true
    chmod 755 "${MNT}/usr/local/bin/"* 2>/dev/null || true
    chmod 755 "${MNT}/usr/share/xsessions/"*.desktop 2>/dev/null || true
    chmod 755 "${MNT}/usr/share/wayland-sessions/"*.desktop 2>/dev/null || true
    chmod 755 "${MNT}/etc/skel/Desktop/"*.desktop 2>/dev/null || true
    chmod 755 "${MNT}/etc/xdg/autostart/"*.desktop 2>/dev/null || true
    chmod 644 "${MNT}/usr/share/applications/"*.desktop 2>/dev/null || true
    # Purge Ubuntu installer autostart and packages
    mount --bind /dev "${MNT}/dev" 2>/dev/null || true
    mount --bind /dev/pts "${MNT}/dev/pts" 2>/dev/null || true
    mount -t proc proc "${MNT}/proc" 2>/dev/null || true
    mount -t sysfs sysfs "${MNT}/sys" 2>/dev/null || true
    chroot "${MNT}" env DEBIAN_FRONTEND=noninteractive apt-get purge -y ubuntu-desktop-bootstrap ubuntu-desktop-installer ubiquity ubiquity-frontend-gtk gnome-initial-setup subiquity subiquity-server curtin >/dev/null 2>&1 || true
    chroot "${MNT}" systemctl mask ubuntu-desktop-bootstrap.service subiquity.service 2>/dev/null || true
    unmount_vfs

    rm -f \
        "${MNT}/etc/xdg/autostart/ubuntu-desktop-bootstrap.desktop" \
        "${MNT}/etc/xdg/autostart/ubiquity.desktop" \
        "${MNT}/etc/xdg/autostart/org.gnome.InitialSetup.desktop" \
        "${MNT}/usr/share/applications/ubuntu-desktop-bootstrap.desktop" \
        "${MNT}/var/lib/snapd/desktop/applications/ubuntu-desktop-bootstrap.desktop" 2>/dev/null || true
    mkdir -p "${MNT}/etc/systemd/system/sddm.service.wants" "${MNT}/etc/systemd/system/multi-user.target.wants"
    ln -sfn /etc/systemd/system/devos-force-installer.service \
        "${MNT}/etc/systemd/system/sddm.service.wants/devos-force-installer.service"
    ln -sfn /etc/systemd/system/devos-force-installer.service \
        "${MNT}/etc/systemd/system/multi-user.target.wants/devos-force-installer.service"
    rm -rf "${MNT}/home/devos"
else

# 1. Create native ext4 working image
echo "==> Step 1: Allocating 14 GB virtual Linux ext4 disk image..."
rm -f "${IMG}"
dd if=/dev/zero of="${IMG}" bs=1M count=14000 status=none
mkfs.ext4 -F -O ^has_journal -b 4096 -m 0 "${IMG}" > /dev/null

mkdir -p "${MNT}"
mount "${IMG}" "${MNT}"

# 2. Extract current squashfs into clean ext4 rootfs
echo "==> Step 2: Unsquashing base rootfs onto ext4 workspace..."
SRC_SQUASHFS="${DEVOS_OUT}/filesystem.squashfs"
[ -f "${SRC_SQUASHFS}" ] || SRC_SQUASHFS="${STAGE_DIR}/casper/filesystem.squashfs"
if [ ! -f "${SRC_SQUASHFS}" ]; then
    echo "ERROR: no source filesystem.squashfs in ${DEVOS_OUT} or ${STAGE_DIR}/casper" >&2
    exit 1
fi
echo "  Source: ${SRC_SQUASHFS}"
unsquashfs -d "${MNT}" -f "${SRC_SQUASHFS}"

# 3. Bind virtual filesystems for chroot operations
echo "==> Step 3: Binding kernel virtual filesystems..."
mount --bind /dev "${MNT}/dev"
mount --bind /dev/pts "${MNT}/dev/pts"
mount -t proc proc "${MNT}/proc"
mount -t sysfs sysfs "${MNT}/sys"

echo "nameserver 1.1.1.1" > "${MNT}/etc/resolv.conf"
cat << 'EOF' > "${MNT}/etc/apt/sources.list"
deb http://archive.ubuntu.com/ubuntu/ noble main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu/ noble-updates main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu/ noble-security main restricted universe multiverse
EOF

# 4. Install Google Chrome, VLC, Codecs, X11 Fallbacks, and Window Decorations
echo "==> Step 4: Installing Chrome browser, VLC, audio/video codecs, and KWin window controls..."
chroot "${MNT}" env DEBIAN_FRONTEND=noninteractive apt-get update -y

# Older images were squashed without /boot. Calamares copies this tree onto
# the disk, so without a kernel here the installed system cannot boot.
if ! ls -1 "${MNT}/boot/vmlinuz-"* >/dev/null 2>&1; then
    echo "  /boot is empty; reinstalling the kernel and GRUB files..."
    mkdir -p "${MNT}/boot"
    KVER=$(ls -1 "${MNT}/usr/lib/modules" | sort -V | tail -n 1)
    chroot "${MNT}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --reinstall \
        "linux-image-${KVER}" "linux-modules-${KVER}" \
        || chroot "${MNT}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --reinstall linux-image-generic
    chroot "${MNT}" update-initramfs -c -k all || chroot "${MNT}" update-initramfs -u -k all
fi
if ! ls -1 "${MNT}/boot/vmlinuz-"* >/dev/null 2>&1; then
    echo "ERROR: no kernel in ${MNT}/boot; the installed disk would not boot." >&2
    exit 1
fi

# Install Google Chrome
if [ -f "/mnt/host/c/docker/deb_cache/google-chrome-stable_current_amd64.deb" ]; then
    echo "  Installing Google Chrome Web Browser..."
    cp "/mnt/host/c/docker/deb_cache/google-chrome-stable_current_amd64.deb" "${MNT}/tmp/chrome.deb"
    chroot "${MNT}" env DEBIAN_FRONTEND=noninteractive apt-get install -y /tmp/chrome.deb || \
    chroot "${MNT}" env DEBIAN_FRONTEND=noninteractive apt-get install -fy
    rm -f "${MNT}/tmp/chrome.deb"
fi

# Install VLC, Audio, Codecs, X11/KWin fallbacks, Falkon
chroot "${MNT}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    vlc \
    falkon \
    pipewire \
    pipewire-pulse \
    pipewire-alsa \
    wireplumber \
    pavucontrol-qt \
    plasma-nm \
    breeze \
    breeze-icon-theme \
    kde-style-breeze \
    kwin-x11 \
    xserver-xorg \
    xserver-xorg-video-all \
    x11-xserver-utils \
    ffmpeg \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav || true

# 5. Apply DevOS branding, user profile, and luxury UI configurations
echo "==> Step 5: Applying DevOS branding, user profiles, and window decorations..."
cp -r "${DEVOS_SRC}/build/includes.chroot/." "${MNT}/" || true

mkdir -p "${MNT}/usr/local/share/devos/components"
cp -r "${DEVOS_SRC}/components/." "${MNT}/usr/local/share/devos/components/" || true

# Live user devos setup
echo "devos" > "${MNT}/etc/hostname"
cat << 'EOF' > "${MNT}/etc/hosts"
127.0.0.1   localhost devos
::1         localhost ip6-localhost ip6-loopback
EOF

echo 'devos ALL=(ALL) NOPASSWD:ALL' > "${MNT}/etc/sudoers.d/devos"
chmod 0440 "${MNT}/etc/sudoers.d/devos"

if [ -f "${MNT}/usr/local/sbin/devos-apply-branding" ]; then
    chroot "${MNT}" /bin/bash /usr/local/sbin/devos-apply-branding || true
fi

if [ -f "${MNT}/usr/local/sbin/devos-install-chrome" ]; then
    chroot "${MNT}" /bin/bash /usr/local/sbin/devos-install-chrome || true
fi

# Execute chroot optimization & security hooks
echo "==> Executing chroot optimization hooks..."
for hook in "${DEVOS_SRC}/build/hooks/"*.hook.chroot; do
    if [ -f "$hook" ]; then
        echo "  Running hook: $(basename "$hook")"
        cp "$hook" "${MNT}/tmp/run_hook.sh"
        chmod +x "${MNT}/tmp/run_hook.sh"
        chroot "${MNT}" /tmp/run_hook.sh || true
        rm -f "${MNT}/tmp/run_hook.sh"
    fi
done

# Desktop icons stay in the skeleton. Do not leave a root-owned /home/devos.
mkdir -p "${MNT}/etc/skel/Desktop"
rm -rf "${MNT}/home/devos"
chmod 755 "${MNT}/etc/skel/Desktop/"*.desktop 2>/dev/null || true
chmod 755 "${MNT}/etc/xdg/autostart/"*.desktop 2>/dev/null || true
chmod 755 "${MNT}/usr/local/sbin/"* 2>/dev/null || true
chmod 755 "${MNT}/usr/local/bin/"* 2>/dev/null || true
chmod 755 "${MNT}/usr/share/xsessions/"*.desktop 2>/dev/null || true
chmod 755 "${MNT}/usr/share/wayland-sessions/"*.desktop 2>/dev/null || true

# Eradicate Ubuntu installer autostarts
rm -f \
    "${MNT}/etc/xdg/autostart/ubuntu-desktop-bootstrap.desktop" \
    "${MNT}/etc/xdg/autostart/ubiquity.desktop" \
    "${MNT}/etc/xdg/autostart/org.gnome.InitialSetup.desktop" \
    "${MNT}/usr/share/applications/ubuntu-desktop-bootstrap.desktop" \
    "${MNT}/var/lib/snapd/desktop/applications/ubuntu-desktop-bootstrap.desktop" 2>/dev/null || true

mkdir -p "${MNT}/etc/systemd/system/sddm.service.wants" "${MNT}/etc/systemd/system/multi-user.target.wants"
ln -sfn /etc/systemd/system/devos-force-installer.service \
    "${MNT}/etc/systemd/system/sddm.service.wants/devos-force-installer.service"
ln -sfn /etc/systemd/system/devos-force-installer.service \
    "${MNT}/etc/systemd/system/multi-user.target.wants/devos-force-installer.service"

# Extract manifest
echo "==> Generating package manifest..."
chroot "${MNT}" dpkg-query -W --showformat='${Package} ${Version}\n' > "${TMP_DIR}/filesystem.manifest" || true

# Clean caches
chroot "${MNT}" env DEBIAN_FRONTEND=noninteractive apt-get clean || true
rm -rf "${MNT}/var/lib/apt/lists/"* "${MNT}/tmp/"* "${MNT}/var/tmp/"* 2>/dev/null || true

# 6. Unmount virtual filesystems
echo "==> Step 6: Unmounting chroot before SquashFS generation..."
unmount_vfs

fi  # end of package install steps (skipped with DEVOS_RESUME=1)

# Extract kernel and initrd if present in boot
if ls -1 "${MNT}/boot/vmlinuz-"* >/dev/null 2>&1; then
    NEW_VMLINUZ=$(ls -1 "${MNT}/boot/vmlinuz-"* 2>/dev/null | sort -V | tail -n 1)
    NEW_INITRD=$(ls -1 "${MNT}/boot/initrd.img-"* 2>/dev/null | sort -V | tail -n 1)
    cp "$NEW_VMLINUZ" "${TMP_DIR}/vmlinuz"
    cp "$NEW_INITRD" "${TMP_DIR}/initrd"
fi

# Secure Boot files. Windows PCs ship with Secure Boot on and reject an
# unsigned BOOTX64.EFI, so the USB must start with Microsoft-signed shim.
for f in shimx64.efi.signed.latest shimx64.efi.signed; do
    [ -f "${MNT}/usr/lib/shim/$f" ] && { cp -L "${MNT}/usr/lib/shim/$f" "${TMP_DIR}/shimx64.efi"; break; }
done
for f in mmx64.efi.signed mmx64.efi; do
    [ -f "${MNT}/usr/lib/shim/$f" ] && { cp -L "${MNT}/usr/lib/shim/$f" "${TMP_DIR}/mmx64.efi"; break; }
done
if [ -f "${MNT}/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed" ]; then
    cp -L "${MNT}/usr/lib/grub/x86_64-efi-signed/grubx64.efi.signed" "${TMP_DIR}/grubx64.efi"
fi

# Never replace the live system with an empty or half-mounted tree.
if [ ! -x "${MNT}/usr/bin/bash" ] || ! ls -1 "${MNT}/boot/vmlinuz-"* >/dev/null 2>&1; then
    echo "ERROR: ${MNT} has no complete system (bash or kernel missing); not writing squashfs." >&2
    exit 1
fi

# 7. Create filesystem.squashfs
echo "==> Step 7: Creating new filesystem.squashfs with zstd compression..."
mkdir -p "${STAGE_DIR}/casper"
rm -f "${STAGE_DIR}/casper/filesystem.squashfs"

mksquashfs "${MNT}" "${STAGE_DIR}/casper/filesystem.squashfs" \
    -comp zstd -Xcompression-level 15 \
    -noappend -e "ubuntu-base-*"

du -sk "${MNT}" | awk '{print $1 * 1024}' > "${STAGE_DIR}/casper/filesystem.size"
if [ -f "${TMP_DIR}/filesystem.manifest" ]; then
    cp "${TMP_DIR}/filesystem.manifest" "${STAGE_DIR}/casper/filesystem.manifest"
fi

if [ -f "${TMP_DIR}/vmlinuz" ]; then
    cp "${TMP_DIR}/vmlinuz" "${STAGE_DIR}/casper/vmlinuz"
    cp "${TMP_DIR}/initrd" "${STAGE_DIR}/casper/initrd"
fi

# Unmount ext4 working disk. ${IMG} is kept so a later failure can resume
# with DEVOS_RESUME=1; delete it by hand once the ISO is tested.
umount "${MNT}"

# 8. Setup GRUB Bootloader with username=devos and universal search
echo "==> Step 8: Configuring GRUB bootloader..."
mkdir -p "${STAGE_DIR}/boot/grub" "${STAGE_DIR}/EFI/BOOT"

cat << 'EOF' > "${STAGE_DIR}/boot/grub/grub.cfg"
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

menuentry "Try or Install DevOS (24.04 LTS)" {
    set gfxpayload=keep
    search --no-floppy --set=root --file /casper/vmlinuz
    linux /casper/vmlinuz boot=casper username=devos hostname=devos quiet splash fsck.mode=skip ---
    initrd /casper/initrd
}

menuentry "DevOS (Safe Graphics)" {
    set gfxpayload=keep
    search --no-floppy --set=root --file /casper/vmlinuz
    linux /casper/vmlinuz boot=casper username=devos hostname=devos nomodeset quiet splash ---
    initrd /casper/initrd
}

menuentry "Check Disc for Defects" {
    search --no-floppy --set=root --file /casper/vmlinuz
    linux /casper/vmlinuz boot=casper integrity-check quiet splash ---
    initrd /casper/initrd
}
EOF

cp "${STAGE_DIR}/boot/grub/grub.cfg" "${STAGE_DIR}/EFI/BOOT/grub.cfg"

# 9. Build universal standalone BOOTX64.EFI with all FS modules
echo "==> Step 9: Generating standalone BOOTX64.EFI..."
cat << 'EOF' > "${TMP_DIR}/early_grub.cfg"
search --no-floppy --set=root --file /casper/vmlinuz
set prefix=($root)/boot/grub
configfile $prefix/grub.cfg
EOF

grub-mkstandalone \
    --format=x86_64-efi \
    --output="${TMP_DIR}/BOOTX64.EFI" \
    --locales="" \
    --fonts="" \
    --modules="iso9660 fat ntfs ext2 part_msdos part_gpt normal boot linux search search_fs_file search_fs_uuid search_label configfile font test sleep echo" \
    "boot/grub/grub.cfg=${TMP_DIR}/early_grub.cfg"

# The signed Ubuntu GRUB finds the disc by /.disk/info, then reads
# /boot/grub/grub.cfg. Prefer shim -> signed GRUB; the standalone image is
# only a fallback for machines with Secure Boot turned off.
mkdir -p "${STAGE_DIR}/.disk"
echo "DevOS 24.04 LTS \"Noble\" - amd64" > "${STAGE_DIR}/.disk/info"

mkdir -p "${TMP_DIR}/efi_structure/EFI/BOOT"
if [ -f "${TMP_DIR}/shimx64.efi" ] && [ -f "${TMP_DIR}/grubx64.efi" ]; then
    echo "  Using signed shim + GRUB (Secure Boot ready)"
    for d in "${STAGE_DIR}/EFI/BOOT" "${TMP_DIR}/efi_structure/EFI/BOOT"; do
        cp "${TMP_DIR}/shimx64.efi" "$d/BOOTX64.EFI"
        cp "${TMP_DIR}/grubx64.efi" "$d/grubx64.efi"
        [ -f "${TMP_DIR}/mmx64.efi" ] && cp "${TMP_DIR}/mmx64.efi" "$d/mmx64.efi"
    done
else
    echo "  WARNING: signed shim/GRUB missing; USB will need Secure Boot disabled" >&2
    cp "${TMP_DIR}/BOOTX64.EFI" "${STAGE_DIR}/EFI/BOOT/BOOTX64.EFI"
    cp "${TMP_DIR}/BOOTX64.EFI" "${TMP_DIR}/efi_structure/EFI/BOOT/BOOTX64.EFI"
fi

# 10. Generate efi.img FAT partition
echo "==> Step 10: Generating efi.img FAT partition..."
cp "${STAGE_DIR}/boot/grub/grub.cfg" "${TMP_DIR}/efi_structure/EFI/BOOT/grub.cfg"

rm -f "${STAGE_DIR}/boot/grub/efi.img"
dd if=/dev/zero of="${STAGE_DIR}/boot/grub/efi.img" bs=1M count=10 status=none
mkfs.vfat "${STAGE_DIR}/boot/grub/efi.img" > /dev/null
mcopy -s -i "${STAGE_DIR}/boot/grub/efi.img" "${TMP_DIR}/efi_structure/EFI" ::

# Remove old boot.catalog if present
rm -f "${STAGE_DIR}/boot.catalog"

# 11. Master final hybrid bootable ISO with xorriso
echo "==> Step 11: Assembling final hybrid BIOS+UEFI ISO..."
LOCAL_ISO="/tmp/devos-24.04-amd64.iso"
rm -f "${LOCAL_ISO}" "${OUTPUT_ISO}"
xorriso -as mkisofs \
    -r -V "DEVOS_2404" \
    -J -joliet-long \
    -partition_offset 16 \
    --eltorito-alt-boot \
    -e boot/grub/efi.img \
    -no-emul-boot \
    -isohybrid-gpt-basdat \
    -output "${LOCAL_ISO}" \
    "${STAGE_DIR}"

echo "==> Moving generated ISO to destination ${OUTPUT_ISO}..."
rm -f "${OUTPUT_ISO}"
cat "${LOCAL_ISO}" > "${OUTPUT_ISO}"
sync
rm -f "${LOCAL_ISO}"

# 12. Cleanup temporary directories
rm -rf "${TMP_DIR}"

# 13. Checksum and size reporting
echo "==> Generating SHA256 checksum..."
sha256sum "${OUTPUT_ISO}" > "${OUTPUT_ISO}.sha256"

ISO_SIZE=$(du -h "${OUTPUT_ISO}" | cut -f1)
ISO_BYTES=$(stat -c%s "${OUTPUT_ISO}")

echo "=========================================================="
echo "          DevOS Master Rebuild Completed Successfully     "
echo "=========================================================="
echo "Target: ${OUTPUT_ISO}"
echo "Size: ${ISO_SIZE} (${ISO_BYTES} bytes)"
echo "SHA256: $(cat "${OUTPUT_ISO}.sha256")"
echo "=========================================================="
