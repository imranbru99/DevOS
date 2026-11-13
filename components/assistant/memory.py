#!/usr/bin/env python3
"""
Durable local memory for DevOS AI — preferences and facts that survive chats.

Premium desktop agents (Copilot / Claude Cowork style) keep user context across
sessions. Everything stays on this PC under ~/.local/share/devos/assistant/.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional

DATA_DIR = Path(os.path.expanduser("~/.local/share/devos/assistant"))
MEMORY_FILE = DATA_DIR / "memory.json"
MAX_FACTS = 80
MAX_FACT_LEN = 240


def _default() -> dict:
    return {"facts": [], "prefs": {}, "updated": 0}


def load(path: Optional[Path] = None) -> dict:
    p = path or MEMORY_FILE
    try:
        with p.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return _default()
        data.setdefault("facts", [])
        data.setdefault("prefs", {})
        return data
    except (OSError, ValueError, TypeError):
        return _default()


def save(data: dict, path: Optional[Path] = None) -> None:
    p = path or MEMORY_FILE
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = dict(data or {})
    data["updated"] = int(time.time())
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(p.parent), delete=False
    ) as fh:
        pending = Path(fh.name)
        try:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
            fh.close()
            pending.replace(p)
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
        finally:
            pending.unlink(missing_ok=True)


def remember(fact: str, path: Optional[Path] = None) -> str:
    """Store a short fact. Returns the cleaned fact."""
    text = re.sub(r"\s+", " ", (fact or "").strip())
    text = re.sub(
        r"^(?:that\s+|i\s+(?:want\s+you\s+to\s+)?remember\s+(?:that\s+)?)",
        "",
        text,
        flags=re.I,
    ).strip(" .")
    if not text or len(text) < 2:
        raise ValueError("Tell me what to remember in a short sentence.")
    text = text[:MAX_FACT_LEN]
    data = load(path)
    facts: List[dict] = [f for f in data.get("facts") or [] if isinstance(f, dict)]
    # Dedup (case-insensitive)
    low = text.lower()
    facts = [f for f in facts if str(f.get("text") or "").lower() != low]
    facts.append({"text": text, "ts": int(time.time())})
    data["facts"] = facts[-MAX_FACTS:]
    save(data, path)
    return text


def forget(query: str, path: Optional[Path] = None) -> int:
    """Remove facts containing query. Returns how many were removed."""
    q = (query or "").strip().lower()
    if not q:
        return 0
    data = load(path)
    facts = [f for f in data.get("facts") or [] if isinstance(f, dict)]
    kept = [f for f in facts if q not in str(f.get("text") or "").lower()]
    removed = len(facts) - len(kept)
    if removed:
        data["facts"] = kept
        save(data, path)
    return removed


def set_pref(key: str, value: str, path: Optional[Path] = None) -> None:
    key = re.sub(r"[^a-z0-9_]+", "_", (key or "").strip().lower())[:40]
    if not key:
        raise ValueError("Missing preference key.")
    data = load(path)
    prefs: Dict[str, str] = dict(data.get("prefs") or {})
    prefs[key] = str(value)[:200]
    data["prefs"] = prefs
    save(data, path)


def summary_for_prompt(path: Optional[Path] = None, limit: int = 12) -> str:
    """Compact block injected into the chat system prompt."""
    data = load(path)
    lines: List[str] = []
    prefs = data.get("prefs") or {}
    if isinstance(prefs, dict) and prefs:
        for k, v in list(prefs.items())[:8]:
            lines.append(f"- prefer {k}: {v}")
    facts = [f for f in (data.get("facts") or []) if isinstance(f, dict)]
    for f in facts[-limit:]:
        t = str(f.get("text") or "").strip()
        if t:
            lines.append(f"- {t}")
    if not lines:
        return ""
    return (
        "\n\n[User memory — local, from earlier chats. Use when relevant; "
        "do not invent extra facts]:\n" + "\n".join(lines)
    )


def list_facts(path: Optional[Path] = None) -> List[str]:
    data = load(path)
    return [str(f.get("text") or "") for f in (data.get("facts") or []) if isinstance(f, dict) and f.get("text")]
