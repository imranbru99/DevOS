#!/bin/bash
# Refresh Plymouth wording + GRUB quiet splash on the installed disk.
set -euo pipefail
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq util-linux mount btrfs-progs fdisk >/dev/null
for loop in $(losetup -j /disk.img | cut -d: -f1); do
  losetup -d "$loop" 2>/dev/null || true
done
mkdir -p /mnt/root
start="$(fdisk -l /disk.img | awk '/Linux filesystem/ {print $2; exit}')"
offset=$((start * 512))
loop="$(losetup -f --show -o "${offset}" /disk.img)"
mount -o rw,subvol=@ "$loop" /mnt/root
cp -f /fix/devos.script /mnt/root/usr/share/plymouth/themes/devos/devos.script
mkdir -p /mnt/root/etc/default/grub.d
cp -f /fix/devos.cfg /mnt/root/etc/default/grub.d/devos.cfg
# Point the installed kernel cmdline at the DevOS splash without a full
# update-grub (no chroot). Edit every GRUB linux line that already has quiet.
if [ -f /mnt/root/boot/grub/grub.cfg ]; then
  sed -i \
    -e 's/quiet splash\(\| plymouth.theme=devos\)/quiet splash plymouth.theme=devos/g' \
    -e 's/quiet splash plymouth.theme=devos plymouth.theme=devos/quiet splash plymouth.theme=devos/g' \
    /mnt/root/boot/grub/grub.cfg
fi
if [ -f /mnt/root/etc/default/grub ]; then
  if grep -q '^GRUB_CMDLINE_LINUX_DEFAULT=' /mnt/root/etc/default/grub; then
    sed -i 's|^GRUB_CMDLINE_LINUX_DEFAULT=.*|GRUB_CMDLINE_LINUX_DEFAULT="quiet splash plymouth.theme=devos"|' \
      /mnt/root/etc/default/grub
  else
    echo 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash plymouth.theme=devos"' \
      >> /mnt/root/etc/default/grub
  fi
fi
umount /mnt/root
losetup -d "$loop"
echo PATCH_BOOT_OK
