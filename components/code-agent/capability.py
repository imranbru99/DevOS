#!/usr/bin/env python3
"""
Is this PC's local AI good enough to write code?

DevOS Code Agent, its menu entry and the VS Code agent setup only appear when
it is: small models (0.5B, 1.5B chat) cannot follow multi-step coding tasks
and would just frustrate people. Good enough means

  * the Coding model (qwen2.5-coder, "devos-ai-code") is downloaded, or
  * a Medium (3B) or bigger chat model is downloaded,

and the PC has at least 8 GB of memory (the model, an editor and a browser
all have to fit).
"""

import os
import sys
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
AI_CORE = os.path.join(os.path.dirname(HERE), "ai-core")
if AI_CORE not in sys.path:
    sys.path.insert(0, AI_CORE)

import model_catalog as catalog  # noqa: E402

MIN_RAM_GB = 8
CAPABLE_CHAT = ("medium", "large", "xl")

NEEDS_MODEL = ("DevOS Code Agent needs the Coding model or a Medium (3B) or bigger DevOS AI. "
               "Open DevOS AI Models to download one.")


def model_dirs() -> List[str]:
    """The folders the AI service loads models from (see server.py)."""
    dirs = [os.environ.get("DEVOS_MODELS_DIR", ""), catalog.MODELS_DIR, "/usr/share/devos/models",
            os.path.expanduser("~/.local/share/DevOS/models")]
    return [d for d in dirs if d]


def total_ram_gb() -> float:
    try:
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def coder_installed(dirs: Optional[List[str]] = None) -> bool:
    return any(catalog.installed_file(m["file"], dirs or model_dirs())
               for m in catalog.CODER_MODELS.values())


def details(ram_gb: Optional[float] = None, dirs: Optional[List[str]] = None,
            choice: Optional[Dict] = None) -> Dict:
    ram = total_ram_gb() if ram_gb is None else ram_gb
    choice = choice or catalog.read_choice()
    installed = [m["id"] for m in catalog.CHAT_MODELS
                 if catalog.installed_file(m["file"], dirs or model_dirs())]
    return {
        "ram_gb": round(ram, 1),
        "coder": coder_installed(dirs),
        "chosen": choice.get("chat", "tiny"),
        "installed_chat": installed,
        "big_chat": [m for m in installed if m in CAPABLE_CHAT],
    }


def coding_capable(ram_gb: Optional[float] = None, dirs: Optional[List[str]] = None,
                   choice: Optional[Dict] = None) -> Tuple[bool, str]:
    """(True, what makes it capable) or (False, a friendly message for people)."""
    info = details(ram_gb, dirs, choice)
    # "8 GB" PCs report about 7.6 GB, as in model_catalog.fits().
    if info["ram_gb"] + 0.5 < MIN_RAM_GB:
        return False, (f"DevOS Code Agent needs a PC with at least {MIN_RAM_GB} GB of memory "
                       f"(this PC has {info['ram_gb']:g} GB). DevOS AI chat still works.")
    if info["coder"]:
        return True, "The Coding model is installed."
    if info["big_chat"]:
        # Prefer naming the model the person chose when it is one of them.
        best = info["chosen"] if info["chosen"] in info["big_chat"] else info["big_chat"][-1]
        model = catalog.chat_model(best)
        return True, f"The {model['name']} ({model['params']}) DevOS AI is installed."
    return False, NEEDS_MODEL


def main() -> int:
    ok, reason = coding_capable()
    print(("yes: " if ok else "no: ") + reason)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
