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


def generate_badged_icon(name, output_48, output_128=None, base_icon=None):
    """
    Render a Google Chrome icon with a bold, high-contrast banner containing the
    profile name directly inside/on the icon at the bottom.
    """
    if not base_icon or not os.path.isfile(base_icon):
        base_icon = get_stock_chrome_icon()

    if base_icon and os.path.isfile(base_icon):
        img = Image.open(base_icon).convert("RGBA").resize((128, 128), Image.Resampling.LANCZOS)
    else:
        # Fallback circle if base icon is missing
        img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 120, 120], fill=(66, 133, 244, 255))

    draw = ImageDraw.Draw(img)

    # Pick display text: first word, uppercase, up to 7 characters for maximum legibility
    label = name.strip().split()[0][:7].upper()
    bg_color = get_profile_color(name)

    # Try font
    font = None
    for font_path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]:
        if os.path.isfile(font_path):
            try:
                # Dynamic font size based on label length
                font_size = 22 if len(label) <= 4 else (19 if len(label) <= 6 else 16)
                font = ImageFont.truetype(font_path, font_size)
                break
            except Exception:
                pass

    # Draw bottom pill banner: [4, 76, 124, 124] (covers bottom third with rounded corners)
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
Exec={devos_bin} --guest
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

    profiles = get_chrome_profiles(os.path.join(home_dir, ".config/google-chrome"))

    all_profiles = list(profiles.items())
    all_profiles.append(("guest", "Guest"))

    created_desktops = []

    devos_bin = (
        os.path.join(home_dir, ".local/bin/devos-browser")
        if os.path.isfile(os.path.join(home_dir, ".local/bin/devos-browser"))
        else "devos-browser"
    )

    for key, name in all_profiles:
        slug = slugify(key if key == "guest" else (name or key))
        icon_name = f"chrome-{slug}"
        icon_file_48 = os.path.join(icons_dir_48, f"{icon_name}.png")
        icon_file_128 = os.path.join(icons_dir_128, f"{icon_name}.png")

        generate_badged_icon(name, icon_file_48, icon_file_128)

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
"""
        with open(desktop_file, "w", encoding="utf-8") as f:
            f.write(content)
        created_desktops.append(desktop_file)

    # Update google-chrome.desktop with all profile actions
    update_google_chrome_desktop(home_dir, all_profiles)

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


def set_window_desktop_file(wid, desktop_slug):
    """Set _KDE_NET_WM_DESKTOP_FILE on an X11 window."""
    try:
        import subprocess
        subprocess.run(
            ["xprop", "-id", hex(wid), "-f", "_KDE_NET_WM_DESKTOP_FILE", "8s", "-set", "_KDE_NET_WM_DESKTOP_FILE", desktop_slug],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def set_window_wm_class(wid, class_name, class_inst=None):
    """Set WM_CLASS on an X11 window."""
    try:
        import subprocess
        inst = class_inst if class_inst else class_name
        subprocess.run(
            ["xprop", "-id", hex(wid), "-f", "WM_CLASS", "8s", "-set", "WM_CLASS", inst, class_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def get_profile_tab_domains(chrome_config_dir):
    """Extract significant domains open in each profile from Sessions/Tabs_*."""
    domains_map = {}
    if not os.path.isdir(chrome_config_dir):
        return domains_map
    for p in os.listdir(chrome_config_dir):
        sess_dir = os.path.join(chrome_config_dir, p, "Sessions")
        if not os.path.isdir(sess_dir):
            continue
        files = sorted(glob.glob(os.path.join(sess_dir, "Tabs_*")), key=os.path.getmtime)
        if not files:
            continue
        try:
            with open(files[-1], "rb") as f:
                data = f.read()
            urls = re.findall(rb"https?://([a-zA-Z0-9\.\-_]+)", data)
            domains = set()
            for u in urls:
                parts = u.decode("utf-8", errors="ignore").lower().split(".")
                if len(parts) >= 2:
                    domains.add(parts[-2])
            domains_map[p] = domains
        except Exception:
            pass
    return domains_map


def detect_window_profile(w, profiles, home_dir=None):
    """
    Determine profile name from window attributes and session activity:
    e.g. WM_CLASS "chrome-mirza" -> "Mirza"
         Title "Facebook - Google Chrome" -> "Tony" (from Profile 2 tabs)
         Title "WhatsApp - Google Chrome" -> "Mirza" (from Profile 1 tabs)
    """
    wid = w.get("id") if isinstance(w, dict) else None
    title = w.get("title", "") if isinstance(w, dict) else str(w)
    wm_class = w.get("wm_class", "") if isinstance(w, dict) else ""

    if wid and wid in WINDOW_PROFILE_CACHE:
        return WINDOW_PROFILE_CACHE[wid]

    # Check wm_class if launched with --class=chrome-<slug>
    for p_key, p_name in profiles.items():
        slug = slugify(p_name)
        if f"chrome-{slug}" in wm_class.lower():
            if wid:
                WINDOW_PROFILE_CACHE[wid] = p_name
            return p_name

    # Check for [ProfileName]
    m = re.search(r"\[([^\]]+)\]", title)
    if m:
        prof = m.group(1).strip()
        if wid:
            WINDOW_PROFILE_CACHE[wid] = prof
        return prof

    # Check for (Guest) or Guest
    if re.search(r"\bGuest\b", title, re.IGNORECASE):
        if wid:
            WINDOW_PROFILE_CACHE[wid] = "Guest"
        return "Guest"

    # Check profile names explicitly mentioned in title
    for p_key, p_name in profiles.items():
        if p_name and p_name.lower() != "work":
            if f"({p_name})" in title or f" - {p_name}" in title:
                if wid:
                    WINDOW_PROFILE_CACHE[wid] = p_name
                return p_name

    # Match domain / tab keywords against profile active sessions
    if not home_dir:
        home_dir = os.path.expanduser("~")
    chrome_dir = os.path.join(home_dir, ".config/google-chrome")
    tab_domains = get_profile_tab_domains(chrome_dir)
    title_lower = title.lower()

    for prof_key, domains in tab_domains.items():
        p_name = profiles.get(prof_key, prof_key)
        for d in domains:
            if len(d) >= 4 and d in title_lower:
                if wid:
                    WINDOW_PROFILE_CACHE[wid] = p_name
                return p_name

    # Check most recently active profile in Local State or Sessions
    local_state = os.path.join(chrome_dir, "Local State")
    if os.path.isfile(local_state):
        try:
            with open(local_state, "r", encoding="utf-8") as f:
                d = json.load(f)
            prof_key = d.get("profile", {}).get("last_used")
            if not prof_key:
                active_list = d.get("profile", {}).get("last_active_profiles")
                if active_list and isinstance(active_list, list) and active_list[0]:
                    prof_key = active_list[0]
            if prof_key and prof_key in profiles:
                p_name = profiles[prof_key]
                if wid:
                    WINDOW_PROFILE_CACHE[wid] = p_name
                return p_name
        except Exception:
            pass

    # Check session directory mtimes
    times = []
    for p in os.listdir(chrome_dir):
        sess_dir = os.path.join(chrome_dir, p, "Sessions")
        if os.path.isdir(sess_dir):
            files = glob.glob(os.path.join(sess_dir, "Session_*"))
            if files:
                mtime = max(os.path.getmtime(f) for f in files)
                times.append((mtime, p))
    if times:
        times.sort(reverse=True)
        recent_p = times[0][1]
        p_name = profiles.get(recent_p, "Work")
        if wid:
            WINDOW_PROFILE_CACHE[wid] = p_name
        return p_name

    # Default profile name
    default_name = profiles.get("Default", "Work")
    if wid:
        WINDOW_PROFILE_CACHE[wid] = default_name
    return default_name


def apply_window_profiles(home_dir=None):
    """
    Inspect all open Chrome windows and assign profile desktop files and icons.
    Window 0 unifies with google-chrome.desktop to keep the pinned launcher satisfied.
    Windows 1, 2, ... are assigned chrome-<slug>.desktop to display as distinct items.
    """
    if not home_dir:
        home_dir = os.path.expanduser("~")

    profiles = get_chrome_profiles(os.path.join(home_dir, ".config/google-chrome"))
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

        # Must be Chrome and have "Google Chrome" in title or be an explicitly launched chrome-* window
        if ("google-chrome" in wc or "chrome-" in wc) and ("google chrome" in title.lower() or wc.startswith("chrome-")):
            chrome_wins.append(w)

    # Clean up stale window profile cache entries
    stale = [wid for wid in WINDOW_PROFILE_CACHE if wid not in active_wids]
    for wid in stale:
        del WINDOW_PROFILE_CACHE[wid]

    if not chrome_wins:
        # No Chrome windows open: ensure google-chrome icon is clean stock icon
        stock_icon = get_stock_chrome_icon()
        if stock_icon:
            user_icon_48 = os.path.join(home_dir, ".local/share/icons/hicolor/48x48/apps/google-chrome.png")
            user_icon_128 = os.path.join(home_dir, ".local/share/icons/hicolor/128x128/apps/google-chrome.png")
            try:
                if os.path.isfile(stock_icon):
                    shutil.copyfile(stock_icon, user_icon_48)
                    shutil.copyfile(stock_icon, user_icon_128)
            except Exception:
                pass
        return 0

    icons_dir_48 = os.path.join(home_dir, ".local/share/icons/hicolor/48x48/apps")
    icons_dir_128 = os.path.join(home_dir, ".local/share/icons/hicolor/128x128/apps")

    # Group windows by detected profile
    processed = 0
    for idx, w in enumerate(chrome_wins):
        prof_name = detect_window_profile(w, profiles, home_dir)
        slug = slugify(prof_name)

        # Ensure badged icon for this profile exists
        prof_icon_48 = os.path.join(icons_dir_48, f"chrome-{slug}.png")
        prof_icon_128 = os.path.join(icons_dir_128, f"chrome-{slug}.png")
        if not os.path.isfile(prof_icon_48):
            generate_badged_icon(prof_name, prof_icon_48, prof_icon_128)

        # Apply _NET_WM_ICON directly to window
        set_window_icon(w["id"], prof_icon_48, prof_icon_128)

        if idx == 0:
            # Primary Chrome window: unifies with the pinned google-chrome.desktop launcher
            set_window_desktop_file(w["id"], "google-chrome.desktop")
            set_window_wm_class(w["id"], "google-chrome", "Google-chrome")

            # Update user's google-chrome.png to show Window 0's profile badge
            user_icon_48 = os.path.join(icons_dir_48, "google-chrome.png")
            user_icon_128 = os.path.join(icons_dir_128, "google-chrome.png")
            try:
                shutil.copyfile(prof_icon_48, user_icon_48)
                shutil.copyfile(prof_icon_128, user_icon_128)
            except Exception:
                pass
        else:
            # Secondary Chrome windows: separate ungrouped task items with badged icons
            desktop_slug = f"chrome-{slug}.desktop"
            set_window_desktop_file(w["id"], desktop_slug)
            set_window_wm_class(w["id"], f"chrome-{slug}", f"chrome-{slug}")

        processed += 1

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
            chrome_wins = [w for w in wins if "google-chrome" in w["wm_class"].lower() or "chrome-" in w["wm_class"].lower()]
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
