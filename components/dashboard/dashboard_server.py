#!/usr/bin/env python3
"""
DevOS System Dashboard & First-Boot Setup Controller

- Real hardware telemetry (CPU, RAM, zRAM, storage, boot mode, AI tier)
- PIN & password setup
- Storage & Boot Doctor (real lsblk data; installer tools only on the live USB)
- Local HTTP API on 127.0.0.1:7070, shown in the DevOS app window (devos-webapp),
  never in a browser tab.

Launching:
  dashboard_server.py               open the Dashboard window; start the server first if
                                    nothing answers on 7070 (it never moves to another port)
  dashboard_server.py --no-browser  server only (systemd service / autostart)
"""

import sys
import os
import json
import time
import socket
import shutil
import hashlib
import secrets
import shlex
import platform
import threading
import subprocess
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse
from typing import Dict, Any, List, Optional

# Adjust paths to locate peer components
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(BASE_DIR, "../.."))
COMPONENTS_DIR = os.path.abspath(os.path.join(BASE_DIR, ".."))

sys.path.insert(0, os.path.join(COMPONENTS_DIR, "ai-core"))
sys.path.insert(0, os.path.join(COMPONENTS_DIR, "settings"))
sys.path.insert(0, os.path.join(COMPONENTS_DIR, "devserver"))

try:
    from hardware_detector import HardwareDetector
except ImportError:
    HardwareDetector = None

try:
    from disk_manager import DiskManager, is_live_system
except ImportError:
    DiskManager = None

    def is_live_system(cmdline_path: str = "/proc/cmdline", casper_dir: str = "/run/casper") -> bool:
        if casper_dir and os.path.isdir(casper_dir):
            return True
        try:
            with open(cmdline_path, "r", encoding="utf-8", errors="replace") as fh:
                return "boot=casper" in fh.read().split()
        except OSError:
            return False

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7070
SERVICE_NAME = "devos-dashboard"
APP_ID = "dashboard"
APP_TITLE = "DevOS Dashboard"
APP_ICON = "preferences-system"
APPWINDOW_SCRIPT = os.path.join(COMPONENTS_DIR, "appwindow", "devos_webapp.py")
SECURE_BOOT_VAR = "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
TABS = ("overview", "security", "subsystems", "storage", "firstboot")


class DevOSSecurityManager:
    """Manages PIN and password authentication for DevOS users."""

    CONFIG_DIR = os.path.expanduser("~/.config/devos")
    PIN_FILE = os.path.join(CONFIG_DIR, "pin.auth")
    STATE_FILE = os.path.join(CONFIG_DIR, "first_boot_completed.json")

    def __init__(self):
        os.makedirs(self.CONFIG_DIR, exist_ok=True)

    @classmethod
    def hash_pin(cls, pin: str, salt: str = None) -> Dict[str, str]:
        if salt is None:
            salt = secrets.token_hex(16)
        hashed = hashlib.sha256((salt + pin).encode("utf-8")).hexdigest()
        return {"salt": salt, "hash": hashed}

    def set_pin(self, pin: str) -> Dict[str, Any]:
        """Saves salted PIN hash for fast unlock."""
        if not pin.isdigit() or len(pin) < 4 or len(pin) > 8:
            return {"success": False, "error": "PIN must be between 4 and 8 digits."}

        data = self.hash_pin(pin)
        with open(self.PIN_FILE, "w") as f:
            json.dump(data, f, indent=2)
        try:
            os.chmod(self.PIN_FILE, 0o600)
        except Exception:
            pass

        return {"success": True, "message": "PIN setup successfully."}

    def verify_pin(self, pin: str) -> bool:
        """Verifies entered PIN against saved hash."""
        if not os.path.exists(self.PIN_FILE):
            return False
        try:
            with open(self.PIN_FILE, "r") as f:
                data = json.load(f)
            check = self.hash_pin(pin, salt=data.get("salt"))
            return check["hash"] == data.get("hash")
        except Exception:
            return False

    def is_pin_configured(self) -> bool:
        return os.path.exists(self.PIN_FILE)

    def set_system_password(self, password: str, username: str = None) -> Dict[str, Any]:
        """Sets Unix account password for local user."""
        if len(password) < 4:
            return {"success": False, "error": "Password must be at least 4 characters long."}

        if username is None:
            username = os.environ.get("USER", "devos")

        if os.name != "nt" and os.path.exists("/usr/sbin/chpasswd"):
            try:
                proc = subprocess.run(
                    ["sudo", "chpasswd"],
                    input=f"{username}:{password}".encode("utf-8"),
                    capture_output=True,
                    timeout=5
                )
                if proc.returncode == 0:
                    return {"success": True, "message": f"Password updated for user '{username}'."}
                return {"success": False, "error": "The account password was not changed."}
            except Exception:
                return {"success": False, "error": "The account password was not changed."}

        if os.name == "nt":
            cred_file = os.path.join(self.CONFIG_DIR, "auth_state.json")
            salt = secrets.token_hex(16)
            pw_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
            with open(cred_file, "w") as f:
                json.dump({"user": username, "salt": salt, "hash": pw_hash, "updated_at": time.time()}, f, indent=2)
            return {"success": True, "message": f"Password stored for '{username}' in the local test file."}

        return {"success": False, "error": "The account password was not changed."}


# ---------------------------------------------------------------------------
# Real system facts (each reader takes paths so tests can feed fixtures)
# ---------------------------------------------------------------------------

def read_os_release(path: str = "/etc/os-release") -> Dict[str, str]:
    data: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, val = line.split("=", 1)
                    data[key] = val.strip().strip('"')
    except OSError:
        pass
    return data


def system_identity(os_release_path: str = "/etc/os-release", live: Optional[bool] = None) -> Dict[str, Any]:
    """Name/version for the header badge: 'DevOS 26.04' installed, 'DevOS Live 26.04' on the USB."""
    rel = read_os_release(os_release_path)
    if live is None:
        live = is_live_system()
    name = rel.get("NAME", "DevOS") if rel.get("ID") == "devos" else "DevOS"
    version_id = rel.get("VERSION_ID", "")
    badge = " ".join(p for p in (name, "Live" if live else "", version_id) if p)
    pretty = rel.get("PRETTY_NAME") if rel.get("ID") == "devos" else " ".join(p for p in (name, version_id) if p)
    return {"os_name": name, "version": rel.get("VERSION", version_id), "version_id": version_id,
            "pretty_name": pretty or name, "live": bool(live), "badge": badge}


def read_meminfo(path: str = "/proc/meminfo") -> Optional[Dict[str, int]]:
    try:
        with open(path, "r") as fh:
            values = {}
            for line in fh:
                key, _, rest = line.partition(":")
                parts = rest.split()
                if parts and parts[0].isdigit():
                    values[key.strip()] = int(parts[0])
    except OSError:
        return None
    if "MemTotal" not in values:
        return None
    total_kb = values["MemTotal"]
    avail_kb = values.get("MemAvailable", values.get("MemFree", 0))
    return {"total_mb": total_kb // 1024, "used_mb": (total_kb - avail_kb) // 1024}


def read_zram(swaps_path: str = "/proc/swaps", sys_block: str = "/sys/block") -> Dict[str, Any]:
    """Real zram swap state: active, algorithm, compression ratio (None when unknown)."""
    devices = []
    try:
        with open(swaps_path, "r") as fh:
            for line in fh.readlines()[1:]:
                name = line.split()[0] if line.split() else ""
                if os.path.basename(name).startswith("zram"):
                    devices.append(os.path.basename(name))
    except OSError:
        pass
    if not devices:
        return {"active": False, "algorithm": "", "ratio": None}
    algorithm, orig, compr = "", 0, 0
    for dev in devices:
        try:
            with open(os.path.join(sys_block, dev, "comp_algorithm")) as fh:
                for tok in fh.read().split():
                    if tok.startswith("["):
                        algorithm = tok.strip("[]")
        except OSError:
            pass
        try:
            with open(os.path.join(sys_block, dev, "mm_stat")) as fh:
                cols = fh.read().split()
                orig += int(cols[0])
                compr += int(cols[1])
        except (OSError, IndexError, ValueError):
            pass
    ratio = round(orig / compr, 1) if compr > 0 else None
    return {"active": True, "algorithm": algorithm, "ratio": ratio}


def read_root_fs(mounts_path: str = "/proc/mounts") -> str:
    fstype = ""
    try:
        with open(mounts_path, "r") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 3 and parts[1] == "/":
                    fstype = parts[2]  # last "/" entry wins (overlay on the live USB)
    except OSError:
        pass
    return fstype


def read_cpu_model(path: str = "/proc/cpuinfo") -> str:
    try:
        with open(path, "r") as fh:
            for line in fh:
                if line.lower().startswith(("model name", "hardware", "processor\t: arm")):
                    return " ".join(line.split(":", 1)[1].split())
    except OSError:
        pass
    return platform.processor() or ""


def read_secure_boot(path: str = SECURE_BOOT_VAR) -> Optional[bool]:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        return bool(raw[-1]) if raw else None
    except OSError:
        return None


def read_uptime(path: str = "/proc/uptime") -> Optional[int]:
    try:
        with open(path, "r") as fh:
            return int(float(fh.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return None


def tcp_open(port: int, host: str = "127.0.0.1", timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def systemd_active(unit: str) -> Optional[bool]:
    if not shutil.which("systemctl"):
        return None
    try:
        res = subprocess.run(["systemctl", "is-active", "--quiet", unit], timeout=2)
        return res.returncode == 0
    except Exception:
        return None


class DevOSSystemMetrics:
    """Collects real-time hardware telemetry. Unknown values are None, never made up."""

    _cpu_prev = None
    _cpu_lock = threading.Lock()
    _tier_cache = (0.0, None)
    _desktop_cache = None

    @classmethod
    def _cpu_times(cls):
        try:
            with open("/proc/stat", "r") as fh:
                vals = [int(v) for v in fh.readline().split()[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            return sum(vals), idle
        except (OSError, ValueError, IndexError):
            return None

    @classmethod
    def cpu_percent(cls) -> Optional[float]:
        with cls._cpu_lock:
            now = cls._cpu_times()
            if now is None:
                return None
            prev = cls._cpu_prev
            if prev is None:
                time.sleep(0.15)
                prev, now = now, cls._cpu_times()
            cls._cpu_prev = now
        total, idle = now[0] - prev[0], now[1] - prev[1]
        if total <= 0:
            return 0.0
        return round(100.0 * (total - idle) / total, 1)

    @classmethod
    def ai_tier(cls) -> Optional[str]:
        stamp, value = cls._tier_cache
        if value is not None and time.time() - stamp < 300:
            return value
        tier = None
        if HardwareDetector:
            try:
                tier = HardwareDetector.evaluate_tier().get("tier")
            except Exception:
                tier = None
        cls._tier_cache = (time.time(), tier)
        return tier

    @classmethod
    def desktop(cls) -> str:
        # The footer already says DevOS. The desktop engine is not a public name.
        return ""

    @classmethod
    def get_metrics(cls) -> Dict[str, Any]:
        identity = system_identity()
        mem = read_meminfo()
        zram = read_zram()

        disk = {"total_gb": None, "used_gb": None, "percent": None}
        try:
            stat = os.statvfs("/")
            total_gb = round((stat.f_blocks * stat.f_frsize) / (1024 ** 3), 1)
            free_gb = round((stat.f_bavail * stat.f_frsize) / (1024 ** 3), 1)
            used_gb = round(total_gb - free_gb, 1)
            disk = {"total_gb": total_gb, "used_gb": used_gb,
                    "percent": round((used_gb / total_gb) * 100, 1) if total_gb else None}
        except (AttributeError, OSError):
            pass

        memory = {"total_mb": None, "used_mb": None, "percent": None}
        if mem:
            memory = {"total_mb": mem["total_mb"], "used_mb": mem["used_mb"],
                      "percent": round(mem["used_mb"] / max(mem["total_mb"], 1) * 100, 1)}
        memory.update({"zram_active": zram["active"], "zram_algorithm": zram["algorithm"],
                       "zram_ratio": zram["ratio"]})

        is_uefi = os.path.isdir("/sys/firmware/efi")
        return {
            **identity,
            "kernel": f"{platform.system()} {platform.release()}",
            "hostname": socket.gethostname(),
            "architecture": platform.machine(),
            "cpu_model": read_cpu_model(),
            "cpu_cores": os.cpu_count(),
            "cpu_percent": cls.cpu_percent(),
            "tier": cls.ai_tier(),
            "memory": memory,
            "disk": disk,
            "root_fs": read_root_fs(),
            "snapper": os.path.exists("/etc/snapper/configs/root"),
            "boot_mode": "uefi" if is_uefi else "bios",
            "secure_boot": read_secure_boot() if is_uefi else None,
            "desktop": cls.desktop(),
            "uptime_sec": read_uptime(),
        }

    @staticmethod
    def get_services() -> Dict[str, Any]:
        return {
            "devserver": {"name": "DevServer (Caddy)", "running": systemd_active("caddy")},
            "winlayer": {"name": "WinLayer (Wine)", "installed": bool(shutil.which("wine"))},
            "waydroid": {"name": "Waydroid Android", "installed": bool(shutil.which("waydroid")),
                         "running": systemd_active("waydroid-container")},
            "ai_core": {"name": "DevOS AI (local)", "running": tcp_open(11434)},
            "btrfs_snapper": {"name": "Btrfs snapshots", "configured": os.path.exists("/etc/snapper/configs/root")},
        }


class DevOSDashboardHandler(SimpleHTTPRequestHandler):
    """Serves the dashboard assets and JSON APIs to this computer only."""

    security = DevOSSecurityManager()

    def __init__(self, *args, **kwargs):
        static_dir = os.path.join(BASE_DIR, "static")
        super().__init__(*args, directory=static_dir, **kwargs)

    def log_message(self, fmt, *args):  # keep the journal quiet
        if os.environ.get("DEVOS_DASHBOARD_DEBUG"):
            super().log_message(fmt, *args)

    def _allowed_hosts(self) -> List[str]:
        port = self.server.server_address[1]
        return [f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"]

    def _request_is_local(self) -> bool:
        """Blocks other web sites (CSRF) and DNS rebinding from driving the API."""
        allowed = self._allowed_hosts()
        if self.headers.get("Host", "") not in allowed:
            return False
        origin = self.headers.get("Origin")
        if origin and origin.rstrip("/") not in {f"http://{h}" for h in allowed}:
            return False
        return True

    def _send_json(self, status: int, data: Dict[str, Any]):
        response = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(response)

    def do_OPTIONS(self):
        # No cross-origin access: preflights are refused.
        self.send_response(403)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/") and not self._request_is_local():
            self._send_json(403, {"error": "Forbidden"})
            return

        if path == "/api/ping":
            self._send_json(200, {"app": SERVICE_NAME, "pid": os.getpid()})
            return

        if path == "/api/system/status":
            metrics = DevOSSystemMetrics.get_metrics()
            metrics["pin_configured"] = self.security.is_pin_configured()
            self._send_json(200, metrics)
            return

        elif path == "/api/services/status":
            self._send_json(200, {"services": DevOSSystemMetrics.get_services()})
            return

        elif path == "/api/security/status":
            self._send_json(200, {
                "pin_configured": self.security.is_pin_configured(),
                "user": os.environ.get("USER", "devos")
            })
            return

        elif path == "/api/storage/devices":
            if DiskManager is None:
                self._send_json(500, {"error": "Storage tools are not installed."})
                return
            try:
                self._send_json(200, DiskManager.storage_report())
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        # Serve frontend files
        if path == "/" or path == "/index.html":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if not self._request_is_local():
            self._send_json(403, {"success": False, "error": "Forbidden"})
            return
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self._send_json(415, {"success": False, "error": "Send JSON."})
            return
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"

        try:
            payload = json.loads(body)
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        if path == "/api/setup/pin":
            pin = str(payload.get("pin", ""))
            res = self.security.set_pin(pin)
            status = 200 if res.get("success") else 400
            self._send_json(status, res)
            return

        elif path == "/api/verify/pin":
            pin = str(payload.get("pin", ""))
            valid = self.security.verify_pin(pin)
            self._send_json(200, {"valid": valid})
            return

        elif path == "/api/setup/password":
            password = str(payload.get("password", ""))
            user = payload.get("username")
            res = self.security.set_system_password(password, user)
            status = 200 if res.get("success") else 400
            self._send_json(status, res)
            return

        elif path == "/api/firstboot/complete":
            state = {
                "completed": True,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "locale": payload.get("locale", "en_US.UTF-8"),
                "keyboard": payload.get("keyboard", "us"),
                "pin_enabled": self.security.is_pin_configured(),
                "ai_tier": payload.get("ai_tier") or DevOSSystemMetrics.ai_tier(),
            }
            try:
                with open(self.security.STATE_FILE, "w") as f:
                    json.dump(state, f, indent=2)
            except OSError as e:
                self._send_json(500, {"success": False, "error": str(e)})
                return
            self._send_json(200, {"success": True, "state": state})
            return

        elif path == "/api/actions/launch":
            action = payload.get("action", "")
            cmd_map = {
                "calamares": ["/bin/bash", "/usr/local/bin/devos-install-gui"],
                "chat": ["/usr/local/bin/devos-chat"],
                "terminal": ["konsole"],
                "vscodium": ["devos-code"],
                "code": ["devos-code"],
                "browser": ["devos-browser"],
                "pdf": ["okular"],
                "notepad": ["kwrite"],
                "settings": ["systemsettings"],
                "dolphin": ["dolphin"],
                "files": ["dolphin"],
                "apphub": [sys.executable, os.path.join(COMPONENTS_DIR, "apphub", "hub.py")],
            }
            if action == "calamares" and not is_live_system():
                self._send_json(400, {"success": False, "error": "DevOS is already installed on this PC."})
                return
            if action in cmd_map:
                try:
                    subprocess.Popen(cmd_map[action], start_new_session=True)
                    self._send_json(200, {"success": True, "action": action})
                    return
                except Exception as e:
                    self._send_json(500, {"success": False, "error": str(e)})
                    return
            self._send_json(400, {"success": False, "error": f"Unknown action: {action}"})
            return

        elif path == "/api/storage/action":
            device = str(payload.get("device", ""))
            action = str(payload.get("action", ""))
            if DiskManager is None:
                self._send_json(500, {"success": False, "error": "Storage tools are not installed."})
                return
            try:
                res = DiskManager.apply_solution(device, action)
                status = 200 if res.get("success") else 400
                self._send_json(status, res)
            except Exception as e:
                self._send_json(500, {"success": False, "error": str(e)})
            return

        self._send_json(404, {"error": "Not Found"})


class DashboardHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second server steal a busy port.
    allow_reuse_address = os.name != "nt"


# ---------------------------------------------------------------------------
# Launching: one server on one port, shown in the DevOS app window
# ---------------------------------------------------------------------------

def dashboard_state(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = 1.5) -> Optional[bool]:
    """True: a DevOS dashboard answers. False: another program holds the port. None: nothing listens."""
    if not tcp_open(port, host):
        return None
    try:
        req = urllib.request.Request(f"http://{host}:{port}/api/ping")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8")).get("app") == SERVICE_NAME
    except Exception:
        return False


def dashboard_url(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, tab: Optional[str] = None) -> str:
    url = f"http://{host}:{port}/"
    if tab and tab in TABS and tab != "overview":
        url += f"#{tab}"
    return url


def server_command(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> List[str]:
    return [sys.executable or "python3", os.path.abspath(__file__), "--no-browser", "--host", host, "--port", str(port)]


def window_command(url: str, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, which=shutil.which) -> List[str]:
    launcher = which("devos-webapp")
    base = [launcher] if launcher else [sys.executable or "python3", APPWINDOW_SCRIPT]
    return base + ["--app-id", APP_ID, "--title", APP_TITLE, "--icon", APP_ICON,
                   "--desktop-file", SERVICE_NAME, "--url", url,
                   "--start-cmd", " ".join(shlex.quote(a) for a in server_command(host, port))]


def start_server_background(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, wait: float = 8.0) -> bool:
    log_dir = os.environ.get("XDG_RUNTIME_DIR") or os.path.join(os.path.expanduser("~"), ".cache")
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, "devos-dashboard.log"), "ab") as log:
        subprocess.Popen(server_command(host, port), stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    deadline = time.time() + wait
    while time.time() < deadline:
        if dashboard_state(host, port, timeout=0.5):
            return True
        time.sleep(0.15)
    return False


def notify(message: str):
    print(message, file=sys.stderr)
    if shutil.which("notify-send"):
        try:
            subprocess.Popen(["notify-send", "-i", APP_ICON, APP_TITLE, message])
        except Exception:
            pass


def open_dashboard(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, tab: Optional[str] = None,
                   execvp=os.execvp) -> int:
    """Open the Dashboard window. Reuses the server on `port`; never picks another port."""
    state = dashboard_state(host, port)
    if state is False:
        notify(f"Port {port} is used by another program, so the DevOS Dashboard cannot start.")
        return 1
    if state is None and not start_server_background(host, port):
        if dashboard_state(host, port) is False:
            notify(f"Port {port} is used by another program, so the DevOS Dashboard cannot start.")
            return 1
        # The window still opens; its Retry button starts the server again.
        print(f"DevOS Dashboard server did not answer on {host}:{port} yet.", file=sys.stderr)
    cmd = window_command(dashboard_url(host, port, tab), host, port)
    try:
        execvp(cmd[0], cmd)
    except OSError as exc:
        notify(f"Cannot open the DevOS Dashboard window: {exc}")
        return 1
    return 0


def run_dashboard_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, auto_open: bool = False) -> int:
    """Serve on exactly host:port. If a dashboard already runs there, reuse it."""
    try:
        server = DashboardHTTPServer((host, port), DevOSDashboardHandler)
    except OSError:
        if dashboard_state(host, port):
            print(f"DevOS Dashboard is already running on http://{host}:{port}")
            if auto_open:
                subprocess.Popen(window_command(dashboard_url(host, port), host, port), start_new_session=True)
            return 0
        print(f"ERROR: port {port} on {host} is used by another program.", file=sys.stderr)
        return 1

    print(f"DevOS Dashboard serving on http://{host}:{port}")
    if auto_open:
        subprocess.Popen(window_command(dashboard_url(host, port), host, port), start_new_session=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDevOS Dashboard stopped.")
    finally:
        server.server_close()
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="DevOS Dashboard & First-Boot Controller")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port (default: 7070)")
    parser.add_argument("--no-browser", "--server-only", dest="server_only", action="store_true",
                        help="Only run the server; do not open the Dashboard window")
    parser.add_argument("--first-boot", action="store_true", help="Open the Setup Wizard tab")
    parser.add_argument("--tab", choices=TABS, help="Tab to open")
    args = parser.parse_args(argv)

    if args.server_only:
        return run_dashboard_server(host=args.host, port=args.port, auto_open=False)
    tab = "firstboot" if args.first_boot else args.tab
    return open_dashboard(args.host, args.port, tab)


if __name__ == "__main__":
    sys.exit(main())
