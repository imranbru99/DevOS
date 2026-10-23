#!/usr/bin/env python3
"""
DevOS Share - put an app you are building on the internet with one click.

A dev server such as http://localhost:3000 is only reachable from this
computer. DevOS Share gives it a public https:// address for as long as you
want, with no domain, no account and no router setup.

Most home and mobile connections in Bangladesh sit behind carrier-grade NAT
(the provider shares one public IP between many customers), so "just open a
port" usually cannot work. The default providers are therefore tunnels: this
computer dials out to a relay, and the relay forwards visitors back in.

Providers (tried in this order by "auto"):
  cloudflare  Cloudflare Quick Tunnel (https://<random>.trycloudflare.com).
              cloudflared is downloaded once to ~/.local/share/DevOS/bin.
  ssh         localhost.run over plain SSH (https://<random>.lhr.life).
              Nothing to download, needs openssh-client.
  direct      This computer's own address: always shows the same-Wi-Fi
              (LAN) link, and tries a UPnP port opening on the router for a
              public link, explaining CGNAT when that cannot work.

CLI:
  share.py start <port> [--provider auto|cloudflare|ssh|direct]
  share.py stop <port|all>
  share.py list
  share.py gui            (default)

Shares are recorded in ~/.config/devos/shares.json. Tunnel processes run in
their own session and log to ~/.cache/devos/share-<port>.log, so closing the
window does not take the app offline; the URL is re-read from that log.

Everything above the "GUI" section is plain stdlib and importable without a
display (or on Windows) so it can be unit-tested. PyQt5 and qrcode are
imported lazily.
"""

import argparse
import ipaddress
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

APP_NAME = "DevOS Share"
MB = 1024 * 1024

# Pinned so every DevOS install gets the same, tested cloudflared and so a
# broken upstream release cannot surprise users. Bump deliberately.
CLOUDFLARED_VERSION = "2024.12.2"
CLOUDFLARED_URL = ("https://github.com/cloudflare/cloudflared/releases/download/"
                   "%s/cloudflared-linux-%%s" % CLOUDFLARED_VERSION)
CLOUDFLARED_ARCH = {"x86_64": "amd64", "amd64": "amd64",
                    "aarch64": "arm64", "arm64": "arm64"}

PUBLIC_IP_URL = "https://api.ipify.org"
UPNP_DESCRIPTION = "DevOS"

PROVIDERS = ("cloudflare", "ssh", "direct")
AUTO_ORDER = ("cloudflare", "ssh")
PROVIDER_LABELS = {
    "cloudflare": "Cloudflare tunnel",
    "ssh": "SSH tunnel (localhost.run)",
    "direct": "Direct (my IP)",
}
# How long to wait for a tunnel to print its address. Cloudflare usually
# answers in 3-10 s; slow mobile data can take much longer.
URL_TIMEOUT_S = {"cloudflare": 45, "ssh": 30}

WARNING_TEXT = ("Anyone with this link can open this app while sharing is on. "
                "Do not share apps that show private data.")
BIND_TIP = ("Your app only accepts connections from this computer. For same-Wi-Fi "
            "or direct sharing, restart it so it listens on all addresses, for example "
            "\"npm run dev -- --host\" or \"python manage.py runserver 0.0.0.0:8000\". "
            "Tunnels work either way.")
HOST_TIP = ("If the shared page says the host is not allowed (Vite, webpack, Django), "
            "add the shared address to the app's allowed hosts.")

# Things that listen on this computer but are not apps the user is building.
# cloudflared/ssh are hidden because cloudflared opens its own metrics port.
HIDDEN_PROCESSES = {
    "systemd-resolve", "systemd-resolved", "cupsd", "sshd", "avahi-daemon",
    "chronyd", "dnsmasq", "cloudflared", "ssh", "kdeconnectd", "rpcbind",
    "exim4", "master", "smbd", "nmbd",
}
# The DevOS AI service: putting it online would let strangers use this
# computer's CPU and read the chat, so it is never offered as a share target.
HIDDEN_PORTS = {11434}

FRIENDLY_PROCESS = {
    "node": "Node.js app", "nodejs": "Node.js app", "bun": "Bun app", "deno": "Deno app",
    "python": "Python app", "python3": "Python app", "uvicorn": "Python app",
    "gunicorn": "Python app", "php": "PHP app", "php-fpm": "PHP app",
    "caddy": "Caddy web server", "nginx": "Nginx web server", "apache2": "Apache web server",
    "httpd": "Web server", "ruby": "Ruby app", "rails": "Rails app", "java": "Java app",
    "dotnet": ".NET app", "go": "Go app", "hugo": "Hugo site", "mailpit": "Mailpit inbox",
    "code-server": "Code Server", "jupyter-lab": "Jupyter", "jupyter-notebook": "Jupyter",
}
# Common default ports, used only to make an unnamed listener recognisable.
PORT_HINTS = {
    3000: "React / Next.js / Express", 3001: "Dev server", 4200: "Angular",
    4321: "Astro", 5000: "Flask", 5173: "Vite", 5174: "Vite", 8000: "Django / Laravel / FastAPI",
    8080: "Web app", 8888: "Jupyter", 1313: "Hugo", 4000: "Jekyll / Phoenix",
    8025: "Mailpit", 80: "Local web server", 443: "Local web server (https)",
}


class ShareError(Exception):
    """A failure with a message that can be shown to the user as-is."""


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def home_dir():
    return os.path.expanduser("~")


def state_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home_dir(), ".config")
    return os.path.join(base, "devos", "shares.json")


def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(home_dir(), ".cache")
    return os.path.join(base, "devos")


def log_path(port):
    return os.path.join(cache_dir(), "share-%d.log" % int(port))


def bin_dir():
    return os.path.join(home_dir(), ".local", "share", "DevOS", "bin")


def cloudflared_path():
    return os.path.join(bin_dir(), "cloudflared")


# ---------------------------------------------------------------------------
# Pure parsing helpers (unit-tested)
# ---------------------------------------------------------------------------

# cloudflared prints the address inside a box on stderr. It also mentions
# https://api.trycloudflare.com when the request fails, which is not a tunnel.
_CF_URL_RE = re.compile(r"https://([a-z0-9][a-z0-9-]*)\.trycloudflare\.com\b", re.I)
_CF_NOT_TUNNEL = {"api", "www"}

# localhost.run prints "<id>.lhr.life tunneled with tls termination, https://<id>.lhr.life".
# Its banner also links to docs/admin pages on localhost.run, which are not tunnels.
_SSH_URL_RE = re.compile(r"https://([a-z0-9][a-z0-9.-]*)\.(lhr\.life|lhr\.rocks|localhost\.run)\b", re.I)
_SSH_NOT_TUNNEL = {"admin", "www", "docs", "localhost"}


def parse_cloudflare_url(text):
    """Return the quick-tunnel URL from cloudflared output, or None."""
    found = None
    for m in _CF_URL_RE.finditer(text or ""):
        if m.group(1).lower() not in _CF_NOT_TUNNEL:
            found = "https://%s.trycloudflare.com" % m.group(1).lower()
    return found


def parse_ssh_url(text):
    """Return the newest localhost.run URL from ssh output, or None.

    The newest one wins because localhost.run can hand out a new address when
    the connection drops and comes back."""
    found = None
    for m in _SSH_URL_RE.finditer(text or ""):
        sub, domain = m.group(1).lower(), m.group(2).lower()
        if domain == "localhost.run" and sub.split(".")[0] in _SSH_NOT_TUNNEL:
            continue
        found = "https://%s.%s" % (sub, domain)
    return found


def parse_url(provider, text):
    if provider == "cloudflare":
        return parse_cloudflare_url(text)
    if provider == "ssh":
        return parse_ssh_url(text)
    return None


def explain_failure(provider, text):
    """Turn the tail of a tunnel log into one plain-English sentence."""
    t = (text or "").lower()
    if "could not resolve" in t or "no such host" in t or "temporary failure in name resolution" in t:
        return "This computer could not reach the internet. Check the connection and try again."
    if "429" in t or "too many requests" in t:
        return "Cloudflare is busy right now (too many new tunnels). Wait a minute or try the SSH tunnel."
    if provider == "cloudflare":
        if "failed to request quick tunnel" in t or "failed to dial" in t or "i/o timeout" in t:
            return "Cloudflare did not answer. Check the internet connection, or try the SSH tunnel."
        if "config" in t and "quick tunnel" in t:
            return ("A cloudflared config file in ~/.cloudflared blocks quick tunnels. "
                    "Rename that folder or use the SSH tunnel.")
        return "The Cloudflare tunnel stopped before it was ready. Try again or use the SSH tunnel."
    if provider == "ssh":
        if "connection refused" in t or "connection timed out" in t or "network is unreachable" in t:
            return ("localhost.run could not be reached (some networks block SSH on port 22). "
                    "Try the Cloudflare tunnel.")
        if "permission denied" in t:
            return "localhost.run refused the connection. Try again in a minute or use the Cloudflare tunnel."
        if "remote port forwarding failed" in t:
            return "localhost.run could not open a public address. Try again in a minute."
        return "The SSH tunnel stopped before it was ready. Try again or use the Cloudflare tunnel."
    return "Sharing could not start."


def _split_host_port(addr):
    if ":" not in addr:
        return None, None
    host, _, port = addr.rpartition(":")
    host = host.strip("[]").split("%")[0]
    try:
        return host, int(port)
    except ValueError:
        return None, None


def is_loopback(host):
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def parse_ss(text):
    """Parse `ss -ltnpH` output into one entry per TCP port.

    The same port often appears twice (IPv4 and IPv6); they are merged. A port
    is "local_only" when every address it listens on is a loopback address,
    which is the default for Vite, Next.js and many other dev servers."""
    by_port = {}
    for line in (text or "").splitlines():
        tokens = line.split()
        local = next((t for t in tokens if ":" in t and not t.startswith("users:")), None)
        if not local:
            continue
        host, port = _split_host_port(local)
        if port is None or port <= 0:
            continue
        m = re.search(r'users:\(\("([^"]+)",pid=(\d+)', line)
        entry = by_port.setdefault(port, {"port": port, "addresses": [], "process": "", "pid": None})
        if host not in entry["addresses"]:
            entry["addresses"].append(host)
        if m and not entry["process"]:
            entry["process"], entry["pid"] = m.group(1), int(m.group(2))
    result = []
    for port in sorted(by_port):
        e = by_port[port]
        e["local_only"] = all(is_loopback(h) for h in e["addresses"])
        result.append(e)
    return result


def shareable(listeners):
    """Drop system services so the list shows what the user is building."""
    out = []
    for e in listeners:
        if e["port"] in HIDDEN_PORTS or e["process"] in HIDDEN_PROCESSES:
            continue
        if e["port"] < 1024 and e["port"] not in (80, 443):
            continue
        # 127.0.0.53 / 127.0.0.54 are the DNS stub resolver.
        if all(h.startswith("127.0.0.5") for h in e["addresses"]):
            continue
        out.append(e)
    return out


def describe_server(entry):
    name = FRIENDLY_PROCESS.get(entry.get("process") or "")
    if not name and entry.get("process"):
        name = entry["process"]
    hint = PORT_HINTS.get(entry["port"])
    if name and hint and name.endswith(" app"):
        return "%s (%s)" % (name, hint)
    return name or hint or "App"


def parse_upnpc_external_ip(text):
    m = re.search(r"ExternalIPAddress\s*=\s*([0-9a-fA-F.:]+)", text or "")
    if not m:
        return None
    try:
        return str(ipaddress.ip_address(m.group(1)))
    except ValueError:
        return None


def _is_shared_or_private(ip):
    addr = ipaddress.ip_address(ip)
    # 100.64.0.0/10 is the range set aside for carrier-grade NAT.
    return addr.is_private or addr in ipaddress.ip_network("100.64.0.0/10")


def cgnat_decision(router_ip, public_ip, port=None):
    """Decide whether a router port opening can make this computer public.

    router_ip: the WAN address the router reports over UPnP (None if UPnP failed).
    public_ip: the address the internet sees (None if it could not be checked).
    Returns {"status": ok|cgnat|no_upnp|unknown, "message": str}."""
    port_txt = " %s" % port if port else ""
    if not router_ip:
        return {"status": "no_upnp",
                "message": ("Your router did not accept an automatic port opening (UPnP is off "
                            "or not supported). Use a tunnel instead, or open port%s in your "
                            "router settings." % port_txt)}
    try:
        router_shared = _is_shared_or_private(router_ip)
    except ValueError:
        router_shared = False
    if router_shared or (public_ip and router_ip != public_ip):
        return {"status": "cgnat",
                "message": ("Your internet provider shares one public address between many "
                            "customers (this is called CGNAT), so people on the internet cannot "
                            "reach your computer directly. Use the Cloudflare or SSH tunnel "
                            "instead - they work behind shared addresses.")}
    if not public_ip:
        return {"status": "unknown",
                "message": ("Your router opened the port, but your public address could not be "
                            "checked (is the internet working?). The link may not work.")}
    return {"status": "ok",
            "message": ("Your router opened port%s. People on the internet can use this link "
                        "while this computer is on." % port_txt)}


# ---------------------------------------------------------------------------
# State (~/.config/devos/shares.json)
# ---------------------------------------------------------------------------

def pid_alive(pid, expect=None):
    """True if pid is a running (not zombie) process, optionally named `expect`."""
    if not pid or os.name != "posix":
        # os.kill(pid, 0) on Windows would terminate the process; never call it there.
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except (OSError, ValueError):
        return False
    proc = "/proc/%d" % int(pid)
    if os.path.isdir(proc):
        try:
            with open(proc + "/stat", "r") as fh:
                # Field after "(comm)" is the state; Z means it already exited.
                if fh.read().rpartition(")")[2].split()[0] == "Z":
                    return False
            if expect:
                with open(proc + "/cmdline", "rb") as fh:
                    # A reused pid must not make an old share look alive.
                    if expect.encode() not in fh.read():
                        return False
        except (OSError, IndexError):
            pass
    return True


def share_alive(entry):
    if entry.get("provider") == "direct":
        return True  # no process; the router mapping stays until "Stop"
    return pid_alive(entry.get("pid"), entry.get("proc"))


def clean_shares(shares, alive=share_alive):
    """Keep well-formed entries whose process is still running (one per port)."""
    kept = {}
    for e in shares or []:
        if not isinstance(e, dict):
            continue
        try:
            e["port"] = int(e["port"])
        except (KeyError, TypeError, ValueError):
            continue
        if e.get("provider") not in PROVIDERS:
            continue
        if alive(e):
            kept[e["port"]] = e
    return [kept[p] for p in sorted(kept)]


def read_state(path=None):
    try:
        with open(path or state_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        shares = data.get("shares", []) if isinstance(data, dict) else []
        return shares if isinstance(shares, list) else []
    except (OSError, ValueError):
        return []


def write_state(shares, path=None):
    path = path or state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"shares": shares}, fh, indent=2)
    os.replace(tmp, path)


def load_shares(path=None, alive=share_alive, refresh_urls=True):
    """Read the state file, drop dead shares and pick up URL changes from logs."""
    raw = read_state(path)
    shares = clean_shares([dict(e) for e in raw if isinstance(e, dict)], alive)
    changed = len(shares) != len(raw)
    if refresh_urls:
        for e in shares:
            if e.get("provider") in ("cloudflare", "ssh") and e.get("log"):
                url = parse_url(e["provider"], _read_tail(e["log"]))
                if url and url != e.get("url"):
                    e["url"] = url
                    changed = True
    if changed:
        try:
            write_state(shares, path)
        except OSError:
            pass
    return shares


def _upsert(entry, path=None):
    shares = [e for e in load_shares(path, refresh_urls=False) if e["port"] != entry["port"]]
    shares.append(entry)
    write_state(sorted(shares, key=lambda e: e["port"]), path)


def _read_tail(path, limit=64 * 1024):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - limit))
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# System probes
# ---------------------------------------------------------------------------

def _run(cmd, timeout=10):
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, timeout=timeout)
        return res.returncode, res.stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def list_listeners():
    """Everything listening on TCP here (empty when ss is unavailable)."""
    code, out = _run(["ss", "-ltnpH"], timeout=5)
    return parse_ss(out) if code == 0 else []


def listener_for(port, listeners=None):
    listeners = list_listeners() if listeners is None else listeners
    return next((e for e in listeners if e["port"] == int(port)), None)


def lan_ip():
    """The address other devices on the same Wi-Fi use to reach this computer."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect sends nothing; it only asks the kernel which interface
        # would be used to reach the internet.
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


def public_ip(timeout=8):
    try:
        req = urllib.request.Request(PUBLIC_IP_URL, headers={"User-Agent": "DevOS-Share"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return str(ipaddress.ip_address(resp.read(64).decode().strip()))
    except (OSError, ValueError, urllib.error.URLError):
        return None


# ---------------------------------------------------------------------------
# cloudflared download
# ---------------------------------------------------------------------------

def _cloudflared_works(path):
    if not path or not os.path.isfile(path):
        return False
    code, out = _run([path, "--version"], timeout=20)
    return code == 0 and "cloudflared" in out.lower()


def ensure_cloudflared(progress=None):
    """Return a working cloudflared, downloading the pinned release on first use.

    progress(done_bytes, total_bytes) is called while downloading."""
    path = cloudflared_path()
    if _cloudflared_works(path):
        return path
    system = shutil.which("cloudflared")
    if system and _cloudflared_works(system):
        return system

    arch = CLOUDFLARED_ARCH.get(platform.machine().lower())
    if not arch:
        raise ShareError("The Cloudflare tunnel is not available for this processor. Use the SSH tunnel.")
    url = CLOUDFLARED_URL % arch
    os.makedirs(bin_dir(), exist_ok=True)
    partial = path + ".partial"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "DevOS-Share"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(partial, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        if total and done < total:
            raise ShareError("The download did not finish. Check the internet connection and try again.")
        os.chmod(partial, 0o755)
        # Rename only after a full download so a half file is never run.
        os.replace(partial, path)
    except ShareError:
        _unlink(partial)
        raise
    except (OSError, urllib.error.URLError) as exc:
        _unlink(partial)
        raise ShareError("Could not download the Cloudflare tunnel helper (%s). "
                         "Check the internet connection, or use the SSH tunnel." % _reason(exc))
    if not _cloudflared_works(path):
        _unlink(path)
        raise ShareError("The downloaded Cloudflare helper did not start. Try again or use the SSH tunnel.")
    return path


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def _reason(exc):
    return str(getattr(exc, "reason", None) or exc)


# ---------------------------------------------------------------------------
# Starting and stopping shares
# ---------------------------------------------------------------------------

# Popen objects started by this process, kept so they can be reaped (no zombies
# while the GUI stays open) and so Python does not warn about them on exit.
_CHILDREN = {}


def tunnel_command(provider, port, cloudflared=None):
    target = "localhost:%d" % int(port)
    if provider == "cloudflare":
        return [cloudflared or cloudflared_path(), "tunnel", "--no-autoupdate",
                "--url", "http://" + target]
    if provider == "ssh":
        return ["ssh", "-T",
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ServerAliveInterval=30",
                "-o", "ExitOnForwardFailure=yes",
                "-R", "80:" + target, "nokey@localhost.run"]
    raise ValueError(provider)


def _start_tunnel(provider, port, progress=None, timeout=None):
    if provider == "cloudflare":
        exe = ensure_cloudflared(progress)
        proc_name = "cloudflared"
    else:
        exe = shutil.which("ssh")
        if not exe:
            raise ShareError("The SSH tunnel needs openssh-client, which is not installed.")
        proc_name = "ssh"
    cmd = tunnel_command(provider, port, exe if provider == "cloudflare" else None)
    log = log_path(port)
    os.makedirs(os.path.dirname(log), exist_ok=True)
    # Truncate so an address from an earlier run is never mistaken for this one.
    with open(log, "wb") as out:
        child = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                 start_new_session=True, close_fds=True)
    _CHILDREN[child.pid] = child

    deadline = time.time() + (timeout or URL_TIMEOUT_S[provider])
    while time.time() < deadline:
        text = _read_tail(log)
        url = parse_url(provider, text)
        if url:
            return {"port": int(port), "provider": provider, "url": url, "pid": child.pid,
                    "proc": proc_name, "log": log, "started": int(time.time())}
        if child.poll() is not None:
            raise ShareError(explain_failure(provider, text))
        time.sleep(0.3)
    _kill(child.pid)
    raise ShareError(explain_failure(provider, _read_tail(log)) if provider == "ssh" else
                     "The Cloudflare tunnel took too long to start. Try again or use the SSH tunnel.")


def _start_direct(port, listener):
    port = int(port)
    lan = lan_ip()
    lan_url = "http://%s:%d" % (lan, port) if lan else None
    notes = []
    if listener and listener["local_only"]:
        notes.append(BIND_TIP)
    entry = {"port": port, "provider": "direct", "url": lan_url, "lan_url": lan_url, "pid": None,
             "upnp": False, "started": int(time.time())}

    if not shutil.which("upnpc"):
        notes.append("The router helper (miniupnpc) is not installed, so only the same-Wi-Fi "
                     "link is available. Use a tunnel for a public link.")
        entry["message"] = " ".join(notes)
        return entry

    code, _ = _run(["upnpc", "-e", UPNP_DESCRIPTION, "-r", str(port), "TCP"], timeout=20)
    router = None
    if code == 0:
        _, status = _run(["upnpc", "-s"], timeout=15)
        router = parse_upnpc_external_ip(status)
    decision = cgnat_decision(router, public_ip() if router else None, port)
    if decision["status"] in ("ok", "unknown") and router:
        entry["upnp"] = True
        entry["url"] = "http://%s:%d" % (router, port)
    elif code == 0:
        # The mapping cannot help behind CGNAT; do not leave a hole in the router.
        _run(["upnpc", "-d", str(port), "TCP"], timeout=15)
    notes.insert(0, decision["message"])
    entry["status"] = decision["status"]
    entry["message"] = " ".join(notes)
    return entry


def start_share(port, provider="auto", progress=None):
    """Share a local port. Returns the saved share entry (with "url").

    Extra keys for display only: "warnings" (list of str), "message" (direct mode)."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ShareError("Enter a port number such as 3000.")
    if not 1 <= port <= 65535:
        raise ShareError("Port numbers go from 1 to 65535.")
    provider = provider or "auto"
    if provider != "auto" and provider not in PROVIDERS:
        raise ShareError("Unknown sharing method '%s'." % provider)

    for e in load_shares():
        if e["port"] == port and (provider in ("auto", e["provider"])):
            e["warnings"] = ["Port %d is already shared." % port]
            return e
        if e["port"] == port:
            stop_share(port)

    warnings = []
    listener = listener_for(port)
    if listener is None and shutil.which("ss"):
        warnings.append("Nothing is running on port %d yet. Start your app, or the link will "
                        "show an error page." % port)

    if provider == "direct":
        entry = _start_direct(port, listener)
    else:
        order = AUTO_ORDER if provider == "auto" else (provider,)
        errors = []
        entry = None
        for p in order:
            try:
                entry = _start_tunnel(p, port, progress)
                break
            except ShareError as exc:
                errors.append(str(exc))
        if entry is None:
            raise ShareError(errors[0] if len(errors) == 1 else
                             "No tunnel could start. " + " ".join(errors))

    stored = {k: v for k, v in entry.items() if k not in ("warnings",)}
    _upsert(stored)
    entry["warnings"] = warnings
    return entry


def _kill(pid):
    """Stop a tunnel and everything in its session; it was started as a group leader."""
    if not pid or os.name != "posix":
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(int(pid), sig)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(int(pid), sig)
            except OSError:
                break
        except OSError:
            break
        for _ in range(20):
            child = _CHILDREN.get(pid)
            if child is not None and child.poll() is not None:
                _CHILDREN.pop(pid, None)
                return
            if child is None and not pid_alive(pid):
                return
            time.sleep(0.1)


def stop_share(port):
    """Stop one share. Returns True if something was shared on that port."""
    port = int(port)
    shares = read_state()
    entry = next((e for e in shares if isinstance(e, dict) and str(e.get("port")) == str(port)), None)
    if entry is None:
        return False
    if entry.get("provider") == "direct":
        if entry.get("upnp") and shutil.which("upnpc"):
            _run(["upnpc", "-d", str(port), "TCP"], timeout=15)
    elif share_alive(entry):
        _kill(entry.get("pid"))
    write_state([e for e in shares if e is not entry])
    return True


def stop_all():
    stopped = []
    for e in read_state():
        if isinstance(e, dict) and "port" in e and stop_share(e["port"]):
            stopped.append(e["port"])
    return stopped


def reap_children():
    for pid, child in list(_CHILDREN.items()):
        if child.poll() is not None:
            _CHILDREN.pop(pid, None)


def age_text(started):
    mins = max(0, int(time.time() - (started or time.time())) // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return "for %d min" % mins
    return "for %d h %d min" % (mins // 60, mins % 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_progress():
    last = [0.0]

    def report(done, total):
        now = time.time()
        if now - last[0] >= 0.5 or (total and done >= total):
            last[0] = now
            # Same "[Downloading] X MB/Y MB" shape as devos-ai-upgrade.
            print("[Downloading] %.1f MB/%.1f MB" % (done / MB, total / MB), file=sys.stderr, flush=True)
    return report


def cmd_start(port, provider):
    try:
        entry = start_share(port, provider, progress=_cli_progress())
    except ShareError as exc:
        print("Could not share port %s: %s" % (port, exc), file=sys.stderr)
        return 1
    for w in entry.get("warnings", []):
        print("Note: " + w, file=sys.stderr)
    if entry.get("message"):
        print(entry["message"], file=sys.stderr)
    if entry.get("lan_url") and entry.get("lan_url") != entry.get("url"):
        print("Same Wi-Fi: " + entry["lan_url"], file=sys.stderr)
    print(WARNING_TEXT, file=sys.stderr)
    if not entry.get("url"):
        print("No link is available (this computer is not on a network).", file=sys.stderr)
        return 1
    # The URL alone on stdout so scripts can capture it.
    print(entry["url"])
    return 0


def cmd_stop(target):
    if target == "all":
        stopped = stop_all()
        print("Stopped sharing %d app(s)." % len(stopped))
        return 0
    try:
        port = int(target)
    except ValueError:
        print("Use a port number or 'all'.", file=sys.stderr)
        return 2
    if stop_share(port):
        print("Port %d is no longer shared." % port)
        return 0
    print("Port %d was not shared." % port, file=sys.stderr)
    return 1


def cmd_list():
    shares = load_shares()
    if not shares:
        print("Nothing is shared right now.")
        return 0
    print("%-7s %-28s %-14s %s" % ("PORT", "METHOD", "SINCE", "LINK"))
    for e in shares:
        print("%-7d %-28s %-14s %s" % (e["port"], PROVIDER_LABELS.get(e["provider"], e["provider"]),
                                      age_text(e.get("started")), e.get("url") or "-"))
    return 0


# ---------------------------------------------------------------------------
# GUI (PyQt5 + qrcode, imported lazily)
# ---------------------------------------------------------------------------

STYLE = """
QWidget#root { background: #0b0f1a; }
QWidget { color: #e5e7eb; font-family: "Inter", "Noto Sans", sans-serif; font-size: 10.5pt; }
QFrame#card { background: #111827; border-radius: 12px; border: 1px solid #1f2937; }
QLabel { background: transparent; }
QLabel#title { font-size: 18pt; font-weight: 600; color: #f9fafb; }
QLabel#muted { color: #9ca3af; font-size: 9.5pt; }
QLabel#section { color: #9ca3af; font-size: 9pt; font-weight: 600; letter-spacing: 1px; }
QLabel#warn { color: #fbbf24; background: #1c1917; border: 1px solid #44403c;
  border-radius: 10px; padding: 10px; }
QLabel#url { color: #38bdf8; font-size: 11.5pt; font-weight: 600; }
QLabel#name { color: #f3f4f6; font-weight: 600; }
QLabel#status { color: #cbd5e1; }
QPushButton { background: #1f2937; color: #e5e7eb; border: none; border-radius: 10px;
  padding: 7px 14px; }
QPushButton:hover { background: #273449; }
QPushButton:disabled { color: #6b7280; }
QPushButton#primary { background: #38bdf8; color: #0b0f1a; font-weight: 600; }
QPushButton#primary:hover { background: #7dd3fc; }
QPushButton#primary:disabled { background: #1e3a4a; color: #6b7280; }
QPushButton#danger { background: #3f1d24; color: #fecaca; }
QPushButton#danger:hover { background: #5b2530; }
QComboBox, QSpinBox { background: #111827; color: #e5e7eb; border: 1px solid #1f2937;
  border-radius: 8px; padding: 5px 8px; }
QComboBox QAbstractItemView { background: #111827; color: #e5e7eb;
  selection-background-color: #1e3a4a; }
QProgressBar { background: #1f2937; border: none; border-radius: 4px; max-height: 8px; }
QProgressBar::chunk { background: #38bdf8; border-radius: 4px; }
QScrollArea { background: transparent; border: none; }
"""


def qr_matrix(text):
    """QR modules (True = dark) including the quiet zone, or None without python3-qrcode."""
    try:
        import qrcode
    except ImportError:
        return None
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    return qr.get_matrix()


def run_gui():
    from PyQt5 import QtCore, QtGui, QtWidgets

    class Worker(QtCore.QThread):
        progress = QtCore.pyqtSignal(object, object)
        done = QtCore.pyqtSignal(object, str)

        def __init__(self, fn, parent=None):
            super().__init__(parent)
            self.fn = fn

        def run(self):
            try:
                self.done.emit(self.fn(lambda d, t: self.progress.emit(d, t)), "")
            except ShareError as exc:
                self.done.emit(None, str(exc))
            except Exception as exc:  # keep the window alive on surprises
                self.done.emit(None, "Something went wrong: %s" % exc)

    class QrWidget(QtWidgets.QWidget):
        def __init__(self, text, size=132, parent=None):
            super().__init__(parent)
            self.matrix = qr_matrix(text)
            self.setFixedSize(size, size)
            self.setToolTip("Scan with your phone camera to open the link")

        def paintEvent(self, _event):
            p = QtGui.QPainter(self)
            p.fillRect(self.rect(), QtGui.QColor("#ffffff"))
            if not self.matrix:
                p.setPen(QtGui.QColor("#111827"))
                p.drawText(self.rect(), QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap,
                           "QR code\nnot available")
                return
            n = len(self.matrix)
            cell = self.width() / float(n)
            black = QtGui.QColor("#000000")
            for y, row in enumerate(self.matrix):
                for x, dark in enumerate(row):
                    if dark:
                        # Round edges outward so neighbouring modules never leave hairline gaps.
                        p.fillRect(QtCore.QRectF(x * cell, y * cell, cell + 0.6, cell + 0.6), black)

    def card():
        frame = QtWidgets.QFrame()
        frame.setObjectName("card")
        frame.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        return frame

    def label(text, name=None, wrap=False):
        lab = QtWidgets.QLabel(text)
        if name:
            lab.setObjectName(name)
        lab.setWordWrap(wrap)
        return lab

    def clear(layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    class ShareWindow(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setObjectName("root")
            self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
            self.setWindowTitle(APP_NAME)
            self.setWindowIcon(QtGui.QIcon.fromTheme("network-workgroup"))
            self.setMinimumSize(640, 720)
            self.setStyleSheet(STYLE)
            self.worker = None
            self.last_servers = None
            self.last_shares = None

            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(24, 22, 24, 18)
            outer.setSpacing(12)
            outer.addWidget(label("DevOS Share", "title"))
            outer.addWidget(label("Put an app you are building on the internet for a while. "
                                  "No domain, no account, no router setup.", "muted", True))
            outer.addWidget(label(WARNING_TEXT, "warn", True))

            method = QtWidgets.QHBoxLayout()
            method.addWidget(label("Sharing method"))
            self.provider = QtWidgets.QComboBox()
            self.provider.addItem("Automatic (recommended)", "auto")
            for key in PROVIDERS:
                self.provider.addItem(PROVIDER_LABELS[key], key)
            self.provider.setToolTip("Tunnels work on any connection. Direct needs a router "
                                     "that gives you your own public address.")
            method.addWidget(self.provider, 1)
            outer.addLayout(method)

            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            body = QtWidgets.QWidget()
            body.setStyleSheet("background: transparent;")
            self.body = QtWidgets.QVBoxLayout(body)
            self.body.setContentsMargins(0, 0, 0, 0)
            self.body.setSpacing(10)

            self.body.addWidget(label("SHARED NOW", "section"))
            self.shares_box = QtWidgets.QVBoxLayout()
            self.shares_box.setSpacing(10)
            self.body.addLayout(self.shares_box)

            self.body.addSpacing(6)
            self.body.addWidget(label("APPS RUNNING ON THIS COMPUTER", "section"))
            self.servers_box = QtWidgets.QVBoxLayout()
            self.servers_box.setSpacing(8)
            self.body.addLayout(self.servers_box)

            other = card()
            row = QtWidgets.QHBoxLayout(other)
            row.setContentsMargins(14, 10, 14, 10)
            row.addWidget(label("Another port", "name"))
            self.port_spin = QtWidgets.QSpinBox()
            self.port_spin.setRange(1, 65535)
            self.port_spin.setValue(3000)
            row.addWidget(self.port_spin)
            row.addStretch(1)
            self.other_btn = QtWidgets.QPushButton("Make public")
            self.other_btn.setObjectName("primary")
            self.other_btn.clicked.connect(lambda: self.start(self.port_spin.value()))
            row.addWidget(self.other_btn)
            self.body.addWidget(other)
            self.body.addWidget(label(HOST_TIP, "muted", True))
            self.body.addStretch(1)
            scroll.setWidget(body)
            outer.addWidget(scroll, 1)

            self.progress = QtWidgets.QProgressBar()
            self.progress.setTextVisible(False)
            self.progress.hide()
            outer.addWidget(self.progress)
            self.status = label("", "status", True)
            outer.addWidget(self.status)

            self.refresh(force=True)
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.refresh)
            self.timer.start(4000)

        # -- data -----------------------------------------------------------
        def refresh(self, force=False):
            reap_children()
            servers = shareable(list_listeners())
            shares = load_shares()
            # Rebuild only on change so a click is never lost to a redraw.
            srv_key = [(s["port"], s["process"], s["local_only"]) for s in servers]
            sh_key = [(s["port"], s["provider"], s.get("url")) for s in shares]
            busy = self.worker is not None
            if force or srv_key != self.last_servers or sh_key != self.last_shares:
                self.last_servers, self.last_shares = srv_key, sh_key
                self.render(servers, shares, busy)

        def render(self, servers, shares, busy):
            clear(self.shares_box)
            clear(self.servers_box)
            shared_ports = {s["port"] for s in shares}
            if not shares:
                self.shares_box.addWidget(label("Nothing is shared. Pick an app below and press "
                                                "\"Make public\".", "muted", True))
            for s in shares:
                self.shares_box.addWidget(self.share_card(s))
            if not servers:
                self.servers_box.addWidget(label("No running apps found. Start your app (for example "
                                                 "\"npm run dev\") or type its port below.",
                                                 "muted", True))
            for srv in servers:
                self.servers_box.addWidget(self.server_card(srv, srv["port"] in shared_ports, busy))
            self.other_btn.setEnabled(not busy)

        def server_card(self, srv, shared, busy):
            frame = card()
            row = QtWidgets.QHBoxLayout(frame)
            row.setContentsMargins(14, 10, 14, 10)
            text = QtWidgets.QVBoxLayout()
            text.addWidget(label("%s  ·  port %d" % (describe_server(srv), srv["port"]), "name"))
            where = ("Only this computer can open it now" if srv["local_only"]
                     else "Open to this computer and your network")
            text.addWidget(label("http://localhost:%d  ·  %s" % (srv["port"], where), "muted"))
            row.addLayout(text, 1)
            btn = QtWidgets.QPushButton("Shared" if shared else "Make public")
            btn.setObjectName("primary")
            btn.setEnabled(not shared and not busy)
            btn.clicked.connect(lambda _=False, p=srv["port"]: self.start(p))
            row.addWidget(btn)
            return frame

        def share_card(self, s):
            frame = card()
            row = QtWidgets.QHBoxLayout(frame)
            row.setContentsMargins(14, 12, 14, 12)
            row.setSpacing(14)
            url = s.get("url") or ""
            if url:
                row.addWidget(QrWidget(url))
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(6)
            col.addWidget(label("Port %d  ·  %s  ·  %s" % (
                s["port"], PROVIDER_LABELS.get(s["provider"], s["provider"]),
                age_text(s.get("started"))), "muted"))
            link = label(url or "No link yet", "url", True)
            link.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            col.addWidget(link)
            if s.get("lan_url") and s.get("lan_url") != url:
                col.addWidget(label("Same Wi-Fi: " + s["lan_url"], "muted", True))
            if s.get("message"):
                col.addWidget(label(s["message"], "muted", True))
            btns = QtWidgets.QHBoxLayout()
            copy = QtWidgets.QPushButton("Copy link")
            copy.setObjectName("primary")
            copy.setEnabled(bool(url))
            copy.clicked.connect(lambda _=False, u=url: self.copy(u))
            open_btn = QtWidgets.QPushButton("Open")
            open_btn.setEnabled(bool(url))
            open_btn.clicked.connect(lambda _=False, u=url:
                                     QtGui.QDesktopServices.openUrl(QtCore.QUrl(u)))
            stop = QtWidgets.QPushButton("Stop")
            stop.setObjectName("danger")
            stop.clicked.connect(lambda _=False, p=s["port"]: self.stop(p))
            for b in (copy, open_btn, stop):
                btns.addWidget(b)
            btns.addStretch(1)
            col.addLayout(btns)
            col.addStretch(1)
            row.addLayout(col, 1)
            return frame

        # -- actions --------------------------------------------------------
        def copy(self, url):
            QtWidgets.QApplication.clipboard().setText(url)
            self.status.setText("Link copied. Paste it in a chat or open it on your phone.")

        def run_worker(self, fn, on_done):
            self.worker = Worker(fn, self)
            self.worker.progress.connect(self.on_progress)
            self.worker.done.connect(on_done)
            self.refresh(force=True)
            self.worker.start()

        def start(self, port):
            if self.worker is not None:
                return
            provider = self.provider.currentData()
            if provider == "direct":
                listener = listener_for(port)
                if listener and listener["local_only"]:
                    QtWidgets.QMessageBox.information(self, APP_NAME, BIND_TIP)
            self.status.setText("Making port %d public…" % port)
            self.run_worker(lambda prog: start_share(port, provider, progress=prog), self.on_started)

        def stop(self, port):
            if self.worker is not None:
                return
            self.status.setText("Stopping…")
            self.run_worker(lambda _prog: stop_share(port) and {"stopped": port}, self.on_stopped)

        def on_progress(self, done, total):
            self.progress.show()
            if total:
                self.progress.setRange(0, 1000)
                self.progress.setValue(int(1000 * done / total))
            else:
                self.progress.setRange(0, 0)
            self.status.setText("Downloading the Cloudflare tunnel helper (one time): %.1f of %.1f MB"
                                % (done / MB, (total or 0) / MB))

        def finish(self):
            self.worker = None
            self.progress.hide()
            self.refresh(force=True)

        def on_started(self, entry, error):
            self.finish()
            if error:
                self.status.setText(error)
                return
            notes = list(entry.get("warnings") or [])
            if entry.get("url") and entry.get("provider") != "direct":
                QtWidgets.QApplication.clipboard().setText(entry["url"])
                notes.insert(0, "Your app is online. The link is copied.")
            elif entry.get("provider") == "direct":
                notes.insert(0, "Direct sharing is on.")
            self.status.setText(" ".join(notes))

        def on_stopped(self, _result, error):
            self.finish()
            self.status.setText(error or "Sharing stopped. The link no longer works.")

        def closeEvent(self, event):
            shares = load_shares(refresh_urls=False)
            if shares:
                # Tunnels deliberately keep running; say so, so nobody is surprised.
                QtWidgets.QMessageBox.information(
                    self, APP_NAME, "%d app(s) stay shared after this window closes. Open DevOS "
                    "Share again and press Stop to end sharing." % len(shares))
            event.accept()

    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setApplicationName("devos-share")
    qapp.setApplicationDisplayName("DevOS Share")
    qapp.setDesktopFileName("devos-share")
    font = QtGui.QFont("Inter")
    if not QtGui.QFontInfo(font).exactMatch():
        font = QtGui.QFont("Noto Sans")
    qapp.setFont(font)
    win = ShareWindow()
    win.show()
    signal.signal(signal.SIGINT, lambda *_: qapp.quit())
    return qapp.exec_()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="share.py", description=APP_NAME)
    sub = parser.add_subparsers(dest="command")
    start_p = sub.add_parser("start", help="share a local port and print the public link")
    start_p.add_argument("port", type=int)
    start_p.add_argument("--provider", default="auto", choices=("auto",) + PROVIDERS)
    stop_p = sub.add_parser("stop", help="stop sharing a port, or 'all'")
    stop_p.add_argument("target")
    sub.add_parser("list", help="show what is shared now")
    sub.add_parser("gui", help="open the DevOS Share window (default)")
    args = parser.parse_args(argv)

    if args.command == "start":
        return cmd_start(args.port, args.provider)
    if args.command == "stop":
        return cmd_stop(args.target)
    if args.command == "list":
        return cmd_list()
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
