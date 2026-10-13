#!/usr/bin/env python3
"""
DevOS AI - hands-free voice commands, without opening the chat window.

    listen.py --once      Push-to-talk (the Meta+H / Ctrl+Alt+Space shortcut):
                          listen until the user stops talking, understand,
                          do it, and show the result in a small overlay.
                          Pressing the shortcut again while listening stops
                          the recording early.
    listen.py --daemon    "Hey DevOS" listener (opt-in, sidebar toggle in
                          DevOS AI, saved in ~/.config/devos/assistant.json).
                          A cheap energy VAD watches 30 ms microphone frames;
                          only a finished speech segment of 0.4-6 s is turned
                          into text, and only a segment that starts with the
                          wake phrase does anything. The command can follow in
                          the same breath ("Hey DevOS, open Chrome") or within
                          6 seconds. Skips work while the CPU is busy, on low
                          battery, or while another app uses the microphone.
                          Shows a tray icon (pause / turn off).

Everything runs on this PC; nothing is sent anywhere. Commands go through the
same whitelisted router and tools as the chat window (tools.py); actions that
need a confirmation (shut down, restart, uninstall ...) are only done after a
click on the overlay. No spoken replies: the overlay shows the result.

The pieces below the GUI line import without a display so tests can drive
them with fake audio, fake transcribers and dry_run tools.
"""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import tools  # noqa: E402
import voice  # noqa: E402

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".config", "devos", "assistant.json")
ASSISTANT_PY = os.path.join(HERE, "assistant.py")
CHAT_LAUNCHER = "/usr/local/bin/devos-chat"
FOLLOW_UP_S = 6.0
CPU_BUSY_PCT = 85.0
LOW_BATTERY_PCT = 15
HIDE_AFTER_MS = 3000
HIDE_AFTER_BUTTON_MS = 9000

HANDS_FREE_LABEL = "Hands-free: say “Hey DevOS”"
NOT_UNDERSTOOD_TEXT = "I'm not sure how to do that here. Open DevOS AI to ask about it."
OPEN_IN_APP_LABEL = "Open in DevOS AI"
NOTHING_HEARD_TEXT = "I didn't catch that. Try again, a little closer to the microphone."

# Results that are worth reading in full in the chat window.
READING_ACTIONS = frozenset(("system_info", "list_apps", "count_apps", "help", "about", "cleanup_scan"))


# ---------------------------------------------------------------------------
# Settings and guard rails
# ---------------------------------------------------------------------------


def load_config(path: str = CONFIG_PATH) -> Dict[str, object]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(path: str = CONFIG_PATH, **updates) -> Dict[str, object]:
    data = load_config(path)
    data.update(updates)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass
    return data


def hands_free_enabled(path: str = CONFIG_PATH) -> bool:
    return bool(load_config(path).get("hands_free", False))


def live_session(cmdline_path: str = "/proc/cmdline") -> bool:
    """True on the live USB (try-before-install) session."""
    try:
        with open(cmdline_path, "r", encoding="utf-8", errors="replace") as fh:
            return "boot=casper" in fh.read().split()
    except OSError:
        return False


def transcribe_threads(cpus: Optional[int] = None) -> int:
    cpus = cpus if cpus is not None else (os.cpu_count() or 2)
    return max(1, min(4, cpus // 2))


class CpuMeter:
    """Whole-system CPU use in % between two calls, from /proc/stat."""

    def __init__(self, stat_path: str = "/proc/stat"):
        self.path = stat_path
        self.last = self._read()

    def _read(self) -> Optional[Tuple[int, int]]:
        try:
            with open(self.path, "r") as fh:
                parts = fh.readline().split()
            vals = [int(x) for x in parts[1:]]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            return sum(vals), idle
        except (OSError, ValueError, IndexError):
            return None

    def percent(self) -> float:
        now = self._read()
        if now is None or self.last is None:
            self.last = now
            return 0.0
        total = now[0] - self.last[0]
        idle = now[1] - self.last[1]
        self.last = now
        return 0.0 if total <= 0 else max(0.0, min(100.0, 100.0 * (total - idle) / total))


def battery_low(ctx: tools.ToolContext, threshold: int = LOW_BATTERY_PCT) -> bool:
    for b in tools.read_batteries(ctx):
        cap = b.get("capacity")
        if str(b.get("status", "")).lower() == "discharging" and cap is not None and cap < threshold:
            return True
    return False


def parse_source_outputs(text: str) -> List[Dict[str, str]]:
    """`pactl list source-outputs` -> [{'pid': ..., 'app': ..., 'binary': ...}]."""
    out: List[Dict[str, str]] = []
    cur: Optional[Dict[str, str]] = None
    for line in text.splitlines():
        if re.match(r"^Source Output #\d+", line):
            cur = {"pid": "", "app": "", "binary": ""}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = re.match(r'^\s*application\.(process\.id|name|process\.binary)\s*=\s*"(.*)"', line)
        if m:
            key = {"process.id": "pid", "name": "app", "process.binary": "binary"}[m.group(1)]
            cur[key] = m.group(2)
    return out


def mic_used_by_others(text: str, own_pids: List[int]) -> bool:
    own = {str(p) for p in own_pids}
    for so in parse_source_outputs(text):
        if so["pid"] and so["pid"] in own:
            continue
        if so["binary"] in ("pavucontrol", "plasmashell"):     # level meters, not a call or recording
            continue
        return True
    return False


class Guard:
    """Reasons not to spend CPU on a segment right now ('' = go ahead)."""

    def __init__(self, ctx: Optional[tools.ToolContext] = None, cpu: Optional[CpuMeter] = None,
                 mic_check: Optional[Callable[[], bool]] = None, paused: Callable[[], bool] = lambda: False,
                 clock: Callable[[], float] = time.monotonic):
        self.ctx = ctx or tools.ToolContext()
        self.cpu = cpu or CpuMeter()
        self.mic_check = mic_check
        self.paused = paused
        self.clock = clock
        self._mic_at = -1e9
        self._mic_busy = False

    def reason(self) -> str:
        if self.paused():
            return "paused"
        if self.cpu.percent() > CPU_BUSY_PCT:
            return "cpu"
        if battery_low(self.ctx):
            return "battery"
        if self.mic_check is not None:
            now = self.clock()
            if now - self._mic_at > 3.0:
                self._mic_at = now
                try:
                    self._mic_busy = bool(self.mic_check())
                except Exception:
                    self._mic_busy = False
            if self._mic_busy:
                return "mic"
        return ""


# ---------------------------------------------------------------------------
# Understanding and doing a command (headless)
# ---------------------------------------------------------------------------


def plain_text(md: str, limit: int = 160) -> str:
    """Markdown answer -> one short line for the overlay."""
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", md or "")
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    lines = [re.sub(r"^\s*[-*•]\s+", "", ln).strip() for ln in t.splitlines()]
    lines = [ln for ln in lines if ln]
    t = lines[0] if lines else ""
    if len(lines) > 1 and len(t) < 60:
        t = t.rstrip(":") + ": " + "; ".join(lines[1:3])
    t = " ".join(t.split())
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


@dataclass
class Outcome:
    heard: str
    handled: bool = False
    ok: bool = True
    text: str = ""
    full_text: str = ""
    actions: List[str] = field(default_factory=list)
    plans: List[List[str]] = field(default_factory=list)
    open_in_app: bool = False
    leftover: str = ""
    data: List[Dict[str, object]] = field(default_factory=list)


class CommandRunner:
    """Routes a spoken sentence and runs it with the whitelisted tools.

    confirm(action) -> bool is asked for actions that carry a confirmation
    question; without it those actions are never run.
    """

    def __init__(self, ctx: Optional[tools.ToolContext] = None, dry_run: bool = False,
                 confirm: Optional[Callable[[tools.Action], bool]] = None):
        self.ctx = ctx or tools.ToolContext()
        self.dry_run = dry_run
        self.confirm = confirm

    def run(self, heard: str) -> Outcome:
        text = voice.fix_transcript(heard or "").strip()
        woke, rest = voice.match_wake(text)
        if woke:
            text = rest
        out = Outcome(heard=text)
        if not text:
            out.ok = False
            out.text = NOTHING_HEARD_TEXT
            return out
        r = tools.route(text, self.ctx)
        out.leftover = r.leftover
        if not r.actions:
            out.ok = False
            out.text = NOT_UNDERSTOOD_TEXT
            out.open_in_app = True
            return out
        out.handled = True
        texts, fulls = [], []
        for a in r.actions:
            out.actions.append(a.name)
            if a.confirm:
                if self.confirm is None or not self.confirm(a):
                    texts.append(f"Okay, I won't {a.label[:1].lower() + a.label[1:]}.")
                    continue
            res = tools.execute(a, self.ctx, dry_run=self.dry_run)
            if a.name == "open_app" and not a.args.get("strong") and res.data.get("not_found"):
                out.open_in_app = True
                texts.append(NOT_UNDERSTOOD_TEXT)
                out.ok = False
                continue
            out.plans.extend(res.plan)
            out.data.append(dict(res.data))
            out.ok = out.ok and res.ok
            texts.append(plain_text(res.text))
            fulls.append(res.text)
            if a.name in READING_ACTIONS:
                out.open_in_app = True
        if r.leftover:
            out.open_in_app = True
        out.text = " ".join(t for t in texts if t)
        out.full_text = "\n\n".join(fulls)
        return out


class HandsFree:
    """The "Hey DevOS" state machine. Speech segments in, events out.

    events: ("skipped", reason) ("ignored", text) ("wake", "") ("heard", cmd)
            ("result", Outcome) ("timeout", "")
    """

    def __init__(self, transcribe_wake: Callable[[bytes], str], runner: CommandRunner,
                 transcribe_command: Optional[Callable[[bytes], str]] = None,
                 guard: Optional[Callable[[], str]] = None, clock: Callable[[], float] = time.monotonic,
                 follow_up_s: float = FOLLOW_UP_S):
        self.transcribe_wake = transcribe_wake
        self.transcribe_command = transcribe_command or transcribe_wake
        self.runner = runner
        self.guard = guard
        self.clock = clock
        self.follow_up_s = follow_up_s
        self.armed_until = 0.0

    @property
    def armed(self) -> bool:
        return self.armed_until > 0

    def tick(self) -> List[Tuple[str, object]]:
        if self.armed and self.clock() > self.armed_until:
            self.armed_until = 0.0
            return [("timeout", "")]
        return []

    def on_segment(self, pcm: bytes) -> List[Tuple[str, object]]:
        events = self.tick()
        if self.armed:
            # the command after "Hey DevOS": any language, no guard (the user is waiting)
            self.armed_until = 0.0
            text = voice.fix_transcript(self.transcribe_command(pcm) or "").strip()
            woke, rest = voice.match_wake(text)
            if woke and not rest:
                self.armed_until = self.clock() + self.follow_up_s
                return events + [("wake", "")]
            cmd = rest if woke else text
            if not cmd:
                return events + [("timeout", "")]
            return events + [("heard", cmd), ("result", self.runner.run(cmd))]
        if self.guard is not None:
            why = self.guard()
            if why:
                return events + [("skipped", why)]
        text = voice.fix_transcript(self.transcribe_wake(pcm) or "").strip()
        woke, rest = voice.match_wake(text)
        if not woke:
            return events + [("ignored", text)]
        if rest and len(rest.split()) >= 1 and re.search(r"[A-Za-zঀ-৿]{2,}", rest):
            return events + [("wake", ""), ("heard", rest), ("result", self.runner.run(rest))]
        self.armed_until = self.clock() + self.follow_up_s
        return events + [("wake", "")]


def segments_from_frames(frames, detector: Optional[voice.SegmentDetector] = None):
    """Yield finished speech segments from an iterable of 30 ms frames."""
    det = detector or voice.SegmentDetector()
    for f in frames:
        seg = det.feed(f)
        if seg:
            yield seg


def runtime_dir() -> str:
    d = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/devos-{os.getuid() if hasattr(os, 'getuid') else 0}"
    os.makedirs(d, exist_ok=True)
    return d


def take_lock(name: str):
    """An exclusive lock file; None when another instance holds it."""
    import fcntl
    path = os.path.join(runtime_dir(), name)
    fh = open(path, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def open_in_app_command(text: str) -> List[str]:
    if os.path.isfile(CHAT_LAUNCHER):
        return [CHAT_LAUNCHER, "--ask", text]
    return [tools.PYTHON, ASSISTANT_PY, "--ask", text]


def recorder_frames(argv: List[str], frame_bytes: int, stop: threading.Event, on_proc=None):
    """Raw PCM frames from a recorder process until stop is set."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if on_proc:
        on_proc(proc)
    try:
        while not stop.is_set():
            block = proc.stdout.read(frame_bytes)
            if not block:
                break
            yield block
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# GUI (PyQt5, imported lazily)
# ---------------------------------------------------------------------------


def _qt():
    from PyQt5 import QtCore, QtGui, QtWidgets
    return QtCore, QtGui, QtWidgets


def make_app(argv):
    QtCore, QtGui, QtWidgets = _qt()
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv)
    app.setApplicationName("DevOS AI")
    app.setQuitOnLastWindowClosed(False)
    font = QtGui.QFont()
    fams = QtGui.QFontDatabase().families()
    for fam in ("Inter", "Noto Sans"):
        if fam in fams:
            font = QtGui.QFont(fam)
            break
    font.setPixelSize(14)
    app.setFont(font)
    return app


def run_once(dry_run: bool = False, argv=None) -> int:
    """Push-to-talk: record one command, do it, show the result."""
    lock = take_lock("devos-voice-once.lock")
    stop_flag = os.path.join(runtime_dir(), "devos-voice-stop")
    if lock is None:
        # already listening: a second press means "I'm done talking"
        open(stop_flag, "w").close()
        return 0
    try:
        os.remove(stop_flag)
    except OSError:
        pass
    QtCore, QtGui, QtWidgets = _qt()
    import overlay
    app = make_app(argv or sys.argv)
    ov = overlay.VoiceOverlay()
    bridge = overlay.Bridge()
    ctx = tools.ToolContext()
    runner = CommandRunner(ctx, dry_run=dry_run, confirm=lambda a: bridge.ask_confirm(a.confirm, a.label))
    bridge.level.connect(ov.set_level)
    bridge.event.connect(lambda kind, payload: ov.handle_event(kind, payload))
    ov.open_in_app.connect(lambda text: tools.popen_detached(open_in_app_command(text)))
    ov.finished.connect(app.quit)
    bridge.confirm_request.connect(ov.ask_confirm)
    ov.confirm_answer.connect(bridge.answer_confirm)
    if not voice.voice_ready():
        ov.handle_event("result", Outcome(heard="", ok=False, text=voice.VOICE_MISSING))
        return app.exec_()
    rec = voice.Recorder(on_level=bridge.level.emit)
    poll = QtCore.QTimer()
    poll.setInterval(100)

    def check_stop():
        if os.path.exists(stop_flag):
            try:
                os.remove(stop_flag)
            except OSError:
                pass
            rec.stop()
    poll.timeout.connect(check_stop)
    poll.start()

    def job():
        try:
            pcm, problem = rec.record()
            if problem or not pcm:
                bridge.event.emit("result", Outcome(heard="", ok=False, text=problem or NOTHING_HEARD_TEXT))
                return
            bridge.event.emit("thinking", "")
            text = voice.fix_transcript(voice.Transcriber.transcribe(pcm))
            woke, rest = voice.match_wake(text)
            if woke:
                text = rest
            if not text:
                bridge.event.emit("result", Outcome(heard="", ok=False, text=NOTHING_HEARD_TEXT))
                return
            bridge.event.emit("heard", text)
            bridge.event.emit("result", runner.run(text))
        except Exception as exc:       # never leave a frozen overlay on screen
            bridge.event.emit("result", Outcome(heard="", ok=False, text=f"Voice command stopped: {exc}"))
    ov.handle_event("listening", "")
    threading.Thread(target=job, daemon=True).start()
    rc = app.exec_()
    lock.close()
    return rc


def run_daemon(dry_run: bool = False, argv=None, config_path: str = CONFIG_PATH) -> int:
    """'Hey DevOS' listener with a tray icon. Exits at once unless turned on."""
    if live_session() or not hands_free_enabled(config_path):
        return 0
    lock = take_lock("devos-voice-daemon.lock")
    if lock is None:
        return 0
    if not voice.voice_ready() or not voice.record_command():
        return 0
    QtCore, QtGui, QtWidgets = _qt()
    import overlay
    app = make_app(argv or sys.argv)
    ov = overlay.VoiceOverlay()
    bridge = overlay.Bridge()
    ctx = tools.ToolContext()
    state = {"paused": bool(load_config(config_path).get("paused", False)), "recorder_pid": 0}
    voice.Transcriber.n_threads = transcribe_threads()

    def mic_check():
        if not shutil.which("pactl"):
            return False
        rc, out = tools.run_capture(["pactl", "list", "source-outputs"], timeout=4)
        return rc == 0 and mic_used_by_others(out, [os.getpid(), state["recorder_pid"]])
    guard = Guard(ctx, mic_check=mic_check, paused=lambda: state["paused"])
    runner = CommandRunner(ctx, dry_run=dry_run, confirm=lambda a: bridge.ask_confirm(a.confirm, a.label))
    hf = HandsFree(lambda pcm: voice.Transcriber.transcribe_as(pcm, "en"), runner,
                   transcribe_command=voice.Transcriber.transcribe, guard=guard.reason)
    bridge.level.connect(ov.set_level)
    bridge.event.connect(lambda kind, payload: ov.handle_event(kind, payload))
    ov.open_in_app.connect(lambda text: tools.popen_detached(open_in_app_command(text)))
    bridge.confirm_request.connect(ov.ask_confirm)
    ov.confirm_answer.connect(bridge.answer_confirm)
    tray = overlay.HandsFreeTray(paused=state["paused"])

    def set_paused(on):
        state["paused"] = on
        save_config(config_path, paused=on)
        tray.set_paused(on)

    def turn_off():
        save_config(config_path, hands_free=False)
        stop.set()
        app.quit()
    tray.pause_toggled.connect(set_paused)
    tray.turn_off.connect(turn_off)
    tray.open_app.connect(lambda: tools.popen_detached(
        [CHAT_LAUNCHER] if os.path.isfile(CHAT_LAUNCHER) else [tools.PYTHON, ASSISTANT_PY]))
    tray.show()

    # the sidebar toggle edits the config file: follow it
    def follow_config():
        cfg = load_config(config_path)
        if not cfg.get("hands_free", False):
            stop.set()
            app.quit()
            return
        p = bool(cfg.get("paused", False))
        if p != state["paused"]:
            state["paused"] = p
            tray.set_paused(p)
    watch = QtCore.QTimer()
    watch.timeout.connect(follow_config)
    watch.start(2000)

    stop = threading.Event()
    import queue
    segments: "queue.Queue[bytes]" = queue.Queue(maxsize=2)

    def reader():
        argv_rec = voice.record_command()
        det = voice.SegmentDetector()
        while not stop.is_set():
            try:
                frames = recorder_frames(argv_rec, voice.SEG_FRAME_BYTES, stop,
                                         on_proc=lambda p: state.__setitem__("recorder_pid", p.pid))
                for f in frames:
                    if hf.armed:
                        bridge.level.emit(voice.level_0_1(voice.rms(f)))
                    seg = det.feed(f)
                    if seg:
                        try:
                            segments.put_nowait(seg)
                        except queue.Full:
                            pass            # still busy with the previous one: drop
            except OSError:
                pass
            if not stop.is_set():
                time.sleep(2.0)             # the recorder died (device change): restart it

    def worker():
        while not stop.is_set():
            try:
                seg = segments.get(timeout=0.5)
            except queue.Empty:
                for kind, payload in hf.tick():
                    bridge.event.emit(kind, payload)
                continue
            try:
                for kind, payload in hf.on_segment(seg):
                    if kind in ("wake", "heard", "result", "timeout"):
                        bridge.event.emit("listening" if kind == "wake" else kind, payload)
            except Exception as exc:
                bridge.event.emit("result", Outcome(heard="", ok=False, text=f"Voice command stopped: {exc}"))
    threading.Thread(target=reader, daemon=True).start()
    threading.Thread(target=worker, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *a: (stop.set(), app.quit()))
    rc = app.exec_()
    stop.set()
    lock.close()
    return rc


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    p = argparse.ArgumentParser(description="DevOS AI voice commands")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true", help="listen for one command (push-to-talk)")
    g.add_argument("--daemon", action="store_true", help="listen for 'Hey DevOS' (if turned on)")
    p.add_argument("--dry-run", action="store_true", help="show what would be done, do nothing")
    ns = p.parse_args(argv[1:])
    if ns.once:
        return run_once(ns.dry_run, argv)
    return run_daemon(ns.dry_run, argv)


if __name__ == "__main__":
    sys.exit(main())
