#!/usr/bin/env python3
"""
DevOS Master Unified CLI
Dispatcher for all DevOS subsystems with interactive arrow-key suggestions and fuzzy completion.
"""

import sys
import os
import subprocess
import shutil
import difflib

COMPONENTS_DIR = os.path.dirname(os.path.abspath(__file__))

COMMAND_CATALOG = {
    "dashboard": {
        "desc": "Open Luxury System Dashboard & PIN/Security Hub",
        "tags": ["panel", "security", "pin", "system", "hub"],
    },
    "setup": {
        "desc": "Launch Interactive First-Boot Configuration Wizard",
        "tags": ["wizard", "welcome", "init", "install", "firstboot"],
    },
    "app": {
        "desc": "Universal App Hub (Windows, Linux, Android)",
        "tags": ["install", "store", "hub", "packages", "flatpak", "apps"],
    },
    "code": {
        "desc": "DevOS AI Code Agent: local coding assistant & repo agent",
        "tags": ["coder", "programming", "developer", "git", "ide"],
    },
    "serve": {
        "desc": "Local developer server manager (Caddy, PHP, DB, Redis)",
        "tags": ["web", "caddy", "server", "php", "mysql", "redis", "laragon", "devserver"],
    },
    "ai": {
        "desc": "System assistant with safe tool calling",
        "tags": ["llm", "chat", "agent", "prompt", "assistant"],
    },
    "win": {
        "desc": "WinLayer prefix manager and compatibility doctor",
        "tags": ["windows", "wine", "proton", "exe", "compat"],
    },
    "android": {
        "desc": "Android & Waydroid container manager and APK runner",
        "tags": ["apk", "waydroid", "mobile", "container"],
    },
    "watchdog": {
        "desc": "System memory pressure and storage audit",
        "tags": ["ram", "memory", "oom", "disk", "pressure"],
    },
    "doctor": {
        "desc": "System health, heavy load & storage check",
        "tags": ["diagnostics", "check", "health", "audit", "fix"],
    },
    "net": {
        "desc": "Wi-Fi and Ethernet connection manager",
        "tags": ["wifi", "network", "ethernet", "internet", "lan", "wlan"],
    },
    "sound": {
        "desc": "PipeWire audio and volume controller",
        "tags": ["audio", "volume", "sound", "speaker", "pipewire", "mute"],
    },
    "driver": {
        "desc": "GPU, Wi-Fi, Bluetooth, and printer drivers",
        "tags": ["nvidia", "hardware", "gpu", "bluetooth", "printer"],
    },
    "disk": {
        "desc": "Storage devices, MBR/GPT partition tables & formatting",
        "tags": ["storage", "partition", "drive", "format", "mbr", "gpt"],
    },
    "link": {
        "desc": "Phone Link: control and manage this PC from your phone",
        "tags": ["phone", "phonelink", "remote", "control", "mobile"],
    },
    "share": {
        "desc": "Make a local app public: devos share start 3000",
        "tags": ["tunnel", "public", "port", "cloudflared", "internet"],
    },
    "backup": {
        "desc": "Optional Google Drive / OneDrive backup of your folders",
        "tags": ["cloud", "gdrive", "onedrive", "sync", "backup"],
    },
    "models": {
        "desc": "DevOS AI models for this PC, and the local AI API",
        "tags": ["llm", "gguf", "llama", "download", "api", "ollama"],
    },
    "auto": {
        "desc": "Local AI automations: commit, review, explain, summarize",
        "tags": ["commit", "review", "explain", "summarize", "hook"],
    },
    "agents": {
        "desc": "One browser per AI agent for isolated multi-tasking",
        "tags": ["browser", "multi", "tasks", "research"],
    },
    "features": {
        "desc": "Add or remove apps and features (Office, browsers, games)",
        "tags": ["apps", "optional", "office", "browser", "games"],
    },
    "restore": {
        "desc": "btrfs restore points (create, list, rollback)",
        "tags": ["snapshot", "btrfs", "rollback", "recover", "snap"],
    },
    "vault": {
        "desc": "Encrypt and protect a folder after install",
        "tags": ["encryption", "security", "luks", "crypto", "safe"],
    },
    "finger": {
        "desc": "Fingerprint sign-in and biometric manager",
        "tags": ["fingerprint", "biometrics", "login", "auth"],
    },
    "domain": {
        "desc": "Join an Active Directory domain",
        "tags": ["activedirectory", "ad", "enterprise", "samba", "ldap"],
    },
    "updates": {
        "desc": "Security updates and Flatpak updates, after a restore point",
        "tags": ["upgrade", "patch", "apt", "flatpak", "security"],
    },
    "update": {
        "desc": "Get the latest DevOS release from GitHub (--check, --version, --os-upgrade)",
        "tags": ["upgrade", "github", "os-upgrade", "release", "version"],
    },
    "kids": {
        "desc": "Mouse-play overlay; apps keep running (Win+K)",
        "tags": ["child", "lock", "toddler", "play"],
    },
    "task": {
        "desc": "Task Manager: processes, performance, startup apps",
        "tags": ["taskman", "process", "kill", "cpu", "performance", "top"],
    },
    "recorder": {
        "desc": "Screen, Window & Region Video Recorder (MP4 / WebM)",
        "tags": ["record", "recording", "screencast", "video", "capture", "mp4", "webm", "screen"],
    },
    "modesty": {
        "desc": "Browser Modesty & safe surfing filter (NSFW / Gore blur)",
        "tags": ["blur", "nsfw", "gore", "modest", "safe", "safesurfing", "filter", "blr"],
    },
    "assistant": {
        "desc": "DevOS AI Desktop Assistant overlay & conversational chat",
        "tags": ["chat", "ai", "ask", "assistant", "help"],
    },
    "familysafe": {
        "desc": "Family safety controls and protected browsing",
        "tags": ["family", "parental", "shield", "protect"],
    },
    "islamic": {
        "desc": "Islamic prayer times, daily verses & Qibla finder",
        "tags": ["prayer", "namaz", "azan", "salat", "qibla", "quran"],
    },
    "notepad": {
        "desc": "Quick Sticky Notes & Scratchpad",
        "tags": ["notes", "memo", "text", "scratchpad"],
    },
    "clipboard": {
        "desc": "System clipboard history & quick paste manager",
        "tags": ["copy", "paste", "history", "clip"],
    },
    "emoji": {
        "desc": "Emoji & symbol picker keyboard helper",
        "tags": ["symbol", "icons", "smileys", "emoji"],
    },
    "power": {
        "desc": "Power profiles, battery management & sleep controls",
        "tags": ["battery", "sleep", "suspend", "hibernate", "energy"],
    },
    "voice": {
        "desc": "Voice typing & speech-to-text dictation",
        "tags": ["voicetype", "speech", "dictation", "mic", "talk"],
    },
    "optimizer": {
        "desc": "System cache, RAM & disk optimizer",
        "tags": ["clean", "cache", "ram", "speed", "boost"],
    },
    "theme": {
        "desc": "Switch system appearance between Dark and Light theme",
        "tags": ["appearance", "dark", "light", "colors", "style", "mode", "toggle"],
    },
    "broadband": {
        "desc": "Mobile broadband & cellular modem connection manager",
        "tags": ["modem", "cellular", "lte", "sim", "4g", "5g"],
    },
}


def is_subsequence(sub, string):
    it = iter(string)
    return all(c in it for c in sub)


def smart_match(query, candidates, tags_map):
    q = query.lower().strip()
    if not q:
        return candidates

    scores = {}
    for c in candidates:
        c_low = c.lower()
        if c_low == q:
            scores[c] = 100
        elif c_low.startswith(q):
            scores[c] = 80 - len(c_low)
        elif q in c_low:
            scores[c] = 60
        elif is_subsequence(q, c_low):
            scores[c] = 40
        else:
            ratio = difflib.SequenceMatcher(None, q, c_low).ratio()
            if ratio > 0.45:
                scores[c] = int(ratio * 50)

    # Check tags & descriptions
    for cmd, tags in tags_map.items():
        if cmd not in scores:
            scores[cmd] = 0
        for tag in tags:
            tag_low = tag.lower()
            if tag_low == q:
                scores[cmd] = max(scores[cmd], 95)
            elif tag_low.startswith(q):
                scores[cmd] = max(scores[cmd], 75)
            elif q in tag_low:
                scores[cmd] = max(scores[cmd], 55)
            elif is_subsequence(q, tag_low):
                scores[cmd] = max(scores[cmd], 35)
            else:
                ratio = difflib.SequenceMatcher(None, q, tag_low).ratio()
                if ratio > 0.55:
                    scores[cmd] = max(scores[cmd], int(ratio * 45))

    sorted_matches = [k for k, v in sorted(scores.items(), key=lambda x: x[1], reverse=True) if v > 15]
    return sorted_matches


def select_with_fzf(items, prequery="", header="DevOS Command Selector"):
    fzf_bin = shutil.which("fzf")
    if not fzf_bin:
        return None
    input_text = "\n".join([f"{cmd:12}  {info['desc']}" for cmd, info in items.items()])
    cmd = [
        fzf_bin,
        "--height=16",
        "--layout=reverse",
        "--border",
        "--inline-info",
        "--prompt=devos ❯ ",
        f"--header={header}\n  [↑/↓: Navigate | Type to filter | Enter: Run | Esc: Exit]",
        "--ansi",
    ]
    if prequery:
        cmd.append(f"--query={prequery}")
    try:
        proc = subprocess.run(cmd, input=input_text, text=True, stdout=subprocess.PIPE, stderr=None)
        if proc.returncode == 0 and proc.stdout.strip():
            selected_line = proc.stdout.strip().split("\n")[0]
            selected_cmd = selected_line.split()[0].strip()
            return selected_cmd
    except Exception:
        pass
    return None


def select_with_ansi(items, prequery="", header="DevOS Command Selector"):
    try:
        import termios
        import tty
        import select
    except ImportError:
        return None

    fd = sys.stdin.fileno()
    try:
        old_settings = termios.tcgetattr(fd)
    except Exception:
        return None

    def get_key():
        ch = os.read(fd, 1)
        if ch == b"\x1b":
            r, _, _ = select.select([fd], [], [], 0.05)
            if not r:
                return "ESC"
            seq = b"\x1b"
            while True:
                r, _, _ = select.select([fd], [], [], 0.02)
                if not r:
                    break
                seq += os.read(fd, 1)
            if seq in (b"\x1b[A", b"\x1bOA"):
                return "UP"
            if seq in (b"\x1b[B", b"\x1bOB"):
                return "DOWN"
            if seq == b"\x1b[5~":
                return "PAGE_UP"
            if seq == b"\x1b[6~":
                return "PAGE_DOWN"
            if seq in (b"\x1b[H", b"\x1b[1~"):
                return "HOME"
            if seq in (b"\x1b[F", b"\x1b[4~"):
                return "END"
            return "ESC"
        if ch in (b"\r", b"\n"):
            return "ENTER"
        if ch in (b"\x7f", b"\x08"):
            return "BACKSPACE"
        if ch == b"\t":
            return "TAB"
        if ch in (b"\x03", b"\x04"):
            return "CTRL_C"
        try:
            return ch.decode("utf-8")
        except UnicodeDecodeError:
            return ""

    query = prequery
    selected_idx = 0
    page_size = 10
    prev_lines_printed = 0
    tags_map = {k: v.get("tags", []) for k, v in items.items()}

    try:
        tty.setraw(fd)
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

        while True:
            if query.strip():
                filtered_cmds = smart_match(query, list(items.keys()), tags_map)
            else:
                filtered_cmds = list(items.keys())

            if not filtered_cmds:
                filtered_cmds = []
                selected_idx = 0
            else:
                selected_idx = max(0, min(selected_idx, len(filtered_cmds) - 1))

            start_idx = (selected_idx // page_size) * page_size
            end_idx = min(start_idx + page_size, len(filtered_cmds))
            page_cmds = filtered_cmds[start_idx:end_idx]

            if prev_lines_printed > 0:
                sys.stdout.write(f"\033[{prev_lines_printed}A\r")
                for _ in range(prev_lines_printed):
                    sys.stdout.write("\033[2K\n")
                sys.stdout.write(f"\033[{prev_lines_printed}A\r")

            lines = []
            lines.append(f"\033[1;36m{header}\033[0m")
            lines.append(f"\033[1;33mSearch:\033[0m {query}\033[1;32m_\033[0m  \033[2m(Matches: {len(filtered_cmds)})\033[0m")
            lines.append("\033[2m─────────────────────────────────────────────────────────────────\033[0m")

            if not filtered_cmds:
                lines.append("  \033[31mNo matching DevOS command found.\033[0m")
            else:
                for idx, cmd in enumerate(page_cmds, start=start_idx):
                    desc = items[cmd]["desc"]
                    if idx == selected_idx:
                        lines.append(f"  \033[1;32m❯ {cmd:12} \033[1;37m{desc}\033[0m")
                    else:
                        lines.append(f"    \033[0;36m{cmd:12}\033[0m \033[2m{desc}\033[0m")

            total = len(filtered_cmds)
            current_pos = f"[{selected_idx + 1}/{total}]" if total > 0 else "[0/0]"
            lines.append("\033[2m─────────────────────────────────────────────────────────────────\033[0m")
            lines.append(f"\033[2m↑/↓: Navigate | Enter: Run | Esc: Exit | {current_pos}\033[0m")

            sys.stdout.write("\r\n".join(lines) + "\r\n")
            sys.stdout.flush()
            prev_lines_printed = len(lines)

            key = get_key()
            if key == "ENTER":
                if filtered_cmds:
                    return filtered_cmds[selected_idx]
                return None
            elif key in ("ESC", "CTRL_C"):
                return None
            elif key == "UP":
                if selected_idx > 0:
                    selected_idx -= 1
                elif filtered_cmds:
                    selected_idx = len(filtered_cmds) - 1
            elif key == "DOWN":
                if filtered_cmds and selected_idx < len(filtered_cmds) - 1:
                    selected_idx += 1
                else:
                    selected_idx = 0
            elif key == "PAGE_UP":
                selected_idx = max(0, selected_idx - page_size)
            elif key == "PAGE_DOWN":
                if filtered_cmds:
                    selected_idx = min(len(filtered_cmds) - 1, selected_idx + page_size)
            elif key == "HOME":
                selected_idx = 0
            elif key == "END":
                if filtered_cmds:
                    selected_idx = len(filtered_cmds) - 1
            elif key == "BACKSPACE":
                if len(query) > 0:
                    query = query[:-1]
                    selected_idx = 0
            elif len(key) == 1 and key.isprintable():
                query += key
                selected_idx = 0
    finally:
        sys.stdout.write("\033[?25h")
        if prev_lines_printed > 0:
            sys.stdout.write(f"\033[{prev_lines_printed}A\r")
            for _ in range(prev_lines_printed):
                sys.stdout.write("\033[2K\n")
            sys.stdout.write(f"\033[{prev_lines_printed}A\r")
        sys.stdout.flush()
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        except Exception:
            pass


def interactive_select(items, prequery="", header="DevOS Unified CLI - Select Command"):
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    res = select_with_fzf(items, prequery=prequery, header=header)
    if res is not None:
        return res
    return select_with_ansi(items, prequery=prequery, header=header)


def print_help():
    print("DevOS Unified Command Line Interface")
    print("=====================================")
    print("Usage: devos <subsystem> [arguments...]")
    print("       devos                     (Interactive suggestion menu with arrow selection)")
    print("\nSubsystems & Commands:")
    for cmd, info in COMMAND_CATALOG.items():
        print(f"  {cmd:12} {info['desc']}")
    print("\nTip: Type 'devos' and use ↑/↓ arrow keys to select, or type partial names for instant suggestions.")


def main():
    hardware_script = os.path.join(COMPONENTS_DIR, "settings", "hardware_manager.py")
    dashboard_script = os.path.join(COMPONENTS_DIR, "dashboard", "dashboard_server.py")
    disk_script = os.path.join(COMPONENTS_DIR, "settings", "disk_manager.py")

    dispatch_map = {
        "kids": os.path.join(COMPONENTS_DIR, "kids", "kids_mode.py"),
        "dashboard": dashboard_script,
        "setup": dashboard_script,
        "app": os.path.join(COMPONENTS_DIR, "apphub", "hub.py"),
        "code": os.path.join(COMPONENTS_DIR, "code-agent", "code_agent.py"),
        "code-agent": os.path.join(COMPONENTS_DIR, "code-agent", "code_agent.py"),
        "agent": os.path.join(COMPONENTS_DIR, "code-agent", "code_agent.py"),
        "serve": os.path.join(COMPONENTS_DIR, "devserver", "server_manager.py"),
        "ai": os.path.join(COMPONENTS_DIR, "ai-agent", "agent.py"),
        "win": os.path.join(COMPONENTS_DIR, "winlayer", "prefix_manager.py"),
        "android": os.path.join(COMPONENTS_DIR, "androidlayer", "waydroid_manager.py"),
        "watchdog": os.path.join(COMPONENTS_DIR, "ai-agent", "system_watchdog.py"),
        "doctor": os.path.join(COMPONENTS_DIR, "ai-agent", "system_watchdog.py"),
        "net": hardware_script,
        "sound": hardware_script,
        "driver": hardware_script,
        "disk": disk_script,
        "storage": disk_script,
        "link": os.path.join(COMPONENTS_DIR, "phonelink", "phonelink.py"),
        "phone": os.path.join(COMPONENTS_DIR, "phonelink", "phonelink.py"),
        "share": os.path.join(COMPONENTS_DIR, "share", "share.py"),
        "backup": os.path.join(COMPONENTS_DIR, "backup", "cloud_backup.py"),
        "models": os.path.join(COMPONENTS_DIR, "ai-core", "models_cli.py"),
        "auto": os.path.join(COMPONENTS_DIR, "ai-core", "automate.py"),
        "agents": os.path.join(COMPONENTS_DIR, "ai-agent", "agent_browser.py"),
        "features": os.path.join(COMPONENTS_DIR, "features", "features_cli.py"),
        "restore": os.path.join(COMPONENTS_DIR, "settings", "snapshot_manager.py"),
        "vault": os.path.join(COMPONENTS_DIR, "settings", "vault.py"),
        "finger": os.path.join(COMPONENTS_DIR, "settings", "fingerprint.py"),
        "fingerprint": os.path.join(COMPONENTS_DIR, "settings", "fingerprint.py"),
        "domain": os.path.join(COMPONENTS_DIR, "settings", "domain.py"),
        "updates": os.path.join(COMPONENTS_DIR, "security", "updates.py"),
        "update": os.path.join(COMPONENTS_DIR, "updater", "updater.py"),
        "task": os.path.join(COMPONENTS_DIR, "taskman", "taskman.py"),
        "tasks": os.path.join(COMPONENTS_DIR, "taskman", "taskman.py"),
        "recorder": os.path.join(COMPONENTS_DIR, "recorder", "recorder.py"),
        "record": os.path.join(COMPONENTS_DIR, "recorder", "recorder.py"),
        "modesty": os.path.join(COMPONENTS_DIR, "modesty", "modesty.py"),
        "blur": os.path.join(COMPONENTS_DIR, "modesty", "modesty.py"),
        "assistant": os.path.join(COMPONENTS_DIR, "assistant", "assistant.py"),
        "chat": os.path.join(COMPONENTS_DIR, "assistant", "assistant.py"),
        "familysafe": os.path.join(COMPONENTS_DIR, "familysafe", "familysafe.py"),
        "family": os.path.join(COMPONENTS_DIR, "familysafe", "familysafe.py"),
        "islamic": os.path.join(COMPONENTS_DIR, "islamic", "islamic_app.py"),
        "notepad": os.path.join(COMPONENTS_DIR, "notepad", "notepad.py"),
        "notes": os.path.join(COMPONENTS_DIR, "notepad", "notepad.py"),
        "clipboard": os.path.join(COMPONENTS_DIR, "clipboard", "clipboard.py"),
        "emoji": os.path.join(COMPONENTS_DIR, "emoji", "emoji.py"),
        "power": os.path.join(COMPONENTS_DIR, "power", "power_settings.py"),
        "voice": os.path.join(COMPONENTS_DIR, "voicetype", "voicetype.py"),
        "voicetype": os.path.join(COMPONENTS_DIR, "voicetype", "voicetype.py"),
        "optimizer": os.path.join(COMPONENTS_DIR, "optimizer", "optimizer.py"),
        "broadband": os.path.join(COMPONENTS_DIR, "broadband", "broadband.py"),
        "theme": os.path.join(COMPONENTS_DIR, "settings", "theme_switcher.py"),
    }

    if len(sys.argv) < 2:
        if sys.stdin.isatty() and sys.stdout.isatty():
            selected = interactive_select(COMMAND_CATALOG, header="DevOS Unified CLI (Use ↑/↓ arrows to select)")
            if not selected:
                sys.exit(0)
            sub = selected
            args = []
        else:
            print_help()
            sys.exit(0)
    elif sys.argv[1] in ("-h", "--help", "help"):
        print_help()
        sys.exit(0)
    else:
        sub = sys.argv[1]
        args = sys.argv[2:]

    if sub == "setup" and "--first-boot" not in args:
        args.append("--first-boot")

    # Normalize subcommands for hardware manager
    if sub == "net" and not args:
        args = ["net-status"]
    elif sub == "sound" and not args:
        args = ["sound-status"]
    elif sub == "driver" and not args:
        args = ["driver-status"]
    elif sub in ("disk", "storage") and "--gui" in args:
        disk_script = os.path.join(COMPONENTS_DIR, "settings", "disk_doctor_gui.py")
        args = [a for a in args if a != "--gui"]
        dispatch_map["disk"] = disk_script
        dispatch_map["storage"] = disk_script

    if sub in dispatch_map:
        target_script = dispatch_map[sub]
        cmd = [sys.executable, target_script] + args
        try:
            sys.exit(subprocess.run(cmd).returncode)
        except KeyboardInterrupt:
            pass
    else:
        tags_map = {k: v.get("tags", []) for k, v in COMMAND_CATALOG.items()}
        matches = smart_match(sub, list(COMMAND_CATALOG.keys()), tags_map)
        if matches and sys.stdin.isatty() and sys.stdout.isatty():
            matched_items = {m: COMMAND_CATALOG[m] for m in matches if m in COMMAND_CATALOG}
            selected = interactive_select(
                matched_items,
                prequery=sub,
                header=f"DevOS: Unknown command '{sub}'. Did you mean:",
            )
            if selected and selected in dispatch_map:
                target_script = dispatch_map[selected]
                cmd = [sys.executable, target_script] + args
                try:
                    sys.exit(subprocess.run(cmd).returncode)
                except KeyboardInterrupt:
                    pass
                sys.exit(0)
            sys.exit(1)

        print(f"Unknown subsystem '{sub}'.", file=sys.stderr)
        if matches:
            print("Did you mean one of these?", file=sys.stderr)
            for m in matches[:5]:
                print(f"  devos {m:12} - {COMMAND_CATALOG.get(m, {}).get('desc', '')}", file=sys.stderr)
        print("Run 'devos help' for available commands.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
