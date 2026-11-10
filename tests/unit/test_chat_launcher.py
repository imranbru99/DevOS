#!/usr/bin/env python3
"""DevOS AI launcher must prefer Qt assistant; HTML page is recovery only."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "build/includes.chroot/usr/local/bin/devos-chat"
CHAT_HTML = ROOT / "components/dashboard/static/chat.html"
CHAT_HTML_CHROOT = (
    ROOT / "build/includes.chroot/usr/local/share/devos/components/dashboard/static/chat.html"
)
ASSISTANT = ROOT / "components/assistant/assistant.py"
ASSISTANT_CHROOT = (
    ROOT / "build/includes.chroot/usr/local/share/devos/components/assistant/assistant.py"
)
VOICE = ROOT / "components/assistant/voice.py"
VOICE_CHROOT = ROOT / "build/includes.chroot/usr/local/share/devos/components/assistant/voice.py"


def test_launcher_logs_and_retries_qt_before_fallback():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "chat-launch.log" in text
    assert "chat-fallback.reason" in text
    assert "retrying once" in text
    assert "startup_fail" in text
    assert "session_fail" in text
    assert "opening recovery page" in text
    # Must not treat a long successful session crash as HTML fallback.
    assert "not falling back" in text
    assert 'import PyQt5.QtWidgets' in text


def test_chat_html_is_recovery_not_bare_send_chat():
    for path in (CHAT_HTML, CHAT_HTML_CHROOT):
        html = path.read_text(encoding="utf-8")
        assert "Full assistant did not start" in html
        assert "Retry full assistant" in html
        assert "/api/actions/launch" in html
        assert 'action: "chat"' in html or '"action": "chat"' in html or '"action":"chat"' in html
        # Old primary chrome must not be the default view.
        assert "Ask DevOS AI anything: apps, files, Windows or Android programs" not in html
        assert "Your private assistant. Everything stays on this computer." not in html
        # Text-only is secondary / optional.
        assert "Text-only" in html


def test_assistant_call_status_labels_present():
    for path in (ASSISTANT, ASSISTANT_CHROOT):
        src = path.read_text(encoding="utf-8")
        assert "def _set_call_status" in src
        assert "Call · Listening" in src
        assert "Call · Speaking" in src
        assert "Call · Thinking" in src or "understanding" in src
        assert 'End call' in src


def test_voice_py_synced_to_chroot():
    assert VOICE.read_bytes() == VOICE_CHROOT.read_bytes()
    assert "class StreamSpeaker" in VOICE.read_text(encoding="utf-8")
    assert "ensure_tts_venv" in VOICE.read_text(encoding="utf-8")
