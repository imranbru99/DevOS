#!/usr/bin/env python3
"""Find the DevOS way to get an app someone asks for.

DevOS AI uses this when someone pastes a Microsoft Store, Google Play, App
Store or Flathub link, or says "install <app>". The small on-device model
used to invent install steps; this answers from facts instead:

    resolve(query=..., link=...) -> dict    what the app is and the best DevOS option
    reply_text(resolution)       -> str     a short, plain answer

The order of preference:
  1. a DevOS Features entry (components/features/feature_catalog.py),
     matched by its name or the Windows app it stands in for
  2. native_alternatives.CATALOG: Windows/Store apps and their DevOS answer
     (a Flathub app, a built-in DevOS app, or the web version)
  3. the Flathub search API (top result)
  4. a plain Windows program: its .exe runs on DevOS (Windows layer)

Store apps (MSIX/UWP from the Microsoft Store, Google Play, App Store) never
run on DevOS, not even through the Windows layer, so they always get the
DevOS way instead.

Network access goes through one injectable fetch(url, data=None, headers=None)
function, so tests run offline with fakes. Run as a program it installs:

    app_resolver.py --install --name Remmina --flatpak org.remmina.Remmina
    app_resolver.py --install --name Zoom --feature zoom
"""

import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "features"))

import native_alternatives as native  # noqa: E402

try:
    import feature_catalog as catalog  # noqa: E402
except ImportError:  # pragma: no cover - DevOS Features not shipped
    catalog = None

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) DevOS-AI/1.0"
TIMEOUT = 8
FLATHUB_SEARCH_API = "https://flathub.org/api/v2/search"
FLATHUB_APPSTREAM_API = "https://flathub.org/api/v2/appstream/"
FLATHUB_SEARCH_PAGE = "https://flathub.org/apps/search?q="
FEATURES_CMD = "/usr/local/bin/devos-features"

Fetch = Callable[..., str]


class FetchError(Exception):
    """A page could not be read. offline=True: no connection at all."""

    def __init__(self, message: str, offline: bool = True):
        super().__init__(message)
        self.offline = offline


def http_fetch(url: str, data: Optional[bytes] = None, headers: Optional[Dict[str, str]] = None,
               timeout: float = TIMEOUT) -> str:
    hdrs = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(3_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code}", offline=False)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError(str(exc), offline=True)


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

LINK_RE = re.compile(r"(?:https?://|ms-windows-store://)[^\s<>\"'`]+|"
                     r"(?<![\w@.])(?:apps\.microsoft\.com|play\.google\.com|apps\.apple\.com|flathub\.org)/[^\s<>\"'`]+",
                     re.I)
_MS_ID = re.compile(r"^(?:9[0-9a-z]{11}|xp[0-9a-z]{12})$", re.I)
_FLATPAK_ID = re.compile(r"^[A-Za-z][\w-]*(?:\.[\w-]+){2,}$")

# Ids people paste most; used when the page can't be read. Each was checked
# against the store page title.
MS_STORE_IDS = {
    "9N1F85V9T8BN": "Windows App",
    "9NKSQGP7F2NH": "WhatsApp",
    "9NCBCSZSJRSB": "Spotify",
    "9WZDNCRFJ3TJ": "Netflix",
}
PLAY_IDS = {
    "com.whatsapp": "WhatsApp", "com.whatsapp.w4b": "WhatsApp Business", "org.telegram.messenger": "Telegram",
    "com.facebook.katana": "Facebook", "com.facebook.orca": "Messenger", "com.instagram.android": "Instagram",
    "com.zhiliaoapp.musically": "TikTok", "com.ss.android.ugc.trill": "TikTok", "com.twitter.android": "X",
    "com.spotify.music": "Spotify", "us.zoom.videomeetings": "Zoom", "com.microsoft.teams": "Microsoft Teams",
    "com.microsoft.office.outlook": "Outlook", "com.microsoft.office.officehubrow": "Microsoft 365",
    "com.microsoft.office.word": "Word", "com.microsoft.office.excel": "Excel",
    "com.microsoft.office.powerpoint": "PowerPoint", "com.microsoft.office.onenote": "OneNote",
    "com.microsoft.skydrive": "OneDrive", "com.microsoft.rdc.androidx": "Windows App",
    "com.netflix.mediaclient": "Netflix", "com.amazon.avod.thirdpartyclient": "Prime Video",
    "com.disney.disneyplus": "Disney+", "com.google.android.youtube": "YouTube", "com.discord": "Discord",
    "com.viber.voip": "Viber", "org.thoughtcrime.securesms": "Signal", "com.slack": "Slack",
    "org.videolan.vlc": "VLC", "com.anydesk.anydeskandroid": "AnyDesk", "com.snapchat.android": "Snapchat",
    "com.linkedin.android": "LinkedIn", "com.google.android.apps.docs": "Google Drive",
    "com.mojang.minecraftpe": "Minecraft", "com.roblox.client": "Roblox", "com.canva.editor": "Canva",
    "com.openai.chatgpt": "ChatGPT", "com.lemon.lvoverseas": "CapCut",
}
STORE_LABEL = {"microsoft": "Microsoft Store", "play": "Google Play", "apple": "App Store", "flathub": "Flathub"}


def find_link(text: str) -> Optional[str]:
    """The first web or Store link in a message, without trailing punctuation."""
    m = LINK_RE.search(text or "")
    if not m:
        return None
    link = m.group(0).rstrip(".,;:!?)]}>'\"")
    if not re.match(r"^(?:https?|ms-windows-store)://", link, re.I):
        link = "https://" + link
    return link


def parse_link(url: str) -> Optional[Dict[str, str]]:
    """{"store": microsoft|play|apple|flathub|web, "id": ..., "url": ...} or None."""
    url = (url or "").strip()
    if not url:
        return None
    if url.lower().startswith("ms-windows-store://"):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        pid = next((v[0] for k, v in q.items() if k.lower() == "productid" and v), "")
        if _MS_ID.match(pid):
            return {"store": "microsoft", "id": pid.upper(), "url": url}
        return None
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    segs = [s for s in parts.path.split("/") if s]
    if host in ("apps.microsoft.com", "www.microsoft.com", "microsoft.com"):
        pid = next((s for s in reversed(segs) if _MS_ID.match(s)), "")
        if not pid:
            pid = next((v[0] for k, v in urllib.parse.parse_qs(parts.query).items()
                        if k.lower() in ("productid", "id") and v and _MS_ID.match(v[0])), "")
        if pid and (host == "apps.microsoft.com" or "store" in segs or "p" in segs):
            return {"store": "microsoft", "id": pid.upper(), "url": url}
        return None
    if host == "play.google.com":
        pkg = urllib.parse.parse_qs(parts.query).get("id", [""])[0]
        if re.match(r"^[A-Za-z][\w]*(?:\.[\w]+)+$", pkg):
            return {"store": "play", "id": pkg, "url": url}
        return None
    if host in ("apps.apple.com", "itunes.apple.com"):
        m = re.search(r"/id(\d+)", parts.path)
        if m:
            slug = segs[segs.index("app") + 1] if "app" in segs and segs.index("app") + 2 < len(segs) else ""
            return {"store": "apple", "id": m.group(1), "slug": slug, "url": url}
        return None
    if host in ("flathub.org", "www.flathub.org", "beta.flathub.org"):
        if "apps" in segs:
            rest = segs[segs.index("apps") + 1:]
            if rest and rest[0] == "details":
                rest = rest[1:]
            if rest and _FLATPAK_ID.match(rest[0]):
                return {"store": "flathub", "id": rest[0], "url": url}
        return None
    if host:
        return {"store": "web", "id": host, "url": url}
    return None


# ---------------------------------------------------------------------------
# App names from store pages
# ---------------------------------------------------------------------------

_BAD_TITLE = re.compile(r"service unavailable|access denied|forbidden|not found|\berror\b|just a moment|"
                        r"attention required|sign in|captcha|^microsoft store$|^google play$|^app store$", re.I)


def _clean_title(t: str, store: str = "") -> str:
    t = html.unescape(t or "").replace("‎", "").replace("‏", "").strip()
    t = re.split(r"\s+[|\-–—]\s+", t)[0].strip()
    t = re.sub(r"\s+on the app store$", "", t, flags=re.I)
    if store == "apple":
        t = re.sub(r"\s+app$", "", t, flags=re.I)
    return t.strip(" \t:")


def page_app_name(page: str, store: str = "") -> Optional[str]:
    """App name from a store page: og:title, then <title>, then JSON "name"."""
    if not page:
        return None
    found: List[str] = []
    for pat in (r"<meta[^>]+property=[\"']og:title[\"'][^>]*content=[\"']([^\"']+)",
                r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]*property=[\"']og:title",
                r"<title[^>]*>([^<]+)</title>"):
        m = re.search(pat, page, re.I)
        if m:
            found.append(m.group(1))
    m = re.search(r"\"name\"\s*:\s*\"([^\"]{1,80})\"", page)
    if m:
        found.append(m.group(1))
    for raw in found:
        if _BAD_TITLE.search(html.unescape(raw)):
            continue
        name = _clean_title(raw, store)
        if name and len(name) <= 80 and not _BAD_TITLE.search(name):
            return name
    return None


def _store_page_url(link: Dict[str, str]) -> str:
    if link["store"] == "microsoft":
        return f"https://apps.microsoft.com/detail/{link['id'].lower()}?hl=en-US&gl=US"
    if link["store"] == "play":
        return "https://play.google.com/store/apps/details?" + urllib.parse.urlencode({"id": link["id"], "hl": "en"})
    return link["url"]


def name_from_link(link: Dict[str, str], fetch: Fetch) -> Dict[str, object]:
    """{"name": str, "offline": bool, "known": bool}: what app a link is about."""
    store = link["store"]
    if store == "flathub":
        try:
            data = json.loads(fetch(FLATHUB_APPSTREAM_API + link["id"]))
            return {"name": str(data.get("name") or link["id"]), "summary": str(data.get("summary") or ""),
                    "offline": False, "known": True}
        except FetchError as exc:
            return {"name": link["id"], "offline": exc.offline, "known": not exc.offline}
        except (ValueError, AttributeError):
            return {"name": link["id"], "offline": False, "known": True}
    offline = False
    try:
        name = page_app_name(fetch(_store_page_url(link)), store)
    except FetchError as exc:
        name, offline = None, exc.offline
    if name:
        return {"name": name, "offline": False, "known": True}
    if store == "microsoft" and link["id"] in MS_STORE_IDS:
        return {"name": MS_STORE_IDS[link["id"]], "offline": offline, "known": True}
    if store == "play" and link["id"].lower() in PLAY_IDS:
        return {"name": PLAY_IDS[link["id"].lower()], "offline": offline, "known": True}
    if store == "apple" and link.get("slug"):
        return {"name": link["slug"].replace("-", " "), "offline": offline, "known": True}
    if store == "web":
        label = link["id"].split(".")
        label = [p for p in label if p not in ("www", "web", "app", "apps", "download", "get")]
        return {"name": label[0] if label else link["id"], "offline": offline, "known": bool(label)}
    return {"name": link["id"], "offline": offline, "known": False}


# ---------------------------------------------------------------------------
# DevOS options
# ---------------------------------------------------------------------------

def _features() -> List[Dict]:
    return list(catalog.FEATURES) if catalog is not None else []


def _feature(fid: str) -> Optional[Dict]:
    return next((f for f in _features() if f["id"] == fid), None)


def short_name(name: str) -> str:
    """"ONLYOFFICE (Word, Excel, PowerPoint look-alike)" -> "ONLYOFFICE"."""
    return re.sub(r"\s*\(.*?\)\s*", " ", name or "").strip()


def _feature_keys(f: Dict) -> List[str]:
    keys = [f["id"], native.normalize_name(f["name"]), native.normalize_name(short_name(f["name"]))]
    for part in re.split(r"\s*(?:/|,|\bor\b)\s*", f.get("windows") or ""):
        if part.strip():
            keys.append(native.normalize_name(part))
    return [k for k in keys if k]


def _bare(q: str) -> str:
    return re.sub(r"\s+(?:for (?:pc|windows|desktop|computer|laptop)|desktop|for linux)$", "", q).strip()


def feature_exact(q: str) -> Optional[Dict]:
    for cand in (q, _bare(q)):
        for f in _features():
            if cand in _feature_keys(f):
                return f
    return None


def feature_by_flatpak(app_id: str) -> Optional[Dict]:
    return next((f for f in _features() if app_id and app_id in f["flatpak"]), None)


def feature_fuzzy(q: str) -> Optional[Dict]:
    for f in _features():
        for k in _feature_keys(f):
            if len(k) >= 4 and re.search(r"\b" + re.escape(k) + r"\b", q):
                return f
            if len(q) >= 4 and re.search(r"\b" + re.escape(q) + r"\b", k):
                return f
    return None


_STOP = {"app", "apps", "the", "for", "pc", "windows", "microsoft", "download", "free", "desktop", "and", "official",
         "install", "latest", "version", "new", "software", "program"}


def flathub_search(query: str, fetch: Fetch) -> Dict[str, object]:
    """{"hit": {name, flatpak, summary} or None, "offline": bool}."""
    try:
        raw = fetch(FLATHUB_SEARCH_API, data=json.dumps({"query": query}).encode("utf-8"),
                    headers={"Content-Type": "application/json"})
        hits = json.loads(raw).get("hits") or []
    except FetchError as exc:
        return {"hit": None, "offline": exc.offline}
    except (ValueError, AttributeError):
        return {"hit": None, "offline": False}
    words = [w for w in native.normalize_name(query).split() if len(w) >= 3 and w not in _STOP]
    for h in hits[:5]:
        if not isinstance(h, dict) or not h.get("app_id"):
            continue
        hay = native.normalize_name(f"{h.get('name', '')} {h['app_id']} {' '.join(h.get('keywords') or [])}")
        if not words or any(re.search(r"\b" + re.escape(w), hay) for w in words):
            return {"hit": {"name": str(h.get("name") or h["app_id"]), "flatpak": str(h["app_id"]),
                            "summary": str(h.get("summary") or "")}, "offline": False}
    return {"hit": None, "offline": False}


def _option_from_feature(f: Dict, entry: Optional[Dict]) -> Dict[str, object]:
    name = short_name(f["name"])
    if entry and entry.get("flatpak") and entry["flatpak"] in f["flatpak"]:
        name = entry["name"]
    return {"name": name, "feature": f["id"], "flatpak": (f["flatpak"] or [""])[0],
            "size_mb": f.get("size_mb") or 0, "preinstalled": bool(f.get("preinstalled")),
            "webapp": bool(f.get("webapp")),
            "builtin": (entry or {}).get("builtin", "") if f.get("preinstalled") else "",
            "why": (entry or {}).get("why") or f.get("about", "")}


def _guarded(fetch: Fetch) -> Fetch:
    """Any failure of an injected fetch becomes a FetchError (OSError: offline)."""
    def call(url, data=None, headers=None):
        try:
            return fetch(url, data=data, headers=headers)
        except FetchError:
            raise
        except OSError as exc:
            raise FetchError(str(exc), offline=True)
        except Exception as exc:
            if type(exc).__name__ == "FetchError":     # same class loaded under another module name
                raise FetchError(str(exc), offline=bool(getattr(exc, "offline", True)))
            raise FetchError(str(exc), offline=False)
    return call


def resolve(query: str = "", link: str = "", fetch: Optional[Fetch] = None) -> Dict[str, object]:
    """Work out what app is meant and the best way to get it on DevOS."""
    fetch = _guarded(fetch or http_fetch)
    res: Dict[str, object] = {"query": query or "", "link": link or "", "store": "", "name": (query or "").strip(),
                              "offline": False, "known": True, "option": None, "web": "", "note": "",
                              "download": "", "found_by": "", "search_url": ""}
    parsed = parse_link(link) if link else None
    if link and parsed is None:
        res["known"] = False
        return res
    if parsed:
        res["store"] = parsed["store"] if parsed["store"] != "web" else ""
        got = name_from_link(parsed, fetch)
        res["name"], res["offline"], res["known"] = got["name"], got["offline"], got["known"]
        if parsed["store"] == "flathub":
            res["option"] = {"name": got["name"], "feature": "", "flatpak": parsed["id"], "size_mb": 0,
                             "preinstalled": False, "builtin": "", "why": got.get("summary", "")}
            res["found_by"] = "flathub"
            f = feature_by_flatpak(parsed["id"])
            if f:
                res["option"] = _option_from_feature(f, None)
                res["found_by"] = "feature"
            return res
    name = str(res["name"]).strip()
    if not name:
        return res
    res["search_url"] = FLATHUB_SEARCH_PAGE + urllib.parse.quote(name)
    if not res["known"]:
        return res
    q = native.normalize_name(name)
    feat = feature_exact(q)
    entry = native.lookup(q)
    if feat is not None and entry is not None:
        same = entry.get("feature") == feat["id"] or (entry.get("flatpak") and entry["flatpak"] in feat["flatpak"])
        if not same and (entry.get("feature") or entry.get("flatpak") or entry.get("builtin")):
            entry = None          # "obsidian" is not OBS Studio
    if feat is None and entry is not None:
        if entry.get("feature"):
            feat = _feature(str(entry["feature"]))
        elif entry.get("flatpak"):
            feat = feature_by_flatpak(str(entry["flatpak"]))
    if feat is None and entry is None:
        feat = feature_fuzzy(q)
    if entry is not None:
        res["web"] = entry.get("web") or ""
        res["note"] = entry.get("note") or ""
        res["download"] = entry.get("download") or ""
    if feat is not None:
        res["option"] = _option_from_feature(feat, entry)
        res["found_by"] = "feature"
        return res
    if entry is not None:
        res["found_by"] = "catalog"
        if entry.get("flatpak") or entry.get("builtin"):
            res["option"] = {"name": entry["name"], "feature": "", "flatpak": entry.get("flatpak", ""),
                             "size_mb": 0, "preinstalled": bool(entry.get("builtin")),
                             "builtin": entry.get("builtin", ""), "why": entry.get("why", "")}
        else:
            res["option"] = None
            res["why"] = entry.get("why", "")
        return res
    found = flathub_search(name, fetch)
    if found["offline"]:
        res["offline"] = True
    if found["hit"]:
        hit = found["hit"]
        res["option"] = {"name": hit["name"], "feature": "", "flatpak": hit["flatpak"], "size_mb": 0,
                         "preinstalled": False, "builtin": "", "why": hit["summary"]}
        res["found_by"] = "flathub"
        f = feature_by_flatpak(hit["flatpak"])
        if f:
            res["option"] = _option_from_feature(f, None)
            res["found_by"] = "feature"
    return res


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------

def _sentence(s: str) -> str:
    s = (s or "").strip()
    return s if not s or s[-1] in ".!?" else s + "."


def reply_text(res: Dict[str, object]) -> str:
    """Short, plain sentences. Never invents menu steps: only what the buttons do."""
    name = str(res.get("name") or "").strip()
    store = str(res.get("store") or "")
    opt = res.get("option") or None
    lines: List[str] = []
    if not name:
        if res.get("link"):
            return "I can't tell which app that link is for. Tell me the app's name and I'll find it for you."
        return "Which app do you want? Tell me its name or paste its link (Microsoft Store, Google Play or Flathub)."
    vendor_web = bool(opt and opt.get("webapp"))
    if store == "microsoft" and vendor_web:
        # The maker's own web app installs fine; only the Store package can't.
        lines.append(f"The Microsoft Store version of “{name}” only runs on Windows, but Microsoft's own "
                     "web version installs on DevOS as a normal app with its own window and icon.")
    elif store == "microsoft":
        lines.append(f"“{name}” is a Microsoft Store app. Store apps only run on Windows, "
                     "so it can't be installed on DevOS (not even with the Windows layer).")
    elif store == "play":
        lines.append(f"“{name}” is an Android app from Google Play. Play Store apps are made for phones.")
    elif store == "apple":
        lines.append(f"“{name}” is from Apple's App Store. Those apps only run on iPhone, iPad and Mac.")
    if res.get("offline"):
        if res.get("known") and store:
            lines.append("I couldn't reach the internet, so I went by the link's id.")
        elif not res.get("known"):
            lines.append("I couldn't reach the internet to check this link, so I can't tell which app it is. "
                         "Connect to the internet and ask me again, or tell me the app's name.")
            return "\n\n".join(lines)
        else:
            lines.append("I couldn't reach the internet to search for more apps.")
    elif not res.get("known") and store:
        lines.append("I couldn't read that store page. Tell me the app's name and I'll find the DevOS way.")
        return "\n\n".join(lines)

    web = str(res.get("web") or "")
    if opt:
        oname = str(opt.get("name") or "")
        why = _sentence(str(opt.get("why") or ""))
        lead = "The DevOS way: " if store or native.normalize_name(oname) != native.normalize_name(name) else ""
        if store == "flathub" or res.get("found_by") == "flathub":
            text = f"**{oname}** is on Flathub, the app store DevOS uses. {why}".strip()
            if store != "flathub" and native.normalize_name(oname) != native.normalize_name(name):
                text = f"I found **{oname}** on Flathub: {why}".strip()
        elif opt.get("preinstalled"):
            text = f"{lead}**{oname}** already comes with DevOS. {why}".strip()
        else:
            text = f"{lead}**{oname}**. {why}".strip() if lead else f"**{oname}** has a DevOS version. {why}".strip()
        lines.append(text)
        if web and not vendor_web:
            lines.append("Or use the web version in Chrome — nothing to install.")
        if vendor_web:
            lines.append(f"Click **Install {oname}** below: it appears in the Start menu right away, no download.")
        elif opt.get("preinstalled"):
            lines.append(f"Click **Open {oname}** below.")
        elif not vendor_web:
            lines.append(f"Click **Install {oname}** below. DevOS asks you first, then downloads it.")
    elif web:
        why = _sentence(str(res.get("why") or ""))
        lines.append(f"{why} Click **Open web version** below.".strip())
    elif res.get("why") or res.get("note"):
        lines.append(_sentence(str(res.get("why") or "")))
    else:
        lines.append(f"I couldn't find “{name}” as a DevOS app. If it has a Windows download (.exe or .msi), "
                     "DevOS can run it: download it and double-click the file.")
    if res.get("note"):
        lines.append(str(res["note"]))
    return "\n\n".join(x for x in lines if x)


# ---------------------------------------------------------------------------
# Installing (run detached by DevOS AI, with its own progress window)
# ---------------------------------------------------------------------------

def _kdialog(*args) -> int:
    if not shutil.which("kdialog"):
        print(" ".join(args[-1:]), file=sys.stderr)
        return 1
    return subprocess.run(["kdialog", "--title", "DevOS", *args]).returncode


class _Progress:
    def __init__(self, text: str, steps: int):
        self.ref = None
        if shutil.which("kdialog"):
            out = subprocess.run(["kdialog", "--title", "DevOS", "--progressbar", text, str(steps)],
                                 capture_output=True, text=True).stdout.split()
            self.ref = out if len(out) == 2 else None

    def update(self, percent: int, text: str) -> None:
        if self.ref:
            subprocess.run(["qdbus", *self.ref, "Set", "", "value", str(percent)], capture_output=True)
            subprocess.run(["qdbus", *self.ref, "setLabelText", text], capture_output=True)

    def close(self) -> None:
        if self.ref:
            subprocess.run(["qdbus", *self.ref, "close"], capture_output=True)


def _feature_installed(fid: str) -> Optional[bool]:
    try:
        out = subprocess.run([FEATURES_CMD, "status"], capture_output=True, text=True, timeout=30)
        data = json.loads(out.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    installed = data.get("installed")
    if not isinstance(installed, list):
        return None
    return fid in installed


def uninstall_main(name: str, feature: str = "", flatpak: str = "") -> int:
    """Remove a DevOS Features app, or a Flathub app DevOS AI installed."""
    if feature:
        if catalog is not None and _feature(feature) is None:
            _kdialog("--error", f"{name} is not in DevOS Features.")
            return 2
        present = _feature_installed(feature)
        if present is False:
            _kdialog("--msgbox", f"{name} is not installed. Ask DevOS AI to install it, or open DevOS Features.")
            return 0
        busy = _Progress(f"Removing {name}…", 0)
        code = subprocess.run(["pkexec", FEATURES_CMD, "set", "--remove", feature]).returncode
        busy.close()
        if code != 0:
            _kdialog("--error", f"{name} could not be removed.")
            return 1
        if _feature_installed(feature):
            _kdialog("--error", f"{name} is part of the desktop, so it was left in place. "
                     "You can hide it from DevOS Features.")
            return 1
        _kdialog("--passivepopup", f"{name} has been removed. Ask DevOS AI or open DevOS Features to install it again.", "8")
        return 0
    if not _FLATPAK_ID.match(flatpak or ""):
        return 2
    if not native.is_installed(flatpak):
        _kdialog("--msgbox", f"{name} is not installed.")
        return 0
    busy = _Progress(f"Removing {name}…", 0)
    code = subprocess.run(["flatpak", "uninstall", "--user", "-y", "--noninteractive", flatpak]).returncode
    busy.close()
    if code != 0:
        _kdialog("--error", f"{name} could not be removed.")
        return 1
    _kdialog("--passivepopup", f"{name} has been removed.", "6")
    return 0


def install_main(name: str, feature: str = "", flatpak: str = "") -> int:
    if feature:
        if catalog is not None and _feature(feature) is None:
            _kdialog("--error", f"{name} is not in DevOS Features.")
            return 2
        busy = _Progress(f"Installing {name}… This can take a few minutes.", 0)
        code = subprocess.run(["pkexec", FEATURES_CMD, "set", "--add", feature]).returncode
        busy.close()
        if code != 0:
            _kdialog("--error", f"{name} could not be installed. Check the internet connection and try again.")
            return 1
        f = _feature(feature) or {}
        app = (f.get("flatpak") or [""])[0]
        _kdialog("--passivepopup", f"{name} is installed. It is in the app menu.", "6")
        if app:
            native.launch(app)
        return 0
    if not _FLATPAK_ID.match(flatpak or ""):
        return 2
    if native.is_installed(flatpak):
        native.launch(flatpak)
        return 0
    busy = _Progress(f"Installing {name}…", 100)
    res = native.install(flatpak, progress=busy.update)
    busy.close()
    if res.get("status") != "INSTALLED":
        _kdialog("--error", f"{name} could not be installed.\n\n{res.get('error', '')}")
        return 1
    _kdialog("--passivepopup", f"{name} is installed. It is in the app menu.", "6")
    native.launch(flatpak)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description="Find or install the DevOS version of an app")
    p.add_argument("query", nargs="*", help="app name or store link")
    p.add_argument("--install", action="store_true")
    p.add_argument("--uninstall", action="store_true")
    p.add_argument("--name", default="")
    p.add_argument("--feature", default="")
    p.add_argument("--flatpak", default="")
    ns = p.parse_args(argv)
    if ns.uninstall:
        return uninstall_main(ns.name or ns.feature or ns.flatpak, ns.feature, ns.flatpak)
    if ns.install:
        return install_main(ns.name or ns.feature or ns.flatpak, ns.feature, ns.flatpak)
    text = " ".join(ns.query)
    link = find_link(text)
    res = resolve(query="" if link else text, link=link or "")
    print(reply_text(res))
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
