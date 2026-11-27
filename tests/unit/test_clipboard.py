"""Clipboard reads and writes work with Wayland and older X11 applications."""

import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "devos_clipboard", ROOT / "components/clipboard/clipboard.py"
)
clipboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clipboard)


def result(text="", code=0):
    return SimpleNamespace(returncode=code, stdout=text)


def test_wayland_primary_selection_preserves_exact_text():
    run = Mock(return_value=result("  log line\n"))
    assert clipboard.read_clipboard(run, selection=True) == "  log line\n"
    run.assert_called_once_with(["wl-paste", "--no-newline", "--primary"])


def test_x11_selection_available_without_wayland():
    run = Mock(side_effect=[FileNotFoundError(), result("terminal text")])
    assert clipboard.read_clipboard(run, selection=True) == "terminal text"
    assert run.call_args.args[0] == ["xclip", "-selection", "primary", "-o"]


def test_clipboard_falls_back_after_timeout():
    run = Mock(side_effect=[subprocess.TimeoutExpired("wl-paste", 3), result("copied")])
    assert clipboard.read_clipboard(run) == "copied"


def test_write_wayland_clipboard():
    run = Mock(return_value=result())
    assert clipboard.write_clipboard("text\n", run)
    run.assert_called_once_with(["wl-copy"], input_text="text\n")


def test_write_x11_clipboard_when_wayland_unavailable():
    run = Mock(side_effect=[result(code=1), result()])
    assert clipboard.write_clipboard("text", run)
    assert run.call_args.args[0] == ["xclip", "-selection", "clipboard"]


def test_write_failure_is_reported():
    run = Mock(side_effect=FileNotFoundError())
    assert not clipboard.write_clipboard("text", run)
