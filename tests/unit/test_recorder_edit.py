import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "components/recorder"))
from media_edit import Clip, export_command, export_video, probe, finalize_capture
from audio_meter import pcm_peak, level_fraction


class RecorderTests(unittest.TestCase):
    def test_pcm_silence_peak_and_db_scale(self):
        self.assertEqual(pcm_peak(b"\0" * 100), 0)
        self.assertEqual(pcm_peak(struct.pack("<hhh", 0, -32768, 42)), 1)
        self.assertEqual(level_fraction(0), 0)
        self.assertAlmostEqual(level_fraction(.0316227766), .5)
        self.assertEqual(level_fraction(1), 1)

    def test_invalid_ranges_are_rejected(self):
        for clip in (Clip(-1, 2), Clip(2, 2), Clip(3, 2), Clip(0, 11), Clip(math.nan, 2)):
            with self.subTest(clip=clip), self.assertRaises(ValueError):
                export_command("source.mp4", [clip], 10, True, "original", None, "out.mp4")

    def test_paths_are_arguments_and_copies_split_streams(self):
        cmd = export_command("movie $x; test.mp4", [Clip(0, 2), Clip(0, 2)], 4, True, "original", None, "out.mp4")
        self.assertTrue(cmd[cmd.index("-i") + 1].endswith("movie $x; test.mp4"))
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("asplit=2", graph)
        self.assertIn("concat=n=2:v=1:a=1", graph)

    def test_original_and_existing_destination_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "original.mp4"
            source.write_bytes(b"original")
            for destination in (source, Path(tmp) / "existing.mp4"):
                destination.write_bytes(b"original")
                with self.assertRaises(ValueError):
                    export_video(str(source), [Clip(0, 1)], 1, False, "mute", None, str(destination))
                self.assertEqual(destination.read_bytes(), b"original")

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg integration requires installed runtime")
    def test_real_exports_trim_copy_cut_mute_replace_and_mix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source space;$.mp4"
            voice = root / "voice.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=20",
                            "-f", "lavfi", "-i", "sine=frequency=440", "-t", "4", "-c:v", "libx264", "-c:a", "aac", str(source)], check=True)
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=880", "-t", "0.5", str(voice)], check=True)
            original = source.read_bytes()
            duration, audio = probe(str(source))
            # Cut out 1..2 seconds; duplicate the last second at the end.
            clips = [Clip(0, 1), Clip(2, 4), Clip(3, 4)]
            for mode in ("original", "mute", "replace", "mix"):
                with self.subTest(mode=mode):
                    output = root / (mode + ".mp4")
                    export_video(str(source), clips, duration, audio, mode, str(voice), str(output))
                    exported_duration, exported_audio = probe(str(output))
                    self.assertAlmostEqual(exported_duration, 4, delta=.12)
                    self.assertEqual(exported_audio, mode != "mute")
            # Silent input must also support a multi-clip export without audio pads.
            silent = root / "silent.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-an", "-c:v", "copy", str(silent)], check=True)
            export_video(str(silent), [Clip(.5, 1.5)], 4, False, "original", None, str(root / "silent-edit.mp4"))
            self.assertFalse(probe(str(root / "silent-edit.mp4"))[1])
            capture = root / "capture.webm"
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(silent), "-c:v", "libvpx-vp9", str(capture)], check=True)
            for target_format in ("mp4", "webm"):
                saved = finalize_capture(str(capture), str(voice), target_format)
                saved_duration, saved_audio = probe(saved)
                self.assertAlmostEqual(saved_duration, 4, delta=.15)
                self.assertTrue(saved_audio)
            self.assertTrue(capture.exists())
            self.assertTrue(voice.exists())
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(list(root.glob(".devos-edit-*")), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
