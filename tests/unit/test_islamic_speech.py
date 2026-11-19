"""Hadith/ayah speech must stay on one voice and Stop must not restart it."""
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _load_notifier():
    path = ROOT / "components" / "islamic" / "notifier.py"
    spec = importlib.util.spec_from_file_location("devos_islamic_notifier_speech", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


notifier = _load_notifier()


class IslamicSpeechTests(unittest.TestCase):
    def setUp(self):
        self._pkill = notifier._pkill_players
        notifier._pkill_players = lambda: None
        self._sleep = notifier._sleep_cancel
        notifier._sleep_cancel = lambda seconds, gen: not notifier._cancelled(gen)

    def tearDown(self):
        notifier._pkill_players = self._pkill
        notifier._sleep_cancel = self._sleep

    def test_chunks_cover_a_long_hadith_once_in_order(self):
        sentence = "রোগীর খোঁজখবর নেওয়া এবং তার সাথে সদাচরণ করা।"
        intro = "আজকের হাদিস।"
        text = intro + " " + " ".join([sentence] * 20)
        chunks = notifier._tts_chunks(text, limit=notifier._EDGE_CHUNK_CHARS)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(" ".join(chunks).split(), text.split())
        self.assertTrue(chunks[0].startswith(intro))
        self.assertTrue(all(intro not in part for part in chunks[1:]))

        words = ["কথা%d" % i for i in range(80)]
        long_sentence = " ".join(words)
        parts = notifier._tts_chunks(long_sentence, limit=220)
        self.assertGreater(len(parts), 1)
        self.assertEqual(" ".join(parts).split(), words)

    def test_speak_button_reads_the_whole_essay(self):
        source = (ROOT / "components" / "islamic" / "islamic_app.py").read_text(encoding="utf-8")
        self.assertIn("speak_text(self.text, self.lang, full=True)", source)
        body = (ROOT / "components" / "islamic" / "notifier.py").read_text(encoding="utf-8")
        self.assertNotIn("len(text) > 500", body)

        sentence = "The believer visits the sick and speaks kindly. "
        essay = (sentence * 30).strip()
        self.assertGreater(len(essay), 500)
        seen = {}

        def edge(text, language, gender=None, gen=None):
            seen["text"] = text
            return "ok"

        orig = notifier._speak_edge_tts
        notifier._speak_edge_tts = edge
        try:
            notifier.speak_text(essay, "en", full=True)
        finally:
            notifier._speak_edge_tts = orig
        self.assertEqual(seen["text"], essay)

    def test_notification_cuts_on_a_sentence_not_mid_word(self):
        essay = ("This is one sentence. " * 400).strip()
        seen = {}

        def edge(text, language, gender=None, gen=None):
            seen["text"] = text
            return "ok"

        orig = notifier._speak_edge_tts
        notifier._speak_edge_tts = edge
        try:
            notifier.speak_text(essay, "en", full=False)
        finally:
            notifier._speak_edge_tts = orig
        spoken = seen["text"]
        self.assertLessEqual(len(spoken), notifier._NOTIFY_SPEECH_CHARS)
        self.assertGreater(len(spoken), 500)
        self.assertTrue(spoken.endswith("."))
        self.assertNotEqual(spoken, essay)

    def test_mid_essay_failure_does_not_start_another_voice(self):
        essay = "আজকের হাদিস। " + ("একটি দীর্ঘ বাক্য যা হাদিসের অংশ। " * 25)
        espeak = []

        def edge(text, language, gender=None, gen=None):
            self.assertGreater(len(text), 500)
            return "partial"

        def offline(text, language, gender=None, gen=None):
            espeak.append(text)
            return True

        orig_edge, orig_espeak = notifier._speak_edge_tts, notifier._speak_espeak
        notifier._speak_edge_tts = edge
        notifier._speak_espeak = offline
        try:
            notifier.speak_text(essay, "bn", full=True)
        finally:
            notifier._speak_edge_tts = orig_edge
            notifier._speak_espeak = orig_espeak
        self.assertEqual(espeak, [])

    def test_stop_does_not_restart_from_the_beginning(self):
        essay = "আজকের হাদিস। " + ("থামাও এই বাক্যটি এখনই। " * 20)
        espeak = []

        def edge(text, language, gender=None, gen=None):
            notifier._stop_speech()
            return "fail"

        def offline(text, language, gender=None, gen=None):
            espeak.append(text)
            return True

        orig_edge, orig_espeak = notifier._speak_edge_tts, notifier._speak_espeak
        notifier._speak_edge_tts = edge
        notifier._speak_espeak = offline
        try:
            notifier.speak_text(essay, "bn", full=True)
        finally:
            notifier._speak_edge_tts = orig_edge
            notifier._speak_espeak = orig_espeak
        self.assertEqual(espeak, [])

    def test_offline_fallback_reads_the_same_full_text_once(self):
        essay = ("A complete sentence about the hadith. " * 20).strip()
        seen = {}

        def edge(text, language, gender=None, gen=None):
            seen["edge"] = text
            return "fail"

        def offline(text, language, gender=None, gen=None):
            seen.setdefault("espeak", []).append(text)
            return True

        orig_edge, orig_espeak = notifier._speak_edge_tts, notifier._speak_espeak
        notifier._speak_edge_tts = edge
        notifier._speak_espeak = offline
        try:
            notifier.speak_text(essay, "en", full=True)
        finally:
            notifier._speak_edge_tts = orig_edge
            notifier._speak_espeak = orig_espeak
        self.assertEqual(seen["edge"], essay)
        self.assertEqual(seen["espeak"], [essay])

    def test_later_chunk_failure_does_not_replay_the_opening(self):
        sentence = "রোগীর খোঁজখবর নেওয়া এবং তার সাথে সদাচরণ করা।"
        text = "আজকের হাদিস। " + " ".join([sentence] * 16)
        chunks = notifier._tts_chunks(text, limit=notifier._EDGE_CHUNK_CHARS)
        self.assertGreaterEqual(len(chunks), 3)
        synths, plays = [], []
        last_suffix = "-%d.mp3" % (len(chunks) - 1)

        def synth(py, chunk, voice, out, gen):
            synths.append((chunk, voice, out))
            # Fail only the final clip. Repeated sentences can share text.
            return not str(out).endswith(last_suffix)

        def play(path, gen=None):
            plays.append(path)
            return True

        orig_synth, orig_play = notifier._synth_edge_chunk, notifier._play_audio_file
        notifier._synth_edge_chunk = synth
        notifier._play_audio_file = play
        try:
            result = notifier._speak_edge_chunks(
                "python", text, "bn-BD-NabanitaNeural", notifier._speech_generation(),
            )
        finally:
            notifier._synth_edge_chunk = orig_synth
            notifier._play_audio_file = orig_play
        self.assertEqual(result, "partial")
        self.assertEqual(synths[0][0], chunks[0])
        self.assertEqual(sum(1 for _chunk, _voice, out in synths if str(out).endswith("-0.mp3")), 1)
        self.assertEqual({voice for _chunk, voice, _out in synths}, {"bn-BD-NabanitaNeural"})
        self.assertEqual(len(plays), len(chunks) - 1)
        self.assertTrue(plays[0].endswith("-0.mp3"))
        self.assertTrue(all(not path.endswith("-0.mp3") for path in plays[1:]))

    def test_stop_during_playback_does_not_continue(self):
        sentence = "রোগীর খোঁজখবর নেওয়া এবং তার সাথে সদাচরণ করা।"
        text = "আজকের হাদিস। " + " ".join([sentence] * 16)
        plays = []

        def synth(py, chunk, voice, out, gen):
            return voice == "bn-BD-NabanitaNeural"

        def play(path, gen=None):
            plays.append(path)
            notifier._stop_speech()
            return True

        orig_synth, orig_play = notifier._synth_edge_chunk, notifier._play_audio_file
        notifier._synth_edge_chunk = synth
        notifier._play_audio_file = play
        try:
            result = notifier._speak_edge_chunks(
                "python", text, "bn-BD-NabanitaNeural", notifier._speech_generation(),
            )
        finally:
            notifier._synth_edge_chunk = orig_synth
            notifier._play_audio_file = orig_play
        self.assertEqual(result, "cancelled")
        self.assertEqual(len(plays), 1)

    def test_espeak_stop_does_not_speak_the_next_chunk(self):
        calls = []

        def which(name):
            if name == "espeak-ng":
                return "/usr/bin/espeak-ng"
            return None

        def run(cmd, gen, timeout):
            calls.append(cmd[-1])
            notifier._stop_speech()
            return 0

        orig_which, orig_run = notifier.shutil.which, notifier._run_tracked
        notifier.shutil.which = which
        notifier._run_tracked = run
        try:
            gen = notifier._speech_generation()
            text = " ".join(["একটি বাক্য।"] * 40)
            self.assertGreater(len(notifier._tts_chunks(text, limit=160)), 1)
            ok = notifier._speak_espeak(text, "bn", gender="female", gen=gen)
        finally:
            notifier.shutil.which = orig_which
            notifier._run_tracked = orig_run
        self.assertFalse(ok)
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
