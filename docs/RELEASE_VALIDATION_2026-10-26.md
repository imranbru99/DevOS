# DevOS release validation — October 26, 2026

Developer: Imran Ahmed <me@imrandev.bd> — https://imrandev.bd.

Runtime source commit: `528249e` (native authentication styling), preceded by
`c9fc92d` (font migration) and `0942347` (installer, dialogs, pipeline and guides).

ISO: `devos-26.04-amd64-final.iso` — 4,443,578,368 bytes (4.44 GB / 4.14 GiB).
SHA256: `54fc9ef8d6d741b45f3f65c73f5f7d1e853dc35576ee99acc66442519f89d115`.

## Completed checks

- 137 focused tests passed: installer/storage protections, updater rollback and
  allowlists, optimizer/cache care, responsiveness, AI queue and packaged binary integrity.
- Native Qt confirmation/input rendering checked; Cancel stays the default and
  password echo masking is preserved.
- Actual KDE/Polkit dialog in the installed disposable VM: wrong password rejected,
  cancellation prevented the command, correct disposable test password authenticated
  `/usr/bin/true` successfully (exit 0). The backend remains the packaged KDE/Polkit/PAM
  implementation. Custom controls are QML styling, not binary string replacements.
- Font migration exercised with real KDE configuration tools: exact old defaults
  updated, custom font preserved, second run unchanged. Installed login migration
  completed and Inter 10 was retained.
- Build compared packaged ELF executables/libraries with dpkg checksums and ran
  `sfdisk`, `gawk`, `nmcli`, `mkswap` smoke checks. No mismatches remained. The final
  live system's readline library matched its package checksum.
- ISO boot layout: 34 checks passed, zero failures.
- The exact final image booted through its UEFI USB loader to the installer.
  Its native authentication service started through the DevOS wrapper; the
  shipped style file hash matched the source.
- Full UEFI installation and installed UEFI desktop boot passed on disposable
  64 GiB system + 64 GiB data disks before the authentication-only styling revision.
  The installer/storage sources are unchanged in the final style revision.
  Layout: GPT, 512 MiB FAT32 EFI, ext4 root; additional A/B/C ext4 data volumes.
  New data volumes: owner 1000:1001, mode 750, actual user write/remove checks passed.
  Home, .config, .cache, .local and .local/share were writable after installed boot.
  Root was ext4 read/write, display manager active, no failed system services.
- Root Snapper template was removed for ext4; no failing Btrfs snapshot boot job.
- Earlier BIOS installation/boot and constrained OOM workload isolation were also
  tested during this development run; these are not physical-hardware certification.
- 252 wallpaper images passed Pillow file verification. Five real FFmpeg edit/export tests
  passed earlier in the build runtime; live microphone/Wayland capture was not
  exercised on physical hardware.
- Local component bundle validated with 227 files, including the native style,
  wrapper and reviewed service override. No stable GitHub release was published.

## USB verification

The final ISO was written to the selected removable USB and flushed. Read-back
of all 4,443,578,368 image bytes matched SHA256
`54fc9ef8d6d741b45f3f65c73f5f7d1e853dc35576ee99acc66442519f89d115`.
The host computer was not rebooted. Physical boot-menu selection remains a user step.
Only the latest ISO and its checksum remain in `out`; disposable VM disks were removed.

## Boundaries

This is VM and build validation, not a guarantee of ten-year support, zero hangs,
all-hardware compatibility, or universal Windows/Android app compatibility.
Physical Secure Boot, physical audio capture, GPU/firmware combinations and external
AI-provider account dispatches still require their own validation. Restarts,
security updates, backups and supported base upgrades remain part of maintenance.

## Implementation references

- [Qt supported custom styles](https://doc.qt.io/qt-6/qtquickcontrols-customize.html#creating-a-custom-style)
- [KDE native authentication UI](https://github.com/KDE/polkit-kde-agent-1/tree/Plasma/6.6)
