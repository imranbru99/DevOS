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


def _stop_speech():
    """Stop any in-flight TTS so a new line is never mixed with an old one."""
    if shutil.which("pkill"):
        for name in ("espeak-ng", "espeak", "spd-say", "ffplay"):
            subprocess.run(
                ["pkill", "-x", name],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        # Only our TTS ffplay jobs (pattern is specific).
        subprocess.run(
            ["pkill", "-f", "ffplay.*devos-islamic-tts"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


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


def _play_audio_file(path):
    if not path or not os.path.isfile(path):
        return False
    if shutil.which("ffplay"):
        try:
            subprocess.run(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=180,
            )
            return True
        except (OSError, subprocess.TimeoutExpired):
            return False
    if path.endswith(".wav") or path.endswith(".oga") or path.endswith(".ogg"):
        play_sound(path, wait=True)
        return True
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


def _speak_edge_tts(text, language, gender=None):
    """Natural neural voice via edge-tts in the DevOS TTS venv (online)."""
    ensure_clear_voice()
    py = os.path.join(_TTS_VENV, "bin", "python")
    if not os.path.isfile(py) or not shutil.which("ffplay"):
        return False
    g = gender or _tts_gender()
    voice = _edge_voice(language, g)
    os.makedirs(_TTS_CACHE, exist_ok=True)
    try:
        for i, chunk in enumerate(_tts_chunks(text, limit=220)):
            out = os.path.join(_TTS_CACHE, "devos-islamic-tts-%d.mp3" % i)
            script = (
                "import asyncio, edge_tts, sys\n"
                "asyncio.run(edge_tts.Communicate(sys.argv[1], sys.argv[2]).save(sys.argv[3]))\n"
            )
            proc = subprocess.run(
                [py, "-c", script, chunk, voice, out],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=60,
            )
            if proc.returncode != 0 or not os.path.isfile(out):
                return False
            if not _play_audio_file(out):
                return False
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _speak_espeak(text, language, gender=None):
    """Offline fallback — gender-aware voice (plain en/bn sound male)."""
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
                try:
                    proc = subprocess.run(
                        cmd,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=120,
                    )
                    if proc.returncode == 0:
                        return True
                except (OSError, subprocess.TimeoutExpired):
                    continue
            return False
        return False
    # Bangla espeak is hard to follow at default speed; slow it and add gaps.
    # Pitch nudge reinforces female when variant voices are thin.
    speed = "105" if language == "bn" else "140"
    gap = "14" if language == "bn" else "6"
    pitch = "60" if g == "female" else "40"
    for chunk in _tts_chunks(text, limit=160):
        subprocess.run(
            [
                "espeak-ng", "-v", voice, "-s", speed, "-g", gap,
                "-p", pitch, "-a", "180", chunk,
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=120,
        )
    return True


def speak_text(text, language="en"):
    """Speak one line clearly and wait until it finishes (never overlaps).

    Uses the same female/male preference as DevOS AI (voice_prefs). Neural TTS
    when online; gender-aware espeak-ng offline (never plain male ``en``/``bn``).
    """
    text = " ".join((text or "").split())
    if not text:
        return
    if len(text) > 500:
        text = text[:500].rsplit(" ", 1)[0]
    language = "bn" if str(language).lower().startswith("bn") else "en"
    gender = _tts_gender()
    _stop_speech()
    try:
        if _speak_edge_tts(text, language, gender=gender):
            return
        _speak_espeak(text, language, gender=gender)
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
