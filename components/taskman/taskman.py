#!/usr/bin/env python3
"""
DevOS Task Manager — the Windows Task Manager pages, with real numbers.

  Processes     apps and background processes (CPU, memory, disk)
  Performance   CPU, memory, disks, network and GPU
  App history   CPU time since this PC started recording
  Startup apps  turn a login program on or off
  Users         one row per signed-in account
  Details       every process: PID, user, architecture
  Services      systemd services, start and stop

Ctrl+Shift+Esc opens this window. Nothing here is estimated: a value that
cannot be read (per-process network, a GPU with no sensor) stays blank.

CLI:
  taskman.py                 open the window
  taskman.py --json          print one snapshot
  taskman.py --sample        record app-history CPU time and exit
  taskman.py end PID         end that process
  taskman.py run COMMAND...  start a program
  taskman.py startup         list login programs
  taskman.py startup disable FILE.desktop
  taskman.py startup enable FILE.desktop
  taskman.py services
  taskman.py service start NAME
  taskman.py service stop NAME
  taskman.py history-clear
"""

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time

APP_NAME = "Task Manager"
HISTORY_NAME = "taskman-history.json"
CLK_DEFAULT = 100
PAGE_DEFAULT = 4096

# Ending these would take down the desktop or the session.
PROTECTED = {
    "systemd", "init", "plasmashell", "kwin_x11", "kwin_wayland", "kwin",
    "xorg", "Xorg", "X", "sddm", "sddm-helper", "sddm-greeter",
    "pipewire", "pipewire-pulse", "wireplumber", "pulseaudio",
    "dbus-daemon", "dbus-broker", "systemd-logind", "polkitd",
}

# Has a display, but it is a helper, not an app the person opened.
NON_APP = {
    "bash", "sh", "zsh", "dash", "fish", "sleep", "cat", "sd-pam",
    "dbus-daemon", "dbus-broker", "at-spi-bus-launcher", "at-spi-bus-laun",
    "at-spi2-registryd", "at-spi2-registr",
    "xdg-desktop-portal", "xdg-desktop-por", "xdg-desktop-portal-kde", "xdg-dbus-proxy",
    "xdg-document-portal", "xdg-document-po", "xdg-permission-store", "xdg-permission-",
    "kded5", "kded6", "kiod5", "kioworker", "kioslave5", "dconf-service", "gvfsd", "obexd",
    "ksystemstats", "fusermount", "fusermount3", "kaccess", "kglobalaccel5", "kglobalaccel6",
    "xembedsniproxy", "gmenudbusmenuproxy", "gmenudbusmenupr", "agent", "ssh-agent", "gpg-agent",
    "kactivitymanagerd", "kactivitymanage", "ksmserver", "kscreen_backend_launcher",
    "kscreen_backend", "ibus-extension-gtk3", "ibus-extension-", "ibus-ui-gtk3", "ibus-x11",
    "ibus-portal", "ibus-dconf", "ibus-engine-simple", "ibus-engine-sim",
    "speech-dispatcher", "speech-dispatch", "language_server",
    "startplasma-x11", "startplasma-wayland", "devos-session", "ibus-daemon",
    "chrome_crashpad_handler", "chrome_crashpad", "optimizer.py", "optimizer",
}

# Count as an app even when another user's environment cannot be read.
KNOWN_GUI = {
    "chrome", "google-chrome", "chromium", "chromium-browser", "firefox",
    "firefox-bin", "code", "codium", "cursor", "plasmashell", "dolphin",
    "konsole", "kate", "okular", "gimp", "soffice.bin", "vlc", "spotify",
    "telegram-desktop", "discord", "steam", "systemsettings",
    "taskman.py", "devos-taskman", "devos-files", "devos-terminal",
    "devos-settings", "devos-ai-code-agent",
}

PRETTY = {
    "chrome": "Google Chrome", "google-chrome": "Google Chrome",
    "chromium": "Chromium", "chromium-browser": "Chromium",
    "firefox": "Firefox", "firefox-bin": "Firefox",
    "code": "Visual Studio Code", "codium": "VSCodium", "cursor": "Cursor",
    "plasmashell": "Desktop", "dolphin": "Files", "konsole": "Terminal",
    "kate": "Text Editor", "okular": "Document Viewer", "gimp": "GIMP",
    "soffice.bin": "LibreOffice", "vlc": "VLC", "spotify": "Spotify",
    "telegram-desktop": "Telegram", "discord": "Discord", "steam": "Steam",
    "systemsettings": "Settings", "kwin_x11": "Window manager",
    "kwin_wayland": "Window manager",
    "taskman.py": "Task Manager", "devos-taskman": "Task Manager", "taskman": "Task Manager",
    "devos-files": "Files", "devos-terminal": "Terminal",
    "devos-settings": "Settings", "devos-ai-code-agent": "AI Code Agent",
}

STATE_NAMES = {
    "R": "Running", "S": "Sleeping", "D": "Disk sleep", "Z": "Zombie",
    "T": "Stopped", "t": "Tracing", "I": "Idle", "X": "Dead",
}

ELF_MACHINES = {3: "x86", 62: "x64", 40: "arm", 183: "arm64"}
GPU_VENDORS = {"0x8086": "Intel", "0x10de": "NVIDIA", "0x1002": "AMD", "0x1af4": "Virtio"}

UNIT_NAME = re.compile(r"[A-Za-z0-9:@._\\-]{1,200}\Z")
DESKTOP_NAME = re.compile(r"[A-Za-z0-9._@+-]+\.desktop\Z")


def clock_ticks():
    try:
        return int(os.sysconf("SC_CLK_TCK")) or CLK_DEFAULT
    except (AttributeError, ValueError, OSError):
        return CLK_DEFAULT


def page_size():
    try:
        return int(os.sysconf("SC_PAGE_SIZE")) or PAGE_DEFAULT
    except (AttributeError, ValueError, OSError):
        return PAGE_DEFAULT


def current_uid():
    for name in ("geteuid", "getuid"):
        fn = getattr(os, name, None)
        if not fn:
            continue
        try:
            return int(fn())
        except (AttributeError, OSError):
            continue
    return None


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def read_bytes(path, count=64):
    try:
        with open(path, "rb") as handle:
            return handle.read(count)
    except OSError:
        return b""


def parse_stat(text):
    """One /proc/<pid>/stat line. The name may contain spaces and parentheses."""
    text = (text or "").strip()
    left = text.find("(")
    right = text.rfind(")")
    if left < 1 or right < left:
        return None
    pid_text = text[:left].strip()
    rest = text[right + 1:].split()
    if not pid_text.isdigit() or len(rest) < 22:
        return None

    def num(index):
        try:
            return int(rest[index])
        except ValueError:
            return 0

    return {
        "pid": int(pid_text),
        "comm": text[left + 1:right],
        "state": rest[0],
        "ppid": num(1),
        "utime": num(11),
        "stime": num(12),
        "threads": num(17),
        "starttime": num(19),
        "rss_pages": num(21),
    }


def parse_status(text):
    uid, rss_kb = None, None
    for line in (text or "").splitlines():
        if line.startswith("Uid:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                uid = int(parts[1])
        elif line.startswith("VmRSS:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                rss_kb = int(parts[1])
    return uid, rss_kb


def parse_io(text):
    read_b = write_b = 0
    for line in (text or "").splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if value.isdigit():
            if key == "read_bytes":
                read_b = int(value)
            elif key == "write_bytes":
                write_b = int(value)
    return read_b + write_b


def parse_cmdline(raw):
    return [part for part in (raw or "").split("\0") if part]


def has_display(raw):
    for part in (raw or "").split("\0"):
        if part.startswith("DISPLAY=") and len(part) > len("DISPLAY="):
            return True
        if part.startswith("WAYLAND_DISPLAY=") and len(part) > len("WAYLAND_DISPLAY="):
            return True
    return False


def elf_arch(header):
    if not header or len(header) < 20 or header[:4] != b"\x7fELF":
        return ""
    machine = int.from_bytes(header[18:20], "little")
    return ELF_MACHINES.get(machine, "")


def pretty_name(comm):
    if comm in PRETTY:
        return PRETTY[comm]
    if not comm:
        return "Process"
    return comm[0].upper() + comm[1:]


def state_name(code):
    return STATE_NAMES.get(code or "", code or "")


def classify(proc):
    if not proc["cmdline"]:
        return "kernel"
    name_lower = (proc.get("name") or "").lower()
    comm_lower = (proc.get("comm") or "").lower()
    if comm_lower in NON_APP or name_lower in NON_APP:
        return "background"
    if comm_lower in KNOWN_GUI or name_lower in KNOWN_GUI:
        return "app"
    if proc["display"]:
        return "app"
    return "background"


def extract_script_name(cmdline):
    if not cmdline or len(cmdline) < 2:
        return None
    for i, arg in enumerate(cmdline[1:], 1):
        if arg in ("-c",):
            return None
        if arg == "-m" and i < len(cmdline) - 1:
            mod = cmdline[i + 1]
            if mod and not mod.startswith("-") and "\n" not in mod and len(mod) < 256:
                return mod
            return None
        if not arg.startswith("-") and "\n" not in arg and len(arg) < 256:
            if arg.endswith((".py", ".js", ".sh", ".pl", ".rb")) or ("/" in arg and not arg.endswith("/")):
                base = os.path.basename(arg)
                if base:
                    return base
            break
    return None


def description_of(proc):
    if proc["cmdline"]:
        base = os.path.basename(proc["cmdline"][0]) or proc["comm"]
        if base.startswith(("python", "node", "ruby", "perl", "bash", "sh")):
            script = extract_script_name(proc["cmdline"])
            if script:
                return script
        return base
    return proc["comm"]


def parse_passwd(text):
    users = {}
    for line in (text or "").splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[2].isdigit():
            users[int(parts[2])] = parts[0]
    return users


def user_name(uid, users):
    if uid is None:
        return ""
    if uid in users:
        return users[uid]
    if uid == 0:
        return "root"
    return str(uid)


def parse_meminfo(text):
    values = {}
    for line in (text or "").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key.strip()] = int(parts[0])
    if "MemTotal" not in values:
        return None
    total = values["MemTotal"]
    avail = values.get("MemAvailable", values.get("MemFree", 0))
    used = max(0, total - avail)
    return {
        "total_kb": total,
        "used_kb": used,
        "percent": round(100.0 * used / total, 1) if total else 0.0,
    }


def parse_cpu_stat(text):
    total = idle = None
    threads = 0
    for line in (text or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "cpu" and len(parts) >= 5:
            nums = [int(p) for p in parts[1:] if p.isdigit() or (p.startswith("-") and p[1:].isdigit())]
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
            total = sum(nums)
        elif parts[0].startswith("cpu") and parts[0][3:].isdigit():
            threads += 1
    if total is None:
        return None
    return {"total": total, "idle": idle, "threads": threads}


def cpu_percent(prev, curr):
    if not prev or not curr:
        return None
    total = curr["total"] - prev["total"]
    idle = curr["idle"] - prev["idle"]
    if total <= 0:
        return 0.0
    return round(100.0 * (total - idle) / total, 1)


def parse_cpuinfo(text):
    model, mhz_sum, mhz_n = "", 0.0, 0
    sockets, cores_per = set(), 0
    threads = 0
    for line in (text or "").splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if key == "processor":
            threads += 1
        elif key == "model name" and not model:
            model = " ".join(value.split())
        elif key == "cpu MHz":
            try:
                mhz_sum += float(value)
                mhz_n += 1
            except ValueError:
                pass
        elif key == "physical id":
            sockets.add(value)
        elif key == "cpu cores" and value.isdigit():
            cores_per = int(value)
    socket_n = len(sockets) or (1 if threads else 0)
    cores = cores_per * socket_n if cores_per else threads
    mhz = round(mhz_sum / mhz_n) if mhz_n else None
    return {"model": model, "mhz": mhz, "sockets": socket_n, "cores": cores, "threads": threads}


def parse_diskstats(text):
    rows = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 14:
            continue
        name = parts[2]
        try:
            rows[name] = {
                "read_sectors": int(parts[5]),
                "write_sectors": int(parts[9]),
                "io_ms": int(parts[12]),
            }
        except ValueError:
            continue
    return rows


def disk_parent(name):
    for pattern in (r"^(nvme\d+n\d+)p\d+$", r"^(mmcblk\d+)p\d+$",
                    r"^(sd[a-z]+)\d+$", r"^(vd[a-z]+)\d+$", r"^(hd[a-z]+)\d+$"):
        match = re.match(pattern, name)
        if match:
            return match.group(1)
    return name


def parse_mounts(text):
    found = {}
    skip = {"proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2",
            "overlay", "squashfs", "securityfs", "pstore", "bpf", "tracefs",
            "configfs", "fusectl", "mqueue", "debugfs", "hugetlbfs", "ramfs"}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[2] in skip:
            continue
        name = os.path.basename(parts[0])
        if name and parts[1] not in found.values():
            found[name] = parts[1]
    return found


def disk_kind(name, rotational):
    if name.startswith("nvme"):
        return "SSD (NVMe)"
    if rotational == "1":
        return "HDD"
    if rotational == "0":
        return "SSD"
    return "Disk"


def parse_netdev(text):
    rows = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        name, _, rest = line.partition(":")
        name = name.strip()
        nums = rest.split()
        if not name or name == "lo" or len(nums) < 9:
            continue
        try:
            rows[name] = {"rx": int(nums[0]), "tx": int(nums[8])}
        except ValueError:
            continue
    return rows


def rate(curr, prev, seconds):
    if curr is None or prev is None or seconds <= 0:
        return None
    return max(0.0, (curr - prev) / seconds)


def parse_systemctl_show(text):
    units = []
    for block in (text or "").split("\n\n"):
        item = {}
        for line in block.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                item[key.strip()] = value.strip()
        name = item.get("Id") or ""
        if not name.endswith(".service"):
            continue
        try:
            pid = int(item.get("MainPID") or 0)
        except ValueError:
            pid = 0
        units.append({
            "name": name,
            "pid": pid,
            "state": item.get("ActiveState") or "",
            "description": item.get("Description") or "",
        })
    units.sort(key=lambda unit: unit["name"].lower())
    return units


def safe_unit(name):
    return bool(UNIT_NAME.fullmatch(name or ""))


def safe_desktop_name(name):
    return bool(DESKTOP_NAME.fullmatch(name or "")) and "/" not in (name or "") and "\\" not in (name or "")


def parse_desktop(text):
    section = None
    data = {}
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped
            continue
        if section != "[Desktop Entry]" or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def desktop_enabled(data):
    if (data.get("Hidden") or "").lower() == "true":
        return False
    flag = data.get("X-GNOME-Autostart-enabled", "true")
    return flag.lower() != "false"


def collect_startup(system_dir, user_dir):
    files = {}
    for folder in (system_dir, user_dir):
        if not folder or not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".desktop"):
                continue
            data = parse_desktop(read_text(os.path.join(folder, name)))
            if data.get("Name") or data.get("Exec"):
                files[name] = data
    items = []
    for name, data in files.items():
        items.append({
            "file": name,
            "name": data.get("Name") or name,
            "command": data.get("Exec") or "",
            "enabled": desktop_enabled(data),
        })
    items.sort(key=lambda item: item["name"].lower())
    return items


def write_desktop(path, data):
    lines = ["[Desktop Entry]"]
    for key, value in data.items():
        lines.append("%s=%s" % (key, value))
    lines.append("")
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))
    os.replace(tmp, path)


def set_startup(system_dir, user_dir, filename, enabled):
    if not safe_desktop_name(filename):
        return {"status": "REFUSED", "reason": "Not a startup entry."}
    if not user_dir:
        return {"status": "FAILED", "reason": "No user startup folder."}
    user_path = os.path.join(user_dir, filename)
    system_path = os.path.join(system_dir, filename) if system_dir else ""
    data = {}
    if os.path.isfile(user_path):
        data = parse_desktop(read_text(user_path))
    elif system_path and os.path.isfile(system_path):
        data = parse_desktop(read_text(system_path))
    if not data:
        return {"status": "MISSING"}
    data["Hidden"] = "false" if enabled else "true"
    data["X-GNOME-Autostart-enabled"] = "true" if enabled else "false"
    data.setdefault("Type", "Application")
    write_desktop(user_path, data)
    return {"status": "ENABLED" if enabled else "DISABLED", "file": filename}


def fresh_history():
    return {"since": time.strftime("%Y-%m-%d"), "apps": {}}


def load_history(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("apps"), dict):
            data.setdefault("since", time.strftime("%Y-%m-%d"))
            return data
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return fresh_history()


def save_history(path, data):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, indent=1, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def update_history(history, procs, clk):
    """Add only the CPU time used since the previous sample of each process."""
    if not isinstance(history, dict):
        history = fresh_history()
    apps = history.setdefault("apps", {})
    history.setdefault("since", time.strftime("%Y-%m-%d"))
    seen = {}
    for proc in procs:
        if proc.get("kind") != "app":
            continue
        key = proc["name"]
        slot = apps.setdefault(key, {"cpu_seconds": 0.0, "live": {}})
        slot.setdefault("cpu_seconds", 0.0)
        live = slot.setdefault("live", {})
        ident = "%s:%s" % (proc["pid"], proc["starttime"])
        prev = live.get(ident)
        ticks = proc.get("ticks") or 0
        if isinstance(prev, (int, float)) and ticks >= prev and clk:
            slot["cpu_seconds"] += (ticks - prev) / float(clk)
        live[ident] = ticks
        seen.setdefault(key, set()).add(ident)
    for key, slot in apps.items():
        live = slot.get("live") or {}
        keep = seen.get(key, set())
        slot["live"] = {ident: ticks for ident, ticks in live.items() if ident in keep}
    return history


def history_rows(history):
    rows = []
    for name, slot in (history.get("apps") or {}).items():
        rows.append({
            "name": name,
            "cpu_seconds": round(float(slot.get("cpu_seconds") or 0), 1),
            "network": None,
            "notifications": None,
        })
    rows.sort(key=lambda row: (-row["cpu_seconds"], row["name"].lower()))
    return rows


def default_runner(argv, timeout=8):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stdout or "", result.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def service_action(name, action, runner=None):
    if action not in ("start", "stop", "restart"):
        return {"status": "REFUSED", "reason": "Unsupported action."}
    if not safe_unit(name):
        return {"status": "REFUSED", "reason": "Not a service name."}
    runner = runner or default_runner
    code, _out, err = runner(["systemctl", action, name], timeout=30)
    if code == 0:
        return {"status": "OK", "name": name, "action": action}
    text = (err or "").lower()
    if "permission" in text or "access denied" in text or "interactive authentication" in text or code == 4:
        return {"status": "NEEDS_ROOT", "name": name, "action": action, "detail": err.strip()}
    return {"status": "FAILED", "name": name, "action": action, "detail": err.strip()}


def start_program(command, popen=None):
    try:
        argv = shlex.split(command or "")
    except ValueError as exc:
        return {"status": "FAILED", "reason": str(exc)}
    if not argv:
        return {"status": "EMPTY"}
    popen = popen or subprocess.Popen
    try:
        popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        return {"status": "FAILED", "reason": str(exc), "argv": argv}
    return {"status": "STARTED", "argv": argv}


def end_task(pid, proc_root, uid=None, euid=None, kill=None):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return {"status": "REFUSED", "reason": "Not a process id."}
    proc = read_process(proc_root, pid, page_size())
    if proc is None:
        return {"status": "MISSING", "pid": pid}
    if pid == 1 or proc["comm"] in PROTECTED or pid == os.getpid():
        return {"status": "REFUSED", "pid": pid, "name": proc["name"],
                "reason": "This keeps the desktop running."}
    euid = current_uid() if euid is None else euid
    uid = current_uid() if uid is None else uid
    if euid not in (0, None) and proc["uid"] not in (None, uid):
        return {"status": "REFUSED", "pid": pid, "name": proc["name"],
                "reason": "That process belongs to another user."}
    kill = kill or os.kill
    try:
        kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return {"status": "MISSING", "pid": pid}
    except PermissionError:
        return {"status": "NEEDS_ROOT", "pid": pid, "name": proc["name"]}
    except OSError as exc:
        return {"status": "FAILED", "pid": pid, "reason": str(exc)}
    return {"status": "ENDED", "pid": pid, "name": proc["name"]}


def read_process(proc_root, pid, pagesz):
    base = os.path.join(proc_root, str(pid))
    stat = parse_stat(read_text(os.path.join(base, "stat")))
    if not stat:
        return None
    uid, rss_kb = parse_status(read_text(os.path.join(base, "status")))
    cmdline = parse_cmdline(read_text(os.path.join(base, "cmdline")))
    if rss_kb is None:
        rss_kb = stat["rss_pages"] * pagesz / 1024.0
    comm = stat["comm"]
    if len(comm) >= 14:
        try:
            exe_base = os.path.basename(os.readlink(os.path.join(base, "exe")))
            if exe_base and (exe_base == comm or exe_base.startswith(comm)):
                comm = exe_base
        except Exception:
            pass
        if len(comm) <= 15 and cmdline and cmdline[0]:
            cmd_base = os.path.basename(cmdline[0])
            if cmd_base and (cmd_base == comm or cmd_base.startswith(comm)):
                comm = cmd_base

    app_name = pretty_name(comm)
    if comm.startswith(("python", "node", "ruby", "perl", "bash", "sh")) and cmdline:
        script = extract_script_name(cmdline)
        if script:
            if script in PRETTY:
                app_name = PRETTY[script]
            else:
                app_name = pretty_name(script)

    proc = {
        "pid": stat["pid"],
        "comm": comm,
        "name": app_name,
        "state": stat["state"],
        "status": state_name(stat["state"]),
        "ppid": stat["ppid"],
        "uid": uid,
        "cmdline": cmdline,
        "display": has_display(read_text(os.path.join(base, "environ"))),
        "ticks": stat["utime"] + stat["stime"],
        "starttime": stat["starttime"],
        "threads": stat["threads"],
        "io": parse_io(read_text(os.path.join(base, "io"))),
        "memory_mb": round(rss_kb / 1024.0, 1),
        "arch": elf_arch(read_bytes(os.path.join(base, "exe"), 64)),
        "cpu": None,
        "disk_bps": None,
    }
    proc["kind"] = classify(proc)
    proc["description"] = description_of(proc)
    return proc


def list_processes(proc_root, pagesz):
    found = []
    try:
        names = os.listdir(proc_root)
    except OSError:
        return found
    for name in names:
        if not name.isdigit():
            continue
        proc = read_process(proc_root, int(name), pagesz)
        if proc:
            found.append(proc)
    return found


def _sum(values):
    nums = [value for value in values if value is not None]
    if not nums:
        return None
    return round(sum(nums), 1)


def build_groups(procs):
    def pack(items):
        buckets = {}
        order = []
        for proc in items:
            key = proc["name"]
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(proc)
        rows = []
        for key in order:
            members = buckets[key]
            children = []
            if len(members) > 1:
                children = [_leaf(member) for member in members]
            rows.append({
                "name": key,
                "count": len(members),
                "label": "%s (%d)" % (key, len(members)) if len(members) > 1 else key,
                "cpu": _sum(member["cpu"] for member in members),
                "memory_mb": round(sum(member["memory_mb"] for member in members), 1),
                "disk_bps": _sum(member["disk_bps"] for member in members),
                "pids": [member["pid"] for member in members],
                "status": "Running" if any(member["state"] == "R" for member in members) else members[0]["status"],
                "children": children,
            })
        rows.sort(key=lambda row: row["memory_mb"], reverse=True)
        return rows

    def _leaf(proc):
        return {
            "name": proc["name"],
            "count": 1,
            "label": proc["description"] or proc["name"],
            "cpu": proc["cpu"],
            "memory_mb": proc["memory_mb"],
            "disk_bps": proc["disk_bps"],
            "pids": [proc["pid"]],
            "status": proc["status"],
            "children": [],
        }

    return {
        "apps": pack([proc for proc in procs if proc["kind"] == "app"]),
        "background": pack([proc for proc in procs if proc["kind"] == "background"]),
    }


def build_users(procs, passwd_text):
    names = parse_passwd(passwd_text)
    buckets = {}
    for proc in procs:
        if proc["kind"] == "kernel" or proc["uid"] is None:
            continue
        slot = buckets.setdefault(proc["uid"], [])
        slot.append(proc)
    rows = []
    for uid, members in buckets.items():
        rows.append({
            "uid": uid,
            "name": user_name(uid, names),
            "status": "Running",
            "cpu": _sum(member["cpu"] for member in members),
            "memory_mb": round(sum(member["memory_mb"] for member in members), 1),
            "disk_bps": _sum(member["disk_bps"] for member in members),
            "processes": len(members),
        })
    rows.sort(key=lambda row: row["memory_mb"], reverse=True)
    return rows


def apply_rates(procs, previous, seconds, clk, ncpu):
    ncpu = ncpu or 1
    for proc in procs:
        prev = previous.get(proc["pid"]) if previous else None
        if not prev or prev.get("starttime") != proc["starttime"] or seconds <= 0:
            proc["cpu"] = None
            proc["disk_bps"] = None
            continue
        ticks = proc["ticks"] - prev["ticks"]
        proc["cpu"] = round(max(0.0, ticks / float(clk) / seconds * 100.0 / ncpu), 1)
        proc["disk_bps"] = round(max(0.0, proc["io"] - prev["io"]) / seconds, 1)
    return procs


def _rotational(sys_block, name):
    return read_text(os.path.join(sys_block, disk_parent(name), "queue", "rotational")).strip()


def _wanted_disk(name, stats, mounts):
    if name.startswith(("loop", "ram", "zram", "fd", "sr")):
        return False
    if not re.match(r"^(nvme\d+n\d+|mmcblk\d+|sd[a-z]+|vd[a-z]+|hd[a-z]+|dm-\d+)$", name):
        return False
    parent = disk_parent(name)
    if parent != name and parent in stats:
        return False
    if name.startswith("dm-") and name not in mounts:
        return False
    return True


def _disk_rows(stats, prev, seconds, mounts, sys_block):
    chosen = [name for name in sorted(stats) if _wanted_disk(name, stats, mounts)]
    rows = []
    seen = []
    for name in chosen:
        if name in seen:
            continue
        seen.append(name)
        curr = stats[name]
        old = (prev or {}).get(name)
        mount = mounts.get(name) or ""
        if not mount:
            for dev, point in mounts.items():
                if disk_parent(dev) == name:
                    mount = point
                    break
        active = None
        read_bps = write_bps = None
        if old and seconds > 0:
            active = min(100.0, max(0.0, (curr["io_ms"] - old["io_ms"]) / (seconds * 1000.0) * 100.0))
            read_bps = (curr["read_sectors"] - old["read_sectors"]) * 512.0 / seconds
            write_bps = (curr["write_sectors"] - old["write_sectors"]) * 512.0 / seconds
            read_bps = max(0.0, read_bps)
            write_bps = max(0.0, write_bps)
        rows.append({
            "name": name,
            "mount": mount,
            "kind": disk_kind(name, _rotational(sys_block, name)),
            "active": None if active is None else round(active, 1),
            "read_bps": None if read_bps is None else round(read_bps, 1),
            "write_bps": None if write_bps is None else round(write_bps, 1),
        })
    return rows


def _net_rows(curr, prev, seconds):
    rows = []
    for name in sorted(curr):
        if name.startswith(("veth", "br-", "docker", "virbr")):
            continue
        old = (prev or {}).get(name)
        rx = tx = None
        if old and seconds > 0:
            rx = max(0.0, (curr[name]["rx"] - old["rx"]) / seconds)
            tx = max(0.0, (curr[name]["tx"] - old["tx"]) / seconds)
        rows.append({
            "name": name,
            "rx_bps": None if rx is None else round(rx, 1),
            "tx_bps": None if tx is None else round(tx, 1),
        })
    return rows


def _gpus(sys_drm):
    if not sys_drm or not os.path.isdir(sys_drm):
        return []
    rows = []
    try:
        names = sorted(os.listdir(sys_drm))
    except OSError:
        return []
    for name in names:
        if not re.fullmatch(r"card\d+", name):
            continue
        device = os.path.join(sys_drm, name, "device")
        vendor = read_text(os.path.join(device, "vendor")).strip().lower()
        label = GPU_VENDORS.get(vendor, "")
        busy_text = read_text(os.path.join(device, "gpu_busy_percent")).strip()
        busy = int(busy_text) if busy_text.isdigit() else None
        rows.append({"name": (label + " graphics").strip() or "GPU", "percent": busy, "card": name})
    return rows


def _zram_active(swaps_text):
    for line in (swaps_text or "").splitlines()[1:]:
        parts = line.split()
        if parts and os.path.basename(parts[0]).startswith("zram"):
            return True
    return False


class Machine:
    """One computer. poll() is safe to call every second; the first call has no rates."""

    def __init__(self, proc_root="/proc", sys_block="/sys/block", sys_drm="/sys/class/drm",
                 passwd="/etc/passwd", history_path=None, system_autostart=None,
                 user_autostart=None, runner=None, clock=None, clk=None, pagesz=None):
        self.proc_root = proc_root
        self.sys_block = sys_block
        self.sys_drm = sys_drm
        self.passwd = passwd
        self.history_path = history_path
        self.system_autostart = system_autostart
        self.user_autostart = user_autostart
        self.runner = runner
        self.clock = clock or time.monotonic
        self.clk = clk or clock_ticks()
        self.pagesz = pagesz or page_size()
        self._prev_time = None
        self._prev_cpu = None
        self._prev_disks = None
        self._prev_net = None
        self._prev_procs = None
        self._services = []
        self._services_at = 0.0
        self._history = None
        self._history_saved_at = None

    def _path(self, name):
        return os.path.join(self.proc_root, name)

    def poll(self, services=True):
        now = self.clock()
        seconds = None if self._prev_time is None else max(0.0, now - self._prev_time)
        procs = list_processes(self.proc_root, self.pagesz)
        cpu_stat = parse_cpu_stat(read_text(self._path("stat")))
        info = parse_cpuinfo(read_text(self._path("cpuinfo")))
        ncpu = (cpu_stat or {}).get("threads") or info.get("threads") or 1
        if self._prev_procs is not None and seconds:
            apply_rates(procs, self._prev_procs, seconds, self.clk, ncpu)
        mem = parse_meminfo(read_text(self._path("meminfo")))
        disks_raw = parse_diskstats(read_text(self._path("diskstats")))
        mounts = parse_mounts(read_text(self._path("mounts")))
        net_raw = parse_netdev(read_text(self._path("net/dev")))
        cpu_pct = cpu_percent(self._prev_cpu, cpu_stat) if seconds else None
        disks = _disk_rows(disks_raw, self._prev_disks, seconds or 0, mounts, self.sys_block)
        nets = _net_rows(net_raw, self._prev_net, seconds or 0)
        groups = build_groups(procs)
        details = []
        for proc in procs:
            details.append({
                "name": proc["description"] or proc["name"],
                "pid": proc["pid"],
                "status": proc["status"],
                "user": user_name(proc["uid"], parse_passwd(read_text(self.passwd))),
                "cpu": proc["cpu"],
                "memory_mb": proc["memory_mb"],
                "arch": proc["arch"],
                "description": proc["name"],
                "kind": proc["kind"],
                "comm": proc["comm"],
            })
        details.sort(key=lambda row: (row["name"].lower(), row["pid"]))
        history = None
        if self.history_path:
            if self._history is None:
                self._history = load_history(self.history_path)
            history = update_history(self._history, procs, self.clk)
            self._history = history
            if self._history_saved_at is None or now - self._history_saved_at >= 30:
                save_history(self.history_path, history)
                self._history_saved_at = now
        startup = collect_startup(
            self.system_autostart if self.system_autostart is not None else "/etc/xdg/autostart",
            self.user_autostart if self.user_autostart is not None else os.path.join(
                os.path.expanduser("~"), ".config", "autostart"),
        )
        service_rows = self._service_rows(now) if services else []
        self._prev_time = now
        self._prev_cpu = cpu_stat
        self._prev_disks = disks_raw
        self._prev_net = net_raw
        self._prev_procs = {proc["pid"]: {"ticks": proc["ticks"], "io": proc["io"],
                                           "starttime": proc["starttime"]} for proc in procs}
        disk_active = None
        actives = [row["active"] for row in disks if row["active"] is not None]
        if actives:
            disk_active = round(max(actives), 1)
        net_bps = None
        rates = [(row["rx_bps"] or 0) + (row["tx_bps"] or 0) for row in nets if row["rx_bps"] is not None]
        if rates:
            net_bps = round(sum(rates), 1)
        return {
            "cpu_percent": cpu_pct,
            "cpu": {
                "percent": cpu_pct,
                "mhz": info.get("mhz"),
                "model": info.get("model") or "",
                "sockets": info.get("sockets") or 0,
                "cores": info.get("cores") or 0,
                "threads": info.get("threads") or ncpu,
            },
            "memory": None if not mem else {
                "total_mb": round(mem["total_kb"] / 1024.0, 1),
                "used_mb": round(mem["used_kb"] / 1024.0, 1),
                "percent": mem["percent"],
                "zram": _zram_active(read_text(self._path("swaps"))),
            },
            "disks": disks,
            "disk_active": disk_active,
            "nets": nets,
            "net_bps": net_bps,
            "gpus": _gpus(self.sys_drm),
            "processes": groups,
            "details": details,
            "users": build_users(procs, read_text(self.passwd)),
            "startup": startup,
            "services": service_rows,
            "history": {
                "since": (history or {}).get("since") or "",
                "apps": history_rows(history or {"apps": {}}),
            },
            "counts": {
                "apps": len(groups["apps"]),
                "background": len(groups["background"]),
                "processes": len(procs),
            },
        }

    def _service_rows(self, now):
        if self.runner is False:
            return []
        if self._services and now - self._services_at < 5:
            return self._services
        runner = self.runner or default_runner
        code, out, _err = runner(
            ["systemctl", "show", "--type=service", "--no-pager",
             "-p", "Id", "-p", "ActiveState", "-p", "MainPID", "-p", "Description"],
            timeout=8)
        self._services = parse_systemctl_show(out) if code == 0 else []
        self._services_at = now
        return self._services


def history_path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "devos", HISTORY_NAME)


def default_machine():
    return Machine(history_path=history_path(),
                   system_autostart="/etc/xdg/autostart",
                   user_autostart=os.path.join(os.path.expanduser("~"), ".config", "autostart"))


def cmd_end(pid):
    result = end_task(pid, "/proc")
    print(result["status"] if result["status"] != "ENDED" else "Ended %s" % result.get("name", pid))
    if result.get("reason"):
        print(result["reason"])
    return 0 if result["status"] == "ENDED" else 1


def cmd_sample():
    default_machine().poll(services=False)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="devos-taskman", description=APP_NAME)
    parser.add_argument("--json", action="store_true", help="print one snapshot and exit")
    parser.add_argument("--sample", action="store_true", help="record app history and exit")
    parser.add_argument("--gui", action="store_true", help="open the window")
    sub = parser.add_subparsers(dest="cmd")
    end = sub.add_parser("end")
    end.add_argument("pid")
    run = sub.add_parser("run")
    run.add_argument("command", nargs=argparse.REMAINDER)
    startup = sub.add_parser("startup")
    startup.add_argument("mode", nargs="?", choices=("enable", "disable"))
    startup.add_argument("file", nargs="?")
    sub.add_parser("services")
    svc = sub.add_parser("service")
    svc.add_argument("action", choices=("start", "stop", "restart"))
    svc.add_argument("name")
    sub.add_parser("history-clear")
    # Accept `taskman.py end 123` and a bare launch.
    args, extra = parser.parse_known_args(argv)
    if args.cmd is None and extra:
        # `end 1` without the subparser seeing it when someone passes a single word gui.
        pass
    if args.sample:
        return cmd_sample()
    if args.json:
        snap = default_machine().poll()
        print(json.dumps(snap, indent=1))
        return 0
    if args.cmd == "end":
        return cmd_end(args.pid)
    if args.cmd == "run":
        result = start_program(" ".join(args.command))
        print(result["status"])
        return 0 if result["status"] == "STARTED" else 1
    if args.cmd == "startup":
        folder = os.path.join(os.path.expanduser("~"), ".config", "autostart")
        if args.mode:
            if not args.file:
                print("Name the startup file.", file=sys.stderr)
                return 1
            result = set_startup("/etc/xdg/autostart", folder, args.file, args.mode == "enable")
            print(result["status"])
            return 0 if result["status"] in ("ENABLED", "DISABLED") else 1
        rows = collect_startup("/etc/xdg/autostart", folder)
        for row in rows:
            print("%s\t%s\t%s" % ("Enabled" if row["enabled"] else "Disabled", row["name"], row["file"]))
        return 0
    if args.cmd == "services":
        _code, out, _err = default_runner(
            ["systemctl", "show", "--type=service", "--no-pager",
             "-p", "Id", "-p", "ActiveState", "-p", "MainPID", "-p", "Description"])
        for row in parse_systemctl_show(out):
            print("%s\t%s\t%s\t%s" % (row["state"], row["pid"] or "", row["name"], row["description"]))
        return 0
    if args.cmd == "service":
        result = service_action(args.name, args.action)
        if result["status"] == "NEEDS_ROOT":
            pkexec = os.environ.get("PKEXEC", "pkexec")
            code, _out, err = default_runner([pkexec, "systemctl", args.action, args.name], timeout=60)
            print("OK" if code == 0 else err or "FAILED")
            return 0 if code == 0 else 1
        print(result["status"])
        return 0 if result["status"] == "OK" else 1
    if args.cmd == "history-clear":
        path = history_path()
        save_history(path, fresh_history())
        print(path)
        return 0
    return run_gui()


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------


def run_gui():
    if "QT_QPA_PLATFORM" not in os.environ:
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    try:
        from PyQt5 import QtCore, QtGui, QtWidgets
    except ImportError:
        print("Task Manager needs PyQt5.", file=sys.stderr)
        return 1

    def fmt_pct(value):
        if value is None:
            return ""
        return "%.1f%%" % value if value < 10 else "%.0f%%" % value

    def fmt_mb(value):
        if value is None:
            return ""
        return "{:,.1f} MB".format(value)

    def fmt_disk(bps):
        if bps is None:
            return ""
        return "%.1f MB/s" % (bps / (1024.0 * 1024.0))

    def fmt_net(bps):
        if bps is None:
            return "—"
        bits = bps * 8.0
        if bits >= 1000000:
            return "%.1f Mbps" % (bits / 1000000.0)
        return "%.1f Kbps" % (bits / 1000.0)

    def fmt_time(seconds):
        seconds = int(seconds or 0)
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        return "%d:%02d:%02d" % (hours, minutes, secs)

    class Graph(QtWidgets.QWidget):
        def __init__(self, auto=False):
            super().__init__()
            self.auto = auto
            self.points = []
            self.setMinimumHeight(240)

        def push(self, value):
            self.points.append(0.0 if value is None else float(value))
            self.points = self.points[-60:]
            self.update()

        def paintEvent(self, _event):
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            w = self.width()
            h = self.height()
            rect = QtCore.QRectF(12, 12, w - 24, h - 36)
            
            # Background card
            bg_path = QtGui.QPainterPath()
            bg_path.addRoundedRect(QtCore.QRectF(0, 0, w, h), 8, 8)
            painter.fillPath(bg_path, QtGui.QColor("#ffffff"))
            painter.setPen(QtGui.QColor("#e2e8f0"))
            painter.drawPath(bg_path)
            
            # Subtle Grid lines
            painter.setPen(QtGui.QColor("#f1f5f9"))
            for step in range(1, 4):
                y = rect.top() + rect.height() * step / 4.0
                painter.drawLine(QtCore.QPointF(rect.left(), y), QtCore.QPointF(rect.right(), y))
                
            peak = 100.0
            if self.auto:
                peak = max(self.points) if self.points else 1.0
                peak = max(peak * 1.25, 1.0)
                
            if len(self.points) >= 2:
                span = rect.width() / 59.0
                offset = 60 - len(self.points)
                
                # Build path for gradient fill and line
                line_path = QtGui.QPainterPath()
                first_x = rect.left() + offset * span
                first_y = rect.bottom() - rect.height() * (min(self.points[0], peak) / peak)
                line_path.moveTo(first_x, first_y)
                
                poly_path = QtGui.QPainterPath()
                poly_path.moveTo(first_x, rect.bottom())
                poly_path.lineTo(first_x, first_y)
                
                for index, value in enumerate(self.points[1:], start=1):
                    x = rect.left() + (index + offset) * span
                    y = rect.bottom() - rect.height() * (min(value, peak) / peak)
                    line_path.lineTo(x, y)
                    poly_path.lineTo(x, y)
                    
                last_x = rect.left() + (len(self.points) - 1 + offset) * span
                poly_path.lineTo(last_x, rect.bottom())
                poly_path.closeSubpath()
                
                # Gradient fill under the curve
                gradient = QtGui.QLinearGradient(0, rect.top(), 0, rect.bottom())
                gradient.setColorAt(0, QtGui.QColor(0, 103, 192, 70))
                gradient.setColorAt(1, QtGui.QColor(0, 103, 192, 5))
                painter.fillPath(poly_path, gradient)
                
                # Crisp Fluent stroke line
                pen = QtGui.QPen(QtGui.QColor("#0067c0"), 2)
                pen.setCapStyle(QtCore.Qt.RoundCap)
                pen.setJoinStyle(QtCore.Qt.RoundJoin)
                painter.setPen(pen)
                painter.drawPath(line_path)
                
            # Footer & axis labels
            painter.setPen(QtGui.QColor("#94a3b8"))
            font = painter.font()
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(QtCore.QRectF(14, h - 22, 100, 16), QtCore.Qt.AlignLeft, "60 seconds")
            if not self.auto:
                painter.drawText(QtCore.QRectF(w - 114, 14, 100, 16), QtCore.Qt.AlignRight, "100%")
                painter.drawText(QtCore.QRectF(w - 114, h - 22, 100, 16), QtCore.Qt.AlignRight, "0%")
            painter.end()

    class Window(QtWidgets.QMainWindow):
        def __init__(self):
            super().__init__()
            self.machine = default_machine()
            self.snap = None
            self.setWindowTitle(APP_NAME)
            self.resize(1100, 720)
            self.setStyleSheet("""
                QMainWindow { background: #f3f4f6; }
                QWidget { color: #111827; font-family: "Segoe UI", "Noto Sans", sans-serif; font-size: 13px; }
                QFrame#side { background: #f3f4f6; border-right: 1px solid #e5e7eb; }
                QPushButton#nav {
                    text-align: left; padding: 10px 14px; border: none; border-radius: 6px;
                    color: #4b5563; font-weight: 500; font-size: 13px; margin-bottom: 2px;
                }
                QPushButton#nav:hover { background: #e5e7eb; color: #111827; }
                QPushButton#nav:checked {
                    background: #e0effe; color: #0067c0; font-weight: 600;
                    border-left: 3px solid #0067c0;
                }
                QLineEdit {
                    background: #ffffff; border: 1px solid #d1d5db; border-radius: 6px;
                    padding: 7px 12px; font-size: 13px; color: #111827;
                }
                QLineEdit:focus { border: 2px solid #0067c0; padding: 6px 11px; }
                QTreeWidget, QTableWidget {
                    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;
                    alternate-background-color: #f8fafc; outline: none;
                    gridline-color: transparent;
                    selection-background-color: #e0effe;
                    selection-color: #0369a1;
                }
                QTreeWidget::item, QTableWidget::item {
                    padding: 8px 10px;
                    border-bottom: 1px solid #f1f5f9;
                }
                QHeaderView::section {
                    background: #f8fafc; color: #475569; border: none;
                    border-bottom: 1px solid #e2e8f0; padding: 10px 12px;
                    font-weight: 600; font-size: 12px; text-transform: uppercase;
                    letter-spacing: 0.5px;
                }
                QHeaderView::section:hover {
                    background: #f1f5f9;
                }
                QTreeWidget::item:selected, QTableWidget::item:selected {
                    background: #e0effe; color: #0284c7; font-weight: 600;
                }
                QScrollBar:vertical {
                    border: none; background: #f1f5f9; width: 8px; margin: 0px; border-radius: 4px;
                }
                QScrollBar::handle:vertical {
                    background: #cbd5e1; min-height: 25px; border-radius: 4px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #94a3b8;
                }
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                    border: none; background: none;
                }
                QPushButton {
                    background-color: #ffffff; color: #1b1b1b; border: 1px solid #d1d5db;
                    border-radius: 6px; padding: 6px 14px; font-weight: 500;
                }
                QPushButton:hover { background-color: #f3f4f6; border-color: #9ca3af; }
                QPushButton:pressed { background-color: #e5e7eb; }
                QPushButton#actionBtn {
                    background-color: #0067c0; color: #ffffff; border: 1px solid #005fb8;
                    border-radius: 6px; padding: 6px 16px; font-weight: 600;
                }
                QPushButton#actionBtn:hover { background-color: #1975c5; border-color: #106ebe; }
                QPushButton#actionBtn:pressed { background-color: #005a9e; }
                QPushButton#endBtn {
                    background-color: #ffffff; color: #1b1b1b; border: 1px solid #d1d5db;
                    border-radius: 6px; padding: 6px 16px; font-weight: 500;
                }
                QPushButton#endBtn:hover { background-color: #f3f4f6; border-color: #9ca3af; }
                QPushButton#endBtn:pressed { background-color: #e5e7eb; }
                QPushButton#endBtn:disabled {
                    background-color: #f9fafb; color: #9ca3af; border: 1px solid #e5e7eb;
                }
                QListWidget#perfDevices { background: transparent; border: none; outline: none; }
                QListWidget#perfDevices::item {
                    background: #ffffff; border: 1px solid #e5e7eb; border-radius: 6px;
                    padding: 8px 10px; margin-bottom: 6px; font-weight: 500; color: #111827;
                }
                QListWidget#perfDevices::item:hover { background: #f8fafc; border-color: #cbd5e1; }
                QListWidget#perfDevices::item:selected {
                    background: #eff6ff; border: 1px solid #0067c0; border-left: 4px solid #0067c0;
                    color: #0067c0; font-weight: 600;
                }
                QLabel#muted { color: #6b7280; font-size: 12px; }
                QLabel#big { font-size: 20px; font-weight: 700; color: #111827; }
            """)
            root = QtWidgets.QWidget()
            self.setCentralWidget(root)
            layout = QtWidgets.QHBoxLayout(root)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            side = QtWidgets.QFrame()
            side.setObjectName("side")
            side.setFixedWidth(178)
            side_layout = QtWidgets.QVBoxLayout(side)
            side_layout.setContentsMargins(8, 12, 8, 12)
            self.nav = []
            pages = (
                ("processes", "▤   Processes"),
                ("performance", "📈  Performance"),
                ("history", "⏱   App history"),
                ("startup", "🚀  Startup apps"),
                ("users", "👤  Users"),
                ("details", "📋  Details"),
                ("services", "⚙   Services"),
            )
            self.stack = QtWidgets.QStackedWidget()
            for index, (key, label) in enumerate(pages):
                button = QtWidgets.QPushButton(label)
                button.setObjectName("nav")
                button.setCheckable(True)
                button.clicked.connect(lambda _checked, i=index: self.show_page(i))
                side_layout.addWidget(button)
                self.nav.append(button)
            side_layout.addStretch(1)
            layout.addWidget(side)

            right = QtWidgets.QWidget()
            right_layout = QtWidgets.QVBoxLayout(right)
            right_layout.setContentsMargins(16, 12, 16, 12)
            top = QtWidgets.QHBoxLayout()
            self.search = QtWidgets.QLineEdit()
            self.search.setPlaceholderText("Type a name or PID to search")
            self.search.textChanged.connect(self.apply_filter)
            top.addWidget(self.search, 1)
            self.run_btn = QtWidgets.QPushButton("Run new task")
            self.run_btn.setObjectName("actionBtn")
            self.run_btn.clicked.connect(self.run_new)
            self.end_btn = QtWidgets.QPushButton("End task")
            self.end_btn.setObjectName("endBtn")
            self.end_btn.clicked.connect(self.end_selected)
            self.end_btn.setEnabled(False)
            top.addWidget(self.run_btn)
            top.addWidget(self.end_btn)
            right_layout.addLayout(top)
            right_layout.addWidget(self.stack, 1)
            layout.addWidget(right, 1)

            self.proc_tree = self._tree(["Name", "Status", "CPU", "Memory", "Disk", "Network"])
            self.proc_tree.itemSelectionChanged.connect(self._selection)
            self.stack.addWidget(self.proc_tree)
            self.perf = self._performance()
            self.stack.addWidget(self.perf)
            self.history_page = self._history_page()
            self.stack.addWidget(self.history_page)
            self.startup_table = self._table(["Name", "Command", "Status", "Startup impact"])
            self.startup_table.horizontalHeader().setStretchLastSection(False)
            self.startup_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
            self.startup_table.setColumnWidth(0, 220)
            self.startup_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
            self.startup_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Interactive)
            self.startup_table.setColumnWidth(2, 100)
            self.startup_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Interactive)
            self.startup_table.setColumnWidth(3, 130)
            self.stack.addWidget(self.startup_table)

            self.users_table = self._table(["User", "Status", "CPU", "Memory", "Disk", "Network"])
            self.users_table.horizontalHeader().setStretchLastSection(False)
            self.users_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            for c, w in {1: 100, 2: 95, 3: 130, 4: 110, 5: 140}.items():
                self.users_table.horizontalHeader().setSectionResizeMode(c, QtWidgets.QHeaderView.Interactive)
                self.users_table.setColumnWidth(c, w)
            self.stack.addWidget(self.users_table)

            self.details_table = self._table(
                ["Name", "PID", "Status", "User name", "CPU", "Memory", "Architecture", "Description"])
            self.details_table.horizontalHeader().setStretchLastSection(True)
            for c, w in {0: 180, 1: 75, 2: 95, 3: 110, 4: 85, 5: 100, 6: 100}.items():
                self.details_table.horizontalHeader().setSectionResizeMode(c, QtWidgets.QHeaderView.Interactive)
                self.details_table.setColumnWidth(c, w)
            self.details_table.horizontalHeader().setSectionResizeMode(7, QtWidgets.QHeaderView.Stretch)
            self.details_table.itemSelectionChanged.connect(self._selection)
            self.stack.addWidget(self.details_table)

            self.services_table = self._table(["Name", "PID", "State", "Description"])
            self.services_table.horizontalHeader().setStretchLastSection(True)
            for c, w in {0: 240, 1: 80, 2: 100}.items():
                self.services_table.horizontalHeader().setSectionResizeMode(c, QtWidgets.QHeaderView.Interactive)
                self.services_table.setColumnWidth(c, w)
            self.services_table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
            self.services_table.itemSelectionChanged.connect(self._selection)
            self.stack.addWidget(self.services_table)
            self.show_page(0)
            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.refresh)
            self.timer.start(1000)
            self.refresh()

        def friendly_net_name(self, iface):
            if iface.startswith(("en", "eth")):
                return f"Ethernet ({iface})"
            elif iface.startswith(("wl", "wlan", "wifi")):
                return f"Wi-Fi ({iface})"
            elif iface.startswith(("lxcbr", "virbr", "br-", "docker")):
                return f"Virtual Bridge ({iface})"
            elif iface.startswith(("tun", "tap", "wg", "tailscale", "ppp")):
                return f"VPN / Tunnel ({iface})"
            return iface

        def _tree(self, headers):
            tree = QtWidgets.QTreeWidget()
            tree.setHeaderLabels(headers)
            tree.setRootIsDecorated(True)
            tree.setAlternatingRowColors(True)
            tree.header().setStretchLastSection(False)
            tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            tree.header().setHighlightSections(False)
            col_widths = {1: 100, 2: 95, 3: 130, 4: 110, 5: 140}
            for col, width in col_widths.items():
                if col < len(headers):
                    tree.header().setSectionResizeMode(col, QtWidgets.QHeaderView.Interactive)
                    tree.setColumnWidth(col, width)
            tree.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
            tree.customContextMenuRequested.connect(self._menu)
            return tree

        def _table(self, headers):
            table = QtWidgets.QTableWidget(0, len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.verticalHeader().setVisible(False)
            table.verticalHeader().setDefaultSectionSize(36)
            table.setShowGrid(False)
            table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            table.setAlternatingRowColors(True)
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            table.horizontalHeader().setHighlightSections(False)
            return table

        def _performance(self):
            page = QtWidgets.QWidget()
            layout = QtWidgets.QHBoxLayout(page)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(14)
            self.devices = QtWidgets.QListWidget()
            self.devices.setObjectName("perfDevices")
            self.devices.setFixedWidth(210)
            self.devices.currentRowChanged.connect(self._show_device)
            layout.addWidget(self.devices)
            panel = QtWidgets.QWidget()
            form = QtWidgets.QVBoxLayout(panel)
            form.setContentsMargins(0, 0, 0, 0)
            form.setSpacing(12)
            self.perf_title = QtWidgets.QLabel("CPU")
            self.perf_title.setObjectName("big")
            self.perf_graph = Graph(auto=False)
            self.perf_facts = QtWidgets.QLabel("")
            self.perf_facts.setTextFormat(QtCore.Qt.RichText)
            self.perf_facts.setWordWrap(True)
            form.addWidget(self.perf_title)
            form.addWidget(self.perf_graph, 1)
            form.addWidget(self.perf_facts)
            layout.addWidget(panel, 1)
            self._device_meta = []
            self._series = {}
            return page

        def _history_page(self):
            page = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(page)
            self.history_note = QtWidgets.QLabel("")
            self.history_note.setObjectName("muted")
            clear = QtWidgets.QPushButton("Delete usage history")
            clear.setFlat(True)
            clear.clicked.connect(self.clear_history)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(self.history_note, 1)
            row.addWidget(clear)
            layout.addLayout(row)
            self.history_table = self._table(["Name", "CPU time", "Network", "Notifications"])
            self.history_table.horizontalHeader().setStretchLastSection(False)
            self.history_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            for c, w in {1: 120, 2: 120, 3: 140}.items():
                self.history_table.horizontalHeader().setSectionResizeMode(c, QtWidgets.QHeaderView.Interactive)
                self.history_table.setColumnWidth(c, w)
            layout.addWidget(self.history_table, 1)
            return page

        def show_page(self, index):
            self.stack.setCurrentIndex(index)
            for i, button in enumerate(self.nav):
                button.setChecked(i == index)
            self._selection()

        def refresh(self):
            try:
                self.snap = self.machine.poll()
            except Exception as exc:
                self.statusBar().showMessage(str(exc))
                return
            for step in (
                self._fill_processes,
                self._fill_performance,
                self._fill_history,
                self._fill_startup,
                self._fill_users,
                self._fill_details,
                self._fill_services,
                self.apply_filter,
            ):
                try:
                    step()
                except Exception as exc:
                    self.statusBar().showMessage(f"{getattr(step, '__name__', 'step')}: {exc}")

        def _fill_processes(self):
            snap = self.snap
            selected = self._selected_pids()
            expanded = set()

            def walk(item):
                if item.isExpanded():
                    expanded.add(item.text(0))
                for child_index in range(item.childCount()):
                    walk(item.child(child_index))

            for index in range(self.proc_tree.topLevelItemCount()):
                walk(self.proc_tree.topLevelItem(index))
            cpu = fmt_pct(snap["cpu_percent"]) or "—"
            mem = fmt_pct((snap["memory"] or {}).get("percent")) or "—"
            disk = fmt_pct(snap["disk_active"]) or "—"
            net = fmt_net(snap["net_bps"])
            self.proc_tree.setHeaderLabels([
                "Name", "Status", "%s CPU" % cpu, "%s Memory" % mem,
                "%s Disk" % disk, "%s Network" % net,
            ])
            for col in (2, 3, 4, 5):
                self.proc_tree.headerItem().setTextAlignment(col, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.proc_tree.clear()
            sections = (
                ("Apps (%d)" % snap["counts"]["apps"], snap["processes"]["apps"]),
                ("Background processes (%d)" % snap["counts"]["background"], snap["processes"]["background"]),
            )
            for title, rows in sections:
                parent = QtWidgets.QTreeWidgetItem([title, "", "", "", "", ""])
                parent.setData(0, QtCore.Qt.UserRole, [])
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                for row in rows:
                    parent.addChild(self._proc_item(row))
                self.proc_tree.addTopLevelItem(parent)
                parent.setExpanded(True)
            if expanded:
                def restore(item):
                    if item.text(0) in expanded:
                        item.setExpanded(True)
                    for child_index in range(item.childCount()):
                        restore(item.child(child_index))
                for index in range(self.proc_tree.topLevelItemCount()):
                    restore(self.proc_tree.topLevelItem(index))
            if selected:
                self._reselect_tree(selected)

        def _proc_item(self, row):
            item = QtWidgets.QTreeWidgetItem([
                row["label"], row["status"], fmt_pct(row["cpu"]), fmt_mb(row["memory_mb"]),
                fmt_disk(row["disk_bps"]), "—",
            ])
            item.setData(0, QtCore.Qt.UserRole, list(row["pids"]))
            item.setToolTip(0, row["label"])
            if row["status"] == "Running":
                item.setForeground(1, QtGui.QBrush(QtGui.QColor("#059669")))
                font = item.font(1)
                font.setBold(True)
                item.setFont(1, font)
            elif row["status"] in ("Stopped", "Zombie"):
                item.setForeground(1, QtGui.QBrush(QtGui.QColor("#dc2626")))
            else:
                item.setForeground(1, QtGui.QBrush(QtGui.QColor("#6b7280")))
            item.setTextAlignment(2, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            item.setTextAlignment(3, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            item.setTextAlignment(4, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            item.setTextAlignment(5, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            for child in row["children"]:
                item.addChild(self._proc_item(child))
            return item

        def _reselect_tree(self, pids):
            def walk(item):
                if set(item.data(0, QtCore.Qt.UserRole) or []) == set(pids):
                    item.setSelected(True)
                    return True
                for child_index in range(item.childCount()):
                    if walk(item.child(child_index)):
                        return True
                return False
            for index in range(self.proc_tree.topLevelItemCount()):
                if walk(self.proc_tree.topLevelItem(index)):
                    return

        def _fill_performance(self):
            snap = self.snap
            meta = [("CPU", "cpu", False, snap["cpu_percent"])]
            memory = snap["memory"] or {}
            meta.append(("Memory", "memory", False, memory.get("percent")))
            for index, disk in enumerate(snap["disks"]):
                label = "Disk %d (%s)" % (index, disk["name"])
                meta.append((label, "disk-%s" % disk["name"], False, disk["active"]))
            for net in snap["nets"]:
                total = None
                if net["rx_bps"] is not None:
                    total = (net["rx_bps"] or 0) + (net["tx_bps"] or 0)
                friendly_name = self.friendly_net_name(net["name"])
                meta.append((friendly_name, "net-%s" % net["name"], True, total))
            if snap["gpus"]:
                for index, gpu in enumerate(snap["gpus"]):
                    meta.append(("GPU %d" % index, "gpu-%s" % gpu["card"], False, gpu["percent"]))
            else:
                meta.append(("GPU", "gpu-none", False, None))
            current = self.devices.currentRow()
            self._device_meta = meta
            self.devices.blockSignals(True)
            self.devices.clear()
            for label, key, auto, value in meta:
                series = self._series.setdefault(key, [])
                series.append(0.0 if value is None else float(value))
                self._series[key] = series[-60:]
                stat_str = ""
                if key == "cpu" and snap["cpu_percent"] is not None:
                    stat_str = "   %s" % fmt_pct(snap["cpu_percent"])
                elif key == "memory" and memory.get("percent") is not None:
                    stat_str = "   %s" % fmt_pct(memory.get("percent"))
                elif key.startswith("disk-") and value is not None:
                    stat_str = "   %s" % fmt_pct(value)
                elif key.startswith("net-") and value is not None:
                    stat_str = "   %s" % fmt_net(value)
                shown = "%s%s" % (label, stat_str)
                self.devices.addItem(shown)
            if current < 0 or current >= self.devices.count():
                current = 0
            self.devices.setCurrentRow(current)
            self.devices.blockSignals(False)
            self._show_device(current)

        def _show_device(self, row):
            if row < 0 or row >= len(self._device_meta) or not self.snap:
                return
            label, key, auto, _value = self._device_meta[row]
            self.perf_title.setText(label)
            self.perf_graph.auto = auto
            self.perf_graph.points = list(self._series.get(key, []))
            self.perf_graph.update()
            snap = self.snap

            def card(title, value, sub=""):
                sub_html = "<div style='font-size:11px; color:#6b7280; margin-top:2px;'>%s</div>" % sub if sub else ""
                return """
                <td style='background:#ffffff; border:1px solid #e2e8f0; border-radius:6px; padding:10px 14px;'>
                    <div style='font-size:10px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;'>%s</div>
                    <div style='font-size:18px; font-weight:700; color:#0f172a; margin-top:2px;'>%s</div>
                    %s
                </td>
                """ % (title, value, sub_html)

            if key == "cpu":
                cpu = snap["cpu"]
                speed = ("%d MHz" % cpu["mhz"]) if cpu.get("mhz") else "—"
                model = cpu.get("model") or "CPU Processor"
                html = """
                <div style='font-family:"Segoe UI",sans-serif;'>
                    <div style='font-size:12px; color:#64748b; margin-bottom:6px;'>%s</div>
                    <table width='100%%' cellspacing='6' cellpadding='0'>
                        <tr>
                            %s
                            %s
                            %s
                        </tr>
                    </table>
                </div>
                """ % (
                    model,
                    card("Utilization", fmt_pct(cpu.get("percent")) or "—", "Live CPU load"),
                    card("Clock Speed", speed, "Nominal frequency"),
                    card("Topology", "%s Cores" % (cpu.get("cores") or "—"), "%s Logical processors" % (cpu.get("threads") or "—")),
                )
                self.perf_facts.setText(html)
            elif key == "memory":
                memory = snap["memory"] or {}
                used = fmt_mb(memory.get("used_mb")) or "—"
                total = fmt_mb(memory.get("total_mb")) or "—"
                pct = fmt_pct(memory.get("percent")) or "—"
                zram_txt = "Active (zram)" if memory.get("zram") else "Standard"
                html = """
                <div style='font-family:"Segoe UI",sans-serif;'>
                    <table width='100%%' cellspacing='6' cellpadding='0'>
                        <tr>
                            %s
                            %s
                            %s
                        </tr>
                    </table>
                </div>
                """ % (
                    card("In Use", used, "%s of total" % pct),
                    card("Installed", total, "Available memory"),
                    card("Compression", zram_txt, "Memory optimizer"),
                )
                self.perf_facts.setText(html)
            elif key.startswith("disk-"):
                name = key.split("-", 1)[1]
                disk = next((item for item in snap["disks"] if item["name"] == name), None)
                if not disk:
                    self.perf_facts.setText("")
                    return
                active = fmt_pct(disk["active"]) or "0.0%"
                read_spd = fmt_disk(disk["read_bps"]) or "0.0 MB/s"
                write_spd = fmt_disk(disk["write_bps"]) or "0.0 MB/s"
                mount_pt = disk["mount"] or "Not mounted"
                kind = disk["kind"] or "Storage Drive"
                html = """
                <div style='font-family:"Segoe UI",sans-serif;'>
                    <div style='font-size:12px; color:#64748b; margin-bottom:6px;'>%s &bull; %s</div>
                    <table width='100%%' cellspacing='6' cellpadding='0'>
                        <tr>
                            %s
                            %s
                            %s
                        </tr>
                    </table>
                </div>
                """ % (
                    kind, mount_pt,
                    card("Active Time", active, "Disk utilization"),
                    card("Read Speed", read_spd, "Throughput"),
                    card("Write Speed", write_spd, "Throughput"),
                )
                self.perf_facts.setText(html)
            elif key.startswith("net-"):
                name = key.split("-", 1)[1]
                net = next((item for item in snap["nets"] if item["name"] == name), None)
                if not net:
                    self.perf_facts.setText("")
                    return
                send_spd = fmt_net(net["tx_bps"]) or "0.0 Kbps"
                recv_spd = fmt_net(net["rx_bps"]) or "0.0 Kbps"
                friendly = self.friendly_net_name(name)
                html = """
                <div style='font-family:"Segoe UI",sans-serif;'>
                    <div style='font-size:12px; color:#64748b; margin-bottom:6px;'>%s &bull; %s</div>
                    <table width='100%%' cellspacing='6' cellpadding='0'>
                        <tr>
                            %s
                            %s
                            %s
                        </tr>
                    </table>
                </div>
                """ % (
                    friendly, name,
                    card("Send (Tx)", send_spd, "Upload throughput"),
                    card("Receive (Rx)", recv_spd, "Download throughput"),
                    card("Adapter", friendly.split(" (")[0], name),
                )
                self.perf_facts.setText(html)
            elif key == "gpu-none":
                self.perf_facts.setText("<div style='color:#64748b; font-size:13px; padding:12px; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px;'>No dedicated graphics utilization sensor detected.</div>")
            else:
                card_name = key.split("-", 1)[1]
                gpu = next((item for item in snap["gpus"] if item["card"] == card_name), None)
                if not gpu:
                    self.perf_facts.setText("")
                    return
                pct = fmt_pct(gpu["percent"]) if gpu["percent"] is not None else "Sensor unavailable"
                html = """
                <div style='font-family:"Segoe UI",sans-serif;'>
                    <table width='100%%' cellspacing='6' cellpadding='0'>
                        <tr>
                            %s
                            %s
                        </tr>
                    </table>
                </div>
                """ % (
                    card("GPU Utilization", pct, gpu.get("vendor", "Graphics")),
                    card("Adapter", gpu["name"], "Renderer"),
                )
                self.perf_facts.setText(html)

        def _fill_history(self):
            history = self.snap["history"]
            since = history.get("since") or "today"
            self.history_note.setText(
                "Resource usage since %s. CPU time counts from the first time each app was seen. "
                "Per-app network and notification counts are not available." % since)
            self._set_rows(self.history_table, [
                [row["name"], fmt_time(row["cpu_seconds"]), "—", "—"]
                for row in history["apps"]
            ])

        def _fill_startup(self):
            self._set_rows(self.startup_table, [
                [row["name"], row["command"], "Enabled" if row["enabled"] else "Disabled", "Not measured", row["file"]]
                for row in self.snap["startup"]
            ], hidden_tail=1)

        def _fill_users(self):
            self._set_rows(self.users_table, [
                [row["name"], row["status"], fmt_pct(row["cpu"]), fmt_mb(row["memory_mb"]),
                 fmt_disk(row["disk_bps"]), "—"]
                for row in self.snap["users"]
            ])

        def _fill_details(self):
            selected = self._table_pid(self.details_table, 1)
            self._set_rows(self.details_table, [
                [row["name"], str(row["pid"]), row["status"], row["user"], fmt_pct(row["cpu"]),
                 fmt_mb(row["memory_mb"]), row["arch"] or "—", row["description"]]
                for row in self.snap["details"]
            ])
            if selected:
                self._select_pid_row(self.details_table, 1, selected)

        def _fill_services(self):
            self._set_rows(self.services_table, [
                [row["name"], str(row["pid"] or ""), row["state"], row["description"]]
                for row in self.snap["services"]
            ])

        def _set_rows(self, table, rows, hidden_tail=0):
            table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                visible = row[:-hidden_tail] if hidden_tail else row
                extra = row[-1] if hidden_tail else ""
                for c, text in enumerate(visible):
                    item = QtWidgets.QTableWidgetItem(text)
                    if c == 0 and extra:
                        item.setData(QtCore.Qt.UserRole, extra)
                    
                    # Modern status badge colors
                    if text in ("Running", "Enabled", "active"):
                        item.setForeground(QtGui.QBrush(QtGui.QColor("#15803d"))) # Green
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                    elif text in ("Disabled", "inactive", "dead", "Stopped", "Zombie"):
                        item.setForeground(QtGui.QBrush(QtGui.QColor("#94a3b8"))) # Muted slate
                    elif text in ("Sleeping", "Idle"):
                        item.setForeground(QtGui.QBrush(QtGui.QColor("#64748b"))) # Neutral
                    elif text in ("failed", "Disk sleep"):
                        item.setForeground(QtGui.QBrush(QtGui.QColor("#dc2626"))) # Red
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                    
                    # Numeric column right-alignment
                    if any(text.endswith(suf) for suf in ("%", "MB", "GB", "KB", "MB/s", "Kbps", "Mbps")) or (text.isdigit() and c > 0):
                        item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                    else:
                        item.setTextAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

                    table.setItem(r, c, item)

        def apply_filter(self):
            query = self.search.text().strip().lower()
            self._filter_tree(query)
            for table in (self.startup_table, self.users_table, self.details_table,
                          self.services_table, self.history_table):
                for row in range(table.rowCount()):
                    text = " ".join(
                        (table.item(row, col).text() if table.item(row, col) else "")
                        for col in range(table.columnCount())
                    ).lower()
                    table.setRowHidden(row, bool(query) and query not in text)

        def _filter_tree(self, query):
            def walk(item):
                matched = query in item.text(0).lower() if query else True
                child_matched = False
                for index in range(item.childCount()):
                    if walk(item.child(index)):
                        child_matched = True
                item.setHidden(bool(query) and not (matched or child_matched))
                return matched or child_matched
            for index in range(self.proc_tree.topLevelItemCount()):
                walk(self.proc_tree.topLevelItem(index))

        def _selected_pids(self):
            items = self.proc_tree.selectedItems()
            if not items:
                return []
            return list(items[0].data(0, QtCore.Qt.UserRole) or [])

        def _table_pid(self, table, column):
            rows = table.selectionModel().selectedRows() if table.selectionModel() else []
            if not rows:
                return None
            item = table.item(rows[0].row(), column)
            return item.text() if item else None

        def _select_pid_row(self, table, column, pid):
            for row in range(table.rowCount()):
                item = table.item(row, column)
                if item and item.text() == str(pid):
                    table.selectRow(row)
                    return

        def _selection(self):
            page = self.stack.currentIndex()
            if page == 0:
                self.end_btn.setEnabled(bool(self._selected_pids()))
                self.end_btn.setText("End task")
            elif page == 5:
                self.end_btn.setEnabled(self._table_pid(self.details_table, 1) is not None)
                self.end_btn.setText("End task")
            elif page == 3:
                self.end_btn.setEnabled(self.startup_table.currentRow() >= 0)
                self.end_btn.setText("Disable" if self._startup_enabled() else "Enable")
            elif page == 6:
                state = self._service_state()
                self.end_btn.setEnabled(bool(state))
                self.end_btn.setText("Stop" if state == "active" else "Start")
            else:
                self.end_btn.setEnabled(False)
                self.end_btn.setText("End task")

        def _startup_enabled(self):
            row = self.startup_table.currentRow()
            if row < 0:
                return False
            item = self.startup_table.item(row, 2)
            return bool(item and item.text() == "Enabled")

        def _service_state(self):
            row = self.services_table.currentRow()
            if row < 0:
                return ""
            item = self.services_table.item(row, 2)
            return item.text() if item else ""

        def _menu(self, pos):
            item = self.proc_tree.itemAt(pos)
            if not item or not item.data(0, QtCore.Qt.UserRole):
                return
            menu = QtWidgets.QMenu(self)
            menu.addAction("End task", self.end_selected)
            menu.exec_(self.proc_tree.viewport().mapToGlobal(pos))

        def end_selected(self):
            page = self.stack.currentIndex()
            if page == 3:
                self._toggle_startup()
                return
            if page == 6:
                self._toggle_service()
                return
            if page == 5:
                pid = self._table_pid(self.details_table, 1)
                pids = [pid] if pid else []
                name = self._table_pid(self.details_table, 0) or "this process"
            else:
                pids = self._selected_pids()
                item = self.proc_tree.selectedItems()
                name = item[0].text(0) if item else "this process"
            if not pids:
                return
            answer = QtWidgets.QMessageBox.question(
                self, APP_NAME, "End %s?" % name,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
            if answer != QtWidgets.QMessageBox.Yes:
                return
            refused = []
            for pid in pids:
                result = end_task(pid, "/proc")
                if result["status"] == "NEEDS_ROOT":
                    pkexec = os.environ.get("PKEXEC", "pkexec")
                    subprocess.run([pkexec, "kill", str(pid)], check=False)
                elif result["status"] == "REFUSED":
                    refused.append(result.get("reason") or result.get("name") or str(pid))
            if refused:
                QtWidgets.QMessageBox.information(self, APP_NAME, "\n".join(refused))
            self.refresh()

        def _toggle_startup(self):
            row = self.startup_table.currentRow()
            if row < 0:
                return
            item = self.startup_table.item(row, 0)
            filename = item.data(QtCore.Qt.UserRole) if item else ""
            enabled = self._startup_enabled()
            result = set_startup("/etc/xdg/autostart",
                                 os.path.join(os.path.expanduser("~"), ".config", "autostart"),
                                 filename, not enabled)
            if result["status"] not in ("ENABLED", "DISABLED"):
                QtWidgets.QMessageBox.warning(self, APP_NAME, result.get("reason") or result["status"])
            self.refresh()

        def _toggle_service(self):
            row = self.services_table.currentRow()
            if row < 0:
                return
            name = self.services_table.item(row, 0).text()
            action = "stop" if self._service_state() == "active" else "start"
            result = service_action(name, action)
            if result["status"] == "NEEDS_ROOT":
                pkexec = os.environ.get("PKEXEC", "pkexec")
                subprocess.run([pkexec, "systemctl", action, name], check=False)
            elif result["status"] not in ("OK",):
                QtWidgets.QMessageBox.warning(self, APP_NAME, result.get("detail") or result["status"])
            self.machine._services_at = 0
            self.refresh()

        def run_new(self):
            command, ok = QtWidgets.QInputDialog.getText(self, "Run new task", "Open:")
            if not ok:
                return
            result = start_program(command)
            if result["status"] != "STARTED":
                QtWidgets.QMessageBox.warning(self, APP_NAME, result.get("reason") or "Could not start that program.")

        def clear_history(self):
            data = fresh_history()
            save_history(history_path(), data)
            self.machine._history = data
            self.machine._history_saved_at = self.machine.clock()
            self.refresh()

        def closeEvent(self, event):
            if self.machine.history_path and self.machine._history:
                save_history(self.machine.history_path, self.machine._history)
            super().closeEvent(event)

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = Window()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main() or 0)
