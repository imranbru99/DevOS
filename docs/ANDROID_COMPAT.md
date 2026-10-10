# DevOS Android Compatibility Guide (`androidlayer`)

DevOS runs Android applications (`.apk`, `.xapk`, `.apks`) at near-native speeds on x86_64 hardware using **Waydroid** running on **KDE Plasma Wayland**.

---

## 1. Architecture & Performance

- **Near-Native Speed**: Waydroid runs Android inside a lightweight Linux LXC container using the host kernel via `binder`/`binderfs`. There is zero CPU emulation for x86/x86_64 binaries.
- **Multi-Window Wayland Mode**: Android applications appear as standard, resizable, floating desktop windows alongside Linux and Windows apps with working taskbar icons and Alt+Tab integration.
- **On-Demand Lifecycle**: The container starts on demand when an Android app is launched and freezes when idle to conserve RAM and battery life.

---

## 2. Licensing & Legal Compliance

- **No Proprietary Google Bundling**: DevOS uses an open-source AOSP/LineageOS base image. Google Play Services and Google proprietary apps are **never bundled in the ISO**.
- **Default Open Stores**: **F-Droid** and **Aurora Store** come pre-configured.
- **User-Initiated Google Services Wizard**: An optional setup wizard allows advanced users to install microG or OpenGApps at their own discretion.
- **ARM-to-x86 Translation Layer**: Proprietary ARM translation layers (such as libndk/libhoudini) are strictly opt-in and downloaded only after explicit user consent.

---

## 3. Desktop & Developer Integration

- **Shared Storage**: Android apps can read and write to the host at `~/Android`.
- **Shared Clipboard**: Cut, copy, and paste text seamlessly between Windows, Linux, and Android windows.
- **Developer Features**:
  - `adb` and `scrcpy` preinstalled.
  - Waydroid auto-registered as an `adb` target.
  - Run your APK directly:
    ```bash
    devos app install myapp.apk
    ```
