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
    """The model held 1.6-2.7 GB forever; it must be freed when idle."""

    def test_unloads_after_idle_and_not_before(self):
        import time as _time
        eng = server.DevOSAIEngine()
        eng._llm = object()
        eng.is_loaded = True
        eng.idle_timeout_seconds = 300
        eng.last_activity = _time.time()
        self.assertFalse(eng.unload_if_idle())
        self.assertIsNotNone(eng._llm)
        eng.last_activity = _time.time() - 301
        self.assertTrue(eng.unload_if_idle())
        self.assertIsNone(eng._llm)
        self.assertFalse(eng._load_tried, "the next question loads it again")

    def test_not_unloaded_while_answering(self):
        import time as _time
        eng = server.DevOSAIEngine()
        eng._llm = object()
        eng.last_activity = _time.time() - 999
        with eng._lock:
            import threading
            result = []
            t = threading.Thread(target=lambda: result.append(eng.unload_if_idle()))
            t.start(); t.join()
        self.assertEqual(result, [False])
        self.assertIsNotNone(eng._llm)
