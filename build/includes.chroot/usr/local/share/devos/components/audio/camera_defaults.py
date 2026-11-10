#!/usr/bin/env python3
"""Camera (V4L2) discovery for DevOS — always-on OS basic, not an installer checkbox.

Lists capture nodes under /sys/class/video4linux so About and helpers can show
whether a webcam is present after plug-in.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

SYS_V4L = Path("/sys/class/video4linux")
DEV_DIR = Path("/dev")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _is_capture_device(sys_node: Path) -> bool:
    """Prefer real capture nodes; skip metadata-only nodes when possible.

    Many UVC cams expose video0=capture and video1=metadata. Keep the primary
    node, drop obvious metadata/IR nodes, and keep extra nodes that look like
    a second capture camera.
    """
    name = sys_node.name  # video0
    try:
        idx = int(name.replace("video", "") or "0")
    except ValueError:
        idx = 0
    label = _read_text(sys_node / "name").lower()
    if any(tok in label for tok in ("meta", "metadata")):
        return False
    if idx == 0:
        return True
    if any(tok in label for tok in ("ir ", "infrared")):
        return False
    return any(tok in label for tok in ("capture", "camera", "webcam"))


def list_cameras(sys_root: Optional[Path] = None, include_all: bool = False) -> List[Dict[str, Any]]:
    """Return cameras as [{device, name, usb, bus_info}, ...]."""
    root = sys_root or SYS_V4L
    if not root.is_dir():
        return []
    cameras: List[Dict[str, Any]] = []
    for node in sorted(root.iterdir(), key=lambda p: p.name):
        if not node.name.startswith("video"):
            continue
        if not include_all and not _is_capture_device(node):
            continue
        dev = DEV_DIR / node.name
        name = _read_text(node / "name") or node.name
        bus_info = _read_text(node / "device" / "uevent")
        usb = "PRODUCT=" in bus_info or "usb" in _read_text(node / "device" / "modalias").lower()
        # Prefer ID_PATH / bus_info from uevent when present
        bus = ""
        for line in bus_info.splitlines():
            if line.startswith("DEVPATH=") and "usb" in line:
                usb = True
            if line.startswith("OF_FULLNAME=") or line.startswith("MODALIAS="):
                bus = line.split("=", 1)[-1]
        cameras.append({
            "device": str(dev),
            "sysfs": str(node),
            "name": name,
            "usb": bool(usb),
            "bus": bus,
            "index": node.name,
        })
    return cameras


def has_camera(sys_root: Optional[Path] = None) -> bool:
    return bool(list_cameras(sys_root=sys_root))


def camera_summary(sys_root: Optional[Path] = None) -> Dict[str, Any]:
    cams = list_cameras(sys_root=sys_root)
    return {
        "count": len(cams),
        "cameras": cams,
        "label": cams[0]["name"] if cams else "No camera",
    }


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="devos-camera-probe",
                                     description="List cameras seen by DevOS")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--all", action="store_true", help="include metadata nodes")
    args = parser.parse_args(argv)
    cams = list_cameras(include_all=bool(args.all))
    if args.json:
        print(json.dumps(camera_summary() if not args.all else {"count": len(cams), "cameras": cams}, indent=2))
    else:
        if not cams:
            print("No camera")
            return 1
        for c in cams:
            tag = "USB" if c.get("usb") else "CAM"
            print(f"{c['device']}\t{c['name']}\t{tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
