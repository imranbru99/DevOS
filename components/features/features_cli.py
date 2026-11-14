#!/usr/bin/env python3
"""
devos-features: add and remove DevOS apps and features (feature_catalog.py).

  devos-features list [--json]          every feature, installed or not
  devos-features status                 choice, installed, pending, progress (JSON)
  devos-features set --add a,b --remove c   change the choice and apply it (root)
  devos-features set --only a,b,c       make exactly these the choice (root)
  devos-features apply                  install what is chosen but missing (root, needs internet)
  devos-features installer-plan FILE    run by the installer inside the new system

The installer page stores the ticked ids in Calamares' global storage;
preservefiles copies that into the new system and "installer-plan" removes
unticked built-ins right away (no internet needed) and leaves the downloads to
devos-features.service, which runs at boot until everything is in.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import feature_catalog as catalog  # noqa: E402

CHOICE_FILE = "/etc/devos/features.conf"
STATE_DIR = "/var/lib/DevOS/features"
STATE_FILE = os.path.join(STATE_DIR, "state.json")
LOG_FILE = "/var/log/devos-features.log"
SERVICE_UNIT = "/etc/systemd/system/devos-features.service"
SERVICE_LINK = "/etc/systemd/system/multi-user.target.wants/devos-features.service"
MIMEAPPS = "/etc/xdg/mimeapps.list"
# DevOS's own tools are switched off by hiding their menu entries: a file of
# the same name here wins over /usr/share/applications (XDG_DATA_DIRS order),
# and "Hidden=true" makes the menu treat the app as removed.
OVERRIDE_DIR = "/usr/local/share/applications"
SYSTEM_APP_DIR = "/usr/share/applications"
MARKER_DIR = "/etc/devos/features.d"
HIDDEN_ENTRY = "[Desktop Entry]\nType=Application\nHidden=true\nX-DevOS-Hidden=true\n"
INSTALLER_CHOICE_KEY = "devos_selected_features"
OFFLINE_REPO = Path("/usr/local/share/devos/offline-apt")
OFFLINE_VENDOR = {"chrome": "google-chrome-stable", "vscode": "code"}

# Removing a feature must never take the desktop, the installer or DevOS
# itself with it (apt removes everything that depends on a purged package).
PROTECTED = {
    "plasma-desktop", "plasma-workspace", "kwin-x11", "kwin-wayland", "sddm", "dolphin", "konsole",
    "systemsettings", "network-manager", "plasma-nm", "python3", "python3-pyqt5", "systemd", "sudo",
    "linux-image-generic", "linux-generic", "grub-common", "calamares", "flatpak", "pipewire",
    "xserver-xorg", "dbus", "udev", "okular", "kate", "ark", "gwenview", "falkon",
} | catalog.BASE_PACKAGES

# Phone Link (8765), KDE Connect and the DevOS AI API (key-protected) answer
# only on home networks when the firewall is on.
PRIVATE_NETS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
FIREWALL_PORTS = (("8765", "tcp"), ("1714:1764", "tcp"), ("1714:1764", "udp"), ("11434", "tcp"))

IBUS_ENV = """# Bangla typing (DevOS Features -> Bangla typing). Ctrl+Space switches.
export GTK_IM_MODULE=ibus
export QT_IM_MODULE=ibus
export XMODIFIERS=@im=ibus
command -v ibus-daemon >/dev/null 2>&1 && (ibus-daemon -drx >/dev/null 2>&1 &)
"""
IBUS_OVERRIDE = """[org.freedesktop.ibus.general]
preload-engines=['xkb:us::eng', 'ibus-avro']

[org.freedesktop.ibus.general.hotkey]
triggers=['<Control>space']
"""


# ---------------------------------------------------------------- helpers

def log(message: str) -> None:
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + message
    print(message, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def run(cmd, env=None, timeout=3600) -> int:
    log("$ " + " ".join(cmd))
    full_env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", **(env or {}))
    try:
        proc = subprocess.run(cmd, env=full_env, timeout=timeout, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"  failed: {exc}")
        return 1
    tail = (proc.stdout or "").strip().splitlines()[-5:]
    for line in tail:
        log("  " + line)
    return proc.returncode


def read_choice(path: str = CHOICE_FILE):
    try:
        with open(path, encoding="utf-8") as handle:
            text = "\n".join(l for l in handle if not l.startswith("#"))
        return catalog.parse_selection(text)
    except OSError:
        return None  # never chosen: keep whatever is installed


def write_choice(ids, path: str = CHOICE_FILE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("# DevOS features, chosen in the installer or DevOS Features.\n")
        handle.write(",".join(catalog.parse_selection(",".join(ids))) + "\n")


def read_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def write_state(**values) -> None:
    state = read_state()
    state.update(values, updated=int(time.time()))
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = STATE_FILE + ".new"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1)
    os.chmod(tmp, 0o644)  # the Features window and sign-in notice read it
    os.replace(tmp, STATE_FILE)


def deb_installed(pkg: str) -> bool:
    try:
        out = subprocess.run(["dpkg-query", "-W", "-f=${Status}", pkg.split(":")[0]],
                             capture_output=True, text=True)
    except OSError:
        return False
    return out.returncode == 0 and "install ok installed" in out.stdout


def flatpak_installed(app: str) -> bool:
    try:
        return subprocess.run(["flatpak", "info", "--system", app], capture_output=True).returncode == 0
    except OSError:
        return False  # flatpak missing


def builtin_on(feature: dict) -> bool:
    built = feature["builtin"]
    if built.get("optin"):
        return os.path.exists(os.path.join(MARKER_DIR, feature["id"] + ".on"))
    return not any(_hidden(d) for d in built.get("desktop", []))


def _hidden(desktop: str) -> bool:
    for directory in (OVERRIDE_DIR, SYSTEM_APP_DIR):
        try:
            with open(os.path.join(directory, desktop), encoding="utf-8") as handle:
                return "X-DevOS-Hidden=true" in handle.read()
        except FileNotFoundError:
            continue
    return False


def set_desktops_visibility(desktops, on: bool) -> None:
    """Show or hide Start-menu .desktop basenames under /usr/local/share/applications."""
    os.makedirs(OVERRIDE_DIR, exist_ok=True)
    hidden_keys = {"Hidden=true", "NoDisplay=true", "X-DevOS-Hidden=true"}

    def _strip_hidden(text: str) -> str:
        return "".join(
            line for line in text.splitlines(keepends=True)
            if line.strip() not in hidden_keys
        )

    for desktop in desktops or []:
        path = os.path.join(OVERRIDE_DIR, desktop)
        backup = path + ".devos-feature-backup"
        if on:
            if not _hidden(desktop):
                continue
            if os.path.lexists(backup):
                os.replace(backup, path)
                continue
            # Prefer DevOS/debrand override (friendly Name=) over upstream.
            template = None
            for directory in (OVERRIDE_DIR, SYSTEM_APP_DIR):
                candidate = os.path.join(directory, desktop)
                try:
                    text = Path(candidate).read_text(encoding="utf-8")
                except FileNotFoundError:
                    continue
                # Skip our tiny hide stub — keep looking for a real launcher.
                if text.strip() == HIDDEN_ENTRY.strip() or text.count("\n") < 4:
                    continue
                template = text
                break
            if template is None:
                continue
            Path(path).write_text(_strip_hidden(template), encoding="utf-8")
        else:
            if os.path.lexists(path) and not _hidden(desktop) and not os.path.lexists(backup):
                os.replace(path, backup)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(HIDDEN_ENTRY)


def set_builtin_visibility(feature: dict, on: bool) -> None:
    set_desktops_visibility((feature.get("builtin") or {}).get("desktop", []), on)


def set_feature_menu_visibility(feature: dict, on: bool) -> None:
    """Hide every launcher this feature owns when it was not chosen."""
    set_desktops_visibility(catalog.feature_desktops(feature), on)


def set_builtin(feature: dict, on: bool) -> bool:
    built = feature["builtin"]
    ok = True
    for cmd in built.get("enable" if on else "disable", []):
        ok = run(cmd) == 0 and ok
    if on and not ok:
        return False
    set_feature_menu_visibility(feature, on)
    marker = os.path.join(MARKER_DIR, feature["id"] + ".on")
    if on:
        os.makedirs(MARKER_DIR, exist_ok=True)
        open(marker, "w").close()
    elif os.path.exists(marker):
        os.remove(marker)
    return ok


# One Windows App only: the ISO ships /usr/share/applications/devos-web-winapp.desktop.
# Never also write /usr/local/share/applications/devos-web-winapp.desktop (that made
# Kicker show two "Windows App" rows). Chrome's PWA copy is hidden by chrome_start_menu.
WINAPP_DESKTOP = "devos-web-winapp.desktop"
WINAPP_SYSTEM_PATH = os.path.join(SYSTEM_APP_DIR, WINAPP_DESKTOP)
WINAPP_OVERRIDE_PATH = os.path.join(OVERRIDE_DIR, WINAPP_DESKTOP)


def webapp_path(feature: dict) -> str:
    if feature.get("id") == "winapp":
        return WINAPP_SYSTEM_PATH
    return os.path.join(OVERRIDE_DIR, "devos-web-%s.desktop" % feature["id"])


def webapp_enabled(feature: dict) -> bool:
    try:
        entry = Path(webapp_path(feature)).read_text(encoding="utf-8")
    except OSError:
        return False
    return "X-DevOS-WebApp=true" in entry and not re.search(
        r"^(?:Hidden|NoDisplay)\s*=\s*true\s*$", entry, re.MULTILINE | re.IGNORECASE
    )


CHROME_POLICY = "/etc/opt/chrome/policies/managed/devos-webapps.json"


def webapp_entry(feature: dict) -> str:
    """First-launch Start-menu entry for a vendor web app. devos-pwa opens the
    app Chrome installed from CHROME_POLICY and then hides this entry in
    favour of Chrome's own launcher, which carries the vendor's real icon.
    Windows App keeps a single DevOS companion entry (system path only).
    A Cloud PC connection stays in that app because the launcher uses the
    installed PWA with navigation capturing — same as Microsoft's Windows App."""
    web = feature["webapp"]
    names = "|".join(web.get("names") or [feature["name"].split(" (")[0]])
    if feature["id"] == "winapp":
        # Short Comment: long about text used to look like a second, different app.
        return (
            "[Desktop Entry]\nType=Application\n"
            "Name=Windows App\n"
            "GenericName=Microsoft Cloud PC\n"
            "Comment=Windows 365, Azure Virtual Desktop and remote apps\n"
            "Exec=/usr/local/bin/devos-windows-app\n"
            "Icon=devos-web-winapp\n"
            "StartupWMClass=chrome-windows.cloud.microsoft__-Default\n"
            "Categories=Network;Office;\nTerminal=false\n"
            "Keywords=windows;cloud;pc;rdp;azure;virtual desktop;365;\n"
            "X-DevOS-WebApp=true\n"
        )
    command = f'/usr/local/bin/devos-pwa {web["url"]} "{names}" devos-web-{feature["id"]}.desktop'
    return (
        "[Desktop Entry]\nType=Application\n"
        f"Name={feature['name'].split(' (')[0]}\n"
        f"Comment={feature['about']}\n"
        f"Exec={command}\n"
        f"Icon={web.get('icon', 'applications-internet')}\n"
        "Categories=Network;Office;\nTerminal=false\nX-DevOS-WebApp=true\n"
    )


def dedupe_windows_app_menu() -> None:
    """Ensure only one Windows App Start-menu entry exists."""
    # Prefer the ISO/system companion; drop the Features override duplicate.
    if os.path.isfile(WINAPP_SYSTEM_PATH) and os.path.isfile(WINAPP_OVERRIDE_PATH):
        try:
            os.remove(WINAPP_OVERRIDE_PATH)
        except OSError:
            try:
                with open(WINAPP_OVERRIDE_PATH, "w", encoding="utf-8") as handle:
                    handle.write(HIDDEN_ENTRY)
            except OSError:
                pass
    try:
        from browser.chrome_start_menu import clean_chrome_start_menu
        clean_chrome_start_menu()
    except Exception:
        pass
    try:
        from cloudpc.launchers import integrate
        apps = os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
                            "applications")
        integrate(apps)
    except Exception:
        pass


def webapp_policy(installed_urls) -> dict:
    """Chrome installs these as real apps for every user and removes them again
    when they leave the list."""
    return {
        "WebAppInstallForceList": [
            {"url": url, "default_launch_container": "window", "create_desktop_shortcut": False}
            for url in installed_urls
        ],
        "WebAppSettings": [
            {"manifest_id": url, "default_launch_container": "window"}
            for url in installed_urls
        ],
    }


def write_webapp_policy(path: str = CHROME_POLICY) -> None:
    chosen = set(read_choice() or [])
    urls = [f["webapp"]["url"] for f in catalog.FEATURES
            if f["id"] in chosen and f.get("webapp") and webapp_enabled(f)]
    if not urls:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(webapp_policy(urls), handle, indent=1)
    os.chmod(path, 0o644)


def detect_hit(spec: str) -> bool:
    """True when a catalog detect entry exists as a path or on PATH."""
    if not spec:
        return False
    if os.path.isabs(spec) or "/" in spec:
        return os.path.exists(os.path.expanduser(spec))
    return shutil.which(spec) is not None


def is_installed(feature: dict) -> bool:
    if feature.get("webapp"):
        return webapp_enabled(feature)
    detect = feature.get("detect") or []
    has_pkg = bool(feature.get("apt") or feature.get("flatpak") or feature.get("script") or detect)
    # Opt-in builtins stay off until Features enables them (marker), even if a
    # wrapper script exists on the ISO.
    if feature.get("builtin") and catalog.optin(feature) and not builtin_on(feature):
        return False
    if detect and any(detect_hit(p) for p in detect):
        return True
    # Pure builtins (no package): menu visibility is the install state.
    if feature.get("builtin") and not has_pkg:
        return builtin_on(feature)
    # Package-backed apps: follow apt/flatpak — not whether the menu is hidden.
    # (Hiding Calc while LibreOffice is still on disk must not block first-boot purge.)
    probes = feature["apt"] or ([] if feature["flatpak"] else feature["remove"][:1])
    if probes and not all(deb_installed(p) for p in probes):
        return False
    if feature["flatpak"] and not all(flatpak_installed(a) for a in feature["flatpak"]):
        return False
    return bool(probes or feature["flatpak"])


def installed_ids():
    return [f["id"] for f in catalog.FEATURES if is_installed(f)]


def apt_candidates(pkgs):
    """Only names apt can install here (a missing one would fail the whole batch)."""
    good = []
    for pkg in pkgs:
        out = subprocess.run(["apt-cache", "policy", pkg], capture_output=True, text=True).stdout
        match = re.search(r"Candidate:\s*(\S+)", out)
        if match and match.group(1) != "(none)":
            good.append(pkg)
        else:
            log(f"  {pkg} is not available, skipped")
    return good


def removal_hits_protected(simulation: str):
    """Package names apt would remove ("Purg x"/"Remv x" lines) that DevOS needs."""
    gone = re.findall(r"^(?:Purg|Remv) (\S+)", simulation, re.M)
    return sorted({g.split(":")[0] for g in gone} & PROTECTED)


# ---------------------------------------------------------------- add / remove

_apt_updated = False
_offline_updated = False


def install_from_media(packages) -> bool:
    """Try only the image's local APT index, keeping network APT lists separate."""
    global _offline_updated
    source = OFFLINE_REPO / "devos.list"
    if not source.is_file():
        return False
    lists = Path(STATE_DIR) / "offline-lists"
    lists.mkdir(parents=True, exist_ok=True)
    apt = [
        "apt-get", "-o", f"Dir::Etc::sourcelist={source}",
        "-o", "Dir::Etc::sourceparts=-", "-o", f"Dir::State::lists={lists}",
        "-o", "Acquire::Languages=none",
    ]
    if not _offline_updated:
        _offline_updated = run([*apt, "update"]) == 0
    return _offline_updated and run([*apt, "install", "-y", "--no-install-recommends", *packages]) == 0


def apt_update() -> bool:
    global _apt_updated
    if not _apt_updated:
        _apt_updated = run(["apt-get", "update"]) == 0
    return _apt_updated


def add_feature(feature: dict) -> bool:
    log(f"Installing {feature['name']}…")
    # Builtin-only features (no download): just show menu entries.
    if feature.get("builtin") and not (
        feature.get("apt") or feature.get("flatpak") or feature.get("script") or feature.get("webapp")
    ):
        return set_builtin(feature, True)
    if feature.get("webapp"):
        if feature["id"] == "winapp":
            # Single menu entry only — never create a second .desktop under OVERRIDE_DIR.
            os.makedirs(SYSTEM_APP_DIR, exist_ok=True)
            with open(WINAPP_SYSTEM_PATH, "w", encoding="utf-8") as handle:
                handle.write(webapp_entry(feature))
            dedupe_windows_app_menu()
            write_webapp_policy()
            after_install(feature)
            return True
        os.makedirs(OVERRIDE_DIR, exist_ok=True)
        with open(webapp_path(feature), "w", encoding="utf-8") as handle:
            handle.write(webapp_entry(feature))
        write_webapp_policy()
        return True
    ok = True
    if feature["eula"]:
        subprocess.run(["debconf-set-selections"], input=feature["eula"] + "\n", text=True)
    if feature["apt"] and not install_from_media(feature["apt"]):
        if not apt_update():
            return False
        pkgs = apt_candidates(feature["apt"])
        ok = bool(pkgs) and run(["apt-get", "install", "-y", "--no-install-recommends"] + pkgs) == 0
    if ok and feature["flatpak"]:
        ok = run(["flatpak", "install", "--system", "-y", "--noninteractive", "flathub"] + feature["flatpak"]) == 0
    if ok and feature["script"]:
        vendor = OFFLINE_VENDOR.get(feature["id"])
        if vendor and not deb_installed(vendor):
            if install_from_media([vendor]):
                log(f"  {feature['name']}: installed from offline media")
            else:
                log(f"  {feature['name']}: offline media unavailable; using install script")
        # Script still runs when the vendor package is present — it applies
        # DevOS policies / menu cleanup and is a no-op install when already there.
        ok = run(["/bin/bash", feature["script"]]) == 0
    if ok and feature.get("builtin"):
        ok = set_builtin(feature, True)
    elif ok and catalog.feature_desktops(feature):
        set_feature_menu_visibility(feature, True)
    if ok:
        after_install(feature)
    return ok


def remove_feature(feature: dict, no_triggers: bool = False) -> bool:
    log(f"Removing {feature['name']}…")
    if feature.get("builtin") and not (
        feature.get("apt") or feature.get("flatpak") or feature.get("script") or feature.get("webapp")
    ):
        return set_builtin(feature, False)
    if feature.get("webapp"):
        if feature["id"] == "winapp":
            # Hide the single companion; do not leave an OVERRIDE duplicate behind.
            try:
                with open(WINAPP_SYSTEM_PATH, "w", encoding="utf-8") as handle:
                    handle.write(HIDDEN_ENTRY)
            except OSError:
                pass
            try:
                os.remove(WINAPP_OVERRIDE_PATH)
            except OSError:
                pass
            write_webapp_policy()
            return True
        try:
            os.remove(webapp_path(feature))
        except OSError:
            pass
        write_webapp_policy()
        return True
    pkgs = [p for p in feature["remove"] if p.split(":", 1)[0] not in PROTECTED and deb_installed(p)]
    if pkgs:
        sim = subprocess.run(["apt-get", "-s", "purge"] + pkgs, capture_output=True, text=True).stdout
        hits = removal_hits_protected(sim)
        if hits:
            log(f"  kept {feature['name']}: removing it would also remove {', '.join(hits)}")
            return False
        purge = ["apt-get", "purge", "-y"] + pkgs
        if no_triggers:
            # The installer chroot must not run initramfs or shim triggers.
            # The initramfs module rebuilds the boot image after this.
            purge = ["apt-get", "-o", "Dpkg::Options::=--no-triggers", "purge", "-y"] + pkgs
        if run(purge) != 0:
            return False
    for app in feature["flatpak"]:
        if flatpak_installed(app):
            if run(["flatpak", "uninstall", "--system", "-y", "--noninteractive", app]) != 0:
                return False
    if feature.get("builtin"):
        set_builtin(feature, False)
    elif catalog.feature_desktops(feature):
        set_feature_menu_visibility(feature, False)
    after_remove(feature)
    return True


def after_install(feature: dict) -> None:
    if feature["id"] == "firewall":
        for port, proto in FIREWALL_PORTS:
            for net in PRIVATE_NETS:
                run(["ufw", "allow", "from", net, "to", "any", "port", port, "proto", proto])
        run(["ufw", "--force", "enable"])
    elif feature["id"] == "bangla":
        os.makedirs("/etc/xdg/plasma-workspace/env", exist_ok=True)
        with open("/etc/xdg/plasma-workspace/env/devos-ibus.sh", "w", encoding="utf-8") as handle:
            handle.write(IBUS_ENV)
        with open("/usr/share/glib-2.0/schemas/90_devos-ibus.gschema.override", "w", encoding="utf-8") as handle:
            handle.write(IBUS_OVERRIDE)
        run(["glib-compile-schemas", "/usr/share/glib-2.0/schemas"])
    elif feature["id"] == "winapp":
        dedupe_windows_app_menu()


def after_remove(feature: dict) -> None:
    if feature["id"] == "bangla":
        for path in ("/etc/xdg/plasma-workspace/env/devos-ibus.sh",
                     "/usr/share/glib-2.0/schemas/90_devos-ibus.gschema.override"):
            try:
                os.remove(path)
            except OSError:
                pass


# ---------------------------------------------------------------- default apps

def system_defaults(installed):
    """role -> desktop file: the first installed feature in catalog order wins
    (ONLYOFFICE before LibreOffice; Google Chrome before Edge/Firefox).

    When Chrome (or another browser feature) is installed, it becomes the
    system default so app logins/OAuth open there instead of DevOS Browser.
    Users can still override in DevOS Features -> Default apps."""
    chosen = {}
    for feature in catalog.FEATURES:
        if feature["id"] not in installed:
            continue
        for role, desktop in feature["roles"].items():
            chosen.setdefault(role, desktop)
    return chosen


def write_mimeapps(defaults, path: str = MIMEAPPS) -> None:
    lines = []
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        pass
    wanted = {}
    for role, desktop in defaults.items():
        for mime in catalog.ROLES.get(role, []):
            wanted[mime] = desktop
    out, section, done = [], "", set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if section == "[Default Applications]":
                out.extend(f"{m}={d}" for m, d in wanted.items() if m not in done)
                done.update(wanted)
            section = stripped
        elif section == "[Default Applications]" and "=" in stripped:
            mime = stripped.split("=", 1)[0]
            if mime in wanted:
                line = f"{mime}={wanted[mime]}"
                done.add(mime)
        out.append(line)
    if section == "[Default Applications]":
        out.extend(f"{m}={d}" for m, d in wanted.items() if m not in done)
    elif "[Default Applications]" not in lines:
        out += ["", "[Default Applications]"] + [f"{m}={d}" for m, d in wanted.items()]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out).strip() + "\n")


# ---------------------------------------------------------------- service

def enable_service() -> None:
    if os.path.exists(SERVICE_UNIT) and not os.path.lexists(SERVICE_LINK):
        os.makedirs(os.path.dirname(SERVICE_LINK), exist_ok=True)
        os.symlink(SERVICE_UNIT, SERVICE_LINK)


def disable_service() -> None:
    try:
        os.remove(SERVICE_LINK)
    except OSError:
        pass


def apply(selected, remove_unselected: bool) -> bool:
    try:
        return _apply(selected, remove_unselected)
    finally:
        # A crash or kill must not leave the Features window waiting forever.
        if read_state().get("running"):
            write_state(running=False, current="")


def _apply(selected, remove_unselected: bool) -> bool:
    have = installed_ids()
    todo = catalog.plan(selected, have)
    if remove_unselected:
        queued = read_state().get("removing", [])
        removing = set(todo["remove"]) | (set(queued) - set(selected))
        todo["remove"] = [f["id"] for f in catalog.FEATURES if f["id"] in removing]
    else:
        todo["remove"] = []
    # DevOS's own tools switch on instantly and offline; doing them first means
    # Family Safety or prayer reminders don't wait behind gigabytes of downloads.
    todo["add"].sort(key=lambda fid: not (catalog.feature(fid).get("builtin") or catalog.feature(fid).get("webapp")))
    write_state(running=True, pending=todo["add"], removing=todo["remove"], failed={}, current="")
    failed = {}
    for fid in todo["remove"]:
        feature = catalog.feature(fid)
        write_state(current=feature["name"])
        if not remove_feature(feature):
            failed[fid] = "could not be removed safely"
    for fid in todo["add"]:
        feature = catalog.feature(fid)
        write_state(current=feature["name"])
        if not add_feature(feature):
            failed[fid] = "download or install failed"
        write_state(pending=[p for p in read_state().get("pending", []) if p != fid])
    installed = installed_ids()
    write_mimeapps(system_defaults(installed))
    missing = [fid for fid in selected if fid not in installed]
    for fid in missing:
        if fid not in failed:
            failed[fid] = "download or install failed"
    write_state(running=False, current="", failed=failed, pending=missing, removing=[], installed=installed)
    if missing:
        enable_service()
    else:
        disable_service()
    return not missing


def _selection_value(value):
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ",".join(value)
    return value if isinstance(value, str) else None


def _parsed_feature_ids(data: dict, key: str):
    value = _selection_value(data.get(key))
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = catalog.parse_selection(value)
    return parsed or None


def selection_from_gs(data: dict):
    """Read the installer app ticks from preserved global storage.

    featuresq.qml writes both ``devos_selected_features`` and Calamares'
    ``packagechooser_features``. Prefer the DevOS key when it lists apps.
    When it is missing or empty, fall back to Calamares' packageChoice so a
    ticked Chrome (or other app) is not dropped if only one key survived.
    """
    if INSTALLER_CHOICE_KEY in data:
        primary = _selection_value(data.get(INSTALLER_CHOICE_KEY))
        if isinstance(primary, str) and primary.strip():
            return catalog.parse_selection(primary)
        for key in ("packagechooser_features", "features"):
            parsed = _parsed_feature_ids(data, key)
            if parsed:
                return parsed
        # Explicit empty string → no optional apps. Wrong types → unknown.
        return [] if isinstance(primary, str) else None
    for key in ("packagechooser_features", "features"):
        parsed = _parsed_feature_ids(data, key)
        if parsed:
            return parsed
    return None


# Skel Desktop shortcuts tied to optional installer features (never core DevOS).
DESKTOP_SHORTCUT_FEATURES = (
    ("vscode", "devos-code.desktop"),
    ("vlc", "vlc.desktop"),
)


def remove_unselected_desktop_shortcuts(selected, username) -> None:
    # The installer has just copied these exact files from /etc/skel.
    # Leave edited or independently created shortcuts alone.
    import pwd

    skeleton = Path("/etc/skel/Desktop")
    try:
        desktop = Path(pwd.getpwnam(username).pw_dir) / "Desktop"
    except (KeyError, TypeError):
        desktop = None
    selected_set = set(selected or [])
    for feature, name in DESKTOP_SHORTCUT_FEATURES:
        if feature in selected_set:
            continue
        template = skeleton / name
        try:
            if template.is_file():
                if desktop is not None:
                    shortcut = desktop / template.name
                    if not shortcut.is_symlink() and shortcut.is_file() and shortcut.read_bytes() == template.read_bytes():
                        shortcut.unlink()
                template.unlink()
        except OSError as exc:
            log(f"Could not remove the unselected shortcut {template.name}: {exc}")


def installer_plan(path: str) -> int:
    """During Calamares: record the app choice only — never apt-purge here.

    Purging unticked packages used to freeze the installer near 89%
    ("Running shell process") for many minutes. Removals and downloads run
    on first boot via devos-features.service instead.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        selected = selection_from_gs(data) if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        selected = None
    finally:
        # The global-storage dump can hold account details: never keep it.
        try:
            os.remove(path)
        except OSError:
            pass
    if selected is None:
        log("No valid optional app choices were saved. Only the base system will be installed.")
        selected = []
        data = {}
    write_choice(selected)
    have = installed_ids()
    todo = catalog.plan(selected, have)
    selected_set = set(selected)
    # Only what the user ticked stays in All Applications. Hide role/menu
    # launchers (Calc, Fingerprint, GIMP, …) immediately — do not wait for apt purge.
    for feature in catalog.FEATURES:
        if feature["id"] in catalog.BASE_FEATURE_IDS:
            continue
        on = feature["id"] in selected_set
        if feature.get("webapp"):
            if not on and webapp_enabled(feature):
                remove_feature(feature)
        elif catalog.feature_desktops(feature) or feature.get("builtin"):
            # First boot exposes pending apps only after their setup succeeds.
            set_feature_menu_visibility(feature, on and feature["id"] in have)
    write_webapp_policy()
    remove_unselected_desktop_shortcuts(selected, data.get("username"))
    write_state(
        running=False,
        pending=todo["add"],
        removing=todo["remove"],
        failed={},
        current="",
    )
    if todo["add"] or todo["remove"]:
        enable_service()
    if todo["remove"]:
        log("Will trim unticked apps after first boot: " + ", ".join(todo["remove"]))
    if todo["add"]:
        log("To download after install: " + ", ".join(todo["add"]))
    return 0


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="devos-features", description="DevOS apps and features")
    sub = parser.add_subparsers(dest="cmd")
    lst = sub.add_parser("list")
    lst.add_argument("--json", action="store_true")
    sub.add_parser("status")
    st = sub.add_parser("set")
    st.add_argument("--add", default="")
    st.add_argument("--remove", default="")
    st.add_argument("--only", default=None)
    sub.add_parser("apply")
    ip = sub.add_parser("installer-plan")
    ip.add_argument("file")
    sub.add_parser("catalog")
    args = parser.parse_args(argv)

    if args.cmd == "catalog":
        print(json.dumps({"categories": catalog.CATEGORIES, "presets": catalog.PRESETS,
                          "features": catalog.FEATURES, "roles": catalog.ROLE_NAMES}, indent=1))
        return 0

    if args.cmd in (None, "list"):
        have = set(installed_ids())
        chosen = read_choice()
        if getattr(args, "json", False):
            print(json.dumps([dict(f, installed=f["id"] in have,
                                   chosen=(f["id"] in chosen) if chosen is not None else f["id"] in have)
                              for f in catalog.FEATURES], indent=1))
            return 0
        for cat, title in catalog.CATEGORIES:
            print(title)
            for f in (f for f in catalog.FEATURES if f["category"] == cat):
                mark = "x" if f["id"] in have else " "
                print(f"  [{mark}] {f['id']:14} {f['name']}  ({f['size_mb']} MB)")
        return 0

    if args.cmd == "status":
        have = installed_ids()
        chosen = read_choice()
        print(json.dumps({"chosen": chosen if chosen is not None else have, "installed": have,
                          "state": read_state()}, indent=1))
        return 0

    if os.name == "posix" and os.geteuid() != 0:
        print("This needs administrator rights: run it with pkexec or sudo.", file=sys.stderr)
        return 1

    if args.cmd == "set":
        current = read_choice()
        if current is None:
            current = installed_ids()
        if args.only is not None:
            selected = catalog.parse_selection(args.only)
        else:
            add = catalog.parse_selection(args.add)
            drop = set(catalog.parse_selection(args.remove))
            selected = [f for f in catalog.parse_selection(",".join(current + add)) if f not in drop]
        write_choice(selected)
        return 0 if apply(selected, remove_unselected=True) else 1

    if args.cmd == "apply":
        selected = read_choice()
        if selected is None:
            return 0
        # First boot after install: also remove unticked apps queued by
        # installer-plan. Later boots (pending downloads only) skip removals.
        queued_remove = bool(read_state().get("removing"))
        return 0 if apply(selected, remove_unselected=queued_remove) else 1

    if args.cmd == "installer-plan":
        return installer_plan(args.file)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
