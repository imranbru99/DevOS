#!/usr/bin/env python3
"""
Shared helpers for DevOS Security (security_center, av, webprotect,
diskguard, updates). Plain stdlib: importable on any OS for the unit tests.

Small things the Optimizer already does well (sizes, memory, live-session
check, the process table and the list of session processes that must never
be signalled) are imported from components/optimizer instead of copied.
"""

import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
COMPONENTS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(COMPONENTS, "optimizer"))

import optimizer  # noqa: E402  (reuse: human_size, read_meminfo, PROTECTED_NAMES...)

human_size = optimizer.human_size
read_meminfo = optimizer.read_meminfo
is_live_session = optimizer.is_live_session

APP_NAME = "DevOS Security"
CLI = "/usr/local/bin/devos-security"
MB = optimizer.MB
GB = optimizer.GB

# Root-owned state shared by every account on the PC.
DATA_DIR = "/var/lib/DevOS/security"
STATE_FILE = "/etc/devos/security.conf"
RUN_DIR = "/run/devos-security"
LOG_FILE = "/var/log/devos-security.log"


def log(message):
    print(message, file=sys.stderr, flush=True)
    if is_root():
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as handle:
                handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")
        except OSError:
            pass


def is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def run(cmd, timeout=60, env=None):
    """(returncode, stdout+stderr text). Never raises."""
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, timeout=timeout, env=env)
        return proc.returncode, proc.stdout or ""
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return 127, str(exc)


def which(name):
    return shutil.which(name)


def low_priority_prefix():
    """nice -n 19 ionice -c 3: scans never slow the desktop down."""
    prefix = []
    if which("nice"):
        prefix += ["nice", "-n", "19"]
    if which("ionice"):
        prefix += ["ionice", "-c", "3"]
    return prefix


def read_text(path, default=None):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return default


def read_json(path, default=None):
    text = read_text(path)
    if text is None:
        return default
    try:
        return json.loads(text)
    except ValueError:
        return default


def write_text(path, text, mode=0o644):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".devos-new"
    with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    try:
        os.chmod(tmp, mode)
    except OSError:
        pass
    os.replace(tmp, path)


def write_json(path, data, mode=0o644):
    write_text(path, json.dumps(data, indent=1, sort_keys=True) + "\n", mode)


def parse_state(text):
    values = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def render_state(values):
    lines = ["# DevOS Security settings. Change them in the DevOS Security window."]
    lines += ["%s=%s" % (k, values[k]) for k in sorted(values)]
    return "\n".join(lines) + "\n"


def load_state(path=STATE_FILE):
    return parse_state(read_text(path, ""))


def save_state(values, path=STATE_FILE):
    write_text(path, render_state(values), 0o644)


def user_state_dir(home=None):
    base = os.environ.get("XDG_STATE_HOME") if home is None else None
    return os.path.join(base or os.path.join(home or os.path.expanduser("~"), ".local", "state"),
                        "devos-security")


def user_config_path(home=None):
    base = os.environ.get("XDG_CONFIG_HOME") if home is None else None
    return os.path.join(base or os.path.join(home or os.path.expanduser("~"), ".config"),
                        "devos", "security.json")


def load_user_config(home=None):
    cfg = {"notify_safe_downloads": False}
    data = read_json(user_config_path(home), {})
    if isinstance(data, dict):
        cfg.update({k: data[k] for k in cfg if k in data})
    return cfg


def save_user_config(cfg, home=None):
    write_json(user_config_path(home), cfg, 0o600)


def systemctl_state(unit, user=False, what="is-active"):
    if not which("systemctl"):
        return "unknown"
    cmd = ["systemctl"] + (["--user"] if user else []) + [what, unit]
    _code, out = run(cmd, timeout=5)
    lines = out.strip().splitlines()
    state = lines[-1].strip() if lines else ""
    # "Failed to connect to bus..." (no session, containers) is not a state.
    return state if state and " " not in state else "unknown"


# ---------------------------------------------------------------- notifications

def notify(title, body, icon="security-high", urgency="normal", actions=None, wait=False):
    """notify-send in the current session. With actions and wait=True it
    returns the chosen action key (libnotify 0.8: --action/--wait)."""
    if not which("notify-send"):
        return None
    cmd = ["notify-send", "-a", APP_NAME, "-i", icon, "-u", urgency]
    for key, label in (actions or []):
        cmd.append("--action=%s=%s" % (key, label))
    if actions and wait:
        cmd.append("--wait")
    cmd += [title, body]
    if actions and wait:
        code, out = run(cmd, timeout=3600)
        return out.strip().splitlines()[-1] if code == 0 and out.strip() else None
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass
    return None


def parse_loginctl_sessions(text):
    """`loginctl list-sessions --no-legend` -> [(session, uid, user)]."""
    out = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1].isdigit():
            out.append((parts[0], int(parts[1]), parts[2]))
    return out


def parse_show_session(text):
    return parse_state(text)


def graphical_sessions():
    """[(uid, user)] of active, local, graphical sessions (root view)."""
    if not which("loginctl"):
        return []
    _code, out = run(["loginctl", "list-sessions", "--no-legend"], timeout=5)
    found = []
    for sid, uid, user in parse_loginctl_sessions(out):
        _c, info = run(["loginctl", "show-session", sid, "-p", "Active", "-p", "Type",
                        "-p", "Remote", "-p", "Class"], timeout=5)
        props = parse_show_session(info)
        if (props.get("Active") == "yes" and props.get("Remote") != "yes"
                and props.get("Type") in ("x11", "wayland") and props.get("Class", "user") == "user"
                and (uid, user) not in found):
            found.append((uid, user))
    return found


def notify_users_cmd(uid, user, title, body, icon, urgency, actions=None, wait=False):
    """Command that shows a notification in `user`'s desktop from root."""
    env = ["env", "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%d/bus" % uid,
           "DISPLAY=:0", "XDG_RUNTIME_DIR=/run/user/%d" % uid]
    cmd = ["runuser", "-u", user, "--"] + env + ["notify-send", "-a", APP_NAME, "-i", icon,
                                                  "-u", urgency]
    for key, label in (actions or []):
        cmd.append("--action=%s=%s" % (key, label))
    if actions and wait:
        cmd.append("--wait")
    return cmd + [title, body]


def notify_desktop_users(title, body, icon="security-high", urgency="normal", users=None):
    """Root: tell every signed-in desktop user (fire and forget)."""
    for uid, user in (users if users is not None else graphical_sessions()):
        try:
            subprocess.Popen(notify_users_cmd(uid, user, title, body, icon, urgency),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass


def launch_detached(cmd):
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return True
    except OSError:
        return False
