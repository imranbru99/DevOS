#!/usr/bin/env python3
"""
DevOS AI - photos and images.

The chat model is text-only, so images go two ways:

1. Text in images (OCR) with the `tesseract` program when it is installed.
   Fast, small, handles "read the text in this image" with no download, so
   it is always tried first for read / extract-text requests.
2. Photo understanding ("what is in this picture", "describe this") with the
   small SmolVLM-256M-Instruct vision model (GGUF, Q8_0) run by llama.cpp's
   own `llama-mtmd-cli` from a pinned official release. llama-cpp-python's
   chat handlers cannot run SmolVLM's idefics3 projector, so the CLI is used
   as a subprocess. Model + runtime are downloaded once, after the user
   agrees, into ~/.local/share/devos/ai/vision/ and checked with sha256.

Nothing here is imported by the AI service; it is isolated so the chat keeps
working when any of it is missing.
"""

import hashlib
import os
import platform
import re
import shutil
import subprocess
import tarfile
import threading
import urllib.request
from typing import Callable, List, Optional, Tuple

VISION_DIR = os.path.expanduser("~/.local/share/devos/ai/vision")
RUNTIME_SUBDIR = "runtime"

FEATURE = "Photo understanding"

MODEL_BASE = "https://huggingface.co/ggml-org/SmolVLM-256M-Instruct-GGUF/resolve/main/"
LLAMA_RELEASE = "b11292"           # published 2026-09-30
LLAMA_ASSET = f"llama-{LLAMA_RELEASE}-bin-ubuntu-x64.tar.gz"
LLAMA_URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_RELEASE}/{LLAMA_ASSET}"

# (file name, url, bytes, sha256)
MODEL_FILE = ("SmolVLM-256M-Instruct-Q8_0.gguf", MODEL_BASE + "SmolVLM-256M-Instruct-Q8_0.gguf", 175054528,
              "2a31195d3769c0b0fd0a4906201666108834848db768af11de1d2cef7cd35e65")
MMPROJ_FILE = ("mmproj-SmolVLM-256M-Instruct-Q8_0.gguf", MODEL_BASE + "mmproj-SmolVLM-256M-Instruct-Q8_0.gguf",
               103769856, "7e943f7c53f0382a6fc41b6ee0c2def63ba4fded9ab8ed039cc9e2ab905e0edd")
RUNTIME_FILE = (LLAMA_ASSET, LLAMA_URL, 17454844, "3332a46b0fdb46bc8c7650f30b5cbf521c8ff409a6f394b5c2c612f050926440")
VISION_FILES = [MODEL_FILE, MMPROJ_FILE, RUNTIME_FILE]
DOWNLOAD_BYTES = sum(f[2] for f in VISION_FILES)

CLI = "llama-mtmd-cli"
# what to take from the release archive: the CLI and the libraries it loads
# (ggml CPU backends are picked at run time for the processor in this PC)
RUNTIME_MEMBERS = re.compile(r"^(?:llama-mtmd-cli|LICENSE|lib(?:ggml|ggml-base|ggml-cpu-[\w-]+|llama|llama-common|mtmd)"
                             r"\.so(?:\.[\d.]+)?)$")

OCR_MISSING = "Reading text in images needs the DevOS text recognition pack, which isn't installed on this PC yet."


def download_size_label() -> str:
    mb = DOWNLOAD_BYTES / 1e6
    return f"{mb:,.0f} MB" if mb < 1000 else f"{mb / 1000:.1f} GB"


def download_button_label() -> str:
    return f"{FEATURE} — one-time {download_size_label()} download"


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------


def ocr_available(which: Callable = shutil.which) -> bool:
    return which("tesseract") is not None


def ocr_languages(runner: Optional[Callable] = None) -> List[str]:
    try:
        p = subprocess.run(["tesseract", "--list-langs"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=10, text=True)
        langs = [l.strip() for l in p.stdout.splitlines()[1:] if l.strip()]
        return langs
    except (OSError, subprocess.TimeoutExpired):
        return []


def _run_tesseract(img_path: str, lang: str) -> str:
    try:
        p = subprocess.run(["tesseract", img_path, "-", "-l", lang], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, timeout=25)
        if p.returncode == 0:
            return p.stdout.decode("utf-8", "replace").strip()
    except Exception:
        pass
    return ""


def ocr(path: str, which: Callable = shutil.which) -> Tuple[str, str]:
    """(text, problem). Robust extraction with camera EXIF sanitization and multi-channel contrast."""
    if not ocr_available(which):
        return "", OCR_MISSING
    langs = ocr_languages()
    lang = "+".join(l for l in ("eng", "ben") if l in langs) or "eng"

    raw_text = _run_tesseract(path, lang)
    if len(raw_text) >= 150:
        return raw_text, ""

    try:
        from PIL import Image, ImageOps
        import numpy as np
        im = Image.open(path)
        im = ImageOps.exif_transpose(im)
    except Exception:
        im = None

    if im is None:
        if raw_text:
            return raw_text, ""
        return "", "I couldn't read that image."

    results = [raw_text] if raw_text else []
    angles = [0, 90] if max(im.size) / (min(im.size) or 1) >= 1.2 else [0]
    candidates = []
    for angle in angles:
        cur = im.rotate(angle, expand=True) if angle != 0 else im
        candidates.append(cur)
        arr = np.array(cur)
        if len(arr.shape) == 3 and arr.shape[2] >= 3:
            # Green channel sharply separates red ink (NIDs, stamps, serial numbers) from blue/green backgrounds
            candidates.append(Image.fromarray(arr[:, :, 1]))

    import tempfile
    for cand in candidates:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_name = tmp.name
        try:
            cand.save(tmp_name, "PNG")
            txt = _run_tesseract(tmp_name, lang)
            if txt:
                results.append(txt)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass

    seen = set()
    merged = []
    for r in results:
        for line in r.splitlines():
            s = line.strip()
            if len(s) >= 2 and s not in seen:
                seen.add(s)
                merged.append(s)

    final_text = "\n".join(merged).strip()
    if not final_text:
        return "", "I didn't find any text in this image."
    return final_text, ""


# ---------------------------------------------------------------------------
# Photo understanding
# ---------------------------------------------------------------------------


def runtime_supported(system: Optional[str] = None, machine: Optional[str] = None) -> Tuple[bool, str]:
    """The prebuilt runtime is for 64-bit Intel / AMD Linux."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if system != "Linux" or machine not in ("x86_64", "amd64"):
        return False, "it needs a 64-bit Intel or AMD processor."
    return True, ""


def runtime_dir(vision_dir: str = VISION_DIR) -> str:
    return os.path.join(vision_dir, RUNTIME_SUBDIR)


def cli_path(vision_dir: str = VISION_DIR) -> str:
    return os.path.join(runtime_dir(vision_dir), CLI)


def model_paths(vision_dir: str = VISION_DIR) -> Tuple[str, str]:
    return os.path.join(vision_dir, MODEL_FILE[0]), os.path.join(vision_dir, MMPROJ_FILE[0])


def model_installed(vision_dir: str = VISION_DIR) -> bool:
    for name, _url, size, _sha in (MODEL_FILE, MMPROJ_FILE):
        if not _complete(vision_dir, name, size):
            return False
    return os.access(cli_path(vision_dir), os.X_OK)


def _complete(vision_dir: str, name: str, size: int) -> bool:
    try:
        return os.path.getsize(os.path.join(vision_dir, name)) == size
    except OSError:
        return False


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def extract_runtime(archive: str, dest: str) -> List[str]:
    """Unpack only the CLI and its libraries, flat, into dest. Refuses unsafe members."""
    os.makedirs(dest, exist_ok=True)
    taken = []
    links = []
    with tarfile.open(archive, "r:gz") as tf:
        for m in tf.getmembers():
            name = m.name
            if name.startswith("/") or ".." in name.split("/"):
                raise ValueError("unsafe path in archive")
            base = os.path.basename(name)
            if not RUNTIME_MEMBERS.match(base):
                continue
            target = os.path.join(dest, base)
            if m.issym():
                if "/" in m.linkname or not RUNTIME_MEMBERS.match(m.linkname):
                    raise ValueError("unsafe link in archive")
                links.append((m.linkname, target))
            elif m.isfile():
                src = tf.extractfile(m)
                tmp = target + ".tmp"
                with open(tmp, "wb") as out:
                    shutil.copyfileobj(src, out)
                os.chmod(tmp, 0o755 if (m.mode & 0o111) else 0o644)
                os.replace(tmp, target)
            else:
                continue
            taken.append(base)
    for linkname, target in links:
        try:
            if os.path.lexists(target):
                os.remove(target)
            os.symlink(linkname, target)
        except OSError:
            shutil.copy2(os.path.join(dest, linkname), target)
    if CLI not in taken:
        raise ValueError("the runtime archive is missing its program")
    return taken


def _have(vision_dir: str, f) -> bool:
    if f[0] == RUNTIME_FILE[0]:
        try:
            with open(os.path.join(runtime_dir(vision_dir), ".release")) as fh:
                same = fh.read().strip() == LLAMA_RELEASE
        except OSError:
            same = False
        return same and os.access(cli_path(vision_dir), os.X_OK)
    return _complete(vision_dir, f[0], f[2])


def download_model(progress: Callable[[int, int], None] = lambda done, total: None,
                   cancel: Optional[threading.Event] = None, vision_dir: str = VISION_DIR,
                   opener: Callable = urllib.request.urlopen, verify: bool = True) -> Tuple[bool, str]:
    """Download (resumable) and verify the photo model and its runtime. Returns (ok, message)."""
    os.makedirs(vision_dir, exist_ok=True)
    pending = [f for f in VISION_FILES if not _have(vision_dir, f)]
    try:
        free = shutil.disk_usage(vision_dir).free
    except OSError:
        free = None
    need = sum(f[2] for f in pending) + 64 * 1024 * 1024
    if free is not None and need > free - 256 * 1024 * 1024:
        return False, f"There isn't enough free disk space for {FEATURE.lower()}."
    done = DOWNLOAD_BYTES - sum(f[2] for f in pending)
    progress(done, DOWNLOAD_BYTES)
    for name, url, size, sha in pending:
        dest = os.path.join(vision_dir, name)
        part = dest + ".partial"
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if have > size:
            os.remove(part)
            have = 0
        if have < size:
            req = urllib.request.Request(url, headers={"User-Agent": "DevOS-AI/1.0"})
            if have:
                req.add_header("Range", f"bytes={have}-")
            try:
                with opener(req, timeout=60) as resp:
                    if have and getattr(resp, "status", 200) != 206:
                        have = 0
                    with open(part, "ab" if have else "wb") as out:
                        cur = done + have
                        while True:
                            if cancel is not None and cancel.is_set():
                                return False, "Download paused. It will continue where it stopped."
                            block = resp.read(1024 * 1024)
                            if not block:
                                break
                            out.write(block)
                            cur += len(block)
                            progress(min(cur, DOWNLOAD_BYTES), DOWNLOAD_BYTES)
            except OSError as exc:
                return False, f"The download stopped ({getattr(exc, 'reason', exc)}). Try again to continue."
        if os.path.getsize(part) != size:
            return False, "The download is incomplete. Try again to continue."
        if verify and _sha256(part) != sha:
            os.remove(part)
            return False, "The downloaded file was damaged and has been removed. Please try again."
        if name == RUNTIME_FILE[0]:
            try:
                extract_runtime(part, runtime_dir(vision_dir))
            except (OSError, ValueError, tarfile.TarError):
                return False, f"{FEATURE} couldn't be set up from the download. Please try again."
            os.remove(part)
            with open(os.path.join(runtime_dir(vision_dir), ".release"), "w") as fh:
                fh.write(LLAMA_RELEASE + "\n")
        else:
            os.replace(part, dest)
        done += size
        progress(done, DOWNLOAD_BYTES)
    if not model_installed(vision_dir):
        return False, "The download is incomplete. Try again to continue."
    return True, f"{FEATURE} is ready."


def describe_command(image: str, question: str = "", vision_dir: str = VISION_DIR,
                     threads: Optional[int] = None) -> List[str]:
    model, mmproj = model_paths(vision_dir)
    prompt = (question or "").strip() or "Describe this image in two or three sentences."
    threads = threads or max(2, min(8, os.cpu_count() or 2))
    return [cli_path(vision_dir), "-m", model, "--mmproj", mmproj, "--image", image, "-p", prompt,
            "-n", "200", "--temp", "0.2", "-t", str(threads), "-lv", "0"]


MAX_SIDE = 1024      # ~3x faster than a full-size photo with the same answers; 512 px loses detail


def downscaled_copy(path: str, max_side: int = MAX_SIDE) -> Optional[str]:
    """A temporary JPEG no larger than max_side (uses Qt's image reader when available)."""
    try:
        from PyQt5.QtCore import QSize, Qt
        from PyQt5.QtGui import QImageReader
    except Exception:
        return None
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or max(size.width(), size.height()) <= max_side:
        return None
    reader.setScaledSize(size.scaled(QSize(max_side, max_side), Qt.KeepAspectRatio))
    img = reader.read()
    if img.isNull():
        return None
    import tempfile
    fd, out = tempfile.mkstemp(prefix="devos-photo-", suffix=".jpg")
    os.close(fd)
    if not img.save(out, "JPEG", 92):
        os.remove(out)
        return None
    return out


def clean_answer(stdout: str) -> str:
    text = (stdout or "").replace("\r", "")
    text = re.sub(r"<end_of_utterance>|<\|im_end\|>|</s>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class VisionModel:
    """Runs the photo model through the downloaded CLI, one request at a time."""

    _lock = threading.Lock()

    @classmethod
    def describe(cls, path: str, question: str = "", vision_dir: str = VISION_DIR,
                 runner: Optional[Callable] = None) -> str:
        ok, why = runtime_supported()
        if not ok:
            raise RuntimeError(why)
        if not model_installed(vision_dir):
            raise RuntimeError("The photo model is not downloaded yet.")
        small = downscaled_copy(path) if runner is None else None
        try:
            return cls._run(small or path, question, vision_dir, runner)
        finally:
            if small:
                try:
                    os.remove(small)
                except OSError:
                    pass

    @classmethod
    def _run(cls, path, question, vision_dir, runner):
        argv = describe_command(path, question, vision_dir)
        env = dict(os.environ)
        rt = runtime_dir(vision_dir)
        env["LD_LIBRARY_PATH"] = rt + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
        with cls._lock:
            if runner is not None:
                rc, out = runner(argv, env)
            else:
                try:
                    p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                       cwd=rt, timeout=240)
                    rc, out = p.returncode, p.stdout.decode("utf-8", "replace")
                except subprocess.TimeoutExpired:
                    raise RuntimeError("Looking at the photo took too long.")
                if rc == 127 and b"shared libraries" in (p.stderr or b""):
                    # e.g. libgomp1 (OpenMP runtime) missing from the system
                    raise RuntimeError("A system component that photo understanding needs is missing on this PC.")
        if rc != 0:
            raise RuntimeError("The photo model stopped unexpectedly.")
        answer = clean_answer(out)
        if not answer:
            raise RuntimeError("The photo model gave no answer.")
        return answer
