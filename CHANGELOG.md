# DevOS Changelog

All notable changes to the DevOS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Dedicated native authentication style for KDE/Polkit: larger rounded password field and buttons, cyan keyboard focus and dark blue surfaces; retains PAM, identity switching, errors, Cancel and password visibility controls.
- Shared DevOS confirmation/input dialog styling, explicit Optimizer delete action with safe Cancel default, and Qt 6 native theme support for system authentication dialogs.
- README operating guide for current storage, recorder, optimizer, pipeline, Islamic reminders, live browser blur controls, and safe component updates.
- Live recorder loudness meter, recording toolbar/tray signal bars, background MP4/WebM saves, and a non-destructive trim/copy/cut editor with audio mute/replace/mix exports.
- Daily bounded Optimizer cache care with an opt-out setting; preserves user files, active caches, recordings and offline models.
- Optional installer Data drives page with explicit selection, confirmation and automatic ext4 A/B/C layouts; leaves Calamares-managed disks and unselected storage intact.
- Storage volume planner for SSD/HDD/USB devices, size previews, protected system-disk cards and an advanced partition-editor entry point.
- Desktop-user home/settings write checks during installation and at login, with distinct permission, read-only, full-disk, quota and I/O error reporting.

### Fixed
- Update new-account dialog fonts and migrate only exact old DevOS font defaults on login; preserve custom fonts and sizes.
- Stop editing compiled KDE branding strings; repair damaged cached native packages and gate ISO builds on ELF checksums and critical disk-tool execution.
- Preserve Modesty Filter locked state and private-window policy during updates; install missing Qt theme dependencies.
- Choose automatic partition tables for the current firmware, show readable drive/volume review, refresh hardware facts on each installer retry, and skip root Snapper boot jobs without a configuration.
- Animated installer startup now uses the shared disk-probing launcher; throttles window checks instead of spawning a subprocess every animation frame.
- AI pipeline respects scheduled order, preserves queue writes atomically under a shared lock, runs provider calls outside the UI thread, and distinguishes submitted work from verified completion. Missing tools and failed repository creation no longer report success.
- Newly formatted Linux data volumes receive the invoking/installed user's ownership instead of remaining unwritable root-owned volumes. Unknown, mounted, read-only and active system targets are rejected; disk identity is rechecked before whole-disk changes.
- Security settings use unique temporary files and durable writes, preserve the old file on write failure, and avoid predictable temporary-file symlinks.
- Replace unsafe automatic Btrfs log clearing/forced write remounts with diagnostic guidance; remove claims that recovery can never fail.
- Security updates match Ubuntu archive origins despite DevOS branding; old generated origin templates are repaired on boot while preserving disabled updates and local settings.
- Manual security updates refresh package lists and fail clearly when the security updater is missing.
- ISO validation normalizes 7z paths instead of reporting existing boot files missing. CI runs installer/update tests and the boot-layout gate, and reports QEMU startup errors.

### Changed
- Add restrained shared animated installer backgrounds, retaining the DevOS emblem and an animation toggle across setup pages.
- Consolidate hardware tuning, cap pending disk writes, isolate optional AI resources and monitor application slices for memory pressure. Bound journal/crash/package cache retention without deleting useful caches for supposed speed gains.
- Bound pre-update snapshot creation to 30 seconds, skip its Python backend on ext4, enable scheduled Snapper cleanup, and rotate security/snapshot logs. Limit runtime journal usage and retain system journal entries for at most 30 days.
- Raise the installer disk-space gate to 32 GB and use a 64 GB sparse disk for new QEMU test targets.
- Add a shared installer animation toggle, keyboard-accessible navigation with focus outlines, a scrolling welcome page, responsive sidebar spacing, and a lightweight vector background.
- Default to manual partitioning for explicit formatting choices; retain automatic single-disk installation. Animate the boot logo and loading indicator.

## [0.3.0] - 2026-10-25
### Added
- **Terminal Smart Suggestions & Autocompletion System**
  - Unified `devos` interactive menu in `components/devos_cli.py` featuring arrow-key navigation (↑/↓), real-time search/filter, and instant command execution.
  - Typo and similar-command detector using subsequence and tag scoring (e.g. `blr` -> `modesty`, `rec` -> `recorder`, `audio` -> `sound`, `screen` -> `recorder`).
  - Shell completion scripts (`/etc/bash_completion.d/devos`, `~/.bash_completion`, `usr/share/bash-completion/completions/devos`) with fuzzy match fallback and argument completions.
  - Readline menu-complete and arrow-key cycling configuration (`~/.inputrc`, `build/includes.chroot/etc/inputrc`, `build/includes.chroot/etc/skel/.inputrc`).
  - Bash `command_not_found_handle` in `~/.bashrc` and `etc/skel/.bashrc` displaying smart suggestions whenever a mistyped DevOS command is entered.
  - Comprehensive unit test coverage for DevOS CLI catalog, fuzzy matching, and typo resolution.
- **Screen Recorder MP4 Format & Recording Controls**
  - Added native MP4 container recording using fragmented MP4 muxing (`-movflags +frag_keyframe+empty_moov+default_base_moof`) alongside WebM.
  - Fixed duplicate recording indicator on dock and system tray.
  - Spectacle region recording shortcuts configured (`Win+Shift+S`).
- **Browser Modesty & Safety Controls**
  - Unlocked browser modesty filter policy allowing user-controlled on/off toggle.
  - Added AI chat tool integration (`sudo devos-modesty enable/disable/status`).
- **Filesystem Resilience & Automated Btrfs Recovery**
  - Added early boot automatic self-healing hook `devos-btrfs-heal` in `etc/initramfs-tools/scripts/local-bottom/` to clear interrupted log trees (`btrfs rescue zero-log`) and mount with `clear_cache` automatically.
  - Added panic rescue guidance screen `devos-panic-guide` in `etc/initramfs-tools/scripts/panic/`.
  - Added fast 15-second systemd shutdown configuration in `etc/systemd/system.conf.d/devos-shutdown.conf` to prevent unclean power-off cache issues.
  - Documented troubleshooting and recovery instructions in `README.md` and `docs/BTRFS_RECOVERY.md`.

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
