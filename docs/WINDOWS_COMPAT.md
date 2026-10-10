# DevOS Windows Application Compatibility Guide (`winlayer`)

DevOS runs Windows applications (.exe, .msi, .bat, .lnk) out of the box using an integrated compatibility stack powered by **Wine Staging, Proton-GE, DXVK, and VKD3D-Proton**, managed through **WinLayer**.

---

## 1. Supported Features

- **Double-Click Execution**: Double-clicking any `.exe` or `.msi` in Dolphin automatically routes to WinLayer.
- **Isolated Per-App Prefixes**: Every application receives an isolated wineprefix in `~/.local/share/winlayer/prefixes/<app>`, avoiding dependency conflicts.
- **Reflink Deduplication**: Prefixes leverage btrfs CoW reflinks, taking **zero extra disk space** for common Windows system libraries.
- **Graphics Acceleration**:
  - DirectX 9, 10, 11 $\to$ Vulkan via **DXVK**.
  - DirectX 12 $\to$ Vulkan via **VKD3D-Proton**.
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

## 3. Windows VM Fallback (QEMU/KVM + VirtIO)

For applications Wine cannot run:
- DevOS integrates **QEMU/KVM + libvirt + VirtIO + RemoteApp seamless mode**.
- DevOS **does NOT ship Microsoft Windows binaries or ISOs**.
- Guided Wizard: "Bring your own Windows ISO and license" to deploy a seamless virtual machine with shared folders (`~/DevOS_Shared`).
