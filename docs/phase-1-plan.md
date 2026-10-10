# DevOS Phase 1 Plan: Base System & ISO Pipeline

## 1. Objectives & Scope
Phase 1 establishes the reproducible foundational image and bootable hybrid BIOS+UEFI ISO for **DevOS**:
- Base: **Ubuntu 24.04 LTS (Noble Numbat)**, strictly avoiding Snaps (using deb/Flatpak/AppImage).
- Installer: **Calamares 3.3+** with DevOS branding, LUKS full-disk encryption, btrfs default (with zstd compression & Snapper snapshots) alongside ext4 option.
- Kernel & Performance: HWE kernel (`linux-generic-hwe-24.04`), `zram-tools` (zstd compression), `earlyoom`, `systemd-oomd`, `fstrim.timer`.
- Boot Speed & Service Optimization: Disable or mask unnecessary daemons (`cups-browsed`, `ModemManager`, `avahi-daemon`, `snapd`, `apport`, `whoopsie`, `motd-news`). Minimal Plymouth splash.
- Storage & Size Budget: ISO <= 4.0 GB; strip documentation (`/usr/share/doc`, `/usr/share/man`), clean package caches, keep only English (`en`) and Bengali (`bn`) locales initially with pluggable locale support. SquashFS compressed with `zstd -Xcompression-level 19`.
- Hardware & Drivers: `linux-firmware`, Mesa Vulkan drivers, `ubuntu-drivers-common` for on-demand proprietary NVIDIA driver selection, Wi-Fi/Bluetooth firmware, CUPS print subsystem on demand.
- Build Reproducibility: Fully automated via single `make iso` command runnable natively or inside a container (`ubuntu:noble`).

---

## 2. Architecture & Pipeline Design

```
+-------------------------------------------------------------+
|                     DevOS Build Pipeline                     |
+-------------------------------------------------------------+
                             |
         +-------------------+-------------------+
         |                                       |
         v                                       v
[Host Environment]                      [Containerized Build]
  Ubuntu 24.04 host / VM                  Docker / Podman (ubuntu:noble)
         |                                       |
         +-------------------+-------------------+
                             |
                             v
                 `build/scripts/build-iso.sh`
                             |
   1. Bootstrap Chroot (debootstrap noble / mirror)
   2. Configure APT repos (noble, noble-updates, noble-security)
   3. Purge & mask snapd; pin apt against snap packages
   4. Install Package Lists:
      - 00-base.list.chroot (kernel, systemd, btrfs, zram, earlyoom)
      - 10-hardware.list.chroot (firmware, mesa, vulkan, wifi, bt)
      - 20-installer.list.chroot (calamares, kpmcore, cryptsetup)
   5. Inject Custom Overrides:
      - includes.chroot/etc (zram, earlyoom, calamares, sysctl)
      - branding (plymouth theme, grub theme, calamares branding)
   6. Execute Optimization Hooks:
      - 01-strip-bloat.hook.chroot (strip doc/man, prune locales)
      - 02-disable-services.hook.chroot (mask unneeded daemons)
      - 03-tune-performance.hook.chroot (sysctl, zram, oomd)
   7. Create Live Rootfs (mksquashfs with zstd -Xcompression-level 19)
   8. Assemble ISO Image (xorriso with hybrid MBR + UEFI El Torito)
                             |
                             v
                  `devos-24.04-amd64.iso`
                             |
            +----------------+----------------+
            |                                 |
            v                                 v
   [BIOS QEMU Test]                  [UEFI QEMU Test]
   - Boot verification               - OVMF boot verification
   - Plymouth display                - Calamares launch
   - systemd-analyze                 - Idle RAM / CPU check
```

---

## 3. Package Selection & Budget Breakdown

| Component Category | Target Compressed Size | Target Installed Size | Key Packages |
|---|---|---|---|
| **Kernel & Core** | ~350 MB | ~1.1 GB | `linux-generic-hwe-24.04`, `systemd`, `systemd-sysv`, `systemd-oomd`, `udev`, `dbus`, `initramfs-tools`, `casper` |
| **Storage & Boot** | ~60 MB | ~180 MB | `btrfs-progs`, `snapper`, `cryptsetup`, `grub-efi-amd64-signed`, `shim-signed`, `efibootmgr` |
| **System Tuning** | ~15 MB | ~45 MB | `zram-tools`, `earlyoom`, `util-linux` (`fstrim`), `procps` |
| **Hardware & Firmware** | ~550 MB | ~1.6 GB | `linux-firmware`, `mesa-vulkan-drivers`, `libvulkan1`, `ubuntu-drivers-common`, `wireless-regdb`, `wpasupplicant`, `bluez` |
| **Installer** | ~120 MB | ~380 MB | `calamares`, `kpmcore`, `calamares-settings-ubuntu`, `parted`, `dosfstools` |
| **Base Utilities** | ~100 MB | ~300 MB | `bash`, `coreutils`, `iproute2`, `curl`, `wget`, `sudo`, `plymouth`, `plymouth-theme-spinner` |
| **Total Phase 1 Base** | **~1.2 GB** | **~3.6 GB** | Well under the 4.0 GB ISO target budget. |

---

## 4. Risks & Mitigations

1. **Snap Dependencies in Ubuntu Noble**:
   - *Risk*: `ubuntu-standard` or desktop packages may attempt to pull `snapd`.
   - *Mitigation*: Mask `snapd` via apt pin (`/etc/apt/preferences.d/nosnap.pref`), install Chromium/Firefox as deb or prepare for Flatpak in Phase 2/3.
2. **SquashFS Compression Overhead**:
   - *Risk*: Highest zstd compression (`level 19`) requires significant CPU and RAM during ISO build.
   - *Mitigation*: Support `-comp zstd -Xcompression-level 15` in dev/debug mode and `19` in production CI builds.
3. **Calamares btrfs + Subvolume Configuration**:
   - *Risk*: Incomplete btrfs subvolume layout (`@` and `@home`) leads to snapshot management issues with Snapper.
   - *Mitigation*: Explicitly define the mount points and subvolumes in Calamares `mount.conf` and `partition.conf`.
4. **Hybrid Boot (UEFI + Legacy BIOS)**:
   - *Risk*: Missing EFI bootloader or incorrect MBR partition table causes boot failures on older BIOS or modern UEFI systems.
   - *Mitigation*: Use standard `xorriso` with `isohybrid --uefi` flags matching Ubuntu/Debian official live ISO templates.

---

## 5. Acceptance Test Criteria

1. **Build Success**: `make iso` (or `make iso-docker`) produces `devos-24.04-amd64.iso` without errors.
2. **Size Constraint**: Final ISO file size <= 4.0 GB (target: ~1.5 - 2.5 GB for base).
3. **BIOS Boot**: Boots in QEMU (`qemu-system-x86_64`) to desktop/live user session.
4. **UEFI Boot**: Boots in QEMU with OVMF firmware.
5. **Installer Validation**: Calamares installer starts, detects disks, offers btrfs with zstd compression by default, and supports LUKS.
6. **Performance & Services**:
   - `systemd-analyze` reports startup time <= 15 s in virtualized environment.
   - Disabled services (`cups-browsed`, `ModemManager`, `avahi-daemon`, `snapd`, `apport`) are not active.
   - `zram-tools` and `earlyoom` are active and configured.
