# DevOS Windows Application Compatibility Guide (`winlayer`)

DevOS runs Windows applications (`.exe`, `.msi`, `.bat`) with **Wine** and, when the `dxvk` package is installed, **DXVK** for DirectX 9–11. DirectX 12 uses Wine's **vkd3d**. This is not Proton-GE. Kernel anti-cheat does not run under Wine.

---

## 1. Supported Features

- **Double-Click Execution**: Double-clicking any `.exe` or `.msi` in Dolphin automatically routes to WinLayer.
- **Isolated Per-App Prefixes**: Every application receives an isolated wineprefix in `~/.local/share/winlayer/prefixes/<app>`, avoiding dependency conflicts.
- **Reflink Deduplication**: Prefixes leverage btrfs CoW reflinks, taking **zero extra disk space** for common Windows system libraries.
- **Graphics**:
  - DirectX 9, 10, 11 use Vulkan via **DXVK** after the prefix is prepared.
  - DirectX 12 uses Wine's **vkd3d** (`libvkd3d1`), not VKD3D-Proton.
- **Desktop Integration**:
  - Real Windows app icons appear in the Start Menu (`~/.local/share/applications/winlayer-*.desktop`).
  - System tray icon support.
  - File associations mapped.

---

## 2. Compatibility Analysis (`winlayer doctor`)

Before running unknown or heavy installers, use the built-in PE header inspector:
```bash
python3 components/winlayer/doctor.py installer.exe
```

Ratings:
1. **Works**: Standard 32-bit and 64-bit Windows software, .NET applications (via Wine-Mono), DirectX 9/11/12 games, 7-Zip, Notepad++, VLC.
2. **Needs Tweaks**: Software requiring specific fonts or VC++ redistributables (auto-injected by WinLayer).
3. **Use VM**: Kernel-level anti-cheat titles (Vanguard, BattlEye, Easy Anti-Cheat with driver requirements) or low-level proprietary hardware flashers.

---

## 3. Windows VM fallback (QEMU)

For programs Wine cannot run (kernel anti-cheat, some drivers):

- Install **Windows virtual machine** in DevOS Features (`qemu-system-x86`, `ovmf`).
- DevOS does **not** ship a Windows ISO or licence.
- `devos win vm create --iso /path/to/Windows.iso` creates a virtual disk and opens Windows in its own window.
- This is a normal virtual PC, not a seamless RemoteApp desktop.
