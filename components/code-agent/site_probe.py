#!/usr/bin/env python3
"""Live site / preview probes for DevOS AI Code Agent.

Local models miss real bugs on large sites because they only see truncated
source. This module collects a compact evidence pack from a running URL:

  - HTTP status, redirects, timing, content-type, title
  - Empty/near-empty body heuristics
  - Missing linked CSS/JS (404)
  - Optional headless Chromium: console errors + failed network requests
  - Structured DOM summary (landmarks, headings, empty roots) — not raw HTML

Privacy: only http(s) URLs; file/javascript/data blocked. Prefer localhost /
user-supplied preview URLs. Output is capped for small local context windows.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

MAX_REPORT_CHARS = 4500
MAX_BODY_SCAN = 250_000
MAX_ASSET_CHECKS = 12
EMPTY_BODY_CHARS = 80
CONSOLE_CAP = 12
NETWORK_FAIL_CAP = 12

_BLOCKED_SCHEMES = ("file", "javascript", "data", "vbscript", "about")


class _DomSummary(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._in_title = False
        self.headings: List[str] = []
        self.landmarks: List[str] = []
        self.forms = 0
        self.images = 0
        self.scripts = 0
        self.links_css = 0
        self.empty_ids: List[str] = []
        self.text_chars = 0
        self._skip_depth = 0
        self._open_empty: Dict[str, Optional[str]] = {}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        ad = {k: (v or "") for k, v in attrs}
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in ("main", "nav", "header", "footer", "aside") or ad.get("role") in (
            "main", "navigation", "banner", "contentinfo", "complementary",
        ):
            label = tag if tag in ("main", "nav", "header", "footer", "aside") else ad.get("role", tag)
            if label not in self.landmarks:
                self.landmarks.append(label)
        if tag in ("h1", "h2", "h3") and len(self.headings) < 12:
            self.headings.append(tag)
        if tag == "form":
            self.forms += 1
        if tag == "img":
            self.images += 1
        if tag == "script" and ad.get("src"):
            self.scripts += 1
        if tag == "link" and "stylesheet" in ad.get("rel", "").lower():
            self.links_css += 1
        eid = ad.get("id")
        if eid in ("app", "root", "__next", "main", "content") or ad.get("data-reactroot") is not None:
            self._open_empty[eid or "react-root"] = tag

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript") and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        # Close empty-candidate tracking loosely by tag name.
        for key, open_tag in list(self._open_empty.items()):
            if open_tag == tag:
                if key not in self.empty_ids:
                    self.empty_ids.append(key)
                del self._open_empty[key]

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title and not self.title:
            self.title = text[:120]
        self.text_chars += len(text)
        # Any text inside a tracked empty root means it is not empty.
        if self._open_empty:
            self._open_empty.clear()


def normalize_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("probe_site needs url.")
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    if parsed.scheme.lower() in _BLOCKED_SCHEMES:
        raise ValueError(f"Blocked URL scheme: {parsed.scheme}")
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError("Only http(s) preview URLs are allowed.")
    return raw


def _http_get(url: str, timeout: float = 12.0) -> Tuple[int, Dict[str, str], bytes, float, str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "DevOS-SiteProbe/1.0", "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
        method="GET",
    )
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final = resp.geturl()
        status = getattr(resp, "status", None) or resp.getcode()
        headers = {k.lower(): v for k, v in resp.headers.items()}
        body = resp.read(MAX_BODY_SCAN)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return int(status), headers, body, elapsed_ms, final


def _extract_assets(base: str, html: str) -> List[str]:
    hrefs = re.findall(
        r"""(?:href|src)\s*=\s*["']([^"']+\.(?:css|js)(?:\?[^"']*)?)["']""",
        html,
        flags=re.I,
    )
    out: List[str] = []
    seen = set()
    for href in hrefs:
        full = urljoin(base, href)
        if full in seen:
            continue
        seen.add(full)
        out.append(full)
        if len(out) >= MAX_ASSET_CHECKS:
            break
    return out


def _check_asset(url: str) -> Optional[str]:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "DevOS-SiteProbe/1.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            code = int(getattr(resp, "status", None) or resp.getcode())
            if code >= 400:
                return f"{code} {url}"
    except urllib.error.HTTPError as exc:
        return f"{exc.code} {url}"
    except Exception:
        # Some servers reject HEAD — try a tiny GET.
        try:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": "DevOS-SiteProbe/1.0", "Range": "bytes=0-0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                code = int(getattr(resp, "status", None) or resp.getcode())
                if code >= 400:
                    return f"{code} {url}"
        except urllib.error.HTTPError as exc:
            return f"{exc.code} {url}"
        except Exception as exc:
            return f"error {url} ({type(exc).__name__})"
    return None


def _find_chromium() -> Optional[str]:
    for name in (
        "google-chrome-stable", "google-chrome", "chromium-browser", "chromium",
        "brave-browser", "microsoft-edge",
    ):
        path = shutil.which(name)
        if path:
            return path
    for path in (
        "/usr/bin/google-chrome-stable",
        "/opt/google/chrome/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


_CDP_SCRIPT = r'''
const puppeteer = (() => { try { return require("puppeteer-core"); } catch { return null; } })();
(async () => {
  const url = process.argv[2];
  const chrome = process.argv[3];
  const outPath = process.argv[4];
  const result = { console: [], network_failures: [], title: "", body_text_len: 0, empty_root: false };
  if (!puppeteer) {
    result.error = "puppeteer-core not installed";
    require("fs").writeFileSync(outPath, JSON.stringify(result));
    process.exit(0);
  }
  const browser = await puppeteer.launch({
    executablePath: chrome,
    headless: "new",
    args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
  });
  try {
    const page = await browser.newPage();
    page.on("console", (msg) => {
      const type = msg.type();
      if (type === "error" || type === "warning") {
        result.console.push({ type, text: String(msg.text()).slice(0, 240) });
      }
    });
    page.on("pageerror", (err) => {
      result.console.push({ type: "pageerror", text: String(err).slice(0, 240) });
    });
    page.on("requestfailed", (req) => {
      result.network_failures.push({
        url: req.url().slice(0, 200),
        error: (req.failure() && req.failure().errorText) || "failed",
      });
    });
    page.on("response", (res) => {
      const s = res.status();
      if (s >= 400) {
        result.network_failures.push({ url: res.url().slice(0, 200), error: "HTTP " + s });
      }
    });
    await page.goto(url, { waitUntil: "networkidle2", timeout: 20000 }).catch(() => {});
    result.title = await page.title();
    const info = await page.evaluate(() => {
      const root = document.querySelector("#app, #root, #__next, main, [data-reactroot]");
      const text = (document.body && document.body.innerText) || "";
      return {
        body_text_len: text.trim().length,
        empty_root: !!(root && !(root.innerText || "").trim() && root.children.length === 0),
      };
    });
    Object.assign(result, info);
  } catch (e) {
    result.error = String(e).slice(0, 200);
  } finally {
    await browser.close().catch(() => {});
  }
  require("fs").writeFileSync(outPath, JSON.stringify(result));
})();
'''


def _chromium_probe(url: str, timeout: float = 35.0) -> Dict[str, Any]:
    chrome = _find_chromium()
    if not chrome:
        return {"skipped": "no chromium binary"}
    node = shutil.which("node")
    if not node:
        return {"skipped": "node not available for headless probe"}
    # Prefer a tiny inline script without requiring puppeteer — use Chrome remote debugging via a simpler path.
    # Fall back: dump console via chrome --dump-dom is limited; use urllib-only findings if CDP deps missing.
    try:
        import importlib.util
        if importlib.util.find_spec("puppeteer_core") is None and importlib.util.find_spec("pyppeteer") is None:
            # Lightweight alternative: load page with chromium --headless --dump-dom and scan for error strings.
            return _chromium_dump_dom(chrome, url, timeout)
    except Exception:
        return _chromium_dump_dom(chrome, url, timeout)

    with tempfile.TemporaryDirectory(prefix="devos-probe-") as tmp:
        script = os.path.join(tmp, "probe.js")
        out_path = os.path.join(tmp, "out.json")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(_CDP_SCRIPT)
        try:
            subprocess.run(
                [node, script, url, chrome, out_path],
                capture_output=True, text=True, timeout=timeout,
                cwd=tmp,
            )
            if os.path.isfile(out_path):
                with open(out_path, encoding="utf-8") as handle:
                    data = json.load(handle)
                data["console"] = (data.get("console") or [])[:CONSOLE_CAP]
                data["network_failures"] = (data.get("network_failures") or [])[:NETWORK_FAIL_CAP]
                return data
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}
    return {"skipped": "headless probe failed"}


def _chromium_dump_dom(chrome: str, url: str, timeout: float) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            [
                chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
                "--virtual-time-budget=8000", "--dump-dom", url,
            ],
            capture_output=True, text=True, timeout=timeout,
        )
        html = proc.stdout or ""
        findings: List[str] = []
        low = html.lower()
        for needle, label in (
            ("uncaught ", "possible uncaught JS in markup"),
            ("syntaxerror", "SyntaxError mentioned in page"),
            ("failed to load resource", "failed resource mentioned"),
            ("cannot get", "HTTP error phrase in body"),
            ("whoops, looks like something went wrong", "Laravel error page"),
            ("exception", "exception text in body"),
        ):
            if needle in low:
                findings.append(label)
        parser = _DomSummary()
        try:
            parser.feed(html[:MAX_BODY_SCAN])
        except Exception:
            pass
        return {
            "title": parser.title,
            "body_text_len": parser.text_chars,
            "empty_root": bool(parser.empty_ids) and parser.text_chars < EMPTY_BODY_CHARS,
            "dom_findings": findings,
            "mode": "dump-dom",
        }
    except Exception as exc:
        return {"error": f"dump-dom {type(exc).__name__}: {exc}"}


def probe_site(url: str, *, headless: bool = True) -> Dict[str, Any]:
    """Return a structured probe report for url."""
    target = normalize_url(url)
    report: Dict[str, Any] = {"url": target, "findings": [], "ok": False}

    try:
        status, headers, body, elapsed_ms, final = _http_get(target)
    except urllib.error.HTTPError as exc:
        report["http"] = {"status": exc.code, "error": str(exc.reason)}
        report["findings"].append(f"HTTP {exc.code} on {target}")
        return report
    except Exception as exc:
        report["http"] = {"error": f"{type(exc).__name__}: {exc}"}
        report["findings"].append(f"Request failed: {type(exc).__name__}: {exc}")
        return report

    ctype = headers.get("content-type", "")
    text = ""
    try:
        text = body.decode(headers.get("content-type", "").split("charset=")[-1].strip()
                           if "charset=" in ctype else "utf-8", errors="replace")
    except Exception:
        text = body.decode("utf-8", errors="replace")

    parser = _DomSummary()
    try:
        parser.feed(text)
    except Exception:
        pass

    title = parser.title
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()[:120]

    http_info = {
        "status": status,
        "final_url": final,
        "elapsed_ms": elapsed_ms,
        "content_type": ctype.split(";")[0],
        "bytes": len(body),
        "title": title,
        "text_chars": parser.text_chars,
        "landmarks": parser.landmarks[:8],
        "headings": parser.headings[:8],
        "forms": parser.forms,
        "images": parser.images,
        "script_tags_with_src": parser.scripts,
        "stylesheets": parser.links_css,
    }
    report["http"] = http_info

    if status >= 400:
        report["findings"].append(f"HTTP {status}")
    if final.rstrip("/") != target.rstrip("/"):
        report["findings"].append(f"Redirected to {final}")
    if parser.text_chars < EMPTY_BODY_CHARS:
        report["findings"].append(
            f"Near-empty page body ({parser.text_chars} visible text chars) — blank render or shell-only SPA"
        )
    if parser.empty_ids:
        report["findings"].append(f"Empty app roots: {', '.join(parser.empty_ids)}")
    if "text/html" in ctype and parser.scripts == 0 and parser.links_css == 0 and parser.text_chars < 200:
        report["findings"].append("HTML shell with no CSS/JS assets and little text")

    low = text.lower()
    for needle, label in (
        ("whoops, looks like something went wrong", "Laravel Whoops / error page"),
        ("exceptiontrace", "PHP exception trace"),
        ("sqlstate", "SQL error exposed"),
        ("nginx error", "Nginx error page"),
        ("cannot get /", "Express Cannot GET"),
        ("404 not found", "404 not found page"),
        ("500 internal server error", "500 page"),
    ):
        if needle in low:
            report["findings"].append(label)

    missing = []
    for asset in _extract_assets(final, text):
        hit = _check_asset(asset)
        if hit:
            missing.append(hit)
    if missing:
        report["missing_assets"] = missing[:MAX_ASSET_CHECKS]
        report["findings"].append(f"{len(missing)} CSS/JS asset(s) failed to load")

    if headless:
        head = _chromium_probe(final)
        report["headless"] = {
            k: head[k] for k in head
            if k in ("title", "body_text_len", "empty_root", "console", "network_failures",
                     "dom_findings", "mode", "skipped", "error")
        }
        for item in (head.get("console") or [])[:CONSOLE_CAP]:
            report["findings"].append(f"console {item.get('type')}: {item.get('text')}")
        for item in (head.get("network_failures") or [])[:NETWORK_FAIL_CAP]:
            report["findings"].append(f"network {item.get('error')}: {item.get('url')}")
        for item in head.get("dom_findings") or []:
            report["findings"].append(str(item))
        if head.get("empty_root"):
            report["findings"].append("Headless: empty #app/#root/__next")
        if head.get("body_text_len") is not None and head["body_text_len"] < EMPTY_BODY_CHARS:
            report["findings"].append(f"Headless visible text only {head['body_text_len']} chars")

    # De-dupe findings while preserving order
    seen = set()
    uniq = []
    for f in report["findings"]:
        if f not in seen:
            seen.add(f)
            uniq.append(f)
    report["findings"] = uniq
    report["ok"] = status < 400 and not uniq
    return report


def format_probe_report(report: Dict[str, Any]) -> str:
    """Compact text for the local model context window."""
    lines = [f"Site probe: {report.get('url')}"]
    http = report.get("http") or {}
    if http.get("status") is not None:
        lines.append(
            f"HTTP {http.get('status')} in {http.get('elapsed_ms')}ms "
            f"({http.get('content_type')}, {http.get('bytes')} bytes) title={http.get('title')!r}"
        )
        lines.append(
            f"DOM: text_chars={http.get('text_chars')} landmarks={http.get('landmarks')} "
            f"headings={http.get('headings')} forms={http.get('forms')} "
            f"css={http.get('stylesheets')} js={http.get('script_tags_with_src')}"
        )
    elif http.get("error"):
        lines.append(f"HTTP error: {http['error']}")
    if report.get("missing_assets"):
        lines.append("Missing assets:")
        lines.extend(f"  - {a}" for a in report["missing_assets"][:8])
    head = report.get("headless") or {}
    if head.get("skipped"):
        lines.append(f"Headless: skipped ({head['skipped']})")
    elif head.get("error"):
        lines.append(f"Headless: {head['error']}")
    elif head:
        lines.append(
            f"Headless: mode={head.get('mode')} text={head.get('body_text_len')} "
            f"empty_root={head.get('empty_root')}"
        )
    findings = report.get("findings") or []
    if findings:
        lines.append("Findings:")
        lines.extend(f"  - {f}" for f in findings[:20])
    else:
        lines.append("Findings: none detected by deterministic probes (still verify UX manually).")
    text = "\n".join(lines)
    if len(text) > MAX_REPORT_CHARS:
        text = text[: MAX_REPORT_CHARS - 20] + "\n... (truncated)"
    return text


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    print(format_probe_report(probe_site(target)))
