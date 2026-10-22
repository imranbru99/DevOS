#!/usr/bin/env python3
"""
Several answers at once from one local model.

On a CPU, writing text is limited by how fast the model's weights can be read from memory, not by
arithmetic: one stream of text reads all the weights for every word. Decoding several streams in one
batch reads them once per step for all of them, so on this PC four files are written at about 3.4 times the
speed of one (measured: 14.8 -> 50 tokens/s for the 3B coder).

BatchGenerator starts from a model that is already loaded (llama_cpp.Llama), shares its weights, reads the
common prompt ONCE, then writes every branch from it:

    BatchGenerator(llama).generate(prefix_messages, [{"id": "a", "prompt": "Write a.php"}, ...])

A branch ends at the end of the model's answer, at the closing ``` of the file it is writing, at its token
limit, or when it starts repeating itself. Events are reported as they happen (for streaming).
"""

import codecs
import ctypes
import time
import zlib
from typing import Any, Callable, Dict, List, Optional

import numpy as np

try:  # the module is importable without llama_cpp (tests of the pure parts)
    import llama_cpp as L
except Exception:  # pragma: no cover
    L = None

MAX_BRANCHES = 8
MAX_FILE_LINES = 450          # a single file longer than this is a loop, not a file
GGML_TYPE_Q8_0 = 8


# ----------------------------------------------------------------------------- pure helpers

def chatml(messages: List[Dict[str, str]], open_last_user: bool = False) -> str:
    """Qwen2.5's chat format. With open_last_user the final user message is left unterminated, so a
    branch can continue it with its own instruction."""
    out = []
    for i, m in enumerate(messages):
        last = i == len(messages) - 1
        out.append(f"<|im_start|>{m.get('role', 'user')}\n{m.get('content', '')}")
        if not (last and open_last_user and m.get("role") == "user"):
            out.append("<|im_end|>\n")
    return "".join(out)


def branch_suffix(prompt: str) -> str:
    return f"\n\n{prompt}<|im_end|>\n<|im_start|>assistant\n"


def closing_fence_end(text: str) -> Optional[int]:
    """Index just after the bare ``` that closes the fenced block `text` starts with (nested fenced
    blocks with a language are skipped), or None while it is still open."""
    stripped = text.lstrip()
    if not stripped.startswith("```"):
        return None
    offset = len(text) - len(stripped)
    depth = 0
    pos = 0
    first = True
    for line in stripped.splitlines(keepends=True):
        s = line.strip()
        if first:
            first = False                      # the opening fence line
        elif s.startswith("```"):
            if s == "```":
                if depth == 0:
                    return offset + pos + len(line)
                depth -= 1
            else:
                depth += 1
        pos += len(line)
    return None


def is_repeating(text: str) -> bool:
    if len(text) < 2500:
        return False
    tail = text[-3000:].encode("utf-8", "replace")
    return len(zlib.compress(tail)) < 0.09 * len(tail)


def sample(logits: np.ndarray, recent: List[int], temperature: float, top_p: float, top_k: int,
           repeat_penalty: float, rng: np.random.Generator) -> int:
    """Next token from one branch's logits: a small repeat penalty, then greedy or temperature/top-k/top-p."""
    if repeat_penalty and repeat_penalty != 1.0 and recent:
        ids = np.unique(np.asarray(recent[-64:], dtype=np.int64))
        vals = logits[ids]
        logits[ids] = np.where(vals > 0, vals / repeat_penalty, vals * repeat_penalty)
    if temperature <= 0.05:
        return int(logits.argmax())
    k = min(max(top_k, 1), logits.shape[0])
    idx = np.argpartition(logits, -k)[-k:]
    vals = logits[idx] / temperature
    vals -= vals.max()
    probs = np.exp(vals)
    probs /= probs.sum()
    order = np.argsort(-probs)
    idx, probs = idx[order], probs[order]
    if 0 < top_p < 1:
        keep = np.searchsorted(np.cumsum(probs), top_p) + 1
        idx, probs = idx[:keep], probs[:keep]
        probs = probs / probs.sum()
    return int(rng.choice(idx, p=probs))


class _Branch:
    __slots__ = ("id", "seq", "suffix", "pos", "next_token", "text", "tokens", "recent", "decoder", "reason")

    def __init__(self, bid: str, seq: int, suffix: List[int]):
        self.id = bid
        self.seq = seq
        self.suffix = suffix
        self.pos = 0
        self.next_token = 0
        self.text = ""
        self.tokens = 0
        self.recent: List[int] = []
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="ignore")
        self.reason = ""


# ----------------------------------------------------------------------------- the generator

class BatchGenerator:
    def __init__(self, llama, n_threads: Optional[int] = None, n_threads_batch: Optional[int] = None):
        if L is None:
            raise RuntimeError("llama_cpp is not available")
        self.llama = llama
        self.model = llama._model.model
        self.vocab = L.llama_model_get_vocab(self.model)
        self.n_vocab = L.llama_vocab_n_tokens(self.vocab)
        self.n_threads = n_threads or getattr(llama, "n_threads", 8)
        self.n_threads_batch = n_threads_batch or getattr(llama, "n_threads_batch", self.n_threads)

    # ---- model plumbing
    def _tokenize(self, text: str) -> List[int]:
        data = text.encode("utf-8")
        cap = len(data) + 16
        buf = (ctypes.c_int32 * cap)()
        n = L.llama_tokenize(self.vocab, data, len(data), buf, cap, False, True)
        if n < 0:
            cap = -n
            buf = (ctypes.c_int32 * cap)()
            n = L.llama_tokenize(self.vocab, data, len(data), buf, cap, False, True)
        return list(buf[:max(n, 0)])

    def _piece(self, token: int) -> bytes:
        buf = ctypes.create_string_buffer(64)
        n = L.llama_token_to_piece(self.vocab, token, buf, 64, 0, False)
        if n < 0:
            buf = ctypes.create_string_buffer(-n)
            n = L.llama_token_to_piece(self.vocab, token, buf, -n, 0, False)
        return buf.raw[:max(n, 0)]

    def _context(self, n_ctx: int, n_seq: int):
        cp = L.llama_context_default_params()
        cp.n_ctx = n_ctx
        cp.n_batch = 512
        cp.n_ubatch = 512
        cp.n_seq_max = n_seq
        cp.n_threads = self.n_threads
        cp.n_threads_batch = self.n_threads_batch
        cp.kv_unified = True                 # one pool: copying the shared prompt to every branch is free
        try:                                  # same speed settings as the server's own context
            cp.flash_attn_type = L.LLAMA_FLASH_ATTN_TYPE_ENABLED
            cp.type_k = GGML_TYPE_Q8_0
            cp.type_v = GGML_TYPE_Q8_0
        except Exception:
            pass
        ctx = L.llama_init_from_model(self.model, cp)
        if not ctx:                           # fall back to the plain settings
            cp.flash_attn_type = L.LLAMA_FLASH_ATTN_TYPE_AUTO
            cp.type_k = cp.type_v = 1
            ctx = L.llama_init_from_model(self.model, cp)
        if not ctx:
            raise RuntimeError("could not create a batch context (not enough memory?)")
        return ctx

    @staticmethod
    def _fill(batch, items) -> None:
        batch.n_tokens = len(items)
        for i, (tok, pos, seq, want) in enumerate(items):
            batch.token[i] = tok
            batch.pos[i] = pos
            batch.n_seq_id[i] = 1
            batch.seq_id[i][0] = seq
            batch.logits[i] = 1 if want else 0

    def _logits(self, ctx, i: int) -> np.ndarray:
        return np.ctypeslib.as_array(L.llama_get_logits_ith(ctx, i), shape=(self.n_vocab,)).copy()

    # ---- the work
    def generate(self, messages: List[Dict[str, str]], branches: List[Dict[str, str]], max_tokens: int = 1800,
                 temperature: float = 0.15, top_p: float = 0.95, top_k: int = 40, repeat_penalty: float = 1.07,
                 fence_stop: bool = True, max_ctx: int = 32768,
                 on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
                 should_stop: Optional[Callable[[], bool]] = None, seed: int = 1234) -> Dict[str, Any]:
        emit = on_event or (lambda e: None)
        stop = should_stop or (lambda: False)
        branches = branches[:MAX_BRANCHES]
        if not branches:
            return {"branches": {}, "tokens": 0}
        prefix = self._tokenize(chatml(messages, open_last_user=True))
        group = [_Branch(str(b.get("id", i)), i, self._tokenize(branch_suffix(str(b.get("prompt", "")))))
                 for i, b in enumerate(branches)]
        k = len(group)
        longest_suffix = max(len(b.suffix) for b in group)
        budget = max(64, min(int(max_tokens), (max_ctx - len(prefix) - 64) // k - longest_suffix))
        n_ctx = len(prefix) + k * (longest_suffix + budget) + 64
        if n_ctx > max_ctx:
            raise RuntimeError(f"the shared prompt ({len(prefix)} tokens) is too long for {k} parallel answers")
        ctx = self._context(n_ctx, k)
        batch = L.llama_batch_init(512, 0, k)
        mem = L.llama_get_memory(ctx)
        rng = np.random.default_rng(seed)
        started = time.time()
        try:
            # 1. the shared prompt, once
            for start in range(0, len(prefix), 512):
                if stop():
                    return self._result(group, started, started, "stopped")
                chunk = prefix[start:start + 512]
                self._fill(batch, [(t, start + i, 0, False) for i, t in enumerate(chunk)])
                if L.llama_decode(ctx, batch) != 0:
                    raise RuntimeError("llama_decode failed while reading the prompt")
                emit({"type": "progress", "phase": "prompt", "done": min(start + 512, len(prefix)), "total": len(prefix)})
            for b in group[1:]:
                L.llama_memory_seq_cp(mem, 0, b.seq, 0, -1)
            for b in group:
                b.pos = len(prefix)
            # 2. each branch's own instruction (all in one or a few batches), then the first token of each
            pending = [(b, t, n == len(b.suffix) - 1) for b in group for n, t in enumerate(b.suffix)]
            first_logits: Dict[int, np.ndarray] = {}
            i = 0
            while i < len(pending):
                part = pending[i:i + 512]
                items, last_index = [], {}
                for j, (b, tok, last) in enumerate(part):
                    items.append((tok, b.pos, b.seq, last))
                    b.pos += 1
                    if last:
                        last_index[b.seq] = j
                self._fill(batch, items)
                if L.llama_decode(ctx, batch) != 0:
                    raise RuntimeError("llama_decode failed while reading the instructions")
                for seq, j in last_index.items():
                    first_logits[seq] = self._logits(ctx, j)
                i += len(part)
            prefill_done = time.time()
            emit({"type": "start", "branches": [b.id for b in group], "prompt_tokens": len(prefix),
                  "prefill_seconds": round(prefill_done - started, 2)})
            active: List[_Branch] = []
            for b in group:
                tok = sample(first_logits[b.seq], b.recent, temperature, top_p, top_k, repeat_penalty, rng)
                b.next_token = tok
                active.append(b)
            # 3. write all branches together, one token each per step
            while active:
                if stop():
                    for b in active:
                        b.reason = b.reason or "stopped"
                    break
                done_now: List[_Branch] = []
                for b in list(active):
                    tok = b.next_token
                    if L.llama_vocab_is_eog(self.vocab, tok):
                        self._finish(b, "stop", emit)
                        done_now.append(b)
                        continue
                    b.recent.append(tok)
                    b.tokens += 1
                    piece = b.decoder.decode(self._piece(tok))
                    if piece:
                        b.text += piece
                        emit({"type": "delta", "id": b.id, "text": piece})
                    reason = self._verdict(b, budget, fence_stop, piece)
                    if reason:
                        self._finish(b, reason, emit)
                        done_now.append(b)
                for b in done_now:
                    active.remove(b)
                    L.llama_memory_seq_rm(mem, b.seq, -1, -1)
                if not active:
                    break
                self._fill(batch, [(b.next_token, b.pos, b.seq, True) for b in active])
                if L.llama_decode(ctx, batch) != 0:
                    raise RuntimeError("llama_decode failed while writing")
                for j, b in enumerate(active):
                    b.pos += 1
                    b.next_token = sample(self._logits(ctx, j), b.recent, temperature, top_p, top_k,
                                          repeat_penalty, rng)
            return self._result(group, started, prefill_done, "done")
        finally:
            L.llama_batch_free(batch)
            L.llama_free(ctx)

    @staticmethod
    def _verdict(b: _Branch, budget: int, fence_stop: bool, piece: str) -> str:
        if b.tokens >= budget:
            return "length"
        if "`" in piece or "\n" in piece:
            if fence_stop:
                end = closing_fence_end(b.text)
                if end is not None:
                    b.text = b.text[:end]
                    return "fence"
            if b.text.count("\n") > MAX_FILE_LINES:
                return "long"
        if b.tokens % 64 == 0 and is_repeating(b.text):
            return "repeat"
        return ""

    @staticmethod
    def _finish(b: _Branch, reason: str, emit) -> None:
        b.reason = reason
        emit({"type": "end", "id": b.id, "reason": reason, "tokens": b.tokens, "chars": len(b.text)})

    @staticmethod
    def _result(group: List[_Branch], started: float, prefill_done: float, status: str) -> Dict[str, Any]:
        now = time.time()
        total = sum(b.tokens for b in group)
        decode = max(now - prefill_done, 0.001)
        return {
            "status": status,
            "branches": {b.id: {"text": b.text, "reason": b.reason or status, "tokens": b.tokens} for b in group},
            "tokens": total,
            "prefill_seconds": round(prefill_done - started, 2),
            "decode_seconds": round(decode, 2),
            "tokens_per_sec": round(total / decode, 1),
        }
