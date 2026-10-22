#!/bin/bash
# Recompress and master an already prepared rootfs without reinstalling packages.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORK_DIR="${DEVOS_WORK_DIR:-${ROOT_DIR}/build_work/resolute}"
CHROOT_DIR="${WORK_DIR}/chroot"
ISODIR="${WORK_DIR}/iso"
OUTPUT_ISO="${ROOT_DIR}/out/${DEVOS_ISO_NAME:-devos-26.04-amd64.iso}"
[ "$(id -u)" = 0 ] || { echo "Run inside the build container or as root." >&2; exit 1; }
[ -f "${CHROOT_DIR}/usr/local/share/devos/components/updater/updater.py" ] || { echo "Prepared DevOS components missing." >&2; exit 1; }
[ -f "${ISODIR}/casper/vmlinuz" ] && [ -f "${ISODIR}/casper/initrd" ] || { echo "Prepared kernel/initrd missing." >&2; exit 1; }
grep -qE '^VERSION_ID="?26\.04"?$' "${CHROOT_DIR}/etc/os-release" || { echo "Prepared rootfs is not 26.04." >&2; exit 1; }
for directory in dev proc sys run; do
    if mountpoint -q "${CHROOT_DIR}/${directory}"; then
        echo "ERROR: ${directory} is mounted. Finish/unmount the chroot before finalizing." >&2
        exit 1
    fi
done
for directory in dev proc sys; do
    [ -z "$(find "${CHROOT_DIR}/${directory}" -mindepth 1 -print -quit)" ] || {
        echo "ERROR: ${directory} is not empty. Inspect the prepared filesystem." >&2; exit 1;
    }
done
find "${CHROOT_DIR}/run" "${CHROOT_DIR}/tmp" "${CHROOT_DIR}/var/tmp" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
mkdir -p "${ROOT_DIR}/out" "${ISODIR}/casper"
chroot "${CHROOT_DIR}" dpkg-query -W --showformat='${Package} ${Version}\n' > "${ISODIR}/casper/filesystem.manifest"
du -sx --block-size=1 "${CHROOT_DIR}" | cut -f1 > "${ISODIR}/casper/filesystem.size"
rm -f "${ISODIR}/casper/filesystem.squashfs"
mksquashfs "${CHROOT_DIR}" "${ISODIR}/casper/filesystem.squashfs" \
    -comp zstd -Xcompression-level "${DEVOS_ZSTD_LEVEL:-15}" -b 1048576 \
    -processors "$(nproc)" -noappend -one-file-system
source "${SCRIPT_DIR}/lib-boot-iso.sh"
devos_prepare_boot_tree "${ISODIR}" "${CHROOT_DIR}" "$(mktemp -d)"
devos_master_iso "${ISODIR}" "${OUTPUT_ISO}"
bash "${ROOT_DIR}/tests/boot/verify-iso-bootability.sh" "${OUTPUT_ISO}"
[ "$(stat -c%s "${OUTPUT_ISO}")" -le 4294967296 ] || { echo "ISO exceeds the 4 GiB budget." >&2; exit 1; }
(cd "${ROOT_DIR}/out" && sha256sum "$(basename "${OUTPUT_ISO}")" > "$(basename "${OUTPUT_ISO}").sha256")
echo "Verified ISO: ${OUTPUT_ISO}"
