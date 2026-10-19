#!/usr/bin/env python3
"""
DevOS AI Code Agent - Engine & Provider Configuration
Supports ultra-fast cloud inference (Google Gemini, Groq, DeepSeek, OpenAI, OpenRouter)
alongside 100% private offline inference on DevOS Local Neural Engine.
"""

import os
import json
import time
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional, Tuple

CONFIG_FILE = os.path.expanduser("~/.config/devos/code-agent.json")

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini",
        "badge": "⚡ Gemini 2.0 Flash",
        "tagline": "Blazing Fast (150+ tok/s) · Free Tier Available",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.0-pro-exp"],
        "default_model": "gemini-2.0-flash",
        "env_key": "GEMINI_API_KEY",
        "key_url": "https://aistudio.google.com/app/apikey",
        "speed": "⚡ Ultra-Fast (~180 t/s)",
    },
    "groq": {
        "id": "groq",
        "name": "Groq LPU (Fastest)",
        "badge": "⚡ Groq LPU",
        "tagline": "Fastest Ever (300+ tok/s) · Ultra-Low Latency",
        "endpoint": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile", "deepseek-r1-distill-llama-70b", "qwen-2.5-32b"],
        "default_model": "llama-3.3-70b-versatile",
        "env_key": "GROQ_API_KEY",
        "key_url": "https://console.groq.com/keys",
        "speed": "⚡⚡ Hyper-Speed (~320 t/s)",
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "badge": "⚡ DeepSeek V3",
        "tagline": "State-of-the-Art Coding & Deep Reasoning",
        "endpoint": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
        "key_url": "https://platform.deepseek.com/api_keys",
        "speed": "⚡ Fast (~85 t/s)",
    },
    "openai": {
        "id": "openai",
        "name": "OpenAI / Custom",
        "badge": "⚡ OpenAI",
        "tagline": "Industry Standard GPT-4o & Compatible Endpoints",
        "endpoint": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "o3-mini"],
        "default_model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com/api-keys",
        "speed": "⚡ Fast (~90-120 t/s)",
    },
    "local": {
        "id": "local",
        "name": "DevOS Local Neural Engine",
        "badge": "🔒 Local Offline",
        "tagline": "100% Private Offline · Zero Cloud Dependencies",
        "endpoint": "http://127.0.0.1:11434/v1",
        "models": ["devos-ai-code"],
        "default_model": "devos-ai-code",
        "env_key": "",
        "key_url": "",
        "speed": "🔒 Local CPU/GPU (~10-25 t/s)",
    }
}


def load_config() -> Dict[str, Any]:
    """Loads configuration with active provider and saved keys."""
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    conf = {
        "active_provider": "local",
        "providers": {}
    }
    try:
        if os.path.isfile(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    conf.update(saved)
    except Exception:
        pass

    # Populate default structure for each provider
    providers_conf = conf.setdefault("providers", {})
    for pid, pdata in PROVIDERS.items():
        entry = providers_conf.setdefault(pid, {})
        entry.setdefault("endpoint", pdata["endpoint"])
        entry.setdefault("model", pdata["default_model"])
        # Check env var for key if not in config
        env_val = os.environ.get(pdata["env_key"], "") if pdata["env_key"] else ""
        if "api_key" not in entry or not entry["api_key"]:
            entry["api_key"] = env_val

    # Auto-select cloud provider if an environment key is present and active is still local
    if conf.get("active_provider") == "local":
        for pid in ("gemini", "groq", "deepseek", "openai"):
            if providers_conf.get(pid, {}).get("api_key"):
                conf["active_provider"] = pid
                break

    return conf


def save_config(conf: Dict[str, Any]) -> None:
    """Saves updated engine configuration."""
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        # Read existing file to preserve other fields (like recent_folders)
        existing = {}
        if os.path.isfile(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}
        existing.update(conf)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        print(f"[providers] Failed to save config: {e}")


def get_active_engine() -> Dict[str, Any]:
    """Returns active endpoint, model, api_key, and provider metadata."""
    conf = load_config()
    active_id = conf.get("active_provider") or "local"
    if active_id not in PROVIDERS:
        active_id = "local"
    
    meta = PROVIDERS[active_id]
    p_conf = conf.get("providers", {}).get(active_id, {})
    
    endpoint = p_conf.get("endpoint") or meta["endpoint"]
    model = p_conf.get("model") or meta["default_model"]
    api_key = p_conf.get("api_key") or (os.environ.get(meta["env_key"], "") if meta["env_key"] else "")

    return {
        "id": active_id,
        "provider": active_id,
        "name": meta["name"],
        "badge": meta["badge"],
        "endpoint": endpoint.rstrip("/"),
        "model": model,
        "api_key": api_key,
        "speed": meta["speed"],
        "is_local": (active_id == "local" or "127.0.0.1" in endpoint or "localhost" in endpoint),
        "tagline": meta["tagline"],
        "key_url": meta["key_url"],
    }


def set_active_engine(provider_id: str, model: Optional[str] = None, api_key: Optional[str] = None) -> None:
    """Sets active engine and persists configuration."""
    conf = load_config()
    if provider_id in PROVIDERS:
        conf["active_provider"] = provider_id
        entry = conf.setdefault("providers", {}).setdefault(provider_id, {})
        if model:
            entry["model"] = model
        if api_key is not None:
            entry["api_key"] = api_key.strip()
        save_config(conf)


def test_engine_connection(endpoint: str, model: str, api_key: str, timeout: float = 12.0) -> Dict[str, Any]:
    """Tests connection to the specified LLM endpoint and measures tokens/sec."""
    endpoint = endpoint.rstrip("/")
    if not endpoint.endswith("/chat/completions"):
        if endpoint.endswith("/v1"):
            url = f"{endpoint}/chat/completions"
        else:
            url = f"{endpoint}/chat/completions"
    else:
        url = endpoint

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a code benchmark assistant. Reply in one brief sentence."},
            {"role": "user", "content": "DevOS benchmark: confirm operational status in 10 words."}
        ],
        "max_tokens": 30,
        "temperature": 0.1,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            elapsed = max(time.time() - started, 0.05)
            choice = (data.get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content") or choice.get("text") or ""
            tokens = (data.get("usage") or {}).get("completion_tokens") or len(text.split())
            tps = round(tokens / elapsed, 1) if elapsed > 0 else 0
            return {
                "success": True,
                "reply": text.strip(),
                "latency_sec": round(elapsed, 2),
                "tokens_per_sec": tps,
                "model": data.get("model") or model,
                "message": f"Connected! Speed: {tps} tok/s (latency: {round(elapsed*1000)}ms)"
            }
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        return {"success": False, "error": f"HTTP {e.code}: {e.reason}. {body[:150]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
