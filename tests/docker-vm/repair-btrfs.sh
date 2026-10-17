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

echo "==> Running btrfs check --repair..."
# Provide yes to prompts if needed
yes | btrfs check --repair "$loop" || true

echo "==> Testing normal rw mount after repair..."
mkdir -p /mnt/root
if mount -o rw,subvol=@ "$loop" /mnt/root; then
    echo "REPAIR_SUCCESS: btrfs filesystem repaired and mounted rw successfully!"
    umount /mnt/root
else
    echo "REPAIR_UNSUCCESSFUL: standard mount failed."
fi

losetup -d "$loop"
