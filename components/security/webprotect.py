#!/usr/bin/env python3
"""
DevOS Security - web protection (phishing and malware sites).

Two layers, both on by default (devos-security-firstboot.service):

1. DNS. systemd-resolved asks Quad9's threat-blocking resolver for every
   name. Quad9 answers "does not exist" (NXDOMAIN) for domains on its threat
   feeds (malware, phishing, command-and-control).
   Addresses from https://docs.quad9.net/services/ and
   https://quad9.net/service/service-addresses-and-features/ (checked
   2026-10-14): 9.9.9.9, 149.112.112.112, 2620:fe::fe, 2620:fe::9, TLS name
   dns.quad9.net. 9.9.9.10 is the same service *without* blocking.
   Test domain: isitblocked.org. It is not on Quad9's own pages; it is the
   name Quad9 staff and users use to show a block. Checked live 2026-10-14:
   9.9.9.9 -> NXDOMAIN, 9.9.9.10 and 1.1.1.1 -> an address.

   The drop-in is zy-devos-security.conf. Family Safety writes
   zz-devos-familysafe.conf; resolved reads drop-ins in name order and that
   file clears the server lists first, so when Family Safety is on its
   filter wins (CleanBrowsing / Cloudflare for Families block malware and
   phishing too). Turning Family Safety off deletes its file and this one
   applies again. Both files sort after devos.conf (1.1.1.1 / 8.8.8.8).

2. Browsers. A separate managed policy, devos-security.json, next to Family
   Safety's devos-familysafe.json (Chromium merges every file in the folder;
   the two files never set the same key):
     SafeBrowsingProtectionLevel=1   Safe Browsing "standard protection"
     PasswordLeakDetectionEnabled    warn when a saved password leaked
     DownloadRestrictions=4          block downloads Safe Browsing flags as
                                     malicious. Not 1: 1 also blocks whole
                                     "dangerous file types" (danger level
                                     ALLOW_ON_USER_GESTURE), which can stop
                                     ordinary .exe downloads that DevOS runs
                                     through WinLayer.
     SafeBrowsingDeepScanningEnabled let Safe Browsing deep-scan suspicious
                                     downloads (Chrome only)
   Edge uses SmartScreen instead. Firefox gets its Safe Browsing prefs
   (phishing, malware, downloads) set and locked through policies.json,
   merged with whatever is there (Family Safety's keys are kept).

Limits: DNS blocking only knows domains on threat lists; a brand-new
phishing site can work for hours. A browser or app that uses its own
DNS-over-HTTPS skips layer 1 (Chrome's "secure DNS" in automatic mode
upgrades to Quad9's own DoH, which blocks the same domains).
"""

import json
import os
import socket
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import seccommon as common  # noqa: E402

QUAD9 = ("9.9.9.9", "149.112.112.112", "2620:fe::fe", "2620:fe::9")
QUAD9_TLS_NAME = "dns.quad9.net"
TEST_BLOCKED = "isitblocked.org"
TEST_CONTROL = "example.com"

DROPIN_DIR = "/etc/systemd/resolved.conf.d"
DROPIN = DROPIN_DIR + "/zy-devos-security.conf"
FAMILYSAFE_DROPIN = DROPIN_DIR + "/zz-devos-familysafe.conf"
DISPATCHER = "/etc/NetworkManager/dispatcher.d/99-devos-dns-security"

POLICY_NAME = "devos-security.json"
FAMILYSAFE_POLICY_NAME = "devos-familysafe.json"
CHROMIUM_DIRS = {
    "chrome": "/etc/opt/chrome/policies/managed",
    "edge": "/etc/opt/edge/policies/managed",
    "brave": "/etc/brave/policies/managed",
    "chromium": "/etc/chromium/policies/managed",
    "chromium-browser": "/etc/chromium-browser/policies/managed",
}
FIREFOX_POLICIES = "/etc/firefox/policies/policies.json"

FIREFOX_PREFS = {
    "browser.safebrowsing.malware.enabled": True,
    "browser.safebrowsing.phishing.enabled": True,
    "browser.safebrowsing.downloads.enabled": True,
    "browser.safebrowsing.downloads.remote.block_dangerous": True,
    "browser.safebrowsing.downloads.remote.block_potentially_unwanted": True,
    # Show the real punycode name, so a look-alike letter cannot hide in the address bar.
    "network.IDN_show_punycode": True,
}


def resolved_dropin():
    servers = " ".join("%s#%s" % (ip, QUAD9_TLS_NAME) for ip in QUAD9)
    return """# DevOS Security: web protection (phishing and malware sites).
# Written by "devos-security web on"; "devos-security web off" deletes it.
#
# Quad9 9.9.9.9 / 149.112.112.112 / 2620:fe::fe / 2620:fe::9 answer
# "does not exist" for domains on its threat feeds (docs.quad9.net/services).
# "#dns.quad9.net" is the TLS server name for DNS-over-TLS.
#
# The name sorts after devos.conf (so these replace 1.1.1.1 / 8.8.8.8) and
# before zz-devos-familysafe.conf: when Family Safety is on, its family
# filter (which blocks malware and phishing as well) wins.
# DNS= and FallbackDNS= are lists: an empty assignment clears what earlier
# files added. Domains=~. sends every name to these servers instead of the
# router's or the per-link servers set by 99-devos-dns.
[Resolve]
DNS=
DNS={servers}
FallbackDNS=
FallbackDNS={servers}
Domains=
Domains=~.
# Encrypt lookups when the network allows port 853; plain DNS otherwise.
DNSOverTLS=opportunistic
""".format(servers=servers)


def chromium_policy(browser="chrome"):
    if browser == "edge":
        return {
            "SmartScreenEnabled": True,
            "SmartScreenPuaEnabled": True,
            "SmartScreenForTrustedDownloadsEnabled": True,
            "DownloadRestrictions": 4,             # 4 = block malicious downloads
            "PasswordMonitorAllowed": True,
            "PreventSmartScreenPromptOverride": True,
            "PreventSmartScreenPromptOverrideForFiles": True,
        }
    policy = {
        "SafeBrowsingProtectionLevel": 1,      # 1 = standard protection
        "PasswordLeakDetectionEnabled": True,
        "DownloadRestrictions": 4,             # 4 = block malicious downloads
        # No "visit this dangerous site anyway" button. Family Safety does not set this key.
        "DisableSafeBrowsingProceedAnyway": True,
    }
    if browser == "chrome":
        policy["SafeBrowsingDeepScanningEnabled"] = True
    return policy


def firefox_policies(existing=None):
    """Merge our Safe Browsing prefs into an existing policies.json."""
    data = dict(existing or {})
    policies = dict(data.get("policies") or {})
    prefs = dict(policies.get("Preferences") or {})
    for name, value in FIREFOX_PREFS.items():
        prefs[name] = {"Value": value, "Status": "locked"}
    policies["Preferences"] = prefs
    data["policies"] = policies
    return data


def firefox_has_ours(data):
    try:
        prefs = data["policies"]["Preferences"]
        return all(prefs.get(k, {}).get("Value") is v for k, v in FIREFOX_PREFS.items())
    except (KeyError, TypeError, AttributeError):
        return False


def strip_firefox(data):
    data = dict(data or {})
    policies = dict(data.get("policies") or {})
    prefs = {k: v for k, v in (policies.get("Preferences") or {}).items() if k not in FIREFOX_PREFS}
    if prefs:
        policies["Preferences"] = prefs
    else:
        policies.pop("Preferences", None)
    data["policies"] = policies
    return data


class WebProtect(object):
    def __init__(self, root="/", runner=None, live=None):
        self.root = root
        self.runner = runner or (lambda cmd: common.run(cmd, timeout=60)[0])
        self.live = (root == "/") if live is None else live

    def p(self, path):
        return path if self.root == "/" else os.path.join(self.root, path.lstrip("/"))

    def files(self):
        out = [(DROPIN, resolved_dropin())]
        for browser, folder in CHROMIUM_DIRS.items():
            out.append((folder + "/" + POLICY_NAME, json.dumps(chromium_policy(browser), indent=2) + "\n"))
        return out

    def firefox_text(self):
        existing = common.read_json(self.p(FIREFOX_POLICIES), {}) or {}
        return json.dumps(firefox_policies(existing), indent=2) + "\n"

    def enabled(self):
        return os.path.exists(self.p(DROPIN))

    def familysafe_on(self):
        return os.path.exists(self.p(FAMILYSAFE_DROPIN))

    def enable(self):
        for path, text in self.files():
            if common.read_text(self.p(path)) != text:
                common.write_text(self.p(path), text, 0o644)
        current = common.read_json(self.p(FIREFOX_POLICIES), {}) or {}
        if not firefox_has_ours(current):
            common.write_text(self.p(FIREFOX_POLICIES), self.firefox_text(), 0o644)
        self.reload()
        return 0

    def repair(self):
        """Boot: put back files someone (or Family Safety's restore) removed."""
        return self.enable() if self.enabled() else 0

    def disable(self):
        for path, _text in self.files():
            try:
                os.remove(self.p(path))
            except FileNotFoundError:
                pass
        current = common.read_json(self.p(FIREFOX_POLICIES))
        if isinstance(current, dict) and firefox_has_ours(current):
            stripped = strip_firefox(current)
            if stripped.get("policies"):
                common.write_text(self.p(FIREFOX_POLICIES), json.dumps(stripped, indent=2) + "\n", 0o644)
            else:
                os.remove(self.p(FIREFOX_POLICIES))
        self.reload()
        return 0

    def reload(self):
        if not self.live:
            return
        self.runner(["systemctl", "try-restart", "systemd-resolved.service"])
        if not self.familysafe_on() and self.enabled() and common.which("nmcli"):
            # Re-run the dispatcher for links that are already up.
            _c, out = common.run(["nmcli", "-t", "-f", "DEVICE,STATE", "device"], timeout=10)
            for line in out.splitlines():
                dev, _sep, state = line.partition(":")
                if state.startswith("connected") and dev and dev != "lo":
                    self.runner(["/bin/bash", DISPATCHER, dev, "up"])
        self.runner(["resolvectl", "flush-caches"])

    def status(self, check=True, resolver=None):
        on = self.enabled()
        familysafe = self.familysafe_on()
        result = {
            "enabled": on, "familysafe_active": familysafe,
            "provider": "Family Safety filter" if familysafe else ("Quad9" if on else None),
            "browser_policies": all(os.path.exists(self.p(f + "/" + POLICY_NAME))
                                    for f in CHROMIUM_DIRS.values()) if on else False,
            "firefox_policy": firefox_has_ours(common.read_json(self.p(FIREFOX_POLICIES), {}) or {}),
            "test_domain": TEST_BLOCKED, "test_blocked": None,
        }
        if check and (on or familysafe):
            blocked = lookup(TEST_BLOCKED, resolver)
            if blocked is not None:
                result["test_blocked"] = blocked == []
        return result


def lookup(name, resolver=None, timeout=4.0):
    """Addresses for name; [] = does not exist / blocked; None = no answer."""
    if resolver:
        return resolver(name)
    box = {}

    def work():
        try:
            box["v"] = sorted({a[4][0] for a in socket.getaddrinfo(name, 443, proto=socket.IPPROTO_TCP)})
        except socket.gaierror as exc:
            box["v"] = [] if exc.errno in (getattr(socket, "EAI_NONAME", -2), -2, -5, 11001) else None
        except OSError:
            box["v"] = None

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    value = box.get("v")
    if value and set(value) <= {"0.0.0.0", "::"}:
        return []
    return value
