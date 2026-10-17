#!/usr/bin/env python3
"""
One browser per AI agent, as many as this PC can keep smooth.

A normal Chrome shares one profile, so a second launch joins the first window
and the agents block each other. Each agent here gets its own profile, a
memory ceiling and a fair share of the CPU. Starting another one past the
PC's capacity is refused, so the ones already open stay usable.

Nothing here turns the sandbox off, and a disguised or short address is not
opened. The desktop Chrome is a different profile and is left alone.
"""

import os
import re
import subprocess
import sys

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
BROWSERS = ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser")
RESERVE_MB = 2800
PER_AGENT_MB = 500
MAX_AGENTS = 32
MEMORY_HIGH_MB = 700
STAGGER_SEC = 0.35

# Lean, still sandboxed. No --no-sandbox and no --disable-web-security.
LEAN_FLAGS = (
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-sync",
    "--disable-translate",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-domain-reliability",
    "--disable-breakpad",
    "--disable-notifications",
    "--no-pings",
    "--password-store=basic",
    "--disk-cache-size=67108864",
    "--media-cache-size=8388608",
    "--renderer-process-limit=2",
    "--disable-dev-shm-usage",
    "--disable-features=TranslateUI,MediaRouter,OptimizationHints",
)


def capacity(ram_mb):
    """How many agent browsers stay smooth on this much RAM."""
    if not ram_mb or ram_mb <= 0:
        return 2
    spare = int(ram_mb) - RESERVE_MB
    if spare < PER_AGENT_MB:
        return 1
    return max(1, min(MAX_AGENTS, spare // PER_AGENT_MB))


def ram_mb(meminfo=None):
    text = meminfo
    if text is None:
        try:
            with open("/proc/meminfo", encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            return 0
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) // 1024
    return 0


def agent_root(home=None):
    home = home or os.path.expanduser("~")
    return os.path.join(home, ".local", "share", "DevOS", "agent-browsers")


def profile_dir(agent_id, home=None):
    return os.path.join(agent_root(home), agent_id)


def valid_id(agent_id):
    return bool(ID_RE.match(agent_id or ""))


def find_browser(which=None):
    which = which or _which
    for name in BROWSERS:
        path = which(name)
        if path:
            return path
    return None


def _which(name):
    from shutil import which
    return which(name)


def chrome_argv(browser, agent_id, url, home=None):
    argv = [browser, f"--user-data-dir={profile_dir(agent_id, home)}",
            f"--class=DevOS-agent-{agent_id}"]
    argv.extend(LEAN_FLAGS)
    argv.append(url or "about:blank")
    return argv


def scope_argv(agent_id, chrome):
    """A transient user service: fair CPU, a memory ceiling, and it returns at once."""
    return [
        "systemd-run", "--user", "--no-block", "--collect",
        f"--unit=devos-agent-browser-{agent_id}",
        "-p", f"MemoryHigh={MEMORY_HIGH_MB}M",
        "-p", "MemorySwapMax=300M",
        "-p", "CPUWeight=30",
        "-p", "IOWeight=40",
        "-p", "Nice=5",
        "--",
        *chrome,
    ]


def running_ids(home=None, proc_root="/proc"):
    """Agent ids that already have a browser, from their --user-data-dir."""
    root = os.path.abspath(agent_root(home))
    found = {}
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return found
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(os.path.join(proc_root, entry, "cmdline"), "rb") as handle:
                raw = handle.read().decode("utf-8", "replace")
        except OSError:
            continue
        for part in raw.split("\0"):
            if not part.startswith("--user-data-dir="):
                continue
            data = os.path.abspath(part.split("=", 1)[1])
            if data == root or not data.startswith(root + os.sep):
                continue
            agent_id = os.path.basename(data)
            if valid_id(agent_id):
                found.setdefault(agent_id, []).append(int(entry))
    return found


def check_url(url, inspect=None):
    """None when the address may open. A sentence when it must not."""
    if not url:
        return None
    raw = url.strip()
    low = raw.lower()
    if low.startswith(("javascript:", "data:", "file:")):
        return "That address is not opened."
    if not low.startswith(("http://", "https://")):
        return "Use an http or https address."
    if inspect is None:
        inspect = _inspect
    try:
        verdict = inspect(raw)
    except Exception:
        return None
    if isinstance(verdict, dict) and verdict.get("level") in ("block", "warn"):
        return verdict.get("summary") or "This address was not opened."
    return None


def _inspect(url):
    sec = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "security"))
    if sec not in sys.path:
        sys.path.insert(0, sec)
    import linkguard
    return linkguard.inspect_url(url)


def plan_open(agent_id, url="", home=None, ram=None, running=None, browser=None, inspect=None):
    """What to do for one agent. Does not start anything."""
    if not valid_id(agent_id):
        return {"action": "error", "id": agent_id or "",
                "text": "An agent name is lowercase letters, digits and hyphens, up to 32 characters."}
    blocked = check_url(url, inspect=inspect)
    if blocked:
        return {"action": "blocked", "id": agent_id, "text": blocked}
    if browser is None:
        browser = find_browser()
    if not browser:
        return {"action": "error", "id": agent_id,
                "text": "Chrome is not installed yet. On the installed system, run: sudo devos-install-chrome"}
    live = set(running if running is not None else running_ids(home))
    chrome = chrome_argv(browser, agent_id, url, home)
    if agent_id in live:
        return {"action": "focus", "id": agent_id, "argv": chrome,
                "text": f"{agent_id} is already open. The address opens in that browser."}
    cap = capacity(ram if ram is not None else ram_mb())
    if len(live) >= cap:
        return {"action": "refuse", "id": agent_id,
                "text": (f"This PC keeps {cap} agent browser{'s' if cap != 1 else ''} smooth, "
                         f"and {len(live)} are already open. Close one before starting {agent_id}.")}
    return {"action": "start", "id": agent_id, "argv": scope_argv(agent_id, chrome),
            "text": f"Starting {agent_id}. This PC keeps {cap} agent browsers smooth."}


def plan_many(ids, url="", home=None, ram=None, running=None, browser=None, inspect=None):
    live = set(running or [])
    plans = []
    for agent_id in ids:
        plan = plan_open(agent_id, url=url, home=home, ram=ram, running=live,
                         browser=browser, inspect=inspect)
        plans.append(plan)
        if plan["action"] in ("start", "focus"):
            live.add(agent_id)
    return plans


def describe(ram, running_count):
    cap = capacity(ram)
    noun = "browser" if cap == 1 else "browsers"
    return (f"This PC can keep {cap} agent {noun} smooth"
            f" ({ram_label(ram)}). {running_count} running.")


def ram_label(ram):
    if not ram:
        return "RAM not read"
    if ram >= 1024:
        whole = ram // 1024
        if ram % 1024 < 128:
            return f"{whole} GB RAM"
    return f"{ram} MB RAM"


def spawn(argv):
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True)


def run_plans(plans, spawn_fn=None, pause=None):
    spawn_fn = spawn_fn or spawn
    pause = pause or _sleep
    started = 0
    for plan in plans:
        action = plan.get("action")
        if action == "start" and started:
            pause(STAGGER_SEC)
        if action in ("start", "focus") and plan.get("argv"):
            spawn_fn(plan["argv"])
            if action == "start":
                started += 1
        print(plan.get("text") or action)


def _sleep(seconds):
    import time
    time.sleep(seconds)


def close_ids(agent_id, home=None, proc_root="/proc", kill=None):
    if not valid_id(agent_id):
        return {"ok": False, "text": "An agent name is lowercase letters, digits and hyphens, up to 32 characters."}
    pids = running_ids(home, proc_root).get(agent_id) or []
    if not pids:
        return {"ok": True, "text": f"{agent_id} is not running."}
    kill = kill or _kill
    stopped = 0
    for pid in pids:
        if pid <= 1:
            continue
        try:
            kill(pid)
            stopped += 1
        except OSError:
            pass
    if not stopped:
        return {"ok": False, "text": f"Could not close {agent_id}."}
    return {"ok": True, "text": f"Closed {agent_id}."}


def _kill(pid):
    os.kill(pid, 15)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("Usage: devos-agent-browser capacity")
        print("       devos-agent-browser list")
        print("       devos-agent-browser open <name> [--url https://...]")
        print("       devos-agent-browser open-many <name> [name...] [--url https://...]")
        print("       devos-agent-browser close <name>")
        print("Each name is its own browser. This PC starts only as many as stay smooth.")
        return 0
    cmd = argv[0]
    if cmd == "capacity":
        live = running_ids()
        print(describe(ram_mb(), len(live)))
        return 0
    if cmd == "list":
        live = running_ids()
        if not live:
            print("No agent browsers are open.")
            print(describe(ram_mb(), 0))
            return 0
        for agent_id in sorted(live):
            print(f"{agent_id}\t{len(live[agent_id])} process(es)")
        print(describe(ram_mb(), len(live)))
        return 0
    if cmd == "open":
        if len(argv) < 2:
            print("Name the agent: devos-agent-browser open research", file=sys.stderr)
            return 2
        url = _url_flag(argv[2:])
        plan = plan_open(argv[1], url=url)
        run_plans([plan])
        return 0 if plan["action"] in ("start", "focus") else 1
    if cmd == "open-many":
        names, url = _names_and_url(argv[1:])
        if not names:
            print("Name at least one agent.", file=sys.stderr)
            return 2
        plans = plan_many(names, url=url, running=set(running_ids()), ram=ram_mb(),
                          browser=find_browser())
        run_plans(plans)
        return 0 if any(p["action"] in ("start", "focus") for p in plans) else 1
    if cmd == "close":
        if len(argv) < 2:
            print("Name the agent to close.", file=sys.stderr)
            return 2
        result = close_ids(argv[1])
        print(result["text"])
        return 0 if result["ok"] else 1
    print(f"Unknown command {cmd}.", file=sys.stderr)
    return 2


def _url_flag(rest):
    if rest[:1] == ["--url"] and len(rest) >= 2:
        return rest[1]
    return ""


def _names_and_url(rest):
    if "--url" in rest:
        at = rest.index("--url")
        url = rest[at + 1] if at + 1 < len(rest) else ""
        names = rest[:at]
    else:
        url = ""
        names = rest
    return names, url


if __name__ == "__main__":
    sys.exit(main())
