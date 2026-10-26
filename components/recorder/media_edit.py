"""Non-destructive screen-recording edits. Commands never invoke a shell."""
import json
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass


@dataclass(frozen=True)
class Clip:
    start: float
    end: float

    @property
    def duration(self):
        return self.end - self.start


def probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", os.path.abspath(path)],
        capture_output=True, text=True, check=True, timeout=30)
    info = json.loads(result.stdout)
    if not any(s.get("codec_type") == "video" for s in info["streams"]):
        raise ValueError("Choose a file containing video.")
    duration = float(info["format"]["duration"])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("This video's duration could not be read.")
    return duration, any(s.get("codec_type") == "audio" for s in info["streams"])


def export_command(source, clips, duration, has_audio, audio_mode, voice, target):
    if not clips or len(clips) > 100:
        raise ValueError("Choose between 1 and 100 clips.")
    if audio_mode not in ("original", "mute", "replace", "mix"):
        raise ValueError("Unknown audio option.")
    for clip in clips:
        if not all(math.isfinite(v) for v in (clip.start, clip.end)) or not 0 <= clip.start < clip.end <= duration + .001:
            raise ValueError("Each clip must be inside the source video's duration.")
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", os.path.abspath(source)]
    if audio_mode in ("replace", "mix"):
        if not voice or not os.path.isfile(voice):
            raise ValueError("Choose an audio file for the voice track.")
        cmd += ["-i", os.path.abspath(voice)]
    original = has_audio and audio_mode in ("original", "mix")
    graph, inputs = [], []
    # split/asplit are necessary when the same source range is copied more than once.
    graph.append(f"[0:v:0]split={len(clips)}" + "".join(f"[sv{i}]" for i in range(len(clips))))
    if original:
        graph.append(f"[0:a:0]asplit={len(clips)}" + "".join(f"[sa{i}]" for i in range(len(clips))))
    for i, c in enumerate(clips):
        graph.append(f"[sv{i}]trim=start={c.start:.6f}:end={c.end:.6f},setpts=PTS-STARTPTS,setsar=1,pad=ceil(iw/2)*2:ceil(ih/2)*2[v{i}]")
        inputs.append(f"[v{i}]")
        if original:
            graph.append(f"[sa{i}]atrim=start={c.start:.6f}:end={c.end:.6f},asetpts=PTS-STARTPTS,apad,atrim=duration={c.duration:.6f}[a{i}]")
            inputs.append(f"[a{i}]")
    graph.append("".join(inputs) + f"concat=n={len(clips)}:v=1:a={int(original)}[video]" + ("[original]" if original else ""))
    total = sum(c.duration for c in clips)
    audio = "original" if original else None
    if audio_mode in ("replace", "mix"):
        graph.append(f"[1:a:0]asetpts=PTS-STARTPTS,apad,atrim=duration={total:.6f}[voice]")
        audio = "voice"
        if audio_mode == "mix" and original:
            graph.append("[original][voice]amix=inputs=2:duration=first:normalize=1[mixed]")
            audio = "mixed"
    cmd += ["-filter_complex", ";".join(graph), "-map", "[video]"]
    cmd += ["-map", f"[{audio}]", "-c:a", "aac", "-b:a", "192k"] if audio else ["-an"]
    return cmd + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                  "-t", f"{total:.6f}", "-movflags", "+faststart", target]


def export_video(source, clips, duration, has_audio, audio_mode, voice, destination):
    if os.path.realpath(source) == os.path.realpath(destination):
        raise ValueError("Save to a new file to preserve the original recording.")
    if os.path.exists(destination):
        raise ValueError("That file already exists. Choose a new filename.")
    fd, temporary = tempfile.mkstemp(prefix=".devos-edit-", suffix=".mp4", dir=os.path.dirname(os.path.abspath(destination)))
    os.close(fd)
    try:
        cmd = export_command(source, clips, duration, has_audio, audio_mode, voice, temporary)
        with tempfile.TemporaryFile(mode="w+") as log:
            result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=log)
            if result.returncode:
                log.seek(0, 2)
                length = log.tell()
                log.seek(max(0, length - 4000))
                raise RuntimeError(log.read() or "Video export failed.")
        probe(temporary)
        # Link creates the final file atomically without overwriting a racing save.
        os.link(temporary, destination)
    finally:
        os.unlink(temporary)


def finalize_capture(source, audio, target_format):
    """Mux capture outside the UI thread; keep source/audio if encoding fails."""
    if target_format not in ("mp4", "webm"):
        raise ValueError("Unsupported recording format")
    destination = os.path.splitext(source)[0] + "-saved." + target_format
    if os.path.exists(destination):
        raise ValueError("The recording destination already exists.")
    fd, temporary = tempfile.mkstemp(prefix=".devos-recording-", suffix="."+target_format,
                                     dir=os.path.dirname(os.path.abspath(source)))
    os.close(fd)
    try:
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", os.path.abspath(source)]
        has_audio = bool(audio and os.path.isfile(audio) and os.path.getsize(audio) > 44)
        if has_audio:
            cmd += ["-i", os.path.abspath(audio)]
        cmd += ["-map", "0:v:0"]
        if has_audio:
            cmd += ["-map", "1:a:0", "-af", "apad", "-shortest", "-c:a",
                    "aac" if target_format == "mp4" else "libopus"]
        else:
            cmd += ["-an"]
        if target_format == "mp4":
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-vf",
                    "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        else:
            cmd += ["-c:v", "copy"]
        with tempfile.TemporaryFile(mode="w+") as log:
            result = subprocess.run(cmd + [temporary], stdout=subprocess.DEVNULL, stderr=log)
            if result.returncode:
                log.seek(0)
                raise RuntimeError(log.read(4000) or "Could not encode recording")
        probe(temporary)
        os.link(temporary, destination)
        return destination
    finally:
        os.unlink(temporary)
