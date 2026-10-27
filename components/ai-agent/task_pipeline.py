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
import uuid
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

STATE_FILE = Path(os.path.expanduser("~/.local/share/devos/ai-pipeline.json"))
CONTEXT_FILE = Path(os.path.expanduser("~/.local/share/devos/ai-pipeline-context.json"))
AGENTAPI_BIN = Path(os.path.expanduser("~/.gemini/antigravity/bin/agentapi"))
CUSTOM_AGENTS_DIR = Path.expanduser(Path("~/.config/devos/agents"))


def discover_agents() -> Dict[str, Dict[str, Any]]:
    """Auto-detects available AI agents on the system and in custom directories."""
    agents = {}

    # 1. Google Antigravity
    ag_bin = shutil.which("antigravity") or AGENTAPI_BIN
    ag_ok = bool(ag_bin and Path(ag_bin).exists())
    agents["antigravity"] = {
        "name": "Google Antigravity",
        "bin": str(ag_bin) if ag_ok else None,
        "color": "#2563eb",
        "available": ag_ok,
    }

    # 1b. Google Antigravity IDE (KDE GUI)
    ag_ide_bin = shutil.which("antigravity") or Path("/opt/antigravity/antigravity")
    ag_ide_ok = bool(ag_ide_bin and Path(ag_ide_bin).exists())
    agents["antigravity-ide"] = {
        "name": "Google Antigravity IDE",
        "bin": str(ag_ide_bin) if ag_ide_ok else None,
        "color": "#4f46e5",
        "available": ag_ide_ok,
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
        "available": bool(codex_bin),
    }

    # 3. Claude Code CLI
    claude_bin = shutil.which("claude")
    agents["claude"] = {
        "name": "Claude Code",
        "bin": claude_bin,
        "color": "#d97706",
        "available": bool(claude_bin),
    }

    # 4. Aider Multi-Model Pair Programmer
    aider_bin = shutil.which("aider")
    agents["aider"] = {
        "name": "Aider Pair Programmer",
        "bin": aider_bin,
        "color": "#059669",
        "available": bool(aider_bin),
    }

    # 5. DevOS Local AI / Ollama
    ollama_bin = shutil.which("ollama")
    agents["local"] = {
        "name": "DevOS Local AI",
        "bin": ollama_bin,
        "color": "#7c3aed",
        "available": True,
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
            }

    return agents


def notify(title: str, message: str, urgency: str = "normal"):
    """Sends native desktop notification."""
    try:
        subprocess.run(
            ["notify-send", "-a", "DevOS AI Pipeline", "-u", urgency, title, message],
            check=False,
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


def is_antigravity_working() -> bool:
    """Checks if any Antigravity conversation is currently executing a turn or tool."""
    brain_dir = Path.home() / ".gemini/antigravity/brain"
    if not brain_dir.exists():
        return False
    transcripts = list(brain_dir.glob("*/.system_generated/logs/transcript.jsonl"))
    if not transcripts:
        return False
    latest = max(transcripts, key=os.path.getmtime)
    try:
        with open(latest, "r", encoding="utf-8") as f:
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
    ag = agent.lower()
    if ag == "antigravity":
        return is_antigravity_working()
    elif ag == "antigravity-ide":
        res = subprocess.run(["pgrep", "-f", "/opt/antigravity/antigravity"], capture_output=True)
        return res.returncode == 0
    elif ag in ("chatgpt", "codex"):
        return is_codex_working()
    elif ag == "local":
        res = subprocess.run(["pgrep", "-f", "devos-ai-code|ollama_llama_server"], capture_output=True)
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
                if method.__name__ == "execute_next":
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
        self.state_file = state_file
        self.context_file = context_file
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.queue: List[Dict[str, Any]] = self._load()
        self.context: Dict[str, Any] = self._load_context()

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
    ) -> str:
        task_id = "task_" + uuid.uuid4().hex[:16]
        run_at = (datetime.datetime.now() + datetime.timedelta(seconds=delay_seconds)).isoformat()
        item = {
            "id": task_id,
            "prompt": prompt,
            "agent": agent.lower(),  # "chatgpt", "antigravity", "local"
            "project": project,
            "status": "QUEUED",      # QUEUED, RUNNING, RATE_LIMITED, COMPLETED, FAILED
            "run_at": run_at,
            "retry_at": None,
            "created_at": datetime.datetime.now().isoformat(),
            "output": None,
            "create_repo": create_repo,
            "repo_name": repo_name,
            "repo_desc": repo_desc,
            "github_url": None,
        }
        self.queue.append(item)
        self._save()
        notify("Task Queued", f"[{agent.upper()}] {prompt[:60]}...")
        return task_id

    def list(self) -> List[Dict[str, Any]]:
        return self.queue

    @queue_transaction
    def update_task(self, task_id, changes):
        for task in self.queue:
            if task["id"] == task_id:
                task.update(changes)
                self._save()
                return
        raise ValueError("Task no longer exists")

    @queue_transaction
    def clear(self):
        self.queue = []
        self._save()

    @queue_transaction
    def execute_next(self) -> bool:
        """Finds next eligible task and executes it."""
        now = datetime.datetime.now()
        for task in self.queue:
            if task["status"] == "COMPLETED":
                continue
            if task["status"] == "FAILED":
                return False

            if task["status"] in ("RUNNING", "SUBMITTED"):
                return False  # no proof of completion; never redispatch after a crash
            if now < datetime.datetime.fromisoformat(task["run_at"]):
                return False  # ordered chain: later tasks cannot overtake this one

            # Check if delayed or rate-limited with scheduled wakeup
            if task["retry_at"]:
                retry_time = datetime.datetime.fromisoformat(task["retry_at"])
                if now < retry_time:
                    remaining = int((retry_time - now).total_seconds())
                    print(f"[Rate-Limited] {task['id']} ({task['agent']}) waiting until {retry_time.strftime('%I:%M %p')} ({remaining}s remaining)")
                    return False

            # Resolve context variables in prompt: e.g. {github_repo}, {repo_url}, {repo_name}
            resolved_prompt = task["prompt"]
            for k, v in self.context.items():
                resolved_prompt = resolved_prompt.replace(f"{{{k}}}", str(v))
            task["resolved_prompt"] = resolved_prompt

            # If target agent is currently busy doing work, wait for current turn to complete
            if is_agent_working(task["agent"]):
                print(f"[{task['agent'].upper()}] Agent is currently working. Waiting for turn to finish before dispatching...")
                return False

            # Run this task
            task["status"] = "RUNNING"
            self._save()
            notify("Executing Task", f"[{task['agent'].upper()}] Starting command: {resolved_prompt[:60]}...")

            task_dispatch = dict(task)
            task_dispatch["prompt"] = resolved_prompt
            try:
                success, output = self._dispatch(task_dispatch)
            except Exception as exc:
                success, output = False, str(exc)
            output = str(output)[-65536:]
            task["output"] = output

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
                task["status"] = "COMPLETED"
                # Check if GitHub repository creation is requested or proposed
                if task.get("create_repo") or task.get("repo_name") or "@create-repo" in task["prompt"]:
                    r_name = task.get("repo_name") or ""
                    r_desc = task.get("repo_desc") or ""
                    if not r_name:
                        ext_name, ext_desc = extract_repo_metadata(output)
                        r_name = ext_name or f"devos-project-{int(time.time())}"
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
                        task["output"] += "\nRepository creation failed: " + repo_info
                        self._save()
                        return True
                    if ok_repo:
                        task["github_url"] = repo_info
                        self.context["github_repo"] = repo_info
                        self.context["repo_url"] = repo_info
                        self.context["repo_name"] = r_name
                        self._save_context()
                        notify("GitHub Repo Created", f"Created & pushed: {repo_info}")
                
                notify("Task Completed", f"[{task['agent'].upper()}] Command finished! Ready for next in chain.")
            else:
                task["status"] = "FAILED"
                notify("Task Failed", f"[{task['agent'].upper()}] Error: {output[:80]}", urgency="critical")

            self._save()
            return True

        return False

    def _dispatch(self, task: Dict[str, Any]) -> tuple[bool, str]:
        agent = task["agent"]
        prompt = task["prompt"]

        if agent == "antigravity":
            if AGENTAPI_BIN.exists():
                cmd = [str(AGENTAPI_BIN), "new-conversation", prompt]
                try:
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=task.get("project") or None)
                    if res.returncode == 0:
                        return False, "SUBMITTED: " + (res.stdout or "Antigravity accepted the conversation; completion is not verified.")
                    return False, res.stderr or res.stdout
                except Exception as e:
                    return False, str(e)
            else:
                return False, "Antigravity CLI (agentapi) not found"

        elif agent == "antigravity-ide":
            ide_bin = discover_agents().get("antigravity-ide", {}).get("bin")
            if not ide_bin:
                return False, "Google Antigravity IDE not found"
            try:
                target_dir = task.get("project") or str(Path.cwd())
                subprocess.Popen([str(ide_bin), target_dir], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, f"Opened Antigravity IDE in workspace: {target_dir}"
            except Exception as e:
                return False, str(e)

        elif agent in ("chatgpt", "codex"):
            # Process exit gives an observable result. Desktop idle heuristics
            # cannot establish whether a particular task succeeded.
            codex_bin = discover_agents().get("chatgpt", {}).get("bin")
            if not codex_bin:
                return False, "Codex CLI is not installed. Install and sign in before running this task."
            try:
                res = subprocess.run([str(codex_bin), "exec", prompt], capture_output=True, text=True, timeout=300, cwd=task.get("project") or None)
                return res.returncode == 0, res.stdout or res.stderr
            except Exception as exc:
                return False, f"Codex CLI error: {exc}"

        elif agent == "local":
            # Local DevOS AI engine
            try:
                import urllib.request
                req_data = json.dumps({
                    "model": "devos-ai-code",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1000
                }).encode("utf-8")
                req = urllib.request.Request(
                    "http://127.0.0.1:11434/v1/chat/completions",
                    data=req_data,
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = json.loads(resp.read().decode())
                    content = data["choices"][0]["message"]["content"]
                    return True, content
            except Exception as e:
                return False, f"Local AI Error: {e}"

        known_agents = discover_agents()

        # Claude Code
        if agent == "claude":
            bin_path = known_agents.get("claude", {}).get("bin") or shutil.which("claude")
            if bin_path:
                try:
                    res = subprocess.run([bin_path, "-p", prompt], capture_output=True, text=True, timeout=300, cwd=task.get("project") or None)
                    return res.returncode == 0, res.stdout or res.stderr
                except Exception as e:
                    return False, f"Claude CLI error: {e}"
            return False, "Claude CLI (claude) not installed"

        # Aider Pair Programmer
        elif agent == "aider":
            bin_path = known_agents.get("aider", {}).get("bin") or shutil.which("aider")
            if bin_path:
                try:
                    res = subprocess.run([bin_path, "--message", prompt, "--no-auto-commits"], capture_output=True, text=True, timeout=300, cwd=task.get("project") or None)
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
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=task.get("project") or None)
                return res.returncode == 0, res.stdout or res.stderr
            except Exception as e:
                return False, f"Custom agent '{agent}' error: {e}"

        # Universal fallback: any CLI tool on PATH
        generic_bin = shutil.which(agent)
        if generic_bin:
            try:
                res = subprocess.run([generic_bin, prompt], capture_output=True, text=True, timeout=300, cwd=task.get("project") or None)
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
    add_p.add_argument("--agent", choices=["chatgpt", "antigravity", "local"], default="antigravity", help="Target AI agent")
    add_p.add_argument("--project", default="", help="Project path or context")
    add_p.add_argument("--delay", type=int, default=0, help="Delay in seconds before running")
    add_p.add_argument("--create-repo", action="store_true", help="Auto-create GitHub repo and push")
    add_p.add_argument("--repo-name", default="", help="GitHub repository name")
    add_p.add_argument("--repo-desc", default="", help="GitHub repository description")

    sub.add_parser("list", help="List all queued and running commands")
    sub.add_parser("run", help="Run the pipeline loop until all tasks complete")
    sub.add_parser("clear", help="Clear the pipeline queue")

    args = parser.parse_args()
    pipeline = TaskPipeline()

    if args.cmd == "gui":
        import pipeline_gui
        pipeline_gui.main()
        return

    elif args.cmd == "add":
        tid = pipeline.add(
            args.prompt,
            agent=args.agent,
            project=args.project,
            delay_seconds=args.delay,
            create_repo=args.create_repo,
            repo_name=args.repo_name,
            repo_desc=args.repo_desc,
        )
        print(f"Task queued: {tid} [{args.agent.upper()}] -> '{args.prompt}'")

    elif args.cmd == "list":
        tasks = pipeline.list()
        if not tasks:
            print("AI Task Pipeline is currently empty.")
            return
        print(f"{'ID':<18} {'AGENT':<12} {'STATUS':<15} {'SCHEDULED / RETRY':<20} PROMPT")
        print("-" * 80)
        for t in tasks:
            sched = t["retry_at"] or t["run_at"]
            print(f"{t['id']:<18} {t['agent'].upper():<12} {t['status']:<15} {sched[:19]:<20} {t['prompt'][:30]}")

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
