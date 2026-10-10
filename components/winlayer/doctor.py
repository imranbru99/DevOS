#!/usr/bin/env python3
"""
DevOS WinLayer Doctor
Static analysis engine for Windows PE binaries (.exe, .msi, .dll).
Parses PE headers, architecture, imported DLLs, and flags compatibility status
(Works / Needs Tweaks / Use VM). Zero external dependencies required.
"""

import sys
import os
import struct
import json
import argparse
from typing import Dict, Any, List


class WinLayerDoctor:
    """Analyzes Windows executables to determine compatibility rating under Wine/Proton."""

    # Well-known problematic imports (anti-cheat, low-level kernel drivers)
    ANTI_CHEAT_SIGNATURES = [
        "vgc.sys", "vgk.sys", "easyanticheat", "eac", "battleye", "bedaisy.sys",
        "blackcipher", "nprotect", "gameguard", "themida", "denuvo"
    ]

    # Common runtime dependencies
    RUNTIME_DLLS = {
        "mscoree.dll": ".NET Framework Runtime",
        "d3d11.dll": "DirectX 11 (Accelerated via DXVK)",
        "d3d12.dll": "DirectX 12 (Accelerated via VKD3D-Proton)",
        "dxgi.dll": "DirectX Graphics Infrastructure (DXVK)",
        "vulkan-1.dll": "Vulkan Native",
        "msvcp140.dll": "Visual C++ 2015-2022 Redistributable",
        "msvcr120.dll": "Visual C++ 2013 Redistributable",
        "msvcr100.dll": "Visual C++ 2010 Redistributable",
    }

    @staticmethod
    def analyze_pe(file_path: str) -> Dict[str, Any]:
        """Parses PE header of given binary."""
        if not os.path.exists(file_path):
            return {"error": f"File '{file_path}' does not exist."}

        with open(file_path, "rb") as f:
            header_bytes = f.read(2048)

        # 1. Verify DOS Magic 'MZ'
        if len(header_bytes) < 64 or header_bytes[:2] != b"MZ":
            return {
                "file": file_path,
                "is_pe": False,
                "compatibility": "Not a Windows PE Executable"
            }

        # 2. Read e_lfanew pointer to PE Header (at offset 0x3C)
        pe_offset = struct.unpack_from("<I", header_bytes, 0x3C)[0]
        if len(header_bytes) < pe_offset + 24 or header_bytes[pe_offset:pe_offset+4] != b"PE\x00\x00":
            return {
                "file": file_path,
                "is_pe": False,
                "compatibility": "Corrupt or invalid PE Header"
            }

        # 3. Read Machine architecture
        machine = struct.unpack_from("<H", header_bytes, pe_offset + 4)[0]
        arch = "x86_64 (64-bit)" if machine == 0x8664 else "i386 (32-bit)" if machine == 0x014c else "Unknown"

        # 4. Scan strings for DLL imports and anti-cheat signatures
        # Read up to 2MB for import scanning
        with open(file_path, "rb") as f:
            content = f.read(2 * 1024 * 1024).lower()

        detected_runtimes = []
        for dll, desc in WinLayerDoctor.RUNTIME_DLLS.items():
            if dll.encode("ascii") in content:
                detected_runtimes.append({"dll": dll, "description": desc})

        anti_cheat_detected = []
        for ac in WinLayerDoctor.ANTI_CHEAT_SIGNATURES:
            if ac.encode("ascii") in content:
                anti_cheat_detected.append(ac)

        # 5. Determine compatibility rating
        if anti_cheat_detected:
            rating = "Use VM (Kernel Anti-Cheat Detected)"
            recommendation = (
                f"Binary contains kernel-level anti-cheat/DRM ({', '.join(anti_cheat_detected)}). "
                "Kernel anti-cheat cannot run under Wine; launch using DevOS Windows VM Fallback."
            )
        elif any("d3d" in r["dll"] for r in detected_runtimes):
            rating = "Works (DirectX / DXVK Accelerated)"
            recommendation = "Fully supported via Proton-GE + DXVK Vulkan translation layer."
        elif any("mscoree" in r["dll"] for r in detected_runtimes):
            rating = "Works (.NET / Mono Supported)"
            recommendation = "Supported via Wine-Mono or winetricks dotnet48 prefix."
        else:
            rating = "Works (Standard Win32/Win64)"
            recommendation = "Executes out of the box in an isolated WinLayer prefix."

        return {
            "file": file_path,
            "is_pe": True,
            "architecture": arch,
            "detected_runtimes": detected_runtimes,
            "anti_cheat_flagged": anti_cheat_detected,
            "compatibility_rating": rating,
            "recommendation": recommendation,
        }


def main():
    parser = argparse.ArgumentParser(description="DevOS WinLayer Doctor PE Analyzer")
    parser.add_argument("binary", help="Path to Windows .exe or .dll")
    args = parser.parse_args()

    report = WinLayerDoctor.analyze_pe(args.binary)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
