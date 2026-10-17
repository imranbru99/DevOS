#!/usr/bin/env python3
"""
DevOS 2027 Era: Privacy-Preserving Semantic Vector Memory
Provides natural-language file & code search across local projects using on-device embeddings.
100% Offline, Encrypted at Rest, Zero Screen Scraping, Zero Cloud Telemetry.
"""

import sys
import os
import math
import json
import base64
import hashlib
import urllib.request
import urllib.error
import argparse
from typing import Dict, Any, List


MEMORY_DB_FILE = os.path.expanduser("~/.local/share/DevOS/semantic_memory.enc")
LEGACY_DB_FILE = os.path.expanduser("~/.local/share/DevOS/semantic_memory.json")
AI_EMBED_URL = os.environ.get("DEVOS_EMBED_URL", "http://127.0.0.1:11434/v1/embeddings")


class SemanticMemoryIndex:
    """Local, encrypted-at-rest vector index for on-device semantic search."""

    def __init__(self):
        os.makedirs(os.path.dirname(MEMORY_DB_FILE), exist_ok=True)
        self._key = self._derive_storage_key()
        self.entries: List[Dict[str, Any]] = self._load()

    @staticmethod
    def _derive_storage_key() -> bytes:
        """Derives a stable machine/user-bound key for local encryption at rest."""
        machine_seed = ""
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        machine_seed = f.read().strip()
                        break
                except Exception:
                    pass
        if not machine_seed:
            machine_seed = os.environ.get("USER", os.environ.get("USERNAME", "devos_secure"))
        return hashlib.sha256(f"devos_semantic_vault:{machine_seed}".encode("utf-8")).digest()

    def _encrypt_bytes(self, raw: bytes) -> bytes:
        key = self._key
        # Keystream encryption with sha256 counter blocks
        blocks = []
        for i in range(0, len(raw), 32):
            stream = hashlib.sha256(key + i.to_bytes(4, "big")).digest()
            chunk = raw[i:i+32]
            blocks.append(bytes(a ^ b for a, b in zip(chunk, stream)))
        return b"".join(blocks)

    def _decrypt_bytes(self, enc: bytes) -> bytes:
        return self._encrypt_bytes(enc)

    def _load(self) -> List[Dict[str, Any]]:
        # 1. Load from encrypted vault
        if os.path.exists(MEMORY_DB_FILE):
            try:
                with open(MEMORY_DB_FILE, "rb") as f:
                    cipher = f.read()
                plain = self._decrypt_bytes(cipher)
                return json.loads(plain.decode("utf-8"))
            except Exception:
                pass

        # 2. Migration from legacy unencrypted json
        if os.path.exists(LEGACY_DB_FILE):
            try:
                with open(LEGACY_DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.entries = data
                        self._save()
                        return data
            except Exception:
                pass
        return []

    def _save(self):
        payload = json.dumps(self.entries, indent=2).encode("utf-8")
        encrypted = self._encrypt_bytes(payload)
        with open(MEMORY_DB_FILE, "wb") as f:
            f.write(encrypted)

    @classmethod
    def _embed_text(cls, text: str) -> List[float]:
        """Generates embedding vector via local AI engine when online, or dense n-gram hashing."""
        # 1. Try querying local DevOS AI server for high-fidelity on-device embeddings
        try:
            req_data = json.dumps({"input": [text[:1000]]}).encode("utf-8")
            req = urllib.request.Request(
                AI_EMBED_URL,
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=0.8) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode())
                    vec = data["data"][0]["embedding"]
                    mag = math.sqrt(sum(v * v for v in vec)) or 1.0
                    return [round(v / mag, 6) for v in vec]
        except Exception:
            pass

        # 2. Local fallback: dense 128-dimensional multi-gram semantic hashing with L2 normalization
        words = text.lower().split()
        vector = [0.0] * 128
        for w in words:
            # Word unigram
            idx = sum(ord(c) * (31 ** i) for i, c in enumerate(w[:6])) % 128
            vector[idx] += 2.0
            # Character trigrams for subword morphology
            for j in range(len(w) - 2):
                tri_idx = sum(ord(c) * 17 for c in w[j:j+3]) % 128
                vector[tri_idx] += 0.5
        # Word bigrams
        for i in range(len(words) - 1):
            bg = words[i] + "_" + words[i + 1]
            bg_idx = sum(ord(c) * 13 for c in bg) % 128
            vector[bg_idx] += 3.0

        # Normalize vector to unit length
        magnitude = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [round(v / magnitude, 6) for v in vector]

    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        return sum(a * b for a, b in zip(vec1, vec2))

    def index_document(self, title: str, content: str, path: str):
        """Indexes local text content into semantic memory."""
        embedding = self._embed_text(title + " " + content)
        self.entries.append({
            "title": title,
            "path": path,
            "snippet": content[:200],
            "vector": embedding,
        })
        self._save()

    def search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Performs semantic similarity search across indexed documents."""
        q_vec = self._embed_text(query)
        scored = []
        for doc in self.entries:
            sim = self._cosine_similarity(q_vec, doc["vector"])
            scored.append({
                "title": doc["title"],
                "path": doc["path"],
                "snippet": doc["snippet"],
                "similarity": round(sim, 4),
            })
        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:top_k]


def main():
    parser = argparse.ArgumentParser(description="DevOS Semantic Memory Search")
    subparsers = parser.add_subparsers(dest="command")

    search_p = subparsers.add_parser("search", help="Semantic query")
    search_p.add_argument("query", help="Natural language query")

    index_p = subparsers.add_parser("index", help="Index a file or note")
    index_p.add_argument("path", help="Path to file")
    index_p.add_argument("title", help="Document title")

    args = parser.parse_args()
    mem = SemanticMemoryIndex()

    if args.command == "index":
        if os.path.exists(args.path):
            with open(args.path, "r", errors="ignore") as f:
                content = f.read(5000)
            mem.index_document(args.title, content, args.path)
            print(f"Indexed document '{args.title}' ({args.path}).")
    elif args.command == "search" or not args.command:
        # If no entries, seed sample entries for testing
        if not mem.entries:
            mem.index_document("Docker Compose Stack", "services: redis: image: redis:alpine mariadb: port 3306", "~/projects/docker-compose.yml")
            mem.index_document("Stripe Payment Webhook", "Stripe API Secret Key STRIPE_WEBHOOK_SECRET=whsec_abc123", "~/projects/.env.stripe")
            mem.index_document("Kernel Tuning Config", "vm.swappiness=150 zram zstd compression anti-hang", "/etc/sysctl.d/99-devos.conf")

        query = args.query if args.command == "search" else "stripe webhook secret"
        res = mem.search(query)
        print(f"Semantic Search Results for: '{query}'")
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
