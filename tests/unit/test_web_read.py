"""read_url: fetch/extract page text and route EN + Bangla speak intents."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SYS_PATH_ASSISTANT = str(ROOT / "components" / "assistant")
if SYS_PATH_ASSISTANT not in sys.path:
    sys.path.insert(0, SYS_PATH_ASSISTANT)

import tools  # noqa: E402
import web_read  # noqa: E402


SAMPLE_HTML = """<!doctype html><html><head>
<title>City Floods After Heavy Rain</title>
<meta name="description" content="Short desc">
</head><body>
<nav>Home About</nav>
<article>
<h1>City Floods After Heavy Rain</h1>
<p>Water covered main roads this morning. Rescue teams are working.</p>
<p>Officials said schools will stay closed tomorrow.</p>
</article>
<script>evil()</script>
</body></html>"""


def test_html_to_text_prefers_article():
    text, title = web_read.html_to_text(SAMPLE_HTML)
    assert title == "City Floods After Heavy Rain"
    assert "Water covered main roads" in text
    assert "schools will stay closed" in text
    assert "evil()" not in text
    assert "Home About" not in text or "Water covered" in text


def test_route_read_url_english():
    r = tools.route("summarize this page https://example.com/news/flood")
    assert len(r.actions) == 1
    a = r.actions[0]
    assert a.name == "read_url"
    assert a.args["url"] == "https://example.com/news/flood"
    assert a.args.get("speak") is False


def test_route_read_aloud_english():
    r = tools.route("read this article aloud https://www.bbc.com/news/123")
    a = r.actions[0]
    assert a.name == "read_url"
    assert "bbc.com" in a.args["url"]
    assert a.args.get("speak") is True


def test_route_bangla_pore_sunao():
    r = tools.route("amake ei news ta pore sunao https://example.com/bn/news")
    assert r.actions[0].name == "read_url"
    assert r.actions[0].args.get("speak") is True
    assert r.actions[0].args["url"] == "https://example.com/bn/news"


def test_route_bangla_script():
    r = tools.route("এই লিংকটা পড়ে শোনাও https://example.com/a")
    assert r.actions[0].name == "read_url"
    assert r.actions[0].args.get("speak") is True


def test_open_url_still_opens_without_read_intent():
    r = tools.route("open https://example.com/news")
    assert r.actions[0].name == "open_url"


def test_read_url_uses_context_link():
    r = tools.route(
        "ei page ta pore sunao",
        context=["check https://example.com/story/1 please"],
    )
    assert r.actions[0].name == "read_url"
    assert r.actions[0].args["url"] == "https://example.com/story/1"
    assert r.actions[0].args.get("speak") is True


def test_read_url_dry_run():
    a = tools.Action(
        "read_url",
        {"url": "https://example.com/x", "mode": "speak", "speak": True},
        label="Read",
    )
    res = tools.execute(a, dry_run=True)
    assert res.ok
    assert "example.com" in res.text
    assert res.data.get("speak") is True
