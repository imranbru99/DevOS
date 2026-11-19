"""Voice call must speak answers smoothly end-to-end and keep listening."""
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
    assert "def _espeak_voice_for" in text
    assert "en+f3" in text
    # Prefer full sentences — never cut after a single word.
    assert "_FIRST_WORDS = 10" in text
    assert '_TTS_RATE = "+0%"' in text
    assert "_OPENER_RE" in text
    assert "feed_delta_total" in text
    assert "Never abandon an in-flight queue read" in text
    # Female default must stay locked for a whole streamed reply.
    assert "self._gender = _tts_gender()" in text
    assert "self._voice = _edge_voice_for(self._lang, self._gender)" in text


def test_first_speak_cut_prefers_sentences_not_one_word():
    import importlib.util
    path = ROOT / "components/assistant/voice.py"
    spec = importlib.util.spec_from_file_location("devos_voice_cut", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # A greeting shares the first playback with the sentence that follows.
    assert mod._next_speak_cut("Hi!", first=True) == ("", 0)
    chunk3, adv3 = mod._next_speak_cut("Hi! How can I help you today?", first=True)
    assert chunk3 == "Hi! How can I help you today?"
    assert adv3 > 0

    # Full sentence is spoken as one unit.
    chunk, advance = mod._next_speak_cut(
        "Sure, I can help with that later. Next we can open Chrome.", first=True
    )
    assert "sure" in chunk.lower()
    assert "." in chunk or "later" in chunk.lower()
    assert advance > 0

    # Incomplete phrase: do NOT speak only the first word while more is coming.
    chunk2, adv2 = mod._next_speak_cut("Hello there friend", first=True)
    assert chunk2 == ""
    assert adv2 == 0

    # Longer unfinished phrase can cut at a natural word boundary.
    long = "Hello there friend how are you doing today my friend again"
    chunk4, adv4 = mod._next_speak_cut(long, first=True)
    assert adv4 > 0
    assert len(chunk4.split()) >= 8

    # Do not consume the tenth word while its last token is still arriving.
    incomplete = "This sentence has several complete words before the final frag"
    assert mod._next_speak_cut(incomplete, first=True) == ("", 0)
    bangla = "আমি আজ সকালে বাজারে গেলাম, তারপর বাসায় ফিরলাম; সবাই অপেক্ষা করছিল।"
    assert mod._next_speak_cut(bangla, first=True)[0] == bangla

    # Middle sentences must remain when splitting a full reply.
    plain = (
        "First sentence is here. Second sentence has more detail. "
        "Third sentence wraps it up."
    )
    chunks = []
    cursor = 0
    first = True
    while cursor < len(plain):
        piece, advance = mod._next_speak_cut(plain[cursor:], force=False, first=first)
        if not piece or advance <= 0:
            tail = plain[cursor:].strip()
            if tail:
                chunks.append(tail)
            break
        chunks.append(piece)
        cursor += advance
        first = False
    joined = " ".join(chunks)
    assert "First sentence" in joined
    assert "Second sentence" in joined
    assert "Third sentence" in joined
    # Already-buffered sentences share one clip, so the voice does not
    # pause at every full stop.
    assert len(chunks) == 1

    packed = " ".join(
        f"This is sentence {i}, with a comma; and a semicolon." for i in range(1, 16)
    )
    parts = []
    cursor = 0
    while cursor < len(packed):
        piece, advance = mod._next_speak_cut(packed[cursor:], force=False, first=False)
        if not piece or advance <= 0:
            break
        parts.append(piece)
        cursor += advance
    assert 1 < len(parts) < 15
    assert " ".join(parts).split() == packed.split()
    for piece in parts[:-1]:
        assert piece.rstrip().endswith(".")
        assert not piece.rstrip().endswith(",")
        assert not piece.rstrip().endswith(";")

    bangla_clause = (
        "আমি আজ সকালে বাজারে গেলাম, তারপর বাসায় ফিরলাম; সবাই অপেক্ষা করছিল। "
        "এরপর আবার বের হলাম।"
    )
    one, one_adv = mod._next_speak_cut(bangla_clause, first=False)
    assert one_adv >= len(bangla_clause.strip())
    assert "," in one and ";" in one and "।" in one

    listed = "1. Practice the interview questions carefully. 2. Prepare a clean resume tonight."
    listed_chunk, _listed_adv = mod._next_speak_cut(listed, first=True)
    assert listed_chunk.startswith("1. Practice")
    assert "resume" in listed_chunk


def test_bullet_list_starts_speaking_on_the_first_line():
    """A list with no full stops must not wait until the last bullet is typed."""
    import importlib.util
    path = ROOT / "components/assistant/voice.py"
    spec = importlib.util.spec_from_file_location("devos_voice_bullets", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    md = (
        "Sure! Here are the key requirements for a full-stack developer:\n\n"
        "- **Programming Skills:**\n"
        "- Proficiency in at least one server-side language (e.g., Python, Node.js, Java, .NET)\n"
        "- Familiarity with client-side languages (e.g., JavaScript, TypeScript)\n"
        "- **Database Knowledge:**\n"
        "- Experience with relational databases (e.g., MySQL, PostgreSQL)\n"
        "- Experience with cloud platforms (e.g., AWS)\n"
    )
    plain = mod.plain_for_speech(md, limit=0)
    assert "\n" in plain
    assert "AWS" in plain
    intro = plain.split("\n", 1)[0]
    # The opening line alone can still grow; speech starts once the next line begins.
    assert mod._next_speak_cut(intro, first=True, hold_short=True) == ("", 0)
    chunk, adv = mod._next_speak_cut(plain, first=True, hold_short=True)
    assert chunk.startswith("Sure!")
    assert "AWS" not in chunk
    assert "PostgreSQL" not in chunk
    assert adv < len(plain)
    # Commas inside a bullet are not a place to stop.
    assert "," in plain
    rest = plain[adv:]
    nxt, _nadv = mod._next_speak_cut(rest, first=False, hold_short=True)
    assert nxt
    assert not nxt.rstrip().endswith(",")
    assert not nxt.rstrip().endswith(";")


def test_plain_for_speech_keeps_long_answers():
    import importlib.util
    path = ROOT / "components/assistant/voice.py"
    spec = importlib.util.spec_from_file_location("devos_voice_plain", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    body = " ".join(f"Sentence number {i} is spoken fully." for i in range(1, 40))
    plain = mod.plain_for_speech(body)
    assert "Sentence number 1" in plain
    assert "Sentence number 30" in plain
    assert len(plain) > 480


def test_stream_speaker_keeps_delayed_middle_sentence_and_flushes_tail(monkeypatch):
    import importlib.util
    import threading
    from unittest.mock import Mock

    path = ROOT / "components/assistant/voice.py"
    spec = importlib.util.spec_from_file_location("devos_voice_stream", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    played = []
    first_played = threading.Event()

    def play(text, *args, **kwargs):
        played.append(text)
        first_played.set()
        return True

    monkeypatch.setattr(mod, "warm_tts", Mock())
    monkeypatch.setattr(mod, "_synthesize_to_file", Mock(return_value=False))
    monkeypatch.setattr(mod, "_speak_chunk", play)
    speaker = mod.StreamSpeaker()
    speaker.start("bn")
    try:
        speaker.feed_delta_total("প্রথম বাক্য।")
        # A dari that just landed, with nothing after it, is held for a moment.
        assert not first_played.wait(0.2)
        speaker.feed_delta_total("প্রথম বাক্য। দ্বিতীয় বাক্য। শেষ কথাটি")
        # The first sentence starts as soon as later words arrive — not after
        # the whole reply has been typed.
        assert first_played.wait(1.0)
        speaker.finish()
        assert played[0] == "প্রথম বাক্য।"
        assert "দ্বিতীয় বাক্য।" in played
        assert "শেষ কথাটি" in " ".join(played)
    finally:
        speaker.stop(kill_audio=False)


def test_detects_bangla_script_and_romanized():
    import importlib.util
    path = ROOT / "components/assistant/voice.py"
    spec = importlib.util.spec_from_file_location("devos_voice_lang", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.detect_user_language("আমি ভালো আছি") == "bn"
    assert mod.detect_user_language("ami kemon acho bhai") == "bn"
    assert mod.detect_user_language("thik ache dhonnobad") == "bn"
    assert mod.detect_user_language("Open Chrome and search laptops") == "en"
    assert mod.detect_user_language("السلام عليكم") == "auto"


def test_chat_call_speaks_voice_turns_and_resumes():
    text = (ROOT / "components/assistant/assistant.py").read_text(encoding="utf-8")
    # Call path: mic → send(..., from_voice=True) → speak reply.
    assert "from_voice=True" in text
    assert "self._speak_reply = bool(from_voice)" in text
    assert "voice.speak_reply" in text
    assert "start_call" in text
    assert "talk=bool(self._speak_reply)" in text
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
