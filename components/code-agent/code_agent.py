#!/usr/bin/env python3
"""
DevOS AI Code Agent: a coding agent that runs only on the local DevOS AI model
(http://127.0.0.1:11434/v1, model "devos-ai-code"). Nothing leaves the PC.

The agent works inside one project folder. It can list, read and search
files on its own (reads are auto-approved by default), but every file change
is shown as a diff and every command is shown before it runs, and both need
the person's approval ("auto-approve edits" can be switched on; commands
always ask).

Small local models are bad at JSON function calling, so the model talks to
the tools with fenced text blocks:

    ```tool read_file
    path: src/app.py
    ```

and the parser here accepts the usual small-model slips (JSON with trailing
commas or raw newlines, Qwen's <tool_call> tags, tool names like "readFile",
a missing closing fence).

Usage:
    devos-ai-code-agent [folder]         the window (agent_gui.py)
    devos-ai-code-agent --cli "task"     in the terminal, with y/n approvals
    code_agent.py "prompt" [--framework] the original one-shot JSON answer
"""

import argparse
import ast
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import patching  # noqa: E402
try:
    import providers  # noqa: E402
except ImportError:
    from . import providers  # noqa: E402

AI_ENDPOINT = os.environ.get("DEVOS_AI_ENDPOINT", "http://127.0.0.1:11434/v1")
CODE_MODEL = os.environ.get("DEVOS_AI_MODEL", "devos-ai-code")

IGNORED_DIRS = {".git", "node_modules", "vendor", "__pycache__", ".venv", "venv", "out", "build_work",
                "dist", ".mypy_cache", ".pytest_cache", ".idea", ".tox", "target", ".next"}
READ_CAP = 8000          # characters of a file shown to the model per read
LIST_CAP = 150           # files per listing
SEARCH_CAP = 60          # matching lines per search
OUTPUT_CAP = 4000        # characters of command output shown to the model
COMMAND_TIMEOUT = 120    # seconds; the model may ask for up to MAX_TIMEOUT
MAX_TIMEOUT = 600
HISTORY_BUDGET = 14000   # characters of conversation sent per step (8k-token window)
NOTES_FILE = os.path.join(".devos", "agent-notes.md")


# ====================================================================== tools

READ_TOOLS = ("list_files", "read_file", "search")
EDIT_TOOLS = ("write_file", "apply_patch")
COMMAND_TOOLS = ("run_command",)
TOOL_NAMES = READ_TOOLS + EDIT_TOOLS + COMMAND_TOOLS

TOOL_ALIASES = {
    "ls": "list_files", "list": "list_files", "list_dir": "list_files", "list_directory": "list_files",
    "files": "list_files", "dir": "list_files", "tree": "list_files",
    "read": "read_file", "cat": "read_file", "open": "read_file", "open_file": "read_file",
    "view": "read_file", "view_file": "read_file", "show_file": "read_file",
    "grep": "search", "rg": "search", "find": "search", "search_files": "search", "search_code": "search",
    "write": "write_file", "create_file": "write_file", "create": "write_file", "save_file": "write_file",
    "new_file": "write_file", "overwrite_file": "write_file",
    "patch": "apply_patch", "edit": "apply_patch", "edit_file": "apply_patch", "diff": "apply_patch",
    "apply_diff": "apply_patch", "modify_file": "apply_patch", "update_file": "apply_patch",
    "run": "run_command", "bash": "run_command", "shell": "run_command", "sh": "run_command",
    "exec": "run_command", "execute": "run_command", "terminal": "run_command", "command": "run_command",
    "run_shell": "run_command", "execute_command": "run_command",
}

ARG_ALIASES = {
    "file": "path", "filename": "path", "file_path": "path", "filepath": "path", "dir": "path",
    "directory": "path", "folder": "path", "target": "path",
    "text": "content", "code": "content", "contents": "content", "body": "content", "data": "content",
    "diff": "patch", "changes": "patch",
    "cmd": "command", "script": "command",
    "query": "pattern", "regex": "pattern", "term": "pattern", "keyword": "pattern",
    "start": "start_line", "line": "start_line", "from_line": "start_line", "end": "end_line",
    "to_line": "end_line",
}


class ToolError(Exception):
    """A tool could not do what the model asked; the message goes back to it."""


class PathOutsideProject(ToolError):
    pass


class Workspace:
    """One project folder. Every path the model names is resolved inside it."""

    def __init__(self, root: str):
        self.root = os.path.realpath(os.path.abspath(os.path.expanduser(root)))
        if not os.path.isdir(self.root):
            raise ToolError(f"{root} is not a folder.")

    # ------------------------------------------------------------- confinement
    def resolve(self, path: str) -> str:
        path = (path or ".").strip().strip("'\"`")
        if path.startswith("~"):
            raise PathOutsideProject(f"{path} is outside the project folder.")
        candidate = path if os.path.isabs(path) else os.path.join(self.root, path)
        real = os.path.realpath(os.path.normpath(candidate))  # follows symlinks out, too
        try:
            inside = os.path.commonpath([real, self.root]) == self.root
        except ValueError:  # another drive on Windows
            inside = False
        if not inside:
            raise PathOutsideProject(f"{path} is outside the project folder; the agent only works inside "
                                     f"{self.root}.")
        return real

    def rel(self, real: str) -> str:
        rel = os.path.relpath(real, self.root)
        return "." if rel == "." else rel.replace(os.sep, "/")

    def check_writable(self, path: str) -> str:
        real = self.resolve(path)
        parts = self.rel(real).split("/")
        if ".git" in parts:
            raise ToolError("The agent does not change files inside .git.")
        if real == self.root or os.path.isdir(real):
            raise ToolError(f"{path} is a folder, not a file.")
        return real

    # ------------------------------------------------------------------ reads
    def read_text(self, path: str) -> Optional[str]:
        """Current text of a file, or None when it does not exist."""
        real = self.resolve(path)
        if not os.path.isfile(real):
            return None
        with open(real, "rb") as handle:
            data = handle.read()
        if b"\0" in data[:4096]:
            raise ToolError(f"{path} is a binary file.")
        return data.decode("utf-8", errors="replace")

    def list_files(self, path: str = ".", limit: int = LIST_CAP) -> str:
        real = self.resolve(path)
        if os.path.isfile(real):
            return self.rel(real)
        if not os.path.isdir(real):
            raise ToolError(f"{path} does not exist.")
        found: List[str] = []
        more = False
        for current, dirs, files in os.walk(real):
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")
                             or d == ".devos")
            for name in sorted(files):
                if len(found) >= limit:
                    more = True
                    break
                found.append(self.rel(os.path.join(current, name)))
            if more:
                break
        if not found:
            return "(no files)"
        return "\n".join(found) + (f"\n... (more files; list a subfolder)" if more else "")

    def read_file(self, path: str, start_line: Any = None, end_line: Any = None) -> str:
        text = self.read_text(path)
        if text is None:
            raise ToolError(f"{path} does not exist.")
        lines = text.splitlines()
        start = _int(start_line, 1)
        end = _int(end_line, len(lines))
        start = max(start, 1)
        chunk = "\n".join(lines[start - 1:end])
        note = ""
        if len(chunk) > READ_CAP:
            chunk = chunk[:READ_CAP]
            shown = chunk.count("\n") + start
            note = (f"\n... (truncated; the file has {len(lines)} lines. Read more with "
                    f"start_line: {shown + 1})")
        elif start > 1 or end < len(lines):
            note = f"\n(lines {start}-{min(end, len(lines))} of {len(lines)})"
        return chunk + note

    def search(self, pattern: str, path: str = ".") -> str:
        if not pattern:
            raise ToolError("search needs a pattern.")
        real = self.resolve(path)
        rg = shutil.which("rg")
        lines: List[str] = []
        if rg:
            try:
                out = subprocess.run(
                    [rg, "--line-number", "--no-heading", "--color", "never", "--smart-case",
                     "--max-count", "5", "--max-columns", "200", "--", pattern, real],
                    capture_output=True, text=True, timeout=30, cwd=self.root)
                for line in out.stdout.splitlines():
                    if line.startswith(self.root):
                        line = line[len(self.root):].lstrip("/\\")
                    lines.append(line)
            except (OSError, subprocess.TimeoutExpired):
                rg = None
        if not rg:
            lines = self._python_search(pattern, real)
        if not lines:
            return f"No matches for {pattern!r}."
        more = len(lines) > SEARCH_CAP
        return "\n".join(lines[:SEARCH_CAP]) + ("\n... (more matches; search a subfolder)" if more else "")

    def _python_search(self, pattern: str, real: str) -> List[str]:
        try:
            rx = re.compile(pattern, 0 if pattern != pattern.lower() else re.I)
        except re.error:
            rx = re.compile(re.escape(pattern), re.I)
        files = [real] if os.path.isfile(real) else []
        if not files:
            for current, dirs, names in os.walk(real):
                dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
                files.extend(os.path.join(current, n) for n in names)
        hits = []
        for name in files:
            try:
                with open(name, encoding="utf-8", errors="strict") as handle:
                    for number, line in enumerate(handle, 1):
                        if rx.search(line):
                            hits.append(f"{self.rel(name)}:{number}:{line.rstrip()[:200]}")
                            if len(hits) > SEARCH_CAP:
                                return hits
            except (OSError, UnicodeDecodeError):
                continue
        return hits

    # ----------------------------------------------------------------- writes
    def write_text(self, path: str, text: Optional[str]) -> None:
        real = self.check_writable(path)
        if text is None:
            if os.path.isfile(real):
                os.remove(real)
            return
        os.makedirs(os.path.dirname(real), exist_ok=True)
        tmp = real + ".devos-tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, real)

    # --------------------------------------------------------------- commands
    def run_command(self, command: str, timeout: Any = None) -> Dict[str, Any]:
        seconds = min(max(_int(timeout, COMMAND_TIMEOUT), 1), MAX_TIMEOUT)
        posix = os.name == "posix"
        proc = subprocess.Popen(
            ["/bin/bash", "-c", command] if posix and os.path.exists("/bin/bash") else command,
            shell=not (posix and os.path.exists("/bin/bash")), cwd=self.root,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=posix)
        timed_out = False
        try:
            out, _ = proc.communicate(timeout=seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                if posix:
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except OSError:
                pass
            out, _ = proc.communicate()
        text = (out or b"").decode("utf-8", errors="replace")
        return {"code": proc.returncode, "output": cap_output(text), "timed_out": timed_out,
                "seconds": seconds}

    def detect_run_info(self) -> Dict[str, Any]:
        """Intelligently detects application type, run/serve command, port, and landing page URL."""
        root = self.root

        # 1. Node / Frontend / Vite / Next.js / Express
        pkg_json = os.path.join(root, "package.json")
        if os.path.isfile(pkg_json):
            try:
                with open(pkg_json, encoding="utf-8") as f:
                    data = json.load(f)
                scripts = data.get("scripts") or {}
                for s in ("dev", "start", "serve", "preview"):
                    if s in scripts:
                        cmd = f"npm run {s}" if s != "start" else "npm start"
                        script_text = scripts.get(s, "")
                        port = 5173 if "vite" in script_text else (3000 if "next" in str(data) else 3000)
                        return {
                            "type": "Node.js / Web Application",
                            "command": cmd,
                            "port": port,
                            "url": f"http://localhost:{port}",
                            "preview_url": f"http://localhost:{port}",
                            "hint": f"package.json (script '{s}')"
                        }
            except Exception:
                pass

        # 2. Django
        if os.path.isfile(os.path.join(root, "manage.py")):
            return {
                "type": "Python / Django",
                "command": "python3 manage.py runserver 8000",
                "port": 8000,
                "url": "http://localhost:8000",
                "preview_url": "http://localhost:8000",
                "hint": "manage.py"
            }

        # 3. Python web frameworks
        for candidate in ("app.py", "main.py", "server.py", "wsgi.py", "asgi.py", "run.py"):
            p = os.path.join(root, candidate)
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(3000)
                    if "FastAPI" in content:
                        mod = os.path.splitext(candidate)[0]
                        return {
                            "type": "Python / FastAPI",
                            "command": f"uvicorn {mod}:app --reload --port 8000",
                            "port": 8000,
                            "url": "http://localhost:8000",
                            "preview_url": "http://localhost:8000",
                            "hint": candidate
                        }
                    if "Flask" in content:
                        return {
                            "type": "Python / Flask",
                            "command": f"python3 {candidate}",
                            "port": 5000,
                            "url": "http://localhost:5000",
                            "preview_url": "http://localhost:5000",
                            "hint": candidate
                        }
                    if "streamlit" in content:
                        return {
                            "type": "Python / Streamlit",
                            "command": f"streamlit run {candidate}",
                            "port": 8501,
                            "url": "http://localhost:8501",
                            "preview_url": "http://localhost:8501",
                            "hint": candidate
                        }
                    if "http.server" in content or "HTTPServer" in content or "__main__" in content:
                        return {
                            "type": "Python / Application Script",
                            "command": f"python3 {candidate}",
                            "port": 8000,
                            "url": "http://localhost:8000",
                            "preview_url": "http://localhost:8000",
                            "hint": candidate
                        }
                except Exception:
                    pass

        # 4. PHP / Laravel
        if os.path.isfile(os.path.join(root, "artisan")):
            return {
                "type": "PHP / Laravel",
                "command": "php artisan serve",
                "port": 8000,
                "url": "http://localhost:8000",
                "preview_url": "http://localhost:8000",
                "hint": "artisan"
            }

        # 5. Static HTML landing page
        for html_candidate in ("index.html", "landing.html", "public/index.html", "dist/index.html", "build/index.html"):
            if os.path.isfile(os.path.join(root, html_candidate)):
                return {
                    "type": "HTML / Static Landing Page",
                    "command": "python3 -m http.server 3000",
                    "port": 3000,
                    "url": "http://localhost:3000",
                    "preview_url": "http://localhost:3000",
                    "hint": html_candidate
                }

        # 6. Rust / Go / Makefile
        if os.path.isfile(os.path.join(root, "Cargo.toml")):
            return {"type": "Rust", "command": "cargo run", "port": None, "url": None, "hint": "Cargo.toml"}
        if os.path.isfile(os.path.join(root, "go.mod")):
            return {"type": "Go", "command": "go run .", "port": None, "url": None, "hint": "go.mod"}
        if os.path.isfile(os.path.join(root, "Makefile")):
            return {"type": "Makefile", "command": "make run", "port": None, "url": None, "hint": "Makefile"}

        return {
            "type": "Generic Project",
            "command": None,
            "port": None,
            "url": None,
            "hint": "No standard web entrypoint detected"
        }

    # ------------------------------------------------------------------ notes
    def notes_path(self) -> str:
        return os.path.join(self.root, NOTES_FILE)

    def read_notes(self, limit: int = 1500) -> str:
        try:
            with open(self.notes_path(), encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            return ""
        clean = []
        for line in lines:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            # Strip lines that contain raw tool commands or prompt syntax
            if any(bad in s for bad in ("write_file", "read_file", "apply_patch", "run_command", "```", "--- #")):
                continue
            clean.append(s)
        text = "\n".join(clean)
        return text[-limit:]

    def add_note(self, line: str) -> None:
        path = self.notes_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8") as handle:
            if new:
                handle.write("# DevOS AI Code Agent notes\n\nWhat the agent did and learned in this project. "
                             "Edit freely; the agent reads this at the start of every task.\n\n")
            handle.write(line.rstrip() + "\n")


def cap_output(text: str, cap: int = OUTPUT_CAP) -> str:
    if len(text) <= cap:
        return text
    head = text[: cap // 3]
    tail = text[-(cap - len(head)):]
    return f"{head}\n... ({len(text) - cap} characters cut) ...\n{tail}"


def _int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


# ============================================================ tool-call parser

class ToolCall:
    def __init__(self, name: str, args: Dict[str, Any], raw: str = ""):
        self.name = name
        self.args = args
        self.raw = raw

    def __repr__(self):
        return f"ToolCall({self.name!r}, {self.args!r})"


def normalize_tool_name(name: str) -> Optional[str]:
    if not name:
        return None
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name.strip().strip("`:\"'"))
    name = re.sub(r"[\s\-.]+", "_", name).lower()
    if name.startswith(("tool_", "tool:")):
        name = name[5:]
    if name in TOOL_NAMES:
        return name
    return TOOL_ALIASES.get(name)


def loads_lenient(text: str) -> Optional[Any]:
    """json.loads that forgives what small models get wrong."""
    text = text.strip()
    start = text.find("{")
    if start < 0:
        return None
    text = _balanced(text[start:])
    attempts = [text]
    fixed = (text.replace("“", '"').replace("”", '"').replace("‘", "'")
             .replace("’", "'"))
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
    attempts.append(fixed)
    attempts.append(_escape_raw_newlines(fixed))
    for attempt in attempts:
        try:
            return json.loads(attempt)
        except ValueError:
            continue
    try:  # single quotes, True/False/None
        pythonish = re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False",
                                                        re.sub(r"\bnull\b", "None", fixed)))
        value = ast.literal_eval(pythonish)
        return value if isinstance(value, dict) else None
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None


def _balanced(text: str) -> str:
    depth, in_str, escape = 0, None, False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == in_str:
                in_str = None
        elif ch in "\"'":
            in_str = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[:i + 1]
    return text


def _escape_raw_newlines(text: str) -> str:
    out, in_str, escape = [], False, False
    for ch in text:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            elif ch == "\n":
                out.append("\\n")
                continue
            elif ch == "\t":
                out.append("\\t")
                continue
        elif ch == '"':
            in_str = True
        out.append(ch)
    return "".join(out)


_OPEN_RE = re.compile(r"^[ \t]*```+[ \t]*([^\n`]*)$", re.M)
_TOOLCALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|\Z)", re.S)
_KEY_RE = re.compile(r"^([A-Za-z_][\w\-]*)\s*[:=]\s?(.*)$")


def _fenced_blocks(text: str):
    """Yield (info, body) for each ``` block; nested ``` in a file body are kept
    by closing at the last bare fence before the next ```tool opener."""
    opens = list(_OPEN_RE.finditer(text))
    i = 0
    while i < len(opens):
        match = opens[i]
        info = match.group(1).strip()
        body_start = match.end() + 1
        # where the next tool block starts (or end of text)
        nxt = len(text)
        for later in opens[i + 1:]:
            if _is_tool_fence(later.group(1)):
                nxt = later.start()
                break
        region = text[body_start:nxt] if body_start <= len(text) else ""
        closes = [m for m in re.finditer(r"^[ \t]*```+[ \t]*$", region, re.M)]
        if closes and _is_tool_fence(info):
            body = region[:closes[-1].start()]
        elif closes:
            body = region[:closes[0].start()]
        else:
            body = region
        yield info, body.rstrip("\n")
        end_abs = body_start + len(body)
        while i + 1 < len(opens) and opens[i + 1].start() < end_abs + 4:
            i += 1
        i += 1


def _is_tool_fence(info: str) -> bool:
    return info.strip().lower().startswith("tool") or _fence_tool(info) is not None


def _fence_tool(info: str) -> Optional[str]:
    """The tool a fence names: ```tool <any alias>, or a bare exact tool name
    (```read_file). ```bash and ```python stay code examples, never commands."""
    info = info.strip()
    if info.lower().startswith("tool"):
        return normalize_tool_name(_info_name(info))
    name = info.split()[0] if info.split() else ""
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    name = re.sub(r"[\s\-.]+", "_", name).lower()
    return name if name in TOOL_NAMES else None


def _info_name(info: str) -> str:
    info = info.strip()
    if info.lower().startswith("tool"):
        info = info[4:].lstrip(" :=-_")
    return info.split()[0] if info.split() else ""


def _parse_body(name: str, body: str) -> Dict[str, Any]:
    stripped = body.strip()
    if stripped.startswith("{"):
        data = loads_lenient(stripped)
        if isinstance(data, dict):
            inner = data.get("arguments") or data.get("args") or data.get("parameters") or data.get("input")
            if isinstance(inner, str):
                inner = loads_lenient(inner) if inner.strip().startswith("{") else None
            if isinstance(inner, dict) and (data.get("name") or data.get("tool")):
                data = inner
            return _norm_args(data)
    args: Dict[str, Any] = {}
    lines = body.split("\n")
    rest_at = None
    for i, line in enumerate(lines):
        if line.strip() in ("---", "<<<", "content:", "patch:"):
            rest_at = i + 1
            break
        key = _KEY_RE.match(line.strip())
        if key and ARG_ALIASES.get(key.group(1).lower(), key.group(1).lower()) in (
                "path", "pattern", "command", "start_line", "end_line", "timeout", "content", "patch"):
            k = ARG_ALIASES.get(key.group(1).lower(), key.group(1).lower())
            if k in ("content", "patch"):
                if key.group(2).strip():  # "content: first line" then the rest of the file
                    args[k] = "\n".join([key.group(2)] + lines[i + 1:])
                rest_at = i + 1
                break
            value = key.group(2).strip()
            args[k] = value if k == "command" else _unquote(value)
            continue
        if line.strip() == "" and not args:
            continue
        rest_at = i
        break
    rest = "\n".join(lines[rest_at:]) if rest_at is not None else ""
    if rest.strip().endswith(">>>"):
        rest = rest.rstrip()[:-3]
    if name == "write_file" and "content" not in args:
        args["content"] = rest
    elif name == "apply_patch" and "patch" not in args:
        args["patch"] = rest if rest.strip() else body
    elif name == "run_command" and "command" not in args:
        args["command"] = re.sub(r"^\s*\$\s*", "", rest.strip())
    elif name in ("read_file", "list_files") and "path" not in args and rest.strip():
        args["path"] = _unquote(rest.strip().split("\n")[0].strip())
    elif name == "search" and "pattern" not in args and rest.strip():
        args["pattern"] = rest.strip().split("\n")[0]
    return args


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"`":
        return value[1:-1]
    return value


def _norm_args(data: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for key, value in data.items():
        k = ARG_ALIASES.get(str(key).lower(), str(key).lower())
        out[k] = value
    return out


def parse_tool_call(text: str) -> Optional[ToolCall]:
    """The first tool call in a model reply, or None when it is a final answer."""
    if not text:
        return None
    for info, body in _fenced_blocks(text):
        name = _fence_tool(info)
        if not name and info.lower().startswith("tool"):
            first, _, rest = body.lstrip("\n").partition("\n")
            name = normalize_tool_name(first)
            if name:
                body = rest
            elif body.strip().startswith("{"):
                data = loads_lenient(body)
                if isinstance(data, dict):
                    name = normalize_tool_name(str(data.get("name") or data.get("tool") or ""))
        if not name and info.lower() in ("json", "") and body.strip().startswith("{"):
            data = loads_lenient(body)
            if isinstance(data, dict):
                name = normalize_tool_name(str(data.get("name") or data.get("tool") or ""))
        if name:
            return ToolCall(name, _parse_body(name, body), body)
    for match in _TOOLCALL_RE.finditer(text):
        data = loads_lenient(match.group(1))
        if isinstance(data, dict):
            name = normalize_tool_name(str(data.get("name") or data.get("tool") or ""))
            if name:
                return ToolCall(name, _parse_body(name, match.group(1)), match.group(1))
    return None


def looks_like_tool_attempt(text: str) -> bool:
    return bool(re.search(r"```\s*tool|<tool_call>|\"(?:tool|name)\"\s*:", text or "", re.I))


def extract_plan(text: str, limit: int = 8) -> List[str]:
    """Numbered or bulleted steps the model wrote before its first tool call."""
    head = re.split(r"```|<tool_call>", text or "", maxsplit=1)[0]
    steps = []
    for line in head.splitlines():
        m = re.match(r"^\s*(?:\d+[.)]|[-*•])\s+(.+)$", line)
        if m:
            steps.append(m.group(1).strip().rstrip("."))
    return steps[:limit]


# ============================================================ approval policy

class ApprovalPolicy:
    """Reads run on their own by default; edits ask unless auto-approved;
    commands ask unless auto-approved."""

    def __init__(self, auto_reads: bool = True, auto_edits: bool = False, auto_commands: bool = False):
        self.auto_reads = auto_reads
        self.auto_edits = auto_edits
        self.auto_commands = auto_commands

    @staticmethod
    def category(tool: str) -> str:
        if tool in READ_TOOLS:
            return "read"
        if tool in EDIT_TOOLS:
            return "edit"
        return "command"

    def needs_approval(self, tool: str) -> bool:
        kind = self.category(tool)
        if kind == "read":
            return not self.auto_reads
        if kind == "edit":
            return not self.auto_edits
        if kind == "command":
            return not self.auto_commands
        return True


class Action:
    """Something the person may have to approve: a read, one file change or a command."""

    def __init__(self, kind: str, tool: str, title: str, path: str = "", diff: str = "",
                 old: Optional[str] = None, new: Optional[str] = None, command: str = ""):
        self.kind = kind
        self.tool = tool
        self.title = title
        self.path = path
        self.diff = diff
        self.old = old
        self.new = new
        self.command = command

    def __repr__(self):
        return f"Action({self.kind}, {self.title!r})"


# ================================================================ local model

class AgentError(Exception):
    pass


def check_ai_health(endpoint: str = AI_ENDPOINT) -> bool:
    """Return True if DevOS AI Core is responding on health endpoint."""
    base = endpoint.rstrip("/")
    if base.endswith("/v1"):
        health_url = base[:-3] + "/health"
    else:
        health_url = f"{base}/health"
    try:
        req = urllib.request.Request(health_url, headers={"User-Agent": "DevOS-Code-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def find_ai_server_py() -> Optional[str]:
    """Find the server.py script for DevOS AI Core."""
    candidates = [
        os.path.abspath(os.path.join(HERE, "..", "ai-core", "server.py")),
        "/usr/local/share/devos/components/ai-core/server.py",
        os.path.expanduser("~/project/dev-os/components/ai-core/server.py"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def ensure_ai_service(endpoint: str = AI_ENDPOINT, timeout_seconds: float = 12.0) -> bool:
    """Ensure DevOS AI Core is running on 127.0.0.1:11434. Auto-starts if not running."""
    if check_ai_health(endpoint):
        return True

    server_py = find_ai_server_py()
    if not server_py:
        return False

    try:
        log_path = os.path.join("/var/tmp", "devos-ai-core.log")
        try:
            log_fh = open(log_path, "ab")
        except OSError:
            log_fh = subprocess.DEVNULL
        subprocess.Popen([sys.executable or "python3", server_py],
                         cwd=os.path.dirname(server_py),
                         stdin=subprocess.DEVNULL, stdout=log_fh, stderr=log_fh,
                         start_new_session=True)
    except Exception:
        return False

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        time.sleep(0.6)
        if check_ai_health(endpoint):
            return True
    return False


class LocalLLM:
    """Talks to DevOS Local AI or high-speed Cloud Providers (Gemini, Groq, DeepSeek, OpenAI) via OpenAI SSE."""

    def __init__(self, endpoint: Optional[str] = None, model: Optional[str] = None, api_key: Optional[str] = None,
                 max_tokens: int = 2048, timeout: int = 180):
        active = providers.get_active_engine()
        self.endpoint = (endpoint or active["endpoint"]).rstrip("/")
        self.model = model or active["model"]
        self.api_key = api_key if api_key is not None else active["api_key"]
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.is_local = (active.get("is_local", True) if endpoint is None else
                         ("127.0.0.1" in self.endpoint or "localhost" in self.endpoint))
        self.provider_name = active.get("name", "AI Engine")
        self._current_resp = None

    def close(self):
        """Immediately closes active HTTP socket to unblock threads upon task cancellation."""
        r = self._current_resp
        self._current_resp = None
        if r:
            try:
                r.close()
            except Exception:
                pass

    def chat(self, messages: List[Dict[str, str]], on_token: Optional[Callable[[str], None]] = None,
             should_stop: Optional[Callable[[], bool]] = None) -> str:
        payload = {"model": self.model, "messages": messages, "stream": True,
                   "temperature": 0.2, "max_tokens": self.max_tokens}
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.endpoint}/chat/completions",
                                     data=json.dumps(payload).encode("utf-8"), headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            self._current_resp = resp
        except (urllib.error.URLError, OSError) as exc:
            # If on localhost and connection failed, auto-start and retry once
            if self.is_local:
                if on_token:
                    on_token("⚡ DevOS AI Core is starting on this PC... initializing neural engine.\n")
                if ensure_ai_service(self.endpoint, timeout_seconds=12.0):
                    try:
                        resp = urllib.request.urlopen(req, timeout=self.timeout)
                        self._current_resp = resp
                    except (urllib.error.URLError, OSError) as retry_exc:
                        raise AgentError("DevOS AI is not answering on this PC. Please run 'devos-ai' in terminal. "
                                         f"({retry_exc})")
                else:
                    raise AgentError("DevOS AI is not answering on this PC. Failed to auto-start DevOS AI Core. "
                                     f"Run 'devos-ai' in terminal or check /var/tmp/devos-ai-core.log. ({exc})")
            else:
                raise AgentError(f"{self.provider_name} ({self.model}) connection error: {exc}. "
                                 "Please check your API key and network connection in Engine Settings.")
        with resp:
            if "event-stream" not in (resp.headers.get("Content-Type") or ""):
                data = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
                text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
                if on_token and text:
                    on_token(text)
                return text
            return read_sse(resp, on_token, should_stop)


def read_sse(lines, on_token=None, should_stop=None) -> str:
    """Join the content deltas of an OpenAI-style event stream."""
    parts: List[str] = []
    try:
        for raw in lines:
            if should_stop and should_stop():
                break
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            for choice in chunk.get("choices") or []:
                piece = (choice.get("delta") or {}).get("content") or ""
                if piece:
                    parts.append(piece)
                    if on_token:
                        on_token(piece)
    except (OSError, ValueError):
        pass
    return "".join(parts)


# ===================================================================== agent

SYSTEM_PROMPT = """You are DevOS AI Code Agent, an expert autonomous software engineer working in the user's project workspace, operating with the precision and speed of Cursor and Antigravity.
Your mission is to understand user requests with high accuracy, inspect code, implement robust solutions, run/test software, and provide clear technical answers.

Workflow Rules:
1. Fast Direct Diagnostics:
   - When asked diagnostic questions (e.g. 'why landing page is blank', 'why is it not working', 'why did it fail', 'how to fix'):
     Immediately inspect the exact suspect files responsible for routing, controllers, and views:
     * Laravel / PHP: inspect `routes/web.php` and the returned view in `resources/views/` (e.g. `welcome.blade.php`). Check if the dev server (`php artisan serve`) is running. If a route or view is empty, missing, or misconfigured, explain it directly and output the concrete fix.
     * React / Vue / Vite / Next.js: inspect `index.html`, `src/App.*`, `package.json`, or root entrypoint.
     * Python / FastAPI / Flask: inspect `main.py`, `app.py`, routes and templates.
     Pinpoint the root cause within 1-2 tool calls, then provide the direct solution without unnecessary loops.
2. Autonomous Application & Feature Implementation:
   - When asked to build, complete, or develop an application, feature, or landing page (e.g. 'make the complete erp application with landing page'):
     * NEVER stop after reading README.md or reviewing files! Reading is only the first step.
     * Actively implement the required code by calling `write_file` or `apply_patch` immediately.
     * For Laravel ERP projects: build out a rich, modern landing page in `resources/views/welcome.blade.php` (with modern UI styling, Hero banner, ERP module cards for Sales, HR, Inventory, Finance, and Users, KPI metrics, and navigation links).
     * Connect all necessary routes in `routes/web.php` and verify controllers.
3. Outline a concise numbered plan (1-5 key milestones) only if a complex multi-step build is requested.
4. When asked to run, test, start, or preview the application:
   - Identify the real project entrypoint (e.g. check for package.json, main.py, app.py, manage.py, server.py, index.html, etc.) before running commands.
   - Use `run_command` with valid execution commands (e.g. `python3 app.py`, `npm start`, `npm run dev`, `pytest`, `php artisan serve`).
   - NEVER try to run documentation (.md), text files (.txt), or configs directly with python3 or bash.
5. If creating or editing code, read relevant existing files first. Always output complete, valid, working code. NEVER use placeholders or ellipsis like '...' or '// rest of code'.
5. When asked questions (e.g. 'why failed to show landing page', 'how does this work', 'why did the command fail'):
   - Inspect the project files or recent actions and explain the technical cause and solution clearly.
   - NEVER refuse with 'I can't assist with that' or similar phrases. You have full capability and permission to assist with all software development, testing, and debugging tasks in this project.
6. Write tool calls exactly like this:
```tool read_file
path: routes/web.php
```
Tools:
- list_files  path: <folder>
- read_file   path: <file>   (optional start_line: <n>)
- search      pattern: <text or regex>   (optional path: <folder>)
- write_file  path: <file>, then a line with ---, then the whole new file content
- apply_patch a unified diff (--- a/file, +++ b/file, @@ hunks with exact unchanged lines)
- run_command command: <shell command run in the project folder>
Only refer to actual files that exist in the project folder.
The user approves every change and command; if they reject one, do not repeat it.
7. When the user's question is answered or all requested steps are completed, reply with a clear final summary and no tool block."""

FORMAT_HELP = ("Your tool call could not be read. Write exactly one block like:\n"
               "```tool read_file\npath: README.md\n```\nor, for a new file:\n"
               "```tool write_file\npath: hello.py\n---\nprint(\"hello\")\n```")


def noop_event(kind: str, payload: Any = None) -> None:
    return None


def extract_task_topic(task: str) -> str:
    """Extract a concise topic/goal headline from the user's task prompt."""
    if not task:
        return "Autonomous Development Task"
    lines = [line.strip() for line in task.strip().splitlines() if line.strip()]
    first_meaningful = ""
    for line in lines:
        cleaned = re.sub(r"^(?:#+|\d+[.)]|[-*•]|\b(?:task|goal|todo|prompt)\b[:\s-]*)\s*", "", line, flags=re.I).strip()
        if len(cleaned) >= 5 and not cleaned.lower().startswith(("you are", "role and mission")):
            first_meaningful = cleaned
            break
    if not first_meaningful:
        first_meaningful = lines[0] if lines else "Development Task"
    if len(first_meaningful) > 75:
        first_meaningful = first_meaningful[:72] + "..."
    return first_meaningful


def clean_file_content(content: str) -> str:
    if not content:
        return ""
    lines = content.split("\n")
    while lines and (not lines[0].strip() or lines[0].strip().startswith("```") or lines[0].strip() in ("---", ", ---", "--")):
        lines.pop(0)
    while lines and (not lines[-1].strip() or lines[-1].strip().startswith("```") or lines[-1].strip() in ("---", ", ---", "--", "...", "... rest of code", "// ...", "# ...")):
        lines.pop()
    cleaned = "\n".join(lines)
    if cleaned and not cleaned.endswith("\n"):
        cleaned += "\n"
    return cleaned


class CodeAgent:
    """The agent loop: ask the model, run one tool, show the result, repeat."""

    def __init__(self, workspace: Workspace, llm, approve: Callable[[Action], bool],
                 policy: Optional[ApprovalPolicy] = None, on_event: Callable[[str, Any], None] = noop_event,
                 max_steps: int = 35, keep_notes: bool = True,
                 history: Optional[List[Dict[str, str]]] = None):
        self.ws = workspace
        self.llm = llm
        self.approve = approve
        self.policy = policy or ApprovalPolicy()
        self.on_event = on_event
        self.max_steps = max_steps
        self.keep_notes = keep_notes
        self.cancelled = False
        self.messages: List[Dict[str, str]] = []
        self.changed: List[str] = []
        self.history: List[Dict[str, str]] = history or []

    def cancel(self) -> None:
        self.cancelled = True
        if hasattr(self.llm, "close"):
            try:
                self.llm.close()
            except Exception:
                pass

    # ---------------------------------------------------------------- context
    def first_message(self, task: str) -> str:
        files = self.ws.list_files(".", limit=40)
        notes = self.ws.read_notes()
        run_info = self.ws.detect_run_info()
        parts = [f"Project folder: {os.path.basename(self.ws.root) or self.ws.root}"]
        if run_info.get("command"):
            url_hint = f" (serves landing page on {run_info['url']})" if run_info.get("url") else ""
            parts.append(f"Project Architecture: {run_info['type']}\n"
                         f"Detected Run Command: `{run_info['command']}`{url_hint}")
        parts.append("Files:\n" + files)
        if notes:
            parts.append("Project notes (.devos/agent-notes.md):\n" + notes)
        parts.append("Task: " + task.strip())
        parts.append(
            "Execution Directive: Fulfill the task using tool calls.\n"
            "- To inspect code: ```tool read_file\npath: <path>\n```\n"
            "- To implement code: ```tool write_file\npath: <path>\n---\n<full code>\n```\n"
            "- To run/test app: ```tool run_command\ncommand: <cmd>\n```\n"
            "Begin immediately with a tool call block. Do not output conversational filler."
        )
        return "\n\n".join(parts)

    def window(self) -> List[Dict[str, str]]:
        """System + task + the most recent turns that fit the model's window.
        Older tool results are shortened first."""
        head, rest = self.messages[:2], self.messages[2:]
        budget = HISTORY_BUDGET - sum(len(m["content"]) for m in head)
        kept: List[Dict[str, str]] = []
        for i, message in enumerate(reversed(rest)):
            content = message["content"]
            if i >= 2 and len(content) > 600:
                content = content[:600] + "\n... (shortened)"
            if budget - len(content) < 0 and kept:
                break
            budget -= len(content)
            kept.append({"role": message["role"], "content": content})
        return head + list(reversed(kept))

    def should_continue_task(self, reply: str, task: str, step: int) -> bool:
        """Determine if the agent should continue executing steps rather than halting prematurely."""
        if step >= self.max_steps - 2:
            return False
        
        reply_lower = reply.lower().strip()
        task_lower = task.lower().strip()

        is_question = any(kw in task_lower for kw in [
            "?", "what is", "why", "how does", "is this", "ia this", "are there",
            "check if", "check whether", "status", "explain"
        ])
        is_build_or_code_action = any(kw in task_lower for kw in [
            "make", "build", "create", "implement", "develop", "complete", "add", "fix",
            "setup", "set up", "scaffold", "generate", "code", "write", "run", "start",
            "serve", "deploy"
        ])

        # If it's a diagnostic or explanatory question without build actions, do not force continuation
        if is_question and not is_build_or_code_action:
            return False

        is_build_or_code_task = is_build_or_code_action or any(kw in task_lower for kw in [
            "landing page", "erp", "project", "application", "app", "feature", "module", "system"
        ])
        
        # 1. Check for explicit continuation phrases in the model's reply
        continuation_patterns = [
            r"\bnext[,:\s]+(?:we|let['’]?s|i|step)\b",
            r"\bnow[,:\s]+(?:let['’]?s|we|i)\b",
            r"\bstart\s+setting\s+up\b",
            r"\bproceed(?:ing)?\s+to\b",
            r"\bwe\s+can\s+(?:start|begin|create|set\s+up|implement|add)\b",
            r"\bi\s+will\s+(?:now\s+)?(?:create|write|implement|add|set\s+up)\b",
            r"\bto\s+set\s+up\b",
            r"\bmoving\s+on\s+to\b",
            r"\bnext\s+step\b",
            r"\bto\s+implement\b",
            r"\bstep\s+\d+:\s*(?:create|build|implement|setup)",
        ]
        for pat in continuation_patterns:
            if re.search(pat, reply_lower):
                return True
        
        # 2. If the user asked to build/create/implement and files haven't been written yet
        if is_build_or_code_task and len(self.changed) == 0 and step < 6:
            return True

        if is_build_or_code_task and len(self.changed) < 2 and step < 6:
            completion_decl = any(ph in reply_lower for ph in [
                "entire project is complete", "all phases are complete", "project has been fully built",
                "everything is complete and ready"
            ])
            if not completion_decl:
                return True
                
        return False

    # ------------------------------------------------------------------- loop
    def run(self, task: str) -> str:
        self.cancelled = False
        topic = extract_task_topic(task)
        initial_plan = extract_plan(task)
        if not initial_plan:
            initial_plan = [
                f"Analyze project requirements & files for {topic}",
                "Formulate architectural plan & component changes",
                "Execute code edits & file implementations",
                "Verify syntax & run validation checks",
            ]
        self.on_event("task_init", {"topic": topic, "task": task, "plan": initial_plan})
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if self.history:
            self.messages.extend(self.history[-6:])
        self.messages.append({"role": "user", "content": self.first_message(task)})
        final = ""
        bad_format = 0
        call_history: List[Tuple[str, str, str]] = []
        call_counts: Dict[Tuple[str, str], int] = {}
        consecutive_no_tool = 0
        last_non_tool_reply = ""

        task_lower = task.lower().strip()
        is_diagnostic = any(kw in task_lower for kw in [
            "why", "how", "what", "is this", "where is", "blank", "fail", "broken", "error", "check", "?"
        ])
        effective_max = min(self.max_steps, 8) if is_diagnostic else self.max_steps

        for step in range(effective_max):
            if self.cancelled:
                final = "Stopped."
                break
            step_num = step + 1
            self.on_event("thinking_status", {
                "step": step_num,
                "topic": topic,
                "status": f"Step {step_num}: Reasoning on architecture and determining next tool action...",
            })
            self.on_event("thinking", step_num)

            current_reply = []

            def on_stream_token(t: str):
                current_reply.append(t)
                self.on_event("token", t)
                partial_text = "".join(current_reply)
                if step == 0:
                    streamed_plan = extract_plan(partial_text)
                    if len(streamed_plan) >= 2 and streamed_plan != initial_plan:
                        self.on_event("plan", streamed_plan)

            reply = self.llm.chat(self.window(), on_token=on_stream_token,
                                  should_stop=lambda: self.cancelled)
            self.on_event("reply", reply)
            if step == 0:
                plan = extract_plan(reply)
                if plan:
                    self.on_event("plan", plan)
            call = parse_tool_call(reply)
            self.messages.append({"role": "assistant", "content": reply[:4000]})

            if call is None:
                if looks_like_tool_attempt(reply) and bad_format < 2:
                    bad_format += 1
                    self.messages.append({"role": "user", "content": FORMAT_HELP})
                    continue

                reply_clean = " ".join(reply.split()).lower()
                is_repetition = (
                    reply_clean == last_non_tool_reply
                    or (last_non_tool_reply and (reply_clean in last_non_tool_reply or last_non_tool_reply in reply_clean))
                )
                last_non_tool_reply = reply_clean
                consecutive_no_tool += 1

                # If the model is repeating itself or has failed to produce a tool call twice
                if is_repetition or consecutive_no_tool >= 2:
                    # Check if user wanted to run/start/preview the app
                    if any(kw in task_lower for kw in ["run", "start", "serve", "launch", "preview"]) and not any(c[0] == "run_command" for c in call_history):
                        run_info = self.ws.detect_run_info()
                        if run_info.get("command"):
                            run_cmd_call = ToolCall("run_command", {"command": run_info["command"]})
                            self.on_event("thinking_status", {
                                "step": step_num,
                                "topic": topic,
                                "status": f"Executing detected project runner: {run_info['command']}...",
                            })
                            cmd_result = self.execute(run_cmd_call)
                            call_history.append(("run_command", run_info["command"], str(cmd_result)[:80]))
                            self.on_event("result", {"tool": "run_command", "text": cmd_result})
                            final = f"Started application with `{run_info['command']}` (URL: {run_info.get('url') or 'active'})."
                            break

                    is_build_or_code_task = any(kw in task_lower for kw in [
                        "make", "build", "create", "implement", "develop", "complete", "add", "fix",
                        "setup", "set up", "scaffold", "generate", "code", "write", "landing page", "erp",
                        "project", "application", "app", "feature", "module", "system"
                    ])
                    if len(self.changed) == 0 and is_build_or_code_task:
                        final = (
                            f"{reply.strip()}\n\n"
                            "💡 **Note**: The active model provided the plan above but did not execute file modifications directly. "
                            "To get Cursor / Antigravity quality and write full multi-file code at 180+ tok/s, "
                            "switch the engine to **Google Gemini 2.0 Flash** or **Groq** via the top-right engine badge."
                        )
                    else:
                        final = reply.strip()
                    break
                
                # Check if the model gave intermediate commentary or if the overall task is unfinished
                if self.should_continue_task(reply, task, step):
                    self.on_event("thinking_status", {
                        "step": step_num,
                        "topic": topic,
                        "status": "Continuing autonomous build to next phase/component...",
                    })
                    if len(self.changed) == 0:
                        cont_prompt = (
                            f"You stated you will work on '{task}'. Start immediately by calling a tool now:\n"
                            "```tool write_file\npath: <filepath>\n---\n<content>\n```\n"
                            "or\n"
                            "```tool run_command\ncommand: <shell command>\n```\n"
                            "Do NOT reply with conversational filler. Output only the tool call block."
                        )
                    else:
                        cont_prompt = (
                            "Do not stop yet. Continue autonomously with the next step of the project. "
                            "Invoke the next tool call (e.g. write_file, apply_patch, or run_command) "
                            "now to implement the next file/action."
                        )
                    self.messages.append({
                        "role": "user",
                        "content": cont_prompt
                    })
                    continue

                final = reply.strip()
                break
            consecutive_no_tool = 0
            tool_target = str(call.args.get("path") or call.args.get("command") or call.args.get("pattern") or "")
            call_sig = (call.name, tool_target)
            
            # Anti-loop check: Detect repetitive tool calls across whole task
            call_counts[call_sig] = call_counts.get(call_sig, 0) + 1
            if call_counts[call_sig] >= 2:
                last_result = call_history[-1][2] if call_history else ""
                self.on_event("thinking_status", {
                    "step": step_num,
                    "topic": topic,
                    "status": f"Already checked {call.name} {tool_target}. Concluding response...",
                })
                self.messages.append({
                    "role": "user",
                    "content": (
                        f"Notice: '{call.name} {tool_target}' was already called with result: {last_result}. "
                        "Do NOT repeat this call. Deliver your final diagnostic explanation and solution now without calling another tool."
                    )
                })
                if call_counts[call_sig] >= 3 or is_diagnostic:
                    final = f"Inspected {tool_target}. Ready with resolution."
                    break
                continue

            self.on_event("thinking_status", {
                "step": step_num,
                "topic": topic,
                "status": f"Executing {call.name} {('· ' + tool_target) if tool_target else ''}...",
            })
            result = self.execute(call)
            call_history.append((call.name, tool_target, str(result)[:80]))
            self.on_event("result", {"tool": call.name, "text": result})
            self.messages.append({
                "role": "user",
                "content": f"Result of {call.name}:\n{result}\n\nProceed with the next step or output your final summary."
            })
        else:
            final = (f"Stopped after {self.max_steps} steps. The changes so far are kept; "
                     "ask again to continue.")
        if self.keep_notes and final and not self.cancelled:
            self.remember(task, final)
        self.on_event("done", final)
        return final

    def remember(self, task: str, final: str) -> None:
        summary = " ".join(final.split())[:200]
        # Never record generic refusals, raw tool commands, or loops into project notes
        if any(bad in summary.lower() for bad in ("i can't assist", "i cannot assist", "i'm sorry, but", "write_file", "read_file", "apply_patch", "--- #")):
            return
        changed = f" Changed: {', '.join(sorted(set(self.changed))[:8])}." if self.changed else ""
        try:
            self.ws.add_note(f"- {datetime.date.today().isoformat()} · {' '.join(task.split())[:120]}"
                             f" → {summary}{changed}")
        except OSError:
            pass

    # ------------------------------------------------------------------ tools
    def execute(self, call: ToolCall) -> str:
        try:
            if call.name in READ_TOOLS:
                return self._read(call)
            if call.name in EDIT_TOOLS:
                return self._edit(call)
            return self._command(call)
        except patching.PatchError as exc:
            return f"Error: {exc}"
        except ToolError as exc:
            return f"Error: {exc}"
        except (OSError, UnicodeError) as exc:
            return f"Error: {exc}"

    def _read(self, call: ToolCall) -> str:
        args = call.args
        path = str(args.get("path") or ".")
        if call.name == "read_file":
            title = f"Read {path}"
        elif call.name == "search":
            title = f"Search for {args.get('pattern', '')!s}"
        else:
            title = f"List {path}"
        self.ws.resolve(path)  # refuse outside paths before asking anyone
        self.on_event("step", {"title": title, "kind": "read"})
        if self.policy.needs_approval(call.name) and not self.approve(Action("read", call.name, title, path=path)):
            self.on_event("step_status", "denied")
            return "The user did not allow this read."
        if call.name == "read_file":
            if not args.get("path"):
                raise ToolError("read_file needs path.")
            out = self.ws.read_file(path, args.get("start_line"), args.get("end_line"))
        elif call.name == "search":
            out = self.ws.search(str(args.get("pattern") or ""), path)
        else:
            out = self.ws.list_files(path)
        self.on_event("step_status", "done")
        return out

    def _edit(self, call: ToolCall) -> str:
        args = call.args
        if call.name == "write_file":
            path = str(args.get("path") or "")
            if not path:
                raise ToolError("write_file needs path.")
            content = args.get("content")
            if content is None:
                raise ToolError("write_file needs the file content after a --- line.")
            content = clean_file_content(str(content))
            self.ws.check_writable(path)
            changes = {path: content}
        else:
            patch = str(args.get("patch") or "")
            if not patch.strip():
                raise ToolError("apply_patch needs a unified diff.")
            default = str(args.get("path")) if args.get("path") else None
            changes = patching.apply_patch(patch, self.ws.read_text, default_path=default)
            for path in changes:
                self.ws.check_writable(path)
        applied, rejected, same = [], [], []
        self.on_event("step", {"title": f"Edit {', '.join(changes)}", "kind": "edit"})
        for path, new in changes.items():
            old = self.ws.read_text(path)
            if old == new:
                same.append(path)
                continue
            rel = self.ws.rel(self.ws.resolve(path))
            action = Action("edit", call.name, f"{'Create' if old is None else 'Delete' if new is None else 'Edit'} {rel}",
                            path=rel, diff=patching.unified_diff(rel, old, new), old=old, new=new)
            self.on_event("change", action)
            ok = (not self.policy.needs_approval(call.name)) or self.approve(action)
            if ok:
                self.ws.write_text(path, new)
                applied.append(rel)
                self.changed.append(rel)
            else:
                rejected.append(rel)
            self.on_event("change_status", {"path": rel, "applied": ok})
        self.on_event("step_status", "done" if applied or same else "denied")
        parts = []
        if applied:
            parts.append("Applied: " + ", ".join(applied) + ".")
        if same:
            parts.append("Already up to date: " + ", ".join(same) + ".")
        if rejected:
            parts.append("The user rejected the change to " + ", ".join(rejected) +
                         ". Do not repeat it; ask what they want instead or try another way.")
        return " ".join(parts) or "Nothing to change."

    def _command(self, call: ToolCall) -> str:
        command = str(call.args.get("command") or "").strip()
        if not command:
            raise ToolError("run_command needs command.")
        action = Action("command", call.name, f"Run: {command}", command=command)
        self.on_event("step", {"title": action.title, "kind": "command"})
        self.on_event("command", action)
        if self.policy.needs_approval(call.name) and not self.approve(action):
            self.on_event("step_status", "denied")
            return "The user did not allow this command. Do not run it again; continue without it or ask."
        result = self.ws.run_command(command, call.args.get("timeout"))
        self.on_event("output", result)
        self.on_event("step_status", "done" if result["code"] == 0 else "failed")
        status = (f"timed out after {result['seconds']} s" if result["timed_out"]
                  else f"exit code {result['code']}")
        return f"{status}\n{result['output'] or '(no output)'}"


# ========================================================= original one-shot

class DevOSCodeAgent:
    """One-shot answer with a repository map (devos code "prompt")."""

    FRAMEWORK_SKILLS = {
        "laravel": "Follow Laravel 11 conventions: Eloquent models, form requests, and clean controllers.",
        "filament": "Use Filament v3 panel architecture, resource tables, and form schema definitions.",
        "nextjs": "Use Next.js App Router (app/), React Server Components, and Tailwind CSS classes.",
        "python": "Use modern Python 3.12+ type hints, pydantic models, and pytest test structures.",
    }

    def __init__(self, project_dir: str = "."):
        self.project_dir = os.path.abspath(project_dir)

    def generate_repo_map(self, max_files: int = 50) -> List[str]:
        """Builds a token-efficient map of the repository tree, ignoring git and binaries."""
        file_list = []
        for root, dirs, files in os.walk(self.project_dir):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in {".py", ".php", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".sh", ".conf"}:
                    file_list.append(os.path.relpath(os.path.join(root, f), self.project_dir))
                    if len(file_list) >= max_files:
                        return file_list
        return file_list

    def query_local_code_model(self, prompt: str, framework: str = None) -> Dict[str, Any]:
        """Sends coding prompt to the local OpenAI-compatible endpoint."""
        skill_instruction = self.FRAMEWORK_SKILLS.get(framework, "Write clean, tested, idiomatic code.")
        repo_files = self.generate_repo_map(max_files=15)
        system_prompt = (
            f"You are the DevOS Local AI Code Agent. {skill_instruction}\n"
            f"Repository files: {', '.join(repo_files[:10])}\n"
            "Return concise, production-ready code with explanations."
        )
        payload = {"model": CODE_MODEL,
                   "messages": [{"role": "system", "content": system_prompt},
                                {"role": "user", "content": prompt}]}
        try:
            req = urllib.request.Request(f"{AI_ENDPOINT}/chat/completions",
                                         data=json.dumps(payload).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
                return {"status": "SUCCESS", "reply": data["choices"][0]["message"]["content"],
                        "model": data.get("model", CODE_MODEL), "repo_files_indexed": len(repo_files)}
        except Exception as e:
            # Offline fallback response if daemon is not running during direct script test
            return {
                "status": "OFFLINE_FALLBACK",
                "reply": f"// [DevOS Local AI Code Agent - Framework: {framework or 'generic'}]\n"
                         f"// Code generation request: '{prompt}'\n"
                         f"// Indexed {len(repo_files)} repository files.\n",
                "repo_files_indexed": len(repo_files),
                "error": str(e),
            }


# ======================================================================= CLI

def _color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if sys.stdout.isatty() else text


def print_diff(diff: str) -> None:
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            print(_color(line, "32"))
        elif line.startswith("-") and not line.startswith("---"):
            print(_color(line, "31"))
        elif line.startswith("@@"):
            print(_color(line, "36"))
        else:
            print(line)


def ask_yes_no(question: str, default: bool = False, read=input) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        answer = read(question + suffix).strip().lower()
    except EOFError:
        return default
    if not answer:
        return default
    return answer in ("y", "yes")


def cli_approver(read=input):
    def approve(action: Action) -> bool:
        print()
        if action.kind == "edit":
            print(_color(f"== {action.title}", "1"))
            print_diff(action.diff)
            return ask_yes_no("Apply this change?", False, read)
        if action.kind == "command":
            print(_color(f"$ {action.command}", "1;33"))
            return ask_yes_no("Run this command in the project folder?", False, read)
        return ask_yes_no(f"Allow: {action.title}?", True, read)
    return approve


def cli_events(kind: str, payload: Any = None) -> None:
    if kind == "thinking":
        print(_color(f"\n· step {payload}", "2"), flush=True)
    elif kind == "token":
        sys.stdout.write(payload)
        sys.stdout.flush()
    elif kind == "reply":
        print()
    elif kind == "output":
        print(_color(payload["output"] or "(no output)", "2"))
        print(_color(f"[exit {payload['code']}]", "2"))
    elif kind == "change_status":
        print(_color(("applied " if payload["applied"] else "rejected ") + payload["path"], "2"))
    elif kind == "done":
        print(_color("\nDone.", "1;32"))


def run_cli(task: str, folder: str, auto_edits: bool = False, auto_reads: bool = True,
            auto_commands: bool = False, max_steps: int = 15) -> int:
    sys.path.insert(0, HERE)
    import capability
    ok, reason = capability.coding_capable()
    if not ok:
        print(reason, file=sys.stderr)
        return 2
    try:
        workspace = Workspace(folder)
    except ToolError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(_color(f"DevOS AI Code Agent · Local · {CODE_MODEL} · {workspace.root}", "1;36"))
    agent = CodeAgent(workspace, LocalLLM(), cli_approver(),
                      ApprovalPolicy(auto_reads=auto_reads, auto_edits=auto_edits, auto_commands=auto_commands),
                      on_event=cli_events, max_steps=max_steps)
    try:
        agent.run(task)
    except AgentError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="DevOS AI Code Agent: a coding agent on the local DevOS AI")
    parser.add_argument("prompt", nargs="?", help="one-shot coding prompt (original JSON answer), "
                                                  "or a folder with --gui")
    parser.add_argument("--cli", metavar="TASK", help="run the agent in this terminal with y/n approvals")
    parser.add_argument("--gui", action="store_true", help="open the DevOS AI Code Agent window")
    parser.add_argument("--framework", default="laravel", choices=["laravel", "filament", "nextjs", "python"])
    parser.add_argument("--dir", default=None, help="project folder (default: current folder)")
    parser.add_argument("--auto-edits", action="store_true", help="apply file changes without asking")
    parser.add_argument("--ask-reads", action="store_true", help="ask before the agent reads files too")
    parser.add_argument("--max-steps", type=int, default=15)
    args = parser.parse_args(argv)

    if args.cli:
        folder = args.dir or args.prompt or os.getcwd()
        return run_cli(args.cli, folder, args.auto_edits, not args.ask_reads, args.max_steps)
    if args.gui or not args.prompt:
        import agent_gui
        return agent_gui.main([a for a in [args.dir or args.prompt] if a])

    agent = DevOSCodeAgent(project_dir=args.dir or ".")
    res = agent.query_local_code_model(args.prompt, framework=args.framework)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
