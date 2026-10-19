#!/usr/bin/env python3
"""
DevOS AI model catalog.

One list of the chat models DevOS offers, how much memory and disk each one
needs, and which one fits this PC. The installer page ("Choose your DevOS AI"),
the devos-ai-models command and the AI service all read it, so a model added
here shows up everywhere.

Only the tiny model is on the ISO (4 GB limit, see devos-install-llm). The
others are downloaded after install, when the PC is online.
"""

import os
from typing import Dict, List, Optional

MODELS_DIR = "/var/lib/DevOS/models"
CHOICE_FILE = "/etc/devos/ai.conf"
USER_CHOICE_FILE = os.path.expanduser("~/.config/devos/ai.conf")
GB = 1024 ** 3

# min_ram_gb: total RAM the PC needs so the model plus the desktop, a browser
# and an editor still fit. File sizes are the real Q4_K_M downloads.
CHAT_MODELS: List[Dict] = [
    {
        "id": "tiny",
        "name": "Tiny",
        "params": "0.5B",
        "file": "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
        "size_mb": 490,
        "min_ram_gb": 2,
        "min_threads": 1,
        "built_in": True,
        "about": "Built in. Quick answers and PC help on any computer.",
    },
    {
        "id": "small",
        "name": "Small",
        "params": "1.5B",
        "file": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "size_mb": 1120,
        "min_ram_gb": 4,
        "min_threads": 2,
        "about": "Better answers and summaries. Good for most laptops.",
    },
    {
        "id": "medium",
        "name": "Medium",
        "params": "3B",
        "file": "qwen2.5-3b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf",
        "size_mb": 2100,
        "min_ram_gb": 8,
        "min_threads": 4,
        "about": "Writes, explains code and reads long PDFs well.",
    },
    {
        "id": "large",
        "name": "Large",
        "params": "7B",
        "file": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        "size_mb": 4680,
        "min_ram_gb": 16,
        "min_threads": 6,
        "about": "Near cloud-assistant quality. Needs a strong PC.",
    },
    {
        "id": "xl",
        "name": "Extra large",
        "params": "14B",
        "file": "Qwen2.5-14B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Qwen2.5-14B-Instruct-GGUF/resolve/main/Qwen2.5-14B-Instruct-Q4_K_M.gguf",
        "size_mb": 8990,
        "min_ram_gb": 32,
        "min_threads": 8,
        # DevOS runs models on the processor; 14B answers at reading speed
        # only on fast desktops, so it is offered but never pre-selected.
        "never_recommend": True,
        "about": "Best quality, slow on most PCs. For workstations.",
    },
]

EXTRAS: List[Dict] = [
    {
        "id": "vision",
        "name": "Photo understanding",
        "size_mb": 520,
        "min_ram_gb": 4,
        "about": "Describe photos and screenshots. Text in images and PDFs is read without it.",
    },
    {
        "id": "coder",
        "name": "Coding model",
        "size_mb": 1120,
        "min_ram_gb": 8,
        "about": "A second model tuned for code, used by DevOS Code and the API (model \"devos-ai-code\").",
    },
]

CODER_MODELS = {
    "small": {
        "file": "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF/resolve/main/qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
        "size_mb": 1120,
    },
    "large": {
        "file": "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
        "url": "https://huggingface.co/bartowski/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf",
        "size_mb": 4680,
    },
}

# Always available, nothing to download: shown on the installer page so people
# know PDFs and text in images work with every choice.
BUILT_IN_SKILLS = "Reading PDFs and text in images (Bangla + English) and voice commands work with every choice."

DISK_RESERVE_MB = 8000  # room left for apps and updates after the download


def chat_model(model_id: str) -> Optional[Dict]:
    return next((m for m in CHAT_MODELS if m["id"] == model_id), None)


def coder_for(chat_id: str) -> Dict:
    """The coding model follows the chat size: a 7B coder only next to 7B+ chat."""
    return CODER_MODELS["large"] if chat_id in ("large", "xl") else CODER_MODELS["small"]


def fits(model: Dict, ram_gb: float, threads: int, disk_free_gb: Optional[float] = None) -> bool:
    if ram_gb + 0.5 < model["min_ram_gb"]:  # "8 GB" PCs report ~7.6 GB
        return False
    if disk_free_gb is not None and not model.get("built_in"):
        if disk_free_gb * 1024 < model["size_mb"] + DISK_RESERVE_MB:
            return False
    return True


def recommend(ram_gb: float, threads: int, disk_free_gb: Optional[float] = None) -> str:
    """Largest model that fits and still answers quickly on this processor."""
    best = "tiny"
    for model in CHAT_MODELS:
        if model.get("never_recommend"):
            continue
        if fits(model, ram_gb, threads, disk_free_gb) and threads >= model["min_threads"]:
            best = model["id"]
    return best


def recommend_extras(ram_gb: float) -> List[str]:
    return [e["id"] for e in EXTRAS if ram_gb + 0.5 >= e["min_ram_gb"] and e["id"] == "vision"]


def parse_choice(text: str) -> Dict:
    """Read "medium+vision+coder" (the installer's value) or the ai.conf body."""
    choice = {"chat": "tiny", "vision": False, "coder": False}
    text = (text or "").strip()
    if "=" in text:
        for line in text.splitlines():
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key == "chat" and chat_model(value):
                choice["chat"] = value
            elif key in ("vision", "coder"):
                choice[key] = value.lower() in ("1", "yes", "true", "on")
        return choice
    parts = [p for p in text.split("+") if p]
    if parts and chat_model(parts[0]):
        choice["chat"] = parts[0]
    choice["vision"] = "vision" in parts[1:]
    choice["coder"] = "coder" in parts[1:]
    return choice


def format_choice(choice: Dict) -> str:
    return (
        "# DevOS AI models, chosen during install or in DevOS AI Models.\n"
        f"chat={choice['chat']}\n"
        f"vision={'yes' if choice.get('vision') else 'no'}\n"
        f"coder={'yes' if choice.get('coder') else 'no'}\n"
    )


def read_choice(path: str = CHOICE_FILE) -> Dict:
    target = path
    if target == CHOICE_FILE and os.path.isfile(USER_CHOICE_FILE):
        target = USER_CHOICE_FILE
    try:
        with open(target, encoding="utf-8") as handle:
            return parse_choice(handle.read())
    except OSError:
        return parse_choice("")


def all_choice_values() -> List[str]:
    """Every value the installer page can produce (for contextualprocess)."""
    values = []
    for model in CHAT_MODELS:
        for extras in ("", "+vision", "+coder", "+vision+coder"):
            values.append(model["id"] + extras)
    return values


def installed_file(name: str, dirs: Optional[List[str]] = None) -> Optional[str]:
    for directory in dirs or [MODELS_DIR, "/usr/share/devos/models"]:
        path = os.path.join(directory, name)
        if os.path.isfile(path) and os.path.getsize(path) > 100_000_000:
            return path
    return None
