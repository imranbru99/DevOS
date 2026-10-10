# DevOS Changelog

All notable changes to the DevOS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-10
### Added
- **Phase 1: Base System & ISO Pipeline** initial implementation.
- `docs/phase-1-plan.md`: Comprehensive Phase 1 execution plan, size budgeting, risk analysis, and acceptance criteria.
- `build/versions.lock`: Exact, verified package and model version locks based on Ubuntu 24.04 LTS (Noble Numbat).
- `build/package-lists/`:
  - `00-base.list.chroot`: Core system, HWE kernel, systemd-oomd, zram-tools, earlyoom, btrfs, snapper, cryptsetup.
  - `10-hardware.list.chroot`: Firmware, Mesa Vulkan drivers, network, audio (PipeWire), Wi-Fi, Bluetooth.
  - `20-installer.list.chroot`: Calamares 3.3+ installer, kpmcore backend, parted.
- `build/hooks/`:
  - `01-strip-bloat.hook.chroot`: Strip documentation, manuals, cache, and prune locales (retaining English and Bengali).
  - `02-disable-services.hook.chroot`: Mask unneeded background services (`cups-browsed`, `ModemManager`, `avahi-daemon`, `snapd`, `apport`, `whoopsie`, `motd-news`).
  - `03-tune-performance.hook.chroot`: Configure zramswap with zstd compression, earlyoom memory limits, systemd-oomd, and sysctl VM optimizations.
- `build/includes.chroot/etc/calamares/`: Complete Calamares installer configuration with default btrfs + zstd compression, LUKS full-disk encryption, and DevOS branding.
- `build/build-iso.sh`: Master automated ISO creation script producing hybrid BIOS+UEFI bootable ISO image with zstd compression.
- `build/setup-build-env.sh`: Host dependency installation script.
- `build/docker/Dockerfile.build`: Containerized reproducible build environment.
- `tests/qemu/run-qemu-test.sh`: Automated QEMU smoke testing script supporting both legacy BIOS and UEFI (OVMF).
- `.github/workflows/build-iso.yml`: GitHub Actions CI pipeline for automated ISO building, size validation (<= 4 GB), and smoke testing.
- `Makefile`: Universal workflow runner (`make setup`, `make iso`, `make iso-docker`, `make test-qemu-bios`, `make test-qemu-uefi`, `make check-size`, `make clean`).
- `THIRD_PARTY_NOTICES.md` & `LICENSES/`: Open-source licensing compliance and notices.
