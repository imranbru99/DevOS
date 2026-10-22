#!/usr/bin/env python3
"""
DevOS AI - intent router and whitelisted tools.

The on-device language model is small. It answers questions well, but it
cannot be trusted to emit reliable tool calls. So every request goes through
this deterministic router FIRST:

    route(text)      -> RouteResult(actions=[Action, ...])
    execute(action)  -> ToolResult(text=markdown, plan=[argv, ...], ...)

Only the actions defined here can run, with validated arguments. Nothing the
model writes is ever executed. Actions that change the system (shutdown,
restart, sleep, uninstall) carry a `confirm` question; the window asks the
user before calling execute().

Every tool takes a ToolContext so tests can point it at fake /proc files,
fake desktop entries and a fake launcher. With dry_run=True nothing is
launched; the planned command lines are returned in ToolResult.plan.

This module is stdlib only and imports without a display.
"""

import datetime
import difflib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import signal
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
COMPONENTS = os.path.dirname(HERE)
APPS_MANAGER_PY = os.path.join(COMPONENTS, "apps", "apps_manager.py")
OPTIMIZER_PY = os.path.join(COMPONENTS, "optimizer", "optimizer.py")
SECURITY_PY = os.path.join(COMPONENTS, "security", "security_center.py")
CLIPBOARD_PY = os.path.join(COMPONENTS, "clipboard", "clipboard.py")
EMOJI_PY = os.path.join(COMPONENTS, "emoji", "emoji.py")
BROADBAND_PY = os.path.join(COMPONENTS, "broadband", "broadband.py")
KIDS_MODE_PY = os.path.join(COMPONENTS, "kids", "kids_mode.py")
NOTEPAD_PY = os.path.join(COMPONENTS, "notepad", "notepad.py")
APP_RESOLVER_PY = os.path.join(COMPONENTS, "apphub", "app_resolver.py")
POWER_PY = os.path.join(COMPONENTS, "power", "power_settings.py")
TOOLS_PY = os.path.abspath(__file__)
PYTHON = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else (sys.executable or "python3")

GB = 1024 ** 3


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Action:
    name: str
    args: Dict[str, object] = field(default_factory=dict)
    confirm: str = ""          # non-empty: ask the user this before running
    label: str = ""            # short human description

    def to_json(self) -> dict:
        return {"name": self.name, "args": dict(self.args), "confirm": self.confirm, "label": self.label}


@dataclass
class ToolResult:
    text: str
    ok: bool = True
    plan: List[List[str]] = field(default_factory=list)
    buttons: List[Tuple[str, Action]] = field(default_factory=list)
    data: Dict[str, object] = field(default_factory=dict)


@dataclass
class RouteResult:
    actions: List[Action] = field(default_factory=list)
    leftover: str = ""          # part of the request no tool handled

    @property
    def handled(self) -> bool:
        return bool(self.actions)


def popen_detached(argv: List[str]) -> bool:
    """Start a program without waiting for it and without tying it to us."""
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        return True
    except OSError:
        return False


def run_capture(argv: List[str], timeout: int = 8) -> Tuple[int, str]:
    try:
        p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout, text=True, errors="replace")
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


class ToolContext:
    """Everything a tool touches on the real system, injectable for tests."""

    def __init__(self, root: str = "/", home: Optional[str] = None,
                 which: Callable[[str], Optional[str]] = shutil.which,
                 launcher: Callable[[List[str]], bool] = popen_detached,
                 runner: Callable[..., Tuple[int, str]] = run_capture,
                 app_dirs: Optional[List[str]] = None,
                 discovery_factory: Optional[Callable[[], object]] = None,
                 optimizer_module: Optional[object] = None,
                 now: Optional[Callable[[], datetime.datetime]] = None,
                 sleep: Callable[[float], None] = time.sleep,
                 env: Optional[Dict[str, str]] = None,
                 killer: Callable[[int, int], None] = os.kill,
                 uid: Optional[int] = None,
                 clock: Callable[[], float] = time.monotonic,
                 fetch: Optional[Callable[..., str]] = None):
        self.root = root
        # reads store pages and the Flathub search for "install <app>"
        # (None: the real network, with an 8 s timeout)
        self.fetch = fetch
        self.sleep = sleep
        self.env = dict(os.environ) if env is None else env
        self.killer = killer
        self.uid = uid if uid is not None else (os.getuid() if hasattr(os, "getuid") else 0)
        self.clock = clock
        self.home = os.path.abspath(home or os.path.expanduser("~"))
        self.which = which
        self.launcher = launcher
        self.runner = runner
        if app_dirs is None:
            app_dirs = [
                os.path.join(root, "usr/share/applications"),
                os.path.join(root, "usr/local/share/applications"),
                os.path.join(self.home, ".local/share/applications"),
                os.path.join(self.home, "Desktop"),
            ]
        self.app_dirs = app_dirs
        self._discovery_factory = discovery_factory
        self._optimizer = optimizer_module
        self.now = now or datetime.datetime.now

    def path(self, p: str) -> str:
        return os.path.join(self.root, p.lstrip("/"))

    def discovery(self):
        if self._discovery_factory is not None:
            return self._discovery_factory()
        mod = load_module_by_path("devos_apps_manager", APPS_MANAGER_PY)
        if mod is None:
            return None
        return mod.AppDiscovery(home=self.home)

    def optimizer(self):
        if self._optimizer is not None:
            return self._optimizer
        return load_module_by_path("devos_optimizer", OPTIMIZER_PY)

    def app_resolver(self):
        return load_module_by_path("devos_app_resolver", APP_RESOLVER_PY)


def load_module_by_path(name: str, path: str):
    if name in sys.modules:
        return sys.modules[name]
    if not os.path.isfile(path):
        return None
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:  # a broken sibling component must not break chat
        sys.modules.pop(name, None)
        sys.stderr.write(f"assistant: could not load {path}: {exc}\n")
        return None


def human_size(n: Optional[float]) -> str:
    if n is None:
        return "unknown"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            if unit in ("B", "KB"):
                return f"{n:.0f} {unit}"
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

_POLITE = re.compile(
    r"^(?:please|pls|plz|kindly|hey|hi|hello|ok|okay|yo|devos(?: ai)?|"
    r"can you|could you|would you|will you|can u|could u|"
    r"i want you to|i need you to|i want to|i would like to|i'd like to|"
    r"i wanna|help me(?: to)?|let's|lets|just|now|then|also)\b[\s,:;!.-]*")
_TRAIL = re.compile(r"[\s,]*(?:please|pls|plz|for me|now|right now|thanks|thank you)?[\s?.!,]*$")


def normalize(text: str) -> str:
    t = (text or "").strip().lower()
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"\s+", " ", t)
    # common slips: "go the chrome" -> "go to the chrome"
    t = re.sub(r"\bgo (?=the\b)", "go to ", t)
    t = re.sub(r"\bgoto\b", "go to", t)
    t = re.sub(r"\bwi[\s-]?fi\b", "wifi", t)
    t = re.sub(r"\bgoogle chrome\b", "chrome", t)
    t = re.sub(r"\bscreen shot\b", "screenshot", t)
    prev = None
    while prev != t:
        prev = t
        t = _POLITE.sub("", t).strip()
        t = _TRAIL.sub("", t).strip()
    return t


def _has(pattern: str, text: str) -> bool:
    return re.search(pattern, text) is not None


_CLAUSE_SPLIT = re.compile(r"\s*(?:,?\s*\band then\b|,?\s*\bthen\b|\band also\b|\band\b|;|,)\s*")


def split_clauses(t: str) -> List[str]:
    return [c.strip() for c in _CLAUSE_SPLIT.split(t) if c and c.strip()]


# ---------------------------------------------------------------------------
# Typo tolerance
#
# Only the command part of a request is corrected: the words before the first
# "payload" word (write / type / save / search / about / called / remind ...).
# Whatever follows - names, numbers, notes, search queries - is never touched.
# A word is corrected only to a word of the router's own vocabulary, only when
# it starts with the same letter and is 1 edit away (2 for long words).
# ---------------------------------------------------------------------------

COMMAND_VOCAB = frozenset("""
open close launch start run search google find write type save note notes take make create folder play pause
resume next previous music song songs volume brightness screenshot lock restart reboot shutdown settings
wifi bluetooth display sound printer remind reminder timer minutes minute hours hour seconds email mail send
directions maps wikipedia youtube chrome firefox browser notepad terminal calculator files explorer
downloads documents pictures photos desktop videos editor text code store apps optimizer dashboard camera kate
libreoffice writer konsole uninstall install quit exit increase decrease mute unmute gmail facebook whatsapp
github system manager post tweet share publish linkedin reddit
""".split())
_CORRECTION_TARGETS = COMMAND_VOCAB | {"can", "could", "please", "you"}

# Frequent words that are never "corrected", even when they are one letter
# away from a command word.
PROTECTED_WORDS = frozenset("""
a an the and or but if then than so to of in on at by for from with without into onto about as is are was were be
been am do does did done have has had can could would should will shall may might must not no yes it its this that
these those there here where when what who whom whose why how which all any some many much more most less few
my me mine your you yours our we us his her him she he they them their i im i'm it's don't can't won't let get got
set put see saw say said tell told ask go goes went come came give gave keep kept know new now old one two three
four five six ten up down out off over just also only very really too again still even ever never always
call called calls mom mum dad son sun man men day days week time times year way ways word words work home house
car cat dog cap cup hot hat top tip map max mix fix fun far fan fat fit few fly fry pay pan pen pin pot
name names number numbers phone mobile email address love like nice good best well bad big small long short
hello hi hey thanks thank okay ok sir madam bro please kindly devos file report reset record remove
repeat return reply replay recent read ready real rest pages paste post print look looks app list last left line
link lot lots low son sons song cast case cost clock cloth clear clean copy core corp tab tabs map maps mode
more move movie movies mean meet meeting mess media type types sure show shop stop stay step text texts
installed uninstalled installs installing downloaded downloads opened closed
made mad same safe site size soon sort sent seen seem self fine fire film fill
last late later loss lose lost lone long note open play

""".split())

_PAYLOAD_WORDS = frozenset(("write", "type", "save", "note", "notes", "jot", "play", "search", "find", "look",
                            "about", "called", "named", "titled", "saying", "says", "remind", "reminder",
                            "email", "mail", "message", "subject", "body", "file", "folder"))
_HEAD_END = re.compile(r"\b(?:write|type|save|jot|note(?! ?pad)|notes|play|search|about|called|named|titled|saying|"
                       r"remind|reminder|email|mail)\b|:", re.I)

# Common mishearings of the speech model / slips of the keyboard (head only).
_PHONETIC = [
    (r"\bnote ?pads?\b", "notepad"),
    (r"\byou ?tube\b", "youtube"),
    (r"\bfire ?fox\b", "firefox"),
    (r"\bcalculate (?:her|or)\b", "calculator"),
    (r"\bset things\b", "settings"),
    (r"\bwiki ?pedia\b", "wikipedia"),
    (r"\bg ?mail\b", "gmail"),
    (r"\b(?:crow me|chrom|krome|krom|crom)\b", "chrome"),
    (r"(?:^|(?<=[,;.!] )|(?<=\band )|(?<=\bthen ))(?:upon|opun|o pen|oven|opan)\b", "open"),
    (r"(?:^|(?<=[,;.!] )|(?<=\band )|(?<=\bthen ))(?:clothes|cloth|clothe)\b", "close"),
    (r"(?<=\band )(?:right|rite|wright)\b|(?<=\bthen )(?:right|rite|wright)\b|(?<=, )(?:right|rite|wright)\b",
     "write"),
    (r"\bterminals\b", "terminal"),
]


def _osa_distance(a: str, b: str) -> int:
    """Edit distance with adjacent transpositions ("opne" -> "open" is 1)."""
    la, lb = len(a), len(b)
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


def correct_word(word: str) -> str:
    """Closest command word for a misspelt one, or the word unchanged."""
    w = word.lower()
    if len(w) < 3 or not w.isalpha() or w in _CORRECTION_TARGETS or w in PROTECTED_WORDS:
        return word
    max_d = 1 if len(w) < 8 else 2
    best: List[Tuple[int, int, str]] = []
    for v in _CORRECTION_TARGETS:
        if v[0] != w[0] or abs(len(v) - len(w)) > max_d:
            continue
        dist = _osa_distance(w, v)
        if dist <= max_d:
            best.append((dist, abs(len(v) - len(w)), v))
    if not best:
        return word
    best.sort()
    if len(best) > 1 and best[0][:2] == best[1][:2]:
        return word          # two equally good, unrelated guesses: leave it
    return best[0][2]


def correct_command_typos(text: str) -> str:
    """Fix typos and mishearings in the command words of `text`, never in its payload."""
    m = _HEAD_END.search(text)
    end = m.start() if m else len(text)
    head, tail = text[:end], text[end:]
    for pattern, rep in _PHONETIC:
        head = re.sub(pattern, rep, head, flags=re.I)
    stopped = [False]

    def fix(mo):
        if stopped[0]:
            return mo.group(0)
        if re.match(r"[.@_/\\-]\w", head[mo.end():mo.end() + 2]) or (mo.start() > 0 and head[mo.start() - 1] in ".@_/\\-"):
            return mo.group(0)        # part of a file name, address or path: leave it
        c = correct_word(mo.group(0))
        if c.lower() in _PAYLOAD_WORDS:
            stopped[0] = True
        return c
    head = re.sub(r"[A-Za-z]+", fix, head)
    return head + tail


def preprocess(text: str) -> str:
    """Case-preserving clean-up: quotes, spaces, command-word typos."""
    t = (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"[ \t\f\v]+", " ", t).strip()
    t = re.sub(r"\s*\n\s*", "\n", t)
    return correct_command_typos(t)


# ---------------------------------------------------------------------------
# Web search / URLs
# ---------------------------------------------------------------------------

KNOWN_SITES = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "google maps": "https://maps.google.com",
    "maps": "https://maps.google.com",
    "google drive": "https://drive.google.com",
    "facebook": "https://www.facebook.com",
    "messenger": "https://www.messenger.com",
    "whatsapp": "https://web.whatsapp.com",
    "whatsapp web": "https://web.whatsapp.com",
    "github": "https://github.com",
    "wikipedia": "https://www.wikipedia.org",
    "linkedin": "https://www.linkedin.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.com",
    "bing": "https://www.bing.com",
    "stack overflow": "https://stackoverflow.com",
    "stackoverflow": "https://stackoverflow.com",
    "reddit": "https://www.reddit.com",
}

SOCIAL_PLATFORMS = {
    "facebook": ("Facebook", "https://www.facebook.com"),
    "fb": ("Facebook", "https://www.facebook.com"),
    "twitter": ("Twitter", "https://x.com"),
    "x": ("X", "https://x.com"),
    "linkedin": ("LinkedIn", "https://www.linkedin.com"),
    "reddit": ("Reddit", "https://www.reddit.com"),
    "threads": ("Threads", "https://www.threads.net"),
    "instagram": ("Instagram", "https://www.instagram.com"),
}

KNOWN_QUERY_SITES = {
    "imrandevbd": "https://imrandev.bd",
    "imran dev": "https://imrandev.bd",
    "imrandev": "https://imrandev.bd",
    "imran dev bd": "https://imrandev.bd",
    "devos": "https://github.com/imranbru99/DevOS",
    "devos ai": "https://github.com/imranbru99/DevOS",
    "devos linux": "https://github.com/imranbru99/DevOS",
    "devos os": "https://github.com/imranbru99/DevOS",
    "python": "https://www.python.org",
    "github": "https://github.com",
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
}


def resolve_search_result(query: str, rank: int = 1) -> str:
    """Resolve the top N-th website for a search query.
    Uses fast Google I'm Feeling Lucky / DuckDuckGo HTML resolution, with fallback to Lucky redirect."""
    q = (query or "").strip().lower()
    if not q:
        return "https://www.google.com"
    if q in KNOWN_QUERY_SITES and rank == 1:
        return KNOWN_QUERY_SITES[q]

    # 1. Try Google I'm Feeling Lucky redirect resolution
    try:
        lucky_url = "https://www.google.com/search?btnI=1&q=" + urllib.parse.quote_plus(query)
        req = urllib.request.Request(lucky_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            final_u = resp.geturl()
            m = re.search(r"url\?q=(https?://[^&]+)", final_u)
            if m:
                u = urllib.parse.unquote(m.group(1)).rstrip("/")
                if u.startswith(("http://", "https://")) and "google.com" not in u:
                    return u
            if final_u.startswith(("http://", "https://")) and "google.com" not in final_u:
                return final_u.rstrip("/")
    except Exception:
        pass

    # 2. Try DuckDuckGo HTML result parsing
    try:
        ddg_url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query)
        req = urllib.request.Request(ddg_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
            urls = re.findall(r"uddg=([^&\"\'\s]+)", html)
            seen = []
            for u in urls:
                dec = urllib.parse.unquote(u)
                if dec.startswith(("http://", "https://")) and "duckduckgo.com" not in dec and dec not in seen:
                    seen.append(dec)
            if len(seen) >= rank:
                return seen[rank - 1].rstrip("/")
    except Exception:
        pass

    # 3. Fallback: browser itself opens Google I'm Feeling Lucky
    return f"https://www.google.com/search?btnI=1&q={urllib.parse.quote_plus(query)}"


_HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}$")
_URLISH = re.compile(r"^(?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,24}(?::\d{1,5})?(?:/\S*)?$")

_RANK_NAV_RE = re.compile(
    r"^(?:(?:open|go to|visit|navigate to|browse|click|click on|load)\s+)?(?:the\s+)?"
    r"(?P<rank>1st|first|top|2nd|second|3rd|third|4th|fourth|5th|fifth)\s+"
    r"(?:website|site|link|result|page)(?:\s+(?:on|in|from)\s+(?:google|search|results?))?$", re.I)

_PAGE_NAV_RE = re.compile(
    r"^(?:(?:open|go to|visit|navigate to|browse|click|click on|load)\s+)?(?:the\s+)?"
    r"(?P<page>contact|about|docs|documentation|pricing|blog|home|download|downloads|features|faq|help|support|team|careers|privacy|terms)"
    r"(?:\s+us)?(?:\s+page|\s+section)?(?:\s+(?:of|on|in)\s+(?:this|the)\s+(?:website|site|page))?$", re.I)


def google_search_url(query: str) -> str:
    return "https://www.google.com/search?q=" + urllib.parse.quote_plus(query.strip())


def youtube_search_url(query: str) -> str:
    return "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query.strip())


def normalize_url(raw: str) -> Optional[str]:
    """Return a safe http(s) URL or None. Only web URLs are accepted."""
    raw = (raw or "").strip().strip("\"'<>")
    if not raw or any(c.isspace() for c in raw):
        return None
    if "://" in raw:
        scheme = raw.split("://", 1)[0].lower()
        if scheme not in ("http", "https"):
            return None
        url = raw
    else:
        url = "https://" + raw
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if not _HOST_RE.match(host) and host not in ("localhost",):
        return None
    return urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, parts.fragment))


_ENGINE_WORDS = r"(?:google|youtube|the web|web|internet|the internet|online|chrome|the browser|browser|firefox)"
_SEARCH_VERB = re.compile(
    r"\b(?:search(?:\s+(?:for|about))?|google|look\s+up|find\s+(?:me\s+)?(?=.+\b(?:on|in|using)\s+" + _ENGINE_WORDS + r"\b))\b")
_LEAD = re.compile(r"^(?:(?:on|in|at|using|with)\s+)?(?:the\s+)?(?:" + _ENGINE_WORDS + r")\s*(?:for|about|and)?\s+|^(?:for|about)\s+")
_TAIL = re.compile(r"\s+(?:on|in|at|using|with|from|via|through)\s+(?:the\s+)?" + _ENGINE_WORDS + r"$|\s+online$")
_BN_SEARCH = re.compile(r"(সার্চ|খুঁজ|খোঁজ)")


def _clean_query(q: str) -> str:
    q = q.strip(" \"'.,?!")
    prev = None
    while prev != q:
        prev = q
        q = _LEAD.sub("", q).strip(" \"'.,?!")
        q = _TAIL.sub("", q).strip(" \"'.,?!")
    return q


def _browser_for(t: str) -> str:
    if _has(r"\bfirefox\b", t):
        return "firefox"
    if _has(r"\bchrome\b|ক্রোম", t):
        return "chrome"
    return "default"


_BROWSER_ONLY_CLAUSE = re.compile(
    r"^(?:(?:open|launch|start|go to|goto|go|visit|switch to|use|in|on|from|using|with|via|the|my|a|new|tab|window|web|"
    r"browser|chrome|firefox|google|youtube|website|site|page|to|and|then)\s*)+$")


_ENGINE_MAP = {"google": "google", "the web": "google", "web": "google", "internet": "google",
               "the internet": "google", "chrome": "google", "browser": "google", "the browser": "google",
               "firefox": "google", "bing": "google", "online": "google",
               "youtube": "youtube", "maps": "maps", "map": "maps", "google maps": "maps",
               "wikipedia": "wikipedia", "wiki": "wikipedia"}
_ENG = r"(?:google maps|google|youtube|maps|map|wikipedia|wiki|the web|web|the internet|internet|chrome|" \
       r"the browser|browser|firefox|bing)"
# A command starts the sentence or follows "and" / "then" / a comma.
_CMD_START = r"(?:^|(?:[,;.]|\band then\b|\bthen\b|\band\b|\balso\b|\bplease\b|\bjust\b|\bnow\b)\s*)"
_SEARCH_RE = re.compile(
    _CMD_START + r"(?P<verb>search|look\s*up|google|find|lookup)\b(?:\s+(?:it|this|that))?"
    r"(?:\s+(?:(?:in|on|using|with|at|from|inside)\s+)?(?:the\s+)?(?P<eng>" + _ENG + r")\b)?"
    r"(?:\s+(?:about|for|regarding|of))?\s*:?\s+(?P<q>\S.*)$")
_PLAY_RE = re.compile(_CMD_START + r"(?:play|watch|put on)\s+(?P<q>\S.*)$")
_DIRECTIONS_RE = re.compile(
    _CMD_START + r"(?:(?:get|show(?: me)?|give me|find)\s+(?:the\s+)?)?(?:directions?|route|the way)\s+"
    r"(?:to|for)\s+(?P<q>\S.*)$|^(?:how (?:do|can) i (?:get|go) to|how to (?:get|go) to|navigate to)\s+(?P<q2>\S.*)$")
_MAPS_RE = re.compile(_CMD_START + r"(?:where is|where's|show(?: me)?|find|locate|search(?: for)?)\s+(?P<q>.+?)\s+"
                      r"(?:on|in)\s+(?:the\s+)?(?:google\s+)?maps?$")
_WIKI_RE = re.compile(_CMD_START + r"(?:(?:who|what)\s+(?:is|was|are|were)\s+(?P<q>.+?)\s+(?:on|in|from|according to)\s+"
                      r"wikipedia$|(?:open\s+|show\s+(?:me\s+)?)?(?:the\s+)?(?:wikipedia|wiki)\s+(?:page\s+|article\s+)?"
                      r"(?:for\s+|about\s+|on\s+|of\s+)?(?P<q2>\S.*))$")
# where a query ends because another command follows it
_QUERY_END = re.compile(
    r"\s+(?:and then|then|after that|and)\s+(?="
    r"(?:open|launch|start|run|go to|goto|visit|navigate to|navigate|browse|click|click on|load|"
    r"close|quit|exit|take a screenshot|take screenshot|screenshot|capture|lock|"
    r"turn|mute|unmute|increase|decrease|volume|brightness|"
    r"search|find|look up|lookup|google|"
    r"write|type|enter|save|jot|note|"
    r"clean|clean up|free up|speed up|"
    r"tell|show|check|what is|what's|how many|list|count|"
    r"restart|reboot|shutdown|shut down|power off|sleep|"
    r"install|uninstall|remove|"
    r"play|pause|resume|next|previous|"
    r"help|about|"
    r"(?:the\s+)?(?:1st|first|top|2nd|second|3rd|third|4th|fifth)\s+(?:website|site|link|result|page)|"
    r"(?:the\s+)?(?:contact|about|docs|documentation|pricing|blog|download|downloads)\s+page"
    r")\b)", re.I)
MEDIA_PLAY_WORDS = re.compile(r"^(?:some |my |the )?(?:music|songs?|audio|playlist|my playlist|something|"
                              r"a song|some songs|my songs|my music)$")
_BN_SEARCH = re.compile(r"(সার্চ|খুঁজ|খোঁজ)")


def maps_search_url(query: str) -> str:
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote_plus(query.strip())


def directions_url(dest: str) -> str:
    return "https://www.google.com/maps/dir/?api=1&destination=" + urllib.parse.quote_plus(dest.strip())


def wikipedia_search_url(query: str) -> str:
    return "https://en.wikipedia.org/w/index.php?search=" + urllib.parse.quote_plus(query.strip())


def _split_query(q: str) -> Tuple[str, str]:
    """'hp laptop and open notepad' -> ('hp laptop', 'open notepad'); other 'and's stay in the query."""
    m = _QUERY_END.search(q)
    if not m:
        return q, ""
    return q[:m.start()], q[m.end():]


def _tail_engine(q: str) -> Tuple[str, str]:
    m = re.search(r"\s+(?:on|in|at|using|with|from|via|through)\s+(?:the\s+)?(" + _ENG + r")$", q)
    if m:
        return q[:m.start()], _ENGINE_MAP.get(m.group(1), "google")
    return q, ""


def parse_web_search(t: str) -> Optional[Tuple[List[str], Action, str]]:
    """Find a search / play / maps / wikipedia request in a normalized sentence.

    Returns (prefix_clauses, action, rest). The query is everything after the
    command words ("search in google about X" -> X), never cut at a later
    "google" or "search". prefix_clauses are the parts before the command that
    are not just "go to chrome / go to google" filler; rest is a following
    command such as "... and open notepad".
    """
    # Bangla: query comes before the verb ("এইচপি ল্যাপটপ গুগলে সার্চ করো")
    if _BN_SEARCH.search(t):
        engine = "youtube" if re.search(r"youtube|ইউটিউব", t) else "google"
        q = re.sub(r"(গুগলে|গুগল|ইউটিউবে|ইউটিউব|ক্রোমে|ক্রোম|সার্চ|খুঁজে|খুঁজ|খোঁজ|করো|করুন|কর|দাও|দেখাও|তো|একটু|প্লিজ|এ)(?=\s|$)", " ", t)
        q = re.sub(r"\b(google|youtube|chrome|in|on)\b", " ", q)
        q = re.sub(r"\s+", " ", q).strip(" ।?.!")
        if q:
            return [], _search_action(engine, q, _browser_for(t)), ""
    found = []      # (start, engine, query)
    pos = 0
    while True:
        m = _SEARCH_RE.search(t, pos)
        if not m:
            break
        q, rest = _split_query(m.group("q"))
        eng = _ENGINE_MAP.get(m.group("eng") or "", "")
        q = q.strip(" \"'.,?!:")
        if eng:
            # the engine was named up front: the rest is the query, word for word
            # ("search youtube for how to search on google")
            tail_eng = ""
            if q and not _BROWSER_ONLY_CLAUSE.match(q):
                found.append((m.start(), eng, q, rest))
                break
        else:
            q, tail_eng = _tail_engine(q)
        engine = eng or tail_eng
        if m.group("verb") == "find" and not engine:
            pos = m.start("verb") + 1      # "find my file" is not a web search
            continue
        q = _clean_query(q)
        if q and not _BROWSER_ONLY_CLAUSE.match(q):
            found.append((m.start(), engine, q, rest))
            break
        pos = m.start("verb") + 1
    m = _PLAY_RE.search(t)
    if m:
        q, rest = _split_query(m.group("q"))
        q2, eng = _tail_engine(q)
        if not MEDIA_PLAY_WORDS.match(q2.strip()) and not re.match(r"^(?:the )?(?:next|previous|last)\b", q2) \
                and (eng in ("", "youtube")):
            q2 = _clean_query(q2)
            if q2:
                found.append((m.start(), "youtube", q2, rest))
    m = _DIRECTIONS_RE.search(t)
    if m:
        dest = (m.group("q") or m.group("q2") or "").strip(" ?.!")
        if dest and not _URLISH.match(dest) and dest not in KNOWN_SITES:
            dest, _e = _tail_engine(dest)
            found.append((m.start(), "directions", dest, ""))
    m = _MAPS_RE.search(t)
    if m:
        found.append((m.start(), "maps", m.group("q").strip(), ""))
    m = _WIKI_RE.search(t)
    if m:
        q = (m.group("q") or m.group("q2") or "").strip(" ?.!")
        if q:
            found.append((m.start(), "wikipedia", q, ""))
    if not found:
        return None
    # the earliest command wins; at the same place the more specific one
    order = {"directions": 0, "maps": 1, "wikipedia": 2, "youtube": 3, "google": 4, "": 5}
    start, engine, q, rest = sorted(found, key=lambda f: (f[0], order.get(f[1], 9)))[0]
    pre = t[:start]
    if not engine:
        engine = "youtube" if _has(r"\byoutube\b", pre) else "google"
    return _prefix_clauses(pre), _search_action(engine, q, _browser_for(t)), rest


def _prefix_clauses(pre: str) -> List[str]:
    out = []
    for c in split_clauses(pre):
        if not c or _BROWSER_ONLY_CLAUSE.match(c):
            continue
        out.append(c)
    return out


_ENGINE_LABEL = {"youtube": "YouTube", "google": "Google", "maps": "Maps", "directions": "Maps",
                 "wikipedia": "Wikipedia"}


def _search_action(engine: str, query: str, browser: str) -> Action:
    url = {"youtube": youtube_search_url, "maps": maps_search_url, "directions": directions_url,
           "wikipedia": wikipedia_search_url}.get(engine, google_search_url)(query)
    where = _ENGINE_LABEL.get(engine, "Google")
    app = {"chrome": "Chrome", "firefox": "Firefox"}.get(browser, "the browser")
    label = f"Directions to “{query}”" if engine == "directions" else f"Search {where} for “{query}” in {app}"
    return Action("web_search", {"engine": engine, "query": query, "url": url, "browser": browser}, label=label)


_PLAT_RE = r"(?:facebook|fb|twitter|x|linkedin|reddit|threads|instagram)"

_SOC_PAT_A = re.compile(
    r"^(?:.*?\b(?:go\s+to|open|visit|launch)\s+)?(?P<plat>" + _PLAT_RE + r")\b.*?"
    r"\b(?:write|create|make|share|put|publish)?\s*(?:a\s+)?(?:post|tweet|status|update)\b"
    r"(?:\s+(?:about|on|saying|of|for|regarding|with))\s+(?P<topic>.+?)"
    r"(?:\s*(?:,|\band\b|\bthen\b)?\s*(?:then\s+)?(?:publish|post|submit|send)(?:\s+it)?)?$",
    re.I
)

_SOC_PAT_B = re.compile(
    r"^(?:(?:please|can you|could you)\s+)?(?:write|create|make|share|publish)?\s*(?:a\s+)?(?:post|status|update)\s+"
    r"(?:on|to|in|at)\s+(?P<plat>" + _PLAT_RE + r")\b"
    r"(?:\s+(?:about|on|saying|of|for|regarding))\s+(?P<topic>.+?)"
    r"(?:\s*(?:,|\band\b|\bthen\b)?\s*(?:then\s+)?(?:publish|post|submit|send)(?:\s+it)?)?$",
    re.I
)

_SOC_PAT_C = re.compile(
    r"^(?:(?:please|can you|could you)\s+)?(?:write\s+a\s+tweet|tweet|post\s+(?:on|to)\s+(?P<plat>" + _PLAT_RE + r"))\s+"
    r"(?:about|on|saying|regarding)\s+(?P<topic>.+?)"
    r"(?:\s*(?:,|\band\b|\bthen\b)?\s*(?:then\s+)?(?:publish|post|submit|send)(?:\s+it)?)?$",
    re.I
)

_SOC_PAT_D = re.compile(
    r"^(?:(?:please|can you|could you)\s+)?(?:write|create|make|share|publish)?\s*(?:a\s+)?(?:post|status|update)\s+"
    r"(?:about|on|saying|regarding)\s+(?P<topic>.+?)\s+(?:on|to|in|at)\s+(?P<plat>" + _PLAT_RE + r")"
    r"(?:\s*(?:,|\band\b|\bthen\b)?\s*(?:then\s+)?(?:publish|post|submit|send)(?:\s+it)?)?$",
    re.I
)


def parse_social_post(text: str) -> Optional[Action]:
    t = (text or "").strip()
    m = _SOC_PAT_B.match(t) or _SOC_PAT_C.match(t) or _SOC_PAT_D.match(t) or _SOC_PAT_A.match(t)
    if not m:
        return None
    plat_key = (m.group("plat") if "plat" in m.groupdict() and m.group("plat") else "twitter").lower()
    topic = m.group("topic").strip().strip("\",'\".")
    topic = re.sub(r"\s*(?:,|\band\b|\bthen\b)?\s*(?:then\s+)?(?:publish|post|submit|send)(?:\s+it)?$", "", topic, flags=re.I).strip()
    if not topic:
        return None
    browser = _browser_for(t)
    plat_info = SOCIAL_PLATFORMS.get(plat_key, (plat_key.title(), "https://" + plat_key + ".com"))
    return Action("social_post", {
        "platform": plat_key,
        "topic": topic,
        "browser": browser,
        "url": plat_info[1],
        "publish": bool(re.search(r"\b(?:publish|submit|send)\b", t, re.I)),
    }, label=f"Draft post for {plat_info[0]}")



def browser_command(browser: str, url: str, which: Callable) -> List[str]:
    if browser == "firefox":
        cands = ["firefox", "devos-browser", "google-chrome-stable", "google-chrome", "xdg-open"]
    elif browser == "chrome":
        cands = ["google-chrome-stable", "google-chrome", "devos-browser", "chromium", "xdg-open"]
    else:
        cands = ["devos-browser", "google-chrome-stable", "google-chrome", "firefox", "xdg-open"]
    for c in cands:
        if which(c):
            return [c, url]
    return ["xdg-open", url]


# ---------------------------------------------------------------------------
# Desktop entries / apps
# ---------------------------------------------------------------------------


def parse_desktop_text(text: str) -> Dict[str, str]:
    entry: Dict[str, str] = {}
    in_group = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_group = line == "[Desktop Entry]"
            continue
        if not in_group or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if "[" in key:
            continue
        entry.setdefault(key, value.strip())
    return entry


@dataclass
class DesktopApp:
    desktop_id: str        # e.g. "devos-browser" (no .desktop)
    path: str
    name: str
    generic: str = ""
    keywords: List[str] = field(default_factory=list)
    exec: str = ""
    hidden: bool = False
    wmclass: str = ""


def scan_desktop_entries(dirs: List[str]) -> Dict[str, DesktopApp]:
    """{desktop_id: DesktopApp}; later dirs override earlier ones (XDG order)."""
    found: Dict[str, DesktopApp] = {}
    for base in dirs:
        if not os.path.isdir(base):
            continue
        is_desktop_dir = os.path.basename(base.rstrip("/")) == "Desktop"
        for root, _dirs, files in os.walk(base):
            if is_desktop_dir and root != base:
                continue
            for fn in sorted(files):
                if not fn.endswith(".desktop"):
                    continue
                path = os.path.join(root, fn)
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        e = parse_desktop_text(fh.read())
                except OSError:
                    continue
                if e.get("Type", "Application") != "Application" or not e.get("Name"):
                    continue
                did = os.path.relpath(path, base).replace(os.sep, "-")[:-8]
                if is_desktop_dir and did in found:
                    continue  # the menu entry wins over a desktop shortcut copy
                found[did] = DesktopApp(
                    desktop_id=did, path=path, name=e.get("Name", ""), generic=e.get("GenericName", ""),
                    keywords=[k.strip().lower() for k in e.get("Keywords", "").split(";") if k.strip()],
                    exec=e.get("Exec", ""),
                    hidden=e.get("NoDisplay", "").lower() == "true" or e.get("Hidden", "").lower() == "true",
                    wmclass=e.get("StartupWMClass", ""),
                )
    return found


# DevOS names -> desktop ids, in preference order.
APP_ALIASES = {
    "chrome": ["devos-browser", "google-chrome", "com.google.Chrome"],
    "browser": ["devos-browser", "google-chrome", "firefox", "org.kde.falkon"],
    "web browser": ["devos-browser", "google-chrome", "firefox"],
    "internet": ["devos-browser", "google-chrome"],
    "firefox": ["firefox", "org.mozilla.firefox", "firefox_firefox"],
    "files": ["devos-thispc", "org.kde.dolphin"],
    "file manager": ["devos-thispc", "org.kde.dolphin"],
    "file explorer": ["devos-thispc", "org.kde.dolphin"],
    "explorer": ["devos-thispc", "org.kde.dolphin"],
    "this pc": ["devos-thispc", "org.kde.dolphin"],
    "my computer": ["devos-thispc", "org.kde.dolphin"],
    "terminal": ["org.kde.konsole", "konsole"],
    "console": ["org.kde.konsole", "konsole"],
    "command prompt": ["org.kde.konsole"],
    "cmd": ["org.kde.konsole"],
    "settings": ["devos-settings", "systemsettings", "org.kde.systemsettings"],
    "control panel": ["devos-settings", "systemsettings"],
    "system settings": ["devos-settings", "systemsettings"],
    "notepad": ["devos-notepad"],
    "text editor": ["devos-notepad", "org.kde.kate", "org.kde.kwrite"],
    "notes": ["devos-notepad"],
    "code": ["devos-code", "codium", "code"],
    "vs code": ["devos-code", "codium", "code"],
    "vscode": ["devos-code", "codium", "code"],
    "code editor": ["devos-code", "codium"],
    "app store": ["devos-apphub"],
    "store": ["devos-apphub"],
    "app hub": ["devos-apphub"],
    "apps": ["devos-apps"],
    "app manager": ["devos-apps"],
    "apps manager": ["devos-apps"],
    "installed apps": ["devos-apps"],
    "optimizer": ["devos-optimizer"],
    "devos optimizer": ["devos-optimizer"],
    "task manager": ["devos-taskman", "org.kde.plasma-systemmonitor", "org.kde.ksysguard"],
    "taskmgr": ["devos-taskman"],
    "system monitor": ["devos-taskman", "org.kde.plasma-systemmonitor", "org.kde.ksysguard"],
    "calculator": ["org.kde.kcalc", "kcalc", "org.gnome.Calculator"],
    "dashboard": ["devos-dashboard"],
    "windows apps": ["devos-winlayer", "devos-windows"],
    "disk": ["devos-disk"],
    "disks": ["devos-disk"],
    "screenshot tool": ["org.kde.spectacle"],
    "camera": ["org.kde.kamoso", "cheese"],
    "chat": ["devos-chat"],
}


def _norm_name(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9ঀ-৿ ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_app(query: str, apps: Dict[str, DesktopApp]) -> Tuple[Optional[DesktopApp], List[str]]:
    """Fuzzy-match a spoken/typed app name. Returns (best, close_names)."""
    q = _norm_name(query)
    q = re.sub(r"\b(?:the|my|app|application|program|software|window)\b", " ", q)
    q = re.sub(r"\s+", " ", q).strip()
    if not q:
        return None, []
    for did in APP_ALIASES.get(q, []):
        if did in apps:
            return apps[did], []
    scored: List[Tuple[float, DesktopApp]] = []
    for app in apps.values():
        names = [_norm_name(app.name)]
        if app.generic:
            names.append(_norm_name(app.generic))
        tail = app.desktop_id.split(".")[-1].lower()
        names.append(_norm_name(tail))
        best = 0.0
        for n in names:
            if not n:
                continue
            if n == q:
                s = 1.0
            elif n.startswith(q + " ") or (len(q) >= 3 and n.startswith(q)):
                s = 0.9
            elif len(q) >= 3 and re.search(r"\b" + re.escape(q) + r"\b", n):
                s = 0.85
            else:
                s = difflib.SequenceMatcher(None, q, n).ratio() * 0.9
            best = max(best, s)
        if q in app.keywords:
            best = max(best, 0.8)
        if app.hidden:
            best -= 0.15
        scored.append((best, app))
    scored.sort(key=lambda x: (-x[0], x[1].name.lower()))
    close = [a.name for s, a in scored[:3] if s >= 0.5]
    if scored and scored[0][0] >= 0.72:
        return scored[0][1], []
    return None, close


def launch_command(app: DesktopApp, which: Callable) -> List[str]:
    if which("gtk-launch") and not app.path.startswith(os.path.expanduser("~/Desktop")):
        return ["gtk-launch", app.desktop_id]
    if which("kioclient5"):
        return ["kioclient5", "exec", app.path]
    if which("kioclient"):
        return ["kioclient", "exec", app.path]
    argv = exec_to_argv(app.exec)
    if argv and which(argv[0]):
        return argv
    return ["xdg-open", app.path]


def exec_to_argv(exec_line: str) -> List[str]:
    try:
        parts = shlex.split(exec_line or "")
    except ValueError:
        parts = (exec_line or "").split()
    return [p for p in parts if not re.fullmatch(r"%[a-zA-Z]", p)]


# ---------------------------------------------------------------------------
# System info
# ---------------------------------------------------------------------------


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def parse_cpuinfo(text: str) -> Dict[str, object]:
    model = ""
    physical = set()
    cores_per = {}
    logical = 0
    phys_id = "0"
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k == "processor":
            logical += 1
        elif k in ("model name", "Model", "Hardware") and not model:
            model = v
        elif k == "physical id":
            phys_id = v
            physical.add(v)
        elif k == "cpu cores":
            try:
                cores_per[phys_id] = int(v)
            except ValueError:
                pass
    cores = sum(cores_per.values()) if cores_per else logical
    model = re.sub(r"\s+", " ", model).replace("(R)", "®").replace("(TM)", "™")
    return {"model": model or "Unknown processor", "cores": cores, "threads": logical,
            "sockets": max(1, len(physical))}


def parse_meminfo(text: str) -> Dict[str, int]:
    info = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                info[parts[0].rstrip(":")] = int(parts[1]) * 1024
            except ValueError:
                pass
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    return {"total": total, "available": avail, "used": max(0, total - avail),
            "swap_total": info.get("SwapTotal", 0), "swap_free": info.get("SwapFree", 0)}


def parse_os_release(text: str) -> Dict[str, str]:
    out = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"')
    return out


def os_display_name(osr: Dict[str, str]) -> str:
    """DevOS never shows the distribution it is built from."""
    name = osr.get("PRETTY_NAME") or osr.get("NAME") or "DevOS"
    if "devos" not in name.lower():
        version = osr.get("DEVOS_VERSION") or ""
        name = ("DevOS " + version).strip()
    return name


def parse_lspci_gpus(text: str) -> List[str]:
    gpus = []
    for line in text.splitlines():
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) < 4:
            continue
        cls = parts[1]
        if not re.search(r"VGA|3D|Display", cls):
            continue
        vendor = re.sub(r"\s*(Corporation|Corp\.|Inc\.|Co\., Ltd\.|\[AMD/ATI\])", "", parts[2]).strip()
        vendor = re.sub(r"Advanced Micro Devices, Inc\.?", "AMD", vendor).strip()
        device = parts[3]
        m = re.search(r"\[([^\]]+)\]", device)
        if m:
            device = m.group(1)
        gpus.append(f"{vendor} {device}".strip())
    return gpus


def parse_lsblk(text: str) -> List[Dict[str, object]]:
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    out = []
    for dev in data.get("blockdevices", []) or []:
        if dev.get("type") != "disk":
            continue
        name = dev.get("name", "")
        if name.startswith(("loop", "zram", "sr", "ram")):
            continue
        size = dev.get("size")
        try:
            size = int(size)
        except (TypeError, ValueError):
            pass
        rota = dev.get("rota")
        kind = "HDD" if rota in (True, "1", 1) else "SSD"
        if str(name).startswith("nvme"):
            kind = "NVMe SSD"
        out.append({"name": name, "size": size, "model": (dev.get("model") or "").strip(), "kind": kind})
    return out


def parse_uptime(text: str) -> Optional[float]:
    try:
        return float(text.split()[0])
    except (IndexError, ValueError):
        return None


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = []
    if d:
        parts.append(f"{d} day" + ("s" if d != 1 else ""))
    if h:
        parts.append(f"{h} hour" + ("s" if h != 1 else ""))
    if not d and (m or not parts):
        parts.append(f"{m} minute" + ("s" if m != 1 else ""))
    return ", ".join(parts)


def read_batteries(ctx: ToolContext) -> List[Dict[str, object]]:
    base = ctx.path("/sys/class/power_supply")
    out = []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for n in names:
        d = os.path.join(base, n)
        if read_text(os.path.join(d, "type")).strip() != "Battery":
            continue
        cap = read_text(os.path.join(d, "capacity")).strip()
        status = read_text(os.path.join(d, "status")).strip()
        try:
            cap_i = int(cap)
        except ValueError:
            cap_i = None
        out.append({"name": n, "capacity": cap_i, "status": status or "Unknown"})
    return out


SYSINFO_TOPICS = ("cpu", "ram", "disk", "gpu", "os", "uptime", "battery")


def gather_system_info(ctx: ToolContext) -> Dict[str, object]:
    info: Dict[str, object] = {}
    info["cpu"] = parse_cpuinfo(read_text(ctx.path("/proc/cpuinfo")))
    info["ram"] = parse_meminfo(read_text(ctx.path("/proc/meminfo")))
    osr = parse_os_release(read_text(ctx.path("/etc/os-release")))
    info["os"] = {"name": os_display_name(osr), "kernel": read_text(ctx.path("/proc/sys/kernel/osrelease")).strip()}
    info["uptime"] = parse_uptime(read_text(ctx.path("/proc/uptime")))
    info["battery"] = read_batteries(ctx)
    disks = []
    seen = set()
    for p in (ctx.path("/"), ctx.home):
        try:
            st = os.stat(p)
            if st.st_dev in seen:
                continue
            seen.add(st.st_dev)
            du = shutil.disk_usage(p)
            disks.append({"path": "/" if p == ctx.path("/") else "~", "total": du.total,
                          "used": du.used, "free": du.free})
        except OSError:
            continue
    info["volumes"] = disks
    info["drives"] = []
    if ctx.which("lsblk"):
        rc, out = ctx.runner(["lsblk", "-J", "-b", "-d", "-o", "NAME,SIZE,MODEL,ROTA,TYPE"])
        if rc == 0:
            info["drives"] = parse_lsblk(out)
    info["gpu"] = []
    if ctx.which("lspci"):
        rc, out = ctx.runner(["lspci", "-mm"])
        if rc == 0:
            info["gpu"] = parse_lspci_gpus(out)
    return info


def format_system_info(info: Dict[str, object], topics: List[str]) -> str:
    topics = topics or list(SYSINFO_TOPICS)
    full = set(topics) >= {"cpu", "ram", "disk"}
    lines = ["**This PC**" if full else "**Here's what I found:**"]
    cpu = info.get("cpu") or {}
    ram = info.get("ram") or {}
    if "os" in topics:
        os_i = info.get("os") or {}
        lines.append(f"- **System:** {os_i.get('name', 'DevOS')}")
    if "cpu" in topics:
        threads = cpu.get("threads") or 0
        cores = cpu.get("cores") or threads
        extra = f"{cores} cores" + (f", {threads} threads" if threads and threads != cores else "")
        lines.append(f"- **Processor:** {cpu.get('model', 'Unknown')} ({extra})")
    if "ram" in topics:
        total = ram.get("total") or 0
        used = ram.get("used") or 0
        pct = f" ({used * 100 // total}%)" if total else ""
        lines.append(f"- **Memory (RAM):** {human_size(total)} total, {human_size(used)} in use{pct}, "
                     f"{human_size(ram.get('available'))} free")
    if "gpu" in topics:
        gpus = info.get("gpu") or []
        lines.append("- **Graphics:** " + (", ".join(gpus) if gpus else "not detected"))
    if "disk" in topics:
        drives = info.get("drives") or []
        for d in drives:
            model = f" {d['model']}" if d.get("model") else ""
            size = human_size(d["size"]) if isinstance(d.get("size"), int) else str(d.get("size"))
            lines.append(f"- **Drive:** {size} {d['kind']}{model}")
        for v in info.get("volumes") or []:
            where = "System disk" if v["path"] == "/" else "Home folder"
            pct = v["used"] * 100 // v["total"] if v["total"] else 0
            lines.append(f"- **{where}:** {human_size(v['free'])} free of {human_size(v['total'])} ({pct}% used)")
    if "battery" in topics:
        bats = info.get("battery") or []
        if bats:
            for b in bats:
                cap = f"{b['capacity']}%" if b.get("capacity") is not None else "unknown"
                lines.append(f"- **Battery:** {cap}, {str(b.get('status', '')).lower()}")
        elif not full:
            lines.append("- **Battery:** no battery found (this looks like a desktop PC)")
    if "uptime" in topics and info.get("uptime") is not None:
        lines.append(f"- **Running for:** {format_duration(info['uptime'])}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Settings, folders, small system actions
# ---------------------------------------------------------------------------

SETTINGS_PAGES = [
    (r"\b(?:wifi|network|internet|ethernet|hotspot|vpn)\b|ওয়াইফাই|নেটওয়ার্ক", "kcm_networkmanagement", "Wi-Fi & network"),
    (r"\bbluetooth\b|ব্লুটুথ", "kcm_bluetooth", "Bluetooth"),
    (r"\b(?:power|battery|energy|sleep|screen timeout|sleep time|power on|power off|power settings|turn off screen)\b|বিদ্যুৎ|স্লিপ|পাওয়ার", "devos-power", "Power & sleep"),
    (r"\b(?:display|screen resolution|resolution|monitors?|screen settings|night ?light)\b", "kcm_kscreen", "Display"),
    (r"\b(?:sound|audio|speakers?|headphones?|microphone|mic)\b", "kcm_pulseaudio", "Sound"),
    (r"\bprinters?\b|\bprinting\b|প্রিন্টার", "kcm_printer_manager", "Printers"),
    (r"\b(?:keyboard|language|input method)\b", "kcm_keyboard", "Keyboard"),
    (r"\b(?:mouse)\b", "kcm_mouse", "Mouse"),
    (r"\b(?:touchpad|trackpad)\b", "kcm_touchpad", "Touchpad"),
    (r"\b(?:date|time|clock|timezone|time zone)\b", "kcm_clock", "Date & time"),
    (r"\b(?:users?|accounts?|password)\b", "kcm_users", "Users"),
    (r"\b(?:theme|appearance|dark mode|light mode)\b", "kcm_lookandfeel", "Appearance"),
    (r"\b(?:wallpaper|background)\b", "kcm_wallpaper", "Wallpaper"),
]


def settings_command(kcm: str, which: Callable) -> List[str]:
    if kcm == "devos-power":
        if which("devos-power"):
            return ["devos-power"]
        return [PYTHON, POWER_PY]
    for exe in ("systemsettings5", "systemsettings"):
        if which(exe):
            return [exe, kcm] if kcm else [exe]
    if kcm and which("kcmshell5"):
        return ["kcmshell5", kcm]
    return ["systemsettings5", kcm] if kcm else ["systemsettings5"]


FOLDERS = {
    "downloads": ("DOWNLOAD", "Downloads"), "download": ("DOWNLOAD", "Downloads"),
    "documents": ("DOCUMENTS", "Documents"), "document": ("DOCUMENTS", "Documents"),
    "pictures": ("PICTURES", "Pictures"), "photos": ("PICTURES", "Pictures"), "images": ("PICTURES", "Pictures"),
    "music": ("MUSIC", "Music"), "songs": ("MUSIC", "Music"),
    "videos": ("VIDEOS", "Videos"), "movies": ("VIDEOS", "Videos"),
    "desktop": ("DESKTOP", "Desktop"),
    "home": ("", ""),
    "screenshots": ("PICTURES", "Pictures/Screenshots"),
}


def user_dir(ctx: ToolContext, key: str, default_rel: str) -> str:
    if not key:
        return ctx.home
    text = read_text(os.path.join(ctx.home, ".config/user-dirs.dirs"))
    m = re.search(r"^XDG_%s_DIR=\"([^\"]+)\"" % key, text, re.M)
    if m and default_rel and "/" not in default_rel:
        return m.group(1).replace("$HOME", ctx.home)
    return os.path.join(ctx.home, default_rel)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

HELP_TEXT = (
    "I'm **DevOS AI**. I run on this PC, so what you type or say stays here. Things I can do:\n"
    "- **Your PC:** “what is my PC config”, “how much RAM”, “disk space”, “battery”\n"
    "- **Apps:** “how many apps are installed”, “list my Windows apps”, “open Notepad”, "
    "“install Zoom”, “uninstall Spotify” (I ask before I install or remove anything)\n"
    "- **Web:** “go to Chrome and search HP latest laptop”, “play lo-fi on YouTube”, “directions to the airport”\n"
    "- **Notes & typing:** “open Notepad and write: buy milk”, “take a note: call the bank”, “type hello here”\n"
    "- **Reminders:** “remind me in 10 minutes to call mom”, “set a timer for 5 minutes”\n"
    "- **More:** “send an email to name@example.com about the meeting”, “make a folder called Projects”, "
    "“open the file report.pdf”, “close Chrome”, “play music”, “next song”\n"
    "- **Settings:** “open Wi-Fi settings”, “Bluetooth”, “display”, “printers”\n"
    "- **Quick actions:** volume up/down/mute, brightness, take a screenshot, lock the screen, open Downloads\n"
    "- **Everyday:** “open clipboard” (Win+V), “open emoji” (Win+.), “start kids mode” (Win+K)\n"
    "- **Clean up:** “free up space” shows what can be cleaned (nothing is deleted without you)\n"
    "- **Problems:** “help me, wifi is not working”, “is my PC safe”, “scan for viruses”, "
    "“is this link safe” plus the address — I check this PC and do the safe next step\n"
    "- **Files:** attach a PDF, text file or image, then ask “summarize this” or “read the text in this image”\n"
    "- **Voice:** press the microphone, speak, and I'll do it\n"
    "Anything else, just ask."
)

_CUE = r"\b(?:my|mine|i have|do i|i got|this (?:pc|computer|laptop|machine|device|system)|how much|how many|which|show|check|tell me|status|free|used|left|total|installed|available|remaining|current)\b|আমার|কত"


def _sysinfo_topics(t: str) -> Optional[List[str]]:
    full = (_has(r"\b(?:pc|computer|laptop|system|machine|hardware|device)\s*(?:config|configuration|specs?|specifications?|info|information|details|summary|overview)\b", t)
            or _has(r"\bspecs?\b|\bspecifications\b|\bsystem info\b|\babout (?:this|my) (?:pc|computer|laptop)\b|\bconfig(?:uration)?\b|কনফিগ", t))
    if full:
        return list(SYSINFO_TOPICS)
    topics = []
    if _has(r"\b(?:ram|memory)\b|র‍্যাম|র্যাম|মেমরি", t):
        topics.append("ram")
    if _has(r"\b(?:cpu|processor|cores?|chip)\b|প্রসেসর", t):
        topics.append("cpu")
    if _has(r"\b(?:disk|storage|ssd|hdd|nvme|hard ?drive|hard ?disk|drive space|space)\b|স্টোরেজ", t):
        topics.append("disk")
    if _has(r"\b(?:gpu|graphics|video card|graphic card)\b", t):
        topics.append("gpu")
    if _has(r"\bbattery\b|ব্যাটারি", t):
        topics.append("battery")
    if _has(r"\b(?:operating system|os version|which os|what os|devos version|version of devos)\b", t):
        topics.append("os")
    if _has(r"\buptime\b|\bhow long\b.*\b(?:on|running|up)\b", t):
        topics.append("uptime")
    if not topics:
        return None
    if topics == ["os"] or topics == ["uptime"] or _has(_CUE, t):
        return topics
    return None


def _volume_action(t: str) -> Optional[Action]:
    if not _has(r"\b(?:volume|sound|louder|quieter|mute|unmute|audio)\b|ভলিউম|সাউন্ড", t):
        return None
    if _has(r"\bsettings?\b", t):
        return None
    m = re.search(r"\b(?:to|at)\s+(\d{1,3})\s*%?", t)
    if m and _has(r"\bvolume\b", t):
        level = max(0, min(150, int(m.group(1))))
        return Action("volume", {"op": "set", "level": level}, label=f"Set volume to {level}%")
    if _has(r"\bunmute\b", t):
        return Action("volume", {"op": "unmute"}, label="Unmute sound")
    if _has(r"\bmute\b", t):
        return Action("volume", {"op": "mute"}, label="Mute sound")
    if _has(r"\b(?:up|increase|raise|louder|higher|turn up|max|boost)\b|বাড়া", t):
        return Action("volume", {"op": "up"}, label="Turn the volume up")
    if _has(r"\b(?:down|decrease|lower|quieter|reduce|turn down)\b|কমা", t):
        return Action("volume", {"op": "down"}, label="Turn the volume down")
    return None


def _brightness_action(t: str) -> Optional[Action]:
    if not _has(r"\b(?:brightness|brighter|dimmer|dim)\b|ব্রাইটনেস", t):
        return None
    m = re.search(r"\b(?:to|at)\s+(\d{1,3})\s*%?", t)
    if m:
        level = max(1, min(100, int(m.group(1))))
        return Action("brightness", {"op": "set", "level": level}, label=f"Set brightness to {level}%")
    if _has(r"\b(?:down|decrease|lower|reduce|dim|dimmer)\b|কমা", t):
        return Action("brightness", {"op": "down"}, label="Lower the brightness")
    return Action("brightness", {"op": "up"}, label="Raise the brightness")


_OPEN_VERB = r"(?:open|launch|start|run|go to|switch to|show(?: me)?|bring up|fire up|load)"
_CLOSE_RE = re.compile(r"^(?:close|quit|exit|kill|terminate)\s+(?:the\s+|my\s+|all\s+)?(?P<name>.+?)"
                       r"(?:\s+(?:app|application|program|windows?|process))?$")


def _media_action(t: str) -> Optional[Action]:
    if _has(r"^(?:play|start|put on|open)\s+(?:some\s+|my\s+|the\s+)?(?:music|songs?|playlist|audio)(?:\s+for me)?$", t):
        return Action("media", {"op": "music"}, label="Play your music")
    if _has(r"^(?:pause|stop)(?:\s+(?:the\s+)?(?:music|song|songs|video|playback|player|media|audio))?$", t):
        return Action("media", {"op": "pause"}, label="Pause playback")
    if _has(r"^(?:resume|continue|unpause|play)(?:\s+(?:the\s+)?(?:music|song|video|playback|media))?$", t):
        return Action("media", {"op": "play"}, label="Resume playback")
    if _has(r"^(?:next|skip)(?:\s+(?:this\s+)?(?:song|track|video))?$|^(?:play\s+)?(?:the\s+)?next\s+(?:song|track|video)$", t):
        return Action("media", {"op": "next"}, label="Next track")
    if _has(r"^(?:previous|prev|last)\s+(?:song|track|video)$|^(?:play\s+)?(?:the\s+)?(?:previous|last)\s+(?:song|track|video)$"
            r"|^go back a (?:song|track)$", t):
        return Action("media", {"op": "previous"}, label="Previous track")
    return None


def _islamic_action(c: str, context: Optional[List[str]] = None) -> Optional[Action]:
    t = c.strip().lower()
    if t in ("tell me bangla", "tell me bangla this", "in bangla", "bangla", "bangla please",
             "বাংলা", "বাংলায় বলো", "বাংলা অনুবাদ", "translate to bangla", "show bangla"):
        if any(re.search(r"\b(?:islamic|ayah|hadith|quran|surah)\b|(?:আয়াত|হাদিস|ইসলামিক)", m.lower()) for m in (context or [])):
            return Action("islamic", {"topic": "all"}, label="Today's Islamic")

    patterns = [
        r"\b(?:today(?:['’]s)?\s+)?islamic(?:\s+(?:ayah|hadith|quote|reminder|prayer))?\b",
        r"\b(?:today(?:['’]s)?\s+)?(?:daily\s+)?(?:ayah|hadith|surah)\b",
        r"\b(?:show|tell|read|give)\s+(?:me\s+)?(?:today(?:['’]s)?\s+)?(?:islamic\s+)?(?:ayah|hadith)\b",
        r"\b(?:quran|hadith|ayah)\s+of\s+the\s+day\b",
        r"\b(?:prayer\s+times?|namaz\s+times?|salat\s+times?)\b",
        r"(?:আজকের\s+)?(?:ইসলামিক|আয়াত|হাদিস|নামাজের\s*সময়|কুরআনের\s*আয়াত)",
    ]
    if any(re.search(p, t) for p in patterns):
        topic = "all"
        if re.search(r"\b(?:prayer|namaz|salat)\b|নামাজ", t):
            topic = "prayer"
        elif re.search(r"\b(?:hadith|হাদিস)\b", t) and not re.search(r"\b(?:ayah|quran|আয়াত)\b", t):
            topic = "hadith"
        elif re.search(r"\b(?:ayah|quran|আয়াত)\b", t) and not re.search(r"\b(?:hadith|হাদিস)\b", t):
            topic = "ayah"
        return Action("islamic", {"topic": topic, "query": c}, label="Today's Islamic")
    return None


def route_clause(c: str, ctx: Optional[ToolContext] = None, context: Optional[List[str]] = None) -> Optional[List[Action]]:
    if not c:
        return None
    if _has(r"^(?:help|\?|what can you do|what can u do|how (?:do i|to) use (?:you|this)|commands|what are your (?:features|commands))$", c) \
            or _has(r"^what (?:can|do) you (?:do|help with)", c):
        return [Action("help", label="Show what I can do")]

    # Who made DevOS / DevOS AI: a fixed answer, the small model rambled.
    # ("devos" itself is stripped by normalize(), so "devos team whose?" arrives
    # as "team ... whose".) Plain "open github.com/..." stays a website.
    if not _has(r"^(?:open|go to|visit|launch)\b", c) and _has(
            r"\b(?:who|whom|whose)\b.*\b(?:made|built|build|created|create|develop(?:ed)?|owns?|behind|team)\b"
            r"|\bteam\b.*\b(?:who|whom|whose)\b"
            r"|\b(?:your|the) (?:creator|developer|maker|founder)s?\b"
            r"|\bsource code\b|\bopen[- ]?source\b|\bportfolio\b"
            # Contact details: the model once invented a LinkedIn URL, so
            # these get the fixed answer too.
            r"|\bcontact (?:info|information|details|number|you|him|imran|the team|the developer|team)\b"
            r"|\breach (?:you|him|imran|the team|the developer)\b"
            r"|\b(?:your|imran'?s?|team'?s?|developer'?s?) (?:linked ?in|github|e-?mail|phone|number|website|whats ?app)\b"
            r"|\b(?:linked ?in|github|e-?mail|phone|number|whats ?app)\b.*\b(?:team|developer|creator|imran)\b"
            r"|\b(?:team|developer|creator|imran)\b.*\b(?:linked ?in|e-?mail|phone|number|whats ?app)\b", c):
        return [Action("about", label="About DevOS")]

    # power (always confirmed)
    if _has(r"\b(?:shut ?down|power off|turn off (?:the |my |this )?(?:pc|computer|laptop|system))\b|বন্ধ কর", c):
        return [Action("power", {"op": "poweroff"}, confirm="Shut down this PC now? Unsaved work will be lost.",
                       label="Shut down the PC")]
    if _has(r"\b(?:restart|reboot)\b(?! (?:the |my )?(?:app|browser|chrome))|রিস্টার্ট", c):
        return [Action("power", {"op": "reboot"}, confirm="Restart this PC now? Unsaved work will be lost.",
                       label="Restart the PC")]
    if _has(r"\b(?:go to sleep|sleep mode|suspend|put (?:the |my |this )?(?:pc|computer|laptop) to sleep)\b|^sleep$", c):
        return [Action("power", {"op": "suspend"}, confirm="Put this PC to sleep now?", label="Sleep")]

    m = re.match(r"^(?P<guide>how\s+(?:to|do i|can i)\s+)?(?:please\s+)?"
                 r"(?:uninstall|uninstal|unistall|unstall|unstal|remove|delete)(?:\s+(?:the|my|this))?"
                 r"(?:\s+(?:app|program|application|software))?\s+(.+)$", c)
    if m:
        name = re.sub(r"\s+from\s+(?:(?:our|my|the|this)\s+)?(?:software|apps?|applications?|programs?)(?:\s+list)?[?.!]*$", "", m.group(2)).strip()
        name = re.sub(r"\b(?:app|application|program|software)$", "", name).strip()
        name = _PLACE_TAIL.sub("", name).strip(" :,.?!-–\"'")
        name = _APP_TAIL.sub("", name).strip()
        if name and not re.search(
                r"\b(?:folder|directory|wallpaper|note|reminder|virus|history|cache|password)\b", name) \
                and not re.fullmatch(r"(?:my |the |a )?(?:files?|folders?)", name) \
                and not re.search(r"\.\w{1,5}$", name):
            return [Action("uninstall", {"name": name, **({"guide": True} if m.group("guide") else {})},
                           confirm="" if m.group("guide") else f"Uninstall “{name}”?",
                           label=f"Uninstall {name}")]

    name = install_request(c)
    if name:
        return [_install_action(name=name)]

    if _has(r"\bscreenshot\b|\bscreen ?capture\b|\bcapture (?:the |my )?screen\b|\bsnap (?:the|my) screen\b|স্ক্রিনশট", c):
        return [Action("screenshot", label="Take a screenshot")]
    if _has(r"\block (?:the |my |this )?(?:screen|pc|computer|laptop|session)\b|^lock$|\block it\b", c):
        return [Action("lock", label="Lock the screen")]
    a = _volume_action(c)
    if a:
        return [a]
    a = _brightness_action(c)
    if a:
        return [a]
    a = _media_action(c)
    if a:
        return [a]
    m = _CLOSE_RE.match(c)
    if m:
        name = re.sub(r"^(?:the|my|all|this|that)\s+", "", m.group("name").strip())
        if name and name not in ("window", "this", "it", "everything", "all", "tab", "this window", "session",
                                 "the window", "them"):
            return [Action("close_app", {"name": name}, label=f"Close {name}")]

    if _has(r"^(?:open|launch|start|run|show)\s+(?:the\s+)?(?:devos\s+)?optimi[sz]er\b", c):
        return [Action("open_tool", {"tool": "optimizer"}, label="Open DevOS Optimizer")]
    if _has(r"\b(?:clean ?up|clean (?:my |the |this )?(?:pc|computer|laptop|disk|system|junk|cache|temp)|free up|junk|temp(?:orary)? files|clear (?:the )?cache|speed up|make (?:my |the |this )?(?:pc|computer|laptop) faster|slow pc|pc is slow|computer is slow)\b|ক্লিন", c):
        return [Action("cleanup_scan", label="Check what can be cleaned")]

    if _has(r"^" + _OPEN_VERB + r"\s+(?:the\s+)?(?:apps?(?: window| manager)?|installed apps(?: window)?|app manager|apps manager)$", c):
        return [Action("open_tool", {"tool": "apps"}, label="Open Apps")]
    if _has(r"\b(?:apps?|applications?|programs?|software|softwares)\b|অ্যাপ|এপ", c) and \
            _has(r"\b(?:how many|count|total|number of|list|show|which|what|installed|all|my|have i got|do i have)\b|কয়টা|কতগুলো|কত", c) \
            and not _has(r"^(?:open|launch|start|run)\b", c) and not _has(r"\b(?:uninstall|install)\s+\w", c):
        platform = ""
        if _has(r"\bwindows\b|উইন্ডোজ", c):
            platform = "windows"
        elif _has(r"\bandroid\b|অ্যান্ড্রয়েড", c):
            platform = "android"
        elif _has(r"\blinux\b", c):
            platform = "linux"
        count_only = _has(r"\b(?:how many|count|total|number of)\b|কয়টা|কতগুলো|কত", c) and not _has(r"\blist\b", c)
        name = "count_apps" if count_only else "list_apps"
        return [Action(name, {"platform": platform}, label=("Count" if count_only else "List") + " installed apps")]

    page = None
    if _has(r"\b(?:settings?|setup|set up|configure|preferences|options|control panel|timeout|sleep time)\b|সেটিং", c) or \
            _has(r"^(?:connect|pair|turn on|turn off|enable|disable)\b", c) or \
            _has(r"^" + _OPEN_VERB + r"\s+(?:the\s+)?(?:wifi|bluetooth|network|display|sound|printers?|power)$", c):
        for pattern, kcm, label in SETTINGS_PAGES:
            if _has(pattern, c):
                page = (kcm, label)
                break
        if page:
            return [Action("open_settings", {"page": page[0], "title": page[1]}, label=f"Open {page[1]} settings")]
        if _has(r"^(?:open|launch|show|go to|start)?\s*(?:the\s+)?(?:system\s+|devos\s+)?(?:settings|control panel)$", c):
            return [Action("open_settings", {"page": "", "title": "Settings"}, label="Open Settings")]

    topics = _sysinfo_topics(c)
    if topics:
        return [Action("system_info", {"topics": topics}, label="Read this PC's details")]

    m = re.match(r"^" + _OPEN_VERB + r"\s+(?:the\s+|my\s+)?([a-z ]+?)(?:\s+folder|\s+directory)?$", c)
    if m and m.group(1).strip() in FOLDERS:
        key = m.group(1).strip()
        if key != "desktop" or _has(r"folder|directory", c):
            return [Action("open_folder", {"folder": key}, label=f"Open {FOLDERS[key][1] or 'Home'}")]

    if _has(r"\b(?:what(?:'s| is)? (?:the )?time|time is it|current time|what(?:'s| is)? (?:the )?date|today's date|what day is (?:it|today))\b|কয়টা বাজে", c) \
            or _has(r"\b(?:tell|show|check|get)\s+(?:me\s+)?(?:the\s+)?time\b", c):
        return [Action("time", label="Tell the time")]

    ia = _islamic_action(c, context=context)
    if ia:
        return [ia]

    try:
        _here = os.path.dirname(os.path.abspath(__file__))
        if _here not in sys.path:
            sys.path.insert(0, _here)
        import solve
    except Exception:
        solve = None
    if solve is not None and solve.wants_solve(c):
        return [Action("solve", {"text": c}, label="Check this PC and fix what is safe")]

    if _has(r"\b(?:clipboard history|open clipboard|show clipboard|my clipboard)\b", c):
        return [Action("open_tool", {"tool": "clipboard"}, label="Open clipboard history")]
    if _has(r"\b(?:emoji panel|emoji picker|open emoji|show emoji)\b", c) or c.strip() in ("emoji", "emojis"):
        return [Action("open_tool", {"tool": "emoji"}, label="Open emoji")]
    if _has(r"\b(?:broadband|dial\s*up|pppoe|onu(?:\s*connection|\s*network)?|connect\s*onu|ডায়াল|ডায়াল|ব্রডব্যান্ড|ওএনইউ)\b", c):
        return [Action("open_tool", {"tool": "broadband"}, label="Open Broadband Dial-up")]
    if _has(r"\b(?:kids?\s*mode|child(?:ren)?\s*mode|kid\s*play|start\s+kids?\s*mode|open\s+kids?\s*mode|turn\s+on\s+kids?\s*mode|run\s+kids?\s*mode)\b|বাচ্চাদের\s*মোড", c):
        return [Action("open_tool", {"tool": "kids"}, label="Start Kids Mode")]

    m = _RANK_NAV_RE.match(c)
    if m:
        rank_str = (m.group("rank") or "1st").lower()
        rank = {"1st": 1, "first": 1, "top": 1, "2nd": 2, "second": 2, "3rd": 3, "third": 3, "4th": 4, "fourth": 4, "5th": 5, "fifth": 5}.get(rank_str, 1)
        return [Action("open_search_result", {"rank": rank, "browser": _browser_for(c)},
                       label=f"Go to the {rank_str} website")]

    m = _PAGE_NAV_RE.match(c)
    if m:
        page = m.group("page").lower()
        return [Action("open_web_page", {"page": page, "browser": _browser_for(c)},
                       label=f"Go to the {page} page")]

    _BROWSER_TAIL = r"(?:\s+(?:website|site|page|(?:in|on|from|using|with|via)\s+(?:the\s+)?(?:chrome|firefox|browser|web browser|internet)))?"

    m = re.match(r"^(?:open|go to|visit|browse|navigate to|take me to|load)\s+(?:the\s+)?(?:website\s+|site\s+|page\s+)?(\S+?)" + _BROWSER_TAIL + r"$", c)
    if m:
        target = m.group(1)
        if _URLISH.match(target):
            url = normalize_url(target)
            if url:
                return [Action("open_url", {"url": url, "browser": _browser_for(c)}, label=f"Open {target}")]
    m = re.match(r"^(?:open|go to|visit|take me to|load)\s+(?:the\s+)?(.+?)" + _BROWSER_TAIL + r"$", c)
    if m and m.group(1).strip() in KNOWN_SITES:
        site = m.group(1).strip()
        return [Action("open_url", {"url": KNOWN_SITES[site], "browser": _browser_for(c)},
                       label=f"Open {site.title()}")]

    m = re.match(r"^(open|launch|start|run|go to|switch to|fire up|bring up)\s+(.+?)(?:\s+(?:app|application|program))?$", c) \
        or re.match(r"^(.+?)\s+(খোলো|খুলো|খোল|চালু করো|চালু কর|ওপেন করো|ওপেন কর)$", c)
    if m:
        if m.group(1) in ("open", "launch", "start", "run", "go to", "switch to", "fire up", "bring up"):
            verb, name = m.group(1), m.group(2)
        else:
            verb, name = "open", m.group(1)
        name = re.sub(r"^(?:the|my|a|an)\s+", "", name.strip())
        name = re.sub(r"\s+(?:app|application|program|window)$", "", name)
        if _has(r"\b(?:website|site|result|link)\b", name):
            return None
        bn = {"ক্রোম": "chrome", "নোটপ্যাড": "notepad", "টার্মিনাল": "terminal", "সেটিংস": "settings",
              "ফাইলস": "files", "ফাইল": "files"}
        name = bn.get(name, name)
        strong = verb in ("open", "launch")
        return [Action("open_app", {"name": name, "strong": strong}, label=f"Open {name}")]
    return None


# ---------------------------------------------------------------------------
# Requests that carry content: notes, typing, email, reminders, folders, files
#
# These run on the case-preserved text (after preprocess()), so names,
# numbers and notes are kept exactly as the user wrote or said them.
# ---------------------------------------------------------------------------

_RF = re.I | re.S
_P = (r"^(?:(?:please|pls|plz|kindly|hey|hi|hello|ok|okay|yo|devos(?:\s+ai)?|can\s+(?:you|u)|could\s+(?:you|u)|"
      r"would\s+you|will\s+you|i\s+want\s+you\s+to|i\s+need\s+you\s+to|i\s+want\s+to|i'?d\s+like\s+to|"
      r"i\s+would\s+like\s+to|help\s+me(?:\s+to)?|just|now|also|then|quickly|go\s+ahead\s+and)\b[\s,:;!.-]*)*")
_J = r"\s*(?:[,;.]|\band then\b|\bthen\b|\band\b)?\s*(?:(?:just|please|also|then|and|now)\s+)*"
_WV = r"(?P<verb>write|type|save|jot\s+down|note\s+down|put\s+down|enter|put)"
_LEAD_IN = r"(?:\s+down)?(?:\s+(?:that|this|the following|these|the text|text|in it|there|into it|on it))*\s*[:,\-–]?\s*"
_TEXT_APPS = (r"notepad|notes?|a note|new note|text file|a text file|txt file|text editor|editor|kate|kwrite|gedit|"
              r"word|ms word|microsoft word|writer|libreoffice(?: writer)?|office|wordpad|document|a document|"
              r"a new document|file|a file|new file")
_TERMINAL_APPS = r"terminal|konsole|console|command prompt|cmd|shell"
_BROWSER_APPS = r"chrome|browser|the browser|web browser|firefox|google|internet"

_OPEN_APP_WRITE = re.compile(
    _P + r"(?:open|launch|start|run|go\s+to|use|bring\s+up)\s+(?:up\s+)?(?:the\s+|my\s+|a\s+)?(?:new\s+)?"
    r"(?P<app>[\w .+-]+?)(?:\s+(?:app|application|window|program))?" + _J + _WV + r"\b" + _LEAD_IN + r"(?P<text>.+)$",
    _RF)
_WRITE_IN_APP = re.compile(
    _P + _WV + r"\s+(?P<text>.+?)\s+(?:in|into|on|to)\s+(?:the\s+|a\s+|my\s+)?(?:new\s+)?"
    r"(?P<app>" + _TEXT_APPS + "|" + _TERMINAL_APPS + r")$", _RF)
_NOTE_RES = [
    re.compile(_P + r"(?:take|make|create|write|add|save|start|new)\s+(?:down\s+)?(?:a\s+|an\s+|me\s+a\s+)?"
               r"(?:quick\s+|new\s+|short\s+)?(?:note|memo)\b(?:\s+(?:that|saying|of|which says|for me))?"
               r"\s*[:,\-–]?\s*(?P<text>.+)$", _RF),
    re.compile(_P + r"(?:note|memo|notes|reminder note)\s*:\s*(?P<text>.+)$", _RF),
    re.compile(_P + r"(?:jot|note|write|put)\s+down\s*(?:that\s+)?[:,\-–]?\s*(?P<text>.+)$", _RF),
    re.compile(_P + r"(?:remember|save)\s+(?:that|this)\s*[:,\-–]?\s*(?P<text>.+)$", _RF),
    re.compile(_P + r"save\s+(?:it\s+|this\s+)?(?:to|in|into|as)\s+(?:a\s+)?(?:note|notes|file|text file|notepad)"
               r"\s*[:,\-–]?\s*(?P<text>.+)$", _RF),
    re.compile(_P + r"(?:save|store|keep)\s+(?P<text>my\s+(?:full\s+)?(?:name|number|phone|mobile|contact|email|"
               r"address|birthday|date of birth)\b.+)$", _RF),
]
_TYPE_RES = [
    re.compile(_P + r"type\s+(?:out\s+|in\s+)?(?:the\s+(?:text|words?)\s+)?[:,]?\s*(?P<text>.+?)"
               r"(?:\s+(?:here|there|for me|in this (?:window|box|field)|where my cursor is|in the (?:box|field)))?$",
               _RF),
    re.compile(_P + r"(?:write|enter|put|insert)\s+[:,]?\s*(?P<text>.+?)\s+(?:here|in here|in this (?:window|box|field)|"
               r"where my cursor is|where the cursor is|in the (?:box|field|text box))$", _RF),
]
# "write a poem about rain" asks the language model to compose something.
_GENERATE = re.compile(r"^(?:me\s+)?(?:a|an|some|the|my)\s+(?:\w+\s+){0,2}?(?:poem|story|essay|letter|email|e-mail|song|"
                       r"joke|paragraph|summary|article|speech|application|cv|resume|cover letter|report|caption|"
                       r"tweet|post|message|bio|description|lyrics|code|program|script|function|list of)\b|"
                       r"^(?:something|anything)\b|^about\b", re.I)

_FIELD_WORDS = (r"full name|name|phone number|mobile number|contact number|number|phone|mobile|contact|"
                r"email address|email|e-mail|address|birthday|date of birth")
_FIELD_LABEL = {"full name": "Name", "name": "Name", "phone number": "Number", "mobile number": "Number",
                "contact number": "Number", "number": "Number", "phone": "Phone", "mobile": "Mobile",
                "contact": "Contact", "email address": "Email", "email": "Email", "e-mail": "Email",
                "address": "Address", "birthday": "Birthday", "date of birth": "Date of birth"}


def parse_fields(s: str) -> Optional[str]:
    """'my name imran ahmed, number: 0151...' -> 'Name: imran ahmed\\nNumber: 0151...' (values verbatim)."""
    s = s.strip().rstrip(".")
    parts = re.split(r"\s*[,;\n]\s*|\s+and\s+(?=(?:my\s+)?(?:" + _FIELD_WORDS + r")\b)", s, flags=re.I)
    out: List[List[str]] = []
    for part in parts:
        if not part.strip():
            continue
        m = re.match(r"^(?:(?:and|also)\s+)?(?:my\s+)?(" + _FIELD_WORDS + r")\b\s*(?:is\s+|:\s*|=\s*|-\s*|as\s+)?(.+)$",
                     part.strip(), re.I | re.S)
        if m and m.group(2).strip():
            out.append([_FIELD_LABEL[m.group(1).lower()], m.group(2).strip()])
        elif out:
            out[-1][1] += ", " + part.strip()
        else:
            return None
    if not out:
        return None
    return "\n".join(f"{k}: {v}" for k, v in out)


def _payload(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"\s+(?:in it|on it|into it|in (?:the |a )?(?:notepad|note|file|text file))$", "", t, flags=re.I)
    t = re.sub(r"\s*(?:,\s*)?(?:please|pls|for me|thanks|thank you)[.!]?$", "", t, flags=re.I)
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1]
    return t.strip()


def note_content(verb: str, text: str) -> str:
    t = _payload(text)
    if re.match(r"^(?:my\s+)?(?:" + _FIELD_WORDS + r")\b", t, re.I) and (verb or "").lower() in ("save", "", "put", "note"):
        fields = parse_fields(t)
        if fields:
            return fields
    return t


def _note_action(text: str, app: str = "notepad", verb: str = "save") -> Optional[Action]:
    content = note_content(verb, text)
    if not content:
        return None
    where = {"kate": "Text Editor", "writer": "LibreOffice Writer"}.get(app, "Notepad")
    return Action("write_note", {"text": content, "app": app}, label=f"Save a note and open it in {where}")


def _text_app_kind(app: str) -> str:
    a = app.lower().strip()
    if re.fullmatch(_TEXT_APPS, a):
        if re.search(r"kate|kwrite|gedit|text editor|editor", a):
            return "kate"
        if re.search(r"word|writer|office|document", a):
            return "writer"
        return "notepad"
    if re.fullmatch(_TERMINAL_APPS, a):
        return "terminal"
    if re.fullmatch(_BROWSER_APPS, a):
        return "browser"
    if a in ("youtube",):
        return "youtube"
    return "other"


def _write_into_app(app: str, verb: str, text: str, raw: str) -> Optional[List[Action]]:
    kind = _text_app_kind(app)
    payload = _payload(text)
    if not payload:
        return None
    if verb.lower() in ("write", "type", "enter", "put") and _GENERATE.match(payload) and kind != "terminal":
        return None          # the model writes it; the router just opens the app (see route())
    if kind in ("notepad", "kate", "writer"):
        a = _note_action(text, kind, verb)
        return [a] if a else None
    if kind in ("browser", "youtube"):
        browser = _browser_for(raw.lower())
        url = normalize_url(payload) if _URLISH.match(payload.lower()) else None
        if url:
            return [Action("open_url", {"url": url, "browser": browser}, label=f"Open {payload}")]
        return [_search_action("youtube" if kind == "youtube" else "google", payload, browser)]
    name = "terminal" if kind == "terminal" else app.strip()
    return [Action("open_app_and_type", {"app": name, "text": payload},
                   label=f"Open {name} and type your text")]


_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
              "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
              "twenty five": 25, "thirty": 30, "forty": 40, "forty five": 45, "fifty": 50, "sixty": 60,
              "ninety": 90, "half an": 0.5, "half a": 0.5, "a couple of": 2, "couple of": 2, "a few": 3}
_NUM = r"(?P<n>\d+(?:\.\d+)?|" + "|".join(sorted((re.escape(k) for k in _NUM_WORDS), key=len, reverse=True)) + r")"
_UNIT = r"(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?|h|m|s)\b"
_DUR = _NUM + r"[\s-]*" + _UNIT
_REMIND_RES = [
    re.compile(_P + r"(?:remind me|set (?:a|an) (?:reminder|alarm)|reminder)\s+(?:in|after)\s+" + _DUR +
               r"\s*(?:,\s*)?(?:to|that|about|for)?\s*(?P<what>.*)$", _RF),
    re.compile(_P + r"(?:remind me|set (?:a|an) reminder)\s+(?:to|that|about)\s+(?P<what>.+?)\s+(?:in|after)\s+" +
               _DUR + r"$", _RF),
]
_REMIND_AT = re.compile(_P + r"(?:remind me|set (?:a|an) (?:reminder|alarm))\s+(?:(?:to|that|about)\s+(?P<what>.+?)\s+)?"
                        r"at\s+(?P<h>\d{1,2})(?::(?P<mi>\d{2}))?\s*(?P<ap>a\.?m\.?|p\.?m\.?)?"
                        r"(?:\s*(?:,\s*)?(?:to|that|about)\s+(?P<what2>.+))?$", _RF)
_TIMER_RES = [
    re.compile(_P + r"(?:set|start|put on|make)\s+(?:a|an|the)?\s*(?:timer|countdown|alarm)\s+(?:for|of)\s+" + _DUR +
               r"$", _RF),
    re.compile(_P + r"(?:set|start)\s+(?:a|an)?\s*" + _DUR + r"\s+(?:timer|countdown)$", _RF),
    re.compile(_P + r"(?:timer|countdown)\s+(?:for\s+)?" + _DUR + r"$", _RF),
]
MAX_REMINDER_S = 7 * 86400


def duration_seconds(n: str, unit: str) -> Optional[int]:
    n = n.lower().strip()
    try:
        value = float(n)
    except ValueError:
        value = _NUM_WORDS.get(n)
    if value is None:
        return None
    u = unit.lower()
    mult = 3600 if u.startswith("h") else 1 if u.startswith("s") else 60
    secs = int(round(value * mult))
    return secs if 1 <= secs <= MAX_REMINDER_S else None


def human_duration(secs: int) -> str:
    if secs < 60:
        return f"{secs} second" + ("s" if secs != 1 else "")
    if secs % 3600 == 0:
        h = secs // 3600
        return f"{h} hour" + ("s" if h != 1 else "")
    if secs < 3600 or secs % 60:
        m = secs // 60
        s = secs % 60
        return f"{m} minute" + ("s" if m != 1 else "") + (f" {s} seconds" if s else "")
    h, m = divmod(secs // 60, 60)
    return f"{h} hour" + ("s" if h != 1 else "") + f" {m} minute" + ("s" if m != 1 else "")


def _clean_what(what: str) -> str:
    w = (what or "").strip().strip(" .!?,")
    w = re.sub(r"^(?:me\s+)?(?:to|that|about)\s+", "", w, flags=re.I)
    w = re.sub(r"\s*(?:please|thanks|thank you)$", "", w, flags=re.I)
    return w[:200]


def _reminder_action(raw: str, ctx: Optional[ToolContext]) -> Optional[Action]:
    for rx in _TIMER_RES:
        m = rx.match(raw)
        if m:
            secs = duration_seconds(m.group("n"), m.group("unit"))
            if secs:
                return Action("reminder", {"seconds": secs, "message": "", "kind": "timer"},
                              label=f"Set a {human_duration(secs)} timer")
    for rx in _REMIND_RES:
        m = rx.match(raw)
        if m:
            secs = duration_seconds(m.group("n"), m.group("unit"))
            if secs:
                what = _clean_what(m.group("what"))
                return Action("reminder", {"seconds": secs, "message": what, "kind": "reminder"},
                              label=f"Remind you in {human_duration(secs)}")
    m = _REMIND_AT.match(raw)
    if m:
        now = (ctx.now if ctx else datetime.datetime.now)()
        h, mi = int(m.group("h")), int(m.group("mi") or 0)
        ap = (m.group("ap") or "").lower().replace(".", "")
        if ap == "pm" and h < 12:
            h += 12
        elif ap == "am" and h == 12:
            h = 0
        if h > 23 or mi > 59:
            return None
        due = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if not ap and due <= now and h < 12:
            due = due + datetime.timedelta(hours=12)
        if due <= now:
            due = due + datetime.timedelta(days=1)
        secs = int((due - now).total_seconds())
        what = _clean_what(m.group("what") or m.group("what2") or "")
        return Action("reminder", {"seconds": secs, "message": what, "kind": "reminder"},
                      label=f"Remind you at {due.strftime('%I:%M %p').lstrip('0')}")
    return None


_EMAIL_ADDR = r"(?P<to>[\w.+-]+(?:@|\s+at\s+)[\w-]+(?:(?:\.|\s+dot\s+)[\w-]+)+)"
_EMAIL_RE = re.compile(
    _P + r"(?:(?:send|write|compose|draft|make|create)\s+(?:an?\s+|the\s+)?(?:new\s+)?(?:e-?mail|mail|message)\s+to|"
    r"e-?mail|mail)\s+" + _EMAIL_ADDR +
    r"(?:\s*,?\s*(?:about|regarding|re|with (?:the )?subject|subject|titled)\s*:?\s*(?P<subj>.+?))?"
    r"(?:\s*,?\s*(?:and\s+)?(?:saying|that says|which says|telling (?:him|her|them)|with (?:the )?(?:body|message|text)|"
    r"message|body)\s*:?\s*(?P<body>.+))?$", _RF)
_EMAIL_OK = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")


def spoken_email(addr: str) -> str:
    a = re.sub(r"\s+at\s+", "@", addr.strip(), flags=re.I)
    a = re.sub(r"\s+dot\s+", ".", a, flags=re.I)
    return a.lower()


def mailto_url(to: str, subject: str = "", body: str = "") -> str:
    url = "mailto:" + urllib.parse.quote(to, safe="@.+-_")
    q = []
    if subject:
        q.append("subject=" + urllib.parse.quote(subject, safe=""))
    if body:
        q.append("body=" + urllib.parse.quote(body, safe=""))
    return url + ("?" + "&".join(q) if q else "")


_FOLDER_RE = re.compile(
    _P + r"(?:make|create|add|new)\s+(?:me\s+)?(?:a\s+)?(?:new\s+)?(?:folder|directory)"
    r"(?:\s+(?:on|in)\s+(?:the\s+|my\s+)?(?P<where>desktop|documents|downloads|pictures|music|videos|home(?: folder)?))?"
    r"\s+(?:called|named|with (?:the )?name|name|titled)?\s*[:\-]?\s*(?P<name>.+?)"
    r"(?:\s+(?:on|in)\s+(?:the\s+|my\s+)?(?P<where2>desktop|documents|downloads|pictures|music|videos|home(?: folder)?))?$",
    _RF)
_FILE_EXT = r"pdf|docx?|odt|txt|md|rtf|xlsx?|ods|csv|pptx?|odp|png|jpe?g|gif|webp|svg|mp3|wav|ogg|flac|mp4|mkv|avi|zip|tar|gz|iso|py|html?"
_OPEN_FILE_RES = [
    re.compile(_P + r"(?:open|show|find|locate|where is)\s+(?:me\s+)?(?:the\s+|my\s+|a\s+)?(?:file|document|pdf|photo|picture|"
               r"image|video|song|spreadsheet|presentation)\s+(?:called|named|titled)?\s*[:\-]?\s*(?P<name>.+?)$", _RF),
    re.compile(_P + r"(?:open|show|find|locate|where is)\s+(?:me\s+)?(?:the\s+|my\s+)?(?P<name>[^\s/\\][^/\\]*?\.(?:" + _FILE_EXT +
               r"))(?:\s+file)?$", _RF),
]


def _valid_name(name: str) -> Optional[str]:
    n = (name or "").strip().strip("\"'").strip().rstrip(".")
    if not n or len(n) > 100 or "/" in n or "\\" in n or "\0" in n or n.startswith(".") or n in ("..", "."):
        return None
    if any(ord(c) < 32 for c in n):
        return None
    return n


def route_content(raw: str, ctx: Optional[ToolContext] = None) -> Optional[RouteResult]:
    """Notes, typing, email, reminders, folders and files, from the case-preserved request."""
    if not raw:
        return None
    m = _EMAIL_RE.match(raw)
    if m:
        to = spoken_email(m.group("to"))
        if _EMAIL_OK.match(to):
            subj = (m.group("subj") or "").strip().strip(" .")
            body = (m.group("body") or "").strip()
            return RouteResult([Action("compose_email", {"to": to, "subject": subj, "body": body},
                                       label=f"Write an email to {to}")])
    a = _reminder_action(raw, ctx)
    if a:
        return RouteResult([a])
    m = _FOLDER_RE.match(raw)
    if m:
        name = _valid_name(re.sub(r"^(?:called|named)\s+", "", m.group("name"), flags=re.I))
        where = (m.group("where") or m.group("where2") or "desktop").lower().replace(" folder", "")
        if name:
            return RouteResult([Action("create_folder", {"name": name, "where": where},
                                       label=f"Create the folder {name}")])
    m = _OPEN_APP_WRITE.match(raw)
    if m:
        acts = _write_into_app(m.group("app"), m.group("verb"), m.group("text"), raw)
        if acts:
            return RouteResult(acts)
    m = _WRITE_IN_APP.match(raw)
    if m:
        acts = _write_into_app(m.group("app"), m.group("verb"), m.group("text"), raw)
        if acts:
            return RouteResult(acts)
    for rx in _NOTE_RES:
        m = rx.match(raw)
        if m:
            a = _note_action(m.group("text"), "notepad", "save")
            if a:
                return RouteResult([a])
    for rx in _TYPE_RES:
        m = rx.match(raw)
        if m:
            text = _payload(m.group("text"))
            if text and not _GENERATE.match(text) and not re.match(r"^of\b", text, re.I):
                return RouteResult([Action("type_text", {"text": text, "delay": 1.0},
                                           label="Type the text into the window you were using")])
    for rx in _OPEN_FILE_RES:
        m = rx.match(raw)
        if m:
            name = _valid_name(m.group("name"))
            low = (name or "").lower()
            if name and low not in FOLDERS and low not in KNOWN_SITES and not re.fullmatch(
                    r"(?:my\s+)?(?:files|documents|downloads|folder|file manager)", low):
                return RouteResult([Action("open_path", {"name": name}, label=f"Find and open {name}")])
    return None


# ---------------------------------------------------------------------------
# "Install <app>" and store links
#
# A Microsoft Store / Google Play / App Store / Flathub link, "install zoom",
# "how can I install it on my PC" and "can you install this" (after a link or
# an app name earlier in the chat) all become one install_app action. The
# answer comes from components/apphub/app_resolver.py, never from the model:
# the small model used to invent DevOS menu steps for these.
# ---------------------------------------------------------------------------

_STORE_LINK_RE = re.compile(
    r"ms-windows-store://\S+"
    r"|(?:https?://)?(?:www\.)?(?:apps\.microsoft\.com/\S+"
    r"|microsoft\.com/(?:[a-z]{2}-[a-z]{2}/)?(?:store/(?:apps|p|productid|detail)|p)/\S+"
    r"|play\.google\.com/store/apps/details\S+"
    r"|(?:apps|itunes)\.apple\.com/\S*?id\d+\S*"
    r"|flathub\.org/(?:[a-z]{2}(?:-[a-z]{2,4})?/)?apps/\S+)", re.I)
_ANY_LINK_RE = re.compile(r"https?://\S+", re.I)
_INSTALL_WORD = re.compile(r"\b(?:install|installing|installation|download|setup|set up)\b|ইনস্টল|ইন্সটল|ডাউনলোড", re.I)
_OPEN_ONLY = re.compile(r"^(?:open|go to|visit|browse|navigate to|take me to|load|show(?: me)?)\b")
_INSTALL_RE = re.compile(
    r"^(?P<pre>how (?:can|do|should|would|could|to) (?:i |we |you |u )?|how to |where (?:can|do) (?:i|we) |"
    r"is it possible to |is there a way to |i want to |i need to |want to |need to |wanna |pls |please )?"
    r"(?P<verb>install|downloads?|get)\b\s*(?P<name>.*?)$")     # typo fixing turns "download" into "downloads"
_BN_INSTALL_RE = re.compile(r"^(?P<name>.*?)\s*(?:কিভাবে|কীভাবে)?\s*(?:ইনস্টল|ইন্সটল|ডাউনলোড)")
_PLACE_TAIL = re.compile(r"\s*\b(?:on|in|for|into|onto|to)\s+(?:my |our |this |the |a )?"
                         r"(?:pc|computer|laptop|devos|system|machine|desktop|linux|ubuntu|windows)\b.*$")
_APP_TAIL = re.compile(r"\s+(?:app|apps|application|program|software)$")
_FOLLOW_UP_NAMES = frozenset(("", "this", "it", "that", "this app", "that app", "the app", "this one", "that one",
                              "them", "these", "those", "this application", "this program", "this software",
                              "the program", "the software", "এটা", "এটি"))
_NOT_AN_APP = re.compile(r"\b(?:videos?|songs?|music|movies?|files?|pictures?|pdfs?|images?|documents?|"
                         r"updates?|drivers?|rid of|ready|started|time|help|wallpapers?|subtitles?|mp3|mp4|"
                         r"a job|money|better|back|home|out|up|over|in touch|lost|well|sleep|from|"
                         # developer questions stay with the model: "install python packages with pip"
                         r"packages?|librar(?:y|ies)|modules?|dependenc(?:y|ies)|extensions?|plugins?|"
                         r"requirements|pip|npm|apt|sudo|using|via|with)\b")


def _store_link(text: str) -> Optional[str]:
    m = _STORE_LINK_RE.search(text or "")
    return m.group(0).rstrip(".,;:!?)]}>'\"") if m else None


def _any_link(text: str) -> Optional[str]:
    m = _ANY_LINK_RE.search(text or "")
    return m.group(0).rstrip(".,;:!?)]}>'\"") if m else None


def install_request(t: str) -> Optional[str]:
    """App name in "install zoom" / "how can i download whatsapp on my pc".

    "" means "this / it" (look back in the chat); None means not an install request.
    """
    t = (t or "").strip().rstrip("?.!:, ")
    m = _INSTALL_RE.match(t)
    if m:
        verb, pre, name = m.group("verb"), m.group("pre") or "", m.group("name")
    else:
        m = _BN_INSTALL_RE.match(t)
        if not m:
            return None
        verb, pre, name = "install", "", m.group("name")
    if re.match(r"(?:to|there|here|directions|into|from)\b", name):
        return None             # "how do i get to dhanmondi lake" is directions
    name = _PLACE_TAIL.sub("", name).strip(" :,.?!-–\"'")
    if name in _FOLLOW_UP_NAMES:
        return ""
    had_app_word = bool(_APP_TAIL.search(name))
    name = re.sub(r"^(?:the|a|an|this|that|me|us)\s+", "", name)
    name = _APP_TAIL.sub("", name).strip()
    if name in _FOLLOW_UP_NAMES:
        return ""
    if _NOT_AN_APP.search(name) or len(name) > 60:
        return None
    if verb == "get" and not (pre.startswith(("how", "where", "is")) or had_app_word):
        return None             # "get the time", "get me a joke"
    return name


def _install_action(name: str = "", link: str = "") -> Action:
    what = name or ("this app" if link else "the app")
    return Action("install_app", {"name": name, "link": link}, label=f"Find how to get {what} on DevOS")


_PACKAGE_LINK_RE = re.compile(
    r"https?://\S+(?:\.(?:deb|appimage|exe|msi|apk)|/releases(?:/\S*)?)(?:[?#]\S*)?", re.I)


def route_install(text: str, context: Optional[List[str]] = None) -> Optional[Action]:
    """install_app for store links, "install <app>" and "install this" follow-ups (see above)."""
    link = _store_link(text)
    if not link:
        pkg_m = _PACKAGE_LINK_RE.search(text or "")
        if pkg_m:
            link = pkg_m.group(0).rstrip(".,;:!?)]}>'\"")
    if not link and _INSTALL_WORD.search(text or ""):
        link = _any_link(text)
    rest = text.replace(link, " ") if link else text
    t = normalize(preprocess(rest))
    if link:
        if _OPEN_ONLY.match(t) and not _INSTALL_WORD.search(t):
            return None         # "open <store link>" just opens the page
        return _install_action(link=link)
    name = install_request(t)
    if name is None:
        return None
    if name:
        return _install_action(name=name)
    for prev in reversed(list(context or [])[-4:]):
        found = _store_link(prev) or _any_link(prev)
        if found:
            return _install_action(link=found)
        n = install_request(normalize(preprocess(prev)))
        if n:
            return _install_action(name=n)
    return _install_action()


def _find_recent_query(context: Optional[List[str]]) -> str:
    if not context:
        return ""
    for msg in reversed(context):
        if not msg:
            continue
        m = re.search(r"\b(?:search|google|look up|lookup|find)\b.*?\b(?:about|for|regarding|in google)?\s*(?::\s*)?([a-zA-Z0-9_.-]+)", msg, re.I)
        if m:
            return m.group(1).strip()
    return ""


def _find_recent_website(context: Optional[List[str]]) -> str:
    if not context:
        return ""
    for msg in reversed(context):
        if not msg:
            continue
        m = re.search(r"https?://[^\s\"'<>]+", msg)
        if m:
            return m.group(0).rstrip(".,;!?)]}'\"")
        for word in msg.split():
            clean = word.strip(".,;!?)]}'\"")
            if "." in clean and len(clean.split(".")[-1]) in (2, 3, 4) and not clean.endswith("."):
                return "https://" + clean
    return ""


def route_single_clause(c: str, ctx: Optional[ToolContext] = None, context: Optional[List[str]] = None,
                        last_query: str = "", last_website: str = "") -> Optional[List[Action]]:
    # 1. Search Result / Web Page navigation
    m = _RANK_NAV_RE.match(c)
    if m:
        rank_str = (m.group("rank") or "1st").lower()
        rank = {"1st": 1, "first": 1, "top": 1, "2nd": 2, "second": 2, "3rd": 3, "third": 3, "4th": 4, "fourth": 4, "5th": 5, "fifth": 5}.get(rank_str, 1)
        q = last_query or _find_recent_query(context)
        return [Action("open_search_result", {"query": q, "rank": rank, "browser": _browser_for(c)},
                       label=f"Go to the {rank_str} website")]

    m = _PAGE_NAV_RE.match(c)
    if m:
        page = m.group("page").lower()
        q = last_query or _find_recent_query(context)
        site = last_website or _find_recent_website(context)
        return [Action("open_web_page", {"page": page, "website": site, "query": q, "browser": _browser_for(c)},
                       label=f"Go to the {page} page")]

    # 2. Search
    ws = parse_web_search(c)
    if ws:
        _pre, act, _rest = ws
        return [act]

    # 2.5 Social Post
    sp = parse_social_post(c)
    if sp:
        return [sp]

    # 3. Route content
    cnt = route_content(c, ctx)
    if cnt and cnt.actions:
        return cnt.actions

    # 4. Standard route_clause
    r = route_clause(c, ctx, context=context)
    if r:
        return r

    # 5. Direct URL
    if _URLISH.match(c):
        norm = normalize_url(c)
        if norm:
            return [Action("open_url", {"url": norm, "browser": _browser_for(c)}, label=f"Open {c}")]
    return None


def route(text: str, ctx: Optional[ToolContext] = None, context: Optional[List[str]] = None,
          initial_query: str = "", initial_website: str = "") -> RouteResult:
    """Deterministic intent router. Empty result -> let the model answer.

    context: the user's earlier messages in this chat (oldest first), for
    follow-ups such as "can you install this" after a pasted link.
    """
    raw = preprocess(text)
    if not raw:
        return RouteResult()
    content = route_content(raw, ctx)
    if content:
        return content
    inst = route_install(text, context)
    if inst:
        return RouteResult([inst])
    t = normalize(raw)
    if not t:
        return RouteResult()
    sp = parse_social_post(raw) or parse_social_post(t)
    if sp:
        return RouteResult([sp])
    whole = route_clause(t, ctx, context=context)
    if whole and whole[0].name in ("open_url", "islamic"):
        return RouteResult(whole)          # "open google maps" is a site, not a search; islamic is direct
    ws = parse_web_search(t)
    if ws:
        pre, action, rest = ws
        actions: List[Action] = []
        for c in pre:
            r = route_clause(c, ctx)
            if r:
                actions.extend(r)
        actions.append(action)
        if rest:
            q = action.args.get("query", "")
            site = resolve_search_result(q, 1) if q else ""
            sub_res = route(rest, ctx, context, initial_query=q, initial_website=site)
            for sub_a in sub_res.actions:
                if sub_a.name in ("open_search_result", "open_web_page") and not sub_a.args.get("query"):
                    sub_a.args["query"] = q
                if sub_a.name == "open_web_page" and (not sub_a.args.get("website") or "google.com" in sub_a.args.get("website", "")):
                    if site:
                        sub_a.args["website"] = site
                actions.append(sub_a)
        return RouteResult(_merge(actions))
    clauses = split_clauses(t)
    if len(clauses) > 1:
        parts: List[Action] = []
        leftovers = []
        last_query = initial_query or _find_recent_query(context)
        last_website = initial_website or _find_recent_website(context)
        for c in clauses:
            r = route_single_clause(c, ctx, context, last_query, last_website)
            if r:
                for act in r:
                    if act.name == "web_search":
                        last_query = act.args.get("query", "")
                    elif act.name == "open_search_result":
                        if not act.args.get("query") and last_query:
                            act.args["query"] = last_query
                        last_query = act.args.get("query", "")
                        last_website = resolve_search_result(last_query, act.args.get("rank", 1))
                    elif act.name == "open_web_page":
                        if not act.args.get("query") and last_query:
                            act.args["query"] = last_query
                        if not act.args.get("website") and last_website:
                            act.args["website"] = last_website
                    elif act.name == "open_url":
                        last_website = act.args.get("url", "")
                    parts.append(act)
            else:
                leftovers.append(c)
        if parts and not leftovers:
            solved = [a for a in parts if a.name == "solve"]
            if solved:
                return RouteResult([Action("solve", {"text": t}, label="Check this PC and fix what is safe")])
            return RouteResult(_merge(parts))
        if whole and whole[0].name != "open_app":
            return RouteResult(whole)
        weak_only = all(a.name == "open_app" and not a.args.get("strong") for a in parts)
        if parts and not weak_only:
            if any(a.name == "solve" for a in parts):
                return RouteResult([Action("solve", {"text": t}, label="Check this PC and fix what is safe")])
            return RouteResult(_merge(parts), leftover=" and ".join(leftovers))
        if parts:
            return RouteResult()
    if whole:
        return RouteResult(whole)
    return RouteResult()


def _merge(actions: List[Action]) -> List[Action]:
    """Several system_info questions in one sentence become one answer."""
    out: List[Action] = []
    for a in actions:
        if a.name == "system_info":
            prev = next((x for x in out if x.name == "system_info"), None)
            if prev is not None:
                for topic in a.args.get("topics", []):
                    if topic not in prev.args["topics"]:
                        prev.args["topics"].append(topic)
                continue
        out.append(a)
    return out


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _launch(ctx: ToolContext, argv: List[str], dry_run: bool) -> bool:
    if dry_run:
        return True
    return ctx.launcher(argv)


def _done(ok: bool, text_ok: str, text_fail: str, plan: List[List[str]], **kw) -> ToolResult:
    return ToolResult(text_ok if ok else text_fail, ok=ok, plan=plan, **kw)


def count_apps_by_type(apps: List[object]) -> Dict[str, int]:
    counts = {"linux": 0, "windows": 0, "android": 0}
    for a in apps:
        p = getattr(a, "platform", "linux")
        counts[p] = counts.get(p, 0) + 1
    return counts


def _discover(ctx: ToolContext) -> Tuple[Optional[List[object]], str]:
    try:
        disc = ctx.discovery()
    except Exception as exc:
        return None, str(exc)
    if disc is None:
        return None, "the Apps component is not available"
    try:
        return list(disc.discover_all()), ""
    except Exception as exc:
        return None, str(exc)


def execute(action: Action, ctx: Optional[ToolContext] = None, dry_run: bool = False) -> ToolResult:
    ctx = ctx or ToolContext()
    fn = _EXECUTORS.get(action.name)
    if fn is None:
        return ToolResult("I can't do that yet.", ok=False)
    try:
        return fn(action, ctx, dry_run)
    except Exception as exc:  # a tool failing must never crash the window
        return ToolResult(f"That didn't work: {exc}", ok=False)


def _x_help(a, ctx, dry):
    return ToolResult(HELP_TEXT)


ABOUT_TEXT = (
    "**DevOS** and **DevOS AI** are made by the DevOS team, led by **Imran Ahmed (Imran Dev)**.\n\n"
    "- Portfolio: https://imrandev.bd/\n"
    "- DevOS is open source: https://github.com/imranbru99/DevOS\n\n"
    # The only contact details DevOS AI gives (same list as DEVOS_CONTACTS in
    # components/ai-core/server.py); the model once invented a LinkedIn URL.
    "**Contact the DevOS team**\n"
    "- Email: devos@imrandev.bd\n"
    "- Contact form: https://imrandev.bd/contact\n"
    "- WhatsApp: https://wa.me/+8801576918420\n"
    "- GitHub: https://github.com/imranbru99\n"
    "- LinkedIn: https://linkedin.com/in/imranbru99\n\n"
    "I run entirely on this PC, built on open-source language-model technology and tuned for DevOS."
)


def _x_about(a, ctx, dry):
    return ToolResult(ABOUT_TEXT)


def _x_web_search(a, ctx, dry):
    url = str(a.args["url"])
    argv = browser_command(str(a.args.get("browser", "default")), url, ctx.which)
    ok = _launch(ctx, argv, dry)
    where = "YouTube" if a.args.get("engine") == "youtube" else "Google"
    return _done(ok, f"Searching {where} for **{a.args['query']}** — the results are opening in your browser.",
                 "I couldn't open the browser.", [argv], data={"url": url})


def copy_to_clipboard(text: str, ctx: ToolContext) -> bool:
    """Copies text to the system clipboard using wl-copy or xclip if available."""
    if not text:
        return False
    if ctx.which("wl-copy"):
        rc, _ = ctx.runner(["wl-copy"], input_text=text, timeout=2.0)
        if rc == 0:
            return True
    if ctx.which("xclip"):
        rc, _ = ctx.runner(["xclip", "-i", "-selection", "clipboard"], input_text=text, timeout=2.0)
        return rc == 0
    return False


def _x_social_post(a: Action, ctx: ToolContext, dry: bool) -> ToolResult:
    plat_key = str(a.args.get("platform", "facebook")).lower()
    plat_info = SOCIAL_PLATFORMS.get(plat_key, (plat_key.title(), "https://" + plat_key + ".com"))
    plat_name, base_url = plat_info
    topic = str(a.args.get("topic", "")).strip()
    browser = str(a.args.get("browser", "default"))
    text = str(a.args.get("text", "")).strip()

    if not text:
        if topic:
            text = f"Exploring {topic} on DevOS — built for smooth performance, developer power, and privacy!"
        else:
            text = "Excited to build on DevOS — the developer-first OS!"

    # For X / Twitter, open tweet composer intent with text pre-filled
    if plat_key in ("twitter", "x"):
        target_url = "https://twitter.com/intent/tweet?text=" + urllib.parse.quote(text)
    else:
        target_url = base_url

    argv = browser_command(browser, target_url, ctx.which)
    plan = [argv]
    if ctx.which("xclip") or ctx.which("wl-copy"):
        plan.append(["xclip", "-i", "-selection", "clipboard", text])

    if dry:
        return ToolResult(
            f"Opening **{plat_name}** with your draft post ready.",
            plan=plan,
            data={"url": target_url, "platform": plat_key, "draft": text, "clipboard": text}
        )

    copy_to_clipboard(text, ctx)
    ok = _launch(ctx, argv, dry)

    b_label = "Chrome" if browser == "chrome" else ("Firefox" if browser == "firefox" else "your browser")
    msg = (
        f"Opening **{plat_name}** in {b_label} with your draft post ready.\n\n"
        f"**Draft Post:**\n"
        f"> {text}\n\n"
        f"📋 *The draft has been copied to your clipboard. Paste (**Ctrl+V**) into the post box and review before publishing!*"
    )
    buttons = [
        ("Open " + plat_name, Action("open_url", {"url": target_url, "browser": browser}, label=f"Open {plat_name}"))
    ]
    return _done(ok, msg, f"I couldn't open {plat_name} in the browser.", plan,
                 buttons=buttons, data={"url": target_url, "platform": plat_key, "draft": text, "clipboard": text})



def _link_verdict(url):
    """None when the checker cannot be loaded. Never raises."""
    try:
        sec = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "security")
        if sec not in sys.path:
            sys.path.insert(0, sec)
        import linkguard
        return linkguard.inspect_url(url)
    except Exception:
        return None


def _x_open_url(a, ctx, dry):
    url = normalize_url(str(a.args.get("url", "")))
    if not url:
        return ToolResult("That doesn't look like a web address I can open.", ok=False)
    verdict = _link_verdict(url)
    if verdict and verdict.get("level") in ("block", "warn"):
        return ToolResult("I did not open that address. " + verdict.get("summary", ""),
                          ok=False, data={"url": url, "linkguard": verdict.get("level")})
    argv = browser_command(str(a.args.get("browser", "default")), url, ctx.which)
    ok = _launch(ctx, argv, dry)
    host = urllib.parse.urlsplit(url).hostname or url
    return _done(ok, f"Opening **{host}**.", "I couldn't open the browser.", [argv], data={"url": url})


def _x_open_search_result(a, ctx, dry):
    query = str(a.args.get("query", "")).strip()
    rank = int(a.args.get("rank", 1))
    browser = str(a.args.get("browser", "default"))
    url = str(a.args.get("url", "")).strip()
    if not url:
        url = resolve_search_result(query, rank)
    verdict = _link_verdict(url)
    if verdict and verdict.get("level") in ("block", "warn"):
        return ToolResult("I did not open that address. " + verdict.get("summary", ""),
                          ok=False, data={"url": url, "linkguard": verdict.get("level")})
    argv = browser_command(browser, url, ctx.which)
    ok = _launch(ctx, argv, dry)
    parts = urllib.parse.urlsplit(url)
    host = (parts.netloc or parts.path or url).replace("www.", "")
    rank_word = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th"}.get(rank, f"{rank}th")
    msg = f"Opening the {rank_word} website (**{host}**)."
    return _done(ok, msg, "I couldn't open the browser.", [argv], data={"url": url, "query": query, "rank": rank})


def _x_open_web_page(a, ctx, dry):
    page = str(a.args.get("page", "")).strip().lower()
    website = str(a.args.get("website", "")).strip()
    query = str(a.args.get("query", "")).strip()
    browser = str(a.args.get("browser", "default"))
    url = str(a.args.get("url", "")).strip()
    if not url:
        if (not website or "google.com" in website) and query:
            website = resolve_search_result(query, 1)
        if not website or "google.com" in website:
            website = "https://imrandev.bd"
        slug = page
        if slug in ("contact", "contact us"):
            slug = "contact"
        elif slug in ("about", "about us"):
            slug = "about"
        elif slug in ("docs", "documentation"):
            slug = "docs"
        base = website.rstrip("/")
        if "btnI=1" in base or "google.com" in base:
            lucky_q = f"{query} {slug}" if query else slug
            url = f"https://www.google.com/search?btnI=1&q={urllib.parse.quote_plus(lucky_q)}"
        else:
            url = f"{base}/{slug}"
    verdict = _link_verdict(url)
    if verdict and verdict.get("level") in ("block", "warn"):
        return ToolResult("I did not open that address. " + verdict.get("summary", ""),
                          ok=False, data={"url": url, "linkguard": verdict.get("level")})
    argv = browser_command(browser, url, ctx.which)
    ok = _launch(ctx, argv, dry)
    parts = urllib.parse.urlsplit(url)
    host = (parts.netloc or parts.path).replace("www.", "")
    path = parts.path
    target_display = f"{host}{path}" if path and path != "/" else host
    msg = f"Opening the {page} page (**{target_display}**)."
    return _done(ok, msg, "I couldn't open the browser.", [argv], data={"url": url, "page": page})


def _x_open_app(a, ctx, dry):
    name = str(a.args.get("name", "")).strip()
    apps = scan_desktop_entries(ctx.app_dirs)
    app, close = match_app(name, apps)
    if app is None:
        site = KNOWN_SITES.get(name.lower())
        if site:
            return _x_open_url(Action("open_url", {"url": site, "browser": "default"}), ctx, dry)
        hint = f" Did you mean {', '.join('**' + c + '**' for c in close)}?" if close else ""
        return ToolResult(f"I couldn't find an app called **{name}** on this PC.{hint} "
                          "You can install apps from the App Hub.", ok=False, data={"not_found": True})
    argv = launch_command(app, ctx.which)
    ok = _launch(ctx, argv, dry)
    return _done(ok, f"Opening **{app.name}**.", f"I couldn't start {app.name}.", [argv],
                 data={"desktop_id": app.desktop_id})


def _x_system_info(a, ctx, dry):
    topics = [t for t in (a.args.get("topics") or []) if t in SYSINFO_TOPICS] or list(SYSINFO_TOPICS)
    info = gather_system_info(ctx)
    return ToolResult(format_system_info(info, topics), data={"info": info})


def _x_count_apps(a, ctx, dry):
    apps, err = _discover(ctx)
    if apps is None:
        return ToolResult(f"I couldn't read the list of apps ({err}).", ok=False)
    platform = a.args.get("platform") or ""
    counts = count_apps_by_type(apps)
    total = len(apps)
    if platform:
        n = counts.get(platform, 0)
        label = {"windows": "Windows", "android": "Android", "linux": "Linux"}[platform]
        return ToolResult(f"You have **{n} {label} app{'s' if n != 1 else ''}** installed.",
                          data={"counts": counts, "total": total})
    lines = [f"You have **{total} apps** installed:",
             f"- {counts.get('linux', 0)} Linux apps",
             f"- {counts.get('windows', 0)} Windows apps",
             f"- {counts.get('android', 0)} Android apps",
             "", "Say “list my apps” to see them, or open the Apps window to uninstall something."]
    return ToolResult("\n".join(lines), data={"counts": counts, "total": total},
                      buttons=[("Open Apps", Action("open_tool", {"tool": "apps"}))])


def _x_list_apps(a, ctx, dry):
    apps, err = _discover(ctx)
    if apps is None:
        return ToolResult(f"I couldn't read the list of apps ({err}).", ok=False)
    platform = a.args.get("platform") or ""
    if platform:
        apps = [x for x in apps if getattr(x, "platform", "") == platform]
    label = {"windows": "Windows ", "android": "Android ", "linux": "Linux "}.get(platform, "")
    if not apps:
        return ToolResult(f"No {label}apps are installed yet.", data={"total": 0})
    names = sorted({getattr(x, "name", "?") for x in apps}, key=str.casefold)
    shown = names[:60]
    text = f"**{len(names)} {label}apps installed:**\n" + "\n".join(f"- {n}" for n in shown)
    if len(names) > len(shown):
        text += f"\n- …and {len(names) - len(shown)} more (open the Apps window for all)"
    return ToolResult(text, data={"total": len(names), "names": names},
                      buttons=[("Open Apps", Action("open_tool", {"tool": "apps"}))])


def _x_open_settings(a, ctx, dry):
    page = str(a.args.get("page", ""))
    if page and not re.fullmatch(r"kcm_[a-z_]+", page):
        return ToolResult("Unknown settings page.", ok=False)
    argv = settings_command(page, ctx.which)
    ok = _launch(ctx, argv, dry)
    title = a.args.get("title") or "Settings"
    return _done(ok, f"Opening **{title}** settings." if page else "Opening **Settings**.",
                 "I couldn't open Settings.", [argv])


def _x_open_folder(a, ctx, dry):
    key = str(a.args.get("folder", ""))
    if key not in FOLDERS:
        return ToolResult("Unknown folder.", ok=False)
    xdg_key, rel = FOLDERS[key]
    path = user_dir(ctx, xdg_key, rel)
    argv = ["xdg-open", path]
    ok = _launch(ctx, argv, dry)
    return _done(ok, f"Opening **{os.path.basename(path) or 'Home'}**.", "I couldn't open that folder.", [argv])


def _x_volume(a, ctx, dry):
    op = a.args.get("op")
    sink = "@DEFAULT_SINK@"
    if op == "up":
        argv = ["pactl", "set-sink-volume", sink, "+10%"]
        msg = "Volume up."
    elif op == "down":
        argv = ["pactl", "set-sink-volume", sink, "-10%"]
        msg = "Volume down."
    elif op == "mute":
        argv = ["pactl", "set-sink-mute", sink, "1"]
        msg = "Sound muted."
    elif op == "unmute":
        argv = ["pactl", "set-sink-mute", sink, "0"]
        msg = "Sound unmuted."
    elif op == "set":
        level = int(a.args.get("level", 50))
        level = max(0, min(150, level))
        argv = ["pactl", "set-sink-volume", sink, f"{level}%"]
        msg = f"Volume set to {level}%."
    else:
        return ToolResult("Unknown volume change.", ok=False)
    plan = [argv]
    if op in ("up", "set") and not dry:
        ctx.runner(["pactl", "set-sink-mute", sink, "0"])
    if dry:
        return ToolResult(msg, plan=plan)
    rc, out = ctx.runner(argv)
    return _done(rc == 0, msg, "I couldn't change the volume (no sound device found).", plan)


def _x_brightness(a, ctx, dry):
    op = a.args.get("op")
    if op == "up":
        val = "10%+"
    elif op == "down":
        val = "10%-"
    elif op == "set":
        val = f"{max(1, min(100, int(a.args.get('level', 50))))}%"
    else:
        return ToolResult("Unknown brightness change.", ok=False)
    argv = ["brightnessctl", "set", val]
    msg = {"up": "Brighter.", "down": "Dimmer."}.get(op, f"Brightness set to {val}.")
    if dry:
        return ToolResult(msg, plan=[argv])
    if not ctx.which("brightnessctl"):
        return ToolResult("Screen brightness can't be changed from here on this PC "
                          "(external monitors use their own buttons).", ok=False, plan=[argv])
    rc, _ = ctx.runner(argv)
    return _done(rc == 0, msg, "This screen doesn't allow brightness changes from software.", [argv])


def _x_screenshot(a, ctx, dry):
    folder = os.path.join(user_dir(ctx, "PICTURES", "Pictures"), "Screenshots")
    stamp = ctx.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = os.path.join(folder, f"Screenshot_{stamp}.png")
    argv = ["spectacle", "-b", "-n", "-f", "-d", "700", "-o", path]
    if not dry:
        os.makedirs(folder, exist_ok=True)
    ok = _launch(ctx, argv, dry)
    return _done(ok, f"Screenshot saved to **Pictures/Screenshots/{os.path.basename(path)}**.",
                 "I couldn't take a screenshot.", [argv], data={"path": path},
                 buttons=[("Open Screenshots", Action("open_folder", {"folder": "screenshots"}))])


def _x_lock(a, ctx, dry):
    argv = ["loginctl", "lock-session"]
    ok = _launch(ctx, argv, dry)
    return _done(ok, "Locking the screen.", "I couldn't lock the screen.", [argv])


def _x_power(a, ctx, dry):
    op = a.args.get("op")
    if op not in ("poweroff", "reboot", "suspend"):
        return ToolResult("Unknown power action.", ok=False)
    argv = ["systemctl", op]
    ok = _launch(ctx, argv, dry)
    msg = {"poweroff": "Shutting down…", "reboot": "Restarting…", "suspend": "Going to sleep…"}[op]
    return _done(ok, msg, "That didn't work.", [argv])


def _x_uninstall(a, ctx, dry):
    name = str(a.args.get("name", "")).strip()
    if a.args.get("guide"):
        return ToolResult(f"To uninstall **{name}**, open **Apps**, select the app, and choose **Uninstall**. "
                          "You can also use the button below; I will ask you to confirm before removal.",
                          buttons=[(f"Uninstall {name}", Action("uninstall", {"name": name},
                                   confirm=f"Uninstall “{name}”?", label=f"Uninstall {name}"))])
    resolver = ctx.app_resolver()
    feature = None
    if resolver is not None and name:
        q = resolver.native.normalize_name(name)
        feature = resolver.feature_exact(q) or resolver.feature_fuzzy(q)
    if feature:
        label = resolver.short_name(feature["name"])
        py = PYTHON
        argv = [py, APP_RESOLVER_PY, "--uninstall", "--name", label, "--feature", feature["id"]]
        ok = _launch(ctx, argv, dry)
        return _done(ok, f"Removing **{label}**. DevOS may ask for your password. "
                     "You can install it again later in DevOS Features, or by asking me.",
                     f"I couldn't start removing {label}.", [argv])
    apps, err = _discover(ctx)
    if apps is None:
        return ToolResult(f"I couldn't read the list of apps ({err}).", ok=False)
    by_name = {getattr(x, "name", ""): x for x in apps}
    entries = {f"app{i}": DesktopApp(desktop_id=getattr(x, "id", ""), path="", name=getattr(x, "name", ""))
               for i, x in enumerate(apps)}
    match, close = match_app(name, entries)
    if match is None:
        hint = f" Did you mean {', '.join(close)}?" if close else ""
        return ToolResult(f"No installed app called **{name}**.{hint} "
                          "If it is one of the DevOS apps, open DevOS Features and untick it.", ok=False,
                          buttons=[("Open DevOS Features", Action("open_app", {"name": "DevOS Features", "strong": True},
                                                                  label="Open DevOS Features"))])
    app = by_name.get(match.name)
    if getattr(app, "system", False) or not getattr(app, "uninstallable", True):
        return ToolResult(f"**{match.name}** is part of the desktop. Open DevOS Features to hide it "
                          "if it is listed there.", ok=False,
                          buttons=[("Open DevOS Features", Action("open_app", {"name": "DevOS Features", "strong": True},
                                                                  label="Open DevOS Features"))])
    argv = [sys.executable or "python3", APPS_MANAGER_PY, "--uninstall", match.desktop_id]
    ok = _launch(ctx, argv, dry)
    return _done(ok, f"Opening the uninstaller for **{match.name}** — confirm there to remove it.",
                 "I couldn't open the uninstaller.", [argv])


def _x_open_tool(a, ctx, dry):
    tool = a.args.get("tool")
    py = sys.executable or "python3"
    if tool == "optimizer":
        argv = [py, OPTIMIZER_PY, "--cleanup"]
        title = "DevOS Optimizer"
    elif tool == "apps":
        argv = [py, APPS_MANAGER_PY]
        title = "Apps"
    elif tool == "security":
        argv = [py, SECURITY_PY]
        title = "DevOS Security"
    elif tool == "clipboard":
        argv = [py, CLIPBOARD_PY]
        title = "Clipboard"
    elif tool == "emoji":
        argv = [py, EMOJI_PY]
        title = "Emoji"
    elif tool == "kids":
        argv = [py, KIDS_MODE_PY]
        title = "Kids Mode"
    elif tool == "broadband":
        argv = [py, BROADBAND_PY]
        title = "Broadband Dial-up"
    else:
        return ToolResult("Unknown tool.", ok=False)
    ok = _launch(ctx, argv, dry)
    return _done(ok, f"Opening **{title}**.", f"I couldn't open {title}.", [argv])


def _x_cleanup_scan(a, ctx, dry):
    opt = ctx.optimizer()
    lines = []
    total = 0
    if opt is None:
        return ToolResult("The cleanup scanner isn't available. Open DevOS Optimizer instead.", ok=False,
                          buttons=[("Open DevOS Optimizer", Action("open_tool", {"tool": "optimizer"}))])
    try:
        results = opt.public_scan(opt.scan_all())
    except Exception as exc:
        return ToolResult(f"The scan failed ({exc}).", ok=False)
    results = sorted(results, key=lambda r: -int(r.get("size") or 0))
    for r in results:
        size = int(r.get("size") or 0)
        if size <= 0:
            continue
        total += size
        lines.append(f"- **{r.get('label', r.get('id'))}:** {human_size(size)}")
    disks = []
    try:
        disks = opt.low_disk(opt.disk_status())
    except Exception:
        pass
    head = (f"I found about **{human_size(total)}** that can be cleaned safely:" if total
            else "Your PC is already clean — there's nothing worth deleting right now.")
    text = "\n".join([head] + lines)
    if disks:
        text += "\n\n⚠ Disk space is low. Uninstalling apps you don't use frees the most space."
    text += "\n\nNothing has been deleted. Open DevOS Optimizer to review and clean."
    return ToolResult(text, data={"total": total},
                      buttons=[("Open DevOS Optimizer", Action("open_tool", {"tool": "optimizer"}))])


def _x_solve(a, ctx, dry):
    """Check the PC for real and carry out the safe next step. Never raises."""
    try:
        _here = os.path.dirname(os.path.abspath(__file__))
        if _here not in sys.path:
            sys.path.insert(0, _here)
        import solve
        result = solve.answer(str(a.args.get("text") or ""))
    except Exception as exc:
        return ToolResult(f"I couldn't finish the check ({exc}). Open DevOS Security.", ok=False,
                          buttons=[("Open DevOS Security", Action("open_tool", {"tool": "security"}))])
    buttons = []
    for spec in result.get("buttons") or []:
        if spec.get("tool"):
            buttons.append((spec["label"], Action("open_tool", {"tool": spec["tool"]})))
        elif spec.get("settings"):
            buttons.append((spec["label"], Action("open_settings", {
                "page": spec["settings"], "title": spec.get("title") or "Settings"})))
    opened = result.get("open")
    if opened == "network":
        _x_open_settings(Action("open_settings", {"page": "kcm_networkmanagement", "title": "Wi-Fi & network"}),
                         ctx, dry)
    elif opened == "security":
        _x_open_tool(Action("open_tool", {"tool": "security"}), ctx, dry)
    return ToolResult(result.get("text") or "I checked this PC.", ok=True, buttons=buttons,
                      data={"solve": result.get("topic"), "blocked": bool(result.get("blocked"))})


def _x_time(a, ctx, dry):
    now = ctx.now()
    return ToolResult(f"It's **{now.strftime('%I:%M %p').lstrip('0')}** on {now.strftime('%A, %d %B %Y')}.")


def _x_islamic(a: Action, ctx: ToolContext, dry: bool) -> ToolResult:
    buttons = [("Open DevOS Islamic", Action("open_app", {"name": "devos-islamic"}))]
    if dry:
        return ToolResult("Islamic texts and prayer times.", ok=True, buttons=buttons)

    topic = str(a.args.get("topic") or "all").lower()
    islamic_dir = os.path.join(COMPONENTS, "islamic")
    if islamic_dir not in sys.path:
        sys.path.insert(0, islamic_dir)
    try:
        import content as islamic_content
        import notifier as islamic_notifier
        import prayer_times as islamic_pt
    except Exception as exc:
        return ToolResult(f"DevOS Islamic could not be loaded: {exc}", ok=False, buttons=buttons)

    now_dt = ctx.now() if hasattr(ctx, "now") else datetime.datetime.now()
    day = now_dt.date()

    ayah = islamic_content.ayah_of_the_day(day)
    hadith = islamic_content.hadith_of_the_day(day)

    if not ayah and not hadith:
        return ToolResult(
            "Authentic Islamic texts have not been downloaded yet. You can download and turn them on via DevOS Islamic.",
            ok=False, buttons=buttons
        )

    lines = []
    if topic == "prayer":
        try:
            settings = islamic_notifier.load_settings()
            loc = islamic_pt.resolve_location(settings)
            local_now = datetime.datetime.now(datetime.timezone.utc).astimezone(loc["tz"])
            times = islamic_pt.times_for_settings(day, settings)
            lines.append(f"### 🕌 Prayer Times ({loc.get('name', 'Local')})")
            lines.append(f"*{local_now.strftime('%A, %d %B %Y')}*")
            lines.append("")
            for p_name in islamic_pt.PRAYERS:
                t_str = times[p_name].strftime("%I:%M %p").lstrip("0")
                p_label = islamic_pt.PRAYER_LABELS.get(p_name, p_name.capitalize())
                lines.append(f"- **{p_label}:** {t_str}")
            return ToolResult("\n".join(lines), ok=True, buttons=buttons)
        except Exception:
            pass

    if topic in ("all", "ayah") and ayah:
        lines.append("### 📖 Ayah of the Day")
        ref = ayah.get("reference", "")
        if ref:
            lines.append(f"**{ref}**\n")
        if ayah.get("ar"):
            lines.append(f"**{ayah['ar']}**\n")
        if ayah.get("en"):
            lines.append(f"- **English:** {ayah['en']} *(Saheeh International)*")
        if ayah.get("bn"):
            lines.append(f"- **বাংলা:** {ayah['bn']} *(মুহিউদ্দীন খান)*")
        lines.append("")

    if topic in ("all", "hadith") and hadith:
        lines.append("### 📜 Hadith of the Day")
        ref = hadith.get("reference", "")
        if ref:
            lines.append(f"**{ref}**\n")
        if hadith.get("ar"):
            lines.append(f"**{hadith['ar']}**\n")
        if hadith.get("en"):
            lines.append(f"- **English:** {hadith['en']}")
        if hadith.get("bn"):
            lines.append(f"- **বাংলা:** {hadith['bn']}")
        lines.append("")

    return ToolResult("\n".join(lines).strip(), ok=True, buttons=buttons)



# ---------------------------------------------------------------------------
# Notes, typing, email, reminders, folders, files, media, closing apps
# ---------------------------------------------------------------------------

TYPING_X11_ONLY_TEXT = "Typing into other apps works only in the standard desktop session (not in this one)."
TYPING_MISSING_TEXT = "Typing into other apps isn't available on this PC (a helper tool is missing)."
CLICK_TO_TYPE_TEXT = "Click where to type, then say it again."

# Window classes of the apps we may type into (WM_CLASS, case-insensitive).
APP_WMCLASS = {
    "devos-browser": "google-chrome", "google-chrome": "google-chrome", "firefox": "firefox",
    "devos-notepad": "notepad.py", "org.kde.konsole": "konsole", "konsole": "konsole", "org.kde.kate": "kate",
    "org.kde.kwrite": "kwrite", "libreoffice-writer": "libreoffice", "org.kde.kcalc": "kcalc",
    "org.kde.dolphin": "dolphin", "devos-thispc": "dolphin", "vlc": "vlc", "devos-code": "vscodium",
    "codium": "vscodium",
}
# Never closed or signalled, whatever the user asks.
PROTECTED_PROCESSES = frozenset((
    "systemd", "init", "xorg", "x", "xwayland", "kwin_x11", "kwin_wayland", "kwin", "plasmashell", "ksmserver",
    "kded5", "kded6", "krunner", "sddm", "dbus-daemon", "dbus-broker", "pipewire", "pipewire-pulse",
    "wireplumber", "pulseaudio", "polkitd", "polkit-kde-authentication-agent-1", "login", "bash", "sh", "zsh",
    "sudo", "pkexec", "networkmanager", "kwalletd5", "kwalletd6", "xdg-desktop-portal", "agetty", "sshd",
))
PYTHON_EXES = ("python3", "python", "python3.12")


def window_class_for(app: DesktopApp) -> str:
    if app.desktop_id in APP_WMCLASS:
        return APP_WMCLASS[app.desktop_id]
    if app.wmclass:
        return app.wmclass
    argv = exec_to_argv(app.exec)
    if argv:
        exe = os.path.basename(argv[0])
        if exe in PYTHON_EXES and len(argv) > 1:
            return os.path.basename(argv[1])
        return exe
    return app.desktop_id.split(".")[-1]


def typing_problem(ctx: ToolContext) -> str:
    """'' when we can type into other windows, else a message for the user."""
    if (ctx.env.get("XDG_SESSION_TYPE") or "").lower() == "wayland":
        return TYPING_X11_ONLY_TEXT
    if not ctx.which("xdotool"):
        return TYPING_MISSING_TEXT
    return ""


def type_command(text: str) -> List[str]:
    return ["xdotool", "type", "--delay", "15", "--", text]


def _xdo_ids(ctx: ToolContext, cls: str) -> List[str]:
    rc, out = ctx.runner(["xdotool", "search", "--onlyvisible", "--class", cls], timeout=5)
    if rc != 0:
        return []
    return [x.strip() for x in out.split() if x.strip().isdigit()]


def _active_window(ctx: ToolContext) -> str:
    rc, out = ctx.runner(["xdotool", "getactivewindow"], timeout=5)
    out = out.strip()
    return out if rc == 0 and out.isdigit() else ""


def _window_title(ctx: ToolContext, wid: str) -> Optional[str]:
    rc, out = ctx.runner(["xdotool", "getwindowname", wid], timeout=5)
    return out.strip() if rc == 0 else None


def wait_for_new_window(ctx: ToolContext, cls: str, before: List[str], timeout: float = 12.0,
                        step: float = 0.25) -> str:
    """Poll for a visible window of `cls` that was not there before; '' on timeout."""
    start = ctx.clock()
    while ctx.clock() - start < timeout:
        new = [w for w in _xdo_ids(ctx, cls) if w not in before]
        if new:
            return new[-1]
        ctx.sleep(step)
    return ""


def settle_window(ctx: ToolContext, wid: str, timeout: float = 4.0, step: float = 0.3) -> bool:
    """Bring `wid` to the front and wait until it is ready for typing: its title
    stops changing (the app finished loading) and it really has the focus."""
    ctx.runner(["xdotool", "windowactivate", "--sync", wid], timeout=6)
    start = ctx.clock()
    last = None
    stable = 0
    while ctx.clock() - start < timeout:
        title = _window_title(ctx, wid)
        if title is not None and title == last:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        last = title
        ctx.sleep(step)
    ctx.sleep(0.5)                     # settle: let the editor take keyboard focus
    return _active_window(ctx) == wid


def _x_write_note(a, ctx, dry):
    text = str(a.args.get("text", ""))
    if not text.strip():
        return ToolResult("There was nothing to write down.", ok=False)
    text = text[:100000]
    folder = os.path.join(user_dir(ctx, "DOCUMENTS", "Documents"), "Notes")
    # first words, without characters that don't belong in a file name (Bangla vowel signs stay)
    words = re.sub(r"[\\/:*?\"<>|,;.!()\[\]{}#&%$@=+~^`'_\s-]+", " ", text).split()[:5]
    title = " ".join(words)[:40].strip() or "Note"
    stamp = ctx.now().strftime("%Y-%m-%d %H-%M")
    base = f"{stamp} {title}"
    path = os.path.join(folder, base + ".txt")
    n = 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{base} ({n}).txt")
        n += 1
    app = str(a.args.get("app", "notepad"))
    if app == "kate" and ctx.which("kate"):
        argv, where = ["kate", path], "Text Editor"
    elif app == "writer" and ctx.which("libreoffice"):
        argv, where = ["libreoffice", "--writer", path], "LibreOffice Writer"
    elif os.path.isfile(NOTEPAD_PY):
        argv, where = [PYTHON, NOTEPAD_PY, path], "Notepad"
    else:
        argv, where = ["xdg-open", path], "the text editor"
    rel = "Documents/Notes/" + os.path.basename(path)
    buttons = [("Open folder", Action("open_path", {"path": folder}, label="Open the Notes folder"))]
    data = {"path": path, "content": text, "folder": folder}
    if not dry:
        os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    ok = _launch(ctx, argv, dry)
    if not ok:
        return ToolResult(f"Saved to **{rel}**, but I couldn't open {where}.", ok=True, plan=[argv],
                          buttons=buttons, data=data)
    return ToolResult(f"Saved to **{rel}** and opened it in {where}.", plan=[argv], buttons=buttons, data=data)


def _x_type_text(a, ctx, dry):
    text = str(a.args.get("text", ""))
    if not text:
        return ToolResult("There was nothing to type.", ok=False)
    try:
        delay = max(0.0, min(5.0, float(a.args.get("delay", 1.0))))
    except (TypeError, ValueError):
        delay = 1.0
    argv = type_command(text)
    if dry:
        return ToolResult("Typing your text into the window you were using.", plan=[argv], data={"delay": delay})
    problem = typing_problem(ctx)
    if problem:
        return ToolResult(problem, ok=False, plan=[argv])
    ctx.sleep(delay)
    wid = _active_window(ctx)
    avoid = str(a.args.get("avoid_window", "") or "")
    if not wid or (avoid and wid == avoid):
        return ToolResult(CLICK_TO_TYPE_TEXT, ok=False, plan=[argv])
    if not settle_window(ctx, wid, timeout=1.5):
        return ToolResult(CLICK_TO_TYPE_TEXT, ok=False, plan=[argv])
    rc, _ = ctx.runner(argv, timeout=max(10, len(text) // 20 + 10))
    return _done(rc == 0, "Typed it.", "I couldn't type the text.", [argv])


def _x_open_app_and_type(a, ctx, dry):
    text = str(a.args.get("text", ""))
    name = str(a.args.get("app", "")).strip()
    if not text or not name:
        return ToolResult("Tell me which app to open and what to type.", ok=False)
    apps = scan_desktop_entries(ctx.app_dirs)
    app, close = match_app(name, apps)
    if app is None:
        hint = f" Did you mean {', '.join('**' + c + '**' for c in close)}?" if close else ""
        return ToolResult(f"I couldn't find an app called **{name}** on this PC.{hint}", ok=False,
                          data={"not_found": True})
    cls = window_class_for(app)
    launch = launch_command(app, ctx.which)
    plan = [launch, ["xdotool", "search", "--sync", "--onlyvisible", "--class", cls],
            ["xdotool", "windowactivate", "--sync", "<new window>"], type_command(text)]
    data = {"desktop_id": app.desktop_id, "wmclass": cls}
    if dry:
        return ToolResult(f"Opening **{app.name}** and typing your text into it.", plan=plan, data=data)
    problem = typing_problem(ctx)
    before = _xdo_ids(ctx, cls) if not problem else []
    if not ctx.launcher(launch):
        return ToolResult(f"I couldn't start {app.name}.", ok=False, plan=plan)
    if problem:
        return ToolResult(f"Opened **{app.name}**. {problem}", ok=False, plan=plan, data=data)
    wid = wait_for_new_window(ctx, cls, before)
    if not wid:
        existing = _xdo_ids(ctx, cls)
        wid = existing[-1] if existing else ""
    if not wid:
        return ToolResult(f"I opened **{app.name}**, but its window didn't appear in time, so I didn't type "
                          "anything.", ok=False, plan=plan, data=data)
    if not settle_window(ctx, wid):
        return ToolResult(f"I opened **{app.name}**, but it didn't come to the front, so I didn't type anything "
                          "(to be safe). " + CLICK_TO_TYPE_TEXT, ok=False, plan=plan, data=data)
    rc, _ = ctx.runner(type_command(text), timeout=max(10, len(text) // 20 + 10))
    return _done(rc == 0, f"Opened **{app.name}** and typed your text.",
                 f"I opened {app.name}, but couldn't type the text.", plan, data=data)


def _x_compose_email(a, ctx, dry):
    to = str(a.args.get("to", ""))
    if not _EMAIL_OK.match(to):
        return ToolResult("That doesn't look like an email address.", ok=False)
    subject = str(a.args.get("subject", ""))[:300]
    body = str(a.args.get("body", ""))[:5000]
    url = mailto_url(to, subject, body)
    argv = ["xdg-open", url]
    ok = _launch(ctx, argv, dry)
    about = f" about **{subject}**" if subject else ""
    return _done(ok, f"Your email to **{to}**{about} is ready in the mail app. Check it and press Send "
                     "there — I never send emails myself.",
                 "I couldn't open the mail app.", [argv], data={"url": url})


def reminder_command(ctx: ToolContext, secs: int, title: str, message: str, unit: str) -> Optional[List[str]]:
    """Command that shows a desktop notification in `secs` seconds, even if DevOS AI is closed."""
    if ctx.which("notify-send"):
        notify = [ctx.which("notify-send"), "--app-name=DevOS AI", "--urgency=critical", "--icon=chronometer",
                  title, message]
    elif ctx.which("kdialog"):
        notify = [ctx.which("kdialog"), "--title", "DevOS AI", "--passivepopup", f"{title}\n{message}", "60"]
    else:
        notify = None
    if ctx.which("systemd-run") and notify:
        argv = ["systemd-run", "--user", "--quiet", "--collect", f"--unit={unit}", f"--on-active={secs}s",
                "--timer-property=AccuracySec=1s"]
        for key in ("DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS"):
            if ctx.env.get(key):
                argv.append(f"--setenv={key}={ctx.env[key]}")
        return argv + notify
    # no user service manager: a small detached helper waits and notifies
    return [PYTHON, TOOLS_PY, "--notify-after", str(secs), title, message]


def _x_reminder(a, ctx, dry):
    try:
        secs = int(a.args.get("seconds", 0))
    except (TypeError, ValueError):
        secs = 0
    if not 1 <= secs <= MAX_REMINDER_S:
        return ToolResult("I can set reminders from 1 second up to 7 days ahead.", ok=False)
    kind = "timer" if a.args.get("kind") == "timer" else "reminder"
    what = re.sub(r"[\x00-\x1f]", " ", str(a.args.get("message", "")))[:200].strip()
    now = ctx.now()
    due = now + datetime.timedelta(seconds=secs)
    when = due.strftime("%I:%M %p").lstrip("0")
    span = human_duration(secs)
    if kind == "timer":
        title, message = "Timer done", f"Your {span} timer is done."
        text = f"Timer set for **{span}** (until {when})."
    else:
        title, message = "Reminder", (what[:1].upper() + what[1:]) if what else "This is your reminder."
        text = (f"Okay, I'll remind you to **{what}** at **{when}** (in {span})." if what
                else f"Okay, I'll remind you at **{when}** (in {span}).")
    unit = f"devos-reminder-{now.strftime('%Y%m%d%H%M%S')}-{secs}"
    argv = reminder_command(ctx, secs, title, message, unit)
    data = {"seconds": secs, "title": title, "message": message, "due": due.isoformat(timespec="seconds")}
    if dry:
        return ToolResult(text, plan=[argv], data=data)
    if argv[0] == "systemd-run":
        rc, out = ctx.runner(argv, timeout=10)
        ok = rc == 0
        if not ok:      # the user manager refused: fall back to the helper
            argv = [PYTHON, TOOLS_PY, "--notify-after", str(secs), title, message]
            ok = ctx.launcher(argv)
    else:
        ok = ctx.launcher(argv)
    if not ok:
        text += " (I'll show it here while DevOS AI stays open.)"
    return ToolResult(text, plan=[argv], data=data)


def _x_create_folder(a, ctx, dry):
    name = _valid_name(str(a.args.get("name", "")))
    where = str(a.args.get("where", "desktop")).lower()
    if not name:
        return ToolResult("That folder name can't be used. Avoid slashes and leading dots.", ok=False)
    if where not in FOLDERS:
        return ToolResult("Unknown place for the folder.", ok=False)
    xdg_key, rel = FOLDERS[where]
    base = user_dir(ctx, xdg_key, rel)
    path = os.path.join(base, name)
    place = os.path.basename(base) if base != ctx.home else "your Home folder"
    argv = ["mkdir", "-p", path]           # shown in the plan; created with os.makedirs
    buttons = [("Open folder", Action("open_path", {"path": path}, label=f"Open {name}"))]
    if os.path.isdir(path):
        return ToolResult(f"**{name}** already exists in {place}.", plan=[argv], buttons=buttons,
                          data={"path": path})
    if not dry:
        os.makedirs(path, exist_ok=True)
    return ToolResult(f"Created the folder **{name}** in {place}.", plan=[argv], buttons=buttons,
                      data={"path": path})


_SKIP_DIRS = {"node_modules", "__pycache__", "snap", "venv", ".venv", "site-packages", "proc"}


def find_files(home: str, name: str, max_depth: int = 4, limit: int = 20, max_entries: int = 60000) -> List[str]:
    """Files under `home` (depth <= max_depth, hidden folders skipped) named like `name`."""
    q = name.lower().strip()
    has_ext = bool(re.search(r"\.[a-z0-9]{1,5}$", q))
    exact, stem, partial = [], [], []
    base_depth = home.rstrip(os.sep).count(os.sep)
    seen = 0
    for root, dirs, files in os.walk(home):
        depth = root.rstrip(os.sep).count(os.sep) - base_depth
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _SKIP_DIRS] if depth < max_depth else []
        for fn in files:
            seen += 1
            low = fn.lower()
            if low.startswith("."):
                continue
            p = os.path.join(root, fn)
            if low == q:
                exact.append(p)
            elif not has_ext and os.path.splitext(low)[0] == q:
                stem.append(p)
            elif len(q) >= 3 and q in low:
                partial.append(p)
        if seen > max_entries:
            break

    def by_recent(paths):
        try:
            return sorted(paths, key=lambda p: -os.path.getmtime(p))
        except OSError:
            return paths
    found = by_recent(exact) or by_recent(stem) or by_recent(partial)
    return found[:limit]


def _inside(path: str, home: str) -> bool:
    try:
        rp, rh = os.path.realpath(path), os.path.realpath(home)
        return os.path.commonpath([rp, rh]) == rh
    except ValueError:
        return False


def _x_open_path(a, ctx, dry):
    path = str(a.args.get("path", "") or "")
    if path:
        if not _inside(path, ctx.home) or not os.path.exists(path):
            return ToolResult("I can only open files and folders in your Home folder.", ok=False)
        argv = ["xdg-open", path]
        ok = _launch(ctx, argv, dry)
        return _done(ok, f"Opening **{os.path.basename(path.rstrip(os.sep)) or 'Home'}**.",
                     "I couldn't open that.", [argv], data={"path": path})
    name = _valid_name(str(a.args.get("name", "")))
    if not name:
        return ToolResult("Which file should I open?", ok=False)
    found = find_files(ctx.home, name)
    if not found:
        return ToolResult(f"I couldn't find a file called **{name}** in your Home folder.", ok=False,
                          data={"found": []})
    if len(found) == 1:
        argv = ["xdg-open", found[0]]
        ok = _launch(ctx, argv, dry)
        rel = os.path.relpath(found[0], ctx.home)
        return _done(ok, f"Opening **{rel}**.", "I couldn't open that file.", [argv], data={"found": found})
    shown = found[:6]
    lines = [f"I found {len(found)} files called **{name}**. Which one?"]
    buttons = []
    for p in shown:
        rel = os.path.relpath(p, ctx.home)
        lines.append(f"- {rel}")
        buttons.append((_elide_mid(rel, 42), Action("open_path", {"path": p}, label=f"Open {rel}")))
    return ToolResult("\n".join(lines), buttons=buttons, data={"found": found})


def _elide_mid(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n // 2 - 1] + "…" + s[-(n // 2):]


MEDIA_OPS = {"play": ("play", "XF86AudioPlay", "Playing."), "pause": ("pause", "XF86AudioPlay", "Paused."),
             "toggle": ("play-pause", "XF86AudioPlay", "Done."), "next": ("next", "XF86AudioNext", "Next track."),
             "previous": ("previous", "XF86AudioPrev", "Previous track."), "stop": ("stop", "XF86AudioStop", "Stopped.")}


def _x_media(a, ctx, dry):
    op = str(a.args.get("op", ""))
    if op == "music":
        music = user_dir(ctx, "MUSIC", "Music")
        if ctx.which("vlc"):
            argv = ["vlc", "--one-instance", music]
        elif ctx.which("elisa"):
            argv = ["elisa", music]
        else:
            argv = ["xdg-open", music]
        ok = _launch(ctx, argv, dry)
        return _done(ok, "Playing the music in your **Music** folder.", "I couldn't open the music player.", [argv])
    if op not in MEDIA_OPS:
        return ToolResult("Unknown media control.", ok=False)
    pc, key, msg = MEDIA_OPS[op]
    if ctx.which("playerctl"):
        argv = ["playerctl", pc]
    elif ctx.which("xdotool") and typing_problem(ctx) == "":
        argv = ["xdotool", "key", key]      # the media key; the desktop passes it to the player
    else:
        return ToolResult("Media controls aren't available on this PC yet. Use the player's own buttons.",
                          ok=False)
    if dry:
        return ToolResult(msg, plan=[argv])
    rc, out = ctx.runner(argv, timeout=5)
    if rc != 0 and argv[0] == "playerctl" and "no players" in out.lower():
        return ToolResult("Nothing is playing right now.", ok=False, plan=[argv])
    return _done(rc == 0, msg, "I couldn't control the player.", [argv])


def _proc_user_pids(ctx: ToolContext, exe: str, script: str = "") -> List[int]:
    """PIDs of the user's own processes running `exe` (or python `script`)."""
    out = []
    proc = ctx.path("/proc")
    try:
        entries = os.listdir(proc)
    except OSError:
        return out
    me = os.getpid()
    for d in entries:
        if not d.isdigit():
            continue
        pid = int(d)
        if pid <= 1 or pid == me:
            continue
        status = read_text(os.path.join(proc, d, "status"))
        m = re.search(r"^Uid:\s+(\d+)", status, re.M)
        if not m or int(m.group(1)) != ctx.uid:
            continue
        try:
            with open(os.path.join(proc, d, "cmdline"), "rb") as fh:
                argv = [x.decode("utf-8", "replace") for x in fh.read().split(b"\0") if x]
        except OSError:
            continue
        if not argv:
            continue
        a0 = os.path.basename(argv[0])
        if script:
            if a0 in PYTHON_EXES and len(argv) > 1 and os.path.basename(argv[1]) == script:
                out.append(pid)
        elif a0 == exe:
            out.append(pid)
    return out


def parse_wmctrl_lx(text: str) -> List[Tuple[str, str, str]]:
    """`wmctrl -lx` -> [(window id, wm_class, title)]."""
    rows = []
    for line in text.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 3 and parts[0].startswith("0x"):
            rows.append((parts[0], parts[2], parts[4] if len(parts) > 4 else ""))
    return rows


def _x_close_app(a, ctx, dry):
    name = str(a.args.get("name", "")).strip()
    apps = scan_desktop_entries(ctx.app_dirs)
    app, close = match_app(name, apps)
    if app is None:
        hint = f" Did you mean {', '.join('**' + c + '**' for c in close)}?" if close else ""
        return ToolResult(f"I couldn't find an app called **{name}**.{hint}", ok=False)
    argv0 = exec_to_argv(app.exec)
    exe = os.path.basename(argv0[0]) if argv0 else ""
    script = os.path.basename(argv0[1]) if exe in PYTHON_EXES and len(argv0) > 1 else ""
    if exe.lower() in PROTECTED_PROCESSES or app.desktop_id in ("devos-chat",):
        return ToolResult(f"**{app.name}** is part of the desktop and can't be closed from here.", ok=False)
    cls = window_class_for(app).lower()
    plan = [["wmctrl", "-lx"], ["wmctrl", "-i", "-c", f"<{cls} windows>"]]
    if dry:
        return ToolResult(f"Closing **{app.name}**.", plan=plan, data={"wmclass": cls, "exe": exe})
    closed = 0
    if ctx.which("wmctrl"):
        rc, out = ctx.runner(["wmctrl", "-lx"], timeout=5)
        if rc == 0:
            for wid, wclass, _title in parse_wmctrl_lx(out):
                if cls and cls in wclass.lower():
                    ctx.runner(["wmctrl", "-i", "-c", wid], timeout=5)
                    closed += 1
    if not closed and (exe or script):
        for pid in _proc_user_pids(ctx, exe, script):
            try:
                ctx.killer(pid, signal.SIGTERM)       # a polite "please quit"
                closed += 1
            except OSError:
                pass
    if not closed:
        return ToolResult(f"**{app.name}** isn't open.", ok=True, plan=plan)
    return ToolResult(f"Closing **{app.name}**. If it has unsaved work it will ask you first.", plan=plan)


FLATHUB_SEARCH_PAGE = "https://flathub.org/apps/search?q="
APP_FINDER_MISSING_TEXT = "Finding apps isn't available on this PC (a DevOS part is missing)."
_FLATPAK_ID = re.compile(r"^[A-Za-z][\w-]*(?:\.[\w-]+){2,}$")


def _x_install_app(a, ctx, dry):
    resolver = ctx.app_resolver()
    if resolver is None:
        return ToolResult(APP_FINDER_MISSING_TEXT, ok=False)
    res = resolver.resolve(query=str(a.args.get("name") or ""), link=str(a.args.get("link") or ""),
                           fetch=ctx.fetch)
    text = resolver.reply_text(res)
    buttons: List[Tuple[str, Action]] = []
    opt = res.get("option") or None
    if opt:
        oname = str(opt.get("name") or "")
        if opt.get("preinstalled"):
            open_name = str(opt.get("builtin") or oname)
            buttons.append((f"Open {oname}", Action("open_app", {"name": open_name, "strong": True},
                                                    label=f"Open {oname}")))
        elif opt.get("kind") == "deb" or opt.get("deb"):
            target_deb = str(opt.get("deb") or opt.get("url") or "")
            buttons.append((f"Install {oname}", Action(
                "install_package", {"name": oname, "deb": target_deb},
                confirm=f"Install {oname} (.deb package)?", label=f"Install {oname}")))
        elif opt.get("kind") == "appimage" or opt.get("appimage"):
            target_appimage = str(opt.get("appimage") or opt.get("url") or "")
            buttons.append((f"Install {oname}", Action(
                "install_package", {"name": oname, "appimage": target_appimage},
                confirm=f"Download and setup {oname} (AppImage)?", label=f"Install {oname}")))
        elif opt.get("kind") == "apt" or opt.get("apt"):
            target_apt = str(opt.get("package") or opt.get("apt") or "")
            buttons.append((f"Install {oname}", Action(
                "install_package", {"name": oname, "apt": target_apt},
                confirm=f"Install {oname} with system package manager?", label=f"Install {oname}")))
        elif opt.get("kind") == "wine" or opt.get("wine"):
            target_wine = str(opt.get("wine") or opt.get("url") or "")
            buttons.append((f"Install {oname}", Action(
                "install_package", {"name": oname, "wine": target_wine},
                confirm=f"Install {oname} with DevOS WinLayer?", label=f"Install {oname}")))
        elif opt.get("feature") or opt.get("flatpak"):
            size = int(opt.get("size_mb") or 0)
            about = f" It downloads about {size} MB." if size else " It downloads from the internet."
            buttons.append((f"Install {oname}", Action(
                "install_package", {"name": oname, "feature": str(opt.get("feature") or ""),
                                    "flatpak": str(opt.get("flatpak") or "")},
                confirm=f"Install {oname}?{about}", label=f"Install {oname}")))
    if res.get("web"):
        buttons.append(("Open web version", Action("open_url", {"url": str(res["web"]), "browser": "default"},
                                                    label="Open the web version")))
    if res.get("download"):
        buttons.append(("Open download page", Action("open_url", {"url": str(res["download"]), "browser": "default"},
                                                      label="Open the download page")))
    name = str(res.get("name") or "").strip()
    if name and res.get("known") and not (opt and opt.get("preinstalled")):
        buttons.append(("Search Flathub", Action("open_url", {"url": FLATHUB_SEARCH_PAGE + urllib.parse.quote(name),
                                                              "browser": "default"}, label="Search Flathub")))
    if name and not opt and not res.get("web") and not res.get("store") and res.get("known") \
            and not res.get("note") and not res.get("why"):
        q = f"{name} download for Windows"
        buttons.append(("Find the Windows download", Action(
            "web_search", {"engine": "google", "query": q, "url": google_search_url(q), "browser": "default"},
            label="Search for the download")))
    return ToolResult(text, buttons=buttons, data={"resolution": res})


def _x_install_package(a, ctx, dry):
    name = str(a.args.get("name") or "the app").strip()[:60]
    feature = str(a.args.get("feature") or "")
    flatpak = str(a.args.get("flatpak") or "")
    deb = str(a.args.get("deb") or "")
    appimage = str(a.args.get("appimage") or "")
    apt = str(a.args.get("apt") or "")
    wine = str(a.args.get("wine") or "")
    url = str(a.args.get("url") or "")
    py = PYTHON
    if feature and re.fullmatch(r"[a-z0-9_-]{1,40}", feature):
        argv = [py, APP_RESOLVER_PY, "--install", "--name", name, "--feature", feature]
    elif _FLATPAK_ID.match(flatpak):
        argv = [py, APP_RESOLVER_PY, "--install", "--name", name, "--flatpak", flatpak]
    elif deb:
        argv = [py, APP_RESOLVER_PY, "--install", "--name", name, "--deb", deb]
    elif appimage:
        argv = [py, APP_RESOLVER_PY, "--install", "--name", name, "--appimage", appimage]
    elif apt and re.fullmatch(r"[a-z0-9][a-z0-9+.-]{1,60}", apt):
        argv = [py, APP_RESOLVER_PY, "--install", "--name", name, "--apt", apt]
    elif wine:
        argv = [py, APP_RESOLVER_PY, "--install", "--name", name, "--wine", wine]
    elif url:
        argv = [py, APP_RESOLVER_PY, "--install", "--name", name, "--url", url]
    else:
        return ToolResult("I can't install that.", ok=False)
    ok = _launch(ctx, argv, dry)
    return _done(ok, f"Installing **{name}**. A progress window shows the download, and {name} opens when it's done.",
                 f"I couldn't start installing {name}.", [argv])


_EXECUTORS = {
    "install_app": _x_install_app, "install_package": _x_install_package,
    "help": _x_help, "about": _x_about, "web_search": _x_web_search, "open_url": _x_open_url, "open_app": _x_open_app,
    "open_search_result": _x_open_search_result, "open_web_page": _x_open_web_page,
    "system_info": _x_system_info, "count_apps": _x_count_apps, "list_apps": _x_list_apps,
    "open_settings": _x_open_settings, "open_folder": _x_open_folder, "volume": _x_volume,
    "brightness": _x_brightness, "screenshot": _x_screenshot, "lock": _x_lock, "power": _x_power,
    "uninstall": _x_uninstall, "open_tool": _x_open_tool, "cleanup_scan": _x_cleanup_scan,
    "solve": _x_solve, "time": _x_time, "islamic": _x_islamic,
    "write_note": _x_write_note, "type_text": _x_type_text, "open_app_and_type": _x_open_app_and_type,
    "compose_email": _x_compose_email, "reminder": _x_reminder, "create_folder": _x_create_folder,
    "open_path": _x_open_path, "media": _x_media, "close_app": _x_close_app,
    "social_post": _x_social_post,
}

ACTION_NAMES = frozenset(_EXECUTORS)


def notify_after(secs: float, title: str, message: str, which: Callable = shutil.which,
                 sleep: Callable[[float], None] = time.sleep) -> int:
    """Fallback reminder helper (no user service manager): wait, then notify."""
    sleep(max(0.0, min(float(secs), MAX_REMINDER_S)))
    if which("notify-send"):
        argv = ["notify-send", "--app-name=DevOS AI", "--urgency=critical", "--icon=chronometer", title, message]
    elif which("kdialog"):
        argv = ["kdialog", "--title", "DevOS AI", "--passivepopup", f"{title}\n{message}", "60"]
    else:
        return 1
    return run_capture(argv)[0]


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--notify-after":
        sys.exit(notify_after(float(sys.argv[2]), sys.argv[3], sys.argv[4]))
    import argparse
    p = argparse.ArgumentParser(description="DevOS AI intent router (dry run)")
    p.add_argument("text", nargs="+")
    p.add_argument("--run", action="store_true", help="execute instead of dry run")
    ns = p.parse_args()
    r = route(" ".join(ns.text))
    print(json.dumps([x.to_json() for x in r.actions], indent=2, ensure_ascii=False))
    for x in r.actions:
        res = execute(x, dry_run=not ns.run)
        print(res.text)
        for argv in res.plan:
            print("  $", " ".join(shlex.quote(s) for s in argv))
