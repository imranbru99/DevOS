#!/usr/bin/env python3
"""Hardware / Secure Boot / GPU qualification report for DevOS.

Produces machine-readable evidence for a specific PC — not a universal
“every GPU certified” claim. Use after install (or on live USB) to see what
this hardware can run well.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from typing import Any, Dict, List


def _run(argv: List[str], timeout: float = 8.0) -> str:
    try:
        out = subprocess.check_output(argv, stderr=subprocess.DEVNULL, timeout=timeout, text=True)
        return out.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def secure_boot() -> Dict[str, Any]:
    path = "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
    info: Dict[str, Any] = {
        "efi": os.path.isdir("/sys/firmware/efi"),
        "secure_boot_enabled": None,
        "mokutil": None,
        "note": "Custom DevOS ISOs are not universally Secure Boot signed; enable SB only with a verified chain.",
    }
    if os.path.isfile(path):
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            # EFI variable: 4-byte attributes + value byte
            if len(data) >= 5:
                info["secure_boot_enabled"] = data[4] == 1
        except OSError:
            pass
    mok = _run(["mokutil", "--sb-state"])
    if mok:
        info["mokutil"] = mok
        low = mok.lower()
        if "enabled" in low:
            info["secure_boot_enabled"] = True
        elif "disabled" in low:
            info["secure_boot_enabled"] = False
    return info


def gpu() -> Dict[str, Any]:
    lspci = _run(["lspci"])
    lines = [ln for ln in lspci.splitlines() if "VGA" in ln or "3D" in ln or "Display" in ln]
    drivers = _run(["bash", "-lc", "lsmod | egrep 'nvidia|amdgpu|i915|xe |nouveau' || true"])
    rec = []
    blob = "\n".join(lines).lower()
    if "nvidia" in blob and "nvidia" not in drivers:
        rec.append("Install proprietary NVIDIA: sudo ubuntu-drivers autoinstall  (or: devos driver)")
    if "amd" in blob and "amdgpu" not in drivers:
        rec.append("AMD GPU usually uses amdgpu; check firmware packages if display fails.")
    if not lines:
        rec.append("No PCI display adapter reported (VM or unusual bus).")
    return {
        "adapters": lines,
        "loaded_modules": [ln.strip() for ln in drivers.splitlines() if ln.strip()],
        "recommendations": rec,
    }


def storage_ram() -> Dict[str, Any]:
    mem = 0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    mem = int(line.split()[1]) // 1024
                    break
    except (OSError, ValueError):
        pass
    disk = _run(["lsblk", "-d", "-o", "NAME,SIZE,TYPE,TRAN,MODEL"])
    return {"ram_mb": mem, "ram_gb": round(mem / 1024, 1) if mem else 0, "block_devices": disk}


def audio_net() -> Dict[str, Any]:
    return {
        "pipewire_or_pulse": bool(shutil.which("pw-cli") or shutil.which("pactl")),
        "networkmanager": bool(shutil.which("nmcli")),
        "wifi_devices": _run(["bash", "-lc", "nmcli -t -f DEVICE,TYPE,STATE device 2>/dev/null | grep wifi || true"]),
    }


def score(report: Dict[str, Any]) -> Dict[str, Any]:
    checks = []
    ram = report.get("memory", {}).get("ram_gb") or 0
    checks.append(("ram_ge_4gb", ram >= 4, "At least 4 GB RAM for comfortable daily use"))
    checks.append(("efi_firmware", bool(report.get("secure_boot", {}).get("efi")), "UEFI firmware present"))
    gpu_ok = bool(report.get("gpu", {}).get("adapters"))
    checks.append(("gpu_visible", gpu_ok, "Display adapter visible to the OS"))
    audio = report.get("audio_net", {})
    checks.append(("audio_stack", bool(audio.get("pipewire_or_pulse")), "PipeWire/PulseAudio available"))
    checks.append(("networkmanager", bool(audio.get("networkmanager")), "NetworkManager available"))
    passed = sum(1 for _, ok, _ in checks if ok)
    return {
        "passed": passed,
        "total": len(checks),
        "grade": "ready" if passed == len(checks) else ("usable" if passed >= 3 else "needs_attention"),
        "checks": [{"id": i, "ok": ok, "about": about} for i, ok, about in checks],
    }


def build_report() -> Dict[str, Any]:
    report = {
        "product": "DevOS",
        "host": platform.node(),
        "kernel": platform.release(),
        "machine": platform.machine(),
        "secure_boot": secure_boot(),
        "gpu": gpu(),
        "memory": storage_ram(),
        "audio_net": audio_net(),
    }
    report["qualification"] = score(report)
    report["disclaimer"] = (
        "This report qualifies THIS PC only. It does not certify every GPU, "
        "Secure Boot chain, or peripheral for all DevOS installs."
    )
    return report


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DevOS hardware qualification report")
    parser.add_argument("--json", action="store_true", help="Print full JSON")
    parser.add_argument("--write", metavar="PATH", help="Write JSON report to PATH")
    args = parser.parse_args(argv)
    report = build_report()
    if args.write:
        with open(args.write, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
            fh.write("\n")
    if args.json or args.write:
        print(json.dumps(report, indent=2))
        return 0
    q = report["qualification"]
    print(f"DevOS hardware qualify — {q['grade']} ({q['passed']}/{q['total']})")
    for item in q["checks"]:
        mark = "PASS" if item["ok"] else "FAIL"
        print(f"  [{mark}] {item['about']}")
    sb = report["secure_boot"]
    print(f"Secure Boot: {sb.get('secure_boot_enabled')}  (EFI={sb.get('efi')})")
    for line in report["gpu"].get("adapters") or ["(none)"]:
        print(f"GPU: {line}")
    for tip in report["gpu"].get("recommendations") or []:
        print(f"Tip: {tip}")
    print(report["disclaimer"])
    return 0 if q["grade"] != "needs_attention" else 2


if __name__ == "__main__":
    sys.exit(main())
