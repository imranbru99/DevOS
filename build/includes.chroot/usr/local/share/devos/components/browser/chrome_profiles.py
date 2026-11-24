#!/usr/bin/env python3
"""
DevOS Chrome Profile & Icon Manager

Windows-like Chrome taskbar:
  - Idle pin = Google Chrome logo
  - While profiles run = one avatar icon per open profile (never grouped)
  - When all close = restore the Google Chrome pin

Uses distinct WM classes (chrome-<profile>) and Plasma Icon Tasks launcher swap.
"""

import ctypes
import glob
import hashlib
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def get_chrome_profiles(config_dir=None):
    """Read all profiles from Google Chrome Local State."""
    if not config_dir:
        config_dir = os.path.expanduser("~/.config/google-chrome")
    local_state_file = os.path.join(config_dir, "Local State")
    profiles = {}
    if os.path.isfile(local_state_file):
        try:
            with open(local_state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            cache = data.get("profile", {}).get("info_cache", {})
            for key, val in cache.items():
                profiles[key] = profile_label(val if isinstance(val, dict) else {}, key)
        except Exception:
            pass
    # Never invent fake "Work" / Guest Start-menu apps. Empty Chrome config =
    # no profile list yet (user opens Chrome and creates profiles there).
    return profiles


def _is_usable_profile_photo(path: str) -> bool:
    """True for real Gaia photos — reject Chrome default circle+person silhouettes.

    Chrome's unsigned-in / default avatars are flat colored circles with a white
    or gray person shape. Those look "colorful" (green/blue/orange bg) so a
    naive saturation check wrongly treats them as photos — then the taskbar
    badge becomes the same gray person the user sees in Chrome's profile chip.
    """
    if not path or not os.path.isfile(path):
        return False
    try:
        if os.path.getsize(path) < 400:
            return False
    except OSError:
        return False
    low = os.path.basename(path).lower()
    # Chrome ships generic avatar_* placeholders that look like the gray person.
    if low.startswith("avatar") or "placeholder" in low or "silhouette" in low:
        return False
    if "idr_profile_avatar" in low or "default_avatar" in low:
        return False
    try:
        raw = Image.open(path).convert("RGBA")
        # Built-in / theme avatars are small simple PNGs; real Gaia photos are larger.
        if max(raw.size) < 48:
            return False
        img = raw.resize((32, 32), Image.Resampling.NEAREST)
        pixels = list(img.getdata())
        if not pixels:
            return False

        opaque = [(r, g, b, a) for r, g, b, a in pixels if a >= 40]
        if len(opaque) < 40:
            return False

        # Quantize: Chrome default avatars use a handful of flat colors.
        buckets = {}
        grayish = 0
        colorful = 0
        for r, g, b, a in opaque:
            key = (r // 24, g // 24, b // 24)
            buckets[key] = buckets.get(key, 0) + 1
            mx, mn = max(r, g, b), min(r, g, b)
            if mx - mn <= 28 and mx >= 160:
                grayish += 1  # white/gray person shape
            if mx - mn > 28:
                colorful += 1

        unique = len(buckets)
        top = max(buckets.values()) if buckets else 0
        dominant_share = top / float(len(opaque))
        gray_share = grayish / float(len(opaque))

        # Flat badge: few unique colors + one dominant fill (the colored circle).
        if unique <= 14 and dominant_share >= 0.35:
            return False
        # Colored circle + light person silhouette (green/blue bg + white body).
        if gray_share >= 0.12 and unique <= 20 and dominant_share >= 0.28:
            return False
        # Real photos need many distinct colors — not a cartoon badge.
        if unique < 18:
            return False
        if colorful < max(12, len(opaque) // 8):
            return False
        return True
    except Exception:
        return False


def get_profile_avatar_path(config_dir, profile_key, info=None):
    """Return a real Google account photo, or None → letter-badge fallback."""
    if not config_dir or not profile_key or profile_key == "guest":
        return None
    folder = os.path.join(config_dir, profile_key)
    candidates = []
    info = info if isinstance(info, dict) else {}

    # A real account photo lives in the profile folder. Chrome still shows it
    # when the theme avatar id is set and use_gaia_picture was not written.
    picture_name = info.get("gaia_picture_file_name")
    if isinstance(picture_name, str) and picture_name and "/" not in picture_name:
        if picture_name.endswith((".png", ".jpg", ".jpeg", ".webp")):
            candidates.append(os.path.join(folder, picture_name))
    for name in (
        "Google Profile Picture.png",
        "Google Profile Picture.jpg",
        "Google Profile Picture.jpeg",
        "Google Profile Picture.webp",
    ):
        candidates.append(os.path.join(folder, name))
    try:
        for entry in os.listdir(folder):
            low = entry.lower()
            if "profile picture" in low or low.startswith("gaia"):
                candidates.append(os.path.join(folder, entry))
    except OSError:
        pass

    # One folder down as well. Chrome sometimes keeps the account picture
    # beside the profile, not only in the profile root.
    try:
        for entry in os.listdir(folder):
            nested = os.path.join(folder, entry)
            if not os.path.isdir(nested):
                continue
            for name in os.listdir(nested):
                low = name.lower()
                if "profile picture" in low or "gaia" in low:
                    candidates.append(os.path.join(nested, name))
    except OSError:
        pass

    # Chrome keeps the toolbar account photo here when it has not written
    # "Google Profile Picture.png" into the profile root.
    images_dir = os.path.join(folder, "Accounts", "Avatar Images")
    sized = []
    if os.path.isdir(images_dir):
        for root, _dirs, files in os.walk(images_dir):
            for name in files:
                path = os.path.join(root, name)
                try:
                    sized.append((os.path.getsize(path), path))
                except OSError:
                    continue
    sized.sort(reverse=True)
    for _size, path in sized:
        candidates.append(path)

    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if _accept_account_photo(path):
            return path
    return None


def _accept_account_photo(path: str) -> bool:
    """True for a Google account picture file.

    Files Chrome names as the account picture are the photo. The strict color
    check is only for unnamed images, so a real picture is not rejected for
    looking simple.
    """
    if not path or not os.path.isfile(path):
        return False
    low = os.path.basename(path).lower()
    parent = os.path.basename(os.path.dirname(path)).lower()
    named = (
        "profile picture" in low
        or "gaia" in low
        or parent == "avatar images"
        or os.path.basename(os.path.dirname(os.path.dirname(path))).lower() == "avatar images"
    )
    if not named:
        return _is_usable_profile_photo(path)
    try:
        if os.path.getsize(path) < 32:
            return False
        with Image.open(path) as img:
            if max(img.size) < 24:
                return False
        return True
    except Exception:
        return False


def get_chrome_profile_details(config_dir=None):
    """Map profile directory → {name, avatar} for icon generation."""
    if not config_dir:
        config_dir = os.path.expanduser("~/.config/google-chrome")
    details = {}
    local_state_file = os.path.join(config_dir, "Local State")
    cache = {}
    if os.path.isfile(local_state_file):
        try:
            with open(local_state_file, "r", encoding="utf-8") as f:
                cache = json.load(f).get("profile", {}).get("info_cache", {}) or {}
        except Exception:
            cache = {}
    profiles = get_chrome_profiles(config_dir)
    for key, name in profiles.items():
        info = cache.get(key) or {}
        details[key] = {
            "name": name,
            "avatar": get_profile_avatar_path(config_dir, key, info),
        }
    return details


def slugify(name):
    """Convert a profile name or key to a safe filename slug."""
    s = re.sub(r"[^\w\d]+", "-", name.strip().lower()).strip("-")
    return s or "default"


_GENERIC_PROFILE_NAMES = {
    "main",
    "your chrome",
    "chrome",
    "default",
    "user",
    "person 1",
}


def _is_generic_profile_name(name):
    """True for Chrome's own placeholder names, not a name the person chose."""
    key = (name or "").strip().lower()
    if key in _GENERIC_PROFILE_NAMES:
        return True
    return bool(re.fullmatch(r"(person|profile)\s+\d+", key))


def profile_label(info, fallback=""):
    """
    Name to show on the taskbar.

    Chrome's menu prints "IMRAN • Main": IMRAN is the Google account and Main
    is the leftover profile name. A badge built from Main is the letter M,
    the same letter as Mirza. Prefer the Google account when the profile name
    is still that placeholder.
    """
    if not isinstance(info, dict):
        info = {}
    name = (info.get("name") or "").strip()
    given = (info.get("gaia_given_name") or "").strip()
    if not given:
        full = (info.get("gaia_name") or "").strip()
        given = full.split()[0] if full else ""
    if _is_generic_profile_name(name) and given:
        return given
    return name or given or (fallback or "").strip() or "Chrome"


def badge_letter(name):
    """One capital letter for the taskbar pill. Mirza → M, IMRAN → I."""
    for ch in (name or ""):
        if ch.isalnum():
            return ch.upper()
    return "C"


def get_profile_color(name):
    """Return a distinct, high-contrast background color for each profile banner."""
    PRESET_COLORS = {
        "work": (26, 115, 232),      # Google Blue
        "default": (26, 115, 232),
        "blog": (216, 27, 96),       # Berry / Magenta
        "mirza": (13, 148, 136),     # Teal
        "tony": (124, 58, 237),      # Royal Purple
        "guest": (71, 85, 105),      # Slate Gray
        "traveling": (217, 119, 6),  # Amber
        "imran": (220, 38, 38),      # Crimson Red
        "nipun": (22, 163, 74),      # Emerald Green
    }
    key = name.strip().lower()
    if key in PRESET_COLORS:
        return PRESET_COLORS[key]

    PALETTE = [
        (26, 115, 232),
        (216, 27, 96),
        (13, 148, 136),
        (124, 58, 237),
        (217, 119, 6),
        (220, 38, 38),
        (22, 163, 74),
        (8, 145, 178),
        (234, 88, 12),
    ]
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)
    return PALETTE[h % len(PALETTE)]


def get_stock_chrome_icon():
    """Find the base clean Google Chrome icon."""
    for candidate in [
        "/usr/share/icons/hicolor/128x128/apps/google-chrome.png",
        "/usr/share/icons/hicolor/48x48/apps/google-chrome.png",
        "/usr/share/pixmaps/google-chrome.png",
    ]:
        if os.path.isfile(candidate):
            return candidate
    return None


def _circle_crop(avatar, size):
    """Return a circular RGBA avatar at the given pixel size."""
    av = avatar.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(av, (0, 0), mask)
    return out


def _profile_initial(name: str) -> str:
    """First letter of the profile name for badge fallback (Guest → G)."""
    text = (name or "").strip()
    if not text:
        return "C"
    for ch in text:
        if ch.isalnum():
            return ch.upper()
    return text[0].upper()


def _draw_letter_badge(img, name: str) -> None:
    """Paint a large colored first-letter badge (never the gray person silhouette)."""
    initial = _profile_initial(name)
    short = (name or "Chrome").strip().split()[0][:8] if (name or "").strip() else "Chrome"
    bg_color = get_profile_color(name or "Chrome")
    font = None
    font_sm = None
    for font_path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSans-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    ]:
        if os.path.isfile(font_path):
            try:
                font = ImageFont.truetype(font_path, 48)
                font_sm = ImageFont.truetype(font_path, 13)
                break
            except Exception:
                pass
    # Large corner badge so the letter stays readable at 48px taskbar size.
    badge_size = 76
    ring = 5
    outer = badge_size + ring * 2
    badge = Image.new("RGBA", (outer, outer), (0, 0, 0, 0))
    bdraw = ImageDraw.Draw(badge)
    bdraw.ellipse((0, 0, outer - 1, outer - 1), fill=(255, 255, 255, 250))
    bdraw.ellipse(
        (ring, ring, ring + badge_size - 1, ring + badge_size - 1),
        fill=bg_color + (255,),
    )
    if font:
        bdraw.text(
            (outer // 2, outer // 2 - 1),
            initial,
            fill=(255, 255, 255, 255),
            font=font,
            anchor="mm",
        )
    else:
        bdraw.text(
            (outer // 2, outer // 2),
            initial,
            fill=(255, 255, 255, 255),
            anchor="mm",
        )
    img.alpha_composite(badge, (128 - outer - 1, 128 - outer - 1))
    if font_sm and short:
        strip_h = 20
        strip = Image.new("RGBA", (128, strip_h), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(strip)
        sdraw.rounded_rectangle(
            [2, 0, 126, strip_h - 1],
            radius=6,
            fill=bg_color + (235,),
        )
        sdraw.text(
            (64, strip_h // 2),
            short.upper(),
            fill=(255, 255, 255, 255),
            font=font_sm,
            anchor="mm",
        )
        img.alpha_composite(strip, (0, 2))


def _draw_photo_badge(img, avatar_path: str) -> bool:
    """Windows-style corner photo. The Chrome logo stays visible."""
    try:
        badge_size = 72
        ring = 4
        photo = _circle_crop(Image.open(avatar_path), badge_size)
        outer = badge_size + ring * 2
        badge = Image.new("RGBA", (outer, outer), (0, 0, 0, 0))
        ImageDraw.Draw(badge).ellipse((0, 0, outer - 1, outer - 1), fill=(255, 255, 255, 255))
        badge.paste(photo, (ring, ring), photo)
        img.alpha_composite(badge, (128 - outer - 1, 128 - outer - 1))
        return True
    except Exception:
        return False


def generate_badged_icon(name, output_48, output_128=None, base_icon=None, avatar_path=None):
    """
    Windows-style Chrome profile icon: stock Chrome logo + badge.

    The Chrome logo is the button. The account photo is the corner badge,
    the same arrangement Windows uses. A photo never replaces the logo.

    Badge priority:
      1) Real Google account photo (Gaia)
      2) Colored circle with the profile name's FIRST CHARACTER
         (profiles with no photo — never leave blank / gray person)
    """
    if not base_icon or not os.path.isfile(base_icon):
        base_icon = get_stock_chrome_icon()

    if base_icon and os.path.isfile(base_icon):
        img = Image.open(base_icon).convert("RGBA").resize((128, 128), Image.Resampling.LANCZOS)
    else:
        img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse([8, 8, 120, 120], fill=(66, 133, 244, 255))
    # Always a new context. `draw` used to exist only when the Chrome logo was
    # missing, so a normal install crashed here and the footer kept one icon.
    draw = ImageDraw.Draw(img)
    if avatar_path and _accept_account_photo(avatar_path) and _draw_photo_badge(img, avatar_path):
        os.makedirs(os.path.dirname(os.path.abspath(output_48)), exist_ok=True)
        img.resize((48, 48), Image.Resampling.LANCZOS).save(output_48, format="PNG")
        _write_badge_stamp(output_48, avatar_path)
        if output_128:
            os.makedirs(os.path.dirname(os.path.abspath(output_128)), exist_ok=True)
            img.save(output_128, format="PNG")
            _write_badge_stamp(output_128, avatar_path)
        return

    label = badge_letter(name)
    bg_color = get_profile_color(name or "Chrome")
    font = None
    for font_path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]:
        if os.path.isfile(font_path):
            try:
                font = ImageFont.truetype(font_path, 42)
                break
            except Exception:
                pass
    draw.rounded_rectangle(
        [4, 76, 124, 124],
        radius=12,
        fill=bg_color,
        outline=(255, 255, 255, 230),
        width=3,
    )
    if font:
        draw.text((64, 100), label, fill=(255, 255, 255), font=font, anchor="mm")
    else:
        draw.text((64, 100), label, fill=(255, 255, 255), anchor="mm")

    os.makedirs(os.path.dirname(os.path.abspath(output_48)), exist_ok=True)
    img_48 = img.resize((48, 48), Image.Resampling.LANCZOS)
    img_48.save(output_48, format="PNG")
    _write_badge_stamp(output_48, None)

    if output_128:
        os.makedirs(os.path.dirname(os.path.abspath(output_128)), exist_ok=True)
        img.save(output_128, format="PNG")
        _write_badge_stamp(output_128, None)


def update_google_chrome_desktop(home_dir, all_profiles):
    """Add Desktop Actions for all profiles to google-chrome.desktop."""
    desktop_file = os.path.join(home_dir, ".local/share/applications/google-chrome.desktop")
    if not os.path.isfile(desktop_file):
        desktop_file = "/usr/local/share/applications/google-chrome.desktop"
    if not os.path.isfile(desktop_file):
        return

    devos_bin = (
        os.path.join(home_dir, ".local/bin/devos-browser")
        if os.path.isfile(os.path.join(home_dir, ".local/bin/devos-browser"))
        else "/usr/local/bin/devos-browser"
    )

    action_keys = ["new-window", "new-private-window", "new-guest-window"]
    action_blocks = []

    for key, name in all_profiles:
        slug = slugify(key if key == "guest" else (name or key))
        action_id = f"profile-{slug}"
        action_keys.append(action_id)

        if key == "guest":
            exec_line = f"{devos_bin} --guest --class=chrome-guest"
            icon_line = "chrome-guest"
        else:
            exec_line = f'{devos_bin} --profile-directory="{key}" --class=chrome-{slug}'
            icon_line = f"chrome-{slug}"

        action_blocks.append(f"""
[Desktop Action {action_id}]
Name={name}
Exec={exec_line}
Icon={icon_line}
""")

    actions_str = ";".join(action_keys) + ";"
    user_desktop = os.path.join(home_dir, ".local/share/applications/google-chrome.desktop")
    default_key = next((k for k, _ in all_profiles if k != "guest"), "Default")
    default_slug = slugify(next((n for k, n in all_profiles if k == default_key), "Chrome"))

    # Idle pin keeps stock Chrome class; running profiles use chrome-<slug>.
    base_content = f"""[Desktop Entry]
Version=1.0
Name=Google Chrome
GenericName=Web Browser
Comment=Access the Internet
Exec={devos_bin} %U
StartupNotify=true
StartupWMClass=google-chrome
Terminal=false
Icon=google-chrome
Type=Application
Categories=Network;WebBrowser;
MimeType=application/pdf;application/rdf+xml;application/rss+xml;application/xhtml+xml;application/xhtml_xml;application/xml;image/gif;image/jpeg;image/png;image/webp;text/html;text/xml;x-scheme-handler/http;x-scheme-handler/https;
Actions={actions_str}

[Desktop Action new-window]
Name=New Window
Exec={devos_bin} --profile-directory="{default_key}" --class=chrome-{default_slug}

[Desktop Action new-private-window]
Name=New Incognito Window
Exec={devos_bin} --incognito --class=chrome-{default_slug}

[Desktop Action new-guest-window]
Name=New Guest Window
Exec={devos_bin} --guest --class=chrome-guest
"""
    full_content = base_content + "".join(action_blocks)
    with open(user_desktop, "w", encoding="utf-8") as f:
        f.write(full_content)


def sync_all_profiles(home_dir=None):
    """Generate all profile icons and desktop launcher entries."""
    if not home_dir:
        home_dir = os.path.expanduser("~")

    icons_dir_48 = os.path.join(home_dir, ".local/share/icons/hicolor/48x48/apps")
    icons_dir_128 = os.path.join(home_dir, ".local/share/icons/hicolor/128x128/apps")
    apps_dir = os.path.join(home_dir, ".local/share/applications")

    os.makedirs(icons_dir_48, exist_ok=True)
    os.makedirs(icons_dir_128, exist_ok=True)
    os.makedirs(apps_dir, exist_ok=True)

    chrome_dir = os.path.join(home_dir, ".config/google-chrome")
    details = get_chrome_profile_details(chrome_dir)
    profiles = {k: v["name"] for k, v in details.items()}

    # Real Chrome profiles only; Guest is a right-click action, not a fake person.
    real_profiles = list(profiles.items())
    all_profiles = list(real_profiles)
    all_profiles.append(("guest", "Guest"))

    created_desktops = []

    devos_bin = (
        os.path.join(home_dir, ".local/bin/devos-browser")
        if os.path.isfile(os.path.join(home_dir, ".local/bin/devos-browser"))
        else "/usr/local/bin/devos-browser"
    )

    # Build complete desktop actions for switching to any profile or guest mode
    action_keys = ["new-window", "new-private-window", "new-guest-window"]
    action_blocks = []

    for key, name in all_profiles:
        slug = slugify(key if key == "guest" else (name or key))
        action_id = f"profile-{slug}"
        action_keys.append(action_id)

        if key == "guest":
            exec_line = f"{devos_bin} --guest --class=chrome-guest"
            icon_line = "chrome-guest"
        else:
            exec_line = f'{devos_bin} --profile-directory="{key}" --class=chrome-{slug}'
            icon_line = f"chrome-{slug}"

        action_blocks.append(f"""
[Desktop Action {action_id}]
Name={name}
Exec={exec_line}
Icon={icon_line}
""")

    actions_str = ";".join(action_keys) + ";"
    # Idle Chrome pin always uses Default (or first real profile) — never Guest.
    default_key = "Default" if "Default" in profiles else (
        real_profiles[0][0] if real_profiles else "Default"
    )
    default_name = profiles.get(default_key, "Chrome")
    default_slug = slugify(default_name) if profiles else "chrome"
    default_class = "google-chrome" if not profiles else f"chrome-{default_slug}"
    common_actions = f"""Actions={actions_str}

[Desktop Action new-window]
Name=New Window
Exec={devos_bin} --profile-directory="{default_key}" --class={default_class}

[Desktop Action new-private-window]
Name=New Incognito Window
Exec={devos_bin} --incognito --class={default_class}

[Desktop Action new-guest-window]
Name=New Guest Window
Exec={devos_bin} --guest --class=chrome-guest
""" + "".join(action_blocks)

    for key, name in all_profiles:
        slug = slugify(key if key == "guest" else (name or key))
        icon_name = f"chrome-{slug}"
        icon_file_48 = os.path.join(icons_dir_48, f"{icon_name}.png")
        icon_file_128 = os.path.join(icons_dir_128, f"{icon_name}.png")
        avatar = None if key == "guest" else (details.get(key) or {}).get("avatar")

        if not (_badge_is_current(icon_file_48, avatar) and _badge_is_current(icon_file_128, avatar)):
            generate_badged_icon(name, icon_file_48, icon_file_128, avatar_path=avatar)

        desktop_file = os.path.join(apps_dir, f"{icon_name}.desktop")
        wm_class = icon_name

        if key == "guest":
            exec_cmd = f"{devos_bin} --guest --class=chrome-guest"
        else:
            exec_cmd = f'{devos_bin} --profile-directory="{key}" --class={wm_class}'

        # NoDisplay: taskbar / WM_CLASS matching only — never Start menu clutter.
        # Profiles belong in Chrome's profile picker (and right-click on Chrome).
        content = f"""[Desktop Entry]
Version=1.0
Name=Google Chrome ({name})
GenericName=Web Browser
Comment=Chrome profile — open from Chrome profile manager (not listed in Start)
Exec={exec_cmd} %U
StartupNotify=true
StartupWMClass={wm_class}
Terminal=false
Icon={icon_name}
Type=Application
Categories=Network;WebBrowser;
NoDisplay=true
Hidden=false
X-DevOS-ChromeProfile=true
{common_actions}"""
        try:
            same = False
            if os.path.isfile(desktop_file):
                with open(desktop_file, encoding="utf-8") as existing:
                    same = existing.read() == content
            if not same:
                with open(desktop_file, "w", encoding="utf-8") as f:
                    f.write(content)
        except OSError:
            pass
        created_desktops.append(desktop_file)

    # Hide any leftover profile launchers that older DevOS builds left visible.
    try:
        for name in os.listdir(apps_dir):
            if not (name.startswith("chrome-") and name.endswith(".desktop")):
                continue
            path = os.path.join(apps_dir, name)
            try:
                text = open(path, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if "NoDisplay=true" in text:
                continue
            if "X-DevOS-ChromeProfile=true" not in text and "StartupWMClass=chrome-" not in text:
                continue
            if "NoDisplay=" in text:
                text = re.sub(r"(?m)^NoDisplay=.*$", "NoDisplay=true", text)
            else:
                text = text.replace("Type=Application\n", "Type=Application\nNoDisplay=true\n", 1)
                if "NoDisplay=true" not in text:
                    text += "\nNoDisplay=true\n"
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError:
                pass
    except OSError:
        pass

    # Idle pin: Chrome logo. Running windows use chrome-<profile> classes instead.
    stock = get_stock_chrome_icon()
    for dest in (
        os.path.join(icons_dir_48, "google-chrome.png"),
        os.path.join(icons_dir_128, "google-chrome.png"),
    ):
        try:
            if stock and os.path.isfile(stock):
                shutil.copyfile(stock, dest)
            else:
                generate_badged_icon("Chrome", dest, None, avatar_path=None)
        except OSError:
            pass
    user_desktop = os.path.join(home_dir, ".local/share/applications/google-chrome.desktop")
    base_content = f"""[Desktop Entry]
Version=1.0
Name=Google Chrome
GenericName=Web Browser
Comment=Access the Internet
Exec={devos_bin} --profile-directory="{default_key}" --class={default_class} %U
StartupNotify=true
StartupWMClass=google-chrome
Terminal=false
Icon=google-chrome
Type=Application
Categories=Network;WebBrowser;
MimeType=application/pdf;application/rdf+xml;application/rss+xml;application/xhtml+xml;application/xhtml_xml;application/xml;image/gif;image/jpeg;image/png;image/webp;text/html;text/xml;x-scheme-handler/http;x-scheme-handler/https;
{common_actions}"""
    with open(user_desktop, "w", encoding="utf-8") as f:
        f.write(base_content)

    # WM_CLASS / pin alias only — never a second Start-menu tile (symlink to
    # google-chrome.desktop made Kickoff list Chrome twice under G).
    com_chrome = os.path.join(apps_dir, "com.google.Chrome.desktop")
    try:
        if os.path.lexists(com_chrome):
            os.remove(com_chrome)
        with open(com_chrome, "w", encoding="utf-8") as fh:
            fh.write(
                "[Desktop Entry]\nType=Application\nName=Google Chrome\n"
                "NoDisplay=true\nHidden=true\nX-DevOS-Hidden=true\n"
                f"Exec={devos_bin} %U\nIcon=google-chrome\n"
                "StartupWMClass=google-chrome\nTerminal=false\n"
                "Categories=Network;WebBrowser;\n"
            )
    except OSError:
        pass

    # Ensure ~/.config/devos/chrome-policies/devos-familysafe.json exists with Guest mode enabled
    pol_dir = os.path.join(home_dir, ".config/devos/chrome-policies")
    os.makedirs(pol_dir, exist_ok=True)
    pol_file = os.path.join(pol_dir, "devos-familysafe.json")
    with open(pol_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "DnsOverHttpsMode": "off",
                "ForceGoogleSafeSearch": True,
                "ForceYouTubeRestrict": 1,
                "IncognitoModeAvailability": 1,
                "BrowserGuestModeEnabled": True,
                "BrowserAddPersonEnabled": True,
            },
            f,
            indent=2,
        )

    # Rename raw https://… Chrome apps and hide duplicates (Windows App twice, etc.).
    try:
        from browser.chrome_start_menu import clean_chrome_start_menu
        clean_chrome_start_menu(Path(apps_dir))
    except Exception:
        try:
            from chrome_start_menu import clean_chrome_start_menu
            clean_chrome_start_menu(Path(apps_dir))
        except Exception:
            pass

    return created_desktops


# --- X11 Window Management & Profile Watcher ---

WINDOW_PROFILE_CACHE = {}
_LAST_PLASMA_LAUNCHERS = None
_APPLIED_CLASS = {}


_ICON_PIXEL_CACHE = {}


def _png_cardinals(path):
    """ARGB words for _NET_WM_ICON. Decode each PNG once until the file changes."""
    st = os.stat(path)
    key = (st.st_mtime_ns, st.st_size)
    cached = _ICON_PIXEL_CACHE.get(path)
    if cached and cached[0] == key:
        return cached[1]
    img = Image.open(path).convert("RGBA")
    w, h = img.size
    raw = img.tobytes()
    pixels = [w, h]
    for i in range(0, len(raw), 4):
        r, g, b, a = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
        pixels.append((a << 24) | (r << 16) | (g << 8) | b)
    if len(_ICON_PIXEL_CACHE) > 48:
        _ICON_PIXEL_CACHE.clear()
    _ICON_PIXEL_CACHE[path] = (key, pixels)
    return pixels


def set_window_icon(wid, icon_path_48, icon_path_128=None):
    """Set _NET_WM_ICON on an X11 window using libX11.so.6.

    The display pointer and the window id are 64-bit. Without argument types,
    the call is truncated and the task button keeps Chrome's own logo.
    """
    paths = [p for p in [icon_path_48, icon_path_128] if p and os.path.isfile(p)]
    if not paths or not wid:
        return
    try:
        x11 = ctypes.CDLL("libX11.so.6")
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x11.XInternAtom.restype = ctypes.c_ulong
        x11.XChangeProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        x11.XChangeProperty.restype = ctypes.c_int
        x11.XFlush.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

        disp_name = os.environ.get("DISPLAY")
        if not disp_name:
            for sock in sorted(glob.glob("/tmp/.X11-unix/X*")):
                disp_num = sock.split("/tmp/.X11-unix/X")[-1]
                disp_name = f":{disp_num}"
                break
        display = x11.XOpenDisplay(disp_name.encode() if disp_name else None)
        if not display:
            return
        net_wm_icon = x11.XInternAtom(display, b"_NET_WM_ICON", False)
        cardinal = x11.XInternAtom(display, b"CARDINAL", False)

        pixels = []
        for p in paths:
            pixels.extend(_png_cardinals(p))
        if not pixels:
            x11.XCloseDisplay(display)
            return

        c_data = (ctypes.c_ulong * len(pixels))(*pixels)
        x11.XChangeProperty(
            display,
            ctypes.c_ulong(int(wid)),
            net_wm_icon,
            cardinal,
            32,
            0,  # PropModeReplace
            ctypes.cast(c_data, ctypes.c_void_p),
            len(pixels),
        )
        x11.XFlush(display)
        x11.XCloseDisplay(display)
    except Exception:
        pass


def get_x11_windows():
    """
    Query open X11 windows and return list of dicts:
    [{'id': int, 'title': str, 'wm_class': str}, ...]
    """
    try:
        import subprocess
        out = subprocess.check_output(["wmctrl", "-lx"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return []

    windows = []
    for line in out.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 5:
            wid_str, desktop_num, wm_class, client_machine, title = parts
            try:
                wid = int(wid_str, 16)
            except ValueError:
                continue
            windows.append({
                "id": wid,
                "wm_class": wm_class,
                "title": title,
            })
    return windows


def _kde_desktop_file_name(desktop_slug: str) -> str:
    """Desktop id Plasma uses to find the file. No .desktop suffix."""
    name = (desktop_slug or "").strip()
    if name.lower().endswith(".desktop"):
        name = name[: -len(".desktop")]
    return name


def set_window_desktop_file(wid, desktop_slug, home_dir=None):
    """Point the window at a distinct .desktop so Plasma can split task icons."""
    try:
        import subprocess
        slug = desktop_slug if desktop_slug.endswith(".desktop") else f"{desktop_slug}.desktop"
        # Plasma looks this name up without the suffix. Sending "x.desktop"
        # misses the file, and the button stays the plain Chrome logo.
        kde_name = _kde_desktop_file_name(slug)
        home = home_dir or os.path.expanduser("~")
        abs_desktop = os.path.join(home, ".local/share/applications", slug)
        if not os.path.isfile(abs_desktop):
            abs_desktop = f"/usr/share/applications/{slug}"
        for atom, value in (
            ("_KDE_NET_WM_DESKTOP_FILE", kde_name),
            ("BAMF_DESKTOP_FILE_HINT", abs_desktop if os.path.isfile(abs_desktop) else slug),
        ):
            subprocess.run(
                ["xprop", "-id", hex(wid), "-f", atom, "8s", "-set", atom, value],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass


def _install_icon_name(home_dir, icon_name: str, src_48: str, src_128: str = None) -> None:
    """Copy badged PNGs into hicolor under icon_name and refresh the icon cache lightly."""
    home = home_dir or os.path.expanduser("~")
    for size, src in ((48, src_48), (128, src_128 or src_48)):
        if not src or not os.path.isfile(src):
            continue
        dest_dir = os.path.join(home, f".local/share/icons/hicolor/{size}x{size}/apps")
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, f"{icon_name}.png")
        try:
            if os.path.abspath(src) != os.path.abspath(dest):
                shutil.copyfile(src, dest)
        except OSError:
            pass
    # A copied file is enough. Rebuilding the icon cache here used to run on
    # every window switch and made the desktop feel like it was loading hard.


def ensure_window_task_desktop(home_dir, prof_name: str, slug: str, wm_class: str, icon_name: str) -> str:
    """
    Create a NoDisplay .desktop whose StartupWMClass matches this ONE window.

    Plasma groups by AppId/WM_CLASS. Two windows that both use chrome-work still
    stack under one tile even with avatar badges — a unique class + desktop
    per window is what actually splits the taskbar.
    """
    home = home_dir or os.path.expanduser("~")
    apps = os.path.join(home, ".local/share/applications")
    os.makedirs(apps, exist_ok=True)
    desktop = f"{wm_class}.desktop"
    path = os.path.join(apps, desktop)
    devos_bin = (
        os.path.join(home, ".local/bin/devos-browser")
        if os.path.isfile(os.path.join(home, ".local/bin/devos-browser"))
        else "/usr/local/bin/devos-browser"
    )
    label = prof_name or slug or "Chrome"
    if slug == "guest" or (prof_name or "").lower() == "guest":
        exec_line = f"{devos_bin} --guest --class={wm_class}"
    else:
        # Best-effort: profile directory may be unknown here; class is what matters for the taskbar.
        exec_line = f"{devos_bin} --class={wm_class}"
    # Absolute Icon= path — Plasma theme lookup often misses new hicolor files
    # and falls back to Chrome's plain logo. The 128px file keeps the photo sharp.
    icon_abs = os.path.join(home, ".local/share/icons/hicolor/128x128/apps", f"{wm_class}.png")
    if not os.path.isfile(icon_abs):
        icon_abs = os.path.join(home, ".local/share/icons/hicolor/48x48/apps", f"{wm_class}.png")
    if not os.path.isfile(icon_abs):
        icon_abs = wm_class
    content = f"""[Desktop Entry]
Version=1.0
Name=Google Chrome ({label})
GenericName=Web Browser
Comment=DevOS per-window Chrome task (not shown in Start menu)
Exec={exec_line} %U
StartupNotify=true
StartupWMClass={wm_class}
Terminal=false
Icon={icon_abs}
Type=Application
Categories=Network;WebBrowser;
NoDisplay=true
Hidden=false
X-DevOS-ChromeWindowTask=true
X-DevOS-ChromeProfileSlug={slug}
"""
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as fh:
                if fh.read() == content:
                    return desktop
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError:
        pass
    return desktop


def window_task_class(slug: str, wid: int) -> str:
    """Unique WM_CLASS so Plasma cannot group two Chrome windows into one tile."""
    base = slugify(slug) or "chrome"
    # Full X11 id. The low 16 bits collide (0x0100002a and 0x0200002a) and those
    # two windows then fall back into one footer group.
    return f"chrome-{base}-w{int(wid) & 0xFFFFFFFF:x}"


def _kwin_unique_key_map(rows, field):
    """Map a row field to a desktop file only when that value belongs to one window.

    A shared Chrome PID must not be used: both of that profile's windows would
    receive one desktop file and the footer would stack them again.
    """
    counts = {}
    for row in rows or []:
        key = str((row or {}).get(field) or "").strip()
        if not key or key == "0":
            continue
        counts[key] = counts.get(key, 0) + 1
    out = {}
    for row in rows or []:
        key = str((row or {}).get(field) or "").strip()
        desk = (row or {}).get("desktop") or ""
        if key and key != "0" and desk and counts.get(key) == 1:
            out[key] = desk
    return out


def kwin_assignment_maps(rows):
    """Split rows into window-id, unique-pid, and unique-title desktop maps."""
    by_window = {}
    for row in rows or []:
        try:
            wid = int((row or {}).get("id") or 0)
        except (TypeError, ValueError):
            wid = 0
        desk = (row or {}).get("desktop") or ""
        if wid > 0 and desk:
            by_window[str(wid)] = desk
    return by_window, _kwin_unique_key_map(rows, "pid"), _kwin_unique_key_map(rows, "title")


def kwin_chrome_desktop_script(by_window, by_pid=None, by_title=None) -> str:
    """KWin script: point each Chrome window at its own taskbar .desktop.

    Plasma groups by the desktop file it stored when the window opened.
    Rewriting WM_CLASS afterwards does not split that group. Setting
    desktopFileName does — each file has that profile's badge as Icon=.
    """
    def obj(mapping):
        parts = []
        for key, desk in (mapping or {}).items():
            parts.append(f"{json.dumps(str(key))}: {json.dumps(str(desk))}")
        return "{" + ",".join(parts) + "}"

    return f"""var byWindow = {obj(by_window)};
var byPid = {obj(by_pid)};
var byTitle = {obj(by_title)};
function devosChromeDesk(win) {{
  if (!win) return;
  var desk = "";
  try {{
    var id = win.windowId;
    if (typeof id === "function") id = id();
    id = String(id || 0);
    if (id && id !== "0" && byWindow[id]) desk = byWindow[id];
  }} catch (e) {{}}
  if (!desk) {{
    try {{
      var pid = String(win.pid || 0);
      if (pid && pid !== "0" && byPid[pid]) desk = byPid[pid];
    }} catch (e2) {{}}
  }}
  if (!desk) {{
    try {{
      var title = String(win.caption || "");
      if (title && byTitle[title]) desk = byTitle[title];
    }} catch (e3) {{}}
  }}
  if (!desk) return;
  try {{
    if (win.desktopFileName !== desk) win.desktopFileName = desk;
  }} catch (e4) {{}}
}}
function devosChromeApplyAll() {{
  var list = [];
  try {{
    if (typeof workspace.windowList === "function") list = workspace.windowList();
    else if (typeof workspace.clientList === "function") list = workspace.clientList();
  }} catch (e) {{ list = []; }}
  for (var i = 0; i < list.length; i++) devosChromeDesk(list[i]);
}}
devosChromeApplyAll();
try {{
  if (workspace.windowAdded) workspace.windowAdded.connect(devosChromeDesk);
  else if (workspace.clientAdded) workspace.clientAdded.connect(devosChromeDesk);
}} catch (e) {{}}
"""


def apply_kwin_window_desktops(rows, home_dir=None) -> bool:
    """Load the KWin script that gives every Chrome window its own footer icon."""
    home = home_dir or os.path.expanduser("~")
    by_window, by_pid, by_title = kwin_assignment_maps(rows)
    script = kwin_chrome_desktop_script(by_window, by_pid, by_title)
    folder = os.path.join(home, ".config", "devos")
    try:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "kwin-chrome-taskbar.js")
        previous = ""
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as handle:
                previous = handle.read()
        # Same map as last time. Reloading KWin here is what blanks the footer
        # when a Chrome title changes (a chat click, or switching apps).
        if previous == script:
            return True
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(script)
    except OSError:
        return False
    bus = None
    for name in ("qdbus6", "qdbus", "qdbus-qt6"):
        if shutil.which(name):
            bus = name
            break
    if not bus:
        return False
    plugin = "devoschrometasks"
    try:
        import subprocess
        subprocess.run(
            [bus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", plugin],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
        if not by_window and not by_pid and not by_title:
            return True
        subprocess.run(
            [bus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript", path, plugin],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=4,
        )
        try:
            listed = subprocess.check_output(
                [bus, "org.kde.KWin"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )
        except Exception:
            listed = ""
        for line in listed.splitlines():
            obj = line.strip()
            if not obj.startswith("/Scripting/") or obj == "/Scripting":
                continue
            subprocess.run(
                [bus, "org.kde.KWin", obj, "org.kde.kwin.Script.run"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
            )
        # Do not call Scripting.start. That restarts every KWin script and
        # the footer disappears while the desktop reloads.
        return True
    except Exception:
        return False


def set_window_wm_class(wid, class_name, class_inst=None):
    """Set a proper two-part WM_CLASS (instance + class) via XSetClassHint / xdotool / xprop."""
    inst_s = class_inst or class_name or "chrome"
    cls_s = class_name or "chrome"
    inst = inst_s.encode("utf-8")
    cls = cls_s.encode("utf-8")
    try:
        x11 = ctypes.CDLL("libX11.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p
        disp_name = os.environ.get("DISPLAY")
        display = x11.XOpenDisplay(disp_name.encode() if disp_name else None)
        if display:
            class XClassHint(ctypes.Structure):
                _fields_ = [("res_name", ctypes.c_char_p), ("res_class", ctypes.c_char_p)]

            hint = XClassHint(inst, cls)
            x11.XSetClassHint(display, ctypes.c_ulong(wid), ctypes.byref(hint))
            x11.XFlush(display)
            x11.XCloseDisplay(display)
    except Exception:
        pass
    try:
        import subprocess
        subprocess.run(
            [
                "xdotool",
                "set_window",
                "--classname",
                inst_s,
                "--class",
                cls_s,
                str(wid),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Plasma often re-reads WM_CLASS from the property; set both ways.
        prop = "%s\0%s" % (inst_s, cls_s)
        subprocess.run(
            ["xprop", "-id", hex(wid), "-f", "WM_CLASS", "8s", "-set", "WM_CLASS", prop],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _find_icontasks_general_section(text: str):
    """Return the exact [Containments][N][Applets][M][Configuration][General] for Icon Tasks."""
    for match in re.finditer(
        r"(?m)^(\[Containments\]\[(\d+)\]\[Applets\]\[(\d+)\])\n",
        text,
    ):
        header, cont, applet = match.group(1), match.group(2), match.group(3)
        # Read only this applet's top-level keys until the next section.
        start = match.end()
        nxt = re.search(r"(?m)^\[", text[start:])
        block = text[start: start + nxt.start()] if nxt else text[start:]
        if re.search(
            r"(?m)^plugin=org\.kde\.plasma\.(icontasks|taskmanager)\s*$",
            block,
        ):
            return f"[Containments][{cont}][Applets][{applet}][Configuration][General]"
    return None


def _is_chrome_launcher(entry: str) -> bool:
    """True for idle Chrome/DevOS Browser pins and per-profile/per-window chrome-* pins."""
    e = (entry or "").strip().lower()
    return (
        "google-chrome.desktop" in e
        or "com.google.chrome.desktop" in e
        or "devos-browser.desktop" in e
        or "devos-web-browser.desktop" in e
        or re.search(r"(^|/)chrome-[a-z0-9-]+\.desktop$", e) is not None
        or "applications:chrome-" in e
    )


def _idle_pin_state_path(home_dir=None):
    home = home_dir or os.path.expanduser("~")
    return Path(home) / ".config/devos/chrome-taskbar-idle-pin"


def _remember_idle_pin(pin: str, home_dir=None) -> None:
    path = _idle_pin_state_path(home_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((pin or "").strip() + "\n", encoding="utf-8")
    except OSError:
        pass


def _idle_chrome_launcher(existing, home_dir=None):
    """Prefer the pin the user already had (DevOS Browser or Google Chrome)."""
    home = home_dir or os.path.expanduser("~")
    for entry in existing or []:
        el = entry.lower()
        if "google-chrome.desktop" in el or "devos-browser.desktop" in el:
            pin = entry if entry.startswith("applications:") else f"applications:{entry}"
            _remember_idle_pin(pin, home)
            return pin
    # Profiles are open → idle browser pin was removed; restore the last one.
    try:
        remembered = _idle_pin_state_path(home).read_text(encoding="utf-8").strip()
        if remembered and (
            "google-chrome.desktop" in remembered or "devos-browser.desktop" in remembered
        ):
            return remembered
    except OSError:
        pass
    # Chrome installed → pin Google Chrome; else keep DevOS Browser tile.
    if (
        os.path.isfile("/usr/bin/google-chrome-stable")
        or os.path.isfile("/usr/bin/google-chrome")
        or os.path.isfile("/opt/google/chrome/google-chrome")
        or os.path.isfile(os.path.join(home, ".local/share/applications/google-chrome.desktop"))
    ):
        return "applications:google-chrome.desktop"
    return "applications:devos-browser.desktop"


def apply_plasma_launchers_live(launcher_csv: str, grouping: str = "1", launchers_only: bool = False) -> bool:
    """Push Icon Tasks launchers into the running bar without rebuilding it.

    writeConfig updates the task buttons in place. ``panels`` is not stored
    in a variable of the same name, because that throws before the write.
    """
    group = "0" if str(grouping).strip() == "0" else "1"
    popups = "false" if group == "0" else "true"
    safe = (launcher_csv or "").replace("\\", "\\\\").replace("'", "\\'")
    extra = ""
    if not launchers_only:
        extra = (
            '    widgets[j].writeConfig("separateLaunchers", "true");'
            f'    widgets[j].writeConfig("groupingStrategy", "{group}");'
            f'    widgets[j].writeConfig("groupPopups", "{popups}");'
            '    widgets[j].writeConfig("onlyGroupWhenFull", "false");'
            '    widgets[j].writeConfig("launchInPlace", "true");'
            '    widgets[j].writeConfig("hideActivatedLaunchers", "false");'
        )
    script = f"""var raw = [];
try {{ raw = panels(); }} catch (e0) {{ raw = []; }}
var rawParts = '{safe}'.split(",");
var parts = [];
for (var k = 0; k < rawParts.length; k++) {{
  if (rawParts[k]) parts.push(rawParts[k]);
}}
function pinKey(v) {{
  var text = "";
  try {{
    if (v && v.join) text = v.join(",");
    else text = String(v || "");
  }} catch (e) {{ text = String(v || ""); }}
  var bits = text.split(",");
  var out = [];
  for (var i = 0; i < bits.length; i++) {{
    var s = String(bits[i] || "").replace(/^\\s+|\\s+$/g, "");
    if (s) out.push(s);
  }}
  out.sort();
  return out.join(",");
}}
var want = pinKey(parts);
var n = 0;
var matched = 0;
var note = "";
for (var i = 0; i < raw.length; i++) {{
  var panel = raw[i];
  if (!panel || !panel.widgets) {{
    try {{ panel = panelById(raw[i]); }} catch (e1) {{ panel = null; }}
  }}
  if (!panel || !panel.widgets) continue;
  var widgets = [];
  try {{ widgets = panel.widgets(); }} catch (e2) {{ widgets = []; }}
  for (var j = 0; j < widgets.length; j++) {{
    var kind = "";
    try {{ kind = String(widgets[j].type || ""); }} catch (e3) {{ kind = ""; }}
    if (kind !== "org.kde.plasma.icontasks" && kind !== "org.kde.plasma.taskmanager") continue;
    var groups = [[], ["General"], ["Configuration", "General"]];
    for (var g = 0; g < groups.length; g++) {{
      try {{
        widgets[j].currentConfigGroup = groups[g];
        widgets[j].writeConfig("launchers", parts);
{extra}
        n = n + 1;
        var got = pinKey(widgets[j].readConfig("launchers"));
        note = got;
        if (got === want) matched = 1;
      }} catch (e4) {{ note = String(e4); }}
    }}
  }}
}}
(n > 0 && matched) ? "devos-launchers-ok" : ("devos-launchers-miss " + n + " " + note);
"""
    try:
        import subprocess
        for cmd in _plasma_script_commands(script):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                continue
            text = ((out.stdout or "") + "\n" + (out.stderr or "")).strip()
            if out.returncode != 0:
                continue
            if any(word in text for word in ("TypeError", "ReferenceError", "SyntaxError")):
                continue
            if "devos-launchers-ok" in text:
                return True
        return False
    except Exception:
        return False


def _plasma_script_commands(script: str) -> list:
    commands = []
    for bus in ("qdbus6", "qdbus", "qdbus-qt6"):
        if shutil.which(bus):
            commands.append([bus, "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", script])
    if shutil.which("busctl"):
        commands.append(
            [
                "busctl", "--user", "call", "org.kde.plasmashell", "/PlasmaShell",
                "org.kde.PlasmaShell", "evaluateScript", "s", script,
            ]
        )
    return commands


_WIN_PIN = re.compile(r"-w([0-9a-f]+)\.desktop$", re.I)
_PUBLISHED_LAUNCHERS = None


def _reconcile_launcher_entries(existing, chrome_wins, idle_pin: str) -> list:
    """Launcher list after Chrome windows open or close.

    A closed window's pin is dropped. When no Chrome window is open, every
    browser icon is removed, including DevOS Browser and Google Chrome.
    Other apps on the bar stay.
    """
    del idle_pin
    preserved = [e for e in (existing or []) if not _is_chrome_launcher(e)]
    wins = list(chrome_wins or [])
    if not wins:
        return preserved
    open_hex = set()
    open_desktops = []
    seen = set()
    for win in wins:
        try:
            open_hex.add(f"{int(win.get('id') or 0) & 0xFFFFFFFF:x}")
        except (TypeError, ValueError):
            pass
        desk = (win.get("task_desktop") or "").strip()
        if desk:
            name = desk if desk.endswith(".desktop") else f"{desk}.desktop"
            entry = name if name.startswith("applications:") else f"applications:{name}"
            if entry not in seen:
                seen.add(entry)
                open_desktops.append(entry)
        for token in re.split(r"[\s,]+", (win.get("wm_class") or "").lower()):
            if token.startswith("chrome-") and "-w" in token:
                name = token if token.endswith(".desktop") else f"{token}.desktop"
                entry = name if name.startswith("applications:") else f"applications:{name}"
                if entry not in seen:
                    seen.add(entry)
                    open_desktops.append(entry)
    if open_desktops:
        return preserved + open_desktops
    kept = []
    for entry in existing or []:
        if not _is_chrome_launcher(entry):
            continue
        match = _WIN_PIN.search(entry.lower())
        if match and match.group(1) not in open_hex:
            continue
        kept.append(entry)
    return preserved + kept


def sync_plasma_profile_launchers(home_dir=None, active_slugs=None, window_desktops=None):
    """
    Windows-like Chrome pins:
      - No Chrome windows → idle browser pin (DevOS Browser / Google Chrome)
      - Windows open → pin each window's unique .desktop (badged Icon= path)
        so Plasma shows OUR icon, not Chrome's gray person badge
    """
    home = home_dir or os.path.expanduser("~")
    cfg = Path(home) / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if not cfg.is_file():
        return False
    text = cfg.read_text(encoding="utf-8", errors="replace")
    section = _find_icontasks_general_section(text)
    if not section:
        return False

    # Undo accidental writes into other applets from older matcher bugs.
    polluted_keys = (
        "launchers",
        "separateLaunchers",
        "groupingStrategy",
        "launchInPlace",
        "hideActivatedLaunchers",
        "groupPopups",
    )

    # Keep every non-Chrome pin the user already had.
    existing = []
    m = re.search(
        rf"(?ms)^{re.escape(section)}\n(.*?)(?=^\[|\Z)",
        text,
    )
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("launchers="):
                existing = [x.strip() for x in line.split("=", 1)[1].split(",") if x.strip()]
                break
    idle_pin = _idle_chrome_launcher(existing, home)
    preserved = [e for e in existing if not _is_chrome_launcher(e)]

    apps_dir = os.path.join(home, ".local/share/applications")
    active = [(s or "").strip().lower() for s in (active_slugs or []) if (s or "").strip()]
    win_desks = []
    for d in window_desktops or []:
        name = (d or "").strip()
        if not name:
            continue
        if not name.endswith(".desktop"):
            name = f"{name}.desktop"
        if os.path.isfile(os.path.join(apps_dir, name)):
            win_desks.append(f"applications:{name}")

    chrome_launchers = []
    if win_desks:
        # Prefer per-window launchers — Icon Tasks then paints our badged PNG.
        chrome_launchers = win_desks
    elif active:
        # Fallback: one pin per open profile (avatar).
        seen = set()
        for slug in active:
            if slug in seen:
                continue
            desktop = f"chrome-{slug}.desktop"
            if not os.path.isfile(os.path.join(apps_dir, desktop)):
                continue
            chrome_launchers.append(f"applications:{desktop}")
            seen.add(slug)
        if not chrome_launchers and idle_pin:
            chrome_launchers = [idle_pin]
    else:
        # Browser is closed. Do not put the shortcut back on the footer.
        chrome_launchers = []

    launchers = preserved + chrome_launchers
    launcher_csv = ",".join(launchers)
    # Always Do Not Group on DevOS Icon Tasks. Plasma "By program name" merges
    # Chrome windows that share a binary even after avatar badging.
    updates = {
        "launchers": launcher_csv,
        # Keep launchers visible as their own buttons (Windows profile icons).
        "separateLaunchers": "true",
        "groupingStrategy": "0",
        "groupPopups": "false",
        "onlyGroupWhenFull": "false",
        "launchInPlace": "true",
        # Windows-like: open apps keep the same pin with an indicator under the icon
        # (never hide the pin / spawn a blank second tile for every running app).
        "hideActivatedLaunchers": "false",
    }

    parts = re.split(r"(?m)(?=^\[)", text)
    found = False
    out = []
    for part in parts:
        header = part.split("\n", 1)[0].strip()
        if header == section:
            found = True
            hdr, _, rest = part.partition("\n")
            lines = []
            seen_keys = set()
            for line in rest.splitlines(keepends=True):
                key = line.split("=", 1)[0].strip() if "=" in line and not line.startswith("[") else None
                if key in updates:
                    lines.append(f"{key}={updates[key]}\n")
                    seen_keys.add(key)
                else:
                    lines.append(line)
            for key, value in updates.items():
                if key not in seen_keys:
                    lines.append(f"{key}={value}\n")
            part = hdr + "\n" + "".join(lines)
            if not part.endswith("\n"):
                part += "\n"
        elif header.endswith("[Configuration][General]") and header != section:
            # Strip chrome launcher keys wrongly written onto spacers/etc.
            hdr, _, rest = part.partition("\n")
            cleaned = []
            for line in rest.splitlines(keepends=True):
                key = line.split("=", 1)[0].strip() if "=" in line else None
                if key in polluted_keys:
                    continue
                cleaned.append(line)
            part = hdr + "\n" + "".join(cleaned)
            if not part.endswith("\n"):
                part += "\n"
        out.append(part)
    if not found:
        out.append(section + "\n" + "\n".join(f"{k}={v}" for k, v in updates.items()) + "\n")
    new_text = "".join(out)
    if new_text == text:
        # Same pins. Rewriting appletsrc or restarting the panel hides the footer.
        return True
    cfg.write_text(new_text, encoding="utf-8")
    # Save the pin list. publish_chrome_task_launchers pushes it with writeConfig.
    return True


def _read_launcher_entries(home_dir):
    home = home_dir or os.path.expanduser("~")
    cfg = Path(home) / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if not cfg.is_file():
        return None, None, []
    text = cfg.read_text(encoding="utf-8", errors="replace")
    section = _find_icontasks_general_section(text)
    if not section:
        return text, None, []
    existing = []
    match = re.search(rf"(?ms)^{re.escape(section)}\n(.*?)(?=^\[|\Z)", text)
    if match:
        for line in match.group(1).splitlines():
            if line.startswith("launchers="):
                existing = [x.strip() for x in line.split("=", 1)[1].split(",") if x.strip()]
                break
    return text, section, existing


def _launcher_sections(text: str) -> list:
    """Groups Plasma may read for Icon Tasks pins."""
    section = _find_icontasks_general_section(text or "")
    if not section:
        return []
    found = [section]
    if section.endswith("[Configuration][General]"):
        sibling = section[: -len("[Configuration][General]")] + "[General]"
        if sibling not in found:
            found.append(sibling)
    return found


def _write_launcher_entries(home_dir, entries) -> str:
    """Replace only the Icon Tasks launcher list. Leave every other applet alone."""
    home = home_dir or os.path.expanduser("~")
    text, section, _existing = _read_launcher_entries(home)
    csv = ",".join(entries)
    if not section or text is None:
        return csv
    wanted = set(_launcher_sections(text))
    parts = re.split(r"(?m)(?=^\[)", text)
    out = []
    seen_headers = set()
    for part in parts:
        header = part.split("\n", 1)[0].strip()
        seen_headers.add(header)
        if header not in wanted:
            out.append(part)
            continue
        hdr, _, rest = part.partition("\n")
        lines = []
        seen = False
        for line in rest.splitlines(keepends=True):
            if line.startswith("launchers="):
                if not seen:
                    lines.append(f"launchers={csv}\n")
                    seen = True
            else:
                lines.append(line)
        if not seen:
            lines.append(f"launchers={csv}\n")
        part = hdr + "\n" + "".join(lines)
        if not part.endswith("\n"):
            part += "\n"
        out.append(part)
    for header in wanted:
        if header in seen_headers:
            continue
        block = header + "\n" + f"launchers={csv}\n"
        out.append(block)
    new_text = "".join(out)
    if new_text != text:
        (Path(home) / ".config/plasma-org.kde.plasma.desktop-appletsrc").write_text(new_text, encoding="utf-8")
    return csv


def _notify_launcher_list(home_dir, csv: str) -> None:
    """Tell the running taskbar the pin list changed, without rebuilding the panel."""
    import subprocess
    home = home_dir or os.path.expanduser("~")
    cfg = Path(home) / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if not cfg.is_file():
        return
    tool = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5") or ""
    if not tool:
        return
    headers = _launcher_sections(cfg.read_text(encoding="utf-8", errors="replace"))
    for index, header in enumerate(headers):
        groups = re.findall(r"\[([^\]]+)\]", header)
        cmd = [tool, "--file", str(cfg)]
        for group in groups:
            cmd.extend(["--group", group])
        if index == len(headers) - 1:
            cmd.append("--notify")
        cmd.extend(["--key", "launchers", "--type", "stringlist", csv])
        try:
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue


def publish_chrome_task_launchers(home_dir, chrome_wins) -> bool:
    """Make the footer match the Chrome windows that are actually open.

    Called when a window appears or disappears, not on a title change. A closed
    Chrome window loses its task button immediately. The rest of the bar stays.
    """
    global _PUBLISHED_LAUNCHERS
    home = home_dir or os.path.expanduser("~")
    _text, section, existing = _read_launcher_entries(home)
    if not section:
        return False
    idle = _idle_chrome_launcher(existing, home)
    desired = _reconcile_launcher_entries(existing, chrome_wins, idle)
    csv = ",".join(desired)
    current = ",".join(existing)
    if csv == current or csv == _PUBLISHED_LAUNCHERS:
        _PUBLISHED_LAUNCHERS = csv
        return True
    # Write the file and notify. Do not run a shell script against Icon Tasks:
    # that script reloads the applet, and the menus hide for a second or two.
    _write_launcher_entries(home, desired)
    _notify_launcher_list(home, csv)
    _PUBLISHED_LAUNCHERS = csv
    return True


_LAST_PLASMA_RELOAD = 0.0


def reload_plasmashell():
    """Restart plasmashell so Icon Tasks picks up launcher changes (rate-limited)."""
    global _LAST_PLASMA_RELOAD
    now = time.time()
    force = os.environ.get("DEVOS_FORCE_PLASMA_RELOAD", "").strip() in ("1", "true", "yes")
    if not force and now - _LAST_PLASMA_RELOAD < 45:
        return False
    _LAST_PLASMA_RELOAD = now
    try:
        import subprocess
        subprocess.run(
            ["systemctl", "--user", "reset-failed", "plasma-plasmashell.service"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.Popen(
            ["systemctl", "--user", "restart", "plasma-plasmashell.service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def set_plasma_chrome_pinned_launcher(visible=True):
    """Compatibility stub — profile pins are handled by sync_plasma_profile_launchers."""
    pass


def get_profile_session_data(chrome_config_dir):
    """
    Extract tab titles and domains open in each profile from Sessions/Session_* and Sessions/Tabs_*.
    Also reads bookmarks for deterministic window title matching.
    """
    prof_data = {}
    if not os.path.isdir(chrome_config_dir):
        return prof_data

    for p in os.listdir(chrome_config_dir):
        sess_dir = os.path.join(chrome_config_dir, p, "Sessions")
        titles = set()
        domains = set()
        latest_mtime = 0

        # Read bookmarks
        for b_name in ["Bookmarks", "AccountBookmarks"]:
            b_path = os.path.join(chrome_config_dir, p, b_name)
            if os.path.isfile(b_path):
                try:
                    with open(b_path, "r", encoding="utf-8", errors="ignore") as bf:
                        b_json = json.load(bf)
                    # recursively get names
                    def _extract_bm(node):
                        if isinstance(node, dict):
                            if node.get("type") == "url":
                                name = node.get("name")
                                if name and len(name) >= 3:
                                    titles.add(name.strip().lower())
                            for v in node.values():
                                _extract_bm(v)
                        elif isinstance(node, list):
                            for item in node:
                                _extract_bm(item)
                    _extract_bm(b_json)
                except Exception:
                    pass

        # Read sessions
        if os.path.isdir(sess_dir):
            for fn in glob.glob(os.path.join(sess_dir, "*")):
                bn = os.path.basename(fn)
                if bn.startswith("Apps_"):
                    continue
                try:
                    mt = os.path.getmtime(fn)
                    if mt > latest_mtime:
                        latest_mtime = mt
                    with open(fn, "rb") as f:
                        data = f.read()

                    # Extract UTF-16LE titles
                    for m in re.finditer(b"(?:[\x20-\x7e]\x00){4,}", data):
                        s = m.group(0).decode("utf-16le", errors="ignore").strip()
                        if len(s) >= 3 and not s.startswith("http") and not s.startswith("<!--") and not s.startswith("{"):
                            titles.add(s.lower())

                    # Extract URLs and domains
                    urls = re.findall(rb"https?://([a-zA-Z0-9\.\-_]+)", data)
                    for u in urls:
                        parts = u.decode("utf-8", errors="ignore").lower().split(".")
                        if len(parts) >= 2:
                            domains.add(parts[-2])
                except Exception:
                    pass

        prof_data[p] = {
            "titles": titles,
            "domains": domains,
            "mtime": latest_mtime,
        }
    return prof_data


def get_profile_tab_domains(chrome_config_dir):
    """Extract significant domains open in each profile (legacy helper)."""
    data = get_profile_session_data(chrome_config_dir)
    return {k: v["domains"] for k, v in data.items()}


def get_open_browser_profile_keys(chrome_dir, profiles):
    """
    Profile directories Chrome currently has open as browser windows
    (Local State last_active_profiles). Empty when Chrome is closed or
    the file cannot be read — callers must then fall back.
    """
    local_state = os.path.join(chrome_dir, "Local State")
    if not os.path.isfile(local_state):
        return []
    try:
        with open(local_state, "r", encoding="utf-8") as f:
            ls = json.load(f)
        last_active = ls.get("profile", {}).get("last_active_profiles") or []
    except Exception:
        return []
    out = []
    seen = set()
    for key in last_active:
        if key in profiles and key not in seen:
            out.append(key)
            seen.add(key)
    return out


def get_ranked_active_profiles(chrome_dir, profiles):
    """
    Return profile keys ordered by recent active browser usage,
    ignoring background PWAs that touch Default.
    """
    ranked = []
    seen = set()

    for p in get_open_browser_profile_keys(chrome_dir, profiles):
        ranked.append(p)
        seen.add(p)

    # Sort remaining profiles by session modification times
    sess_times = []
    for p in profiles:
        if p in seen:
            continue
        sdir = os.path.join(chrome_dir, p, "Sessions")
        mtime = 0
        if os.path.isdir(sdir):
            for fn in glob.glob(os.path.join(sdir, "*")):
                if not os.path.basename(fn).startswith("Apps_"):
                    mt = os.path.getmtime(fn)
                    if mt > mtime:
                        mtime = mt
        sess_times.append((mtime, p))

    sess_times.sort(reverse=True)
    for _, p in sess_times:
        ranked.append(p)
        seen.add(p)

    return ranked


def _window_pid(wid) -> int:
    try:
        import subprocess
        out = subprocess.check_output(
            ["xprop", "-id", hex(int(wid)), "_NET_WM_PID"],
            text=True, stderr=subprocess.DEVNULL,
        )
        return int(out.rsplit(None, 1)[-1])
    except Exception:
        return 0


def _read_proc_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            return handle.read().replace(b"\0", b" ").decode("utf-8", "ignore")
    except OSError:
        return ""


def _profile_key_from_cmdline(raw: str):
    """Return the Chrome --profile-directory value, or None."""
    match = re.search(
        r'--profile-directory(?:=|\s+)("[^"]+"|\'[^\']+\'|\S+)',
        raw or "",
    )
    if not match:
        return None
    value = match.group(1).strip().strip('"').strip("'")
    if not value or value.lower() == "guest":
        return None
    return value


def _cmdline_profile_key(pid: int):
    """Profile directory of this Chrome window, walking up to the browser process."""
    if not pid:
        return None
    seen = set()
    cur = int(pid)
    for _ in range(8):
        if not cur or cur in seen or cur <= 1:
            break
        seen.add(cur)
        key = _profile_key_from_cmdline(_read_proc_cmdline(cur))
        if key:
            return key
        try:
            with open(f"/proc/{cur}/status", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if line.startswith("PPid:"):
                        cur = int(line.split()[1])
                        break
                else:
                    break
        except (OSError, ValueError):
            break
    return None


def profile_name_for_key(profile_key, profiles):
    """Map a --profile-directory value onto the display name."""
    if not profile_key or not profiles:
        return None
    if profile_key in profiles:
        return profiles[profile_key]
    wanted = profile_key.strip().lower()
    for key, name in profiles.items():
        if (key or "").strip().lower() == wanted:
            return name
    return None


def _cmdline_looks_guest(raw: str) -> bool:
    text = f" {(raw or '').lower()} "
    return (
        " --guest " in text
        or text.strip().endswith("--guest")
        or "guest profile" in text
        or "/guest profile" in text
        or "profile-directory=guest" in text
    )


def _walk_proc_cmdlines(pid: int, depth: int = 6):
    """Yield cmdline strings walking from pid up toward the session leader."""
    if not pid:
        return
    seen = set()
    cur = int(pid)
    for _ in range(max(1, depth)):
        if not cur or cur in seen:
            break
        seen.add(cur)
        yield _read_proc_cmdline(cur)
        try:
            with open(f"/proc/{cur}/status", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if line.startswith("PPid:"):
                        cur = int(line.split()[1])
                        break
                else:
                    break
        except (OSError, ValueError):
            break


def _cmdline_is_guest(pid: int) -> bool:
    """True when this Chrome process (or a close parent) is a Guest session."""
    for raw in _walk_proc_cmdlines(pid):
        if _cmdline_looks_guest(raw):
            return True
    return False


def _cmdline_profile_directory(pid: int) -> str:
    """Return Chrome --profile-directory= value from this window's process tree."""
    for raw in _walk_proc_cmdlines(pid):
        if not raw or "chrome" not in raw.lower():
            continue
        m = re.search(r"--profile-directory=([^\s]+)", raw)
        if m:
            key = m.group(1).strip().strip('"').strip("'")
            if key:
                return key
        # Quoted form used by some launchers: --profile-directory="Profile 1"
        m = re.search(r'--profile-directory="([^"]+)"', raw)
        if m:
            return m.group(1).strip()
    return ""


def _any_guest_chrome_pid() -> bool:
    """True if any running Chrome process is a Guest session."""
    try:
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            raw = _read_proc_cmdline(int(name))
            if "chrome" in raw.lower() and _cmdline_looks_guest(raw):
                return True
    except OSError:
        return False
    return False


def _wm_class_profile(wm_class, profiles):
    """Return profile name when WM_CLASS is already chrome-<slug> / chrome-guest."""
    wc = (wm_class or "").lower()
    if "chrome-guest" in wc:
        return "Guest"
    for _key, p_name in profiles.items():
        slug = slugify(p_name)
        if slug and f"chrome-{slug}" in wc:
            return p_name
    return None


def detect_window_profile(w, profiles, home_dir=None, assigned_profiles=None, prof_session_data=None):
    """
    Determine profile name from window attributes and session activity:
    - Real Guest (--guest cmdline / chrome-guest class) before any avatar profile
    - WM_CLASS chrome-<slug> only when that profile is currently open in Chrome
      (avoids sticky wrong badges after a shared-process mis-tag)
    - Title markers, session/bookmark match among open profiles, then fallback
    """
    wid = w.get("id") if isinstance(w, dict) else None
    title = w.get("title", "") if isinstance(w, dict) else str(w)
    wm_class = (w.get("wm_class", "") if isinstance(w, dict) else "").lower()
    pid = _window_pid(wid) if wid else 0
    is_guest_proc = bool(wid and _cmdline_is_guest(pid))
    proc_profile_key = _cmdline_profile_directory(pid) if wid and pid else ""

    if not home_dir:
        home_dir = os.path.expanduser("~")
    chrome_dir = os.path.join(home_dir, ".config/google-chrome")
    open_keys = get_open_browser_profile_keys(chrome_dir, profiles)
    open_names = {profiles[k] for k in open_keys if k in profiles}

    # Guest only when the process/class really is Guest — never sticky forever.
    if is_guest_proc or "chrome-guest" in wm_class:
        if wid:
            WINDOW_PROFILE_CACHE[wid] = "Guest"
        return "Guest"
    # Title markers: "(Guest)", " - Guest", and Chrome's idle Guest page
    # "You're browsing as a Guest" (new-tab Guest window).
    if re.search(
        r"(\(Guest\)| - Guest( - |$)|browsing as a Guest|You.?re browsing as a Guest)",
        title or "",
        re.IGNORECASE,
    ):
        if wid:
            WINDOW_PROFILE_CACHE[wid] = "Guest"
        return "Guest"

    # The process flag is the profile Chrome actually opened. A previous pass
    # can leave the wrong chrome-<slug> class on the window (both icons then
    # show Mirza's M). The directory wins over that sticky class.
    if pid:
        keyed = profile_name_for_key(_cmdline_profile_key(pid), profiles)
        if keyed:
            if wid:
                WINDOW_PROFILE_CACHE[wid] = keyed
            return keyed

    # Trust chrome-<slug> only if that profile is among Chrome's open browser
    # profiles. A shared Chrome PID previously got Work windows rewritten to
    # chrome-tony; without this check the wrong face sticks forever.
    class_prof = _wm_class_profile(wm_class, profiles)
    if class_prof and class_prof != "Guest":
        if not open_names or class_prof in open_names:
            if wid:
                WINDOW_PROFILE_CACHE[wid] = class_prof
            return class_prof
        if wid and WINDOW_PROFILE_CACHE.get(wid) == class_prof:
            del WINDOW_PROFILE_CACHE[wid]

    if wid and WINDOW_PROFILE_CACHE.get(wid) == "Guest":
        del WINDOW_PROFILE_CACHE[wid]
    if wid and open_names and WINDOW_PROFILE_CACHE.get(wid) not in open_names:
        # Cached name is for a profile Chrome no longer has open.
        if WINDOW_PROFILE_CACHE.get(wid):
            del WINDOW_PROFILE_CACHE[wid]

    # Check for [ProfileName]
    m = re.search(r"\[([^\]]+)\]", title)
    if m:
        prof = m.group(1).strip()
        if wid:
            WINDOW_PROFILE_CACHE[wid] = prof
        return prof

    # Check profile names explicitly mentioned in title (e.g. "Work - Google Chrome")
    for p_key, p_name in profiles.items():
        if p_name and p_name.lower() != "work":
            if f"({p_name})" in title or f" - {p_name}" in title:
                if wid:
                    WINDOW_PROFILE_CACHE[wid] = p_name
                return p_name

    if prof_session_data is None:
        prof_session_data = get_profile_session_data(chrome_dir)

    # Clean title for comparison
    title_clean = title.replace(" - Google Chrome", "").strip().lower()

    # Prefer open browser profiles when scoring session/title matches.
    score_keys = open_keys or list(profiles.keys())
    sorted_profs = sorted(
        ((k, prof_session_data[k]) for k in score_keys if k in prof_session_data),
        key=lambda item: item[1].get("mtime", 0),
        reverse=True,
    )

    best_prof = None
    best_score = 0

    for p_key, sdata in sorted_profs:
        if p_key not in profiles:
            continue
        p_name = profiles[p_key]
        score = 0

        for t in sdata.get("titles", []):
            if t == title_clean:
                score += 150
            elif len(t) >= 5 and (t in title_clean or title_clean in t):
                score += 100

        for d in sdata.get("domains", []):
            if len(d) >= 4 and d in title_clean:
                score += 40

        if score > 0:
            mtime = sdata.get("mtime", 0)
            recency = max(0, 30 - int((time.time() - mtime) / 3600))
            score += recency
            if open_keys and p_key in open_keys:
                score += 50

            if assigned_profiles and p_name in assigned_profiles:
                score -= 30

            if score > best_score:
                best_score = score
                best_prof = p_name

    if best_prof and best_score >= 40:
        if wid:
            WINDOW_PROFILE_CACHE[wid] = best_prof
        return best_prof

    if wid and wid in WINDOW_PROFILE_CACHE:
        cached = WINDOW_PROFILE_CACHE[wid]
        if not open_names or cached in open_names:
            return cached

    # Unassigned fallback: open browser profiles first (never invent Guest → Work)
    ranked_keys = open_keys or get_ranked_active_profiles(chrome_dir, profiles)
    if assigned_profiles:
        for k in ranked_keys:
            name = profiles.get(k, k)
            if name not in assigned_profiles:
                if wid:
                    WINDOW_PROFILE_CACHE[wid] = name
                return name

    if ranked_keys:
        p_name = profiles.get(ranked_keys[0], "Work")
        if wid:
            WINDOW_PROFILE_CACHE[wid] = p_name
        return p_name

    default_name = profiles.get("Default", "Work")
    if wid:
        WINDOW_PROFILE_CACHE[wid] = default_name
    return default_name


def _avatar_stamp(avatar_path) -> str:
    """Identity of the picture baked into a taskbar icon."""
    if avatar_path and os.path.isfile(avatar_path) and _accept_account_photo(avatar_path):
        st = os.stat(avatar_path)
        return f"photo|{os.path.abspath(avatar_path)}|{st.st_mtime_ns}|{st.st_size}"
    return "letter"


def _write_badge_stamp(png_path, avatar_path) -> None:
    if not png_path:
        return
    try:
        with open(png_path + ".src", "w", encoding="utf-8") as handle:
            handle.write(_avatar_stamp(avatar_path))
    except OSError:
        pass


def _badge_is_current(png_path, avatar_path):
    """True when this PNG was already drawn from this exact profile photo."""
    if not png_path or not os.path.isfile(png_path):
        return False
    try:
        with open(png_path + ".src", encoding="utf-8") as handle:
            saved = handle.read()
    except OSError:
        return False
    return saved == _avatar_stamp(avatar_path)


def _reassert_window_icons(home_dir, chrome_wins):
    """Put the profile photo back on the window. Does not touch the footer."""
    icons_48 = os.path.join(home_dir, ".local/share/icons/hicolor/48x48/apps")
    icons_128 = os.path.join(home_dir, ".local/share/icons/hicolor/128x128/apps")
    for w in chrome_wins:
        name = ""
        for part in (w.get("wm_class") or "").replace(".", " ").split():
            if part.lower().startswith("chrome-"):
                name = part
                break
        if not name:
            continue
        set_window_icon(
            w["id"],
            os.path.join(icons_48, name + ".png"),
            os.path.join(icons_128, name + ".png"),
        )


def apply_window_profiles(home_dir=None, panel=True):
    """
    Windows-like Chrome taskbar: one avatar icon per open profile, never grouped.

    Sets per-profile WM_CLASS + desktop file, badges the window icon, hides the
    idle Google Chrome pin while any browser window is open, and restores it when
    every window is closed.
    """
    global _LAST_PLASMA_LAUNCHERS
    if not home_dir:
        home_dir = os.path.expanduser("~")

    chrome_dir = os.path.join(home_dir, ".config/google-chrome")
    details = get_chrome_profile_details(chrome_dir)
    profiles = {k: v["name"] for k, v in details.items()}
    name_to_key = {v["name"]: k for k, v in details.items()}
    windows = get_x11_windows()

    chrome_wins = []
    active_wids = set()
    for w in windows:
        wc = w["wm_class"].lower()
        title = w["title"]
        active_wids.add(w["id"])

        if "crx_" in wc or "windows app" in title.lower() or "setting up" in title.lower():
            continue

        is_chrome = (
            "google-chrome" in wc
            or "chrome-" in wc
            or "google-chrome.devos-real" in wc
        )
        title_l = title.lower().strip()
        if is_chrome and (
            "google chrome" in title_l
            or wc.startswith("chrome-")
            or "gmail" in title_l
            or " - " in title
            or title_l in ("new tab", "new incognito tab", "about:blank")
            or title_l.startswith("new tab")
            or "browsing as a guest" in title_l
        ):
            chrome_wins.append(w)

    stale = [wid for wid in WINDOW_PROFILE_CACHE if wid not in active_wids]
    for wid in stale:
        del WINDOW_PROFILE_CACHE[wid]

    if not chrome_wins:
        apply_kwin_window_desktops([], home_dir)
        # Restore the idle pin in place. Restarting the panel hides the footer.
        sync_plasma_profile_launchers(home_dir, [])
        _LAST_PLASMA_LAUNCHERS = ()
        return 0

    icons_dir_48 = os.path.join(home_dir, ".local/share/icons/hicolor/48x48/apps")
    icons_dir_128 = os.path.join(home_dir, ".local/share/icons/hicolor/128x128/apps")
    os.makedirs(icons_dir_48, exist_ok=True)
    os.makedirs(icons_dir_128, exist_ok=True)

    assigned_profiles = set()
    processed = 0
    active_slugs = []
    window_classes = []
    kwin_rows = []
    prof_session_data = None

    # Profile icons and pin files. Skips work when the photo on disk is already current.
    sync_all_profiles(home_dir)

    for w in chrome_wins:
        # Do NOT mark profiles "assigned" across windows — two Work windows are
        # both Work; forcing the second onto Guest/Mirza made grouping worse.
        # Bookmark scan is the slow path. The process flag already names the profile.
        if prof_session_data is None and not _cmdline_profile_directory(_window_pid(w["id"])):
            prof_session_data = get_profile_session_data(chrome_dir)
        prof_name = detect_window_profile(
            w, profiles, home_dir, None, prof_session_data
        )
        slug = slugify(prof_name)
        if slug not in active_slugs:
            active_slugs.append(slug)
        is_guest = (prof_name or "").lower() == "guest" or slug == "guest"
        prof_key = None if is_guest else name_to_key.get(prof_name)
        avatar = None if is_guest else ((details.get(prof_key) or {}).get("avatar") if prof_key else None)

        icon_name = f"chrome-{slug}"
        prof_icon_48 = os.path.join(icons_dir_48, f"{icon_name}.png")
        prof_icon_128 = os.path.join(icons_dir_128, f"{icon_name}.png")
        if not (_badge_is_current(prof_icon_48, avatar) and _badge_is_current(prof_icon_128, avatar)):
            generate_badged_icon(prof_name, prof_icon_48, prof_icon_128, avatar_path=avatar)

        # Unique class+desktop+icon per WINDOW so tiles never share one graphic.
        class_name = window_task_class(slug, w["id"])
        win_icon_48 = os.path.join(icons_dir_48, f"{class_name}.png")
        win_icon_128 = os.path.join(icons_dir_128, f"{class_name}.png")
        try:
            if not _badge_is_current(win_icon_48, avatar):
                shutil.copyfile(prof_icon_48, win_icon_48)
            if not _badge_is_current(win_icon_128, avatar):
                shutil.copyfile(prof_icon_128, win_icon_128)
        except OSError:
            win_icon_48, win_icon_128 = prof_icon_48, prof_icon_128
        _install_icon_name(home_dir, class_name, win_icon_48, win_icon_128)
        _install_icon_name(home_dir, icon_name, prof_icon_48, prof_icon_128)
        set_window_icon(w["id"], win_icon_48, win_icon_128)

        # .desktop Icon= uses absolute path to the badge file installed above.
        desktop_name = ensure_window_task_desktop(
            home_dir, prof_name, slug, class_name, class_name
        )
        # Rewriting WM_CLASS on a window that already has it makes KWin drop
        # the task and the footer flashes. Set it once per profile.
        already = (w.get("wm_class") or "").lower()
        if class_name.lower() not in already and _APPLIED_CLASS.get(w["id"]) != class_name:
            set_window_wm_class(w["id"], class_name, class_name)
            set_window_desktop_file(w["id"], desktop_name, home_dir=home_dir)
            _APPLIED_CLASS[w["id"]] = class_name
        elif _APPLIED_CLASS.get(w["id"]) != class_name:
            set_window_desktop_file(w["id"], desktop_name, home_dir=home_dir)
            _APPLIED_CLASS[w["id"]] = class_name
        window_classes.append(class_name)
        kwin_rows.append({
            "id": w["id"],
            "pid": _window_pid(w["id"]),
            "title": w.get("title") or "",
            "desktop": desktop_name,
        })
        processed += 1

    # The running footer is left alone. Unloading the KWin script or rewriting
    # the taskbar pins removes the bar for a second or two, then it comes back.
    # Photos are applied with the window icon above. A manual `apply` may still
    # record the pin list for the next sign-in.
    if panel:
        apply_kwin_window_desktops(kwin_rows, home_dir)
        sync_plasma_profile_launchers(
            home_dir,
            active_slugs,
            window_desktops=[f"{c}.desktop" for c in window_classes],
        )
        _LAST_PLASMA_LAUNCHERS = tuple(sorted(window_classes))

    return processed


def _chrome_switch_identity(chrome_wins):
    """Window ids only.

    Profile-directory text from /proc flickers empty and then filled. Treating
    that flicker as a change rewrote WM_CLASS, KWin dropped the task, and the
    footer went empty for a second or two.
    """
    return tuple(w["id"] for w in chrome_wins)


_DESKTOP_ICON_BACKUP = {}
_PHOTO_PUSHED = None


def _swap_desktop_icon(path: str, new_icon: str) -> bool:
    """Point one launcher file at a profile photo. Remember the original Icon=."""
    if not path or not os.path.isfile(path):
        return False
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return False
    if path not in _DESKTOP_ICON_BACKUP:
        found = re.search(r"(?m)^Icon=.*$", text)
        line = found.group(0) if found else "Icon=google-chrome"
        # A previous run stored a bare face here. Closing Chrome must bring
        # the Chrome logo back, not that face.
        if "-face.png" in line or "-win.png" in line or "/hicolor/" in line:
            base = os.path.basename(path)
            line = "Icon=devos-browser" if base.startswith("devos-browser") else "Icon=google-chrome"
        _DESKTOP_ICON_BACKUP[path] = line
    new_line = f"Icon={new_icon}"
    if re.search(r"(?m)^" + re.escape(new_line) + r"\s*$", text):
        return False
    if re.search(r"(?m)^Icon=.*$", text):
        text = re.sub(r"(?m)^Icon=.*$", new_line, text, count=1)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += new_line + "\n"
    try:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    except OSError:
        return False
    return True


def _restore_desktop_icons() -> None:
    """Put the browser logo back on launcher files after Chrome closes."""
    global _PHOTO_PUSHED
    for path, line in list(_DESKTOP_ICON_BACKUP.items()):
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
            text = re.sub(r"(?m)^Icon=.*$", line, text, count=1)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError:
            pass
        _DESKTOP_ICON_BACKUP.pop(path, None)
    _PHOTO_PUSHED = None


def refresh_open_profile_icons(home_dir, chrome_wins) -> None:
    """Windows task button: Chrome logo with this account's photo on the corner.

    The logo stays. The photo is only the badge, and it is the photo of the
    profile this window opened. The panel is not reloaded.
    """
    global _PHOTO_PUSHED
    if not home_dir:
        home_dir = os.path.expanduser("~")
    if not chrome_wins:
        if _DESKTOP_ICON_BACKUP:
            _restore_desktop_icons()
        return
    chrome_dir = os.path.join(home_dir, ".config/google-chrome")
    details = get_chrome_profile_details(chrome_dir)
    profiles = {k: v["name"] for k, v in details.items()}
    name_to_key = {v["name"]: k for k, v in details.items()}
    icons_48 = os.path.join(home_dir, ".local/share/icons/hicolor/48x48/apps")
    icons_128 = os.path.join(home_dir, ".local/share/icons/hicolor/128x128/apps")
    os.makedirs(icons_48, exist_ok=True)
    os.makedirs(icons_128, exist_ok=True)
    open_badges = []
    for w in chrome_wins:
        wid = w.get("id")
        # The process flag is the profile this window actually opened. A cached
        # name can belong to a different account, and the button then shows
        # that account's face.
        pid = _window_pid(wid) if wid else 0
        prof_key = _cmdline_profile_key(pid) if pid else ""
        if prof_key and prof_key in details and (prof_key or "").lower() != "guest":
            prof_name = details[prof_key]["name"]
            avatar = (details.get(prof_key) or {}).get("avatar")
            if wid:
                WINDOW_PROFILE_CACHE[wid] = prof_name
        else:
            prof_name = WINDOW_PROFILE_CACHE.get(wid) if wid else None
            if not prof_name:
                prof_name = detect_window_profile(w, profiles, home_dir, None, None)
            slug_guess = slugify(prof_name or "")
            is_guest = (prof_name or "").lower() == "guest" or slug_guess == "guest"
            prof_key = None if is_guest else name_to_key.get(prof_name)
            avatar = None if is_guest else ((details.get(prof_key) or {}).get("avatar") if prof_key else None)
        slug = slugify(prof_name or "")
        is_guest = (prof_name or "").lower() == "guest" or slug == "guest"
        if is_guest:
            avatar = None
        icon_base = f"chrome-{slug}-win" if avatar else f"chrome-{slug}"
        icon_48 = os.path.join(icons_48, f"{icon_base}.png")
        icon_128 = os.path.join(icons_128, f"{icon_base}.png")
        if not (_badge_is_current(icon_48, avatar) and _badge_is_current(icon_128, avatar)):
            generate_badged_icon(prof_name, icon_48, icon_128, avatar_path=avatar)
        if not wid:
            continue
        # One file per window. A shared Chrome launcher was painting the first
        # account's photo onto every other browser button.
        class_name = window_task_class(slug or "chrome", int(wid))
        win_icon = os.path.join(icons_48, f"{class_name}.png")
        win_icon_128 = os.path.join(icons_128, f"{class_name}.png")
        try:
            if os.path.isfile(icon_48) and os.path.abspath(icon_48) != os.path.abspath(win_icon):
                shutil.copyfile(icon_48, win_icon)
            if os.path.isfile(icon_128) and os.path.abspath(icon_128) != os.path.abspath(win_icon_128):
                shutil.copyfile(icon_128, win_icon_128)
        except OSError:
            win_icon = icon_48
            win_icon_128 = icon_128
        ensure_window_task_desktop(home_dir, prof_name, slug, class_name, class_name)
        w["task_class"] = class_name
        w["task_desktop"] = f"{class_name}.desktop"
        set_window_icon(wid, win_icon, win_icon_128)
        shown = win_icon_128 if os.path.isfile(win_icon_128) else win_icon
        open_badges.append({
            "key": prof_key or slug or "",
            "icon": shown if os.path.isfile(shown) else "",
            "avatar": avatar if avatar and _accept_account_photo(avatar) else "",
        })
    # The footer button uses the shared Chrome launcher's Icon. One open
    # account: that icon is the Chrome logo with this account's photo.
    # Different accounts keep their own buttons and do not inherit the first.
    _apply_shared_launcher_icon(home_dir, open_badges)


def _shared_launcher_icon(rows):
    """Badge path for the shared Chrome button.

    One open account returns that account's Chrome-logo-plus-photo file.
    Two accounts return None so the first photo is not painted on the others.
    """
    keys = []
    icon = None
    for row in rows or []:
        key = (row or {}).get("key") or ""
        if not key:
            continue
        keys.append(key)
        if (row or {}).get("avatar") and (row or {}).get("icon"):
            icon = (row or {}).get("icon")
    if len(set(keys)) != 1 or not icon:
        return None
    return icon


def _point_shared_launchers(home_dir: str, target: str) -> bool:
    """Point the pinned Chrome button at one account's badged icon."""
    if not target or not os.path.isfile(target):
        return False
    target = os.path.abspath(target)
    _text, _section, existing = _read_launcher_entries(home_dir)
    apps = os.path.join(home_dir, ".local/share/applications")
    os.makedirs(apps, exist_ok=True)
    names = ["google-chrome.desktop", "devos-browser.desktop", "com.google.chrome.desktop"]
    for entry in existing or []:
        if not _is_chrome_launcher(entry):
            continue
        base = entry.split(":")[-1]
        if "-w" in base.lower():
            continue
        if base not in names:
            names.append(base)
    changed = False
    for base in names:
        path = os.path.join(apps, base)
        if not os.path.isfile(path):
            system = os.path.join("/usr/share/applications", base)
            if not os.path.isfile(system):
                continue
            try:
                shutil.copyfile(system, path)
            except OSError:
                continue
        if _swap_desktop_icon(path, target):
            changed = True
    return changed


def _apply_shared_launcher_icon(home_dir, rows) -> None:
    """Show this account's photo on the button the footer actually draws."""
    global _PHOTO_PUSHED
    target = _shared_launcher_icon(rows)
    if target:
        if target != _PHOTO_PUSHED:
            if _point_shared_launchers(home_dir, target):
                _refresh_service_cache()
            _PHOTO_PUSHED = target
        return
    if _PHOTO_PUSHED or _DESKTOP_ICON_BACKUP:
        _release_shared_chrome_icons(home_dir)
        if _DESKTOP_ICON_BACKUP:
            _restore_desktop_icons()
        _PHOTO_PUSHED = None


def _release_shared_chrome_icons(home_dir: str) -> None:
    """Stop the plain Chrome launcher from showing one account's photo.

    Each open window has its own button. The shared launcher is only the
    Chrome logo, and it is not the picture for every profile.
    """
    apps = os.path.join(home_dir, ".local/share/applications")
    for name, icon in (
        ("google-chrome.desktop", "google-chrome"),
        ("com.google.chrome.desktop", "google-chrome"),
        ("devos-browser.desktop", "devos-browser"),
    ):
        path = os.path.join(apps, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            continue
        found = re.search(r"(?m)^Icon=(.*)$", text)
        if not found:
            continue
        current = found.group(1).strip()
        if current == icon:
            continue
        if not (current.endswith(".png") or "/hicolor/" in current or "-win.png" in current or "-face.png" in current):
            continue
        text = re.sub(r"(?m)^Icon=.*$", f"Icon={icon}", text, count=1)
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError:
            continue


def bind_each_chrome_window_once(home_dir, chrome_wins) -> None:
    """Point each window at its own button, once.

    Repeating the class change drops the task and the footer flashes, so a
    window is tagged only the first time it is seen.
    """
    if not home_dir:
        home_dir = os.path.expanduser("~")
    for w in chrome_wins or []:
        wid = w.get("id")
        class_name = w.get("task_class") or ""
        desk = w.get("task_desktop") or ""
        if not wid or not class_name:
            continue
        already = (w.get("wm_class") or "").lower()
        if class_name.lower() not in already and _APPLIED_CLASS.get(wid) != class_name:
            set_window_wm_class(wid, class_name, class_name)
            _APPLIED_CLASS[wid] = class_name
        if desk and _APPLIED_CLASS.get(f"desk:{wid}") != desk:
            set_window_desktop_file(wid, desk, home_dir=home_dir)
            _APPLIED_CLASS[f"desk:{wid}"] = desk


def _refresh_service_cache() -> None:
    """Make Plasma read the new Icon= path. Does not restart the desktop."""
    import subprocess
    tool = shutil.which("kbuildsycoca6") or shutil.which("kbuildsycoca5")
    if not tool:
        return
    try:
        subprocess.run(
            [tool, "--noincremental"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass


def paint_chrome_icons(home_dir, chrome_wins):
    """Put the profile photo on each window. Do not retag it or touch the panel."""
    if not home_dir:
        home_dir = os.path.expanduser("~")
    chrome_dir = os.path.join(home_dir, ".config/google-chrome")
    details = get_chrome_profile_details(chrome_dir)
    profiles = {k: v["name"] for k, v in details.items()}
    name_to_key = {v["name"]: k for k, v in details.items()}
    icons_48 = os.path.join(home_dir, ".local/share/icons/hicolor/48x48/apps")
    icons_128 = os.path.join(home_dir, ".local/share/icons/hicolor/128x128/apps")
    os.makedirs(icons_48, exist_ok=True)
    os.makedirs(icons_128, exist_ok=True)
    for w in chrome_wins:
        wid = w["id"]
        pid = _window_pid(wid) if wid else 0
        prof_key = _cmdline_profile_key(pid) if pid else ""
        if prof_key and prof_key in details and str(prof_key).lower() != "guest":
            prof_name = details[prof_key]["name"]
            avatar = (details.get(prof_key) or {}).get("avatar")
        else:
            prof_name = WINDOW_PROFILE_CACHE.get(wid)
            if not prof_name:
                prof_name = detect_window_profile(w, profiles, home_dir, None, None)
            slug = slugify(prof_name)
            is_guest = (prof_name or "").lower() == "guest" or slug == "guest"
            prof_key = None if is_guest else name_to_key.get(prof_name)
            avatar = None if is_guest else ((details.get(prof_key) or {}).get("avatar") if prof_key else None)
        slug = slugify(prof_name or "")
        if (prof_name or "").lower() == "guest" or slug == "guest":
            avatar = None
        icon_base = f"chrome-{slug}-win" if avatar else f"chrome-{slug}"
        icon_48 = os.path.join(icons_48, f"{icon_base}.png")
        icon_128 = os.path.join(icons_128, f"{icon_base}.png")
        if not (_badge_is_current(icon_48, avatar) and _badge_is_current(icon_128, avatar)):
            generate_badged_icon(prof_name, icon_48, icon_128, avatar_path=avatar)
        set_window_icon(wid, icon_48, icon_128)


def keep_footer_visible(home_dir=None) -> bool:
    """Keep the bottom panel on screen. Dodge-windows hides it under a maximized app."""
    home = home_dir or os.path.expanduser("~")
    cfg = Path(home) / ".config" / "plasma-org.kde.plasma.desktop-appletsrc"
    if not cfg.is_file():
        return False
    text = cfg.read_text(encoding="utf-8", errors="replace")
    parts = re.split(r"(?m)(?=^\[)", text)
    changed = False
    out = []
    for part in parts:
        header = part.split("\n", 1)[0].strip()
        own = part.split("\n[", 1)[0]
        if re.fullmatch(r"\[Containments\]\[\d+\]", header) and "plugin=org.kde.panel" in own:
            if re.search(r"(?m)^hiding=(?!0\s*$)", own):
                part = re.sub(r"(?m)^hiding=.*$", "hiding=0", part, count=1)
                changed = True
            elif not re.search(r"(?m)^hiding=", own):
                part = part if part.endswith("\n") else part + "\n"
                part += "hiding=0\n"
                changed = True
        out.append(part)
    if not changed:
        # Already always-visible. Asking plasmashell to set it again repaints
        # the bar and the footer disappears for a second or two.
        return False
    cfg.write_text("".join(out), encoding="utf-8")
    # The file is corrected for the next sign-in. Do not push it into the
    # running shell: that call removes the footer, then draws it again.
    return changed


def watch_chrome_windows(home_dir=None, poll_interval=None):
    """Monitor Chrome windows and refresh taskbar profile icons.

    Default poll is 5s (was 1s) — still snappy when switching profiles, far
    cheaper at idle. Override with DEVOS_CHROME_POLL_S.
    """
    if not home_dir:
        home_dir = os.path.expanduser("~")
    if poll_interval is None:
        try:
            poll_interval = float(os.environ.get("DEVOS_CHROME_POLL_S", "5"))
        except ValueError:
            poll_interval = 5.0
    poll_interval = max(2.0, float(poll_interval))

    # Initial sync + immediate apply so existing windows ungroup without waiting
    # for the first poll cycle. Pin the footer so a maximized window cannot cover it.
    try:
        keep_footer_visible(home_dir)
    except Exception:
        pass
    last_ident = None
    last_icon = 0.0
    while True:
        try:
            wins = get_x11_windows()
            chrome_wins = [
                w for w in wins
                if ("google-chrome" in w["wm_class"].lower() or "chrome-" in w["wm_class"].lower())
                and "crx_" not in w["wm_class"].lower()
                and "windows app" not in w["title"].lower()
                and "setting up" not in w["title"].lower()
            ]
            ident = _chrome_switch_identity(chrome_wins)
            now = time.time()

            # The profile photo goes on the button as soon as the window is
            # open. Waiting here left Chrome's own logo on the footer.
            try:
                refresh_open_profile_icons(home_dir, chrome_wins)
                bind_each_chrome_window_once(home_dir, chrome_wins)
            except Exception:
                pass

            # A window opened or closed. Drop every browser button once Chrome
            # is gone. Title changes are not part of ident. If the running bar
            # does not accept the list, try again on the next pass.
            if ident != last_ident:
                try:
                    if publish_chrome_task_launchers(home_dir, chrome_wins):
                        last_ident = ident
                except Exception:
                    pass

            # Photos only. Never retag the window and never reload the panel:
            # both of those remove the footer for a second or two.
            if chrome_wins and now - last_icon >= 15:
                paint_chrome_icons(home_dir, chrome_wins)
                last_icon = now
            sleep_for = 1.0 if (chrome_wins or ident != last_ident) else max(poll_interval, 15.0)

        except Exception:
            sleep_for = poll_interval

        time.sleep(sleep_for)


def class_for_profile_key(profile_key: str, home_dir=None) -> str:
    """Return chrome-<slug> for a profile directory key (Default, Profile 1, …)."""
    key = (profile_key or "").strip() or "Default"
    if key.lower() == "guest":
        return "chrome-guest"
    home = home_dir or os.path.expanduser("~")
    chrome_dir = os.path.join(home, ".config/google-chrome")
    profiles = get_chrome_profiles(chrome_dir)
    name = profiles.get(key) or key
    return f"chrome-{slugify(name)}"


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "sync"
    if action == "sync":
        created = sync_all_profiles()
        print(f"Synced {len(created)} Chrome profile launchers and badged icons.")
    elif action == "apply":
        n = apply_window_profiles()
        print(f"Applied profile badging to {n} Chrome windows.")
    elif action == "watch":
        print("Starting DevOS Chrome Profile Watcher...")
        watch_chrome_windows()
    elif action == "class-for":
        key = sys.argv[2] if len(sys.argv) > 2 else "Default"
        print(class_for_profile_key(key))
    else:
        print(f"Unknown action: {action}. Use sync, apply, watch, or class-for.")
