#!/usr/bin/env python3
"""Generate branded DevOS SVG app icons for every Icon=devos-* desktop entry.

Only creates missing files — existing hand-authored icons are left alone.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "build/includes.chroot/usr/share/applications"
OUT = ROOT / "build/includes.chroot/usr/share/icons/hicolor/scalable/apps"

GLYPHS = {
    "about": '<circle cx="32" cy="24" r="10"/><path d="M20 52q12-16 24 0"/><circle cx="32" cy="22" r="2" fill="#f1f7ff" stroke="none"/>',
    "ai-models": '<path d="M18 40V24l14-8 14 8v16l-14 8z"/><path d="M32 16v32 M18 24l14 8 14-8"/>',
    "apphub": '<rect x="16" y="16" width="14" height="14" rx="3"/><rect x="34" y="16" width="14" height="14" rx="3"/><rect x="16" y="34" width="14" height="14" rx="3"/><rect x="34" y="34" width="14" height="14" rx="3"/>',
    "apps": '<rect x="14" y="18" width="36" height="28" rx="4"/><path d="M20 26h24 M20 32h18 M20 38h12"/>',
    "backup": '<path d="M20 40V24h24v16"/><path d="M24 28h16"/><path d="M32 20v28 M26 42l6 6 6-6"/>',
    "chat": '<path d="M16 20h32a6 6 0 0 1 6 6v14a6 6 0 0 1-6 6H28l-8 8v-8h-4a6 6 0 0 1-6-6V26a6 6 0 0 1 6-6z"/>',
    "dashboard": '<rect x="14" y="14" width="16" height="16" rx="3"/><rect x="34" y="14" width="16" height="36" rx="3"/><rect x="14" y="34" width="16" height="16" rx="3"/>',
    "islamic": '<path d="M34 14a16 16 0 1 0 0 36 14 14 0 0 1 0-36z"/><path d="M42 18l2 5 5 1-4 3 1 5-4-3-4 3 1-5-4-3 5-1z"/>',
    "notepad": '<rect x="18" y="12" width="28" height="40" rx="3"/><path d="M24 22h16 M24 30h16 M24 38h12"/>',
    "notes": '<rect x="18" y="14" width="28" height="36" rx="3"/><path d="M24 24h16 M24 32h12"/><path d="M40 14v10l5-5"/>',
    "optimizer": '<circle cx="32" cy="32" r="14"/><path d="M32 18v6 M32 40v6 M18 32h6 M40 32h6 M22 22l4 4 M38 38l4 4 M42 22l-4 4 M26 38l-4 4"/>',
    "phonelink": '<rect x="22" y="12" width="20" height="36" rx="4"/><path d="M28 42h8"/><path d="M14 28h6 M44 28h6"/>',
    "restore": '<path d="M20 32a12 12 0 1 0 4-8"/><path d="M18 18v10h10"/><path d="M28 40h12v-8"/>',
    "security": '<path d="M32 12 48 20v12c0 12-10 20-16 22-6-2-16-10-16-22V20z"/><path d="M26 32l4 4 8-10"/>',
    "settings": '<circle cx="32" cy="32" r="8"/><path d="M32 14v6 M32 44v6 M14 32h6 M44 32h6 M20 20l4 4 M40 40l4 4 M44 20l-4 4 M24 40l-4 4"/>',
    "taskman": '<path d="M14 18h36v8H14z M14 30h36v8H14z M14 42h36v8H14z"/><path d="M20 22h8 M20 34h14 M20 46h10"/>',
    "vault": '<rect x="16" y="26" width="32" height="24" rx="4"/><path d="M24 26v-6a8 8 0 0 1 16 0v6"/><circle cx="32" cy="38" r="3"/>',
    "winlayer": '<rect x="14" y="18" width="36" height="28" rx="3"/><path d="M14 26h36 M32 26v20"/>',
    "kids-mode": '<circle cx="32" cy="24" r="8"/><path d="M18 48q14-16 28 0"/><path d="M24 22h2 M38 22h2 M26 28q6 6 12 0"/>',
    "code": '<path d="M24 20 14 32l10 12 M40 20l10 12-10 12 M36 18 28 46"/>',
    "code-agent": '<path d="M20 22h24v20H20z"/><path d="M26 30h12 M26 36h8"/><path d="M32 14v8 M28 14h8"/>',
    "browser": '<circle cx="32" cy="32" r="18"/><path d="M14 32h36 M32 14c6 6 10 12 10 18s-4 12-10 18c-6-6-10-12-10-18s4-12 10-18z"/>',
    "sound": '<path d="M18 26h8l10-8v28l-10-8h-8z"/><path d="M42 24q6 8 0 16 M46 20q10 12 0 24"/>',
    "display": '<rect x="12" y="16" width="40" height="26" rx="3"/><path d="M24 48h16 M32 42v6"/>',
    "power": '<path d="M32 14v18"/><path d="M22 22a14 14 0 1 0 20 0"/>',
    "refresh": '<path d="M20 24a14 14 0 1 1-2 10"/><path d="M16 16v12h12"/>',
    "fingerprint": '<path d="M32 14a14 14 0 0 1 14 14v10"/><path d="M32 18a10 10 0 0 1 10 10v12"/><path d="M32 22a6 6 0 0 1 6 6v16"/><path d="M32 26v22"/>',
    "thispc": '<rect x="12" y="16" width="40" height="26" rx="3"/><path d="M20 48h24 M28 42v6 M36 42v6"/>',
    "cursor-agent": '<path d="M20 16 44 32 32 36 28 48z"/>',
    "ai-code-agent": '<path d="M20 22h24v20H20z"/><path d="M26 30h12 M26 36h8"/><path d="M32 14v8"/>',
    "ai-pipeline": '<path d="M14 32h10l6-10 8 20 6-10h10"/>',
    "logo": '<circle cx="32" cy="32" r="16"/><path d="M24 32h16 M32 24v16"/>',
}

COLORS = [
    ("#2563eb", "#0f172a"),
    ("#0ea5e9", "#082f49"),
    ("#8a63da", "#14243d"),
    ("#10b981", "#064e3b"),
    ("#f59e0b", "#422006"),
    ("#ef4444", "#450a0a"),
    ("#ec4899", "#500724"),
    ("#14b8a6", "#134e4a"),
]


def svg_for(icon_id: str) -> str:
    key = icon_id.removeprefix("devos-")
    glyph = GLYPHS.get(key)
    if not glyph:
        letter = (key[:1] or "D").upper()
        glyph = (
            f'<text x="32" y="40" text-anchor="middle" fill="#f1f7ff" '
            f'font-size="28" font-family="sans-serif" font-weight="700" stroke="none">{letter}</text>'
        )
    c1, c2 = COLORS[sum(ord(c) for c in icon_id) % len(COLORS)]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
        f'<defs><linearGradient id="g" x2="1" y2="1">'
        f'<stop stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
        f'</linearGradient></defs>'
        f'<rect x="2" y="2" width="60" height="60" rx="17" fill="url(#g)"/>'
        f'<g fill="none" stroke="#f1f7ff" stroke-width="2.5" '
        f'stroke-linecap="round" stroke-linejoin="round">{glyph}</g></svg>\n'
    )


def needed_icons() -> set[str]:
    found: set[str] = {f"devos-{k}" for k in GLYPHS}
    for desk in APPS.glob("devos-*.desktop"):
        for line in desk.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Icon=devos-"):
                found.add(line.split("=", 1)[1].strip())
    return found


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    created = 0
    for icon_id in sorted(needed_icons()):
        if not re.fullmatch(r"devos-[a-z0-9-]+", icon_id):
            continue
        path = OUT / f"{icon_id}.svg"
        if path.is_file():
            continue
        path.write_text(svg_for(icon_id), encoding="utf-8")
        created += 1
        print("created", path.name)
    print(f"done; created={created}; total={len(list(OUT.glob('devos-*.svg')))}")


if __name__ == "__main__":
    main()
