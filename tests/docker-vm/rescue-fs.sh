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

echo "Trying btrfs restore..."
mkdir -p /tmp/test-restore
btrfs restore -l "$loop" | head -n 20 || true

echo "Trying btrfs rescue super-recover..."
btrfs rescue super-recover -v "$loop" || true

echo "Trying mount with usebackuproot..."
mkdir -p /mnt/root
if mount -o ro,usebackuproot,subvol=@ "$loop" /mnt/root; then
    echo "SUCCESS: mounted with usebackuproot!"
    umount /mnt/root
elif mount -o ro,rescue=all,subvol=@ "$loop" /mnt/root; then
    echo "SUCCESS: mounted with rescue=all!"
    umount /mnt/root
else
    echo "Mount with rescue options failed."
fi

losetup -d "$loop"
