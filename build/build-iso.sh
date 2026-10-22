#!/bin/bash
# DevOS ISO Generation Pipeline (Phase 1)
# Produces a bootable, hybrid BIOS+UEFI ISO for DevOS based on Ubuntu 26.04 LTS (Resolute)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

DISTRO_NAME="DevOS"
DISTRO_RELEASE="resolute"
DISTRO_VERSION="26.04"
ISO_NAME="${DEVOS_ISO_NAME:-devos-${DISTRO_VERSION}-amd64.iso}"
OUTPUT_DIR="${ROOT_DIR}/out"
OUTPUT_ISO="${OUTPUT_DIR}/${ISO_NAME}"

WORK_DIR="${DEVOS_WORK_DIR:-${ROOT_DIR}/build_work/${DISTRO_RELEASE}}"
CHROOT_DIR="${WORK_DIR}/chroot"
ISODIR="${WORK_DIR}/iso"

ZSTD_LEVEL="${DEVOS_ZSTD_LEVEL:-15}"
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
            umount --recursive --lazy "$mnt" || true
        fi
    done
}
trap cleanup EXIT

mkdir -p "${OUTPUT_DIR}" "${WORK_DIR}" "${ISODIR}"

# 1. Debootstrap stage
if [ ! -d "${CHROOT_DIR}/etc" ]; then
    echo "==> Step 1: Bootstrapping Ubuntu ${DISTRO_RELEASE} rootfs..."
    mkdir -p "${CHROOT_DIR}"
    TARBALL="ubuntu-base-26.04.1-base-amd64.tar.gz"
    BASE_URL="https://cdimage.ubuntu.com/ubuntu-base/releases/${DISTRO_VERSION}/release"
    curl -fSL --retry 3 "${BASE_URL}/SHA256SUMS" -o "/tmp/devos-base-SHA256SUMS"
    BASE_SUM="$(awk -v name="${TARBALL}" '$2 == "*" name || $2 == name {print $1}' /tmp/devos-base-SHA256SUMS)"
    [ "${#BASE_SUM}" -eq 64 ] || { echo "ERROR: Base image checksum missing" >&2; exit 1; }
    if ! echo "${BASE_SUM}  /tmp/${TARBALL}" | sha256sum -c - >/dev/null 2>&1; then
        echo "  Fetching Ubuntu base rootfs tarball (${TARBALL})..."
        curl -fSL --retry 3 "${BASE_URL}/${TARBALL}" -o "/tmp/${TARBALL}.partial"
        echo "${BASE_SUM}  /tmp/${TARBALL}.partial" | sha256sum -c -
        mv "/tmp/${TARBALL}.partial" "/tmp/${TARBALL}"
    fi
    if [ -f "/tmp/${TARBALL}" ]; then
        echo "  Extracting base rootfs into chroot..."
        tar -xzf "/tmp/${TARBALL}" -C "${CHROOT_DIR}"
    else
        echo "  Running debootstrap..."
        debootstrap --arch=amd64 \
            --components=main,restricted,universe,multiverse \
            --include=systemd,systemd-sysv,udev,dbus,curl,ca-certificates \
            "${DISTRO_RELEASE}" "${CHROOT_DIR}" "${MIRROR}"
    fi
else
    echo "==> Step 1: Using existing chroot at ${CHROOT_DIR}..."
    BASE_ID="${CHROOT_DIR}/usr/lib/os-release.ubuntu"
    [ -f "${BASE_ID}" ] || BASE_ID="${CHROOT_DIR}/etc/os-release"
    EXISTING_VERSION=$(. "${BASE_ID}"; printf '%s' "${VERSION_ID:-unknown}")
    if [ "${EXISTING_VERSION}" != "${DISTRO_VERSION}" ]; then
        echo "ERROR: Cached rootfs is ${EXISTING_VERSION}, expected ${DISTRO_VERSION}. Use a separate DEVOS_WORK_DIR." >&2
        exit 1
    fi
fi

# 2. Prepare chroot mount points
echo "==> Step 2: Preparing virtual filesystems inside chroot..."
# Rootless containers expose /dev/null and friends as child mounts. A plain
# bind loses those mounts and leaves inaccessible placeholder files in chroot.
mount --rbind /dev "${CHROOT_DIR}/dev"
mount --make-rslave "${CHROOT_DIR}/dev"
mount -t proc proc "${CHROOT_DIR}/proc"
mount --rbind /sys "${CHROOT_DIR}/sys"
mount --make-rslave "${CHROOT_DIR}/sys"
mount -o remount,bind,ro "${CHROOT_DIR}/sys"

# Configure DNS
cp -L /etc/resolv.conf "${CHROOT_DIR}/etc/resolv.conf" 2>/dev/null || echo "nameserver 1.1.1.1" > "${CHROOT_DIR}/etc/resolv.conf"

# 3. Configure APT inside chroot
echo "==> Step 3: Configuring APT sources and preferences..."
rm -rf "${CHROOT_DIR}/etc/apt/sources.list.d/"* 2>/dev/null || true
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

# Waydroid (Android apps) is not in Ubuntu's archive. Use the project's own
# signed repository. Without it .apk files can only report "not installed".
# The Ubuntu base tarball has no certificate bundle. Bootstrap trust from
# Ubuntu's signed archive before enabling third-party HTTPS repositories.
rm -f "${CHROOT_DIR}/etc/apt/sources.list.d/waydroid.list"
chroot "${CHROOT_DIR}" apt-get update
chroot "${CHROOT_DIR}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates
mkdir -p "${CHROOT_DIR}/usr/share/keyrings"
if curl -fsSL --retry 3 https://repo.waydro.id/waydroid.gpg \
        -o "${CHROOT_DIR}/usr/share/keyrings/waydroid.gpg"; then
    echo "deb [signed-by=/usr/share/keyrings/waydroid.gpg] https://repo.waydro.id/ ${DISTRO_RELEASE} main" \
        > "${CHROOT_DIR}/etc/apt/sources.list.d/waydroid.list"
else
    echo "  WARNING: Waydroid repository unreachable; Android support skipped."
fi

# Most Windows installers (AnyDesk, many setup.exe files) are 32-bit.
# wine64 alone cannot start them; wine32 comes from the i386 architecture.
chroot "${CHROOT_DIR}" dpkg --add-architecture i386

# 4. Install Packages
echo "==> Step 4: Installing package lists..."
chroot "${CHROOT_DIR}" env DEBIAN_FRONTEND=noninteractive apt-get update -y

for listfile in $(ls -1 "${ROOT_DIR}/build/package-lists/"*.list.chroot 2>/dev/null | sort); do
    if [ -f "$listfile" ]; then
        echo "  Processing package list: $(basename "$listfile")"
        PKG_BATCH=""
        while IFS= read -r pkg || [ -n "$pkg" ]; do
            pkg_trimmed=$(echo "$pkg" | sed -e 's/#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
            if [ -n "$pkg_trimmed" ]; then
                PKG_BATCH="${PKG_BATCH} ${pkg_trimmed}"
            fi
        done < "$listfile"
        if [ -n "$PKG_BATCH" ]; then
            if ! chroot "${CHROOT_DIR}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ${PKG_BATCH}; then
                echo "  Batch install failed; installing packages individually..."
                for pkg_one in ${PKG_BATCH}; do
                    chroot "${CHROOT_DIR}" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "${pkg_one}" \
                        || echo "  WARNING: skipped ${pkg_one}"
                done
            fi
        fi
    fi
done

# Copy a source tree into the image as root with sane modes. A checkout on a
# Windows drive (Docker Desktop, WSL /mnt/c) reports every file as 0777, and
# "cp -a" carried that into /etc. sudo then ignores a world-writable
# /etc/sudoers.d, the live user cannot start Calamares as root, and the
# installer never opens ("sudo: /etc/sudoers.d is world writable").
install_tree() {
    local src="$1" dest="$2"
    mkdir -p "$dest"
    rsync -rltp --chown=root:root --chmod=D755,F644 \
        --exclude='__pycache__/' --exclude='*.pyc' \
        "${src}/" "${dest}/"
    # Anything starting with "#!" is a script and stays executable.
    (cd "$src" && find . -type f -print0) | while IFS= read -r -d '' f; do
        if [ "$(head -c 2 "${src}/${f}" 2>/dev/null)" = "#!" ]; then
            chmod 755 "${dest}/${f}"
        fi
    done
}

# 5. Copy includes
echo "==> Step 5: Copying includes into chroot..."
if [ -d "${ROOT_DIR}/build/includes.chroot" ]; then
    install_tree "${ROOT_DIR}/build/includes.chroot" "${CHROOT_DIR}"
fi
# Plasma shows desktop shortcuts that are not executable as untrusted (⚠).
chmod 755 "${CHROOT_DIR}"/etc/skel/Desktop/*.desktop 2>/dev/null || true
chmod 750 "${CHROOT_DIR}/etc/sudoers.d"
chmod 440 "${CHROOT_DIR}"/etc/sudoers.d/* 2>/dev/null || true
chmod 600 "${CHROOT_DIR}"/etc/NetworkManager/system-connections/* 2>/dev/null || true
chmod 600 "${CHROOT_DIR}"/etc/netplan/*.yaml 2>/dev/null || true

# Chrome is a real system package. Its profile stays in the user home folder.
if [ -f "${CHROOT_DIR}/usr/local/sbin/devos-install-chrome" ]; then
    echo "==> Installing Google Chrome..."
    chroot "${CHROOT_DIR}" /bin/bash /usr/local/sbin/devos-install-chrome || true
fi

if [ -f "${CHROOT_DIR}/usr/local/sbin/devos-install-code" ]; then
    echo "==> Installing Visual Studio Code..."
    chroot "${CHROOT_DIR}" /bin/bash /usr/local/sbin/devos-install-code || true
fi

if [ -f "${CHROOT_DIR}/usr/local/sbin/devos-install-llm" ]; then
    echo "==> Installing the local chat model..."
    chroot "${CHROOT_DIR}" /bin/bash /usr/local/sbin/devos-install-llm
fi

# Install DevOS components into chroot
echo "==> Installing DevOS components and unified CLI..."
if [ -d "${ROOT_DIR}/components" ]; then
    install_tree "${ROOT_DIR}/components" "${CHROOT_DIR}/usr/local/share/devos/components"
fi

mkdir -p "${CHROOT_DIR}/usr/local/bin"
cat << 'EOF' > "${CHROOT_DIR}/usr/local/bin/devos"
#!/usr/bin/env bash
exec /usr/bin/python3 /usr/local/share/devos/components/devos_cli.py "$@"
EOF
chmod +x "${CHROOT_DIR}/usr/local/bin/devos"

# Desktop icons live in the skeleton. The live account is created at boot.
# A root-owned /home/devos in the image makes login refuse that folder.
mkdir -p "${CHROOT_DIR}/etc/skel/Desktop"
chmod +x "${CHROOT_DIR}/usr/share/applications/devos-dashboard.desktop" 2>/dev/null || true
chmod +x "${CHROOT_DIR}/etc/xdg/autostart/devos-dashboard.desktop" 2>/dev/null || true
chmod +x "${CHROOT_DIR}/etc/skel/Desktop/devos-dashboard.desktop" 2>/dev/null || true

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
for virtual in dev proc sys; do
    if mountpoint -q "${CHROOT_DIR}/${virtual}"; then
        echo "ERROR: ${virtual} is still mounted; refusing to package virtual filesystems." >&2
        exit 1
    fi
done

# Ensure critical mount points and temporary directories exist with correct permissions
mkdir -p "${CHROOT_DIR}/dev" "${CHROOT_DIR}/proc" "${CHROOT_DIR}/sys" "${CHROOT_DIR}/tmp" "${CHROOT_DIR}/run" "${CHROOT_DIR}/mnt" "${CHROOT_DIR}/media" "${CHROOT_DIR}/var/crash"
rm -rf "${CHROOT_DIR}"/tmp/* "${CHROOT_DIR}"/var/tmp/* 2>/dev/null || true
chmod 1777 "${CHROOT_DIR}/tmp" "${CHROOT_DIR}/var/tmp" 2>/dev/null || true

# Drop a root-owned live home. Casper creates /home/devos at boot and copies
# the skeleton into it. If this folder is already here, login skips it and
# the installer window never opens.
rm -rf "${CHROOT_DIR}/home/devos"

# Drop the builder resolver. A regular file here (127.0.0.11) makes Chrome
# report DNS_PROBE_FINISHED_BAD_CONFIG after Ethernet is already connected.
rm -f "${CHROOT_DIR}/etc/resolv.conf"
ln -s ../run/systemd/resolve/stub-resolv.conf "${CHROOT_DIR}/etc/resolv.conf"

# A world-writable system path makes sudo, polkit and sshd refuse their config.
# Clear leftovers (bytecode caches, backups made from 0777 copies by an older
# build of a reused chroot), then stop if anything is still writable by all.
find "${CHROOT_DIR}/usr/local" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "${CHROOT_DIR}/etc" "${CHROOT_DIR}/usr" -xdev -perm -o+w ! -type l ! -perm -1000 \
    -exec chmod o-w {} + 2>/dev/null || true
world_writable="$(find "${CHROOT_DIR}/etc" "${CHROOT_DIR}/usr" -xdev \
    -perm -o+w ! -type l ! -perm -1000 2>/dev/null | head -20)"
if [ -n "$world_writable" ]; then
    echo "ERROR: world-writable system paths in the image:" >&2
    echo "$world_writable" >&2
    exit 1
fi

# 9. Create SquashFS with zstd
# 1 MiB blocks give better sequential throughput during Calamares unpack
# while zstd level 15 keeps the image under 4 GB without level-19 CPU cost.
echo "==> Step 8: Creating filesystem.squashfs (zstd level ${ZSTD_LEVEL}, 1M blocks)..."
rm -f "${ISODIR}/casper/filesystem.squashfs"
mksquashfs "${CHROOT_DIR}" "${ISODIR}/casper/filesystem.squashfs" \
    -comp zstd -Xcompression-level "${ZSTD_LEVEL}" \
    -b 1048576 -processors "$(nproc)" -noappend -one-file-system

# Generate size and manifest info
chroot "${CHROOT_DIR}" dpkg-query -W --showformat='${Package} ${Version}\n' > "${ISODIR}/casper/filesystem.manifest"
printf $(du -sx --block-size=1 "${CHROOT_DIR}" | cut -f1) > "${ISODIR}/casper/filesystem.size"

# 10-12. Configure GRUB, build UEFI/BIOS boot files, and master the hybrid ISO.
# All of this is now handled by the shared lib-boot-iso.sh so every build path
# (native, Docker, remaster, fast-rebuild) produces the same real-hardware layout.
echo "==> Step 9: Preparing hybrid boot tree (BIOS+UEFI+Secure Boot)..."
source "${SCRIPT_DIR}/lib-boot-iso.sh"
BOOT_TMP="$(mktemp -d)"
devos_prepare_boot_tree "${ISODIR}" "${CHROOT_DIR}" "${BOOT_TMP}"

echo "==> Step 10: Mastering final hybrid ISO with xorriso..."
mkdir -p "${OUTPUT_DIR}"
devos_master_iso "${ISODIR}" "${OUTPUT_ISO}"

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

    # Hardware-boot gate: refuse to publish an ISO that would not start on a
    # real PC. The same gate is also a Makefile target for quick CI checks.
    if [ -x "${ROOT_DIR}/tests/boot/verify-iso-bootability.sh" ]; then
        echo "==> Running hardware-boot verification gate..."
        "${ROOT_DIR}/tests/boot/verify-iso-bootability.sh" "${OUTPUT_ISO}" || exit 1
    fi

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
