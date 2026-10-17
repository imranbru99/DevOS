#!/usr/bin/env python3
"""
DevOS Islamic notifier - the small background helper behind devos-islamic.service.

It runs only after the user turns DevOS Islamic on (systemctl --user enable
--now devos-islamic.service) and does three things:
  * a desktop notification at each of the five prayer times,
  * an optional reminder N minutes before each one,
  * an optional daily "Ayah of the day" / "Hadith of the day" notification,
playing the user's own adhan/reminder sound with paplay if they picked one.

Low CPU by design: there is no polling loop doing work every second. We work
out the next event, sleep until it (never more than 60 s at a time, so a
suspend/resume, a midnight rollover, a time-zone change or an edited settings
file is picked up within a minute), then simply recompute from the wall
clock. Events that were missed by more than a few minutes (the laptop was
asleep) are skipped instead of firing a burst of stale notifications.

Everything except run() is pure and unit-tested.
"""

import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import prayer_times as pt  # noqa: E402

APP_NAME = "DevOS"
ICON = "preferences-system-time"
MAX_SLEEP_S = 60
LATE_GRACE = _dt.timedelta(minutes=5)

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
    "language": "bn",            # "bn" or "en": translation shown on cards and daily notifications
    "sound": "",                 # the user's own audio file; nothing is bundled
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
            events.append(Event(at, "ayah", "", "Ayah of the day"))
            events.append(Event(at, "hadith", "", "Hadith of the day"))
    cutoff = now - LATE_GRACE
    return sorted((e for e in events if e.when > cutoff), key=lambda e: (e.when, e.kind))


def due_events(events, now, fired):
    """Events whose time has come (at most LATE_GRACE late) and were not sent yet."""
    return [e for e in events if e.when <= now and now - e.when <= LATE_GRACE and e.key not in fired]


def seconds_until_next(events, now, fired, max_sleep=MAX_SLEEP_S):
    """How long to sleep: until the next unsent event, capped at max_sleep (and >= 1)."""
    upcoming = [e for e in events if e.key not in fired and e.when > now]
    if not upcoming:
        return max_sleep
    delta = (upcoming[0].when - now).total_seconds()
    return max(1.0, min(float(max_sleep), delta))


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
        return None  # texts not downloaded; stay quiet rather than show nothing useful
    return content.short_text(item, "bn" if lang == "bn" else "en")


def notify(title, body, sound=""):
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", APP_NAME, "-i", ICON, title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print("%s: %s" % (title, body), flush=True)
    if sound and os.path.isfile(sound) and shutil.which("paplay"):
        subprocess.Popen(["paplay", sound], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run():
    path = settings_path()
    settings, stamp = load_settings(path), None
    fired = set()
    while True:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        if mtime != stamp:  # the window saved new settings
            settings, stamp = load_settings(path), mtime
        now = _dt.datetime.now(_dt.timezone.utc)
        events = build_events(now, settings)
        for event in due_events(events, now, fired):
            fired.add(event.key)
            body = event.body
            if event.kind in ("ayah", "hadith"):
                body = daily_text(event, settings, event.when.date())
                if not body:
                    continue
            # The user's adhan belongs to the prayer time itself, not the early reminder.
            sound = settings.get("sound", "") if event.kind == "prayer" else ""
            notify(event.title, body, sound)
        fired = prune_fired(fired, now)
        time.sleep(seconds_until_next(events, _dt.datetime.now(_dt.timezone.utc), fired))


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
