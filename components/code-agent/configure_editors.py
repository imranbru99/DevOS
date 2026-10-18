#!/usr/bin/env python3
"""
Runs at login (/etc/xdg/autostart/devos-code-agent-setup.desktop).

1. VS Code + Continue: when this PC's DevOS AI can code (capability.py), add
   a "DevOS AI Code (Local)" model (devos-ai-code) for chat, edit and agent
   mode to ~/.continue/config.json, and tab autocomplete when the Coding
   model is installed. When it cannot, take those entries out again.
   Only DevOS-managed entries are touched: an entry is ours when it still
   equals what this script wrote last time (remembered in
   ~/.config/devos/code-agent-editors.json) or the stock /etc/skel value.
   Anything the person changed or removed stays as they left it, and the
   file is only rewritten when something actually changes.

2. The "DevOS AI Code Agent" menu entry: /usr/share/applications is shared by
   every account and is part of the system image, but whether the agent is
   useful depends on the models on this PC, which change after install (DevOS
   AI Models). So the entry is hidden per user: a copy with NoDisplay=true in
   ~/.local/share/applications/ overrides the system file of the same name
   (XDG desktop-file-id lookup prefers the user's data dir). The copy carries
   X-DevOS-Managed so it is removed again once the PC can code, and an
   override the person made themselves is never touched.
"""

import copy
import json
import os
import subprocess
import sys
from typing import Dict, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

API_BASE = "http://127.0.0.1:11434/v1"
API_KEY = "devos-offline-key"
AGENT_TITLE = "DevOS AI Code (Local)"
AUTOCOMPLETE_TITLE = "DevOS AI Autocomplete"
ROLES = ("inlineEdit", "applyCodeBlock")

SYSTEM_DESKTOP = "/usr/share/applications/devos-ai-code-agent.desktop"
DESKTOP_NAME = "devos-ai-code-agent.desktop"
MANAGED_KEY = "X-DevOS-Managed"
MANAGED_VALUE = "code-agent-gate"

# What /etc/skel/.continue/config.json ships: still ours while unchanged.
SKEL_AUTOCOMPLETE = {
    "title": AUTOCOMPLETE_TITLE,
    "provider": "openai",
    "model": "qwen2.5-coder-1.5b",
    "apiBase": API_BASE,
    "apiKey": API_KEY,
}


def agent_model() -> Dict:
    return {
        "title": AGENT_TITLE,
        "provider": "openai",
        "model": "devos-ai-code",
        "apiBase": API_BASE,
        "apiKey": API_KEY,
        "contextLength": 8192,
        "completionOptions": {"maxTokens": 1536, "temperature": 0.2},
        "capabilities": {"tools": True},
    }


def autocomplete_model() -> Dict:
    return {
        "title": AUTOCOMPLETE_TITLE,
        "provider": "openai",
        "model": "devos-ai-code",
        "apiBase": API_BASE,
        "apiKey": API_KEY,
    }


def merge_continue(config: Dict, capable: bool, coder: bool, state: Dict) -> Tuple[Dict, Dict]:
    """Return (new config, new state). Pure: the inputs are not modified."""
    config = copy.deepcopy(config) if isinstance(config, dict) else {}
    state = copy.deepcopy(state) if isinstance(state, dict) else {}

    # --- chat / edit / agent model
    models = config.get("models")
    if not isinstance(models, list):
        models = []
    index = next((i for i, m in enumerate(models)
                  if isinstance(m, dict) and m.get("title") == AGENT_TITLE), None)
    ours = index is not None and models[index] == state.get("model")
    if capable:
        wanted = agent_model()
        if index is None:
            if "model" not in state:          # never added, or removed by us: add it
                models.insert(0, wanted)       # first = Continue's default model
                state["model"] = copy.deepcopy(wanted)
        elif ours:
            models[index] = wanted
            state["model"] = copy.deepcopy(wanted)
    else:
        if ours:
            models.pop(index)
        if index is None or ours:
            state.pop("model", None)
    if models or "models" in config:
        config["models"] = models

    # --- tab autocomplete (only with the Coding model)
    current = config.get("tabAutocompleteModel")
    ours = current is not None and (current == state.get("autocomplete") or current == SKEL_AUTOCOMPLETE)
    if coder and capable:
        wanted = autocomplete_model()
        if current is None and "autocomplete" not in state or ours:
            config["tabAutocompleteModel"] = wanted
            state["autocomplete"] = copy.deepcopy(wanted)
    else:
        if ours:
            del config["tabAutocompleteModel"]
        if current is None or ours:
            state.pop("autocomplete", None)

    # --- edit / apply roles point at the agent model
    experimental = config.get("experimental") if isinstance(config.get("experimental"), dict) else None
    roles = experimental.get("modelRoles") if experimental and isinstance(experimental.get("modelRoles"), dict) else None
    set_roles = state.get("roles", [])
    if capable and any(m.get("title") == AGENT_TITLE for m in models if isinstance(m, dict)):
        for role in ROLES:
            value = (roles or {}).get(role)
            if value is None and role not in set_roles:
                if experimental is None:
                    experimental = config.setdefault("experimental", {})
                if roles is None:
                    roles = experimental.setdefault("modelRoles", {})
                roles[role] = AGENT_TITLE
                set_roles = sorted(set(set_roles) | {role})
    else:
        removed = False
        for role in list(set_roles):
            if roles is not None and roles.get(role) == AGENT_TITLE:
                del roles[role]
                removed = True
            set_roles = [r for r in set_roles if r != role]
        if removed and not roles:
            del experimental["modelRoles"]
            if not experimental:
                del config["experimental"]
    if set_roles:
        state["roles"] = set_roles
    else:
        state.pop("roles", None)
    return config, state


# ------------------------------------------------------------------ files

def _read_json(path: str) -> Tuple[Optional[Dict], bool]:
    """(data, ok). Missing file -> ({}, True); unreadable/invalid -> (None, False)."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return (data if isinstance(data, dict) else None), isinstance(data, dict)
    except FileNotFoundError:
        return {}, True
    except (OSError, ValueError):
        return None, False


def _write_json(path: str, data: Dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".devos-tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


def update_continue(home: str, capable: bool, coder: bool) -> bool:
    """Apply merge_continue to the files in `home`. True when config.json changed."""
    config_path = os.path.join(home, ".continue", "config.json")
    state_path = os.path.join(home, ".config", "devos", "code-agent-editors.json")
    config, ok = _read_json(config_path)
    if not ok:
        # Comments or a typo the person is still fixing: never overwrite it.
        sys.stderr.write(f"[devos-code-agent] {config_path} is not plain JSON; left unchanged.\n")
        return False
    state, _ = _read_json(state_path)
    new_config, new_state = merge_continue(config, capable, coder, state or {})
    changed = new_config != config
    if changed and (new_config or os.path.exists(config_path)):
        _write_json(config_path, new_config)
    if new_state != (state or {}):
        _write_json(state_path, new_state)
    return changed


def desktop_override_text(system_text: str) -> str:
    out, in_main, done = [], False, False
    for line in system_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_main and not done:
                out += ["NoDisplay=true", f"{MANAGED_KEY}={MANAGED_VALUE}"]
                done = True
            in_main = stripped == "[Desktop Entry]"
        elif in_main and (stripped.startswith("NoDisplay=") or stripped.startswith(MANAGED_KEY + "=")):
            continue
        out.append(line)
    if in_main and not done:
        out += ["NoDisplay=true", f"{MANAGED_KEY}={MANAGED_VALUE}"]
    return "\n".join(out) + "\n"


def update_menu_entry(home: str, capable: bool, system_entry: str = SYSTEM_DESKTOP) -> bool:
    """Hide or show the menu entry for this user. True when something changed."""
    override = os.path.join(home, ".local", "share", "applications", DESKTOP_NAME)
    existing = None
    try:
        with open(override, encoding="utf-8") as handle:
            existing = handle.read()
    except OSError:
        pass
    ours = existing is not None and f"{MANAGED_KEY}={MANAGED_VALUE}" in existing
    if capable:
        if ours:
            os.remove(override)
            return True
        return False
    if existing is not None and not ours:
        return False  # the person's own override
    try:
        with open(system_entry, encoding="utf-8") as handle:
            wanted = desktop_override_text(handle.read())
    except OSError:
        return False
    if existing == wanted:
        return False
    os.makedirs(os.path.dirname(override), exist_ok=True)
    with open(override, "w", encoding="utf-8") as handle:
        handle.write(wanted)
    return True


def refresh_menu() -> None:
    for tool in ("kbuildsycoca5", "update-desktop-database"):
        try:
            args = [tool] if tool == "kbuildsycoca5" else [tool, os.path.expanduser("~/.local/share/applications")]
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            continue


def main(argv=None) -> int:
    import capability
    home = os.path.expanduser("~")
    capable, reason = capability.coding_capable()
    coder = capability.coder_installed()
    changed = update_continue(home, capable, coder)
    menu = update_menu_entry(home, capable)
    if menu:
        refresh_menu()
    if "--quiet" not in (argv if argv is not None else sys.argv[1:]):
        print(f"DevOS AI Code Agent: {'available' if capable else 'hidden'} ({reason})"
              f"{' · Continue updated' if changed else ''}{' · menu updated' if menu else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
