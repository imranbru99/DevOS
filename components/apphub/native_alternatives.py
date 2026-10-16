#!/usr/bin/env python3
"""Windows installers that have a native DevOS (Linux) version.

Some Windows programs start under the Windows layer but cannot fully work
there: remote-desktop tools (AnyDesk, TeamViewer) need Windows screen-capture
and input drivers, and AnyDesk crashed as soon as a session was used. When a
downloaded installer matches one of these, DevOS offers the native version
from Flathub instead; it installs per user, without a password.
"""

import os
import re
import shutil
import subprocess
from typing import Callable, Dict, List, Optional

FLATHUB_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"

# pattern -> (display name, Flathub id, why the native version is better)
#
# The first block also matches downloaded installers by file name (match()).
# Entries with "installer": False are only used to answer "how do I install
# X?" in DevOS AI (lookup()): Microsoft Store, Google Play and App Store apps
# that cannot run on DevOS, with the DevOS way to get the same thing.
#   flatpak  Flathub id of the DevOS version ("" when there is none)
#   feature  DevOS Features id that installs it (devos-features set --add)
#   builtin  name of the DevOS app that already does it (nothing to install)
#   web      the web version, which works in Chrome
#   download vendor's own download page (its Windows .exe runs on DevOS too)
#   note     extra advice shown with the answer
# Every Flathub id was checked: https://flathub.org/api/v2/appstream/<id> -> 200.
CATALOG: List[Dict[str, object]] = [
    {"pattern": r"anydesk", "name": "AnyDesk", "flatpak": "com.anydesk.Anydesk",
     "why": "Remote control, file transfer and unattended access only work in the DevOS version."},
    {"pattern": r"zoom", "name": "Zoom", "flatpak": "us.zoom.Zoom", "web": "https://app.zoom.us/wc",
     "why": "Camera, microphone and screen sharing work properly in the DevOS version."},
    {"pattern": r"discord", "name": "Discord", "flatpak": "com.discordapp.Discord", "web": "https://discord.com/app",
     "why": "Voice, video and notifications work properly in the DevOS version."},
    {"pattern": r"spotify", "name": "Spotify", "flatpak": "com.spotify.Client", "web": "https://open.spotify.com",
     "why": "The DevOS version plays smoothly and uses less memory."},
    {"pattern": r"telegram", "name": "Telegram", "flatpak": "org.telegram.desktop", "web": "https://web.telegram.org",
     "why": "The DevOS version supports calls and notifications."},
    {"pattern": r"whatsapp", "name": "WhatsApp (ZapZap)", "flatpak": "com.rtosta.zapzap", "web": "https://web.whatsapp.com",
     "why": "WhatsApp has no Windows-layer support; this DevOS app opens WhatsApp Web with notifications."},
    {"pattern": r"steam", "name": "Steam", "flatpak": "com.valvesoftware.Steam",
     "why": "The DevOS version runs Windows games through Proton automatically."},
    {"pattern": r"obs[-_ ]?studio|^obs", "name": "OBS Studio", "flatpak": "com.obsproject.Studio",
     "why": "Screen and camera capture only work in the DevOS version."},
    {"pattern": r"slack", "name": "Slack", "flatpak": "com.slack.Slack", "web": "https://app.slack.com",
     "why": "Calls, screen sharing and notifications work in the DevOS version."},
    {"pattern": r"firefox", "name": "Firefox", "flatpak": "org.mozilla.firefox",
     "why": "The DevOS version is faster and updates itself."},
    {"pattern": r"brave", "name": "Brave", "flatpak": "com.brave.Browser",
     "why": "The DevOS version is faster and updates itself."},
    {"pattern": r"gimp", "name": "GIMP", "flatpak": "org.gimp.GIMP",
     "why": "The DevOS version is faster and supports your graphics tablet."},
    {"pattern": r"blender", "name": "Blender", "flatpak": "org.blender.Blender",
     "why": "The DevOS version uses your graphics card directly."},
    {"pattern": r"audacity", "name": "Audacity", "flatpak": "org.audacityteam.Audacity",
     "why": "Recording works with your microphone in the DevOS version."},
    {"pattern": r"libreoffice", "name": "LibreOffice", "flatpak": "org.libreoffice.LibreOffice",
     "why": "The DevOS version opens Word, Excel and PowerPoint files natively."},
    {"pattern": r"postman", "name": "Postman", "flatpak": "com.getpostman.Postman",
     "why": "The DevOS version is faster and updates itself."},
    {"pattern": r"teamviewer", "name": "Remmina (remote desktop)", "flatpak": "org.remmina.Remmina",
     "why": "TeamViewer's Windows version cannot control this PC; Remmina is the DevOS remote-desktop app."},
]


def _store(pattern: str, name: str, why: str, flatpak: str = "", feature: str = "", builtin: str = "",
           web: str = "", download: str = "", note: str = "") -> Dict[str, object]:
    return {"pattern": pattern, "name": name, "flatpak": flatpak, "feature": feature, "builtin": builtin,
            "web": web, "download": download, "note": note, "why": why, "installer": False}


# Windows / Store / phone apps people ask DevOS AI to install. lookup() reads
# these after the entries above; the patterns run on a normalized app name
# (lower case, "+" -> " plus ", other punctuation -> spaces).
CATALOG += [
    _store(r"^windows app$|remote ?desktop|\brdp\b|\bmstsc\b|windows 365|azure virtual desktop|\bcloud pc\b|"
           r"\bavd\b", "Windows App (Microsoft)", feature="winapp", web="https://windows.cloud.microsoft",
           why="Microsoft's own Windows App, installed as an app with its own window: the same cloud PCs, "
               "Azure Virtual Desktop and remote apps, signed in with your Microsoft account. Connecting "
               "a Cloud PC stays in that app. For plain Remote Desktop (RDP) to a PC, Remmina is also in "
               "DevOS Features."),
    _store(r"\b(?:ms |microsoft )?teams\b", "Teams for Linux", feature="teams",
           flatpak="com.github.IsmaelMartinez.teams_for_linux", web="https://teams.microsoft.com",
           why="Teams for Linux signs in to the same Microsoft Teams account, with calls and chat."),
    _store(r"\boutlook\b|^(?:windows )?mail(?: and calendar)?$|\bhotmail\b", "Thunderbird", feature="thunderbird",
           flatpak="org.mozilla.Thunderbird", web="https://outlook.live.com",
           why="Thunderbird reads Outlook.com, Hotmail, Gmail and work email, with a calendar."),
    _store(r"\bone ?note\b", "Joplin", feature="notes", flatpak="net.cozic.joplin_desktop",
           web="https://www.onenote.com", why="Joplin keeps notes and to-dos like OneNote and can sync with OneDrive."),
    _store(r"\bone ?drive\b", "DevOS Cloud Backup", feature="backup", web="https://onedrive.live.com",
           why="DevOS Cloud Backup keeps your folders backed up to OneDrive (or Google Drive)."),
    _store(r"\bgoogle drive\b", "DevOS Cloud Backup", feature="backup", web="https://drive.google.com",
           why="DevOS Cloud Backup keeps your folders backed up to Google Drive (or OneDrive)."),
    _store(r"\b(?:microsoft 365|office 365|ms office|microsoft office|office|word|excel|power ?point|"
           r"publisher)\b", "ONLYOFFICE", feature="onlyoffice", flatpak="org.onlyoffice.desktopeditors",
           web="https://www.office.com",
           why="ONLYOFFICE opens and saves Word, Excel and PowerPoint files with the same ribbon layout."),
    _store(r"\bnetflix\b", "Netflix in Chrome", web="https://www.netflix.com",
           why="Netflix has no PC app for DevOS, but the website plays everything in Chrome."),
    _store(r"prime video|amazon prime", "Prime Video in Chrome", web="https://www.primevideo.com",
           why="Prime Video works in Chrome; there is no separate PC app for DevOS."),
    _store(r"\bdisney\b|\bhotstar\b", "Disney+ in Chrome", web="https://www.disneyplus.com",
           why="Disney+ works in Chrome; there is no separate PC app for DevOS."),
    _store(r"\bitunes\b|apple music", "Apple Music in Chrome", web="https://music.apple.com",
           why="iTunes is Windows-only; Apple Music plays in Chrome with your Apple ID."),
    _store(r"apple tv", "Apple TV in Chrome", web="https://tv.apple.com",
           why="Apple TV plays in Chrome with your Apple ID."),
    _store(r"\bicloud\b", "iCloud in Chrome", web="https://www.icloud.com",
           why="iCloud photos, mail and files open in Chrome with your Apple ID."),
    _store(r"\binstagram\b", "Instagram in Chrome", web="https://www.instagram.com",
           why="Instagram's website does everything the app does, including messages."),
    _store(r"\bfacebook\b", "Facebook in Chrome", web="https://www.facebook.com",
           why="Facebook's website works fully in Chrome."),
    _store(r"\bmessenger\b", "Messenger in Chrome", web="https://www.messenger.com",
           why="Messenger's website has chats and calls in Chrome."),
    _store(r"\btik ?tok\b", "TikTok in Chrome", web="https://www.tiktok.com",
           why="TikTok's website works in Chrome."),
    _store(r"^x$|^x (?:corp|formerly)|\btwitter\b", "X in Chrome", web="https://x.com",
           why="X (Twitter) works fully in Chrome."),
    _store(r"\byoutube\b", "YouTube in Chrome", web="https://www.youtube.com",
           why="YouTube works best in Chrome; there is no separate PC app."),
    _store(r"\blinked ?in\b", "LinkedIn in Chrome", web="https://www.linkedin.com",
           why="LinkedIn's website works fully in Chrome."),
    _store(r"\bsnapchat\b", "Snapchat in Chrome", web="https://web.snapchat.com",
           why="Snapchat for Web has chats and calls in Chrome."),
    _store(r"\bantigravity\b|\bagy\b|\bgoogle antigravity\b", "Antigravity Code Agent", builtin="Antigravity Code Agent",
           why="Antigravity is the next-gen autonomous AI coding agent and developer workflow engine."),
    _store(r"\bchat ?gpt\b|\bopenai\b", "ChatGPT in Chrome", web="https://chatgpt.com",
           why="ChatGPT works in Chrome. DevOS AI is also built in and works offline."),
    _store(r"\bnotion\b", "Notion in Chrome", web="https://www.notion.so",
           why="Notion's website has everything the app has."),
    _store(r"\bcanva\b", "Canva in Chrome", web="https://www.canva.com", why="Canva works fully in Chrome."),
    _store(r"\bfigma\b", "Figma in Chrome", web="https://www.figma.com", why="Figma works fully in Chrome."),
    _store(r"\bvlc\b", "VLC", feature="vlc", builtin="vlc", flatpak="org.videolan.VLC",
           why="VLC plays every video and music format."),
    _store(r"media player|movies (?:and|&) tv|groove music|windows media", "VLC", feature="vlc", builtin="vlc",
           why="VLC plays every video and music format, like Media Player."),
    _store(r"\b7 ?zip\b|\bwin ?rar\b|\bwin ?zip\b|\brar\b|\bpeazip\b", "Ark", builtin="ark",
           flatpak="org.kde.ark", why="Ark comes with DevOS and opens and makes .zip, .rar and .7z files."),
    _store(r"notepad ?(?:plus ?plus|pp)\b|\bsublime\b", "Kate", builtin="kate", flatpak="org.kde.kate",
           download="https://notepad-plus-plus.org/downloads/",
           why="Kate comes with DevOS: tabs, syntax colours and search like Notepad++.",
           note="If you want Notepad++ itself, its Windows .exe also runs on DevOS."),
    _store(r"\bphotoshop\b|\blightroom\b", "GIMP", feature="gimp", flatpak="org.gimp.GIMP",
           web="https://www.photopea.com",
           why="GIMP edits photos like Photoshop; Krita is there for drawing and painting."),
    _store(r"\billustrator\b|corel ?draw", "Inkscape", feature="inkscape", flatpak="org.inkscape.Inkscape",
           why="Inkscape makes logos and vector art like Illustrator and opens .svg and .pdf files."),
    _store(r"\bpremiere\b|after effects|\bfilmora\b|vegas pro|\bclipchamp\b", "Kdenlive", feature="kdenlive",
           flatpak="org.kde.kdenlive", why="Kdenlive is a full video editor like Premiere and Clipchamp."),
    _store(r"\bcap ?cut\b", "Kdenlive", feature="kdenlive", flatpak="org.kde.kdenlive",
           web="https://www.capcut.com/editor", why="Kdenlive edits videos on the PC; CapCut also has a web editor."),
    _store(r"visual studio(?! code)|^vs 20\d\d$", "Visual Studio Code", feature="vscode", builtin="code",
           why="VS Code comes with DevOS and handles C#, C++, Python and web projects."),
    _store(r"paint ?net|\bpinta\b", "Pinta", flatpak="com.github.PintaProject.Pinta",
           why="Pinta is a simple image editor made to feel like Paint.NET; Krita is there for drawing."),
    _store(r"power ?toys", "Built into DevOS", why="DevOS already has the main PowerToys tools built in.",
           note="Drag a window to a screen edge or corner to snap it. Press Alt+Space to search and run "
                "anything. Press Print Screen to take a screenshot."),
    _store(r"\bxbox\b|game ?pass", "Steam", feature="steam", flatpak="com.valvesoftware.Steam",
           web="https://www.xbox.com/play",
           why="Xbox PC games need Windows. Steam runs Windows games on DevOS, Heroic opens Epic and GOG games, "
               "and Xbox Cloud Gaming works in Chrome."),
    _store(r"epic games|\bgog\b|\bamazon games\b", "Heroic Games Launcher", feature="heroic",
           flatpak="com.heroicgameslauncher.hgl", why="Heroic opens your Epic, GOG and Amazon game libraries."),
    _store(r"\bminecraft\b", "Minecraft", flatpak="com.mojang.Minecraft",
           why="The official Minecraft Launcher (Java Edition) runs on DevOS."),
    _store(r"\broblox\b", "Sober (Roblox)", flatpak="org.vinegarhq.Sober",
           why="Sober runs Roblox on DevOS. It is made by the Vinegar team, not by Roblox."),
    _store(r"\bdropbox\b", "Dropbox", flatpak="com.dropbox.Client", web="https://www.dropbox.com",
           why="The DevOS version syncs your Dropbox folder."),
    _store(r"\bviber\b", "Viber", flatpak="com.viber.Viber", why="The DevOS version has chats and calls."),
    _store(r"\bsignal\b", "Signal", feature="signal", flatpak="org.signal.Signal", why="Private messaging."),
    _store(r"\bopera\b", "Opera", flatpak="com.opera.Opera", why="The DevOS version updates itself."),
    _store(r"\bvivaldi\b", "Vivaldi", flatpak="com.vivaldi.Vivaldi", why="The DevOS version updates itself."),
    _store(r"\bkeepass\b", "KeePassXC", feature="passwords", flatpak="org.keepassxc.KeePassXC",
           why="KeePassXC opens your KeePass password files."),
    _store(r"\bu ?torrent\b|\bbit ?torrent\b|\bqbittorrent\b", "qBittorrent", feature="torrent",
           why="qBittorrent downloads torrents without ads."),
    _store(r"\bintellij\b", "IntelliJ IDEA Community", flatpak="com.jetbrains.IntelliJ-IDEA-Community",
           why="The DevOS version of IntelliJ IDEA."),
    _store(r"\bpycharm\b", "PyCharm Community", flatpak="com.jetbrains.PyCharm-Community",
           why="The DevOS version of PyCharm."),
    _store(r"acrobat|adobe reader|pdf reader", "Okular", builtin="okular",
           why="Okular comes with DevOS and opens, fills and signs PDF files."),
    _store(r"snipping tool|snip (?:and|&) sketch|\blightshot\b|\bgreenshot\b|\bsharex\b", "Spectacle",
           builtin="spectacle", why="Spectacle comes with DevOS: press Print Screen to take a screenshot."),
    _store(r"task ?manager|^taskmgr$|process explorer|procexp", "Task Manager", builtin="taskman",
           why="DevOS Task Manager shows processes, performance, startup apps and services. Press Ctrl+Shift+Esc."),
    _store(r"^(?:windows )?calculator$", "Calculator", builtin="calculator", flatpak="org.kde.kcalc",
           why="A calculator comes with DevOS."),
    _store(r"windows terminal|\bpowershell\b|^cmd$|command prompt", "Terminal", builtin="terminal",
           why="DevOS has a terminal built in (Konsole)."),
    _store(r"\bblue ?stacks\b|\bnox ?player\b|\bld ?player\b|android emulator|subsystem for android",
           "Android apps", feature="android",
           why="DevOS runs Android .apk apps in a window, no emulator needed."),
    _store(r"\bskype\b", "Microsoft Teams", feature="teams", flatpak="com.github.IsmaelMartinez.teams_for_linux",
           web="https://teams.live.com", why="Microsoft closed Skype and moved its users to Teams."),
]


def normalize_name(name: str) -> str:
    """"Notepad++" -> "notepad plus plus", "Microsoft 365 (Office)" -> "microsoft 365 office"."""
    t = (name or "").lower().replace("&", " and ").replace("+", " plus ")
    t = re.sub(r"[^\w]+", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()


def lookup(name: str) -> Optional[Dict[str, object]]:
    """Catalog entry for an app name ("Windows App", "WhatsApp Messenger"), or None."""
    q = normalize_name(name)
    if not q:
        return None
    for entry in CATALOG:
        if re.search(entry["pattern"], q):
            return entry
    return None


def match(file_path: str) -> Optional[Dict[str, str]]:
    """Catalog entry for a downloaded installer, by its file name."""
    base = os.path.basename(file_path).lower()
    # Windows installers and Android packages: both have DevOS versions for
    # popular apps, which also saves the one-time Android download.
    if not base.endswith((".exe", ".msi", ".apk", ".xapk")):
        return None
    stem = os.path.splitext(base)[0]
    for entry in CATALOG:
        if entry.get("installer", True) and entry["flatpak"] and re.search(entry["pattern"], stem):
            return entry
    return None


def is_installed(app_id: str) -> bool:
    if not shutil.which("flatpak"):
        return False
    out = subprocess.run(["flatpak", "info", app_id], capture_output=True, text=True)
    return out.returncode == 0


def parse_progress(line: str) -> Optional[int]:
    """Percentage from a flatpak install line ("Installing 2/3… ████  45%  2.1 MB/s")."""
    found = re.findall(r"(\d{1,3})%", line)
    if not found:
        return None
    value = int(found[-1])
    return value if 0 <= value <= 100 else None


def install(app_id: str, progress: Callable[[int, str], None] = None) -> Dict[str, str]:
    """Install for the current user from Flathub (no password needed)."""
    if not shutil.which("flatpak"):
        return {"status": "ERROR", "error": "App installs are not available on this system."}
    subprocess.run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB_URL],
                   capture_output=True)
    proc = subprocess.Popen(
        ["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", app_id],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    tail = []
    line = bytearray()
    while True:
        ch = proc.stdout.read(1)
        if not ch:
            break
        if ch not in (b"\r", b"\n"):
            line += ch
            continue
        text = line.decode("utf-8", "replace").strip()
        line.clear()
        if not text:
            continue
        tail = (tail + [text])[-3:]
        percent = parse_progress(text)
        if progress and percent is not None:
            progress(percent, "Downloading and installing...")
    proc.wait()
    if proc.returncode != 0:
        return {"status": "ERROR", "error": "The download did not finish. Check the internet connection.",
                "details": " | ".join(tail)}
    return {"status": "INSTALLED"}


def launch(app_id: str) -> None:
    subprocess.Popen(["flatpak", "run", app_id], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
