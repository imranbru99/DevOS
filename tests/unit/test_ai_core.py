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


class TestDevOSAICore(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Start server in background thread for testing
        cls.server = HTTPServer((HOST, PORT), OpenAIHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
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
            self.assertTrue(len(content) > 0)
            self.assertIn("Hardware Tier", content)

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
