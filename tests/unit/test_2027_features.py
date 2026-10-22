"""
Unit tests for DevOS 2027 Era Features:
- NPU silicon detection & ambient scheduling
- AI-Native Smart Shell Auto-Healer
- Privacy-Preserving Semantic Vector Memory
"""

import sys
import os
import unittest
import tempfile
from unittest.mock import patch

SYS_PATH_AI = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/ai-core"))
SYS_PATH_AGENT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/ai-agent"))
sys.path.insert(0, SYS_PATH_AI)
sys.path.insert(0, SYS_PATH_AGENT)

from npu_accelerator import NPUAccelerator
from smart_shell import SmartShellHealer
from semantic_memory import SemanticMemoryIndex


class Test2027Features(unittest.TestCase):

    def test_01_npu_detection(self):
        npu = NPUAccelerator.detect_npu()
        self.assertIn("npu_detected", npu)
        self.assertIn("vendor", npu)
        self.assertIn("power_efficiency", npu)

    def test_02_npu_scheduling(self):
        sched = NPUAccelerator.get_scheduling_recommendation()
        self.assertIn("ambient_chat_target", sched)
        self.assertIn("power_savings", sched)

    def test_03_smart_shell_command_not_found(self):
        diag = SmartShellHealer.diagnose_failure("htop", "command not found: htop", exit_code=127)
        self.assertEqual(diag["status"], "AUTO_HEAL_READY")
        self.assertIn("devos app install htop", diag["suggested_fix"])

    def test_04_smart_shell_port_collision(self):
        diag = SmartShellHealer.diagnose_failure("npm run dev", "Error: bind: address already in use 80", exit_code=1)
        self.assertEqual(diag["status"], "AUTO_HEAL_READY")
        self.assertIn("fuser", diag["suggested_fix"])

    def test_05_smart_shell_permission_denied(self):
        diag = SmartShellHealer.diagnose_failure("cat /etc/shadow", "permission denied", exit_code=1)
        self.assertEqual(diag["status"], "AUTO_HEAL_READY")
        self.assertIn("sudo", diag["suggested_fix"])

    def test_06_semantic_vector_memory(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix="devos-memory-test-"))
        self.enterContext(patch("semantic_memory.MEMORY_DB_FILE", os.path.join(directory, "memory.enc")))
        self.enterContext(patch("semantic_memory.LEGACY_DB_FILE", os.path.join(directory, "legacy.json")))
        # Exercise the local fallback without reading a user's running AI service.
        self.enterContext(patch("semantic_memory.urllib.request.urlopen", side_effect=OSError("offline test")))
        mem = SemanticMemoryIndex()
        mem.index_document("Payment Config", "STRIPE_KEY=pk_test_12345", "/test/.env")
        mem.index_document("Database Docker", "postgres: image postgres:16", "/test/compose.yml")

        results = mem.search("stripe payment key", top_k=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Payment Config")
        self.assertGreater(results[0]["similarity"], 0.0)


if __name__ == "__main__":
    unittest.main()
