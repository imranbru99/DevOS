#!/usr/bin/env python3
"""
Automations that call the DevOS AI model on this PC.

  devos auto ask "Where does the AI service start?"
  devos auto commit                 subject line from the staged diff
  devos auto review                 short review of that diff
  devos auto explain                explain the error on stdin
  devos auto summarize FILE
  devos auto hook                   fill empty commit messages from the model
  devos auto hook remove
  devos auto docs

Nothing here commits, pushes or runs a command. The model is the local
OpenAI-compatible API (http://127.0.0.1:11434). See API.md.
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request


AI_URL = os.environ.get("DEVOS_AI_URL", "http://127.0.0.1:11434/v1/chat/completions")
DOCS_URL = "http://127.0.0.1:11434/docs"
DIFF_LIMIT = 8000
HOOK_MARK = "# DevOS Local AI hook"

JOBS = {
    "commit": {
        "model": "devos-ai-code",
        "temperature": 0.2,
        "max_tokens": 60,
        "system": (
            "You write git commit subjects. Reply with one line, under 72 characters, "
            "imperative mood. No quotes, no prefix, no explanation."
        ),
        "user": "Diff:\n{body}",
    },
    "review": {
        "model": "devos-ai-code",
        "temperature": 0.2,
        "max_tokens": 400,
        "system": (
            "You review a code diff. Reply with at most 6 short bullets: real bugs, "
            "missing checks, or a risky change. If the diff looks fine, say so in one line. "
            "Do not rewrite the code."
        ),
        "user": "Diff:\n{body}",
    },
    "explain": {
        "model": "devos-ai",
        "temperature": 0.2,
        "max_tokens": 320,
        "system": (
            "You explain an error from the user's computer. Say what failed and the most "
            "likely cause, in a few short sentences. Do not invent file paths that are not in the text."
        ),
        "user": "Error:\n{body}",
    },
    "summarize": {
        "model": "devos-ai",
        "temperature": 0.2,
        "max_tokens": 280,
        "system": "Summarize the text in 3 to 5 short bullets. Keep the language of the text.",
        "user": "Text:\n{body}",
    },
    "ask": {
        "model": "devos-ai",
        "temperature": 0.3,
        "max_tokens": 384,
        "system": "You are DevOS AI, running on this computer. Answer directly and briefly.",
        "user": "{body}",
    },
}


def clip(text: str, limit: int = DIFF_LIMIT) -> str:
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…(truncated)"


def build_job(name: str, body: str) -> list:
    job = JOBS[name]
    return [
        {"role": "system", "content": job["system"]},
        {"role": "user", "content": job["user"].format(body=clip(body))},
    ]


def commit_subject(text: str) -> str:
    """The first real line of a model reply, short enough for a commit subject."""
    for raw in (text or "").splitlines():
        line = raw.strip().strip("`").strip('"').strip("'")
        if not line or line.startswith("#"):
            continue
        for prefix in ("commit message:", "commit:", "subject:"):
            if line.lower().startswith(prefix):
                line = line[len(prefix):].strip()
        return line[:72]
    return ""


def chat(messages, model="devos-ai", max_tokens=384, temperature=0.2, timeout=90, url=None):
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    req = urllib.request.Request(
        url or AI_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(
            "DevOS AI is not answering. It starts with the PC. "
            "Start it with: systemctl start devos-ai-core"
        ) from exc
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("DevOS AI returned an unexpected reply.") from exc


def read_diff(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.read()
    try:
        staged = subprocess.check_output(
            ["git", "diff", "--cached", "--no-color"], text=True, errors="replace")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Run this inside a git repository.") from exc
    if staged.strip():
        return staged
    try:
        return subprocess.check_output(["git", "diff", "--no-color"], text=True, errors="replace")
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Could not read the git diff.") from exc


def hook_script() -> str:
    return f"""#!/bin/sh
{HOOK_MARK}
# Fills an empty commit message from the model on this PC.
# Remove with: devos auto hook remove
msg="$1"
# merge, squash, message: git already wrote the text
[ -n "$2" ] && exit 0
if grep -q '^[^#]' "$msg" 2>/dev/null; then
    exit 0
fi
diff=$(git diff --cached --no-color | head -c {DIFF_LIMIT})
[ -n "$diff" ] || exit 0
subject=$(printf '%s' "$diff" | /usr/local/bin/devos auto commit --stdin 2>/dev/null) || exit 0
[ -n "$subject" ] || exit 0
tmp=$(mktemp) || exit 0
printf '%s\\n\\n' "$subject" > "$tmp"
cat "$msg" >> "$tmp"
mv "$tmp" "$msg"
"""


def hooks_dir() -> str:
    try:
        path = subprocess.check_output(
            ["git", "rev-parse", "--git-path", "hooks"], text=True, errors="replace").strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Run this inside a git repository.") from exc
    if not path:
        raise RuntimeError("Run this inside a git repository.")
    return path


def install_hook() -> str:
    dest = os.path.join(hooks_dir(), "prepare-commit-msg")
    if os.path.exists(dest):
        with open(dest, encoding="utf-8", errors="replace") as handle:
            current = handle.read()
        if HOOK_MARK not in current:
            raise RuntimeError("A prepare-commit-msg hook already exists. DevOS left it alone.")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(hook_script())
    os.chmod(dest, 0o755)
    return dest


def remove_hook() -> str:
    dest = os.path.join(hooks_dir(), "prepare-commit-msg")
    if not os.path.exists(dest):
        return ""
    with open(dest, encoding="utf-8", errors="replace") as handle:
        current = handle.read()
    if HOOK_MARK not in current:
        raise RuntimeError("The prepare-commit-msg hook is not DevOS's. It was left alone.")
    os.remove(dest)
    return dest


def run_job(name: str, body: str) -> str:
    job = JOBS[name]
    text = chat(build_job(name, body), model=job["model"], max_tokens=job["max_tokens"],
                temperature=job["temperature"])
    if name == "commit":
        return commit_subject(text)
    return (text or "").strip()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="devos auto", description="DevOS AI automations on this PC")
    sub = parser.add_subparsers(dest="cmd")

    ask = sub.add_parser("ask", help="Ask the local model")
    ask.add_argument("question", nargs="+")

    commit = sub.add_parser("commit", help="Commit subject from the staged diff")
    commit.add_argument("--stdin", action="store_true", help="Read the diff from stdin")

    review = sub.add_parser("review", help="Review the staged diff")
    review.add_argument("--stdin", action="store_true")

    sub.add_parser("explain", help="Explain the error on stdin")

    summary = sub.add_parser("summarize", help="Summarize a text file")
    summary.add_argument("file")

    hook = sub.add_parser("hook", help="Git hook that fills an empty commit message")
    hook.add_argument("action", nargs="?", choices=("install", "remove"), default="install")

    sub.add_parser("docs", help="Where the local AI reference lives")

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        print("\nDocs: " + DOCS_URL)
        return 0

    try:
        if args.cmd == "docs":
            here = os.path.dirname(os.path.abspath(__file__))
            print(DOCS_URL)
            local = os.path.join(here, "API.md")
            if os.path.isfile(local):
                print(local)
            return 0
        if args.cmd == "hook":
            if args.action == "remove":
                removed = remove_hook()
                print("Removed the DevOS commit hook." if removed else "No DevOS commit hook was installed.")
            else:
                print("Installed " + install_hook())
                print("Empty commit messages in this repository are filled by DevOS AI.")
            return 0
        if args.cmd == "ask":
            body = " ".join(args.question).strip()
            if not body:
                print("Ask a question after: devos auto ask", file=sys.stderr)
                return 2
            print(run_job("ask", body))
            return 0
        if args.cmd == "summarize":
            with open(args.file, encoding="utf-8", errors="replace") as handle:
                body = handle.read()
            if not body.strip():
                print("That file is empty.", file=sys.stderr)
                return 2
            print(run_job("summarize", body))
            return 0
        if args.cmd == "explain":
            body = sys.stdin.read()
            if not body.strip():
                print("Pipe an error in: pytest -q 2>&1 | devos auto explain", file=sys.stderr)
                return 2
            print(run_job("explain", body))
            return 0
        if args.cmd in ("commit", "review"):
            body = read_diff(args.stdin)
            if not body.strip():
                print("Nothing to read. Stage a change, or pass a diff on stdin.", file=sys.stderr)
                return 2
            text = run_job(args.cmd, body)
            if not text:
                print("The model did not produce a reply.", file=sys.stderr)
                return 1
            print(text)
            return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
