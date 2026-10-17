#!/usr/bin/env python3
"""
DevOS Islamic - Quran and Hadith texts (authentic sources only).

Nothing is bundled in the ISO and nothing is generated: when the user turns
DevOS Islamic on, the texts are downloaded ONCE from the fawazahmed0 datasets
on jsDelivr, pinned to an exact git commit and checked against SHA-256 sums
recorded below, so every DevOS PC shows exactly the same, verified words.

Sources (see /usr/share/doc/devos-islamic/SOURCES.txt):
  quran-api   https://github.com/fawazahmed0/quran-api   commit 47ca096b0976443ba2eab2e45cdf0fb4096a2610
  hadith-api  https://github.com/fawazahmed0/hadith-api  commit df57907be35291c91ad6a6691180e22ca9920784
Licence: both repositories are released under The Unlicense (public domain
dedication). The individual texts come from older sources (King Fahd Complex
Uthmani Hafs text via qurancomplex.gov.sa, translations via tanzil.net,
hadith translations as published by their translators); their original terms
ask for the text to be reproduced unchanged and credited, which is what we do:
we never edit a word, and every card shows its reference and translator.

Where the texts live:
  /var/lib/DevOS/islamic          system-wide (one copy for every account,
                                  written as root via pkexec on "enable")
  ~/.local/share/DevOS/islamic    per-user fallback when administrator
                                  approval is not available or was declined
Readers check the system folder first, then the user folder.

The local DevOS AI may only be used for the optional "Explain" reflection;
it never produces or "corrects" the ayah/hadith text itself.
"""

import datetime as _dt
import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request

SYSTEM_DIR = "/var/lib/DevOS/islamic"
QURAN_COMMIT = "47ca096b0976443ba2eab2e45cdf0fb4096a2610"
HADITH_COMMIT = "df57907be35291c91ad6a6691180e22ca9920784"
QURAN_BASE = "https://cdn.jsdelivr.net/gh/fawazahmed0/quran-api@%s" % QURAN_COMMIT
HADITH_BASE = "https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@%s" % HADITH_COMMIT

AYAH_COUNT = 6236
SURAH_COUNT = 114

# edition -> (language, what we show as the translator/source, sha256)
QURAN_EDITIONS = {
    "ara-quranuthmanihaf": ("ar", "Uthmani script, Hafs - King Fahd Glorious Quran Printing Complex",
                            "13a4668ca04e60898ee3922affa62a8a1d1a76d60f6e6f8431718eaa8a0e776d"),
    "ben-muhiuddinkhan": ("bn", "Muhiuddin Khan (Bangla)",
                          "679ca84d667bb6f581dcaceac2fd74b945c92a38be1123f67e44b7b2afa68614"),
    "eng-ummmuhammad": ("en", "Saheeh International (Umm Muhammad)",
                        "2b151ae6829e1edff538189a5ec8b102e00eaae820bbc343df53a605ec5f463f"),
}
QURAN_INFO_SHA = "99c654caeea7c63bf9634703167ea0f806d90c55f98d23e2e82d3e3d1b74075c"

# collection -> display name, editions (language -> (edition, translator, sha256)), entry count
HADITH_COLLECTIONS = {
    "bukhari": {
        "name": "Sahih al-Bukhari",
        "count": 7589,
        "editions": {
            "ar": ("ara-bukhari", "Arabic original",
                   "f887d8724f75fb6e1d5d29342a173af5346ad9b933173c85e6e3cb570063ea33"),
            "bn": ("ben-bukhari", "Bangla translation (translator not named by the dataset)",
                   "2886f6ec0af0833a7529ff63c608e035e61045b81788c08d2d23755f2df553ef"),
            "en": ("eng-bukhari", "Muhammad Muhsin Khan",
                   "60f8dfcf2cb8bcd2c8e281be68d912ee153e0fc4d02ad317d33c532d3814a04f"),
        },
    },
    "muslim": {
        "name": "Sahih Muslim",
        "count": 7563,
        "editions": {
            "ar": ("ara-muslim", "Arabic original",
                   "2cb296f3455ff8a3da9f6a0ca3de75da675788b2fb446ad316df297838e48217"),
            "bn": ("ben-muslim", "Bangla translation (translator not named by the dataset)",
                   "f24bf6d942fd96290abe37458214cb30f98b3f5f25109e388d3b04e5028d6ad0"),
            "en": ("eng-muslim", "Abdul Hamid Siddiqui",
                   "b5a04a66206b2cfaab18e2439ed2efeb824c6e179627e36a883dc060c03d4960"),
        },
    },
}

AI_URL = "http://127.0.0.1:11434/v1/chat/completions"
AI_MODEL = "devos-ai"
AI_TIMEOUT_S = 60
AI_LABEL = "AI reflection — may contain mistakes; not a religious ruling"
AI_UNAVAILABLE_MSG = "DevOS AI is not running right now — try again in a minute."
# The guard is deliberately blunt: a small local model will happily "quote"
# verses it half-remembers, and a wrong verse or hadith is far worse than no
# reflection at all.
AI_SYSTEM_PROMPT = (
    "You are DevOS AI writing a short, gentle personal reflection about a Quran ayah or a hadith "
    "that the user is reading. The exact text and its reference are given to you; they come from "
    "a verified source. Rules you must follow:\n"
    "1. Do NOT quote, recite, paraphrase as a quote, or invent any Quran verse or hadith - not even "
    "the one given. Never write Arabic scripture text. Never cite verse numbers, hadith numbers or "
    "collections other than the reference you were given.\n"
    "2. Do NOT issue fatwas or religious rulings, and do not say what is halal, haram, obligatory "
    "or forbidden. For rulings, tell the user to ask a qualified scholar.\n"
    "3. Write 3 to 5 short, plain sentences about the general meaning and how it can inspire good "
    "character today. Be humble; if unsure, say so.\n"
    "4. Reply in the language requested."
)

_LANG_NAMES = {"en": "English", "bn": "Bangla (Bengali)"}


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

def user_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "DevOS", "islamic")


def is_root():
    return hasattr(os, "geteuid") and os.geteuid() == 0


def data_dir():
    """The folder that already holds verified content, or None."""
    for path in (os.environ.get("DEVOS_ISLAMIC_DATA"), SYSTEM_DIR, user_dir()):
        if path and os.path.isfile(os.path.join(path, "manifest.json")):
            return path
    return None


def have_content():
    return data_dir() is not None


# ---------------------------------------------------------------------------
# Download + verify
# ---------------------------------------------------------------------------

class ContentError(Exception):
    pass


def _download(url, sha256, log=print):
    log("Downloading %s" % url.rsplit("/", 1)[-1])
    req = urllib.request.Request(url, headers={"User-Agent": "DevOS-Islamic/1"})
    digest = hashlib.sha256()
    chunks = []
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                chunks.append(chunk)
    except (urllib.error.URLError, OSError) as exc:
        raise ContentError("Could not download %s (%s). Check the internet connection." % (url, exc))
    if digest.hexdigest() != sha256:
        raise ContentError("%s did not match its recorded checksum - not using it." % url)
    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except ValueError as exc:
        raise ContentError("%s is not valid JSON (%s)" % (url, exc))


def build_quran(info, editions):
    """Merge downloaded editions into our compact file; raises ContentError if anything is off."""
    chapters = info.get("chapters", [])
    if len(chapters) != SURAH_COUNT:
        raise ContentError("Quran info has %d surahs, expected %d" % (len(chapters), SURAH_COUNT))
    texts = {}
    for name, data in editions.items():
        verses = data.get("quran", [])
        if len(verses) != AYAH_COUNT:
            raise ContentError("%s has %d ayahs, expected %d" % (name, len(verses), AYAH_COUNT))
        texts[QURAN_EDITIONS[name][0]] = verses
    ayahs = []
    for i in range(AYAH_COUNT):
        row = {lang: texts[lang][i] for lang in texts}
        ref = (row["ar"]["chapter"], row["ar"]["verse"])
        for lang, v in row.items():
            if (v["chapter"], v["verse"]) != ref or not v["text"].strip():
                raise ContentError("Quran editions disagree at %d:%d (%s)" % (ref[0], ref[1], lang))
        ayahs.append([ref[0], ref[1], row["ar"]["text"], row["bn"]["text"], row["en"]["text"]])
    return {
        "kind": "quran",
        "source": QURAN_BASE,
        "translators": {QURAN_EDITIONS[n][0]: QURAN_EDITIONS[n][1] for n in editions},
        "surahs": [{"number": c["chapter"], "name": c["name"], "english": c["englishname"],
                    "arabic": c.get("arabicname", ""), "verses": len(c.get("verses", []))}
                   for c in chapters],
        "ayahs": ayahs,
    }


def build_hadith(key, editions):
    """Keep hadiths present in all three languages with a whole-number reference."""
    spec = HADITH_COLLECTIONS[key]
    lists = {}
    for lang, data in editions.items():
        items = data.get("hadiths", [])
        if len(items) != spec["count"]:
            raise ContentError("%s %s has %d entries, expected %d" % (spec["name"], lang, len(items), spec["count"]))
        lists[lang] = items
    sections = editions["en"].get("metadata", {}).get("sections", {})
    keep = []
    for ar, bn, en in zip(lists["ar"], lists["bn"], lists["en"]):
        num = ar["hadithnumber"]
        if not (num == bn["hadithnumber"] == en["hadithnumber"]):
            raise ContentError("%s editions are out of step at %s" % (spec["name"], num))
        if float(num) != int(float(num)):
            continue  # sub-numbered variants (e.g. 402.2) - skip to keep references unambiguous
        if not (ar["text"].strip() and bn["text"].strip() and en["text"].strip()):
            continue
        book = (en.get("reference") or {}).get("book")
        keep.append([int(float(num)), ar["text"].strip(), bn["text"].strip(), en["text"].strip(),
                     book, sections.get(str(book), "")])
    if len(keep) < spec["count"] * 0.9:
        raise ContentError("%s: only %d complete hadiths found" % (spec["name"], len(keep)))
    return {
        "kind": "hadith",
        "collection": key,
        "name": spec["name"],
        "source": HADITH_BASE,
        "translators": {lang: spec["editions"][lang][1] for lang in spec["editions"]},
        "hadiths": keep,
    }


def _write_json(path, data):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def fetch_content(target=None, log=print):
    """Download, verify and store everything. Returns the folder used."""
    target = target or (SYSTEM_DIR if is_root() else user_dir())
    os.makedirs(target, mode=0o755, exist_ok=True)
    info = _download(QURAN_BASE + "/info.json", QURAN_INFO_SHA, log)
    editions = {name: _download("%s/editions/%s.min.json" % (QURAN_BASE, name), sha, log)
                for name, (_lang, _who, sha) in QURAN_EDITIONS.items()}
    quran = build_quran(info, editions)
    del info, editions
    hadith = {}
    for key, spec in HADITH_COLLECTIONS.items():
        eds = {lang: _download("%s/editions/%s.min.json" % (HADITH_BASE, ed), sha, log)
               for lang, (ed, _who, sha) in spec["editions"].items()}
        hadith[key] = build_hadith(key, eds)
    _write_json(os.path.join(target, "quran.json"), quran)
    for key, data in hadith.items():
        _write_json(os.path.join(target, "%s.json" % key), data)
    manifest = {
        "quran_commit": QURAN_COMMIT, "hadith_commit": HADITH_COMMIT,
        "ayahs": len(quran["ayahs"]),
        "hadiths": {k: len(v["hadiths"]) for k, v in hadith.items()},
        "fetched": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "licence": "The Unlicense (fawazahmed0/quran-api, fawazahmed0/hadith-api); see SOURCES.txt",
    }
    _write_json(os.path.join(target, "manifest.json"), manifest)  # written last = "complete"
    log("Saved %d ayahs and %s hadiths in %s" % (manifest["ayahs"], manifest["hadiths"], target))
    return target


# ---------------------------------------------------------------------------
# Reading + "of the day"
# ---------------------------------------------------------------------------

_cache = {}


def _load(name, folder=None):
    folder = folder or data_dir()
    if not folder:
        return None
    path = os.path.join(folder, name)
    key = (path, os.path.getmtime(path) if os.path.exists(path) else 0)
    if key not in _cache:
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            _cache.clear()  # keep only one big file in memory at a time
            _cache[key] = json.load(fh)
    return _cache[key]


def day_index(date, salt, n):
    """Stable pick for a date: same on every PC, every Python version, every run."""
    digest = hashlib.sha256(("%s:%s" % (salt, date.isoformat())).encode()).hexdigest()
    return int(digest[:12], 16) % n


def ayah_of_the_day(date, folder=None):
    quran = _load("quran.json", folder)
    if not quran:
        return None
    s, a, ar, bn, en = quran["ayahs"][day_index(date, "ayah", len(quran["ayahs"]))]
    surah = quran["surahs"][s - 1]
    return {
        "kind": "ayah", "surah": s, "ayah": a,
        "reference": "Surah %s (%s) %d:%d" % (surah["name"], surah["english"], s, a),
        "ar": ar, "bn": bn, "en": en,
        "translators": quran["translators"],
    }


def hadith_of_the_day(date, folder=None):
    keys = sorted(HADITH_COLLECTIONS)
    key = keys[day_index(date, "collection", len(keys))]
    data = _load("%s.json" % key, folder)
    if not data:
        return None
    num, ar, bn, en, book, book_name = data["hadiths"][day_index(date, "hadith", len(data["hadiths"]))]
    ref = "%s %d" % (data["name"], num)
    if book_name:
        ref += " · Book: %s" % book_name.strip()
    return {
        "kind": "hadith", "collection": key, "number": num,
        "reference": ref, "ar": ar, "bn": bn, "en": en,
        "translators": data["translators"],
    }


def short_text(item, lang="en", limit=180):
    """One-line version for a desktop notification (always with its reference)."""
    text = " ".join((item.get(lang) or item.get("en") or "").split())
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return "%s\n— %s" % (text, item["reference"])


# ---------------------------------------------------------------------------
# Optional AI reflection
# ---------------------------------------------------------------------------

def ai_messages(item, lang="en"):
    what = "Quran ayah" if item["kind"] == "ayah" else "hadith"
    text = item.get("en") or ""
    user = ("Reference: %s (%s).\nEnglish meaning (%s): %s\n\nWrite a short reflection in %s. "
            "Remember: do not quote any text, only reflect." % (
                item["reference"], what, item["translators"].get("en", ""), text,
                _LANG_NAMES.get(lang, "English")))
    return [{"role": "system", "content": AI_SYSTEM_PROMPT}, {"role": "user", "content": user}]


def ai_reflection(item, lang="en", url=AI_URL, timeout=AI_TIMEOUT_S):
    """The reflection text (to be shown under AI_LABEL), or AI_UNAVAILABLE_MSG."""
    body = json.dumps({"model": AI_MODEL, "messages": ai_messages(item, lang),
                       "temperature": 0.4, "max_tokens": 300}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            reply = json.loads(resp.read().decode("utf-8"))
        return reply["choices"][0]["message"]["content"].strip() or AI_UNAVAILABLE_MSG
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError):
        return AI_UNAVAILABLE_MSG
