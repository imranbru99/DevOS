# DevOS 26.04 — Cloud PC, app identity and migration follow-up

Developer: Imran Ahmed <me@imrandev.bd> — https://imrandev.bd

This follow-up supersedes the earlier ISO checksum in
`RELEASE_VALIDATION_2026-10-26.md`.

- ISO: `out/devos-26.04-amd64-final.iso`
- Size: 4,422,815,744 bytes (4.42 GB / approximately 4.12 GiB).
- SHA256: `586e99b96a15d716901ca1631332024c77a48865bad86b30754629815098aca7`
- Runtime source commit: `26c340a`.

## Changes

The Windows App companion provides a configurable local inactivity reminder,
actionable Open Windows App notification, pause/reset controls and a tray menu.
It uses Microsoft's existing browser app. It does not observe remote activity,
change provider policy, or generate synthetic activity. Existing recognized vendor
shortcuts are routed through the companion; unrelated shortcuts are preserved.

Qt entry points connect application identity to desktop metadata and load their
individual icons. Twelve additional SVG icons replace generic icons for common
DevOS tools. Native dialogs inherit the application icon. The component bundle
includes reviewed DevOS desktop files and icons so installed systems receive them.

The Ubuntu audit replaced Python 3.12-specific executable matching, added KDE 6
wallet-module defaults and protected core packages, and fixed the preserved
upstream identity. The builder repairs contaminated identity using signed
`base-files`, then validates Ubuntu ID, version and codename before packing.
The resulting upstream identity is Ubuntu 26.04.1 / Resolute; active APT sources
contain no Noble/Jammy suites. Build-only pip downloads are removed. Intentional
24.04 upgrade compatibility and Qt5 application dependencies remain.

## Validation

- 223 focused unit tests passed: assistant 143, apps manager 34, updater 16,
  install branding 10, reminder/identity/migration 9, feature notice 5, features 6.
- Python compilation, shell syntax and Git whitespace checks passed.
- All 16 DevOS SVG app icons rendered through Qt's icon plugin.
- Offscreen Qt application name/icon checks passed for representative apps.
- Windows App companion layout rendered and inspected at 600 × 650 pixels.
- Local update bundle validated: 484 files. No GitHub release asset was published.
- Final rootfs package binary integrity and command smoke checks passed.
- All 34 ISO boot-layout checks passed.
- Exact ISO booted as a virtual USB with UEFI/KVM and reached the branded installer.

This follow-up did not repeat the previous complete installation tests. It does
not certify every physical device, Secure Boot setup, or Microsoft account/session.
The Windows App timer is tested locally; no logged-in Cloud PC session was used.
