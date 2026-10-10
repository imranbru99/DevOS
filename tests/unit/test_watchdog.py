"""
Unit tests for DevOS System Watchdog & Storage Optimizer
Verifies memory pressure monitoring, cache audit, and btrfs optimization handlers.
"""

import sys
import os
import unittest

SYS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/ai-agent"))
sys.path.insert(0, SYS_PATH)

from system_watchdog import SystemWatchdog


class TestSystemWatchdog(unittest.TestCase):

    def test_01_memory_pressure_check(self):
        pressure = SystemWatchdog.get_memory_pressure()
        self.assertIn("status", pressure)
        self.assertIn(pressure["status"], ["normal", "elevated", "critical"])
        self.assertIn("some_avg10", pressure)

    def test_02_disk_reclaim_audit(self):
        audit = SystemWatchdog.inspect_disk_reclaim_potential()
        self.assertIn("total_reclaimable_mb", audit)
        self.assertIn("total_reclaimable_gb", audit)
        self.assertIn("btrfs_zstd_compression_ratio", audit)
        self.assertIsInstance(audit["breakdown"], list)

    def test_03_heavy_app_optimization(self):
        opt = SystemWatchdog.optimize_heavy_app_storage("~/.wine")
        self.assertEqual(opt["status"], "OPTIMIZED")
        self.assertIn("zstd:3", opt["btrfs_compression"])
        self.assertIn("deduplicat", opt["reflink_deduplication"].lower())


if __name__ == "__main__":
    unittest.main()
