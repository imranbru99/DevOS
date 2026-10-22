#!/usr/bin/env python3
"""
Reading a long project brief the way a person does, so a small local model is never asked to
hold 30,000 characters in its head (and never has to guess the parts it cannot see).

  * split_sections / Brief         the brief's own structure: sections, packages, phases, rules,
                                   an extractive "what I understood", folder tree, questions
  * select_sections                the few sections one phase really needs, verbatim
  * Grounding                      the packages the brief names; anything else from the same
                                   vendor (for example imrandevbd/ledger when the brief lists
                                   only seven imrandevbd packages) is refused or corrected
  * BriefState                     which phases are built, saved in .devos/brief.json so the
                                   user's "go" in a later message continues the same build
"""

import difflib
import json
import os
import re
import shlex
from typing import Any, Dict, List, Optional, Set, Tuple

STATE_FILE = os.path.join(".devos", "brief.json")
SPEC_FILE = os.path.join(".devos", "spec.md")

UNLISTED = "(not in your brief)"

# Packages every Laravel / PHP skeleton carries; never treated as "invented".
BASELINE_PACKAGES = {
    "laravel/laravel", "laravel/framework", "laravel/tinker", "laravel/pail", "laravel/sail", "laravel/pint",
    "fakerphp/faker", "mockery/mockery", "nunomaduro/collision", "phpunit/phpunit",
}

# Vendors of well-known ecosystem packages: never "the user's own vendor", even if the brief lists several of them.
WELL_KNOWN_VENDORS = {
    "laravel", "illuminate", "spatie", "filament", "livewire", "symfony", "pestphp", "phpunit", "nunomaduro",
    "barryvdh", "doctrine", "guzzlehttp", "league", "monolog", "nesbot", "ramsey", "vlucas", "fakerphp", "mockery",
    "maatwebsite", "knuckleswtf", "predis", "google", "firebase", "aws", "stripe", "twilio", "sentry", "larastan",
    "psr", "composer", "friendsofphp", "squizlabs", "brick", "carbonphp", "intervention", "mpdf", "dompdf",
    "tecnickcom", "barryvdh", "bacon", "endroid", "pusher", "inertiajs", "tightenco", "wire-elements", "blade-ui-kit",
    "ezyang", "opis", "staudenmeir", "kirschbaum-development", "bezhansalleh", "awcodes", "guava", "alpinejs",
}

# ======================================================================== text helpers


def shorten(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:(-") + "…"


_ACRONYMS = {"UX", "PWA", "API", "PDF", "SMS", "POS", "UI", "AI", "CSV", "VAT", "HR", "OCR", "RBAC", "SaaS"}


def sentence_case(title: str) -> str:
    """'ANDROID / PWA' -> 'Android / PWA'; titles already in mixed case are kept."""
    if title != title.upper():
        return title
    out = "".join(w if w in _ACRONYMS else w.lower() for w in re.split(r"(\W+)", title))
    return out[:1].upper() + out[1:]


def first_sentence(text: str) -> str:
    m = re.match(r"^(.{1,400}?[.!?])(?:\s+[A-Z(*]|\s*$)", text)
    return m.group(1) if m else text


def plain(text: str) -> str:
    """Markdown stripped: no backticks, bold, or links. Linear time (bounded patterns)."""
    text = re.sub(r"`([^`\n]{0,300})`", r"\1", text)
    text = re.sub(r"\*\*([^*\n]{0,300})\*\*", r"\1", text)
    text = re.sub(r"__([^_\n]{0,300})__", r"\1", text)
    text = re.sub(r"\[([^\]\n]{0,200})\]\([^)\n]{0,300}\)", r"\1", text)
    return text.strip()


# ======================================================================== sections


class Section:
    __slots__ = ("number", "level", "heading", "title", "body")

    def __init__(self, number: str, level: int, heading: str, title: str, body: str):
        self.number = number      # "3.1", "14", or ""
        self.level = level        # heading depth; 0 for text before the first heading
        self.heading = heading    # raw heading text
        self.title = title        # heading without the number and markdown
        self.body = body

    @property
    def text(self) -> str:
        return f"{'#' * max(self.level, 1)} {self.heading}\n{self.body}".rstrip() if self.heading else self.body

    def __repr__(self):
        return f"Section({self.number or '-'}, {self.title[:40]!r}, {len(self.body)} chars)"


_ATX_RE = re.compile(r"^(#{1,6})[ \t]+(.*\S)[ \t]*$")
_NUMBER_RE = re.compile(r"^(\d+(?:\.\d+)*)[ \t]*[.)]?[ \t]+(.*)$")
_BOLD_LINE_RE = re.compile(r"^\*\*([^*\n]{3,100}?)\*\*:?$")
_CAPS_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)[.)]?[ \t]+([A-Z][A-Z0-9 ,&/()'\-]{3,90})$")


def _split(lines: List[str], loose: bool) -> List[Section]:
    sections: List[Section] = []
    heading: Optional[Tuple[int, str]] = None
    body: List[str] = []
    in_fence = False

    def flush():
        raw = heading[1] if heading else ""
        level = heading[0] if heading else 0
        m = _NUMBER_RE.match(plain(raw))
        number, title = (m.group(1), m.group(2)) if m else ("", plain(raw))
        content = "\n".join(body).strip("\n")
        if heading or content.strip():
            sections.append(Section(number, level, raw, title, content))

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
        found: Optional[Tuple[int, str]] = None
        if not in_fence and len(line) - len(line.lstrip()) < 4:
            m = _ATX_RE.match(stripped)
            if m:
                found = (len(m.group(1)), m.group(2).rstrip("# \t") or m.group(2))
            elif (stripped and i + 1 < len(lines) and re.fullmatch(r"(=+|-{3,})", lines[i + 1].strip() or "x")
                  and len(stripped) < 100 and stripped[0] not in ">|-*#`" and (i == 0 or not lines[i - 1].strip())):
                found = (1 if lines[i + 1].strip().startswith("=") else 2, stripped)
            elif loose:
                m = _CAPS_NUM_RE.match(stripped)
                if m:
                    found = (2 if "." not in m.group(1) else 3, f"{m.group(1)}. {m.group(2)}")
                else:
                    m = _BOLD_LINE_RE.match(stripped)
                    if m and not m.group(1).endswith(":"):
                        found = (3, m.group(1))
        if found:
            flush()
            heading, body = found, []
        else:
            body.append(line)
    flush()
    return sections


def split_sections(text: str) -> List[Section]:
    """Sections by heading: '#' headings, underlined (setext) headings, and - when a document has
    few of those - bold-only or '1. UPPER CASE' lines. Headings inside code fences do not count.
    Text before the first heading becomes a section with an empty heading."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    sections = _split(lines, loose=False)
    if sum(1 for s in sections if s.heading) < 3:
        loose = _split(lines, loose=True)
        if sum(1 for s in loose if s.heading) > sum(1 for s in sections if s.heading):
            sections = loose
    return sections


# ======================================================================== packages

# vendor/package (any case), not glued to a longer word; used for scanning text
_NAME = r"[A-Za-z][A-Za-z0-9_-]{1,38}"
_TAIL = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,60}[A-Za-z0-9]"
_PKG_RE = re.compile(r"(?<![A-Za-z0-9_./@\\-])(" + _NAME + r")/(" + _TAIL + r")(?![A-Za-z0-9_/])")
# where a package name is really a package: backticks, composer require, composer.json keys, package links
_PKG_CONTEXT_RES = [
    re.compile(r"`(" + _NAME + r"/" + _TAIL + r")(?:[:@=][^`\n]{0,40})?`"),
    re.compile(r"composer(?:\.phar)?\s+(?:global\s+)?(?:require|req)\s+(?:--?[\w-]+\s+){0,4}(" + _NAME + r"/" + _TAIL + r")"),
    re.compile(r"\"(" + _NAME + r"/" + _TAIL + r")\"\s*:"),
    re.compile(r"(?:packagist\.org/packages|github\.com)/(" + _NAME + r"/" + _TAIL + r")"),
    re.compile(r"^[ \t]*(?:[-*+]|\d{1,2}[.)])[ \t]+\**(" + _NAME + r"/" + _TAIL + r")\**(?=[ \t:,;—–-]|$)", re.M),   # a bullet that starts with one
    re.compile(r"\|[ \t]*\**(" + _NAME + r"/" + _TAIL + r")\**[ \t]*(?=\|)"),                                  # a table cell that is one
]
_FILE_EXT = {"php", "md", "json", "yml", "yaml", "js", "ts", "css", "html", "txt", "xml", "lock", "env", "csv",
             "sql", "sh", "png", "jpg", "svg", "blade", "vue", "toml", "ini", "log"}
_FOLDERS = {"app", "docs", "lang", "config", "resources", "public", "storage", "routes", "database", "tests", "src",
            "vendor", "mobile", "bootstrap", "build", "dist", "node_modules", "lib", "bin", "var", "etc", "usr", "tmp",
            "www", "home", "opt", "mnt", "media", "assets", "images", "static", "scripts", "migrations", "views"}


def _is_file_like(name: str) -> bool:
    tail = name.split("/")[1]
    return "." in tail and tail.rsplit(".", 1)[-1].lower() in _FILE_EXT


def find_packages(text: str) -> List[str]:
    """Package names the text really names (lower case): in backticks, in `composer require`, as
    composer.json keys or in package links. ('hit/miss' in ordinary prose is not a package.)
    Packages of a vendor the text clearly owns are also picked up when written without backticks."""
    text = text or ""
    strict: List[str] = []
    for rx in _PKG_CONTEXT_RES:
        for m in rx.finditer(text):
            name = m.group(1).lower()
            if name not in strict and not _is_file_like(name) and name.split("/")[0] not in _FOLDERS:
                strict.append(name)
    vendors = owned_vendors(text, strict)
    out = list(strict)
    if vendors:
        for m in _PKG_RE.finditer(text):
            name = f"{m.group(1)}/{m.group(2)}".lower()
            if m.group(1).lower() in vendors and name not in out and not _is_file_like(name):
                out.append(name)
    return out


_SUITE_RE = re.compile(r"`?([A-Za-z][A-Za-z0-9_-]{1,38})`?\s+(?:package|packages|library|libraries)\s+(?:suite|collection|family|set)", re.I)


def owned_vendors(text: str, packages: List[str]) -> Set[str]:
    """Vendors the brief owns: it lists several of their packages (and they are not a well-known
    ecosystem vendor), or it says 'vendor/*' or 'the vendor package suite'."""
    count: Dict[str, Set[str]] = {}
    for pkg in packages:
        count.setdefault(pkg.split("/")[0].lower(), set()).add(pkg.lower())
    owned = {v for v, pk in count.items() if len(pk) >= 2}
    for m in re.finditer(r"`?(" + _NAME + r")/\*`?", text or ""):
        owned.add(m.group(1).lower())
    for m in _SUITE_RE.finditer(text or ""):
        owned.add(m.group(1).lower())
    return {v for v in owned if v not in WELL_KNOWN_VENDORS and v not in _FOLDERS and len(v) > 2}


# ======================================================================== phases

_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "zero": 0, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
_PHASE_KINDS = "phase|stage|milestone|sprint"       # not "part" or "step": far too common in ordinary documents
_HEAD_STRIP = re.compile(r"^[\s>*_\-•#|]*(?:\d{1,2}[.)]\s+)?")


def _phase_number(token: str) -> Optional[int]:
    t = token.lower().strip()
    if t.isdigit() and len(t) <= 2:
        return int(t)
    if t in _WORD_NUM:
        return _WORD_NUM[t]
    if t in _ROMAN:
        return _ROMAN[t]
    if len(token) == 1 and token.isalpha() and token.isupper():
        return ord(token) - 64
    return None


def _phase_head(line: str) -> Optional[Tuple[str, int, str, str]]:
    """('phase', 1, 'Foundation', 'Laravel 12, Docker…') for a line that starts a phase, else None."""
    if len(line) > 4000 or "phase" not in line.lower() and not re.search(_PHASE_KINDS, line, re.I):
        return None
    s = _HEAD_STRIP.sub("", plain(line.strip()))
    m = re.match(r"(?i)^(" + _PHASE_KINDS + r")[ \t]+([A-Za-z0-9]{1,6})\b(?:[ \t]+of[ \t]+\d+)?[ \t]*(.*)$", s)
    if not m:
        return None
    n = _phase_number(m.group(2))
    if n is None:
        return None
    rest = m.group(3).lstrip(" \t:.—–-)")
    title, body = rest, ""
    cut = re.search(r"\s[—–-]\s|:\s|:$|\s\(", rest)
    if cut and cut.start() <= 80:
        title, body = rest[:cut.start()], rest[cut.end():] if cut.group(0).strip() != "(" else rest[cut.start():]
    elif len(rest) > 80:
        title, body = "", rest
    return m.group(1).lower(), n, title.strip(" :.—–-*_"), body.strip()


def _phase_tasks(body: str, bullets: List[str]) -> List[str]:
    return bullets if len(bullets) >= 2 else split_tasks(body)


def extract_phases(text: str) -> List[Dict[str, Any]]:
    """The brief's own delivery phases, in any common notation: '**Phase 1 — Foundation:** a, b', a
    '### Phase 2: Title' heading with bullets, 'Phase B', 'Phase III', 'Phase one', 'Stage/Milestone/Step N',
    numbered-list or table rows. Picks the run numbered 1, 2, 3 ... (or 0, 1, 2 ...) that sits
    under a heading about phases/plans/delivery, else the longest one."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    hits: List[Dict[str, Any]] = []
    in_fence = False
    table_phase = False
    section_title = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        atx = _ATX_RE.match(stripped)
        if atx:
            section_title = plain(atx.group(2))
        if stripped.startswith("|"):
            cells = [plain(c) for c in stripped.strip("|").split("|")]
            if cells and re.fullmatch(r"(?i)phases?|stages?|milestones?|steps?", cells[0] or "x"):
                table_phase = True
                continue
            if table_phase and len(cells) >= 2 and not set(stripped) <= set("|-: "):
                n = _phase_number(cells[0])
                if n is not None:
                    hits.append({"i": i, "kind": "phase", "n": n, "title": cells[1], "body": " ".join(cells[2:]),
                                 "heading": False, "section": section_title})
                continue
        else:
            table_phase = False
        head = _phase_head(line)
        if head:
            hits.append({"i": i, "kind": head[0], "n": head[1], "title": head[2], "body": head[3],
                         "heading": bool(atx), "section": section_title})
    best: List[Dict[str, Any]] = []
    best_score = -1.0
    for kind in {h["kind"] for h in hits}:
        group = [h for h in hits if h["kind"] == kind]
        run: List[Dict[str, Any]] = []
        for h in group + [None]:
            if h is not None and run and h["n"] == run[-1]["n"] + 1:
                run.append(h)
                continue
            if run:
                score = len(run) + (3 if re.search(r"phase|plan|roadmap|deliver|milestone|stage", run[0]["section"], re.I) else 0) \
                    + (0.5 if kind == "phase" else 0)
                if len(run) >= 2 and score > best_score:
                    best, best_score = run, score
            run = [h] if h is not None and h["n"] in (0, 1) else []
    phases: List[Dict[str, Any]] = []
    for k, h in enumerate(best):
        nxt = best[k + 1]["i"] if k + 1 < len(best) else len(lines)
        extra: List[str] = []
        bullets: List[str] = []
        own_level = (len(_ATX_RE.match(lines[h["i"]].strip()).group(1)) if h["heading"] else 0)
        for line in lines[h["i"] + 1:nxt]:
            s = line.strip()
            atx = _ATX_RE.match(s)
            if s == "---":
                break
            if atx:
                if not h["heading"] or len(atx.group(1)) <= own_level:
                    break                                   # the next section
                extra.append(plain(atx.group(2)))          # a sub-heading inside a heading-style phase
                continue
            if not s:
                if h["heading"] or not (extra or bullets or h["body"]):
                    continue
                break
            bullet = re.match(r"^(?:[-*•]|\d+[.)])\s+(.*)$", s)
            if bullet:
                bullets.append(plain(bullet.group(1)))
                continue
            if not h["heading"] and (extra or h["body"] or h["title"]) and s[:1].isupper() and not line[:1].isspace():
                break        # a new paragraph after the list, not part of this phase
            extra.append(plain(s))
        title = h["title"]
        if not title and h["heading"] and extra and len(extra[0]) <= 60:
            title = extra.pop(0)                         # '## Phase 1' followed by its title on the next line
        body = " ".join(x for x in [h["body"]] + extra if x).strip()
        tasks = _phase_tasks(body, bullets)
        if not title:
            title = f"Phase {h['n']}"
        full = "; ".join(x for x in [body] + bullets if x)
        phases.append({"n": h["n"], "title": title.strip(), "text": full or title, "tasks": tasks})
    return phases


def phase_gaps(text: str) -> List[int]:
    """Phase numbers the brief mentions after its run ends (for example 4 when it lists 1, 2): a hint the list was cut."""
    found = [h[1] for h in (_phase_head(ln) for ln in text.split("\n")) if h and h[0] == "phase"]
    have = {p["n"] for p in extract_phases(text)}
    return sorted(n for n in set(found) if have and n not in have and n > max(have))


def split_tasks(text: str) -> List[str]:
    """'Laravel 12, Docker, CI (a, b), Install X and Y.' -> separate tasks, ignoring commas in brackets."""
    out, depth, cur = [], 0, []
    for ch in text.replace("; ", ", ").replace("\n", ", "):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur).strip())
    tasks = []
    for item in out:
        for part in re.split(r"(?<=[a-z\)])\.\s+(?=[A-Z])", item):
            part = part.strip(" .")
            if part:
                tasks.append(part)
    return tasks


# ======================================================================== the brief

# An instruction to stop between steps and wait for the user. 'go' must be the user's own word
# ("my go", "I say go"); a Go program or a payment gateway's confirmation is not an instruction.
_PROTOCOL_RES = [re.compile(p, re.I) for p in (
    r"wait\s+(?:for|until)\s+(?:my|your)\s+[\"“'‘]?(?:go|ok|okay|approval|confirmation|confirm|review|feedback|signal|say[- ]?so|reply)\b",
    r"wait\s+until\s+i\s+(?:say|confirm|approve|tell|reply|give|respond|answer)\b",
    r"(?:do\s+not|don'?t|never)\s+(?:start|begin|continue|proceed|move\s+on)\b[^.\n]{0,60}\buntil\s+(?:i|my)\b",
    r"(?:ask|check\s+with)\s+me\s+before\s+(?:starting|moving|proceeding|continuing|each|the\s+next)",
    r"(?:pause|stop|halt)\s+after\s+(?:each|every|the)\s+(?:phase|step|milestone|stage)",
    r"first\s+reply\s+only",
)]
_RULE_START = re.compile(r"^(never|do not|don't|must|always|no\s+\w+ ?(?:hardcoded|placeholder))\b", re.I)


def detect_protocol(text: str) -> bool:
    outside_fences = re.sub(r"```.*?```", " ", text, flags=re.S)
    return any(rx.search(outside_fences) for rx in _PROTOCOL_RES)


class Brief:
    def __init__(self, text: str):
        self.text = text
        self.sections = split_sections(text)
        h1 = next((s for s in self.sections if s.level == 1 and s.heading), None)
        first_line = next((ln for ln in text.splitlines() if ln.strip()), "Project brief")
        self.title = plain(h1.heading)[:120] if h1 else plain(first_line)[:90]
        self.packages = find_packages(text)
        self.owned = owned_vendors(text, self.packages)
        self.phases = extract_phases(text)
        self.protocol = detect_protocol(text)

    # ---- facts
    def stack(self, limit: int = 12) -> List[Tuple[str, str]]:
        rows: List[Tuple[str, str]] = []
        for s in self.sections:
            if not re.search(r"\b(stack|technolog\w*|tech)\b", s.title, re.I):
                continue
            for line in s.body.splitlines():
                if line.strip().startswith("|"):
                    cells = [plain(c) for c in line.strip().strip("|").split("|")]
                    if len(cells) >= 2 and not set(line.strip()) <= set("|-: ") and cells[0].lower() not in ("layer", ""):
                        rows.append((cells[0], cells[1]))
                else:
                    m = re.match(r"^\s*[-*•]\s+\**([^:*\n]{2,40}?)\**\s*[:—–-]\s*\**\s*(.+)$", line)
                    if m:
                        rows.append((plain(m.group(1)), plain(m.group(2))))
            if rows:
                break
        return rows[:limit]

    def modules(self) -> List[str]:
        out = []
        for s in self.sections:
            if s.level >= 3 and re.match(r"^4\.\d+$", s.number or ""):
                out.append(s.title.split("(")[0].strip())
        return out

    def package_sections(self) -> List[Section]:
        return [s for s in self.sections if s.level >= 3 and find_packages(s.heading)]

    def rules(self, limit: int = 12) -> List[str]:
        found: List[str] = []
        keys: Set[str] = set()
        for s in self.sections:
            for raw in s.body.splitlines():
                line = plain(raw.strip().lstrip(">").strip())
                line = re.sub(r"^\d{1,2}[.)]\s*", "", line)
                for sentence in re.split(r"(?<=[.!?])\s+", line[:1500]):
                    sentence = sentence.strip(" -*")
                    key = re.sub(r"\W+", " ", sentence.lower().replace("output", "write")).strip()
                    if _RULE_START.match(sentence) and 25 < len(sentence) < 170 and key not in keys:
                        keys.add(key)
                        found.append(sentence)
        return found[:limit]

    def required_questions(self) -> List[str]:
        """Questions the brief itself says the first reply must contain."""
        out: List[str] = []
        flat = " ".join(self.text.split())
        for m in re.finditer(r"questions?\s*\((?:include|including|e\.g\.|such as|about)[:\s]+(.{1,600}?)\)", flat, re.I):
            for part in re.split(r",\s*(?:and\s+)?", m.group(1)):
                part = part.strip(" .")
                if len(part) > 8:
                    out.append(part[0].upper() + part[1:])
        for m in re.finditer(r"questions\s+(?:about|on|covering):\s*(.{1,400}?)(?:\.\s|$)", flat, re.I):
            for part in re.split(r",\s*(?:and\s+)?|;\s*", m.group(1)):
                part = part.strip(" .")
                if len(part) > 8:
                    out.append(part[0].upper() + part[1:])
        for sentence in re.split(r"(?<=[.!?])\s+", plain(flat[:60000])):
            if re.search(r"\bconfirm (?:it |this )?with me\b", sentence, re.I) and len(sentence) < 400:
                term = re.search(r"[\"“]([^\"”]{3,40})[\"”]", sentence)
                if term and any(term.group(1).lower() in q.lower() for q in out):
                    continue                       # already asked above
                out.append("Please confirm: " + sentence.strip(" ."))
        seen, uniq = set(), []
        for q in out:
            key = re.sub(r"\W+", "", q.lower())[:40]
            if key not in seen:
                seen.add(key)
                uniq.append(q)
        return uniq

    # ---- extractive understanding (no model involved)
    @staticmethod
    def _clean_line(raw: str) -> str:
        line = plain(raw.strip())
        line = re.sub(r"^(?:[-*•>]+\s*|\d{1,2}[.)]\s+)", "", line).strip()
        return re.sub(r"\s+", " ", line)

    def gist(self, section: Section, max_chars: int = 320, parts: int = 2) -> str:
        """The first lines of a section that say something, joined: what the section is about, in the brief's own words."""
        picked: List[str] = []
        in_fence = False
        for raw in section.body.splitlines():
            if raw.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            line = self._clean_line(raw)
            if in_fence or not line or raw.lstrip().startswith("|") or set(line) <= set("-=_ ") or raw.lstrip().startswith("#"):
                continue
            if line.endswith(":"):                          # a label such as 'Rules for yourself:'
                continue
            picked.append(first_sentence(line))
            if len(picked) >= parts + 1 or (len(picked) >= parts and len(" ".join(picked)) >= 110):
                break
        return shorten(" · ".join(picked), max_chars)

    def package_roles(self) -> List[Tuple[str, str]]:
        """(package, what the brief uses it for), from headings like '3.1 `vendor/pkg` — speed and performance'."""
        roles = []
        for s in self.package_sections():
            names = [n for n in find_packages(s.heading) if n.split("/")[0] in self.owned]
            if names:
                role = plain(s.heading).split("—", 1)[1].strip() if "—" in s.heading else s.title
                roles.append((names[0], role))
        return roles

    def understanding(self, max_lines: int = 15) -> List[str]:
        """About fifteen lines that confirm what the brief says, each taken from the brief itself."""
        lines: List[str] = []
        promise = re.search(r"one-line promise:?\**\s*\"?([^\n\"]{1,300})\"?", self.text, re.I)
        users = re.search(r"target users:?\**\s*([^\n]{1,400})", self.text, re.I)
        what = plain(promise.group(1)).strip(" *") if promise else ""
        if users:
            what += (" " if what else "") + "For " + shorten(plain(users.group(1)).strip(" .*"), 140) + "."
        if what:
            lines.append(f"**What it is:** {what}")
        stack = self.stack()
        if stack:
            rows = "".join(f"\n  - {a}: {shorten(re.sub(r'\s*\([^)]*\)', '', b), 90)}" for a, b in stack)
            lines.append("**Fixed stack:**" + rows)
        mods = self.modules()
        if mods:
            lines.append(f"**{len(mods)} modules to build:** " + " · ".join(mods))
        skip = re.compile(r"\b(role|stack|packages?|modules?|phases?|respond|how you|product|data model)\b", re.I)
        for s in self.sections:
            if s.level != 2 or not s.number or skip.search(s.title):
                continue
            gist = self.gist(s)
            if gist:
                lines.append(f"**{sentence_case(s.title.split('(')[0].strip())}:** {gist}")
        rules = self.rules(6)
        if rules:
            lines.append("**Hard rules:** " + " ".join(rules)[:330])
        return lines[:max_lines]

    def open_choices(self) -> List[str]:
        """Places where the brief offers alternatives: the engineer's decisions."""
        out = []
        for layer, choice in self.stack(30):
            m = re.search(r"([A-Za-z][\w+ /.-]{2,40}?)\s+or\s+([A-Za-z][\w+ /.-]{2,40})", choice)
            if m:
                out.append(f"{layer}: {m.group(1).strip()} or {re.split(r' behind | for | with |,', m.group(2))[0].strip()}")
        return out[:8]

    def optional_features(self) -> List[str]:
        out = []
        for raw in self.text.splitlines()[:4000]:
            line = self._clean_line(raw)
            if re.search(r"\boptional\b", line, re.I) and raw.lstrip()[:1] in "-*" and 15 < len(line) < 170 and line not in out:
                out.append(line)
        return out[:6]

    def choice_questions(self) -> List[str]:
        qs = []
        for choice in self.open_choices():
            m = re.match(r"^([^:]+):\s*(.+?) or (.+)$", choice)
            if m:
                qs.append(f"{m.group(1)}: the brief allows {m.group(2)} or {m.group(3)}. Which should I start with?")
        return qs

    def assumptions(self) -> List[str]:
        """What I will take for granted until told otherwise: stated by the brief itself or by its own open points."""
        out: List[str] = []
        if self.protocol:
            out.append("I stop after every phase, run the migrations and tests, and show what passed; I continue only when you say `go`.")
        if re.search(r"\bdev-main\b", self.text):
            out.append("Some packages are `dev-main` only: I set `minimum-stability: dev` with `prefer-stable: true` and pin commits in `composer.lock`, as you wrote.")
        if re.search(r"read its .{0,10}README", self.text, re.I):
            out.append("After installing each package I read its README and config in `vendor/` and follow the real API; where it differs from the brief I tell you instead of inventing methods.")
        for q in self.required_questions():
            if q.startswith("Please confirm:"):
                out.append("Until you confirm — " + q[len("Please confirm:"):].strip() + ".")
        for choice in self.open_choices():
            out.append(f"Open choice — {choice}: I keep it swappable until you answer the question below.")
        return out[:8]

    # ---- folders the brief names
    def path_mentions(self) -> List[str]:
        """Folders and files the brief itself names in backticks (braces expanded), in order."""
        seen: List[str] = []
        for m in re.finditer(r"`([^`\n]{2,200})`", self.text):
            tok = m.group(1).strip()
            if "<" in tok or " " in tok or tok.startswith(("vendor/", "http", "composer", "php ")):
                continue
            bare = tok.lstrip("/")
            lead = bare.split("/")[0].split("{")[0].lower()
            looks_dir = tok.startswith("/") and "/" not in bare and lead in ("mobile", "docs")
            if not (looks_dir or ("/" in bare and lead in _FOLDERS)):
                continue
            if tok.startswith("/") and not looks_dir:
                continue
            for p in _expand_braces(bare):
                p = p.rstrip("/")
                if p and p not in seen and (re.search(r"\.\w{1,6}$", p) or "/" in p or p in ("mobile", "docs")):
                    seen.append(p)
        return seen[:80]

    def folder_tree(self, root: str = "project") -> List[str]:
        node: Dict[str, Any] = {}
        for p in self.path_mentions():
            cur = node
            for seg in p.split("/"):
                cur = cur.setdefault(seg, {})
        lines = [root + "/"]

        def walk(n: Dict[str, Any], prefix: str):
            keys = list(n)
            for i, k in enumerate(keys):
                last = i == len(keys) - 1
                is_file = "." in k and not n[k]
                lines.append(f"{prefix}{'└── ' if last else '├── '}{k}{'' if is_file else '/'}")
                if n[k]:
                    walk(n[k], prefix + ("    " if last else "│   "))
        walk(node, "")
        if re.search(r"\blaravel\b", self.text, re.I):
            lines.append("(+ the standard Laravel skeleton: bootstrap, public, resources, routes, storage, tests …)")
        return lines if len(lines) > 2 else []

    def card(self, max_chars: int = 3200) -> str:
        """A short deterministic summary of the whole brief: what it is, the stack, the allowed
        packages, the phases and the hard rules. Small enough to send with every request."""
        lines = [f"BRIEF: {self.title}"]
        promise = re.search(r"one-line promise:?\**\s*\"?([^\n\"]{1,300})\"?", self.text, re.I)
        if promise:
            lines.append("Promise: " + plain(promise.group(1)).strip(" *"))
        stack = self.stack()
        if stack:
            lines.append("Fixed stack: " + "; ".join(f"{a}: {b}" for a, b in stack)[:700])
        if self.owned:
            own = sorted(p for p in self.packages if p.split("/")[0] in self.owned)
            lines.append(f"The user's own packages (use ONLY these from {', '.join(sorted(self.owned))}; "
                         f"never invent others): " + ", ".join(own))
        if self.phases:
            lines.append("Phases: " + "; ".join(f"{p['n']} {p['title']}" for p in self.phases))
        rules = self.rules()
        if rules:
            lines.append("Hard rules:\n- " + "\n- ".join(rules))
        return "\n".join(lines)[:max_chars]


def _expand_braces(path: str) -> List[str]:
    m = re.search(r"\{([^{}]+)\}", path)
    if not m:
        return [path]
    out: List[str] = []
    for part in m.group(1).split(","):
        out.extend(_expand_braces(path[:m.start()] + part.strip() + path[m.end():]))
    return out[:200]


def looks_like_brief(b: Brief) -> bool:
    """A structured specification (phases, or many headed sections), not a pasted log or snippet."""
    headed = sum(1 for s in b.sections if s.heading)
    return len(b.phases) >= 2 or (headed >= 5 and len(b.text) > 3000) or (b.protocol and headed >= 3)


# ----------------------------------------------------------------- section selection

_STOP = set("""this that with from have will your their they them then than into onto over under also each every
more most such only other some what when where which while about after before being between both could would should
those these there here make sure using used uses use build built need needs must shall them its our out for the and
are not but you can all any per via one two three laravel install installed package packages suite phase phases""".split())


def _words(text: str, min_len: int = 4) -> List[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9]{%d,}" % (min_len - 1), text.lower()) if w not in _STOP]


def _stem(word: str) -> str:
    """Crude stem so 'invoices' meets 'invoicing' and 'payments' meets 'payment'."""
    return word[:6] if len(word) >= 7 else word.rstrip("s")


def _aliases(section: Section) -> Set[str]:
    """Names a phase may use for this package section: 'laravel-ai-hub', 'ai-hub'."""
    out = set()
    for pkg in find_packages(section.heading):
        tail = pkg.split("/")[1]
        out.add(tail)
        if tail.startswith("laravel-"):
            out.add(tail[len("laravel-"):])
    return out


_ALWAYS_RE = re.compile(r"\b(working rules|rules|constraints|conventions|non-negotiable|standards|tech(?:nology)? stack|stack)\b", re.I)


def select_sections(brief: "Brief", query: str, budget: int = 9000, per_section: int = 3200,
                    always: bool = True) -> str:
    """The brief sections a piece of work needs, verbatim and in document order: the sections the
    query names (section numbers, package names), the ones it shares words with, and the standing
    rules and stack. A brief with no usable headings yields its best-matching paragraphs instead."""
    q = query.lower()
    q_words = set(_words(query))
    q_stems = {_stem(w) for w in q_words}
    q_short = {w for w in _words(query, 3) if len(w) == 3}      # acronyms: PWA, FCM, POS ...
    refs = set(re.findall(r"(?:section|sections|§)\s*(\d+(?:\.\d+)?)", q)) | set(re.findall(r"\((\d+\.\d+)\)", q))
    scored = []
    for idx, s in enumerate(brief.sections):
        if not s.heading:
            continue
        if len(re.findall(r"^\W*\**\s*(?:Phase|Stage|Milestone)\s+\w", s.body, re.I | re.M)) >= 2:
            continue                       # the phase list itself: the phase text is already in the request
        score = 0.0
        title_l = s.title.lower()
        title_words = _words(_PKG_RE.sub(" ", s.title), 3)
        title_stems = {_stem(w) for w in title_words if len(w) >= 4}
        if s.number and s.number in refs:
            score += 100
        for alias in _aliases(s):
            if re.search(r"(?<![\w-])" + re.escape(alias) + r"(?![\w-])", q):
                score += 90
        if always and _ALWAYS_RE.search(title_l):
            score += 60
        score += 14 * len(q_stems & title_stems) + 14 * len(q_short & set(title_words))
        body_l = s.body.lower()
        score += sum(min(body_l.count(w), 3) * 0.5 for w in q_words if len(w) > 4)
        scored.append((score, idx, s))
    chosen, used = [], 0
    for score, idx, s in sorted(scored, key=lambda t: -t[0]):
        if score < 8 or used >= budget:
            continue
        text = s.text if len(s.text) <= per_section else s.text[:per_section].rstrip() + "\n… (section continues in .devos/spec.md)"
        if used + len(text) > budget and chosen:
            continue
        chosen.append((idx, text))
        used += len(text)
    if chosen:
        return "\n\n".join(t for _, t in sorted(chosen))
    # no headed sections matched: the best paragraphs of the text itself
    paras = [p.strip() for p in re.split(r"\n\s*\n", brief.text) if p.strip()]
    ranked = sorted(range(len(paras)), key=lambda i: -(sum(paras[i].lower().count(w) for w in q_words) or 0))
    pick, used = [], 0
    for i in ranked:
        if used + len(paras[i]) > budget and pick:
            continue
        pick.append(i)
        used += len(paras[i])
        if used >= budget:
            break
    return "\n\n".join(paras[i][:per_section] for i in sorted(pick))


# ======================================================================== grounding


def _camel(tail: str) -> str:
    tail = re.sub(r"^laravel-", "", tail)
    return "".join(part.capitalize() for part in re.split(r"[-_.]", tail))


class Grounding:
    """What the brief allows. Built from the brief's text; the brief itself is saved in .devos/spec.md."""

    def __init__(self, brief: Brief):
        self.allowed: Set[str] = {p.lower() for p in brief.packages} | BASELINE_PACKAGES
        self.owned: Set[str] = {v.lower() for v in brief.owned}
        self.spec_lower = brief.text.lower()
        self._owned_names = sorted(p for p in brief.packages if p.split("/")[0] in self.owned)
        self._owned_re = (re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(re.escape(v) for v in sorted(self.owned)) +
                                     r")(?:/|\\\\)(" + _TAIL + r")(?![A-Za-z0-9_])", re.I) if self.owned else None)
        # PHP namespaces of the owned vendors, as the brief writes them: ImranDevBd\AiHub, ImranDev\UnicodePdf
        self.namespaces: Set[str] = set()
        self._ns_segments: Set[str] = {_camel(p.split("/")[1]).lower() for p in self._owned_names}
        for m in re.finditer(r"\b([A-Z][A-Za-z0-9]{2,30})\\{1,2}([A-Z][A-Za-z0-9]{1,40})", brief.text):
            ns = m.group(1).lower()
            if any(v.startswith(ns) or ns.startswith(v) for v in self.owned):
                self.namespaces.add(ns)
                self._ns_segments.add(m.group(2).lower())

    @property
    def active(self) -> bool:
        return bool(self.owned)

    # ---- single names
    def suggest(self, name: str) -> Optional[str]:
        """The listed package the model most likely meant (imrandevbd/ai-hub -> imrandevbd/laravel-ai-hub)."""
        vendor, _, tail = name.lower().partition("/")
        pool = [p for p in self._owned_names if p.startswith(vendor + "/")] or self._owned_names
        tails = {p: p.split("/")[1] for p in pool}
        for pkg, t in tails.items():
            if t == tail or t.endswith("-" + tail) or tail.endswith("-" + t):
                return pkg
        close = difflib.get_close_matches(tail, list(tails.values()), n=1, cutoff=0.72)
        return next((p for p, t in tails.items() if close and t == close[0]), None)

    def is_invented(self, name: str, ignore: Tuple[str, ...] = ()) -> bool:
        """True for a package of the brief's own vendor that the brief does not list."""
        name = name.lower()
        vendor, _, tail = name.partition("/")
        return vendor in self.owned and name not in self.allowed and tail not in ignore

    def third_party_unmentioned(self, name: str) -> bool:
        """A package from another vendor whose name appears nowhere in the brief (and is not a skeleton default)."""
        name = name.lower()
        if name in self.allowed or name.split("/")[0] in self.owned or name.startswith(("ext-", "lib-")) or name == "php":
            return False
        tail = name.split("/")[-1]
        first = tail.split("-")[0]
        if tail in self.spec_lower:
            return False
        if first not in ("laravel", "symfony") and len(first) >= 4 and first in self.spec_lower:
            return False
        if tail.startswith("laravel-") and tail[len("laravel-"):] in self.spec_lower:
            return False
        return True

    # ---- text, files, commands
    def invented_in_text(self, text: str, ignore: Tuple[str, ...] = ()) -> List[str]:
        """Packages of the brief's own vendor in this text (any case; also in URLs and vendor/ paths)
        that the brief does not list; and PHP namespaces of that vendor the brief does not use."""
        found: Set[str] = set()
        if self._owned_re is not None:
            for m in self._owned_re.finditer(text or ""):
                name = f"{m.group(1)}/{m.group(2)}".lower()
                if not _is_file_like(name) and self.is_invented(name, ignore):
                    found.add(name)
        for m in re.finditer(r"\b([A-Za-z][A-Za-z0-9]{2,30})\\{1,2}([A-Z][A-Za-z0-9]{1,40})", text or ""):
            if m.group(1).lower() in self.namespaces and m.group(2).lower() not in self._ns_segments \
                    and m.group(2).lower() not in ignore:
                found.add(f"{m.group(1)}\\{m.group(2)}")
        return sorted(found)

    def ground_text(self, text: str) -> Tuple[str, List[str]]:
        """Replace invented package names in prose with the listed package they most likely mean,
        or drop them. Returns (clean text, names that were changed)."""
        changed: List[str] = []
        if self._owned_re is None:
            return text, changed

        def repl(m):
            name = f"{m.group(1)}/{m.group(2)}".lower()
            if not self.is_invented(name) or _is_file_like(name):
                return m.group(0)
            changed.append(name)
            return self.suggest(name) or UNLISTED

        return self._owned_re.sub(repl, text), changed

    def owned_mentions(self, text: str) -> List[str]:
        """Every package of the brief's own vendor named in this text (listed or not), lower case."""
        if self._owned_re is None:
            return []
        return sorted({f"{m.group(1)}/{m.group(2)}".lower() for m in self._owned_re.finditer(text or "")
                       if not _is_file_like(f"{m.group(1)}/{m.group(2)}")})

    def composer_problems(self, names: List[str], ignore: Tuple[str, ...] = ()) -> List[str]:
        """Blocking problems: packages of the brief's own vendor that the brief does not list."""
        bad = []
        for n in names:
            n = n.lower()
            if self.is_invented(n, ignore):
                hint = self.suggest(n)
                bad.append(f"{n} is not in the brief" + (f" (did you mean {hint}?)" if hint else ""))
        return bad

    def composer_warnings(self, names: List[str]) -> List[str]:
        """Packages from other vendors that the brief never mentions: allowed, but the agent is told to justify them."""
        return [f"{n.lower()} is not mentioned in the brief" for n in names if self.third_party_unmentioned(n)]

    def allowed_owned(self) -> List[str]:
        return list(self._owned_names)


_COMPOSER_OPTS_WITH_VALUE = {"-d", "--working-dir", "--prefer-install", "--repository", "--repository-url", "--stability",
                             "-s", "--ignore-platform-req", "--with", "--no-scripts-dir", "--keep-vcs-dir"}


def composer_command_packages(command: str) -> List[str]:
    """Package names a `composer require/create-project` command would install (also inside `bash -c`)."""
    try:
        tokens = shlex.split(command.replace("&&", " ; ").replace("||", " ; ").replace("|", " ; "), posix=True)
    except ValueError:
        tokens = command.split()
    names: List[str] = []
    i = 0
    active = ""
    positional = 0
    skip_next = False
    while i < len(tokens):
        tok = tokens[i]
        i += 1
        if tok in ("bash", "sh", "zsh", "dash") and i < len(tokens) and tokens[i] in ("-c", "-lc", "-ic"):
            if i + 1 < len(tokens):
                names.extend(composer_command_packages(tokens[i + 1]))
            i += 2
            continue
        if tok in (";", "&", "(", ")", "{", "}"):
            active, positional = "", 0
            continue
        base = os.path.basename(tok)
        if base in ("composer", "composer.phar", "composer2"):
            active, positional = "", 0
            continue
        if tok in ("require", "req", "r", "create-project", "create"):
            active = "create" if tok.startswith("create") else "require"
            positional = 0
            continue
        if not active:
            continue
        if skip_next:
            skip_next = False
            continue
        if tok.startswith("-"):
            if tok in _COMPOSER_OPTS_WITH_VALUE:
                skip_next = True
            continue
        name = re.split(r"[:=@]", tok, 1)[0].lower()
        if active == "create":
            positional += 1
            if positional > 1:
                continue                       # target directory / version
        if name.startswith((".", "/", "~")) or not re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", name):
            continue
        names.append(name)
    return names


def composer_json_packages(content: str) -> List[str]:
    """Dependencies a composer.json asks for (require and require-dev), not its own 'name'."""
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            names = []
            for key in ("require", "require-dev"):
                block = data.get(key)
                if isinstance(block, dict):
                    names.extend(str(k).lower() for k in block)
            return [n for n in names if "/" in n]
    except ValueError:
        pass
    return [n.lower() for n in re.findall(r'"([A-Za-z0-9_.-]{1,40}/[A-Za-z0-9_.-]{1,60})"\s*:\s*"', content or "")]


def composer_json_own_name(content: str) -> str:
    try:
        data = json.loads(content)
        if isinstance(data, dict) and isinstance(data.get("name"), str):
            return data["name"].split("/")[-1].lower()
    except ValueError:
        pass
    return ""


# ======================================================================== state


class BriefState:
    """Where the build stands, saved in the project so 'go' in a later message continues it.
    Which phase is next is always derived from which phases are done."""

    def __init__(self, root: str, data: Optional[Dict[str, Any]] = None):
        self.root = root
        d = data or {}
        self.title: str = str(d.get("title", ""))
        self.protocol: bool = bool(d.get("protocol", False))
        phases = d.get("phases", [])
        self.phases: List[Dict[str, Any]] = [p for p in phases if isinstance(p, dict) and isinstance(p.get("n"), int)] \
            if isinstance(phases, list) else []
        done = d.get("done", {})
        self.done: Dict[str, Dict[str, Any]] = {str(k): v for k, v in done.items() if isinstance(v, dict)} \
            if isinstance(done, dict) else {}
        answers = d.get("answers", [])
        self.answers: List[str] = [str(a) for a in answers] if isinstance(answers, list) else []
        self.asked: bool = bool(d.get("asked", False))      # the understanding reply was given
        self.spec_hash: str = str(d.get("spec_hash", ""))

    @classmethod
    def load(cls, root: str) -> Optional["BriefState"]:
        try:
            with open(os.path.join(root, STATE_FILE), encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return None
        state = cls(root, data) if isinstance(data, dict) else None
        return state if state and state.phases else None

    @classmethod
    def create(cls, root: str, brief: Brief) -> "BriefState":
        import hashlib
        return cls(root, {"title": brief.title, "protocol": brief.protocol, "phases": brief.phases,
                          "spec_hash": hashlib.sha1(brief.text.encode("utf-8", "replace")).hexdigest()})

    def _payload(self) -> Dict[str, Any]:
        return {"title": self.title, "protocol": self.protocol, "phases": self.phases, "done": self.done,
                "answers": self.answers, "asked": self.asked, "spec_hash": self.spec_hash}

    def save(self) -> None:
        """Write the state; when another run saved meanwhile, keep what it recorded (phases done, answers)."""
        path = os.path.join(self.root, STATE_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, encoding="utf-8") as handle:
                other = json.load(handle)
            if isinstance(other, dict) and other.get("spec_hash", "") == self.spec_hash:
                for k, v in (other.get("done") or {}).items():
                    if isinstance(v, dict):
                        self.done.setdefault(str(k), v)
                for a in other.get("answers") or []:
                    if str(a) not in self.answers:
                        self.answers.append(str(a))
        except (OSError, ValueError):
            pass
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self._payload(), handle, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

    def clear(self) -> None:
        for rel in (STATE_FILE, SPEC_FILE):
            try:
                os.remove(os.path.join(self.root, rel))
            except OSError:
                pass

    # ---- derived from `done`
    @property
    def total(self) -> int:
        return len(self.phases)

    def numbers(self) -> List[int]:
        return sorted(p["n"] for p in self.phases)

    def remaining(self) -> List[int]:
        return [n for n in self.numbers() if str(n) not in self.done]

    @property
    def next(self) -> int:
        rest = self.remaining()
        return rest[0] if rest else (self.numbers()[-1] + 1 if self.phases else 1)

    @property
    def finished(self) -> bool:
        return bool(self.phases) and not self.remaining()

    def phase(self, n: int) -> Optional[Dict[str, Any]]:
        return next((p for p in self.phases if p["n"] == n), None)

    def mark_done(self, n: int, files: List[str], summary: str) -> None:
        self.done[str(n)] = {"files": files, "summary": summary}

    @property
    def awaiting(self) -> bool:
        """The user has a next step to approve."""
        return self.protocol and self.asked and not self.finished


def load_spec(root: str) -> Optional[Brief]:
    try:
        with open(os.path.join(root, SPEC_FILE), encoding="utf-8", errors="replace") as handle:
            return Brief(handle.read())
    except OSError:
        return None


def save_spec(root: str, text: str, name: str = SPEC_FILE) -> None:
    path = os.path.join(root, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", errors="replace") as handle:
        handle.write(text.rstrip() + "\n")


# ======================================================================== commands

_END = r"[\s.!,]*$"
_GO = re.compile(r"^(?:go|go ahead|go on|continue|proceed|next|yes|yes please|y|ok|okay|ok go|start|begin|do it)" + _END, re.I)
_GO_ALL = re.compile(r"^(?:(?:go|run|do|build|continue)\s+(?:all|everything|the rest|remaining)(?:\s+phases)?|all phases|"
                     r"go on and (?:finish|build)(?: it)?(?: all)?)" + _END, re.I)
_GO_N = re.compile(r"^(?:(?:go|redo|retry)\s+(?:with\s+)?(?:phase\s+)?|(?:run|build|start|continue|do)\s+(?:with\s+)?phase\s+)(\d{1,2})" + _END, re.I)
_RESET = re.compile(r"^(?:reset|forget|clear|drop|discard)\s+(?:the\s+|my\s+|this\s+)?(?:saved\s+)?(?:brief|spec|build)(?:\s+plan)?" + _END, re.I)
_STATUS = re.compile(r"^(?:status|progress|where are we|what(?:'s| is) done)\s*\??" + _END, re.I)
_IMPERATIVE = re.compile(r"^(?:make|build|create|add|fix|implement|write|generate|install|update|change|remove|delete|"
                         r"refactor|rename|move|show|explain|why|how|what|list|read|open|scan|test)\b", re.I)
_ANSWERS = re.compile(r"^\s*(?:\d{1,2}\s*[.):-]|q\d+\s*[.):-]|answers?\b)", re.I)


def parse_command(text: str, state: "BriefState") -> Optional[Tuple[str, Optional[int]]]:
    """What the user's short message means for a saved build: ('go', n) ('go_all', None) ('reset', None)
    ('status', None) ('answers', None) - or None when it is an ordinary new request. Patterns match the
    whole message, so 'go to the settings page and rename Save' stays an ordinary request."""
    t = " ".join(text.strip().split())
    if not t:
        return None
    if len(t) <= 60:
        if _RESET.match(t):
            return ("reset", None)
        if _GO_ALL.match(t):
            return ("go_all", None) if not state.finished else None
        m = _GO_N.match(t)
        if m:
            return ("go", int(m.group(1)))
        if _GO.match(t):
            if state.finished:
                return ("go", None) if t.lower().startswith("go") else None
            return ("go", state.next)
        if _STATUS.match(t):
            return ("status", None)
    if state.protocol and state.asked and not state.done and len(t) <= 2500:
        if _ANSWERS.match(text.strip()) or not _IMPERATIVE.match(t):   # answers to the questions, not a new task
            return ("answers", None)
    return None


def bare_command(text: str) -> Optional[str]:
    """'go' / 'go all' / 'go 3' typed when no brief is saved in this folder."""
    t = " ".join(text.strip().split())
    if len(t) > 40:
        return None
    if _GO_ALL.match(t) or _GO_N.match(t) or re.match(r"^go" + _END, t, re.I):
        return t
    return None


# ======================================================================== streaming filter


class StreamGrounder:
    """Streamed model text, cleaned at word boundaries so an invented package name can never reach the screen."""

    def __init__(self, grounding: Optional[Grounding], emit):
        self.grounding = grounding
        self.emit = emit
        self.buf = ""
        self.changed: List[str] = []
        self.shown: List[str] = []

    def _out(self, text: str) -> None:
        if not text:
            return
        if self.grounding and self.grounding.active:
            text, changed = self.grounding.ground_text(text)
            self.changed.extend(changed)
        self.shown.append(text)
        self.emit(text)

    def feed(self, token: str) -> None:
        self.buf += token
        cut = max(self.buf.rfind(" "), self.buf.rfind("\n"))
        if cut >= 0:
            self._out(self.buf[:cut + 1])
            self.buf = self.buf[cut + 1:]

    def finish(self) -> None:
        if self.buf:
            self._out(self.buf)
            self.buf = ""

    @property
    def text(self) -> str:
        return "".join(self.shown)
