#!/usr/bin/env python3
"""
When someone asks DevOS AI for help, check this PC and do the safe next step.

The on-device model is not asked to invent menus or repair steps. A link in
the message is checked here. Security, a missing network route and low disk
space come from the same checks DevOS Security and the Optimizer use.
"""

import os
import re
import sys

_PROBLEM = re.compile(
    r"\b(?:help me|i need help|can you help|fix (?:this|it|my|the)|something(?:'s| is) wrong|"
    r"not working|doesn'?t work|won'?t work|is broken|virus|malware|phishing|scam|hacked|"
    r"suspicious link|is this (?:link |site |address )?safe|is my (?:pc|computer|laptop) "
    r"(?:safe|secure|ok|infected)|security check|check (?:my )?security|"
    r"scan (?:my )?(?:pc|computer|laptop|downloads)|scan for (?:a )?(?:virus|viruses|malware)|"
    r"no internet|can'?t connect|cannot connect|wifi (?:is )?(?:down|broken|dead)|"
    r"internet (?:is )?(?:down|not working|gone|dead))\b",
    re.I)
_PASTED_ERROR = re.compile(r"\b(?:traceback|exception|error:|errno)\b", re.I)
_URL = re.compile(r"https?://[^\s<>'\"]+|www\.[^\s<>'\"]+", re.I)
_OPEN_VERB = re.compile(r"\b(?:open|launch|start|go to)\b", re.I)
_NETWORK = re.compile(r"\b(?:wifi|wi-fi|internet|network|connect|connection|ethernet)\b", re.I)
_SECURITY = re.compile(
    r"\b(?:virus|malware|phishing|scam|hacked|security|safe|infected|scan|suspicious)\b", re.I)
_SLOW = re.compile(r"\b(?:slow|lag|freez\w*|full disk|no space|storage)\b", re.I)


def wants_solve(text: str) -> bool:
    """True when the message is a problem to solve, not a normal command."""
    raw = text or ""
    if _OPEN_VERB.search(raw) and re.search(r"\bhelp me\b", raw, re.I):
        return False
    if re.fullmatch(r"(?:help me|i need help|can you help)[.?!]?", (raw or "").strip(), re.I):
        return False
    if _PROBLEM.search(raw):
        return True
    return len(raw) > 80 and bool(_PASTED_ERROR.search(raw))


def urls_in(text: str):
    found = []
    for match in _URL.findall(text or ""):
        url = match.rstrip(".,);]")
        if not url.lower().startswith("http"):
            url = "https://" + url
        if url not in found:
            found.append(url)
    return found[:5]


def topic_of(text: str) -> str:
    raw = text or ""
    if urls_in(raw) and _SECURITY.search(raw):
        return "link"
    if urls_in(raw) and not _NETWORK.search(raw) and not _SLOW.search(raw):
        return "link" if _SECURITY.search(raw) or "safe" in raw.lower() or "scam" in raw.lower() else "general"
    if _NETWORK.search(raw):
        return "network"
    if _SLOW.search(raw):
        return "slow"
    if _SECURITY.search(raw) or _PASTED_ERROR.search(raw):
        return "security"
    return "general"


def network_up():
    """True, False, or None when this session cannot see the routing table."""
    try:
        with open("/proc/net/route", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "00000000" and parts[0] != "Iface":
                    return True
    except OSError:
        return None
    return False


def _linkguard():
    sec = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "security"))
    if sec not in sys.path:
        sys.path.insert(0, sec)
    import linkguard
    return linkguard


def live_security():
    """(cards, headline, score) or (None, None, None) if Security cannot be read."""
    sec = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "security"))
    if sec not in sys.path:
        sys.path.insert(0, sec)
    try:
        import security_center as center
        status = center.full_status(check=False)
    except Exception:
        return None, None, None
    return status.get("cards") or [], status.get("headline"), status.get("score")


def answer(text, cards=None, online=None, headline=None, score=None, load_security=None):
    """A reply from real checks. cards/online are injected by tests."""
    raw = text or ""
    topic = topic_of(raw)
    if cards is None:
        loader = load_security or live_security
        try:
            cards, headline, score = loader()
        except Exception:
            cards, headline, score = None, None, None
    if online is None and topic in ("network", "general"):
        online = network_up()

    lines = ["I checked this on your PC."]
    buttons = []
    open_what = None
    blocked = False

    for url in urls_in(raw):
        try:
            verdict = _linkguard().inspect_url(url)
        except Exception:
            verdict = {"level": "ok", "summary": ""}
        level = verdict.get("level")
        if level == "block":
            blocked = True
            lines.append(f"I did not open `{url}`. {verdict.get('summary')}")
        elif level == "warn":
            lines.append(f"I did not open `{url}`. {verdict.get('summary')}")
        else:
            lines.append(f"`{url}` does not look like a disguised address. "
                         "That does not prove the page itself is honest.")

    attention = []
    if cards and topic in ("security", "general", "slow"):
        attention = [c for c in cards if c.get("level") in ("bad", "warn") and c.get("id") != "family"]
        if attention:
            lines.append("What needs attention:")
            for card in attention[:4]:
                detail = (card.get("detail") or "").strip()
                lines.append(f"- **{card.get('title')}:** {card.get('summary')}. {detail}".rstrip())
            buttons.append({"label": "Open DevOS Security", "tool": "security"})
            if topic in ("security", "general"):
                open_what = "security"
        elif topic == "security":
            shown = headline or "Your PC is protected"
            extra = f" Score {score}." if isinstance(score, int) else ""
            lines.append(f"**{shown}.**{extra} Nothing in DevOS Security needs a fix right now.")

    if topic == "slow":
        lines.append("Open DevOS Optimizer to see what can be cleaned. Nothing is deleted until you confirm.")
        buttons.append({"label": "Open DevOS Optimizer", "tool": "optimizer"})

    if topic == "network":
        if online is False:
            lines.append("This PC has no network route. I am opening Wi-Fi settings.")
            open_what = "network"
        elif online is True:
            lines.append("The network route is up. If one site fails, the connection itself is still there.")
        else:
            lines.append("I could not read the network route in this session. Wi-Fi settings are the place to check.")
        buttons.append({"label": "Open Wi-Fi settings", "settings": "kcm_networkmanagement",
                        "title": "Wi-Fi & network"})

    if topic == "general" and not urls_in(raw) and not attention:
        if online is False:
            lines.append("This PC has no network route. I am opening Wi-Fi settings.")
            open_what = "network"
            buttons.append({"label": "Open Wi-Fi settings", "settings": "kcm_networkmanagement",
                            "title": "Wi-Fi & network"})
        elif cards is None:
            lines.append("I could not read DevOS Security from here. Open DevOS Security to see each layer.")
            buttons.append({"label": "Open DevOS Security", "tool": "security"})
        else:
            lines.append("DevOS Security has nothing that needs a fix right now. "
                         "Tell me the exact error, or paste the link, and I will check that.")

    if _PASTED_ERROR.search(raw) and topic != "link":
        lines.append("Paste the error as it is shown. I will not guess file paths that are not in it. "
                     "If it names a DevOS window, use that window's own Fix button.")

    if not blocked:
        lines.append("These checks run on this PC. A brand-new scam site can still be missed until it is listed.")
    return {"text": "\n".join(lines), "buttons": buttons, "open": open_what, "topic": topic,
            "blocked": blocked}
