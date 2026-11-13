#!/usr/bin/env python3
"""
Local scheduled tasks for DevOS AI (Claude Routines / Copilot Tasks style).

- Natural language: “every day at 8am remind me to stretch”
- Stored on this PC; runs while the user session is awake
- One systemd --user timer ticks every minute and fires due jobs
- Kinds: notify (desktop notification) or agent (re-run a safe prompt via tools)

No cloud. Jobs are skipped if the PC is asleep at the due minute; the next tick
after wake can catch daily jobs that still match “today not yet run”.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
DATA_DIR = Path(os.path.expanduser("~/.local/share/devos/assistant"))
SCHEDULE_FILE = DATA_DIR / "schedules.json"
UNIT_DIR = Path(os.path.expanduser("~/.config/systemd/user"))
TICK_SERVICE = "devos-ai-schedule.service"
TICK_TIMER = "devos-ai-schedule.timer"
PYTHON = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else (sys.executable or "python3")

WEEKDAY_NAMES = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}


@dataclass
class Task:
    id: str
    title: str
    prompt: str
    kind: str = "notify"          # notify | agent
    recur: str = "once"           # once | daily | weekdays | weekly
    hour: int = 9
    minute: int = 0
    weekday: Optional[int] = None  # 0=Mon … 6=Sun for weekly
    enabled: bool = True
    created: int = 0
    last_run_day: str = ""        # YYYY-MM-DD of last successful fire
    next_hint: str = ""

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(row: dict) -> Optional["Task"]:
        if not isinstance(row, dict) or not row.get("id"):
            return None
        try:
            return Task(
                id=str(row["id"]),
                title=str(row.get("title") or "Scheduled task")[:120],
                prompt=str(row.get("prompt") or "")[:500],
                kind=str(row.get("kind") or "notify"),
                recur=str(row.get("recur") or "once"),
                hour=int(row.get("hour", 9)),
                minute=int(row.get("minute", 0)),
                weekday=(None if row.get("weekday") is None else int(row["weekday"])),
                enabled=bool(row.get("enabled", True)),
                created=int(row.get("created") or 0),
                last_run_day=str(row.get("last_run_day") or ""),
                next_hint=str(row.get("next_hint") or ""),
            )
        except (TypeError, ValueError):
            return None


def load_tasks(path: Optional[Path] = None) -> List[Task]:
    p = path or SCHEDULE_FILE
    try:
        with p.open(encoding="utf-8") as fh:
            rows = json.load(fh)
        if not isinstance(rows, list):
            return []
        out = []
        for row in rows:
            t = Task.from_json(row)
            if t:
                out.append(t)
        return out
    except (OSError, ValueError, TypeError):
        return []


def save_tasks(tasks: List[Task], path: Optional[Path] = None) -> None:
    p = path or SCHEDULE_FILE
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(p.parent), delete=False
    ) as fh:
        pending = Path(fh.name)
        try:
            json.dump([t.to_json() for t in tasks], fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
            fh.close()
            pending.replace(p)
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
        finally:
            pending.unlink(missing_ok=True)


def _parse_clock(h: str, mi: str, ap: str) -> Tuple[int, int]:
    hour = int(h)
    minute = int(mi or 0)
    ap = (ap or "").lower().replace(".", "")
    if ap == "pm" and hour < 12:
        hour += 12
    elif ap == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError("bad clock")
    return hour, minute


_SCHED_RE = re.compile(
    r"(?i)^\s*(?:please\s+|pls\s+)?"
    r"(?:(?:schedule|set|create|add|make)\s+(?:a\s+|an\s+|me\s+a\s+)?)?"
    r"(?P<recur>"
    r"every\s+day|everyday|daily|"
    r"every\s+weekday|weekdays|each\s+weekday|"
    r"every\s+(?P<wd>monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)"
    r")"
    r"(?:\s+at\s+|\s+)(?P<h>\d{1,2})(?::(?P<mi>\d{2}))?\s*(?P<ap>a\.?m\.?|p\.?m\.?)?"
    r"(?:\s*[,:]?\s*|\s+)"
    r"(?:(?:to|and)\s+)?"
    r"(?:(?:remind\s+me(?:\s+to)?|tell\s+me(?:\s+to)?|notify\s+me(?:\s+to)?)\s+)?"
    r"(?P<what>.+?)\s*$"
)

_LIST_RE = re.compile(
    r"(?i)^\s*(?:(?:list|show|what are|my)\s+)?(?:my\s+)?"
    r"(?:scheduled\s+tasks?|schedules?|recurring\s+(?:tasks?|reminders?)|timers?\s+and\s+schedules?)"
    r"(?:\s+please)?\s*$"
)

_CANCEL_RE = re.compile(
    r"(?i)^\s*(?:cancel|delete|remove|stop)\s+(?:the\s+|my\s+)?"
    r"(?:schedule[d]?\s+(?:tasks?|reminders?)?|recurring\s+(?:tasks?|reminders?)|"
    r"scheduled\s+tasks?)"
    r"(?:\s+(?P<q>.+?))?\s*$"
)


def parse_schedule_request(text: str) -> Optional[dict]:
    """Parse natural language into schedule fields, or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    m = _SCHED_RE.match(raw)
    if not m:
        return None
    try:
        hour, minute = _parse_clock(m.group("h"), m.group("mi"), m.group("ap") or "")
    except ValueError:
        return None
    recur_raw = (m.group("recur") or "").lower()
    wd_name = (m.group("wd") or "").lower()
    if "weekday" in recur_raw:
        recur = "weekdays"
        weekday = None
    elif wd_name:
        recur = "weekly"
        weekday = WEEKDAY_NAMES.get(wd_name)
    else:
        recur = "daily"
        weekday = None
    what = (m.group("what") or "").strip().strip(" .")
    what = re.sub(r"^(?:to\s+|that\s+)", "", what, flags=re.I).strip()
    if len(what) < 2:
        return None
    # Agent kind when the payload looks like an action, else notify
    kind = "notify"
    if re.search(
        r"(?i)\b(?:open|search|check|scan|cleanup|clean|install|summarize|read|run|launch)\b",
        what,
    ):
        kind = "agent"
    title = what[:60]
    return {
        "title": title,
        "prompt": what,
        "kind": kind,
        "recur": recur,
        "hour": hour,
        "minute": minute,
        "weekday": weekday,
    }


def wants_list_schedules(text: str) -> bool:
    return bool(_LIST_RE.match((text or "").strip()))


def parse_cancel(text: str) -> Optional[str]:
    m = _CANCEL_RE.match((text or "").strip())
    if not m:
        return None
    q = (m.group("q") or "").strip()
    if not q or q.lower() in ("all", "everything", "all schedules", "all tasks"):
        return "*"
    return q


def human_when(task: Task) -> str:
    clock = f"{task.hour % 12 or 12}:{task.minute:02d} {'AM' if task.hour < 12 else 'PM'}"
    if task.recur == "daily":
        return f"every day at {clock}"
    if task.recur == "weekdays":
        return f"every weekday at {clock}"
    if task.recur == "weekly":
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day = names[task.weekday] if task.weekday is not None and 0 <= task.weekday <= 6 else "week"
        return f"every {day} at {clock}"
    return f"once at {clock}"


def add_task(fields: dict, path: Optional[Path] = None) -> Task:
    tasks = load_tasks(path)
    task = Task(
        id=uuid.uuid4().hex[:12],
        title=str(fields["title"])[:120],
        prompt=str(fields["prompt"])[:500],
        kind=str(fields.get("kind") or "notify"),
        recur=str(fields.get("recur") or "daily"),
        hour=int(fields["hour"]),
        minute=int(fields["minute"]),
        weekday=fields.get("weekday"),
        enabled=True,
        created=int(time.time()),
        next_hint=human_when(
            Task(
                id="x",
                title="",
                prompt="",
                recur=str(fields.get("recur") or "daily"),
                hour=int(fields["hour"]),
                minute=int(fields["minute"]),
                weekday=fields.get("weekday"),
            )
        ),
    )
    tasks.append(task)
    save_tasks(tasks, path)
    ensure_tick_timer()
    return task


def cancel_tasks(query: str, path: Optional[Path] = None) -> int:
    tasks = load_tasks(path)
    if query == "*":
        n = len(tasks)
        save_tasks([], path)
        return n
    q = query.lower()
    kept = [t for t in tasks if q not in t.title.lower() and q not in t.prompt.lower() and q not in t.id]
    removed = len(tasks) - len(kept)
    if removed:
        save_tasks(kept, path)
    return removed


def due_now(task: Task, now: Optional[dt.datetime] = None) -> bool:
    now = now or dt.datetime.now()
    if not task.enabled:
        return False
    if now.hour != task.hour or now.minute != task.minute:
        return False
    today = now.strftime("%Y-%m-%d")
    if task.last_run_day == today:
        return False
    wd = now.weekday()  # Mon=0
    if task.recur == "daily":
        return True
    if task.recur == "weekdays":
        return wd < 5
    if task.recur == "weekly":
        return task.weekday is not None and wd == task.weekday
    if task.recur == "once":
        return True
    return False


def _notify(title: str, message: str) -> None:
    if shutil_which("notify-send"):
        subprocess.run(
            ["notify-send", "--app-name=DevOS AI", "--urgency=normal",
             "--icon=chronometer", title, message],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            check=False,
        )
    elif shutil_which("kdialog"):
        subprocess.run(
            ["kdialog", "--title", "DevOS AI", "--passivepopup", f"{title}\n{message}", "12"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
            check=False,
        )


def shutil_which(name: str) -> Optional[str]:
    from shutil import which
    return which(name)


def run_task(task: Task) -> str:
    """Execute one due task. Returns a short status string."""
    if task.kind == "agent":
        try:
            if str(HERE) not in sys.path:
                sys.path.insert(0, str(HERE))
            import tools
            result = tools.route(task.prompt)
            if result.actions:
                texts = []
                for a in result.actions:
                    # Skip destructive / confirm-gated actions when unattended
                    if a.confirm:
                        texts.append(f"Skipped (needs confirm): {a.label or a.name}")
                        continue
                    if a.name in ("power", "uninstall"):
                        texts.append(f"Skipped unsafe: {a.name}")
                        continue
                    res = tools.execute(a, dry_run=False)
                    texts.append(res.text[:300])
                msg = " · ".join(texts) or task.prompt
            else:
                msg = f"Scheduled: {task.prompt}"
            _notify(task.title or "DevOS AI", msg[:200])
            return msg
        except Exception as exc:
            _notify("DevOS AI schedule", f"Could not run: {exc}")
            return str(exc)
    # notify
    body = task.prompt or task.title
    _notify(task.title or "Reminder", body)
    return body


def tick(path: Optional[Path] = None, now: Optional[dt.datetime] = None) -> List[str]:
    """Fire every due task for this minute. Called by the systemd timer."""
    now = now or dt.datetime.now()
    today = now.strftime("%Y-%m-%d")
    tasks = load_tasks(path)
    logs: List[str] = []
    changed = False
    for t in tasks:
        if due_now(t, now):
            try:
                logs.append(run_task(t))
            except Exception as exc:
                logs.append(str(exc))
            t.last_run_day = today
            changed = True
            if t.recur == "once":
                t.enabled = False
                changed = True
    if changed:
        live = [t for t in tasks if not (t.recur == "once" and not t.enabled)]
        save_tasks(live, path)
    return logs


def ensure_tick_timer() -> bool:
    """Install / refresh the user systemd timer that runs tick every minute."""
    try:
        UNIT_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    script = HERE / "schedule.py"
    service = UNIT_DIR / TICK_SERVICE
    timer = UNIT_DIR / TICK_TIMER
    service_body = (
        "[Unit]\nDescription=DevOS AI scheduled tasks tick\n\n"
        "[Service]\nType=oneshot\n"
        f"ExecStart={PYTHON} {script} --tick\n"
    )
    timer_body = (
        "[Unit]\nDescription=DevOS AI schedule timer (every minute)\n\n"
        "[Timer]\nOnCalendar=*-*-* *:*:00\nPersistent=true\nAccuracySec=30s\n\n"
        "[Install]\nWantedBy=timers.target\n"
    )
    try:
        service.write_text(service_body, encoding="utf-8")
        timer.write_text(timer_body, encoding="utf-8")
    except OSError:
        return False
    if not shutil_which("systemctl"):
        return False
    try:
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", TICK_TIMER],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False,
        )
        return True
    except Exception:
        return False


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="DevOS AI local schedule")
    p.add_argument("--tick", action="store_true", help="run due tasks for this minute")
    p.add_argument("--install-timer", action="store_true", help="install user systemd timer")
    p.add_argument("--list", action="store_true")
    ns = p.parse_args(argv)
    if ns.install_timer:
        ok = ensure_tick_timer()
        print("timer ok" if ok else "timer install failed")
        return 0 if ok else 1
    if ns.tick:
        for line in tick():
            print(line)
        return 0
    if ns.list:
        for t in load_tasks():
            print(f"{t.id}\t{human_when(t)}\t{t.title}\t{t.kind}")
        return 0
    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
