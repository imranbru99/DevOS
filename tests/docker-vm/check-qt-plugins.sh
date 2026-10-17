#!/bin/bash
set -euo pipefail

apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq util-linux mount btrfs-progs fdisk >/dev/null

for loop in $(losetup -j /disk.img 2>/dev/null | cut -d: -f1); do
  losetup -d "$loop" 2>/dev/null || true
done

mkdir -p /mnt/root
start="$(fdisk -l /disk.img | awk '/Linux filesystem/ {print $2; exit}')"
offset=$((start * 512))
loop="$(losetup -f --show -o "${offset}" /disk.img)"
mount -o rw,subvol=@ "$loop" /mnt/root

echo "=== Check ldd on libqwayland-generic.so ==="
chroot /mnt/root ldd /usr/lib/x86_64-linux-gnu/qt5/plugins/platforms/libqwayland-generic.so 2>&1 | grep "not found" || echo "All libs found for wayland-generic"

echo "=== Check ldd on libqxcb.so ==="
chroot /mnt/root ldd /usr/lib/x86_64-linux-gnu/qt5/plugins/platforms/libqxcb.so 2>&1 | grep "not found" || echo "All libs found for xcb"

echo "=== Test running taskman with QT_DEBUG_PLUGINS=1 ==="
chroot /mnt/root /bin/bash -c '
export QT_DEBUG_PLUGINS=1
export QT_QPA_PLATFORM=xcb
python3 -c "from PyQt5 import QtWidgets; app = QtWidgets.QApplication([])" 2>&1 | head -n 40
' || true

umount /mnt/root
losetup -d "$loop"
echo "=== DONE ==="
