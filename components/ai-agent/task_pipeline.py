#!/usr/bin/env python3
"""DevOS AI Multi-Agent Task Pipeline & Rate-Limit Aware Scheduler.

Enables serial chaining of AI commands across ChatGPT/Codex, Antigravity,
and DevOS Local AI with automatic rate-limit cooldown detection and timer wakeups.

Features:
1. Sequential Command Chaining:
   Task 1 (ChatGPT) -> on complete -> Task 2 (Antigravity) -> Task 3 (Local AI)
2. Smart Rate-Limit Detection & Auto-Sleep:
   Detects cooldowns like "wait for usage to reset on 10:46 AM" and automatically
   schedules the next command for 10:47 AM with zero human intervention.
3. Cross-Agent Failover:
   Optionally delegates pending commands to Antigravity when ChatGPT hits a rate limit.
4. OS-Level Desktop Notifications:
   Notifies the user via desktop toast notifications when commands start, pause, or complete.
"""

import argparse
import fcntl
import functools
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import threading
import uuid
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

STATE_FILE = Path(os.path.expanduser("~/.local/share/devos/ai-pipeline.json"))
CONTEXT_FILE = Path(os.path.expanduser("~/.local/share/devos/ai-pipeline-context.json"))
AGENTAPI_BIN = Path(os.path.expanduser("~/.gemini/antigravity/bin/agentapi"))
CUSTOM_AGENTS_DIR = Path.expanduser(Path("~/.config/devos/agents"))


def to_slug(text: str) -> str:
    """Converts a title, name, or prompt into a clean, filesystem-safe slug."""
    if not text:
        return "project"
    slug = text.strip().lower()
    slug = slug.replace("'", "").replace('"', "")
    slug = re.sub(r"[^\w\s-]", "-", slug)
    slug = re.sub(r"[-\s_]+", "-", slug)
    return slug.strip("-") or "project"


def split_prompts(raw_text: str) -> List[str]:
    """Splits a multi-command / multi-step prompt string into individual tasks.

    Rules:
    1. If explicit delimiters exist ('---', '===', or '### Step N' / '[Step N]' on their own line),
       split by delimiter so each step can contain multiple paragraphs, code blocks, and 5000+ words.
    2. If no delimiters exist:
       The ENTIRE text (including all paragraphs, headings, bullet points, and newlines)
       is preserved intact as ONE single comprehensive prompt step.
    """
    text = (raw_text or "").strip()
    if not text:
        return []

    # Delimiters: 3 or more hyphens or equals on a line, or Step headers
    delim_pattern = re.compile(
        r"(?:\r?\n|^)\s*(?:-{3,}|={3,}|###\s*Step\s*\d+|\[Step\s*\d+\])\s*(?:\r?\n|$)",
        re.IGNORECASE,
    )
    parts = delim_pattern.split(text)
    cleaned = [p.strip() for p in parts if p.strip()]
    if len(cleaned) > 1:
        return cleaned
    return [text]


def is_agent_process_running(agent: str) -> tuple[bool, Optional[int]]:
    """Checks whether the agent's application process is actively running in the OS.
    Returns: (is_running, pid)
    """
    ag = (agent or "").lower()
    proc_dir = Path("/proc")
    if not proc_dir.exists():
        return False, None

    for proc in proc_dir.iterdir():
        if not proc.name.isdigit():
            continue
        try:
            pid = int(proc.name)
            cmdline_bytes = (proc / "cmdline").read_bytes()
            cmdline = cmdline_bytes.decode("utf-8", errors="ignore").replace("\0", " ")
            if not cmdline.strip():
                continue

            if ag in ("antigravity-kde", "antigravity_kde"):
                if "antigravity-kde" in cmdline or "Antigravity-KDE" in cmdline or "app_data_dir=antigravity-kde" in cmdline:
                    return True, pid
            elif ag in ("antigravity", "google-antigravity"):
                if ("/opt/antigravity" in cmdline or "app_data_dir=antigravity" in cmdline) and "antigravity-kde" not in cmdline:
                    return True, pid
            elif ag in ("chatgpt", "codex"):
                if "codex-linux-sandbox" in cmdline or "codex-code-mode-host" in cmdline or "codex exec" in cmdline:
                    return True, pid
            elif ag == "claude":
                comm = (proc / "comm").read_text(errors="ignore").strip()
                if comm == "claude":
                    return True, pid
            elif ag == "aider":
                comm = (proc / "comm").read_text(errors="ignore").strip()
                if comm == "aider":
                    return True, pid
            elif ag == "local":
                comm = (proc / "comm").read_text(errors="ignore").strip()
                if "ollama" in comm or "devos-ai-code" in cmdline:
                    return True, pid
        except Exception:
            continue

    return False, None


def detect_current_project(
    base_dir: Optional[str] = None, agent: Optional[str] = None
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Auto-detects the currently active working project name, slug, and folder path.

    Detection strategy:
    1. Active target agent's running processes (--add-dir / open workspaces)
    2. Target agent's workspace storage (Antigravity-KDE / Antigravity workspaceStorage)
    3. Active agent conversation brain transcripts
    4. Active Antigravity / IDE app_storage.json
    5. Active terminal shell processes working directory (/proc/*/cwd)
    6. Current process working directory
    7. Most recently modified project folder in base_dir
    Returns: (slug, title, folder_path)
    """
    b_dir = Path(base_dir).resolve() if base_dir else Path.home() / "project"
    if not b_dir.exists() or not b_dir.is_dir():
        b_dir = Path.cwd().resolve()

    candidates: List[Path] = []

    def _add_cand(p):
        try:
            cand = Path(p).resolve()
            if not cand.exists() or not cand.is_dir():
                return
            if cand.is_relative_to(b_dir):
                if cand != b_dir:
                    top_sub = b_dir / cand.relative_to(b_dir).parts[0]
                    if top_sub.is_dir() and top_sub not in candidates:
                        candidates.append(top_sub)
                elif cand == b_dir and (b_dir / ".git").exists() and cand not in candidates:
                    candidates.append(cand)
            elif not candidates and (b_dir == (Path.home() / "project") or b_dir == Path.cwd()):
                # Allow candidate if base_dir is default fallback root
                if cand not in candidates:
                    candidates.append(cand)
        except Exception:
            pass

    is_kde_session = ("KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "")) or (
        os.environ.get("DESKTOP_SESSION") == "plasma"
    )

    # 1. Inspect running process command lines for --add-dir (gives live active workspace)
    proc_dir = Path("/proc")
    if proc_dir.exists():
        for proc in proc_dir.iterdir():
            if not proc.name.isdigit():
                continue
            try:
                cmdline_bytes = (proc / "cmdline").read_bytes()
                cmdline = cmdline_bytes.decode("utf-8", errors="ignore").replace("\0", " ")
                if not cmdline.strip():
                    continue

                match_kde = (
                    "antigravity-kde" in cmdline
                    or "Antigravity-KDE" in cmdline
                    or "app_data_dir=antigravity-kde" in cmdline
                )
                match_std = (
                    ("/opt/antigravity" in cmdline or "app_data_dir=antigravity" in cmdline)
                    and not match_kde
                )

                is_target = False
                if agent in ("antigravity-kde", "antigravity_kde"):
                    is_target = match_kde
                elif agent in ("antigravity", "google-antigravity"):
                    is_target = match_std
                else:
                    is_target = (match_kde if is_kde_session else match_std) or match_kde or match_std

                if is_target:
                    for m in re.finditer(r"--add-dir[=\s]+([^\s\0]+)", cmdline):
                        _add_cand(m.group(1))
            except Exception:
                continue

    # 2. Inspect workspaceStorage for Antigravity-KDE and/or Antigravity
    config_dirs = []
    if agent in ("antigravity-kde", "antigravity_kde"):
        config_dirs.append(Path.home() / ".config/Antigravity-KDE")
    elif agent in ("antigravity", "google-antigravity"):
        config_dirs.append(Path.home() / ".config/Antigravity")
    else:
        if is_kde_session:
            config_dirs.extend([Path.home() / ".config/Antigravity-KDE", Path.home() / ".config/Antigravity"])
        else:
            config_dirs.extend([Path.home() / ".config/Antigravity", Path.home() / ".config/Antigravity-KDE"])

    for cdir in config_dirs:
        ws_files = list(cdir.glob("User/workspaceStorage/*/workspace.json"))
        ws_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        for wf in ws_files:
            try:
                data = json.loads(wf.read_text())
                uri = data.get("folder", "")
                if uri.startswith("file://"):
                    _add_cand(uri[7:])
            except Exception:
                pass

        app_storage = cdir / "app_storage.json"
        if app_storage.exists():
            try:
                data = json.loads(app_storage.read_text())
                text = json.dumps(data)
                matches = re.findall(r"file://(" + re.escape(str(b_dir)) + r"/[^/\"\'#]+)", text)
                for m in reversed(matches):
                    _add_cand(m)
            except Exception:
                pass

    # 3. Check Brain transcripts for recent Active Workspaces
    brain_dirs = []
    if agent in ("antigravity-kde", "antigravity_kde"):
        brain_dirs.append(Path.home() / ".gemini/antigravity-kde/brain")
    elif agent in ("antigravity", "google-antigravity"):
        brain_dirs.append(Path.home() / ".gemini/antigravity/brain")
    else:
        if is_kde_session:
            brain_dirs.extend([Path.home() / ".gemini/antigravity-kde/brain", Path.home() / ".gemini/antigravity/brain"])
        else:
            brain_dirs.extend([Path.home() / ".gemini/antigravity/brain", Path.home() / ".gemini/antigravity-kde/brain"])

    for bdir in brain_dirs:
        transcripts = list(bdir.glob("*/.system_generated/logs/transcript.jsonl"))
        transcripts.sort(key=lambda t: t.stat().st_mtime, reverse=True)
        for t in transcripts[:5]:
            try:
                with open(t, "r", encoding="utf-8", errors="ignore") as f:
                    chunk = f.read(8192)
                    m = re.findall(r"Active Workspaces:\s*\n-\s*([^\n\r]+)", chunk)
                    for path_str in m:
                        _add_cand(path_str.strip())
            except Exception:
                pass

    # 4. Inspect active shell processes in /proc
    if proc_dir.exists():
        for proc in proc_dir.iterdir():
            if proc.name.isdigit():
                try:
                    cwd = Path(os.readlink(f"/proc/{proc.name}/cwd")).resolve()
                    if cwd.is_relative_to(b_dir) and cwd != b_dir:
                        proj = b_dir / cwd.relative_to(b_dir).parts[0]
                        _add_cand(proj)
                except Exception:
                    pass

    # 5. Check current process working directory (if inside base_dir)
    cwd = Path.cwd().resolve()
    if cwd.is_relative_to(b_dir) and cwd != b_dir:
        proj = b_dir / cwd.relative_to(b_dir).parts[0]
        _add_cand(proj)

    # 6. Check most recently modified folder in base_dir
    if b_dir.exists():
        subdirs = [d for d in b_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        subdirs.sort(key=lambda d: os.path.getmtime(d), reverse=True)
        for s in subdirs:
            _add_cand(s)

    # 7. Fallback to cwd if no project was found in base_dir
    if not candidates and (cwd / ".git").exists():
        _add_cand(cwd)

    if candidates:
        top = candidates[0]
        slug = to_slug(top.name)
        title = top.name.replace("-", " ").title()
        return slug, title, str(top)

    return None, None, None


def list_existing_projects(base_dir: Optional[str] = None) -> List[Dict[str, str]]:
    """Returns all project directories inside base_dir ordered by recent modification."""
    b_dir = Path(base_dir).resolve() if base_dir else Path.home() / "project"
    if not b_dir.exists() or not b_dir.is_dir():
        return []
    projects = []
    subdirs = [d for d in b_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    subdirs.sort(key=lambda d: os.path.getmtime(d), reverse=True)
    for d in subdirs:
        projects.append({
            "slug": to_slug(d.name),
            "title": d.name.replace("-", " ").title(),
            "path": str(d.resolve()),
        })
    return projects


def get_grouped_projects(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Groups queued tasks into structured project objects preserving sequence."""
    projects_map: Dict[str, Dict[str, Any]] = {}
    projects_order: List[str] = []

    for task in tasks:
        slug = task.get("project_slug") or to_slug(task.get("project_title") or "default-project")
        if slug not in projects_map:
            p_title = task.get("project_title") or slug.replace("-", " ").title()
            p_dir = task.get("project") or ""
            projects_map[slug] = {
                "slug": slug,
                "title": p_title,
                "dir": p_dir,
                "tasks": [],
                "github_url": None,
            }
            projects_order.append(slug)

        projects_map[slug]["tasks"].append(task)
        if task.get("github_url") and not projects_map[slug]["github_url"]:
            projects_map[slug]["github_url"] = task["github_url"]
        if not projects_map[slug]["dir"] and task.get("project"):
            projects_map[slug]["dir"] = task["project"]

    return [projects_map[s] for s in projects_order]


def discover_agents() -> Dict[str, Dict[str, Any]]:
    """Auto-detects available AI agents, their binary paths, and live running process states."""
    agents = {}

    kde_running, kde_pid = is_agent_process_running("antigravity-kde")
    std_running, std_pid = is_agent_process_running("antigravity")
    codex_running, codex_pid = is_agent_process_running("chatgpt")
    claude_running, claude_pid = is_agent_process_running("claude")
    aider_running, aider_pid = is_agent_process_running("aider")
    local_running, local_pid = is_agent_process_running("local")

    # 1. Google Antigravity
    ag_bin = shutil.which("antigravity") or AGENTAPI_BIN
    ag_ok = bool((ag_bin and Path(ag_bin).exists()) or std_running)
    agents["antigravity"] = {
        "name": "Google Antigravity",
        "bin": str(ag_bin) if ag_bin and Path(ag_bin).exists() else None,
        "color": "#2563eb",
        "available": ag_ok,
        "running": std_running,
        "pid": std_pid,
    }

    # 1b. Antigravity KDE (Second Independent Agent)
    kde_candidates = [
        shutil.which("antigravity-kde"),
        Path.home() / ".local/bin/antigravity-kde",
        Path.home() / ".local/lib/antigravity-ide/antigravity-ide",
        Path.home() / ".local/lib/antigravity-ide/bin/antigravity-ide",
    ]
    ag_kde_bin = next((str(p) for p in kde_candidates if p and Path(p).exists()), None)
    ag_kde_ok = bool(ag_kde_bin or kde_running)
    import importlib
    import antigravity_connection
    importlib.reload(antigravity_connection)
    connection_environment = antigravity_connection.connection_environment
    kde_api_ready = connection_environment("antigravity-kde") is not None
    agents["antigravity-kde"] = {
        "name": "Antigravity KDE" + (" (API configured)" if kde_api_ready else " (API setup required)"),
        "bin": ag_kde_bin,
        "color": "#0ea5e9",
        "available": ag_kde_ok,
        "running": kde_running,
        "pid": kde_pid,
    }

    # 2. ChatGPT / Codex CLI
    codex_candidates = [
        shutil.which("codex"),
        Path.home() / ".npm-global/bin/codex",
        Path("/usr/local/bin/codex"),
    ]
    codex_bin = next((str(p) for p in codex_candidates if p and Path(p).exists()), None)
    agents["chatgpt"] = {
        "name": "ChatGPT / Codex",
        "bin": codex_bin,
        "color": "#10a37f",
        "available": bool(codex_bin or codex_running),
        "running": codex_running,
        "pid": codex_pid,
    }

    # 3. Claude Code CLI
    claude_bin = shutil.which("claude")
    agents["claude"] = {
        "name": "Claude Code",
        "bin": claude_bin,
        "color": "#d97706",
        "available": bool(claude_bin or claude_running),
        "running": claude_running,
        "pid": claude_pid,
    }

    # 4. Aider Multi-Model Pair Programmer
    aider_bin = shutil.which("aider")
    agents["aider"] = {
        "name": "Aider Pair Programmer",
        "bin": aider_bin,
        "color": "#059669",
        "available": bool(aider_bin or aider_running),
        "running": aider_running,
        "pid": aider_pid,
    }

    # 5. DevOS Local AI / Ollama
    ollama_bin = shutil.which("ollama")
    agents["local"] = {
        "name": "DevOS Local AI",
        "bin": ollama_bin,
        "color": "#7c3aed",
        "available": True,
        "running": local_running,
        "pid": local_pid,
    }

    # 6. Custom Agents directory: ~/.config/devos/agents/
    if CUSTOM_AGENTS_DIR.exists():
        for script in list(CUSTOM_AGENTS_DIR.glob("*.sh")) + list(CUSTOM_AGENTS_DIR.glob("*.py")):
            key = script.stem.lower()
            agents[key] = {
                "name": f"Custom: {script.stem.title()}",
                "bin": str(script),
                "color": "#ec4899",
                "available": True,
                "running": False,
                "pid": None,
            }

    return agents


def notify(title: str, message: str, urgency: str = "normal"):
    """Sends native desktop notification asynchronously."""
    try:
        subprocess.Popen(
            ["notify-send", "-a", "DevOS AI Pipeline", "-u", urgency, title, message],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def copy_to_clipboard(text: str):
    """Copies text to the Linux system clipboard using xclip or wl-copy."""
    for cmd in (["xclip", "-selection", "clipboard"], ["wl-copy"]):
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            p.communicate(input=text.encode("utf-8"), timeout=2)
            if p.returncode == 0:
                return
        except Exception:
            continue


def extract_repo_metadata(text: str) -> tuple[Optional[str], Optional[str]]:
    """Extracts proposed SEO repository name and description from AI response or prompt."""
    name = None
    desc = None

    # Search for repo name in various markdown and plain text formats
    name_patterns = [
        r"^[ \t]*(?:\*\*|###|#)?[ \t]*(?:best\s+)?(?:github\s+)?repo(?:sitory)?[ \t]*(?:name)?[ \t]*(?:\*\*|###|#)?[ \t]*[:\-=][ \t]*[`'\"]?([a-zA-Z0-9_\-\.]+)[`'\"]?",
        r"(?:\*\*|###|#)?[ \t]*(?:github\s+)?repo(?:sitory)?[ \t]*(?:name)?[ \t]*(?:\*\*|###|#)?[ \t]*[:\-=][ \t]*[`'\"]?([a-zA-Z0-9_\-\.]+)[`'\"]?",
        r"(?:repo(?:sitory)?(?:_name)?|github_repo)\s*[:=]\s*[`'\"]?([a-zA-Z0-9_\-\.]+)[`'\"]?",
        r"`([a-z0-9]+(?:-[a-z0-9]+)+)`",
    ]
    for p in name_patterns:
        m = re.search(p, text, re.IGNORECASE | re.MULTILINE)
        if m:
            candidate = m.group(1).strip()
            # Ignore generic placeholders
            if candidate.lower() not in ("name", "repo", "repository", "none", "best"):
                name = candidate
                break

    # Search for description (up to 350-400 chars for maximum SEO reach)
    desc_patterns = [
        r"(?:\*\*|###|#)?[ \t]*(?:seo\s+)?desc(?:ription)?(?:\s*\([^\)]*\))?(?:\*\*|###|#)?[ \t]*[:\-=][ \t]*[`'\"]?([^\n\r]+(?:\n[^\n\r#*]+)*)",
        r"desc(?:ription)?\s*[:=]\s*[`'\"]?([^`'\n]+)",
    ]
    for p in desc_patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            raw_desc = m.group(1).strip()
            # Clean up markdown formatting and multi-line wrapping
            clean_desc = re.sub(r"\s+", " ", raw_desc).strip("`'\"*# ")
            # Strip trailing tags or headers
            clean_desc = re.split(r"###|\*\*Tags|Tags:", clean_desc)[0].strip()
            # GitHub description has a 350 character maximum limit
            if len(clean_desc) > 350:
                clean_desc = clean_desc[:347].rsplit(" ", 1)[0] + "..."
            desc = clean_desc
            break

    return name, desc


def create_github_repo(
    repo_name: str,
    description: str = "",
    project_dir: str = "",
    public: bool = True,
    push: bool = True,
    open_browser: bool = True,
) -> tuple[bool, str]:
    """Creates a GitHub repository under the logged-in account, pushes code, and opens it in the browser."""
    clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "-", repo_name.strip()).strip("-")
    if not clean_name:
        return False, "Invalid repository name"

    # Copy description and name to system clipboard so user has it instantly
    clipboard_content = f"{clean_name}\n\n{description}" if description else clean_name
    copy_to_clipboard(clipboard_content)

    p_path = Path(project_dir).resolve() if project_dir else Path.cwd()
    if not p_path.exists():
        p_path.mkdir(parents=True, exist_ok=True)

    # Pre-generate populated browser URL for github.com/new
    query_params = {"name": clean_name}
    if description:
        query_params["description"] = description
    browser_new_url = f"https://github.com/new?{urllib.parse.urlencode(query_params)}"

    # Check gh auth status
    if not shutil.which("gh"):
        return False, "GitHub CLI is not installed; repository was not created."
    gh_check = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if gh_check.returncode != 0:
        # Fallback to opening browser create form directly
        if open_browser:
            subprocess.Popen(["xdg-open", browser_new_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return False, "GitHub authentication required; repository was not created."

    # Ensure git repo is initialized locally
    if not (p_path / ".git").exists():
        subprocess.run(["git", "init", "-b", "main"], cwd=str(p_path), check=False)

    # Enforce developer identity
    subprocess.run(["git", "config", "user.name", "Imran Ahmed"], cwd=str(p_path), check=False)
    subprocess.run(["git", "config", "user.email", "me@imrandev.bd"], cwd=str(p_path), check=False)

    # Ensure README.md exists
    readme_path = p_path / "README.md"
    if not readme_path.exists():
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(
                f"# {clean_name}\n\n"
                f"{description or 'Created with DevOS AI Task Pipeline.'}\n\n"
                f"---\n*Developed by [Imran Ahmed](https://imrandev.bd)*\n"
            )

    # Add and commit if there are changes
    subprocess.run(["git", "add", "."], cwd=str(p_path), check=False)
    for command in (["git", "config", "user.name"], ["git", "config", "user.email"],
                    ["git", "var", "GIT_AUTHOR_IDENT"], ["git", "var", "GIT_COMMITTER_IDENT"]):
        identity = subprocess.run(command, cwd=str(p_path), capture_output=True, text=True, check=True).stdout.strip()
        expected = "Imran Ahmed <me@imrandev.bd>"
        if command[-1] == "user.name" and identity != "Imran Ahmed":
            return False, "Git author name mismatch"
        if command[-1] == "user.email" and identity != "me@imrandev.bd":
            return False, "Git author email mismatch"
        if command[1] == "var" and not identity.startswith(expected + " "):
            return False, "Effective Git identity mismatch"
    changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(p_path))
    if changed.returncode == 1:
        subprocess.run(["git", "commit", "-m", f"Initial commit: {clean_name}"], cwd=str(p_path), check=True)

    vis_flag = "--public" if public else "--private"
    cmd = ["gh", "repo", "create", f"imranbru99/{clean_name}", vis_flag]
    if description:
        cmd.extend(["-d", description])
    if push:
        cmd.extend(["--source", str(p_path), "--remote", "origin", "--push"])

    res = subprocess.run(cmd, cwd=str(p_path), capture_output=True, text=True)
    full_url = f"https://github.com/imranbru99/{clean_name}"

    if res.returncode == 0:
        if open_browser:
            subprocess.Popen(["xdg-open", full_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, full_url
    else:
        # If gh failed, open browser new repo page with name & description prefilled
        if open_browser:
            subprocess.Popen(["xdg-open", browser_new_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return False, res.stderr or "Failed to create repo via gh"


def is_antigravity_working(kde: bool = False) -> bool:
    """Checks if any Antigravity conversation (GNOME or KDE instance) is currently executing a turn or tool."""
    brain_dir = (Path.home() / ".gemini/antigravity-kde/brain") if kde else (Path.home() / ".gemini/antigravity/brain")
    if not brain_dir.exists():
        return False
    transcripts = list(brain_dir.glob("*/.system_generated/logs/transcript.jsonl"))
    if not transcripts:
        return False
    latest = max(transcripts, key=os.path.getmtime)
    try:
        if time.time() - latest.stat().st_mtime > 180:
            return False  # stale transcript is not an active turn (nor proof of completion)
        with open(latest, "r", encoding="utf-8") as f:
            f.seek(max(0, latest.stat().st_size - 65536))
            lines = f.readlines()
            if lines:
                data = json.loads(lines[-1])
                return data.get("status") == "RUNNING"
    except Exception:
        pass
    return False


def is_codex_working() -> bool:
    """Checks if Codex desktop app is actively running a turn, container, or command."""
    # Check if sandbox or host execution processes are running
    res = subprocess.run(["pgrep", "-f", "codex-linux-sandbox|codex-code-mode-host"], capture_output=True)
    if res.returncode == 0:
        return True

    # Check recent session rollout updates (within 6 seconds)
    sessions_dir = Path.home() / ".codex/sessions"
    if sessions_dir.exists():
        rollouts = list(sessions_dir.glob("*/*/*.jsonl"))
        if rollouts:
            latest = max(rollouts, key=os.path.getmtime)
            if (time.time() - os.path.getmtime(latest)) < 6.0:
                return True
    return False


def is_agent_working(agent: str) -> bool:
    """Universal status check: returns True if the specified agent is actively busy."""
    ag = (agent or "").lower()
    if ag == "antigravity":
        return is_antigravity_working(kde=False)
    elif ag in ("antigravity-ide", "antigravity-kde"):
        return is_antigravity_working(kde=True)
    elif ag in ("chatgpt", "codex"):
        return is_codex_working()
    elif ag == "local":
        res = subprocess.run(["pgrep", "-f", "code-agent/pipeline_worker.py"], capture_output=True)
        return res.returncode == 0
    return False


def parse_reset_time(text: str) -> Optional[datetime.datetime]:
    """Extracts rate-limit reset time from messages like:

    'wait for usage to reset on 10:46 AM' or 'try again at 02:15 PM'.
    Returns target datetime with a 1-minute safety buffer.
    """
    patterns = [
        r"reset\s+on\s+(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)",
        r"try\s+again\s+(?:at|on)\s+(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)",
        r"resets?\s+(?:in|at)\s+(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            time_str = m.group(1).strip()
            now = datetime.datetime.now()
            # Try 12-hour AM/PM format
            for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M"):
                try:
                    t = datetime.datetime.strptime(time_str.upper(), fmt).time()
                    target = datetime.datetime.combine(now.date(), t)
                    # If target is in the past, it might be for tomorrow
                    if target < now:
                        target += datetime.timedelta(days=1)
                    # Add 60-second safety buffer so limit has cleared (e.g. 10:46 -> 10:47)
                    return target + datetime.timedelta(minutes=1)
                except ValueError:
                    continue
    return None


def queue_transaction(method):
    @functools.wraps(method)
    def wrapped(self, *args, **kwargs):
        lock = self.state_file.with_suffix(self.state_file.suffix + ".lock")
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if method.__name__ in ("execute_next", "_claim_next"):
                    return False
                raise RuntimeError("Another pipeline command is running. Try again after it finishes.")
            self.queue = self._load()
            self.context = self._load_context()
            return method(self, *args, **kwargs)
        finally:
            os.close(fd)
    return wrapped


class TaskPipeline:
    def __init__(self, state_file: Path = STATE_FILE, context_file: Path = CONTEXT_FILE):
        self.event_callback = None
        self._dispatch_threads = []
        self._last_event = None
        self.state_file = state_file
        self.context_file = context_file
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.queue: List[Dict[str, Any]] = self._load()
        self.context: Dict[str, Any] = self._load_context()

    def emit_event(self, message):
        if message == self._last_event:
            return
        self._last_event = message
        line = f"[{datetime.datetime.now():%H:%M:%S}] {message}"
        path = self.state_file.with_suffix('.events.jsonl')
        try:
            if path.exists() and path.stat().st_size > 1024 * 1024:
                os.replace(path, path.with_suffix('.previous.jsonl'))
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'a', encoding='utf-8') as stream:
                stream.write(json.dumps({'message': line}) + '\n')
        except OSError:
            pass
        if self.event_callback:
            self.event_callback(line)

    def clear_events(self):
        """Clear activity history only; preserve all projects and task state."""
        path = self.state_file.with_suffix('.events.jsonl')
        for target in (path, path.with_suffix('.previous.jsonl')):
            if target.exists():
                fd = os.open(target, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
                os.close(fd)
        self._last_event = None

    def recent_events(self):
        path = self.state_file.with_suffix('.events.jsonl')
        if not path.exists():
            return []
        result = []
        for line in path.read_text().splitlines()[-100:]:
            try:
                result.append(json.loads(line)['message'])
            except (ValueError, KeyError):
                continue
        return result

    def _load(self) -> List[Dict[str, Any]]:
        if not self.state_file.exists():
            return []
        with self.state_file.open(encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, list) or any(not isinstance(t, dict) for t in value):
            raise ValueError("Invalid pipeline queue; the existing file was preserved.")
        return value

    @staticmethod
    def _atomic_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".pipeline-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _save(self):
        self._atomic_json(self.state_file, self.queue)

    def _load_context(self) -> Dict[str, Any]:
        if not self.context_file.exists():
            return {}
        with self.context_file.open(encoding="utf-8") as stream:
            value = json.load(stream)
        if not isinstance(value, dict):
            raise ValueError("Invalid pipeline context; the existing file was preserved.")
        return value

    def _save_context(self):
        self._atomic_json(self.context_file, self.context)

    def get_base_dir(self) -> str:
        stored = self.context.get("base_dir")
        if stored:
            p = Path(stored).expanduser().resolve()
            if p.exists() and p.is_dir():
                return str(p)
        candidates = [
            Path.home() / "project",
            Path.home() / "Projects",
            Path.cwd(),
        ]
        for c in candidates:
            if c.exists() and c.is_dir():
                return str(c.resolve())
        default_dir = Path.home() / "project"
        default_dir.mkdir(parents=True, exist_ok=True)
        return str(default_dir.resolve())

    @queue_transaction
    def set_base_dir(self, directory: str) -> str:
        p = Path(directory).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        self.context["base_dir"] = str(p)
        self._save_context()
        return str(p)

    @queue_transaction
    def add(
        self,
        prompt: str,
        agent: str = "antigravity",
        project: str = "",
        delay_seconds: int = 0,
        create_repo: bool = False,
        repo_name: str = "",
        repo_desc: str = "",
        project_title: str = "",
        project_slug: str = "",
        notify_desktop: bool = False,
    ) -> str:
        task_id = "task_" + uuid.uuid4().hex[:16]
        run_at = (datetime.datetime.now() + datetime.timedelta(seconds=delay_seconds)).isoformat()

        # Derive slug and title
        p_title = (project_title or "").strip()
        p_slug = to_slug(project_slug) if (project_slug or "").strip() else ""

        if not p_slug:
            if p_title:
                p_slug = to_slug(p_title)
            elif repo_name:
                p_slug = to_slug(repo_name)
            elif project:
                p_slug = to_slug(Path(project).name)
            else:
                p_slug = to_slug(prompt[:40])

        if not p_title:
            p_title = p_slug.replace("-", " ").title()

        if not project:
            base_dir = self.get_base_dir()
            project = str(Path(base_dir) / p_slug)

        item = {
            "id": task_id,
            "project_title": p_title,
            "project_slug": p_slug,
            "prompt": prompt,
            "agent": agent.lower(),  # "chatgpt", "antigravity", "local", etc.
            "project": project,
            "status": "QUEUED",      # QUEUED, RUNNING, RATE_LIMITED, COMPLETED, FAILED
            "run_at": run_at,
            "retry_at": None,
            "created_at": datetime.datetime.now().isoformat(),
            "output": None,
            "create_repo": create_repo,
            "repo_name": repo_name or (p_slug if create_repo else ""),
            "repo_desc": repo_desc,
            "github_url": None,
        }
        self.queue.append(item)
        self._save()
        if notify_desktop:
            notify("Task Queued", f"[{p_slug}] [{agent.upper()}] {prompt[:60]}...")
        return task_id

    def add_commands(
        self,
        prompts: List[str],
        agent: str = "antigravity",
        project_title: str = "",
        project_slug: str = "",
        create_repo: bool = False,
        repo_name: str = "",
        repo_desc: str = "",
        delay_seconds: int = 0,
        notify_desktop: bool = True,
    ) -> List[str]:
        task_ids = []
        clean_prompts = [p.strip() for p in prompts if p.strip()]
        for idx, p in enumerate(clean_prompts):
            is_repo = create_repo if idx == 0 else False
            tid = self.add(
                prompt=p,
                agent=agent,
                project_title=project_title,
                project_slug=project_slug,
                create_repo=is_repo,
                repo_name=repo_name,
                repo_desc=repo_desc,
                delay_seconds=delay_seconds,
                notify_desktop=False,
            )
            task_ids.append(tid)
        if notify_desktop and clean_prompts:
            notify("Project Queued", f"[{project_slug or 'project'}] Added {len(clean_prompts)} step(s)")
        return task_ids

    def list(self) -> List[Dict[str, Any]]:
        return self.queue

    @queue_transaction
    def append_project_prompt(self, project_slug, prompt, agent=None):
        if not prompt.strip():
            raise ValueError("Enter a prompt first.")
        positions = [i for i, t in enumerate(self.queue) if t.get('project_slug') == project_slug]
        if not positions:
            raise ValueError("Project no longer exists.")
        previous = self.queue[positions[-1]]
        now = datetime.datetime.now().isoformat()
        task = {k: previous.get(k, '') for k in ('project', 'project_title', 'project_slug')}
        task.update(id='task_' + uuid.uuid4().hex[:16], prompt=prompt,
                    agent=agent or previous['agent'], status='QUEUED', run_at=now,
                    created_at=now, retry_at=None, output=None, create_repo=False,
                    repo_name='', repo_desc='', github_url=previous.get('github_url'))
        self.queue.insert(positions[-1] + 1, task)
        self._save()
        return task['id']

    @queue_transaction
    def move_project_prompt(self, task_id, direction):
        if direction not in (-1, 1):
            raise ValueError("Direction must be up or down.")
        index = next((i for i,t in enumerate(self.queue) if t['id'] == task_id), None)
        if index is None:
            raise ValueError("Prompt no longer exists.")
        task = self.queue[index]
        positions = [i for i,t in enumerate(self.queue) if t.get('project_slug') == task.get('project_slug')]
        target = positions.index(index) + direction
        if target < 0 or target >= len(positions):
            return False
        other = positions[target]
        if task['status'] != 'QUEUED' or self.queue[other]['status'] != 'QUEUED':
            raise ValueError("Only unstarted prompts can move. Running or completed steps keep their order.")
        self.queue[index], self.queue[other] = self.queue[other], self.queue[index]
        self._save()
        return True

    @queue_transaction
    def delete_task(self, task_id: str, force: bool = False):
        if not force and any(t["id"] == task_id and t["status"] == "RUNNING" for t in self.queue):
            raise ValueError("Verify or finish the active task before removing it.")
        self.queue = [t for t in self.queue if t["id"] != task_id]
        self._save()

    @queue_transaction
    def delete_project(self, project_slug: str, force: bool = False):
        if not force and any(t.get("project_slug") == project_slug and t["status"] == "RUNNING" for t in self.queue):
            raise ValueError("Verify or finish the active project before removing it.")
        self.queue = [t for t in self.queue if t.get("project_slug") != project_slug]
        self._save()

    @queue_transaction
    def update_task(self, task_id, changes):
        for task in self.queue:
            if task["id"] == task_id:
                task.update(changes)
                self._save()
                return
        raise ValueError("Task no longer exists")

    @queue_transaction
    def clear(self, force: bool = False):
        if not force and any(t["status"] == "RUNNING" for t in self.queue):
            raise ValueError("Verify or finish active tasks before clearing the queue.")
        self.queue = []
        self._save()

    def _complete_task(self, task):
        task["status"] = "COMPLETED"
        # Check if GitHub repository creation is requested or proposed
        if task.get("create_repo") or task.get("repo_name") or "@create-repo" in task["prompt"]:
            r_name = task.get("repo_name") or task.get("project_slug") or ""
            r_desc = task.get("repo_desc") or ""
            if not r_name:
                ext_name, ext_desc = extract_repo_metadata(task.get("output", ""))
                r_name = ext_name or task.get("project_slug") or f"devos-project-{int(time.time())}"
                r_desc = r_desc or (ext_desc or "")

            ok_repo, repo_info = create_github_repo(
                repo_name=r_name,
                description=r_desc,
                project_dir=task.get("project", ""),
                push=True,
                open_browser=True,
            )
            if not ok_repo:
                task["status"] = "FAILED"
                task["output"] = (task.get("output") or "") + "\nRepository creation failed: " + repo_info
                self._save()
                return
            if ok_repo:
                task["github_url"] = repo_info
                self.context.setdefault("projects", {})[str(Path(task["project"]).resolve())] = {"github_repo": repo_info, "repo_url": repo_info, "repo_name": r_name}
                self.context["github_repo"] = repo_info
                self.context["repo_url"] = repo_info
                self.context["repo_name"] = r_name
                self._save_context()
                notify("GitHub Repo Created", f"Created & pushed: {repo_info}")

        notify("Task Completed", f"[{task['agent'].upper()}] Command finished! Ready for next in chain.")

    def check_running_tasks(self) -> bool:
        """Observe task-specific activity without approving questions or inferring success."""
        updated = False
        for task in self.queue:
            if task.get('status') not in ('RUNNING', 'SUBMITTED'):
                continue
            from pipeline_completion import read as read_completion
            report = read_completion(task)
            if report:
                task['status'] = {'completed': 'COMPLETED', 'failed': 'FAILED', 'blocked': 'SUBMITTED'}[report['status']]
                task['status_message'] = report['summary'][:600]
                task['completion_evidence'] = report
                if report['status'] == 'completed':
                    self._complete_task(task)
                self.emit_event(f"{task['id']}: agent reported {report['status']}: {report['summary'][:500]}")
                updated = True
                continue
            conv_id = task.get('conversation_id')
            if not conv_id:
                # Repair older queues whose dispatch output had the ID but dropped the field.
                output = task.get('output') or ''
                if output.startswith('STARTED:'):
                    conv_id = output.split(':', 1)[1].strip()
                elif output.startswith('SUBMITTED:'):
                    try:
                        data = json.loads(output.split(':', 1)[1])
                        conv_id = data.get('response', {}).get('newConversation', {}).get('conversationId')
                    except (ValueError, AttributeError):
                        pass
                if conv_id:
                    task['conversation_id'] = conv_id
                    updated = True
            if not conv_id or not re.fullmatch(r'[A-Za-z0-9_-]+', conv_id):
                msg = f"{task['id']}: awaiting verification; no tracked conversation. Do not resubmit until checked."
                if task.get('last_emitted_event') != msg:
                    task['last_emitted_event'] = msg
                    self.emit_event(msg)
                continue
            profile = 'antigravity-kde' if task['agent'] in ('antigravity-kde', 'antigravity-ide') else 'antigravity'
            path = Path.home()/'.gemini'/profile/'brain'/conv_id/'.system_generated/logs/transcript.jsonl'
            try:
                with path.open('rb') as stream:
                    stream.seek(max(0, path.stat().st_size-65536))
                    lines = stream.read().decode('utf-8', errors='replace').splitlines()
                last = next((json.loads(line) for line in reversed(lines) if line.strip().startswith('{') and line.strip().endswith('}')), {})
                tools = [t.get('name','') for t in last.get('tool_calls', [])]
                marker = f"{last.get('step_index', '?')}:{last.get('status', '?')}:{last.get('type', '?')}"
                if task.get('last_agent_event') != marker:
                    task['last_agent_event'] = marker
                    task['status_message'] = 'Awaiting your answer in Antigravity' if 'ask_question' in tools else f"Agent event {marker}" + (f" · {', '.join(tools)}" if tools else '')
                    msg = f"{task['id']}: {task['status_message']}"
                    if task.get('last_emitted_event') != msg:
                        task['last_emitted_event'] = msg
                        self.emit_event(msg)
                    updated = True
                elif last.get('status') == 'DONE' and last.get('type') == 'PLANNER_RESPONSE' and not tools:
                    msg_text = 'Agent response available. Verify the result, then Confirm completed.'
                    if task.get('status') != 'SUBMITTED' or task.get('status_message') != msg_text:
                        task['status'] = 'SUBMITTED'
                        task['status_message'] = msg_text
                        msg = f"{task['id']}: {msg_text}"
                        if task.get('last_emitted_event') != msg:
                            task['last_emitted_event'] = msg
                            self.emit_event(msg)
                        updated = True
                elif time.time() - path.stat().st_mtime > 120 and task.get('status') == 'RUNNING':
                    msg_text = 'No recent agent activity. Verify the conversation before continuing or resubmitting.'
                    if task.get('status') != 'SUBMITTED' or task.get('status_message') != msg_text:
                        task['status'] = 'SUBMITTED'
                        task['status_message'] = msg_text
                        msg = f"{task['id']}: {msg_text}"
                        if task.get('last_emitted_event') != msg:
                            task['last_emitted_event'] = msg
                            self.emit_event(msg)
                        updated = True
            except (OSError, ValueError):
                msg = f"{task['id']}: conversation submitted; waiting for agent activity."
                if task.get('last_emitted_event') != msg:
                    task['last_emitted_event'] = msg
                    self.emit_event(msg)
        if updated:
            self._save()
        return updated

    @queue_transaction
    def observe_tasks(self) -> bool:
        """Refresh accepted conversations without dispatching queued work."""
        return self.check_running_tasks()

    @staticmethod
    def agent_slot(agent):
        return {'codex': 'chatgpt', 'antigravity-ide': 'antigravity-kde'}.get(agent, agent)

    def _run_claimed(self, task):
        dispatched = dict(task)
        dispatched['prompt'] = task['resolved_prompt']
        try:
            success, output = self._dispatch(dispatched)
        except Exception as exc:
            success, output = False, str(exc)
        # Dispatch runs outside the queue lock. Merge only this task's result.
        for attempt in range(100):
            try:
                return self._finish_dispatch(dispatched, success, output)
            except RuntimeError as exc:
                if 'Another pipeline command' not in str(exc):
                    raise
                time.sleep(.05)
        self.emit_event(f"{task['id']}: result pending; queue busy. Verify completion before retrying.")
        return False

    def execute_next(self):
        task = self._claim_next()
        return self._run_claimed(task) if task else False

    def execute_parallel_tick(self, limit=2):
        self.observe_tasks()
        self._dispatch_threads = [t for t in self._dispatch_threads if t.is_alive()]
        started = False
        for _ in range(limit):
            task = self._claim_next(parallel=True, limit=limit)
            if not task:
                break
            worker = TaskPipeline(self.state_file, self.context_file)
            worker.event_callback = self.event_callback
            thread = threading.Thread(target=worker._run_claimed, args=(task,),
                                      name='pipeline-' + task['id'], daemon=False)
            self._dispatch_threads.append(thread)
            thread.start()
            started = True
        return started

    @queue_transaction
    def _claim_next(self, parallel=False, limit=2):
        """Finds next eligible task and executes it."""
        self.check_running_tasks()
        now = datetime.datetime.now()
        active = [t for t in self.queue if t['status'] in ('RUNNING', 'SUBMITTED')]
        if parallel and len(active) >= limit:
            return None
        busy_agents = {self.agent_slot(t['agent']) for t in active}
        blocked_projects = set()
        for task in self.queue:
            if task["status"] == "COMPLETED":
                continue
            project_key = str(Path(task.get('project') or (Path(self.get_base_dir()) / task.get('project_slug', 'project'))).resolve())
            if parallel and project_key in blocked_projects:
                continue
            blocked_projects.add(project_key)
            unavailable = (
                task['status'] in ('FAILED', 'RUNNING', 'SUBMITTED')
                or now < datetime.datetime.fromisoformat(task['run_at'])
                or (task.get('retry_at') and now < datetime.datetime.fromisoformat(task['retry_at']))
                or (parallel and self.agent_slot(task['agent']) in busy_agents)
            )
            if unavailable:
                if parallel:
                    continue
                return None

            # Ensure project slug and local folder are created
            p_slug = task.get("project_slug") or to_slug(task.get("project_title") or "project")
            task["project_slug"] = p_slug

            project_path = task.get("project")
            if not project_path:
                base = self.get_base_dir()
                project_path = str(Path(base) / p_slug)
                task["project"] = project_path

            # Auto-create the project folder if it does not exist
            try:
                proj_dir = Path(project_path).resolve()
                proj_dir.mkdir(parents=True, exist_ok=True)
                task["project"] = str(proj_dir)
            except Exception as e:
                task["status"] = "FAILED"
                task["output"] = f"Failed to auto-create project directory '{project_path}': {e}"
                self._save()
                return None

            # Resolve context variables in prompt: e.g. {github_repo}, {repo_url}, {repo_name}, {project_dir}, {project_slug}
            resolved_prompt = task["prompt"]
            context_vars = dict(self.context)
            if parallel:
                for key in ('github_repo', 'repo_url', 'repo_name'):
                    context_vars.pop(key, None)
                context_vars.update(self.context.get('projects', {}).get(str(proj_dir), {}))
            context_vars["project_dir"] = str(proj_dir)
            context_vars["project_slug"] = p_slug
            for k, v in context_vars.items():
                resolved_prompt = resolved_prompt.replace(f"{{{k}}}", str(v))

            # Prepend strict workspace directive so the agent never confuses the active IDE workspace with the target project directory
            ws_directive = (
                f"================================================================================\n"
                f"[MANDATORY TARGET PROJECT DIRECTORY: {proj_dir}]\n"
                f"You MUST create, initialize, build, and write all project files, directories, code,\n"
                f"and configurations directly inside:\n"
                f"{proj_dir}\n\n"
                f"DO NOT create or modify files in any other workspace (such as dev-os).\n"
                f"All shell commands (composer, artisan, npm, git, etc.) must be executed with\n"
                f"working directory inside: {proj_dir}\n"
                f"Ask for clarification if required information or authorization is missing.\n"
                f"================================================================================\n\n"
            )
            if not resolved_prompt.startswith("================================================================================"):
                resolved_prompt = ws_directive + resolved_prompt

            if task['agent'] in ('antigravity', 'antigravity-kde', 'antigravity-ide'):
                from pipeline_completion import prepare as prepare_completion
                resolved_prompt += prepare_completion(task)

            task["resolved_prompt"] = resolved_prompt
            self.emit_event(f"Project folder ready: {proj_dir}")

            # If target agent is currently busy doing work, wait for current turn to complete
            if is_agent_working(task["agent"]):
                self.emit_event(f"{task['agent']}: another turn is active; waiting before submission.")
                if parallel:
                    continue
                return None

            # Run this task
            task["status"] = "RUNNING"
            task["started_at"] = datetime.datetime.now().isoformat()
            self.emit_event(f"{task['id']}: dispatching to {task['agent']}…")
            self._save()
            notify("Executing Task", f"[{p_slug}] [{task['agent'].upper()}] {resolved_prompt[:60]}...")

            return dict(task)
        return None

    @queue_transaction
    def _finish_dispatch(self, dispatched, success, output):
        task = next((t for t in self.queue if t['id'] == dispatched['id']), None)
        if not task or task.get('status') != 'RUNNING':
            return False
        task_dispatch = dispatched
        p_slug = task.get('project_slug', 'project')
        now = datetime.datetime.now()
        output = str(output)[-65536:]
        task["status_message"] = output[:600]
        task["output"] = output

        if output.startswith("STARTED:"):
            task["conversation_id"] = task_dispatch.get("conversation_id") or output.split(":", 1)[1].strip()
            task["status"] = "RUNNING"
            self.emit_event(f"{task['id']}: prompt accepted; tracking conversation {task['conversation_id']}.")
            self._save()
            notify("Task Running", f"[{p_slug}] [{task['agent'].upper()}] Task is running in background.")
            return True

        if output.startswith("SUBMITTED:"):
            task["status"] = "SUBMITTED"
            self._save()
            notify("Task submitted", "Waiting for verified agent completion before the next task.")
            return True

        # Check if rate-limited
        if not success and ("rate limit" in output.lower() or "usage to reset" in output.lower()):
            reset_target = parse_reset_time(output)
            if not reset_target:
                # Default 5 min cooldown if time not explicitly specified
                reset_target = now + datetime.timedelta(minutes=5)

            task["status"] = "RATE_LIMITED"
            task["retry_at"] = reset_target.isoformat()
            self._save()

            reset_str = reset_target.strftime("%I:%M %p")
            notify(
                "Rate Limit Reached",
                f"{task['agent'].upper()} is paused. Cooldown expires at {reset_str}. Auto-resuming then!",
                urgency="critical"
            )
            print(f"--> Rate limit detected! Scheduled auto-resume for {reset_str}")
            return True

        if success:
            self._complete_task(task)
        else:
            task["status"] = "FAILED"
            self.emit_event(f"{task['id']}: failed: {output[:1000]}")
            notify("Task Failed", f"[{task['agent'].upper()}] Error: {output[:80]}", urgency="critical")

        self._save()
        return True

    def _dispatch(self, task: Dict[str, Any]) -> tuple[bool, str]:
        agent = task["agent"]
        prompt = task["prompt"]

        if agent in ("antigravity", "antigravity-kde", "antigravity-ide"):
            kde = agent != "antigravity"
            api_bin = Path.home()/".gemini/antigravity-kde/bin/agentapi" if kde else AGENTAPI_BIN
            if not api_bin.exists() and kde:
                agy_bin = Path.home()/".gemini/bin/agy"
                if agy_bin.exists():
                    try:
                        api_bin.parent.mkdir(parents=True, exist_ok=True)
                        api_bin.write_text(f'#!/bin/sh\nexec "{agy_bin}" agentapi "$@"\n')
                        api_bin.chmod(0o755)
                    except Exception:
                        pass
            if api_bin.exists():
                title = f"[Pipeline] {task.get('project_slug') or 'Project'}"
                proj_path = task.get("project")
                if proj_path:
                    try:
                        launcher = (Path.home() / ".local/bin/antigravity-kde") if kde else Path("/opt/antigravity/antigravity")
                        if launcher.is_file():
                            cmd = [str(launcher), "--new-window", str(proj_path)] if kde else [str(launcher), str(proj_path)]
                            clean_env = dict(os.environ)
                            clean_env.pop("ELECTRON_RUN_AS_NODE", None)
                            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=clean_env)
                    except Exception:
                        pass
                cmd = [str(api_bin), "new-conversation", f"--title={title}", "--", prompt]
                try:
                    import importlib
                    import antigravity_connection
                    importlib.reload(antigravity_connection)
                    ensure_connection = antigravity_connection.ensure_connection
                    bind_project = antigravity_connection.bind_project
                    connection_environment = antigravity_connection.connection_environment
                    connection = ensure_connection(task.get("project"), self.emit_event, profile="antigravity-kde") if kde else ensure_connection(task.get("project"), self.emit_event)
                    if kde:
                        primary = connection_environment("antigravity")
                        if primary and primary.get('ANTIGRAVITY_LS_ADDRESS') == connection.get('ANTIGRAVITY_LS_ADDRESS'):
                            return False, "Antigravity KDE must use a different API endpoint from Google Antigravity; no prompt was sent."
                    env = bind_project(connection, task["project"])
                    self.emit_event("Antigravity API ready; submitting the project prompt…")
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=task.get("project") or None, env=env)
                    if res.returncode == 0:
                        conv_id = None
                        try:
                            data = json.loads(res.stdout)
                            conv_id = data.get("response", {}).get("newConversation", {}).get("conversationId")
                        except Exception:
                            pass
                        if conv_id:
                            task["conversation_id"] = conv_id
                            try:
                                set_workspace_last_conversation = getattr(antigravity_connection, "set_workspace_last_conversation", None)
                                if set_workspace_last_conversation and task.get("project"):
                                    set_workspace_last_conversation(task["project"], conv_id, profile="antigravity-kde" if kde else "antigravity")
                            except Exception:
                                pass
                            return True, f"STARTED:{conv_id}"
                        return False, "SUBMITTED: Antigravity accepted the request without a conversation ID; verify it in the agent before retrying."
                    return False, res.stderr or res.stdout
                except subprocess.TimeoutExpired:
                    return False, "SUBMITTED: Antigravity submission timed out; acceptance is uncertain. Check the agent before retrying."
                except Exception as e:
                    return False, str(e)
            else:
                return False, "Antigravity CLI (agentapi) not found"

        elif agent in ("chatgpt", "codex"):
            # Process exit gives an observable result. Desktop idle heuristics
            # cannot establish whether a particular task succeeded.
            codex_bin = discover_agents().get("chatgpt", {}).get("bin")
            if not codex_bin:
                return False, "Codex CLI is not installed. Install and sign in before running this task."
            try:
                res = subprocess.run([str(codex_bin), "exec", prompt], capture_output=True, text=True, timeout=3600, cwd=task.get("project") or None)
                return res.returncode == 0, res.stdout or res.stderr
            except Exception as exc:
                return False, f"Codex CLI error: {exc}"

        elif agent == "local":
            worker = Path(__file__).resolve().parent.parent / "code-agent/pipeline_worker.py"
            if not worker.is_file():
                return False, "DevOS coding engine is missing; reinstall the code-agent component."
            self.emit_event("Starting DevOS coding engine in the project workspace…")
            # Prompts go through stdin, not command-line arguments or repository files.
            with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as prompt_file:
                prompt_file.write(prompt)
                prompt_file.seek(0)
                proc = subprocess.Popen(
                    [sys.executable, "-u", str(worker), "--project", task["project"]],
                    stdin=prompt_file, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, cwd=task["project"],
                )
                output = ""
                for line in proc.stdout:
                    output = (output + line)[-65536:]
                    try:
                        event = json.loads(line)
                        if event.get("event") == "thinking_status":
                            detail = event.get("detail", {})
                            self.emit_event(str(detail.get("status", detail))[:500])
                        elif "result" in event:
                            self.emit_event("DevOS coding engine: " + event["result"]["status"])
                    except (ValueError, AttributeError, TypeError):
                        pass
                return proc.wait() == 0, output

        known_agents = discover_agents()

        # Claude Code
        if agent == "claude":
            bin_path = known_agents.get("claude", {}).get("bin") or shutil.which("claude")
            if bin_path:
                try:
                    res = subprocess.run([bin_path, "-p", prompt], capture_output=True, text=True, timeout=3600, cwd=task.get("project") or None)
                    return res.returncode == 0, res.stdout or res.stderr
                except Exception as e:
                    return False, f"Claude CLI error: {e}"
            return False, "Claude CLI (claude) not installed"

        # Aider Pair Programmer
        elif agent == "aider":
            bin_path = known_agents.get("aider", {}).get("bin") or shutil.which("aider")
            if bin_path:
                try:
                    res = subprocess.run([bin_path, "--message", prompt, "--no-auto-commits"], capture_output=True, text=True, timeout=3600, cwd=task.get("project") or None)
                    return res.returncode == 0, res.stdout or res.stderr
                except Exception as e:
                    return False, f"Aider CLI error: {e}"
            return False, "Aider CLI (aider) not installed"

        # Custom agent scripts in ~/.config/devos/agents/
        if agent in known_agents and known_agents[agent].get("bin"):
            bin_path = known_agents[agent]["bin"]
            try:
                if bin_path.endswith(".py"):
                    cmd = [sys.executable, bin_path, prompt]
                else:
                    cmd = [bin_path, prompt]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=3600, cwd=task.get("project") or None)
                return res.returncode == 0, res.stdout or res.stderr
            except Exception as e:
                return False, f"Custom agent '{agent}' error: {e}"

        # Universal fallback: any CLI tool on PATH
        generic_bin = shutil.which(agent)
        if generic_bin:
            try:
                res = subprocess.run([generic_bin, prompt], capture_output=True, text=True, timeout=3600, cwd=task.get("project") or None)
                return res.returncode == 0, res.stdout or res.stderr
            except Exception as e:
                return False, f"Agent '{agent}' execution error: {e}"

        return False, f"Unknown agent: {agent}"


def main():
    if len(sys.argv) == 1 and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        # Launch Visual GUI when invoked without arguments on desktop
        import pipeline_gui
        pipeline_gui.main()
        return

    parser = argparse.ArgumentParser(description="DevOS AI Task Pipeline & Rate-Limit Scheduler")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("gui", help="Open Visual Pipeline & Scheduler Dashboard")
    add_p = sub.add_parser("add", help="Add command to pipeline")
    add_p.add_argument("prompt", help="Command or prompt to execute")
    add_p.add_argument("--agent", default="antigravity", help="Target AI agent")
    add_p.add_argument("--project", default="", help="Project path or context")
    add_p.add_argument("--title", default="", help="Project title (auto-converts to slug)")
    add_p.add_argument("--slug", default="", help="Project folder slug")
    add_p.add_argument("--base-dir", default="", help="Base directory for project creation")
    add_p.add_argument("--delay", type=int, default=0, help="Delay in seconds before running")
    add_p.add_argument("--create-repo", action="store_true", help="Auto-create GitHub repo and push")
    add_p.add_argument("--repo-name", default="", help="GitHub repository name")
    add_p.add_argument("--repo-desc", default="", help="GitHub repository description")

    sub.add_parser("list", help="List all queued and running commands")
    sub.add_parser("run", help="Run the pipeline loop until all tasks complete")
    sub.add_parser("clear", help="Clear the pipeline queue")
    base_p = sub.add_parser("set-base-dir", help="Configure base directory for project folders")
    base_p.add_argument("directory", help="Absolute path to base directory")

    args = parser.parse_args()
    pipeline = TaskPipeline()

    if args.cmd == "gui":
        import pipeline_gui
        pipeline_gui.main()
        return

    elif args.cmd == "set-base-dir":
        configured = pipeline.set_base_dir(args.directory)
        print(f"Projects base directory set to: {configured}")

    elif args.cmd == "add":
        if args.base_dir:
            pipeline.set_base_dir(args.base_dir)
        tid = pipeline.add(
            args.prompt,
            agent=args.agent,
            project=args.project,
            delay_seconds=args.delay,
            create_repo=args.create_repo,
            repo_name=args.repo_name,
            repo_desc=args.repo_desc,
            project_title=args.title,
            project_slug=args.slug,
        )
        print(f"Task queued: {tid} [{args.agent.upper()}] -> '{args.prompt}'")

    elif args.cmd == "list":
        tasks = pipeline.list()
        if not tasks:
            print("AI Task Pipeline is currently empty.")
            return
        print(f"{'PROJECT':<25} {'ID':<18} {'AGENT':<12} {'STATUS':<15} PROMPT")
        print("-" * 90)
        for t in tasks:
            slug = t.get("project_slug", "default")
            print(f"{slug:<25} {t['id']:<18} {t['agent'].upper():<12} {t['status']:<15} {t['prompt'][:35]}")

    elif args.cmd == "run":
        print("DevOS AI Task Pipeline Runner starting...")
        while True:
            has_more = pipeline.execute_next()
            if not has_more:
                # Check if any tasks are rate limited
                rate_limited = [t for t in pipeline.list() if t["status"] == "RATE_LIMITED"]
                pending = [t for t in pipeline.list() if t["status"] not in ("COMPLETED", "FAILED")]
                if pending and any(t["status"] == "FAILED" for t in pipeline.list()):
                    print("Pipeline paused after a failed task; later tasks have not run.")
                    break
                if any(t["status"] in ("RUNNING", "SUBMITTED") for t in pending):
                    print("Pipeline paused: awaiting verified agent completion.")
                    break
                if not pending:
                    failed = any(t["status"] == "FAILED" for t in pipeline.list())
                    print("Pipeline finished with failed tasks." if failed else "All tasks completed successfully.")
                    break
            time.sleep(2)

    elif args.cmd == "clear":
        pipeline.clear()
        print("Cleared AI Task Pipeline.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
