# DevOS: The AI-Native, Developer-First Operating System

DevOS is a bootable, installable Linux distribution based on **Ubuntu 24.04 LTS (Noble Numbat)** engineered to look and feel like Windows, run Windows (`.exe` / `.msi`), Linux (deb / Flatpak / AppImage), and Android (`.apk`) applications out of the box, and integrate an offline-first, free local AI stack and developer environment.

---

## Key Highlights

- **Desktop Experience:** Familiar Windows-like workflow powered by KDE Plasma 6 (Wayland default), fluent styling, Windows keyboard shortcuts, and unified settings.
- **Universal App Hub:** Runs Windows apps (via WinLayer / Wine Staging / Proton / DXVK), Linux packages (Flatpak / AppImage / deb), and Android apps (Waydroid container) managed from a single hub.
- **AI-Native & 100% Offline-First:** Ships with a local OpenAI-compatible inference daemon, hardware-tiered local models (Qwen2.5 / Llama 3), system AI assistant, and local coding agent.
- **Developer Workstation:** Preconfigured with VSCodium, containers (Podman/Docker), PHP 8.3/Composer/Laravel, Node.js/pnpm, Python, databases, and a Laragon-style local server manager (`devserver`).
- **Lean & Fast:** Target base ISO <= 4.0 GB, installed footprint <= 12 GB, cold boot <= 15 s, idle RAM <= 900 MB. Default **btrfs + zstd** filesystem with snapshot support.

---

## Repository Structure

```
DevOS/
  Makefile                 # Master build and test targets
  README.md                # Project documentation
  CHANGELOG.md             # Version and progress log
  THIRD_PARTY_NOTICES.md   # Open-source license attribution
  LICENSES/                # Open source license copies
  build/
    config/                # Live-build / chroot configuration
    package-lists/         # Modular chroot package lists (base, hardware, installer)
    hooks/                 # Chroot optimization and stripping hooks
    includes.chroot/       # Chroot filesystem overrides (/etc, /usr, /opt)
    branding/              # Calamares, Plymouth, SDDM, GRUB branding
    versions.lock          # Package and component lockfile
    docker/                # Containerized build files
    setup-build-env.sh     # Host environment setup script
    build-iso.sh           # Master ISO generation script
  components/
    ai-core/               # Local AI engine (OpenAI-compatible server)
    ai-agent/              # System assistant with tool calling and safe executor
    code-agent/            # Local code agent & VSCodium integration
    devserver/             # Laragon-style local server manager dashboard
    winlayer/              # Windows application compatibility layer
    linuxlayer/            # Linux package & Distrobox management
    androidlayer/          # Waydroid integration & Android manager
    apphub/                # Universal App Hub (GUI & CLI)
    first-boot/            # Hardware tier detection & setup wizard
    settings/              # DevOS Control Center app
  tests/
    qemu/                  # Automated BIOS & UEFI boot smoke tests
    unit/                  # Component unit tests
  docs/
    phase-1-plan.md        # Phase 1 planning & verification specification
  .github/workflows/       # Automated CI build & testing workflows
```

---

## Building DevOS (Phase 1)

### Option 1: Native Build on Ubuntu 24.04 LTS

1. Ensure you have an Ubuntu 24.04 LTS environment with root/sudo privileges.
2. Install host build prerequisites:
   ```bash
   sudo make setup
   ```
3. Build the hybrid BIOS+UEFI ISO:
   ```bash
   sudo make iso
   ```
4. Output ISO will be located at:
   ```
   out/devos-24.04-amd64.iso
   ```

### Option 2: Containerized Build (Docker / Podman)

Run a clean, isolated build inside a container:
```bash
make iso-docker
```

---

## Testing the ISO

### Legacy BIOS Boot:
```bash
make test-qemu-bios
```

### Modern UEFI Boot (OVMF):
```bash
make test-qemu-uefi
```

### Check Size Metrics:
```bash
make check-size
```

---

## Project Status

- [x] **Phase 1: Base System & ISO Pipeline** (Current Phase - Initial Pipeline & Structure)
- [ ] **Phase 2: Windows-like Desktop** (KDE Plasma 6, Fluent theme, Dolphin Explorer, Control Center)
- [ ] **Phase 3: Windows Application Compatibility Layer (`winlayer`)**
- [ ] **Phase 3B: Linux Apps + Android Apps + Universal App Hub (`linuxlayer`, `androidlayer`, `apphub`)**
- [ ] **Phase 4: Local AI Core (`ai-core`)**
- [ ] **Phase 5: System AI Agent (`ai-agent`)**
- [ ] **Phase 6: Developer Workstation (`devserver`)**
- [ ] **Phase 7: Local Code Agent (`code-agent`)**
- [ ] **Phase 8: Polish, Updates, Backup**
