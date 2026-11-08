#!/usr/bin/env python3
import importlib.util
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "download_stats", ROOT / "tools" / "download-stats.py"
)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)


class DownloadStatsTests(unittest.TestCase):
    def test_summarize_counts_iso_and_update(self):
        releases = [
            {
                "tag_name": "v26.04.1",
                "published_at": "2026-04-01T00:00:00Z",
                "draft": False,
                "prerelease": False,
                "assets": [
                    {"name": "devos-26.04-amd64.iso", "download_count": 42, "size": 1},
                    {"name": "devos-26.04-amd64.iso.sha256", "download_count": 9, "size": 1},
                    {"name": "devos-update.tar.gz", "download_count": 7, "size": 1},
                    {"name": "notes.txt", "download_count": 100, "size": 1},
                ],
            }
        ]
        summary = mod.summarize(releases, "imranbru99/DevOS")
        self.assertEqual(summary["totals"]["iso"], 42)
        self.assertEqual(summary["totals"]["update_bundle"], 7)
        # ISO + update counted; checksum and notes.txt ignored
        self.assertEqual(summary["totals"]["all_counted_assets"], 42 + 7)
        self.assertEqual(summary["releases"][0]["iso_downloads"], 42)

    def test_checksum_not_counted_as_iso(self):
        self.assertTrue(mod.ISO_NAME.search("devos.iso"))
        self.assertFalse(mod.ISO_NAME.search("devos.iso.sha256"))
        self.assertFalse(mod.COUNT_NAME.search("devos.iso.sha256"))
        self.assertTrue(mod.COUNT_NAME.search("devos-update.tar.gz"))


if __name__ == "__main__":
    unittest.main()
