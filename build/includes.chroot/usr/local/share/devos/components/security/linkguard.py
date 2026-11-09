#!/usr/bin/env python3
"""
DevOS Security - look-alike links, phishing pages and scam messages.

This runs on the PC with no extra service and no signature database. A check
reads at most 64 KB and returns immediately for ordinary files, so it does
not add RAM next to ClamAV. Downloads that are already an obvious phishing
page are quarantined before ClamAV loads its signatures.

It does not claim to know every scam. A brand-new site with a normal name
still depends on Quad9 and the browser's Safe Browsing.
"""

import os
import re
import stat
from urllib.parse import urlsplit

OK = "ok"
WARN = "warn"
BLOCK = "block"

READ_LIMIT = 64 * 1024
FILE_LIMIT = 2 * 1024 * 1024
PHISH_EXTS = (".html", ".htm", ".svg", ".url", ".desktop")

# Names people are tricked into trusting, and the real registrable domains.
OFFICIAL = {
    "paypal": ("paypal.com",),
    "microsoft": ("microsoft.com", "microsoftonline.com", "office.com", "office365.com",
                  "outlook.com", "windows.com", "live.com", "msn.com", "azure.com"),
    "google": ("google.com", "gmail.com", "youtube.com", "youtu.be", "googleapis.com",
               "googleusercontent.com", "gstatic.com"),
    "apple": ("apple.com", "icloud.com",),
    "amazon": ("amazon.com", "amazonaws.com"),
    "facebook": ("facebook.com", "fb.com", "messenger.com"),
    "instagram": ("instagram.com",),
    "whatsapp": ("whatsapp.com", "whatsapp.net"),
    "netflix": ("netflix.com",),
    "binance": ("binance.com",),
    "coinbase": ("coinbase.com",),
    "metamask": ("metamask.io",),
    "steam": ("steampowered.com", "steamcommunity.com"),
    "adobe": ("adobe.com",),
    "dhl": ("dhl.com",),
    "fedex": ("fedex.com",),
}
ALL_OFFICIAL = {host for hosts in OFFICIAL.values() for host in hosts}

# A word in the address, and which company's real domains it belongs to.
TOKENS = {
    "paypal": "paypal",
    "microsoft": "microsoft", "office": "microsoft", "outlook": "microsoft", "hotmail": "microsoft",
    "google": "google", "gmail": "google", "youtube": "google",
    "apple": "apple", "icloud": "apple",
    "amazon": "amazon",
    "facebook": "facebook", "messenger": "facebook",
    "instagram": "instagram",
    "whatsapp": "whatsapp",
    "netflix": "netflix",
    "binance": "binance",
    "coinbase": "coinbase",
    "metamask": "metamask",
    "steam": "steam",
    "adobe": "adobe",
    "dhl": "dhl",
    "fedex": "fedex",
}

# Pages on these hosts often mention a brand without being that brand.
PUBLIC_HOSTS = {
    "github.io", "github.com", "gitlab.io", "netlify.app", "pages.dev", "vercel.app",
    "wordpress.com", "blogspot.com", "cloudfront.net", "azurewebsites.net",
}

SHORTENERS = {
    "bit.ly", "tinyurl.com", "t.co", "goo.gl", "cutt.ly", "is.gd", "rb.gy", "ow.ly",
    "buff.ly", "shorturl.at", "rebrand.ly", "tiny.cc",
}

# Leftover pieces that still mean "this token is pretending to be the brand".
DECOYS = {
    "secure", "login", "account", "verify", "update", "support", "help", "online",
    "service", "alert", "billing", "wallet", "signin", "sign", "web", "app", "my",
    "the", "official", "auth", "recovery", "customer", "confirm", "id",
}

# Letters that look like Latin letters. Digits are folded only for the brand test.
_LETTERS = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i",
    "ѕ": "s", "һ": "h", "ј": "j", "ԁ": "d", "ɡ": "g", "ν": "v", "ο": "o", "α": "a",
    "ε": "e", "ι": "i", "τ": "t", "κ": "k", "μ": "u", "у": "y", "х": "x",
})
_DIGITS = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t"})

_SECOND_LEVEL = {"co", "com", "ac", "org", "net", "gov", "edu"}
_LOGIN_WORDS = re.compile(r"(login|log-in|signin|sign-in|password|verify|account|wallet|bank|otp)", re.I)
_URL_ATTR = re.compile(r"""(?i)(?:href|src|action)\s*=\s*["']([^"']+)""")
_URL_LINE = re.compile(r"(?im)^(?:url)\s*=\s*(\S+)")
def _private_host(host):
    if host in ("localhost", "::1"):
        return True
    if host.startswith(("127.", "10.", "192.168.", "169.254.")):
        return True
    match = re.match(r"^172\.(\d+)\.", host)
    return bool(match and 16 <= int(match.group(1)) <= 31)


def verdict(level, threat, summary, reasons=None):
    return {"level": level, "threat": threat, "summary": summary, "reasons": list(reasons or [])}


def ok_result(summary="Nothing here matches a look-alike address or a common scam pattern."):
    return verdict(OK, None, summary)


def _decode_host(host):
    labels = []
    for label in (host or "").split("."):
        if label.startswith("xn--"):
            try:
                label = label.encode("ascii").decode("idna")
            except (UnicodeError, UnicodeDecodeError):
                pass
        labels.append(label)
    return ".".join(labels)


def registrable(host):
    labels = [part for part in (host or "").split(".") if part]
    if len(labels) <= 2:
        return ".".join(labels)
    if labels[-2] in _SECOND_LEVEL and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _brand_in_token(token):
    if token in TOKENS:
        return TOKENS[token]
    for name, brand in TOKENS.items():
        if name in token and len(token) <= len(name) + 16:
            rest = token.replace(name, "")
            parts = [part for part in rest.split("-") if part]
            if parts and all(part in DECOYS for part in parts):
                return brand
    return None


def _brands(host):
    found = []
    for label in host.split("."):
        if label in ("www", "com", "net", "org"):
            continue
        for token in label.split("-"):
            brand = _brand_in_token(token)
            if brand and brand not in found:
                found.append(brand)
    return found


def _official(brand, reg):
    return reg in OFFICIAL.get(brand, ())


def inspect_url(url):
    """Classify one web address. ok, warn, or block."""
    raw = (url or "").strip()
    if not raw or raw.startswith(("#", "/", "mailto:", "about:")):
        return ok_result()
    low = raw.lower()
    if low.startswith("javascript:") or low.startswith("data:"):
        return verdict(BLOCK, "DevOS.Phishing.Script",
                       "This address runs as a script instead of opening a normal page.",
                       ["script-url"])
    try:
        parts = urlsplit(raw if "://" in raw else "https://" + raw)
    except ValueError:
        return verdict(WARN, None, "This address could not be read.", ["unreadable"])
    if parts.username or parts.password:
        return verdict(BLOCK, "DevOS.Phishing.HiddenHost",
                       "The real site is hidden after an @ sign. The part before @ is not the site you would visit.",
                       ["userinfo"])
    host = _decode_host((parts.hostname or "").strip(".").lower())
    if not host:
        return ok_result()
    if _private_host(host):
        return ok_result("This address is on the local network.")
    letters = host.translate(_LETTERS)
    branded = letters.translate(_DIGITS)
    reg = registrable(host)
    reasons = []

    def homograph(folded):
        return folded != host and (_brands(folded) or registrable(folded) in ALL_OFFICIAL)

    if homograph(letters) or homograph(branded):
        return verdict(BLOCK, "DevOS.Phishing.Lookalike",
                       "This address is written to look like a well-known site.",
                       ["lookalike"])
    hits = _brands(host) or _brands(branded)
    for brand in hits:
        if _official(brand, reg) or _official(brand, registrable(branded)):
            continue
        if reg in PUBLIC_HOSTS or registrable(branded) in PUBLIC_HOSTS:
            return verdict(WARN, None,
                           "A well-known name appears in this address, but the site is a public host, not that company.",
                           ["brand-on-public-host"])
        return verdict(BLOCK, "DevOS.Phishing.Lookalike",
                       "This address uses a well-known name but is not that company's site.",
                       ["brand-mismatch"])
    if reg in SHORTENERS or host in SHORTENERS:
        reasons.append("shortener")
        return verdict(WARN, None,
                       "This is a short link. The real destination is hidden until it is opened.",
                       reasons)
    if re.fullmatch(r"[0-9.]+", host) or ":" in host:
        if _LOGIN_WORDS.search(parts.path + "?" + parts.query):
            return verdict(BLOCK, "DevOS.Phishing.RawAddress",
                           "A login page on a raw numeric address is a common phishing trick.",
                           ["raw-ip-login"])
        return verdict(WARN, None, "This site is a numeric address, not a normal name.", ["raw-ip"])
    if host.count(".") >= 5:
        return verdict(WARN, None, "This address has an unusual number of names in it.", ["long-host"])
    return ok_result()


def inspect_text(text):
    """Score a message. One ordinary word is not enough; several scam signals are."""
    raw = (text or "").strip()
    if len(raw) < 12:
        return ok_result()
    t = raw.lower()
    score = 0
    reasons = []

    def hit(flag, points, reason):
        nonlocal score
        if flag:
            score += points
            reasons.append(reason)

    hit(re.search(r"gift\s*cards?", t) and re.search(
        r"\b(code|codes|buy|payment|pay|urgent|apple|google|steam|itunes)\b", t),
        3, "gift-card")
    hit(re.search(r"(seed phrase|recovery phrase|secret recovery|12 words|24 words)", t),
        4, "seed-phrase")
    hit(re.search(r"\b(wire transfer|western union|moneygram)\b", t) and re.search(
        r"\b(urgent|immediately|today|fee|tax)\b", t),
        3, "wire")
    hit(re.search(r"(account|mailbox|bank).{0,48}(suspend|locked|closed|disabled|limited)", t)
        and re.search(r"https?://|\bclick\b|\blink\b|\bverify\b", t),
        3, "account-threat")
    hit(re.search(r"\b(otp|one[- ]time (?:code|password)|verification code)\b", t)
        and re.search(r"\b(send|tell|reply|share|give|forward)\b", t),
        4, "otp-request")
    hit(re.search(r"\b(you(?:'ve| have) won|lottery|prize)\b", t)
        and re.search(r"\b(fee|tax|gift card|processing)\b", t),
        3, "prize-fee")
    hit(re.search(r"\b(telegram|whatsapp)\b", t) and re.search(r"\b(task|commission)\b", t)
        and re.search(r"\b(pay|payment|earn|job)\b", t),
        3, "task-scam")
    if score >= 4:
        return verdict(BLOCK, "DevOS.Scam.Message",
                       "This message matches a common scam: do not send codes, card numbers or money.",
                       reasons)
    if score >= 3:
        return verdict(WARN, None,
                       "This message looks like a scam. Check it with the person by a method you already use.",
                       reasons)
    return ok_result()


def _read_head(path):
    try:
        st = os.lstat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode) or st.st_size <= 0 or st.st_size > FILE_LIMIT:
        return None
    try:
        with open(path, "rb") as handle:
            return handle.read(READ_LIMIT)
    except OSError:
        return None


def inspect_path(path):
    """Phishing page or internet shortcut. Other files are left for the virus scanner."""
    name = os.path.basename(path or "").lower()
    if not name.endswith(PHISH_EXTS):
        return ok_result()
    blob = _read_head(path)
    if not blob:
        return ok_result()
    text = blob.decode("utf-8", "replace")
    if name.endswith((".url", ".desktop")):
        found = _URL_LINE.findall(text)
    else:
        found = _URL_ATTR.findall(text)[:30]
    worst = ok_result()
    rank = {OK: 0, WARN: 1, BLOCK: 2}
    for item in found:
        item = item.strip()
        if not item or item.startswith(("#", "mailto:")):
            continue
        one = inspect_url(item)
        if rank[one["level"]] > rank[worst["level"]]:
            worst = one
    if worst["level"] == BLOCK:
        worst = dict(worst)
        worst["threat"] = worst["threat"] or "DevOS.Phishing.Page"
        return worst
    return ok_result()
