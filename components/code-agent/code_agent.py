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
import zlib
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import patching  # noqa: E402
import brief  # noqa: E402
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
LONG_TASK_CHARS = 1500   # a brief longer than this is split into build phases
MAX_PHASES = 6
PHASE_STEPS = 14         # model turns allowed per phase of a brief with no phases of its own
BRIEF_PHASE_STEPS = 24   # model turns per phase when the brief defines its own phases
MAX_CONTINUATIONS = 1    # times a reply cut off inside a code block is continued
MAX_REPLY_TOKENS = 2600  # one reply (about 250 lines of code); a file takes minutes on this PC, so replies stay short
MAX_FILE_LINES = 450     # a single generated file longer than this is cut: it is a loop, not a file
MIN_PARALLEL_FILES = 3
MAX_PARALLEL_FILES = 8   # files written at the same time (on this CPU 4 files run at ~3.4x the speed of one)
PARALLEL_FILE_TOKENS = 1800
HISTORY_BUDGET = 24000   # characters of conversation sent per step (supports up to 32k-token window)
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

    def read_text_safe(self, path: str) -> Optional[str]:
        """None when the file does not exist; '' when it cannot be read or is outside the project (so callers stay away)."""
        try:
            return self.read_text(path)
        except (ToolError, OSError):
            return ""

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
    def run_command(self, command: str, timeout: Any = None, should_stop: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
        seconds = min(max(_int(timeout, COMMAND_TIMEOUT), 1), MAX_TIMEOUT)
        posix = os.name == "posix"
        is_server = any(p in command.lower() for p in [
            "artisan serve", "manage.py runserver", "http.server", "npm run dev",
            "npm start", "yarn dev", "pnpm dev", "vite", "uvicorn", "flask run"
        ])
        proc = subprocess.Popen(
            ["/bin/bash", "-c", command] if posix and os.path.exists("/bin/bash") else command,
            shell=not (posix and os.path.exists("/bin/bash")), cwd=self.root,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=posix)

        if is_server:
            # Dev servers are persistent daemons and should not be killed with timeout
            try:
                time.sleep(1.8)
                exit_code = proc.poll()
                if exit_code is None:
                    try:
                        import fcntl
                        fl = fcntl.fcntl(proc.stdout.fileno(), fcntl.F_GETFL)
                        fcntl.fcntl(proc.stdout.fileno(), fcntl.F_SETFL, fl | os.O_NONBLOCK)
                        raw_initial = proc.stdout.read()
                        text = (raw_initial or b"").decode("utf-8", errors="replace")
                    except Exception:
                        text = ""
                    if not text.strip():
                        text = f"Server started and running with `{command}`."
                    text += f"\n\n[Dev server active and running in background (PID {proc.pid})]"
                    return {"code": 0, "output": text, "timed_out": False, "seconds": 2}
                else:
                    out, _ = proc.communicate(timeout=2)
                    text = (out or b"").decode("utf-8", errors="replace")
                    return {"code": exit_code, "output": cap_output(text), "timed_out": False, "seconds": 2}
            except Exception:
                pass

        timed_out = False
        stopped = False
        deadline = time.time() + seconds
        out = b""
        while True:
            try:
                out, _ = proc.communicate(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                stopped = bool(should_stop and should_stop())
                timed_out = time.time() > deadline
                if stopped or timed_out:
                    try:
                        if posix:
                            os.killpg(proc.pid, signal.SIGKILL)
                        else:
                            proc.kill()
                    except OSError:
                        pass
                    out, _ = proc.communicate()
                    break
        if stopped:
            out = (out or b"") + b"\n[stopped by the user]"
        text = (out or b"").decode("utf-8", errors="replace")
        return {"code": proc.returncode, "output": cap_output(text), "timed_out": timed_out,
                "seconds": seconds}

    def detect_run_info(self) -> Dict[str, Any]:
        """Intelligently detects application type, run/serve command, port, and landing page URL."""
        root = self.root

        # 1. PHP / Laravel (Prioritized: Laravel contains package.json for vite, but primary server is artisan)
        if os.path.isfile(os.path.join(root, "artisan")):
            return {
                "type": "PHP / Laravel Application",
                "command": "php artisan serve",
                "port": 8000,
                "url": "http://localhost:8000",
                "preview_url": "http://localhost:8000",
                "hint": "artisan"
            }

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

        # 4. Node / Frontend / Vite / Next.js / Express
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

    # ---------------------------------------------------------- understanding
    def project_brief(self, limit: int = 1400) -> str:
        """A few lines about what this project is built with, from its manifests,
        so the model starts with the stack instead of guessing it."""
        lines: List[str] = []

        def load(name: str) -> Optional[Any]:
            try:
                with open(os.path.join(self.root, name), encoding="utf-8") as handle:
                    return json.load(handle)
            except (OSError, ValueError):
                return None

        composer = load("composer.json")
        if isinstance(composer, dict):
            req = composer.get("require") or {}
            key = [f"{k} {v}" for k, v in req.items() if k != "php" and not k.startswith("ext-")][:10]
            lines.append(f"PHP {req.get('php', '')} · composer packages: " + (", ".join(key) or "none"))
        pkg = load("package.json")
        if isinstance(pkg, dict):
            deps = list((pkg.get("dependencies") or {}))[:8] + list((pkg.get("devDependencies") or {}))[:6]
            lines.append("Node scripts: " + (", ".join((pkg.get("scripts") or {}).keys()) or "none")
                         + " · packages: " + (", ".join(deps) or "none"))
        for name in ("requirements.txt", "pyproject.toml", "go.mod", "Cargo.toml"):
            path = os.path.join(self.root, name)
            if os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8", errors="replace") as handle:
                        head = " ".join(handle.read(400).split())
                    lines.append(f"{name}: {head[:300]}")
                except OSError:
                    pass
        dirs = []
        try:
            for entry in sorted(os.listdir(self.root)):
                if os.path.isdir(os.path.join(self.root, entry)) and entry not in IGNORED_DIRS \
                        and not entry.startswith("."):
                    dirs.append(entry)
        except OSError:
            pass
        if dirs:
            lines.append("Top-level folders: " + ", ".join(dirs[:20]))
        if os.path.isfile(os.path.join(self.root, "routes", "web.php")):
            lines.append("Laravel routes live in routes/web.php; views in resources/views; controllers in app/Http/Controllers.")
        for name in ("README.md", "readme.md"):
            path = os.path.join(self.root, name)
            if os.path.isfile(path):
                try:
                    with open(path, encoding="utf-8", errors="replace") as handle:
                        lines.append("README: " + " ".join(handle.read(500).split()))
                except OSError:
                    pass
                break
        return "\n".join(lines)[:limit]

    def check_syntax(self, path: str) -> str:
        """'' when the file parses (or its type is not checked), else the error.
        Run right after a write so a typo is fixed in the next step, not found later."""
        real = self.resolve(path)
        ext = os.path.splitext(real)[1].lower()
        try:
            if ext == ".py":
                with open(real, encoding="utf-8") as handle:
                    compile(handle.read(), real, "exec")
                return ""
            if ext == ".json":
                with open(real, encoding="utf-8") as handle:
                    json.load(handle)
                return ""
            tool = {".php": ["php", "-l"], ".js": ["node", "--check"], ".mjs": ["node", "--check"],
                    ".cjs": ["node", "--check"], ".sh": ["bash", "-n"]}.get(ext)
            if not tool or ext == ".php" and real.endswith(".blade.php") or not shutil.which(tool[0]):
                return ""
            done = subprocess.run(tool + [real], capture_output=True, text=True, timeout=15, cwd=self.root)
            if done.returncode != 0:
                return cap_output((done.stderr or done.stdout).strip().replace(real, path), 600)
        except SyntaxError as exc:
            return f"{exc.msg} (line {exc.lineno})"
        except ValueError as exc:
            return str(exc)
        except (OSError, subprocess.SubprocessError, UnicodeError):
            return ""
        return ""

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


def _block_call(info: str, body: str) -> Optional[ToolCall]:
    """The tool call one fenced block holds, or None for a plain code block."""
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
    return ToolCall(name, _parse_body(name, body), body) if name else None


MAX_CALLS_PER_REPLY = 4


# A small model sometimes puts several files in one write_file block: after a file's content it writes
# "next/path.ext" and a line "---" and goes on. Each such path starts a new file.
_NEXT_FILE_RE = re.compile(r"(?m)^[ \t]*(?:path:[ \t]*)?([\w@./\-\[\]]+\.[A-Za-z0-9]{1,8})[ \t]*\n---[ \t]*\n")


def split_multi_file(call: ToolCall) -> List[ToolCall]:
    if call.name != "write_file":
        return [call]
    content = str(call.args.get("content") or "")
    marks = list(_NEXT_FILE_RE.finditer(content))
    if not marks:
        return [call]
    out = [ToolCall("write_file", {"path": call.args.get("path"), "content": content[:marks[0].start()]}, call.raw)]
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(content)
        out.append(ToolCall("write_file", {"path": m.group(1), "content": content[m.end():end]}, ""))
    return out


def parse_tool_calls(text: str, limit: int = MAX_CALLS_PER_REPLY) -> List[ToolCall]:
    """Every tool call in a model reply, in order. Several blocks in one reply save
    a model round trip each; a command ends the batch because what comes next
    depends on its output."""
    if not text:
        return []
    calls: List[ToolCall] = []
    for info, body in _fenced_blocks(text):
        call = _block_call(info, body)
        if call:
            calls.extend(split_multi_file(call))
            if call.name == "run_command" or len(calls) >= limit:
                return calls
    if calls:
        return calls
    for match in _TOOLCALL_RE.finditer(text):
        data = loads_lenient(match.group(1))
        if isinstance(data, dict):
            name = normalize_tool_name(str(data.get("name") or data.get("tool") or ""))
            if name:
                calls.append(ToolCall(name, _parse_body(name, match.group(1)), match.group(1)))
                if len(calls) >= limit:
                    break
    return calls


def parse_tool_call(text: str) -> Optional[ToolCall]:
    """The first tool call in a model reply, or None when it is a final answer."""
    calls = parse_tool_calls(text, limit=1)
    return calls[0] if calls else None


_LOOSE_PATH = r"[\w@.\-]+(?:/[\w@.\-\[\]]+)*\.[A-Za-z0-9]{1,8}"
_LOOSE_HEAD_RE = re.compile(
    r"(?:^|\n)[ \t]*(?:#{1,6}[ \t]*|[-*][ \t]+|\d+[.)][ \t]+)?(?:\*\*|`)?(?:file|path|create|filename)?:?[ \t]*"
    r"(?:\*\*|`)?(" + _LOOSE_PATH + r")(?:\*\*|`)?:?[ \t]*\n[ \t]*```[\w+#.-]*[ \t]*\n(.*?)\n[ \t]*```", re.S | re.I)
_LOOSE_INNER_RE = re.compile(r"^[ \t]*(?:<\?php\s*)?(?://|#|/\*|<!--)[ \t]*(?:file(?:name)?|path)\s*:\s*(" + _LOOSE_PATH + r")", re.I)


def parse_loose_files(text: str, limit: int = MAX_CALLS_PER_REPLY) -> List[ToolCall]:
    """When a small model answers with 'path/to/file.ext' followed by a code block
    instead of a tool block, treat each such pair as a write_file."""
    calls: List[ToolCall] = []
    for match in _LOOSE_HEAD_RE.finditer(text or ""):
        path, body = match.group(1), match.group(2)
        if path.lower().startswith(("http", "www.")) or "/" not in path and len(body.strip()) < 20:
            continue
        calls.append(ToolCall("write_file", {"path": path, "content": body + "\n"}, body))
        if len(calls) >= limit:
            return calls
    if calls:
        return calls
    for info, body in _fenced_blocks(text or ""):
        first = body.lstrip("\n").split("\n", 1)[0]
        m = _LOOSE_INNER_RE.match(first)
        if m and not _is_tool_fence(info):
            calls.append(ToolCall("write_file", {"path": m.group(1), "content": body + "\n"}, body))
            if len(calls) >= limit:
                break
    return calls


def has_unclosed_fence(text: str) -> bool:
    return len(re.findall(r"^[ \t]*```", text or "", re.M)) % 2 == 1


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
                 max_tokens: int = 4096, timeout: int = 600, temperature: float = 0.15):
        active = providers.get_active_engine()
        self.endpoint = (endpoint or active["endpoint"]).rstrip("/")
        self.model = model or active["model"]
        self.api_key = api_key if api_key is not None else active["api_key"]
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.temperature = temperature
        self.is_local = (active.get("is_local", True) if endpoint is None else
                         ("127.0.0.1" in self.endpoint or "localhost" in self.endpoint))
        self.provider_name = active.get("name", "AI Engine")
        self._current_resp = None
        self.last_finish = ""      # "stop" or "length" (the reply hit max_tokens and was cut off)

    def context_tokens(self) -> int:
        """The model window the server runs with (tokens). Cloud engines have plenty. A failed lookup is
        not remembered, so a server that was still starting is asked again next time."""
        if not self.is_local:
            return 32768
        cached = getattr(self, "_ctx_tokens", 0)
        if cached:
            return cached
        base = self.endpoint[:-3] if self.endpoint.endswith("/v1") else self.endpoint
        try:
            req = urllib.request.Request(base + "/health", headers={"User-Agent": "DevOS-Code-Agent/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            speed = data.get("speed") if isinstance(data, dict) else None
            speed = speed if isinstance(speed, dict) else {}
            ctx = int(speed.get("code_context") or speed.get("context") or 0)
            if ctx >= 2048:
                self._ctx_tokens = ctx
                return ctx
        except Exception:
            pass
        return 8192

    def supports_batch(self) -> bool:
        """True when this engine can write several files at once (the local DevOS AI server can)."""
        if not self.is_local or getattr(self, "_batch_broken", False):
            return False
        cached = getattr(self, "_batch_supported", None)
        if cached is not None:
            return cached
        base = self.endpoint[:-3] if self.endpoint.endswith("/v1") else self.endpoint
        ok = False
        try:
            req = urllib.request.Request(base + "/health", headers={"User-Agent": "DevOS-Code-Agent/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            ok = isinstance(data, dict) and isinstance(data.get("batch"), dict)
        except Exception:
            return False                       # not remembered: the server may still be starting
        self._batch_supported = ok
        return ok

    def chat_batch(self, messages: List[Dict[str, str]], branches: List[Dict[str, str]],
                   on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
                   should_stop: Optional[Callable[[], bool]] = None, max_tokens: int = 1800,
                   temperature: Optional[float] = None) -> Dict[str, Any]:
        """Write several independent answers from one shared prompt at the same time. `on_event` gets the
        server's events (start / delta / end / done); the result holds each branch's text and why it ended."""
        payload = {"model": self.model, "messages": messages, "branches": branches, "max_tokens": max_tokens,
                   "temperature": self.temperature if temperature is None else temperature}
        req = urllib.request.Request(f"{self.endpoint}/devos/batch", data=json.dumps(payload).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (404, 405):
                self._batch_broken = True       # an older server without the endpoint
            raise AgentError(f"The AI server cannot write files in parallel ({exc.code}).")
        except (urllib.error.URLError, OSError) as exc:
            raise AgentError(f"DevOS AI is not answering: {exc}")
        self._current_resp = resp
        out: Dict[str, Any] = {"branches": {}, "tokens_per_sec": 0.0, "error": ""}
        texts: Dict[str, str] = {}
        try:
            with resp:
                for raw in resp:
                    if should_stop and should_stop():
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except ValueError:
                        continue
                    kind = event.get("type")
                    if kind == "delta":
                        texts[event["id"]] = texts.get(event["id"], "") + event.get("text", "")
                    elif kind == "end":
                        out["branches"][event["id"]] = {"text": texts.get(event["id"], ""), "reason": event.get("reason", ""),
                                                        "tokens": event.get("tokens", 0)}
                    elif kind == "done":
                        out["tokens_per_sec"] = event.get("tokens_per_sec", 0.0)
                    elif kind == "error":
                        out["error"] = event.get("message", "error")
                    if on_event:
                        on_event(event)
        except (OSError, ValueError):
            pass
        finally:
            self._current_resp = None
        for bid, text in texts.items():          # branches cut off by a stop or an error keep what they wrote
            out["branches"].setdefault(bid, {"text": text, "reason": "stopped", "tokens": 0})
        return out

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
             should_stop: Optional[Callable[[], bool]] = None, options: Optional[Dict[str, Any]] = None) -> str:
        self.last_finish = ""
        payload = {"model": self.model, "messages": messages, "stream": True,
                   "temperature": self.temperature, "max_tokens": self.max_tokens}
        if options:
            payload.update(options)
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(f"{self.endpoint}/chat/completions",
                                     data=json.dumps(payload).encode("utf-8"), headers=headers)
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
            self._current_resp = resp
        except urllib.error.HTTPError as exc:
            # A responding server is already running; restarting it cannot fix a
            # missing model, invalid request, or rejected credential.
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise AgentError(f"{self.provider_name} ({self.model}) returned HTTP {exc.code}: {detail}") from exc
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
                choice = (data.get("choices") or [{}])[0]
                text = choice.get("message", {}).get("content", "") or ""
                self.last_finish = choice.get("finish_reason") or "stop"
                if on_token and text:
                    on_token(text)
                return text
            meta: Dict[str, Any] = {}
            text = read_sse(resp, on_token, should_stop, meta)
            self.last_finish = meta.get("finish_reason", "")
            return text


def read_sse(lines, on_token=None, should_stop=None, meta: Optional[Dict[str, Any]] = None) -> str:
    """Join the content deltas of an OpenAI-style event stream. meta["finish_reason"]
    is filled in when the stream reports one ("length" = cut off at max_tokens)."""
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
                if meta is not None and choice.get("finish_reason"):
                    meta["finish_reason"] = choice["finish_reason"]
                piece = (choice.get("delta") or {}).get("content") or ""
                if piece:
                    parts.append(piece)
                    if on_token:
                        on_token(piece)
    except (OSError, ValueError):
        pass
    return "".join(parts)


# ===================================================================== agent

SYSTEM_PROMPT = """You are DevOS AI Code Agent, an autonomous senior software engineer working inside the user's project folder. You act; you do not ask permission, wait for a "go", or answer with only a plan.

Tool calls are fenced blocks, exactly like this (reads may be combined; write ONE file or run ONE command per reply, then wait for its result):
```tool read_file
path: routes/web.php
```
Tools:
- list_files  path: <folder>
- read_file   path: <file>   (optional start_line: <n>, end_line: <n>)
- search      pattern: <text or regex>   (optional path: <folder>)
- write_file  path: <file>, then a line with ---, then the COMPLETE file content
- apply_patch path: <file>, then a line with ---, then a unified diff (@@ hunks with exact unchanged lines)
- run_command command: <shell command run in the project folder>

How you work:
1. Build/implement/fix requests: act in your first reply. Read only the 1-3 files you need, then write real code with write_file (new files, rewrites) or apply_patch (small edits to existing files). Reading alone never completes a task.
2. Prefer generators over hand-writing: composer require, php artisan make:*, npm/composer scaffolding. A file written by hand takes minutes on this PC. Always write complete, working code. Never use placeholders, TODO stubs for core logic, or "... rest of code". Keep each file under about 250 lines (split into classes/partials/components) so nothing gets cut off.
3. Follow the project's existing stack and conventions (see the Project Architecture and manifests below). Only use files that exist; create the folders and files you need.
4. After writing code, verify it: a SYNTAX ERROR or failed command in a result means fix it now. Run tests/build/serve only when asked or when it is the natural check. Never run .md/.txt files; use the detected run command for the app.
5. Questions ("why is X blank", "how does this work"): inspect the exact suspect files (Laravel: routes/web.php, the view, the controller; JS: index.html, src/App, package.json; Python: main.py/app.py, routes), find the root cause in 1-3 calls, explain it, and apply the fix when one is needed.
6. If the user rejects a change or command, do not repeat it.
7. When everything is done, reply with a short final summary (files created/changed, how to run it) and no tool block."""

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
                 history: Optional[List[Dict[str, str]]] = None, bootstrap: bool = True,
                 parallel_files: bool = True):
        self.ws = workspace
        self.llm = llm
        self.approve = approve
        self.policy = policy or ApprovalPolicy()
        self._raw_event = on_event
        self.on_event = self._event
        self._tokens_streamed = 0
        self.max_steps = max_steps
        self.keep_notes = keep_notes
        self.bootstrap = bootstrap     # create a framework skeleton with its own installer when the brief names one
        self.parallel_files = parallel_files   # write a phase's independent new files at the same time
        self.cancelled = False
        self.messages: List[Dict[str, str]] = []
        self.changed: List[str] = []
        self.history: List[Dict[str, str]] = history or []
        self.grounding = None          # brief.Grounding: which packages the user's brief allows
        self._brief = None
        self.brief_ctx = ""
        self.history_budget = HISTORY_BUDGET
        self._outcome = "done"         # how the last _loop ended: done / cancelled / limit / empty
        self._commands_run = 0
        self._commands_log: List[Tuple[str, int]] = []     # (command, exit code) of every command this agent ran
        self._task_idx = 1             # index of the task message in self.messages
        self._multi_cut = False
        self._multi_notice = False
        self._cut: Optional[str] = None
        self._bootstrap_note = ""
        self._runaway_notice = ""

    def _event(self, kind: str, payload: Any = None) -> None:
        if kind == "token":
            self._tokens_streamed += 1
        self._raw_event(kind, payload)

    def cancel(self) -> None:
        self.cancelled = True
        if hasattr(self.llm, "close"):
            try:
                self.llm.close()
            except Exception:
                pass

    # ---------------------------------------------------------------- context
    def first_message(self, task: str, directive: bool = True) -> str:
        files = self.ws.list_files(".", limit=40)
        notes = self.ws.read_notes()
        run_info = self.ws.detect_run_info()
        parts = [f"Project folder: {os.path.basename(self.ws.root) or self.ws.root}"]
        if run_info.get("command"):
            url_hint = f" (serves landing page on {run_info['url']})" if run_info.get("url") else ""
            parts.append(f"Project Architecture: {run_info['type']}\n"
                         f"Detected Run Command: `{run_info['command']}`{url_hint}")
        brief = self.ws.project_brief()
        if brief:
            parts.append("Project manifests:\n" + brief)
        parts.append("Files:\n" + files)
        if notes:
            parts.append("Project notes (.devos/agent-notes.md):\n" + notes)
        if self.brief_ctx:
            parts.append("The user's saved brief for this project:\n" + self.brief_ctx)
        parts.append("Task: " + task.strip())
        if directive:
            parts.append(
                "Execution Directive: Fulfill the task using tool blocks, starting with this reply.\n"
                "```tool write_file\npath: <path>\n---\n<complete code>\n```  to create/replace a file;\n"
                "```tool read_file\npath: <path>\n```  only when you must see a file first.\n"
                "No conversational filler, no questions."
            )
        return "\n\n".join(parts)

    def window(self) -> List[Dict[str, str]]:
        """System + earlier conversation + the task + as many recent turns as fit the model's window.
        Past turns are sent unchanged from step to step, so the server can reuse the part of the
        prompt it already processed (that is most of the wait on a CPU). Only when the budget runs
        out are the oldest results shortened, then dropped. The task message is never shortened
        below a generous limit and never dropped."""
        idx = min(max(self._task_idx, 1), max(len(self.messages) - 1, 0))
        head = [dict(m) for m in self.messages[:idx + 1]]
        for m in head[1:idx]:                       # earlier conversation turns: keep them short
            if len(m.get("content", "")) > 1200:
                m["content"] = m["content"][:1200] + "\n... (shortened)"
        rest = [dict(m) for m in self.messages[idx + 1:]]
        limit = max(18000, self.history_budget // 2)
        if len(head) >= 2 and len(head[-1].get("content", "")) > limit:
            c = head[-1]["content"]
            head[-1]["content"] = c[:limit // 2] + "\n... (context shortened to fit model window) ...\n" + c[-(limit // 2):]
        budget = self.history_budget - sum(len(m["content"]) for m in head)

        def used() -> int:
            return sum(len(m["content"]) for m in rest)

        i = 0
        while used() > budget and i < len(rest) - 2:   # shorten the oldest long turns first
            if len(rest[i]["content"]) > 600:
                rest[i]["content"] = rest[i]["content"][:600] + "\n... (shortened)"
            i += 1
        while used() > budget and len(rest) > 2:       # then drop the oldest
            rest.pop(0)
        return head + rest

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
        if is_build_or_code_task and self._n_changed() == 0 and step < 6:
            return True

        if is_build_or_code_task and self._n_changed() < 2 and step < 6:
            completion_decl = any(ph in reply_lower for ph in [
                "entire project is complete", "all phases are complete", "project has been fully built",
                "everything is complete and ready"
            ])
            if not completion_decl:
                return True
                
        return False

    # ------------------------------------------------------------------- loop
    _WAIT_LINE = re.compile(r"first reply only|wait for my [\"“'‘]?go|after (?:my )?[\"“'‘]?go[\"”'’]?\s*:|"
                            r"^\s*#+\s*\d*\.?\s*how you\b|^\s*begin with step\s+1 now\.?\s*$", re.I)

    @staticmethod
    def _sanitize_task(task: str) -> str:
        """Drop meta-instructions that make the local model answer with talk instead of tool calls
        ('first reply only', 'wait for my go', 'after go:'). Linear time. The 'start immediately'
        note is added only when something was dropped, so ordinary requests are left as written."""
        kept, removed = [], False
        for line in task.split("\n"):
            if len(line) < 1500 and CodeAgent._WAIT_LINE.search(line):
                removed = True
                continue
            kept.append(line)
        text = "\n".join(kept)
        cleaned = re.sub(r"(?i)\b(?:then[ \t]+)?wait[ \t]+for[ \t]+my[ \t]+[\"“'‘]?go[\"”'’]?[ \t]*[.,]?", "", text)
        removed = removed or cleaned != text
        text = cleaned.strip()
        if removed and text:
            if not text.endswith((".", "!")):
                text += "."
            text += ("\n\nNote: do not wait or ask for confirmation first; begin with a tool call.")
        return text

    # ------------------------------------------------------- run: entry points
    def _n_changed(self) -> int:
        """Files changed since this run (or this phase) began."""
        return len(self.changed) - getattr(self, "_base_changed", 0)

    @staticmethod
    def _is_diagnostic(task: str) -> bool:
        """A short question about the project (not a request to build or fix it)."""
        head = task.split("\n\nNote: do not wait")[0].strip().lower()
        if len(head) > 500:
            return False
        build = re.search(r"\b(make|build|create|implement|develop|complete|add|write|generate|scaffold|"
                          r"set ?up|install|refactor|convert|fix|update|change|improve|redesign)\b", head)
        ask = re.search(r"\?|\b(why|how|what|where|which|explain|is this|check|status|blank|fail\w*|broken|error)\b",
                        head)
        return bool(ask and not build)

    def _ground(self, text: str) -> str:
        """Prose for the user with invented packages of the user's vendor replaced or dropped."""
        return self.grounding.ground_text(text)[0] if self.grounding is not None else text

    def run(self, task: str) -> str:
        self.cancelled = False
        self._base_changed = len(self.changed)
        self.history_budget = HISTORY_BUDGET
        self._tokens_streamed = 0
        self._load_grounding()
        try:
            final = self._brief_flow(task)
            if final is None:
                final = self._run_task(task)
        except AgentError as exc:
            if self.changed:  # keep what was built; say how to carry on
                final = (f"Stopped: {exc}\nFiles changed so far: {', '.join(sorted(set(self.changed))[:12])}."
                         + ("\nSay `go` to continue the current phase." if brief.BriefState.load(self.ws.root) else ""))
            else:
                raise
        final = self._ground(final)
        if not final.strip():
            final = self._fallback_summary()
        if self._tokens_streamed == 0 and final:
            self.on_event("report", final)        # an answer that was never streamed (status, notes, errors)
        if self.keep_notes and final and not self.cancelled:
            self.remember(task, final)
        self.on_event("done", final)
        return final

    def _run_task(self, task: str) -> str:
        """An ordinary request (or a long structured brief with no phases of its own)."""
        raw = task
        if self._brief is not None and brief.BriefState.load(self.ws.root):
            self.brief_ctx = self._brief_context(raw)       # a follow-up inside a saved brief
        big = len(raw) > LONG_TASK_CHARS and brief.looks_like_brief(brief.Brief(raw))
        task = raw if big else self._sanitize_task(raw)
        topic = extract_task_topic(task)
        initial_plan = extract_plan(task)
        if not initial_plan:
            initial_plan = [
                f"Analyze project requirements & files for {topic}",
                "Formulate architectural plan & component changes",
                "Execute code edits & file implementations",
                "Verify syntax & run validation checks",
            ]
        self.on_event("task_init", {"topic": topic, "task": task, "plan": [] if big else initial_plan})
        if big:
            return self._run_phased(task, topic)
        return self._loop(task, topic, self.max_steps, initial_plan=initial_plan, intent=raw)

    def _fallback_summary(self) -> str:
        if self.changed:
            return "Finished. Files changed: " + ", ".join(sorted(set(self.changed))[:12]) + "."
        return ("The model finished without making changes or giving an answer. Rephrase the goal as one concrete "
                "step (for example: \"create resources/views/welcome.blade.php with a landing page\") and run again.")

    # ------------------------------------------------ the brief: facts, not guesses
    def _load_grounding(self) -> None:
        """The brief saved in this project (if any) says which packages are real."""
        self.brief_ctx = ""
        self._brief = brief.load_spec(self.ws.root)
        self.grounding = brief.Grounding(self._brief) if self._brief else None
        if self.grounding is not None and not self.grounding.active:
            self.grounding = None

    def _brief_context(self, task: str) -> str:
        b = self._brief
        if b is None:
            return ""
        parts = [b.card(1800)]
        picked = brief.select_sections(b, task, budget=4500)
        if picked:
            parts.append("Relevant parts of the saved brief (.devos/spec.md):\n" + picked)
        return "\n\n".join(parts)

    def _own_names(self, path: str, content: str) -> Tuple[str, ...]:
        """Names under the user's vendor that are the project itself (its folder, its composer name), not dependencies."""
        names = {re.sub(r"[^a-z0-9]+", "-", (os.path.basename(self.ws.root) or "").lower()).strip("-")}
        if os.path.basename(path) == "composer.json":
            names.add(brief.composer_json_own_name(content))
        return tuple(n for n in names if n)

    def _grounding_problems(self, path: str, content: str) -> Tuple[List[str], List[str]]:
        """(blocking problems, soft warnings) for a file about to be written."""
        g = self.grounding
        if g is None:
            return [], []
        ignore = self._own_names(path, content)
        problems = [f"{n} is not in the brief" + (f" (did you mean {g.suggest(n)}?)" if "/" in n and g.suggest(n) else "")
                    for n in g.invented_in_text(content, ignore)]
        warnings: List[str] = []
        if os.path.basename(path) == "composer.json":
            deps = brief.composer_json_packages(content)
            for item in g.composer_problems(deps, ignore):
                if item not in problems:
                    problems.append(item)
            warnings = g.composer_warnings(deps)
        return problems, warnings

    def _grounding_error(self, subject: str, problems: List[str]) -> str:
        own = ", ".join(self.grounding.allowed_owned()) if self.grounding else ""
        return (f"{subject} names packages that are not in the user's brief: " + "; ".join(problems[:8]) + ". "
                + (f"The brief's own packages are exactly: {own}. " if own else "")
                + "Use only those (plus Laravel's own packages and others the brief mentions) and try again.")

    # ---------------------------------------------------------- brief messages
    def _brief_flow(self, task: str) -> Optional[str]:
        """Messages about a long brief: the brief itself, and the user's 'go' / 'go all' / 'go 3' /
        answers / 'status' / 'reset' that follow it. None means an ordinary request."""
        root = self.ws.root
        text = task.strip()
        state = brief.BriefState.load(root)
        if state:
            cmd = brief.parse_command(text, state)
            if cmd:
                kind, arg = cmd
                if kind == "reset":
                    state.clear()
                    self._load_grounding()
                    return "Brief cleared. I will treat your next message as a fresh request."
                if kind == "status":
                    return self._brief_status(state)
                if kind == "answers":
                    state.answers.append(text)
                    state.save()
                    nxt = state.phase(state.next)
                    return (f"Noted ({len(state.answers)} repl{'ies' if len(state.answers) != 1 else 'y'} saved with the brief). "
                            + (f"Reply `go` to build Phase {nxt['n']} — {nxt['title']}." if nxt and not state.finished
                               else "All phases are built."))
                if self._brief is None:
                    return ("The saved brief (.devos/spec.md) is missing, so I cannot continue safely. Paste the brief "
                            "again (your progress is kept), or say `reset the brief` to start over.")
                if kind == "go_all":
                    return self._build_phases(state, state.remaining())
                if kind == "go":
                    if arg is None or state.phase(arg) is None:
                        nums = state.numbers()
                        return (f"All {state.total} phases are built." if state.finished and arg is None
                                else f"There is no phase {arg}. The phases are numbered {nums[0]} to {nums[-1]}.")
                    return self._build_phases(state, [arg])
        elif brief.bare_command(text):
            return ("There is no saved brief in this folder yet, so there is nothing to continue. Paste your brief first; "
                    "after my first reply you can say `go`.")
        if len(text) > LONG_TASK_CHARS:
            b = brief.Brief(text)
            if b.phases or (b.protocol and brief.looks_like_brief(b)):
                return self._start_brief(b, text, state)
        return None

    def _start_brief(self, b: "brief.Brief", text: str, state: Optional["brief.BriefState"]) -> str:
        root = self.ws.root
        fresh = brief.BriefState.create(root, b)
        if state and state.spec_hash == fresh.spec_hash:
            if self._brief is None:                      # the same brief again, and its saved copy went missing
                brief.save_spec(root, text)
                self._load_grounding()
            if state.asked:
                return "This brief is already loaded.\n\n" + self._brief_status(state)
            fresh = state
        brief.save_spec(root, text)
        self._load_grounding()
        if not fresh.phases:                             # no phases of its own: propose some, do not build unasked
            fresh.phases = self._plan_phases(text, b.title)
        fresh.save()
        if fresh.protocol:
            return self._understand(b, fresh)
        return self._build_phases(fresh, fresh.remaining())

    def _brief_status(self, state: "brief.BriefState") -> str:
        lines = [f"**{state.title}** — {len(state.done)} of {state.total} phases built."]
        for p in state.phases:
            info = state.done.get(str(p["n"]))
            if info:
                files = info.get("files") or []
                lines.append(f"✓ Phase {p['n']} — {p['title']}: {len(files)} file(s)")
            else:
                lines.append(f"○ Phase {p['n']} — {p['title']}")
        nxt = state.phase(state.next)
        if nxt and not state.finished:
            lines.append(f"\nReply `go` to build Phase {nxt['n']} — {nxt['title']}, `go all` for everything left, "
                         "or `go N` for a specific phase.")
        return "\n".join(lines)

    # ---------------------------------------------- first reply to a protocol brief
    def _understand(self, b: "brief.Brief", state: "brief.BriefState") -> str:
        """The first reply the brief asks for: what I understood, assumptions, folder structure, the
        Phase 1 task list and questions, then wait for 'go'. All of it is taken from the brief itself,
        so nothing in it can be invented; the model is used only when the brief has too little
        structure to summarise, and then its text is cleaned of invented package names."""
        roles = b.package_roles()
        phases = state.phases
        self.on_event("task_init", {"topic": b.title, "task": b.title,
                                    "plan": [f"Phase {p['n']} — {p['title']}" for p in phases]})
        self.on_event("thinking_status", {"step": 1, "topic": b.title, "status": "Reading the brief section by section..."})
        self.on_event("thinking", 1)
        out: List[str] = []

        def say(text: str) -> None:
            out.append(text)
            self.on_event("token", text)

        say(f"**I read your whole brief: {b.title}**\n"
            f"{sum(1 for s in b.sections if s.heading)} sections · {len(roles)} of your own packages · {len(phases)} delivery phases\n\n")
        if roles:
            say("**Your packages** (the only `" + "`, `".join(sorted(b.owned)) + "` ones I will use, each behind an adapter):\n")
            for name, role in roles:
                say(f"- `{name}` — {role}\n")
            say("\n")
        say("**Your phases:** " + " → ".join(f"{p['n']}. {p['title']}" for p in phases) + "\n\n")
        stale = self._stale_composer()
        if stale:
            say("**Heads-up:** `composer.json` in this folder already lists packages that are not in your brief ("
                + ", ".join(stale[:8]) + "). Phase 1 will replace them.\n\n")
        lines = b.understanding()
        if len(lines) >= 4:
            say("**What I understood**\n")
            for line in lines:
                say(f"- {line}\n")
            say("\n")
            assumptions = b.assumptions()
            if assumptions:
                say("**Assumptions** (tell me if any is wrong)\n")
                for item in assumptions:
                    say(f"- {item}\n")
                say("\n")
            tree = b.folder_tree(re.sub(r"[^A-Za-z0-9_-]+", "-", os.path.basename(self.ws.root)) or "project")
            if tree:
                say("**Folder structure** (the folders and files your brief names)\n```\n" + "\n".join(tree) + "\n```\n")
        elif not self.cancelled:                         # an unstructured brief: let the model summarise it, carefully
            self.on_event("thinking_status", {"step": 1, "topic": b.title, "status": "Summarising the brief..."})
            grounder = brief.StreamGrounder(self.grounding, say)
            saved = self.llm.max_tokens
            self.llm.max_tokens = 900
            try:
                self.llm.chat(self._understand_messages(b), on_token=grounder.feed, should_stop=lambda: self.cancelled)
            except AgentError as exc:
                say(f"_(The local model could not be reached, so I only list what I found in your brief: {exc})_\n\n")
            finally:
                self.llm.max_tokens = saved
                grounder.finish()

        first = phases[0]
        say(f"\n**Phase {first['n']} — {first['title']}: task list**\n")
        for i, item in enumerate(first.get("tasks") or brief.split_tasks(first.get("text", "")), 1):
            say(f"{i}. {item}\n")
        questions: List[str] = []
        for q in b.required_questions() + b.choice_questions():
            words = {w for w in re.findall(r"[a-z]{4,}", q.lower())}
            if not any(len(words & {w for w in re.findall(r"[a-z]{4,}", e.lower())}) >= max(2, len(words) // 2) for e in questions):
                questions.append(q)
        questions = questions[:10]
        if questions:
            say("\n**Questions for you** (answer by number, or just say `go` to accept my assumptions)\n")
            for i, q in enumerate(questions, 1):
                say(f"{i}. {q}\n")
        say(f"\n**Next:** reply `go` to build Phase {first['n']} — {first['title']}. I stop after every phase and show what "
            "passed, as your brief says. Reply `go all` to build every phase without stopping, or `go 3` to jump to a phase.")
        state.asked = True
        state.save()
        final = "".join(out)
        self.on_event("reply", final)
        return final

    def _understand_messages(self, b: "brief.Brief") -> List[Dict[str, str]]:
        system = ("You are a principal architect reading a project brief written by the user. Use ONLY facts in the "
                  "text below. Never mention a package that the brief does not list. Do not invent features, names, "
                  "numbers or file names. Write plain Markdown.")
        user = (f"{b.card(2600)}\n\nBRIEF (start):\n{b.text[:5000]}\n\n"
                "Write: '## What I understood' (up to 12 short lines), then '## Assumptions' (up to 5 bullets, only "
                "where the brief leaves a choice or a detail open).")
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _stale_composer(self) -> List[str]:
        """Packages in an existing composer.json that the brief does not support (leftovers of an earlier run)."""
        if self.grounding is None:
            return []
        try:
            content = self.ws.read_text("composer.json")
        except ToolError:
            return []
        if not content:
            return []
        own = self._own_names("composer.json", content)
        return [item.split(" is not")[0] for item in self.grounding.composer_problems(brief.composer_json_packages(content), own)]

    # ------------------------------------------------------ building the phases
    def _budget_chars(self) -> int:
        """How much conversation fits the model's window (characters), from what the server reports."""
        ctx = 8192
        getter = getattr(self.llm, "context_tokens", None)
        if callable(getter):
            try:
                ctx = int(getter())
            except (TypeError, ValueError):
                pass
        else:
            ctx = 32768
        return max(9000, min(60000, int((ctx - getattr(self.llm, "max_tokens", 4096) - 1500) * 3.2)))

    def _bootstrap(self, b: "brief.Brief") -> str:
        """Boilerplate costs the model minutes per file on this PC but nothing when a generator makes it. If the
        brief names a Laravel version and this folder is not a Laravel project yet, create the skeleton with
        Composer first. Returns a note for the phase prompt ('' when nothing was needed)."""
        root = self.ws.root
        m = re.search(r"\blaravel\s*(\d{1,2})\b", b.text, re.I)
        if not self.bootstrap or not m or os.path.isfile(os.path.join(root, "artisan")) or not (shutil.which("composer") and shutil.which("php")):
            return ""
        version = f"^{m.group(1)}.0"
        steps = [
            (f"Create the Laravel {m.group(1)} skeleton",
             f"composer create-project \"laravel/laravel:{version}\" .devos-skeleton --prefer-dist --no-interaction"),
            ("Move it into the project folder", "cp -a .devos-skeleton/. . && rm -rf .devos-skeleton"),
        ]
        if re.search(r"\bdev-main\b", b.text):
            steps.append(("Allow the dev-main packages the brief names",
                          "composer config minimum-stability dev && composer config prefer-stable true"))
        for title, command in steps:
            if self.cancelled:
                return ""
            self.on_event("thinking_status", {"step": 1, "topic": "Bootstrap", "status": f"{title}..."})
            result = self.execute(ToolCall("run_command", {"command": command, "timeout": MAX_TIMEOUT}))
            self.on_event("result", {"tool": "run_command", "text": result})
            if not str(result).startswith("exit code 0"):
                shutil.rmtree(os.path.join(root, ".devos-skeleton"), ignore_errors=True)
                return (f"NOTE: creating the Laravel skeleton with Composer failed ({' '.join(str(result).split())[:200]}). "
                        "Create the files the phase needs by hand, as short as possible.")
        return ("ALREADY DONE by the agent (do not redo it): the Laravel skeleton was created with `composer create-project` "
                "in this folder (artisan, app/, config/, routes/, resources/, .env ...)"
                + ("; composer is set to minimum-stability dev with prefer-stable" if len(steps) > 2 else "") + ".")

    def _install_phase_packages(self, b: "brief.Brief", phase: Dict[str, Any]) -> str:
        """The packages a phase says to install ('Install **drutogoti** and **universal-slug**') are installed by the
        agent with `composer require`, as the brief says. A small model skips this step and then claims it did it.
        Returns a note for the phase prompt ('' when there was nothing to do)."""
        root = self.ws.root
        if not self.bootstrap or not os.path.isfile(os.path.join(root, "composer.json")) or not shutil.which("composer"):
            return ""
        text = " ".join([phase.get("title", ""), phase.get("text", "")] + list(phase.get("tasks") or [])).lower()
        try:
            with open(os.path.join(root, "composer.json"), encoding="utf-8") as handle:
                manifest = json.load(handle)
                have = {k.lower() for section in ("require", "require-dev")
                        for k in (manifest.get(section) or {})}
        except (OSError, ValueError):
            have = set()
        wanted = []
        for pkg in b.packages:
            tail = pkg.split("/")[1]
            aliases = {tail, tail[len("laravel-"):] if tail.startswith("laravel-") else tail}
            if pkg.lower() not in have and any(re.search(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])", text) for a in aliases):
                wanted.append(pkg)
        if not wanted or self.cancelled:
            return ""
        dev = bool(re.search(r"\bdev-main\b", b.text))
        args = " ".join(f"{p}:dev-main" if dev and p.split("/")[0] in b.owned else p for p in wanted)
        self.on_event("thinking_status", {"step": 1, "topic": "Packages", "status": f"Installing {', '.join(wanted)}..."})
        result = str(self.execute(ToolCall("run_command", {"command": f"composer require {args} --no-interaction --no-progress",
                                                           "timeout": MAX_TIMEOUT})))
        self.on_event("result", {"tool": "run_command", "text": result})
        if result.startswith("exit code 0"):
            return f"ALREADY DONE by the agent (do not redo it): composer require {', '.join(wanted)} succeeded."
        return (f"NOTE: `composer require {args}` FAILED: {' '.join(result.split())[:350]} Do not claim these packages are "
                "installed; report the failure in your summary.")

    def _verified_facts(self, cmd_start: int, made: List[str], summary: str) -> str:
        """What the agent itself saw during the phase: commands and their exit codes, and whether the packages the
        model's summary says it installed are really in composer.json. The model's words are never taken as proof."""
        log = self._commands_log[cmd_start:]
        lines = []
        if log:
            ok = sum(1 for _, code in log if code == 0)
            shown = "; ".join(f"`{c[:60]}` → {'ok' if code == 0 else f'exit {code}'}" for c, code in log[:6])
            lines.append(f"Commands run: {len(log)} ({ok} succeeded). {shown}")
        else:
            lines.append("Commands run: none — no migrations, tests or installs were run in this phase.")
        try:
            with open(os.path.join(self.ws.root, "composer.json"), encoding="utf-8") as handle:
                have = {k.lower() for k in (json.load(handle).get("require") or {})}
        except (OSError, ValueError):
            have = None
        if have is not None and self.grounding is not None:
            # A retry can replace a fabricated success claim with a generic "Done".
            # Check all assistant replies from this phase, not only the last one.
            replies = "\n".join(m.get("content", "") for m in self.messages[self._task_idx + 1:]
                                if m.get("role") == "assistant") if hasattr(self, "_task_idx") else ""
            claimed = self.grounding.owned_mentions(summary + "\n" + replies)
            missing = sorted(p for p in claimed if p not in have)
            if missing:
                lines.append("⚠ The model mentioned these packages, but composer.json does not list "
                             "them: " + ", ".join(missing) + ".")
        return "\n".join(lines)

    def _phase_task(self, b: "brief.Brief", state: "brief.BriefState", phase: Dict[str, Any], budget: int) -> str:
        parts = [b.card(2600)]
        query = f"{phase['title']}: {phase.get('text', '')}"
        # Every 1000 prompt tokens cost the local model ~8 seconds before it writes anything (and again each time a new
        # prompt is read), so a local engine gets the sections a phase needs but not the whole brief.
        local = bool(getattr(self.llm, "is_local", True))
        picked = brief.select_sections(b, query, budget=max(4000, min(6500 if local else 11000, int(budget * 0.33))))
        if picked:
            parts.append("RELEVANT PARTS OF THE BRIEF (verbatim; follow them exactly; the rest is in .devos/spec.md):\n" + picked)
        if state.answers:
            parts.append("THE OWNER'S ANSWERS AND DECISIONS:\n" + "\n".join(state.answers)[-2500:])
        built = [f"Phase {k}: " + ", ".join((v.get("files") or [])[:10]) for k, v in sorted(state.done.items(), key=lambda kv: int(kv[0]))]
        if built:
            parts.append("ALREADY BUILT:\n" + "\n".join(built))
        if getattr(self, "_bootstrap_note", ""):
            parts.append(self._bootstrap_note)
        tasks = phase.get("tasks") or []
        scope = ("\n".join(f"- {t}" for t in tasks) if len(tasks) > 1 else phase.get("text", ""))
        parts.append(
            f"CURRENT PHASE {phase['n']} of {state.total} — {phase['title']}\n"
            f"Scope, exactly as the brief states it:\n{scope}\n\n"
            "Build only this phase. Concrete requirements for this phase:\n"
            "- Create the specific database migrations (`database/migrations/...`) and Eloquent models (`app/Models/...`) for this phase.\n"
            "- DO NOT repeatedly re-write routes/web.php or HomeController.php. routes/web.php already exists; only add routes when a new controller is created.\n"
            "- Use generators and commands wherever they exist (`composer require vendor/package` — never hand-write composer.json; "
            "`php artisan make:*`; `php artisan vendor:publish`; `php artisan migrate`); a file written by hand costs minutes "
            "on this PC, so write only what no generator makes and keep each file short (under about 120 lines, no "
            "boilerplate comments, no repeated entries). Write ONE file per reply. Use only the packages the brief lists; read "
            "each package's README and config in vendor/ before using it. Add nothing the brief does not ask for. When the phase's code is written, run the migrations and the tests if the project has them and report "
            "what passed and what failed. Then reply with a short summary; do not ask to continue.")
        return "\n\n".join(parts)

    def _build_phases(self, state: "brief.BriefState", numbers: List[int]) -> str:
        b = self._brief
        if b is None or not numbers:
            return f"All {state.total} phases are built." if state.finished else "Nothing to build."
        if self.grounding is None and b.owned:
            self.grounding = brief.Grounding(b)
        budget = self._budget_chars()
        self.on_event("task_init", {"topic": state.title, "task": state.title,
                                    "plan": [f"Phase {p['n']} — {p['title']}" for p in state.phases]})
        self._commands_log = []
        bootstrap_note = self._bootstrap(b)
        heads: List[str] = []       # one line per phase for the on-screen report
        full: List[str] = []        # the same plus the model's own summary, for the return value
        for n in numbers:
            phase = state.phase(n)
            if self.cancelled or phase is None:
                break
            self.on_event("phase", {"index": n, "total": state.total, "title": f"{phase['title']}"})
            self._base_changed = len(self.changed)
            self._commands_run = 0
            cmd_start = 0 if not heads and not full else len(self._commands_log)
            self.history_budget = budget
            self.brief_ctx = ""
            self._bootstrap_note = " ".join(x for x in (bootstrap_note, self._install_phase_packages(b, phase)) if x)
            bootstrap_note = ""
            result = self._loop(self._phase_task(b, state, phase, budget), state.title, BRIEF_PHASE_STEPS,
                                phase=(n, state.total), use_history=False, intent="build the phase")
            made = sorted(set(self.changed[self._base_changed:]))
            if self._outcome == "cancelled" or self.cancelled:
                self.on_event("phase_done", {"index": n, "ok": False})
                heads.append(f"**Phase {n} of {state.total} — {phase['title']}:** stopped. Nothing was recorded; "
                             "`go` builds it again from where the files are now.")
                full.append(heads[-1])
                break
            ok = self._outcome == "done" and (bool(made) or len(self._commands_log) > cmd_start)
            line = f"**Phase {n} of {state.total} — {phase['title']}:** " + (
                f"{len(made)} file(s) created or changed ({', '.join(made[:10])}{'…' if len(made) > 10 else ''})."
                if made else "no files were changed.")
            summary = self._ground(result.strip())
            facts = self._verified_facts(cmd_start, made, summary)
            line += "\n" + facts
            if ok:
                state.mark_done(n, made, " ".join(summary.split())[:300])
                state.save()
                if self.keep_notes:
                    try:
                        self.ws.add_note(f"- Phase {n}/{state.total} {phase['title']}: {len(made)} file(s)")
                    except OSError:
                        pass
            else:
                reason = {"limit": "it hit the step limit", "empty": "the model returned nothing"}.get(
                    self._outcome, "it finished without changing any file or running any command")
                line += f" Not marked as built: {reason}. Say `go` to continue this phase."
            self.on_event("phase_done", {"index": n, "ok": ok})
            heads.append(line)
            full.append(line + (f"\nThe model's own summary (not verified by the agent):\n{summary}" if summary else ""))
            if not ok:
                break                                   # do not build on top of a phase that did not finish
        nxt = state.phase(state.next)
        tail = (f"\n\nReply `go` to build Phase {nxt['n']} — {nxt['title']}, `go all` for everything left, or `go N` for a "
                "specific phase." if nxt and not state.finished else f"\n\nAll {state.total} phases are built.")
        self.on_event("report", "\n\n".join(heads) + tail)
        return "\n\n".join(full) + tail

    # --------------------------------------------------- big tasks, in phases
    def _plan_phases(self, spec: str, topic: str) -> List[Dict[str, Any]]:
        """A big spec with no phases of its own: ask the model to split it, from the brief's outline
        (every section heading) so nothing in the middle is invisible to it."""
        b = brief.Brief(spec)
        self.on_event("thinking_status", {"step": 1, "topic": topic,
                                          "status": "Reading the full brief and splitting it into build phases..."})
        self.on_event("thinking", 1)
        outline = "\n".join(f"{s.number or '-'} {s.title}" for s in b.sections if s.heading)[:3500]
        system = ("You are a software architect. Split the project brief into 3 to 8 sequential build phases that a coder "
                  "finishes one at a time. Phase 1 must produce something that runs. Use only things the brief names. Reply "
                  "with ONLY a numbered list, one line per phase: a short title, a colon, then what it builds. No questions, "
                  "no commentary. Example format:\n1. Setup: project configuration and folder structure\n"
                  "2. Data: models and migrations\n3. Screens: the pages users see")
        user = f"{b.card(2200)}\n\nOUTLINE OF THE BRIEF:\n{outline}\n\nSTART OF THE BRIEF:\n{spec[:1800]}"
        saved = self.llm.max_tokens
        self.llm.max_tokens = 600
        grounder = brief.StreamGrounder(self.grounding, lambda t: self.on_event("token", t))
        try:
            reply = self.llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                  on_token=grounder.feed, should_stop=lambda: self.cancelled)
        finally:
            self.llm.max_tokens = saved
            grounder.finish()
        self.on_event("reply", reply)
        phases = []
        for line in reply.splitlines():
            m = re.match(r"^\s*(?:\d+[.)]|[-*•])\s+(.+)$", line)
            if m:
                title, _, rest = m.group(1).strip().strip("*").partition(":")
                phases.append({"n": len(phases) + 1, "title": title.strip(" *"), "text": rest.strip() or title.strip(),
                               "tasks": brief.split_tasks(rest) if rest.strip() else []})
        phases = phases[:MAX_PHASES + 2]
        if len(phases) < 2:
            phases = [{"n": 1, "title": "Project skeleton", "text": f"Create the project skeleton and configuration for {topic}", "tasks": []},
                      {"n": 2, "title": "Core logic", "text": "Build the core data models, services and routes", "tasks": []},
                      {"n": 3, "title": "Interface", "text": "Build the user interface pages and components", "tasks": []},
                      {"n": 4, "title": "Verify", "text": "Connect everything, add sample data, and verify it runs", "tasks": []}]
        return phases

    def _run_phased(self, task: str, topic: str) -> str:
        """A structured spec with no phases of its own and no wait-for-go rule: build it in phases the model proposes."""
        b = brief.Brief(task)
        saved_state = brief.BriefState.load(self.ws.root)
        try:
            # never overwrite the saved brief (and its package guard) with a different long message
            brief.save_spec(self.ws.root, task, os.path.join(".devos", "task-spec.md" if saved_state else "spec.md"))
        except (OSError, ValueError):
            pass
        if b.owned and saved_state is None:
            self.grounding = brief.Grounding(b)
        phases = self._plan_phases(task, topic)
        state = brief.BriefState(self.ws.root, {"title": topic, "protocol": False, "phases": phases})
        self.on_event("plan", [f"{p['title']}" for p in phases])
        self._brief = b if saved_state is None else self._brief
        budget = self._budget_chars()
        summaries: List[str] = []
        for p in phases:
            if self.cancelled:
                break
            self.on_event("phase", {"index": p["n"], "total": len(phases), "title": p["title"]})
            self._base_changed = len(self.changed)
            self.history_budget = budget
            self.brief_ctx = ""
            self._loop(self._phase_task(b, state, p, budget), topic, PHASE_STEPS, phase=(p["n"], len(phases)),
                       use_history=False, intent="build the phase")
            made = sorted(set(self.changed[self._base_changed:]))
            state.done[str(p["n"])] = {"files": made}
            line = f"Phase {p['n']}/{len(phases)} {p['title'][:80]}: " + (
                f"{len(made)} file(s) ({', '.join(made[:6])})" if made else "no file changes")
            summaries.append(line)
            self.on_event("phase_done", {"index": p["n"], "ok": bool(made)})
            if self.keep_notes:
                try:
                    self.ws.add_note("- " + line)
                except OSError:
                    pass
        built = sorted(set(self.changed))
        head = (f"Built in {len(summaries)} phase(s); {len(built)} file(s) created or changed."
                if built else "No files were created.")
        text = head + "\n" + "\n".join("• " + line for line in summaries)
        self.on_event("report", text)
        return text

    # ------------------------------------------------------------- model turn
    _EDIT_OPEN = re.compile(r"```[ \t]*tool[ \t]+(?:write_file|apply_patch|run_command)\b[^\n]*\n")

    @staticmethod
    def _closing_fence_end(body: str) -> Optional[int]:
        """Index just after the fence that closes a tool block whose text starts at `body`. A fence with a
        language ('```php') inside the block opens a nested block that its own bare fence closes."""
        depth = 0
        pos = 0
        for line in body.splitlines(keepends=True):
            stripped = line.strip()
            if stripped.startswith("```"):
                if stripped == "```":
                    if depth == 0:
                        return pos + len(line)
                    depth -= 1
                else:
                    depth += 1
            pos += len(line)
        return None

    def _stream_verdict(self, text: str) -> Optional[Tuple[str, int]]:
        """Why this (partial) reply should be cut now, and where: ('block', end) the first write / patch /
        command block is complete - run it before asking for more; ('second', at) a second file started
        inside one block; ('repeat', at) the model is repeating itself; ('long', at) the file is far too long."""
        m = self._EDIT_OPEN.search(text)
        if m is None:
            return None
        body = text[m.end():]
        second = self._second_file_start(text)
        if second is not None:
            return ("second", second)
        if len(body) > 2500:
            tail = body[-3000:]
            if len(zlib.compress(tail.encode("utf-8", "replace"))) < 0.09 * len(tail.encode("utf-8", "replace")):
                return ("repeat", m.start())
        if body.count("\n") > MAX_FILE_LINES:
            return ("long", m.start())
        end = self._closing_fence_end(body)
        if end is not None and self._one_edit_per_reply():
            return ("block", m.end() + end)
        return None

    def _one_edit_per_reply(self) -> bool:
        """On this PC's model a file takes minutes, so each write is run as soon as it is complete (progress you
        can see, and a mistake costs one file, not ten). Fast cloud engines may write several files per reply."""
        return bool(getattr(self.llm, "is_local", True))

    def _ask(self, step_num: int, stream_plan: Optional[List[str]] = None) -> str:
        """One model reply, streamed. It is cut as soon as its first write / patch / command block is complete
        (or runs away); a reply cut off at the token limit inside a code block is continued."""
        parts: List[str] = []
        started = time.time()
        last_speed = [started]
        shown = brief.StreamGrounder(self.grounding, lambda t: self.on_event("token", t))   # what the user sees
        self._cut = None
        self._multi_cut = False

        def on_stream_token(t: str):
            if self._cut:
                return
            parts.append(t)
            shown.feed(t)
            now = time.time()
            if now - last_speed[0] >= 2.0 and now - started > 2.0:
                last_speed[0] = now
                chars = sum(len(p) for p in parts)
                self.on_event("speed", {"tokens_per_sec": round(chars / 3.6 / (now - started), 1),
                                        "seconds": round(now - started, 1), "live": True})
            if "\n" in t or "`" in t:
                verdict = self._stream_verdict("".join(parts))
                if verdict:
                    self._cut = verdict[0]
            if stream_plan is not None and step_num == 1:
                streamed = extract_plan("".join(parts))
                if len(streamed) >= 2 and streamed != stream_plan:
                    self.on_event("plan", streamed)

        saved_tokens = getattr(self.llm, "max_tokens", None)
        if saved_tokens and self._one_edit_per_reply():
            self.llm.max_tokens = min(saved_tokens, MAX_REPLY_TOKENS)
        try:
            reply = self.llm.chat(self.window(), on_token=on_stream_token,
                                  should_stop=lambda: self.cancelled or bool(self._cut))
            for _ in range(MAX_CONTINUATIONS):
                if (self.cancelled or self._cut or getattr(self.llm, "last_finish", "") != "length"
                        or not has_unclosed_fence(reply)):
                    break
                self.on_event("thinking_status", {"step": step_num, "status": "Long file: continuing where the reply "
                                                                              "was cut off..."})
                more = self.llm.chat(self.window() + [
                    {"role": "assistant", "content": reply},
                    {"role": "user", "content": "Continue EXACTLY where you stopped. Output only the rest of the file "
                                                "and the closing fence. Do not repeat anything or reopen the block."}],
                    on_token=on_stream_token, should_stop=lambda: self.cancelled or bool(self._cut))
                if not more.strip():
                    break
                reply += more
        finally:
            if saved_tokens:
                self.llm.max_tokens = saved_tokens
        shown.finish()
        # Whatever the model returned (a scripted or non-streaming engine ignores should_stop), cut it the same way.
        verdict = self._stream_verdict(reply)
        if verdict:
            kind, at = verdict
            self._cut = kind
            if kind == "block":
                reply = reply[:at]
            elif kind == "second":
                reply = reply[:at].rstrip("\n") + "\n```"
                self._multi_notice = True
            else:                                        # runaway or far too long: the file is useless, drop it
                reply = reply[:at].rstrip() + "\n(The file was cut off.)"
                self._runaway_notice = kind
        elapsed = max(time.time() - started, 0.05)
        if len(reply) > 40:
            self.on_event("speed", {"tokens_per_sec": round(len(reply) / 3.6 / elapsed, 1), "seconds": round(elapsed, 1)})
        return reply

    @staticmethod
    def _second_file_start(text: str) -> Optional[int]:
        """Where a second file begins inside the FIRST write_file block of a reply (else None)."""
        if not text.lstrip().startswith("```"):
            return None
        head = text.find("\n---\n")
        if head < 0:
            return None
        body_start = head + 5
        end = text.find("\n```", body_start)
        m = _NEXT_FILE_RE.search(text[body_start:end if end >= 0 else len(text)])
        return body_start + m.start() if m else None

    @staticmethod
    def _compact(reply: str, calls: List[ToolCall]) -> str:
        """What stays in the history for a reply: its words, and each tool call with
        file bodies reduced to a line count. Keeps the prompt small, so every next step is faster."""
        if len(reply) <= 1200 or not calls:
            return reply[:4000]
        lead = re.split(r"```|<tool_call>", reply, maxsplit=1)[0].strip()[:400]
        blocks = []
        for call in calls:
            if call.name == "write_file":
                lines = str(call.args.get("content") or "").count("\n") + 1
                blocks.append(f"```tool write_file\npath: {call.args.get('path', '')}\n---\n({lines} lines written)\n```")
            elif call.name == "apply_patch":
                blocks.append(f"```tool apply_patch\npath: {call.args.get('path', '')}\n---\n(patch applied)\n```")
            else:
                target = call.args.get("path") or call.args.get("command") or call.args.get("pattern") or ""
                key = {"run_command": "command", "search": "pattern"}.get(call.name, "path")
                blocks.append(f"```tool {call.name}\n{key}: {target}\n```")
        return (lead + "\n" if lead else "") + "\n".join(blocks)

    def _force_action(self, task: str, topic: str, step_num: int) -> List[ToolCall]:
        """The model keeps talking instead of acting: ask once, with a minimal prompt, for
        the single most important file."""
        self.on_event("thinking_status", {"step": step_num, "topic": topic,
                                          "status": "No action yet; requesting the first concrete file..."})
        self.on_event("thinking", step_num)
        ask = (self.first_message(task) + "\n\nYou MUST reply now with exactly ONE tool block that creates or edits "
               "the most important file for this task, with its complete content. No explanation before or after.\n"
               "```tool write_file\npath: <file>\n---\n<complete file content>\n```")
        shown = brief.StreamGrounder(self.grounding, lambda t: self.on_event("token", t))
        reply = self.llm.chat([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": ask}],
                              on_token=shown.feed, should_stop=lambda: self.cancelled)
        shown.finish()
        self.on_event("reply", reply)
        self.messages.append({"role": "assistant", "content": reply[:3000]})
        return parse_tool_calls(reply) or [c for c in parse_loose_files(reply)
                                           if self.ws.read_text_safe(str(c.args.get("path"))) is None]

    # ------------------------------------------------- several files at the same time
    _PLAN_LINE = re.compile(r"^\s*(?:\d+[.)]|[-*•])?\s*[`*]*([\w@./\\\-\[\]]+\.[A-Za-z0-9]{1,8})[`*]*(?:\s*(?:::|—|–|-|:)\s*(.+?))?\s*$")
    _NOT_PLANNED = {"composer.json", "composer.lock", "package.json", "package-lock.json", "yarn.lock", ".env", ".gitignore",
                    "artisan", "vite.config.js", "phpunit.xml"}

    @staticmethod
    def _scope_of(task: str) -> str:
        """The scope lines of a phase task ('Scope, exactly as the brief states it: ...'), else the task itself."""
        m = re.search(r"Scope, exactly as the brief states it:\n(.+?)\n\nBuild only this phase", task, re.S)
        return m.group(1).strip() if m else task[-1500:]

    @staticmethod
    def _stems(text: str) -> set:
        """Word stems of a text (camelCase, snake_case and paths split): 'tenancy' and 'tenant' meet."""
        words = re.findall(r"[a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower())
        return {w[:5] if len(w) >= 6 else w for w in words if len(w) >= 2 and w not in
                {"the", "and", "for", "with", "that", "this", "file", "files", "from", "into", "php", "app", "new", "use",
                 "create", "custom", "page", "model", "controller"}}

    def _plan_files(self, task: str, topic: str) -> List[Tuple[str, str]]:
        """Ask the model which NEW files this phase needs and can be written independently of each other. The
        request ends with the phase's scope, a repeat penalty keeps the small model from looping, the stream is
        cut as soon as it starts repeating, and a file that has nothing to do with the scope is dropped."""
        self.on_event("thinking_status", {"step": 1, "topic": topic, "status": "Planning the files for this phase..."})
        self.on_event("thinking", 1)
        scope = self._scope_of(task)
        system = ("You plan files for a coding agent. Reply with ONLY a list, one NEW file per line, written exactly as\n"
                  "path/to/file.ext :: what it contains (one short sentence)\n"
                  f"List at most {MAX_PARALLEL_FILES} files, each one needed by an item of THIS PHASE'S SCOPE and writable "
                  "independently of the others (models, controllers, routes, views, migrations, config, docker, CI, tests, "
                  "docs). Never list files that already exist, files a generator creates (framework skeleton, composer.json, "
                  "composer.lock, package.json), or anything outside the scope. Each line must be a different file with a "
                  "different purpose. Use exact paths and class names so the files fit together. No commentary.")
        lines_seen: List[str] = []
        state = {"buf": "", "stop": False}
        shown = brief.StreamGrounder(self.grounding, lambda t: self.on_event("token", t))

        def watch(token: str) -> None:
            shown.feed(token)
            state["buf"] += token
            if "\n" in token:
                done = state["buf"].split("\n")
                state["buf"] = done[-1]
                for line in done[:-1]:
                    if line.strip():
                        lines_seen.append(line.strip())
                heads = [" ".join(re.sub(r"^.*?::", "", ln).split()[:4]).lower() for ln in lines_seen]
                if len(lines_seen) >= MAX_PARALLEL_FILES + 2 or (len(heads) >= 3 and len(set(heads[-3:])) == 1):
                    state["stop"] = True                        # a full list, or the same line again and again

        summary = self._brief.card(1500) if self._brief is not None else task[:1500]
        try:
            top = ", ".join(sorted(e for e in os.listdir(self.ws.root) if not e.startswith(".")
                                   and e not in IGNORED_DIRS)[:40]) or "(empty)"
        except OSError:
            top = "(unknown)"
        user = (f"PROJECT SUMMARY:\n{summary}\n\nEntries that already exist in the project folder: {top}\n\n"
                f"THIS PHASE'S SCOPE (only this; nothing else):\n{scope}\n\n"
                "Format example (a different project): app/Models/Invoice.php :: invoice model with number, total and status\n\n"
                "List the new files now.")
        saved = self.llm.max_tokens
        self.llm.max_tokens = 320
        try:
            reply = self.llm.chat([{"role": "system", "content": system},
                                   {"role": "user", "content": user}],
                                  on_token=watch, should_stop=lambda: self.cancelled or state["stop"],
                                  options={"repeat_penalty": 1.15})
        finally:
            self.llm.max_tokens = saved
            shown.finish()
        self.on_event("reply", reply)
        scope_stems = self._stems(scope)
        plan: List[Tuple[str, str]] = []
        seen_purposes: set = set()
        for line in reply.splitlines():
            m = self._PLAN_LINE.match(line)
            if not m:
                continue
            path = re.sub(r"^(?:\./)+", "", m.group(1).replace("\\", "/"))
            root_name = os.path.basename(self.ws.root)
            if root_name and path.startswith(root_name + "/"):
                path = path[len(root_name) + 1:]               # the model repeated the project folder
            purpose = (m.group(2) or "").strip() or f"the {os.path.basename(path)} file of this phase"
            if not path or path.startswith(("/", "~")) or ".." in path.split("/") or ".git" in path.split("/") \
                    or os.path.basename(path) in self._NOT_PLANNED or any(p == path for p, _ in plan):
                continue
            key = " ".join(re.sub(r"[A-Z][a-z]+", "", purpose).lower().split()[:5])
            if key in seen_purposes:
                continue                                        # the same sentence for another name: a loop
            if not (self._stems(path + " " + purpose) & scope_stems):
                continue                                        # nothing to do with this phase's scope
            try:
                if self.ws.read_text_safe(path) is not None:
                    continue                                    # exists already: edits stay in the step-by-step loop
            except ToolError:
                continue
            seen_purposes.add(key)
            plan.append((path, purpose))
            if len(plan) >= MAX_PARALLEL_FILES:
                break
        return plan

    def _file_call(self, path: str, text: str) -> Optional[ToolCall]:
        """The write_file call in one branch's answer, aimed at the planned path."""
        for call in parse_tool_calls(text):
            if call.name == "write_file" and call.args.get("content") is not None:
                return ToolCall("write_file", {"path": path, "content": call.args["content"]}, call.raw)
        stripped = text.strip()
        if stripped.startswith("```"):                  # a fenced file without the tool header
            body = stripped.split("\n", 1)[1] if "\n" in stripped else ""
            end = body.rfind("\n```")
            return ToolCall("write_file", {"path": path, "content": body[:end] if end >= 0 else body}, text)
        return None

    def _parallel_files(self, task: str, topic: str, label: str = "") -> bool:
        """Plan the new files of this task, then write them all at once from the shared context. Returns True when
        files were written (the normal loop then installs, tests and fixes). False means: nothing to fan out."""
        if not (self.parallel_files and getattr(self.llm, "supports_batch", None) and self.llm.supports_batch()):
            return False
        plan = self._plan_files(task, topic)
        if len(plan) < MIN_PARALLEL_FILES or self.cancelled:       # a few small files: reading the prompt once costs more than it saves
            return False
        listing = "\n".join(f"- {p} :: {d}" for p, d in plan)
        shared = [{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": self.first_message(task, directive=False)
                   + "\n\nFILES BEING WRITTEN AT THE SAME TIME (their paths, class names and purposes are fixed; use exactly "
                     "these names so the files fit together):\n" + listing}]
        branches = [{"id": p, "prompt": (
            f"Write the COMPLETE file `{p}` now ({d}). Reply with exactly one block and nothing else:\n"
            f"```tool write_file\npath: {p}\n---\n<complete file content>\n```\n"
            "Working code, no placeholders, no boilerplate comments, under about 150 lines.")} for p, d in plan]
        started = time.time()
        written: List[str] = []
        outcomes: List[str] = []
        defer = self.policy.needs_approval("write_file")
        done_texts: Dict[str, Tuple[str, str]] = {}
        chars = [0]
        last = [started]
        first_delta: Dict[str, float] = {}
        self.on_event("thinking_status", {"step": 1, "topic": topic,
                                          "status": f"{label}Writing {len(plan)} files at the same time..."})
        self.on_event("thinking", 1)

        def apply(path: str, text: str, reason: str) -> None:
            call = self._file_call(path, text) if reason in ("fence", "stop") else None
            if call is None:
                why = {"repeat": "it started repeating itself", "long": "it was far too long", "length": "it was cut off"}.get(
                    reason, "no complete file came back")
                outcomes.append(f"[write_file {path}]\nNot written: {why}. Write it again in the next step, shorter.")
                return
            self.on_event("token", f"```tool write_file\npath: {path}\n---\n{str(call.args['content'])}\n```\n")
            result = self.execute(call)
            self.on_event("result", {"tool": "write_file", "text": result})
            outcomes.append(f"[write_file {path}]\n{result}")
            if "Applied:" in str(result):
                written.append(path)

        def on_event(event: Dict[str, Any]) -> None:
            kind = event.get("type")
            if kind == "delta":
                now = time.time()
                first_delta.setdefault("t", now)
                chars[0] += len(event.get("text", ""))
                if now - last[0] >= 2.0 and now - first_delta["t"] >= 2.0:
                    last[0] = now
                    self.on_event("speed", {"tokens_per_sec": round(chars[0] / 3.6 / (now - first_delta["t"]), 1),
                                            "seconds": round(now - started, 1), "live": True})
            elif kind == "end":
                self.on_event("thinking_status", {"step": 1, "topic": topic,
                                                  "status": f"{label}{len(done_texts) + 1} of {len(plan)} files written..."})
                done_texts[event["id"]] = ("", event.get("reason", ""))

        try:
            result = self.llm.chat_batch(shared, branches, on_event=on_event, should_stop=lambda: self.cancelled,
                                         max_tokens=PARALLEL_FILE_TOKENS)
        except AgentError:
            self.on_event("thinking_status", {"step": 1, "topic": topic, "status": "Parallel writing is not available; "
                                                                                   "writing file by file..."})
            return False
        if result.get("error") and not result["branches"]:
            return False
        for path, _ in plan:                      # the files land in plan order, each through the normal write path
            info = result["branches"].get(path)
            if self.cancelled:
                continue
            if info is None:
                outcomes.append(f"[write_file {path}]\nNot written: no result came back. Write this planned file in the next step.")
                continue
            apply(path, info["text"], info["reason"])
        seconds = max(time.time() - started, 0.1)
        self.on_event("speed", {"tokens_per_sec": result.get("tokens_per_sec") or round(chars[0] / 3.6 / seconds, 1),
                                "seconds": round(seconds, 1)})
        self.messages.append({"role": "assistant", "content": "Wrote these files at the same time: " +
                              (", ".join(written) or "none") + "."})
        self.messages.append({"role": "user", "content": (
            "Results:\n" + "\n\n".join(outcomes) + "\n\nThe files above were just written in parallel from the plan. Now do "
            "what is left: install packages with composer require, run the migrations and tests, fix any SYNTAX ERROR or "
            "failure, write a file the plan missed. When the task is complete reply with the final summary and no tool block.")})
        return bool(written)

    # ------------------------------------------------------------------- loop
    def _loop(self, task: str, topic: str, max_steps: int, phase: Optional[Tuple[int, int]] = None,
              initial_plan: Optional[List[str]] = None, use_history: bool = True,
              intent: Optional[str] = None) -> str:
        """`intent` is what the user actually asked, used for the 'is this a question / a build / run it'
        decisions; `task` is the (longer) text the model is given."""
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if self.history and use_history:
            self.messages.extend(self.history[-6:])
        self.messages.append({"role": "user", "content": self.first_message(task)})
        self._task_idx = len(self.messages) - 1
        self._outcome = "done"
        final = ""
        bad_format = empty_replies = consecutive_no_tool = strikes = runaway_retries = 0
        forced = False
        call_history: List[Tuple[str, str, str]] = []
        call_counts: Dict[Tuple[str, str], int] = {}
        last_non_tool_reply = ""

        intent = intent if intent is not None else task
        task_lower = intent.lower().strip()
        is_diagnostic = self._is_diagnostic(intent)
        is_build_task = (not is_diagnostic) and any(kw in task_lower for kw in [
            "make", "build", "create", "implement", "develop", "complete", "add", "fix", "setup", "set up",
            "scaffold", "generate", "code", "write", "landing page", "erp", "project", "application", "app",
            "feature", "module", "system", "phase"])
        effective_max = min(max_steps, 8) if is_diagnostic else max_steps
        label = f"Phase {phase[0]}/{phase[1]} · " if phase else ""
        if phase is not None and not is_diagnostic:
            try:
                self._parallel_files(task, topic, label)
            except ToolError:
                pass

        for step in range(effective_max):
            if self.cancelled:
                final, self._outcome = "Stopped.", "cancelled"
                break
            step_num = step + 1
            self.on_event("thinking_status", {
                "step": step_num,
                "topic": topic,
                "status": f"{label}Step {step_num}: reasoning and choosing the next action...",
            })
            self.on_event("thinking", step_num)

            reply = self._ask(step_num, initial_plan if phase is None else None)
            self.on_event("reply", reply)
            if self.cancelled:
                final, self._outcome = "Stopped.", "cancelled"
                break
            if step == 0 and phase is None:
                plan = extract_plan(reply)
                if plan:
                    self.on_event("plan", plan)

            if not reply.strip():
                empty_replies += 1
                if empty_replies >= 3:
                    final = "The local model returned an empty answer three times in a row. Check DevOS AI Models and try again."
                    self._outcome = "empty"
                    break
                self.messages.append({"role": "user", "content":
                                      "Your last reply was empty. Reply now with one tool block (or the final summary)."})
                continue

            empty_replies = 0                       # only consecutive empty replies count
            calls = parse_tool_calls(reply)
            if not calls and is_build_task:
                # 'path + code block' answers become file writes, but never overwrite a file that already exists
                calls = [c for c in parse_loose_files(reply) if self.ws.read_text_safe(str(c.args.get("path"))) is None]
            self.messages.append({"role": "assistant", "content": self._compact(reply, calls)})

            if not calls and self._runaway_notice:           # the file was cut off as a loop: ask for a short one
                runaway_retries += 1
                reason = "repeating itself" if self._runaway_notice == "repeat" else f"far too long (over {MAX_FILE_LINES} lines)"
                self._runaway_notice = ""
                if runaway_retries <= 2:
                    self.messages.append({"role": "user", "content": (
                        f"Your last file was cut off and NOT written because it was {reason}. Write it again, much shorter: only "
                        "what this phase needs, under about 120 lines, no repeated entries, no boilerplate comments. Prefer a "
                        "generator command (composer require, php artisan make:*) over writing it by hand.")})
                    continue
            if not calls:
                if looks_like_tool_attempt(reply) and bad_format < 2:
                    bad_format += 1
                    self.messages.append({"role": "user", "content": FORMAT_HELP})
                    continue

                reply_clean = " ".join(reply.split()).lower()
                is_repetition = bool(
                    reply_clean == last_non_tool_reply
                    or (last_non_tool_reply and (reply_clean in last_non_tool_reply
                                                 or last_non_tool_reply in reply_clean)))
                last_non_tool_reply = reply_clean
                consecutive_no_tool += 1

                if is_repetition or consecutive_no_tool >= 2:
                    # The user wanted the app started: do it ourselves with the detected command.
                    if any(kw in task_lower for kw in ["run", "start", "serve", "launch", "preview"]) \
                            and not phase and not any(c[0] == "run_command" for c in call_history):
                        run_info = self.ws.detect_run_info()
                        if run_info.get("command"):
                            self.on_event("thinking_status", {
                                "step": step_num, "topic": topic,
                                "status": f"Executing detected project runner: {run_info['command']}..."})
                            cmd_result = self.execute(ToolCall("run_command", {"command": run_info["command"]}))
                            call_history.append(("run_command", run_info["command"], str(cmd_result)[:80]))
                            self.on_event("result", {"tool": "run_command", "text": cmd_result})
                            final = f"Started application with `{run_info['command']}` (URL: {run_info.get('url') or 'active'})."
                            break
                    # A build task with nothing built yet: one forced attempt before giving up.
                    if is_build_task and self._n_changed() == 0 and not forced:
                        forced = True
                        calls = self._force_action(task, topic, step_num)
                        if calls:
                            consecutive_no_tool = 0
                    if not calls:
                        if is_build_task and self._n_changed() == 0:
                            final = (f"{reply.strip()}\n\nThe model described the work but did not write any files. "
                                     "Try a smaller, concrete request (one file or one feature at a time), or pick a "
                                     "stronger engine from the badge at the top right.")
                        else:
                            final = reply.strip()
                        break
                else:
                    if (self.should_continue_task(reply, intent, step) if phase is None
                            else (self._n_changed() == 0 and self._commands_run == 0 and step < 4)):
                        self.on_event("thinking_status", {
                            "step": step_num, "topic": topic,
                            "status": "Continuing autonomous build to next phase/component..."})
                        if self._n_changed() == 0:
                            cont_prompt = (
                                f"Do not describe; act. Start now with a tool block for '{topic}':\n"
                                "```tool write_file\npath: <filepath>\n---\n<complete content>\n```\n"
                                "or\n```tool run_command\ncommand: <shell command>\n```\n"
                                "Output only the tool block.")
                        else:
                            cont_prompt = ("Continue with the next file or action for the task. If the task is "
                                           "fully done, reply with the final summary and no tool block.")
                        self.messages.append({"role": "user", "content": cont_prompt})
                        continue
                    final = reply.strip()
                    break

            if not calls:
                continue
            consecutive_no_tool = 0

            results: List[str] = []
            stop_final = ""
            for call in calls:
                if self.cancelled:
                    break
                tool_target = str(call.args.get("path") or call.args.get("command") or call.args.get("pattern") or "")
                sig = (call.name, tool_target)
                call_counts[sig] = call_counts.get(sig, 0) + 1
                seen = call_counts[sig]
                limit = 3 if call.name in EDIT_TOOLS else 3 if call.name in COMMAND_TOOLS else 2
                if seen >= limit:
                    strikes += 1
                    last = next((h[2] for h in reversed(call_history) if (h[0], h[1]) == sig), "")
                    results.append(f"[{call.name} {tool_target}] already done {seen - 1} times (last result: {last}). "
                                   "Do NOT repeat it. " + ("Give your final answer now."
                                                         if is_diagnostic else "Move on to the next file or finish."))
                    if strikes >= 2 or (is_diagnostic and seen >= limit):
                        stop_final = f"Finished {tool_target or call.name}. See the results above."
                    continue
                self.on_event("thinking_status", {
                    "step": step_num, "topic": topic,
                    "status": f"{label}Executing {call.name} {('· ' + tool_target) if tool_target else ''}...",
                })
                result = self.execute(call)
                if call.name in COMMAND_TOOLS:
                    self._commands_run += 1
                call_history.append((call.name, tool_target, " ".join(str(result).split())[:80]))
                self.on_event("result", {"tool": call.name, "text": result})
                shown = str(result) if len(calls) == 1 else cap_output(str(result), 1500)
                if call.name in EDIT_TOOLS and "Already up to date" in str(result):
                    call_counts[sig] = max(call_counts[sig], limit)
                    shown += f" (File is already identical on disk. Do NOT write {tool_target} again. Move on to a different file or next action.)"
                results.append(f"[{call.name} {tool_target}]\n{shown}")
            if stop_final:
                final = stop_final
                if is_diagnostic:
                    final = next((m["content"] for m in reversed(self.messages) if m["role"] == "assistant"
                                  and len(m["content"]) > 80), stop_final)
                break
            if self.cancelled:
                final, self._outcome = "Stopped.", "cancelled"
                break
            hint = ("Fix any SYNTAX ERROR or failure shown above first. Then continue with the next step, "
                    "or give the final summary if the task is complete.")
            if self._runaway_notice:
                reason = ("repeating itself" if self._runaway_notice == "repeat" else "far too long (a file over "
                          f"{MAX_FILE_LINES} lines)")
                self._runaway_notice = ""
                hint = (f"Your last file was cut off and NOT written because it was {reason}. Write it again, much shorter: "
                        "only what this phase needs, under about 120 lines, no repeated entries, no boilerplate comments. "
                        "Prefer a generator command (composer require, php artisan make:*) over writing it by hand. " + hint)
            if self._multi_notice:
                self._multi_notice = False
                hint = ("Only the FIRST file of your last reply was used: you started a second file inside the same block. "
                        "Write every file in its own ```tool write_file block, close each block with ```, then continue "
                        "with the next file. " + hint)
            self.messages.append({"role": "user", "content": "Results:\n" + "\n\n".join(results) + "\n\n" + hint})
        else:
            final = (f"Stopped after {effective_max} steps. The changes so far are kept; "
                     "ask again to continue.")
            self._outcome = "limit"
        return self._ground(final)

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
        notes: List[str] = []
        for path, new in changes.items():
            if new is not None:
                problems, warnings = self._grounding_problems(path, new)
                if problems:
                    raise ToolError(self._grounding_error(f"Not written: {path}", problems))
                notes.extend(f"Note: {w}. Keep it only if it is essential, and say why in your summary." for w in warnings)
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
        broken = []
        for rel in applied:
            error = self.ws.check_syntax(rel)
            if error:
                broken.append(f"SYNTAX ERROR in {rel}: {error}")
        self.on_event("step_status", "failed" if broken else "done" if applied or same else "denied")
        parts = []
        if applied:
            parts.append("Applied: " + ", ".join(applied) + ".")
        parts.extend(notes)
        if broken:
            parts.extend(broken)
            parts.append("Fix the error now with write_file (complete file) or apply_patch.")
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
        warnings: List[str] = []
        if self.grounding is not None:
            names = brief.composer_command_packages(command)
            own = self._own_names("", "")
            problems = self.grounding.composer_problems(names, own)
            for n in self.grounding.invented_in_text(command, own):     # heredocs, echo >> composer.json, npm, git ...
                msg = f"{n} is not in the brief"
                if msg not in problems:
                    problems.append(msg)
            if problems:
                raise ToolError(self._grounding_error("Not run", problems))
            warnings = self.grounding.composer_warnings(names)
        action = Action("command", call.name, f"Run: {command}", command=command)
        self.on_event("step", {"title": action.title, "kind": "command"})
        self.on_event("command", action)
        if self.policy.needs_approval(call.name) and not self.approve(action):
            self.on_event("step_status", "denied")
            return "The user did not allow this command. Do not run it again; continue without it or ask."
        result = self.ws.run_command(command, call.args.get("timeout"), should_stop=lambda: self.cancelled)
        self._commands_log.append((command, int(result["code"]) if result["code"] is not None else -1))
        self.on_event("output", result)
        self.on_event("step_status", "done" if result["code"] == 0 else "failed")
        status = (f"timed out after {result['seconds']} s" if result["timed_out"]
                  else f"exit code {result['code']}")
        notes = "".join(f"\nNote: {w}. Keep it only if it is essential, and say why in your summary." for w in warnings)
        return f"{status}\n{result['output'] or '(no output)'}{notes}"


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
    elif kind == "report":
        print("\n" + payload)
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
    parser.add_argument("--auto-commands", action="store_true", help="run project commands without asking (trusted projects only)")
    parser.add_argument("--ask-reads", action="store_true", help="ask before the agent reads files too")
    parser.add_argument("--max-steps", type=int, default=15)
    args = parser.parse_args(argv)

    if args.cli:
        folder = args.dir or args.prompt or os.getcwd()
        return run_cli(args.cli, folder, args.auto_edits, not args.ask_reads,
                       auto_commands=args.auto_commands, max_steps=args.max_steps)
    if args.gui or not args.prompt:
        import agent_gui
        return agent_gui.main([a for a in [args.dir or args.prompt] if a])

    agent = DevOSCodeAgent(project_dir=args.dir or ".")
    res = agent.query_local_code_model(args.prompt, framework=args.framework)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
