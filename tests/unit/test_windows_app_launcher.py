"""Windows App menu entry must open Microsoft Cloud PC app window, not xdg-open."""

from pathlib import Path
import importlib.util
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components/cloudpc"))

import linux_client  # noqa: E402


def _load_wrapper_text() -> str:
    return (ROOT / "build/includes.chroot/usr/local/bin/devos-windows-app").read_text(
        encoding="utf-8"
    )


def test_wrapper_defaults_to_browser_launch_not_flatpak_client():
    text = _load_wrapper_text()
    assert "browser_launch.py" in text
    # Flatpak / unofficial client is opt-in only.
    assert "--install-client" in text
    assert "--native-client" in text
    # Default (no args) must not exec linux_client.py.
    assert 'if [ "$#" -eq 0 ]' not in text


def test_linux_client_default_opens_microsoft_pwa_not_xdg():
    with patch.object(linux_client.browser_launch, "open_isolated") as open_iso:
        with patch.object(linux_client.subprocess, "run") as run:
            assert linux_client.main() == 0
            open_iso.assert_called_once_with()
            run.assert_not_called()


def test_linux_client_falls_back_to_xdg_when_chrome_missing():
    with patch.object(
        linux_client.browser_launch, "open_isolated", side_effect=OSError("no chrome")
    ):
        with patch.object(linux_client.subprocess, "run", return_value=type("R", (), {"returncode": 0})()) as run:
            assert linux_client.main() == 0
            assert run.call_args[0][0][0] == "xdg-open"
