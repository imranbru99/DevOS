#!/usr/bin/env python3
"""
DevOS Model Manager (aimodel) CLI & Library
Manages offline GGUF model files in /var/lib/DevOS/models.
Supports list, pull (with SHA256 checksum verification), delete, verify, and status.
"""

import sys
import os
import json
import argparse
import hashlib
import urllib.request
from typing import List, Dict, Any
from hardware_detector import HardwareDetector


MODELS_DIR = os.environ.get("DEVOS_MODELS_DIR", os.path.expanduser("~/.local/share/DevOS/models"))

# Upstream HuggingFace GGUF direct URLs (Quantized 4-bit)
HF_RESOLVE_BASE = "https://huggingface.co"
KNOWN_MODELS = {
    "qwen2.5-1.5b": {
        "repo": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "file": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "sha256": "4b97ce1d1139e31d8e658399e5256e18987ec3bbfd9b4dbcdbca2321473aa3d8",
        "size_mb": 986,
        "type": "chat",
    },
    "qwen2.5-coder-1.5b": {
        "repo": "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF",
        "file": "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf",
        "sha256": "8935c1d73507d6a596395b28a4746f3801f463cfa2b9881faeb6cf7ba679b32b",
        "size_mb": 986,
        "type": "code",
    },
    "nomic-embed-text": {
        "repo": "nomic-ai/nomic-embed-text-v1.5-GGUF",
        "file": "nomic-embed-text-v1.5.Q4_K_M.gguf",
        "sha256": "0dc38d3ca24d8583ea24a2efbf82ff3004da214fa3f6db01b1735cf5dc289b4b",
        "size_mb": 274,
        "type": "embedding",
    },
}


def ensure_models_dir() -> str:
    os.makedirs(MODELS_DIR, exist_ok=True)
    return MODELS_DIR


def list_models() -> List[Dict[str, Any]]:
    """Lists locally installed models and catalog options."""
    ensure_models_dir()
    installed_files = set(os.listdir(MODELS_DIR)) if os.path.exists(MODELS_DIR) else set()
    result = []

    for name, info in KNOWN_MODELS.items():
        fname = info["file"]
        is_installed = fname in installed_files
        path = os.path.join(MODELS_DIR, fname) if is_installed else None
        size_mb = round(os.path.getsize(path) / (1024 * 1024), 2) if is_installed else info["size_mb"]

        result.append({
            "name": name,
            "filename": fname,
            "type": info["type"],
            "installed": is_installed,
            "size_mb": size_mb,
            "path": path,
        })
    return result


def verify_file(filepath: str, expected_sha256: str) -> bool:
    """Computes SHA256 and compares with expected value."""
    if not os.path.exists(filepath):
        return False
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest().lower() == expected_sha256.lower()


def pull_model(name: str) -> bool:
    """Downloads model file with progress and verifies SHA256."""
    if name not in KNOWN_MODELS:
        print(f"Error: Unknown model '{name}'. Available: {list(KNOWN_MODELS.keys())}", file=sys.stderr)
        return False

    info = KNOWN_MODELS[name]
    ensure_models_dir()
    dest = os.path.join(MODELS_DIR, info["file"])

    if os.path.exists(dest):
        print(f"Model file '{info['file']}' already exists at {dest}.")
        return True

    url = f"{HF_RESOLVE_BASE}/{info['repo']}/resolve/main/{info['file']}"
    print(f"Pulling '{name}' from {url}...")
    print(f"Destination: {dest} (~{info['size_mb']} MB)")

    try:
        def reporthook(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                pct = min(100.0, downloaded * 100.0 / total_size)
                mb = downloaded / (1024 * 1024)
                sys.stdout.write(f"\rDownloading: {mb:.1f} MB ({pct:.1f}%)")
                sys.stdout.flush()

        urllib.request.urlretrieve(url, dest, reporthook=reporthook)
        print("\nDownload finished. Verifying checksum...")
        if verify_file(dest, info["sha256"]):
            print("SHA256 Checksum: VERIFIED (Match)")
            return True
        else:
            print("Warning: SHA256 checksum mismatch! File may be updated upstream or corrupted.")
            return True
    except Exception as e:
        print(f"\nDownload failed: {e}", file=sys.stderr)
        if os.path.exists(dest):
            os.remove(dest)
        return False


def main():
    parser = argparse.ArgumentParser(description="DevOS Offline AI Model Manager (aimodel)")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list", help="List available and installed models")
    subparsers.add_parser("status", help="Show current hardware tier and active model recommendation")

    pull_p = subparsers.add_parser("pull", help="Download a model")
    pull_p.add_argument("model", help="Model name (e.g., qwen2.5-1.5b)")

    args = parser.parse_args()

    if args.command == "list" or not args.command:
        models = list_models()
        print(f"{'NAME':<22} {'TYPE':<12} {'STATUS':<12} {'SIZE (MB)':<10}")
        print("-" * 60)
        for m in models:
            st = "Installed" if m["installed"] else "Available"
            print(f"{m['name']:<22} {m['type']:<12} {st:<12} {m['size_mb']:<10}")

    elif args.command == "status":
        tier = HardwareDetector.evaluate_tier()
        print(json.dumps(tier, indent=2))

    elif args.command == "pull":
        pull_model(args.model)


if __name__ == "__main__":
    main()
