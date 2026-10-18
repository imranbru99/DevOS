#!/usr/bin/env python3
"""
DevOS AI - the part of the assistant that decides what to do.

No Qt here. The window calls these functions from worker threads:

  plan(text)                 -> RouteResult  (instant, deterministic)
  run_actions(actions, ...)  -> [Reply]      (whitelisted tools)
  chat(text, history)        -> Reply        (the on-device model)
  handle_attachments(...)    -> [Reply]      (PDF / text / Word / images)

The model is the local AI service (OpenAI-compatible, 127.0.0.1:11434). It is
only ever asked to write text; it never chooses or runs actions.
"""

import json
import os
import re
import subprocess
import threading
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import documents  # noqa: E402
import tools  # noqa: E402
import vision  # noqa: E402

AI_URL = os.environ.get("DEVOS_AI_URL", "http://127.0.0.1:11434")
AI_SERVER_PY = os.path.join(tools.COMPONENTS, "ai-core", "server.py")
DATA_DIR = os.path.expanduser("~/.local/share/devos/assistant")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
HISTORY_TURNS = 50
MODEL_NAME = "devos-ai"

MODEL_MISSING = ("The on-device language model isn't installed on this PC yet, so I can't write free-form "
                 "answers. I can still do actions and answer questions about this PC — type **help** to see how.")
MODEL_OFFLINE = ("The DevOS AI service isn't responding. I've asked it to start; try again in a few seconds. "
                 "Actions and PC questions still work.")

APP_PROMPT = (
    "You are answering inside the DevOS AI app on the user's PC. The app itself (not you) can open apps and "
    "websites, search Google or YouTube, show this PC's details, count installed apps, install or remove "
    "apps after you agree, change volume and "
    "brightness, take screenshots, open settings and read attached files. If the user asks for one of those "
    "and it did not happen, tell them to say it directly, for example “open Chrome and search for ...”. "
    "Problems with this PC (security, a link, Wi-Fi, an error) are checked by the app itself. "
    "Never invent repair steps or menus. Never invent facts about this PC; only use the PC facts given here. "
    "Use short Markdown: short paragraphs, "
    "bullet lists, **bold** for key words."
)


class ModelUnavailable(Exception):
    pass


# ---------------------------------------------------------------------------
# Talking to the local model
# ---------------------------------------------------------------------------

_BRANDS = [
    (re.compile(r"\b(?:Qwen|QWen|qwen)[\w.\-]*(?:\s*(?:model|LLM))?", re.I), "DevOS AI"),
    (re.compile(r"\bTongyi(?:\s+Qianwen)?\b", re.I), "DevOS AI"),
    # The base model's maker is not the DevOS team; keep that truthful.
    (re.compile(r"\bAlibaba(?:\s+Cloud)?(?:\s+Group)?\b", re.I), "open-source developers"),
    (re.compile(r"\bllama[\s._-]?cpp\b|\bLlama\b(?:\s*\d[\w.]*)?", re.I), "the DevOS AI engine"),
]
_OS_BRANDS = [
    (re.compile(r"\bKubuntu\b|\bUbuntu(?:\s+\d{2}\.\d{2}(?:\s+LTS)?)?\b", re.I), "DevOS"),
    (re.compile(r"\bKDE\s+Plasma(?:\s+\d[\d.]*)?\b|\bKDE\b|\bPlasma\b"), "the DevOS desktop"),
]


# The tiny model sometimes writes its answer like a transcript line
# ("me: How can I assist you today?"), which looked like it was replying as
# the user. Drop such a leading speaker label.
_ROLE_LABEL = re.compile(
    r"^\s*(?:\*\*)?(?:me|you|user|assistant|ai|bot|devos ai|devos)(?:\*\*\s*:|\s*:(?:\*\*)?)\s*", re.I)


def scrub(text: str, os_names: bool = True) -> str:
    text = _ROLE_LABEL.sub("", text, count=1)
    for rx, rep in _BRANDS:
        text = rx.sub(rep, text)
    if os_names:
        for rx, rep in _OS_BRANDS:
            text = rx.sub(rep, text)
    return re.sub(r"(DevOS AI)(?:\s+DevOS AI)+", r"\1", text)


class LocalModel:
    def __init__(self, url: str = AI_URL, timeout: float = 180.0):
        self.url = url.rstrip("/")
        self.timeout = timeout

    def health(self, timeout: float = 1.5) -> Optional[dict]:
        try:
            with urllib.request.urlopen(self.url + "/health", timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except (OSError, ValueError):
            return None

    def chat(self, messages: List[Dict[str, str]], on_delta: Optional[Callable[[str], None]] = None,
             cancel: Optional["StreamHandle"] = None, max_tokens: int = 384,
             temperature: float = 0.3) -> str:
        """The answer text. With on_delta, the reply is streamed (server-sent events) and every new
        piece is passed to on_delta as it arrives; cancel.stop() ends it early (the text so far is
        returned). A server that answers with plain JSON instead of a stream is handled too."""
        stream = on_delta is not None
        body = json.dumps({"model": MODEL_NAME, "messages": messages, "stream": stream,
                           "max_tokens": int(max_tokens), "temperature": float(temperature)}).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if stream:
            headers["Accept"] = "text/event-stream"
        req = urllib.request.Request(self.url + "/v1/chat/completions", data=body, headers=headers)
        try:
            r = urllib.request.urlopen(req, timeout=self.timeout)
        except (OSError, ValueError) as exc:
            raise ModelUnavailable(MODEL_OFFLINE) from exc
        try:
            if cancel is not None:
                cancel.attach(r)
                if cancel.stopped:
                    return ""
            ctype = (r.headers.get("Content-Type") or "").lower()
            if stream and "event-stream" in ctype:
                return self._read_stream(r, on_delta, cancel)
            data = json.loads(r.read().decode("utf-8"))
        except (OSError, ValueError, AttributeError) as exc:
            if cancel is not None and cancel.stopped:
                return ""
            raise ModelUnavailable(MODEL_OFFLINE) from exc
        finally:
            try:
                r.close()
            except Exception:
                pass
        if data.get("model_loaded") is False:
            raise ModelUnavailable(MODEL_MISSING)
        try:
            text = (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            raise ModelUnavailable(MODEL_OFFLINE)
        if stream and text:
            on_delta(text)
        return text

    @staticmethod
    def _read_stream(r, on_delta, cancel) -> str:
        parts: List[str] = []
        try:
            for raw in r:
                if cancel is not None and cancel.stopped:
                    break
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                piece = parse_sse_delta(payload)
                if piece is None:
                    continue
                if isinstance(piece, ModelUnavailable):
                    raise piece
                if piece:
                    parts.append(piece)
                    on_delta(piece)
        except (OSError, ValueError, AttributeError):
            if not (cancel is not None and cancel.stopped) and not parts:
                raise ModelUnavailable(MODEL_OFFLINE)
        return "".join(parts).strip()


def parse_sse_delta(payload: str):
    """One `data:` payload -> the text piece, "" for none, None for junk, ModelUnavailable for errors."""
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("model_loaded") is False:
        return ModelUnavailable(MODEL_MISSING)
    if data.get("error"):
        return ModelUnavailable(MODEL_OFFLINE)
    try:
        ch = data["choices"][0]
        delta = ch.get("delta") or ch.get("message") or {}
        return str(delta.get("content") or "")
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


def stream_preview(text: str) -> str:
    """What to show while an answer is still arriving: whole words only (so a half-written name
    is never shown before scrub() can catch it), scrubbed."""
    cut = max(text.rfind(" "), text.rfind("\n"))
    return scrub(text[:cut]) if cut > 0 else ""


class StreamHandle:
    """Lets the window stop an answer that is being streamed: stop() closes the HTTP connection."""

    def __init__(self):
        self.stopped = False
        self._resp = None
        self._lock = threading.Lock()

    def attach(self, resp) -> None:
        with self._lock:
            self._resp = resp

    def stop(self) -> None:
        with self._lock:
            self.stopped = True
            r = self._resp
        if r is not None:
            for close in (getattr(getattr(r, "fp", None), "close", None), getattr(r, "close", None)):
                try:
                    if close:
                        close()
                except Exception:
                    pass


def start_ai_service(server_py: str = AI_SERVER_PY) -> bool:
    if not os.path.isfile(server_py):
        return False
    try:
        log = open(os.path.join("/var/tmp", "devos-ai-core.log"), "ab")
    except OSError:
        log = subprocess.DEVNULL
    try:
        subprocess.Popen([sys.executable or "python3", server_py], cwd=os.path.dirname(server_py),
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# "Smarter DevOS AI": the optional bigger chat model (installed by a root helper)
# ---------------------------------------------------------------------------

SMART_MODEL_FILE = "/var/lib/DevOS/models/qwen2.5-1.5b-instruct-q4_k_m.gguf"
UPGRADE_HELPER = "/usr/local/sbin/devos-ai-upgrade"
SMART_LABEL = "Smarter DevOS AI"
SMART_SIZE = "1.1 GB"
_PROGRESS = re.compile(r"\[Downloading\]\s*([\d.]+)\s*MB\s*/\s*([\d.]+)\s*MB", re.I)


def smart_model_installed(path: str = SMART_MODEL_FILE) -> bool:
    return os.path.isfile(path)


def parse_upgrade_progress(line: str) -> Optional[Tuple[float, float]]:
    """'[Downloading] 312.0 MB/1066.0 MB' -> (312.0, 1066.0); anything else -> None."""
    m = _PROGRESS.search(line or "")
    if not m:
        return None
    return float(m.group(1)), float(m.group(2))


def upgrade_command(remove: bool = False) -> List[str]:
    return ["pkexec", UPGRADE_HELPER] + (["--remove"] if remove else [])


def run_upgrade(remove: bool = False, progress: Callable[[float, float], None] = lambda d, t: None,
                popen: Callable = subprocess.Popen) -> Tuple[bool, str]:
    """Run the helper as root through pkexec. Returns (ok, message for the user)."""
    try:
        proc = popen(upgrade_command(remove), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except OSError:
        return False, f"{SMART_LABEL} can't be set up on this PC."
    last = ""
    for line in proc.stdout:
        p = parse_upgrade_progress(line)
        if p:
            progress(*p)
        elif line.strip():
            last = line.strip()
    err = (proc.stderr.read() or "").strip() if proc.stderr else ""
    rc = proc.wait()
    if rc == 0:
        return True, ("Back to the built-in DevOS AI. The space has been freed." if remove
                      else f"{SMART_LABEL} is ready.")
    if rc in (126, 127):        # pkexec: password dialog dismissed / not authorised
        return False, "Nothing was changed: the administrator password wasn't entered."
    msg = scrub(err.splitlines()[-1] if err else last)
    return False, msg or "That didn't finish. Check the internet connection and try again."


# ---------------------------------------------------------------------------
# Replies and history
# ---------------------------------------------------------------------------


@dataclass
class Reply:
    text: str
    ok: bool = True
    # (label, payload). payload is a tools.Action, or a string command the
    # window understands: "download_vision", "download_voice", "open_path:<p>"
    buttons: List[Tuple[str, object]] = field(default_factory=list)
    source: str = "tool"        # tool / model / doc / image / system


class History:
    """~/.local/share/devos/assistant/history.json, last HISTORY_TURNS turns."""

    def __init__(self, path: str = HISTORY_FILE, turns: int = HISTORY_TURNS):
        self.path = path
        self.turns = turns
        self.messages: List[Dict[str, object]] = []

    def load(self) -> "History":
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            msgs = data.get("messages", []) if isinstance(data, dict) else []
            self.messages = [m for m in msgs if isinstance(m, dict) and m.get("role") in ("user", "assistant")
                             and isinstance(m.get("text"), str)]
        except (OSError, ValueError):
            self.messages = []
        self._trim()
        return self

    def add(self, role: str, text: str, **extra) -> None:
        m = {"role": role, "text": text, "ts": int(time.time())}
        m.update(extra)
        self.messages.append(m)
        self._trim()

    def _trim(self) -> None:
        # a turn = one user message and what followed it
        user_idx = [i for i, m in enumerate(self.messages) if m["role"] == "user"]
        if len(user_idx) > self.turns:
            self.messages = self.messages[user_idx[-self.turns]:]

    def clear(self) -> None:
        self.messages = []
        self.save()

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "messages": self.messages}, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def for_model(self, limit: int = 6, chars: int = 700) -> List[Dict[str, str]]:
        out = []
        for m in self.messages[-limit:]:
            text = str(m.get("text", ""))
            if m.get("role") == "assistant":
                # Older replies saved as "me: …" made the model copy the label
                # into every new answer; never feed it back.
                text = _ROLE_LABEL.sub("", text, count=1)
            if len(text) > chars:
                text = text[:chars] + "…"
            out.append({"role": str(m["role"]), "content": text})
        return out


# ---------------------------------------------------------------------------
# Many conversations: chats/<id>.json + chats/index.json
# ---------------------------------------------------------------------------

TITLE_CHARS = 40


def chat_title(text: str, n: int = TITLE_CHARS) -> str:
    """First user message, one line, trimmed to n characters."""
    t = " ".join((text or "").split())
    if not t:
        return "New chat"
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def day_group(ts: float, now: Optional[float] = None) -> str:
    """'Today', 'Yesterday' or 'Earlier' in local time."""
    now = time.time() if now is None else now
    d = time.localtime(ts)
    n = time.localtime(now)
    day = (d.tm_year, d.tm_yday)
    today = (n.tm_year, n.tm_yday)
    if day == today:
        return "Today"
    y = time.localtime(now - 86400)
    if day == (y.tm_year, y.tm_yday):
        return "Yesterday"
    return "Earlier"


class ChatStore:
    """
    ~/.local/share/devos/assistant/chats/
        index.json   {"version": 1, "chats": [{id, title, created, updated}, ...]}
        <id>.json    one History file per conversation

    The old single history.json is migrated into the first chat once.
    A new chat only appears in the index after its first message is saved.
    """

    def __init__(self, data_dir: str = DATA_DIR, turns: int = HISTORY_TURNS):
        self.data_dir = data_dir
        self.dir = os.path.join(data_dir, "chats")
        self.index_path = os.path.join(self.dir, "index.json")
        self.turns = turns
        self.chats: List[Dict[str, object]] = []

    # -- index ------------------------------------------------------------

    def load(self) -> "ChatStore":
        try:
            with open(self.index_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            chats = data.get("chats", []) if isinstance(data, dict) else []
            self.chats = [c for c in chats if isinstance(c, dict) and re.fullmatch(r"[\w-]{1,64}", str(c.get("id", "")))
                          and os.path.isfile(self.path_for(str(c["id"])))]
        except (OSError, ValueError):
            self.chats = []
            self._migrate()
        self.chats.sort(key=lambda c: -float(c.get("updated") or 0))
        return self

    def _migrate(self) -> None:
        old = os.path.join(self.data_dir, "history.json")
        if not os.path.isfile(old):
            return
        h = History(old, self.turns).load()
        if h.messages:
            cid = self.new_id()
            h.path = self.path_for(cid)
            h.save()
            first = next((m["text"] for m in h.messages if m["role"] == "user"), "")
            ts = [float(m.get("ts") or 0) for m in h.messages if m.get("ts")]
            self.chats.append({"id": cid, "title": chat_title(first), "created": min(ts) if ts else time.time(),
                               "updated": max(ts) if ts else time.time()})
        self.save_index()
        try:
            os.replace(old, old + ".migrated")
        except OSError:
            pass

    def save_index(self) -> None:
        try:
            os.makedirs(self.dir, exist_ok=True)
            tmp = self.index_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "chats": self.chats}, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.index_path)
        except OSError:
            pass

    # -- chats ------------------------------------------------------------

    @staticmethod
    def new_id() -> str:
        return time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()

    def path_for(self, cid: str) -> str:
        return os.path.join(self.dir, f"{cid}.json")

    def get(self, cid: str) -> Optional[Dict[str, object]]:
        return next((c for c in self.chats if c["id"] == cid), None)

    def new_history(self) -> History:
        h = History(self.path_for(self.new_id()), self.turns)
        h.chat_id = os.path.splitext(os.path.basename(h.path))[0]
        return h

    def open(self, cid: str) -> History:
        h = History(self.path_for(cid), self.turns).load()
        h.chat_id = cid
        return h

    def touch(self, history: History) -> Dict[str, object]:
        """Record that `history` was saved: add it to the index or bump it."""
        cid = getattr(history, "chat_id", None) or os.path.splitext(os.path.basename(history.path))[0]
        c = self.get(cid)
        now = time.time()
        if c is None:
            first = next((m["text"] for m in history.messages if m["role"] == "user" and m.get("text")), "")
            if not first:
                first = next((", ".join(m.get("files") or []) for m in history.messages if m["role"] == "user"), "")
            c = {"id": cid, "title": chat_title(first), "created": now, "updated": now}
            self.chats.insert(0, c)
        else:
            c["updated"] = now
            self.chats.sort(key=lambda x: -float(x.get("updated") or 0))
        self.save_index()
        return c

    def rename(self, cid: str, title: str) -> bool:
        c = self.get(cid)
        title = " ".join((title or "").split())
        if c is None or not title:
            return False
        c["title"] = title[:80]
        self.save_index()
        return True

    def delete(self, cid: str) -> bool:
        c = self.get(cid)
        if c is None:
            return False
        self.chats.remove(c)
        try:
            os.remove(self.path_for(cid))
        except OSError:
            pass
        self.save_index()
        return True

    def search(self, query: str = "") -> List[Dict[str, object]]:
        q = (query or "").strip().lower()
        if not q:
            return list(self.chats)
        out = []
        for c in self.chats:
            if q in str(c.get("title", "")).lower():
                out.append(c)
                continue
            try:
                msgs = History(self.path_for(str(c["id"])), self.turns).load().messages
            except Exception:
                msgs = []
            if any(q in str(m.get("text", "")).lower() for m in msgs):
                out.append(c)
        return out

    def grouped(self, query: str = "", now: Optional[float] = None) -> List[Tuple[str, List[Dict[str, object]]]]:
        groups: Dict[str, List[Dict[str, object]]] = {}
        for c in self.search(query):
            groups.setdefault(day_group(float(c.get("updated") or 0), now), []).append(c)
        return [(g, groups[g]) for g in ("Today", "Yesterday", "Earlier") if g in groups]


# ---------------------------------------------------------------------------
# The assistant
# ---------------------------------------------------------------------------

_OCR_WORDS = re.compile(r"\b(?:read|text|ocr|extract|copy|transcribe|what does (?:it|this) say|written|words?|"
                        r"letters?|type out)\b|লেখা|পড়")


class Assistant:
    def __init__(self, model: Optional[LocalModel] = None, ctx: Optional[tools.ToolContext] = None,
                 which: Callable = None):
        self.model = model or LocalModel()
        self.ctx = ctx or tools.ToolContext()
        self.which = which or self.ctx.which
        self._pc_facts: Optional[str] = None

    # -- routing ----------------------------------------------------------

    def plan(self, text: str, history: Optional[History] = None) -> tools.RouteResult:
        """Route a request. The chat's earlier user messages let "install this"
        refer to a link or app named before."""
        context: List[str] = []
        if history is not None:
            context = [str(m.get("text") or "") for m in history.messages if m.get("role") == "user"]
            if context and context[-1].strip() == (text or "").strip():
                context = context[:-1]      # the message being answered
        return tools.route(text, self.ctx, context=context[-4:])

    def run_actions(self, actions: List[tools.Action], original: str, leftover: str = "",
                    history: Optional[History] = None, dry_run: bool = False,
                    on_delta: Optional[Callable[[str], None]] = None,
                    cancel: Optional[StreamHandle] = None) -> List[Reply]:
        replies: List[Reply] = []
        fallback = False
        for a in actions:
            res = tools.execute(a, self.ctx, dry_run=dry_run)
            if a.name == "open_app" and not a.args.get("strong") and res.data.get("not_found"):
                fallback = True
                continue
            replies.append(Reply(res.text, ok=res.ok, buttons=list(res.buttons), source="tool"))
        if fallback and not replies:
            return [self.chat(original, history, on_delta=on_delta, cancel=cancel)]
        if leftover:
            replies.append(self.chat(leftover, history, on_delta=on_delta, cancel=cancel))
        return replies

    # -- free-form chat ---------------------------------------------------

    def pc_facts(self) -> str:
        if self._pc_facts is None:
            try:
                info = tools.gather_system_info(self.ctx)
                cpu = info["cpu"]
                ram = info["ram"]
                gpu = ", ".join(info.get("gpu") or []) or "integrated graphics"
                vol = (info.get("volumes") or [{}])[0]
                self._pc_facts = (f"PC facts: processor {cpu['model']} with {cpu['cores']} cores; "
                                  f"{tools.human_size(ram['total'])} RAM; graphics {gpu}; "
                                  f"{tools.human_size(vol.get('free'))} free on the system disk; "
                                  f"system {info['os']['name']}.")
            except Exception:
                self._pc_facts = ""
        return self._pc_facts

    def chat(self, text: str, history: Optional[History] = None,
             on_delta: Optional[Callable[[str], None]] = None, cancel: Optional[StreamHandle] = None) -> Reply:
        """on_delta(piece) gets the answer as it is written (streaming); cancel.stop() ends it early."""
        system = APP_PROMPT
        messages = [{"role": "system", "content": system}]
        if history is not None:
            past = history.for_model()
            # the newest user message is the one we are answering
            if past and past[-1]["role"] == "user" and past[-1]["content"].strip() == text.strip():
                past = past[:-1]
            messages += past
        messages.append({"role": "user", "content": text})
        try:
            if on_delta is not None:
                answer = self.model.chat(messages, on_delta=on_delta, cancel=cancel)
            else:
                answer = self.model.chat(messages)
        except ModelUnavailable as exc:
            if str(exc) == MODEL_OFFLINE:
                start_ai_service()
            return Reply(str(exc), ok=False, source="system")
        stopped = cancel is not None and cancel.stopped
        if not answer:
            if stopped:
                return Reply("Stopped.", ok=False, source="system")
            return Reply("I don't have an answer for that. Try asking it another way.", ok=False, source="model")
        return Reply(scrub(answer), source="model")

    def _ask(self, prompt: str) -> str:
        return self.model.chat([
            {"role": "system", "content": "You read documents for the user. Be accurate and brief. Use Markdown bullets."},
            {"role": "user", "content": prompt},
        ])

    # -- attachments ------------------------------------------------------

    def handle_attachments(self, text: str, paths: List[str], history: Optional[History] = None) -> List[Reply]:
        replies = []
        for p in paths:
            kind = documents.kind_of(p)
            name = os.path.basename(p)
            if kind == "image":
                replies.append(self.handle_image(p, text))
            elif kind in ("pdf", "text", "docx"):
                replies.append(self.handle_document(p, text))
            else:
                replies.append(Reply(f"I can't read **{name}**. I can read PDF, Word (.docx), text and Markdown "
                                     "files, and PNG/JPG/WebP images.", ok=False, source="doc"))
        return replies

    def handle_document(self, path: str, question: str) -> Reply:
        name = os.path.basename(path)
        text, problem = documents.extract_text(path, which=self.which)
        if problem:
            return Reply(f"**{name}:** {problem}", ok=False, source="doc")
        words = len(text.split())
        try:
            if documents.wants_summary(question):
                summary, calls = documents.summarize(text, self._ask, name=f"“{name}”")
                body = f"**Summary of {name}** ({words:,} words)\n\n{scrub(summary, os_names=False)}"
            else:
                answer = documents.answer_question(text, question, self._ask, name=f"“{name}”")
                body = f"**From {name}:**\n\n{scrub(answer, os_names=False)}"
            return Reply(body, source="doc")
        except ModelUnavailable as exc:
            preview = text[:1500].strip()
            return Reply(f"{exc}\n\nHere is the start of **{name}** ({words:,} words):\n\n```\n{preview}\n```",
                         ok=False, source="doc")

    def handle_image(self, path: str, question: str) -> Reply:
        name = os.path.basename(path)
        q = (question or "").strip()
        wants_text = bool(_OCR_WORDS.search(q.lower())) if q else False
        vision_ready = vision.model_installed() and vision.runtime_supported()[0]
        if vision_ready and not wants_text:
            try:
                answer = vision.VisionModel.describe(path, q)
                return Reply(f"**{name}:** {scrub(answer, os_names=False)}", source="image")
            except Exception as exc:
                sys.stderr.write(f"assistant: vision failed: {exc}\n")
        ocr_text, problem = ("", vision.OCR_MISSING)
        if vision.ocr_available(self.which):
            ocr_text, problem = vision.ocr(path, self.which)
        buttons = []
        if not vision_ready:
            buttons.append((vision.download_button_label(), "download_vision"))
        if ocr_text:
            if wants_text or not q:
                body = f"**Text in {name}:**\n\n```\n{ocr_text[:4000]}\n```"
                if not q and not vision_ready:
                    body += ("\n\nTo also describe what's in photos, photo understanding needs a one-time "
                             f"{vision.download_size_label()} download.")
                return Reply(body, source="image", buttons=buttons if not q else [])
            # a question about an image that contains text: answer from the text
            try:
                answer = self._ask(f"This text was read from an image named {name}:\n---\n{ocr_text[:5000]}\n---\n"
                                   f"Using it, answer: {q}")
                note = "" if vision_ready else ("\n\n_I answered from the text in the image. To understand the "
                                                 "photo itself, download photo understanding._")
                return Reply(f"**{name}:** {scrub(answer, os_names=False)}{note}", source="image", buttons=buttons)
            except ModelUnavailable:
                return Reply(f"**Text in {name}:**\n\n```\n{ocr_text[:4000]}\n```", source="image", buttons=buttons)
        lines = []
        if problem and problem != vision.OCR_MISSING:
            lines.append(problem)
        if not vision_ready:
            ok, why = vision.runtime_supported()
            if ok:
                lines.append(f"Photo understanding needs a one-time **{vision.download_size_label()}** download. "
                             "After that, everything runs on this PC.")
            else:
                lines.append(f"Photo understanding isn't available: {why}")
                buttons = []
        if problem == vision.OCR_MISSING:
            lines.append("Reading the text in images isn't available on this PC yet.")
        elif not ocr_text and vision.ocr_available(self.which):
            lines.append("I didn't find any text in this image.")
        return Reply(f"**{name}:** " + " ".join(lines), ok=False, source="image", buttons=buttons)
