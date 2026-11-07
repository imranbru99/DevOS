#!/usr/bin/env python3
"""Deterministic site probe findings for the local code agent."""

import http.server
import socketserver
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "code-agent"))

import site_probe  # noqa: E402


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith(".css") or self.path.endswith(".js"):
            self.send_response(404)
            self.end_headers()
            return
        body = (
            b"<html><head><title>Blank App</title>"
            b'<link rel="stylesheet" href="/missing.css">'
            b"</head><body><div id=\"root\"></div></body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def log_message(self, *args):
        return


def test_probe_detects_empty_root_and_missing_css():
    httpd = socketserver.TCPServer(("127.0.0.1", 0), _Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        report = site_probe.probe_site(f"http://127.0.0.1:{port}/", headless=False)
        text = site_probe.format_probe_report(report)
        joined = " ".join(report["findings"]).lower()
        assert "empty" in joined or "near-empty" in joined
        assert "asset" in joined
        assert "Blank App" in text or "Blank" in text
        assert len(text) <= site_probe.MAX_REPORT_CHARS
    finally:
        httpd.shutdown()


def test_probe_blocks_file_scheme():
    try:
        site_probe.normalize_url("file:///etc/passwd")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "Blocked" in str(exc) or "scheme" in str(exc).lower()
