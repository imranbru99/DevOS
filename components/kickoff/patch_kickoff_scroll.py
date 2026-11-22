#!/usr/bin/env python3
"""Keep the Start Menu on All Applications while that list is scrolled.

Kickoff resets the sidebar to row 0 (Favorites) when the application model
reloads, and a hover over the category list does the same thing. Scrolling
All Applications then replaces the full list with Favorites. A category
changes only when it is clicked or chosen with the keyboard.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

MARKER = "devos-keep-category-while-scrolling"

KICKOFF_REL = Path("usr/share/plasma/plasmoids/org.kde.plasma.kickoff")

LIST_HOLD = """
        // devos-keep-category-while-scrolling
        // Do not bind the row to the model size. That binding sends this
        // list back to Favorites whenever applications are reloaded.
        property int devosHeldIndex: -1
        property bool devosRestoring: false
        onCurrentIndexChanged: {
            if (devosRestoring) {
                return
            }
            if (currentIndex > 0) {
                devosHeldIndex = currentIndex
                return
            }
            if (root.devosUserDriving || root.devosUserPick === 0) {
                devosHeldIndex = 0
                return
            }
            if (devosHeldIndex > 0 && devosHeldIndex < count) {
                var devosKeep = devosHeldIndex
                devosRestoring = true
                currentIndex = devosKeep
                devosRestoring = false
            }
        }
"""

LIST_PROPS = """
    // devos-keep-category-while-scrolling
    property int devosUserPick: -1
    property bool devosUserDriving: false
    function devosNoteUserPick(index) {
        devosUserPick = index
        devosUserDriving = true
        devosDriveTimer.restart()
    }
    Timer {
        id: devosDriveTimer
        interval: 400
        onTriggered: root.devosUserDriving = false
    }
"""

EXPANDED = """function onExpandedChanged() {
                // devos-keep-category-while-scrolling
                // Do not send the open menu back to Favorites.
            }"""

CATEGORY_GUARD = """{
            // devos-keep-category-while-scrolling
            if (root.isCategoryListItem) {
                return
            }
"""

PRESS_NOTE = re.compile(
    r"(// Select and focus on press to improve responsiveness and touch feedback\n)"
    r"([ \t]+)view\.currentIndex = index"
)

STICK_PROPERTY = """id: root
    // devos-keep-category-while-scrolling
    property int devosStickCategory: 0
"""

STICK_HANDLER = """function onCurrentIndexChanged() {
                // devos-keep-category-while-scrolling
                var devosBar = root.sideBarItem
                if (devosBar && devosBar.currentIndex > 0) {
                    root.devosStickCategory = devosBar.currentIndex
                } else if (devosBar && devosBar.currentIndex === 0 && root.devosStickCategory > 0
                        && !devosBar.devosUserDriving && devosBar.devosUserPick !== 0) {
                    var devosKeep = root.devosStickCategory
                    if (devosKeep < devosBar.count) {
                        devosBar.currentIndex = devosKeep
                    }
                    return
                } else if (devosBar && devosBar.currentIndex === 0) {
                    root.devosStickCategory = 0
                }
"""


class PatchError(RuntimeError):
    pass


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected 1 match, found {count}")
    return text.replace(old, new, 1)


def patch_list_view(text: str) -> str:
    if MARKER in text:
        return text
    text = _replace_once(
        text,
        "    property bool hasSectionView: false\n",
        "    property bool hasSectionView: false\n" + LIST_PROPS,
        "KickoffListView properties",
    )
    text = _replace_once(
        text,
        "        currentIndex: count > 0 ? 0 : -1\n",
        LIST_HOLD,
        "KickoffListView currentIndex binding",
    )
    if "function onExpandedChanged()" not in text:
        raise PatchError("KickoffListView is missing onExpandedChanged")
    start = text.find("function onExpandedChanged()")
    end = text.find("Connections {", start)
    # The handler lives inside the first Connections block. Cut through its closing brace.
    brace = text.find("{", start)
    depth = 0
    close = None
    for index in range(brace, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                close = index + 1
                break
    if close is None:
        raise PatchError("KickoffListView onExpandedChanged is not closed")
    text = text[:start] + EXPANDED + text[close:]
    hover_old = "hoverEnabled: mainContentView || Plasmoid.configuration.switchCategoryOnHover"
    if text.count(hover_old) == 2:
        text = text.replace(hover_old, "hoverEnabled: root.mainContentView")
    elif text.count("        hoverEnabled: true\n") >= 2:
        text = text.replace("        hoverEnabled: true\n", "        hoverEnabled: root.mainContentView\n", 2)
    else:
        raise PatchError("KickoffListView category hover switches were not found")
    if "Keys.onPressed: event => {" in text:
        text = _replace_once(
            text,
            "Keys.onPressed: event => {\n",
            "Keys.onPressed: event => {\n            root.devosNoteUserPick(currentIndex)\n",
            "KickoffListView keys",
        )
    else:
        text = _replace_once(
            text,
            "Keys.onPressed: {\n",
            "Keys.onPressed: {\n            root.devosNoteUserPick(currentIndex)\n",
            "KickoffListView keys",
        )
    return text


def patch_delegate(text: str) -> str:
    if MARKER in text:
        return text
    if "onEntered: {" in text:
        text = _replace_once(text, "onEntered: {", "onEntered: " + CATEGORY_GUARD, "delegate onEntered")
    elif "onPositionChanged: {" in text:
        text = _replace_once(
            text,
            "onPositionChanged: {",
            "onPositionChanged: " + CATEGORY_GUARD,
            "delegate onPositionChanged",
        )
    else:
        raise PatchError("delegate hover handler was not found")
    match = PRESS_NOTE.search(text)
    if match is None:
        raise PatchError("delegate press: expected 1 match, found 0")
    if len(PRESS_NOTE.findall(text)) != 1:
        raise PatchError("delegate press: expected 1 match")
    indent = match.group(2)
    note = (
        f"{match.group(1)}"
        f"{indent}var devosPage = view\n"
        f"{indent}while (devosPage && !devosPage.devosNoteUserPick) {{\n"
        f"{indent}    devosPage = devosPage.parent\n"
        f"{indent}}}\n"
        f"{indent}if (devosPage) {{\n"
        f"{indent}    devosPage.devosNoteUserPick(index)\n"
        f"{indent}}}\n"
        f"{indent}view.currentIndex = index"
    )
    text = PRESS_NOTE.sub(note, text, count=1)
    text = text.replace(
        "acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad | PointerDevice.Stylus",
        "acceptedDevices: PointerDevice.Mouse | PointerDevice.Stylus",
    )
    return text


def patch_applications_page(text: str) -> str:
    if MARKER in text:
        return text
    text = _replace_once(text, "id: root\n", STICK_PROPERTY, "ApplicationsPage id")
    text = _replace_once(
        text,
        "function onCurrentIndexChanged() {\n",
        STICK_HANDLER,
        "ApplicationsPage category handler",
    )
    return text


def patch_kickoff_tree(root: Path) -> list[str]:
    ui = root / "contents" / "ui"
    if not ui.is_dir():
        raise PatchError(f"Kickoff UI was not found at {ui}")
    changed: list[str] = []
    jobs = {
        "KickoffListView.qml": patch_list_view,
        "AbstractKickoffItemDelegate.qml": patch_delegate,
        "ApplicationsPage.qml": patch_applications_page,
    }
    for name, patch in jobs.items():
        path = ui / name
        if not path.is_file():
            raise PatchError(f"missing {path}")
        original = path.read_text(encoding="utf-8")
        updated = patch(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(str(path))
    return changed


def patch_appletsrc(text: str) -> str:
    """Turn off hover category changes for every Kickoff applet."""
    lines = text.splitlines()
    headers: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if line.startswith("[") and line.endswith("]"):
            headers.append((index, line))
    kickoff_groups: list[str] = []
    for position, (index, name) in enumerate(headers):
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        body = lines[index + 1:end]
        if "plugin=org.kde.plasma.kickoff" in body:
            kickoff_groups.append(name)
    if not kickoff_groups:
        return text
    for group in kickoff_groups:
        header = group + "[Configuration][General]"
        if header in lines:
            start = lines.index(header) + 1
            end = start
            while end < len(lines) and not lines[end].startswith("["):
                end += 1
            keys = lines[start:end]
            replaced = False
            for offset, key in enumerate(keys):
                if key.startswith("switchCategoryOnHover="):
                    keys[offset] = "switchCategoryOnHover=false"
                    replaced = True
            if not replaced:
                keys.append("switchCategoryOnHover=false")
            lines[start:end] = keys
        else:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(header)
            lines.append("switchCategoryOnHover=false")
    result = "\n".join(lines)
    if text.endswith("\n"):
        result += "\n"
    return result


def patch_user_configs(home: Path | None = None) -> list[str]:
    homes = []
    if home is not None:
        homes.append(home)
    else:
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user and sudo_user != "root":
            homes.append(Path("/home") / sudo_user)
        homes.append(Path.home())
        homes.append(Path("/etc/skel"))
    changed: list[str] = []
    seen: set[Path] = set()
    for candidate in homes:
        path = candidate / ".config" / "plasma-org.kde.plasma.desktop-appletsrc"
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        original = path.read_text(encoding="utf-8")
        updated = patch_appletsrc(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(str(path))
    return changed


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("/") / KICKOFF_REL
    if not root.exists():
        print(f"Kickoff is not installed at {root}")
        return 0
    try:
        changed = patch_kickoff_tree(root)
    except PatchError as exc:
        print(f"Could not update the Start Menu: {exc}", file=sys.stderr)
        return 1
    configs = patch_user_configs()
    if changed:
        print("Updated:")
        for path in changed:
            print(f"  {path}")
    else:
        print("Start Menu scroll fix is already installed.")
    for path in configs:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
