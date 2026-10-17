#!/bin/bash
set -euo pipefail
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq util-linux fdisk btrfs-progs e2fsprogs >/dev/null
losetup -Pf /disk.img
loop="$(losetup -j /disk.img | head -1 | cut -d: -f1)"
echo "loop=${loop}"
blkid "${loop}"* || true
fdisk -l "$loop" || true
for p in "${loop}p1" "${loop}p2"; do
  echo "=== try mount $p ==="
  mkdir -p /mnt/t
  if mount -o ro "$p" /mnt/t 2>/tmp/merr; then
    echo OK
    ls /mnt/t | head
    umount /mnt/t
  else
    cat /tmp/merr
  fi
done
losetup -d "$loop"
