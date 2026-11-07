#!/usr/bin/env python3
"""Fast storage breakdown so DevOS does not look as heavy as Windows.

Windows File Explorer shows one Used bar that lumps OS + apps + user data.
DevOS keeps the same bar for familiarity, then adds a one-line insight:
  OS · Your files · Apps · Freeable
so people can see the base system is lean (~15 GB) and reclaim caches safely.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

GB = 1024 ** 3


def _du_bytes(path: Path) -> int:
    """Prefer `du -sb` (fast); fall back to a shallow walk."""
    if not path.exists():
        return 0
    try:
        import subprocess
        out = subprocess.check_output(
            ["du", "-sb", "--apparent-size", str(path)],
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
        return int(out.split()[0])
    except Exception:
        pass
    total = 0
    try:
        if path.is_file() and not path.is_symlink():
            return path.stat().st_size
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        total += _du_bytes(Path(entry.path))
                except OSError:
                    continue
    except OSError:
        return total
    return total


def _sum_existing(paths: List[Path], budget: Optional[List[int]] = None) -> int:
    total = 0
    for p in paths:
        if budget is not None and budget[0] <= 0:
            break
        size = _du_bytes(p)
        total += size
        if budget is not None:
            budget[0] -= size
    return total


def secondary_data_roots(home: Optional[Path] = None) -> List[Path]:
    """Mounted DevOS data volumes (D:, E:, …) suitable for large AI models."""
    home = home or Path.home()
    roots: List[Path] = []
    seen = set()
    home_dev = None
    try:
        home_dev = home.stat().st_dev
    except OSError:
        pass

    for base in (Path("/run/media") / home.name, Path("/media") / home.name, Path("/mnt")):
        if not base.is_dir():
            continue
        try:
            candidates = list(base.iterdir()) if base.name == "mnt" else list(base.iterdir())
        except OSError:
            continue
        # /mnt may contain nested mounts; prefer direct children only.
        for cand in candidates:
            if not cand.is_dir() or cand.is_symlink():
                continue
            try:
                st = cand.stat()
            except OSError:
                continue
            if home_dev is not None and st.st_dev == home_dev:
                continue
            key = (st.st_dev, st.st_ino)
            if key in seen:
                continue
            # Prefer writable data/ folder when present
            data = cand / "data"
            pick = data if data.is_dir() and os.access(data, os.W_OK) else cand
            if not os.access(pick, os.W_OK):
                continue
            seen.add(key)
            roots.append(pick)
    return roots


def preferred_models_dir(home: Optional[Path] = None) -> Path:
    """Prefer a secondary drive for AI models so C: stays lean."""
    env = os.environ.get("DEVOS_MODELS_DIR")
    if env:
        return Path(env)
    home = home or Path.home()
    for root in secondary_data_roots(home):
        return root / "DevOS" / "models"
    return home / ".local" / "share" / "DevOS" / "models"


def human_size(num: int) -> str:
    if num < 1024:
        return f"{num} B"
    units = ["KB", "MB", "GB", "TB"]
    value = float(num)
    for unit in units:
        value /= 1024.0
        if value < 1024 or unit == units[-1]:
            if value >= 100:
                return f"{value:.0f} {unit}"
            if value >= 10:
                return f"{value:.1f} {unit}"
            return f"{value:.2f} {unit}"
    return f"{num} B"


def analyze(home: Optional[Path] = None, mount: str = "/") -> Dict:
    """Return category sizes without a full-disk walk."""
    home = home or Path.home()

    system_paths = [
        Path("/usr"),
        Path("/boot"),
        Path("/var/lib/apt"),
        Path("/var/cache/apt"),
        Path("/var/lib/dpkg"),
        Path("/var/lib/snapd"),
    ]
    app_paths = [
        Path("/var/lib/flatpak"),
        home / ".local" / "share" / "flatpak",
        home / ".local" / "share" / "containers",
        home / ".var" / "app",
    ]
    personal_paths = [
        home / "project",
        home / "Projects",
        home / "Documents",
        home / "Downloads",
        home / "Desktop",
        home / "Pictures",
        home / "Videos",
        home / "Music",
    ]
    reclaim_paths = [
        home / ".cache",
        home / ".local" / "share" / "Trash",
        Path("/tmp"),
        Path("/var/tmp"),
    ]
    # Browser disk caches (safe to clear; sessions stay in IndexedDB/Local Storage)
    for browser in ("google-chrome", "chromium", "BraveSoftware/Brave-Browser", "microsoft-edge"):
        base = home / ".config" / browser
        if not base.is_dir():
            continue
        try:
            profiles = list(base.iterdir())
        except OSError:
            continue
        for profile in profiles:
            if not profile.is_dir() or profile.is_symlink():
                continue
            for name in ("Cache", "Code Cache", "GPUCache", "Service Worker"):
                reclaim_paths.append(profile / name)

    ai_paths = [
        preferred_models_dir(home),
        home / ".local" / "share" / "DevOS" / "models",
        Path("/var/lib/DevOS/models"),
        home / ".cache" / "huggingface",
        home / ".cache" / "whisper",
        home / ".cache" / "torch",
    ]

    # Measure categories independently so a large /usr does not starve the rest
    system = _sum_existing(system_paths)
    apps = _sum_existing(app_paths)
    personal = _sum_existing(personal_paths)
    reclaimable = _sum_existing(reclaim_paths)
    ai = _sum_existing(ai_paths)

    try:
        usage = shutil.disk_usage(mount)
        total, free, used = usage.total, usage.free, usage.used
    except OSError:
        total = free = used = 0

    accounted = system + apps + personal + reclaimable + ai
    other = max(0, used - accounted) if used else 0

    categories = [
        {"id": "system", "label": "DevOS system", "size": system,
         "hint": "Core OS under /usr — typically ~12–18 GB, leaner than Windows 11."},
        {"id": "personal", "label": "Your files", "size": personal,
         "hint": "Projects, Documents, Downloads and media."},
        {"id": "apps", "label": "Apps & containers", "size": apps,
         "hint": "Flatpak runtimes and container images."},
        {"id": "ai", "label": "AI models", "size": ai,
         "hint": "Offline models. Prefer storing these on D: when available."},
        {"id": "reclaimable", "label": "Freeable caches", "size": reclaimable,
         "hint": "Browser/app caches and Trash — safe via Optimizer."},
        {"id": "other", "label": "Other", "size": other,
         "hint": "Configs, browsers, editor data, and uncategorized paths."},
    ]

    tip = None
    if reclaimable >= 2 * GB:
        tip = f"Free about {human_size(reclaimable)} of caches with Optimizer."
    elif apps >= 5 * GB:
        tip = "Large Flatpak/container images are on C:. Move heavy work to D: or prune unused images."
    elif ai >= 1 * GB and secondary_data_roots(home):
        tip = "Move AI models to D: so DevOS (C:) stays free for the system."
    elif personal >= 10 * GB and secondary_data_roots(home):
        tip = "Most used space is your projects — keep them on D: when possible."
    else:
        tip = "DevOS system itself is compact; most used space is your apps and files."

    summary = (
        f"OS {human_size(system)} · Your files {human_size(personal)} · "
        f"Apps {human_size(apps)} · Freeable {human_size(reclaimable)}"
    )

    return {
        "mount": mount,
        "total": total,
        "free": free,
        "used": used,
        "categories": categories,
        "summary": summary,
        "tip": tip,
        "models_dir": str(preferred_models_dir(home)),
        "secondary_roots": [str(p) for p in secondary_data_roots(home)],
    }


def analyze_quick(home: Optional[Path] = None, mount: str = "/") -> Tuple[str, str]:
    """Return (summary_line, tip) for UI labels."""
    report = analyze(home=home, mount=mount)
    return report["summary"], report["tip"]


if __name__ == "__main__":
    import json
    print(json.dumps(analyze(), indent=2))
