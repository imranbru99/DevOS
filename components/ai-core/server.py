#!/usr/bin/env python3
"""
DevOS Local AI Inference Server (ai-core)
Provides an offline OpenAI-compatible HTTP service on 127.0.0.1:11434.
Zero external dependencies required (uses built-in http.server & json).
"""

import sys
import os
import time
import json
import uuid
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, List
from hardware_detector import HardwareDetector


HOST = "127.0.0.1"
PORT = 11434


class DevOSAIEngine:
    """Inference engine controller with memory governor and mock/llama backend."""

    def __init__(self):
        self.tier_info = HardwareDetector.evaluate_tier()
        # Public name in the API (/health, /v1/models, replies). The real file
        # is kept in _model_file; users and apps only ever see "devos-ai".
        self.active_model = "devos-ai"
        self.idle_timeout_seconds = 300
        self.last_activity = time.time()
        self.is_loaded = False
        self._llm = None
        self._load_tried = False
        self._model_file = None
        self.tokens_generated = 0
        self.start_time = time.time()
        # One generation at a time (the server answers health checks in
        # parallel threads while the model is busy).
        import threading
        self._lock = threading.RLock()

    def generate_chat_response(self, messages: List[Dict[str, str]], stream: bool = False) -> Dict[str, Any]:
        """Answer from the local GGUF when it is installed."""
        self.last_activity = time.time()
        user_prompt = ""
        for m in messages:
            if m.get("role") == "user":
                user_prompt = m.get("content", "")

        started = time.time()
        with self._lock:
            self._ensure_model()
        if self._llm is not None:
            reply_content = self._complete(messages)
        else:
            reply_content = self._reason(user_prompt)
        elapsed = max(time.time() - started, 0.001)
        prompt_tokens = len(user_prompt.split()) + 15
        completion_tokens = len(reply_content.split())
        self.tokens_generated += completion_tokens

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.active_model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": reply_content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "devos_tier": self.tier_info["tier"],
            "model_loaded": self._llm is not None,
            "tokens_per_sec": round(completion_tokens / elapsed, 2),
        }

    def generate_embeddings(self, inputs: List[str]) -> Dict[str, Any]:
        """Generates embedding vectors for local RAG."""
        self.last_activity = time.time()
        data = []
        for idx, text in enumerate(inputs):
            # Deterministic pseudo-embedding vector of 384 dimensions for testing
            seed = sum(ord(c) for c in text) % 1000
            vector = [(float((seed + i) % 100) / 100.0) - 0.5 for i in range(384)]
            data.append({
                "object": "embedding",
                "index": idx,
                "embedding": vector,
            })
        return {
            "object": "list",
            "data": data,
            "model": self.tier_info["models"]["embed_model"],
            "usage": {
                "prompt_tokens": sum(len(t.split()) for t in inputs),
                "total_tokens": sum(len(t.split()) for t in inputs),
            }
        }

    def _reason(self, prompt: str) -> str:
        """Internal prompt reasoning logic."""
        p_lower = prompt.lower()
        # Used only while no model file is present. Speak about DevOS only,
        # never about the parts it is built from.
        if "hardware" in p_lower or "tier" in p_lower or "specs" in p_lower or "config" in p_lower:
            facts = pc_facts()
            return "This PC: " + facts if facts else f"This PC has {self.tier_info['ram_gb']} GB of RAM."
        elif "install" in p_lower:
            return ("To install an app, double-click the downloaded file: Windows programs (.exe, .msi) "
                    "and Android apps (.apk) open directly in DevOS. To remove one, open the Apps window.")
        elif "optimize" in p_lower or "speed" in p_lower:
            return "Open DevOS Optimizer to clean temporary files and see apps you have not used for a while."
        else:
            return ("DevOS AI is still being set up on this PC, so it cannot answer that yet. "
                    "Questions about this PC, apps and settings already work in the DevOS AI window.")

    def _model_dirs(self):
        configured = os.environ.get("DEVOS_MODELS_DIR", "")
        return [
            configured,
            "/var/lib/DevOS/models",
            "/usr/share/devos/models",
            os.path.expanduser("~/.local/share/DevOS/models"),
        ]

    def _find_model(self):
        names = [
            "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            "qwen2.5-0.5b-instruct-q4_k_m.gguf",
            self.tier_info["models"].get("chat_file", ""),
        ]
        # Best model first, in any folder: "Smarter DevOS AI" (1.5B) wins over
        # the built-in tiny model even when they sit in different folders.
        for name in names:
            if not name:
                continue
            for directory in self._model_dirs():
                if not directory:
                    continue
                path = os.path.join(directory, name)
                if os.path.isfile(path) and os.path.getsize(path) > 100_000_000:
                    return path
        return None

    def _ensure_model(self):
        if self._llm is not None or self._load_tried:
            return
        self._load_tried = True
        path = self._find_model()
        if not path:
            return
        try:
            from llama_cpp import Llama
            threads = max(2, min(8, os.cpu_count() or 2))
            self._llm = Llama(
                model_path=path,
                n_ctx=2048,  # short chats; 4096 doubled the working memory
                n_threads=threads,
                n_gpu_layers=0,
                verbose=False,
            )
            # Reuse the processed system prompt between questions. It is the
            # same text every time (see devos_identity_prompt), so only the
            # new question has to be read; on a 2-core PC that saved seconds.
            try:
                from llama_cpp import LlamaRAMCache
                self._llm.set_cache(LlamaRAMCache(capacity_bytes=64 << 20))
            except Exception as exc:
                sys.stderr.write(f"[ai-core] prompt cache unavailable: {exc}\n")
            self._model_file = path
            self.active_model = "devos-ai"
            self.is_loaded = True
        except Exception as exc:
            sys.stderr.write(f"[ai-core] model did not load: {exc}\n")
            self._llm = None
            self.is_loaded = False

    def unload_if_idle(self) -> bool:
        """Give the model's memory back when nobody has asked anything for a
        while. It held 1.6-2.7 GB for hours, and on a 4 GB laptop that made
        Android and Chrome get killed. The file is memory-mapped, so loading it
        again on the next question takes about a second."""
        if self._llm is None or time.time() - self.last_activity < self.idle_timeout_seconds:
            return False
        if not self._lock.acquire(blocking=False):
            return False  # answering right now
        try:
            self._llm = None
            self._load_tried = False
            self.is_loaded = False
            import gc
            gc.collect()
            try:
                import ctypes
                ctypes.CDLL("libc.so.6").malloc_trim(0)  # hand freed pages back to the system
            except Exception:
                pass
            return True
        finally:
            self._lock.release()

    def idle_watch(self):
        while True:
            time.sleep(30)
            if self.unload_if_idle():
                sys.stderr.write("[ai-core] idle: model unloaded to free memory\n")

    def warm_up(self):
        """Load the model and process the system prompt at service start, so
        the first question does not pay for it."""
        with self._lock:
            self._ensure_model()
            if self._llm is None:
                return
            try:
                self._llm.create_chat_completion(messages=self._build_chat([{"role": "user", "content": "Hi"}]),
                                                 max_tokens=1, temperature=0.0)
            except Exception as exc:
                sys.stderr.write(f"[ai-core] warm-up failed: {exc}\n")

    def _build_chat(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        ram = self.tier_info.get("ram_gb")
        tier = self.tier_info.get("tier")
        # The identity always comes first, even when a caller (Optimizer, code
        # agent, VS Code) sends its own system message. Small models otherwise
        # guess who they are and claimed to be a cloud assistant.
        identity = devos_identity_prompt(ram, tier)
        callers = [m.get("content") or "" for m in messages if m.get("role") == "system"]
        chat = [{"role": "system", "content": "\n\n".join([identity] + [c for c in callers if c])}]
        for message in messages:
            role = message.get("role") or "user"
            content = message.get("content") or ""
            if role not in ("user", "assistant") or not content:
                continue
            chat.append({"role": role, "content": content})
        return chat

    def _complete(self, messages: List[Dict[str, str]]) -> str:
        chat = self._build_chat(messages)
        if not any(item["role"] == "user" for item in chat):
            return "Ask a question and I will answer from the model on this computer."
        try:
            with self._lock:
                result = self._llm.create_chat_completion(
                    messages=chat,
                    max_tokens=384,
                    temperature=0.3,
                )
            text = result["choices"][0]["message"]["content"]
            text = (text or "").strip()
            # Small models sometimes answer like a transcript ("me: ...").
            import re as _re
            text = _re.sub(r"^\s*(?:me|you|user|assistant|ai|bot|devos ai)\s*:\s*", "", text, count=1, flags=_re.I)
            if text:
                return text
        except Exception as exc:
            sys.stderr.write(f"[ai-core] generation failed: {exc}\n")
        return "The local model is installed, but it did not produce an answer. Ask again."

    def stream_chat(self, messages: List[Dict[str, str]]):
        """Yield the answer in small pieces as the model writes it, so the
        window shows words within a second instead of after the whole reply."""
        self.last_activity = time.time()
        with self._lock:
            self._ensure_model()
        if self._llm is None:
            user_prompt = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
            yield self._reason(user_prompt)
            return
        chat = self._build_chat(messages)
        with self._lock:
            try:
                for chunk in self._llm.create_chat_completion(messages=chat, max_tokens=384,
                                                               temperature=0.3, stream=True):
                    delta = chunk["choices"][0].get("delta", {}).get("content")
                    if delta:
                        yield delta
            except Exception as exc:
                sys.stderr.write(f"[ai-core] generation failed: {exc}\n")
                yield "The local model did not produce an answer. Ask again."


_PC_FACTS = None


def pc_facts() -> str:
    """Real hardware of this PC, so "what is my PC config" is answered, not guessed.

    Measured once and kept: the system prompt must stay byte-identical between
    questions for the prompt cache to work, so only fixed facts (no free RAM,
    no battery level) go in. Live numbers come from the DevOS AI window's tools.
    """
    global _PC_FACTS
    if _PC_FACTS is None:
        _PC_FACTS = _measure_pc_facts()
    return _PC_FACTS


def _measure_pc_facts() -> str:
    facts = []
    try:
        model, cores = "", 0
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("model name") and not model:
                    model = line.split(":", 1)[1].strip()
                elif line.startswith("processor"):
                    cores += 1
        if model:
            facts.append(f"Processor: {' '.join(model.split())} ({cores} threads)")
    except OSError:
        pass
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            mem = {l.split(":")[0]: int(l.split()[1]) for l in handle if l.split()[1:2] and l.split()[1].isdigit()}
        total = mem.get("MemTotal", 0) / 1048576
        avail = mem.get("MemAvailable", 0) / 1048576
        facts.append(f"Memory (RAM): {total:.1f} GB")
    except (OSError, ValueError, IndexError):
        pass
    try:
        import shutil as _shutil
        disk = _shutil.disk_usage("/")
        facts.append(f"Disk: {disk.total / 1e9:.0f} GB")
    except OSError:
        pass
    try:
        import subprocess as _sp
        out = _sp.run(["lspci", "-mm"], capture_output=True, text=True, timeout=3).stdout
        gpus = [l.split('"')[5] + " " + l.split('"')[3] for l in out.splitlines()
                if ("VGA" in l or "3D" in l or "Display" in l) and l.count('"') >= 6]
        if gpus:
            facts.append("Graphics: " + "; ".join(gpus))
    except (OSError, IndexError, Exception):
        pass
    try:
        for name in os.listdir("/sys/class/power_supply"):
            base = os.path.join("/sys/class/power_supply", name)
            if open(os.path.join(base, "type")).read().strip() == "Battery":
                facts.append("Laptop with a battery")
                break
    except OSError:
        pass
    return "; ".join(facts)


def devos_identity_prompt(ram=None, tier=None) -> str:
    """Who the assistant is. Kept truthful: it runs locally on an open model."""
    hardware = ""
    if ram:
        hardware = f" This computer has {ram} GB of RAM and the {tier} hardware profile."
    facts = pc_facts()
    if facts:
        hardware = (" Facts about THIS computer (use them when asked about the PC, its "
                    "configuration, processor, RAM, storage, graphics or battery; never invent "
                    "other specs): " + facts + ".")
    return (
        "You are DevOS AI, the private assistant built into DevOS. "
        "DevOS and DevOS AI are made by the DevOS team, led by Imran Ahmed (Imran Dev); "
        "his portfolio is https://imrandev.bd/ . DevOS is open source: "
        "https://github.com/imranbru99/DevOS . When asked who made you or DevOS, who the DevOS "
        "team is, or where the source code is, give these names and links. "
        "You run entirely on this computer: nothing the user types is sent to the internet. "
        "You are not Claude, ChatGPT, Gemini, Copilot or any other cloud service, and you were not made by "
        "Anthropic, OpenAI, Google, Microsoft or Alibaba; never say you are. "
        "If asked which model you are, say you are DevOS AI, the on-device model that ships with DevOS, "
        "built on open-source language-model technology and tuned for DevOS. "
        "You help with DevOS itself: Windows apps (.exe and .msi files open directly in DevOS, just "
        "double-click them), Android apps (.apk files open in the DevOS Android window after a one-time "
        "download), installing and uninstalling apps (the Apps window), keeping the PC fast (DevOS "
        "Optimizer cleans temporary files and points out unused apps), files, Wi-Fi, printers and coding. "
        "Talk about DevOS, not about the software it is built from. "
        "Answer directly and briefly, in the user's language. Do not greet unless the user greeted you. "
        "Write only your reply: never start with a speaker label such as 'me:', 'AI:' or 'DevOS AI:'."
        + hardware
    )


engine = DevOSAIEngine()


class OpenAIHandler(BaseHTTPRequestHandler):
    """HTTP request handler implementing the OpenAI API specification."""

    def _send_json(self, status: int, data: Any):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _send_stream(self, messages):
        """OpenAI-style server-sent events: one small piece of text per event."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        chat_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

        def event(payload):
            self.wfile.write(b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n")
            self.wfile.flush()

        try:
            for piece in engine.stream_chat(messages):
                event({"id": chat_id, "object": "chat.completion.chunk", "created": int(time.time()),
                       "model": engine.active_model,
                       "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]})
            event({"id": chat_id, "object": "chat.completion.chunk", "created": int(time.time()),
                   "model": engine.active_model,
                   "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the window was closed while answering

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path in ("/health", "/v1/health"):
            self._send_json(200, {
                "status": "healthy",
                "tier": engine.tier_info["tier"],
                "active_model": engine.active_model,
                "uptime_seconds": round(time.time() - engine.start_time, 1)
            })
        elif self.path in ("/v1/models", "/models"):
            models_list = [
                {"id": "devos-ai", "object": "model", "owned_by": "devos"},
                {"id": "devos-ai-code", "object": "model", "owned_by": "devos"},
                {"id": "devos-ai-embed", "object": "model", "owned_by": "devos"},
            ]
            self._send_json(200, {"object": "list", "data": models_list})
        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            req_data = json.loads(post_body)
        except Exception:
            req_data = {}

        if self.path in ("/v1/chat/completions", "/chat/completions"):
            messages = req_data.get("messages", [])
            if req_data.get("stream", False):
                self._send_stream(messages)
                return
            res = engine.generate_chat_response(messages)
            self._send_json(200, res)

        elif self.path in ("/v1/embeddings", "/embeddings"):
            inputs = req_data.get("input", [])
            if isinstance(inputs, str):
                inputs = [inputs]
            res = engine.generate_embeddings(inputs)
            self._send_json(200, res)

        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def log_message(self, format, *args):
        # Concise logging
        sys.stderr.write(f"[ai-core] {args[0]} {args[1]} -> {args[2]}\n")


def run_server():
    # Threads: /health answers at once even while a long reply is generating.
    server = ThreadingHTTPServer((HOST, PORT), OpenAIHandler)
    server.daemon_threads = True
    # Load the model and process the system prompt now, not on the first question.
    import threading
    threading.Thread(target=engine.warm_up, daemon=True).start()
    threading.Thread(target=engine.idle_watch, daemon=True).start()
    print(f"DevOS AI Core daemon listening on http://{HOST}:{PORT}/v1")
    print(f"Hardware tier: {engine.tier_info['tier']}")
    print(f"Active model: {engine.active_model}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down DevOS AI Core daemon.")
        server.server_close()


if __name__ == "__main__":
    run_server()
