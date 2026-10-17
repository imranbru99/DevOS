#!/usr/bin/env python3
"""
A small, forgiving unified-diff applier for DevOS Code Agent (pure Python, no
`patch` or git needed).

Local models write diffs with wrong line numbers, bare "@@" hunk headers,
missing leading spaces on context lines and trailing-whitespace drift. Hunks
are therefore located by their content: first at the stated line, then
anywhere in the file (closest match wins), then ignoring trailing
whitespace. A hunk that cannot be found is an error, never a guess.
"""

import difflib
import re
from typing import Callable, Dict, List, Optional, Tuple

HUNK_RE = re.compile(r"^@@+\s*-?(\d+)?(?:,(\d+))?\s*\+?(\d+)?(?:,(\d+))?\s*@@+")


class PatchError(ValueError):
    pass


class FilePatch:
    def __init__(self, old_path: Optional[str], new_path: Optional[str]):
        self.old_path = old_path
        self.new_path = new_path
        self.hunks: List[Tuple[int, List[str]]] = []  # (stated old start, lines with prefix)

    @property
    def path(self) -> str:
        return self.new_path or self.old_path or ""


def _clean_path(raw: str) -> Optional[str]:
    raw = raw.strip().split("\t")[0].strip()
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    if raw in ("/dev/null", "dev/null", ""):
        return None
    if raw.startswith(("a/", "b/")) and len(raw) > 2:
        raw = raw[2:]
    return raw


def parse_patch(text: str, default_path: Optional[str] = None) -> List[FilePatch]:
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    files: List[FilePatch] = []
    current: Optional[FilePatch] = None
    hunk: Optional[List[str]] = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
            current = FilePatch(_clean_path(line[4:]), _clean_path(lines[i + 1][4:]))
            files.append(current)
            hunk = None
            i += 2
            continue
        if line.startswith(("diff --git", "index ", "new file mode", "deleted file mode", "similarity")):
            hunk = None
            i += 1
            continue
        if line.startswith("@@"):
            if current is None:
                if not default_path:
                    raise PatchError("The patch does not say which file it changes (add --- a/file and +++ b/file).")
                current = FilePatch(default_path, default_path)
                files.append(current)
            match = HUNK_RE.match(line)
            start = int(match.group(1)) if match and match.group(1) else 0
            hunk = []
            current.hunks.append((start, hunk))
            i += 1
            continue
        if hunk is not None:
            if line.startswith(("+", "-", " ")):
                hunk.append(line)
            elif line == "\\ No newline at end of file":
                pass
            else:
                hunk.append(" " + line)  # context line that lost its leading space
        i += 1
    files = [f for f in files if f.hunks or f.new_path is None]
    if not files:
        raise PatchError("No changes found in the patch (it needs @@ hunks with - and + lines).")
    return files


def _find(haystack: List[str], needle: List[str], hint: int, loose: bool) -> int:
    if not needle:
        return min(max(hint, 0), len(haystack))
    norm = (lambda s: s.rstrip()) if loose else (lambda s: s)
    target = [norm(s) for s in needle]
    candidates = [i for i in range(len(haystack) - len(needle) + 1)
                  if [norm(s) for s in haystack[i:i + len(needle)]] == target]
    if not candidates:
        return -1
    return min(candidates, key=lambda i: abs(i - hint))


def apply_hunks(original: str, hunks: List[Tuple[int, List[str]]], path: str = "") -> str:
    ends_with_newline = original.endswith("\n") or original == ""
    lines = original.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    offset = 0
    for number, (start, body) in enumerate(hunks, 1):
        old = [l[1:] for l in body if l[:1] in (" ", "-")]
        new = [l[1:] for l in body if l[:1] in (" ", "+")]
        # Blank context lines at the hunk edges are often invented; drop them if needed.
        hint = max(start - 1 + offset, 0)
        at = _find(lines, old, hint, loose=False)
        if at < 0:
            at = _find(lines, old, hint, loose=True)
        if at < 0:
            trimmed_old, trimmed_new = _trim_blank_edges(old, new)
            if trimmed_old != old:
                at = _find(lines, trimmed_old, hint, loose=True)
                if at >= 0:
                    old, new = trimmed_old, trimmed_new
        if at < 0:
            where = f" in {path}" if path else ""
            raise PatchError(f"Hunk {number}{where} does not match the file. Read the file again and "
                             "copy the unchanged lines exactly.")
        lines[at:at + len(old)] = new
        offset += len(new) - len(old)
    text = "\n".join(lines)
    if lines and ends_with_newline:
        text += "\n"
    return text


def _trim_blank_edges(old: List[str], new: List[str]):
    old, new = list(old), list(new)
    while old and new and old[0].strip() == "" and new[0].strip() == "":
        old.pop(0)
        new.pop(0)
    while old and new and old[-1].strip() == "" and new[-1].strip() == "":
        old.pop()
        new.pop()
    return old, new


def apply_patch(patch: str, read: Callable[[str], Optional[str]],
                default_path: Optional[str] = None) -> Dict[str, Optional[str]]:
    """Apply a unified diff. `read(path)` returns the current text or None for a
    missing file. Returns {path: new text, or None when the file is deleted}.
    Nothing is written here."""
    result: Dict[str, Optional[str]] = {}
    for fp in parse_patch(patch, default_path):
        if fp.new_path is None:
            result[fp.old_path or ""] = None
            continue
        source_path = fp.old_path or fp.new_path
        current = result.get(source_path) if source_path in result else read(source_path)
        if current is None:
            current = ""
            if fp.old_path is not None and any(l.startswith(("-", " ")) for _, h in fp.hunks for l in h):
                raise PatchError(f"{source_path} does not exist yet; use write_file to create it.")
        result[fp.new_path] = apply_hunks(current, fp.hunks, fp.new_path)
        if fp.old_path and fp.old_path != fp.new_path:
            result[fp.old_path] = None
    return result


def unified_diff(path: str, old: Optional[str], new: Optional[str]) -> str:
    a = (old or "").splitlines(keepends=True)
    b = (new or "").splitlines(keepends=True)
    diff = difflib.unified_diff(a, b, "/dev/null" if old is None else f"a/{path}",
                                "/dev/null" if new is None else f"b/{path}")
    out = []
    for line in diff:
        out.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(out)
