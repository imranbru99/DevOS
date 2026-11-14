#!/usr/bin/env python3
"""Chrome (when installed) must become the default browser for app logins/OAuth."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "features"))

import features_cli as cli  # noqa: E402


def test_system_defaults_sets_chrome_browser_when_installed():
    defaults = cli.system_defaults({"chrome", "libreoffice"})
    assert defaults.get("browser") == "google-chrome.desktop"
    assert "documents" in defaults


def test_system_defaults_omits_browser_without_browser_feature():
    defaults = cli.system_defaults({"libreoffice"})
    assert "browser" not in defaults
