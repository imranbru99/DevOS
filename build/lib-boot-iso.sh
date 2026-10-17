#!/bin/bash
# DevOS shared hybrid-boot ISO mastering engine.
# Produces a real-hardware-bootable ISO: Legacy BIOS, UEFI (x64 & IA32),
# Secure Boot on/off, from a dd-written USB stick or from a burned DVD.
# shellcheck shell=bash
set -euo pipefail

DEVOS_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVOS_ISO_LABEL="${DEVOS_ISO_LABEL:-DEVOS_2404}"

# Show a fatal error and stop the build.
_devos_die() { echo "FATAL: $*" >&2; exit 1; }

# Determine the grub tools/modules source for the given chroot (or host).
# Prints a path to a directory containing i386-pc/ and/or x86_64-efi/.
_devos_grub_dir() {
    local chroot="${1:-}"
    local host_dir host_ver chroot_ver
    host_dir=/usr/lib/grub
    host_ver="$(grub-mkimage --version 2>/dev/null | head -1 || true)"
    if [ -n "$chroot" ] && [ -x "${chroot}/usr/bin/grub-mkimage" ]; then
        chroot_ver="$(chroot "$chroot" grub-mkimage --version 2>/dev/null | head -1 || true)"
        if [ -n "$chroot_ver" ] && [ "$host_ver" = "$chroot_ver" ]; then
            echo "${chroot}/usr/lib/grub"
            return 0
        fi
    fi
    if [ -d "${host_dir}/i386-pc" ] || [ -d "${host_dir}/x86_64-efi" ]; then
        echo "$host_dir"
        return 0
    fi
    if [ -n "$chroot" ] && [ -d "${chroot}/usr/lib/grub/i386-pc" ]; then
        echo "${chroot}/usr/lib/grub"
        return 0
    fi
    return 1
}

# Resolve a tool: prefer inside chroot if versions match, otherwise host.
_devos_grub_tool() {
    local tool="$1" chroot="${2:-}"
    local host_ver chroot_ver
    host_ver="$("$tool" --version 2>/dev/null | head -1 || true)"
    if [ -n "$chroot" ] && [ -x "${chroot}/usr/bin/${tool}" ]; then
        chroot_ver="$(chroot "$chroot" "$tool" --version 2>/dev/null | head -1 || true)"
        if [ -n "$chroot_ver" ] && [ "$host_ver" = "$chroot_ver" ]; then
            echo "chroot $chroot $tool"
            return 0
        fi
    fi
    command -v "$tool" || _devos_die "grub tool '$tool' not found on host or in chroot"
}

# Copy a Unicode font into the stage so GRUB's gfxterm works on real GPUs.
devos_grub_font() {
    local stage="$1" chroot="${2:-}"
    mkdir -p "${stage}/boot/grub/fonts"
    local candidates=(
        "${chroot}/usr/share/grub/unicode.pf2"
        "${chroot}/boot/grub/fonts/unicode.pf2"
        "/usr/share/grub/unicode.pf2"
        "/boot/grub/fonts/unicode.pf2"
    )
    for f in "${candidates[@]}"; do
        if [ -f "$f" ]; then
            cp -f "$f" "${stage}/boot/grub/font.pf2"
            cp -f "$f" "${stage}/boot/grub/fonts/unicode.pf2"
            return 0
        fi
    done
    # Build a minimal font from DejaVu; fallback is thin but usable.
    local ttf=""
    for d in /usr/share/fonts/truetype/dejavu /usr/share/fonts/TTF "${chroot}/usr/share/fonts/truetype/dejavu"; do
        [ -f "${d}/DejaVuSans.ttf" ] && ttf="${d}/DejaVuSans.ttf" && break
    done
    if [ -n "$ttf" ] && command -v grub-mkfont >/dev/null 2>&1; then
        grub-mkfont -s 14 -o "${stage}/boot/grub/font.pf2" "$ttf" >/dev/null 2>&1 || true
        grub-mkfont -s 14 -o "${stage}/boot/grub/fonts/unicode.pf2" "$ttf" >/dev/null 2>&1 || true
    fi
}

# Copy the module directories needed for BIOS and UEFI GRUB into the ISO.
# UEFI Secure Boot shim -> signed grub -> normal.mod must be on the ISO9660 FS.
devos_grub_modules() {
    local stage="$1" chroot="${2:-}"
    local grub_dir
    grub_dir="$(_devos_grub_dir "$chroot")" || _devos_die "Cannot find GRUB module directory (host or chroot)"

    mkdir -p "${stage}/boot/grub/i386-pc" "${stage}/boot/grub/x86_64-efi"

    if [ -d "${grub_dir}/i386-pc" ]; then
        rsync -aL "${grub_dir}/i386-pc/" "${stage}/boot/grub/i386-pc/" --include='*.mod' --include='*.lst' --include='*.o' --exclude='*' || true
        # eltorito.img is generated fresh later; make sure we don't ship an old one.
        rm -f "${stage}/boot/grub/i386-pc/eltorito.img"
    fi

    if [ -d "${grub_dir}/x86_64-efi" ]; then
        rsync -aL "${grub_dir}/x86_64-efi/" "${stage}/boot/grub/x86_64-efi/" --include='*.mod' --include='*.lst' --include='*.o' --exclude='*' || true
    fi
}

# Write the single canonical GRUB config used by both BIOS and UEFI boot paths.
# Adds serial output so automated USB-boot tests / headless hardware can observe GRUB.
devos_grub_cfg() {
    local stage="$1"
    local out="${stage}/boot/grub/grub.cfg"
    mkdir -p "$(dirname "$out")"
    cat > "$out" << 'GRUBEOF'
# DevOS hardware-safe boot menu. Keep it short; real PCs ship with awful screens.
set default="0"
set timeout_style=menu
set timeout=8

# Serial console is harmless and lets QEMU/headless hardware show the menu.
serial --unit=0 --speed=115200 --word=8 --parity=no --stop=1
terminal_input console serial
terminal_output console serial

# Modern GPUs sometimes blank during gfxterm; keep it optional.
insmod part_gpt
insmod part_msdos
insmod iso9660
insmod fat
insmod ext2
insmod ntfs

set menu_color_normal=white/black
set menu_color_highlight=black/light-gray

function devos_root {
    search --no-floppy --set=root --file /casper/vmlinuz
    if [ -f /casper/vmlinuz ]; then
        return
    fi
    # Remastered/Ventoy fallbacks: find by label or scan everything.
    search --no-floppy --set=root --label DEVOS_2404
}

set bootargs="boot=casper username=devos hostname=devos ignore_uuid nopersistent fsck.mode=skip"

menuentry "Try or Install DevOS" {
    set gfxpayload=keep
    devos_root
    linux /casper/vmlinuz ${bootargs} quiet splash plymouth.theme=devos ---
    initrd /casper/initrd
}

menuentry "DevOS (Safe Graphics)" {
    set gfxpayload=text
    devos_root
    linux /casper/vmlinuz ${bootargs} nomodeset quiet splash plymouth.theme=devos ---
    initrd /casper/initrd
}

menuentry "DevOS (Safe Graphics, no splash)" {
    set gfxpayload=text
    devos_root
    linux /casper/vmlinuz ${bootargs} nomodeset plymouth.enable=0 ---
    initrd /casper/initrd
}

menuentry "DevOS (Serial debug)" {
    set gfxpayload=text
    devos_root
    linux /casper/vmlinuz ${bootargs} nomodeset plymouth.enable=0 console=ttyS0,115200n8 ---
    initrd /casper/initrd
}

menuentry "Check Disc for Defects" {
    devos_root
    linux /casper/vmlinuz ${bootargs} integrity-check quiet splash plymouth.theme=devos ---
    initrd /casper/initrd
}
GRUBEOF

    # UEFI Secure Boot signed GRUB may look at /EFI/BOOT/grub.cfg first, depending
    # on its compiled-in prefix. Provide the same file in the ESP as well.
    mkdir -p "${stage}/EFI/BOOT"
    cp -f "$out" "${stage}/EFI/BOOT/grub.cfg"
}

# Build the BIOS El Torito boot image.
devos_eltorito_img() {
    local stage="$1" chroot="${2:-}"
    local tmp="$3"
    local grub_dir tool cdboot
    grub_dir="$(_devos_grub_dir "$chroot")" || _devos_die "No GRUB i386-pc directory"
    [ -f "${grub_dir}/i386-pc/cdboot.img" ] || _devos_die "Missing cdboot.img"
    cdboot="${grub_dir}/i386-pc/cdboot.img"

    tool="$(_devos_grub_tool grub-mkstandalone "$chroot")"

    mkdir -p "${stage}/boot/grub/i386-pc"
    rm -f "${stage}/boot/grub/i386-pc/eltorito.img"

    # Embedded config for the standalone image: chain to the canonical grub.cfg.
    cat > "${tmp}/early_grub.cfg" << 'EOF'
search --no-floppy --set=root --file /casper/vmlinuz
set prefix=($root)/boot/grub
configfile $prefix/grub.cfg
EOF

    # --modules = linked into core.img; --install-modules = available in memdisk.
    $tool \
        --format=i386-pc \
        --output="${tmp}/core.img" \
        --locales="" \
        --fonts="" \
        --install-modules="linux linux16 normal iso9660 biosdisk memdisk search search_fs_file search_fs_uuid search_label part_msdos part_gpt fat ext2 ntfs chain configfile test sleep echo font gfxterm all_video" \
        --modules="linux normal iso9660 biosdisk search" \
        "boot/grub/grub.cfg=${tmp}/early_grub.cfg"

    cat "$cdboot" "${tmp}/core.img" > "${stage}/boot/grub/i386-pc/eltorito.img"
}

# Populate the UEFI ESP structure.
devos_efi_files() {
    local stage="$1" chroot="${2:-}"
    mkdir -p "${stage}/EFI/BOOT"

    local shim= grub= mm= fallback= boot_csv= ia32=

    # Prefer Microsoft-signed shim + Canonical signed GRUB when available.
    if [ -n "$chroot" ]; then
        for f in shimx64.efi.signed.latest shimx64.efi.signed; do
            [ -f "${chroot}/usr/lib/shim/$f" ] && shim="${chroot}/usr/lib/shim/$f" && break
        done
        for f in grubx64.efi.signed gcdx64.efi.signed; do
            [ -f "${chroot}/usr/lib/grub/x86_64-efi-signed/$f" ] && grub="${chroot}/usr/lib/grub/x86_64-efi-signed/$f" && break
        done
        for f in mmx64.efi.signed mmx64.efi; do
            [ -f "${chroot}/usr/lib/shim/$f" ] && mm="${chroot}/usr/lib/shim/$f" && break
        done
        for f in fallback.efi.signed fallback.efi; do
            [ -f "${chroot}/usr/lib/shim/$f" ] && fallback="${chroot}/usr/lib/shim/$f" && break
        done
        [ -f "${chroot}/usr/lib/shim/BOOTX64.CSV" ] && boot_csv="${chroot}/usr/lib/shim/BOOTX64.CSV"

        # Some Bay Trail/Atom tablets and old mini-PCs ship with IA32 UEFI on x86_64 CPUs.
        if [ -f "${chroot}/usr/lib/grub/i386-efi/monolithic/grubia32.efi" ]; then
            ia32="${chroot}/usr/lib/grub/i386-efi/monolithic/grubia32.efi"
        elif [ -d "${chroot}/usr/lib/grub/i386-efi" ] && command -v grub-mkstandalone >/dev/null 2>&1; then
            chroot "$chroot" grub-mkstandalone --format=i386-efi --output=/tmp/grubia32.efi \
                --modules="iso9660 fat part_msdos part_gpt normal boot linux search configfile" \
                "boot/grub/grub.cfg=/boot/grub/grub.cfg" >/dev/null 2>&1 && ia32="${chroot}/tmp/grubia32.efi" || true
        fi
    fi

    # Fall back to the stage (remaster/resume scenario).
    if [ -z "$shim" ] && [ -f "${stage}/EFI/BOOT/BOOTX64.EFI" ]; then
        shim="${stage}/EFI/BOOT/BOOTX64.EFI"
    fi
    if [ -z "$grub" ] && [ -f "${stage}/EFI/BOOT/grubx64.efi" ]; then
        grub="${stage}/EFI/BOOT/grubx64.efi"
    fi

    if [ -n "$shim" ] && [ -n "$grub" ]; then
        echo "  Using signed shim + GRUB for Secure Boot (x64)"
        [ "$shim" != "${stage}/EFI/BOOT/BOOTX64.EFI" ] && cp -fL "$shim" "${stage}/EFI/BOOT/BOOTX64.EFI"
        [ "$grub" != "${stage}/EFI/BOOT/grubx64.efi" ] && cp -fL "$grub" "${stage}/EFI/BOOT/grubx64.efi"
        [ -n "$mm" ] && [ "$mm" != "${stage}/EFI/BOOT/mmx64.efi" ] && cp -fL "$mm" "${stage}/EFI/BOOT/mmx64.efi"
        [ -n "$fallback" ] && cp -fL "$fallback" "${stage}/EFI/BOOT/fallback.efi"
        [ -n "$boot_csv" ] && cp -fL "$boot_csv" "${stage}/EFI/BOOT/BOOTX64.CSV"
    else
        echo "  WARNING: signed shim/GRUB missing; building unsigned x64 standalone fallback"
        local tool
        tool="$(_devos_grub_tool grub-mkstandalone "$chroot")"
        $tool --format=x86_64-efi --output="${stage}/EFI/BOOT/BOOTX64.EFI" \
            --locales="" --fonts="" \
            --modules="iso9660 fat ntfs ext2 part_msdos part_gpt normal boot linux search search_fs_file search_fs_uuid search_label configfile font test sleep echo" \
            "boot/grub/grub.cfg=${stage}/boot/grub/grub.cfg" || true
    fi

    if [ -n "$ia32" ]; then
        echo "  Adding IA32 UEFI fallback for 32-bit-EFI machines"
        cp -fL "$ia32" "${stage}/EFI/BOOT/BOOTIA32.EFI"
    fi

    # UEFI signed GRUB might look for its config relative to where it loaded from,
    # so keep a copy in the ESP as well.
    if [ -f "${stage}/boot/grub/grub.cfg" ]; then
        cp -f "${stage}/boot/grub/grub.cfg" "${stage}/EFI/BOOT/grub.cfg"
    fi
}

# Build a FAT ESP image from the ESP files placed under $stage/EFI.
devos_efi_img() {
    local stage="$1" tmp="$2"
    local efi_structure="${tmp}/efi_structure"

    mkdir -p "${efi_structure}/EFI/BOOT"
    cp -a "${stage}/EFI/BOOT/." "${efi_structure}/EFI/BOOT/"

    # Fixed 16 MB ESP: large enough for signed shim + GRUB + MokManager + IA32
    # fallback, and universally accepted by UEFI firmware.
    rm -f "${stage}/boot/grub/efi.img"
    dd if=/dev/zero of="${stage}/boot/grub/efi.img" bs=1M count=16 status=none
    mkfs.vfat -F 16 "${stage}/boot/grub/efi.img" >/dev/null
    mcopy -s -i "${stage}/boot/grub/efi.img" "${efi_structure}/EFI" ::
}

# Write .disk metadata that casper and the signed GRUB expect.
devos_disk_meta() {
    local stage="$1" initrd="${2:-}"
    mkdir -p "${stage}/.disk"
    echo 'DevOS 24.04 LTS "Noble" - amd64' > "${stage}/.disk/info"
    echo 'full_cd/single' > "${stage}/.disk/cd_type"
    echo 'DevOS 24.04 LTS' > "${stage}/.disk/base_installable"
    if [ -n "$initrd" ] && [ -f "$initrd" ]; then
        local uuid
        uuid="$(devos_initrd_casper_uuid "$initrd" || true)"
        if [ -n "$uuid" ]; then
            echo "$uuid" > "${stage}/.disk/casper-uuid-generic"
        fi
    fi
}

# Try to read the casper UUID baked into the live initrd.
devos_initrd_casper_uuid() {
    local initrd="$1"
    command -v lsinitramfs >/dev/null 2>&1 || return 1
    lsinitramfs "$initrd" 2>/dev/null | sed -n 's#^conf/conf\.d/casper-uuid-generic:\s*##p' | head -1
}

# Generate md5sum.txt for the integrity-check menu entry.
# Exclude files that xorriso patches during mastering.
devos_md5sum_txt() {
    local stage="$1"
    rm -f "${stage}/md5sum.txt"
    (cd "$stage" && find . -type f \
        ! -path './boot/grub/i386-pc/eltorito.img' \
        ! -path './boot.catalog' \
        ! -path './md5sum.txt' \
        -print0 | xargs -0 md5sum > md5sum.txt) || true
}

# Prepare the full boot tree: GRUB config, modules, font, BIOS El Torito image,
# UEFI ESP structure + efi.img, .disk metadata, md5sum.txt.
devos_prepare_boot_tree() {
    local stage="$1" chroot="${2:-}"
    local tmp="${3:-$(mktemp -d)}"

    # Make sure /casper is present before we build paths around it.
    [ -f "${stage}/casper/vmlinuz" ] || _devos_die "Stage missing casper/vmlinuz"

    devos_grub_cfg "$stage"
    devos_grub_font "$stage" "$chroot"
    devos_grub_modules "$stage" "$chroot"
    devos_eltorito_img "$stage" "$chroot" "$tmp"
    devos_efi_files "$stage" "$chroot"
    devos_efi_img "$stage" "$tmp"
    devos_disk_meta "$stage" "${stage}/casper/initrd"
    devos_md5sum_txt "$stage"

    rm -rf "$tmp"
}

# Master the final hybrid ISO. stage/ must already contain casper/* and a prepared
# boot tree from devos_prepare_boot_tree.
devos_master_iso() {
    local stage="$1" out_iso="$2"
    local staged_iso

    [ -f "${stage}/boot/grub/i386-pc/eltorito.img" ] || _devos_die "Missing El Torito image"
    [ -f "${stage}/boot/grub/efi.img" ] || _devos_die "Missing EFI boot image"
    [ -f "${stage}/casper/filesystem.squashfs" ] || _devos_die "Missing casper/filesystem.squashfs"

    GRUB_PC_DIR=/usr/lib/grub/i386-pc
    if [ ! -f "${GRUB_PC_DIR}/boot_hybrid.img" ]; then
        # Try chroot as fallback (should match the tools used for eltorito.img).
        GRUB_PC_DIR="${stage}/../../usr/lib/grub/i386-pc"
    fi
    [ -f "${GRUB_PC_DIR}/boot_hybrid.img" ] || _devos_die "GRUB boot_hybrid.img not found at ${GRUB_PC_DIR}"

    mkdir -p "$(dirname "$out_iso")"
    staged_iso="$(mktemp /tmp/devos-iso-XXXXXX.iso)"
    rm -f "$staged_iso" "$out_iso"

    xorriso -as mkisofs \
        -iso-level 3 \
        -r -V "${DEVOS_ISO_LABEL}" \
        -J -joliet-long \
        -partition_offset 16 \
        --mbr-force-bootable \
        --grub2-mbr "${GRUB_PC_DIR}/boot_hybrid.img" \
        -c /boot.catalog \
        -b /boot/grub/i386-pc/eltorito.img \
        -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
        -eltorito-alt-boot \
        -append_partition 2 0xef "${stage}/boot/grub/efi.img" \
        -appended_part_as_gpt \
        -e '--interval:appended_partition_2:all::' \
        -no-emul-boot \
        -output "$staged_iso" \
        "$stage"

    cp -f "$staged_iso" "$out_iso"
    rm -f "$staged_iso"
}
