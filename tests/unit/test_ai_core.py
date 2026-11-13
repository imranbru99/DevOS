"""
Unit tests for DevOS Local AI Core
Verifies Hardware Tier detection, OpenAI endpoints, Chat Completions, and Embeddings.
"""

import sys
import os
import json
import threading
import time
import unittest
import urllib.request

# Add components/ai-core to path
SYS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/ai-core"))
sys.path.insert(0, SYS_PATH)

from hardware_detector import HardwareDetector
from server import HTTPServer, OpenAIHandler, HOST, PORT, engine
import server


class TestDevOSAICore(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # If server is already running on HOST:PORT, use it directly
        cls.server = None
        try:
            with urllib.request.urlopen(f"http://{HOST}:{PORT}/health", timeout=1.0) as resp:
                if resp.status == 200:
                    return
        except Exception:
            pass
        # Start server in background thread for testing
        cls.server = HTTPServer((HOST, PORT), OpenAIHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        if cls.server is not None:
            cls.server.shutdown()
            cls.server.server_close()

    def test_01_hardware_detection(self):
        tier_data = HardwareDetector.evaluate_tier()
        self.assertIn("tier", tier_data)
        self.assertIn(tier_data["tier"], ["Lite", "Standard", "Pro"])
        self.assertGreater(tier_data["ram_gb"], 0.0)
        self.assertIn("chat_model", tier_data["models"])

    def test_02_health_endpoint(self):
        req = urllib.request.Request(f"http://{HOST}:{PORT}/health")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertEqual(data["status"], "healthy")
            self.assertIn("tier", data)

    def test_03_models_endpoint(self):
        req = urllib.request.Request(f"http://{HOST}:{PORT}/v1/models")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertIn("data", data)
            self.assertGreaterEqual(len(data["data"]), 2)

    def test_04_chat_completion(self):
        payload = json.dumps({
            "messages": [{"role": "user", "content": "Tell me about my hardware tier and optimization"}]
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://{HOST}:{PORT}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertIn("choices", data)
            content = data["choices"][0]["message"]["content"]
            # Real facts about this PC, not an internal tier/model report.
            self.assertTrue(any(k in content for k in ("This PC", "this PC", "Intel", "RAM", "GB", "processor", "CPU")))
            self.assertNotIn("qwen", content.lower())

    def test_04b_plain_question_is_not_the_canned_greeting(self):
        payload = json.dumps({
            "messages": [{"role": "user", "content": "What is two plus two?"}]
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://{HOST}:{PORT}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            content = data["choices"][0]["message"]["content"]
            self.assertNotIn("local assistant running completely offline", content)
            self.assertNotIn("How can I help you today", content)

    def test_05_embeddings_endpoint(self):
        payload = json.dumps({
            "input": ["DevOS AI native operating system"]
        }).encode("utf-8")
        req = urllib.request.Request(
            f"http://{HOST}:{PORT}/v1/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode())
            self.assertIn("data", data)
            vector = data["data"][0]["embedding"]
            self.assertEqual(len(vector), 384)


if __name__ == "__main__":
    unittest.main()


class TestIdleUnload(unittest.TestCase):
    """Model must sleep after 10 minutes with no chat — never sit at 5 GB idle."""

    def test_default_idle_is_ten_minutes(self):
        self.assertEqual(server.DEFAULT_IDLE_TIMEOUT_SECONDS, 600)
        eng = server.DevOSAIEngine()
        self.assertEqual(eng.idle_timeout_seconds, 600)
        self.assertEqual(eng.last_activity, 0.0)
        self.assertFalse(server.configured_warmup())

    def test_health_reports_model_loaded_without_loading(self):
        """Chat-off / sleep: /health must say whether GGUF is in RAM, not load it."""
        src = open(os.path.join(SYS_PATH, "server.py"), encoding="utf-8").read()
        self.assertIn('"model_loaded": bool(slots.get("loaded"))', src)
        self.assertIn("sleep mode: model loads on first chat", src)
        self.assertIn("Preload at boot is OFF unless explicitly enabled", src)
        self.assertIn("/v1/devos/sleep", src)
        self.assertIn("/v1/devos/awake", src)
        self.assertIn("def unload_now", src)
        self.assertIn("def keep_awake", src)

    def test_keep_awake_only_when_loaded(self):
        eng = server.DevOSAIEngine()
        eng.last_activity = 0.0
        cold = eng.keep_awake()
        self.assertFalse(cold["kept_awake"])
        self.assertFalse(cold["model_loaded"])
        eng._slots[0].llm = object()
        eng.is_loaded = True
        before = eng.last_activity
        warm = eng.keep_awake()
        self.assertTrue(warm["kept_awake"])
        self.assertTrue(warm["model_loaded"])
        self.assertGreater(eng.last_activity, before)

    def test_unloads_after_idle_and_not_before(self):
        import time as _time
        eng = server.DevOSAIEngine()
        eng.idle_timeout_seconds = 600
        slot = eng._slots[0]
        slot.llm = object()
        slot.load_tried = True
        eng.is_loaded = True
        eng.last_activity = _time.time()
        self.assertFalse(eng.unload_if_idle())
        self.assertIsNotNone(slot.llm)
        eng.last_activity = _time.time() - 601
        self.assertTrue(eng.unload_if_idle())
        self.assertIsNone(slot.llm)
        self.assertFalse(slot.load_tried, "the next question loads it again")

    def test_never_used_load_unloads_immediately(self):
        """Mistaken preload with no chat must not keep RAM."""
        eng = server.DevOSAIEngine()
        eng.idle_timeout_seconds = 600
        eng.last_activity = 0.0
        slot = eng._slots[0]
        slot.llm = object()
        slot.load_tried = True
        self.assertTrue(eng.unload_if_idle())
        self.assertIsNone(slot.llm)

    def test_not_unloaded_while_answering(self):
        import time as _time
        eng = server.DevOSAIEngine()
        slot = eng._slots[0]
        slot.llm = object()
        slot.busy = True
        eng.last_activity = _time.time() - 999
        self.assertFalse(eng.unload_if_idle())
        self.assertIsNotNone(slot.llm)

    def test_unload_now_frees_when_idle_keeps_when_busy(self):
        eng = server.DevOSAIEngine()
        slot = eng._slots[0]
        slot.llm = object()
        slot.load_tried = True
        slot.busy = True
        eng.is_loaded = True
        held = eng.unload_now("chat-closed")
        self.assertFalse(held["unloaded"])
        self.assertTrue(held["busy"])
        self.assertTrue(held["model_loaded"])
        self.assertIsNotNone(slot.llm)
        slot.busy = False
        freed = eng.unload_now("chat-closed")
        self.assertTrue(freed["unloaded"])
        self.assertFalse(freed["model_loaded"])
        self.assertIsNone(slot.llm)
        again = eng.unload_now("chat-closed")
        self.assertFalse(again["unloaded"])
        self.assertEqual(again["reason"], "nothing_loaded")

    def test_sleep_requested_while_busy_releases_after_generation(self):
        eng = server.DevOSAIEngine()
        slot = eng._slots[0]
        slot.llm = object()
        slot.busy = True
        self.assertTrue(eng.unload_now("chat-closed")["busy"])
        self.assertIsNotNone(slot.llm)
        eng._release(slot)
        self.assertIsNone(slot.llm)
