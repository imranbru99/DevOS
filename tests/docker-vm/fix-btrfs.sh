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

echo "==> Clearing space cache and zeroing log..."
btrfs rescue zero-log "$loop" || true
btrfs rescue clear-space-cache v2 "$loop" || true
btrfs rescue clear-space-cache v1 "$loop" || true

echo "==> Testing mount..."
mkdir -p /mnt/root
if mount -o rw,subvol=@ "$loop" /mnt/root; then
    echo "MOUNT_SUCCESS_NORMAL: File system recovered and mounted rw normally!"
    umount /mnt/root
else
    echo "MOUNT_FAILED: standard rw mount still failed."
fi

losetup -d "$loop"
