#!/usr/bin/env python3
"""
DevOS Modesty filter - system switch (run as root).

    modesty.py enable [--mode women|people] [--keep-incognito]
    modesty.py disable
    modesty.py status [--json]

`enable` packs the extension into a signed CRX3, puts it with its update
manifest in /usr/share/devos/modesty/ and writes a managed browser policy that
force-installs it from there (file:// update URL, no web store, no server) and
locks it on through chrome.storage.managed ({"locked": true, "mode": ...}).
`disable` removes the policies and files again; Chrome then uninstalls the
extension by itself.

Used by the DevOS Islamic app and DevOS Features; the functions enable(),
disable() and status() can be imported directly. `--root DIR` (tests) writes
under DIR instead of /.
"""

import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crx3  # noqa: E402

EXT_DIR = os.path.join(HERE, "extension")
KEY_PATH = os.path.join(HERE, "key.pem")
DEVICE_KEY = "var/lib/devos-modesty/key.pem"

INSTALL_DIR = "usr/share/devos/modesty"
FLATPAK_DIR = "etc/devos/modesty"              # visible inside Flatpak browsers as /run/host/etc/...
STATE_FILE = "etc/devos/modesty.json"
CRX_NAME = "devos-modesty.crx"
UPDATE_XML = "update.xml"
FLATPAK_UPDATE_XML = "update-flatpak.xml"
POLICY_FILE = "devos-modesty.json"
MODES = ("women", "people")

# Browsers DevOS knows about. Chrome is the main browser and always gets the
# policy (it is harmless if Chrome is not installed yet, and makes the filter
# active as soon as it is). The others only when they are present.
BROWSERS = [
    {"name": "chrome", "always": True,
     "policy_dirs": ["etc/opt/chrome/policies/managed"],
     "native": ["opt/google/chrome/chrome", "usr/bin/google-chrome-stable"], "flatpak": []},
    {"name": "chromium",
     "policy_dirs": ["etc/chromium/policies/managed", "etc/chromium-browser/policies/managed"],
     "native": ["usr/bin/chromium", "usr/bin/chromium-browser", "usr/lib/chromium/chromium"], "flatpak": []},
    {"name": "edge",
     "policy_dirs": ["etc/opt/edge/policies/managed"],
     "native": ["opt/microsoft/msedge/msedge", "usr/bin/microsoft-edge-stable"],
     "flatpak": ["var/lib/flatpak/app/com.microsoft.Edge"]},
    {"name": "brave",
     "policy_dirs": ["etc/brave/policies/managed"],
     "native": ["opt/brave.com/brave/brave", "usr/bin/brave-browser"],
     "flatpak": ["var/lib/flatpak/app/com.brave.Browser"]},
]


def _p(root, rel):
    return os.path.join(root, rel)


def extension_version():
    with open(os.path.join(EXT_DIR, "manifest.json"), encoding="utf-8") as fh:
        return json.load(fh)["version"]


def extension_id(key_path=KEY_PATH):
    return crx3.extension_id(crx3.public_key_der(key_path))


def file_url(path):
    return "file://" + path


def build_policy(ext_id, update_url, mode, lock_private_modes=True):
    """Managed policy JSON for Chromium-based browsers on Linux."""
    if mode not in MODES:
        raise ValueError("mode must be one of %s" % ", ".join(MODES))
    policy = {
        "ExtensionSettings": {
            ext_id: {
                "installation_mode": "force_installed",
                "update_url": update_url,
                "toolbar_pin": "force_pinned",
            }
        },
        # chrome.storage.managed for the extension (Linux JSON policy "3rdparty" key).
        "3rdparty": {"extensions": {ext_id: {"locked": True, "mode": mode}}},
    }
    if lock_private_modes:
        # Extensions do not run in Incognito/Guest windows unless the user
        # allows it, so a locked filter closes those two side doors.
        policy["IncognitoModeAvailability"] = 1
        policy["BrowserGuestModeEnabled"] = False
    return policy


def detect_browsers(root):
    """[(browser, kind)] with kind 'native' or 'flatpak'."""
    found = []
    for b in BROWSERS:
        if any(os.path.exists(_p(root, x)) for x in b["native"]):
            found.append((b, "native"))
        elif any(os.path.exists(_p(root, x)) for x in b["flatpak"]):
            found.append((b, "flatpak"))
        elif b.get("always"):
            found.append((b, "native"))
    return found


def _write(path, data, mode=0o644):
    os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _require_root(root):
    if os.path.abspath(root) == os.path.abspath(os.sep) and hasattr(os, "geteuid") and os.geteuid() != 0:
        raise PermissionError("Run as root: sudo devos-modesty ...")


def pack(out_dir, codebase_dir, key_path=KEY_PATH, update_name=UPDATE_XML):
    """Write <out_dir>/devos-modesty.crx and the update manifest; return (ext_id, version)."""
    zip_bytes = crx3.zip_directory(EXT_DIR)
    crx = crx3.build_crx3(zip_bytes, key_path)
    ext_id = extension_id(key_path)
    version = extension_version()
    _write(os.path.join(out_dir, CRX_NAME), crx)
    xml = crx3.update_manifest_xml(ext_id, version, file_url(codebase_dir.rstrip("/") + "/" + CRX_NAME))
    _write(os.path.join(out_dir, update_name), xml)
    return ext_id, version


def enable(root="/", mode="women", lock_private_modes=True):
    _require_root(root)
    if mode not in MODES:
        raise ValueError("mode must be one of %s" % ", ".join(MODES))
    install = _p(root, INSTALL_DIR)
    key_path = _p(root, DEVICE_KEY)
    if not os.path.exists(key_path):
        os.makedirs(os.path.dirname(key_path), mode=0o700, exist_ok=True)
        if os.path.isfile(KEY_PATH):  # Keep the ID of an older local installation.
            with open(KEY_PATH, "rb") as handle:
                _write(key_path, handle.read(), mode=0o600)
        else:
            crx3.generate_key(key_path)
    ext_id, version = pack(install, "/" + INSTALL_DIR, key_path=key_path)
    browsers = detect_browsers(root)
    written = []
    if any(kind == "flatpak" for _, kind in browsers):
        # Flatpak browsers see the host's /etc (host-etc permission) but not its /usr.
        pack(_p(root, FLATPAK_DIR), "/run/host/" + FLATPAK_DIR, key_path=key_path, update_name=FLATPAK_UPDATE_XML)
    for b, kind in browsers:
        if kind == "flatpak":
            url = file_url("/run/host/" + FLATPAK_DIR + "/" + FLATPAK_UPDATE_XML)
        else:
            url = file_url("/" + INSTALL_DIR + "/" + UPDATE_XML)
        policy = build_policy(ext_id, url, mode, lock_private_modes)
        for d in b["policy_dirs"]:
            path = _p(root, os.path.join(d, POLICY_FILE))
            _write(path, json.dumps(policy, indent=2) + "\n")
            written.append(path)
    state = {"enabled": True, "mode": mode, "extension_id": ext_id, "version": version,
             "browsers": [b["name"] + ("" if kind == "native" else " (flatpak)") for b, kind in browsers],
             "lock_private_modes": lock_private_modes}
    _write(_p(root, STATE_FILE), json.dumps(state, indent=2) + "\n")
    return dict(state, policies=written)


def disable(root="/"):
    _require_root(root)
    removed = []
    for b in BROWSERS:
        for d in b["policy_dirs"]:
            path = _p(root, os.path.join(d, POLICY_FILE))
            if os.path.exists(path):
                os.remove(path)
                removed.append(path)
    for d in (INSTALL_DIR, FLATPAK_DIR):
        if os.path.isdir(_p(root, d)):
            shutil.rmtree(_p(root, d))
            removed.append(_p(root, d))
    state_path = _p(root, STATE_FILE)
    if os.path.exists(state_path):
        os.remove(state_path)
    return {"enabled": False, "removed": removed}


def status(root="/"):
    state = {}
    try:
        with open(_p(root, STATE_FILE), encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        pass
    policies = []
    for b in BROWSERS:
        for d in b["policy_dirs"]:
            path = _p(root, os.path.join(d, POLICY_FILE))
            if os.path.exists(path):
                policies.append(path)
    crx = _p(root, os.path.join(INSTALL_DIR, CRX_NAME))
    return {
        "enabled": bool(policies) and os.path.exists(crx),
        "mode": state.get("mode"),
        "extension_id": state.get("extension_id") or (extension_id(_p(root, DEVICE_KEY)) if os.path.isfile(_p(root, DEVICE_KEY)) else None),
        "version": state.get("version"),
        "browsers": state.get("browsers", []),
        "policies": policies,
        "crx": crx if os.path.exists(crx) else None,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(prog="devos-modesty", description="DevOS Modesty filter (browser image/video blur)")
    ap.add_argument("--root", default=os.environ.get("DEVOS_MODESTY_ROOT", "/"), help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    en = sub.add_parser("enable", help="turn the filter on for all users (locked)")
    en.add_argument("--mode", choices=MODES, default="women",
                    help="women: blur detected adult women body regions (default); people: blur detected person regions")
    en.add_argument("--keep-incognito", action="store_true",
                    help="do not disable Incognito and Guest windows (they would not be filtered)")
    sub.add_parser("disable", help="turn the filter off and remove it from the browsers")
    st = sub.add_parser("status", help="show whether the filter is on")
    st.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "enable":
            r = enable(args.root, args.mode, not args.keep_incognito)
            print("Modesty filter enabled (mode: %s)." % r["mode"])
            print("Extension %s %s, browsers: %s" % (r["extension_id"], r["version"], ", ".join(r["browsers"])))
            print("Restart the browser (or wait a few minutes) for it to appear.")
        elif args.cmd == "disable":
            disable(args.root)
            print("Modesty filter disabled. The browser removes the extension on its next policy refresh.")
        else:
            s = status(args.root)
            if args.json:
                print(json.dumps(s, indent=2))
            else:
                print("Modesty filter: %s" % ("on (mode: %s)" % s["mode"] if s["enabled"] else "off"))
                print("Extension ID: %s" % s["extension_id"])
                if s["browsers"]:
                    print("Browsers: %s" % ", ".join(s["browsers"]))
    except PermissionError as e:
        print(str(e), file=sys.stderr)
        return 1
    except (RuntimeError, ValueError, OSError) as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
