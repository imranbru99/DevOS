#!/usr/bin/env python3
"""Installer catalog must offer Cursor Agent + both Antigravity slots with real backends."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "features"))

import feature_catalog as catalog  # noqa: E402


def _by_id(fid: str) -> dict:
    return next(f for f in catalog.FEATURES if f["id"] == fid)


def test_ai_coding_agents_in_developer_catalog():
    for fid in ("antigravity", "antigravity-kde", "cursor", "cursor-agent", "chatgpt", "claude", "codex"):
        feat = _by_id(fid)
        assert feat["category"] == "developer"
        assert "developer" in feat["presets"]


def test_antigravity_and_kde_have_install_hooks():
    ag = _by_id("antigravity")
    kde = _by_id("antigravity-kde")
    assert ag["script"] == "/usr/local/sbin/devos-install-antigravity"
    assert ag["detect"]
    assert "antigravity.desktop" in (ag.get("builtin") or {}).get("desktop", [])
    assert kde["script"] == "/usr/local/sbin/devos-install-antigravity-kde"
    assert "antigravity-kde.desktop" in (kde.get("builtin") or {}).get("desktop", [])


def test_cursor_agent_has_install_hook():
    ca = _by_id("cursor-agent")
    assert ca["script"] == "/usr/local/sbin/devos-install-cursor-agent"
    assert "/usr/local/bin/cursor-agent" in ca["detect"]
    assert "devos-cursor-agent.desktop" in (ca.get("builtin") or {}).get("desktop", [])


def test_features_catalog_js_mentions_new_agents():
    js = (ROOT / "build/includes.chroot/etc/calamares/branding/devos/features-catalog.js").read_text(encoding="utf-8")
    for fid in ("antigravity-kde", "cursor-agent", "antigravity", "cursor"):
        assert f'"id": "{fid}"' in js or f'"id":"{fid}"' in js
