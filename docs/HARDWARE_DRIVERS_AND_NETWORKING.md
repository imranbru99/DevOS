# DevOS Hardware, Drivers, Audio & Networking Architecture

DevOS provides out-of-the-box hardware compatibility for modern laptops, custom workstations, and desktop rigs. This document explains how Wi-Fi, Ethernet, Audio, GPU drivers, Bluetooth, and Printers are managed.

---

## 1. Networking Subsystem (Wi-Fi & Ethernet)

DevOS uses **NetworkManager** with native KDE Plasma integration in the system tray and CLI integration via `devos net`:

### Features
- **Wi-Fi & Ethernet Auto-Switching**: Automatically prioritizes high-speed Ethernet when plugged in, falling back smoothly to Wi-Fi.
- **Fast DNS by Default**: Preconfigured with privacy-preserving, ultra-fast fallback DNS (`1.1.1.1` and `1.0.0.1`).
- **Wi-Fi Scanning & Connecting**:
  ```bash
  # Scan available networks
  devos net wifi-scan

  # Connect to network
  devos net wifi-connect "MySSID" --password "MyPassword"

  # Check network status and IP
  devos net
  ```
- **Hotspot & Tethering**: One-click Wi-Fi hotspot creation from the DevOS Control Center.
- **Airplane Mode**: Hardware-level `rfkill` toggle blocking all wireless transmitters.

---

## 2. Audio & Sound Subsystem (PipeWire + WirePlumber)

DevOS eliminates legacy ALSA/PulseAudio audio latency issues by running **PipeWire 1.0** and **WirePlumber**:

### Key Features
- **Pro-Audio Ultra-Low Latency**: Perfect for music production, streaming, gaming, and real-time AI speech processing.
- **Modern Laptop Microphone Support**: Ships `firmware-sof-signed` (Sound Open Firmware) for modern Intel Tiger Lake/Alder Lake/Raptor Lake and AMD Ryzen digital array microphones.
- **High-Fidelity Bluetooth Audio Codecs**: Ships `libspa-0.2-bluetooth` supporting **LDAC, aptX-HD, AAC, and SBC** for wireless headphones.
- **Audio CLI & System Control**:
  ```bash
  # View audio devices and status
  devos sound

  # Set master volume (0 - 100)
  devos sound volume 80
  ```

---

## 3. All-Type GPU & Peripheral Drivers

DevOS features a tiered driver detection engine:

### Graphics Cards (GPU)
- **AMD Radeon**:
  - Uses native in-kernel `amdgpu` driver.
  - Mesa RADV Vulkan driver preinstalled.
  - Zero proprietary driver installation required.
- **Intel Arc & Iris Xe**:
  - Uses in-kernel `i915` or `xe` driver.
  - Mesa ANV Vulkan driver preinstalled.
  - Hardware video acceleration (`VA-API`) enabled out of the box via `intel-media-va-driver`.
- **NVIDIA GeForce**:
  - Detected automatically on first boot.
  - If proprietary drivers are needed for CUDA or high-end 3D games:
    ```bash
    # Check driver recommendations
    devos driver

    # Install recommended NVIDIA proprietary driver (e.g. nvidia-driver-550)
    devos driver driver-install
    ```

### Printers and Scanners (Driverless IPP Everywhere)
- **Zero-Driver USB Printing**: Ships `ipp-usb` and `cups-ipp-utils`.
- Modern USB and network printers support **IPP Everywhere / AirPrint**: plug in your printer and print immediately without downloading obscure Windows `.exe` driver installers.

### Bluetooth & Peripherals
- **BlueZ 5.72**: Fast pairing for Xbox, PlayStation, and generic Bluetooth game controllers.
- Multi-touch trackpad gestures (Windows-like 3-finger swipe for desktop and task view) handled natively by `libinput` on Wayland.
