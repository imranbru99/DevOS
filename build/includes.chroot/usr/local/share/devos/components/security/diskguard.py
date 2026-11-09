#!/usr/bin/env python3
"""
DevOS Disk Guard - catches a program that is filling the disk.

devos-diskguard.service (root, Nice=19, idle CPU and I/O class) wakes every
60 s, reads free space with statvfs() for each real filesystem and the
per-process write counters (/proc/*/io). That is a few hundred tiny reads a
minute: no measurable CPU, about 12 MB of RAM.

It raises an alert when
  * free space drops by more than 2 GB within 5 minutes, or by more than 10 %
    of the disk within 30 minutes (abnormal growth), or
  * free space is critical: under 2 % or under 1 GB.
(Plain "low space" - under 10 % or 3 GB - only shows in DevOS Security; the
Optimizer tray already offers Clean up for that.)

On an alert it looks for the culprit, only then doing heavier work:
  * files on that filesystem changed during the window and bigger than
    200 MB (find -xdev -newermt -size +200M, low priority, 30 s limit),
  * which process has them (or any big file there) open for writing
    (/proc/PID/fd + the flags line of /proc/PID/fdinfo),
  * which process wrote the most bytes during the window (/proc/PID/io).
The signed-in user gets a notification naming the file and the app with
Pause app (SIGSTOP), Stop app, Open folder and Ignore.

Auto-protect: when space is critical and one non-system program wrote more
than 1 GB in the window, it is paused (SIGSTOP; nothing is lost, "Resume"
continues it) and the user is told. Never paused, only warned about: PID 1,
kernel threads, system services (UID < 1000), the desktop (Xorg, kwin,
plasmashell, sddm, ...) and package managers (dpkg/apt/unattended-upgrades/
PackageKit/flatpak and anything they started): pausing those mid-way can
corrupt the system.
"""

import argparse
import collections
import json
import os
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import seccommon as common  # noqa: E402
from seccommon import optimizer, GB, MB  # noqa: E402

SAMPLE_S = 60
FAST_WINDOW_S = 5 * 60
FAST_DROP = 2 * GB
SLOW_WINDOW_S = 30 * 60
SLOW_FRACTION = 0.10
LOW_FRACTION = 0.10
LOW_BYTES = 3 * GB
CRITICAL_FRACTION = 0.02
CRITICAL_BYTES = 1 * GB
AUTO_PAUSE_BYTES = 1 * GB
BIG_FILE = 200 * MB
FIND_TIMEOUT_S = 30
ALERT_REPEAT_S = 30 * 60
IGNORE_S = 24 * 3600
STATE_FILE = common.RUN_DIR + "/diskguard.json"

REAL_FS = {"ext4", "ext3", "ext2", "btrfs", "xfs", "f2fs", "jfs", "reiserfs", "bcachefs", "zfs"}
SKIP_MOUNT_PREFIXES = ("/snap/", "/media/", "/run/", "/mnt/", "/boot/efi", "/var/lib/docker/",
                       "/var/snap/", "/cdrom", "/rofs")

# Pausing these could corrupt the system or freeze the desktop: warn only.
PACKAGE_MANAGERS = {"dpkg", "apt", "apt-get", "aptitude", "apt-check", "unattended-upgr",
                    "unattended-upgrade", "packagekitd", "synaptic", "flatpak", "flatpak-system-",
                    "fwupd", "fwupdmgr", "snapd", "update-initramfs", "mkinitramfs", "grub-install",
                    "update-grub", "dracut", "devos-features", "calamares", "rsync-install"}
NEVER_PAUSE = set(optimizer.PROTECTED_NAMES) | PACKAGE_MANAGERS | {
    "systemd", "systemd-journal", "systemd-journald", "systemd-logind", "systemd-udevd",
    "systemd-resolve", "systemd-timesyncd", "systemd-oomd", "init", "xorg", "xwayland",
    "kwin_x11", "kwin_wayland", "kwin", "plasmashell", "sddm", "sddm-helper", "sddm-greeter",
    "networkmanager", "polkitd", "udisksd", "dbus-daemon", "devos-diskguard", "kthreadd",
}


# ---------------------------------------------------------------- free space

def parse_mounts(text):
    """/proc/self/mounts -> [mountpoint] of real, local filesystems."""
    out, seen_dev = [], set()
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        dev, mount, fstype = parts[0], parts[1].replace("\\040", " "), parts[2]
        if fstype not in REAL_FS or mount.startswith(SKIP_MOUNT_PREFIXES):
            continue
        if dev in seen_dev:  # btrfs subvolumes: one entry per device is enough
            continue
        seen_dev.add(dev)
        out.append(mount)
    return out or ["/"]


def statvfs_space(mount):
    st = os.statvfs(mount)
    return st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize


def drop_within(samples, window, now_ts):
    """Largest drop from the highest free value seen in `window` to now."""
    recent = [free for t, free in samples if t >= now_ts - window - 1]
    if len(recent) < 2:
        return 0
    return max(0, max(recent) - recent[-1])


def detect(samples, total, now_ts):
    """samples: [(time, free_bytes)] oldest first. Returns the verdict."""
    free = samples[-1][1] if samples else 0
    fast = drop_within(samples, FAST_WINDOW_S, now_ts)
    slow = drop_within(samples, SLOW_WINDOW_S, now_ts)
    verdict = {
        "free": free, "total": total,
        "low": bool(total) and (free < total * LOW_FRACTION or free < LOW_BYTES),
        "critical": bool(total) and (free < total * CRITICAL_FRACTION or free < CRITICAL_BYTES),
        "growth": None, "drop": 0, "window": 0,
    }
    if fast > FAST_DROP:
        verdict.update(growth="fast", drop=fast, window=FAST_WINDOW_S)
    elif total and slow > total * SLOW_FRACTION:
        verdict.update(growth="steady", drop=slow, window=SLOW_WINDOW_S)
    return verdict


# ---------------------------------------------------------------- processes

def parse_stat(text):
    """/proc/PID/stat -> (comm, ppid, starttime)."""
    rpar = text.rindex(")")
    comm = text[text.index("(") + 1:rpar]
    fields = text[rpar + 2:].split()
    return comm, int(fields[1]), int(fields[19])


def parse_io(text):
    """/proc/PID/io -> bytes really written (write_bytes - cancelled)."""
    values = {}
    for line in (text or "").splitlines():
        key, _sep, value = line.partition(":")
        try:
            values[key.strip()] = int(value)
        except ValueError:
            pass
    return max(0, values.get("write_bytes", 0) - values.get("cancelled_write_bytes", 0))


def _listdir(path):
    try:
        return os.listdir(path)
    except OSError:
        return []


def read_proc(proc_root="/proc"):
    """{pid: {"comm", "ppid", "start", "uid", "written"}}; one pass, small reads."""
    table = {}
    for name in _listdir(proc_root):
        if not name.isdigit():
            continue
        base = os.path.join(proc_root, name)
        try:
            with open(os.path.join(base, "stat"), "r") as fh:
                comm, ppid, start = parse_stat(fh.read())
            uid = os.stat(base).st_uid
        except (OSError, ValueError, IndexError):
            continue
        try:
            with open(os.path.join(base, "io"), "r") as fh:
                written = parse_io(fh.read())
        except OSError:
            written = 0
        table[int(name)] = {"comm": comm, "ppid": ppid, "start": start, "uid": uid, "written": written}
    return table


def write_deltas(before, after):
    """Bytes each process wrote between two read_proc() snapshots. A process
    that started in between counts everything it wrote."""
    out = {}
    for pid, info in after.items():
        old = before.get(pid)
        base = old["written"] if old and old["start"] == info["start"] else 0
        delta = info["written"] - base
        if delta > 0:
            out[pid] = delta
    return out


def parse_fdinfo_flags(text):
    for line in (text or "").splitlines():
        if line.startswith("flags:"):
            try:
                return int(line.split(":", 1)[1].strip(), 8)
            except ValueError:
                return 0
    return 0


def opened_for_writing(flags):
    return (flags & 0o3) in (0o1, 0o2)  # O_WRONLY or O_RDWR


def open_writers(proc_root="/proc", within=None, paths=None, readlink=os.readlink, size_of=None,
                 min_size=BIG_FILE):
    """{path: [pid]} for files open for writing that are in `paths`, or (when
    `within` is a mount point) bigger than min_size on that filesystem."""
    size_of = size_of or _size
    wanted = set(paths or ())
    found = {}
    for name in _listdir(proc_root):
        if not name.isdigit():
            continue
        fd_dir = os.path.join(proc_root, name, "fd")
        for fd in _listdir(fd_dir):
            try:
                target = readlink(os.path.join(fd_dir, fd))
            except OSError:
                continue
            if not target.startswith("/"):
                continue  # pipe:, socket:, anon_inode:
            clean = target[:-len(" (deleted)")] if target.endswith(" (deleted)") else target
            hit = clean in wanted
            if not hit and within:
                root = within.rstrip("/") + "/"
                hit = (within == "/" or clean.startswith(root)) and size_of(target) >= min_size
            if not hit:
                continue
            try:
                with open(os.path.join(proc_root, name, "fdinfo", fd), "r") as fh:
                    flags = parse_fdinfo_flags(fh.read())
            except OSError:
                continue
            if opened_for_writing(flags):
                found.setdefault(target, [])
                if int(name) not in found[target]:
                    found[target].append(int(name))
    return found


def _size(path):
    try:
        return os.stat(path[:-len(" (deleted)")] if path.endswith(" (deleted)") else path).st_size
    except OSError:
        return 0


def find_command(mount, since_ts):
    return common.low_priority_prefix() + [
        "find", mount, "-xdev", "-maxdepth", "14", "-type", "f",
        "-newermt", "@%d" % int(since_ts), "-size", "+%dM" % (BIG_FILE // MB),
        "-printf", "%s\\t%T@\\t%p\\n"]


def parse_find(text):
    out = []
    for line in (text or "").splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            try:
                out.append({"size": int(parts[0]), "mtime": float(parts[1]), "path": parts[2]})
            except ValueError:
                continue
    return sorted(out, key=lambda f: f["size"], reverse=True)


def recent_big_files(mount, since_ts, runner=None):
    runner = runner or (lambda cmd: common.run(cmd, timeout=FIND_TIMEOUT_S))
    _code, out = runner(find_command(mount, since_ts))
    return parse_find(out)[:20]


def ancestors(pid, table, limit=32):
    out = []
    cur = table.get(pid, {}).get("ppid")
    while cur and cur in table and len(out) < limit:
        out.append(table[cur]["comm"])
        cur = table[cur]["ppid"]
    return out


def protection_reason(pid, table):
    """Why this process must not be paused (None = it may be paused)."""
    info = table.get(pid)
    if not info:
        return "gone"
    comm = info["comm"].lower()
    if pid <= 2 or info["ppid"] == 2:
        return "system core"
    if comm in PACKAGE_MANAGERS or any(a.lower() in PACKAGE_MANAGERS for a in ancestors(pid, table)):
        return "package manager"
    if comm in NEVER_PAUSE or comm.startswith("systemd"):
        return "desktop or system process"
    if info["uid"] < 1000:
        return "system service"
    if pid == os.getpid():
        return "self"
    return None


def pick_culprits(table, deltas, writers, files):
    """Rank processes: the one holding the biggest growing file first, then
    by bytes written in the window. Returns a list of dicts."""
    file_size = {f["path"]: f["size"] for f in files}
    holders = {}
    for path, pids in writers.items():
        for pid in pids:
            holders.setdefault(pid, []).append(path)
    candidates = set(deltas) | set(holders)
    ranked = []
    for pid in candidates:
        info = table.get(pid)
        if not info:
            continue
        held = sorted(holders.get(pid, []), key=lambda p: file_size.get(p, _size(p)), reverse=True)
        ranked.append({
            "pid": pid, "comm": info["comm"], "name": optimizer.pretty_name(info["comm"]),
            "uid": info["uid"], "start": info["start"], "written": deltas.get(pid, 0),
            "files": held[:3], "protected": protection_reason(pid, table),
        })
    ranked.sort(key=lambda c: (bool(c["files"]), c["written"]), reverse=True)
    return [c for c in ranked if c["written"] >= 64 * MB or c["files"]][:5]


def auto_pause_choice(verdict, culprits):
    """The process to pause automatically, or None."""
    if not verdict.get("critical"):
        return None
    heavy = [c for c in culprits if c["written"] > AUTO_PAUSE_BYTES]
    if len(heavy) != 1:
        return None  # not one clear culprit: only warn
    choice = heavy[0]
    return None if choice["protected"] else choice


# ---------------------------------------------------------------- actions

def same_process(pid, start, proc_root="/proc"):
    try:
        with open(os.path.join(proc_root, str(pid), "stat"), "r") as fh:
            return parse_stat(fh.read())[2] == start
    except (OSError, ValueError, IndexError):
        return False


def send(pid, start, sig):
    if not same_process(pid, start):
        return False
    try:
        if sig == signal.SIGTERM:
            os.kill(pid, signal.SIGCONT)
        os.kill(pid, sig)
        return True
    except OSError:
        return False


def alert_text(verdict, mount, culprit, files):
    growth = verdict.get("growth")
    what = files[0]["path"] if files else (culprit["files"][0] if culprit and culprit["files"] else None)
    if growth:
        head = "Disk filling up fast" if growth == "fast" else "Disk space shrinking"
        body = "%s less free space on %s in %d minutes" % (
            common.human_size(verdict["drop"]), mount, verdict["window"] // 60)
    else:
        head = "Disk almost full"
        body = "Only %s left on %s" % (common.human_size(verdict["free"]), mount)
    if culprit:
        body += ". %s is writing it" % culprit["name"]
        if culprit["written"]:
            body += " (%s)" % common.human_size(culprit["written"])
    if what:
        body += ": %s" % what
    return head, body + "."


class Guard(object):
    def __init__(self, proc_root="/proc", notify=True):
        self.proc_root = proc_root
        self.notify = notify
        self.samples = {}
        self.snapshots = collections.deque(maxlen=SLOW_WINDOW_S // SAMPLE_S + 2)
        self.mounts = []
        self.mounts_at = 0
        self.last_alert = {}
        self.ignored = {}
        self.paused = []
        self.alerts = []
        self.lock = threading.Lock()

    def refresh_mounts(self, now_ts):
        if now_ts - self.mounts_at > 600 or not self.mounts:
            self.mounts = [m for m in parse_mounts(common.read_text("/proc/self/mounts", ""))
                           if os.path.isdir(m)] or ["/"]
            self.mounts_at = now_ts

    def snapshot_at(self, since_ts):
        for t, snap in self.snapshots:
            if t >= since_ts - 1:
                return snap
        return self.snapshots[0][1] if self.snapshots else {}

    def tick(self, now_ts=None):
        now_ts = now_ts or time.time()
        self.refresh_mounts(now_ts)
        table = read_proc(self.proc_root)
        self.snapshots.append((now_ts, table))
        report = []
        for mount in self.mounts:
            try:
                total, free = statvfs_space(mount)
            except OSError:
                continue
            series = self.samples.setdefault(mount, collections.deque(maxlen=SLOW_WINDOW_S // SAMPLE_S + 2))
            series.append((now_ts, free))
            verdict = detect(list(series), total, now_ts)
            report.append({"mount": mount, "total": total, "free": free, "low": verdict["low"],
                           "critical": verdict["critical"], "growth": verdict["growth"]})
            if verdict["growth"] or verdict["critical"]:
                self.investigate(mount, verdict, table, now_ts)
        self.write_state(report, now_ts)
        return report

    def investigate(self, mount, verdict, table, now_ts):
        window = verdict["window"] or FAST_WINDOW_S
        deltas = write_deltas(self.snapshot_at(now_ts - window), table)
        files = recent_big_files(mount, now_ts - window)
        writers = open_writers(self.proc_root, within=mount, paths=[f["path"] for f in files])
        culprits = pick_culprits(table, deltas, writers, files)
        culprit = culprits[0] if culprits else None
        key = (mount, culprit["comm"] if culprit else None)
        if key in self.ignored and self.ignored[key] > now_ts:
            return
        if now_ts - self.last_alert.get(key, 0) < ALERT_REPEAT_S:
            return
        self.last_alert[key] = now_ts
        head, body = alert_text(verdict, mount, culprit, files)
        alert = {"time": int(now_ts), "mount": mount, "title": head, "text": body,
                 "culprit": culprit, "files": files[:3]}
        auto = auto_pause_choice(verdict, culprits)
        if auto and send(auto["pid"], auto["start"], signal.SIGSTOP):
            alert["auto_paused"] = True
            self.add_paused(auto, "auto")
            body += " It was paused to protect your PC; resume or stop it in DevOS Security."
            self.tell(head, body, culprit=None, folder=None, urgency="critical", mount=mount)
        else:
            if culprit and culprit["protected"]:
                body += " (%s: not paused automatically, it could break the system)." % culprit["protected"]
            folder = os.path.dirname(files[0]["path"]) if files else None
            self.tell(head, body, culprit if culprit and not culprit["protected"] else None, folder,
                      urgency="critical" if verdict["critical"] else "normal", mount=mount)
        with self.lock:
            self.alerts = ([alert] + self.alerts)[:10]
        common.log("diskguard: %s %s" % (head, body))

    def add_paused(self, culprit, why):
        with self.lock:
            self.paused = [p for p in self.paused if p["pid"] != culprit["pid"]]
            self.paused.append({"pid": culprit["pid"], "start": culprit["start"], "comm": culprit["comm"],
                                "name": culprit["name"], "uid": culprit["uid"], "why": why,
                                "time": int(time.time())})

    def tell(self, head, body, culprit, folder, urgency, mount):
        if not self.notify:
            return
        users = common.graphical_sessions()
        if culprit:
            users = [u for u in users if u[0] == culprit["uid"]] or users
        for uid, user in users:
            actions = []
            if culprit:
                actions += [("pause", "Pause app"), ("stop", "Stop app")]
            if folder:
                actions.append(("open", "Open folder"))
            actions.append(("ignore", "Ignore"))
            cmd = common.notify_users_cmd(uid, user, head, body, "drive-harddisk", urgency, actions, wait=True)
            threading.Thread(target=self.await_choice, args=(cmd, culprit, folder, uid, user, mount),
                             daemon=True).start()

    def await_choice(self, cmd, culprit, folder, uid, user, mount):
        try:
            out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 text=True, timeout=3600).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return
        choice = out.splitlines()[-1] if out else ""
        if choice == "pause" and culprit and send(culprit["pid"], culprit["start"], signal.SIGSTOP):
            self.add_paused(culprit, "user")
        elif choice == "stop" and culprit:
            send(culprit["pid"], culprit["start"], signal.SIGTERM)
        elif choice == "open" and folder:
            subprocess.Popen(["runuser", "-u", user, "--", "env",
                              "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/%d/bus" % uid,
                              "DISPLAY=:0", "xdg-open", folder],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif choice == "ignore":
            self.ignored[(mount, culprit["comm"] if culprit else None)] = time.time() + IGNORE_S

    def write_state(self, report, now_ts):
        with self.lock:
            self.paused = [p for p in self.paused if same_process(p["pid"], p["start"], self.proc_root)]
            state = {"time": int(now_ts), "filesystems": report, "alerts": self.alerts,
                     "paused": self.paused}
        try:
            common.write_json(STATE_FILE, state, 0o644)
        except OSError:
            pass


def run_daemon():
    try:
        os.nice(19)
    except OSError:
        pass
    guard = Guard()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    while not stop.is_set():
        try:
            guard.tick()
        except Exception as exc:  # keep guarding even after an odd /proc race
            common.log("diskguard: %s" % exc)
        stop.wait(SAMPLE_S)
    return 0


def status():
    data = common.read_json(STATE_FILE)
    active = common.systemctl_state("devos-diskguard.service")
    out = {"running": active == "active", "service": active, "filesystems": [], "alerts": [],
           "paused": []}
    if isinstance(data, dict) and time.time() - data.get("time", 0) < 10 * SAMPLE_S:
        out.update({k: data.get(k, []) for k in ("filesystems", "alerts", "paused")})
    else:
        # Not running (or stale): measure now so the window still shows space.
        mounts = [m for m in parse_mounts(common.read_text("/proc/self/mounts", "")) if os.path.isdir(m)]
        for mount in mounts or ["/"]:
            if not os.path.isdir(mount):
                continue  # bind-mounted files (containers)
            try:
                total, free = statvfs_space(mount)
            except (OSError, AttributeError):
                continue
            v = detect([(0, free)], total, 0)
            out["filesystems"].append({"mount": mount, "total": total, "free": free,
                                       "low": v["low"], "critical": v["critical"], "growth": None})
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(prog="devos-diskguard")
    parser.add_argument("cmd", nargs="?", default="run", choices=("run", "status", "once"))
    args = parser.parse_args(argv)
    if args.cmd == "status":
        print(json.dumps(status(), indent=1))
        return 0
    if args.cmd == "once":
        print(json.dumps(Guard(notify=False).tick(), indent=1))
        return 0
    return run_daemon()


if __name__ == "__main__":
    sys.exit(main())
