# DevOS UI/UX full audit — 2026-11-09

Production-facing audit of installer, Plasma chrome, and first-party apps.
Status values: **done** · **partial** · **blocked** (needs live OS / package QML).

## Screen checklist

### Installer (Calamares branding)

| Screen | Status | Notes |
|--------|--------|-------|
| Welcome | partial | Responsive margins; requirements still generic |
| Locale (stock) | partial | QSS frosted; no custom QML |
| Keyboard (stock) | partial | QSS frosted |
| Partition (stock) | partial | Calamares jargon remains |
| Users | done | pageMargin / pageMaxWidth |
| Data drives | partial | pageMargin; still shows device paths / ext4 |
| DevOS AI | done | pageMargin / pageMaxWidth |
| Voice | done | pageMargin / pageMaxWidth |
| You (PC type) | done | pageMargin |
| Apps | done | pageMargin + softened catalog about text |
| Summary | done | Humanized AI/voice/usertype/apps labels |
| Slideshow | partial | Marketing strings still technical in places |
| Finished (stock) | partial | QSS only |
| Sidebar / Nav | done | Install confirm no longer dismisses on backdrop |
| InstallerAppearance | done | Semantic color + spacing tokens added |

### Desktop chrome

| Surface | Status | Notes |
|---------|--------|-------|
| Color schemes DevOS / DevOS-Light | done | Link AA, frosted tooltip tokens aligned |
| Look-and-feel metadata | done | Light-first description + fallback |
| Theme switcher CLI | done | No user-facing “Plasma”; mac-light LNF safe |
| Panel height fallback | done | apply-ui.js 48px |
| Context menus (Tooltip) | done | Tokens; live visual QA blocked |
| System Settings QML debrand | partial | Script exists; live kcm patch blocked off-ISO |
| Custom plasma desktoptheme | blocked | Still Breeze shell theme |

### PyQt / first-party apps

| App | Status | Notes |
|-----|--------|-------|
| Shared `devos_appearance` | done | Frosted light tooltips; mirror synced |
| Features GUI | done | Already adapt_stylesheet |
| Models GUI | done | Already adapt_stylesheet |
| Security Center | done | adapt_stylesheet at init |
| Apps Manager | done | adapt via app stylesheet |
| About this PC | done | Friendlier nav + adapt |
| Task Manager | done | Emoji nav → text; adapt |
| Optimizer cleanup | done | adapt_stylesheet |
| Assistant | partial | Appearance install only; large STYLE remains |
| Dashboard | partial | CSS themes OK; chat.html dark-only |
| File Explorer | partial | Chroot-only source; not moved this pass |
| Power settings | partial | components-only; dark-authored |
| First-boot wizard | partial | CLI vs dashboard Setup still split |

## Design direction (locked)

- Brand: cyan accent on dark graphite (`#38bdf8`), blue selection (`#2563eb`), light daylight surfaces with deeper link blue (`#1d4ed8`).
- Light transient chrome (menus/tooltips): frosted dark slate — matches desktop context menus.
- Avoid purple SaaS gradients, cream/terracotta brochure, broadsheet layouts.

## Verification during the redesign

- **Unit tests:** not executed — no Python interpreter available on this Windows host (store stub only; winget install blocked).
- **Static checks run:** color-scheme link/tooltip tokens, appearance↔chroot mirror hashes, theme_switcher debrand + LNF fallbacks, summary humanizers, install-confirm backdrop guard, panel height 48, feature about-text sanitization.
- Live Plasma/installer visual QA was **not** performed in this environment.

## Release image checks

- 66 targeted Linux tests passed for installer, boot, storage, branding, and
  contrast. The broader test suite still has failures and unmet test dependencies.
- 12 application windows were opened in light and dark configurations. The
  follow-up run verified the Security Center shutdown, Task Manager sizing,
  and Features process cleanup fixes.
- All 28 Flagship wallpaper packages and their 308 PNG assets passed metadata
  and image checks. The release image includes all 28 packages.
- The final image passed 38 boot-layout checks and reached the DevOS boot menu
  in BIOS and UEFI USB QEMU runs. The offline BIOS guest continued through
  DevOS Motion and the live chooser to the Calamares Welcome screen.
  The VM had no installation disk attached.
- The corrected live chooser was rendered in 640, 800, 1024, and 1280 pixel
  windows. The content fit its viewport and all four cards fit their wrapped text.
