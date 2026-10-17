#!/bin/bash
set -euo pipefail
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq util-linux mount e2fsprogs btrfs-progs fdisk >/dev/null
for loop in $(losetup -j /disk.img | cut -d: -f1); do
  echo "detach $loop"
  losetup -d "$loop" 2>/dev/null || true
done
mkdir -p /mnt/root /mnt/home
start="$(fdisk -l /disk.img | awk '/Linux filesystem/ {print $2; exit}')"
offset=$((start * 512))
loop="$(losetup -f --show -o "${offset}" /disk.img)"
echo "loop=${loop} offset=${offset}"
blkid "$loop" || true
btrfs subvolume list /mnt/root 2>/dev/null || true
mount -o rw,subvol=@ "$loop" /mnt/root
echo "mounted @"
ls /mnt/root | head
# Home may be a separate subvolume.
if mount -o rw,subvol=@home "$loop" /mnt/home 2>/dev/null; then
  home_root=/mnt/home
  echo "mounted @home"
else
  home_root=/mnt/root/home
fi
home=""
for d in "${home_root}"/*; do
  [ -d "$d" ] || continue
  base="$(basename "$d")"
  [ "$base" = "lost+found" ] && continue
  home="$d"
  break
done
echo "home=${home}"
if [ -z "$home" ]; then
  echo "NO_USER_HOME"
  ls -la "$home_root" || true
  umount /mnt/home 2>/dev/null || true
  umount /mnt/root
  losetup -d "$loop"
  exit 3
fi
mkdir -p "$home/.config"
cp -f /fix/appletsrc "$home/.config/plasma-org.kde.plasma.desktop-appletsrc"
rm -f "$home/.config/devos-ui.stamp"
chown -R --reference="$home" "$home/.config" 2>/dev/null || true
mkdir -p /mnt/root/usr/local/share/devos /mnt/root/usr/local/bin
cp -f /fix/apply-ui.js /mnt/root/usr/local/share/devos/apply-ui.js
cp -f /fix/devos-apply-desktop /mnt/root/usr/local/bin/devos-apply-desktop
chmod 755 /mnt/root/usr/local/bin/devos-apply-desktop
ls -la /mnt/root/usr/share/wallpapers/DevOS/DevOS-Default.png
ls -la /mnt/root/usr/local/share/devos/
ls -la "$home/.config/plasma-org.kde.plasma.desktop-appletsrc"
umount /mnt/home 2>/dev/null || true
umount /mnt/root
losetup -d "$loop"
echo PATCH_OK
