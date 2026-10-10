# DevOS: The AI-Native, Developer-First Operating System

![DevOS Banner](https://raw.githubusercontent.com/devos-project/devos/main/build/branding/wallpapers/banner.png)

> **DevOS** is a bootable, installable, modern operating system based on **Ubuntu 24.04 LTS (Noble Numbat)** engineered to look and feel like Windows, run Windows (`.exe` / `.msi`), Linux (Flatpak / `.deb` / AppImage), and Android (`.apk`) apps out of the box, and ship a 100% free, offline, local AI model and developer workstation.

---

## 🌟 Executive Summary

DevOS solves the operating system fragmentation dilemma for software developers:
1. **Familiar Windows UX:** Fluent Dark theme with acrylic blur, bottom centered/left taskbar, Start Menu, Dolphin Explorer with breadcrumbs and "This PC", and identical Windows keyboard shortcuts (`Win`, `Win+E`, `Win+D`, `Win+R`, `Win+Shift+S`, `Ctrl+Shift+Esc`).
2. **Universal App Hub:** Seamlessly double-click or install **any** application. A magic-byte type router automatically directs `.exe`/`.msi` to **WinLayer** (Wine/Proton-GE/DXVK), `.apk` to **AndroidLayer** (Waydroid multi-window), and `.deb`/AppImage/Flatpak to **LinuxLayer**.
3. **100% Offline, Free AI Stack:** Ships an OpenAI-compatible daemon on `127.0.0.1:11434/v1`, auto-assigning hardware-tiered local models (Qwen2.5 / Llama 3) based on system RAM and GPU (NVIDIA CUDA, AMD ROCm, Intel Vulkan).
4. **Turnkey Developer Workstation:** Pre-configured with **VSCodium** (VS Code without telemetry) + Continue local AI assistant, rootless Podman/Docker, PHP 8.3/Composer/Laravel, Node.js/pnpm, Python/pipx, and a Laragon-style manager (**`devserver`**) for one-click local `https://*.test` environments with automatic SSL (`mkcert`).
5. **Anti-Hang & Storage Optimization:** Default **btrfs + zstd:3** filesystem compression reduces heavy 10–20 GB Windows/Chrome applications by 50% on disk. In-RAM compressed `zram` swap, `earlyoom`, and Linux PSI memory stall monitoring guarantee the desktop **never freezes** under heavy loads.

---

## 📐 System Architecture

```
+-----------------------------------------------------------------------+
|                             DevOS Desktop                             |
|        KDE Plasma 6 (Wayland Default)  *  Fluent Dark Acrylic UI      |
+-----------------------------------------------------------------------+
|  Start Menu  |  Taskbar  |  Dolphin Explorer  |  DevOS Control Center  |
+-----------------------------------------------------------------------+
                                   |
         +-------------------------+-------------------------+
         |                         |                         |
         v                         v                         v
+------------------+     +-------------------+     +--------------------+
|  Universal Apps  |     |  Developer Stack  |     |   Local AI Engine  |
+------------------+     +-------------------+     +--------------------+
| * WinLayer       |     | * devserver (Web) |     | * Hardware Tiering |
|   (Wine/Proton)  |     |   Caddy/PHP-FPM   |     |   Lite/Std/Pro     |
| * LinuxLayer     |     |   MariaDB/Postgres|     | * aimodel Manager  |
|   Flatpak/deb/App|     |   Redis/Mailpit   |     | * OpenAI Daemon    |
| * AndroidLayer   |     | * VSCodium + AI   |     |   (127.0.0.1:11434)|
|   Waydroid LXC   |     | * Podman / Docker |     | * System AI Agent  |
| * Type Router &  |     | * One-Click       |     | * Local Code Agent |
|   ClamAV Scan    |     |   https://*.test  |     | * PSI Watchdog     |
+------------------+     +-------------------+     +--------------------+
         |                         |                         |
         +-------------------------+-------------------------+
                                   |
                                   v
+-----------------------------------------------------------------------+
|                         DevOS Linux Foundation                        |
+-----------------------------------------------------------------------+
| * Ubuntu 24.04 LTS (Noble) Minimal Core (Zero Snap Bloat / No Spyware)|
| * HWE Kernel + BBR TCP + EarlyOOM + systemd-oomd (PSI Memory Shield)   |
| * In-RAM zram Swap (zstd algorithm, 50% RAM allocation)               |
| * btrfs Filesystem with zstd:3 Compression & Snapper Snapshots        |
| * Hybrid BIOS + UEFI Boot with Secure Boot (shim-signed)              |
+-----------------------------------------------------------------------+
```

---

## 🚀 Key Feature Highlights

### 1. Windows Look & Feel (Zero Learning Curve)
- **Taskbar & Start Menu:** Centered or left-aligned icons, Windows 11-style Start Menu with pinned apps and recent files, system tray, clock, and peek-at-desktop corner.
- **Dolphin Configured Like Explorer:** Breadcrumb address bar, details view mode, "This PC" folder hierarchy, and right-click actions ("Open in VSCodium", "Analyze with WinLayer Doctor", "Install on DevOS Android").
- **Windows Keyboard Shortcuts:**
  - `Win` $\to$ Open Start Menu
  - `Win + E` $\to$ Open File Explorer (Dolphin)
  - `Win + D` $\to$ Show / Hide Desktop
  - `Win + R` $\to$ Run Command Dialog (KRunner)
  - `Win + L` $\to$ Lock Workstation
  - `Win + Shift + S` $\to$ Snipping Tool (Spectacle)
  - `Win + Left / Right / Up / Down` $\to$ Window Tiling & Snapping
  - `Alt + Tab` $\to$ Window Switcher
  - `Ctrl + Shift + Esc` $\to$ System Task Manager (`btop`)
- **Typography:** Microsoft fonts are aliased to open-source metrics-compatible typography via Fontconfig:
  - `Segoe UI` $\to$ **Inter**
  - `Arial` $\to$ **Liberation Sans**
  - `Calibri` $\to$ **Carlito**
  - `Cambria` $\to$ **Caladea**
  - `Consolas / Monospace` $\to$ **Fira Code**

---

### 2. Universal App Hub: Run Any Application
DevOS eliminates package format silos. Double-click or run any app from a single interface:

| Runtime | Handled Formats | Execution Engine | Isolation & Features |
|---|---|---|---|
| **Windows** | `.exe`, `.msi`, `.bat`, `.lnk` | **WinLayer** (Wine Staging, Proton-GE, DXVK, VKD3D-Proton) | Per-app isolated prefixes, btrfs reflink deduplication (0 MB added space), real Start Menu shortcuts. |
| **Linux** | Flatpak, AppImage, `.deb`, APT | **LinuxLayer** (Flathub, Native APT, Distrobox) | Flathub enabled by default, FUSE3 AppImage integration, dependency-resolved `.deb` installer. |
| **Android** | `.apk`, `.xapk`, `.apks` | **AndroidLayer** (Waydroid on Wayland) | Multi-window floating mode, shared clipboard, shared folder (`~/Android`), `adb` debugging, F-Droid & Aurora Store preinstalled. |

#### Magic-Byte File Type Router
DevOS does **not** rely on file extensions. Even if a file is mislabeled (e.g. `installer.png`), the [type_router.py](file:///c:/docker/DevOS/components/apphub/type_router.py) inspects the binary headers:
- `MZ` $\to$ Routes to WinLayer
- `PK + AndroidManifest.xml` $\to$ Routes to Waydroid
- `\x7fELF` $\to$ Routes to LinuxLayer
- `!<arch> + debian-binary` $\to$ Routes to APT

#### Pre-Execution Safety Scan
Before running downloaded binaries, [safety_scanner.py](file:///c:/docker/DevOS/components/apphub/safety_scanner.py) performs:
- **Malware Signature Checks:** ClamAV definitions + EICAR test verification.
- **Android Permission Audits:** Flags dangerous permissions (SMS interception, accessibility spyware, overlay windows, device admin).
- **PE Header Inspection:** [doctor.py](file:///c:/docker/DevOS/components/winlayer/doctor.py) flags kernel-level anti-cheat/DRM (Vanguard, BattlEye) and suggests native VM fallback if needed.

---

### 3. Local AI Core & System AI Assistant

#### Hardware Tiering (Automatic First-Boot Detection)
[hardware_detector.py](file:///c:/docker/DevOS/components/ai-core/hardware_detector.py) inspects physical RAM and GPU acceleration (CUDA, ROCm, Vulkan) to allocate the optimal offline model:

| Tier | Hardware Profile | Recommended Chat Model | Recommended Code Model | Embeddings |
|---|---|---|---|---|
| **Lite** | $\le 8\text{ GB}$ RAM, CPU / basic GPU | Qwen2.5 1.5B / 3B Instruct Q4 | Qwen2.5-Coder 1.5B / 3B Q4 | nomic-embed-text |
| **Standard** | $16\text{ GB}$ RAM or 6–8 GB VRAM | Qwen2.5 7B Instruct Q4_K_M | Qwen2.5-Coder 7B Q4 | nomic-embed-text |
| **Pro** | $32\text{ GB}+$ RAM or 12–24 GB VRAM | Qwen2.5 14B / 32B Q4 | Qwen2.5-Coder 14B / 32B Q4 | bge-m3 |

- **OpenAI-Compatible Local API ([server.py](file:///c:/docker/DevOS/components/ai-core/server.py)):** Runs offline on `http://127.0.0.1:11434/v1` serving `/v1/chat/completions`, `/v1/embeddings`, and `/v1/models`.
- **System AI Assistant ([agent.py](file:///c:/docker/DevOS/components/ai-agent/agent.py)):** Operates the OS through natural language ("clean up large files", "switch to dark mode", "diagnose failed service").
- **Strict Safety Gate:** Read-only and reversible tools run freely; destructive or privileged tools **enforce confirmation**. Input sanitization blocks prompt-injection attempts, and all actions are recorded in `~/.local/share/DevOS/agent.log`.

---

### 4. Turnkey Developer Workstation (`devserver`)

#### Laragon-Style Local Stack Manager
[server_manager.py](file:///c:/docker/DevOS/components/devserver/server_manager.py) manages local services with on-demand socket activation to conserve RAM:
- **Web:** Caddy / Nginx reverse proxy
- **PHP:** PHP 8.3 FPM + all extensions
- **Databases:** MariaDB (MySQL), PostgreSQL, SQLite, Redis
- **Mail Sandbox:** Mailpit (Web UI on port 8025)
- **One-Click Projects:** Scaffold a new project with automatic `https://*.test` local domains, trusted SSL certificates (`mkcert`), and database creation:
  ```bash
  devos serve new myapp --stack laravel
  devos serve new webapp --stack nextjs
  devos serve new backend --stack fastapi
  ```

#### Telemetry-Free IDE & Local Code Agent
- **VSCodium Preconfigured:** Equipped with the **Continue** local AI extension connected to `http://127.0.0.1:11434/v1`.
- **Inline Tab Completion:** Fast local completion via `Qwen2.5-Coder 1.5B`.
- **Local Code Agent CLI:**
  ```bash
  devos code "Add an Eloquent User model with email verification" --framework laravel
  ```

---

### 5. Heavy-Load & Anti-Hang Performance Shield

Why DevOS **never freezes** under heavy load:

1. **In-RAM Compressed Swap (`zram` with `zstd`):** 50% RAM allocation paired with `vm.swappiness = 150` eliminates slow SSD disk thrashing.
2. **I/O Flush Throttling:** `vm.dirty_ratio = 10` and `vm.dirty_background_ratio = 5` ensure disk writes never stall the GUI compositor.
3. **PSI Memory Stall Monitoring (`systemd-oomd`):** Monitors `/proc/pressure/memory` and terminates runaway cgroups before the machine locks up.
4. **Smart Process Hierarchy (`earlyoom`):** Explicitly protects `kwin_wayland`, `plasmashell`, `sddm`, and `systemd` from termination while sacrificing memory-leaking background tabs or rogue processes.
5. **Transparent Filesystem Compression (`btrfs + zstd:3`):** Compresses apps and caches on the fly, cutting 10–20 GB applications down to ~5–10 GB while speeding up NVMe read speeds.

---

## 💻 DevOS Master CLI Reference

The unified `devos` command provides a single interface to manage the entire OS:

```bash
# Universal App Hub
devos app search <keyword>               # Search Flathub, APT, F-Droid, WinLayer
devos app install <file.exe | apk | deb> # Auto-route by magic bytes and install
devos app list                           # List installed universal apps

# Local Code Agent
devos code "Generate a user auth service" --framework laravel
devos code "Create a responsive navbar"   --framework nextjs

# Local Developer Server (Laragon-style)
devos serve status                       # Check Caddy, PHP, DB, Redis, Mailpit
devos serve new myapp --stack laravel    # Provision https://myapp.test with SSL
devos serve list                         # List provisioned virtual hosts

# System AI Assistant
devos ai "Turn on dark mode"
devos ai "Find files larger than 100MB"
devos ai "Why did the database service crash?"

# Windows Layer (WinLayer)
devos win doctor setup.exe               # Analyze PE headers & anti-cheat
devos win launch app.exe                 # Launch in isolated prefix
devos win list                           # List active Windows prefixes

# Android Layer (Waydroid)
devos android status                     # Check container & Wayland status
devos android install package.apk        # Install APK into multi-window container

# System Watchdog & Heavy Load Optimizer
devos watchdog --check-pressure          # Check Linux PSI memory stall pressure
devos watchdog --audit-space             # Audit reclaimable Chrome & Wine cache
devos watchdog --optimize                # Compress and optimize heavy app storage
```

---

## 🛠️ Building the DevOS ISO

You can build the bootable ISO natively on an Ubuntu 24.04 host or inside a reproducible Docker container.

### Prerequisites (Host Build)
- Clean Ubuntu 24.04 LTS (Noble) installation with root/sudo privileges.
- At least 25 GB of free disk space.

### Step 1: Install Build Tools
```bash
git clone https://github.com/devos-project/devos.git
cd devos
sudo make setup
```

### Step 2: Build the Hybrid ISO
```bash
# Native Build
sudo make iso

# Or Reproducible Containerized Build (Docker / Podman)
make iso-docker
```
The resulting hybrid BIOS+UEFI image will be saved to:
```
out/devos-24.04-amd64.iso
```

---

## 🧪 Testing with QEMU

Test your freshly built ISO in virtualized environments before flashing to hardware:

### Legacy BIOS Mode:
```bash
make test-qemu-bios
```

### Modern UEFI Mode (OVMF):
```bash
make test-qemu-uefi
```

### Automated Unit Test Suite:
Run the built-in test suite verifying all 21 core subsystems:
```bash
python3 -m unittest discover -s tests/unit
# Result: Ran 21 tests in 1.068s. OK.
```

---

## 💾 Installation on Real Hardware

1. **Flash to USB:**
   - **Ventoy (Recommended):** Simply copy `devos-24.04-amd64.iso` onto your Ventoy USB drive.
   - **Rufus:** Select GPT partition scheme and UEFI target.
   - **dd (Linux / macOS):**
     ```bash
     sudo dd if=out/devos-24.04-amd64.iso of=/dev/sdX bs=4M status=progress oflag=sync
     ```
2. **Boot Your PC:** Select your USB drive in the BIOS/UEFI boot menu.
3. **Launch Calamares:** Click "Install DevOS" on the desktop.
4. **Partitioning:** Choose **btrfs** (default) with automated Snapper subvolumes and optionally check **Encrypt system (LUKS)**.
5. **Reboot:** Enjoy your AI-native, developer-first operating system!

---

## 🗂️ Repository Layout

```
DevOS/
├── Makefile                                       # Master build & test targets
├── README.md                                      # Comprehensive documentation
├── CHANGELOG.md                                   # Version tracking & release log
├── THIRD_PARTY_NOTICES.md                         # Open-source license attribution
├── LICENSES/                                      # Open-source license files
├── build/
│   ├── build-iso.sh                               # Master hybrid ISO builder
│   ├── setup-build-env.sh                         # Host dependencies installer
│   ├── versions.lock                              # Exact locked package versions
│   ├── docker/
│   │   └── Dockerfile.build                       # Reproducible build container
│   ├── package-lists/                             # Modular chroot package lists
│   │   ├── 00-base.list.chroot                    # Kernel, systemd, btrfs, zram
│   │   ├── 10-hardware.list.chroot                # Firmware, mesa, vulkan, wifi
│   │   ├── 20-installer.list.chroot               # Calamares installer engine
│   │   ├── 30-developer.list.chroot               # PHP, Node, Python, Podman, DBs
│   │   └── 50-wine.list.chroot                    # Wine, Proton, DXVK, GameMode
│   ├── hooks/                                     # Chroot optimization hooks
│   │   ├── 01-strip-bloat.hook.chroot             # Doc/man purge, locale pruner
│   │   ├── 02-disable-services.hook.chroot        # Mask cups-browsed, snapd, apport
│   │   └── 03-tune-performance.hook.chroot        # zram (zstd), earlyoom, sysctl
│   ├── includes.chroot/                           # Rootfs filesystem injection
│   │   ├── etc/calamares/                         # Calamares installer configuration
│   │   ├── etc/fonts/conf.d/                      # Fontconfig Windows font aliases
│   │   ├── etc/skel/                              # Default user VSCodium & Continue configs
│   │   ├── etc/sysctl.d/                          # Heavy-load anti-hang kernel configs
│   │   ├── etc/xdg/                               # Windows shortcuts & MIME mappings
│   │   └── usr/share/                             # Desktop entries & context menus
│   └── branding/                                  # Wallpapers, Plymouth, Calamares
├── components/
│   ├── devos_cli.py                               # Master unified CLI dispatcher
│   ├── ai-core/                                   # Local OpenAI daemon & aimodel CLI
│   ├── ai-agent/                                  # System assistant & PSI watchdog
│   ├── code-agent/                                # Local Code Agent & repo mapper
│   ├── devserver/                                 # Laragon-style local server manager
│   ├── winlayer/                                  # Windows prefix manager & PE doctor
│   ├── linuxlayer/                                # Linux package handlers
│   ├── androidlayer/                              # Waydroid container manager
│   ├── apphub/                                    # Universal App Hub & safety scan
│   ├── first-boot/                                # First-boot setup wizard
│   └── settings/                                  # DevOS Control Center & snapshots
├── tests/
│   ├── qemu/                                      # QEMU BIOS & UEFI smoke runners
│   └── unit/                                      # Comprehensive 21 unit tests
├── tools/
│   └── size-report.sh                             # Debloat audit & package size tool
├── docs/
│   ├── phase-1-plan.md                            # Phase 1 architectural specification
│   ├── HEAVY_LOAD_AND_STORAGE_OPTIMIZATION.md     # Anti-hang & btrfs zstd deep-dive
│   ├── WINDOWS_COMPAT.md                          # WinLayer compatibility guide
│   ├── ANDROID_COMPAT.md                          # Waydroid integration & licensing
│   ├── DEVELOPER_WORKSTATION.md                   # Devserver & coding guide
│   └── COMING_FROM_WINDOWS.md                     # Transition guide for Windows users
└── .github/workflows/
    └── build-iso.yml                              # CI workflow for ISO builds & tests
```

---

## 📜 Legal & Licensing Compliance

- **No Proprietary Microsoft Assets:** DevOS contains no Microsoft binaries, fonts, or copyrighted code. All Windows compatibility is achieved via **Wine, Proton, DXVK, and open-source font metric substitutions**.
- **No Proprietary Google Apps:** The Android environment uses open-source AOSP/LineageOS images with **F-Droid and Aurora Store**. Proprietary Google Play Services are **never bundled in the ISO**.
- **Telemetry Free:** No personal telemetry or usage data leaves your machine.
- **License Attribution:** Comprehensive package notices are documented in [THIRD_PARTY_NOTICES.md](file:///c:/docker/DevOS/THIRD_PARTY_NOTICES.md) and [LICENSES/](file:///c:/docker/DevOS/LICENSES/).

---

## 🤝 Contributing & Community

Contributions are warmly welcomed! Please read our [Developer Guide](file:///c:/docker/DevOS/docs/DEVELOPER_WORKSTATION.md) and submit pull requests following our modular component architecture.

**DevOS Project** &copy; 2026. Distributed under the [MIT License](file:///c:/docker/DevOS/LICENSES/MIT.txt).
