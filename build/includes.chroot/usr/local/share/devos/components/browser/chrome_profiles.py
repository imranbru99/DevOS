#!/usr/bin/env python3
"""
DevOS Chrome Profile & Icon Manager
Generates distinct badged icons and desktop entries for each Google Chrome profile
(e.g., Work, Mirza, Tony, Guest) so each profile window appears as its own icon
with its profile name clearly visible inside the icon on the taskbar.
Also runs a dynamic watcher that unifies open windows with taskbar launchers
so pinned Chrome icons are never duplicated.
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
                name = val.get("name") or key
                profiles[key] = name
        except Exception:
            pass
    if not profiles:
        profiles["Default"] = "Work"
    return profiles


def get_profile_avatar_path(config_dir, profile_key, info=None):
    """Return the on-disk Google account / profile picture for a Chrome profile."""
    if not config_dir or not profile_key or profile_key == "guest":
        return None
    folder = os.path.join(config_dir, profile_key)
    candidates = []
    picture_name = None
    if isinstance(info, dict):
        picture_name = info.get("gaia_picture_file_name") or info.get("last_downloaded_gaia_picture_url_with_size")
        if isinstance(picture_name, str) and "/" not in picture_name and picture_name.endswith((".png", ".jpg", ".jpeg", ".webp")):
            candidates.append(os.path.join(folder, picture_name))
    for name in (
        "Google Profile Picture.png",
        "Google Profile Picture.jpg",
        "profile_picture.png",
    ):
        candidates.append(os.path.join(folder, name))
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


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


def generate_badged_icon(name, output_48, output_128=None, base_icon=None, avatar_path=None):
    """
    Windows-style Chrome profile icon: stock Chrome logo with the profile's
    Google account photo as a circular badge in the lower-right corner.
    Falls back to a short name pill when no avatar image is available.
    """
    if not base_icon or not os.path.isfile(base_icon):
        base_icon = get_stock_chrome_icon()

    if base_icon and os.path.isfile(base_icon):
        img = Image.open(base_icon).convert("RGBA").resize((128, 128), Image.Resampling.LANCZOS)
    else:
        img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 120, 120], fill=(66, 133, 244, 255))

    draw = ImageDraw.Draw(img)
    used_avatar = False
    if avatar_path and os.path.isfile(avatar_path):
        try:
            badge_size = 56
            ring = 4
            badge = _circle_crop(Image.open(avatar_path), badge_size)
            # White ring behind the photo (Windows taskbar style).
            cx = 128 - badge_size // 2 - 4
            cy = 128 - badge_size // 2 - 4
            outer = badge_size + ring * 2
            ring_img = Image.new("RGBA", (outer, outer), (0, 0, 0, 0))
            ImageDraw.Draw(ring_img).ellipse(
                (0, 0, outer - 1, outer - 1),
                fill=(255, 255, 255, 245),
            )
            ring_img.paste(badge, (ring, ring), badge)
            img.alpha_composite(ring_img, (cx - outer // 2, cy - outer // 2))
            used_avatar = True
        except Exception:
            used_avatar = False

    if not used_avatar:
        label = (name or "Chrome").strip().split()[0][:7].upper() or "CHROME"
        bg_color = get_profile_color(name or "Chrome")
        font = None
        for font_path in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        ]:
            if os.path.isfile(font_path):
                try:
                    font_size = 22 if len(label) <= 4 else (19 if len(label) <= 6 else 16)
                    font = ImageFont.truetype(font_path, font_size)
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
    img_48.save(output_48)

    if output_128:
        os.makedirs(os.path.dirname(os.path.abspath(output_128)), exist_ok=True)
        img.save(output_128)


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
        else "devos-browser"
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
Exec={devos_bin}

[Desktop Action new-private-window]
Name=New Incognito Window
Exec={devos_bin} --incognito

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

    all_profiles = list(profiles.items())
    all_profiles.append(("guest", "Guest"))

    created_desktops = []

    devos_bin = (
        os.path.join(home_dir, ".local/bin/devos-browser")
        if os.path.isfile(os.path.join(home_dir, ".local/bin/devos-browser"))
        else "devos-browser"
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
    # Default launcher opens the first/default profile with its own WM class so
    # Plasma/GNOME can show a separate avatar icon per profile, like Windows.
    default_key = "Default" if "Default" in profiles else (all_profiles[0][0] if all_profiles else "Default")
    default_name = profiles.get(default_key, "Chrome")
    default_slug = slugify(default_name)
    default_class = f"chrome-{default_slug}"
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

        generate_badged_icon(name, icon_file_48, icon_file_128, avatar_path=avatar)

        desktop_file = os.path.join(apps_dir, f"{icon_name}.desktop")
        wm_class = icon_name

        if key == "guest":
            exec_cmd = f"{devos_bin} --guest --class=chrome-guest"
        else:
            exec_cmd = f'{devos_bin} --profile-directory="{key}" --class={wm_class}'

        content = f"""[Desktop Entry]
Version=1.0
Name=Google Chrome ({name})
GenericName=Web Browser
Comment=Access the Internet as {name}
Exec={exec_cmd} %U
StartupNotify=true
StartupWMClass={wm_class}
Terminal=false
Icon={icon_name}
Type=Application
Categories=Network;WebBrowser;
{common_actions}"""
        with open(desktop_file, "w", encoding="utf-8") as f:
            f.write(content)
        created_desktops.append(desktop_file)

    # Main Chrome launcher uses the default profile's avatar + WM class so the
    # taskbar shows the profile photo instead of a generic Chrome blob.
    default_avatar = (details.get(default_key) or {}).get("avatar")
    generate_badged_icon(
        default_name,
        os.path.join(icons_dir_48, "google-chrome.png"),
        os.path.join(icons_dir_128, "google-chrome.png"),
        avatar_path=default_avatar,
    )
    user_desktop = os.path.join(home_dir, ".local/share/applications/google-chrome.desktop")
    base_content = f"""[Desktop Entry]
Version=1.0
Name=Google Chrome
GenericName=Web Browser
Comment=Access the Internet
Exec={devos_bin} --profile-directory="{default_key}" --class={default_class} %U
StartupNotify=true
StartupWMClass={default_class}
Terminal=false
Icon=google-chrome
Type=Application
Categories=Network;WebBrowser;
MimeType=application/pdf;application/rdf+xml;application/rss+xml;application/xhtml+xml;application/xhtml_xml;application/xml;image/gif;image/jpeg;image/png;image/webp;text/html;text/xml;x-scheme-handler/http;x-scheme-handler/https;
{common_actions}"""
    with open(user_desktop, "w", encoding="utf-8") as f:
        f.write(base_content)

    # Ensure com.google.Chrome.desktop symlinks to google-chrome.desktop so pinned launcher unifies in-place
    com_chrome = os.path.join(apps_dir, "com.google.Chrome.desktop")
    if not os.path.exists(com_chrome) or os.path.islink(com_chrome):
        try:
            if os.path.lexists(com_chrome):
                os.remove(com_chrome)
            os.symlink("google-chrome.desktop", com_chrome)
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

    return created_desktops


# --- X11 Window Management & Profile Watcher ---

WINDOW_PROFILE_CACHE = {}
_LAST_PLASMA_LAUNCHERS = None


def set_window_icon(wid, icon_path_48, icon_path_128=None):
    """Set _NET_WM_ICON on an X11 window using libX11.so.6."""
    paths = [p for p in [icon_path_48, icon_path_128] if p and os.path.isfile(p)]
    if not paths:
        return
    try:
        x11 = ctypes.CDLL("libX11.so.6")
        x11.XOpenDisplay.restype = ctypes.c_void_p

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
            img = Image.open(p).convert("RGBA")
            w, h = img.size
            pixels.append(w)
            pixels.append(h)
            for y in range(h):
                for x in range(w):
                    r, g, b, a = img.getpixel((x, y))
                    argb = (a << 24) | (r << 16) | (g << 8) | b
                    pixels.append(argb)

        c_data = (ctypes.c_ulong * len(pixels))(*pixels)
        x11.XChangeProperty(
            display,
            wid,
            net_wm_icon,
            cardinal,
            32,
            0,  # PropModeReplace
            ctypes.cast(c_data, ctypes.POINTER(ctypes.c_ubyte)),
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


def set_window_desktop_file(wid, desktop_slug, home_dir=None):
    """Point the window at a distinct .desktop so Plasma can split task icons."""
    try:
        import subprocess
        slug = desktop_slug if desktop_slug.endswith(".desktop") else f"{desktop_slug}.desktop"
        home = home_dir or os.path.expanduser("~")
        abs_desktop = os.path.join(home, ".local/share/applications", slug)
        if not os.path.isfile(abs_desktop):
            abs_desktop = f"/usr/share/applications/{slug}"
        for atom, value in (
            ("_KDE_NET_WM_DESKTOP_FILE", slug),
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


def set_window_wm_class(wid, class_name, class_inst=None):
    """Set a proper two-part WM_CLASS (instance + class) via XSetClassHint / xdotool."""
    inst = (class_inst or class_name or "chrome").encode("utf-8")
    cls = (class_name or "chrome").encode("utf-8")
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
            return
    except Exception:
        pass
    try:
        import subprocess
        subprocess.run(
            [
                "xdotool",
                "set_window",
                "--classname",
                inst.decode(),
                "--class",
                cls.decode(),
                str(wid),
            ],
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
        if re.search(r"(?m)^plugin=org\.kde\.plasma\.icontasks\s*$", block):
            return f"[Containments][{cont}][Applets][{applet}][Configuration][General]"
    return None


def _is_chrome_launcher(entry: str) -> bool:
    e = (entry or "").strip().lower()
    return (
        "google-chrome.desktop" in e
        or "com.google.chrome.desktop" in e
        or re.search(r"(^|/)chrome-[a-z0-9-]+\.desktop$", e) is not None
        or "applications:chrome-" in e
    )


def sync_plasma_profile_launchers(home_dir=None, active_slugs=None):
    """
    Pin Chrome like Windows:
    - No Chrome windows → show the pinned Google Chrome icon.
    - Any Chrome window open → hide that pin; show only running profile icons.
    Other pinned apps are preserved.
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
    preserved = [e for e in existing if not _is_chrome_launcher(e)]

    apps_dir = os.path.join(home, ".local/share/applications")
    active = [(s or "").strip().lower() for s in (active_slugs or []) if (s or "").strip()]
    chrome_launchers = []
    if active:
        # Browser is open → do not show the idle pinned Google Chrome icon.
        seen = set()
        for slug in active:
            if slug in seen or slug in {"default"}:
                continue
            desktop = f"chrome-{slug}.desktop"
            if not os.path.isfile(os.path.join(apps_dir, desktop)):
                # Work often only has google-chrome.desktop; ensure chrome-work exists via sync.
                continue
            chrome_launchers.append(f"applications:{desktop}")
            seen.add(slug)
    else:
        # Nothing open → restore the normal pinned Chrome launcher.
        chrome_launchers = ["applications:google-chrome.desktop"]

    launchers = preserved + chrome_launchers
    updates = {
        "launchers": ",".join(launchers) if launchers else "applications:google-chrome.desktop",
        "separateLaunchers": "true",
        "groupingStrategy": "0",
        "launchInPlace": "true",
        # Hide a pin when its own window is running (profile pins).
        "hideActivatedLaunchers": "true",
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
    cfg.write_text("".join(out), encoding="utf-8")
    return True


_LAST_PLASMA_RELOAD = 0.0


def reload_plasmashell():
    """Restart plasmashell so Icon Tasks picks up launcher changes (rate-limited)."""
    global _LAST_PLASMA_RELOAD
    now = time.time()
    if now - _LAST_PLASMA_RELOAD < 45:
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


def get_ranked_active_profiles(chrome_dir, profiles):
    """
    Return profile keys ordered by recent active browser usage,
    ignoring background PWAs that touch Default.
    """
    ranked = []
    seen = set()

    local_state = os.path.join(chrome_dir, "Local State")
    if os.path.isfile(local_state):
        try:
            with open(local_state, "r", encoding="utf-8") as f:
                ls = json.load(f)
            last_active = ls.get("profile", {}).get("last_active_profiles") or []
            for p in last_active:
                if p in profiles and p not in seen:
                    ranked.append(p)
                    seen.add(p)
        except Exception:
            pass

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


def _cmdline_looks_guest(raw: str) -> bool:
    text = f" {(raw or '').lower()} "
    return (
        " --guest " in text
        or text.strip().endswith("--guest")
        or "guest profile" in text
        or "/guest profile" in text
        or "profile-directory=guest" in text
    )


def _cmdline_is_guest(pid: int) -> bool:
    """True when this Chrome process (or a close parent) is a Guest session."""
    if not pid:
        return False
    seen = set()
    cur = pid
    for _ in range(4):
        if not cur or cur in seen:
            break
        seen.add(cur)
        if _cmdline_looks_guest(_read_proc_cmdline(cur)):
            return True
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
    return False


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
    - Explicit launch WM_CLASS (e.g. chrome-traveling) before title heuristics
    - Title markers, session/bookmark match, then ranked fallback
    """
    wid = w.get("id") if isinstance(w, dict) else None
    title = w.get("title", "") if isinstance(w, dict) else str(w)
    wm_class = (w.get("wm_class", "") if isinstance(w, dict) else "").lower()
    pid = _window_pid(wid) if wid else 0
    is_guest_proc = bool(wid and _cmdline_is_guest(pid))

    # Guest only when the process/class really is Guest — never sticky forever.
    if is_guest_proc or "chrome-guest" in wm_class:
        if wid:
            WINDOW_PROFILE_CACHE[wid] = "Guest"
        return "Guest"
    # Title "(Guest)" / " - Guest" only — bare word "Guest" in page titles is too noisy.
    if re.search(r"(\(Guest\)| - Guest( - |$))", title or "", re.IGNORECASE):
        if wid:
            WINDOW_PROFILE_CACHE[wid] = "Guest"
        return "Guest"

    # Trust an already-assigned per-profile WM_CLASS (Windows-style split).
    class_prof = _wm_class_profile(wm_class, profiles)
    if class_prof and class_prof != "Guest":
        if wid:
            WINDOW_PROFILE_CACHE[wid] = class_prof
        return class_prof

    # Drop a stale Guest cache entry once this window is clearly not Guest.
    if wid and WINDOW_PROFILE_CACHE.get(wid) == "Guest":
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

    if not home_dir:
        home_dir = os.path.expanduser("~")
    chrome_dir = os.path.join(home_dir, ".config/google-chrome")

    if prof_session_data is None:
        prof_session_data = get_profile_session_data(chrome_dir)

    # Clean title for comparison
    title_clean = title.replace(" - Google Chrome", "").strip().lower()

    # Rank profiles by match score for this title
    sorted_profs = sorted(
        prof_session_data.items(),
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
        return WINDOW_PROFILE_CACHE[wid]

    # Unassigned fallback using ranked active profiles (never invent Guest → Work)
    ranked_keys = get_ranked_active_profiles(chrome_dir, profiles)
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


def apply_window_profiles(home_dir=None):
    """
    Inspect all open Chrome windows and assign profile desktop files and badged icons.
    Each profile window gets its own badged icon and desktop entry on the taskbar.
    When browser windows are open, the pinned launcher is hidden so no blank/unbadged
    icons remain. When all windows close, the pinned launcher is restored.
    """
    global _LAST_PLASMA_LAUNCHERS
    if not home_dir:
        home_dir = os.path.expanduser("~")

    chrome_dir = os.path.join(home_dir, ".config/google-chrome")
    details = get_chrome_profile_details(chrome_dir)
    profiles = {k: v["name"] for k, v in details.items()}
    name_to_key = {v["name"]: k for k, v in details.items()}
    windows = get_x11_windows()

    # Filter for real Chrome browser windows (exclude PWAs like Windows App, Maps, etc.)
    chrome_wins = []
    active_wids = set()
    for w in windows:
        wc = w["wm_class"].lower()
        title = w["title"]
        active_wids.add(w["id"])

        # Strictly ignore any Chrome PWA / Chrome App (starts with crx_) or Windows App
        if "crx_" in wc or "windows app" in title.lower() or "setting up" in title.lower():
            continue

        # Match stock Chrome, DevOS wrapper (.devos-real), and per-profile classes.
        is_chrome = (
            "google-chrome" in wc
            or "chrome-" in wc
            or "google-chrome.devos-real" in wc
        )
        if is_chrome and (
            "google chrome" in title.lower()
            or wc.startswith("chrome-")
            or "gmail" in title.lower()
            or " - " in title
        ):
            chrome_wins.append(w)

    # Clean up stale window profile cache entries
    stale = [wid for wid in WINDOW_PROFILE_CACHE if wid not in active_wids]
    for wid in stale:
        del WINDOW_PROFILE_CACHE[wid]

    if not chrome_wins:
        # Restore the pinned Google Chrome icon when every window is closed.
        if sync_plasma_profile_launchers(home_dir, []):
            if _LAST_PLASMA_LAUNCHERS != ():
                _LAST_PLASMA_LAUNCHERS = ()
                reload_plasmashell()
        return 0

    prof_session_data = get_profile_session_data(chrome_dir)

    icons_dir_48 = os.path.join(home_dir, ".local/share/icons/hicolor/48x48/apps")
    icons_dir_128 = os.path.join(home_dir, ".local/share/icons/hicolor/128x128/apps")

    assigned_profiles = set()
    processed = 0
    active_slugs = []
    default_key = "Default" if "Default" in profiles else next(iter(profiles), "Default")
    default_name = profiles.get(default_key, "Chrome")
    default_slug = slugify(default_name)

    for w in chrome_wins:
        prof_name = detect_window_profile(w, profiles, home_dir, assigned_profiles, prof_session_data)
        assigned_profiles.add(prof_name)
        slug = slugify(prof_name)
        if slug not in active_slugs:
            active_slugs.append(slug)
        is_guest = (prof_name or "").lower() == "guest" or slug == "guest"
        prof_key = None if is_guest else name_to_key.get(prof_name)
        # Guest never inherits a signed-in profile photo.
        avatar = None if is_guest else ((details.get(prof_key) or {}).get("avatar") if prof_key else None)

        # Ensure avatar-badged icon for this profile exists / stays fresh
        prof_icon_48 = os.path.join(icons_dir_48, f"chrome-{slug}.png")
        prof_icon_128 = os.path.join(icons_dir_128, f"chrome-{slug}.png")
        generate_badged_icon(prof_name, prof_icon_48, prof_icon_128, avatar_path=avatar)

        # Apply _NET_WM_ICON directly to window
        set_window_icon(w["id"], prof_icon_48, prof_icon_128)

        # Every profile gets its own desktop id + WM class (Windows-style split icons).
        # The pinned Google Chrome launcher uses the default profile's class.
        class_name = f"chrome-{slug}"
        set_window_wm_class(w["id"], class_name, class_name)
        # Always use the per-profile desktop id so the idle google-chrome pin
        # can be removed while any Chrome window is open.
        set_window_desktop_file(w["id"], f"chrome-{slug}.desktop", home_dir=home_dir)
        if not is_guest and (prof_name == default_name or slug == default_slug):
            try:
                shutil.copyfile(prof_icon_48, os.path.join(icons_dir_48, "google-chrome.png"))
                shutil.copyfile(prof_icon_128, os.path.join(icons_dir_128, "google-chrome.png"))
            except Exception:
                pass

        processed += 1

    # Teach Plasma Icon Tasks about each open profile; drop the idle Chrome pin.
    launcher_key = tuple(active_slugs)
    if sync_plasma_profile_launchers(home_dir, active_slugs):
        if launcher_key != _LAST_PLASMA_LAUNCHERS:
            _LAST_PLASMA_LAUNCHERS = launcher_key
            reload_plasmashell()

    return processed


def watch_chrome_windows(home_dir=None, poll_interval=1.0):
    """Continuously monitor and badge Chrome windows."""
    if not home_dir:
        home_dir = os.path.expanduser("~")

    # Initial sync
    sync_all_profiles(home_dir)

    last_win_state = None
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
            cur_state = [(w["id"], w["title"]) for w in chrome_wins]

            if cur_state != last_win_state:
                apply_window_profiles(home_dir)
                last_win_state = cur_state

        except Exception as e:
            pass

        time.sleep(poll_interval)


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
    else:
        print(f"Unknown action: {action}. Use sync, apply, or watch.")
