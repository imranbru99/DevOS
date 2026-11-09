#!/usr/bin/env python3
"""PC owner profile storage and AI answer text."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "settings"))
sys.path.insert(0, str(ROOT / "components"))

import owner_profile as op  # noqa: E402
from assistant import tools as _tools  # noqa: E402


class TestOwnerProfile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "owner.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_and_load_normalizes_urls(self):
        saved = op.save_profile(
            {
                "display_name": "Imran Ahmed",
                "email": "me@imrandev.bd",
                "bio": "Builder of DevOS",
                "portfolio": "imrandev.bd",
                "github": "github.com/imranbru99",
            },
            path=self.path,
        )
        self.assertEqual(saved["portfolio"], "https://imrandev.bd")
        self.assertEqual(saved["github"], "https://github.com/imranbru99")
        loaded = op.load_profile(self.path)
        self.assertEqual(loaded["display_name"], "Imran Ahmed")
        self.assertEqual(loaded["email"], "me@imrandev.bd")

    def test_answer_includes_name_email_portfolio(self):
        op.save_profile(
            {
                "display_name": "Imran Ahmed",
                "email": "me@imrandev.bd",
                "portfolio": "https://imrandev.bd/",
                "bio": "DevOS creator",
            },
            path=self.path,
        )
        with mock.patch.object(op, "CONFIG_FILE", self.path):
            text = op.owner_answer_text(op.load_profile(self.path))
        self.assertIn("Imran Ahmed", text)
        self.assertIn("me@imrandev.bd", text)
        self.assertIn("https://imrandev.bd/", text)
        self.assertIn("DevOS creator", text)

    def test_empty_profile_points_to_my_profile(self):
        with mock.patch.object(op, "CONFIG_FILE", self.path):
            text = op.owner_answer_text(op.load_profile(self.path))
        self.assertIn("My Profile", text)

    def test_router_pc_owner_not_about(self):
        actions = _tools.route_clause("who owns this pc")
        self.assertIsNotNone(actions)
        self.assertEqual(actions[0].name, "pc_owner")
        about = _tools.route_clause("who made DevOS")
        self.assertIsNotNone(about)
        self.assertEqual(about[0].name, "about")

    def test_facts_line_mentions_owner(self):
        op.save_profile(
            {"display_name": "Test User", "email": "a@b.c", "portfolio": "https://example.com"},
            path=self.path,
        )
        line = op.owner_facts_line(op.load_profile(self.path))
        self.assertIn("Test User", line)
        self.assertIn("a@b.c", line)
        self.assertIn("https://example.com", line)


if __name__ == "__main__":
    unittest.main()
