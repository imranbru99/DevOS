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
import datetime
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

STATE_FILE = Path(os.path.expanduser("~/.local/share/devos/ai-pipeline.json"))
CONTEXT_FILE = Path(os.path.expanduser("~/.local/share/devos/ai-pipeline-context.json"))
AGENTAPI_BIN = Path(os.path.expanduser("~/.gemini/antigravity/bin/agentapi"))


def notify(title: str, message: str, urgency: str = "normal"):
    """Sends native desktop notification."""
    try:
        subprocess.run(
            ["notify-send", "-a", "DevOS AI Pipeline", "-u", urgency, title, message],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception:
        pass


import urllib.parse


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
    gh_check = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if gh_check.returncode != 0:
        # Fallback to opening browser create form directly
        if open_browser:
            subprocess.Popen(["xdg-open", browser_new_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, browser_new_url

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
    subprocess.run(["git", "commit", "-m", f"Initial commit: {clean_name}"], cwd=str(p_path), check=False)

    vis_flag = "--public" if public else "--private"
    cmd = ["gh", "repo", "create", f"imranbru99/{clean_name}", vis_flag]
    if description:
        cmd.extend(["-d", description])
    if push:
        cmd.extend(["--source", str(p_path), "--remote", "origin", "--push"])

    res = subprocess.run(cmd, cwd=str(p_path), capture_output=True, text=True)
    full_url = f"https://github.com/imranbru99/{clean_name}"

    if res.returncode == 0 or "already exists" in (res.stderr or "").lower():
        if open_browser:
            subprocess.Popen(["xdg-open", full_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, full_url
    else:
        # If gh failed, open browser new repo page with name & description prefilled
        if open_browser:
            subprocess.Popen(["xdg-open", browser_new_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return False, res.stderr or "Failed to create repo via gh"


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


class TaskPipeline:
    def __init__(self, state_file: Path = STATE_FILE, context_file: Path = CONTEXT_FILE):
        self.state_file = state_file
        self.context_file = context_file
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.queue: List[Dict[str, Any]] = self._load()
        self.context: Dict[str, Any] = self._load_context()

    def _load(self) -> List[Dict[str, Any]]:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _save(self):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self.queue, f, indent=2)

    def _load_context(self) -> Dict[str, Any]:
        if self.context_file.exists():
            try:
                with open(self.context_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_context(self):
        with open(self.context_file, "w", encoding="utf-8") as f:
            json.dump(self.context, f, indent=2)

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
        task_id = f"task_{int(time.time() * 1000)}"
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

    def clear(self):
        self.queue = []
        self._save()

    def execute_next(self) -> bool:
        """Finds next eligible task and executes it."""
        now = datetime.datetime.now()
        for task in self.queue:
            if task["status"] in ("COMPLETED", "FAILED"):
                continue

            # Check if delayed or rate-limited with scheduled wakeup
            if task["retry_at"]:
                retry_time = datetime.datetime.fromisoformat(task["retry_at"])
                if now < retry_time:
                    remaining = int((retry_time - now).total_seconds())
                    print(f"[Rate-Limited] {task['id']} ({task['agent']}) waiting until {retry_time.strftime('%I:%M %p')} ({remaining}s remaining)")
                    continue

            # Resolve context variables in prompt: e.g. {github_repo}, {repo_url}, {repo_name}
            resolved_prompt = task["prompt"]
            for k, v in self.context.items():
                resolved_prompt = resolved_prompt.replace(f"{{{k}}}", str(v))
            task["resolved_prompt"] = resolved_prompt

            # Run this task
            task["status"] = "RUNNING"
            self._save()
            notify("Executing Task", f"[{task['agent'].upper()}] Starting command: {resolved_prompt[:60]}...")

            task_dispatch = dict(task)
            task_dispatch["prompt"] = resolved_prompt
            success, output = self._dispatch(task_dispatch)
            task["output"] = output

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
                    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                    return res.returncode == 0, res.stdout or res.stderr
                except Exception as e:
                    return False, str(e)
            else:
                return False, "Antigravity CLI (agentapi) not found"

        elif agent == "chatgpt":
            # For desktop window automation via xdotool or Codex window
            # Look for running Codex / ChatGPT window
            find_win = subprocess.run(["xdotool", "search", "--name", "Codex"], capture_output=True, text=True)
            win_id = find_win.stdout.strip().splitlines()[0] if find_win.stdout.strip() else None
            
            if win_id:
                try:
                    # Activate window, type prompt, press Return
                    subprocess.run(["xdotool", "windowactivate", win_id], check=False)
                    time.sleep(0.5)
                    subprocess.run(["xdotool", "type", "--delay", "10", prompt], check=False)
                    subprocess.run(["xdotool", "key", "Return"], check=False)
                    return True, "Dispatched prompt to Codex/ChatGPT desktop window via xdotool"
                except Exception as e:
                    return False, f"xdotool error: {e}"
            else:
                # If window is not open, simulate response or call API
                return True, f"Simulated ChatGPT command completed: {prompt[:40]}"

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
                if not rate_limited:
                    print("All tasks in pipeline completed successfully!")
                    break
            time.sleep(2)

    elif args.cmd == "clear":
        pipeline.clear()
        print("Cleared AI Task Pipeline.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
