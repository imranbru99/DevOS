#!/bin/bash
set -euo pipefail

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq util-linux mount btrfs-progs fdisk python3 >/dev/null

for loop in $(losetup -j /disk.img 2>/dev/null | cut -d: -f1); do
  losetup -d "$loop" 2>/dev/null || true
done

mkdir -p /mnt/root
start="$(fdisk -l /disk.img | awk '/Linux filesystem/ {print $2; exit}')"
offset=$((start * 512))
loop="$(losetup -f --show -o "${offset}" /disk.img)"
mount -o rw,subvol=@ "$loop" /mnt/root

echo "=== 1. Checking PyQt5 in chroot ==="
chroot /mnt/root python3 -c '
import sys
try:
    from PyQt5 import QtCore, QtGui, QtWidgets
    print("SUCCESS: PyQt5 imported cleanly!")
except Exception as e:
    print("PyQt5 IMPORT ERROR:", type(e).__name__, e)
' || true

echo "=== 2. Checking available Qt platform plugins ==="
ls -la /mnt/root/usr/lib/x86_64-linux-gnu/qt5/plugins/platforms/ 2>/dev/null || echo "No qt5 platforms dir!"

echo "=== 3. Testing devos-taskman directly ==="
chroot /mnt/root /bin/bash -c '
export DISPLAY=:0
export WAYLAND_DISPLAY=wayland-0
/usr/local/bin/devos-taskman 2>&1
' || true

echo "=== 4. Checking permissions and file size of taskman ==="
ls -la /mnt/root/usr/local/share/devos/components/taskman/taskman.py
ls -la /mnt/root/usr/local/bin/devos-taskman

umount /mnt/root
losetup -d "$loop"
echo "=== DIAGNOSTIC_DONE ==="
