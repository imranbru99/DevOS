#!/usr/bin/env python3
"""
DevOS feature catalog: the apps and features people know from Windows, as
pick-what-you-want items.

The installer's "Choose your apps" page, the devos-features command and the
DevOS Features window all read this list. Every apt name was checked against
Ubuntu 24.04 (noble) and every Flatpak id against Flathub. Thunderbird and
Firefox come from Flathub because noble's apt packages only install Snap,
which DevOS blocks.

preinstalled: already on the ISO. Unticking it in the installer removes it
from the new system (offline); everything else is downloaded after install.
"""

from typing import Dict, List, Optional

CATEGORIES = [
    ("office", "Office & documents"),
    ("internet", "Internet & email"),
    ("chat", "Calls & messaging"),
    ("media", "Music & video"),
    ("creative", "Photo, design & video editing"),
    ("games", "Games"),
    ("developer", "Developer tools"),
    ("utilities", "Everyday tools"),
    ("security", "Security & privacy"),
    ("language", "Language & fonts"),
    ("compat", "Windows & Android apps"),
    ("devos", "DevOS tools"),
    ("family", "Islamic & family"),
]

# Default-app roles the Features window offers, with the MIME types they own.
ROLES = {
    "documents": ["application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                  "application/msword", "application/vnd.oasis.opendocument.text", "application/rtf"],
    "spreadsheets": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     "application/vnd.ms-excel", "application/vnd.oasis.opendocument.spreadsheet", "text/csv"],
    "presentations": ["application/vnd.openxmlformats-officedocument.presentationml.presentation",
                      "application/vnd.ms-powerpoint", "application/vnd.oasis.opendocument.presentation"],
    "pdf": ["application/pdf"],
    "browser": ["x-scheme-handler/http", "x-scheme-handler/https", "text/html"],
    "email": ["x-scheme-handler/mailto"],
    "music": ["audio/mpeg", "audio/flac", "audio/ogg", "audio/x-wav", "audio/mp4"],
    "video": ["video/mp4", "video/x-matroska", "video/webm", "video/x-msvideo", "video/quicktime"],
    "images": ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"],
}

ROLE_NAMES = {
    "documents": "Documents (.docx)", "spreadsheets": "Spreadsheets (.xlsx)",
    "presentations": "Presentations (.pptx)", "pdf": "PDF", "browser": "Web browser",
    "email": "Email", "music": "Music", "video": "Video", "images": "Photos",
}

# Built-in handlers that are always there (fallbacks in the Default apps list).
BUILT_IN_HANDLERS = {
    "pdf": [("org.kde.okular.desktop", "Document Viewer")],
    "browser": [("devos-browser.desktop", "DevOS Browser"), ("org.kde.falkon.desktop", "Falkon")],
    "music": [("vlc.desktop", "VLC")],
    "video": [("vlc.desktop", "VLC")],
    "images": [("org.kde.gwenview.desktop", "Photos")],
}


def F(id, cat, name, about, size_mb, win="", apt=None, flatpak=None, script=None, preinstalled=False,
      remove=None, presets=(), roles=None, needs_eula="", services=None, min_ram_gb=0, builtin=None, webapp=None):
    if "windows" in presets and "islamic" not in presets:
        presets = tuple(presets) + ("islamic",)
    return {
        "id": id, "category": cat, "name": name, "about": about, "size_mb": size_mb,
        "windows": win, "apt": list(apt or []), "flatpak": list(flatpak or []), "script": script,
        "preinstalled": preinstalled, "remove": list(remove or apt or []), "presets": list(presets),
        # role -> desktop file this feature provides (for Default apps)
        "roles": dict(roles or {}), "eula": needs_eula, "services": list(services or []),
        # Total RAM below which the app feels slow; the installer then leaves it
        # unticked in "Recommended for this PC" and tags it "Needs N GB RAM".
        "min_ram_gb": min_ram_gb,
        # DevOS's own tools: {"desktop": [...], "enable": [[cmd]], "disable": [[cmd]],
        # "optin": True when off until chosen}. Switched by features_cli.set_builtin.
        "builtin": builtin,
        # Vendor web apps installed like Edge/Chrome "Install app": a Start-menu
        # entry that opens the site in its own window. {"url", "icon"}.
        "webapp": webapp,
        "preinstalled": preinstalled or bool(builtin),
    }


EVERYONE = ("windows", "student", "developer", "creator", "gamer")
# Kept even by the "Minimal" preset: DevOS itself relies on them.
ESSENTIAL = EVERYONE + ("minimal",)

FEATURES: List[Dict] = [
    # ---------------------------------------------------------------- office
    F("onlyoffice", "office", "ONLYOFFICE (Word, Excel, PowerPoint look-alike)",
      "Opens and saves .docx, .xlsx and .pptx exactly like Microsoft Office, with the same ribbon layout.",
      650, win="Microsoft Office", flatpak=["org.onlyoffice.desktopeditors"], presets=EVERYONE,
      roles={r: "org.onlyoffice.desktopeditors.desktop" for r in ("documents", "spreadsheets", "presentations")}, min_ram_gb=3),
    F("libreoffice", "office", "LibreOffice Writer, Calc, Impress",
      "The classic free office suite; best for .odt/.ods files and complex macros.",
      380, win="Microsoft Office", apt=["libreoffice-writer", "libreoffice-calc", "libreoffice-impress",
                                         "libreoffice-kf5", "libreoffice-style-breeze"],
      presets=("student",),
      roles={"documents": "libreoffice-writer.desktop", "spreadsheets": "libreoffice-calc.desktop",
             "presentations": "libreoffice-impress.desktop"}, min_ram_gb=3),
    F("wps", "office", "WPS Office",
      "Free Microsoft Office alternative popular with students; includes PDF tools.",
      1100, win="Microsoft Office", flatpak=["com.wps.Office"], min_ram_gb=4),
    F("officefonts", "office", "Office-compatible fonts",
      "Free fonts with the exact sizes of Calibri and Cambria, so Word files keep their layout.",
      8, apt=["fonts-crosextra-carlito", "fonts-crosextra-caladea"], presets=ESSENTIAL),
    F("msfonts", "office", "Microsoft core fonts (Arial, Times New Roman, Verdana…)",
      "Downloaded from Microsoft. Ticking this accepts Microsoft's font licence (EULA).",
      12, win="Windows fonts", apt=["ttf-mscorefonts-installer"], presets=("windows", "student"),
      needs_eula="ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true"),
    F("pdftools", "office", "PDF tools: merge, split, sign, annotate",
      "PDF Arranger (merge, split, rotate pages) and Xournal++ (write, highlight and sign on PDFs).",
      15, win="Adobe Acrobat", apt=["pdfarranger", "xournalpp"], presets=EVERYONE),
    F("notes", "office", "Joplin notes",
      "Notes and to-dos with sync to OneDrive/Dropbox, like OneNote.",
      300, win="OneNote", flatpak=["net.cozic.joplin_desktop"], presets=("student",), min_ram_gb=4),
    F("obsidian", "office", "Obsidian", "Markdown notes and knowledge base.", 350, flatpak=["md.obsidian.Obsidian"], min_ram_gb=4),
    F("calendar", "office", "Calendar & reminders", "Calendar with reminders, like Outlook Calendar.",
      60, win="Outlook Calendar", apt=["korganizer", "kalarm"], presets=("professional",)),
    F("mindmap", "office", "XMind mind maps", "Mind maps and brainstorming.", 400, flatpak=["net.xmind.XMind"], min_ram_gb=4),

    # ---------------------------------------------------------------- internet
    F("chrome", "internet", "Google Chrome", "Chrome with Google sign-in and sync.", 330, win="Chrome",
      script="/usr/local/sbin/devos-install-chrome", preinstalled=True, remove=["google-chrome-stable"],
      presets=EVERYONE, roles={"browser": "google-chrome.desktop"}),
    F("edge", "internet", "Microsoft Edge", "Edge with Microsoft account sync.", 400, win="Edge",
      flatpak=["com.microsoft.Edge"], presets=("windows",), roles={"browser": "com.microsoft.Edge.desktop"}, min_ram_gb=4),
    F("firefox", "internet", "Firefox", "Private, open-source browser.", 280, win="Firefox",
      flatpak=["org.mozilla.firefox"], roles={"browser": "org.mozilla.firefox.desktop"}),
    F("brave", "internet", "Brave", "Browser with built-in ad blocking.", 350, flatpak=["com.brave.Browser"],
      roles={"browser": "com.brave.Browser.desktop"}, min_ram_gb=4),
    F("thunderbird", "internet", "Thunderbird email",
      "Email and calendar for Gmail, Outlook.com and work accounts.", 300, win="Outlook / Mail",
      flatpak=["org.mozilla.Thunderbird"], presets=("windows", "student"),
      roles={"email": "org.mozilla.Thunderbird.desktop"}),
    F("winapp", "internet", "Windows App (Microsoft)",
      "Microsoft's own Windows App: Windows 365 cloud PCs, Azure Virtual Desktop, Dev Box and remote apps, "
      "in its own window. Connecting a Cloud PC stays in this app. Same app Microsoft offers for every "
      "browser; no third-party software.", 1,
      win="Windows App", presets=("windows", "developer"), webapp={"url": "https://windows.cloud.microsoft/",
                                                                  "icon": "preferences-desktop-remote-desktop",
                                                                  "names": ["Windows App"]}),
    F("m365web", "internet", "Microsoft 365 (Word, Excel, PowerPoint online)",
      "Microsoft's own Office apps and OneDrive in their own window, with your Microsoft account.", 1,
      win="Microsoft 365", presets=("windows", "student"),
      webapp={"url": "https://www.office.com/", "icon": "x-office-document",
              "names": ["Microsoft 365", "Office", "Microsoft Office"]}),
    F("outlookweb", "internet", "Outlook (Microsoft)", "Microsoft's own Outlook mail and calendar in its own window.",
      1, win="Outlook", presets=("windows",), webapp={"url": "https://outlook.live.com/mail/",
                                                      "icon": "internet-mail", "names": ["Outlook"]}),
    F("torrent", "internet", "qBittorrent", "Torrent downloads.", 30, apt=["qbittorrent"]),

    # ---------------------------------------------------------------- chat
    F("whatsapp", "chat", "WhatsApp", "WhatsApp for desktop (ZapZap).", 250, win="WhatsApp",
      flatpak=["com.rtosta.zapzap"], presets=("windows", "student")),
    F("zoom", "chat", "Zoom", "Video meetings.", 600, win="Zoom", flatpak=["us.zoom.Zoom"], presets=("student", "professional"), min_ram_gb=4),
    F("teams", "chat", "Microsoft Teams", "Teams for work and school.", 350, win="Teams",
      flatpak=["com.github.IsmaelMartinez.teams_for_linux"], presets=("professional", "business"), min_ram_gb=4),
    F("telegram", "chat", "Telegram", "Telegram Desktop.", 150, flatpak=["org.telegram.desktop"]),
    F("discord", "chat", "Discord", "Voice and text chat.", 300, flatpak=["com.discordapp.Discord"], presets=("gamer",), min_ram_gb=4),
    F("slack", "chat", "Slack", "Team chat.", 350, flatpak=["com.slack.Slack"], presets=("professional",), min_ram_gb=4),
    F("signal", "chat", "Signal", "Private messaging.", 300, flatpak=["org.signal.Signal"], min_ram_gb=4),
    F("kdeconnect", "chat", "Phone integration",
      "Notifications, clipboard and files with your phone, like Phone Link.", 20, win="Phone Link",
      apt=["kdeconnect"], preinstalled=True, presets=EVERYONE),

    # ---------------------------------------------------------------- media
    F("vlc", "media", "VLC media player", "Plays every video and music format.", 60, win="Media Player",
      apt=["vlc"], preinstalled=True, presets=EVERYONE, roles={"music": "vlc.desktop", "video": "vlc.desktop"}),
    F("spotify", "media", "Spotify", "Music streaming.", 300, win="Spotify", flatpak=["com.spotify.Client"],
      presets=("windows", "student"), min_ram_gb=4),
    F("webcam", "media", "Camera", "Take photos and videos with the webcam.", 10, win="Camera", apt=["kamoso"],
      presets=("windows", "student")),
    F("recorder", "media", "Voice Recorder",
      "Record a voice note or a meeting from the microphone, like Windows Voice Recorder.",
      15, win="Voice Recorder", apt=["gnome-sound-recorder"], presets=("windows", "student")),

    # ---------------------------------------------------------------- creative
    F("paint", "creative", "Paint (KolourPaint)", "Simple drawing and image editing, like MS Paint.", 15,
      win="Paint", apt=["kolourpaint"], presets=EVERYONE),
    F("gimp", "creative", "GIMP", "Photo editing, like Photoshop.", 400, win="Photoshop",
      flatpak=["org.gimp.GIMP"], presets=("creator",), min_ram_gb=4),
    F("krita", "creative", "Krita", "Digital painting and illustration.", 450, flatpak=["org.kde.krita"],
      presets=("creator",), min_ram_gb=6),
    F("inkscape", "creative", "Inkscape", "Vector graphics, like Illustrator.", 350, win="Illustrator",
      flatpak=["org.inkscape.Inkscape"], presets=("creator",), min_ram_gb=4),
    F("kdenlive", "creative", "Kdenlive video editor", "Video editing, like Clipchamp or Premiere.", 500,
      win="Clipchamp", flatpak=["org.kde.kdenlive"], presets=("creator",), min_ram_gb=8),
    F("obs", "creative", "OBS Studio", "Screen recording and live streaming.", 400, win="Xbox Game Bar recording",
      flatpak=["com.obsproject.Studio"], presets=("creator", "gamer"), min_ram_gb=6),
    F("audacity", "creative", "Audacity", "Record and edit audio.", 120, flatpak=["org.audacityteam.Audacity"],
      presets=("creator",)),
    F("blender", "creative", "Blender", "3D modelling and animation.", 900, flatpak=["org.blender.Blender"], min_ram_gb=8),
    F("handbrake", "creative", "HandBrake", "Convert and shrink videos.", 120, flatpak=["fr.handbrake.ghb"], min_ram_gb=4),

    # ---------------------------------------------------------------- games
    F("steam", "games", "Steam", "Steam games, with Proton for Windows games.", 600, win="Steam",
      flatpak=["com.valvesoftware.Steam"], presets=("gamer",), min_ram_gb=8),
    F("heroic", "games", "Heroic (Epic Games, GOG, Amazon)", "Epic and GOG libraries.", 400,
      win="Epic Games Launcher", flatpak=["com.heroicgameslauncher.hgl"], presets=("gamer",), min_ram_gb=6),
    F("lutris", "games", "Lutris", "Game manager for many stores and emulators.", 250,
      flatpak=["net.lutris.Lutris"], min_ram_gb=4),
    F("protonup", "games", "ProtonUp-Qt", "Install newer Proton/Wine versions for games.", 80,
      flatpak=["net.davidotek.pupgui2"], presets=("gamer",)),
    F("xbox", "games", "Xbox",
      "Xbox cloud games in their own window. Sign in with your Microsoft account.",
      1, win="Xbox", presets=("windows", "gamer"),
      webapp={"url": "https://www.xbox.com/play", "icon": "applications-games", "names": ["Xbox"]}),

    # ---------------------------------------------------------------- developer
    F("vscode", "developer", "Visual Studio Code", "Code editor with DevOS AI built in.", 400,
      win="VS Code", script="/usr/local/sbin/devos-install-code", preinstalled=True, remove=["code"],
      presets=("windows", "student", "developer", "creator", "gamer")),
    F("devservers", "developer", "Web servers & databases",
      "PHP, MariaDB, PostgreSQL and Redis for local websites (like XAMPP/Laragon). Untick to save ~600 MB "
      "and memory if you don't build websites.", 600, win="XAMPP / Laragon",
      apt=["mariadb-server", "postgresql", "redis-server", "php-fpm"],
      remove=["mariadb-server", "mariadb-client", "postgresql", "postgresql-client", "redis-server", "php-fpm"],
      preinstalled=True, presets=("windows", "student", "developer")),
    F("postman", "developer", "Postman", "Test web APIs.", 450, flatpak=["com.getpostman.Postman"],
      presets=("developer",), min_ram_gb=6),
    F("dbeaver", "developer", "DBeaver", "Database manager for MySQL, PostgreSQL and more.", 400,
      flatpak=["io.dbeaver.DBeaverCommunity"], presets=("developer",), min_ram_gb=6),
    F("githubdesktop", "developer", "GitHub Desktop", "Git with a simple window.", 300,
      flatpak=["io.github.shiftey.Desktop"], presets=("developer",)),
    F("androidstudio", "developer", "Android Studio", "Build Android apps.", 2500,
      flatpak=["com.google.AndroidStudio"], min_ram_gb=16),

    # ---------------------------------------------------------------- utilities
    F("calculator", "utilities", "Calculator", "Everyday calculator, like the Windows Calculator.",
      2, win="Calculator", apt=["kcalc"], preinstalled=True, presets=ESSENTIAL),
    F("notepad", "utilities", "Notepad",
      "A simple text editor, like Windows Notepad. Turning it off only hides it from the menu.",
      1, win="Notepad", presets=ESSENTIAL, builtin={"desktop": ["org.kde.kate.desktop"]}),
    F("snip", "utilities", "Snipping Tool",
      "Capture the screen or one area, like the Windows Snipping Tool.",
      5, win="Snipping Tool", apt=["kde-spectacle"], preinstalled=True, presets=ESSENTIAL),
    F("photos", "utilities", "Photos",
      "View your pictures, like Windows Photos. Turning it off only hides it from the menu.",
      1, win="Photos", presets=ESSENTIAL, builtin={"desktop": ["org.kde.gwenview.desktop"]}),
    F("explorer", "utilities", "File Explorer",
      "Browse your files, drives and USB sticks, like Windows File Explorer. Turning it off only hides it "
      "from the menu.",
      1, win="File Explorer", presets=ESSENTIAL, builtin={"desktop": ["org.kde.dolphin.desktop"]}),
    F("terminal", "utilities", "Terminal",
      "A command window, like Windows Terminal. Turning it off only hides it from the menu.",
      1, win="Terminal", presets=ESSENTIAL, builtin={"desktop": ["org.kde.konsole.desktop"]}),
    F("charmap", "utilities", "Character Map",
      "Find and copy any letter or symbol, like Windows Character Map.",
      3, win="Character Map", apt=["kcharselect"], presets=("windows",)),
    F("alarms", "utilities", "Clock & alarms",
      "Alarms, a timer and a stopwatch, like the Windows Clock app.",
      40, win="Clock", flatpak=["org.kde.kclock"], presets=("windows",)),
    F("weather", "utilities", "Weather", "The forecast for your city, like Windows Weather.",
      1, win="Weather", presets=("windows",),
      webapp={"url": "https://www.msn.com/en-us/weather/", "icon": "weather-clear", "names": ["Weather"]}),
    F("maps", "utilities", "Maps", "Directions and places, like Windows Maps.",
      1, win="Maps", presets=("windows",),
      webapp={"url": "https://www.bing.com/maps", "icon": "maps", "names": ["Maps"]}),
    F("onedrive", "utilities", "OneDrive",
      "Your Microsoft files in their own window. Cloud Backup can also copy folders to OneDrive.",
      1, win="OneDrive", presets=("windows", "student"),
      webapp={"url": "https://onedrive.live.com/", "icon": "folder-cloud", "names": ["OneDrive"]}),
    F("diskusage", "utilities", "Disk usage map", "See what fills your disk (Filelight).", 5, win="Storage settings",
      apt=["filelight"], presets=EVERYONE),
    F("remote", "utilities", "Remote desktop (AnyDesk + RustDesk)",
      "Help or get help on another PC.", 200, win="Quick Assist / AnyDesk",
      flatpak=["com.anydesk.Anydesk", "com.rustdesk.RustDesk"], presets=("windows",), min_ram_gb=4),
    F("remmina", "utilities", "Remote Desktop (Remmina)",
      "Connect to Windows PCs, Windows 365 and Azure Virtual Desktop over RDP, like Microsoft's Windows App. "
      "Cloud PCs also open in the browser at windows.cloud.microsoft.", 15, win="Windows App / Remote Desktop",
      apt=["remmina", "remmina-plugin-rdp"], presets=("windows", "developer", "student")),
    F("scanner", "utilities", "Scanner app", "Scan documents to PDF.", 10, win="Windows Scan",
      apt=["skanlite"], presets=("windows", "student")),
    F("timeshift", "utilities", "System restore points (Timeshift)",
      "Take a snapshot before changes and roll back in one click, like System Restore. "
      "DevOS also keeps btrfs restore points on the default install.", 10,
      win="System Restore", apt=["timeshift"], presets=EVERYONE),
    F("access", "utilities", "Accessibility (screen reader, magnifier, on-screen keyboard)",
      "Orca reads the screen aloud, KMag enlarges it, and Onboard types by pointer.",
      80, win="Narrator, Magnifier, Touch keyboard",
      apt=["orca", "kmag", "onboard", "speech-dispatcher", "espeak-ng"],
      preinstalled=True, presets=ESSENTIAL),
    F("appstore", "utilities", "Flatpak app manager (Warehouse)", "Update, roll back and clean up store apps.",
      30, flatpak=["io.github.flattool.Warehouse"]),

    # ---------------------------------------------------------------- security
    F("firewall", "security", "Firewall (on)", "Blocks incoming connections; Phone Link, the phone companion and "
      "DevOS Share keep working.", 5, win="Windows Firewall", apt=["ufw", "plasma-firewall"],
      preinstalled=True, presets=ESSENTIAL, services=["ufw"]),
    F("antivirus", "security", "ClamTk virus scanner window", "A classic scanner window for manual scans and "
      "schedules. Virus protection itself is built into DevOS Security.", 5, win="Windows Defender",
      apt=["clamtk"], remove=["clamtk"], presets=("windows",), min_ram_gb=4),
    F("passwords", "security", "KeePassXC password manager", "Offline password vault.", 30,
      apt=["keepassxc"], presets=("student", "developer", "professional")),
    F("bitwarden", "security", "Bitwarden", "Password manager with sync.", 300, flatpak=["com.bitwarden.desktop"], min_ram_gb=4),
    F("fingerprint", "security", "Fingerprint sign-in",
      "Sign in with a fingerprint reader, like Windows Hello, on laptops that have one. The password still works.",
      8, win="Windows Hello", apt=["fprintd", "libpam-fprintd"], preinstalled=True, presets=ESSENTIAL),
    F("domain", "security", "Company network (Active Directory)",
      "Join this PC to a workplace Active Directory domain.",
      20, win="Domain join", apt=["realmd", "sssd", "adcli", "oddjob", "oddjob-mkhomedir", "packagekit"],
      presets=("business",)),

    # ---------------------------------------------------------------- language
    F("bangla", "language", "Bangla typing (Avro phonetic)", "Type Bangla with an English keyboard "
      "(ami -> আমি). Switch with Ctrl+Space.", 20, apt=["ibus", "ibus-avro", "fonts-beng"],
      presets=EVERYONE),
    F("notofonts", "language", "Fonts for all languages", "Noto fonts so every website and document shows "
      "correctly.", 40, apt=["fonts-noto-core"], preinstalled=True, presets=ESSENTIAL),

    # ---------------------------------------------------------------- compat
    F("winapps", "compat", "Windows apps (.exe, .msi)", "Run Windows programs with a double-click. DirectX 9–11 uses DXVK.", 900,
      win=".exe support", apt=["wine", "wine64", "winetricks", "libvkd3d1"],
      remove=["wine", "wine64", "wine32:i386", "winetricks", "libvkd3d1"],
      preinstalled=True, presets=ESSENTIAL),
    F("winvm", "compat", "Windows virtual machine",
      "Run programs Wine cannot run, such as kernel anti-cheat, inside a virtual PC. "
      "You supply your own Windows ISO and licence. DevOS does not include Windows.",
      80, win="Hyper-V", apt=["qemu-system-x86", "qemu-utils", "ovmf"],
      presets=("windows", "gamer"), min_ram_gb=8),
    F("bottles", "compat", "Bottles", "Advanced Windows-app manager with ready-made setups for popular programs.",
      350, flatpak=["com.usebottles.bottles"], presets=("gamer",), min_ram_gb=4),
    F("android", "compat", "Android apps (.apk)", "Run Android apps in a window (downloads ~850 MB on first use).",
      30, win="Windows Subsystem for Android", apt=["waydroid"], preinstalled=True, presets=EVERYONE, min_ram_gb=4),
]

# DevOS's own tools. Hiding one only removes it from the menu (and stops its
# services): the code stays, so ticking it again needs no download.
DEVOS = "/usr/local/bin/"
FEATURES += [
    F("taskman", "devos", "Task Manager", "Processes, performance, startup apps, users and services. "
      "Opens with Ctrl+Shift+Esc.", 1, win="Task Manager", presets=ESSENTIAL,
      builtin={"desktop": ["devos-taskman.desktop"]}),
    F("security", "devos", "DevOS Security", "Virus scanning of downloads and USB drives, phishing-site "
      "blocking, firewall, security updates and Disk Guard in one place.", 1, win="Windows Security",
      presets=ESSENTIAL, builtin={"desktop": ["devos-security.desktop"]}),
    F("devosnotes", "devos", "DevOS Notes", "Notes, sticky notes and voice notes with AI summaries; saved in "
      "Documents so Cloud Backup keeps them.", 1, win="Sticky Notes / OneNote", presets=ESSENTIAL,
      builtin={"desktop": ["devos-notes.desktop"]}),
    F("voicetype", "devos", "Voice typing (Win+Alt+H)", "Speak instead of typing in any app, in Bangla or "
      "English, fully offline.", 1, win="Voice typing (Win+H)", presets=ESSENTIAL,
      builtin={"desktop": ["devos-voice-typing.desktop"]}),
    F("aiactions", "devos", "AI on any text (Win+Alt+A)", "Select text anywhere to rewrite, fix, shorten, "
      "translate or summarize it with DevOS AI.", 1, win="Copilot", presets=ESSENTIAL,
      builtin={"desktop": ["devos-ai-actions.desktop"]}),
    F("clipboard", "devos", "Clipboard history (Win+V)", "Press Win+V to pick something you copied earlier "
      "and paste it back. Stays on this PC.", 1, win="Clipboard history (Win+V)", presets=ESSENTIAL,
      builtin={"desktop": ["devos-clipboard.desktop"]}),
    F("emoji", "devos", "Emoji panel (Win+.)", "Press Win+. and search smile, love, food or bd. "
      "The one you pick is pasted into the app you were using.", 1, win="Emoji panel (Win+.)",
      presets=ESSENTIAL, builtin={"desktop": ["devos-emoji.desktop"]}),
    F("codeagent", "devos", "DevOS AI Code Agent", "A Cursor-style AI coding agent on your own PC. Appears when a "
      "Medium+ or Coding AI model is installed.", 1, win="GitHub Copilot", presets=EVERYONE, min_ram_gb=8,
      builtin={"desktop": ["devos-ai-code-agent.desktop", "devos-code-agent.desktop"]}),
    F("phonelink", "devos", "Phone Link", "Control the PC from your phone's browser: files, clipboard, "
      "volume, screen and DevOS AI.", 1, win="Phone Link", presets=EVERYONE,
      builtin={"desktop": ["devos-phonelink.desktop"]}),
    F("share", "devos", "DevOS Share", "Give an app running on this PC a public https link to show anyone.",
      1, win="ngrok", presets=("developer", "student", "windows"),
      builtin={"desktop": ["devos-share.desktop"]}),
    F("backup", "devos", "Cloud Backup", "Optional backup of your folders to Google Drive or OneDrive.", 1,
      win="OneDrive backup", presets=EVERYONE, builtin={"desktop": ["devos-backup.desktop"]}),
    F("vault", "devos", "DevOS Vault",
      "Encrypt a folder with a password after install. Full-disk encryption is still chosen in the installer.",
      1, win="Device encryption", presets=ESSENTIAL, builtin={"desktop": ["devos-vault.desktop"]}),
    F("restore", "devos", "Restore points",
      "btrfs snapshots you can roll back, taken automatically before package updates.",
      1, win="System Restore", presets=ESSENTIAL, builtin={"desktop": ["devos-restore.desktop"]}),
    F("islamic", "family", "Islamic DevOS: prayer times, Quran & Hadith",
      "Prayer-time reminders, Qibla, Hijri date, and a daily ayah and hadith from verified sources "
      "(Bangla + English); DevOS AI only adds labelled reflections.", 55, presets=("islamic",),
      builtin={"optin": True, "desktop": ["devos-islamic.desktop"],
               "enable": [[DEVOS + "devos-islamic", "fetch-content", "--system"],
                          ["systemctl", "--global", "enable", "devos-islamic.service"]],
               "disable": [["systemctl", "--global", "disable", "devos-islamic.service"]]}),
    F("familysafe", "family", "Family Safety: block adult content",
      "Blocks adult sites for every app, forces SafeSearch and YouTube Restricted mode, turns off private "
      "browsing. Set a password so children can't switch it off.", 1, presets=("islamic", "family"),
      builtin={"optin": True,
               "enable": [[DEVOS + "devos-familysafe", "enable", "--level", "family"]],
               "disable": [[DEVOS + "devos-familysafe", "disable"]]}),
    F("modesty", "family", "Modesty filter: blur adult women body regions",
      "Local AI masks detected body regions in Chrome, Edge and Brave while keeping page text clear. "
      "Age, gender and body estimates can be wrong or missed. An all-people mode is also available.", 1, presets=("islamic",), min_ram_gb=4,
      builtin={"optin": True,
               "enable": [["/usr/local/sbin/devos-modesty", "enable", "--mode", "women"]],
               "disable": [["/usr/local/sbin/devos-modesty", "disable"]]}),
]

PRESETS = [
    ("recommended", "Normal", "Everyday apps for a normal PC. Heavy ones stay off when this computer is small."),
    ("professional", "Professional", "Office, Outlook, Teams, Zoom, PDF tools, remote desktop and a password manager, plus the everyday apps."),
    ("student", "Student", "Notes, Zoom, Office and a password manager, plus the everyday apps."),
    ("developer", "Development", "Code editor, servers, databases, Git and API tools, plus the everyday apps."),
    ("creator", "Creator", "Photo, drawing, video and audio tools, plus the everyday apps."),
    ("gamer", "Gamer", "Steam, Epic, GOG, Discord and game recording, plus the everyday apps."),
    ("business", "Business", "The professional set, plus company network sign-in and remote access to office PCs."),
    ("family", "Family", "The normal everyday apps, plus Family Safety so adult sites stay blocked."),
    ("islamic", "Normal + Islamic", "The normal everyday apps, plus prayer times, Quran & Hadith and Family Safety."),
    ("premium", "Premium", "Every app DevOS offers. Family Safety and the modesty filter stay off until you turn them on."),
    ("later", "Choose later", "Skip the extra apps for now. After install, add or remove any of them in DevOS Features, or ask DevOS AI."),
    ("windows", "Windows-like", "Office, Edge, WhatsApp, Spotify, email and the everyday tools Windows users expect."),
    ("minimal", "Minimal", "Only what DevOS needs; add apps later in DevOS Features."),
]

# The page before Choose your apps. id is what the installer stores.
USER_TYPES = [
    ("normal", "Normal", "Everyday apps: Office, browser, chat, music and photos. Apps that are too heavy for this computer stay off.", "⌂"),
    ("professional", "Professional", "Work apps: Office, Outlook, Teams, Zoom, PDF tools, remote desktop and a password manager, plus the everyday apps.", "Pro"),
    ("student", "Student", "Notes, Zoom, Office and a password manager, plus the everyday apps.", "✎"),
    ("developer", "Development", "Code editor, servers, databases, Git and API tools, plus the everyday apps.", "</>"),
    ("creator", "Creator", "Photo, drawing, video and audio tools, plus the everyday apps.", "✦"),
    ("gamer", "Gamer", "Steam, Epic, GOG, Discord and game recording, plus the everyday apps.", "♞"),
    ("business", "Business", "The professional set, plus signing this PC into a company network and remote access to office PCs.", "▣"),
    ("family", "Family", "The normal everyday apps, plus Family Safety so adult sites stay blocked.", "♥"),
    ("islamic", "Normal + Islamic", "The normal apps, plus prayer times, Quran and Hadith, and Family Safety. The modesty filter is included with this choice.", "☪"),
    ("premium", "Premium", "Every app DevOS offers. Family Safety and the modesty filter stay off until you turn them on.", "★"),
]

USER_TYPE_PRESETS = {
    "recommended": "normal",
    "normal": "normal",
    "professional": "professional",
    "student": "student",
    "developer": "developer",
    "creator": "creator",
    "gamer": "gamer",
    "business": "business",
    "family": "family",
    "islamic": "islamic",
    "premium": "premium",
}


def feature(fid: str) -> Optional[Dict]:
    return next((f for f in FEATURES if f["id"] == fid), None)


def optin(feature: Dict) -> bool:
    return bool((feature.get("builtin") or {}).get("optin"))


def premium_ids() -> List[str]:
    """Every app, for a complete PC. Opt-in family controls stay off."""
    return [f["id"] for f in FEATURES if not optin(f)]


def later_ids() -> List[str]:
    """What is already on the PC. Nothing new is downloaded."""
    return [f["id"] for f in FEATURES if f["preinstalled"] and not optin(f)]


def preset_ids(preset: str, ram_gb: Optional[float] = None, disk_gb: Optional[float] = None) -> List[str]:
    if preset in USER_TYPE_PRESETS:
        return user_type_ids(preset, ram_gb, disk_gb)
    if preset == "later":
        return later_ids()
    return [f["id"] for f in FEATURES if preset in f["presets"]]


def this_pc():
    """(RAM GB, disk GB) of the running PC, for "Recommended for this PC"."""
    import os
    import shutil
    ram = 4.0
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    ram = int(line.split()[1]) / 1048576
                    break
    except (OSError, ValueError):
        pass
    try:
        disk = shutil.disk_usage("/").total / 1e9
    except OSError:
        disk = 0.0
    return round(ram, 1), round(disk, 1)


def default_ids() -> List[str]:
    return preset_ids("windows")


SMALL_DISK_GB = 64
BIG_DOWNLOAD_MB = 500


def recommended_ids(ram_gb: float, disk_gb: float) -> List[str]:
    """The installer's "Recommended for this PC": the Windows-like set minus
    apps this PC's memory can't run smoothly, and minus big downloads on small
    disks. featuresq.qml (featuresRecommended in features-catalog.js) does the
    same; keep them in step."""
    ids = []
    for f in FEATURES:
        if "windows" not in f["presets"]:
            continue
        if ram_gb + 0.5 < f["min_ram_gb"]:
            continue
        if 0 < disk_gb < SMALL_DISK_GB and not f["preinstalled"] and f["size_mb"] > BIG_DOWNLOAD_MB:
            continue
        ids.append(f["id"])
    # Every PC gets an office suite: the lighter LibreOffice when ONLYOFFICE
    # was left out for this PC.
    if "onlyoffice" not in ids:
        ids.insert(0, "libreoffice")
    return ids


def _tagged(*presets: str):
    wanted = set(presets)
    return {f["id"] for f in FEATURES if wanted.intersection(f["presets"])}


def _ordered(wanted) -> List[str]:
    return [f["id"] for f in FEATURES if f["id"] in wanted]


def user_type_ids(kind: str, ram_gb: Optional[float] = None, disk_gb: Optional[float] = None) -> List[str]:
    """Apps ticked for one of the 10 choices on the page before Choose your apps.

    Normal and Family leave off apps this PC cannot run smoothly. The other
    choices add their own apps on top of the everyday Windows set.
    """
    kind = USER_TYPE_PRESETS.get(kind, kind)
    if ram_gb is None or disk_gb is None:
        ram, disk = this_pc()
        ram_gb = ram if ram_gb is None else ram_gb
        disk_gb = disk if disk_gb is None else disk_gb
    everyday = _tagged("windows")
    if kind == "normal":
        return recommended_ids(ram_gb, disk_gb)
    if kind == "premium":
        return premium_ids()
    if kind == "family":
        return _ordered(set(recommended_ids(ram_gb, disk_gb)) | _tagged("family"))
    if kind == "islamic":
        return _ordered(_tagged("islamic"))
    if kind == "professional":
        return _ordered(everyday | _tagged("professional"))
    if kind == "business":
        return _ordered(everyday | _tagged("professional", "business"))
    if kind in ("student", "developer", "creator", "gamer"):
        return _ordered(everyday | _tagged(kind))
    return recommended_ids(ram_gb, disk_gb)


def parse_selection(text: str) -> List[str]:
    """"onlyoffice,chrome,…" -> known ids in catalog order (unknown ids dropped)."""
    wanted = {p.strip() for p in (text or "").replace("\n", ",").split(",") if p.strip()}
    return [f["id"] for f in FEATURES if f["id"] in wanted]


def plan(selected: List[str], installed: List[str]) -> Dict[str, List[str]]:
    """What to add and what to remove to go from `installed` to `selected`."""
    sel, have = set(selected), set(installed)
    return {
        "add": [f["id"] for f in FEATURES if f["id"] in sel and f["id"] not in have],
        "remove": [f["id"] for f in FEATURES if f["id"] in have and f["id"] not in sel],
    }


def size_mb(ids: List[str], only_downloads: bool = True) -> int:
    return sum(f["size_mb"] for f in FEATURES if f["id"] in ids and not (only_downloads and f["preinstalled"]))
