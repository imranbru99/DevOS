# DevOS current feature inventory

Reviewed against the source tree on **October 22, 2026**. This inventory describes
implemented components and configured installation options. It is not a claim
that every app, hardware device or installation path has been tested. The current
source targets Ubuntu 26.04 LTS (Resolute), amd64. An older published ISO may not
contain these changes.

## Desktop, sign-in and installer

- KDE Plasma with DevOS branding, Windows-style keyboard shortcuts, compact taskbar,
  Sapphire Waves wallpaper and the bundled wallpaper collection.
- SDDM dark sign-in theme: centered account card, date/time, password visibility,
  login failure feedback, account and session selection, restart and shutdown.
- Calamares pages: welcome, location, keyboard, partitions, local account, AI model,
  user type, app selection, summary, progress and finish. An online account is not required.
- Btrfs or ext4 installation, optional LUKS encryption, EFI partition setup,
  Btrfs subvolumes/compression and optional disk swap; zram is the normal swap path.
- Hybrid BIOS/UEFI build and safe-graphics boot option; boot artifact verification
  checks the image structure. Secure Boot requires separate verification of the exact image.
- First-boot dashboard with machine statistics, setup guidance, storage tools and runtimes.

## Everyday tools and hardware

| Area | Implemented tools |
|---|---|
| Files | This PC drive view, quick access, tabs, breadcrumbs, search filter, details/icons, properties, new file/folder dialogs and clipboard file operations. ZIP/7z compression and extraction via context menus. |
| Storage | Disk/partition inspection, unformatted volume discovery, formatting, filesystem diagnostics, Btrfs snapshots and restore tooling. Formatting requires careful target selection. |
| Networking | NetworkManager Wi-Fi/Ethernet, Bluetooth integration, PPPoE Broadband Connection for direct ONU/modem credentials, and duplicate automatic wired-profile prevention. |
| Display | Resolution, refresh and scaling controls; keep/revert workflow. Hardware discovery uses XRandR, so Wayland may require native Plasma display settings. |
| Power | Battery/AC status, efficiency/balanced/performance modes, separate idle timeouts, sleep, lock, restart and shutdown. X11-based idle/display controls are session-dependent. |
| Monitoring | Task Manager with process/performance/startup/service views; Optimizer with friendly application names, idle-memory suggestions, cache cleanup and storage warnings. |
| Productivity | Notepad session recovery, Notes, clipboard history, emoji search, screenshots, voice typing and AI actions on selected text. |
| Media | VLC, image/PDF viewers, SimpleScreenRecorder and FFmpeg in package lists. Other creative apps are selectable downloads. |
| Family | Optional Islamic content, prayer/Qibla tools, Family Safety and a local browser body-region filter. Kids Mode is an escapable full-screen playground, not an account lock. |

## AI, development and connectivity

- Local assistant with conversation history, streaming, system-information answers,
  multi-step app/settings actions, notes, reminders, document reading, OCR and
  English/Bangla voice interaction. Web search and navigation open network services.
- Local OpenAI-compatible API at `http://127.0.0.1:11434/v1`, API documentation,
  optional authenticated LAN sharing and model management. Tiny chat model is the
  build default; larger chat, coding and vision models download separately.
- AI Code Agent with repository context, plans, file diffs, command review, project
  runner/preview, prompt queue, stop, retry and rerun. Local inference is available;
  configured Google Gemini, Groq, DeepSeek and OpenAI-compatible providers send
  prompts and code context to their services. A configured API key can select a
  cloud provider automatically; inspect the active engine before using private code.
- `devos auto` commit-message, review, explanation and summarization helpers;
  separate browser profiles and resource limits for agent browser sessions.
- Git/Git LFS/GitHub CLI, Node/npm, Python/pip/venv/pipx, PHP/Composer, MariaDB,
  PostgreSQL, Redis, SQLite, Podman and terminal tools. PHP follows Ubuntu's package
  version. VS Code and Chrome are fetched during the build, with online helpers
  if they are absent; check a specific image's package manifest for inclusion.
- `devos serve` local project starters and optional online scaffolding for Laravel,
  Next.js, PHP, WordPress and FastAPI; service status and public sharing helpers.
- Phone Link browser pairing and KDE Connect; DevOS Share public tunnels;
  optional Google Drive/OneDrive backups. These network features are distinct from
  local AI processing.
- DevOS Security: ClamAV integration, quarantine, download/USB monitoring,
  look-alike-link checks, DNS/browser policies, firewall, update status and Disk Guard.
- Component updater with release checksums and rollback; Ubuntu release upgrades
  remain a separate interactive operation. Btrfs snapshots are not a substitute
  for an external backup or a guarantee of automatic boot recovery.

## What is bundled and what downloads

**ISO package/component** means the source includes the component or requests its
package in the image. **Download** means the selected app is installed online.
A bundled launcher can still need a runtime, model, account or network connection.
The Android container images download on first setup; Windows applications vary
in Wine compatibility; a Windows VM requires your own ISO and licence.

The installer offers Normal, Professional, Student, Development, Creator, Gamer,
Business, Family, Normal + Islamic and Premium. DevOS Features also supports
Windows-like, Minimal and Choose later. Normal filters heavier apps by hardware;
Premium selects the catalog except opt-in family controls. Presets can be edited.

The following **97 entries** come from
[`components/features/feature_catalog.py`](../components/features/feature_catalog.py).
They list selection options, not 97 preinstalled apps. Some small packages marked
Download may already be present as dependencies; the table follows the catalog's
delivery contract. Check `devos features list` on the installed system for state.

### Office & documents

| Feature ID | Feature | Delivery / requirement |
|---|---|---|
| `onlyoffice` | ONLYOFFICE (Word, Excel, PowerPoint look-alike) | Download from Flathub; catalog recommends 3 GB RAM |
| `libreoffice` | LibreOffice Writer, Calc, Impress | Download from Ubuntu package repositories; catalog recommends 3 GB RAM |
| `wps` | WPS Office | Download from Flathub; catalog recommends 4 GB RAM |
| `officefonts` | Office-compatible fonts | Download from Ubuntu package repositories |
| `msfonts` | Microsoft core fonts (Arial, Times New Roman, Verdana…) | Download from Ubuntu package repositories |
| `pdftools` | PDF tools: merge, split, sign, annotate | Download from Ubuntu package repositories |
| `notes` | Joplin notes | Download from Flathub; catalog recommends 4 GB RAM |
| `obsidian` | Obsidian | Download from Flathub; catalog recommends 4 GB RAM |
| `calendar` | Calendar & reminders | Download from Ubuntu package repositories |
| `mindmap` | XMind mind maps | Download from Flathub; catalog recommends 4 GB RAM |

### Internet & email

| Feature ID | Feature | Delivery / requirement |
|---|---|---|
| `chrome` | Google Chrome | Build-time vendor download; online helper if absent |
| `edge` | Microsoft Edge | Download from Flathub; catalog recommends 4 GB RAM |
| `firefox` | Firefox | Download from Flathub |
| `brave` | Brave | Download from Flathub; catalog recommends 4 GB RAM |
| `thunderbird` | Thunderbird email | Download from Flathub |
| `winapp` | Windows App (Microsoft) | Web-app shortcut; internet/vendor account as needed |
| `m365web` | Microsoft 365 (Word, Excel, PowerPoint online) | Web-app shortcut; internet/vendor account as needed |
| `outlookweb` | Outlook (Microsoft) | Web-app shortcut; internet/vendor account as needed |
| `torrent` | qBittorrent | Download from Ubuntu package repositories |

### Calls & messaging

| Feature ID | Feature | Delivery / requirement |
|---|---|---|
| `whatsapp` | WhatsApp | Download from Flathub |
| `zoom` | Zoom | Download from Flathub; catalog recommends 4 GB RAM |
| `teams` | Microsoft Teams | Download from Flathub; catalog recommends 4 GB RAM |
| `telegram` | Telegram | Download from Flathub |
| `discord` | Discord | Download from Flathub; catalog recommends 4 GB RAM |
| `slack` | Slack | Download from Flathub; catalog recommends 4 GB RAM |
| `signal` | Signal | Download from Flathub; catalog recommends 4 GB RAM |
| `kdeconnect` | Phone integration | ISO package/component |

### Music & video

| Feature ID | Feature | Delivery / requirement |
|---|---|---|
| `vlc` | VLC media player | ISO package/component |
| `spotify` | Spotify | Download from Flathub; catalog recommends 4 GB RAM |
| `webcam` | Camera | Download from Ubuntu package repositories |
| `recorder` | Voice Recorder | Download from Ubuntu package repositories |

### Photo, design & video editing

| Feature ID | Feature | Delivery / requirement |
|---|---|---|
| `paint` | Paint (KolourPaint) | Download from Ubuntu package repositories |
| `gimp` | GIMP | Download from Flathub; catalog recommends 4 GB RAM |
| `krita` | Krita | Download from Flathub; catalog recommends 6 GB RAM |
| `inkscape` | Inkscape | Download from Flathub; catalog recommends 4 GB RAM |
| `kdenlive` | Kdenlive video editor | Download from Flathub; catalog recommends 8 GB RAM |
| `obs` | OBS Studio | Download from Flathub; catalog recommends 6 GB RAM |
| `audacity` | Audacity | Download from Flathub |
| `blender` | Blender | Download from Flathub; catalog recommends 8 GB RAM |
| `handbrake` | HandBrake | Download from Flathub; catalog recommends 4 GB RAM |

### Games

| Feature ID | Feature | Delivery / requirement |
|---|---|---|
| `steam` | Steam | Download from Flathub; catalog recommends 8 GB RAM |
| `heroic` | Heroic (Epic Games, GOG, Amazon) | Download from Flathub; catalog recommends 6 GB RAM |
| `lutris` | Lutris | Download from Flathub; catalog recommends 4 GB RAM |
| `protonup` | ProtonUp-Qt | Download from Flathub |
| `xbox` | Xbox | Web-app shortcut; internet/vendor account as needed |

### Developer tools

| Feature ID | Feature | Delivery / requirement |
|---|---|---|
| `vscode` | Visual Studio Code | Build-time vendor download; online helper if absent |
| `devservers` | Web servers & databases | ISO package/component |
| `postman` | Postman | Download from Flathub; catalog recommends 6 GB RAM |
| `dbeaver` | DBeaver | Download from Flathub; catalog recommends 6 GB RAM |
| `githubdesktop` | GitHub Desktop | Download from Flathub |
| `androidstudio` | Android Studio | Download from Flathub; catalog recommends 16 GB RAM |

### Everyday tools

| Feature ID | Feature | Delivery / requirement |
|---|---|---|
| `calculator` | Calculator | ISO package/component |
| `notepad` | Notepad | ISO package/component |
| `snip` | Snipping Tool | ISO package/component |
| `photos` | Photos | ISO package/component |
| `explorer` | File Explorer | ISO package/component |
| `terminal` | Terminal | ISO package/component |
| `charmap` | Character Map | Download from Ubuntu package repositories |
| `alarms` | Clock & alarms | Download from Flathub |
| `weather` | Weather | Web-app shortcut; internet/vendor account as needed |
| `maps` | Maps | Web-app shortcut; internet/vendor account as needed |
| `onedrive` | OneDrive | Web-app shortcut; internet/vendor account as needed |
| `diskusage` | Disk usage map | Download from Ubuntu package repositories |
| `remote` | Remote desktop (AnyDesk + RustDesk) | Download from Flathub; catalog recommends 4 GB RAM |
| `remmina` | Remote Desktop (Remmina) | Download from Ubuntu package repositories |
| `scanner` | Scanner app | Download from Ubuntu package repositories |
| `timeshift` | System restore points (Timeshift) | Download from Ubuntu package repositories |
| `access` | Accessibility (screen reader, magnifier, on-screen keyboard) | ISO package/component |
| `appstore` | Flatpak app manager (Warehouse) | Download from Flathub |

### Security & privacy

| Feature ID | Feature | Delivery / requirement |
|---|---|---|
| `firewall` | Firewall (on) | ISO package/component |
| `antivirus` | ClamTk virus scanner window | Download from Ubuntu package repositories; catalog recommends 4 GB RAM |
| `passwords` | KeePassXC password manager | Download from Ubuntu package repositories |
| `bitwarden` | Bitwarden | Download from Flathub; catalog recommends 4 GB RAM |
| `fingerprint` | Fingerprint sign-in | ISO package/component |
| `domain` | Company network (Active Directory) | Download from Ubuntu package repositories |

### Language & fonts

| Feature ID | Feature | Delivery / requirement |
|---|---|---|
| `bangla` | Bangla typing (Avro phonetic) | Download from Ubuntu package repositories |
| `notofonts` | Fonts for all languages | ISO package/component |

### Windows & Android apps

| Feature ID | Feature | Delivery / requirement |
|---|---|---|
| `winapps` | Windows apps (.exe, .msi) | ISO package/component |
| `winvm` | Windows virtual machine | Download from Ubuntu package repositories; catalog recommends 8 GB RAM |
| `bottles` | Bottles | Download from Flathub; catalog recommends 4 GB RAM |
| `android` | Android apps (.apk) | Bundled launcher; Android image downloads at setup; catalog recommends 4 GB RAM |

### DevOS tools

| Feature ID | Feature | Delivery / requirement |
|---|---|---|
| `taskman` | Task Manager | ISO package/component |
| `security` | DevOS Security | ISO package/component |
| `devosnotes` | DevOS Notes | ISO package/component |
| `voicetype` | Voice typing (Win+Alt+H) | ISO package/component |
| `aiactions` | AI on any text (Win+Alt+A) | ISO package/component |
| `clipboard` | Clipboard history (Win+V) | ISO package/component |
| `emoji` | Emoji panel (Win+.) | ISO package/component |
| `codeagent` | DevOS AI Code Agent | Bundled app; local model or configured cloud provider; catalog recommends 8 GB RAM |
| `phonelink` | Phone Link | ISO package/component |
| `share` | DevOS Share | ISO package/component |
| `backup` | Cloud Backup | ISO package/component |
| `vault` | DevOS Vault | ISO package/component |
| `restore` | Restore points | ISO package/component |

### Islamic & family

| Feature ID | Feature | Delivery / requirement |
|---|---|---|
| `islamic` | Islamic DevOS: prayer times, Quran & Hadith | Bundled controls; opt in (content may download) |
| `familysafe` | Family Safety: block adult content | Bundled controls; opt in (content may download) |
| `modesty` | Modesty filter: blur adult women body regions | Bundled controls; opt in (content may download); catalog recommends 4 GB RAM |

## Experimental components and release evidence

NPU detection/recommendations, smart-shell diagnostics and semantic-memory search
exist in source but have narrower capabilities than a complete hardware scheduler,
automatic repair shell or secure document vault. See the
[architecture status](MODERN_2027_OS_ARCHITECTURE.md).

A release should publish its ISO SHA-256 and test results separately. Unit tests,
QML previews, boot-layout inspection, a live VM boot and a completed disk installation
exercise different paths; one does not establish the others. The screenshots in
[README](../README.md) are labeled previews or captures from earlier builds.
