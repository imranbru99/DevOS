#!/usr/bin/env python3
"""
devos-familysafe: Family Safety, opt-in adult-content blocking for the whole PC.

  devos-familysafe enable [--level family|strict]   turn it on or change level (root)
  devos-familysafe disable                          turn it off, put every file back (root)
  devos-familysafe status [--no-check]              JSON; no root needed
  devos-familysafe apply                            run at boot by devos-familysafe.service (root)
  devos-familysafe gui                              the Family Safety window

How it works (each layer covers a gap in the one before it):

1. DNS. systemd-resolved sends every lookup to a family filter (CleanBrowsing,
   Cloudflare for Families). Those answer "does not exist" for adult sites and
   point google.com / bing.com (and, at "strict", youtube.com) at their
   SafeSearch / Restricted Mode addresses. This covers every browser and app.
2. Bypass protection. An nftables table refuses plain DNS (53), DNS-over-TLS
   and DNS-over-QUIC (853) to any other server and DNS-over-HTTPS (443) to the
   big public resolvers, so an app or a router setting cannot route around (1).
3. Browser policies. Chrome / Edge / Brave / Chromium and Firefox get locked
   policies: their own DNS-over-HTTPS off, SafeSearch and YouTube Restricted
   Mode forced, private/incognito windows off (DNS still filters there, but
   nobody can see the history afterwards).
4. "strict" adds a local list of known adult domains (StevenBlack hosts,
   porn-only, MIT licence) in /etc/hosts, used by resolved before any server.

Only an administrator can change any of this (pkexec asks for an administrator
password). A child should use a separate standard account; if the
administrator account has no password, pkexec accepts an empty one and the
child could turn it off, so the window warns about that.

Turning it off restores every file it replaced (backups in
/var/lib/DevOS/familysafe/backup) and deletes every file it created.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

# ---------------------------------------------------------------- name servers
#
# CleanBrowsing, https://cleanbrowsing.org/filters/ (checked 2026-10-14):
#   Family Filter 185.228.168.168, 185.228.169.168, 2a0d:2a00:1::, 2a0d:2a00:2::
#     adult + explicit sites, proxy and VPN domains used to get around filters,
#     mixed-content sites (e.g. Reddit), malware/phishing; Google, Bing and
#     YouTube are put in safe mode (a live lookup of www.youtube.com answers
#     216.239.38.119 = restrict.youtube.com, Strict Restricted Mode).
#   Adult Filter 185.228.168.10, 185.228.169.11, 2a0d:2a00:1::1, 2a0d:2a00:2::1
#     adult + explicit sites, malware/phishing, Google and Bing SafeSearch
#     (www.google.com answers 216.239.38.120 = forcesafesearch.google.com);
#     does NOT block proxies/VPNs or mixed content, YouTube is left alone.
# Cloudflare for Families, https://developers.cloudflare.com/1.1.1.1/setup/
# (checked 2026-10-14): malware + adult content 1.1.1.3, 1.0.0.3,
#   2606:4700:4700::1113, 2606:4700:4700::1003. Blocked names answer 0.0.0.0;
#   a live lookup showed Google SafeSearch enforced too (not documented there).
CLEANBROWSING_FAMILY = ("185.228.168.168", "185.228.169.168", "2a0d:2a00:1::", "2a0d:2a00:2::")
CLEANBROWSING_ADULT = ("185.228.168.10", "185.228.169.11", "2a0d:2a00:1::1", "2a0d:2a00:2::1")
CLOUDFLARE_FAMILIES = ("1.1.1.3", "1.0.0.3", "2606:4700:4700::1113", "2606:4700:4700::1003")

# "family" keeps Cloudflare as a second provider so the PC still resolves if
# CleanBrowsing is down. "strict" stays on CleanBrowsing's Family Filter only,
# because Cloudflare does not block proxies/VPNs or restrict YouTube and
# resolved keeps using whichever server answered last.
LEVELS = {
    "family": {
        "name": "Family",
        "about": "Adult sites blocked, SafeSearch on Google and Bing, YouTube Restricted Mode "
                 "(moderate) in Chrome, Edge and Brave.",
        "dns": CLEANBROWSING_ADULT + CLOUDFLARE_FAMILIES,
        "youtube": 1,  # ForceYouTubeRestrict: 1 = moderate
        "hosts_list": False,
    },
    "strict": {
        "name": "Strict",
        "about": "Also blocks proxy and VPN sites and mixed-content sites, YouTube Strict "
                 "Restricted Mode for every app, plus a local list of ~77,000 adult domains.",
        "dns": CLEANBROWSING_FAMILY,
        "youtube": 2,  # 2 = strict
        "hosts_list": True,
    },
}
DEFAULT_LEVEL = "family"

# DNS-over-HTTPS by IP: the resolvers browsers and apps ship as presets. A
# short list on purpose; DoH to anything else still needs a host name, and
# those are answered 0.0.0.0 below (DOH_HOSTS) and by the filters' own
# proxy category at "strict". Sources: each provider's public DNS page.
DOH_V4 = (
    "8.8.8.8", "8.8.4.4",                    # Google Public DNS (dns.google)
    "1.1.1.1", "1.0.0.1",                    # Cloudflare (unfiltered)
    "9.9.9.9", "149.112.112.112",            # Quad9
    "208.67.222.222", "208.67.220.220",      # OpenDNS / Cisco Umbrella
    "94.140.14.14", "94.140.15.15",          # AdGuard DNS
)
DOH_V6 = (
    "2001:4860:4860::8888", "2001:4860:4860::8844",
    "2606:4700:4700::1111", "2606:4700:4700::1001",
    "2620:fe::fe", "2620:fe::9",
    "2620:119:35::35", "2620:119:53::53",
    "2a10:50c0::ad1:ff", "2a10:50c0::ad2:ff",
)
# DoH host names (Cloudflare's DoH front ends sit on shared CDN addresses, so
# they are blocked by name, not by IP). family.cloudflare-dns.com and
# doh.cleanbrowsing.org stay reachable: they filter too.
DOH_HOSTS = (
    "dns.google", "dns.google.com", "8888.google",
    "cloudflare-dns.com", "mozilla.cloudflare-dns.com", "chrome.cloudflare-dns.com",
    "one.one.one.one", "1dot1dot1dot1.cloudflare-dns.com", "security.cloudflare-dns.com",
    "dns.quad9.net", "dns9.quad9.net", "dns10.quad9.net", "dns11.quad9.net",
    "doh.opendns.com", "dns.adguard-dns.com", "dns.adguard.com", "unfiltered.adguard-dns.com",
    "dns.nextdns.io", "doh.mullvad.net", "dns.mullvad.net", "doh.libredns.gr",
)

# StevenBlack/hosts, MIT licence (https://github.com/StevenBlack/hosts,
# license.txt). "porn-only" is the adult list alone (~77k domains) without
# the ad/malware lists of the "porn" variant (~149k), which would block ad
# networks and break some sites; ads are not what Family Safety is for.
HOSTS_LIST_URL = "https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/porn-only/hosts"
HOSTS_LIST_MAX = 16 * 1024 * 1024

# CleanBrowsing's own verification guide uses pornhub.com as the blocked
# example (https://cleanbrowsing.org/learn/verify-dns-configuration): every
# level and Cloudflare for Families answer NXDOMAIN or 0.0.0.0 for it.
TEST_BLOCKED = "pornhub.com"
TEST_CONTROL = "example.com"
SAFESEARCH_IPS = {"216.239.38.120", "2001:4860:4802:32::78"}  # forcesafesearch.google.com
BLOCK_ANSWERS = {"0.0.0.0", "::", "127.0.0.1", "::1"}

# ---------------------------------------------------------------- files

STATE_FILE = "/etc/devos/familysafe.conf"
DATA_DIR = "/var/lib/DevOS/familysafe"
BACKUP_DIR = DATA_DIR + "/backup"
MANIFEST = BACKUP_DIR + "/manifest.json"
HOSTS_CACHE = DATA_DIR + "/porn-only.hosts"
LOG_FILE = "/var/log/devos-familysafe.log"

# "zz-" sorts after devos.conf, so these values win (see resolved_dropin()).
RESOLVED_DROPIN = "/etc/systemd/resolved.conf.d/zz-devos-familysafe.conf"
# NetworkManager runs dispatcher scripts in name order: this one runs right
# after 99-devos-dns and replaces the per-link servers it just set.
DISPATCHER = "/etc/NetworkManager/dispatcher.d/99-devos-familysafe"
DEVOS_DISPATCHER = "/etc/NetworkManager/dispatcher.d/99-devos-dns"
NFT_FILE = "/etc/devos/familysafe.nft"
NFT_TABLE = "devos_familysafe"
HOSTS = "/etc/hosts"
HOSTS_BEGIN = "# >>> DevOS Family Safety (managed: turn it off in Family Safety) >>>"
HOSTS_END = "# <<< DevOS Family Safety <<<"
SERVICE = "devos-familysafe.service"
SERVICE_UNIT = "/etc/systemd/system/" + SERVICE
SERVICE_LINK = "/etc/systemd/system/multi-user.target.wants/" + SERVICE
AUTOLOGIN = "/etc/sddm.conf.d/zz-devos-autologin.conf"  # devos-install-finalize: no password
CLI = "/usr/local/bin/devos-familysafe"

POLICY_NAME = "devos-familysafe.json"
# Chromium-family managed policy folders. Files in "managed" are merged by
# the browser, so ours sits next to anything else an admin put there.
# Written even when the browser is not installed yet, so a browser added
# later is covered from its first start.
CHROMIUM_DIRS = {
    "chrome": "/etc/opt/chrome/policies/managed",          # Google Chrome .deb
    "edge": "/etc/opt/edge/policies/managed",              # Microsoft Edge .deb
    # Brave .deb; the Flathub com.brave.Browser has host-etc access and its
    # launcher links /etc/brave/policies in (Flathub forum, thread 9304).
    "brave": "/etc/brave/policies/managed",
    "chromium": "/etc/chromium/policies/managed",          # Debian-style chromium
    "chromium-browser": "/etc/chromium-browser/policies/managed",
}
FIREFOX_POLICIES = "/etc/firefox/policies/policies.json"
# Flathub org.mozilla.firefox reads system policies from its "systemconfig"
# extension point (Mozilla bug 1814897, Firefox 115+).
FIREFOX_FLATPAK_POLICIES = ("/var/lib/flatpak/extension/org.mozilla.firefox.systemconfig/"
                            "x86_64/stable/policies/policies.json")


def log(message: str) -> None:
    print(message, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")
    except OSError:
        pass


def default_runner(cmd, timeout=120) -> int:
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              timeout=timeout, env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"))
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"  {cmd[0]}: {exc}")
        return 1
    if proc.returncode:
        for line in (proc.stdout or "").strip().splitlines()[-3:]:
            log("  " + line)
    return proc.returncode


# ---------------------------------------------------------------- generated text

def split_ips(servers):
    return [s for s in servers if ":" not in s], [s for s in servers if ":" in s]


def resolved_dropin(level: str) -> str:
    servers = " ".join(LEVELS[level]["dns"])
    return f"""# DevOS Family Safety ({LEVELS[level]['name']}). Written by devos-familysafe;
# turning Family Safety off deletes this file and devos.conf applies again.
#
# DNS=, FallbackDNS= and Domains= are lists: a later drop-in adds to the
# lists of earlier ones and an empty assignment clears them. Clear first so
# 1.1.1.1 / 8.8.8.8 from devos.conf are not used next to the filter.
#
# Domains=~. puts the global servers in charge of every name. resolved
# routes a lookup to the scope with the longest matching routing domain;
# links that only have DefaultRoute=yes (the router's DNS from DHCP, the
# servers 99-devos-dns and devos-bring-up-network set) match nothing, so
# they are not asked. A link that also carries "~." would be asked in
# parallel: 99-devos-familysafe sets those links to the same servers, and
# the nftables table refuses any other DNS server anyway.
[Resolve]
DNS=
DNS={servers}
FallbackDNS=
FallbackDNS={servers}
Domains=
Domains=~.
# Plain DNS to the filter: resolved's opportunistic DoT could fall back to
# servers it learns elsewhere; port 853 to the filter is allowed regardless.
DNSOverTLS=no
# /etc/hosts carries the DoH names (and the "strict" list); resolved answers
# from it before asking any server.
ReadEtcHosts=yes
"""


def dispatcher_script(level: str) -> str:
    servers = " ".join(LEVELS[level]["dns"])
    return f"""#!/bin/bash
# DevOS Family Safety ({LEVELS[level]['name']}). Written by devos-familysafe and
# deleted when Family Safety is turned off.
# NetworkManager runs dispatcher scripts in name order, so this runs right
# after 99-devos-dns and replaces the per-link name servers it set (the
# router's DNS and public resolvers) with the family filter.
iface="$1"
action="$2"
case "$action" in
    up|dhcp4-change|dhcp6-change|connectivity-change) ;;
    *) exit 0 ;;
esac
[ -n "$iface" ] && [ "$iface" != "none" ] || exit 0
command -v resolvectl >/dev/null 2>&1 || exit 0
resolvectl dns "$iface" {servers} >/dev/null 2>&1 || true
exit 0
"""


def _elements(items) -> str:
    return ", ".join(items)


def nft_ruleset(level: str) -> str:
    v4, v6 = split_ips(LEVELS[level]["dns"])
    return f"""#!/usr/sbin/nft -f
# DevOS Family Safety ({LEVELS[level]['name']}): keep name lookups on the family filter.
# Loaded by devos-familysafe.service at boot; "devos-familysafe disable"
# deletes the table. Only this table is touched: ufw's and Docker's tables
# stay as they are, and a packet must pass every table, so a reject here holds.
#
# Declaring then deleting the table makes the load an atomic replace.
table inet {NFT_TABLE}
delete table inet {NFT_TABLE}

table inet {NFT_TABLE} {{
\tset family_dns4 {{
\t\ttype ipv4_addr
\t\telements = {{ {_elements(v4)} }}
\t}}
\tset family_dns6 {{
\t\ttype ipv6_addr
\t\telements = {{ {_elements(v6)} }}
\t}}
\tset doh4 {{
\t\ttype ipv4_addr
\t\telements = {{ {_elements(DOH_V4)} }}
\t}}
\tset doh6 {{
\t\ttype ipv6_addr
\t\telements = {{ {_elements(DOH_V6)} }}
\t}}

\tchain guard {{
\t\t# DNS (53), DNS-over-TLS and DNS-over-QUIC (853): only the family servers.
\t\tmeta l4proto {{ tcp, udp }} th dport {{ 53, 853 }} ip daddr @family_dns4 accept
\t\tmeta l4proto {{ tcp, udp }} th dport {{ 53, 853 }} ip6 daddr @family_dns6 accept
\t\tmeta l4proto tcp th dport {{ 53, 853 }} counter reject with tcp reset
\t\tmeta l4proto udp th dport {{ 53, 853 }} counter reject
\t\t# DNS-over-HTTPS (and HTTP/3) to the well-known public resolvers.
\t\tip daddr @doh4 meta l4proto tcp th dport 443 counter reject with tcp reset
\t\tip daddr @doh4 meta l4proto udp th dport 443 counter reject
\t\tip6 daddr @doh6 meta l4proto tcp th dport 443 counter reject with tcp reset
\t\tip6 daddr @doh6 meta l4proto udp th dport 443 counter reject
\t}}

\tchain output {{
\t\ttype filter hook output priority filter; policy accept;
\t\t# 127.0.0.53 (resolved's stub) and other local services.
\t\toifname "lo" accept
\t\tjump guard
\t}}

\t# Containers and VMs behind this PC (Docker, Waydroid, libvirt) too.
\tchain forward {{
\t\ttype filter hook forward priority filter; policy accept;
\t\tjump guard
\t}}
}}
"""


def chromium_policy(level: str, browser: str = "chrome") -> dict:
    policy = {
        # Chrome would otherwise upgrade to (or be set to) its own DoH server
        # and skip the system resolver.
        "DnsOverHttpsMode": "off",
        "ForceGoogleSafeSearch": True,
        "ForceYouTubeRestrict": LEVELS[level]["youtube"],
        "IncognitoModeAvailability": 1,  # 1 = incognito not available
        "BrowserGuestModeEnabled": False,
        "BrowserAddPersonEnabled": False,  # a fresh profile would have no history either
    }
    if browser == "edge":
        policy.update({
            "ForceBingSafeSearch": 2,       # 2 = strict
            "InPrivateModeAvailability": 1,  # Edge's name for incognito
        })
    if browser == "brave":
        # Brave's "Private window with Tor" sends lookups through Tor.
        policy.update({"TorDisabled": True, "BraveVPNDisabled": True})
    return policy


def firefox_policies(existing: dict = None) -> dict:
    """Our policies merged into an existing policies.json (ours win)."""
    data = dict(existing or {})
    policies = dict(data.get("policies") or {})
    policies.update({
        # Firefox's TRR (DoH to Cloudflare by default) would skip the filter.
        "DNSOverHTTPS": {"Enabled": False, "Locked": True},
        "DisablePrivateBrowsing": True,
    })
    data["policies"] = policies
    return data


def hosts_block(level: str, extra_domains=()) -> str:
    lines = [HOSTS_BEGIN, "# DNS-over-HTTPS servers that would skip the family filter:"]
    lines += [f"0.0.0.0 {name}" for name in DOH_HOSTS]
    if extra_domains:
        lines.append("# Adult sites: StevenBlack/hosts porn-only list (MIT licence).")
        lines += [f"0.0.0.0 {name}" for name in extra_domains]
    lines.append(HOSTS_END)
    return "\n".join(lines) + "\n"


def strip_hosts_block(text: str) -> str:
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        if line.strip() == HOSTS_BEGIN:
            skipping = True
        elif line.strip() == HOSTS_END and skipping:
            skipping = False
        elif not skipping:
            out.append(line)
    return "".join(out)


_HOST_LINE = re.compile(r"^0\.0\.0\.0[ \t]+([a-z0-9][a-z0-9.-]*[a-z0-9])[ \t]*(?:#.*)?$")


def parse_hosts_list(text: str):
    """Domains from a StevenBlack-style list. Anything that is not a plain
    "0.0.0.0 name" line is ignored, so a tampered download cannot redirect
    a name to a real address."""
    seen, names = set(), []
    for line in text.splitlines():
        match = _HOST_LINE.match(line.strip().lower())
        if not match:
            continue
        name = match.group(1)
        if "." not in name or ".." in name or name in seen or name in ("0.0.0.0", "localhost"):
            continue
        seen.add(name)
        names.append(name)
    return names


def render_state(values: dict) -> str:
    lines = ["# DevOS Family Safety. Change it in the Family Safety window (needs an administrator)."]
    lines += [f"{key}={values[key]}" for key in sorted(values)]
    return "\n".join(lines) + "\n"


def parse_state(text: str) -> dict:
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


# ---------------------------------------------------------------- accounts

def admin_users(group_text: str):
    users = set()
    for line in group_text.splitlines():
        parts = line.split(":")
        if len(parts) >= 4 and parts[0] in ("sudo", "admin", "wheel"):
            users.update(u for u in parts[3].split(",") if u)
    return users


def empty_password(hash_field: str) -> bool:
    """True when the account signs in with an empty password ("" or a hash
    of ""). "!"/"*" are locked accounts: those cannot authenticate at all."""
    if hash_field == "":
        return True
    if hash_field.startswith(("!", "*")):
        return False
    try:
        import warnings
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        try:
            import crypt
        except ImportError:  # Python 3.13+: Ubuntu ships the standalone module.
            import legacycrypt as crypt
        return crypt.crypt("", hash_field) == hash_field
    except Exception:
        return False


def passwordless_admins(shadow_text: str, group_text: str):
    admins = admin_users(group_text)
    found = []
    for line in shadow_text.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[0] in admins and empty_password(parts[1]):
            found.append(parts[0])
    return sorted(found)


# ---------------------------------------------------------------- status

def lookup(name: str, resolver=None):
    """Addresses for `name` through the system resolver (resolved's stub,
    /etc/hosts). [] = does not exist; None = lookup failed for another reason."""
    resolver = resolver or socket.getaddrinfo
    try:
        infos = resolver(name, 443, 0, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        if exc.errno in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -5)):
            return []
        return None
    except OSError:
        return None
    return sorted({info[4][0] for info in infos})


def is_blocked(answer) -> bool:
    return answer == [] or (bool(answer) and set(answer) <= BLOCK_ANSWERS)


def judge(enabled: bool, blocked_answer, control_answer):
    """-> (state, protected). state: off | protected | not_protected | offline."""
    if not enabled:
        return "off", False
    if not control_answer or is_blocked(control_answer):
        return "offline", None  # cannot tell: no working DNS at all
    if is_blocked(blocked_answer):
        return "protected", True
    return "not_protected", False


# ---------------------------------------------------------------- engine

class FamilySafe:
    """Every path goes through self.p(), so tests run the whole engine on a
    temporary folder with a fake command runner."""

    def __init__(self, root="/", runner=None, which=None, fetch=None, live=None):
        self.root = root
        self.runner = runner or default_runner
        self.which = which or shutil.which
        self.fetch = fetch or self._download
        # Only touch the running system (nft, resolved, links) on the real root.
        self.live = (root == "/") if live is None else live

    def p(self, path: str) -> str:
        return path if self.root == "/" else os.path.join(self.root, path.lstrip("/"))

    # -- small file helpers
    def read(self, path: str, default=None):
        try:
            with open(self.p(path), encoding="utf-8") as handle:
                return handle.read()
        except (OSError, UnicodeDecodeError):
            return default

    def write(self, path: str, text: str, mode: int = 0o644) -> None:
        full = self.p(path)
        self._makedirs(os.path.dirname(path))
        tmp = full + ".devos-new"
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        try:
            os.replace(tmp, full)
        except OSError:
            # A bind-mounted file (/etc/hosts in a container) cannot be
            # replaced, only rewritten in place.
            os.remove(tmp)
            with open(full, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)

    def _makedirs(self, path: str) -> None:
        missing = []
        while path not in ("", "/") and not os.path.isdir(self.p(path)):
            missing.append(path)
            path = os.path.dirname(path)
        for folder in reversed(missing):
            os.makedirs(self.p(folder), exist_ok=True)
            manifest = self.manifest()
            if folder not in manifest["dirs"]:
                manifest["dirs"].append(folder)
                self.save_manifest(manifest)

    # -- backups
    def manifest(self) -> dict:
        try:
            data = json.loads(self.read(MANIFEST, "") or "{}")
        except ValueError:
            data = {}
        data.setdefault("files", {})
        data.setdefault("dirs", [])
        return data

    def save_manifest(self, data: dict) -> None:
        folder = BACKUP_DIR
        while folder not in ("", "/") and not os.path.isdir(self.p(folder)):
            if folder not in data["dirs"]:
                data["dirs"].append(folder)  # created by us: removed on disable
            folder = os.path.dirname(folder)
        os.makedirs(self.p(BACKUP_DIR), exist_ok=True)
        with open(self.p(MANIFEST), "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=1)

    def backup(self, path: str) -> None:
        """Remember how `path` was before the first change (once)."""
        manifest = self.manifest()
        if path in manifest["files"]:
            return
        existed = os.path.lexists(self.p(path))
        if existed:
            self.save_manifest(manifest)  # creates (and records) the backup folder
            shutil.copy2(self.p(path), self.p(BACKUP_DIR + "/" + path.strip("/").replace("/", "%")))
        manifest = self.manifest()  # _makedirs may have saved it
        manifest["files"][path] = existed
        self.save_manifest(manifest)

    def put(self, path: str, text: str, mode: int = 0o644) -> None:
        self.backup(path)
        self.write(path, text, mode)

    # -- state
    def state(self) -> dict:
        return parse_state(self.read(STATE_FILE, "") or "")

    def enabled(self) -> bool:
        return self.state().get("enabled") == "1"

    # -- pieces
    def policy_files(self, level: str):
        """(path, text) for every browser policy file."""
        files = []
        for browser, folder in CHROMIUM_DIRS.items():
            files.append((folder + "/" + POLICY_NAME,
                          json.dumps(chromium_policy(level, browser), indent=2) + "\n"))
        targets = [FIREFOX_POLICIES]
        if os.path.isdir(self.p("/var/lib/flatpak")):
            targets.append(FIREFOX_FLATPAK_POLICIES)
        for path in targets:
            manifest = self.manifest()
            # Merge with what was there before we first touched it, not with
            # our own earlier copy.
            if path in manifest["files"]:
                before = self.read(BACKUP_DIR + "/" + path.strip("/").replace("/", "%"), "") \
                    if manifest["files"][path] else ""
            else:
                before = self.read(path, "")
            try:
                existing = json.loads(before) if before and before.strip() else {}
            except ValueError:
                existing = {}
            files.append((path, json.dumps(firefox_policies(existing), indent=2) + "\n"))
        return files

    def adult_list(self, refresh: bool):
        if refresh:
            try:
                text = self.fetch(HOSTS_LIST_URL)
                names = parse_hosts_list(text)
                if len(names) > 1000:  # a real list, not an error page
                    self.write(HOSTS_CACHE, "\n".join(names) + "\n")
                    return names
                log("The adult-site list download looked wrong; using the saved copy.")
            except Exception as exc:  # offline, HTTP error, too big
                log(f"Could not download the adult-site list ({exc}); using the saved copy.")
        cached = self.read(HOSTS_CACHE, "")
        return [line for line in (cached or "").splitlines() if line]

    @staticmethod
    def _download(url: str) -> str:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = resp.read(HOSTS_LIST_MAX + 1)
        if len(data) > HOSTS_LIST_MAX:
            raise ValueError("list too large")
        return data.decode("utf-8", errors="replace")

    def write_hosts(self, block: str) -> None:
        self.backup(HOSTS)
        current = self.read(HOSTS, "") or "127.0.0.1 localhost\n"
        base = strip_hosts_block(current)
        if base and not base.endswith("\n"):
            base += "\n"
        self.write(HOSTS, base + block)

    def links(self):
        try:
            return sorted(n for n in os.listdir(self.p("/sys/class/net")) if n != "lo")
        except OSError:
            return []

    def ensure_nft(self) -> bool:
        if self.which("nft"):
            return True
        if not self.live:
            return False
        log("Installing nftables (bypass protection)…")
        self.runner(["apt-get", "update"], 600)
        self.runner(["apt-get", "install", "-y", "--no-install-recommends", "nftables"], 900)
        return bool(self.which("nft"))

    # -- commands
    def enable(self, level: str = DEFAULT_LEVEL, refresh_list: bool = True) -> int:
        if level not in LEVELS:
            raise ValueError(f"unknown level {level!r}")
        log(f"Turning on Family Safety ({LEVELS[level]['name']})…")
        warnings = []

        self.put(RESOLVED_DROPIN, resolved_dropin(level))
        self.put(DISPATCHER, dispatcher_script(level), 0o755)
        self.put(NFT_FILE, nft_ruleset(level), 0o600)
        for path, text in self.policy_files(level):
            self.put(path, text)

        names = self.adult_list(refresh_list) if LEVELS[level]["hosts_list"] else []
        if LEVELS[level]["hosts_list"] and not names:
            warnings.append("The extra adult-site list could not be downloaded; the DNS filter still "
                            "blocks adult sites. Turn Strict on again when online to add it.")
        self.write_hosts(hosts_block(level, names))

        shadow = self.read("/etc/shadow", "") or ""
        group = self.read("/etc/group", "") or ""
        open_admins = passwordless_admins(shadow, group)
        if open_admins:
            warnings.append("No password on administrator account(s) " + ", ".join(open_admins) +
                            ": anyone at this PC can turn Family Safety off. Set a password.")

        nft_ok = self.ensure_nft()
        if not nft_ok:
            warnings.append("nftables is not installed, so apps that use their own DNS server are "
                            "not stopped. Connect to the internet and turn Family Safety on again.")

        self.backup(SERVICE_LINK)
        self._makedirs(os.path.dirname(SERVICE_LINK))
        if not os.path.lexists(self.p(SERVICE_LINK)):
            try:
                os.symlink(SERVICE_UNIT, self.p(SERVICE_LINK))
            except OSError:  # Windows test runs without symlink rights
                self.write(SERVICE_LINK, "")

        self.write(STATE_FILE, render_state({
            "enabled": "1",
            "level": level,
            "since": datetime.datetime.now().replace(microsecond=0).isoformat(),
            "dns": " ".join(LEVELS[level]["dns"]),
            "hosts_list": str(len(names)),
            "bypass_protection": "1" if nft_ok else "0",
            "passwordless_admins": ",".join(open_admins),
        }))

        if self.live:
            if nft_ok:
                self.runner(["nft", "-f", NFT_FILE])
            self.runner(["systemctl", "daemon-reload"])
            self.runner(["systemctl", "restart", "systemd-resolved"])
            servers = list(LEVELS[level]["dns"])
            for link in self.links():
                self.runner(["resolvectl", "dns", link] + servers)
            self.runner(["resolvectl", "flush-caches"])
        for line in warnings:
            log("Warning: " + line)
        log("Family Safety is on.")
        return 0

    def disable(self) -> int:
        log("Turning off Family Safety…")
        manifest = self.manifest()
        if self.live:
            self.runner(["nft", "delete", "table", "inet", NFT_TABLE])
        for path, existed in sorted(manifest["files"].items()):
            full = self.p(path)
            saved = self.p(BACKUP_DIR + "/" + path.strip("/").replace("/", "%"))
            if path == HOSTS:
                # Keep anything added to /etc/hosts since: drop only our block.
                text = self.read(HOSTS, None)
                if text is not None:
                    self.write(HOSTS, strip_hosts_block(text))
                elif existed and os.path.exists(saved):
                    shutil.copy2(saved, full)
                continue
            if existed and os.path.lexists(saved):
                if os.path.lexists(full):
                    os.remove(full)
                shutil.copy2(saved, full, follow_symlinks=False)
            elif os.path.lexists(full):
                os.remove(full)
        for path in (STATE_FILE, HOSTS_CACHE):
            if os.path.exists(self.p(path)):
                os.remove(self.p(path))
        shutil.rmtree(self.p(BACKUP_DIR), ignore_errors=True)
        for folder in sorted(set(manifest["dirs"]) | {DATA_DIR}, key=len, reverse=True):
            try:
                os.rmdir(self.p(folder))
            except OSError:
                pass  # not empty (someone else uses it) or gone already

        if self.live:
            self.runner(["systemctl", "daemon-reload"])
            self.runner(["systemctl", "restart", "systemd-resolved"])
            # Give every link back the servers DevOS normally publishes.
            if os.path.exists(DEVOS_DISPATCHER):
                for link in self.links():
                    self.runner(["/bin/bash", DEVOS_DISPATCHER, link, "up"])
            self.runner(["resolvectl", "flush-caches"])
        log("Family Safety is off. Every changed file was put back.")
        return 0

    def apply(self) -> int:
        """Boot: load the firewall table and repair removed files."""
        state = self.state()
        if state.get("enabled") != "1":
            return 0
        level = state.get("level") if state.get("level") in LEVELS else DEFAULT_LEVEL
        for path, text, mode in ((RESOLVED_DROPIN, resolved_dropin(level), 0o644),
                                 (DISPATCHER, dispatcher_script(level), 0o755),
                                 (NFT_FILE, nft_ruleset(level), 0o600)):
            if self.read(path) != text:
                self.put(path, text, mode)
        if self.live and self.which("nft"):
            return 0 if self.runner(["nft", "-f", NFT_FILE]) == 0 else 1
        return 0

    def status(self, check: bool = True, resolver=None) -> dict:
        state = self.state()
        enabled = state.get("enabled") == "1"
        level = state.get("level") if state.get("level") in LEVELS else (DEFAULT_LEVEL if enabled else None)
        result = {
            "enabled": enabled,
            "level": level,
            "level_name": LEVELS[level]["name"] if level else None,
            "since": state.get("since"),
            "dns": state.get("dns", "").split() if enabled else [],
            "hosts_list": int(state.get("hosts_list") or 0),
            "bypass_protection": state.get("bypass_protection") == "1",
            "passwordless_admins": [u for u in state.get("passwordless_admins", "").split(",") if u],
            "autologin": os.path.exists(self.p(AUTOLOGIN)),
            "state": "off" if not enabled else "unchecked",
            "protected": None if enabled else False,
            "checks": {},
            "warnings": [],
        }
        if check:
            blocked = lookup(TEST_BLOCKED, resolver)
            control = lookup(TEST_CONTROL, resolver)
            google = lookup("www.google.com", resolver)
            result["state"], result["protected"] = judge(enabled, blocked, control)
            result["checks"] = {
                "test_domain": TEST_BLOCKED,
                "test_domain_blocked": is_blocked(blocked) if blocked is not None else None,
                "internet_dns": bool(control) and not is_blocked(control),
                "google_safesearch": bool(google) and bool(set(google) & SAFESEARCH_IPS),
            }
        if enabled and (result["passwordless_admins"] or result["autologin"]):
            result["warnings"].append("An administrator account has no password, so anyone at this "
                                      "PC can turn Family Safety off. Set a password.")
        if enabled and not result["bypass_protection"]:
            result["warnings"].append("Bypass protection (nftables) is missing.")
        return result


def require_root() -> None:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print("This needs an administrator: run it with pkexec or sudo.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------- window

def gui() -> int:
    from PyQt5 import QtCore, QtWidgets  # lazy: the CLI and tests need no Qt

    style = """
    QWidget { background: #0b0f1a; color: #e2e8f0; font-size: 14px; }
    QLabel#title { font-size: 24px; font-weight: 600; color: #f8fafc; }
    QLabel#muted { color: #94a3b8; }
    QLabel#big { font-size: 30px; font-weight: 700; }
    QFrame#card { background: #0f172a; border: 1px solid #1e293b; border-radius: 14px; }
    QFrame#warn { background: #2a1a06; border: 1px solid #b45309; border-radius: 10px; }
    QPushButton { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 8px 16px; }
    QPushButton#primary { background: #0284c7; border-color: #38bdf8; color: white; }
    QPushButton#danger { background: #3f1d1d; border-color: #b91c1c; color: #fecaca; }
    QPushButton:disabled { color: #64748b; }
    QRadioButton { spacing: 10px; padding: 4px 0; }
    """
    colors = {"protected": "#4ade80", "off": "#94a3b8", "not_protected": "#f87171",
              "offline": "#fbbf24", "unchecked": "#38bdf8"}
    headline = {"protected": "Protected", "off": "Off", "not_protected": "Not protected",
                "offline": "On (can't check: offline)", "unchecked": "On"}

    def cli_cmd(*args):
        if os.path.exists(CLI):
            return CLI, list(args)
        return sys.executable, [os.path.abspath(__file__)] + list(args)

    class Window(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Family Safety")
            self.resize(640, 700)
            self.setStyleSheet(style)
            self.info = {}
            self.proc = None

            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(24, 20, 24, 20)
            layout.setSpacing(12)
            title = QtWidgets.QLabel("Family Safety")
            title.setObjectName("title")
            layout.addWidget(title)
            intro = QtWidgets.QLabel("Blocks known adult sites on this PC for all browsers and apps, "
                                     "for every account. Only an administrator can turn it off.")
            intro.setObjectName("muted")
            intro.setWordWrap(True)
            layout.addWidget(intro)

            card = QtWidgets.QFrame()
            card.setObjectName("card")
            card_layout = QtWidgets.QVBoxLayout(card)
            card_layout.setContentsMargins(20, 18, 20, 18)
            self.big = QtWidgets.QLabel("Checking…")
            self.big.setObjectName("big")
            card_layout.addWidget(self.big)
            self.detail = QtWidgets.QLabel("")
            self.detail.setObjectName("muted")
            self.detail.setWordWrap(True)
            card_layout.addWidget(self.detail)
            layout.addWidget(card)

            self.warn = QtWidgets.QFrame()
            self.warn.setObjectName("warn")
            warn_layout = QtWidgets.QHBoxLayout(self.warn)
            self.warn_text = QtWidgets.QLabel("")
            self.warn_text.setWordWrap(True)
            warn_layout.addWidget(self.warn_text, 1)
            set_pw = QtWidgets.QPushButton("Set a password…")
            set_pw.clicked.connect(self.open_accounts)
            warn_layout.addWidget(set_pw)
            self.warn.hide()
            layout.addWidget(self.warn)

            level_title = QtWidgets.QLabel("Level")
            level_title.setStyleSheet("font-size: 18px; font-weight: 600; color: #f8fafc;")
            layout.addWidget(level_title)
            self.group = QtWidgets.QButtonGroup(self)
            for key, level in LEVELS.items():
                radio = QtWidgets.QRadioButton(level["name"])
                radio.setStyleSheet("font-weight: 600;")
                radio.setProperty("level", key)
                radio.setChecked(key == DEFAULT_LEVEL)
                self.group.addButton(radio)
                layout.addWidget(radio)
                about = QtWidgets.QLabel(level["about"])
                about.setObjectName("muted")
                about.setWordWrap(True)
                about.setContentsMargins(28, 0, 0, 4)
                layout.addWidget(about)

            row = QtWidgets.QHBoxLayout()
            self.toggle = QtWidgets.QPushButton("Turn on")
            self.toggle.setObjectName("primary")
            self.toggle.clicked.connect(self.toggle_clicked)
            row.addWidget(self.toggle)
            self.off = QtWidgets.QPushButton("Turn off")
            self.off.setObjectName("danger")
            self.off.clicked.connect(lambda: self.run_root(["disable"]))
            row.addWidget(self.off)
            self.test = QtWidgets.QPushButton("Test protection")
            self.test.clicked.connect(self.refresh)
            row.addWidget(self.test)
            row.addStretch(1)
            layout.addLayout(row)
            self.message = QtWidgets.QLabel("")
            self.message.setObjectName("muted")
            self.message.setWordWrap(True)
            layout.addWidget(self.message)

            kids = QtWidgets.QLabel(
                "Tip: give children their own standard (not administrator) account, and make sure "
                "every administrator account has a password. Then nobody else can turn this off.")
            kids.setObjectName("muted")
            kids.setWordWrap(True)
            layout.addWidget(kids)
            add_child = QtWidgets.QPushButton("Add a child account…")
            add_child.clicked.connect(self.open_accounts)
            row2 = QtWidgets.QHBoxLayout()
            row2.addWidget(add_child)
            row2.addStretch(1)
            layout.addLayout(row2)

            notes = QtWidgets.QLabel(
                "Honest notes: no filter catches everything, new sites appear every day. It works by "
                "filtering name lookups (CleanBrowsing, Cloudflare for Families) and locking browser "
                "settings; it does not read or record what anyone visits. A phone hotspot or VPN app "
                "installed by an administrator can still get around it.")
            notes.setObjectName("muted")
            notes.setWordWrap(True)
            layout.addWidget(notes)
            layout.addStretch(1)
            self.refresh()

        def chosen_level(self) -> str:
            button = self.group.checkedButton()
            return button.property("level") if button else DEFAULT_LEVEL

        def busy(self, on: bool):
            for button in (self.toggle, self.off, self.test):
                button.setEnabled(not on)

        def refresh(self):
            self.busy(True)
            self.big.setText("Checking…")
            self.big.setStyleSheet("color: #38bdf8;")
            proc = QtCore.QProcess(self)
            program, args = cli_cmd("status")
            proc.finished.connect(lambda *_: self.show_status(proc))
            proc.start(program, args)
            self.status_proc = proc

        def show_status(self, proc):
            self.busy(False)
            try:
                self.info = json.loads(bytes(proc.readAllStandardOutput()).decode())
            except ValueError:
                self.info = {"state": "off", "enabled": False}
            info = self.info
            state = info.get("state", "off")
            self.big.setText(headline.get(state, state))
            self.big.setStyleSheet(f"color: {colors.get(state, '#e2e8f0')};")
            checks = info.get("checks", {})
            if info.get("enabled"):
                text = f"Level: {info.get('level_name')}. "
                if state == "protected":
                    text += f"Test: {checks.get('test_domain')} is blocked. "
                    if checks.get("google_safesearch"):
                        text += "Google SafeSearch is enforced. "
                elif state == "not_protected":
                    text += ("Test: an adult test site still opens. Restart the PC; if it stays like "
                             "this, turn Family Safety off and on again. ")
                if info.get("hosts_list"):
                    text += f"Extra list: {info['hosts_list']:,} adult domains."
                for key in self.group.buttons():
                    key.setChecked(key.property("level") == info.get("level"))
            else:
                text = "Turn it on to block adult sites for everyone who uses this PC."
            self.detail.setText(text)
            self.toggle.setText("Apply level" if info.get("enabled") else "Turn on")
            self.off.setVisible(bool(info.get("enabled")))
            warnings = list(info.get("warnings", []))
            if not info.get("enabled") and info.get("autologin"):
                warnings.append("This PC signs in without a password. Set an administrator password "
                                "first, otherwise anyone can turn Family Safety off.")
            self.warn_text.setText("\n".join(warnings))
            self.warn.setVisible(bool(warnings))

        def toggle_clicked(self):
            self.run_root(["enable", "--level", self.chosen_level()])

        def run_root(self, args):
            self.busy(True)
            self.message.setText("Waiting for administrator approval…")
            self.proc = QtCore.QProcess(self)
            self.proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
            self.proc.readyReadStandardOutput.connect(self.progress)
            self.proc.finished.connect(self.root_done)
            program, rest = cli_cmd(*args)
            self.proc.start("pkexec", [program] + rest)

        def progress(self):
            text = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
            lines = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("  ")]
            if lines:
                self.message.setText(lines[-1])

        def root_done(self, code, _status):
            if code in (126, 127):
                self.message.setText("Nothing changed (administrator approval was cancelled).")
            elif code != 0:
                self.message.setText("Something went wrong. Details: /var/log/devos-familysafe.log")
            self.refresh()

        def open_accounts(self):
            QtCore.QProcess.startDetached("kcmshell5", ["kcm_users"])

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("devos-familysafe")
    app.setApplicationDisplayName("Family Safety")
    app.setDesktopFileName("devos-familysafe")
    window = Window()
    window.show()
    return app.exec_()


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="devos-familysafe", description="DevOS Family Safety")
    sub = parser.add_subparsers(dest="cmd")
    on = sub.add_parser("enable", help="turn on or change level (root)")
    on.add_argument("--level", choices=sorted(LEVELS), default=DEFAULT_LEVEL)
    sub.add_parser("disable", help="turn off and restore files (root)")
    st = sub.add_parser("status", help="JSON status, no root needed")
    st.add_argument("--no-check", action="store_true", help="skip the live DNS test")
    sub.add_parser("apply", help="boot: load the firewall table (root)")
    sub.add_parser("gui", help="open the window")
    args = parser.parse_args(argv)

    if args.cmd in (None, "gui"):
        return gui()
    engine = FamilySafe()
    if args.cmd == "status":
        print(json.dumps(engine.status(check=not args.no_check), indent=1))
        return 0
    require_root()
    if args.cmd == "enable":
        return engine.enable(args.level)
    if args.cmd == "disable":
        return engine.disable()
    return engine.apply()


if __name__ == "__main__":
    sys.exit(main())
