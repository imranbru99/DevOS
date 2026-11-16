#!/usr/bin/env python3
"""
DevOS Islamic notifier - the small background helper behind devos-islamic.service.

It runs only after the user turns DevOS Islamic on (systemctl --user enable
--now devos-islamic.service) and does three things:
  * a desktop notification at each of the five prayer times (with a system
    chime, or the user's own adhan file if they picked one),
  * an optional reminder N minutes before each one,
  * an optional daily "Ayah of the day" / "Hadith of the day" notification,
    including a same-day catch-up a short while after login when the PC was
    off at the scheduled clock time,
  * optional spoken prayer name / daily text (clear neural Bangla/English when
    online; slowed espeak-ng offline).

Low CPU by design: there is no polling loop doing work every second. We work
out the next event, sleep until it (never more than 60 s at a time, so a
suspend/resume, a midnight rollover, a time-zone change or an edited settings
file is picked up within a minute), then simply recompute from the wall
clock. Prayer events missed by more than a few minutes (the laptop was
asleep) are skipped; daily ayah/hadith still fire once later the same day.
"""

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import prayer_times as pt  # noqa: E402

APP_NAME = "DevOS Islamic"
ICON = "devos-islamic"
MAX_SLEEP_S = 60
LATE_GRACE = _dt.timedelta(minutes=5)
# Wait for PipeWire / session audio after login before catch-up or speech.
SESSION_AUDIO_READY_S = 90
DEFAULT_SOUND_CANDIDATES = (
    "/usr/share/sounds/freedesktop/stereo/message-new-instant.oga",
    "/usr/share/sounds/ocean/stereo/message-new-instant.oga",
    "/usr/share/sounds/freedesktop/stereo/complete.oga",
    "/usr/share/sounds/freedesktop/stereo/bell.oga",
)

DEFAULTS = {
    "city": "Dhaka",
    "manual": None,              # {"name","lat","lon","tz","offset"} overrides city
    "method": pt.DEFAULT_METHOD,
    "asr": pt.DEFAULT_ASR,
    "hijri_adjust": 0,           # -2..+2 days, to match the local moon sighting
    "notify_at_prayer": True,
    "remind_before_min": 10,     # 0 = no reminder
    "daily_text": True,
    "daily_time": "07:00",
    "language": "bn",            # "bn" or "en": translation + TTS language
    "sound": "",                 # optional adhan/reminder file; empty = system chime
    "play_sound": True,          # chime / adhan for prayer and daily alerts
    "speak": True,               # speak prayer name and daily text
}


# ---------------------------------------------------------------------------
# Settings (~/.config/devos/islamic.json)
# ---------------------------------------------------------------------------

def settings_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "devos", "islamic.json")


def load_settings(path=None):
    path = path or settings_path()
    data = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            data.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    if data["method"] not in pt.METHODS:
        data["method"] = pt.DEFAULT_METHOD
    if data["asr"] not in pt.ASR_FACTORS:
        data["asr"] = pt.DEFAULT_ASR
    try:
        data["remind_before_min"] = max(0, min(120, int(data["remind_before_min"])))
        data["hijri_adjust"] = max(-2, min(2, int(data["hijri_adjust"])))
    except (TypeError, ValueError):
        data["remind_before_min"], data["hijri_adjust"] = 10, 0
    data["play_sound"] = bool(data.get("play_sound", True))
    data["speak"] = bool(data.get("speak", True))
    data["language"] = "bn" if str(data.get("language", "bn")).lower().startswith("bn") else "en"
    return data


def save_settings(data, path=None):
    path = path or settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({k: data.get(k, v) for k, v in DEFAULTS.items()}, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Schedule (pure)
# ---------------------------------------------------------------------------

class Event:
    __slots__ = ("when", "kind", "prayer", "title", "body")

    def __init__(self, when, kind, prayer="", title="", body=""):
        self.when, self.kind, self.prayer, self.title, self.body = when, kind, prayer, title, body

    @property
    def key(self):
        return "%s:%s:%s" % (self.kind, self.prayer, self.when.isoformat())

    def __repr__(self):
        return "Event(%s %s %s)" % (self.when.isoformat(), self.kind, self.prayer)


def _parse_hhmm(text, default=(7, 0)):
    try:
        h, m = (int(x) for x in str(text).split(":", 1))
        if 0 <= h < 24 and 0 <= m < 60:
            return h, m
    except ValueError:
        pass
    return default


def build_events(now, settings, times_fn=None):
    """
    All notification events for today and tomorrow (in the location's time
    zone) that are still ahead of `now` minus the late grace, sorted.
    times_fn(date, settings) -> {prayer: aware datetime}; defaults to the real calculation.
    """
    times_fn = times_fn or pt.times_for_settings
    loc = pt.resolve_location(settings)
    tz = loc["tz"]
    local_now = now.astimezone(tz)
    events = []
    for offset in (0, 1):
        day = local_now.date() + _dt.timedelta(days=offset)
        times = times_fn(day, settings)
        for name in pt.SALAH:
            label = pt.PRAYER_LABELS[name]
            at = times[name]
            clock = at.strftime("%H:%M")
            if settings.get("notify_at_prayer", True):
                events.append(Event(at, "prayer", name, "%s time" % label,
                                    "It is time for %s (%s) in %s." % (label, clock, loc["name"])))
            before = int(settings.get("remind_before_min") or 0)
            if before > 0:
                events.append(Event(at - _dt.timedelta(minutes=before), "reminder", name,
                                    "%s in %d minutes" % (label, before),
                                    "%s is at %s in %s." % (label, clock, loc["name"])))
        if settings.get("daily_text", True):
            h, m = _parse_hhmm(settings.get("daily_time"))
            at = _dt.datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
            # Normalise through UTC so a DST gap/overlap still gives a real instant.
            at = at.astimezone(_dt.timezone.utc).astimezone(tz)
            # Hadith a few minutes later so two long readings never start together.
            hadith_at = at + _dt.timedelta(minutes=3)
            events.append(Event(at, "ayah", "", "Ayah of the day"))
            events.append(Event(hadith_at, "hadith", "", "Hadith of the day"))
    # Keep prayer/reminder within LATE_GRACE; keep today's daily texts all day
    # so a late login still gets ayah/hadith once.
    keep = []
    for e in events:
        if e.when > now:
            keep.append(e)
            continue
        if e.kind in ("ayah", "hadith"):
            if e.when.astimezone(tz).date() == local_now.date():
                keep.append(e)
        elif now - e.when <= LATE_GRACE:
            keep.append(e)
    return sorted(keep, key=lambda e: (e.when, e.kind))


def due_events(events, now, fired, session_start=None, audio_ready_s=SESSION_AUDIO_READY_S):
    """Events whose time has come and were not sent yet.

    Daily ayah/hadith wait until session audio is ready so a fresh login on a
    new date chimes/speaks after PipeWire is up, not in the first silent seconds.
    """
    ready = True
    if session_start is not None:
        ready = (time.monotonic() - session_start) >= float(audio_ready_s)
    out = []
    for e in events:
        if e.key in fired or e.when > now:
            continue
        if e.kind in ("ayah", "hadith"):
            if not ready:
                continue
            out.append(e)
            continue
        if now - e.when <= LATE_GRACE:
            out.append(e)
    return out


def seconds_until_next(events, now, fired, max_sleep=MAX_SLEEP_S, session_start=None,
                       audio_ready_s=SESSION_AUDIO_READY_S):
    """How long to sleep: until the next unsent event, capped at max_sleep (and >= 1)."""
    upcoming = [e for e in events if e.key not in fired and e.when > now]
    wait = float(max_sleep)
    if upcoming:
        wait = min(wait, max(1.0, (upcoming[0].when - now).total_seconds()))
    # Pending same-day daily catch-up waiting on session audio.
    if session_start is not None:
        remaining = float(audio_ready_s) - (time.monotonic() - session_start)
        if remaining > 0:
            pending_daily = [e for e in events if e.key not in fired
                             and e.kind in ("ayah", "hadith") and e.when <= now]
            if pending_daily:
                wait = min(wait, max(1.0, remaining))
    return max(1.0, min(float(max_sleep), wait))


def prune_fired(fired, now):
    """Forget keys older than two days so the set cannot grow forever."""
    limit = now - _dt.timedelta(days=2)
    keep = set()
    for key in fired:
        try:
            when = _dt.datetime.fromisoformat(key.split(":", 2)[2])
        except (IndexError, ValueError):
            continue
        if when > limit:
            keep.add(key)
    return keep


# ---------------------------------------------------------------------------
# Side effects
# ---------------------------------------------------------------------------

def daily_text(event, settings, date):
    """Fill in the body of an ayah/hadith event from the verified local texts."""
    import content
    lang = settings.get("language", "en")
    item = content.ayah_of_the_day(date) if event.kind == "ayah" else content.hadith_of_the_day(date)
    if not item:
        return None, None  # texts not downloaded; stay quiet rather than show nothing useful
    body = content.short_text(item, "bn" if lang == "bn" else "en")
    speak_src = " ".join((item.get(lang) or item.get("en") or "").split())
    return body, speak_src


def default_sound_path():
    for path in DEFAULT_SOUND_CANDIDATES:
        if os.path.isfile(path):
            return path
    return ""


def resolve_sound(settings, kind):
    """Custom adhan for prayer; otherwise the system notification chime."""
    if not settings.get("play_sound", True):
        return ""
    custom = (settings.get("sound") or "").strip()
    if kind == "prayer" and custom and os.path.isfile(custom):
        return custom
    if custom and os.path.isfile(custom) and kind in ("reminder", "ayah", "hadith"):
        # Reminders / daily use the short system chime, not a full adhan.
        return default_sound_path()
    return default_sound_path()


def play_sound(path, wait=True):
    """Play a short chime; wait so speech does not overlap the chime."""
    if not path or not os.path.isfile(path):
        return
    cmd = None
    if shutil.which("paplay"):
        cmd = ["paplay", path]
    elif shutil.which("pw-play"):
        cmd = ["pw-play", path]
    if not cmd:
        return
    try:
        if wait:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8)
        else:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass


_TTS_VENV = os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share"),
    "devos", "tts-venv",
)
_TTS_CACHE = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache"),
    "devos", "islamic-tts",
)
# Fallback neural voices when voice_prefs is unavailable (female default).
_EDGE_VOICES = {
    ("bn", "female"): "bn-BD-NabanitaNeural",
    ("bn", "male"): "bn-BD-PradeepNeural",
    ("en", "female"): "en-US-JennyNeural",
    ("en", "male"): "en-US-GuyNeural",
}


def _tts_gender() -> str:
    """Honor DevOS AI voice gender (Settings) for prayer / ayah speech too."""
    try:
        assistant = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assistant",
        )
        if assistant not in sys.path:
            sys.path.insert(0, assistant)
        import voice_prefs  # noqa: WPS433
        g = str(voice_prefs.tts_gender() or "female").lower()
        if g in ("female", "male"):
            return g
    except Exception:
        pass
    # Installer / system default
    try:
        with open("/var/lib/DevOS/voice-prefs.json", encoding="utf-8") as fh:
            raw = json.load(fh)
        g = str((raw or {}).get("tts_gender") or "female").lower()
        if g in ("female", "male"):
            return g
    except (OSError, ValueError, TypeError):
        pass
    return "female"


def _edge_voice(language: str, gender: str = None) -> str:
    lang = "bn" if language == "bn" else "en"
    g = (gender or _tts_gender()).lower()
    if g not in ("female", "male"):
        g = "female"
    try:
        assistant = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "assistant",
        )
        if assistant not in sys.path:
            sys.path.insert(0, assistant)
        import voice_prefs  # noqa: WPS433
        return voice_prefs.edge_voice_id(lang, gender=g)
    except Exception:
        return _EDGE_VOICES.get((lang, g), _EDGE_VOICES[("en", "female")])


def _espeak_voice(language: str, gender: str = None) -> str:
    """Plain ``en``/``bn`` sound male — always attach a female/male variant."""
    g = (gender or _tts_gender()).lower()
    if language == "bn":
        return "bn+f2" if g == "female" else "bn"
    return "en+f3" if g == "female" else "en+m3"


# One generation per utterance. Stop (and any newer Speak) bumps it so the
# in-flight reader notices and exits. Without this, killing ffplay looked like
# a playback failure and the offline voice restarted the whole hadith.
_SPEECH_LOCK = threading.Lock()
_SPEECH_GEN = 0
_SPEECH_PROCS = []


def _speech_generation():
    with _SPEECH_LOCK:
        return _SPEECH_GEN


def _cancelled(gen):
    return gen != _speech_generation()


def _track_proc(proc):
    with _SPEECH_LOCK:
        _SPEECH_PROCS.append(proc)
    return proc


def _untrack_proc(proc):
    with _SPEECH_LOCK:
        try:
            _SPEECH_PROCS.remove(proc)
        except ValueError:
            pass


def _kill_speech_procs(procs):
    for proc in procs:
        try:
            if proc.poll() is None:
                proc.kill()
        except OSError:
            pass
    for proc in procs:
        try:
            proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _pkill_players():
    """Stop audio we may have lost track of (Stop must silence the speakers)."""
    if not shutil.which("pkill"):
        return
    for name in ("espeak-ng", "espeak", "spd-say", "ffplay"):
        subprocess.run(
            ["pkill", "-x", name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    subprocess.run(
        ["pkill", "-f", "ffplay.*devos-islamic-tts"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _begin_speech():
    """Start a new utterance and invalidate whatever was speaking."""
    global _SPEECH_GEN
    with _SPEECH_LOCK:
        _SPEECH_GEN += 1
        gen = _SPEECH_GEN
        procs = list(_SPEECH_PROCS)
    _kill_speech_procs(procs)
    _pkill_players()
    return gen


def _stop_speech():
    """Stop any in-flight TTS so a new line is never mixed with an old one."""
    _begin_speech()


def _run_tracked(cmd, gen, timeout):
    """Run cmd as a child we can kill from Stop. None if cancelled or it failed."""
    if _cancelled(gen):
        return None
    try:
        proc = _track_proc(subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))
    except OSError:
        return None
    if _cancelled(gen):
        try:
            proc.kill()
        except OSError:
            pass
        _untrack_proc(proc)
        return None
    try:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
            return None
        if _cancelled(gen):
            return None
        return proc.returncode
    finally:
        _untrack_proc(proc)


def _tts_chunks(text, limit=180):
    """Split long text so neural TTS stays clear and under URL/size limits."""
    text = " ".join((text or "").split())
    if not text:
        return []
    parts = re.split(r"(?<=[।.!?؟])\s+", text)
    chunks, buf = [], ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) > limit:
            if buf:
                chunks.append(buf)
                buf = ""
            while len(part) > limit:
                cut = part[:limit].rsplit(" ", 1)[0] or part[:limit]
                chunks.append(cut)
                part = part[len(cut):].strip()
            if part:
                buf = part
            continue
        if buf and len(buf) + 1 + len(part) > limit:
            chunks.append(buf)
            buf = part
        else:
            buf = (buf + " " + part).strip() if buf else part
    if buf:
        chunks.append(buf)
    return chunks


def _drop_clip(path):
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _play_audio_file(path, gen=None):
    """Play one clip to the end. False when Stop cancelled it or playback failed."""
    if gen is None:
        gen = _speech_generation()
    if _cancelled(gen):
        return False
    if not path or not os.path.isfile(path):
        return False
    try:
        if os.path.getsize(path) < 32:
            return False
    except OSError:
        return False
    if shutil.which("ffplay"):
        rc = _run_tracked(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
            gen, timeout=180,
        )
        return rc == 0 and not _cancelled(gen)
    if path.endswith(".wav") or path.endswith(".oga") or path.endswith(".ogg"):
        play_sound(path, wait=True)
        return not _cancelled(gen)
    return False


def ensure_clear_voice():
    """Create ~/.local/share/devos/tts-venv with edge-tts when missing (once)."""
    py = os.path.join(_TTS_VENV, "bin", "python")
    if os.path.isfile(py):
        return True
    if not shutil.which("python3"):
        return False
    try:
        subprocess.run(
            ["python3", "-m", "venv", _TTS_VENV],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120, check=True,
        )
        pip = os.path.join(_TTS_VENV, "bin", "pip")
        subprocess.run(
            [pip, "install", "-q", "edge-tts>=6.1.0"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300, check=True,
        )
        return os.path.isfile(py)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


_EDGE_CHUNK_CHARS = 220
# Daily notifications stay bounded, but always on a sentence so they do not
# stop mid-phrase. The Speak button passes full=True and reads the whole card.
_NOTIFY_SPEECH_CHARS = 4000
_EDGE_SCRIPT = (
    "import asyncio, edge_tts, sys\n"
    "asyncio.run(edge_tts.Communicate(sys.argv[1], sys.argv[2]).save(sys.argv[3]))\n"
)


def _sleep_cancel(seconds, gen):
    end = time.time() + seconds
    while time.time() < end:
        if _cancelled(gen):
            return False
        time.sleep(0.05)
    return not _cancelled(gen)


def _cap_speech(text, limit):
    """Shorten unattended speech on a sentence boundary. None means no cap."""
    text = " ".join((text or "").split())
    if not text or limit is None or len(text) <= limit:
        return text
    window = text[:limit]
    best = -1
    for sep in ("।", ".", "!", "?", "؟"):
        idx = window.rfind(sep)
        if idx > best:
            best = idx
    if best >= int(limit * 0.5):
        return window[:best + 1].strip()
    cut = window.rsplit(" ", 1)[0]
    return (cut or window).strip()


def _synth_edge_chunk(py, chunk, voice, out, gen):
    """Write one clip in the locked neural voice. Never reuse an older file."""
    if _cancelled(gen):
        return False
    try:
        if os.path.isfile(out):
            os.remove(out)
    except OSError:
        return False
    rc = _run_tracked(
        [py, "-c", _EDGE_SCRIPT, chunk, voice, out],
        gen, timeout=45,
    )
    if rc != 0 or _cancelled(gen):
        return False
    try:
        return os.path.isfile(out) and os.path.getsize(out) > 32
    except OSError:
        return False


def _speak_edge_chunks(py, text, voice, gen):
    """Speak every chunk in ``voice``.

    Returns:
      ok        — the whole passage was played
      fail      — nothing was played (caller may use the offline voice)
      partial   — the neural voice already started; do not switch voices
      cancelled — Stop, or a newer Speak, interrupted it
      empty     — no speakable text
    """
    chunks = _tts_chunks(text, limit=_EDGE_CHUNK_CHARS)
    if not chunks:
        return "empty"
    os.makedirs(_TTS_CACHE, exist_ok=True)

    def synth(index, chunk):
        # Generation in the name so a Stop/new Speak cannot replay an older clip.
        out = os.path.join(_TTS_CACHE, "devos-islamic-tts-g%s-%d.mp3" % (gen, index))
        for attempt in range(3):
            if _cancelled(gen):
                return None
            if _synth_edge_chunk(py, chunk, voice, out, gen):
                return out
            if _cancelled(gen) or attempt == 2 or not _sleep_cancel(0.4, gen):
                break
        return None

    pending = synth(0, chunks[0])
    if _cancelled(gen):
        return "cancelled"
    if not pending:
        return "fail"
    for i, chunk in enumerate(chunks):
        if _cancelled(gen):
            return "cancelled"
        current = pending
        pending = None
        if not current:
            current = synth(i, chunk)
            if _cancelled(gen):
                return "cancelled"
            if not current:
                # Female (or male) voice already spoke the earlier part.
                # Restarting here is the "other voice from the beginning" bug.
                return "partial"
        holder = {}
        prefetch = None
        if i + 1 < len(chunks):
            nxt_i, nxt = i + 1, chunks[i + 1]

            def _prefetch(index=nxt_i, piece=nxt):
                holder["path"] = synth(index, piece)

            prefetch = threading.Thread(
                target=_prefetch, daemon=True, name="devos-islamic-tts-next",
            )
            prefetch.start()
        played = _play_audio_file(current, gen)
        if _cancelled(gen):
            return "cancelled"
        if not played:
            played = _play_audio_file(current, gen)
            if _cancelled(gen):
                return "cancelled"
            if not played:
                return "partial" if i else "fail"
        _drop_clip(current)
        if prefetch is not None:
            while prefetch.is_alive():
                if _cancelled(gen):
                    return "cancelled"
                prefetch.join(0.05)
            pending = holder.get("path")
    return "ok"


def _speak_edge_tts(text, language, gender=None, gen=None):
    """Natural neural voice via edge-tts in the DevOS TTS venv (online).

    The voice id is chosen once and reused for every chunk of a long hadith,
    so a later sentence cannot come back as a different speaker.
    """
    if gen is None:
        gen = _speech_generation()
    if _cancelled(gen):
        return "cancelled"
    ensure_clear_voice()
    py = os.path.join(_TTS_VENV, "bin", "python")
    if not os.path.isfile(py) or not shutil.which("ffplay"):
        return "fail"
    g = gender or _tts_gender()
    voice = _edge_voice(language, g)
    try:
        return _speak_edge_chunks(py, text, voice, gen)
    except OSError:
        return "fail"


def _speak_espeak(text, language, gender=None, gen=None):
    """Offline fallback — one gender-aware voice for the whole passage."""
    if gen is None:
        gen = _speech_generation()
    if _cancelled(gen):
        return False
    g = gender or _tts_gender()
    voice = _espeak_voice(language, g)
    lang_flag = "bn" if language == "bn" else "en"
    if not shutil.which("espeak-ng"):
        if shutil.which("spd-say"):
            # Try gendered speech-dispatcher voice, then plain language.
            for cmd in (
                ["spd-say", "-l", lang_flag, "-t", g, "-w", text],
                ["spd-say", "-l", lang_flag, "-w", text],
            ):
                if _cancelled(gen):
                    return False
                rc = _run_tracked(cmd, gen, timeout=120)
                if _cancelled(gen):
                    return False
                if rc == 0:
                    return True
            return False
        return False
    # Bangla espeak is hard to follow at default speed; slow it and add gaps.
    # Pitch nudge reinforces female when variant voices are thin.
    speed = "105" if language == "bn" else "140"
    gap = "14" if language == "bn" else "6"
    pitch = "60" if g == "female" else "40"
    for chunk in _tts_chunks(text, limit=160):
        if _cancelled(gen):
            return False
        _run_tracked(
            [
                "espeak-ng", "-v", voice, "-s", speed, "-g", gap,
                "-p", pitch, "-a", "180", chunk,
            ],
            gen, timeout=120,
        )
        if _cancelled(gen):
            return False
    return True


def speak_text(text, language="en", full=False):
    """Speak one passage in a single voice and wait until it finishes.

    ``full=True`` (the ayah/hadith Speak button) reads the whole card. Daily
    notifications are shortened on a sentence boundary.

    Uses the DevOS AI female/male voice. Neural TTS when online; espeak only
    when that voice never started. A failure in the middle of a long hadith
    must not start espeak again from the first word — that was a second voice
    taking over mid-essay. Stop cancels the rest instead of skipping ahead.
    """
    text = " ".join((text or "").split())
    if not text:
        return
    text = _cap_speech(text, None if full else _NOTIFY_SPEECH_CHARS)
    if not text:
        return
    language = "bn" if str(language).lower().startswith("bn") else "en"
    gender = _tts_gender()
    gen = _begin_speech()
    try:
        status = _speak_edge_tts(text, language, gender=gender, gen=gen)
    except (OSError, subprocess.TimeoutExpired):
        status = "fail"
    if status in ("ok", "cancelled", "partial", "empty") or _cancelled(gen):
        return
    try:
        _speak_espeak(text, language, gender=gender, gen=gen)
    except (OSError, subprocess.TimeoutExpired):
        pass


def prayer_speech(prayer, settings):
    label = pt.PRAYER_LABELS.get(prayer, prayer)
    if settings.get("language") == "bn":
        bn = {
            "fajr": "ফজর", "dhuhr": "যোহর", "asr": "আসর",
            "maghrib": "মাগরিব", "isha": "এশা",
        }
        name = bn.get(prayer, label)
        return "এখন %s এর ওয়াক্ত" % name
    return "It is time for %s" % label


def notify(title, body, sound="", speak="", language="en"):
    if shutil.which("notify-send"):
        cmd = [
            "notify-send", "-a", APP_NAME, "-i", ICON, "-u", "normal",
            "--hint=string:desktop-entry:devos-islamic",
            "--hint=string:sound-name:message-new-instant",
            title, body,
        ]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print("%s: %s" % (title, body), flush=True)
    # Chime first (if any), then speak — never start two voices at once.
    if sound and not speak:
        play_sound(sound, wait=False)
    elif sound:
        play_sound(sound, wait=True)
    if speak:
        speak_text(speak, language)


def run():
    path = settings_path()
    settings, stamp = load_settings(path), None
    fired = set()
    session_start = time.monotonic()
    while True:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        if mtime != stamp:  # the window saved new settings
            settings, stamp = load_settings(path), mtime
        now = _dt.datetime.now(_dt.timezone.utc)
        events = build_events(now, settings)
        due = due_events(events, now, fired, session_start=session_start)
        # One spoken alert at a time. Prefer a single due event per wake when
        # any of them needs speech, so ayah/hadith catch-up never double-talks.
        if settings.get("speak", True) and len(due) > 1:
            due = due[:1]
        for event in due:
            fired.add(event.key)
            body = event.body
            speak = ""
            lang = settings.get("language", "bn")
            if event.kind in ("ayah", "hadith"):
                body, speak_src = daily_text(event, settings, event.when.date())
                if not body:
                    continue
                if settings.get("speak", True):
                    kind_label = "Ayah of the day. " if event.kind == "ayah" else "Hadith of the day. "
                    if lang == "bn":
                        kind_label = "আজকের আয়াত। " if event.kind == "ayah" else "আজকের হাদিস। "
                    speak = kind_label + (speak_src or "")
            elif event.kind == "prayer" and settings.get("speak", True):
                speak = prayer_speech(event.prayer, settings)
            elif event.kind == "reminder" and settings.get("speak", True):
                label = pt.PRAYER_LABELS.get(event.prayer, event.prayer)
                before = int(settings.get("remind_before_min") or 0)
                if lang == "bn":
                    speak = prayer_speech(event.prayer, settings).replace("এখন ", "") + \
                        " %d মিনিট পরে" % before
                else:
                    speak = "%s in %d minutes" % (label, before)
            sound = resolve_sound(settings, event.kind)
            notify(event.title, body, sound=sound, speak=speak, language=lang)
        fired = prune_fired(fired, now)
        time.sleep(seconds_until_next(
            events, _dt.datetime.now(_dt.timezone.utc), fired, session_start=session_start))


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
