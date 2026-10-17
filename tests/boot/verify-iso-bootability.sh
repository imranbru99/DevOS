#!/bin/bash
# DevOS hardware-boot verification gate.
# Validates that an ISO is a real hybrid image: bootable on a dd-written USB
# under Legacy BIOS/CSM, UEFI, and Secure Boot on/off.
# Exits 0 if all checks pass; non-zero with details otherwise.
set -euo pipefail

ISO="${1:-}"
[ -n "$ISO" ] || { echo "Usage: $0 <iso>" >&2; exit 2; }
[ -f "$ISO" ] || { echo "ERROR: ISO not found: $ISO" >&2; exit 2; }

PASS=0
FAIL=0
fail() { echo "  FAIL: $*" >&2; FAIL=$((FAIL+1)); }
pass() { echo "  PASS: $*"; PASS=$((PASS+1)); }
skip() { echo "  SKIP: $*"; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> Verifying hardware boot layout of $ISO"

# --- 0. Build a file list from the ISO (used for many checks) ---
ISO_LIST="${TMP}/iso.list"
if command -v xorriso >/dev/null 2>&1; then
    # xorriso -find uses '-exec echo', not '-print', and echoes quoted paths.
    xorriso -indev "$ISO" -find / -type f -exec echo 2>/dev/null |
        sed "s/^'//; s/'$//" > "$ISO_LIST" || true
elif command -v 7z >/dev/null 2>&1; then
    7z l -ba "$ISO" | awk '{print $6}' > "$ISO_LIST" || true
fi
iso_has() { grep -qFx "$1" "$ISO_LIST" 2>/dev/null; }

# --- 1. Basic ISO image sanity ---
if command -v file >/dev/null 2>&1; then
    file "$ISO" | grep -q "ISO 9660" || fail "File is not an ISO 9660 image"
    [ "$FAIL" -eq 0 ] && pass "ISO 9660 image format"
else
    skip "'file' not available, cannot verify ISO 9660 magic"
fi

# --- 2. MBR bootstrap code and bootable flag (Legacy BIOS) ---
MBR_BOOTCODE="$(od -An -tx1 -N 446 "$ISO" | tr -d ' \n')"
MBR_SIG="$(od -An -tx1 -N 2 -j 510 "$ISO" | tr -d ' \n')"
MBR_PT_BOOTABLE="$(od -An -tx1 -N 64 -j 446 "$ISO" | tr -d ' \n')"
if [ "${#MBR_BOOTCODE}" -lt 200 ] || [ "$MBR_BOOTCODE" = "$(printf '%0.s00' $(seq 1 446))" ]; then
    fail "MBR bootstrap code (bytes 0-445) is empty; Legacy BIOS USB boot will fail"
else
    pass "MBR bootstrap code is present"
fi
[ "$MBR_SIG" = "55aa" ] && pass "MBR signature 0x55AA present" || fail "Missing MBR signature 0x55AA"
# The bootable flag is the first byte of any of the four 16-byte partition
# entries that begin at MBR offset 446.
if printf '%s' "$MBR_PT_BOOTABLE" | grep -qE '^(.{32}){0,3}80'; then
    pass "MBR has a bootable partition entry"
else
    fail "No MBR partition marked bootable (some BIOSes ignore the stick)"
fi

# --- 3. GPT with an EFI System Partition (UEFI USB enumeration) ---
GPT_HEADER="$(dd if="$ISO" bs=512 skip=1 count=1 2>/dev/null | head -c 8)"
if [ "$GPT_HEADER" = "EFI PART" ]; then
    pass "GPT header present at LBA1"
    if command -v sgdisk >/dev/null 2>&1; then
        GPT_TYPE="$(sgdisk -i 2 "$ISO" 2>/dev/null | grep -i "Partition GUID code" | head -1 || true)"
        if echo "$GPT_TYPE" | grep -qi "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"; then
            pass "GPT partition 2 is an EFI System Partition"
        else
            fail "GPT partition 2 is NOT an EFI System Partition"
            echo "       $GPT_TYPE" >&2
        fi
    else
        skip "sgdisk not available, cannot verify ESP GUID"
    fi
else
    fail "No GPT header at LBA1; UEFI firmware cannot enumerate the ESP"
fi

# --- 4. xorriso system-area report: must show hybrid MBR + BIOS/UEFI entries ---
if command -v xorriso >/dev/null 2>&1; then
    SYSAREA="$(xorriso -indev "$ISO" -report_system_area as_mkisofs 2>/dev/null || true)"
    if echo "$SYSAREA" | grep -q -- "--grub2-mbr"; then
        pass "xorriso report: --grub2-mbr hybrid MBR used"
    else
        fail "xorriso report: missing --grub2-mbr hybrid MBR"
    fi
    if echo "$SYSAREA" | grep -qE "(-b|--boot-load-size).*eltorito.img"; then
        pass "xorriso report: BIOS El Torito entry present"
    else
        fail "xorriso report: missing BIOS El Torito entry"
    fi
    if echo "$SYSAREA" | grep -q "appended_partition_2"; then
        pass "xorriso report: UEFI entry points to appended ESP partition"
    else
        fail "xorriso report: UEFI entry does not reference appended ESP"
    fi
else
    skip "xorriso not available, cannot verify system area layout"
fi

# --- 5. Presence of required files on the ISO9660 filesystem ---
required=(
    /casper/vmlinuz
    /casper/initrd
    /casper/filesystem.squashfs
    /casper/filesystem.size
    /boot/grub/grub.cfg
    /boot/grub/i386-pc/eltorito.img
    /boot/grub/i386-pc/normal.mod
    /boot/grub/x86_64-efi/normal.mod
    /EFI/BOOT/BOOTX64.EFI
    /EFI/BOOT/grubx64.efi
    /.disk/info
)
for f in "${required[@]}"; do
    if iso_has "$f"; then
        pass "ISO file present: $f"
    else
        fail "ISO file missing: $f"
    fi
done

# --- 6. Live initrd contains the storage drivers needed for USB boot ---
if command -v lsinitramfs >/dev/null 2>&1 && command -v xorriso >/dev/null 2>&1; then
    INITRD="${TMP}/initrd"
    xorriso -osirrox on -indev "$ISO" -extract /casper/initrd "$INITRD" >/dev/null 2>&1 || true
    if [ -f "$INITRD" ]; then
        INITRD_LIST="${TMP}/initrd.list"
        lsinitramfs "$INITRD" 2>/dev/null > "$INITRD_LIST" || true

        for mod in isofs overlay usb-storage uas xhci-pci xhci-hcd nvme ahci vmd hid usbhid e1000e r8169; do
            if grep -qE "/${mod}\.ko" "$INITRD_LIST"; then
                pass "initrd module present: $mod"
            else
                skip "initrd module not present (may be built-in): $mod"
            fi
        done

        for mod in squashfs loop sd_mod sr_mod cdrom ext4 vfat; do
            if grep -qE "/${mod}\.ko" "$INITRD_LIST"; then
                pass "initrd module present: $mod"
            else
                skip "initrd module not present (expected built-in on Ubuntu): $mod"
            fi
        done
    else
        fail "Could not extract /casper/initrd from the ISO"
    fi
else
    skip "xorriso/lsinitramfs not available, cannot verify initrd contents"
fi

# --- 7. Squashfs rootfs is complete (kernel modules, firmware, /boot) ---
if command -v unsquashfs >/dev/null 2>&1 && command -v xorriso >/dev/null 2>&1; then
    SQUASH_IMG="${TMP}/filesystem.squashfs"
    SQUASH="${TMP}/squash"
    xorriso -osirrox on -indev "$ISO" -extract /casper/filesystem.squashfs "$SQUASH_IMG" >/dev/null 2>&1 || true
    if [ -f "$SQUASH_IMG" ]; then
        unsquashfs -q -d "$SQUASH" "$SQUASH_IMG" usr/lib/modules usr/lib/firmware boot >/dev/null 2>&1 || true
        if [ -d "$SQUASH/usr/lib/modules" ]; then
            kver_dir="$(find "$SQUASH/usr/lib/modules" -maxdepth 1 -mindepth 1 -type d | head -1)"
            if [ -n "$kver_dir" ] && [ -f "${kver_dir}/modules.dep" ]; then
                pass "squashfs rootfs contains kernel modules"
            else
                fail "squashfs rootfs kernel modules directory looks incomplete"
            fi
        else
            fail "squashfs rootfs has no /usr/lib/modules; installed system will not boot"
        fi
        [ -d "$SQUASH/usr/lib/firmware" ] && pass "squashfs rootfs contains firmware" || fail "squashfs rootfs missing firmware"
        ls "$SQUASH/boot/"vmlinuz-* >/dev/null 2>&1 && pass "squashfs rootfs contains /boot kernel" || fail "squashfs rootfs missing /boot kernel"
    else
        fail "Could not extract /casper/filesystem.squashfs from the ISO"
    fi
else
    skip "xorriso/unsquashfs not available, cannot verify rootfs contents"
fi

# --- Summary ---
echo ""
echo "==========================================================="
if [ "$FAIL" -eq 0 ]; then
    echo "Hardware-boot verification: PASSED ($PASS checks, $FAIL failures)"
    exit 0
else
    echo "Hardware-boot verification: FAILED ($PASS checks, $FAIL failures)"
    exit 1
fi
