#!/usr/bin/env python3
"""
DevOS AI - reading attached documents.

The on-device model has a small context (4096 tokens, ~384 tokens out), so a
long document is never sent whole:

  * "summarize this"  -> map-reduce with at most MAX_CALLS model calls
                         (<= MAX_CALLS-1 section summaries + 1 combine)
  * any other question -> the most relevant chunks (keyword scoring) that fit
                         in CONTEXT_CHARS, then one model call

Text extraction:
  * .pdf          pdftotext -layout (poppler-utils)
  * .txt / .md    read directly
  * .docx         stdlib zip + XML (no python-docx needed)

The model is passed in as a plain function  ask(prompt:str) -> str  so all of
this is testable without the AI service.
"""

import os
import re
import shutil
import subprocess
import zipfile
from typing import Callable, List, Optional, Tuple

CONTEXT_CHARS = 6000      # what one model call may read
MAX_CALLS = 4
CHUNK_CHARS = 1200
MAX_FILE_BYTES = 60 * 1024 * 1024

PDF_EXT = {".pdf"}
TEXT_EXT = {".txt", ".md", ".markdown", ".log", ".csv", ".json", ".py", ".sh", ".ini", ".conf", ".yaml", ".yml"}
DOCX_EXT = {".docx"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
DOC_EXT = PDF_EXT | TEXT_EXT | DOCX_EXT

PDF_TOOL_MISSING = "Reading PDF files needs the DevOS PDF reader pack, which isn't installed on this PC yet."


def kind_of(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in PDF_EXT:
        return "pdf"
    if ext in DOCX_EXT:
        return "docx"
    if ext in TEXT_EXT:
        return "text"
    return "other"


def extract_text(path: str, which: Callable = shutil.which, runner: Optional[Callable] = None) -> Tuple[str, str]:
    """(text, problem). problem is "" on success, a user-facing note otherwise."""
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return "", "That file is too large to read here (over 60 MB)."
    except OSError:
        return "", "I can't open that file any more."
    kind = kind_of(path)
    if kind == "pdf":
        if not which("pdftotext"):
            return "", PDF_TOOL_MISSING
        argv = ["pdftotext", "-layout", "-enc", "UTF-8", path, "-"]
        if runner is not None:
            rc, out = runner(argv)
        else:
            try:
                p = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120)
                rc, out = p.returncode, p.stdout.decode("utf-8", "replace")
            except (OSError, subprocess.TimeoutExpired):
                rc, out = 1, ""
        if rc != 0:
            return "", "I couldn't read that PDF (it may be damaged or password-protected)."
        text = clean_text(out)
        if not text.strip():
            return "", ("This PDF has no text layer (it's a scan). Attach the pages as images and ask me "
                        "to read the text in them.")
        return text, ""
    if kind == "text":
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return clean_text(fh.read()), ""
        except OSError as exc:
            return "", f"I couldn't read that file ({exc.strerror})."
    if kind == "docx":
        text = docx_text(path)
        if text is None:
            return "", "I couldn't read that Word document."
        return clean_text(text), ""
    return "", "I can read PDF, Word (.docx), text and Markdown files, and images."


def docx_text(path: str) -> Optional[str]:
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    xml = re.sub(r"<w:br/>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&")):
        text = text.replace(a, b)
    return text


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n\n")
    text = re.sub(r"[ \t]{3,}", "  ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, size: int = CHUNK_CHARS) -> List[str]:
    """Split on paragraph boundaries into chunks of at most ~size chars."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    cur = ""
    for p in paras:
        while len(p) > size:
            cut = p.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            piece, p = p[:cut].strip(), p[cut:].strip()
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(piece)
        if cur and len(cur) + len(p) + 2 > size:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + "\n\n" + p) if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def _fit(chunks: List[str], budget: int) -> str:
    """Take evenly spaced chunks (keeping order) until the budget is used."""
    if not chunks:
        return ""
    total = sum(len(c) + 2 for c in chunks)
    if total <= budget:
        return "\n\n".join(chunks)
    n = max(1, budget // (max(len(c) for c in chunks) + 2))
    n = min(n, len(chunks))
    step = len(chunks) / n
    picked = [chunks[int(i * step)] for i in range(n)]
    out = "\n\n[…]\n\n".join(picked)
    return out[:budget]


def summary_plan(text: str, budget: int = CONTEXT_CHARS, max_calls: int = MAX_CALLS) -> List[str]:
    """Sections to summarise separately. len(plan) == 1 means one direct call."""
    text = text.strip()
    if len(text) <= budget:
        return [text]
    chunks = chunk_text(text)
    n_map = min(max_calls - 1, -(-len(text) // budget))
    n_map = max(2, n_map)
    per = -(-len(chunks) // n_map)
    sections = [chunks[i:i + per] for i in range(0, len(chunks), per)][:n_map]
    return [_fit(s, budget) for s in sections if s]


def summarize(text: str, ask: Callable[[str], str], name: str = "the document",
              budget: int = CONTEXT_CHARS, max_calls: int = MAX_CALLS) -> Tuple[str, int]:
    """Map-reduce summary. Returns (summary, number_of_model_calls)."""
    plan = summary_plan(text, budget, max_calls)
    if len(plan) == 1:
        prompt = (f"Summarize {name} below in 5-8 short bullet points, then one line saying what it is for.\n\n"
                  f"---\n{plan[0]}\n---")
        return ask(prompt).strip(), 1
    partials = []
    for i, section in enumerate(plan, 1):
        prompt = (f"This is part {i} of {len(plan)} of {name}. Write 3-5 short bullet points with the "
                  f"key facts from this part only.\n\n---\n{section}\n---")
        partials.append(ask(prompt).strip())
    joined = "\n\n".join(f"Part {i}:\n{p}" for i, p in enumerate(partials, 1))
    prompt = (f"Here are notes from each part of {name}. Combine them into one summary: 5-8 bullet points "
              f"in order, no repetition, then one line saying what the document is for.\n\n{joined[:budget]}")
    return ask(prompt).strip(), len(plan) + 1


_STOP = set("""a an the and or of to in on for with is are was were be been it this that these those what which who
whom how why when where do does did can could should would will shall may might i you he she we they me my your our
their its about from by as at into than then so if not no yes please tell me give show explain document pdf file
page pages say says said there here any all some""".split())


def keywords(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9ঀ-৿]{2,}", text.lower())
    out = []
    for w in words:
        if w in _STOP:
            continue
        w = re.sub(r"(?:ing|ed|es|s)$", "", w) if len(w) > 4 else w
        out.append(w)
    return out


def score_chunk(chunk: str, terms: List[str]) -> float:
    if not terms:
        return 0.0
    words = keywords(chunk)
    if not words:
        return 0.0
    bag = {}
    for w in words:
        bag[w] = bag.get(w, 0) + 1
    hits = sum(min(bag.get(t, 0), 3) for t in set(terms))
    distinct = sum(1 for t in set(terms) if t in bag)
    return distinct * 2 + hits / (1 + len(words) / 200)


def relevant_context(text: str, question: str, budget: int = CONTEXT_CHARS) -> str:
    chunks = chunk_text(text)
    if sum(len(c) for c in chunks) <= budget:
        return "\n\n".join(chunks)
    terms = keywords(question)
    ranked = sorted(range(len(chunks)), key=lambda i: (-score_chunk(chunks[i], terms), i))
    chosen, used = [], 0
    for i in ranked:
        if used + len(chunks[i]) > budget:
            continue
        chosen.append(i)
        used += len(chunks[i]) + 2
    if 0 not in chosen and used + len(chunks[0]) <= budget:
        chosen.append(0)        # the start usually says what the document is
    return "\n\n".join(chunks[i] for i in sorted(chosen))


def answer_question(text: str, question: str, ask: Callable[[str], str], name: str = "the document") -> str:
    ctx = relevant_context(text, question)
    prompt = (f"Answer the question using only the text from {name} below. If the answer is not in the text, "
              f"say so.\n\n---\n{ctx}\n---\n\nQuestion: {question}")
    return ask(prompt).strip()


SUMMARY_RE = re.compile(r"\b(?:summar\w*|sum up|tl;?dr|overview|gist|key points|main points|what(?:'s| is) (?:this|it|the)(?: \w+)? about)\b|সারাংশ|সংক্ষেপ")


def wants_summary(question: str) -> bool:
    q = (question or "").strip().lower()
    return not q or bool(SUMMARY_RE.search(q))
