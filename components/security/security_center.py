#!/usr/bin/env python3
"""
DevOS Security - one window for the protections on this PC (like Windows
Security), plus the "devos-security" command.

  devos-security [gui]                         the window
  devos-security status [--no-check]           JSON, no root needed
  devos-security scan quick|full|PATH          virus scan (as you; archives too)
  devos-security downloads                     recently scanned downloads (JSON)
  devos-security quarantine list               JSON
  devos-security quarantine restore|delete ID  (root for items already in
                                               /var/lib/DevOS/quarantine)
  devos-security notify-safe on|off            "Download is safe" pop-ups
Root (the window runs these through pkexec):
  devos-security check URL|--text            look-alike link, or scam text on stdin
  devos-security web on|off|repair             web protection (Quad9 + browser policies)
  devos-security firewall on                   ufw on, local sharing kept working
  devos-security updates on|off                automatic security updates
  devos-security av install|setup|update       ClamAV: install / pick engine by RAM / signatures
  devos-security diskguard run|enable|resume PID|stop PID
  devos-security boot                          devos-security-firstboot.service
Session / services:
  devos-security av watch-run|usb-run|watch-setup   (systemd --user units)
  devos-security quarantine ingest                   (devos-security-quarantine.path)
  devos-security updates notify-reboot               (devos-reboot-notify.path)

Defaults, applied once by devos-security-firstboot.service on the first boot
of an installed system (and on every live boot): web protection on,
firewall on (when ufw is installed), automatic security updates on (when
unattended-upgrades is installed), ClamAV engine chosen by RAM (when ClamAV
is installed), Disk Guard on. A choice made later in this window is kept:
/etc/devos/security.conf remembers it and the first-boot step never runs
again on that PC.

Nothing here promises 100 %: every card is one layer, and the window says so.
"""

import argparse
import getpass
import json
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import seccommon as common  # noqa: E402
import av  # noqa: E402
import webprotect  # noqa: E402
import updates  # noqa: E402
import diskguard  # noqa: E402

FAMILYSAFE_CLI = "/usr/local/bin/devos-familysafe"
FEATURES_CLI = "/usr/local/bin/devos-features"
AUTOLOGIN = "/etc/sddm.conf.d/zz-devos-autologin.conf"
UFW_CONF = "/etc/ufw/ufw.conf"
OK, WARN, BAD, INFO = "ok", "warn", "bad", "info"

HONEST_NOTE = ("Layered protection: each card is one layer. No security software can promise to "
               "stop every threat, so keep updates on and only run apps you trust.")

# Weight of each card in the protection score (info cards count as fine).
WEIGHTS = {"virus": 20, "web": 15, "firewall": 15, "updates": 20, "account": 10,
           "disk": 8, "sandbox": 7, "encryption": 5, "family": 0, "downloads": 0}


# ---------------------------------------------------------------- raw checks

def firewall_status():
    installed = bool(common.which("ufw")) or os.path.exists("/usr/sbin/ufw")
    conf = common.parse_state(common.read_text(UFW_CONF, ""))
    return {"installed": installed,
            "enabled": installed and conf.get("ENABLED", "no").lower() == "yes",
            "service": common.systemctl_state("ufw.service") if installed else "missing"}


def parse_passwd_status(text):
    """`passwd -S user` -> "P" (password), "NP" (none), "L" (locked) or None."""
    parts = (text or "").split()
    return parts[1] if len(parts) >= 2 else None


def account_status(user=None, live=None):
    user = user or getpass.getuser()
    live = common.is_live_session() if live is None else live
    admin = False
    try:
        import grp
        admin = any(user in grp.getgrnam(g).gr_mem for g in ("sudo", "admin")
                    if _group_exists(grp, g))
    except ImportError:
        pass
    pw = None
    if common.which("passwd"):
        code, out = common.run(["passwd", "-S", user], timeout=5)
        pw = parse_passwd_status(out) if code == 0 else None
    nopasswd_sudo = False
    if admin and common.which("sudo"):
        code, out = common.run(["sudo", "-n", "-l"], timeout=5, env=dict(os.environ, LC_ALL="C"))
        nopasswd_sudo = code == 0 and "NOPASSWD" in out and "ALL" in out
    return {"user": user, "admin": admin, "password": pw, "autologin": os.path.exists(AUTOLOGIN),
            "nopasswd_sudo": nopasswd_sudo, "live": live}


def _group_exists(grp, name):
    try:
        grp.getgrnam(name)
        return True
    except KeyError:
        return False


def parse_lsblk_types(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def encryption_status(live=None):
    live = common.is_live_session() if live is None else live
    if live:
        return {"live": True, "encrypted": None, "source": None}
    _c, src = common.run(["findmnt", "-n", "-o", "SOURCE", "/"], timeout=5)
    src = src.strip().split("[")[0]
    if not src.startswith("/dev/"):
        return {"live": False, "encrypted": None, "source": src or None}
    _c, out = common.run(["lsblk", "-s", "-n", "-o", "TYPE", src], timeout=5)
    types = parse_lsblk_types(out)
    return {"live": False, "encrypted": "crypt" in types, "source": src, "types": types}


def apparmor_status():
    if common.which("aa-enabled"):
        code, out = common.run(["aa-enabled"], timeout=5)
        return {"enabled": code == 0 and out.strip().lower().startswith("yes"), "tool": True}
    flag = (common.read_text("/sys/module/apparmor/parameters/enabled", "") or "").strip()
    return {"enabled": flag == "Y", "tool": False}


def familysafe_status():
    if os.path.exists(FAMILYSAFE_CLI):
        code, out = common.run([FAMILYSAFE_CLI, "status", "--no-check"], timeout=10)
        if code == 0:
            try:
                return json.loads(out)
            except ValueError:
                pass
    return {"enabled": False, "available": os.path.exists(FAMILYSAFE_CLI)}


def collect(check=True, home=None):
    """Every raw status. Each piece is guarded: one failing check must not
    hide the others."""
    live = common.is_live_session()
    raw = {"live": live, "time": int(time.time())}
    for key, fn in (("virus", lambda: av.status(home)),
                    ("web", lambda: webprotect.WebProtect().status(check=check)),
                    ("firewall", firewall_status),
                    ("updates", updates.status),
                    ("disk", diskguard.status),
                    ("account", lambda: account_status(live=live)),
                    ("encryption", lambda: encryption_status(live)),
                    ("sandbox", apparmor_status),
                    ("family", familysafe_status)):
        try:
            raw[key] = fn()
        except Exception as exc:  # report, never crash the window
            raw[key] = {"error": str(exc)}
    return raw


# ---------------------------------------------------------------- cards

def card(cid, title, level, summary, detail="", fix=None, fix_label=None):
    return {"id": cid, "title": title, "level": level, "summary": summary, "detail": detail,
            "fix": fix, "fix_label": fix_label}


def card_virus(s, live=False):
    title = "Virus protection"
    if s.get("error"):
        return card("virus", title, WARN, "Could not check virus protection", s["error"])
    if not s.get("installed"):
        return card("virus", title, WARN, "ClamAV antivirus is not installed",
                    "Install it to scan downloads, USB drives and Windows/Android apps before "
                    "they run (about 250 MB with signatures).", "install-av", "Install")
    age = s.get("signatures_age_days")
    engine = "instant scans (clamd)" if s.get("engine") == "clamdscan" else "low-memory scans"
    if age is None:
        return card("virus", title, WARN, "Virus signatures not downloaded yet",
                    "Signatures download automatically when the PC is online.", "av-update", "Update now")
    if age > 7:
        return card("virus", title, BAD, "Virus signatures are %d days old" % int(age),
                    "Old signatures miss new threats.", "av-update", "Update now")
    if s.get("watching") not in ("active", "unknown"):
        return card("virus", title, WARN, "Automatic download scanning is off",
                    "New downloads and USB drives are not scanned.", "av-watch-on", "Turn on")
    if age > 3:
        return card("virus", title, WARN, "Virus signatures are %d days old" % int(age),
                    "Connect to the internet so they can update.", "av-update", "Update now")
    detail = "Downloads, Desktop, USB drives and apps before they run are scanned · %s · " \
             "signatures updated %s." % (engine, "today" if age < 1 else "%d days ago" % int(age))
    if s.get("quarantine"):
        detail += " %d item(s) in quarantine." % s["quarantine"]
    return card("virus", title, OK, "On", detail)


def card_web(s, family=None):
    title = "Web protection"
    family = family or {}
    if s.get("error"):
        return card("web", title, WARN, "Could not check web protection", s["error"])
    if s.get("familysafe_active") or family.get("enabled"):
        return card("web", title, OK, "On (Family Safety filter)",
                    "Family Safety's filter is in charge of DNS and blocks malware and phishing "
                    "sites as well as adult sites.")
    if not s.get("enabled"):
        return card("web", title, BAD, "Off",
                    "Turn it on to block known phishing and malware sites in every browser and app "
                    "(Quad9 threat-blocking DNS + browser Safe Browsing).", "web-on", "Turn on")
    if s.get("test_blocked") is False:
        return card("web", title, WARN, "On, but the test site was not blocked",
                    "Another DNS setting (a VPN or an app's own secure DNS) may be bypassing it.",
                    "web-on", "Repair")
    if not s.get("firefox_policy") or not s.get("browser_policies"):
        return card("web", title, WARN, "On, browser settings missing",
                    "DNS blocking works; browser Safe Browsing policies need to be put back.",
                    "web-on", "Repair")
    return card("web", title, OK, "On",
                "Known phishing and malware sites are blocked (Quad9). Browsers block dangerous "
                "downloads, warn about leaked passwords, and do not offer a button to continue "
                "to a site they have already marked dangerous. Look-alike addresses and phishing "
                "pages in Downloads are checked on this PC before a full virus scan. New sites "
                "may not be listed yet.")


def card_firewall(s):
    title = "Firewall"
    if not s.get("installed"):
        return card("firewall", title, BAD, "Not installed",
                    "Install the firewall to block incoming connections.", "firewall-on", "Install")
    if not s.get("enabled"):
        return card("firewall", title, BAD, "Off", "Incoming connections are not filtered.",
                    "firewall-on", "Turn on")
    return card("firewall", title, OK, "On",
                "Incoming connections are blocked; Phone Link, the phone companion and DevOS Share keep "
                "working on your home network.")


def card_updates(s):
    title = "Security updates"
    if not s.get("installed"):
        return card("updates", title, WARN, "Automatic updates are not installed",
                    "Install unattended-upgrades so security fixes arrive by themselves.",
                    "updates-on", "Install")
    if not s.get("enabled"):
        return card("updates", title, BAD, "Off", "Security fixes are not installed automatically.",
                    "updates-on", "Turn on")
    if s.get("reboot_required"):
        return card("updates", title, WARN, "Restart to finish",
                    "Security updates were installed and need a restart. Nothing restarts by itself.",
                    "restart", "Restart…")
    return card("updates", title, OK, "On",
                "Security fixes install daily in the background; the PC never restarts by itself.")


def card_disk(s):
    title = "Disk guard"
    if s.get("error"):
        return card("disk", title, WARN, "Could not check the disk", s["error"])
    paused = s.get("paused") or []
    if paused:
        return card("disk", title, BAD, "%s was paused" % paused[0]["name"],
                    "It was filling the disk. Resume or stop it on the Device page.", "page-device", "Review")
    fss = s.get("filesystems") or []
    crit = [f for f in fss if f.get("critical")]
    low = [f for f in fss if f.get("low")]
    if crit:
        f = crit[0]
        return card("disk", title, BAD, "Disk almost full",
                    "Only %s free on %s." % (common.human_size(f["free"]), f["mount"]), "cleanup", "Clean up")
    if low:
        f = low[0]
        return card("disk", title, WARN, "Running low on space",
                    "%s free on %s." % (common.human_size(f["free"]), f["mount"]), "cleanup", "Clean up")
    if not s.get("running"):
        return card("disk", title, WARN, "Off", "Nothing watches for a program filling the disk.",
                    "diskguard-on", "Turn on")
    free = ", ".join("%s free on %s" % (common.human_size(f["free"]), f["mount"]) for f in fss[:2])
    return card("disk", title, OK, "On", "Watches for programs that fill the disk. " + free + ".")


def card_account(s):
    title = "Account protection"
    if s.get("live"):
        return card("account", title, INFO, "Live USB session",
                    "Install DevOS to create your own account with a password.")
    if s.get("nopasswd_sudo"):
        return card("account", title, BAD, "Admin commands need no password",
                    "Any program you run could take over the PC. Remove the NOPASSWD rule.",
                    "accounts", "Open accounts")
    if s.get("admin") and (s.get("password") == "NP" or s.get("autologin")):
        return card("account", title, WARN, "Your admin account has no password",
                    "Anyone at this PC (or a program) can change system settings. Set a password.",
                    "accounts", "Set password")
    return card("account", title, OK, "Password set",
                "Changes to the system ask for your password.")


def card_encryption(s):
    title = "Device encryption"
    if s.get("live"):
        return card("encryption", title, INFO, "Chosen during installation",
                    "Tick “Encrypt system” in the installer to protect your files if the PC is lost.")
    if s.get("encrypted"):
        return card("encryption", title, OK, "On", "The system disk is encrypted (LUKS).")
    if s.get("encrypted") is None:
        return card("encryption", title, INFO, "Unknown", "Could not tell how the system disk is set up.")
    return card("encryption", title, INFO, "Off",
                "Files can be read if someone takes the disk out. Full-disk encryption can only be chosen when "
                "installing DevOS (“Encrypt system”). Until then, DevOS Vault encrypts a folder with a password.",
                "vault", "Encrypt a folder")


def card_sandbox(s):
    title = "App sandboxing"
    if s.get("enabled"):
        return card("sandbox", title, OK, "On (AppArmor)",
                    "AppArmor limits what confined apps (browsers, Flatpaks, services) can touch.")
    return card("sandbox", title, WARN, "AppArmor is off",
                "Apps run without AppArmor limits. It is switched on by the kernel at start-up; "
                "check that apparmor is installed and not disabled on the boot line.")


def card_family(s):
    title = "Family Safety"
    if s.get("enabled"):
        level = s.get("level_name") or "On"
        warn = s.get("warnings") or []
        return card("family", title, WARN if warn else OK, "On (%s)" % level,
                    warn[0] if warn else "Adult sites are blocked for every browser and account.",
                    "familysafe", "Open")
    return card("family", title, INFO, "Off", "Optional: block adult websites for children.",
                "familysafe", "Open")


def card_downloads(entries):
    title = "Downloads"
    bad = [e for e in entries if e.get("result") in ("quarantined", "threat (not moved)")]
    skipped = [e for e in entries if e.get("result") == "not scanned"]
    if not entries:
        return card("downloads", title, INFO, "Nothing scanned yet",
                    "Every finished download is scanned automatically.", "page-virus", "Details")
    if bad:
        return card("downloads", title, WARN, "%d threat(s) quarantined" % len(bad),
                    "Latest: %s (%s)." % (bad[0]["name"], bad[0].get("threat", "")), "page-quarantine",
                    "Review")
    if skipped:
        return card("downloads", title, WARN, "%d download(s) not scanned" % len(skipped),
                    "The scanner was not available. Windows and Android apps are checked again "
                    "before they run.", "page-virus", "Details")
    return card("downloads", title, OK, "%d recent download(s) clean" % len(entries),
                "Latest: %s." % entries[0]["name"], "page-virus", "Details")


def build_cards(raw):
    family = raw.get("family", {})
    downloads = (raw.get("virus") or {}).get("recent_downloads") or []
    return [
        card_virus(raw.get("virus", {}), raw.get("live")),
        card_web(raw.get("web", {}), family),
        card_firewall(raw.get("firewall", {})),
        card_updates(raw.get("updates", {})),
        card_downloads(downloads),
        card_disk(raw.get("disk", {})),
        card_account(raw.get("account", {})),
        card_sandbox(raw.get("sandbox", {})),
        card_encryption(raw.get("encryption", {})),
        card_family(family),
    ]


def headline(cards):
    """(level, title, subtitle, score 0-100). Never claims 100 % safety."""
    total = sum(WEIGHTS.get(c["id"], 0) for c in cards) or 1
    got = 0.0
    for c in cards:
        w = WEIGHTS.get(c["id"], 0)
        got += w * {OK: 1.0, INFO: 1.0, WARN: 0.5, BAD: 0.0}[c["level"]]
    score = int(round(100.0 * got / total))
    bad = [c for c in cards if c["level"] == BAD]
    warn = [c for c in cards if c["level"] == WARN]
    if bad:
        names = " and ".join(c["title"].lower() for c in bad[:2])
        return BAD, "Your PC needs attention", "Fix %s to stay protected." % names, score
    if warn:
        return WARN, "Action recommended", "%d item(s) could be safer. Nothing urgent." % len(warn), score
    return OK, "Your PC is protected", "All protection layers are on. No tool catches everything: " \
                                        "stay careful with unknown files and links.", score


def full_status(check=True, home=None):
    raw = collect(check, home)
    cards = build_cards(raw)
    level, title, sub, score = headline(cards)
    return {"level": level, "headline": title, "subtitle": sub, "score": score,
            "note": HONEST_NOTE, "cards": cards, "raw": raw}


# ---------------------------------------------------------------- root actions

def require_root():
    if not common.is_root():
        print("This needs an administrator: run it with pkexec or sudo.", file=sys.stderr)
        sys.exit(1)


def set_choice(key, value):
    state = common.load_state()
    state[key] = value
    try:
        common.save_state(state)
    except OSError:
        pass


def firewall_on():
    if not common.which("ufw"):
        if os.path.exists(FEATURES_CLI):
            return common.run([FEATURES_CLI, "set", "--add", "firewall"], timeout=1800)[0]
        return 1
    sys.path.insert(0, os.path.join(common.COMPONENTS, "features"))
    try:
        import features_cli
        ports, nets = features_cli.FIREWALL_PORTS, features_cli.PRIVATE_NETS
    except Exception:
        ports, nets = (), ()
    for port, proto in ports:
        for net in nets:
            common.run(["ufw", "allow", "from", net, "to", "any", "port", port, "proto", proto])
    code = common.run(["ufw", "--force", "enable"])[0]
    common.run(["systemctl", "enable", "ufw.service"])
    set_choice("firewall", "1")
    return code


def updates_on(on=True):
    if on and not updates.installed():
        common.run(["apt-get", "install", "-y", "unattended-upgrades"], timeout=1800,
                   env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"))
    set_choice("updates", "1" if on else "0")
    return updates.set_enabled(on) if updates.installed() else 1


def av_setup():
    """Pick the engine by RAM: clamd + freshclam daemon on >= 8 GB, else
    scheduled freshclam and on-demand clamscan."""
    if not common.which("clamscan"):
        return 0
    ram = common.read_meminfo().get("total", 0)
    systemctl = ["systemctl"]
    if ram >= av.CLAMD_MIN_RAM and common.which("clamdscan") and not common.is_live_session():
        common.run(systemctl + ["disable", "--now", "devos-freshclam.timer"])
        common.run(systemctl + ["enable", "--now", "clamav-freshclam.service",
                                "clamav-daemon.socket", "clamav-daemon.service"])
    else:
        common.run(systemctl + ["disable", "--now", "clamav-daemon.service", "clamav-daemon.socket",
                                "clamav-freshclam.service"])
        common.run(systemctl + ["enable", "--now", "devos-freshclam.timer"])
    return 0


def low_memory_freshclam_conf(text):
    """freshclam.conf without the test load of the new signatures (that load
    needs about 1 GB) and without telling a clamd that is not running."""
    out = [line for line in (text or "").splitlines()
           if not line.split(" ", 1)[0] in ("TestDatabases", "NotifyClamd")]
    out.append("TestDatabases no")
    return "\n".join(out) + "\n"


def av_update(scheduled=False):
    if not common.which("freshclam"):
        return 1
    ram = common.read_meminfo().get("total", 0)
    cmd = common.low_priority_prefix() + ["freshclam", "--quiet"]
    if ram < av.CLAMD_MIN_RAM:
        conf = os.path.join(common.RUN_DIR, "freshclam.conf")
        common.write_text(conf, low_memory_freshclam_conf(common.read_text("/etc/clamav/freshclam.conf", "")), 0o644)
        cmd.append("--config-file=" + conf)
    elif not scheduled:
        common.run(["systemctl", "stop", "clamav-freshclam.service"])  # it holds the lock
    code = common.run(cmd, timeout=1800)[0]
    if ram >= av.CLAMD_MIN_RAM and not scheduled:
        common.run(["systemctl", "start", "clamav-freshclam.service"])
    if common.systemctl_state("clamav-daemon.service", what="is-enabled") == "enabled":
        common.run(["systemctl", "start", "clamav-daemon.socket", "clamav-daemon.service"])
    return 0 if code in (0, 1) else code


def av_install():
    if not common.which("clamscan") and os.path.exists(FEATURES_CLI):
        common.run([FEATURES_CLI, "set", "--add", "antivirus"], timeout=3600)
    if common.which("clamscan") and common.read_meminfo().get("total", 0) >= av.CLAMD_MIN_RAM \
            and not common.which("clamdscan"):
        common.run(["apt-get", "install", "-y", "clamav-daemon", "clamdscan", "clamav-freshclam"], timeout=1800,
                   env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"))
    if not common.which("clamscan"):
        return 1
    av_setup()
    av_update()
    return 0


def diskguard_enable():
    common.run(["systemctl", "enable", "--now", "devos-diskguard.service"])
    set_choice("diskguard", "1")
    return 0


def boot():
    """devos-security-firstboot.service: defaults once, repairs every boot."""
    state = common.load_state()
    web = webprotect.WebProtect()
    if state.get("defaults") != "1":
        if state.get("web") != "0":
            web.enable()
        if state.get("firewall") != "0" and common.which("ufw"):
            firewall_on()
        if state.get("updates") != "0" and updates.installed():
            updates.set_enabled(True)
        av_setup()
        state = common.load_state()
        state["defaults"] = "1"
        state.setdefault("web", "1" if web.enabled() else "0")
        try:
            common.save_state(state)
        except OSError:
            pass
        common.log("first boot: security defaults applied")
    else:
        web.repair()
        if common.systemctl_state("clamav-daemon.service", what="is-enabled") == "enabled" and \
                os.path.exists(os.path.join(av.CLAMAV_DB, "main.cvd")):
            common.run(["systemctl", "start", "--no-block", "clamav-daemon.socket"])
    return 0


def resume_or_stop(pid, action):
    info = None
    for p in diskguard.status().get("paused", []):
        if p["pid"] == pid:
            info = p
    start = info["start"] if info else None
    if start is None:
        try:
            with open("/proc/%d/stat" % pid) as fh:
                start = diskguard.parse_stat(fh.read())[2]
        except (OSError, ValueError, IndexError):
            return 1
    sig = signal.SIGCONT if action == "resume" else signal.SIGTERM
    return 0 if diskguard.send(pid, start, sig) else 1


# ---------------------------------------------------------------- CLI

def main(argv=None):
    parser = argparse.ArgumentParser(prog="devos-security", description=common.APP_NAME)
    sub = parser.add_subparsers(dest="cmd")
    g = sub.add_parser("gui")
    g.add_argument("--page", default="overview")
    st = sub.add_parser("status")
    st.add_argument("--no-check", action="store_true", help="skip the live DNS test")
    sc = sub.add_parser("scan")
    sc.add_argument("target", help="quick, full or a file/folder")
    sub.add_parser("downloads")
    q = sub.add_parser("quarantine")
    q.add_argument("action", choices=("list", "restore", "delete", "ingest"))
    q.add_argument("id", nargs="?")
    ns = sub.add_parser("notify-safe")
    ns.add_argument("state", choices=("on", "off"))
    a = sub.add_parser("av")
    a.add_argument("action", choices=("watch-run", "usb-run", "watch-setup", "install", "setup",
                                      "update", "status"))
    a.add_argument("--scheduled", action="store_true")
    chk = sub.add_parser("check", help="look-alike link, or scam text with --text")
    chk.add_argument("target", nargs="?", default="")
    chk.add_argument("--text", action="store_true", help="read the message from stdin")
    w = sub.add_parser("web")
    w.add_argument("action", choices=("on", "off", "repair", "status"))
    f = sub.add_parser("firewall")
    f.add_argument("action", choices=("on",))
    u = sub.add_parser("updates")
    u.add_argument("action", choices=("on", "off", "status", "notify-reboot"))
    d = sub.add_parser("diskguard")
    d.add_argument("action", choices=("run", "status", "enable", "resume", "stop"))
    d.add_argument("pid", nargs="?", type=int)
    sub.add_parser("boot")
    args = parser.parse_args(argv)

    def out(data):
        print(json.dumps(data, indent=1, default=str))
        return 0

    if args.cmd in (None, "gui"):
        return gui(getattr(args, "page", "overview"))
    if args.cmd == "status":
        return out(full_status(check=not args.no_check))
    if args.cmd == "scan":
        kind = args.target if args.target in ("quick", "full") else "path"
        res = av.run_scan(kind, None if kind != "path" else args.target)
        out(res)
        return 0 if res["ok"] and not res["threats"] else (1 if res["threats"] else 2)
    if args.cmd == "check":
        import linkguard
        if args.text or args.target == "-":
            result = linkguard.inspect_text(sys.stdin.read() if args.target in ("", "-") else args.target)
        elif not args.target:
            print("Give a web address, or --text to read a message from stdin.", file=sys.stderr)
            return 2
        else:
            result = linkguard.inspect_url(args.target)
        out(result)
        return {linkguard.OK: 0, linkguard.WARN: 1, linkguard.BLOCK: 2}.get(result["level"], 2)
    if args.cmd == "downloads":
        return out(av.recent_downloads(limit=50))
    if args.cmd == "notify-safe":
        cfg = common.load_user_config()
        cfg["notify_safe_downloads"] = args.state == "on"
        common.save_user_config(cfg)
        return 0
    if args.cmd == "quarantine":
        if args.action == "list":
            return out(av.user_quarantine())
        if args.action == "ingest":
            require_root()
            return out(av.ingest())
        if not args.id:
            parser.error("quarantine %s needs an ID" % args.action)
        pending = {m["id"] for m in av.pending_items()}
        if args.id in pending:
            if args.action == "restore":
                return out({"restored": av.restore_pending(args.id)})
            return out({"deleted": av.delete_pending(args.id)})
        require_root()
        qr = av.Quarantine()
        try:
            if args.action == "restore":
                return out({"restored": qr.restore(args.id)})
            return out({"deleted": qr.delete(args.id)})
        except KeyError:
            print("No quarantined item %s." % args.id, file=sys.stderr)
        except OSError as exc:
            print("Could not %s it: %s" % (args.action, exc), file=sys.stderr)
        return 1
    if args.cmd == "av":
        if args.action == "watch-run":
            av.watch_run()
            return 0
        if args.action == "usb-run":
            av.usb_run()
            return 0
        if args.action == "watch-setup":
            av.watch_setup()
            return 0
        if args.action == "status":
            return out(av.status())
        require_root()
        return {"install": av_install, "setup": av_setup,
                "update": lambda: av_update(args.scheduled)}[args.action]()
    if args.cmd == "web":
        engine = webprotect.WebProtect()
        if args.action == "status":
            return out(engine.status())
        require_root()
        if args.action == "repair":
            return engine.repair()
        set_choice("web", "1" if args.action == "on" else "0")
        return engine.enable() if args.action == "on" else engine.disable()
    if args.cmd == "firewall":
        require_root()
        return firewall_on()
    if args.cmd == "updates":
        if args.action == "status":
            return out(updates.status())
        require_root()
        if args.action == "notify-reboot":
            return updates.notify_reboot()
        return updates_on(args.action == "on")
    if args.cmd == "diskguard":
        if args.action == "status":
            return out(diskguard.status())
        if args.action in ("resume", "stop"):
            if args.pid is None:
                parser.error("diskguard %s needs a PID" % args.action)
            return resume_or_stop(args.pid, args.action)
        require_root()
        return diskguard_enable() if args.action == "enable" else diskguard.run_daemon()
    if args.cmd == "boot":
        require_root()
        return boot()
    parser.print_help()
    return 2


# ---------------------------------------------------------------- window

COLORS = {OK: "#22c55e", WARN: "#f59e0b", BAD: "#ef4444", INFO: "#64748b"}
LEVEL_WORD = {OK: "Protected", WARN: "Check", BAD: "Action needed", INFO: "Info"}

STYLE = """
QWidget { background: #0b0f1a; color: #e2e8f0; font-size: 13px; }
QWidget#sidebar { background: #080b14; border-right: 1px solid #172033; }
QLabel { background: transparent; }
QLabel#brand { font-size: 16px; font-weight: 700; color: #f8fafc; }
QLabel#brandsub { color: #64748b; font-size: 11px; }
QPushButton#nav { text-align: left; padding: 10px 14px; border: none; border-radius: 10px;
  background: transparent; color: #94a3b8; font-size: 13px; }
QPushButton#nav:hover { background: #111a2c; color: #e2e8f0; }
QPushButton#nav:checked { background: #10233a; color: #7dd3fc; font-weight: 600; }
QLabel#h1 { font-size: 26px; font-weight: 700; color: #f8fafc; }
QLabel#h2 { font-size: 17px; font-weight: 600; color: #f1f5f9; }
QLabel#muted { color: #94a3b8; }
QLabel#tiny { color: #64748b; font-size: 11px; }
QLabel#cardtitle { font-size: 14px; font-weight: 600; color: #f1f5f9; }
QLabel#cardsum { font-size: 13px; color: #e2e8f0; }
QFrame#hero { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0f1b30, stop:1 #0b1222);
  border: 1px solid #1e293b; border-radius: 18px; }
QFrame#card { background: #0f172a; border: 1px solid #1e293b; border-radius: 14px; }
QFrame#card:hover { border-color: #2b3a55; }
QFrame#note { background: #0d1424; border: 1px solid #172033; border-radius: 12px; }
QPushButton { background: #1e293b; border: 1px solid #334155; border-radius: 9px; padding: 7px 14px;
  color: #e2e8f0; }
QPushButton:hover { background: #26354d; }
QPushButton:disabled { color: #64748b; }
QPushButton#primary { background: #0284c7; border-color: #38bdf8; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #0ea5e9; }
QPushButton#fix { background: #0c2a44; border: 1px solid #1d4f7a; color: #7dd3fc; padding: 5px 12px;
  font-weight: 600; }
QPushButton#fix:hover { background: #10375a; }
QPushButton#danger { background: #3a1216; border-color: #7f1d1d; color: #fecaca; }
QProgressBar { background: #0f172a; border: 1px solid #1e293b; border-radius: 6px; height: 10px;
  text-align: center; color: transparent; }
QProgressBar::chunk { background: #38bdf8; border-radius: 6px; }
QTableWidget { background: #0f172a; border: 1px solid #1e293b; border-radius: 12px;
  gridline-color: #172033; selection-background-color: #10233a; }
QTableWidget::item { padding-left: 10px; }
QHeaderView::section { background: #0b1222; color: #94a3b8; border: none; padding: 8px 10px;
  font-weight: 600; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid #334155;
  background: #0b0f1a; }
QCheckBox::indicator:checked { background: #38bdf8; border-color: #38bdf8; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #1e293b; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def gui(page="overview"):
    from PyQt5 import QtCore, QtGui, QtWidgets  # lazy: CLI and tests need no Qt

    class StatusThread(QtCore.QThread):
        done = QtCore.pyqtSignal(object)

        def __init__(self, check, parent=None):
            super().__init__(parent)
            self.check = check

        def run(self):
            try:
                self.done.emit(full_status(check=self.check))
            except Exception as exc:
                self.done.emit({"error": str(exc)})

    class Shield(QtWidgets.QWidget):
        """Painted shield in the status colour with a check or an exclamation."""

        def __init__(self, size=96, parent=None):
            super().__init__(parent)
            self.level = INFO
            self.setFixedSize(size, int(size * 1.12))

        def set_level(self, level):
            self.level = level
            self.update()

        def paintEvent(self, _event):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            w, h = self.width(), self.height()
            color = QtGui.QColor(COLORS[self.level])
            glow = QtGui.QRadialGradient(w / 2, h / 2, w * 0.62)
            c0 = QtGui.QColor(color)
            c0.setAlpha(70)
            c1 = QtGui.QColor(color)
            c1.setAlpha(0)
            glow.setColorAt(0, c0)
            glow.setColorAt(1, c1)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QtCore.QRectF(0, 0, w, h))
            m = w * 0.16
            path = QtGui.QPainterPath()
            top, bottom = h * 0.12, h * 0.9
            path.moveTo(w / 2, top)
            path.cubicTo(w * 0.62, top + h * 0.06, w - m, top + h * 0.07, w - m, top + h * 0.1)
            path.cubicTo(w - m, h * 0.55, w * 0.72, h * 0.78, w / 2, bottom)
            path.cubicTo(w * 0.28, h * 0.78, m, h * 0.55, m, top + h * 0.1)
            path.cubicTo(m, top + h * 0.07, w * 0.38, top + h * 0.06, w / 2, top)
            grad = QtGui.QLinearGradient(0, top, 0, bottom)
            grad.setColorAt(0, color.lighter(125))
            grad.setColorAt(1, color.darker(140))
            p.setBrush(grad)
            p.drawPath(path)
            pen = QtGui.QPen(QtGui.QColor("#0b0f1a"), w * 0.075, QtCore.Qt.SolidLine,
                             QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
            p.setPen(pen)
            if self.level == OK:
                p.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(w * 0.36, h * 0.5),
                                                QtCore.QPointF(w * 0.47, h * 0.6),
                                                QtCore.QPointF(w * 0.66, h * 0.4)]))
            elif self.level in (WARN, BAD):
                p.drawLine(QtCore.QPointF(w / 2, h * 0.34), QtCore.QPointF(w / 2, h * 0.56))
                p.drawPoint(QtCore.QPointF(w / 2, h * 0.68))
            else:
                p.drawEllipse(QtCore.QPointF(w / 2, h * 0.5), w * 0.02, w * 0.02)

    class ScoreRing(QtWidgets.QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.score, self.level = 0, INFO
            self.setFixedSize(112, 112)

        def set(self, score, level):
            self.score, self.level = score, level
            self.update()

        def paintEvent(self, _event):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            r = QtCore.QRectF(8, 8, self.width() - 16, self.height() - 16)
            p.setPen(QtGui.QPen(QtGui.QColor("#1e293b"), 9, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
            p.drawArc(r, 0, 360 * 16)
            p.setPen(QtGui.QPen(QtGui.QColor(COLORS[self.level]), 9, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
            p.drawArc(r, 90 * 16, -int(360 * 16 * self.score / 100.0))
            p.setPen(QtGui.QColor("#f8fafc"))
            f = QtGui.QFont(self.font())
            f.setPointSize(19)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QtCore.QRectF(r.x(), r.y() - 6, r.width(), r.height()), QtCore.Qt.AlignCenter,
                       str(self.score))
            f.setPointSize(7)
            f.setBold(False)
            p.setFont(f)
            p.setPen(QtGui.QColor("#94a3b8"))
            p.drawText(QtCore.QRectF(r.x(), r.y() + 22, r.width(), r.height()), QtCore.Qt.AlignCenter,
                       "SCORE")

    class Dot(QtWidgets.QWidget):
        def __init__(self, level, parent=None):
            super().__init__(parent)
            self.level = level
            self.setFixedSize(12, 12)

        def paintEvent(self, _event):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor(COLORS[self.level]))
            p.drawEllipse(1, 1, 10, 10)

    def label(text, name=None, wrap=False):
        lab = QtWidgets.QLabel(text)
        if name:
            lab.setObjectName(name)
        lab.setWordWrap(wrap)
        return lab

    def frame(name):
        f = QtWidgets.QFrame()
        f.setObjectName(name)
        f.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        return f

    class Window(QtWidgets.QWidget):
        def __init__(self, start_page):
            super().__init__()
            self.setWindowTitle(common.APP_NAME)
            icon = QtGui.QIcon.fromTheme("security-high")
            if not icon.isNull():
                self.setWindowIcon(icon)
            self.resize(1080, 760)
            self.setStyleSheet(STYLE)
            self.data = None
            self.threads = []
            self.proc = None

            root = QtWidgets.QHBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(0)
            side = QtWidgets.QWidget()
            side.setObjectName("sidebar")
            side.setAttribute(QtCore.Qt.WA_StyledBackground, True)
            side.setFixedWidth(218)
            sl = QtWidgets.QVBoxLayout(side)
            sl.setContentsMargins(14, 20, 14, 16)
            sl.setSpacing(4)
            brand_row = QtWidgets.QHBoxLayout()
            self.mini = Shield(30)
            brand_row.addWidget(self.mini)
            bcol = QtWidgets.QVBoxLayout()
            bcol.setSpacing(0)
            bcol.addWidget(label("DevOS Security", "brand"))
            bcol.addWidget(label("Layered protection", "brandsub"))
            brand_row.addLayout(bcol)
            brand_row.addStretch(1)
            sl.addLayout(brand_row)
            sl.addSpacing(18)
            self.stack = QtWidgets.QStackedWidget()
            self.nav = {}
            group = QtWidgets.QButtonGroup(self)
            for key, text in (("overview", "Overview"), ("virus", "Virus && downloads"),
                              ("quarantine", "Quarantine"), ("device", "Device && disk"),
                              ("history", "Scan history")):
                b = QtWidgets.QPushButton(text)
                b.setObjectName("nav")
                b.setCheckable(True)
                b.setCursor(QtCore.Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, k=key: self.show_page(k))
                group.addButton(b)
                sl.addWidget(b)
                self.nav[key] = b
            sl.addStretch(1)
            sl.addWidget(label("Nothing here can promise 100 %.\nIt stacks several layers so one "
                               "miss is caught by the next.", "tiny", True))
            root.addWidget(side)
            root.addWidget(self.stack, 1)

            self.pages = {}
            for key, builder in (("overview", self.build_overview), ("virus", self.build_virus),
                                 ("quarantine", self.build_quarantine), ("device", self.build_device),
                                 ("history", self.build_history)):
                page_widget = builder()
                self.pages[key] = page_widget
                self.stack.addWidget(page_widget)
            self.show_page(start_page if start_page in self.pages else "overview")
            self.refresh(check=True)

        # ---- helpers
        def scroll_page(self):
            area = QtWidgets.QScrollArea()
            area.setWidgetResizable(True)
            inner = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(inner)
            lay.setContentsMargins(30, 26, 30, 26)
            lay.setSpacing(16)
            area.setWidget(inner)
            return area, lay

        def show_page(self, key):
            self.nav[key].setChecked(True)
            self.stack.setCurrentWidget(self.pages[key])

        def refresh(self, check=False):
            t = StatusThread(check, self)
            t.done.connect(self.on_status)
            self.threads.append(t)
            t.finished.connect(lambda t=t: self.threads.remove(t) if t in self.threads else None)
            t.start()

        # ---- overview
        def build_overview(self):
            area, lay = self.scroll_page()
            hero = frame("hero")
            hl = QtWidgets.QHBoxLayout(hero)
            hl.setContentsMargins(26, 22, 26, 22)
            hl.setSpacing(22)
            self.shield = Shield(96)
            hl.addWidget(self.shield)
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(6)
            self.head = label("Checking your PC…", "h1")
            self.sub = label("This takes a few seconds.", "muted", True)
            col.addStretch(1)
            col.addWidget(self.head)
            col.addWidget(self.sub)
            row = QtWidgets.QHBoxLayout()
            self.quick_btn = QtWidgets.QPushButton("Quick scan")
            self.quick_btn.setObjectName("primary")
            self.quick_btn.setCursor(QtCore.Qt.PointingHandCursor)
            self.quick_btn.clicked.connect(lambda: (self.show_page("virus"), self.start_scan("quick")))
            again = QtWidgets.QPushButton("Check again")
            again.clicked.connect(lambda: self.refresh(check=True))
            row.addWidget(self.quick_btn)
            row.addWidget(again)
            row.addStretch(1)
            col.addSpacing(6)
            col.addLayout(row)
            col.addStretch(1)
            hl.addLayout(col, 1)
            self.ring = ScoreRing()
            hl.addWidget(self.ring)
            lay.addWidget(hero)
            self.grid_holder = QtWidgets.QWidget()
            self.grid = QtWidgets.QGridLayout(self.grid_holder)
            self.grid.setContentsMargins(0, 0, 0, 0)
            self.grid.setSpacing(14)
            lay.addWidget(self.grid_holder)
            note = frame("note")
            nl = QtWidgets.QHBoxLayout(note)
            nl.setContentsMargins(16, 12, 16, 12)
            nl.addWidget(label(HONEST_NOTE, "muted", True))
            lay.addWidget(note)
            lay.addStretch(1)
            return area

        def make_card(self, c):
            f = frame("card")
            f.setMinimumHeight(150)
            v = QtWidgets.QVBoxLayout(f)
            v.setContentsMargins(16, 14, 16, 14)
            v.setSpacing(6)
            top = QtWidgets.QHBoxLayout()
            top.addWidget(Dot(c["level"]))
            top.addWidget(label(c["title"], "cardtitle"))
            top.addStretch(1)
            badge = label(LEVEL_WORD[c["level"]], "tiny")
            badge.setStyleSheet("color: %s; font-weight: 600;" % COLORS[c["level"]])
            top.addWidget(badge)
            v.addLayout(top)
            v.addWidget(label(c["summary"], "cardsum", True))
            d = label(c["detail"], "muted", True)
            d.setStyleSheet("font-size: 12px;")
            v.addWidget(d, 1)
            if c.get("fix"):
                b = QtWidgets.QPushButton(c.get("fix_label") or "Fix")
                b.setObjectName("fix")
                b.setCursor(QtCore.Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, a=c["fix"]: self.do_fix(a))
                row = QtWidgets.QHBoxLayout()
                row.addWidget(b)
                row.addStretch(1)
                v.addLayout(row)
            return f

        def on_status(self, data):
            if data.get("error"):
                self.head.setText("Could not check everything")
                self.sub.setText(data["error"])
                return
            self.data = data
            self.shield.set_level(data["level"])
            self.mini.set_level(data["level"])
            self.ring.set(data["score"], data["level"])
            self.head.setText(data["headline"])
            self.sub.setText(data["subtitle"])
            while self.grid.count():
                item = self.grid.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            order = {BAD: 0, WARN: 1, OK: 2, INFO: 3}
            cards = sorted(data["cards"], key=lambda c: order[c["level"]])
            for i, c in enumerate(cards):
                self.grid.addWidget(self.make_card(c), i // 3, i % 3)
            for col in range(3):
                self.grid.setColumnStretch(col, 1)
            self.fill_virus(data)
            self.fill_quarantine()
            self.fill_device(data)
            self.fill_history()

        # ---- virus & downloads
        def build_virus(self):
            area, lay = self.scroll_page()
            lay.addWidget(label("Virus & downloads", "h1"))
            self.av_info = label("", "muted", True)
            lay.addWidget(self.av_info)
            box = frame("card")
            bl = QtWidgets.QVBoxLayout(box)
            bl.setContentsMargins(18, 16, 18, 16)
            bl.addWidget(label("Scan now", "h2"))
            bl.addWidget(label("Quick: Downloads, Desktop, USB drives, autostart. Full: your whole home "
                               "folder (can take an hour). Archives are scanned inside.", "muted", True))
            row = QtWidgets.QHBoxLayout()
            self.scan_btns = []
            for text, kind in (("Quick scan", "quick"), ("Full scan", "full"), ("Choose folder…", "path")):
                b = QtWidgets.QPushButton(text)
                if kind == "quick":
                    b.setObjectName("primary")
                b.clicked.connect(lambda _=False, k=kind: self.start_scan(k))
                row.addWidget(b)
                self.scan_btns.append(b)
            row.addStretch(1)
            bl.addLayout(row)
            self.scan_bar = QtWidgets.QProgressBar()
            self.scan_bar.setRange(0, 0)
            self.scan_bar.hide()
            bl.addWidget(self.scan_bar)
            self.scan_result = label("", "muted", True)
            bl.addWidget(self.scan_result)
            lay.addWidget(box)
            lay.addWidget(label("Recent downloads", "h2"))
            self.dl_table = self.table(["File", "Result", "When"])
            lay.addWidget(self.dl_table)
            self.notify_box = QtWidgets.QCheckBox("Also tell me when a download is safe "
                                                  "(threats are always reported)")
            self.notify_box.setChecked(bool(common.load_user_config().get("notify_safe_downloads")))
            self.notify_box.toggled.connect(self.toggle_notify)
            lay.addWidget(self.notify_box)
            lay.addStretch(1)
            return area

        def table(self, headers):
            t = QtWidgets.QTableWidget(0, len(headers))
            t.setHorizontalHeaderLabels(headers)
            t.verticalHeader().hide()
            t.setShowGrid(False)
            t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            head = t.horizontalHeader()
            head.setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            head.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
            head.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            t.verticalHeader().setDefaultSectionSize(34)
            t.setWordWrap(False)
            t.setMinimumHeight(220)
            return t

        def fill_virus(self, data):
            s = data["raw"].get("virus", {})
            if s.get("installed"):
                age = s.get("signatures_age_days")
                self.av_info.setText(
                    "ClamAV · %s · signatures %s · this PC has %s GB RAM, so DevOS uses %s." % (
                        "watching new files" if s.get("watching") in ("active", "unknown") else "watcher off",
                        "not downloaded yet" if age is None else ("updated today" if age < 1 else
                                                                  "%d days old" % int(age)),
                        s.get("ram_gb"), "the always-ready clamd engine" if s.get("engine") == "clamdscan"
                        else "on-demand scans that free their memory afterwards"))
            else:
                self.av_info.setText("ClamAV is not installed. Open the Overview and press Install.")
            rows = av.recent_downloads(limit=40)
            self.dl_table.setRowCount(len(rows))
            for i, e in enumerate(rows):
                result = e.get("result", "")
                text = {"clean": "Clean", "quarantined": "Quarantined · %s" % e.get("threat", ""),
                        "not scanned": "Not scanned", "allowed": "Allowed by you"}.get(result, result)
                item = QtWidgets.QTableWidgetItem(text)
                item.setForeground(QtGui.QColor(COLORS[OK] if result == "clean" else
                                                COLORS[BAD] if "uarantin" in result or "threat" in result
                                                else COLORS[WARN]))
                self.dl_table.setItem(i, 0, QtWidgets.QTableWidgetItem(e.get("name", "")))
                self.dl_table.setItem(i, 1, item)
                self.dl_table.setItem(i, 2, QtWidgets.QTableWidgetItem(
                    time.strftime("%d %b %H:%M", time.localtime(e.get("time", 0)))))

        def toggle_notify(self, on):
            cfg = common.load_user_config()
            cfg["notify_safe_downloads"] = bool(on)
            try:
                common.save_user_config(cfg)
            except OSError:
                pass

        def start_scan(self, kind):
            target = kind
            if kind == "path":
                target = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder to scan",
                                                                    os.path.expanduser("~"))
                if not target:
                    return
            if self.proc is not None:
                return
            for b in self.scan_btns:
                b.setEnabled(False)
            self.quick_btn.setEnabled(False)
            self.scan_bar.show()
            self.scan_result.setText("Scanning… on PCs with less than 8 GB RAM the first seconds load "
                                     "the virus signatures.")
            self.proc = QtCore.QProcess(self)
            self.proc.finished.connect(self.scan_done)
            self.proc.start(sys.executable, [os.path.abspath(__file__), "scan", target])

        def scan_done(self, *_):
            raw = bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace")
            self.proc = None
            for b in self.scan_btns:
                b.setEnabled(True)
            self.quick_btn.setEnabled(True)
            self.scan_bar.hide()
            try:
                res = json.loads(raw)
            except ValueError:
                self.scan_result.setText("The scan could not run.")
                return
            if res.get("threats"):
                self.scan_result.setText("%d threat(s) found and moved to quarantine." % len(res["threats"]))
            elif not res.get("ok"):
                self.scan_result.setText("The scan could not finish: %s" % "; ".join(res.get("errors", []))[:300])
            else:
                self.scan_result.setText("No threats found (%s s)." % res.get("seconds"))
            self.refresh()

        # ---- quarantine
        def build_quarantine(self):
            area, lay = self.scroll_page()
            lay.addWidget(label("Quarantine", "h1"))
            lay.addWidget(label("Files here cannot run or be opened. Restore only a file you are sure "
                                "about (an administrator password is needed for files the system "
                                "already locked away).", "muted", True))
            self.q_table = self.table(["File", "Threat", "Found", "Where"])
            lay.addWidget(self.q_table)
            row = QtWidgets.QHBoxLayout()
            self.restore_btn = QtWidgets.QPushButton("Restore")
            self.delete_btn = QtWidgets.QPushButton("Delete permanently")
            self.delete_btn.setObjectName("danger")
            self.restore_btn.clicked.connect(lambda: self.q_action("restore"))
            self.delete_btn.clicked.connect(lambda: self.q_action("delete"))
            row.addWidget(self.restore_btn)
            row.addWidget(self.delete_btn)
            row.addStretch(1)
            lay.addLayout(row)
            lay.addStretch(1)
            return area

        def fill_quarantine(self):
            self.q_items = av.user_quarantine()
            self.q_table.setRowCount(len(self.q_items))
            for i, m in enumerate(self.q_items):
                vals = (os.path.basename(m.get("original", "")), m.get("threat", ""),
                        time.strftime("%d %b %Y %H:%M", time.localtime(m.get("time", 0))),
                        os.path.dirname(m.get("original", "")))
                for j, v in enumerate(vals):
                    self.q_table.setItem(i, j, QtWidgets.QTableWidgetItem(v))

        def q_action(self, action):
            row = self.q_table.currentRow()
            if row < 0 or row >= len(self.q_items):
                return
            item = self.q_items[row]
            name = os.path.basename(item.get("original", ""))
            if action == "restore":
                ask = ("Restore %s?\n\nIt was flagged as %s. Restore it only if you trust where it "
                       "came from." % (name, item.get("threat")))
            else:
                ask = "Delete %s permanently? This cannot be undone." % name
            if QtWidgets.QMessageBox.question(self, common.APP_NAME, ask) != QtWidgets.QMessageBox.Yes:
                return
            if item.get("status") == "pending":
                try:
                    if action == "restore":
                        av.restore_pending(item["id"])
                    else:
                        av.delete_pending(item["id"])
                except (OSError, KeyError) as exc:
                    QtWidgets.QMessageBox.warning(self, common.APP_NAME, str(exc))
                self.fill_quarantine()
                return
            self.run_root(["quarantine", action, item["id"]])

        # ---- device & disk
        def build_device(self):
            area, lay = self.scroll_page()
            lay.addWidget(label("Device & disk", "h1"))
            self.dev_info = label("", "muted", True)
            lay.addWidget(self.dev_info)
            self.disk_holder = QtWidgets.QVBoxLayout()
            lay.addLayout(self.disk_holder)
            lay.addWidget(label("Paused apps", "h2"))
            self.p_table = self.table(["App", "Process", "Paused"])
            self.p_table.setMinimumHeight(120)
            lay.addWidget(self.p_table)
            row = QtWidgets.QHBoxLayout()
            res = QtWidgets.QPushButton("Resume")
            stop = QtWidgets.QPushButton("Stop app")
            stop.setObjectName("danger")
            res.clicked.connect(lambda: self.p_action("resume"))
            stop.clicked.connect(lambda: self.p_action("stop"))
            row.addWidget(res)
            row.addWidget(stop)
            row.addStretch(1)
            lay.addLayout(row)
            lay.addStretch(1)
            return area

        def fill_device(self, data):
            raw = data["raw"]
            disk = raw.get("disk", {})
            while self.disk_holder.count():
                it = self.disk_holder.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            for fs in disk.get("filesystems", [])[:4]:
                f = frame("card")
                g = QtWidgets.QGridLayout(f)
                g.setContentsMargins(16, 12, 16, 12)
                used = fs["total"] - fs["free"]
                g.addWidget(label("Disk %s" % fs["mount"], "cardtitle"), 0, 0)
                g.addWidget(label("%s free of %s" % (common.human_size(fs["free"]),
                                                     common.human_size(fs["total"])), "muted"), 0, 1,
                            QtCore.Qt.AlignRight)
                bar = QtWidgets.QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(int(used * 100 / max(1, fs["total"])))
                if fs.get("critical") or fs.get("low"):
                    bar.setStyleSheet("QProgressBar::chunk { background: %s; }" %
                                      COLORS[BAD if fs.get("critical") else WARN])
                g.addWidget(bar, 1, 0, 1, 2)
                self.disk_holder.addWidget(f)
            for a in disk.get("alerts", [])[:3]:
                self.disk_holder.addWidget(label("⚠ %s — %s" % (a["title"], a["text"]), "muted", True))
            self.paused = disk.get("paused", [])
            self.p_table.setRowCount(len(self.paused))
            for i, p in enumerate(self.paused):
                for j, v in enumerate((p["name"], "%s (PID %d)" % (p["comm"], p["pid"]),
                                       time.strftime("%H:%M", time.localtime(p["time"])))):
                    self.p_table.setItem(i, j, QtWidgets.QTableWidgetItem(v))
            enc = raw.get("encryption", {})
            aa = raw.get("sandbox", {})
            self.dev_info.setText("Disk Guard %s · Encryption %s · AppArmor %s" % (
                "is watching" if disk.get("running") else "is off",
                "on" if enc.get("encrypted") else ("chosen at install" if enc.get("live") else
                                                   "unknown" if enc.get("encrypted") is None else "off"),
                "on" if aa.get("enabled") else "off"))

        def p_action(self, action):
            row = self.p_table.currentRow()
            if row < 0 or row >= len(self.paused):
                return
            p = self.paused[row]
            if hasattr(os, "getuid") and p["uid"] == os.getuid():
                diskguard.send(p["pid"], p["start"], signal.SIGCONT if action == "resume" else signal.SIGTERM)
                self.refresh()
            else:
                self.run_root(["diskguard", action, str(p["pid"])])

        # ---- history
        def build_history(self):
            area, lay = self.scroll_page()
            lay.addWidget(label("Scan history", "h1"))
            self.h_table = self.table(["Scan", "Result", "When", "Engine"])
            self.h_table.setMinimumHeight(420)
            lay.addWidget(self.h_table)
            lay.addStretch(1)
            return area

        def fill_history(self):
            rows = av.scan_history(limit=60)
            self.h_table.setRowCount(len(rows))
            for i, h in enumerate(rows):
                kind = {"quick": "Quick scan", "full": "Full scan", "usb": "USB drive",
                        "path": "Folder scan"}.get(h.get("kind"), h.get("kind", ""))
                result = ("%d threat(s)" % h["threats"]) if h.get("threats") else \
                    ("No threats" if h.get("ok") else "Did not finish")
                for j, v in enumerate((kind, result, time.strftime("%d %b %Y %H:%M",
                                                                   time.localtime(h.get("time", 0))),
                                       h.get("engine", ""))):
                    self.h_table.setItem(i, j, QtWidgets.QTableWidgetItem(v))

        # ---- fixes
        def do_fix(self, action):
            user_cmds = {
                "av-watch-on": ["systemctl", "--user", "enable", "--now", "devos-av-watch.path",
                                "devos-av-usb.path"],
                "accounts": ["kcmshell5", "kcm_users"],
                "familysafe": [FAMILYSAFE_CLI, "gui"],
                "cleanup": ["/usr/bin/python3", os.path.join(common.COMPONENTS, "optimizer", "optimizer.py"),
                            "--cleanup"],
                "vault": ["/usr/bin/python3", os.path.join(common.COMPONENTS, "settings", "vault.py"), "gui"],
                "restart": ["qdbus", "org.kde.LogoutPrompt", "/LogoutPrompt", "promptReboot"],
            }
            root_cmds = {
                "install-av": ["av", "install"], "av-update": ["av", "update"], "web-on": ["web", "on"],
                "firewall-on": ["firewall", "on"], "updates-on": ["updates", "on"],
                "diskguard-on": ["diskguard", "enable"],
            }
            if action.startswith("page-"):
                self.show_page(action[5:])
            elif action in user_cmds:
                cmd = user_cmds[action]
                if action == "accounts" and not common.which("kcmshell5"):
                    cmd = ["systemsettings5", "kcm_users"]
                common.launch_detached(cmd)
                if action == "av-watch-on":
                    QtCore.QTimer.singleShot(1500, self.refresh)
            elif action in root_cmds:
                self.run_root(root_cmds[action])

        def run_root(self, args):
            proc = QtCore.QProcess(self)
            self.head.setText("Working…")
            self.sub.setText("Asking for an administrator password if needed.")
            proc.finished.connect(lambda code, _s, p=proc: self.root_done(code, p))
            cli = common.CLI if os.path.exists(common.CLI) else os.path.abspath(__file__)
            proc.start("pkexec", [cli] + args)
            self._root_proc = proc

        def root_done(self, code, proc):
            if code in (126, 127):
                self.sub.setText("Cancelled.")
            elif code != 0:
                err = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
                QtWidgets.QMessageBox.warning(self, common.APP_NAME,
                                              "That did not work.\n\n" + (err[-400:] or "Exit code %d" % code))
            self.refresh(check=True)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName(common.APP_NAME)
    app.setDesktopFileName("devos-security")
    font = QtGui.QFont("Inter")
    if not QtGui.QFontInfo(font).exactMatch():
        font = QtGui.QFont("Noto Sans")
    font.setPointSize(10)
    app.setFont(font)
    win = Window(page)
    win.show()
    if os.environ.get("DEVOS_SECURITY_SCREENSHOT"):
        def shot():
            win.grab().save(os.environ["DEVOS_SECURITY_SCREENSHOT"])
            app.quit()
        QtCore.QTimer.singleShot(int(os.environ.get("DEVOS_SECURITY_SCREENSHOT_MS", "2500")), shot)
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
