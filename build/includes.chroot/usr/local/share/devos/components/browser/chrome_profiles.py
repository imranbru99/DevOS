#!/usr/bin/env python3
"""
DevOS Chrome Profile & Icon Manager
Generates distinct badged icons and desktop entries for each Google Chrome profile
(e.g., Work, Mirza, Tony, Guest) so each profile window appears as its own icon
with its profile name clearly visible inside the icon on the taskbar.
"""

import json
import os
import re
import sys
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


def generate_badged_icon(name, output_48, output_128=None, base_icon=None):
    """
    Render a Google Chrome icon with a clean pill badge containing the
    profile name directly inside/on the icon at the bottom.
    """
    if not base_icon or not os.path.isfile(base_icon):
        for candidate in [
            "/usr/share/icons/hicolor/128x128/apps/google-chrome.png",
            "/usr/share/icons/hicolor/48x48/apps/google-chrome.png",
            "/usr/share/pixmaps/google-chrome.png",
        ]:
            if os.path.isfile(candidate):
                base_icon = candidate
                break

    if base_icon and os.path.isfile(base_icon):
        img = Image.open(base_icon).convert("RGBA").resize((128, 128), Image.Resampling.LANCZOS)
    else:
        # Fallback circle if base icon is missing
        img = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([8, 8, 120, 120], fill=(66, 133, 244, 255))

    draw = ImageDraw.Draw(img)

    # Pick display text: first word or up to 8 characters
    label = name.strip().split()[0][:8]

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
                font_size = 22 if len(label) <= 5 else (18 if len(label) <= 7 else 15)
                font = ImageFont.truetype(font_path, font_size)
                break
            except Exception:
                pass

    # Draw bottom pill badge: [6, 90, 122, 124]
    draw.rounded_rectangle(
        [6, 90, 122, 124],
        radius=10,
        fill=(15, 23, 42, 245),
        outline=(56, 189, 248, 240),
        width=3,
    )

    if font:
        draw.text((64, 106), label, fill=(255, 255, 255), font=font, anchor="mm")
    else:
        draw.text((64, 106), label, fill=(255, 255, 255), anchor="mm")

    os.makedirs(os.path.dirname(os.path.abspath(output_48)), exist_ok=True)
    img_48 = img.resize((48, 48), Image.Resampling.LANCZOS)
    img_48.save(output_48)

    if output_128:
        os.makedirs(os.path.dirname(os.path.abspath(output_128)), exist_ok=True)
        img.save(output_128)


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

    # Include guest mode
    all_profiles = list(profiles.items())
    all_profiles.append(("guest", "Guest"))

    created_desktops = []

    for key, name in all_profiles:
        slug = slugify(key if key == "guest" else (name or key))
        icon_name = f"chrome-{slug}"
        icon_file_48 = os.path.join(icons_dir_48, f"{icon_name}.png")
        icon_file_128 = os.path.join(icons_dir_128, f"{icon_name}.png")

        generate_badged_icon(name, icon_file_48, icon_file_128)

        desktop_file = os.path.join(apps_dir, f"{icon_name}.desktop")
        wm_class = icon_name

        if key == "guest":
            exec_cmd = "devos-browser --guest"
        else:
            exec_cmd = f'devos-browser --profile-directory="{key}"'

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

    # Also ensure ~/.config/devos/chrome-policies/devos-familysafe.json exists
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


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "sync"
    if action == "sync":
        created = sync_all_profiles()
        print(f"Synced {len(created)} Chrome profile launchers and badged icons.")
    else:
        print(f"Unknown action: {action}")
