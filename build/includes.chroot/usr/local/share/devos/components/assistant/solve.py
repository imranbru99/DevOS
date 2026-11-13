#!/usr/bin/env python3
"""
When someone asks DevOS AI for help, check this PC and do the safe next step.

The on-device model is not asked to invent menus or repair steps. A link in
the message is checked here. Security, a missing network route and low disk
space come from the same checks DevOS Security and the Optimizer use.

Covers premium “OS self-heal” topics market agents advertise: network, slow PC,
security, audio, display, bluetooth, printer, updates, and app launch gaps
(those last are routed via tools APP_LAUNCH_FIXES when phrased as fail-to-open).
"""

import os
import re
import sys

# Real PC symptoms only — polite "help me" / "please help" alone is NOT a problem
# (that used to hijack IELTS / study questions into a Security dump).
_PROBLEM = re.compile(
    r"\b(?:fix (?:this|it|my|the)|something(?:'s| is) wrong|"
    r"not working|doesn'?t work|won'?t work|is broken|virus|malware|phishing|scam|hacked|"
    r"suspicious link|is this (?:link |site |address )?safe|is my (?:pc|computer|laptop) "
    r"(?:safe|secure|ok|infected)|security check|check (?:my )?security|"
    r"scan (?:my )?(?:pc|computer|laptop|downloads)|scan for (?:a )?(?:virus|viruses|malware)|"
    r"no internet|can'?t connect|cannot connect|wifi (?:is )?(?:down|broken|dead)|"
    r"internet (?:is )?(?:down|not working|gone|dead)|"
    r"no sound|no audio|mute(?:d)?|speaker(?:s)? (?:not|isn'?t)|microphone (?:not|isn'?t)|"
    r"screen (?:is )?(?:black|blank|flicker)|display (?:not|isn'?t)|resolution|"
    r"bluetooth (?:not|isn'?t|won'?t)|can'?t pair|"
    r"printer (?:not|isn'?t|won'?t)|won'?t print|"
    r"update(?:s)? (?:fail|failed|stuck)|can'?t update|"
    r"app (?:crash|crashed|keeps closing)|keeps crashing)\b",
    re.I)
_HELP_POLITE = re.compile(
    r"\b(?:help me|i need help|can you help|please help|would you (?:please )?help)\b", re.I)
_PASTED_ERROR = re.compile(r"\b(?:traceback|exception|error:|errno)\b", re.I)
_URL = re.compile(r"https?://[^\s<>'\"]+|www\.[^\s<>'\"]+", re.I)
_OPEN_VERB = re.compile(r"\b(?:open|launch|start|go to)\b", re.I)
_NETWORK = re.compile(r"\b(?:wifi|wi-fi|internet|network|connect|connection|ethernet)\b", re.I)
_SECURITY = re.compile(
    r"\b(?:virus|malware|phishing|scam|hacked|security|safe|infected|scan|suspicious)\b", re.I)
_SLOW = re.compile(r"\b(?:slow|lag|freez\w*|full disk|no space|storage)\b", re.I)
_AUDIO = re.compile(r"\b(?:sound|audio|speaker|microphone|mic|volume|mute|headphone|earphone)\b", re.I)
_DISPLAY = re.compile(r"\b(?:display|screen|monitor|resolution|brightness|flicker|black screen)\b", re.I)
_BLUETOOTH = re.compile(r"\b(?:bluetooth|bt\b|airpods|earbuds|pair(?:ing)?)\b", re.I)
_PRINTER = re.compile(r"\b(?:printer|printing|cups|inkjet|laserjet)\b", re.I)
_UPDATE = re.compile(r"\b(?:update|upgrade|dist-upgrade|software update)\b", re.I)
_APP_CRASH = re.compile(
    r"\b(?:crash(?:ed|ing)?|keeps closing|force close|not responding|frozen app)\b", re.I)


def wants_solve(text: str) -> bool:
    """True when the message is a PC problem to solve, not a normal question."""
    raw = text or ""
    if _OPEN_VERB.search(raw) and _HELP_POLITE.search(raw):
        return False
    if re.fullmatch(r"(?:help me|i need help|can you help|please help)[.?!]?", (raw or "").strip(), re.I):
        return False
    # "Would you please help me become an IELTS expert?" → model, not Security.
    if _HELP_POLITE.search(raw) and not _PROBLEM.search(raw) and not urls_in(raw) and not _PASTED_ERROR.search(raw):
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
    if _AUDIO.search(raw) and _PROBLEM.search(raw):
        return "audio"
    if _DISPLAY.search(raw) and _PROBLEM.search(raw):
        return "display"
    if _BLUETOOTH.search(raw) and (_PROBLEM.search(raw) or "pair" in raw.lower()):
        return "bluetooth"
    if _PRINTER.search(raw) and _PROBLEM.search(raw):
        return "printer"
    if _UPDATE.search(raw) and _PROBLEM.search(raw):
        return "update"
    if _APP_CRASH.search(raw):
        return "app"
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
    if cards and topic in ("security", "general", "slow", "app"):
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

    if topic == "audio":
        lines.append(
            "Sound issues are usually fixed in **Sound** settings (output device, mute, or wrong HDMI). "
            "I am opening Sound settings. Also try: unplug/replug headphones, then set the correct output."
        )
        buttons.append({"label": "Open Sound settings", "settings": "kcm_pulseaudio", "title": "Sound"})
        open_what = "settings"

    if topic == "display":
        lines.append(
            "Display issues: check cable, then **Display** settings for the right screen and resolution. "
            "Opening Display settings."
        )
        buttons.append({"label": "Open Display settings", "settings": "kcm_kscreen", "title": "Display"})
        open_what = "settings"

    if topic == "bluetooth":
        lines.append(
            "For Bluetooth: turn it on, put the device in pairing mode, then connect from Bluetooth settings. "
            "Opening Bluetooth now."
        )
        buttons.append({"label": "Open Bluetooth", "settings": "kcm_bluetooth", "title": "Bluetooth"})
        open_what = "settings"

    if topic == "printer":
        lines.append(
            "Printer problems: confirm power/cable/Wi-Fi, then add or fix the printer in Printer settings."
        )
        buttons.append({"label": "Open Printers", "settings": "kcm_printer_manager", "title": "Printers"})
        open_what = "settings"

    if topic == "update":
        lines.append(
            "If updates fail, open **Discover** or run system updates from DevOS, and keep the PC plugged in. "
            "I will not force a distro upgrade from chat."
        )
        buttons.append({"label": "Open Apps", "tool": "apps"})

    if topic == "app":
        lines.append(
            "If an app keeps crashing: close it fully, reopen once, then tell me the exact app name "
            "(e.g. “Snipping Tool failed to open”) so I can install the missing package if needed."
        )
        buttons.append({"label": "Open Apps", "tool": "apps"})

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
            lines.append(
                "DevOS Security has nothing that needs a fix right now. "
                "Tell me the exact error, app name, or paste the link — "
                "or say things like “no sound”, “Wi-Fi down”, “PC is slow”, “printer not working”."
            )

    if _PASTED_ERROR.search(raw) and topic != "link":
        lines.append("Paste the error as it is shown. I will not guess file paths that are not in it. "
                     "If it names a DevOS window, use that window's own Fix button.")

    if not blocked:
        lines.append("These checks run on this PC. A brand-new scam site can still be missed until it is listed.")
    return {"text": "\n".join(lines), "buttons": buttons, "open": open_what, "topic": topic,
            "blocked": blocked}
