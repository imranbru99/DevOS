# DevOS Changelog

All notable changes to the DevOS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-10
### Added
- **Phase 2: Windows-Like Desktop (`DevOS Desktop`)**
  - Plasma 6 Windows keybindings in `build/includes.chroot/etc/xdg/kglobalshortcutsrc` (Win for Start, Win+E for Dolphin Explorer, Win+D for Desktop, Win+R for KRunner, Win+Shift+S for Spectacle, Alt+Tab, and Win+Arrow snapping).
  - Dolphin file manager layout in `build/includes.chroot/etc/xdg/dolphinrc` configured to feel like Explorer.
  - DevOS Control Center manager in `components/settings/control_center.py` managing display, AI, apps, dev tools, and backups.
  - Interactive First-Boot setup wizard in `components/first-boot/wizard.py` detecting hardware, Bengali & English locales, and feature toggles.
- **Phase 3: Windows Application Compatibility Layer (`winlayer`)**
  - Per-app isolated prefix manager in `components/winlayer/prefix_manager.py` with automatic Start Menu `.desktop` shortcut creation and btrfs reflink deduplication.
  - Static PE analyzer in `components/winlayer/doctor.py` parsing PE headers, architecture, DirectX/Vulkan/DotNet runtimes, and flagging kernel anti-cheat / DRM.
  - Detailed compatibility guide in `docs/WINDOWS_COMPAT.md`.
- **Phase 3B: Linux Apps + Android Apps + Universal App Hub (`apphub`, `androidlayer`)**
  - Universal magic-byte type router in `components/apphub/type_router.py` accurately routing mislabeled files by binary signatures (PE `MZ`, APK `AndroidManifest.xml`, ELF/AppImage, `.deb`).
  - Pre-execution safety scanner in `components/apphub/safety_scanner.py` with ClamAV/EICAR malware detection and high-risk Android permission inspection.
  - Universal App Hub CLI in `components/apphub/hub.py` unified across Flathub, APT, F-Droid, and WinLayer.
  - Waydroid manager in `components/androidlayer/waydroid_manager.py` handling container lifecycle, multi-window mode, and `~/Android` shared folders.
  - Detailed Android compatibility guide in `docs/ANDROID_COMPAT.md`.
- **Phase 4 & 5: Local AI Core & System Agent**
  - Zero-dependency local hardware detector in `components/ai-core/hardware_detector.py`.
  - Offline model manager in `components/ai-core/aimodel.py` with SHA256 integrity verification.
  - OpenAI-compatible inference server on `127.0.0.1:11434/v1` in `components/ai-core/server.py`.
  - Conversational system agent with safety gates and audit logging in `components/ai-agent/agent.py`.
  - Heavy load watchdog in `components/ai-agent/system_watchdog.py`.
- **Phase 6: Local Developer Workstation (`devserver`)**
  - Laragon-style local server manager in `components/devserver/server_manager.py` for Caddy, PHP-FPM, MariaDB, Redis, and Mailpit with one-click `*.test` HTTPS domain provisioning.
- **Phase 7: Local Code Agent (`code-agent`)**
  - CLI `components/code-agent/code_agent.py` integrating repository tree mapping, local model querying, and framework skills for Laravel, Filament, Next.js, and Python.
- **Phase 8: Polish, Snapshots & Master CLI**
  - Master unified CLI dispatcher in `components/devos_cli.py` (`devos app`, `devos code`, `devos serve`, `devos ai`, `devos win`, `devos android`, `devos watchdog`).
  - Btrfs Snapper restore point manager in `components/settings/snapshot_manager.py`.
  - Debloat and size audit script in `tools/size-report.sh`.

## [0.1.0] - 2026-10-10
### Added
- **Phase 1: Base System & ISO Pipeline** initial implementation.
- `docs/phase-1-plan.md`, `Makefile`, `build/build-iso.sh`, `build/setup-build-env.sh`, and `build/docker/Dockerfile.build`.
- Complete Calamares installer configuration with default btrfs + zstd compression and LUKS support.
- Anti-hang kernel tuning and `systemd-oomd` configuration.
