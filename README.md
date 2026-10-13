<p align="center">
  <img src="build/includes.chroot/etc/calamares/branding/devos/logo.png" width="120" alt="DevOS logo">
</p>

<h1 align="center">DevOS</h1>

<p align="center">
  <b>One fast desktop for your Linux, Windows and Android apps — with a private AI assistant built in.</b><br>
  Based on Ubuntu 24.04 LTS · Open source (MIT) · Made by <a href="https://imrandev.bd/">Imran Ahmed (Imran Dev)</a>
</p>

<p align="center">
  <a href="https://drive.google.com/drive/folders/1RHM8niXwkPsqzOkiMxxp4tpf41bnyJ01?usp=sharing">
    <img src="https://img.shields.io/badge/%E2%AC%87%EF%B8%8F_Download_DevOS_ISO-3.3_GB_(Google_Drive)-2563eb?style=for-the-badge&logo=googledrive&logoColor=white" alt="Download DevOS ISO">
  </a>
</p>

---

## Our aim

DevOS exists to give people — especially Windows users and developers — **an operating system that feels familiar on day one, stays fast on ordinary laptops, and respects their privacy**:

- **Run what you already use.** Double-click a Windows `.exe`, an Android `.apk` or a Linux app and it opens. When a better native version of the app exists, DevOS offers it.
- **Stay fast on modest hardware.** A 3.3 GB ISO, a small on-device AI that gives its memory back when idle, compressed memory and storage, and a built-in optimizer.
- **AI that works for you, privately.** DevOS AI runs entirely on your PC: it answers questions about your computer, does things for you (open apps, search, save notes, set reminders…), reads PDFs and images, and understands your voice in Bangla and English — nothing is sent to the cloud.
- **Premium, simple, and yours.** A polished dark design, one-click install with no account required, and no telemetry.

---

## Highlights

| | |
|---|---|
| 🪟 **Windows apps** | `.exe` / `.msi` open with a double-click (32- and 64-bit). Popular apps such as AnyDesk, Zoom, Discord, Spotify and Steam get their **native DevOS version** offered instead. |
| 🤖 **Android apps** | `.apk` files install into a built-in Android system (downloaded once on first use, ~850 MB). WhatsApp, Telegram, Spotify and similar APKs are offered as native DevOS apps — no Android download needed. |
| ✨ **DevOS AI** | Private on-device assistant: PC questions, actions, notes, web search, reminders, PDFs, text-in-images, photos, voice (Bangla + English), **Meta+H** push-to-talk and optional **“Hey DevOS”**. |
| 🧹 **DevOS Optimizer** | Finds apps you haven't used for 15+ minutes and offers to close them; cleans temp files, caches, the Recycle Bin and Windows-app leftovers. |
| 📦 **Apps window** | Windows-style *Installed apps*: uninstall Linux, Windows and Android apps, clear cache, reset data and browser cookies. |
| 📝 **Notepad** | Windows 11-style tabs; **unsaved text survives crashes and power cuts**. |
| 💻 **Developer ready** | VS Code, Git, Node.js, Python, PHP + Composer, MariaDB, PostgreSQL, Redis, SQLite, Podman (Docker-compatible). |
| 🎨 **Premium look** | Dark DevOS theme, icons-only taskbar, **21 wallpapers**, a modern installer, DevOS names everywhere (Files, Terminal, Settings…). |
| ⚡ **Small & fast** | 3.3 GB ISO, boots straight to the desktop, compressed RAM swap, btrfs + zstd storage, memory-hog protection. |

---

## What you get

### 1. Installer
- Modern full-screen installer: welcome page, location, keyboard, disk, account, summary, progress.
- **Erase disk** creates an EFI partition plus a btrfs system (subvolumes for `/`, `/home`, `/.snapshots`, `/var/log`, `/var/cache`; zstd compression). Manual partitioning and full-disk encryption (LUKS) are available too.
- **The account is optional.** Name, sign-in name and computer name are pre-filled; leave the password empty and DevOS signs in automatically (you can add a password later).
- Boots on **UEFI and legacy BIOS** PCs, from USB or DVD. After install it starts **straight to the desktop** — no boot menu wait (the menu still appears when Windows is installed alongside).

### 2. Desktop that feels like Windows
- Start menu with the DevOS logo, **icons-only taskbar** (many apps fit; windows of one app are grouped), system tray and clock.
- Desktop shortcuts: Apps, Chrome, DevOS AI, DevOS Code, Documents, Notepad, Settings, Terminal, This PC, VLC and more.
- **Windows keyboard shortcuts**

  | Keys | Action |
  |---|---|
  | `Win` | Start menu |
  | `Win + E` | Files (file explorer) |
  | `Win + D` | Show desktop |
  | `Win + R` | Run / search |
  | `Win + L` | Lock |
  | `Win + Shift + S` | Screenshot of a region |
  | `Win + ← → ↑ ↓` | Snap / maximise / minimise windows |
  | `Win + H` | **DevOS AI voice command** |

- **21 wallpapers**: the DevOS default plus 20 premium designs (Aurora Veil, Silk Current, Nebula Drift, Glass Horizon…), with previews in *Configure Desktop and Wallpaper*. See [`tools/wallpapers/preview.jpg`](tools/wallpapers/preview.jpg).
- Everything is called **DevOS**: the sign-in session, “About this PC”, and apps named by what they do — *Files, Terminal, Text Editor, Photos, Document Viewer, Settings, Task Manager*.

### 3. Run any app

#### Windows programs (`.exe`, `.msi`)
- Double-click to run. Each app gets its own isolated Windows environment, prepared **silently** the first time (no technical pop-ups) and copied instantly for every new app on btrfs.
- 32-bit installers (most setup files) and 64-bit programs are supported.
- **Native versions first:** for AnyDesk, Zoom, Discord, Spotify, Telegram, WhatsApp, Steam, OBS, Slack, Firefox, Brave, GIMP, Blender, Audacity, LibreOffice, Postman and TeamViewer (Remmina), DevOS offers to install the **DevOS (native) version** from Flathub — faster and fully featured (e.g. AnyDesk's remote control only works natively). You can still run the Windows version.

#### Android apps (`.apk`)
- Double-click an APK: on first use DevOS asks once to download the Android system (~850 MB, shown with a real progress bar, resumable and checksum-verified), then installs and opens the app in a **DevOS Android** window. Installed apps appear in the app menu.
- Works on Intel and AMD graphics; other GPUs and virtual machines automatically use software rendering.
- Popular apps with native versions (WhatsApp, Telegram, Spotify, Discord, Zoom…) skip the Android download entirely.

#### Linux apps
- Thousands of apps from **Flathub** (preconfigured), plus `.deb` packages and AppImages.

#### Apps window — uninstall and clean
- One list of every installed app (Linux, Windows, Android) with search, sort by size and type filter.
- **Uninstall**, **Clear cache**, and **Reset data & cookies** (for browsers: cookies and cache, optionally history, passwords and bookmarks). System parts are protected from removal.
- Right-click any app shortcut → **Uninstall…**

### 4. DevOS AI — your private assistant
Open **DevOS AI** from the desktop, or press **Win + H** and just speak.

**Ask about your PC** — “What's my PC config?”, “How much RAM?”, “How many apps are installed?” — answered from real system data, not guesses.

**Tell it what to do** (typed or spoken, typos are fine):

| Say or type | DevOS AI does |
|---|---|
| “Go to Chrome and search HP latest laptop” | Opens Chrome with that Google search |
| “Play lo-fi music on YouTube” / “Directions to Dhaka airport” | YouTube / Maps search |
| “Open Notepad and save my name Imran Ahmed, number 0151…” | Saves a note in *Documents/Notes* and opens it |
| “Take a note: buy milk, eggs and bread” | Same, as a note |
| “Remind me in 10 minutes to call mom” / “Set a timer for 5 minutes” | Desktop reminder, even if the window is closed |
| “Send an email to x@y.com about the meeting” | Opens a ready email draft (never sends by itself) |
| “Open my Downloads” / “Make a folder called Projects on the desktop” | Files and folders |
| “Open Wi-Fi settings”, “Volume up”, “Brightness down”, “Take a screenshot”, “Lock the screen” | Settings and system actions |
| “Close Chrome”, “Free up space”, “Open Apps” | App and cleanup actions |

Shut down, restart and uninstall always ask for confirmation first.

**Documents & images**
- Attach a **PDF**, Word file or text file and ask “Summarize this” or a question about it.
- **Read text in images** (English + Bangla) instantly, no download.
- **Describe photos** (“What's in this picture?”) with an optional one-time 296 MB download.

**Voice**
- Offline speech recognition for **Bangla and English** (included in the ISO).
- **Win + H**: speak a command; a small pill shows what was heard and the result.
- **“Hey DevOS”** hands-free mode (off by default, one switch in the sidebar), with battery and CPU guards and a tray icon to pause it.

**Experience**
- Modern chat window: conversation history sidebar with search, rename and delete; answers stream in word by word; Stop button; copy and regenerate; drag-and-drop files.
- **Fast and light:** the built-in model is small (0.5B, ~490 MB); the first words usually appear in under a second, and its memory is **released after 5 idle minutes**.
- **Smarter DevOS AI:** one click adds a larger model (1.1 GB) for better free-form answers; one click removes it again.
- **Private:** runs only on your PC; chats, files and voice never leave it.
- Also available to apps: an OpenAI-compatible local API at `http://127.0.0.1:11434/v1` (used by DevOS Code's AI features).

### 5. DevOS Optimizer
- Tray app that watches for apps you haven't used for 15+ minutes and that use a lot of memory, and offers **Close / Keep / Don't ask again** (never touches system processes).
- **Clean up**: temporary files, app and browser caches, Recycle Bin, Windows-app temp files, old crash logs, and (optionally) old downloads — with sizes shown first and a confirmation.
- Low disk space warnings, and an **Ask DevOS AI** button for tips based on what's using your PC.

### 6. Notepad
- Tabs, find & replace, go to line, zoom, word wrap, line/column status bar — like Windows 11 Notepad.
- **Never lose text:** every tab (including unsaved *Untitled* ones) is saved automatically and restored after a crash, a forced close or a power cut.

### 7. For developers
- **VS Code** (“DevOS Code”) with DevOS AI wired in for offline chat and autocomplete; Copilot cloud chat is switched off.
- Git, Git LFS, GitHub CLI, Node.js + npm, Python 3 + pip/venv/pipx, PHP 8.3 (FPM + common extensions) + Composer, MariaDB, PostgreSQL, Redis, SQLite, Podman / podman-compose (Docker-compatible), Neovim, tmux, ripgrep, fzf, btop, jq.
- `devos serve` scaffolds Laravel, Next.js and FastAPI projects and shows the status of local services.

### 8. Performance and reliability
- **zram** compressed swap in RAM (zstd, 50%) and tuned kernel settings for heavy loads.
- **earlyoom + systemd-oomd** stop runaway programs before the desktop freezes.
- **btrfs with zstd compression** saves disk space and is snapshot-ready (Snapper installed).
- Unneeded services (snapd, apport, telemetry) are removed or masked; boots straight to the desktop.

### 9. Hardware
- Wi-Fi and Ethernet (NetworkManager), Bluetooth, PipeWire audio, printers and scanners (CUPS / IPP), Intel and AMD graphics (Mesa + Vulkan), NVIDIA via the driver manager, broad firmware support.

---

## System requirements

| | Minimum | Recommended |
|---|---|---|
| Processor | 64-bit (x86-64), 2 cores | 4+ cores |
| Memory | 4 GB | **8 GB** (for Android apps + AI + browser at the same time) |
| Storage | 30 GB | 64 GB+ SSD |
| Firmware | UEFI or legacy BIOS | UEFI |
| Graphics | Any | Intel or AMD (hardware-accelerated Android apps) |

---

## 💿 Download ISO & Easy Installation Guide (For Everyone)

You do **not** need to be a developer or Linux expert to install and run DevOS. Follow these 4 easy steps:

---

### Step 1: Download the DevOS ISO File
- 🔗 **Google Drive Direct Download:** [**Click here to Download DevOS ISO (Google Drive)**](https://drive.google.com/drive/folders/1RHM8niXwkPsqzOkiMxxp4tpf41bnyJ01?usp=sharing)
- **File size:** ~3.3 GB
- **What you need:** A USB flash drive (8 GB or larger). *Note: Back up any important files on the USB drive, as flashing will erase it.*

---

### Step 2: Make a Bootable USB Flash Drive (Takes ~3 minutes)

Choose whichever tool is easiest for you:

#### Option A: Rufus (Easiest for Windows users)
1. Download [Rufus](https://rufus.ie/) (free, portable application — no installation required).
2. Insert your USB flash drive into your computer.
3. Open Rufus:
   - Under **Device**, select your USB drive.
   - Under **Boot selection**, click **SELECT** and choose the downloaded `devos-24.04-amd64.iso` file.
   - Click the **START** button at the bottom.
   - If a prompt asks for write mode, choose **"Write in DD Image mode"** and click **OK**.
4. Wait until the progress bar reaches 100% and displays **Ready**.

#### Option B: balenaEtcher (Windows, Mac, or Linux)
1. Download and install [balenaEtcher](https://etcher.balena.io/) (free).
2. Open balenaEtcher and plug in your USB drive.
3. Click **Flash from file** and select the downloaded `devos-24.04-amd64.iso`.
4. Click **Select target** and pick your USB stick.
5. Click **Flash!** and wait for verification to complete.

*(Advanced Linux/macOS users can also use `sudo dd if=devos-24.04-amd64.iso of=/dev/sdX bs=4M status=progress oflag=sync`)*

---

### Step 3: Boot your PC from the USB

1. **Turn off Secure Boot** in your PC's BIOS / UEFI settings:
   - Restart your computer and press the BIOS key right as it powers on (usually **F2**, **F12**, **Del**, or **Esc** depending on your computer brand).
   - Navigate to the **Security** or **Boot** tab, set **Secure Boot** to **Disabled**, then save and exit.
2. **Open the Boot Menu**:
   - Turn on your computer and immediately tap your brand's Boot Menu key:
     - **Dell / Lenovo:** `F12`
     - **HP:** `F9` or `Esc`
     - **Asus / Acer:** `F8` or `F12`
     - **MSI / Gigabyte:** `F11` or `F12`
   - Select your **USB drive** from the list and press **Enter**.

---

### Step 4: Try or Install DevOS

- **Try it first without touching your hard drive (Live Session):** DevOS boots directly to the desktop. You can test Wi-Fi, audio, the browser, and DevOS AI risk-free before installing anything.
- **Install permanently to your PC:**
  1. The **DevOS Installer** opens automatically on the desktop.
  2. Follow the friendly prompts: **Welcome → Location & Language → Keyboard → Partitions**.
  3. Under *Partitions*, select:
     - **Erase disk:** Best for a clean system; sets up high-speed compressed storage automatically.
     - **Install alongside:** Keeps your existing Windows installation intact and lets you choose your OS at startup.
  4. Create your account name (password is optional; if left blank, DevOS signs in automatically).
  5. Click **Install**. The setup completes in about 5–8 minutes.
  6. When finished, restart your PC and remove the USB drive when the screen turns off.

---

### 🧪 Try it first in Docker (Windows, Docker Desktop)
Want to test DevOS right from your existing Windows desktop without restarting?
```bash
powershell -ExecutionPolicy Bypass -File .\tests\docker-vm\run-devos-vm.ps1 -Reset
```
Then open **http://localhost:8006** in your browser. The VM uses a virtual disk (`tests/docker-vm/storage`) — your real hard drives are untouched. See [`tests/docker-vm/README.md`](tests/docker-vm/README.md).

---

## Build the ISO from source

Requirements: Docker (Linux or Docker Desktop) or an Ubuntu 24.04 host, ~25 GB free space, internet.

```bash
git clone https://github.com/imranbru99/DevOS.git
cd DevOS
make iso-docker          # containerized build -> out/devos-24.04-amd64.iso
```

Manual container build (keeps a reusable build cache so rebuilds take ~25 minutes):
```bash
docker build -t devos-builder -f build/docker/Dockerfile.build .
docker run --rm --privileged \
  -e DEVOS_WORK_DIR=/build_work -e DEVOS_ZSTD_LEVEL=19 \
  -v devos-work:/build_work -v "$PWD:/workspace" -w /workspace \
  devos-builder ./build/build-iso.sh
```

Useful options: `DEVOS_ISO_NAME` (output file name), `DEVOS_ZSTD_LEVEL` (15 = faster build, 19 = smaller ISO), `UBUNTU_MIRROR`. The build fails on purpose if the ISO exceeds 4 GB or if any system file is world-writable.

**Tests**
```bash
python3 -m unittest discover -s tests/unit
```

---

## Command line

```bash
devos app install <file.exe|file.apk|file.deb>   # install / run any app
devos app search <name>                          # search the app catalog
devos win launch <app.exe>                       # run a Windows program
devos win doctor <app.exe>                       # compatibility check
devos android setup                              # one-time Android download
devos android install <app.apk>                  # install an Android app
devos serve new myapp --stack laravel            # scaffold a project (laravel | nextjs | fastapi)
devos serve status                               # local developer services
devos ai "find files larger than 100MB"          # system assistant
devos net | devos sound | devos driver | devos disk   # network, audio, drivers, storage
devos watchdog --check-pressure                  # memory pressure check
```

---

## Repository layout

```
DevOS/
├── build/
│   ├── build-iso.sh                 # Builds the hybrid BIOS + UEFI ISO
│   ├── docker/Dockerfile.build      # Reproducible build container
│   ├── package-lists/               # Packages (base, hardware, desktop, apps, installer, developer, Wine, Android)
│   ├── hooks/                       # Clean-up, services, performance, branding
│   └── includes.chroot/             # Files placed into the system (installer branding, desktop, scripts)
├── components/
│   ├── assistant/                   # DevOS AI app: chat window, commands, voice, documents, photos
│   ├── ai-core/                     # Local AI service (OpenAI-compatible API on 127.0.0.1:11434)
│   ├── apps/                        # Apps window (uninstall, cache, cookies)
│   ├── optimizer/                   # DevOS Optimizer (idle apps, clean-up)
│   ├── notepad/                     # Notepad with crash-proof sessions
│   ├── apphub/                      # App routing, safety scan, native-version catalog
│   ├── winlayer/                    # Windows programs
│   ├── androidlayer/                # Android apps
│   ├── devserver/ code-agent/ ai-agent/ settings/ dashboard/ first-boot/ linuxlayer/
│   └── devos_cli.py                 # `devos` command
├── tests/
│   ├── unit/                        # Automated tests
│   └── docker-vm/                   # Run the ISO in Docker Desktop
├── tools/wallpapers/                # Wallpaper generator + preview
└── docs/                            # Guides (coming from Windows, compatibility, performance…)
```

---

## Known limitations

- **Secure Boot** must be off to boot the USB stick.
- **Android apps** need the one-time ~850 MB download and an installed system (not the live USB). Apps that require Google Play services, or that only contain ARM code, may not run.
- **Windows apps:** most everyday programs work; games with kernel anti-cheat, drivers and some remote-control tools don't (DevOS offers native versions where they exist).
- **DevOS AI's built-in model is small:** great for commands and PC questions, simpler for open conversation — turn on *Smarter DevOS AI* for better answers. Voice recognition quality depends on your microphone.
- Window title bars still show some programs' own names.
- Google Chrome asks you to accept Google's terms on first launch.

## Roadmap

- Signed boot loader for Secure Boot
- NPU / GPU acceleration for DevOS AI on supported laptops
- ARM-app translation and optional app store for Android
- Wayland session with native multi-window Android apps
- Automatic system snapshots before updates
- More native-version matches and one-click app catalog

---

## Privacy & licensing

- **No telemetry.** DevOS AI, voice and document features run locally; nothing is uploaded.
- DevOS's own code is released under the **MIT License** ([`LICENSE`](LICENSE)).
- DevOS includes open-source components under their own licenses (Ubuntu packages, KDE Plasma, Calamares, Wine, Waydroid, llama.cpp, whisper.cpp, and the open-weight Qwen2.5 and SmolVLM models), plus **Google Chrome** and **Microsoft Visual Studio Code**, which are distributed under their vendors' terms. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and [`LICENSES/`](LICENSES/).
- DevOS is not affiliated with Microsoft, Google or Canonical. The Android system is open-source LineageOS without Google services.

---

## 🤝 Let's Connect & Collaborate

DevOS is created and maintained by **Imran Ahmed (Imran Dev)**. Contributions, issues and ideas are welcome on [GitHub](https://github.com/imranbru99/DevOS).

I am open to **Senior Remote Full-Stack Roles, AI Platform Architecture Contracts, and Enterprise Technical Advisory**.

- **Timezone:** UTC+6 (Dhaka / Rangpur, Bangladesh) — Flexible overlap with US, UK, and European business hours.
- **Delivery Mode:** Async-ready, Slack, Discord, Jira, GitHub, and production-first accountability.

| Channel | Address / Handle | Quick Action |
|---|---|---|
| 🌐 **Primary Portfolio** | [imrandev.bd](https://imrandev.bd/) | [Visit Site ↗](https://imrandev.bd/) |
| 📦 **Packagist Packages** | [packagist.org/packages/imrandevbd/](https://packagist.org/packages/imrandevbd/) | [View Packages ↗](https://packagist.org/packages/imrandevbd/) |
| 💼 **LinkedIn Profile** | [linkedin.com/in/imranbru99](https://linkedin.com/in/imranbru99) | [Connect ↗](https://linkedin.com/in/imranbru99) |
| 🐙 **GitHub Profile** | [github.com/imranbru99](https://github.com/imranbru99) | [Follow ↗](https://github.com/imranbru99) |
| 💬 **WhatsApp Direct** | [+880 1576-918420](http://wa.me/+8801576918420) | [Chat Now ↗](http://wa.me/+8801576918420) |
| 📧 **Direct Email** | [me@imrandev.bd](mailto:me@imrandev.bd) | [Send Email ↗](mailto:me@imrandev.bd) |
| 🐦 **X (Twitter)** | [@imrandev_bd](https://x.com/imrandev_bd) | [Follow ↗](https://x.com/imrandev_bd) |
| 📺 **YouTube Tech** | [@ImranDevBD](https://youtube.com/@ImranDevBD) | [Subscribe ↗](https://youtube.com/@ImranDevBD) |

---

**DevOS** © 2026 Imran Ahmed. Released under the [MIT License](LICENSE).
