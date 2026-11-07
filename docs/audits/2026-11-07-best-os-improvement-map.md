# DevOS improvement map — 2026-11-07

Prioritized after shipping tray overflow, theme Chrome-crash hardening, HiDPI,
Windows App PWA, hang-soak, pipeline abort, and first-boot tips.

## Done in this pass

- Installer / Features: **Cursor Agent**, **Antigravity**, **Antigravity KDE**
  (and Codex CLI) have real install scripts + detect paths + pipeline discovery.
- Local **DevOS AI Code Agent**: `probe_site` for large-site evidence (HTTP/DOM/assets).
- Live deploy: install scripts + ThemeSwitcher under `/usr/local`.
- Signed updates: pinned `update-pubkey.pub`, `package-update --sign-key`, CI uploads `.sig`.
- CI boot gate: fail-closed live BIOS/UEFI serial markers + USB GRUB assert.
- ext4 recovery: SnapshotManager Timeshift backend; Timeshift on ISO package list;
  apt pre-upgrade hook uses Timeshift when root is not btrfs.
- Single Files identity: MIME + Meta+E → DevOS Files; Dolphin NoDisplay.

## Next (highest ROI)

| # | Item | Impact | Effort |
|---|---|---|---|
| 1 | Add `DEVOS_UPDATE_SIGN_KEY_B64` to GitHub repo secrets (ops) | High | S |
| 2 | Theme bus: refresh stock KDE apps without Chromium `notifyChange` crash | High | M |
| 3 | CI install → reboot → first-boot desktop marker (Phase C) | High | L |
| 4 | Heavy-load oomd / io.weight policy activated with soak evidence | Med–High | M |
| 5 | First-boot checklist tied to Calamares AI/apps/FS choices | Med | M |
| 6 | LTS upgrade path past 26.04 | High (long-term) | L |
| 7 | Hardware / Secure Boot / LUKS / dual-disk qualification matrix | High (claim) | L |
| 8 | Hide duplicate stock apps (Kate vs Notepad, Gwenview vs Photos) | Med | S |

## Local agent follow-ups

- Wire puppeteer-core optional for richer console/network capture.
- Auto-probe detected preview URL after `artisan serve` / `npm run dev`.
- Route-scoped multi-pass map for repos >1k files.
