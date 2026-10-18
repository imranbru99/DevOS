#!/bin/bash
set -euo pipefail

echo "==> Installing disk tools in helper container..."
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq util-linux mount btrfs-progs fdisk python3 >/dev/null

for loop in $(losetup -j /disk.img 2>/dev/null | cut -d: -f1); do
  losetup -d "$loop" 2>/dev/null || true
done

mkdir -p /mnt/root
start="$(fdisk -l /disk.img | awk '/Linux filesystem/ {print $2; exit}')"
offset=$((start * 512))
loop="$(losetup -f --show -o "${offset}" /disk.img)"
echo "Mounted disk offset ${offset} via ${loop}"

mount -o rw,subvol=@ "$loop" /mnt/root
echo "Mounted btrfs subvol=@ to /mnt/root"

echo "==> Updating Task Manager files..."
mkdir -p /mnt/root/usr/local/share/devos/components/taskman
mkdir -p /mnt/root/usr/local/bin
mkdir -p /mnt/root/usr/share/applications
mkdir -p /mnt/root/usr/local/sbin

cp -f /devos/components/taskman/taskman.py /mnt/root/usr/local/share/devos/components/taskman/taskman.py
cp -f /devos/build/includes.chroot/usr/local/bin/devos-taskman /mnt/root/usr/local/bin/devos-taskman
chmod 755 /mnt/root/usr/local/bin/devos-taskman
cp -f /devos/build/includes.chroot/usr/share/applications/devos-taskman.desktop /mnt/root/usr/share/applications/devos-taskman.desktop

echo "==> Installing DevOS AI Code Agent application..."
cp -f /devos/build/includes.chroot/usr/local/bin/devos-ai-code-agent /mnt/root/usr/local/bin/devos-ai-code-agent
chmod 755 /mnt/root/usr/local/bin/devos-ai-code-agent
cp -f /devos/build/includes.chroot/usr/local/bin/devos-antigravity /mnt/root/usr/local/bin/devos-antigravity 2>/dev/null || true
chmod 755 /mnt/root/usr/local/bin/devos-antigravity 2>/dev/null || true
cp -f /devos/build/includes.chroot/usr/local/bin/devos-code-agent /mnt/root/usr/local/bin/devos-code-agent 2>/dev/null || true
chmod 755 /mnt/root/usr/local/bin/devos-code-agent 2>/dev/null || true
cp -f /devos/build/includes.chroot/usr/share/applications/devos-ai-code-agent.desktop /mnt/root/usr/share/applications/devos-ai-code-agent.desktop
rm -f /mnt/root/usr/share/applications/devos-antigravity.desktop
if [ -f /devos/build/includes.chroot/usr/share/pixmaps/devos-ai-code-agent.png ]; then
    cp -f /devos/build/includes.chroot/usr/share/pixmaps/devos-ai-code-agent.png /mnt/root/usr/share/pixmaps/devos-ai-code-agent.png
    cp -f /devos/build/includes.chroot/usr/share/pixmaps/devos-ai-code-agent.png /mnt/root/usr/share/pixmaps/antigravity.png 2>/dev/null || true
    for size in 16 22 24 32 48 64 128 256; do
        dir="/mnt/root/usr/share/icons/hicolor/${size}x${size}/apps"
        mkdir -p "$dir"
        cp -f /devos/build/includes.chroot/usr/share/pixmaps/devos-ai-code-agent.png "${dir}/devos-ai-code-agent.png" 2>/dev/null || true
        cp -f /devos/build/includes.chroot/usr/share/pixmaps/devos-ai-code-agent.png "${dir}/antigravity.png" 2>/dev/null || true
    done
fi

echo "==> Updating branding scripts and DevOS logo branding..."
cp -f /devos/build/includes.chroot/usr/local/sbin/devos-debrand-desktop /mnt/root/usr/local/sbin/devos-debrand-desktop
chmod 755 /mnt/root/usr/local/sbin/devos-debrand-desktop
cp -f /devos/build/includes.chroot/usr/local/sbin/devos-apply-branding /mnt/root/usr/local/sbin/devos-apply-branding
chmod 755 /mnt/root/usr/local/sbin/devos-apply-branding

# Brand plasma icon with DevOS logo across icon themes
if [ -f /mnt/root/usr/share/pixmaps/devos-logo.png ]; then
    for size in 16 22 24 32 48 64 128 256; do
        dir="/mnt/root/usr/share/icons/hicolor/${size}x${size}/apps"
        mkdir -p "$dir"
        cp -f /mnt/root/usr/share/pixmaps/devos-logo.png "${dir}/plasma.png" 2>/dev/null || true
    done
    mkdir -p /mnt/root/usr/share/icons/hicolor/scalable/apps
    cp -f /mnt/root/usr/share/pixmaps/devos-logo.png /mnt/root/usr/share/icons/hicolor/scalable/apps/plasma.png 2>/dev/null || true
fi

# Run debrand desktop inside chroot
chroot /mnt/root /bin/bash /usr/local/sbin/devos-debrand-desktop || true

# Also sync to user home application cache if present and clear ksycoca cache
for home_user in /mnt/root/home/*; do
    if [ -d "$home_user/.local/share/applications" ]; then
        cp -f /mnt/root/usr/share/applications/devos-taskman.desktop "$home_user/.local/share/applications/" 2>/dev/null || true
        rm -f "$home_user/.local/share/applications/devos-antigravity.desktop" 2>/dev/null || true
    fi
    rm -rf "$home_user/.cache/ksycoca6"* "$home_user/.cache/krunner"* 2>/dev/null || true
done

sync
umount /mnt/root
losetup -d "$loop"
echo "==> PATCH_COMPLETE_SUCCESS: Task Manager and DevOS branding successfully written to disk!"
