#!/bin/bash
set -euo pipefail
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq util-linux mount btrfs-progs fdisk >/dev/null

for loop in $(losetup -j /disk.img 2>/dev/null | cut -d: -f1); do
  losetup -d "$loop" 2>/dev/null || true
done

start="$(fdisk -l /disk.img | awk '/Linux filesystem/ {print $2; exit}')"
offset=$((start * 512))
loop="$(losetup -f --show -o "${offset}" /disk.img)"
echo "Mounted loop device: $loop"

echo "Checking btrfs filesystem..."
btrfs check "$loop" || true

echo "Attempting mount..."
mkdir -p /mnt/root
if mount -o rw,subvol=@ "$loop" /mnt/root; then
    echo "Mount succeeded!"
    ls -la /mnt/root/boot || true
    echo "FSTAB entries:"
    cat /mnt/root/etc/fstab || true
    umount /mnt/root
else
    echo "Mount failed!"
fi

losetup -d "$loop"
