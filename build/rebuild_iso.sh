#!/bin/bash
set -euo pipefail

DEVOS_OUT="/mnt/host/c/docker/DevOS/out"
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

# 1. Update grub.cfg in ISO
echo "==> Writing updated grub.cfg..."
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

# 2. Create embedded early config for standalone grub
cat << 'EOF' > "${TMP_DIR}/early_grub.cfg"
search --no-floppy --set=root --file /casper/vmlinuz
set prefix=($root)/boot/grub
configfile $prefix/grub.cfg
EOF

# 3. Generate universal standalone BOOTX64.EFI with all FS drivers
echo "==> Building standalone BOOTX64.EFI with full filesystem support..."
grub-mkstandalone \
    --format=x86_64-efi \
    --output="${TMP_DIR}/BOOTX64.EFI" \
    --locales="" \
    --fonts="" \
    --modules="iso9660 fat ntfs ext2 part_msdos part_gpt normal boot linux search search_fs_file search_fs_uuid search_label configfile font test sleep echo" \
    "boot/grub/grub.cfg=${TMP_DIR}/early_grub.cfg" || true

# If signed shim and GRUB exist, prioritize them for Secure Boot compatibility
mkdir -p "${TMP_DIR}/efi_structure/EFI/BOOT"
if [ -f "${STAGE_DIR}/EFI/BOOT/grubx64.efi" ] && [ -f "${STAGE_DIR}/EFI/BOOT/BOOTX64.EFI" ]; then
    echo "  Retaining Microsoft-signed shim and GRUB binaries for Secure Boot..."
    cp "${STAGE_DIR}/EFI/BOOT/BOOTX64.EFI" "${TMP_DIR}/efi_structure/EFI/BOOT/BOOTX64.EFI"
    cp "${STAGE_DIR}/EFI/BOOT/grubx64.efi" "${TMP_DIR}/efi_structure/EFI/BOOT/grubx64.efi"
    [ -f "${STAGE_DIR}/EFI/BOOT/mmx64.efi" ] && cp "${STAGE_DIR}/EFI/BOOT/mmx64.efi" "${TMP_DIR}/efi_structure/EFI/BOOT/mmx64.efi"
else
    cp "${TMP_DIR}/BOOTX64.EFI" "${STAGE_DIR}/EFI/BOOT/BOOTX64.EFI"
    cp "${TMP_DIR}/BOOTX64.EFI" "${TMP_DIR}/efi_structure/EFI/BOOT/BOOTX64.EFI"
fi

# 4. Create efi.img FAT partition image
echo "==> Creating EFI boot image (efi.img)..."
cp "${STAGE_DIR}/boot/grub/grub.cfg" "${TMP_DIR}/efi_structure/EFI/BOOT/grub.cfg"

rm -f "${STAGE_DIR}/boot/grub/efi.img"
dd if=/dev/zero of="${STAGE_DIR}/boot/grub/efi.img" bs=1M count=10 status=none
mkfs.vfat "${STAGE_DIR}/boot/grub/efi.img" > /dev/null
mcopy -s -i "${STAGE_DIR}/boot/grub/efi.img" "${TMP_DIR}/efi_structure/EFI" ::

# Remove boot.catalog if present so xorriso can generate a fresh one
rm -f "${STAGE_DIR}/boot.catalog"

# 5. Rebuild hybrid bootable ISO with xorriso
echo "==> Mastering new hybrid bootable ISO with xorriso..."
rm -f "${OUTPUT_ISO}"
xorriso -as mkisofs \
    -r -V "DEVOS_2404" \
    -J -joliet-long \
    -partition_offset 16 \
    --eltorito-alt-boot \
    -e boot/grub/efi.img \
    -no-emul-boot \
    -isohybrid-gpt-basdat \
    -output "${OUTPUT_ISO}" \
    "${STAGE_DIR}"

# 6. Cleanup temp files
rm -rf "${TMP_DIR}" "${STAGE_DIR}"

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
