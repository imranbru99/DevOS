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
import subprocess
import sys
import time

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
MARKER_DIR = "/etc/devos/features.d"
HIDDEN_ENTRY = "[Desktop Entry]\nType=Application\nHidden=true\nX-DevOS-Hidden=true\n"
GS_KEYS = ("packagechooser_features", "features")

# Removing a feature must never take the desktop, the installer or DevOS
# itself with it (apt removes everything that depends on a purged package).
PROTECTED = {
    "plasma-desktop", "plasma-workspace", "kwin-x11", "kwin-wayland", "sddm", "dolphin", "konsole",
    "systemsettings", "network-manager", "plasma-nm", "python3", "python3-pyqt5", "systemd", "sudo",
    "linux-image-generic", "linux-generic", "grub-common", "calamares", "flatpak", "pipewire",
    "xserver-xorg", "dbus", "udev", "okular", "kate", "ark", "gwenview", "falkon",
}

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
    try:
        with open(os.path.join(OVERRIDE_DIR, desktop), encoding="utf-8") as handle:
            return "X-DevOS-Hidden=true" in handle.read()
    except OSError:
        return False


def set_builtin(feature: dict, on: bool) -> bool:
    built = feature["builtin"]
    ok = True
    for cmd in built.get("enable" if on else "disable", []):
        ok = run(cmd) == 0 and ok
    if on and not ok:
        return False
    os.makedirs(OVERRIDE_DIR, exist_ok=True)
    for desktop in built.get("desktop", []):
        path = os.path.join(OVERRIDE_DIR, desktop)
        if on:
            if _hidden(desktop):
                os.remove(path)
        else:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(HIDDEN_ENTRY)
    marker = os.path.join(MARKER_DIR, feature["id"] + ".on")
    if on:
        os.makedirs(MARKER_DIR, exist_ok=True)
        open(marker, "w").close()
    elif os.path.exists(marker):
        os.remove(marker)
    return ok


def webapp_path(feature: dict) -> str:
    return os.path.join(OVERRIDE_DIR, "devos-web-%s.desktop" % feature["id"])


CHROME_POLICY = "/etc/opt/chrome/policies/managed/devos-webapps.json"


def webapp_entry(feature: dict) -> str:
    """First-launch Start-menu entry for a vendor web app. devos-pwa opens the
    app Chrome installed from CHROME_POLICY and then hides this entry in
    favour of Chrome's own launcher, which carries the vendor's real icon.
    A Cloud PC connection stays in that app because Chrome's launcher keeps
    the new window there."""
    web = feature["webapp"]
    names = "|".join(web.get("names") or [feature["name"].split(" (")[0]])
    return (
        "[Desktop Entry]\nType=Application\n"
        f"Name={feature['name'].split(' (')[0]}\n"
        f"Comment={feature['about']}\n"
        f"Exec=/usr/local/bin/devos-pwa {web['url']} \"{names}\" devos-web-{feature['id']}.desktop\n"
        f"Icon={web.get('icon', 'applications-internet')}\n"
        "Categories=Network;Office;\nTerminal=false\nX-DevOS-WebApp=true\n"
    )


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
    urls = [f["webapp"]["url"] for f in catalog.FEATURES
            if f.get("webapp") and os.path.exists(webapp_path(f))]
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


def is_installed(feature: dict) -> bool:
    if feature.get("webapp"):
        return os.path.exists(webapp_path(feature))
    if feature.get("builtin"):
        return builtin_on(feature)
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


def apt_update() -> bool:
    global _apt_updated
    if not _apt_updated:
        _apt_updated = run(["apt-get", "update"]) == 0
    return _apt_updated


def add_feature(feature: dict) -> bool:
    log(f"Installing {feature['name']}…")
    if feature.get("builtin"):
        return set_builtin(feature, True)
    if feature.get("webapp"):
        os.makedirs(OVERRIDE_DIR, exist_ok=True)
        with open(webapp_path(feature), "w", encoding="utf-8") as handle:
            handle.write(webapp_entry(feature))
        write_webapp_policy()
        return True
    ok = True
    if feature["eula"]:
        subprocess.run(["debconf-set-selections"], input=feature["eula"] + "\n", text=True)
    if feature["apt"]:
        if not apt_update():
            return False
        pkgs = apt_candidates(feature["apt"])
        ok = bool(pkgs) and run(["apt-get", "install", "-y", "--no-install-recommends"] + pkgs) == 0
    if ok and feature["flatpak"]:
        ok = run(["flatpak", "install", "--system", "-y", "--noninteractive", "flathub"] + feature["flatpak"]) == 0
    if ok and feature["script"]:
        ok = run(["/bin/bash", feature["script"]]) == 0
    if ok:
        after_install(feature)
    return ok


def remove_feature(feature: dict, no_triggers: bool = False) -> bool:
    log(f"Removing {feature['name']}…")
    if feature.get("builtin"):
        return set_builtin(feature, False)
    if feature.get("webapp"):
        try:
            os.remove(webapp_path(feature))
        except OSError:
            pass
        write_webapp_policy()
        return True
    pkgs = [p for p in feature["remove"] if deb_installed(p)]
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
            run(["flatpak", "uninstall", "--system", "-y", "--noninteractive", app])
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
    (ONLYOFFICE before LibreOffice). The browser stays DevOS Browser, which
    opens the user's pick; people change it in DevOS Features -> Default apps."""
    chosen = {}
    for feature in catalog.FEATURES:
        if feature["id"] not in installed:
            continue
        for role, desktop in feature["roles"].items():
            if role != "browser":
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
    if not remove_unselected:
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
    write_state(running=False, current="", failed=failed, pending=missing, installed=installed)
    if missing:
        enable_service()
    else:
        disable_service()
    return not missing


def selection_from_gs(path: str):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    for key in GS_KEYS:
        if key in data:
            value = data[key]
            if isinstance(value, list):
                value = ",".join(value)
            return catalog.parse_selection(str(value))
    return None


def installer_plan(path: str) -> int:
    """Inside the new system, during install: remove unticked built-ins now,
    leave downloads for the first online boot."""
    try:
        selected = selection_from_gs(path)
    except (OSError, ValueError):
        selected = None
    finally:
        # The global-storage dump can hold account details: never keep it.
        try:
            os.remove(path)
        except OSError:
            pass
    if selected is None:
        log("No feature choice from the installer; keeping the standard set.")
        return 0
    if not selected:
        log("No apps were chosen. Keeping the apps already on this PC. "
            "Install or remove any app later in DevOS Features, or ask DevOS AI.")
        have = installed_ids()
        write_choice(have)
        write_state(running=False, pending=[], removing=[], failed={}, current="")
        return 0
    write_choice(selected)
    have = installed_ids()
    todo = catalog.plan(selected, have)
    for fid in todo["remove"]:
        remove_feature(catalog.feature(fid), no_triggers=True)
    run(["apt-get", "-o", "Dpkg::Options::=--no-triggers", "autoremove", "-y"])
    write_state(running=False, pending=todo["add"], removing=[], failed={}, current="")
    if todo["add"]:
        enable_service()
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
        # At boot only add: removals happen when the person asks for them.
        return 0 if apply(selected, remove_unselected=False) else 1

    if args.cmd == "installer-plan":
        return installer_plan(args.file)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
