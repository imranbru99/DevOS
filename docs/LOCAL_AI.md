# DevOS Local AI

DevOS AI is the private model that runs on this computer. Your apps talk to it with the same HTTP API as OpenAI. Chats, code and files stay on this PC: nothing you send to this API leaves the machine.

Open this page in a browser on the DevOS PC: <http://127.0.0.1:11434/docs>

## Address

| What | Where |
|---|---|
| API base (OpenAI-compatible) | `http://127.0.0.1:11434/v1` |
| This documentation | `http://127.0.0.1:11434/docs` |
| Machine-readable spec | `http://127.0.0.1:11434/openapi.json` |
| Health and speed | `http://127.0.0.1:11434/health` |

Calls from this PC do not need an API key. Any string works if a library insists on one (`devos`).

To use it from a phone or another PC on the same Wi-Fi:

```bash
devos models api lan on
```

That prints a key. Those callers send `Authorization: Bearer <key>`. Turn it back off with `devos models api lan off`. `devos models api new-key` replaces the key.

## Models

| `model` | Use |
|---|---|
| `devos-ai` | Chat, writing, summaries, help with this PC |
| `devos-ai-code` | Code: DevOS Code, VS Code, and `devos auto` |
| `devos-ai-embed` | Embeddings. Each input becomes 384 numbers, for search over your own files |

The file behind `devos-ai` is the size chosen for this PC in **DevOS AI Models** (or at install):

| Choice | Size | Fits |
|---|---|---|
| Tiny | 0.5B, built in | any PC |
| Small | 1.5B | 4 GB RAM |
| Medium | 3B | 8 GB RAM |
| Large | 7B | 16 GB RAM |
| Extra large | 14B | 32 GB RAM |

The API name stays `devos-ai` when you change size, so scripts do not have to change. `devos-ai-code` uses the coding model when that extra is installed, and the chat model otherwise.

List them:

```bash
curl http://127.0.0.1:11434/v1/models
```

One model: `GET /v1/models/devos-ai`.

## Speed

The service measures this PC at startup and loads the model for it. You do not pick thread counts by hand.

- **Prompt processing** uses every logical processor, split across parallel answers. Long code prompts are the slow part, and they scale with threads.
- **Replies** use one thread per physical core. Extra hyperthreads do not make token generation faster; they fight over memory bandwidth.
- **Flash attention** and a **Q8 KV cache** are turned on when this build of the engine accepts them. The cache is about half the working memory of the full-precision one, so each token moves less data.
- **Batch size** is 1024 tokens for code on an 8 GB+ PC with 8 or more prompt threads, and 512 otherwise.
- While a reply is generating, the CPU leaves powersave and returns to its previous setting when the last reply finishes.
- The model is loaded and the system prompt is processed at service start, so the first question does not pay for that.
- After 5 minutes with no questions the weights are unloaded. The next question loads them again in about a second. Extra parallel copies are freed sooner.
- When CUDA, ROCm or Vulkan is detected, layers are placed on the GPU. If that fails, the service continues on the processor.
- On a 32 GB+ PC the weights can be locked in RAM so they are not pushed into swap.

Chat context is **2048** tokens (longer windows made 4 GB laptops run out of memory). Code context is **8192**. `max_tokens` is capped at **2048**.

Check what this PC is using:

```bash
curl -s http://127.0.0.1:11434/health
```

The `speed` object reports `threads`, `prompt_threads`, `batch`, `context`, `kv_cache` (`q8_0` or `f16`), `gpu_layers` and `parallel`.

Optional overrides, set in the environment of `devos-ai-core.service` only when the automatic choice is wrong:

| Variable | Effect |
|---|---|
| `DEVOS_AI_FAST=0` | Full-precision KV cache, no flash attention |
| `DEVOS_AI_THREADS` | Reply threads for one slot |
| `DEVOS_AI_BATCH_THREADS` | Prompt threads for one slot |
| `DEVOS_AI_PARALLEL` | How many answers run at the same time (1–8) |
| `DEVOS_GPU_LAYERS` | Layers to place on the GPU (`0` forces the processor) |

For the shortest code replies, send `"temperature": 0`. The default is `0.3`.

Several apps can ask at once. A small laptop answers one at a time and the others wait. A larger PC runs two to four answers together; they share one copy of the weights. If the waiting line is full the API returns HTTP 503 with `"type": "server_busy"`.

## Chat

`POST /v1/chat/completions`

```bash
curl http://127.0.0.1:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"devos-ai","messages":[{"role":"user","content":"Hello"}]}'
```

Streaming (server-sent events, ending with `data: [DONE]`):

```bash
curl http://127.0.0.1:11434/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"devos-ai","stream":true,"messages":[{"role":"user","content":"Hello"}]}'
```

Fields:

| Field | Meaning |
|---|---|
| `model` | `devos-ai` or `devos-ai-code` |
| `messages` | `{role, content}` with roles `system`, `user`, `assistant` |
| `max_tokens` or `max_completion_tokens` | Reply length, 16–2048, default 384 |
| `temperature` | 0–2, default 0.3. `0` is the fastest, most repeatable setting |
| `top_p` | 0.05–1 |
| `top_k` | 0–200 |
| `repeat_penalty` | 1–2 |
| `stop` | String or list of up to 8 stop strings |
| `seed` | Integer, when you need the same reply again |
| `stream` | `true` for word-by-word output |

DevOS adds its own identity in front of any `system` message you send, so the model stays DevOS AI. The reply is OpenAI-shaped: `choices[0].message.content`, plus `usage` and `tokens_per_sec`.

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:11434/v1", api_key="devos")
reply = client.chat.completions.create(
    model="devos-ai-code",
    temperature=0,
    messages=[{"role": "user", "content": "Write a Python function that reverses a list."}],
)
print(reply.choices[0].message.content)
```

### Python (no extra packages)

```python
import json, urllib.request

req = urllib.request.Request(
    "http://127.0.0.1:11434/v1/chat/completions",
    data=json.dumps({
        "model": "devos-ai",
        "messages": [{"role": "user", "content": "Summarize this function in one sentence."}],
    }).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=120) as resp:
    print(json.load(resp)["choices"][0]["message"]["content"])
```

### JavaScript

```javascript
const res = await fetch("http://127.0.0.1:11434/v1/chat/completions", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({
    model: "devos-ai",
    messages: [{role: "user", content: "Hello"}],
  }),
});
const data = await res.json();
console.log(data.choices[0].message.content);
```

## Text completion

`POST /v1/completions` is the older prompt-in, text-out shape. Editors that still speak it can point at DevOS.

```bash
curl http://127.0.0.1:11434/v1/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"devos-ai-code","prompt":"def add(a, b):\n","max_tokens":64,"temperature":0}'
```

The text is `choices[0].text`. `stream: true` works here too.

## Embeddings

`POST /v1/embeddings`

```bash
curl http://127.0.0.1:11434/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"devos-ai-embed","input":["search over my notes"]}'
```

`input` is a string or a list. Each item comes back as `data[i].embedding` with **384** numbers. When the embedding file is not installed yet, DevOS still returns 384 numbers from the text itself so search keeps working offline.

## Automations

These call the model on this PC. They are for coding; they do not commit, push or run commands.

```bash
devos auto commit          # one-line subject from the staged diff (or the unstaged diff)
devos auto review          # short review of that diff
devos auto explain         # explain the error you pipe in
devos auto summarize app.py
devos auto ask "Where is the AI service started?"
devos auto hook            # git hook: fill an empty commit message
devos auto hook remove
devos auto docs            # print this reference's address
```

Examples:

```bash
# subject only, for a script
git diff --cached | devos auto commit --stdin

# a failing test
pytest -q 2>&1 | devos auto explain
```

`devos auto hook` writes `.git/hooks/prepare-commit-msg` in the current repository. If a hook is already there and DevOS did not write it, it is left alone. The hook does nothing when you already typed a message, and it gives up quietly if the model is busy.

## Already wired in

- **DevOS AI** window and **Win+H** voice
- **Win+Alt+A** on selected text (rewrite, grammar, translate, summarize)
- **DevOS Code** and VS Code (chat, edit, autocomplete) via this API
- **DevOS Code Agent** on PCs with 8 GB+ RAM and a Medium or coding model
- **Optimizer**, **Notes**, **Phone Link** and prayer reflections, each asking this same service

Point any other OpenAI client at `http://127.0.0.1:11434/v1` and model `devos-ai` or `devos-ai-code`.

## Limits

- The service listens on this PC only until you turn network access on.
- Context is 2048 tokens for chat and 8192 for code. Longer input is not a longer window: send the part that matters.
- Quality follows the size you installed. Tiny is quick PC help. Medium and the coding model are what you want for `devos auto` and VS Code.
- The model can invent menus and steps. For changing DevOS itself, use **DevOS Features** and the Apps window.
- A reply that sits in the queue too long (10 minutes) or finds a full queue gets HTTP 503. Ask again.
