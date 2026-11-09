#!/usr/bin/env python3
"""
DevOS App Hub Type Router
Detects binary and package types strictly by MAGIC BYTES, not file extensions.
Accurately routes mislabeled files to WinLayer, LinuxLayer, or AndroidLayer.
"""

import sys
import os
import zipfile
import json
import argparse
from typing import Dict, Any


class AppTypeRouter:
    """Inspects file headers to determine runtime target."""

    TARGET_WINDOWS = "windows"   # WinLayer (Wine / Proton)
    TARGET_ANDROID = "android"   # AndroidLayer (Waydroid / APK)
    TARGET_LINUX = "linux"       # LinuxLayer (ELF / AppImage)
    TARGET_DEB = "deb"           # LinuxLayer (APT .deb package)
    TARGET_FLATPAK = "flatpak"   # LinuxLayer (Flatpak reference)
    TARGET_UNKNOWN = "unknown"

    @classmethod
    def identify_type(cls, file_path: str) -> Dict[str, Any]:
        """Inspects file magic bytes and internal structures."""
        abs_path = os.path.abspath(os.path.expanduser(file_path))
        if not os.path.exists(abs_path):
            return {"error": f"File '{abs_path}' not found."}

        with open(abs_path, "rb") as f:
            header = f.read(512)

        # 1. Check for Windows PE Executable (Magic: MZ)
        if len(header) >= 2 and header[:2] == b"MZ":
            return {
                "file": abs_path,
                "detected_runtime": cls.TARGET_WINDOWS,
                "magic_signature": "PE_MZ",
                "handler": "components/winlayer/prefix_manager.py",
                "runtime_badge": "[Windows (WinLayer)]",
                "description": "Windows Executable (.exe / .msi)",
            }

        # 2. Check for Linux ELF executable or AppImage (Magic: 0x7F 'E' 'L' 'F')
        if len(header) >= 4 and header[:4] == b"\x7fELF":
            # Check for AppImage Type 2 signature (offset 0x08 has 'AI\x02')
            is_appimage = len(header) >= 10 and header[8:10] == b"AI"
            subtype = "AppImage" if is_appimage else "Native ELF Binary"
            return {
                "file": abs_path,
                "detected_runtime": cls.TARGET_LINUX,
                "magic_signature": "ELF_APPIMAGE" if is_appimage else "ELF_NATIVE",
                "handler": "components/linuxlayer/appimage_runner.sh",
                "runtime_badge": "[Linux (Native/AppImage)]",
                "description": f"Linux Executable ({subtype})",
            }

        # 3. Check for Debian Package Archive (Magic: !<arch>\ndebian-binary)
        if len(header) >= 8 and header[:7] == b"!<arch>":
            return {
                "file": abs_path,
                "detected_runtime": cls.TARGET_DEB,
                "magic_signature": "AR_DEB",
                "handler": "apt install",
                "runtime_badge": "[Linux (Debian/APT)]",
                "description": "Debian System Package (.deb)",
            }

        # 4. Check for ZIP container (Magic: PK\x03\x04 or PK\x05\x06) -> Android APK or Flatpakref
        if len(header) >= 4 and header[:2] == b"PK":
            try:
                with zipfile.ZipFile(abs_path, "r") as zf:
                    namelist = zf.namelist()
                    if "AndroidManifest.xml" in namelist:
                        return {
                            "file": abs_path,
                            "detected_runtime": cls.TARGET_ANDROID,
                            "magic_signature": "ZIP_ANDROID_MANIFEST",
                            "handler": "components/androidlayer/waydroid_manager.py",
                            "runtime_badge": "[Android (Waydroid)]",
                            "description": "Android Application Package (APK)",
                        }
            except Exception:
                pass

        # 5. Check text for Flatpakref
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as tf:
                first_lines = tf.read(256)
                if "[Flatpak Ref]" in first_lines:
                    return {
                        "file": abs_path,
                        "detected_runtime": cls.TARGET_FLATPAK,
                        "magic_signature": "FLATPAKREF_TEXT",
                        "handler": "flatpak install",
                        "runtime_badge": "[Linux (Flatpak)]",
                        "description": "Flatpak Application Reference (.flatpakref)",
                    }
        except Exception:
            pass

        return {
            "file": abs_path,
            "detected_runtime": cls.TARGET_UNKNOWN,
            "magic_signature": "UNKNOWN",
            "runtime_badge": "[Unknown]",
            "description": "Unrecognized binary format",
        }


def main():
    parser = argparse.ArgumentParser(description="DevOS App Hub Magic-Byte Type Router")
    parser.add_argument("file", help="Path to file to inspect")
    args = parser.parse_args()

    res = AppTypeRouter.identify_type(args.file)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
