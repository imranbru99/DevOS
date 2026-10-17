#!/bin/bash
set -euo pipefail

DEVOS_OUT="${DEVOS_OUT:-/workspace/out}"
STAGE_DIR="${DEVOS_OUT}/iso_stage"
OUTPUT_ISO="${DEVOS_OUT}/devos-24.04-amd64.iso"
TMP_DIR="${DEVOS_OUT}/tmp_build"

echo "=========================================================="
echo "          DevOS Fast ISO Remaster & Rebuild               "
echo "=========================================================="

mkdir -p "${TMP_DIR}"
export TMPDIR="${TMP_DIR}"

if [ ! -f "${STAGE_DIR}/casper/vmlinuz" ]; then
    echo "ERROR: ${STAGE_DIR}/casper/vmlinuz not found!"
    exit 1
fi

chmod -R u+w "${STAGE_DIR}"

# 1-5. Prepare the boot tree and master the ISO with the shared engine.
# This script has no chroot, so the library will use host GRUB tools and
# re-use any signed UEFI binaries already present in the stage.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib-boot-iso.sh"

echo "==> Preparing real-hardware hybrid boot tree (BIOS+UEFI+Secure Boot)..."
devos_prepare_boot_tree "${STAGE_DIR}" "" "${TMP_DIR}"

echo "==> Mastering new hybrid bootable ISO with xorriso..."
rm -f "${OUTPUT_ISO}"
devos_master_iso "${STAGE_DIR}" "${OUTPUT_ISO}"

# 6. Cleanup temp files
rm -rf "${TMP_DIR}" "${STAGE_DIR}"

# The verifier uses mktemp; do not let it inherit the build's TMPDIR which was
# deleted above.
unset TMPDIR
echo "==> Running hardware-boot verification gate..."
"${SCRIPT_DIR}/../tests/boot/verify-iso-bootability.sh" "${OUTPUT_ISO}" || exit 1

echo "==> Generating SHA256 checksum..."
sha256sum "${OUTPUT_ISO}" > "${OUTPUT_ISO}.sha256"

ISO_SIZE=$(du -h "${OUTPUT_ISO}" | cut -f1)
ISO_BYTES=$(stat -c%s "${OUTPUT_ISO}")

echo "=========================================================="
echo "          DevOS ISO Rebuild Completed Successfully        "
echo "=========================================================="
echo "Output: ${OUTPUT_ISO}"
echo "Size: ${ISO_SIZE} (${ISO_BYTES} bytes)"
echo "SHA256: $(cat "${OUTPUT_ISO}.sha256")"
echo "=========================================================="
