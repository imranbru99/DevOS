#!/usr/bin/env python3
"""
DevOS AI voice preferences — wake name, TTS gender/language, hands-free.

Stored in ~/.config/devos/assistant.json (same file as hands-free).
Installer writes defaults into /var/lib/DevOS/voice-prefs.json and
/etc/skel/.config/devos/assistant.json.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "devos")
CONFIG_PATH = os.path.join(CONFIG_DIR, "assistant.json")
SYSTEM_PREFS = "/var/lib/DevOS/voice-prefs.json"
SKEL_PREFS = "/etc/skel/.config/devos/assistant.json"

DEFAULT_WAKE_NAME = "Mira"
DEFAULT_GENDER = "female"       # female | male
DEFAULT_TTS_LANG = "auto"       # auto | en | bn  (auto = match what the user spoke)

# Edge neural voices used for spoken replies.
EDGE_VOICES = {
    ("en", "female"): "en-US-JennyNeural",
    ("en", "male"): "en-US-GuyNeural",
    ("bn", "female"): "bn-BD-NabanitaNeural",
    ("bn", "male"): "bn-BD-PradeepNeural",
}

TEST_PHRASES = {
    "en": {
        "female": "Hello, I'm Mira. I can open apps, search the web, and help with this PC.",
        "male": "Hello, I'm Mira. I can open apps, search the web, and help with this PC.",
    },
    "bn": {
        "female": "হ্যালো, আমি মিরা। আমি অ্যাপ খুলতে, খুঁজতে এবং এই কম্পিউটারে সাহায্য করতে পারি।",
        "male": "হ্যালো, আমি মিরা। আমি অ্যাপ খুলতে, খুঁজতে এবং এই কম্পিউটারে সাহায্য করতে পারি।",
    },
}


def _defaults() -> Dict[str, object]:
    return {
        "hands_free": False,
        "paused": False,
        "wake_name": DEFAULT_WAKE_NAME,
        "tts_gender": DEFAULT_GENDER,
        "tts_language": DEFAULT_TTS_LANG,
    }


def _normalize_prefs(data: Dict[str, object]) -> Dict[str, object]:
    data["wake_name"] = normalize_wake_name(str(data.get("wake_name") or DEFAULT_WAKE_NAME))
    gender = str(data.get("tts_gender") or DEFAULT_GENDER).lower()
    data["tts_gender"] = gender if gender in ("female", "male") else DEFAULT_GENDER
    lang = str(data.get("tts_language") or DEFAULT_TTS_LANG).lower()
    data["tts_language"] = lang if lang in ("auto", "en", "bn") else DEFAULT_TTS_LANG
    data["hands_free"] = bool(data.get("hands_free", False))
    data["paused"] = bool(data.get("paused", False))
    return data


def _write_prefs(path: str, data: Dict[str, object]) -> None:
    """Atomic write without calling load/save (avoids first-login recursion)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def load(path: str = CONFIG_PATH) -> Dict[str, object]:
    data = dict(_defaults())
    # First login: seed from installer system prefs if user file is missing.
    if not os.path.isfile(path) and os.path.isfile(SYSTEM_PREFS):
        try:
            with open(SYSTEM_PREFS, encoding="utf-8") as fh:
                sys_data = json.load(fh)
            if isinstance(sys_data, dict):
                data.update({k: sys_data[k] for k in _defaults() if k in sys_data})
                data = _normalize_prefs(data)
                try:
                    _write_prefs(path, {k: data[k] for k in _defaults()})
                except OSError:
                    pass
                return data
        except (OSError, ValueError):
            pass
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            data.update(raw)
    except (OSError, ValueError):
        pass
    return _normalize_prefs(data)


def save(path: str = CONFIG_PATH, **updates) -> Dict[str, object]:
    data = load(path)
    if "wake_name" in updates:
        updates["wake_name"] = normalize_wake_name(str(updates["wake_name"] or DEFAULT_WAKE_NAME))
    if "tts_gender" in updates:
        g = str(updates["tts_gender"] or "").lower()
        updates["tts_gender"] = g if g in ("female", "male") else data["tts_gender"]
    if "tts_language" in updates:
        lang = str(updates["tts_language"] or "").lower()
        updates["tts_language"] = lang if lang in ("auto", "en", "bn") else data["tts_language"]
    data.update(updates)
    data = _normalize_prefs(data)
    try:
        _write_prefs(path, data)
    except OSError:
        pass
    return data


def normalize_wake_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9\u0980-\u09FF \-]", "", (name or "").strip())
    name = re.sub(r"\s+", " ", name).strip()
    if not name:
        return DEFAULT_WAKE_NAME
    # Title-case Latin; keep Bangla as typed.
    if re.fullmatch(r"[A-Za-z0-9 \-]+", name):
        return " ".join(p[:1].upper() + p[1:].lower() for p in name.split())
    return name


def wake_name(path: str = CONFIG_PATH) -> str:
    return str(load(path).get("wake_name") or DEFAULT_WAKE_NAME)


def tts_gender(path: str = CONFIG_PATH) -> str:
    return str(load(path).get("tts_gender") or DEFAULT_GENDER)


def tts_language_pref(path: str = CONFIG_PATH) -> str:
    return str(load(path).get("tts_language") or DEFAULT_TTS_LANG)


def edge_voice_id(language: str, gender: Optional[str] = None) -> str:
    lang = "bn" if language == "bn" else "en"
    g = (gender or tts_gender()).lower()
    if g not in ("female", "male"):
        g = "female"
    return EDGE_VOICES[(lang, g)]


def resolve_reply_language(spoken_lang: Optional[str] = None, text: str = "",
                           path: str = CONFIG_PATH) -> str:
    """Language for the spoken/written reply: prefer spoken, then pref, then text script."""
    pref = tts_language_pref(path)
    if pref in ("en", "bn"):
        return pref
    if spoken_lang in ("en", "bn"):
        return spoken_lang
    # auto from text script
    if re.search(r"[\u0980-\u09FF]", text or ""):
        return "bn"
    return "en"


def test_phrase(language: str, gender: str) -> str:
    lang = "bn" if language == "bn" else "en"
    g = gender if gender in ("female", "male") else "female"
    return TEST_PHRASES[lang][g]


def play_test(language: str, gender: str) -> Tuple[bool, str]:
    """Synthesize and play a short sample. Returns (ok, message)."""
    phrase = test_phrase(language, gender)
    try:
        import voice as _voice
    except Exception as exc:
        return False, f"Voice module unavailable: {exc}"
    out = os.path.join(_voice._TTS_CACHE, "devos-voice-test.mp3")
    os.makedirs(_voice._TTS_CACHE, exist_ok=True)
    lang = language if language in ("en", "bn") else "en"
    voice_id = edge_voice_id(lang, gender)
    # Prefer the exact voice id for this gender (pool otherwise reads saved prefs).
    ok = False
    py = os.path.join(_voice._TTS_VENV, "bin", "python")
    if os.path.isfile(py):
        script = (
            "import asyncio, edge_tts, sys\n"
            "asyncio.run(edge_tts.Communicate(sys.argv[1], sys.argv[2], rate=sys.argv[4]).save(sys.argv[3]))\n"
        )
        try:
            proc = subprocess.run(
                [py, "-c", script, phrase, voice_id, out, _voice._TTS_RATE],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
            )
            ok = proc.returncode == 0 and os.path.isfile(out) and os.path.getsize(out) > 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
    if not ok:
        # Fall back through the warm pool (uses currently saved gender).
        prev = tts_gender()
        try:
            save(tts_gender=gender)
            ok = _voice._EdgePool.synthesize(phrase, lang, out, rate=_voice._TTS_RATE)
        finally:
            save(tts_gender=prev)
    if ok and _voice._play_file(out):
        return True, "Playing sample…"
    if _voice._speak_espeak(phrase, "bn" if lang == "bn" else "en"):
        return True, "Playing local sample…"
    return False, "Could not play a sample on this PC."


def apply_installer_choice(raw: str, dest_system: str = SYSTEM_PREFS,
                           dest_skel: str = SKEL_PREFS) -> Dict[str, object]:
    """Parse installer packageChoice and write system + skel defaults.

    Format: mira=1;gender=female;lang=auto;wake=Mira
    """
    parts = {}
    for chunk in (raw or "").split(";"):
        chunk = chunk.strip()
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            parts[k.strip().lower()] = v.strip()
    prefs = _defaults()
    prefs["hands_free"] = parts.get("mira", "0") in ("1", "true", "yes", "on")
    g = parts.get("gender", DEFAULT_GENDER).lower()
    prefs["tts_gender"] = g if g in ("female", "male") else DEFAULT_GENDER
    lang = parts.get("lang", DEFAULT_TTS_LANG).lower()
    prefs["tts_language"] = lang if lang in ("auto", "en", "bn") else DEFAULT_TTS_LANG
    prefs["wake_name"] = normalize_wake_name(parts.get("wake") or DEFAULT_WAKE_NAME)
    for path in (dest_system, dest_skel):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(prefs, fh, indent=1, ensure_ascii=False)
            try:
                os.chmod(path, 0o644)
            except OSError:
                pass
        except OSError:
            pass
    return prefs


def wake_aliases(name: str) -> List[str]:
    """Compact lowercase forms the STT might produce for the wake name."""
    base = re.sub(r"[^a-z0-9\u0980-\u09FF]", "", (name or "").lower())
    if not base:
        base = "mira"
    forms = {base, DEFAULT_WAKE_NAME.lower(), "mira", "meera", "mirra", "meer a", "mir a"}
    # Common STT misspellings for Mira
    forms.update({"mira", "meera", "miraa", "mirra", "myra", "miera", "mera", "miro"})
    # Bangla মিরা
    forms.update({"মিরা", "mira"})
    # Also keep DevOS legacy forms so old habit still works
    forms.update({"devos", "devops"})
    return sorted(forms)


def is_stop_phrase(text: str, name: Optional[str] = None) -> bool:
    """True for hang-up phrases: stop, Mira stop, stop now, end call, …"""
    name = normalize_wake_name(name or wake_name())
    raw = (text or "").strip().lower()
    if not raw:
        return False
    raw = re.sub(r"[^\w\s\u0980-\u09FF]", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    wake = re.sub(r"[^a-z0-9\u0980-\u09FF]", "", name.lower()) or "mira"
    # Strip leading wake name so "mira stop now" == "stop now"
    for w in (wake, "mira", "meera", "myra", "মিরা", "devos"):
        if raw == w or raw.startswith(w + " "):
            raw = raw[len(w):].strip()
            break
    stops = {
        "stop", "stop now", "please stop", "hang up", "hangup", "end call",
        "end the call", "cancel", "quiet", "be quiet", "shut up",
        "বন্ধ", "বন্ধ করো", "থামো", "থাম",
    }
    return raw in stops


def match_wake_name(text: str, name: Optional[str] = None) -> Tuple[bool, str]:
    """(heard wake name, command after it). Supports Mira / custom / legacy DevOS."""
    name = normalize_wake_name(name or wake_name())
    raw = text or ""
    # Bangla: look for wake as substring near the start
    bn_name = name if re.search(r"[\u0980-\u09FF]", name) else "মিরা"
    for bn in (bn_name, "মিরা"):
        idx = raw.find(bn)
        if 0 <= idx <= 24:
            rest = raw[idx + len(bn):]
            rest = re.sub(r"^[\s,.!?:;'’\-]+", "", rest).strip()
            return True, rest

    toks = [(m.group(0).lower().replace("'", "").replace("’", ""), m.start(), m.end())
            for m in re.finditer(r"[A-Za-z\u0980-\u09FF][A-Za-z\u0980-\u09FF'’]*", raw)]
    if not toks:
        return False, ""

    greetings = ("hey", "hi", "hay", "hei", "ok", "okay", "hello", "a", "eh", "yo", "oi", "oye", "are", "call")
    i = 0
    greeted = False
    while i < len(toks) and i < 2 and toks[i][0] in greetings:
        greeted = True
        i += 1

    aliases = set(wake_aliases(name))
    primary = re.sub(r"[^a-z0-9]", "", name.lower()) or "mira"
    # Compact join for split STT ("mi ra", "dev os")
    for n in (3, 2, 1):
        if i + n > len(toks):
            continue
        compact = "".join(t[0] for t in toks[i:i + n])
        if compact in aliases or _near(compact, primary) or _near(compact, "mira") or _near(compact, "devos"):
            if not greeted and compact not in aliases and not _near(compact, primary) and not _near(compact, "mira"):
                if compact not in ("mira", "devos", primary):
                    continue
            rest = raw[toks[i + n - 1][2]:]
            rest = re.sub(r"^[\s,.!?:;'’\-]+", "", rest).strip()
            return True, rest
    # Lone fuzzy wake anywhere in a short utterance ("um mira", "mirror")
    if len(toks) <= 3:
        for t, _a, _b in toks:
            if t in aliases or _near(t, primary) or _near(t, "mira"):
                return True, ""
    return False, ""


def _near(a: str, b: str, max_dist: int = 1) -> bool:
    if not a or not b or abs(len(a) - len(b)) > max_dist:
        return False
    if a == b:
        return True
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[-1] <= max_dist


def main(argv=None):
    import sys
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "apply-installer":
        raw = argv[1] if len(argv) > 1 else ""
        prefs = apply_installer_choice(raw)
        print(json.dumps(prefs, ensure_ascii=False))
        return 0
    if argv and argv[0] == "test":
        lang = argv[1] if len(argv) > 1 else "en"
        gender = argv[2] if len(argv) > 2 else "female"
        ok, msg = play_test(lang, gender)
        print(msg)
        return 0 if ok else 1
    print(json.dumps(load(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
