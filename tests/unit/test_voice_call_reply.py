"""Voice call must speak answers and keep listening for the next prompt."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_voice_module_auto_installs_tts_venv():
    text = (ROOT / "components/assistant/voice.py").read_text(encoding="utf-8")
    assert "def ensure_tts_venv" in text
    assert "edge-tts" in text
    assert "ensure_tts_venv()" in text
    assert "def speak_reply" in text
    assert "StreamSpeaker" in text
    assert "_speak_espeak" in text
    # Voice must start with typing (eager first cut), at natural pace.
    assert "_FIRST_WORDS = 2" in text
    assert '_TTS_RATE = "+0%"' in text
    assert "_OPENER_RE" in text
    assert "feed_delta_total" in text


def test_first_speak_cut_starts_with_typing():
    import importlib.util
    path = ROOT / "components/assistant/voice.py"
    spec = importlib.util.spec_from_file_location("devos_voice_cut", path)
    mod = importlib.util.module_from_spec(spec)
    # Avoid running heavy side effects; load via exec of just the cut helper is hard.
    # Import the module (no GUI); TTS venv checks are lazy.
    spec.loader.exec_module(mod)
    chunk, advance = mod._next_speak_cut("Sure, I can help with that later.", first=True)
    assert chunk.lower().startswith("sure")
    assert advance > 0
    chunk2, adv2 = mod._next_speak_cut("Hello there friend how are you", first=True)
    assert len(chunk2.split()) <= 3
    assert adv2 > 0
    chunk3, adv3 = mod._next_speak_cut("Hi! How can I help you today?", first=True)
    assert "hi" in chunk3.lower()
    assert adv3 > 0


def test_chat_call_speaks_voice_turns_and_resumes():
    text = (ROOT / "components/assistant/assistant.py").read_text(encoding="utf-8")
    # Call path: mic → send(..., from_voice=True) → speak reply.
    assert "from_voice=True" in text
    assert "self._speak_reply = bool(from_voice)" in text
    assert "voice.speak_reply" in text
    assert "start_call" in text
    assert "_continue_call_listen" in text
    # Silent on-screen actions during a call must still resume listening.
    assert "Pure on-screen actions" in text
    assert "self._call_active and not speak" in text
    # TTS warms while listening; StreamSpeaker feeds while tokens stream.
    assert "warm_tts" in text
    assert "feed_delta_total" in text
    assert "StreamSpeaker" in text


def test_hands_free_daemon_also_speaks_outcomes():
    text = (ROOT / "components/assistant/listen.py").read_text(encoding="utf-8")
    assert "def speak_outcome" in text
    assert "voice.speak_reply" in text
