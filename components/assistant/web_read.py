#!/usr/bin/env python3
"""
Fetch a public web page and turn HTML into plain text for the local model.

Stdlib only. Used by the read_url tool when the user pastes a link and asks
to read, summarize, or speak the page (including Bangla “pore sunao”).
"""

from __future__ import annotations

import html as html_lib
import re
import urllib.error
import urllib.request
from typing import Callable, Optional, Tuple

MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 120_000
DEFAULT_TIMEOUT = 18.0
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 DevOS-AI/1.0"
)

_SCRIPT_RE = re.compile(
    r"<(script|style|noscript|svg|iframe|object|embed)[^>]*>.*?</\1>",
    re.I | re.S,
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\f\v]+")
_BLANK_RE = re.compile(r"\n{3,}")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_ARTICLE_RE = re.compile(r"<article\b[^>]*>(.*?)</article>", re.I | re.S)
_MAIN_RE = re.compile(r"<main\b[^>]*>(.*?)</main>", re.I | re.S)
_BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body>", re.I | re.S)
_META_DESC_RE = re.compile(
    r'<meta\b[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']'
    r"|<meta\b[^>]+content=[\"']([^\"']+)[\"'][^>]+name=[\"']description[\"']",
    re.I,
)
_BLOCK_BR_RE = re.compile(
    r"</(?:p|div|h[1-6]|li|tr|section|article|br|blockquote)>|<br\s*/?>",
    re.I,
)


def _strip_html(chunk: str) -> str:
    chunk = _SCRIPT_RE.sub(" ", chunk)
    chunk = _COMMENT_RE.sub(" ", chunk)
    chunk = _BLOCK_BR_RE.sub("\n", chunk)
    chunk = _TAG_RE.sub(" ", chunk)
    chunk = html_lib.unescape(chunk)
    chunk = _WS_RE.sub(" ", chunk)
    chunk = _BLANK_RE.sub("\n\n", chunk)
    return chunk.strip()


def html_to_text(raw_html: str) -> Tuple[str, str]:
    """Return (plain_text, title). Prefers <article>, then <main>, then <body>."""
    html = raw_html or ""
    title = ""
    m = _TITLE_RE.search(html)
    if m:
        title = _strip_html(m.group(1))[:200]

    body = ""
    for rx in (_ARTICLE_RE, _MAIN_RE, _BODY_RE):
        found = rx.search(html)
        if found and len(found.group(1)) > 80:
            body = found.group(1)
            break
    if not body:
        body = html

    text = _strip_html(body)
    if len(text) < 80:
        md = _META_DESC_RE.search(html)
        if md:
            desc = (md.group(1) or md.group(2) or "").strip()
            if desc:
                text = (text + "\n\n" + desc).strip() if text else desc
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS].rsplit(" ", 1)[0] + "…"
    return text, title


def fetch_page_text(
    url: str,
    timeout: float = DEFAULT_TIMEOUT,
    opener: Optional[Callable] = None,
) -> Tuple[str, str, str]:
    """Download url and extract readable text.

    Returns (text, title, error). error is empty on success.
    """
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        return "", "", "That doesn't look like a web address I can read."

    open_fn = opener or urllib.request.urlopen
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
        },
        method="GET",
    )
    try:
        with open_fn(req, timeout=timeout) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            raw = resp.read(MAX_HTML_BYTES + 1)
            final_url = getattr(resp, "geturl", lambda: url)()
    except urllib.error.HTTPError as exc:
        return "", "", f"The site returned HTTP {exc.code}."
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None) or exc
        return "", "", f"I couldn't reach that page ({reason})."
    except Exception as exc:
        return "", "", f"I couldn't download that page ({exc})."

    if len(raw) > MAX_HTML_BYTES:
        return "", "", "That page is too large to read here."

    # Plain text / markdown responses
    if "text/plain" in ctype or "text/markdown" in ctype:
        try:
            text = raw.decode("utf-8", "replace").strip()
        except Exception:
            text = raw.decode("latin-1", "replace").strip()
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS] + "…"
        if len(text) < 20:
            return "", "", "That page has almost no readable text."
        return text, final_url or url, ""

    if ctype and "html" not in ctype and "xml" not in ctype and "text/" not in ctype:
        return "", "", "That link is not a readable web page (it looks like a file download)."

    # Detect charset lightly from header or meta; fall back to utf-8
    charset = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype)
    if m:
        charset = m.group(1)
    try:
        html = raw.decode(charset, "replace")
    except LookupError:
        html = raw.decode("utf-8", "replace")

    text, title = html_to_text(html)
    if len(text) < 40:
        return "", title, "I opened the page but couldn't find enough article text to read."
    return text, title, ""
