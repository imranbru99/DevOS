#!/usr/bin/env python3
"""Writing several files at once: the pure parts, the real decoder (when a model is installed) and the HTTP endpoint."""

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/ai-core")))

import numpy as np  # noqa: E402

import batch_decode as B  # noqa: E402


class PureTests(unittest.TestCase):
    def test_chatml_and_open_user_message(self):
        msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "U"}]
        self.assertEqual(B.chatml(msgs), "<|im_start|>system\nS<|im_end|>\n<|im_start|>user\nU<|im_end|>\n")
        opened = B.chatml(msgs, open_last_user=True)
        self.assertTrue(opened.endswith("<|im_start|>user\nU"))
        self.assertTrue(B.branch_suffix("Write a.php").endswith("<|im_end|>\n<|im_start|>assistant\n"))

    def test_closing_fence_handles_nested_blocks(self):
        self.assertIsNone(B.closing_fence_end("```tool write_file\npath: a\n---\nx = 1\n"))
        done = "```tool write_file\npath: a.md\n---\n# T\n```php\necho 1;\n```\ntext\n```\nTRAILING"
        end = B.closing_fence_end(done)
        self.assertEqual(done[:end].rstrip().splitlines()[-1], "```")
        self.assertNotIn("TRAILING", done[:end])
        self.assertIsNone(B.closing_fence_end("no fence at all"))
        self.assertIsNone(B.closing_fence_end("```tool write_file\n---\n```php\nopen nested\n"))

    def test_repetition_detection(self):
        self.assertFalse(B.is_repeating("short"))
        self.assertTrue(B.is_repeating('    "vendor/package": "^1.0",\n' * 200))
        import random
        random.seed(1)
        noisy = "".join(random.choice("abcdefghijklmnopqrstuvwxyz \n{};$") for _ in range(4000))
        self.assertFalse(B.is_repeating(noisy))

    def test_sampling(self):
        rng = np.random.default_rng(0)
        logits = np.array([0.1, 3.0, 0.2, 0.3], dtype=np.float32)
        self.assertEqual(B.sample(logits.copy(), [], 0.0, 0.95, 40, 1.0, rng), 1)
        picks = {B.sample(logits.copy(), [], 1.0, 1.0, 4, 1.0, np.random.default_rng(i)) for i in range(60)}
        self.assertIn(1, picks)
        self.assertGreater(len(picks), 1)                                   # temperature explores
        # a repeated token is discouraged: 1 was just used
        again = B.sample(np.array([2.0, 2.05, 0.0], dtype=np.float32), [1] * 5, 0.0, 1.0, 3, 1.5, rng)
        self.assertEqual(again, 0)


def model_available() -> bool:
    try:
        import server
        return bool(server.engine._find_model("code"))
    except Exception:
        return False


@unittest.skipUnless(model_available(), "no local model installed")
class RealModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.OpenAIHandler)
        cls.httpd.daemon_threads = True
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def post(self, body, expect=200):
        req = urllib.request.Request(self.base + "/v1/devos/batch", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(req, timeout=240)
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, expect)
            return None

    def test_health_advertises_batching(self):
        data = json.load(urllib.request.urlopen(self.base + "/health"))
        self.assertEqual(data["batch"]["max_branches"], 8)

    def test_bad_requests_are_refused(self):
        self.post({"messages": []}, 400)
        self.post({"messages": [{"role": "user", "content": "x"}], "branches": []}, 400)

    def test_two_files_are_written_at_once_and_stop_at_their_fence(self):
        resp = self.post({"model": "devos-ai-code", "max_tokens": 200, "messages": [
            {"role": "system", "content": "Reply with exactly one fenced block: ```tool write_file\npath: <file>\n---\n<complete content>\n``` and nothing else."},
            {"role": "user", "content": "a.php prints hello; b.php prints world."}],
            "branches": [{"id": "a.php", "prompt": "Write the COMPLETE file a.php now."},
                         {"id": "b.php", "prompt": "Write the COMPLETE file b.php now."}]})
        texts, ends, done = {}, {}, None
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                continue
            event = json.loads(line[5:])
            if event["type"] == "delta":
                texts[event["id"]] = texts.get(event["id"], "") + event["text"]
            elif event["type"] == "end":
                ends[event["id"]] = event["reason"]
            elif event["type"] == "done":
                done = event
        self.assertEqual(sorted(texts), ["a.php", "b.php"])
        self.assertEqual(ends, {"a.php": "fence", "b.php": "fence"})
        self.assertIn("hello", texts["a.php"])
        self.assertIn("world", texts["b.php"])
        self.assertTrue(texts["a.php"].rstrip().endswith("```"))
        self.assertGreater(done["tokens"], 10)


if __name__ == "__main__":
    unittest.main()
