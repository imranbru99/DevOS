# Coming to DevOS From Windows: A Quick Reference

DevOS is engineered specifically to make developers transitioning from Microsoft Windows feel instantly at home.

---

## 1. Keyboard Shortcuts (Identical to Windows)

| Action | Shortcut | DevOS Behavior |
|---|---|---|
| **Start Menu** | `Win` (Super) | Opens the DevOS Fluent Application Menu |
| **File Explorer** | `Win + E` | Opens Dolphin Explorer with breadcrumbs and "This PC" |
| **Show Desktop** | `Win + D` | Minimizes all open windows |
| **Run Command** | `Win + R` | Launches KRunner search and quick-launcher |
| **Lock Screen** | `Win + L` | Locks the session |
| **Take Screenshot** | `Win + Shift + S` | Launches Spectacle rectangular screen snip |
| **Snap Left / Right** | `Win + Left / Right` | Tiles the current window to the half-screen |
| **Maximize / Minimize** | `Win + Up / Down` | Maximizes or restores window |
| **Switch Windows** | `Alt + Tab` | Fluid window switcher |
| **Task Manager** | `Ctrl + Shift + Esc` | Launches Plasma System Monitor / `btop` |

---

## 2. Windows Concepts vs. DevOS Concepts

| Windows Concept | DevOS Equivalent | Notes |
|---|---|---|
| **C:\ Drive** | `~/.local/share/winlayer/prefixes/<app>/drive_c` | Each Windows app gets its own clean, isolated C: drive. |
| **File Explorer** | Dolphin Explorer | Configured with Explorer-like breadcrumb navigation, details view, and "This PC". |
| **Windows Installer (.msi / .exe)** | Double-click or `devos app install <file>` | Runs in an isolated WinLayer prefix with DXVK GPU acceleration. |
| **Android Apps (.apk)** | Double-click or `devos app install <apk>` | Launches directly in multi-window mode via Waydroid. |
| **Windows Registry** | Per-prefix `system.reg` / `user.reg` | Clean, isolated hives; uninstalling an app purges its entire registry footprint. |
| **PowerShell / CMD** | Bash / Zsh / PowerShell Core | Full Linux command line power with optional PowerShell Core. |
| **Control Panel** | DevOS Control Center (`devos`) | Unified settings for Display, Network, AI, and Dev Tools. |
| **Windows Defender** | ClamAV + AppSafetyScanner + PSI Watchdog | Proactive malware scanning and memory protection without performance bloat. |

---

## 3. Right-Click Context Menu Enhancements

Right-clicking files and folders in Dolphin gives you instant developer and compatibility options:
- **"Open in VSCodium"**: Opens any folder or code file in your pre-configured code editor.
- **"Analyze with WinLayer Doctor"**: Checks PE headers and flags compatibility before running unknown `.exe` files.
- **"Install on DevOS Android"**: Sends APKs directly to the Waydroid container.
- **"Create Local Dev Project Here"**: Sets up a `devserver` virtual host for the directory.
