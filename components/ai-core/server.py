#!/usr/bin/env python3
"""
DevOS Local AI Inference Server (ai-core)
Provides an offline OpenAI-compatible HTTP service on 127.0.0.1:11434.
Zero external dependencies required (uses built-in http.server & json).

Speed is chosen from this PC: prompt processing uses every thread, replies use
one thread per physical core, and flash attention plus a compact KV cache are
turned on when this build of the engine accepts them. Docs: GET /docs.
"""

import sys
import os
import re
import time
import math
import json
import uuid
import html
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, List, Optional, Tuple
from hardware_detector import HardwareDetector
import model_catalog


HOST = "127.0.0.1"
PORT = int(os.environ.get("DEVOS_AI_PORT") or 11434)
# "devos-ai-models api lan on" opens the API to phones and PCs on the same
# network (0.0.0.0); those callers must send "Authorization: Bearer <key>".
API_CONF = "/etc/devos/ai-api.conf"
API_SETTINGS = {"listen": "local", "key": ""}


def read_api_conf(path: str = API_CONF) -> Dict[str, str]:
    conf = {"listen": "local", "key": ""}
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.partition("=")
                if key.strip() in conf:
                    conf[key.strip()] = value.strip()
    except OSError:
        pass
    # Network mode without a real key would let anyone on the Wi-Fi use the PC's AI.
    if conf["listen"] != "lan" or len(conf["key"]) < 16:
        conf["listen"] = "local"
    return conf


def is_loopback(address: str) -> bool:
    return address in ("::1", "::ffff:127.0.0.1") or address.startswith("127.")


def request_allowed(client_ip: str, auth_header: str, conf: Dict[str, str]) -> bool:
    """Apps on this PC never need a key; anything from the network does."""
    if is_loopback(client_ip):
        return True
    if conf.get("listen") != "lan" or not conf.get("key"):
        return False
    import hmac
    given = (auth_header or "").strip()
    if given.lower().startswith("bearer "):
        given = given[7:].strip()
    return hmac.compare_digest(given.encode(), conf["key"].encode())


import threading


class EngineBusy(Exception):
    """Every slot is busy and the waiting line is full (or waited too long)."""


class _Slot:
    """One loaded copy of a model with its own working memory (KV cache).

    Several agents (DevOS AI window, VS Code, Optimizer, scripts using the API)
    each get a slot, so one long answer no longer makes the others hang. The
    copies share the model file through the page cache (mmap): a second slot
    costs only its working memory, not another copy of the weights."""

    def __init__(self, index: int):
        self.index = index
        self.llm = None
        self.kind = "chat"
        self.load_tried = False
        self.lock = threading.RLock()
        self.busy = False
        self.last_used = time.time()


def clamp_tokens(value) -> int:
    """Callers may ask for longer answers (the code agent writes whole files),
    within what a local model finishes in reasonable time."""
    try:
        return max(16, min(2048, int(value)))
    except (TypeError, ValueError):
        return 1024


def parallel_slots(ram_gb: float, threads: int, configured: int = 0) -> int:
    """How many questions DevOS AI answers at the same time on this PC.

    Each slot gets its own processor threads; splitting a 4-thread laptop would
    make every answer slower, so small PCs answer one at a time (the others
    wait in line, and /health keeps answering)."""
    if configured > 0:
        return max(1, min(8, configured))
    if threads < 6 or ram_gb < 7.5:
        return 1
    if threads < 12 or ram_gb < 15.5:
        return 2
    return max(2, min(4, threads // 4))


def configured_parallel(path: str = "/etc/devos/ai.conf") -> int:
    value = os.environ.get("DEVOS_AI_PARALLEL", "")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                key, _, val = line.partition("=")
                if key.strip() == "parallel":
                    value = val.strip()
    except OSError:
        pass
    try:
        return int(value)
    except ValueError:
        return 0


def configured_idle_timeout(path: str = "/etc/devos/ai.conf") -> int:
    value = os.environ.get("DEVOS_AI_IDLE_TIMEOUT", "")
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                key, _, val = line.partition("=")
                if key.strip() in ("idle_timeout", "timeout"):
                    value = val.strip()
    except OSError:
        pass
    try:
        return int(value)
    except ValueError:
        return 0


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def physical_cores(logical: int) -> int:
    """Real cores, not hyperthreads. Reply generation is limited by memory
    bandwidth, so a second thread on the same core usually does not help."""
    ids = set()
    base = "/sys/devices/system/cpu"
    try:
        for name in os.listdir(base):
            if len(name) < 4 or not name.startswith("cpu") or not name[3:].isdigit():
                continue
            with open(os.path.join(base, name, "topology", "core_id"), encoding="utf-8") as handle:
                ids.add(int(handle.read().strip()))
    except (OSError, ValueError):
        ids = set()
    if ids:
        return max(1, min(len(ids), logical))
    return max(1, logical)


def fast_mode(fast: Optional[bool] = None) -> bool:
    """Compact KV cache and flash attention. DEVOS_AI_FAST=0 keeps the slower,
    full-precision cache for builds that misbehave with the fast flags."""
    if fast is not None:
        return bool(fast)
    return os.environ.get("DEVOS_AI_FAST", "1").strip().lower() not in ("0", "no", "off", "false")


def thread_plan(logical: int, physical: int, parallel: int) -> Tuple[int, int]:
    """(generation threads, prompt threads) for one slot.

    Prompt processing scales with threads. Token generation does not, past one
    thread per physical core, and two slots must not each grab every core.
    """
    logical = max(1, logical)
    physical = max(1, min(physical, logical))
    slots = max(1, parallel)
    if slots <= 1:
        gen = min(12, physical)
    else:
        gen = min(12, max(4, (physical * 3) // max(2, slots + 1)))
    batch = max(gen, logical)
    gen = max(1, min(_int_env("DEVOS_AI_THREADS", gen), logical))
    batch = max(gen, min(_int_env("DEVOS_AI_BATCH_THREADS", batch), logical))
    return gen, batch


def llama_speed_kwargs(kind: str, ram_gb: float, parallel: int, gpu_layers: int,
                       logical: Optional[int] = None, physical: Optional[int] = None,
                       fast: Optional[bool] = None) -> Dict[str, Any]:
    """Arguments for llama.cpp that make this PC answer sooner.

    Chat stays at 2048 tokens of context (a 4 GB laptop cannot spare more).
    Coding gets 8192. n_batch is how much of a long prompt is read per pass.
    """
    logical = logical if logical is not None else (os.cpu_count() or 2)
    physical = physical if physical is not None else physical_cores(logical)
    gen, batch = thread_plan(logical, physical, parallel)
    gpu_layers = max(0, int(gpu_layers))
    ctx = 8192 if kind == "code" else (4096 if ram_gb >= 15.5 else 2048)
    if kind == "embedding":
        ctx = 2048
    n_batch = 2048 if batch >= 16 and ram_gb >= 16 else (1024 if batch >= 8 and ram_gb >= 8 else 512)
    n_batch = min(n_batch, ctx)
    kwargs = {
        "n_ctx": ctx,
        "n_threads": gen,
        "n_threads_batch": batch,
        "n_batch": n_batch,
        "n_ubatch": min(512, n_batch),
        "n_gpu_layers": gpu_layers,
        "use_mmap": True,
        # Locking a multi-GB file on a 32 GB PC (reported ~31.1 GB) keeps it locked in RAM with 0 cold-start latency.
        "use_mlock": ram_gb >= 24 and gpu_layers == 0,
        "verbose": False,
    }
    if fast_mode(fast):
        kwargs["flash_attn"] = True
        if gpu_layers > 0:
            kwargs["offload_kqv"] = True
        else:
            # GGML_TYPE_Q8_0. About half the working memory of f16, and less
            # memory traffic per token, which is what limits CPU speed.
            kwargs["type_k"] = 8
            kwargs["type_v"] = 8
    return kwargs


def _unexpected_keyword(exc: BaseException, keys) -> Optional[str]:
    match = re.search(r"unexpected keyword argument '(\w+)'", str(exc))
    if match and match.group(1) in keys and match.group(1) != "model_path":
        return match.group(1)
    return None


def open_llama(llama_cls, path: str, kwargs: Dict[str, Any]):
    """Load the model. Drop speed flags this build does not know, and retry
    on the processor when the GPU backend refuses the file."""
    attempt = dict(kwargs)
    attempt["model_path"] = path
    dropped = []
    tried_cpu = False
    tried_plain = False
    while True:
        try:
            return llama_cls(**attempt), dropped
        except TypeError as exc:
            key = _unexpected_keyword(exc, attempt)
            if not key:
                raise
            attempt.pop(key, None)
            dropped.append(key)
        except Exception as exc:
            if attempt.get("n_gpu_layers", 0) > 0 and not tried_cpu:
                tried_cpu = True
                attempt["n_gpu_layers"] = 0
                attempt.pop("offload_kqv", None)
                dropped.append("n_gpu_layers")
                sys.stderr.write(f"[ai-core] GPU offload failed ({exc}); using the processor.\n")
                continue
            fast_keys = [k for k in ("flash_attn", "type_k", "type_v", "use_mlock") if k in attempt]
            if fast_keys and not tried_plain:
                tried_plain = True
                for key in fast_keys:
                    attempt.pop(key, None)
                    dropped.append(key)
                sys.stderr.write(f"[ai-core] fast load failed ({exc}); loading with standard settings.\n")
                continue
            raise


def call_completion(llm, **kwargs):
    """create_chat_completion, dropping sampling fields this build does not accept,
    and automatically adjusting max_tokens if prompt + completion exceeds the context window."""
    while True:
        try:
            return llm.create_chat_completion(**kwargs)
        except TypeError as exc:
            key = _unexpected_keyword(exc, kwargs)
            if not key:
                raise
            kwargs.pop(key, None)
        except ValueError as exc:
            msg = str(exc)
            m = re.search(r"Requested tokens \((\d+)\) exceed(?:s)? context window of (\d+)", msg, re.I)
            if m:
                requested, limit = int(m.group(1)), int(m.group(2))
                cur_max = kwargs.get("max_tokens") or 1024
                excess = requested - limit
                if cur_max - excess >= 64:
                    kwargs["max_tokens"] = max(64, cur_max - excess - 16)
                    continue
                msgs = kwargs.get("messages")
                if isinstance(msgs, list) and len(msgs) > 2:
                    for i, item in enumerate(msgs):
                        if item.get("role") != "system":
                            msgs.pop(i)
                            break
                    kwargs["max_tokens"] = min(limit // 2, max(64, cur_max))
                    continue
            raise


def sampling_kwargs(req: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """OpenAI sampling fields, clamped so a client cannot stall the PC."""
    req = req or {}

    def fnum(key, default, lo, hi):
        if req.get(key) is None:
            return default
        try:
            return max(lo, min(hi, float(req[key])))
        except (TypeError, ValueError):
            return default

    opts = {"temperature": fnum("temperature", 0.3, 0.0, 2.0)}
    if req.get("top_p") is not None:
        opts["top_p"] = fnum("top_p", 0.9, 0.05, 1.0)
    if req.get("repeat_penalty") is not None:
        opts["repeat_penalty"] = fnum("repeat_penalty", 1.05, 1.0, 2.0)
    if req.get("top_k") is not None:
        try:
            opts["top_k"] = max(0, min(200, int(req["top_k"])))
        except (TypeError, ValueError):
            pass
    stop = req.get("stop")
    if isinstance(stop, str) and stop:
        opts["stop"] = [stop[:200]]
    elif isinstance(stop, list):
        opts["stop"] = [str(item)[:200] for item in stop[:8] if item]
    if req.get("seed") is not None:
        try:
            opts["seed"] = int(req["seed"])
        except (TypeError, ValueError):
            pass
    return opts


class _CpuBoost:
    """While a reply is generating, leave powersave so the first tokens are
    not waiting on a CPU that has been idle. Restored when the last reply ends.
    Skipped when the governor is not writable (normal for a non-root test)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._depth = 0
        self._saved = []

    @staticmethod
    def _paths():
        root = "/sys/devices/system/cpu"
        found = []
        try:
            names = os.listdir(root)
        except OSError:
            return found
        for name in names:
            if not name.startswith("cpu") or not name[3:].isdigit():
                continue
            path = os.path.join(root, name, "cpufreq", "scaling_governor")
            if os.path.isfile(path):
                found.append(path)
        return found

    def enter(self):
        with self._lock:
            self._depth += 1
            if self._depth != 1:
                return
            saved = []
            for path in self._paths():
                try:
                    with open(path, encoding="utf-8") as handle:
                        current = handle.read().strip()
                    if not current or current == "performance":
                        continue
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write("performance")
                    saved.append((path, current))
                except OSError:
                    continue
            self._saved = saved

    def leave(self):
        with self._lock:
            self._depth = max(0, self._depth - 1)
            if self._depth != 0:
                return
            for path, current in self._saved:
                try:
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write(current)
                except OSError:
                    pass
            self._saved = []


cpu_boost = _CpuBoost()


def mem_available_mb() -> int:
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return 1 << 20


class DevOSAIEngine:
    """Inference engine controller with memory governor and mock/llama backend."""

    # Free memory needed before an extra slot loads (its working memory plus
    # headroom); below that, extra questions wait for a busy slot instead.
    EXTRA_SLOT_MIN_FREE_MB = 1024
    EXTRA_SLOT_IDLE_SECONDS = 120

    def __init__(self):
        self.tier_info = HardwareDetector.evaluate_tier()
        # Public name in the API (/health, /v1/models, replies). The real file
        # is kept in _model_file; users and apps only ever see "devos-ai".
        self.active_model = "devos-ai"
        ram = float(self.tier_info.get("ram_gb") or 4)
        conf_timeout = configured_idle_timeout()
        if conf_timeout > 0:
            self.idle_timeout_seconds = conf_timeout
        elif ram >= 24.0:
            self.idle_timeout_seconds = 86400 * 7  # 7 days (never unload during normal usage on 32GB RAM)
        elif ram >= 15.5:
            self.idle_timeout_seconds = 86400      # 24 hours on 16GB+ RAM
        elif ram >= 7.5:
            self.idle_timeout_seconds = 3600       # 1 hour on 8GB+ RAM
        else:
            self.idle_timeout_seconds = 300        # 5 min on small memory (<8GB) systems
        self.last_activity = time.time()
        self.is_loaded = False
        self._model_file = None
        self.tokens_generated = 0
        self.start_time = time.time()
        self.parallel = parallel_slots(ram, os.cpu_count() or 2, configured_parallel())
        self._slots = [_Slot(i) for i in range(self.parallel)]
        self._cond = threading.Condition()
        self._waiting = 0
        self.max_waiting = 32
        self.wait_timeout_seconds = 600

    # Slot 0 is the always-first slot; these keep the older single-model
    # names working for callers and tests.
    @property
    def _llm(self):
        return self._slots[0].llm

    @_llm.setter
    def _llm(self, value):
        self._slots[0].llm = value

    @property
    def _lock(self):
        return self._slots[0].lock

    @property
    def _load_tried(self):
        return self._slots[0].load_tried

    @_load_tried.setter
    def _load_tried(self, value):
        self._slots[0].load_tried = value

    @property
    def _loaded_kind(self):
        return self._slots[0].kind

    def status(self) -> Dict[str, Any]:
        return {
            "parallel": self.parallel,
            "busy": sum(1 for s in self._slots if s.busy),
            "loaded": sum(1 for s in self._slots if s.llm is not None),
            "waiting": self._waiting,
        }

    # ---------------------------------------------------------- slots
    def _slot_may_load(self, slot: _Slot) -> bool:
        if slot.index == 0 or slot.llm is not None:
            return True
        return mem_available_mb() >= self.EXTRA_SLOT_MIN_FREE_MB

    def _pick(self, kind: str):
        free = [s for s in self._slots if not s.busy]
        for test in (lambda s: s.llm is not None and s.kind == kind,
                     lambda s: s.llm is None and self._slot_may_load(s),
                     lambda s: s.llm is not None):
            for slot in free:
                if test(slot):
                    return slot
        return None

    def _acquire(self, kind: str) -> _Slot:
        deadline = time.time() + self.wait_timeout_seconds
        with self._cond:
            if self._waiting >= self.max_waiting:
                raise EngineBusy()
            self._waiting += 1
            try:
                while True:
                    slot = self._pick(kind)
                    if slot is not None:
                        slot.busy = True
                        return slot
                    left = deadline - time.time()
                    if left <= 0:
                        raise EngineBusy()
                    self._cond.wait(min(left, 5))
            finally:
                self._waiting -= 1

    def _release(self, slot: _Slot) -> None:
        with self._cond:
            slot.busy = False
            slot.last_used = time.time()
            self._cond.notify_all()

    def _gpu_layers(self) -> int:
        if "DEVOS_GPU_LAYERS" in os.environ:
            try:
                return max(0, int(os.environ["DEVOS_GPU_LAYERS"]))
            except ValueError:
                return 0
        backend = (self.tier_info.get("gpu") or {}).get("backend")
        if backend in ("cuda", "rocm", "vulkan"):
            try:
                return max(0, int((self.tier_info.get("models") or {}).get("gpu_layers") or 0))
            except (TypeError, ValueError):
                return 0
        return 0

    def speed_kwargs(self, kind: str = "chat") -> Dict[str, Any]:
        ram = float(self.tier_info.get("ram_gb") or 4)
        return llama_speed_kwargs(kind, ram, self.parallel, self._gpu_layers())

    def speed_info(self) -> Dict[str, Any]:
        """What this PC will use. Safe to call before a model file is loaded."""
        kw = self.speed_kwargs("chat")
        code = self.speed_kwargs("code")
        return {
            "threads": kw["n_threads"],
            "prompt_threads": kw["n_threads_batch"],
            "batch": kw["n_batch"],
            "context": kw["n_ctx"],
            "code_context": code["n_ctx"],
            "code_batch": code["n_batch"],
            "flash_attention": bool(kw.get("flash_attn")),
            "kv_cache": "q8_0" if kw.get("type_k") == 8 else "f16",
            "gpu_layers": kw["n_gpu_layers"],
            "parallel": self.parallel,
            "mlock": bool(kw.get("use_mlock")),
        }

    def _threads_per_slot(self) -> int:
        return self.speed_info()["threads"]

    @staticmethod
    def kind_for(model_name: str) -> str:
        return "code" if "code" in (model_name or "").lower() else "chat"

    def generate_chat_response(self, messages: List[Dict[str, str]], stream: bool = False,
                               model: str = "devos-ai", max_tokens: int = 1024,
                               options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Answer from the local GGUF when it is installed."""
        self.last_activity = time.time()
        user_prompt = ""
        for m in messages:
            if m.get("role") == "user":
                user_prompt = m.get("content", "")

        started = time.time()
        kind = self.kind_for(model)
        slot = self._acquire(kind)
        cpu_boost.enter()
        try:
            with slot.lock:
                self._load(slot, kind)
                if slot.llm is not None:
                    reply_content, usage = self._complete_on(slot, messages, max_tokens, options)
                else:
                    reply_content = self._reason(user_prompt)
                    usage = {}
                loaded = slot.llm is not None
        finally:
            cpu_boost.leave()
            self._release(slot)
        elapsed = max(time.time() - started, 0.001)
        prompt_tokens = int(usage.get("prompt_tokens") or (len(user_prompt.split()) + 15))
        completion_tokens = int(usage.get("completion_tokens") or len(reply_content.split()))
        self.tokens_generated += completion_tokens

        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "devos-ai-code" if self.kind_for(model) == "code" else self.active_model,
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
            "model_loaded": loaded,
            "tokens_per_sec": round(completion_tokens / elapsed, 2),
        }

    def generate_embeddings(self, inputs: List[str]) -> Dict[str, Any]:
        """Generates embedding vectors for local RAG."""
        self.last_activity = time.time()
        data = []
        embed_model_path = self._find_model("embedding")
        llm_embed = None
        if embed_model_path:
            try:
                from llama_cpp import Llama
                if not hasattr(self, "_embed_llm") or self._embed_llm is None:
                    embed_kw = self.speed_kwargs("embedding")
                    self._embed_llm, _dropped = open_llama(Llama, embed_model_path, {
                        "embedding": True,
                        "n_ctx": embed_kw["n_ctx"],
                        "n_threads": embed_kw["n_threads"],
                        "n_threads_batch": embed_kw["n_threads_batch"],
                        "n_batch": embed_kw["n_batch"],
                        "use_mmap": True,
                        "verbose": False,
                    })
                llm_embed = self._embed_llm
            except Exception:
                llm_embed = None

        for idx, text in enumerate(inputs):
            vector = None
            if llm_embed is not None:
                try:
                    res = llm_embed.create_embedding(text)
                    raw_vec = res["data"][0]["embedding"]
                    if len(raw_vec) >= 384:
                        vector = raw_vec[:384]
                    else:
                        vector = raw_vec + [0.0] * (384 - len(raw_vec))
                except Exception:
                    vector = None

            if vector is None:
                # Semantic n-gram dense feature embedding with unit normalization (384 dims)
                words = text.lower().split()
                vec = [0.0] * 384
                for w in words:
                    h1 = sum(ord(c) * (31 ** i) for i, c in enumerate(w[:8])) % 384
                    h2 = sum(ord(c) for c in w) % 384
                    vec[h1] += 1.0
                    vec[h2] += 0.5
                for i in range(len(words) - 1):
                    bg = words[i] + "_" + words[i + 1]
                    h_bg = sum(ord(c) * 17 for c in bg) % 384
                    vec[h_bg] += 1.5
                mag = math.sqrt(sum(v * v for v in vec)) or 1.0
                vector = [round(v / mag, 6) for v in vec]

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

    def _candidate_names(self, kind: str = "chat") -> List[str]:
        if kind == "embedding":
            return [
                self.tier_info["models"].get("embed_file", ""),
                "nomic-embed-text-v1.5.Q4_K_M.gguf",
                "bge-m3-q4_k_m.gguf",
            ]
        choice = model_catalog.read_choice()
        if kind == "code":
            # The coding model when it was downloaded, else the chat model.
            names = [model_catalog.coder_for(choice["chat"])["file"]]
            names += [m["file"] for m in model_catalog.CODER_MODELS.values() if m["file"] not in names]
            return names + self._candidate_names("chat")
        # The model picked in the installer (or DevOS AI Models) first. Then the
        # biggest other one on disk that fits in memory, in any folder:
        # "Smarter DevOS AI" (1.5B) still wins over the built-in tiny model.
        chosen = model_catalog.chat_model(choice["chat"])
        names = [chosen["file"]] if chosen else []
        ram = float(self.tier_info.get("ram_gb") or 0) or 64.0
        for model in reversed(model_catalog.CHAT_MODELS):
            if model["file"] not in names and ram + 0.5 >= model["min_ram_gb"]:
                names.append(model["file"])
        names.append(self.tier_info["models"].get("chat_file", ""))
        return names

    def _find_model(self, kind: str = "chat"):
        for name in self._candidate_names(kind):
            if not name:
                continue
            for directory in self._model_dirs():
                if not directory:
                    continue
                path = os.path.join(directory, name)
                if os.path.isfile(path) and os.path.getsize(path) > 100_000_000:
                    return path
        return None

    def _ensure_model(self, kind: str = "chat"):
        self._load(self._slots[0], kind)

    def _load(self, slot: _Slot, kind: str = "chat"):
        """Load the model for `kind` into this slot (caller holds slot.lock)."""
        if kind != slot.kind:
            # A slot holds one model; switching chat <-> code swaps it.
            slot.llm = None
            slot.load_tried = False
            slot.kind = kind
        if slot.llm is not None or slot.load_tried:
            return
        slot.load_tried = True
        path = self._find_model(kind)
        if not path:
            return
        try:
            from llama_cpp import Llama

            # Chat stays at 2048 tokens: 4096 doubled the working memory on a
            # 4 GB laptop. Coding (DevOS Code Agent, VS Code) reads whole files,
            # so it gets 8192; it is only offered on PCs with 8 GB or more.
            # use_mmap: slots share one copy of the weights.
            profile = self.speed_kwargs(kind)
            slot.llm, dropped = open_llama(Llama, path, profile)
            if dropped:
                sys.stderr.write("[ai-core] loaded without: " + ", ".join(dropped) + "\n")
            self._loaded_speed = dict(profile)
            # Reuse the processed system prompt between questions. It is the
            # same text every time (see devos_identity_prompt), so only the
            # new question has to be read; on a 2-core PC that saved seconds.
            try:
                from llama_cpp import LlamaRAMCache
                slot.llm.set_cache(LlamaRAMCache(capacity_bytes=(128 if kind == "code" else 64) << 20))
            except Exception as exc:
                sys.stderr.write(f"[ai-core] prompt cache unavailable: {exc}\n")
            self._model_file = path
            self.active_model = "devos-ai"
            self.is_loaded = True
            if slot.index:
                sys.stderr.write(f"[ai-core] slot {slot.index} loaded for parallel requests\n")
        except Exception as exc:
            sys.stderr.write(f"[ai-core] model did not load: {exc}\n")
            slot.llm = None

    def unload_if_idle(self) -> bool:
        """Give the model's memory back when nobody has asked anything for a
        while. It held 1.6-2.7 GB for hours, and on a 4 GB laptop that made
        Android and Chrome get killed. The file is memory-mapped, so loading it
        again on the next question takes about a second. Extra slots (parallel
        agents) are freed sooner than the first one."""
        now = time.time()
        freed = False
        for slot in self._slots:
            if slot.llm is None:
                continue
            if slot.index == 0:
                idle = now - self.last_activity >= self.idle_timeout_seconds
            else:
                idle = now - slot.last_used >= min(self.EXTRA_SLOT_IDLE_SECONDS, self.idle_timeout_seconds)
            if not idle or slot.busy or not slot.lock.acquire(blocking=False):
                continue  # answering right now
            try:
                slot.llm = None
                slot.load_tried = False
                freed = True
            finally:
                slot.lock.release()
        if freed:
            self.is_loaded = any(s.llm is not None for s in self._slots)
            import gc
            gc.collect()
            try:
                import ctypes
                ctypes.CDLL("libc.so.6").malloc_trim(0)  # hand freed pages back to the system
            except Exception:
                pass
        return freed

    def idle_watch(self):
        while True:
            time.sleep(30)
            if self.unload_if_idle():
                sys.stderr.write("[ai-core] idle: model unloaded to free memory\n")

    def warm_up(self):
        """Load the model and process the system prompt at service start, so
        the first question does not pay for it."""
        try:
            slot = self._slots[0]
            with slot.lock:
                self._load(slot, "chat")
                if slot.llm is None:
                    return
                slot.llm.create_chat_completion(
                    messages=self._build_chat([{"role": "user", "content": "Hi"}]),
                    max_tokens=1,
                    temperature=0.0
                )
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
        total_chars = sum(len(m.get("content") or "") for m in chat)
        max_chars = 12000 if (ram and ram >= 15.5) else 5000
        if total_chars > max_chars and len(chat) > 2:
            for msg in chat[1:-1]:
                c = msg.get("content") or ""
                if len(c) > 400:
                    msg["content"] = c[:400] + "..."
        return chat

    def _complete(self, messages: List[Dict[str, str]]) -> str:
        text, _usage = self._complete_on(self._slots[0], messages)
        return text

    def _complete_on(self, slot: _Slot, messages: List[Dict[str, str]], max_tokens: int = 1024,
                     options: Optional[Dict[str, Any]] = None):
        chat = self._build_chat(messages)
        if not any(item["role"] == "user" for item in chat):
            return "Ask a question and I will answer from the model on this computer.", {}
        opts = dict(options or {})
        opts.setdefault("temperature", 0.3)
        try:
            with slot.lock:
                result = call_completion(
                    slot.llm,
                    messages=chat,
                    max_tokens=clamp_tokens(max_tokens),
                    **opts,
                )
            text = result["choices"][0]["message"]["content"]
            text = (text or "").strip()
            # Small models sometimes answer like a transcript ("me: ...").
            text = re.sub(r"^\s*(?:me|you|user|assistant|ai|bot|devos ai)\s*:\s*", "", text, count=1, flags=re.I)
            usage = result.get("usage") or {}
            if text:
                return text, usage
        except Exception as exc:
            sys.stderr.write(f"[ai-core] generation failed: {exc}\n")
        return "The local model is installed, but it did not produce an answer. Ask again.", {}

    def stream_chat(self, messages: List[Dict[str, str]], model: str = "devos-ai", max_tokens: int = 1024,
                    options: Optional[Dict[str, Any]] = None):
        """Yield the answer in small pieces as the model writes it, so the
        window shows words within a second instead of after the whole reply."""
        self.last_activity = time.time()
        kind = self.kind_for(model)
        try:
            slot = self._acquire(kind)
        except EngineBusy:
            yield "DevOS AI is busy answering other apps right now. Please ask again in a moment."
            return
        opts = dict(options or {})
        opts.setdefault("temperature", 0.3)
        cpu_boost.enter()
        try:
            with slot.lock:
                self._load(slot, kind)
                if slot.llm is None:
                    user_prompt = next((m.get("content", "") for m in reversed(messages)
                                        if m.get("role") == "user"), "")
                    yield self._reason(user_prompt)
                    return
                chat = self._build_chat(messages)
                try:
                    for chunk in call_completion(
                            slot.llm, messages=chat, max_tokens=clamp_tokens(max_tokens), stream=True, **opts):
                        delta = chunk["choices"][0].get("delta", {}).get("content")
                        if delta:
                            yield delta
                except Exception as exc:
                    sys.stderr.write(f"[ai-core] generation failed: {exc}\n")
                    if "exceed" in str(exc).lower() and len(chat) > 2:
                        try:
                            truncated_chat = [chat[0], chat[-1]]
                            for chunk in call_completion(
                                    slot.llm, messages=truncated_chat, max_tokens=min(512, clamp_tokens(max_tokens)), stream=True, **opts):
                                delta = chunk["choices"][0].get("delta", {}).get("content")
                                if delta:
                                    yield delta
                            return
                        except Exception:
                            pass
                    yield "The local model did not produce an answer. Ask again."
        finally:
            cpu_boost.leave()
            self._release(slot)


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


# The only DevOS team contact details the AI may give; the model once made up
# a LinkedIn URL. Same list as ABOUT_TEXT in components/assistant/tools.py.
DEVOS_CONTACTS = (
    "email devos@imrandev.bd; contact form https://imrandev.bd/contact; "
    "WhatsApp https://wa.me/+8801576918420; GitHub https://github.com/imranbru99; "
    "LinkedIn https://linkedin.com/in/imranbru99"
)


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
        "Contact details of the DevOS team (give exactly these when asked how to contact or reach "
        "the team or Imran, and never invent any other email, phone, URL or profile): " + DEVOS_CONTACTS + ". "
        "You run entirely on this computer: nothing the user types is sent to the internet. "
        "You are not Claude, ChatGPT, Gemini, Copilot or any other cloud service, and you were not made by "
        "Anthropic, OpenAI, Google, Microsoft or Alibaba; never say you are. "
        "If asked which model you are, say you are DevOS AI, the on-device model that ships with DevOS, "
        "built on open-source language-model technology and tuned for DevOS. "
        "You help with DevOS itself: Windows apps (.exe and .msi files open directly in DevOS, just "
        "double-click them), Android apps (.apk files open in the DevOS Android window after a one-time "
        "download), installing and uninstalling apps (DevOS AI can do it when you ask, and DevOS Features "
        "lists every app), keeping the PC fast (DevOS Optimizer cleans temporary files and points out unused apps), "
        "files, Wi-Fi, printers and coding. "
        "Talk about DevOS, not about the software it is built from. "
        "Never invent DevOS menus, buttons or step-by-step instructions you are not sure of: to add or "
        "remove apps, point to DevOS Features (Start menu) or the Apps window, and say plainly when "
        "something cannot work on DevOS (for example Microsoft Store-only apps). "
        "Answer directly and briefly, in the user's language. Do not greet unless the user greeted you. "
        "Write only your reply: never start with a speaker label such as 'me:', 'AI:' or 'DevOS AI:'."
        + hardware
    )


engine = DevOSAIEngine()


PUBLIC_MODELS = [
    {"id": "devos-ai", "object": "model", "owned_by": "devos",
     "description": "Chat, writing and help with this PC. Uses the model installed for this computer."},
    {"id": "devos-ai-code", "object": "model", "owned_by": "devos",
     "description": "Coding. Uses the coding model when it is installed, otherwise the chat model."},
    {"id": "devos-ai-embed", "object": "model", "owned_by": "devos",
     "description": "Embeddings, 384 numbers per text, for search over your own files."},
]

_DOC_FALLBACK = """# DevOS Local AI

Base URL: http://127.0.0.1:11434/v1

Models: `devos-ai` (chat), `devos-ai-code` (code), `devos-ai-embed` (embeddings).

Endpoints:

- POST /v1/chat/completions
- POST /v1/completions
- POST /v1/embeddings
- GET /v1/models
- GET /health
- GET /openapi.json

No API key is required from this PC. The full reference ships as API.md next to this service and as docs/LOCAL_AI.md in the DevOS source tree.
"""


def api_doc_text() -> str:
    """The local-model reference. Prefers the copy installed with the service."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.environ.get("DEVOS_AI_DOCS", ""),
        os.path.join(here, "API.md"),
        "/usr/share/doc/devos/LOCAL_AI.md",
        os.path.abspath(os.path.join(here, "..", "..", "docs", "LOCAL_AI.md")),
    ]
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read().strip()
        except OSError:
            continue
        if text:
            return text + "\n"
    return _DOC_FALLBACK


def docs_html(markdown: str) -> str:
    body = html.escape(markdown)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DevOS Local AI</title>
<style>
  body {{ margin: 0; background: #0e141b; color: #e8eef4; font: 16px/1.55 "Segoe UI", sans-serif; }}
  main {{ max-width: 52rem; margin: 0 auto; padding: 2rem 1.25rem 4rem; }}
  h1 {{ font-size: 1.6rem; margin: 0 0 0.25rem; }}
  p.lead {{ color: #9fb0c0; margin-top: 0; }}
  a {{ color: #8ec8ff; }}
  pre {{ white-space: pre-wrap; background: #17202a; border-radius: 10px; padding: 1.1rem 1.25rem; }}
</style>
</head>
<body>
<main>
  <h1>DevOS Local AI</h1>
  <p class="lead">On-device model. OpenAI-compatible API at <a href="/v1">/v1</a>.
  Machine-readable spec: <a href="/openapi.json">openapi.json</a>.</p>
  <pre>{body}</pre>
</main>
</body>
</html>
"""


def api_index() -> Dict[str, Any]:
    return {
        "service": "DevOS AI",
        "openai": f"http://127.0.0.1:{PORT}/v1",
        "docs": f"http://127.0.0.1:{PORT}/docs",
        "openapi": f"http://127.0.0.1:{PORT}/openapi.json",
        "models": [item["id"] for item in PUBLIC_MODELS],
        "endpoints": [
            "/v1/chat/completions",
            "/v1/completions",
            "/v1/embeddings",
            "/v1/models",
            "/health",
        ],
        "speed": engine.speed_info(),
        "auth": "No key from this PC. Other devices need Authorization: Bearer <key> after `devos models api lan on`.",
    }


def openapi_spec() -> Dict[str, Any]:
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "DevOS Local AI",
            "version": "1.0.0",
            "description": "OpenAI-compatible API for the on-device DevOS AI model. Requests stay on this PC.",
        },
        "servers": [{"url": f"http://127.0.0.1:{PORT}"}],
        "paths": {
            "/v1/chat/completions": {"post": {"summary": "Chat completion", "operationId": "chat"}},
            "/v1/completions": {"post": {"summary": "Text completion", "operationId": "complete"}},
            "/v1/embeddings": {"post": {"summary": "Embeddings", "operationId": "embed"}},
            "/v1/models": {"get": {"summary": "List models", "operationId": "models"}},
            "/health": {"get": {"summary": "Health and speed", "operationId": "health"}},
            "/docs": {"get": {"summary": "Documentation", "operationId": "docs"}},
        },
        "components": {
            "securitySchemes": {
                "bearer": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Required only for callers that are not on this PC.",
                }
            }
        },
    }


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

    def _route(self) -> str:
        return self.path.split("?", 1)[0].rstrip("/") or "/"

    def _model_name(self, model: str) -> str:
        return "devos-ai-code" if engine.kind_for(model) == "code" else engine.active_model

    def _send_bytes(self, status: int, body: str, content_type: str):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _send_stream(self, messages, model="devos-ai", max_tokens=1024, options=None, legacy=False):
        """OpenAI-style server-sent events: one small piece of text per event."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        chat_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        shown = self._model_name(model)

        def event(payload):
            self.wfile.write(b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n")
            self.wfile.flush()

        try:
            for piece in engine.stream_chat(messages, model, max_tokens, options):
                if legacy:
                    choice = {"index": 0, "text": piece, "finish_reason": None}
                    kind = "text_completion"
                else:
                    choice = {"index": 0, "delta": {"content": piece}, "finish_reason": None}
                    kind = "chat.completion.chunk"
                event({"id": chat_id, "object": kind, "created": int(time.time()),
                       "model": shown, "choices": [choice]})
            if legacy:
                done = {"index": 0, "text": "", "finish_reason": "stop"}
                kind = "text_completion"
            else:
                done = {"index": 0, "delta": {}, "finish_reason": "stop"}
                kind = "chat.completion.chunk"
            event({"id": chat_id, "object": kind, "created": int(time.time()),
                   "model": shown, "choices": [done]})
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

    def _authorized(self) -> bool:
        if request_allowed(self.client_address[0], self.headers.get("Authorization", ""), API_SETTINGS):
            return True
        self._send_json(401, {"error": {
            "message": "Send the DevOS AI API key as 'Authorization: Bearer <key>'. "
                       "Run 'devos-ai-models api' on the DevOS PC to see it.",
            "type": "invalid_api_key"}})
        return False

    def do_GET(self):
        path = self._route()
        # The reference and the discovery document contain no secrets.
        if path in ("/docs", "/v1/docs"):
            self._send_bytes(200, docs_html(api_doc_text()), "text/html; charset=utf-8")
            return
        if path == "/openapi.json":
            self._send_json(200, openapi_spec())
            return
        if not self._authorized():
            return
        if path in ("/", "/v1"):
            self._send_json(200, api_index())
            return
        if path in ("/health", "/v1/health"):
            self._send_json(200, {
                "status": "healthy",
                "tier": engine.tier_info["tier"],
                "active_model": engine.active_model,
                "uptime_seconds": round(time.time() - engine.start_time, 1),
                "slots": engine.status(),
                "speed": engine.speed_info(),
                "docs": f"http://127.0.0.1:{PORT}/docs",
            })
        elif path in ("/v1/models", "/models"):
            self._send_json(200, {"object": "list", "data": PUBLIC_MODELS})
        elif path.startswith("/v1/models/") or path.startswith("/models/"):
            name = path.rsplit("/", 1)[-1]
            found = next((item for item in PUBLIC_MODELS if item["id"] == name), None)
            if found:
                self._send_json(200, found)
            else:
                self._send_json(404, {"error": {"message": f"Unknown model '{name}'.", "type": "model_not_found"}})
        else:
            self._send_json(404, {"error": "Endpoint not found"})

    def _read_json(self) -> Dict[str, Any]:
        content_len = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            data = json.loads(post_body)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _finish_chat(self, req: Dict[str, Any], legacy: bool = False):
        if legacy:
            prompt = req.get("prompt") or ""
            if isinstance(prompt, list):
                prompt = "\n".join(str(part) for part in prompt)
            messages = [{"role": "user", "content": str(prompt)}]
        else:
            messages = req.get("messages") or []
        model = str(req.get("model") or "devos-ai")
        max_tokens = req.get("max_tokens") or req.get("max_completion_tokens") or 1024
        options = sampling_kwargs(req)
        if req.get("stream", False):
            self._send_stream(messages, model, max_tokens, options, legacy=legacy)
            return
        try:
            res = engine.generate_chat_response(messages, model=model, max_tokens=max_tokens, options=options)
        except EngineBusy:
            self._send_json(503, {"error": {"message": "DevOS AI is busy with other requests; retry shortly.",
                                            "type": "server_busy"}})
            return
        if legacy:
            text = res["choices"][0]["message"]["content"]
            res = {
                "id": "cmpl-" + res["id"].split("-", 1)[-1],
                "object": "text_completion",
                "created": res["created"],
                "model": res["model"],
                "choices": [{"text": text, "index": 0, "finish_reason": "stop"}],
                "usage": res["usage"],
            }
        self._send_json(200, res)

    def do_POST(self):
        if not self._authorized():
            return
        path = self._route()
        req_data = self._read_json()

        if path in ("/v1/chat/completions", "/chat/completions"):
            self._finish_chat(req_data)
        elif path in ("/v1/completions", "/completions"):
            self._finish_chat(req_data, legacy=True)
        elif path in ("/v1/embeddings", "/embeddings"):
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
    API_SETTINGS.update(read_api_conf())
    host = "0.0.0.0" if API_SETTINGS["listen"] == "lan" else HOST
    # Threads: /health answers at once even while a long reply is generating.
    server = ThreadingHTTPServer((host, PORT), OpenAIHandler)
    server.daemon_threads = True
    # Load the model and process the system prompt now, not on the first question.
    import threading
    threading.Thread(target=engine.warm_up, daemon=True).start()
    threading.Thread(target=engine.idle_watch, daemon=True).start()
    print(f"DevOS AI Core daemon listening on http://{host}:{PORT}/v1")
    print(f"Docs: http://{host}:{PORT}/docs")
    print(f"Hardware tier: {engine.tier_info['tier']}")
    print(f"Active model: {engine.active_model}")
    speed = engine.speed_info()
    print(f"Speed: {speed['prompt_threads']} prompt threads, {speed['threads']} reply threads, "
          f"kv {speed['kv_cache']}, gpu layers {speed['gpu_layers']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down DevOS AI Core daemon.")
        server.server_close()


if __name__ == "__main__":
    run_server()
